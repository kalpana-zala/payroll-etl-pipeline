"""
Generate realistic, intentionally messy dummy source data for the payroll ETL pipeline.

Three "client" source systems export timesheets in three different formats,
exactly like real life:
  - client_a: clean CSV export from a time-tracking tool (ISO dates, decimal hours)
  - client_b: Excel-style CSV with DD/MM/YYYY dates, "7h 30m" style durations,
              extra spaces and inconsistent casing in names
  - client_c: JSON export from an API with start/end clock times instead of hours

Known data-quality problems are planted on purpose (duplicates, missing IDs,
negative or impossible hours, unknown employees) so the pipeline's
validation layer has something real to catch.

All names and numbers are fictional.
"""
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

random.seed(42)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REF = ROOT / "data" / "reference"
RAW.mkdir(parents=True, exist_ok=True)
REF.mkdir(parents=True, exist_ok=True)

FIRST = ["Aarav", "Meera", "Liam", "Sofia", "Noah", "Ava", "Kabir", "Isla", "Ethan",
         "Zara", "Lucas", "Anaya", "Oliver", "Mia", "Arjun", "Chloe", "Leo", "Riya",
         "Jack", "Emma", "Vihaan", "Grace", "Ryan", "Diya", "Henry", "Nora", "Ishaan",
         "Ella", "Samuel", "Tara"]
LAST = ["Shah", "Patel", "Smith", "Garcia", "Brown", "Wilson", "Mehta", "Taylor",
        "Nguyen", "Khan", "Martin", "Joshi", "Clark", "Lee", "Desai"]
ROLES = {
    "Support Worker":     (31.50, 1.00),
    "Senior Support":     (36.20, 1.00),
    "Team Leader":        (41.75, 1.00),
    "Admin Officer":      (29.80, 1.00),
}
CLIENTS = {"CLT-A": "Client A", "CLT-B": "Client B", "CLT-C": "Client C"}

# ---------------------------------------------------------------- reference
employees = []
eid = 1001
for client_id in CLIENTS:
    for _ in range(10):
        role = random.choice(list(ROLES))
        employees.append({
            "employee_id": f"E{eid}",
            "first_name": random.choice(FIRST),
            "last_name": random.choice(LAST),
            "client_id": client_id,
            "role": role,
            "employment_type": random.choice(["Full-time", "Part-time", "Casual"]),
            "base_rate": ROLES[role][0],
            "start_date": (date(2025, 1, 1) + timedelta(days=random.randint(0, 400))).isoformat(),
        })
        eid += 1
emp_df = pd.DataFrame(employees)
emp_df.to_csv(REF / "employees.csv", index=False)

pay_rules = pd.DataFrame([
    {"shift_type": "Weekday",  "multiplier": 1.00},
    {"shift_type": "Evening",  "multiplier": 1.15},
    {"shift_type": "Saturday", "multiplier": 1.50},
    {"shift_type": "Sunday",   "multiplier": 2.00},
    {"shift_type": "Holiday",  "multiplier": 2.50},
])
pay_rules.to_csv(REF / "pay_rules.csv", index=False)
pd.DataFrame([{"holiday_date": d} for d in ["2026-08-15", "2026-10-02", "2026-10-20"]]) \
    .to_csv(REF / "public_holidays.csv", index=False)

# ---------------------------------------------------------------- shifts
START = date(2026, 8, 3)      # Monday
WEEKS = 12                    # six fortnightly pay periods


def random_shift(day):
    start_hour = random.choice([7, 8, 9, 10, 14, 15, 16])
    length = random.choice([4, 5, 6, 7.5, 8, 8, 8, 9, 10])
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=start_hour,
                                                                   minutes=random.choice([0, 15, 30]))
    end = start + timedelta(hours=length)
    return start, end, length


def employee_shifts(emp):
    for w in range(WEEKS):
        week_start = START + timedelta(weeks=w)
        days = random.sample(range(7), k=random.choice([3, 4, 4, 5, 5]))
        for d in sorted(days):
            day = week_start + timedelta(days=d)
            yield (day, *random_shift(day))


# client A: clean CSV
rows_a = []
for emp in [e for e in employees if e["client_id"] == "CLT-A"]:
    for day, start, end, hrs in employee_shifts(emp):
        rows_a.append({"EmpID": emp["employee_id"], "WorkDate": day.isoformat(),
                       "Hours": round(hrs, 2), "Notes": ""})
# planted issues
rows_a.append(dict(rows_a[5]))                                                # exact duplicate
rows_a.append({"EmpID": "E9999", "WorkDate": "2026-09-01", "Hours": 8, "Notes": ""})  # unknown emp
rows_a.append({"EmpID": "E1003", "WorkDate": "2026-09-02", "Hours": -4, "Notes": "correction"})  # negative
pd.DataFrame(rows_a).to_csv(RAW / "client_a_timesheets.csv", index=False)

# client B: messy Excel-style export
rows_b = []
for emp in [e for e in employees if e["client_id"] == "CLT-B"]:
    for day, start, end, hrs in employee_shifts(emp):
        h, m = int(hrs), int(round((hrs - int(hrs)) * 60))
        name = f"  {emp['first_name']} {emp['last_name']} "
        rows_b.append({
            "Staff Name": random.choice([name, name.upper(), name.lower()]),
            "Staff No": emp["employee_id"],
            "Date": day.strftime("%d/%m/%Y"),
            "Duration": f"{h}h {m}m" if m else f"{h}h",
        })
rows_b.append({"Staff Name": "Ghost Entry", "Staff No": "", "Date": "05/09/2026", "Duration": "8h"})  # missing ID
rows_b.append({"Staff Name": "x", "Staff No": "E1012", "Date": "31/09/2026", "Duration": "6h"})        # invalid date
rows_b.append({"Staff Name": "y", "Staff No": "E1014", "Date": "10/09/2026", "Duration": "26h"})       # impossible hours
pd.DataFrame(rows_b).to_csv(RAW / "client_b_timesheets.csv", index=False)

# client C: API JSON with clock-in / clock-out
rows_c = []
for emp in [e for e in employees if e["client_id"] == "CLT-C"]:
    for day, start, end, hrs in employee_shifts(emp):
        rows_c.append({"worker": {"id": emp["employee_id"]},
                       "clock_in": start.isoformat(timespec="minutes"),
                       "clock_out": end.isoformat(timespec="minutes"),
                       "break_minutes": 30 if hrs >= 6 else 0})
rows_c.append({"worker": {"id": "E1025"}, "clock_in": "2026-09-08T17:00",
               "clock_out": "2026-09-08T09:00", "break_minutes": 0})               # clock-out before clock-in
with open(RAW / "client_c_timesheets.json", "w") as f:
    json.dump({"exported_at": "2026-10-26T06:00:00Z", "records": rows_c}, f, indent=1)

print(f"employees: {len(emp_df)}  |  client A rows: {len(rows_a)}  |  "
      f"client B rows: {len(rows_b)}  |  client C rows: {len(rows_c)}")
