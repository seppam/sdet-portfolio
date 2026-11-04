"""FastAPI app: upload CSV -> S3 -> SQS, lalu cek status job.

`create_app()` menerima dependency (aws, store) dari luar. Ini kunci
"testability": API test bisa menyuntikkan fake gateway tanpa emulator,
sedangkan integration test memakai gateway sungguhan ke emulator.
"""

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.aws import AwsGateway
from app.config import Settings, load_settings
from app.db import JobStore
from app.worker import run_forever

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def rupiah(value: int) -> str:
    return "Rp " + f"{value:,}".replace(",", ".")


TEMPLATES.env.filters["rupiah"] = rupiah


def create_app(settings: Settings | None = None, aws=None, store: JobStore | None = None):
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.aws = aws or AwsGateway(settings)
        app.state.store = store or JobStore(settings.db_path)
        app.state.aws.ensure_resources()
        stop = threading.Event()
        if settings.run_worker_in_app:
            threading.Thread(
                target=run_forever, args=(app.state.aws, app.state.store, stop), daemon=True
            ).start()
        yield
        stop.set()

    app = FastAPI(title="Struk Kilat", version="0.1.0", lifespan=lifespan)

    async def _accept_upload(request: Request, file: UploadFile) -> dict:
        name = file.filename or ""
        if not name.lower().endswith(".csv"):
            raise HTTPException(status_code=415, detail="hanya file .csv yang diterima")
        body = await file.read(settings.max_upload_bytes + 1)
        if len(body) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="ukuran file maksimal 1 MB")
        if not body.strip():
            raise HTTPException(status_code=422, detail="file kosong")
        store_: JobStore = request.app.state.store
        job = store_.create(name)
        try:
            request.app.state.aws.put_upload(job["s3_key"], body)
            request.app.state.aws.enqueue_job(job["id"], job["s3_key"])
        except Exception as exc:
            # BUG-001: jangan biarkan job tertinggal 'queued' kalau S3/SQS gagal.
            store_.update(job["id"], "failed", error="gagal menyimpan ke penyimpanan file")
            raise HTTPException(
                status_code=503, detail="layanan penyimpanan sedang gangguan"
            ) from exc
        return job

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/uploads", status_code=202)
    async def upload(request: Request, file: UploadFile = File(...)):
        job = await _accept_upload(request, file)
        return {"job_id": job["id"], "status": job["status"]}

    @app.get("/api/jobs")
    def list_jobs(request: Request, limit: int = 20):
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit harus 1-100")
        return {"jobs": request.app.state.store.list(limit)}

    @app.get("/api/jobs/{job_id}")
    def get_job(request: Request, job_id: str):
        job = request.app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job tidak ditemukan")
        return job

    # ---------- Halaman web (dipakai E2E test) ----------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return TEMPLATES.TemplateResponse(
            request, "index.html", {"jobs": request.app.state.store.list(10), "error": None}
        )

    @app.post("/upload", response_class=HTMLResponse)
    async def upload_form(request: Request, file: UploadFile = File(...)):
        try:
            job = await _accept_upload(request, file)
        except HTTPException as exc:
            return TEMPLATES.TemplateResponse(
                request, "index.html",
                {"jobs": request.app.state.store.list(10), "error": exc.detail},
                status_code=exc.status_code,
            )
        return RedirectResponse(f"/jobs/{job['id']}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str):
        job = request.app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job tidak ditemukan")
        return TEMPLATES.TemplateResponse(request, "job.html", {"job": job})

    return app


app = create_app()
