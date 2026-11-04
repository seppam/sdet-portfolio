"""mini-aws: emulator S3 + SQS super kecil, hanya pakai standard library Python.

Tujuannya BELAJAR: melihat bahwa "AWS" dari sisi SDK itu cuma HTTP request
dengan format tertentu. boto3 tidak tahu (dan tidak peduli) apakah yang
menjawab itu AWS asli, moto, atau server 300 baris ini.

Yang didukung (cukup untuk app Struk Kilat):
  S3  (REST + XML, path-style):  ListBuckets, CreateBucket, HeadBucket,
                                 PutObject, GetObject, DeleteObject, ListObjectsV2
  SQS (JSON protocol, header X-Amz-Target):
                                 CreateQueue, GetQueueUrl, ListQueues, SendMessage,
                                 ReceiveMessage, DeleteMessage, PurgeQueue

Tidak didukung: auth/signature check, IAM, versioning, multipart, FIFO, DLQ, dst.
Jangan dipakai untuk apa pun selain test lokal.

Jalankan:  python -m mini_aws --port 5066
"""

import argparse
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
DEFAULT_VISIBILITY = 30
ACCOUNT = "000000000000"


# ---------------------------------------------------------------- state

@dataclass
class S3Object:
    body: bytes
    content_type: str
    etag: str
    modified: datetime


@dataclass
class Message:
    id: str
    body: str
    md5: str
    visible_at: float = 0.0
    receipt: str | None = None


@dataclass
class Queue:
    name: str
    url: str
    visibility_timeout: int = DEFAULT_VISIBILITY
    messages: list[Message] = field(default_factory=list)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets: dict[str, dict[str, S3Object]] = {}
        self.bucket_created: dict[str, datetime] = {}
        self.queues: dict[str, Queue] = {}

    def reset(self):
        with self.lock:
            self.buckets.clear()
            self.bucket_created.clear()
            self.queues.clear()


# ---------------------------------------------------------------- helpers

def decode_aws_chunked(raw: bytes) -> bytes:
    """Bongkar body 'aws-chunked' (dipakai boto3 baru untuk checksum di trailer).

    Format:  <hex-size>[;chunk-signature=..]\\r\\n<data>\\r\\n ... 0\\r\\n<trailer>\\r\\n\\r\\n
    """
    out, pos = bytearray(), 0
    while True:
        line_end = raw.index(b"\r\n", pos)
        size = int(raw[pos:line_end].split(b";")[0], 16)
        pos = line_end + 2
        if size == 0:
            return bytes(out)
        out += raw[pos:pos + size]
        pos += size + 2  # lewati data + \r\n


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def s3_error(code: str, message: str, status: int, resource: str = "") -> tuple[int, bytes]:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Error><Code>{code}</Code><Message>{escape(message)}</Message>"
        f"<Resource>{escape(resource)}</Resource><RequestId>{uuid.uuid4().hex}</RequestId></Error>"
    )
    return status, body.encode()


class SqsError(Exception):
    """`query_code` = kode lama (protokol Query) yang dikirim AWS di header
    x-amzn-query-error; boto3 memakainya untuk memilih kelas exception."""

    def __init__(self, code: str, message: str, status: int = 400,
                 query_code: str | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.query_code = query_code or code


def queue_missing() -> SqsError:
    return SqsError("QueueDoesNotExist", "The specified queue does not exist.",
                    query_code="AWS.SimpleQueueService.NonExistentQueue")


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    state: State  # diisi oleh make_server()
    protocol_version = "HTTP/1.1"

    # Matikan log default yang berisik; aktifkan dengan --verbose.
    verbose = False

    def log_message(self, fmt, *args):
        pass  # log bawaan diganti log_request di bawah

    def log_request(self, code="-", size="-"):
        """Satu baris per request yang menunjukkan 'AWS cuma HTTP':
        S3 terlihat dari method + path, SQS dari header X-Amz-Target."""
        if not self.verbose:
            return
        target = self.headers.get("X-Amz-Target", "")
        if target:
            what = f"SQS  {target.removeprefix('AmazonSQS.'):<15} {self.command} {self.path}"
        else:
            what = f"S3   {self.command:<15} {self.path}"
        print(f"{time.strftime('%H:%M:%S')}  {code}  {what}", flush=True)

    # ---- dispatch

    def do_GET(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch(head=True)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        encoding = self.headers.get("Content-Encoding", "")
        sha = self.headers.get("x-amz-content-sha256", "")
        if "aws-chunked" in encoding or sha.startswith("STREAMING-"):
            raw = decode_aws_chunked(raw)
        return raw

    def _dispatch(self, head: bool = False):
        body = self._read_body()
        url = urlsplit(self.path)
        if url.path == "/_mini/reset" and self.command == "POST":
            self.state.reset()
            return self._send(200, b'{"reset": true}', "application/json")
        target = self.headers.get("X-Amz-Target", "")
        if target.startswith("AmazonSQS."):
            return self._sqs(target.removeprefix("AmazonSQS."), body)
        return self._s3(url, body, head)

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/xml",
              headers: dict | None = None, head: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-amz-request-id", uuid.uuid4().hex)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    # ---- S3

    def _s3(self, url, body: bytes, head: bool):
        parts = unquote(url.path).lstrip("/").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        query = parse_qs(url.query)
        st = self.state
        m = self.command

        with st.lock:
            if not bucket:
                if m == "GET":
                    return self._send(200, self._list_buckets())
                return self._send(*s3_error("MethodNotAllowed", "not allowed", 405))

            exists = bucket in st.buckets
            if not key:
                if m == "PUT":
                    if exists:
                        return self._send(*s3_error("BucketAlreadyOwnedByYou",
                                                    "bucket already exists", 409, bucket))
                    st.buckets[bucket] = {}
                    st.bucket_created[bucket] = datetime.now(UTC)
                    return self._send(200, headers={"Location": f"/{bucket}"})
                if not exists:
                    return self._send(*s3_error("NoSuchBucket", "bucket not found", 404, bucket),
                                      head=head)
                if m == "HEAD":
                    return self._send(200, head=True)
                if m == "GET":
                    return self._send(200, self._list_objects(bucket, query))
                if m == "DELETE":
                    if st.buckets[bucket]:
                        return self._send(*s3_error("BucketNotEmpty", "bucket not empty", 409))
                    del st.buckets[bucket]
                    return self._send(204)

            if not exists:
                return self._send(*s3_error("NoSuchBucket", "bucket not found", 404, bucket),
                                  head=head)
            objects = st.buckets[bucket]
            if m == "PUT":
                etag = f'"{hashlib.md5(body).hexdigest()}"'
                objects[key] = S3Object(
                    body, self.headers.get("Content-Type", "binary/octet-stream"),
                    etag, datetime.now(UTC),
                )
                return self._send(200, headers={"ETag": etag})
            if m in ("GET", "HEAD"):
                obj = objects.get(key)
                if obj is None:
                    return self._send(*s3_error("NoSuchKey", "The specified key does not exist.",
                                                404, f"/{bucket}/{key}"), head=head)
                return self._send(200, obj.body, obj.content_type, head=head, headers={
                    "ETag": obj.etag,
                    "Last-Modified": formatdate(obj.modified.timestamp(), usegmt=True),
                })
            if m == "DELETE":
                objects.pop(key, None)
                return self._send(204)
        return self._send(*s3_error("NotImplemented", f"{m} not supported", 501))

    def _list_buckets(self) -> bytes:
        items = "".join(
            f"<Bucket><Name>{escape(n)}</Name><CreationDate>{iso(c)}</CreationDate></Bucket>"
            for n, c in sorted(self.state.bucket_created.items())
        )
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><ListAllMyBucketsResult xmlns="{S3_NS}">'
            f"<Owner><ID>{ACCOUNT}</ID><DisplayName>mini</DisplayName></Owner>"
            f"<Buckets>{items}</Buckets></ListAllMyBucketsResult>"
        ).encode()

    def _list_objects(self, bucket: str, query: dict) -> bytes:
        prefix = query.get("prefix", [""])[0]
        objs = sorted((k, o) for k, o in self.state.buckets[bucket].items() if k.startswith(prefix))
        items = "".join(
            f"<Contents><Key>{escape(k)}</Key><LastModified>{iso(o.modified)}</LastModified>"
            f"<ETag>{escape(o.etag)}</ETag><Size>{len(o.body)}</Size>"
            f"<StorageClass>STANDARD</StorageClass></Contents>"
            for k, o in objs
        )
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{S3_NS}">'
            f"<Name>{escape(bucket)}</Name><Prefix>{escape(prefix)}</Prefix>"
            f"<KeyCount>{len(objs)}</KeyCount><MaxKeys>1000</MaxKeys>"
            f"<IsTruncated>false</IsTruncated>{items}</ListBucketResult>"
        ).encode()

    # ---- SQS

    def _sqs(self, action: str, body: bytes):
        try:
            params = json.loads(body or b"{}")
            handler = getattr(self, f"_sqs_{action}", None)
            if handler is None:
                raise SqsError("UnsupportedOperation", f"{action} belum didukung mini-aws")
            if action == "ReceiveMessage":
                result = handler(params)  # long polling: kunci diambil di dalam
            else:
                with self.state.lock:
                    result = handler(params)
            return self._send(200, json.dumps(result).encode(), "application/x-amz-json-1.0")
        except SqsError as err:
            payload = {"__type": f"com.amazonaws.sqs#{err.code}", "message": err.message}
            return self._send(err.status, json.dumps(payload).encode(),
                              "application/x-amz-json-1.0",
                              headers={"x-amzn-query-error": f"{err.query_code};Sender"})

    def _queue_url(self, name: str) -> str:
        host = self.headers.get("Host", "localhost")
        return f"http://{host}/{ACCOUNT}/{name}"

    def _queue(self, url: str) -> Queue:
        name = url.rstrip("/").rsplit("/", 1)[-1]
        q = self.state.queues.get(name)
        if q is None:
            raise queue_missing()
        return q

    def _sqs_CreateQueue(self, p):
        name = p["QueueName"]
        q = self.state.queues.get(name)
        if q is None:
            vt = int(p.get("Attributes", {}).get("VisibilityTimeout", DEFAULT_VISIBILITY))
            q = self.state.queues[name] = Queue(name, self._queue_url(name), vt)
        return {"QueueUrl": q.url}

    def _sqs_GetQueueUrl(self, p):
        q = self.state.queues.get(p["QueueName"])
        if q is None:
            raise queue_missing()
        return {"QueueUrl": q.url}

    def _sqs_ListQueues(self, p):
        prefix = p.get("QueueNamePrefix", "")
        return {"QueueUrls": [q.url for n, q in sorted(self.state.queues.items())
                              if n.startswith(prefix)]}

    def _sqs_SendMessage(self, p):
        q = self._queue(p["QueueUrl"])
        body = p["MessageBody"]
        msg = Message(uuid.uuid4().hex, body, hashlib.md5(body.encode()).hexdigest())
        q.messages.append(msg)
        # boto3 MEMVERIFIKASI MD5 ini; kalau salah, boto3 menolak respons.
        return {"MessageId": msg.id, "MD5OfMessageBody": msg.md5}

    def _sqs_ReceiveMessage(self, p):
        limit = int(p.get("MaxNumberOfMessages", 1))
        if not 1 <= limit <= 10:
            # Sama seperti AWS asli: tolak, jangan diam-diam dipotong.
            raise SqsError("InvalidParameterValue",
                           "Value for parameter MaxNumberOfMessages is invalid. "
                           "Reason: must be between 1 and 10, if provided.")
        wait = min(int(p.get("WaitTimeSeconds", 0)), 20)
        deadline = time.monotonic() + wait
        while True:
            with self.state.lock:
                q = self._queue(p["QueueUrl"])
                got = self._take_visible(q, p)
            if got or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        if not got:
            return {}
        return {"Messages": [
            {"MessageId": m.id, "ReceiptHandle": m.receipt, "MD5OfBody": m.md5, "Body": m.body}
            for m in got
        ]}

    @staticmethod
    def _take_visible(q: Queue, p) -> list[Message]:
        now = time.monotonic()
        limit = min(int(p.get("MaxNumberOfMessages", 1)), 10)
        vt = int(p.get("VisibilityTimeout", q.visibility_timeout))
        got = []
        for m in q.messages:
            if len(got) >= limit:
                break
            if m.visible_at <= now:
                m.visible_at = now + vt
                m.receipt = uuid.uuid4().hex  # handle baru tiap kali diterima
                got.append(m)
        return got

    def _sqs_DeleteMessage(self, p):
        q = self._queue(p["QueueUrl"])
        q.messages = [m for m in q.messages if m.receipt != p["ReceiptHandle"]]
        return {}

    def _sqs_PurgeQueue(self, p):
        self._queue(p["QueueUrl"]).messages.clear()
        return {}


# ---------------------------------------------------------------- entrypoint

def make_server(host: str = "127.0.0.1", port: int = 5066, verbose: bool = False):
    handler = type("BoundHandler", (Handler,), {"state": State(), "verbose": verbose})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="mini-aws: emulator S3+SQS untuk belajar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5066)
    parser.add_argument("--verbose", action="store_true", help="tampilkan tiap request")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port, args.verbose)
    print(f"mini-aws jalan di http://{args.host}:{args.port}  (Ctrl+C untuk berhenti)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
