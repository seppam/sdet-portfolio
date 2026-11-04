# Rencana SDET Portfolio — "Struk Kilat"

Status: **Fase 0–8 selesai (4 Nov 2026)**. Detail hasil ada di README.md.

## Ide app

**Struk Kilat**: app kecil untuk upload laporan pengeluaran (CSV).

1. User upload CSV lewat web UI atau API.
2. File disimpan ke **S3**, lalu job dikirim ke **SQS**.
3. Worker ambil job dari SQS, validasi tiap baris (tanggal, nominal, kategori, duplikat), hitung total per kategori.
4. Hasil dan status job (`queued` → `processing` → `done` / `failed`) disimpan di SQLite, lalu ditampilkan di UI.

App ini sengaja "testable":
- Ada aturan bisnis yang jelas, cocok buat unit test.
- Ada REST API, cocok buat API test.
- Ada alur async lewat S3 + SQS, cocok buat integration test ke emulator AWS.
- Ada UI sederhana, cocok buat E2E.

## Stack (usulan)

| Bagian | Pilihan | Alasan |
|---|---|---|
| App | Python 3.12 + FastAPI + SQLite + boto3 | Ringan, satu bahasa dari app sampai test |
| UI | HTML + Jinja (tanpa framework JS) | Fokus ke testing, bukan frontend |
| Emulator AWS | **moto server** (Docker) | Gratis, open source (Apache 2.0), tanpa akun |
| Unit/API/integration | pytest, httpx, pytest-cov, pytest-html | Standar industri Python |
| E2E | Playwright | Paling banyak dicari di lowongan SDET |
| CI | GitHub Actions | Gratis untuk repo public |
| Tooling | uv, ruff, docker compose | Setup cepat dan rapi |

## Struktur repo (rencana)

```
sdet-portfolio/
├── app/                 # FastAPI app + worker
├── tests/
│   ├── unit/            # aturan validasi & kalkulasi
│   ├── api/             # endpoint, status code, schema, error
│   ├── integration/     # S3 + SQS lewat moto server
│   └── e2e/             # Playwright + page objects
├── docker-compose.yml   # app + moto
├── .github/workflows/   # CI per layer + report
└── docs/                # test strategy, test plan, contoh bug report
```

## Fase

0. Setup: repo, uv, ruff, docker compose + moto.
1. App: upload → S3 → SQS → worker → status.
2. Unit test: parametrize, edge case, coverage.
3. API test: happy path, validasi input, error response.
4. Integration test: moto server, fixture reset state, test async (polling/timeout).
5. E2E Playwright: page object, screenshot/trace saat gagal.
6. CI GitHub Actions: job per layer, artifact HTML report + Playwright trace.
7. Docs: README strategi testing, test plan, contoh bug report (dari pengalaman QA manual).
8. *(Opsional, belakangan)*: mini-emulator S3+SQS buatan sendiri sebagai side project belajar; load test k6.

Push ke GitHub hanya setelah user izin.
