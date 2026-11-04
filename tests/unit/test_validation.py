"""Unit test aturan validasi CSV.

Teknik yang dipakai (sama seperti bikin test case manual):
- Equivalence partitioning: satu wakil per kelompok input (valid / tidak valid).
- Boundary value: nilai di tepi batas (0, 1, MAX, MAX+1).
- Parametrize: satu fungsi test, banyak data -> tiap data jadi test case sendiri di report.
"""

from datetime import date

import pytest

from app.validation import (
    MAX_AMOUNT,
    MAX_DESCRIPTION,
    MAX_ROWS,
    FileRejected,
    parse_amount,
    parse_date,
    validate_csv,
)

TODAY = date(2026, 11, 4)  # tanggal tetap supaya test tidak berubah hasil tiap hari
HEADER = "date,description,category,amount\n"


def csv_of(*rows: str) -> str:
    return HEADER + "\n".join(rows) + "\n"


# ---------- parse_amount ----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),                        # batas bawah valid
        ("150000", 150000),
        ("250.000", 250000),             # format ribuan ala Indonesia
        (" 75000 ", 75000),              # spasi di pinggir
        (str(MAX_AMOUNT), MAX_AMOUNT),   # batas atas valid
    ],
)
def test_parse_amount_valid(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["0", "-5000", "12,5", "abc", "", str(MAX_AMOUNT + 1), "1e5"],
    ids=["nol", "negatif", "desimal", "teks", "kosong", "lewat-batas", "notasi-ilmiah"],
)
def test_parse_amount_invalid(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


# ---------- parse_date ----------

def test_parse_date_today_is_allowed():
    assert parse_date("2026-11-04", TODAY) == TODAY


def test_parse_date_future_is_rejected():
    with pytest.raises(ValueError, match="masa depan"):
        parse_date("2026-11-05", TODAY)


@pytest.mark.parametrize("raw", ["04-11-2026", "2026/11/04", "2026-02-30", "kemarin"])
def test_parse_date_bad_format(raw):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_date(raw, TODAY)


# ---------- validate_csv: level file ----------

@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "kosong"),
        ("   \n  ", "kosong"),
        ("tanggal,keterangan,kategori,jumlah\n2026-10-01,a,makan,1\n", "header"),
        (HEADER, "tidak ada baris data"),
        (HEADER + "\n\n", "tidak ada baris data"),
    ],
    ids=["kosong", "spasi-saja", "header-salah", "header-saja", "baris-kosong-saja"],
)
def test_file_rejected(text, message):
    with pytest.raises(FileRejected, match=message):
        validate_csv(text, today=TODAY)


def test_header_is_case_insensitive_and_bom_tolerant():
    text = "﻿Date, Description ,CATEGORY,amount\n2026-10-01,Kopi,makan,10000\n"
    report = validate_csv(text, today=TODAY)
    assert report.grand_total == 10000


def test_max_rows_boundary():
    row = "2026-10-01,Item {i},lainnya,1000"
    at_limit = csv_of(*(row.format(i=i) for i in range(MAX_ROWS)))
    assert len(validate_csv(at_limit, today=TODAY).expenses) == MAX_ROWS

    over = csv_of(*(row.format(i=i) for i in range(MAX_ROWS + 1)))
    with pytest.raises(FileRejected, match="maksimal"):
        validate_csv(over, today=TODAY)


# ---------- validate_csv: level baris ----------

def test_happy_path_totals_per_category():
    report = validate_csv(
        csv_of(
            "2026-10-01,Makan siang,makan,150000",
            "2026-10-02,Taksi,transport,250.000",
            "2026-10-03,Kopi,MAKAN,50000",
        ),
        today=TODAY,
    )
    assert report.errors == []
    assert report.totals == {"makan": 200000, "transport": 250000}
    assert report.grand_total == 450000


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ("2026-10-01,Kopi,makan", "jumlah kolom"),
        ("2026-10-01,,makan,1000", "deskripsi wajib"),
        (f"2026-10-01,{'x' * (MAX_DESCRIPTION + 1)},makan,1000", "deskripsi maksimal"),
        ("2026-10-01,Nonton,hiburan,1000", "kategori tidak dikenal"),
        ("2026-12-01,Besok,makan,1000", "masa depan"),
    ],
    ids=["kolom-kurang", "deskripsi-kosong", "deskripsi-kepanjangan", "kategori-asing",
         "tanggal-depan"],
)
def test_row_level_errors_are_reported_with_row_number(row, reason):
    report = validate_csv(csv_of("2026-10-01,Valid,makan,1000", row), today=TODAY)
    assert len(report.expenses) == 1          # baris valid tetap dihitung
    assert len(report.errors) == 1
    assert report.errors[0].row == 3          # header=1, baris valid=2, baris rusak=3
    assert reason in report.errors[0].reason


def test_description_exactly_at_limit_is_ok():
    report = validate_csv(csv_of(f"2026-10-01,{'x' * MAX_DESCRIPTION},makan,1000"), today=TODAY)
    assert report.errors == []


def test_duplicate_detection_ignores_case_but_not_amount():
    report = validate_csv(
        csv_of(
            "2026-10-01,Kopi,makan,10000",
            "2026-10-01,KOPI,makan,10000",   # duplikat (beda huruf besar saja)
            "2026-10-01,Kopi,makan,12000",   # bukan duplikat (nominal beda)
        ),
        today=TODAY,
    )
    assert [e.row for e in report.errors] == [3]
    assert report.grand_total == 22000


def test_to_dict_shape_is_stable():
    """Bentuk output ini 'kontrak' yang dibaca UI & API. Kalau berubah, test ini teriak."""
    data = validate_csv(csv_of("2026-10-01,Kopi,makan,10000"), today=TODAY).to_dict()
    assert set(data) == {"valid_rows", "invalid_rows", "totals", "grand_total", "errors"}
