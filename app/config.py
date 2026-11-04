"""Konfigurasi dari environment variable.

Semua yang beda antara laptop, CI, dan "production" ditaruh di env,
supaya test bisa mengarahkan app ke emulator AWS tanpa ubah kode.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    aws_endpoint_url: str | None
    aws_region: str
    bucket: str
    queue_name: str
    db_path: str
    run_worker_in_app: bool
    max_upload_bytes: int = 1_000_000


def load_settings() -> Settings:
    return Settings(
        aws_endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
        aws_region=os.getenv("AWS_DEFAULT_REGION", "ap-southeast-3"),
        bucket=os.getenv("STRUK_BUCKET", "struk-uploads"),
        queue_name=os.getenv("STRUK_QUEUE", "struk-jobs"),
        db_path=os.getenv("STRUK_DB_PATH", "data/struk.db"),
        run_worker_in_app=os.getenv("STRUK_RUN_WORKER", "0") == "1",
    )
