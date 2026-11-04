"""Integration test: kode kita + boto3 + emulator S3/SQS.

Yang dibuktikan di sini TIDAK bisa dibuktikan oleh fake di API test:
format request boto3 benar, bucket/queue benar-benar terbentuk,
dan perilaku SQS (visibility timeout, delete) sesuai harapan.
"""

import json
import time

import pytest

from app.aws import AwsGateway
from app.worker import process_once

pytestmark = pytest.mark.integration

VALID = b"date,description,category,amount\n2026-10-01,Kopi,makan,10000\n"


def test_ensure_resources_is_idempotent(settings, aws):
    AwsGateway(settings).ensure_resources()  # panggil kedua kali: tidak boleh error
    names = [b["Name"] for b in aws.s3.list_buckets()["Buckets"]]
    assert names.count(settings.bucket) == 1


def test_s3_roundtrip_preserves_bytes(aws):
    payload = "date,description,category,amount\n2026-10-01,Café ☕,makan,1\n".encode()
    aws.put_upload("uploads/x.csv", payload)
    assert aws.get_upload("uploads/x.csv") == payload


def test_s3_missing_key_raises(aws):
    with pytest.raises(aws.s3.exceptions.NoSuchKey):
        aws.get_upload("uploads/tidak-ada.csv")


def test_sqs_message_is_gone_after_delete(aws):
    aws.enqueue_job("job1", "uploads/job1.csv")
    msgs = aws.receive_jobs(wait_seconds=1)
    assert [json.loads(m["Body"])["job_id"] for m in msgs] == ["job1"]
    aws.delete_message(msgs[0]["ReceiptHandle"])
    assert aws.receive_jobs(wait_seconds=1) == []


def test_sqs_undeleted_message_comes_back_after_visibility_timeout(aws):
    """Inti 'at-least-once delivery': kalau worker crash sebelum delete, pesan muncul lagi."""
    aws.enqueue_job("job2", "uploads/job2.csv")
    first = aws.sqs.receive_message(QueueUrl=aws.queue_url, VisibilityTimeout=1,
                                    WaitTimeSeconds=1)["Messages"]
    assert aws.sqs.receive_message(QueueUrl=aws.queue_url, WaitTimeSeconds=0).get(
        "Messages", []) == []  # sedang "dipinjam", tidak terlihat
    time.sleep(1.5)
    again = aws.receive_jobs(wait_seconds=1)
    assert [m["Body"] for m in again] == [m["Body"] for m in first]


def test_full_pipeline_upload_to_done(aws, store):
    job = store.create("laporan.csv")
    aws.put_upload(job["s3_key"], VALID)
    aws.enqueue_job(job["id"], job["s3_key"])

    assert process_once(aws, store) == 1

    done = store.get(job["id"])
    assert done["status"] == "done"
    assert done["result"]["totals"] == {"makan": 10000}
    assert aws.receive_jobs(wait_seconds=0) == []  # pesan sudah dihapus


def test_poison_message_does_not_kill_worker(aws, store):
    """Pesan rusak (bukan JSON) harus dibuang, dan pesan berikutnya tetap diproses."""
    aws.sqs.send_message(QueueUrl=aws.queue_url, MessageBody="ini bukan json")
    job = store.create("ok.csv")
    aws.put_upload(job["s3_key"], VALID)
    aws.enqueue_job(job["id"], job["s3_key"])

    processed = 0
    for _ in range(3):  # SQS tidak menjamin urutan, jadi polling beberapa kali
        processed += process_once(aws, store)
        if processed >= 2:
            break
    assert processed == 2
    assert store.get(job["id"])["status"] == "done"


def test_missing_s3_object_marks_job_not_stuck(aws, store):
    """Pesan menunjuk file yang tidak ada: job tidak boleh tertinggal 'processing'."""
    job = store.create("hilang.csv")
    aws.enqueue_job(job["id"], job["s3_key"])  # sengaja tidak upload
    process_once(aws, store)
    assert store.get(job["id"])["status"] == "failed"
