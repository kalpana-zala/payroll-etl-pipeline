-- Example analysis queries on the payroll warehouse

-- 1. Payroll cost per pay period, with overtime share
SELECT pay_period_id,
       ROUND(SUM(gross_pay), 2)                                   AS gross_pay,
       ROUND(100.0 * SUM(overtime_pay) / SUM(gross_pay), 2)       AS overtime_pct
FROM vw_payroll_summary
GROUP BY pay_period_id
ORDER BY pay_period_id;

-- 2. Period-over-period change in gross pay per client (window function)
WITH p AS (
    SELECT client_name, pay_period_id, SUM(gross_pay) AS gross_pay
    FROM vw_payroll_summary GROUP BY 1, 2
)
SELECT client_name, pay_period_id, ROUND(gross_pay, 2) AS gross_pay,
       ROUND(gross_pay - LAG(gross_pay) OVER (PARTITION BY client_name ORDER BY pay_period_id), 2) AS change_vs_prev
FROM p
ORDER BY client_name, pay_period_id;

-- 3. Employees working above 38 hours in a week (fatigue / cost risk)
SELECT f.employee_id, e.full_name, f.iso_week, ROUND(SUM(f.hours), 1) AS week_hours
FROM fact_timesheet f JOIN dim_employee e USING (employee_id)
GROUP BY 1, 2, 3
HAVING SUM(f.hours) > 38
ORDER BY week_hours DESC;

-- 4. Penalty-rate exposure: share of pay from weekend / holiday shifts
SELECT shift_type, ROUND(SUM(hours), 1) AS hours, ROUND(SUM(gross_pay), 2) AS gross_pay,
       ROUND(100.0 * SUM(gross_pay) / (SELECT SUM(gross_pay) FROM fact_timesheet), 1) AS pct_of_pay
FROM fact_timesheet
GROUP BY shift_type
ORDER BY gross_pay DESC;

-- 5. Data-quality trend across pipeline runs
SELECT run_id, started_at, rows_extracted, rows_rejected,
       ROUND(100.0 * rows_valid / rows_extracted, 2) AS pass_rate_pct, rows_inserted, rows_skipped
FROM etl_run_log
ORDER BY run_id;
