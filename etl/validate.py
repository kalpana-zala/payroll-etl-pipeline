"""VALIDATE: data-quality rules. Bad rows are quarantined with a reason, never silently dropped.

Each rule is a (code, description, function) where the function returns a boolean
mask of FAILING rows. A row is rejected for the first rule it fails.
"""
import hashlib

import pandas as pd

from . import config


def add_row_hash(df):
    """Business-key hash used for de-duplication and idempotent (incremental) loads."""
    parts = df[["source_client", "employee_id", "work_date", "shift_start"]].astype(object)
    parts["hours"] = df["hours_raw"].round(4)
    key = parts.apply(lambda r: "|".join("" if pd.isna(v) else str(v) for v in r), axis=1)
    df["row_hash"] = key.map(lambda s: hashlib.sha256(s.encode()).hexdigest()[:16])
    return df


def rules(known_employees):
    return [
        ("DQ01_MISSING_EMPLOYEE_ID", "Employee ID is blank",
         lambda d: d["employee_id"].isna() | (d["employee_id"].astype(str).str.strip() == "")),
        ("DQ02_INVALID_DATE", "Work date could not be parsed",
         lambda d: d["work_date"].isna()),
        ("DQ03_UNPARSEABLE_HOURS", "Hours could not be parsed",
         lambda d: d["hours_raw"].isna()),
        ("DQ04_NEGATIVE_OR_ZERO_HOURS", f"Hours below {config.MIN_SHIFT_HOURS}",
         lambda d: d["hours_raw"] < config.MIN_SHIFT_HOURS),
        ("DQ05_EXCESSIVE_HOURS", f"Shift longer than {config.MAX_SHIFT_HOURS} hours",
         lambda d: d["hours_raw"] > config.MAX_SHIFT_HOURS),
        ("DQ06_UNKNOWN_EMPLOYEE", "Employee ID not in employee master",
         lambda d: ~d["employee_id"].isin(known_employees)),
        ("DQ07_DUPLICATE_ROW", "Exact duplicate of an earlier record",
         lambda d: d.duplicated(subset="row_hash", keep="first")),
    ]


def validate(staged, employees):
    df = add_row_hash(staged.copy())
    df["reject_code"] = None
    df["reject_reason"] = None
    for code, reason, fn in rules(set(employees["employee_id"])):
        open_rows = df["reject_code"].isna()
        failing = open_rows & fn(df).fillna(True)
        df.loc[failing, "reject_code"] = code
        df.loc[failing, "reject_reason"] = reason
    clean = df[df["reject_code"].isna()].drop(columns=["reject_code", "reject_reason"])
    rejects = df[df["reject_code"].notna()].copy()
    return clean.reset_index(drop=True), rejects.reset_index(drop=True)


def summary(staged, clean, rejects):
    by_rule = rejects.groupby("reject_code").size().rename("rows").reset_index()
    return {
        "rows_extracted": int(len(staged)),
        "rows_valid": int(len(clean)),
        "rows_rejected": int(len(rejects)),
        "pass_rate_pct": round(100 * len(clean) / max(len(staged), 1), 2),
        "rejects_by_rule": by_rule.to_dict(orient="records"),
    }
