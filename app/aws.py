"""Pembungkus tipis S3 + SQS.

`endpoint_url` diisi saat pakai emulator (moto / mini-aws).
Kalau kosong, boto3 bicara ke AWS sungguhan — kodenya sama persis.
"""

import json

import boto3
from botocore.config import Config

from app.config import Settings


class AwsGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        common = {
            "region_name": settings.aws_region,
            "endpoint_url": settings.aws_endpoint_url,
        }
        self.s3 = boto3.client(
            "s3", config=Config(s3={"addressing_style": "path"}), **common
        )
        self.sqs = boto3.client("sqs", **common)
        self._queue_url: str | None = None

    def ensure_resources(self) -> None:
        """Buat bucket & queue kalau belum ada (idempotent)."""
        existing = {b["Name"] for b in self.s3.list_buckets().get("Buckets", [])}
        if self.settings.bucket not in existing:
            kwargs = {"Bucket": self.settings.bucket}
            if self.settings.aws_region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.settings.aws_region
                }
            self.s3.create_bucket(**kwargs)
        self._queue_url = self.sqs.create_queue(QueueName=self.settings.queue_name)["QueueUrl"]

    @property
    def queue_url(self) -> str:
        if self._queue_url is None:
            self._queue_url = self.sqs.get_queue_url(QueueName=self.settings.queue_name)[
                "QueueUrl"
            ]
        return self._queue_url

    def put_upload(self, key: str, body: bytes) -> None:
        self.s3.put_object(Bucket=self.settings.bucket, Key=key, Body=body,
                           ContentType="text/csv")

    def get_upload(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.settings.bucket, Key=key)["Body"].read()

    def enqueue_job(self, job_id: str, key: str) -> None:
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"job_id": job_id, "s3_key": key}),
        )

    def receive_jobs(self, wait_seconds: int = 1, max_messages: int = 5) -> list[dict]:
        resp = self.sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return resp.get("Messages", [])

    def delete_message(self, receipt_handle: str) -> None:
        self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
