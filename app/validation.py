"""Aturan bisnis: parsing & validasi CSV laporan pengeluaran.

Modul ini sengaja *murni* (tanpa AWS, tanpa database), jadi gampang
di-unit-test: masukkan teks, cek hasilnya.

Format CSV yang diterima:

    date,description,category,amount
    2026-10-01,Makan siang klien,makan,150000
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date

REQUIRED_COLUMNS = ["date", "description", "category", "amount"]
ALLOWED_CATEGORIES = {"makan", "transport", "akomodasi", "lainnya"}
MAX_ROWS = 1000
MAX_AMOUNT = 100_000_000  # Rp 100 juta per baris
MAX_DESCRIPTION = 120


class FileRejected(Exception):
    """File tidak bisa diproses sama sekali (header salah, kosong, terlalu besar)."""


@dataclass
class RowError:
    row: int  # nomor baris di file (header = baris 1)
    reason: str


@dataclass
class Expense:
    date: date
    description: str
    category: str
    amount: int


@dataclass
class Report:
    expenses: list[Expense] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for e in self.expenses:
            result[e.category] = result.get(e.category, 0) + e.amount
        return dict(sorted(result.items()))

    @property
    def grand_total(self) -> int:
        return sum(e.amount for e in self.expenses)

    def to_dict(self) -> dict:
        return {
            "valid_rows": len(self.expenses),
            "invalid_rows": len(self.errors),
            "totals": self.totals,
            "grand_total": self.grand_total,
            "errors": [{"row": e.row, "reason": e.reason} for e in self.errors],
        }


def parse_amount(raw: str) -> int:
    """'150000' atau '150.000' -> 150000. Tolak desimal, negatif, nol, dan teks."""
    cleaned = raw.strip().replace(".", "")
    if not cleaned.isdigit():
        raise ValueError(f"nominal tidak valid: {raw!r}")
    value = int(cleaned)
    if value <= 0:
        raise ValueError("nominal harus lebih dari 0")
    if value > MAX_AMOUNT:
        raise ValueError(f"nominal melebihi batas {MAX_AMOUNT}")
    return value


def parse_date(raw: str, today: date) -> date:
    try:
        value = date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(f"tanggal harus format YYYY-MM-DD: {raw!r}") from exc
    if value > today:
        raise ValueError("tanggal tidak boleh di masa depan")
    return value


def validate_csv(text: str, today: date | None = None) -> Report:
    today = today or date.today()
    if text.startswith("﻿"):  # BOM dari Excel
        text = text[1:]
    if not text.strip():
        raise FileRejected("file kosong")

    reader = csv.reader(io.StringIO(text))
    header = [h.strip().lower() for h in next(reader)]
    if header != REQUIRED_COLUMNS:
        raise FileRejected(f"header harus {','.join(REQUIRED_COLUMNS)}")

    report = Report()
    seen: set[tuple] = set()
    data_rows = 0
    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue  # baris kosong dilewati
        data_rows += 1
        if data_rows > MAX_ROWS:
            raise FileRejected(f"maksimal {MAX_ROWS} baris data")
        if len(row) != len(REQUIRED_COLUMNS):
            report.errors.append(RowError(line_no, "jumlah kolom tidak sesuai"))
            continue

        raw_date, description, category, raw_amount = (c.strip() for c in row)
        try:
            when = parse_date(raw_date, today)
            amount = parse_amount(raw_amount)
            if not description:
                raise ValueError("deskripsi wajib diisi")
            if len(description) > MAX_DESCRIPTION:
                raise ValueError(f"deskripsi maksimal {MAX_DESCRIPTION} karakter")
            category = category.lower()
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(f"kategori tidak dikenal: {category!r}")
        except ValueError as exc:
            report.errors.append(RowError(line_no, str(exc)))
            continue

        key = (when, description.lower(), amount)
        if key in seen:
            report.errors.append(RowError(line_no, "duplikat baris sebelumnya"))
            continue
        seen.add(key)
        report.expenses.append(Expense(when, description, category, amount))

    if data_rows == 0:
        raise FileRejected("tidak ada baris data")
    return report
