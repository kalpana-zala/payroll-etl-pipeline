-- Payroll data warehouse: star schema (SQLite dialect, portable to SQL Server / BigQuery)

CREATE TABLE IF NOT EXISTS dim_client (
    client_id       TEXT PRIMARY KEY,
    client_name     TEXT NOT NULL,
    source_format   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_employee (
    employee_id     TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    client_id       TEXT NOT NULL REFERENCES dim_client(client_id),
    role            TEXT,
    employment_type TEXT,
    base_rate       REAL NOT NULL,
    start_date      TEXT
);

CREATE TABLE IF NOT EXISTS dim_pay_period (
    pay_period_id   TEXT PRIMARY KEY,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_timesheet (
    row_hash        TEXT PRIMARY KEY,          -- business-key hash => idempotent upserts
    source_client   TEXT NOT NULL REFERENCES dim_client(client_id),
    source_row      INTEGER,
    employee_id     TEXT NOT NULL REFERENCES dim_employee(employee_id),
    work_date       TEXT NOT NULL,
    iso_week        TEXT NOT NULL,
    pay_period_id   TEXT NOT NULL REFERENCES dim_pay_period(pay_period_id),
    shift_start     TEXT,
    shift_end       TEXT,
    shift_type      TEXT NOT NULL,
    multiplier      REAL NOT NULL,
    hours           REAL NOT NULL,
    overtime_hours  REAL NOT NULL DEFAULT 0,
    base_rate       REAL NOT NULL,
    ordinary_pay    REAL NOT NULL,
    overtime_pay    REAL NOT NULL DEFAULT 0,
    gross_pay       REAL NOT NULL,
    load_run_id     INTEGER NOT NULL,
    loaded_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fact_emp_period ON fact_timesheet (employee_id, pay_period_id);

CREATE TABLE IF NOT EXISTS dq_rejects (
    reject_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    source_client   TEXT,
    source_row      INTEGER,
    employee_id     TEXT,
    work_date       TEXT,
    hours_raw       REAL,
    reject_code     TEXT NOT NULL,
    reject_reason   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,
    rows_extracted  INTEGER,
    rows_valid      INTEGER,
    rows_rejected   INTEGER,
    rows_inserted   INTEGER,
    rows_skipped    INTEGER,
    message         TEXT
);

-- Reporting view: one row per employee per pay period (what payroll actually processes)
CREATE VIEW IF NOT EXISTS vw_payroll_summary AS
SELECT
    f.pay_period_id,
    p.period_start,
    p.period_end,
    e.client_id,
    c.client_name,
    f.employee_id,
    e.full_name,
    e.role,
    COUNT(*)                         AS shifts,
    ROUND(SUM(f.hours), 2)           AS total_hours,
    ROUND(SUM(f.overtime_hours), 2)  AS overtime_hours,
    ROUND(SUM(f.ordinary_pay), 2)    AS ordinary_pay,
    ROUND(SUM(f.overtime_pay), 2)    AS overtime_pay,
    ROUND(SUM(f.gross_pay), 2)       AS gross_pay
FROM fact_timesheet f
JOIN dim_employee   e ON e.employee_id  = f.employee_id
JOIN dim_client     c ON c.client_id    = e.client_id
JOIN dim_pay_period p ON p.pay_period_id = f.pay_period_id
GROUP BY f.pay_period_id, p.period_start, p.period_end, e.client_id, c.client_name,
         f.employee_id, e.full_name, e.role;
