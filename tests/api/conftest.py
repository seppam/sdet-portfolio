"""Fixture untuk API test.

Fixture = "persiapan" yang otomatis disuntikkan pytest ke test yang memintanya.
Tiap test dapat app + database + fake AWS yang baru, jadi test saling independen.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import JobStore
from app.main import create_app
from tests.fakes import FakeAws


@pytest.fixture
def fake_aws():
    return FakeAws()


@pytest.fixture
def store():
    return JobStore(":memory:")


@pytest.fixture
def client(fake_aws, store):
    settings = Settings(
        aws_endpoint_url=None, aws_region="ap-southeast-3", bucket="b", queue_name="q",
        db_path=":memory:", run_worker_in_app=False,
    )
    app = create_app(settings, aws=fake_aws, store=store)
    with TestClient(app) as c:
        yield c
