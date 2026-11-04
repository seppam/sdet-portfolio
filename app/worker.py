"""Worker: ambil job dari SQS, baca file dari S3, validasi, simpan hasil.

Jalankan terpisah:  python -m app.worker
Atau di dalam app (untuk dev/E2E): STRUK_RUN_WORKER=1
"""

import json
import logging
import threading

from app.aws import AwsGateway
from app.config import load_settings
from app.db import JobStore
from app.validation import FileRejected, validate_csv

log = logging.getLogger("struk.worker")


def handle_message(body: str, aws: AwsGateway, store: JobStore) -> str:
    """Proses satu pesan. Return status akhir job."""
    payload = json.loads(body)
    job_id = payload["job_id"]
    store.update(job_id, "processing")
    try:
        raw = aws.get_upload(payload["s3_key"])
        text = raw.decode("utf-8")
        report = validate_csv(text)
    except UnicodeDecodeError:
        store.update(job_id, "failed", error="file harus UTF-8")
        return "failed"
    except FileRejected as exc:
        store.update(job_id, "failed", error=str(exc))
        return "failed"
    except Exception:
        # BUG-002: error tak terduga (mis. file S3 hilang) dulu bikin job
        # nyangkut di 'processing' selamanya. Sekarang ditandai failed.
        log.exception("job %s gagal diproses", job_id)
        store.update(job_id, "failed", error="gagal membaca file upload")
        return "failed"
    store.update(job_id, "done", result=report.to_dict())
    return "done"


def process_once(aws: AwsGateway, store: JobStore, wait_seconds: int = 1) -> int:
    """Satu putaran polling. Return jumlah pesan yang diproses (berguna untuk test)."""
    messages = aws.receive_jobs(wait_seconds=wait_seconds)
    for msg in messages:
        try:
            handle_message(msg["Body"], aws, store)
        except Exception:  # pesan rusak jangan bikin worker mati
            log.exception("gagal memproses pesan")
        aws.delete_message(msg["ReceiptHandle"])
    return len(messages)


def run_forever(aws: AwsGateway, store: JobStore, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    log.info("worker mulai polling %s", aws.settings.queue_name)
    while not stop.is_set():
        try:
            process_once(aws, store, wait_seconds=1)
        except Exception:
            log.exception("polling gagal, coba lagi")
            stop.wait(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    aws = AwsGateway(settings)
    aws.ensure_resources()
    run_forever(aws, JobStore(settings.db_path))


if __name__ == "__main__":
    main()
