# 0003. Loader pasal yang idempotent

- Status: diterima
- Tanggal: 2026-09-26

## Konteks

`ingestion.load` memindahkan `data/processed/<code>.jsonl` ke tabel `regulations` dan `provisions`. Loader akan dijalankan berulang kali: setiap kali parser diperbaiki, metadata di `sources.yaml` berubah, atau ada pasal yang baru diverifikasi. Menjalankannya ulang tidak boleh menghasilkan baris ganda, mengganti `id` (dirujuk `answer_citations` dan URL `/pasal/[id]`), atau menghapus hasil langkah konsolidasi UU 6/2023 yang berjalan sesudahnya.

## Keputusan

### 1. Identitas versi pasal sebagai kunci upsert

`UNIQUE NULLS NOT DISTINCT (regulation_id, article, amended_by_id, amendment_ref)`, bernama `uq_provisions_version`. Teks asli UU-13 Pasal 156 beridentitas `(UU-13, '156', NULL, NULL)`; versi hasil UU 6/2023 beridentitas `(UU-13, '156', UU-6, 'Pasal 81 angka N')`.

`NULLS NOT DISTINCT` wajib: tanpanya PostgreSQL menganggap dua NULL berbeda, sehingga teks asli bisa masuk berkali-kali. Fitur ini **butuh PostgreSQL 15+**, termasuk project Neon saat deploy. Docker lokal dan CI memakai `pgvector/pgvector:pg16`.

`amendment_ref` selalu dihasilkan parser amandemen dengan format tetap (`Pasal 81 angka N`), tidak pernah diketik manual. Satu spasi atau huruf kapital yang berbeda akan membuat identitas versi baru dan baris ganda.

Index `uq_provisions_in_force_article` tidak bisa dipakai sebagai kunci karena hanya berisi versi yang masih berlaku; setelah konsolidasi mengisi `valid_to`, versi asli keluar dari index itu.

### 2. Pembagian kolom antara loader dan konsolidasi

Loader memperbarui `label`, `chapter`, `section`, `text`, `penjelasan`, `content_sha256`, `valid_from`, dan `verified_manually`. Kolom `valid_to` dan `status` milik langkah konsolidasi dan tidak disentuh saat upsert, sehingga memuat ulang UU-13 tidak membatalkan amandemen yang sudah tercatat.

### 3. Tidak pernah menghapus

Pasal yang ada di database tetapi tidak ada di JSONL membuat loader berhenti dengan `OrphanProvisionError`. Satu regulasi dimuat dalam satu transaksi, jadi kegagalan tidak meninggalkan data setengah jadi.

### 4. Verifikasi manual terikat ke hash teks

`content_sha256` = SHA-256 dari `text` (tanpa penjelasan, karena yang diverifikasi adalah norma). `data/verified_provisions.yaml` mencatat `(regulation, article, content_sha256)` untuk pasal yang sudah dicocokkan dengan PDF. `verified_manually` bernilai true hanya bila hash di file itu sama dengan hash teks yang dimuat. Jika parser mengubah teks, status verifikasi gugur sendiri dan loader mencatat warning. Status verifikasi hidup di git, bukan di database.

### 5. Kolom tambahan

- `regulations.text_quality` (`native | ocr | manual`), tanpa default, supaya loader yang lupa mengisinya gagal alih-alih melabeli hasil scan sebagai teks asli. UI menampilkan catatan "teks hasil pemindaian" bila kualitas sumber teks (regulasi pengubah untuk versi hasil amandemen) adalah `ocr` dan pasalnya belum `verified_manually`.
- `provisions.section`: jalur Bagian/Paragraf, terpisah dari `chapter` agar pengelompokan per BAB tidak perlu mem-parse string.
- `provisions.penjelasan`: NULL berarti "Cukup jelas" atau tidak ada penjelasan.

## Alternatif yang ditolak

- **Hapus semua pasal regulasi lalu insert ulang**: sederhana, tetapi `id` berubah dan kutipan yang tersimpan rusak.
- **SELECT lalu INSERT/UPDATE per pasal di Python**: lebih banyak kode dan query per baris; upsert PostgreSQL melakukannya dalam satu statement.
- **`section` digabung ke `chapter`**: menghemat satu kolom, tetapi breadcrumb dan statistik per BAB jadi harus mem-parse string.
- **Hash dipakai untuk melewati update yang tidak berubah**: 193 baris murah untuk diperbarui, dan perubahan `penjelasan` tidak mengubah hash.

## Konsekuensi

- Loader berjalan sinkron (`create_engine`), seperti `alembic env.py`, karena perintah CLI sekali jalan tidak butuh event loop.
- Integration test memakai database sekali pakai `hakkerja_integration_test` dan mencakup: dua kali load menghasilkan jumlah baris dan `id` yang sama, teks berubah diperbarui di tempat, kolom konsolidasi dipertahankan, pasal yatim membatalkan seluruh load, dan status verifikasi mengikuti hash.
- Pemeriksaan hash verifikasi yang basi saat ini hanya membandingkan teks asli. Slice UU-6 perlu memperluasnya ke versi hasil amandemen.
