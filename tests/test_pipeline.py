"""Unit tests for the parsing, validation and payroll rules.  Run:  python -m pytest -q"""
from datetime import date, datetime

import pandas as pd

from etl import config, extract, transform, validate


def test_duration_parser():
    assert extract._parse_duration("7h 30m") == 7.5
    assert extract._parse_duration("9h") == 9
    assert extract._parse_duration(" 8H 15M ") == 8.25
    assert extract._parse_duration("eight hours") is None


def test_pay_period_boundaries():
    assert transform.pay_period(date(2026, 8, 3))[0] == "PP01"
    assert transform.pay_period(date(2026, 8, 16))[0] == "PP01"
    assert transform.pay_period(date(2026, 8, 17))[0] == "PP02"


def test_shift_classification():
    holidays = {date(2026, 10, 2)}
    row = lambda d, s=None, e=None: {"work_date": d, "shift_start": s, "shift_end": e}
    assert transform.classify_shift(row(date(2026, 10, 2)), holidays) == "Holiday"
    assert transform.classify_shift(row(date(2026, 10, 4)), holidays) == "Sunday"
    assert transform.classify_shift(row(date(2026, 10, 3)), holidays) == "Saturday"
    assert transform.classify_shift(row(date(2026, 10, 6), pd.Timestamp("2026-10-06 15:00"),
                                        pd.Timestamp("2026-10-06 23:00")), holidays) == "Evening"
    assert transform.classify_shift(row(date(2026, 10, 6)), holidays) == "Weekday"


def _staged(rows):
    df = pd.DataFrame(rows)
    for c in extract.STAGING_COLUMNS:
        if c not in df:
            df[c] = None
    return df[extract.STAGING_COLUMNS]


def test_validation_rejects_each_rule():
    employees = pd.DataFrame({"employee_id": ["E1"]})
    base = {"source_client": "CLT-A", "work_date": date(2026, 9, 1)}
    staged = _staged([
        {**base, "source_row": 1, "employee_id": "E1", "hours_raw": 8},     # valid
        {**base, "source_row": 2, "employee_id": "E1", "hours_raw": 8},     # duplicate
        {**base, "source_row": 3, "employee_id": None, "hours_raw": 8},     # missing id
        {**base, "source_row": 4, "employee_id": "E1", "hours_raw": -2},    # negative
        {**base, "source_row": 5, "employee_id": "E1", "hours_raw": 30},    # excessive
        {**base, "source_row": 6, "employee_id": "E404", "hours_raw": 5},   # unknown
    ])
    clean, rejects = validate.validate(staged, employees)
    assert len(clean) == 1
    assert set(rejects["reject_code"]) == {"DQ07_DUPLICATE_ROW", "DQ01_MISSING_EMPLOYEE_ID",
                                           "DQ04_NEGATIVE_OR_ZERO_HOURS", "DQ05_EXCESSIVE_HOURS",
                                           "DQ06_UNKNOWN_EMPLOYEE"}


def test_weekly_overtime_only_above_threshold():
    employees = pd.DataFrame({"employee_id": ["E1"], "base_rate": [30.0], "role": ["X"]})
    pay_rules = pd.DataFrame({"shift_type": ["Weekday"], "multiplier": [1.0]})
    days = [date(2026, 9, 7 + i) for i in range(5)]  # Mon-Fri, 5 x 9h = 45h
    clean = validate.add_row_hash(_staged([
        {"source_client": "CLT-A", "source_row": i, "employee_id": "E1", "work_date": d, "hours_raw": 9}
        for i, d in enumerate(days)]))
    facts = transform.transform(clean, employees, pay_rules, set())
    assert facts["overtime_hours"].sum() == 45 - config.WEEKLY_OT_THRESHOLD
    assert facts["overtime_pay"].sum() == round((45 - config.WEEKLY_OT_THRESHOLD) * 30 * config.OT_PREMIUM, 2)
