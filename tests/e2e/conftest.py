"""Fixture E2E: nyalakan app sungguhan (uvicorn + worker) yang terhubung ke emulator.

Satu server dipakai bersama semua test E2E di sesi ini (scope="session"),
karena menyalakan server itu mahal. Data tiap test tetap terpisah karena
tiap test meng-upload file sendiri dan memeriksa job-nya sendiri.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://localhost:5055")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    try:
        urllib.request.urlopen(ENDPOINT, timeout=2)
    except urllib.error.HTTPError:
        pass
    except OSError:
        pytest.skip(f"emulator AWS tidak jalan di {ENDPOINT}")

    port = _free_port()
    suffix = uuid.uuid4().hex[:8]
    env = {
        **os.environ,
        "AWS_ENDPOINT_URL": ENDPOINT,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "ap-southeast-3",
        "STRUK_BUCKET": f"e2e-bucket-{suffix}",
        "STRUK_QUEUE": f"e2e-queue-{suffix}",
        "STRUK_DB_PATH": str(tmp_path_factory.mktemp("db") / "e2e.db"),
        "STRUK_RUN_WORKER": "1",
    }
    log = open(tmp_path_factory.mktemp("log") / "server.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            break
        except OSError:
            if proc.poll() is not None:
                pytest.fail(f"server mati saat start, lihat {log.name}")
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.fail("server tidak siap dalam 20 detik")

    yield url
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


@pytest.fixture
def samples() -> Path:
    return SAMPLES
