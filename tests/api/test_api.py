"""API test: cek kontrak HTTP (status code, bentuk JSON, pesan error).

Mirip yang biasa dicek manual di Postman, tapi otomatis dan bisa diulang.
"""

import pytest

from app.worker import process_once

VALID = b"date,description,category,amount\n2026-10-01,Kopi,makan,10000\n"


def upload(client, content=VALID, name="laporan.csv"):
    return client.post("/api/uploads", files={"file": (name, content, "text/csv")})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_returns_202_and_queues_job(client, fake_aws):
    resp = upload(client)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert len(body["job_id"]) == 12

    # Efek samping: file masuk "S3", pesan masuk "SQS"
    assert fake_aws.objects[f"uploads/{body['job_id']}.csv"] == VALID
    assert fake_aws.queue == [{"job_id": body["job_id"], "s3_key": f"uploads/{body['job_id']}.csv"}]


@pytest.mark.parametrize(
    ("name", "content", "status", "detail"),
    [
        ("laporan.txt", VALID, 415, "hanya file .csv"),
        ("laporan.csv", b"", 422, "file kosong"),
        ("laporan.csv", b"   \n", 422, "file kosong"),
        ("laporan.csv", b"x" * 1_000_001, 413, "maksimal 1 MB"),
    ],
    ids=["ekstensi-salah", "kosong", "spasi-saja", "kebesaran"],
)
def test_upload_rejections(client, fake_aws, name, content, status, detail):
    resp = upload(client, content, name)
    assert resp.status_code == status
    assert detail in resp.json()["detail"]
    assert fake_aws.queue == []  # tidak boleh ada job "hantu"


def test_upload_exactly_1mb_is_accepted(client):
    content = VALID + b"#" * (1_000_000 - len(VALID))
    assert len(content) == 1_000_000
    assert upload(client, content).status_code == 202


def test_upload_without_file_field(client):
    assert client.post("/api/uploads").status_code == 422


def test_get_unknown_job_is_404(client):
    resp = client.get("/api/jobs/tidakada")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "job tidak ditemukan"}


def test_job_lifecycle_queued_to_done(client, fake_aws, store):
    job_id = upload(client).json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"

    assert process_once(fake_aws, store) == 1

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert job["result"]["grand_total"] == 10000
    assert job["error"] is None


def test_job_with_bad_header_fails_with_reason(client, fake_aws, store):
    job_id = upload(client, b"a,b,c,d\n1,2,3,4\n").json()["job_id"]
    process_once(fake_aws, store)
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "header" in job["error"]


def test_job_with_non_utf8_file_fails(client, fake_aws, store):
    job_id = upload(client, "date,description,category,amount\n2026-10-01,Café,makan,1\n"
                    .encode("latin-1")).json()["job_id"]
    process_once(fake_aws, store)
    assert client.get(f"/api/jobs/{job_id}").json()["error"] == "file harus UTF-8"


def test_list_jobs_newest_first(client):
    ids = [upload(client).json()["job_id"] for _ in range(3)]
    listed = [j["id"] for j in client.get("/api/jobs").json()["jobs"]]
    assert listed == list(reversed(ids))


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_list_jobs_limit_bounds(client, limit):
    assert client.get(f"/api/jobs?limit={limit}").status_code == 422


def test_s3_outage_returns_503_and_marks_job_failed(client, fake_aws):
    """Regression test BUG-001: dulu job tertinggal 'queued' selamanya kalau S3 down.

    Lihat docs/bug-reports/BUG-001-ghost-queued-job.md
    """
    fake_aws.fail_put = True
    resp = upload(client)
    assert resp.status_code == 503
    assert fake_aws.queue == []
    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["status"] for j in jobs] == ["failed"]
    assert "penyimpanan" in jobs[0]["error"]


def test_web_form_redirects_to_job_page(client):
    resp = client.post("/upload", files={"file": ("a.csv", VALID, "text/csv")},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/jobs/")


def test_web_form_shows_error_message(client):
    resp = client.post("/upload", files={"file": ("a.txt", VALID, "text/plain")})
    assert resp.status_code == 415
    assert 'data-testid="upload-error"' in resp.text
