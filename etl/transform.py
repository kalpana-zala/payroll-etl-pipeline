"""TRANSFORM: apply payroll business rules to validated timesheet rows.

Steps
  1. Classify each shift (Weekday / Evening / Saturday / Sunday / Holiday)
  2. Join employee master + pay rules -> ordinary pay per shift
  3. Assign ISO week and fortnightly pay period
  4. Calculate weekly overtime above the threshold and its premium
"""
from datetime import timedelta

import pandas as pd

from . import config


def classify_shift(row, holidays):
    d = row["work_date"]
    if d in holidays:
        return "Holiday"
    if d.weekday() == 6:
        return "Sunday"
    if d.weekday() == 5:
        return "Saturday"
    start, end = row["shift_start"], row["shift_end"]
    if pd.notna(start) and pd.notna(end):
        if start.hour >= config.EVENING_START_HOUR and (end.hour >= config.EVENING_END_HOUR or end.date() > start.date()):
            return "Evening"
    return "Weekday"


def pay_period(d):
    idx = (d - config.PAY_PERIOD_ANCHOR).days // config.PAY_PERIOD_DAYS
    start = config.PAY_PERIOD_ANCHOR + timedelta(days=idx * config.PAY_PERIOD_DAYS)
    end = start + timedelta(days=config.PAY_PERIOD_DAYS - 1)
    return f"PP{idx + 1:02d}", start, end


def transform(clean, employees, pay_rules, holidays):
    df = clean.copy()
    df["hours"] = df["hours_raw"].round(2)
    df["shift_type"] = df.apply(classify_shift, axis=1, holidays=holidays)

    df = df.merge(employees[["employee_id", "base_rate", "role"]], on="employee_id", how="left")
    df = df.merge(pay_rules, on="shift_type", how="left")
    df["ordinary_pay"] = (df["hours"] * df["base_rate"] * df["multiplier"]).round(2)

    pp = df["work_date"].map(pay_period)
    df["pay_period_id"] = pp.map(lambda x: x[0])
    df["pay_period_start"] = pp.map(lambda x: x[1])
    df["pay_period_end"] = pp.map(lambda x: x[2])
    iso = pd.to_datetime(df["work_date"]).dt.isocalendar()
    df["iso_week"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)

    # Weekly overtime: hours above threshold earn a premium on base rate,
    # allocated to the latest shifts of the week (the ones that crossed the line).
    df = df.sort_values(["employee_id", "work_date", "shift_start"], na_position="first")
    df["cum_week_hours"] = df.groupby(["employee_id", "iso_week"])["hours"].cumsum()
    prev = df["cum_week_hours"] - df["hours"]
    df["overtime_hours"] = (df["cum_week_hours"].clip(lower=config.WEEKLY_OT_THRESHOLD)
                            - prev.clip(lower=config.WEEKLY_OT_THRESHOLD)).round(2)
    df["overtime_pay"] = (df["overtime_hours"] * df["base_rate"] * config.OT_PREMIUM).round(2)
    df["gross_pay"] = (df["ordinary_pay"] + df["overtime_pay"]).round(2)

    keep = ["row_hash", "source_client", "source_row", "employee_id", "work_date", "iso_week",
            "pay_period_id", "pay_period_start", "pay_period_end", "shift_start", "shift_end",
            "shift_type", "multiplier", "hours", "overtime_hours", "base_rate",
            "ordinary_pay", "overtime_pay", "gross_pay"]
    return df[keep].reset_index(drop=True)
