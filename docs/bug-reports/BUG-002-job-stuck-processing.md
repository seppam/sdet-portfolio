# BUG-002: Job nyangkut "processing" saat file di S3 tidak ditemukan

| Field | Nilai |
|---|---|
| ID | BUG-002 |
| Severity | Major |
| Priority | High |
| Komponen | Worker (`app/worker.py`, fungsi `handle_message`) |
| Ditemukan oleh | Integration test terhadap moto server (emulator AWS). Fake di API test tidak menemukan bug ini karena fake tidak meniru error `NoSuchKey` dari S3. |
| Status | Fixed |

## Ringkasan

Jika pesan SQS menunjuk ke key S3 yang tidak ada, worker melempar `botocore.errorfactory.NoSuchKey` yang tidak ditangani. Status job tetap `processing` selamanya, walaupun pesan SQS sudah dihapus dan worker tetap berjalan.

## Langkah reproduksi

1. Buat job di SQLite dengan status `queued`.
2. Kirim pesan SQS yang berisi `job_id` tersebut dan `s3_key` yang tidak ada di S3 (moto server).
3. Jalankan worker satu putaran (`process_once`).
4. Cek status job di database.

## Hasil yang diharapkan

- Job berstatus `failed` dengan alasan "gagal membaca file upload".
- Worker tetap hidup dan melanjutkan polling.

## Hasil aktual

- Exception `botocore.errorfactory.NoSuchKey` lolos dari `handle_message`.
- `process_once` menangkapnya di level loop dan menghapus pesan.
- Status job tetap `processing` selamanya.

## Dampak ke user

User melihat upload-nya "sedang diproses" tanpa batas waktu dan tidak mendapat hasil maupun pesan error. Pesan sudah hilang dari antrian, sehingga tidak ada mekanisme retry yang bisa memulihkan job ini.

## Akar masalah

`handle_message` hanya menangani `UnicodeDecodeError` dan `FileRejected`. Error lain (seperti `NoSuchKey` dari S3) tidak mengubah status job, sehingga job tertinggal di `processing`.

## Perbaikan

Menambahkan blok `except Exception` di `handle_message` yang mencatat log error (`log.exception`) lalu menandai job `failed` dengan alasan "gagal membaca file upload".

## Regression test

- `tests/integration/test_aws_pipeline.py::test_missing_s3_object_marks_job_not_stuck`

## Pelajaran

- Test double (fake) hanya sebaik asumsi kita tentang perilaku dependensi. Fake yang tidak meniru error asli S3 menyembunyikan bug.
- Integration test ke emulator (moto) menangkap perilaku asli boto3/S3, termasuk jenis exception yang sebenarnya.
- Setiap jalur error harus memiliki transisi status yang jelas; jangan biarkan job berhenti di status transisi.
