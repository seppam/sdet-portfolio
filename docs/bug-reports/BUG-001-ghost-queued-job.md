# BUG-001: Job tertinggal "queued" selamanya saat S3 tidak bisa dihubungi

| Field | Nilai |
|---|---|
| ID | BUG-001 |
| Severity | Major |
| Priority | High |
| Komponen | API upload (`app/main.py`, fungsi `_accept_upload`) |
| Ditemukan oleh | API test dengan fake AWS (`tests/fakes.py`, flag `fail_put = True`) saat menulis skenario "S3 down" |
| Status | Fixed |

## Ringkasan

Saat penyimpanan S3 tidak tersedia, `POST /api/uploads` gagal dengan error 500 yang tidak jelas, tetapi baris job di SQLite sudah terlanjur dibuat dengan status `queued`. Job tersebut tampil di `GET /api/jobs` padahal pesannya tidak pernah masuk antrian SQS, sehingga tidak akan pernah diproses.

## Langkah reproduksi

1. Set kondisi S3 tidak tersedia (fake: `fake_aws.fail_put = True`).
2. Kirim `POST /api/uploads` dengan file CSV valid.
3. Perhatikan respons API.
4. Kirim `GET /api/jobs` dan cek status job yang baru dibuat.

## Hasil yang diharapkan

- API menjawab HTTP 503 dengan pesan jelas ("layanan penyimpanan sedang gangguan").
- Job ditandai `failed` dengan alasan yang jelas.
- Tidak ada pesan yang dikirim ke SQS.

## Hasil aktual

- Request gagal dengan HTTP 500 tanpa pesan yang berarti.
- Job muncul di `GET /api/jobs` dengan status `queued`.
- Job tidak pernah masuk antrian dan tidak akan pernah diproses.

## Dampak ke user

User menerima error tanpa penjelasan dan mengira upload gagal total. Namun job "hantu" tetap tercatat `queued` di daftar, sehingga membingungkan dan mengotori data monitoring.

## Akar masalah

Baris job dibuat di database (`store_.create`) sebelum operasi S3 (`put_upload`) dan SQS (`enqueue_job`). Tidak ada penanganan error maupun kompensasi (rollback), sehingga jika operasi AWS gagal, status job tidak pernah diperbarui.

## Perbaikan

Operasi `put_upload` dan `enqueue_job` dibungkus `try/except`. Jika gagal:

- `store_.update(job["id"], "failed", error="gagal menyimpan ke penyimpanan file")`
- Mengembalikan HTTP 503 dengan detail "layanan penyimpanan sedang gangguan".

## Regression test

- `tests/api/test_api.py::test_s3_outage_returns_503_and_marks_job_failed`
- Ditulis lebih dulu (merah), lalu hijau setelah perbaikan (TDD).

## Pelajaran

- Operasi multi-langkah lintas sistem (DB, S3, SQS) harus punya strategi kegagalan. Status di database harus selalu mencerminkan kenyataan.
- Skenario "dependensi down" perlu diuji secara eksplisit, bukan hanya jalur sukses.
