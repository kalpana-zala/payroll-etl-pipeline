"""
Run the payroll ETL pipeline end to end.

    python run_pipeline.py            # incremental run (safe to repeat)
    python run_pipeline.py --full     # drop the warehouse and rebuild from scratch

Outputs (in ./output):
    payroll_warehouse.db      SQLite star schema + run log + rejects
    payroll_summary.csv       employee x pay-period payroll file (Power BI / Excel ready)
    dq_report.json            data-quality summary for this run
    dashboard_data.json       aggregates consumed by the HTML dashboard
"""
import argparse
import json
import logging

import pandas as pd

from etl import config, extract, load, transform, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("payroll_etl")


def export_outputs(conn, dq):
    summary = pd.read_sql("SELECT * FROM vw_payroll_summary ORDER BY pay_period_id, employee_id", conn)
    summary.to_csv(config.OUT_DIR / "payroll_summary.csv", index=False)
    (config.OUT_DIR / "dq_report.json").write_text(json.dumps(dq, indent=2))

    def q(sql):
        df = pd.read_sql(sql, conn).astype(object)
        return df.where(df.notna(), None).to_dict(orient="records")
    dashboard = {
        "kpis": q("""SELECT COUNT(DISTINCT employee_id) employees, COUNT(*) shifts,
                     ROUND(SUM(hours),1) hours, ROUND(SUM(overtime_hours),1) overtime_hours,
                     ROUND(SUM(gross_pay),2) gross_pay FROM fact_timesheet""")[0],
        "by_period": q("""SELECT pay_period_id, period_start, period_end,
                          ROUND(SUM(total_hours),1) hours, ROUND(SUM(overtime_hours),1) overtime_hours,
                          ROUND(SUM(ordinary_pay),2) ordinary_pay, ROUND(SUM(overtime_pay),2) overtime_pay,
                          ROUND(SUM(gross_pay),2) gross_pay
                          FROM vw_payroll_summary GROUP BY 1,2,3 ORDER BY 1"""),
        "by_client": q("""SELECT client_name, COUNT(DISTINCT employee_id) employees,
                          ROUND(SUM(total_hours),1) hours, ROUND(SUM(gross_pay),2) gross_pay
                          FROM vw_payroll_summary GROUP BY 1 ORDER BY 1"""),
        "by_shift_type": q("""SELECT shift_type, ROUND(SUM(hours),1) hours, ROUND(SUM(gross_pay),2) gross_pay
                              FROM fact_timesheet GROUP BY 1 ORDER BY 3 DESC"""),
        "top_overtime": q("""SELECT full_name, client_name, ROUND(SUM(overtime_hours),1) overtime_hours,
                             ROUND(SUM(overtime_pay),2) overtime_pay FROM vw_payroll_summary
                             GROUP BY 1,2 HAVING SUM(overtime_hours) > 0 ORDER BY 3 DESC LIMIT 8"""),
        "rejects": q("""SELECT reject_code, reject_reason, source_client, source_row, employee_id,
                        work_date, hours_raw FROM dq_rejects
                        WHERE run_id = (SELECT MAX(run_id) FROM dq_rejects) ORDER BY reject_code"""),
        "runs": q("""SELECT run_id, started_at, status, rows_extracted, rows_valid, rows_rejected,
                     rows_inserted, rows_skipped FROM etl_run_log ORDER BY run_id"""),
        "dq": dq,
    }
    (config.OUT_DIR / "dashboard_data.json").write_text(json.dumps(dashboard, indent=1, default=str))


def main(full_refresh=False):
    if full_refresh and config.DB_PATH.exists():
        config.DB_PATH.unlink()
        log.info("Full refresh: existing warehouse removed")

    conn = load.connect()
    run_id = load.start_run(conn)
    stats = {}
    try:
        log.info("EXTRACT  reading %d client sources", len(config.SOURCES))
        staged = extract.extract_all()
        employees, pay_rules, holidays = extract.extract_reference()

        log.info("VALIDATE %d staged rows", len(staged))
        clean, rejects = validate.validate(staged, employees)
        dq = validate.summary(staged, clean, rejects)
        stats.update({k: dq[k] for k in ("rows_extracted", "rows_valid", "rows_rejected")})
        log.info("VALIDATE %d valid | %d rejected | pass rate %.2f%%",
                 dq["rows_valid"], dq["rows_rejected"], dq["pass_rate_pct"])

        log.info("TRANSFORM applying shift classification, pay rules and overtime")
        facts = transform.transform(clean, employees, pay_rules, holidays)

        log.info("LOAD     writing to %s", config.DB_PATH.name)
        load.load_dimensions(conn, employees, facts)
        inserted, skipped = load.load_facts(conn, facts, run_id)
        load.load_rejects(conn, rejects, run_id)
        stats.update(rows_inserted=inserted, rows_skipped=skipped)
        conn.commit()
        log.info("LOAD     %d new rows inserted | %d already present (skipped)", inserted, skipped)

        load.finish_run(conn, run_id, "SUCCESS", stats)
        export_outputs(conn, dq)
        log.info("DONE     outputs written to %s", config.OUT_DIR)
    except Exception as exc:
        conn.rollback()
        load.finish_run(conn, run_id, "FAILED", stats, str(exc))
        log.exception("Pipeline failed")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Payroll ETL pipeline")
    parser.add_argument("--full", action="store_true", help="drop and rebuild the warehouse")
    main(full_refresh=parser.parse_args().full)
