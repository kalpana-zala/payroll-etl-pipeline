"""LOAD: write dimensions and facts into the SQLite warehouse.

Facts are inserted with INSERT OR IGNORE on row_hash, so re-running the pipeline
on the same files is safe (idempotent) and only genuinely new rows are added
(incremental load).
"""
import sqlite3
from datetime import datetime

import pandas as pd

from . import config


def connect():
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(config.SCHEMA_SQL.read_text())
    return conn


def start_run(conn):
    cur = conn.execute("INSERT INTO etl_run_log (started_at, status) VALUES (?, 'RUNNING')",
                       (datetime.now().isoformat(timespec="seconds"),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status, stats, message=""):
    conn.execute("""UPDATE etl_run_log SET finished_at=?, status=?, rows_extracted=?, rows_valid=?,
                    rows_rejected=?, rows_inserted=?, rows_skipped=?, message=? WHERE run_id=?""",
                 (datetime.now().isoformat(timespec="seconds"), status,
                  stats.get("rows_extracted"), stats.get("rows_valid"), stats.get("rows_rejected"),
                  stats.get("rows_inserted"), stats.get("rows_skipped"), message, run_id))
    conn.commit()


def load_dimensions(conn, employees, facts):
    clients = pd.DataFrame([{"client_id": k, "client_name": f"Client {k[-1]}", "source_format": v["format"]}
                            for k, v in config.SOURCES.items()])
    conn.executemany("INSERT OR REPLACE INTO dim_client VALUES (?,?,?)", clients.itertuples(index=False))

    emp = employees.assign(full_name=employees["first_name"] + " " + employees["last_name"])
    conn.executemany("INSERT OR REPLACE INTO dim_employee VALUES (?,?,?,?,?,?,?)",
                     emp[["employee_id", "full_name", "client_id", "role", "employment_type",
                          "base_rate", "start_date"]].itertuples(index=False))

    periods = facts[["pay_period_id", "pay_period_start", "pay_period_end"]].drop_duplicates()
    conn.executemany("INSERT OR IGNORE INTO dim_pay_period VALUES (?,?,?)",
                     [(p, str(s), str(e)) for p, s, e in periods.itertuples(index=False)])


def load_facts(conn, facts, run_id):
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in facts.itertuples(index=False):
        rows.append((r.row_hash, r.source_client, int(r.source_row), r.employee_id, str(r.work_date),
                     r.iso_week, r.pay_period_id,
                     None if pd.isna(r.shift_start) else str(r.shift_start),
                     None if pd.isna(r.shift_end) else str(r.shift_end),
                     r.shift_type, float(r.multiplier), float(r.hours), float(r.overtime_hours),
                     float(r.base_rate), float(r.ordinary_pay), float(r.overtime_pay),
                     float(r.gross_pay), run_id, now))
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO fact_timesheet VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    inserted = conn.total_changes - before
    return inserted, len(rows) - inserted


def load_rejects(conn, rejects, run_id):
    conn.executemany(
        """INSERT INTO dq_rejects (run_id, source_client, source_row, employee_id, work_date,
           hours_raw, reject_code, reject_reason) VALUES (?,?,?,?,?,?,?,?)""",
        [(run_id, r.source_client, int(r.source_row),
          None if pd.isna(r.employee_id) else r.employee_id,
          None if pd.isna(r.work_date) else str(r.work_date),
          None if pd.isna(r.hours_raw) else float(r.hours_raw),
          r.reject_code, r.reject_reason) for r in rejects.itertuples(index=False)])
