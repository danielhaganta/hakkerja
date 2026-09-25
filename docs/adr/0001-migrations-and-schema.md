# 0001. Migrasi Alembic dan aturan skema awal

- Status: diterima
- Tanggal: 2026-09-25

## Konteks

Tahap 0 butuh migrasi awal untuk semua tabel di SPEC §6. Backend memakai SQLAlchemy 2.0 async dengan psycopg 3, PostgreSQL 16 + pgvector, lokal di Docker dan production di Neon. Aturan hukum bisa berganti (RUU Pelindungan Ketenagakerjaan), jadi skema harus mudah diubah lewat migrasi dan harus menjaga riwayat versi pasal dengan benar.

## Keputusan

### 1. Alembic dengan `env.py` sinkron

`env.py` memakai `create_engine` biasa, bukan template async. psycopg 3 melayani URL `postgresql+psycopg://` yang sama dalam mode sync, jadi aplikasi tetap async sementara migrasi (perintah CLI sekali jalan) tidak perlu event loop. Template async di Windows juga butuh `SelectorEventLoop` karena psycopg async tidak berjalan di `ProactorEventLoop`.

URL database diambil dari `app.config` (`DATABASE_URL`), tidak ditulis di `alembic.ini`. Test mengarahkan migrasi ke database sekali pakai lewat `config.attributes["database_url"]`.

### 2. Status dan jenis: `TEXT` + `CHECK`, bukan `ENUM` PostgreSQL

Berlaku untuk `regulations.type`, `regulations.status`, `provisions.status`, `questions.status`, `eval_runs.mode`. Nilai yang diizinkan didefinisikan sebagai `StrEnum` di `app/db/models.py` dan dirender menjadi `CHECK (kolom IN (...))`.

### 3. Naming convention di `MetaData`

Semua constraint dan index punya nama deterministik (`pk_`, `fk_`, `uq_`, `ck_`, `ix_`), sehingga migrasi berikutnya bisa melakukan `drop_constraint` dengan nama yang sama di Docker lokal dan di Neon.

### 4. Kepemilikan versi pasal

Versi pasal yang diubah oleh UU 6/2023 tetap memakai `regulation_id` milik UU asalnya. Contoh: versi baru Pasal 156 tetap milik `UU-13-2003`, dengan `amended_by_id` menunjuk `UU-6-2023` dan `amendment_ref = 'Pasal 81 angka N'`.

Dengan aturan ini, unique partial index `uq_provisions_in_force_article` pada `(regulation_id, article) WHERE valid_to IS NULL` benar-benar menjamin **satu versi berlaku per pasal**. Versi lama tetap disimpan dengan `valid_to` terisi. Jika konsolidasi keliru dan menghasilkan dua versi berlaku, database menolaknya.

### 5. `valid_to` bersifat eksklusif

`valid_to` adalah hari pertama pasal **tidak lagi** berlaku. Versi yang berlaku pada tanggal `d`:

```sql
valid_from <= d AND (valid_to IS NULL OR d < valid_to)
```

Versi lama dan versi pengganti berbagi satu tanggal (`valid_to` lama = `valid_from` baru) tanpa celah atau tumpang tindih. Ini dijaga oleh `CHECK (valid_to IS NULL OR valid_to > valid_from)`.

### 6. Perubahan dari draf SPEC §6

| Perubahan | Alasan |
|---|---|
| PK `query_embedding_cache` menjadi `(text_hash, embedding_model)` | Gemini dan Jina sama-sama 768 dimensi tetapi ruang vektornya berbeda. Tanpa model di kunci, fallback embedder bisa memakai vektor dari model lain. |
| `answer_cache.question_id` diberi `ON DELETE SET NULL` | Job retensi 180 hari menghapus `questions`. Tanpa ini, DELETE gagal karena FK. |
| Index `(valid_to) WHERE valid_to IS NULL` dan `(regulation_id, article)` diganti unique partial index di atas, ditambah `CHECK` rentang tanggal | Index lama mengindeks kolom yang nilainya selalu NULL. Index baru sekaligus menegakkan invariant keputusan 4. |
| `chunks.embedding` menjadi `NOT NULL` | `ingestion.embed` berjalan sebelum `ingestion.load`, dan `embedding_model` sudah `NOT NULL`. |

## Alternatif yang ditolak

- **Template Alembic async.** Kodenya lebih banyak dan butuh penanganan event loop Windows, padahal migrasi tidak mendapat manfaat dari async.
- **`ENUM` native PostgreSQL.**
  - `drop_table` tidak menghapus TYPE yang dibuat `create_table`, sehingga siklus upgrade → downgrade → upgrade gagal dengan `type already exists`.
  - Nilai ENUM tidak bisa dihapus tanpa membuat ulang type.
  - Autogenerate tidak mendeteksi perubahan nilai ENUM tanpa paket tambahan.
- **`sa.Enum(native_enum=False)`.** Secara default menyimpan *nama* member (`BERLAKU`), bukan value-nya (`berlaku`), dan memakai `VARCHAR(n)`.
- **Nama constraint default PostgreSQL.** Nama seperti `provisions_regulation_id_fkey` tidak diketahui SQLAlchemy, jadi migrasi berikutnya harus menebaknya.
- **Menulis migrasi awal sepenuhnya dengan SQL mentah.** Model dan database kehilangan satu sumber kebenaran, dan `alembic check` tidak lagi bisa mendeteksi drift.
- **Versi pasal hasil amandemen dimiliki UU 6/2023.** Unique index per `(regulation_id, article)` tidak lagi menjaga apa pun, karena Pasal 156 lama dan baru akan berada di regulasi berbeda.
- **`valid_to` inklusif (hari terakhir berlaku).** Versi lama dan baru harus berbeda satu hari, sehingga rentang mudah salah hitung dan query menjadi `d <= valid_to`.

## Konsekuensi

- Alembic tidak membandingkan `CHECK` constraint. Mengubah nilai status butuh migrasi manual (drop + add constraint, 2 baris).
- Autogenerate tidak mengenal extension. `CREATE EXTENSION IF NOT EXISTS vector` ditulis manual di migrasi awal, dan `downgrade` menghapusnya kembali.
- Mengubah ekspresi kolom generated `chunks.tsv` tidak dideteksi autogenerate. PostgreSQL 16 tidak bisa mengubahnya langsung, jadi migrasinya adalah drop + add kolom.
- `script.py.mako` selalu mengimpor `pgvector.sqlalchemy`, karena autogenerate merender tipe `VECTOR` tanpa import.
- Ingestion wajib mengikuti keputusan 4 dan 5 saat mengonsolidasi UU 13/2003 dengan Pasal 81 UU 6/2023.
- `tests/integration/test_migrations.py` menjalankan upgrade → downgrade → upgrade, `alembic check`, dan kedua invariant di atas pada database sekali pakai.
