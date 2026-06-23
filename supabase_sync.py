#!/usr/bin/env python3
"""Push the SQLite database to Supabase (Postgres) after each daily sync.

Supabase is the published backend/source-of-truth DB; the Cloudflare-hosted static
site is built from the same data, and the public tables are also queryable live via
Supabase's auto REST API (PostgREST) for future dynamic features.

This upserts every table by primary key (idempotent), so re-running just refreshes.
It is a no-op (clean exit) when SUPABASE_URL / SUPABASE_SERVICE_KEY are not set, so
it can live in the pipeline before credentials are configured.

Env:
  SUPABASE_URL          e.g. https://abcdefgh.supabase.co
  SUPABASE_SERVICE_KEY  service_role key (server-side only — bypasses RLS)
"""
import os
import sqlite3

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'fifa_2026.db')
URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')

# Composite-PK tables need their conflict target named explicitly for upsert.
ON_CONFLICT = {
    'external_champion_predictions': 'source_key,snapshot_date,team',
    'external_match_predictions': 'source_key,snapshot_date,match_num',
}
CHUNK = 500


def log(m):
    print(f"[supabase] {m}", flush=True)


def upsert(table, rows, on_conflict=None):
    endpoint = f"{URL}/rest/v1/{table}"
    params = {'on_conflict': on_conflict} if on_conflict else {}
    headers = {
        'apikey': KEY,
        'Authorization': f'Bearer {KEY}',
        'Content-Type': 'application/json',
        # merge-duplicates => UPSERT on the primary key / on_conflict target.
        'Prefer': 'resolution=merge-duplicates,return=minimal',
    }
    for i in range(0, len(rows), CHUNK):
        batch = rows[i:i + CHUNK]
        r = requests.post(endpoint, params=params, headers=headers, json=batch, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"{table} upsert failed {r.status_code}: {r.text[:300]}")
    return len(rows)


def main():
    if not URL or not KEY:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping (no-op).")
        return

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    total = 0
    for t in tables:
        rows = [dict(r) for r in con.execute(f'SELECT * FROM "{t}"')]
        if not rows:
            log(f"{t}: 0 rows (skip)")
            continue
        n = upsert(t, rows, ON_CONFLICT.get(t))
        total += n
        log(f"{t}: upserted {n}")
    con.close()
    log(f"done — {total} rows across {len(tables)} tables synced to Supabase.")


if __name__ == '__main__':
    main()
