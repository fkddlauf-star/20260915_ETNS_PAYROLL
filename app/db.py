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
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
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

                CREATE INDEX IF NOT EXISTS idx_pr_review_items_employee ON pr_review_items(employee_id);
                CREATE INDEX IF NOT EXISTS idx_pr_review_items_status ON pr_review_items(status);
                CREATE INDEX IF NOT EXISTS idx_pr_review_items_period ON pr_review_items(period_year, period_month);
                CREATE INDEX IF NOT EXISTS idx_pr_source_records_file_emp ON pr_source_records(source_file_id, employee_id);
                """
            )
    finally:
        conn.close()
