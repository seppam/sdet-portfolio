"""Test untuk mini-aws sendiri (emulator juga kode -> juga perlu dites).

Server dinyalakan di thread terpisah dalam proses test, jadi tidak butuh Docker.
"""

import threading

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from mini_aws.server import decode_aws_chunked, make_server


@pytest.fixture(scope="module")
def endpoint():
    server = make_server(port=0)  # port 0 = pilih port kosong otomatis
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def s3(endpoint):
    return boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                        aws_access_key_id="t", aws_secret_access_key="t",
                        config=Config(s3={"addressing_style": "path"}))


@pytest.fixture
def sqs(endpoint):
    return boto3.client("sqs", endpoint_url=endpoint, region_name="us-east-1",
                        aws_access_key_id="t", aws_secret_access_key="t")


# ---------- unit: parser aws-chunked ----------

def test_decode_aws_chunked_plain():
    raw = b"5\r\nhello\r\n6\r\n world\r\n0\r\nx-amz-checksum-crc32:abc=\r\n\r\n"
    assert decode_aws_chunked(raw) == b"hello world"


def test_decode_aws_chunked_with_signature_extension():
    raw = b"3;chunk-signature=deadbeef\r\nabc\r\n0;chunk-signature=00\r\n\r\n"
    assert decode_aws_chunked(raw) == b"abc"


def test_decode_aws_chunked_empty_body():
    assert decode_aws_chunked(b"0\r\n\r\n") == b""


# ---------- perilaku S3 ----------

def test_s3_errors_match_aws_codes(s3):
    with pytest.raises(ClientError) as exc:
        s3.get_object(Bucket="tidak-ada", Key="a")
    assert exc.value.response["Error"]["Code"] == "NoSuchBucket"

    s3.create_bucket(Bucket="err-test")
    with pytest.raises(s3.exceptions.NoSuchKey):
        s3.get_object(Bucket="err-test", Key="a")

    with pytest.raises(ClientError) as exc:
        s3.create_bucket(Bucket="err-test")
    assert exc.value.response["Error"]["Code"] == "BucketAlreadyOwnedByYou"


def test_s3_list_objects_with_prefix(s3):
    s3.create_bucket(Bucket="list-test")
    for key in ["uploads/a.csv", "uploads/b.csv", "other/c.csv"]:
        s3.put_object(Bucket="list-test", Key=key, Body=b"x")
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="list-test", Prefix="uploads/")["Contents"]]
    assert keys == ["uploads/a.csv", "uploads/b.csv"]


def test_s3_large_binary_roundtrip(s3):
    s3.create_bucket(Bucket="big-test")
    blob = bytes(range(256)) * 4096  # 1 MiB, semua nilai byte
    s3.put_object(Bucket="big-test", Key="blob.bin", Body=blob)
    assert s3.get_object(Bucket="big-test", Key="blob.bin")["Body"].read() == blob


# ---------- perilaku SQS ----------

def test_sqs_unknown_queue_maps_to_boto_exception(sqs):
    with pytest.raises(sqs.exceptions.QueueDoesNotExist):
        sqs.get_queue_url(QueueName="tidak-ada")


def test_sqs_create_queue_is_idempotent(sqs):
    a = sqs.create_queue(QueueName="idem")["QueueUrl"]
    b = sqs.create_queue(QueueName="idem")["QueueUrl"]
    assert a == b


def test_sqs_max_messages_is_capped_at_10(sqs):
    url = sqs.create_queue(QueueName="cap")["QueueUrl"]
    for i in range(15):
        sqs.send_message(QueueUrl=url, MessageBody=f"m{i}")
    got = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10)["Messages"]
    assert len(got) == 10
    # AWS asli menolak >10 (boto3 tidak memvalidasi ini di sisi klien).
    with pytest.raises(ClientError) as exc:
        sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=11)
    assert exc.value.response["Error"]["Code"] == "InvalidParameterValue"


def test_sqs_unicode_body_passes_md5_check(sqs):
    """boto3 memverifikasi MD5 body; emoji/aksara non-ASCII menguji encoding kita."""
    url = sqs.create_queue(QueueName="uni")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="kopi ☕ 咖啡")
    assert sqs.receive_message(QueueUrl=url)["Messages"][0]["Body"] == "kopi ☕ 咖啡"


def test_sqs_purge(sqs):
    url = sqs.create_queue(QueueName="purge")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="x")
    sqs.purge_queue(QueueUrl=url)
    assert "Messages" not in sqs.receive_message(QueueUrl=url)


def test_unsupported_sqs_action_fails_loudly(sqs):
    url = sqs.create_queue(QueueName="unsup")["QueueUrl"]
    with pytest.raises(ClientError) as exc:
        sqs.tag_queue(QueueUrl=url, Tags={"a": "b"})
    assert "belum didukung" in exc.value.response["Error"]["Message"]
