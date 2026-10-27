"""Central configuration: paths, business rules and validation thresholds."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
REF_DIR = ROOT / "data" / "reference"
OUT_DIR = ROOT / "output"
DB_PATH = OUT_DIR / "payroll_warehouse.db"
SCHEMA_SQL = ROOT / "sql" / "schema.sql"

# Business rules
PAY_PERIOD_ANCHOR = date(2026, 8, 3)    # first Monday of the fortnightly pay calendar
PAY_PERIOD_DAYS = 14
WEEKLY_OT_THRESHOLD = 38.0              # hours per week before overtime applies
OT_PREMIUM = 0.5                        # extra multiple of base rate for overtime hours
EVENING_START_HOUR = 14                 # shifts starting at/after this hour and ending after 20:00
EVENING_END_HOUR = 20

# Validation thresholds
MIN_SHIFT_HOURS = 0.25
MAX_SHIFT_HOURS = 16.0

# Source system registry: one entry per client export
SOURCES = {
    "CLT-A": {"file": "client_a_timesheets.csv", "format": "csv_decimal_hours"},
    "CLT-B": {"file": "client_b_timesheets.csv", "format": "csv_duration_text"},
    "CLT-C": {"file": "client_c_timesheets.json", "format": "json_clock_times"},
}
