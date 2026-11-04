"""Test double: pengganti AwsGateway yang menyimpan semuanya di memori.

Dipakai di API test supaya cepat dan tidak butuh Docker.
Integration test TIDAK pakai ini — di sana kita pakai emulator sungguhan.
"""

import json


class FakeAws:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.queue: list[dict] = []
        self.fail_put = False  # skenario: S3 sedang down

    def ensure_resources(self):
        pass

    def put_upload(self, key, body):
        if self.fail_put:
            raise ConnectionError("S3 tidak bisa dihubungi")
        self.objects[key] = body

    def get_upload(self, key):
        return self.objects[key]

    def enqueue_job(self, job_id, key):
        self.queue.append({"job_id": job_id, "s3_key": key})

    def receive_jobs(self, wait_seconds=1, max_messages=5):
        batch, self.queue = self.queue[:max_messages], self.queue[max_messages:]
        return [{"Body": json.dumps(m), "ReceiptHandle": str(i)} for i, m in enumerate(batch)]

    def delete_message(self, receipt_handle):
        pass
