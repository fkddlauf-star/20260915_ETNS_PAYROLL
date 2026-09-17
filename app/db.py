import os

import psycopg2
import psycopg2.extras
from flask import g

DATABASE_URL = os.environ["DATABASE_URL"]


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), fetch="all"):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
        return None


def execute(sql, params=(), returning=False):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        result = cur.fetchone() if returning else None
    db.commit()
    return result


def execute_values(sql, rows, page_size=1000):
    """Bulk insert: sql is 'INSERT INTO t (a, b) VALUES %s [ON CONFLICT ...]', rows is a list
    of value tuples. One round trip (per page) instead of one per row — use this for any
    row-by-row loop that would otherwise call execute() once per record."""
    if not rows:
        return
    db = get_db()
    with db.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=page_size)
    db.commit()


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pr_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'employee',
                    employee_id TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS pr_source_files (
                    id SERIAL PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    stored_filename TEXT,
                    data_type TEXT NOT NULL,
                    period_year INTEGER,
                    period_month INTEGER,
                    department TEXT,
                    description TEXT,
                    uploaded_by INTEGER REFERENCES pr_users(id),
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    status TEXT NOT NULL DEFAULT '업로드',
                    row_count INTEGER,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS pr_source_records (
                    id SERIAL PRIMARY KEY,
                    source_file_id INTEGER REFERENCES pr_source_files(id) ON DELETE CASCADE,
                    sheet_name TEXT,
                    row_number INTEGER,
                    employee_id TEXT,
                    raw JSONB,
                    normalized JSONB
                );

                CREATE TABLE IF NOT EXISTS pr_review_rules (
                    id SERIAL PRIMARY KEY,
                    rule_type TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    key_columns TEXT NOT NULL,
                    amount_tolerance NUMERIC NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    base_template_key TEXT,
                    compare_template_key TEXT,
                    target_period_year INTEGER,
                    target_period_month INTEGER,
                    amount_field_base TEXT,
                    amount_field_compare TEXT
                );

                CREATE TABLE IF NOT EXISTS pr_review_items (
                    id SERIAL PRIMARY KEY,
                    review_type TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    period_year INTEGER,
                    period_month INTEGER,
                    employee_id TEXT,
                    employee_name TEXT,
                    department TEXT,
                    source_file_id INTEGER REFERENCES pr_source_files(id),
                    source_sheet TEXT,
                    source_row INTEGER,
                    compare_file_id INTEGER REFERENCES pr_source_files(id),
                    expected_value TEXT,
                    actual_value TEXT,
                    diff_amount NUMERIC,
                    detail TEXT,
                    status TEXT NOT NULL DEFAULT '신규',
                    assignee_id INTEGER REFERENCES pr_users(id),
                    comment TEXT,
                    requested_status TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS pr_review_history (
                    id SERIAL PRIMARY KEY,
                    review_item_id INTEGER REFERENCES pr_review_items(id) ON DELETE CASCADE,
                    changed_by INTEGER REFERENCES pr_users(id),
                    field_changed TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    comment TEXT,
                    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS pr_processing_jobs (
                    id SERIAL PRIMARY KEY,
                    source_file_id INTEGER REFERENCES pr_source_files(id),
                    status TEXT NOT NULL,
                    rows_read INTEGER DEFAULT 0,
                    rows_matched INTEGER DEFAULT 0,
                    missing_count INTEGER DEFAULT 0,
                    duplicate_count INTEGER DEFAULT 0,
                    mismatch_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0,
                    error_detail TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                ALTER TABLE pr_source_files ADD COLUMN IF NOT EXISTS stored_filename TEXT;
                ALTER TABLE pr_review_items ADD COLUMN IF NOT EXISTS requested_status TEXT;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS base_template_key TEXT;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS compare_template_key TEXT;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS target_period_year INTEGER;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS target_period_month INTEGER;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS amount_field_base TEXT;
                ALTER TABLE pr_review_rules ADD COLUMN IF NOT EXISTS amount_field_compare TEXT;

                CREATE INDEX IF NOT EXISTS idx_pr_review_items_employee ON pr_review_items(employee_id);
                CREATE INDEX IF NOT EXISTS idx_pr_review_items_status ON pr_review_items(status);
                CREATE INDEX IF NOT EXISTS idx_pr_review_items_period ON pr_review_items(period_year, period_month);
                CREATE INDEX IF NOT EXISTS idx_pr_source_records_file_emp ON pr_source_records(source_file_id, employee_id);
                """
            )
            cur.execute("SELECT COUNT(*) FROM pr_review_rules")
            if cur.fetchone()[0] == 0:
                cur.execute(
                    """
                    INSERT INTO pr_review_rules
                        (rule_type, data_type, label, key_columns, amount_tolerance, is_active,
                         base_template_key, compare_template_key, target_period_year, target_period_month,
                         amount_field_base, amount_field_compare)
                    VALUES
                        ('누락', '급여', 'HR마스터 vs 급여상세', 'employee_id', 0, TRUE,
                         'hr_master', 'salary_detail', NULL, NULL, NULL, NULL),
                        ('누락', '급여', '급여상세 vs 월별지급내역(당월)', 'employee_id', 0, TRUE,
                         'salary_detail', 'monthly_payout', 2025, 12, NULL, NULL),
                        ('중복', '급여', '월별지급내역 내 중복', 'employee_id,period_year,period_month', 0, TRUE,
                         'monthly_payout', NULL, NULL, NULL, NULL, NULL),
                        ('누락', '복리후생', 'HR마스터 vs 복리후생', 'employee_id', 0, TRUE,
                         'hr_master', 'benefits_payout', NULL, NULL, NULL, NULL),
                        ('중복', '복리후생', '복리후생 내 중복', 'employee_id', 0, TRUE,
                         'benefits_payout', NULL, NULL, NULL, NULL, NULL),
                        ('금액불일치', '복리후생', '직급별 한도 초과', '', 0, TRUE,
                         'benefits_payout', NULL, NULL, NULL, 'benefit_amount', 'benefit_limit')
                    """
                )
    finally:
        conn.close()
