#!/usr/bin/env python3
"""Apply supabase/schema.sql to a Postgres/Supabase database (one-time, optional).

Convenience alternative to pasting supabase/schema.sql into the Supabase SQL editor.
Needs a direct Postgres connection string and psycopg2:

    pip install psycopg2-binary
    SUPABASE_DB_URL='postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres' \
        python migrate/apply_schema.py

(Get the URI from Supabase → Project Settings → Database → Connection string → URI.)
Safe to re-run: the DDL uses `create table if not exists` + idempotent policies.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, '..', 'supabase', 'schema.sql')


def main():
    url = os.environ.get('SUPABASE_DB_URL')
    if not url:
        print('[apply_schema] SUPABASE_DB_URL not set — skipping. '
              '(Supabase → Settings → Database → Connection string → URI)')
        return
    import psycopg2  # optional dep; only needed for this convenience path
    with open(SCHEMA, encoding='utf-8') as f:
        sql = f.read()
    con = psycopg2.connect(url)
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute(sql)
    con.close()
    print('[apply_schema] schema.sql applied OK.')


if __name__ == '__main__':
    main()
