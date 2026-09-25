# 0002. Ekstraksi teks PDF regulasi

- Status: diterima
- Tanggal: 2026-09-26

## Konteks

Korpus MVP berasal dari PDF resmi. Eksplorasi awal (Tahap 1 langkah 1.2) menemukan tiga jenis dokumen:

- teks asli (UU-13-2003, PMK-168-2024);
- scan dengan text layer OCR yang banyak salah baca (PP-35-2021, PP-51-2023, UU-6-2023), misalnya `REPUELIK`, `2O2l`, `Pasal4T`, `(21` untuk ayat (2);
- scan tanpa teks sama sekali (PP-36-2021).

Ingestion berjalan offline, tetapi test parser berjalan di CI. Repo ini public dan belum punya lisensi.

## Keputusan

### 1. pypdfium2 di dependency group `ingestion`

Diukur dengan ekstraksi penuh UU-6-2023 (1127 halaman): pypdfium2 4,8 detik, pypdf 55,3 detik, dengan hasil teks yang hampir sama. Lisensi pypdfium2 Apache-2.0/BSD-3.

Group `ingestion` masuk `default-groups` supaya `uv sync` lokal dan di CI memasangnya. Image production wajib memakai `uv sync --no-default-groups`.

### 2. Tiga tahap dengan file perantara

`parse_pdf` (PDF → `data/interim/<code>.txt`, halaman dipisah `\f`, gitignored) lalu `split_pasal` (→ `data/processed/<code>.jsonl`, di-commit). Teks bersih bisa diperiksa dan di-grep saat parser salah, dan PDF besar tidak dibaca ulang setiap kali aturan pemecahan pasal diubah.

### 3. Heading pasal dan ayat divalidasi urutannya

`Pasal N` hanya diterima sebagai heading bila nomornya tepat setelah pasal sebelumnya (`88` → `88A` → `89`); ayat diperlakukan sama. Baris yang diawali `(2)` setelah baris yang berakhir dengan kata "ayat" dianggap rujukan yang terpotong baris, bukan ayat baru. Di UU-13 kasus ini muncul lebih dari 20 kali.

### 4. Tanda hubung pergantian baris (U+FFFE) diputuskan per dokumen

PDFium menandai tanda hubung akhir baris dengan U+FFFE, tetapi tidak membedakan pemenggalan suku kata (`Ketenaga-kerjaan`) dari kata ulang (`undang-undang`). Urutan keputusan:

1. bentuk yang lebih sering muncul di bagian dokumen yang tidak terpenggal (`x-y` atau `xy`);
2. bila tidak ada bukti: kata ulang jika akhir kata kiri sama dengan awal kata kanan, minimal tiga huruf (`sewenang-wenang`, `sebaik-baiknya`);
3. selain itu digabung, dan dicatat di log sebagai ambigu.

Aturan kedua sengaja dibuat lebih umum dari "kanan adalah akhiran kiri", karena `sebaik-baiknya` tidak memenuhi aturan itu. Kata ulang berubah bunyi (`terus-menerus`, `bolak-balik`) tidak tertangkap aturan kedua dan akan muncul sebagai ambigu bila dokumen tidak memuat bentuk lainnya.

## Alternatif yang ditolak

- **PyMuPDF**: cepat dan lengkap, tetapi AGPL-3.0 akan ikut menentukan lisensi repo public ini.
- **pypdf**: lisensi BSD dan pure Python, tetapi 11× lebih lambat pada dokumen terbesar tanpa kelebihan kualitas teks.
- **pdfplumber/pdfminer.six**: memberi koordinat per kata, belum dibutuhkan, dan paling lambat.
- **OCR ulang dengan Tesseract**: ditunda. Lebih dulu dicari PDF dengan text layer yang baik dari sumber lain.

## Konsekuensi

- pypdfium2 tidak menyertakan type hints; mypy memakai `ignore_missing_imports` khusus modul itu, dan hanya `read_page_texts` yang memanggilnya.
- Dokumen OCR butuh aturan tambahan (heading toleran OCR, footer `SK No`, catchword tanpa elipsis) yang ditambahkan saat slice dokumen OCR dikerjakan.
- `data/processed/*.jsonl` divalidasi di CI tanpa PDF mentah: jumlah dan urutan pasal, konsistensi `text` dengan `ayat`, dan tidak ada sisa header atau catchword.
