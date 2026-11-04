"""E2E: alur user di browser sungguhan (Chromium via Playwright).

E2E paling mahal & paling lambat, jadi jumlahnya sedikit: hanya alur penting
yang benar-benar dilihat user. Detail aturan validasi sudah dicek di unit test.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages import UploadPage

pytestmark = pytest.mark.e2e


def test_valid_csv_shows_summary(page: Page, app_url, samples):
    job = UploadPage(page, app_url).open().upload(samples / "valid.csv").wait_until_finished()

    expect(job.status).to_have_text("done")
    expect(job.grand_total).to_have_text("Rp 1.685.000")
    expect(job.row_counts).to_have_text("4 baris valid, 0 baris ditolak")
    expect(job.errors_table).to_have_count(0)


def test_mixed_csv_lists_rejected_rows(page: Page, app_url, samples):
    job = UploadPage(page, app_url).open().upload(samples / "mixed.csv").wait_until_finished()

    expect(job.status).to_have_text("done")
    expect(job.row_counts).to_have_text("2 baris valid, 4 baris ditolak")
    rows = job.errors_table.locator("tbody tr")
    expect(rows).to_have_count(4)
    expect(rows.nth(0)).to_contain_text("YYYY-MM-DD")
    expect(rows.nth(3)).to_contain_text("duplikat")


def test_bad_header_marks_job_failed(page: Page, app_url, samples):
    job = UploadPage(page, app_url).open().upload(samples / "bad_header.csv").wait_until_finished()

    expect(job.status).to_have_text("failed")
    expect(job.error).to_contain_text("header harus")


def test_non_csv_is_rejected_on_upload_page(page: Page, app_url, tmp_path):
    bogus = tmp_path / "foto.png"
    bogus.write_bytes(b"\x89PNG fake")
    upload_page = UploadPage(page, app_url).open()
    upload_page.upload(bogus)

    expect(upload_page.error).to_have_text("hanya file .csv yang diterima")
    expect(page).to_have_url(app_url + "/upload")


def test_uploaded_job_appears_in_recent_list(page: Page, app_url, samples):
    UploadPage(page, app_url).open().upload(samples / "valid.csv").wait_until_finished()
    home = UploadPage(page, app_url).open()
    expect(home.jobs_table.locator("tbody tr").first).to_contain_text("valid.csv")
