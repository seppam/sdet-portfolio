"""Fixture integration test: bicara ke emulator AWS sungguhan lewat jaringan.

Emulator dipilih lewat AWS_ENDPOINT_URL:
- moto server  -> http://localhost:5055 (default)
- mini-aws     -> http://localhost:5066 (emulator buatan sendiri, Fase 8)

Tiap test dapat bucket & queue dengan nama unik, jadi test tidak saling ganggu
dan tidak perlu "reset" emulator (berlaku untuk emulator apa pun).
"""

import os
import urllib.request
import uuid

import pytest

from app.aws import AwsGateway
from app.config import Settings
from app.db import JobStore

ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://localhost:5055")


def _emulator_up() -> bool:
    try:
        urllib.request.urlopen(ENDPOINT, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # server jawab (meski 4xx) -> berarti hidup
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    if _emulator_up():
        return
    skip = pytest.mark.skip(reason=f"emulator AWS tidak jalan di {ENDPOINT}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _dummy_credentials(monkeypatch):
    # Kredensial palsu: emulator tidak memeriksa, dan ini mencegah boto3
    # tidak sengaja memakai kredensial AWS asli di laptop.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")


@pytest.fixture
def settings():
    suffix = uuid.uuid4().hex[:8]
    return Settings(
        aws_endpoint_url=ENDPOINT,
        aws_region="ap-southeast-3",
        bucket=f"it-bucket-{suffix}",
        queue_name=f"it-queue-{suffix}",
        db_path=":memory:",
        run_worker_in_app=False,
    )


@pytest.fixture
def aws(settings):
    gw = AwsGateway(settings)
    gw.ensure_resources()
    return gw


@pytest.fixture
def store():
    return JobStore(":memory:")
