"""Page Object Model.

Selector & langkah UI dikumpulkan di satu kelas per halaman. Kalau UI berubah,
yang diubah cukup di sini, bukan di puluhan test. Selector pakai data-testid
supaya tidak gampang patah karena perubahan teks/CSS.
"""

import re
from pathlib import Path

from playwright.sync_api import Page, expect

FINISHED = re.compile(r"^(done|failed)$")


class UploadPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url
        self.file_input = page.get_by_test_id("file-input")
        self.upload_button = page.get_by_test_id("upload-button")
        self.error = page.get_by_test_id("upload-error")
        self.jobs_table = page.get_by_test_id("jobs-table")

    def open(self) -> "UploadPage":
        self.page.goto(self.base_url + "/")
        return self

    def upload(self, path: Path) -> "JobPage":
        self.file_input.set_input_files(path)
        self.upload_button.click()
        return JobPage(self.page)


class JobPage:
    def __init__(self, page: Page):
        self.page = page
        self.status = page.get_by_test_id("job-status")
        self.grand_total = page.get_by_test_id("grand-total")
        self.row_counts = page.get_by_test_id("row-counts")
        self.errors_table = page.get_by_test_id("errors-table")
        self.error = page.get_by_test_id("job-error")

    def wait_until_finished(self, timeout_ms: int = 15_000) -> "JobPage":
        # Halaman refresh otomatis tiap 1 detik. expect() otomatis menunggu & retry
        # sampai teks cocok -> TIDAK perlu time.sleep() (sumber utama test flaky).
        expect(self.status).to_have_text(FINISHED, timeout=timeout_ms)
        return self
