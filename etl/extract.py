"""EXTRACT: read each client's raw export and map it to one common staging shape.

Every source is normalised to these columns:
    source_client, source_row, employee_id, work_date, shift_start, shift_end,
    break_minutes, hours_raw

Nothing is dropped or fixed here; parsing failures are kept as nulls so the
validation step can reject them with a clear reason.
"""
import json
import re

import pandas as pd

from . import config

STAGING_COLUMNS = ["source_client", "source_row", "employee_id", "work_date",
                   "shift_start", "shift_end", "break_minutes", "hours_raw"]


def _parse_duration(text):
    """'7h 30m' -> 7.5, '9h' -> 9.0, anything unparseable -> None."""
    if not isinstance(text, str):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*h(?:\s*(\d+)\s*m)?\s*", text.lower())
    if not m:
        return None
    return int(m.group(1)) + int(m.group(2) or 0) / 60


def extract_csv_decimal_hours(path, client_id):
    df = pd.read_csv(path, dtype=str)
    out = pd.DataFrame({
        "employee_id": df["EmpID"].str.strip(),
        "work_date": pd.to_datetime(df["WorkDate"], format="%Y-%m-%d", errors="coerce").dt.date,
        "hours_raw": pd.to_numeric(df["Hours"], errors="coerce"),
    })
    return out


def extract_csv_duration_text(path, client_id):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    out = pd.DataFrame({
        "employee_id": df["Staff No"].str.strip().replace("", None),
        "work_date": pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce").dt.date,
        "hours_raw": df["Duration"].map(_parse_duration),
    })
    return out


def extract_json_clock_times(path, client_id):
    with open(path) as f:
        records = json.load(f)["records"]
    df = pd.json_normalize(records)
    start = pd.to_datetime(df["clock_in"], errors="coerce")
    end = pd.to_datetime(df["clock_out"], errors="coerce")
    brk = pd.to_numeric(df["break_minutes"], errors="coerce").fillna(0)
    out = pd.DataFrame({
        "employee_id": df["worker.id"].str.strip(),
        "work_date": start.dt.date,
        "shift_start": start,
        "shift_end": end,
        "break_minutes": brk,
        "hours_raw": (end - start).dt.total_seconds() / 3600 - brk / 60,
    })
    return out


EXTRACTORS = {
    "csv_decimal_hours": extract_csv_decimal_hours,
    "csv_duration_text": extract_csv_duration_text,
    "json_clock_times": extract_json_clock_times,
}


def extract_all():
    frames = []
    for client_id, spec in config.SOURCES.items():
        path = config.RAW_DIR / spec["file"]
        df = EXTRACTORS[spec["format"]](path, client_id)
        df["source_client"] = client_id
        df["source_row"] = range(1, len(df) + 1)
        frames.append(df)
    staged = pd.concat(frames, ignore_index=True)
    for col in STAGING_COLUMNS:
        if col not in staged:
            staged[col] = None
    return staged[STAGING_COLUMNS]


def extract_reference():
    employees = pd.read_csv(config.REF_DIR / "employees.csv")
    pay_rules = pd.read_csv(config.REF_DIR / "pay_rules.csv")
    holidays = pd.to_datetime(pd.read_csv(config.REF_DIR / "public_holidays.csv")["holiday_date"]).dt.date
    return employees, pay_rules, set(holidays)
