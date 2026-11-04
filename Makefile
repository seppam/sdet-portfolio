# Jalankan `make help` untuk lihat semua perintah.
.PHONY: help install moto-up moto-down floci-up mini-aws dev lint test-fast test-int test-int-floci test-int-mini test-e2e test-all report

MOTO_URL := http://localhost:5055
MINI_URL := http://localhost:5066
FLOCI_URL := http://localhost:4566

help:
	@grep -E '^[a-z-]+:.*## ' Makefile | awk 'BEGIN{FS=":.*## "}{printf "  %-14s %s\n",$$1,$$2}'

install: ## Install dependency + browser Playwright
	uv sync
	uv run playwright install chromium

moto-up: ## Nyalakan moto server (Docker) di port 5055
	docker compose up -d moto

moto-down: ## Matikan semua emulator
	docker compose --profile floci down

floci-up: ## Nyalakan Floci (pengganti LocalStack) di port 4566
	docker compose --profile floci up -d floci

mini-aws: ## Nyalakan mini-aws buatan sendiri di port 5066 (foreground)
	uv run python -m mini_aws --port 5066 --verbose

dev: ## Jalankan app + worker di http://localhost:8077 (butuh moto-up)
	set -a; . ./.env.example; set +a; uv run uvicorn app.main:app --port 8077 --reload

lint: ## Cek gaya kode
	uv run ruff check .

test-fast: ## Unit + API + test mini-aws (tanpa Docker)
	uv run pytest tests/unit tests/api tests/mini_aws

test-int: ## Integration test ke moto
	AWS_ENDPOINT_URL=$(MOTO_URL) uv run pytest tests/integration

test-int-floci: ## Integration test ke Floci (butuh floci-up)
	AWS_ENDPOINT_URL=$(FLOCI_URL) uv run pytest tests/integration

test-int-mini: ## Integration test ke mini-aws (nyalakan `make mini-aws` dulu)
	AWS_ENDPOINT_URL=$(MINI_URL) uv run pytest tests/integration

test-e2e: ## E2E Playwright (butuh moto-up). Tambah HEADED=1 untuk lihat browser
	AWS_ENDPOINT_URL=$(MOTO_URL) uv run pytest tests/e2e $(if $(HEADED),--headed --slowmo 400,) \
		--tracing retain-on-failure --screenshot only-on-failure

test-all: ## Semua test + HTML report di reports/
	AWS_ENDPOINT_URL=$(MOTO_URL) uv run pytest --cov --cov-report=html:reports/coverage \
		--html=reports/all.html --self-contained-html

report: ## Buka HTML report terakhir
	open reports/all.html
