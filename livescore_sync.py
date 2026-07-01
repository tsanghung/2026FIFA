#!/usr/bin/env python3
"""livescore_sync.py — 365Scores is the AUTHORITATIVE source for final scores.

Authority model
---------------
Wikipedia (sync_fifa.py) is the source of truth for SCHEDULE (date/time/venue)
and KNOCKOUT BRACKET ADVANCEMENT (which two teams meet in each R32/R16/... slot),
because that's editorial/structural information 365Scores doesn't organize the
same way. But Wikipedia's raw score text is community-edited and can be delayed,
transiently wrong, or carry inconsistent annotations (e.g. "1–1 (a.e.t.)"), so it
is NOT trusted as the final word on a match's RESULT.

365Scores is free, structured, and (already used for xG in threefivescores_sync.py)
publishes finals reliably. This module re-derives the authoritative score/status
for every fixture 365Scores can identify and OVERWRITES whatever sync_fifa.py just
wrote from Wikipedia — every run, since sync_fifa.py's `force_recreate` rebuilds
`matches` from a fresh Wikipedia scrape each time this pipeline runs, discarding
any correction from the previous run. Wikipedia's value is used only as a
fallback for fixtures 365Scores has no data for (e.g. a very old/obscure game it
doesn't track).

To bound API cost as the tournament progresses, we re-validate against 365Scores:
  1. Any fixture not yet marked Completed (always — it needs a result).
  2. Any fixture completed within the last RECHECK_DAYS days, EVEN IF Wikipedia
     already marked it Completed — this is the window where a transient wiki
     error/edit-lag is most likely, and where 365Scores is most likely to have
     the game in its "current" rolling feed anyway.
Older, long-settled fixtures are not re-queried every run (Wikipedia's text for
those has had days to stabilize, and 365Scores already confirmed it while it was
still "recent"), so cost stays bounded rather than growing with the tournament.

A `score_source` column records provenance ('365scores' vs the implicit
Wikipedia default) so the site can show which fixtures were cross-validated.

Live games (a running match clock in the status) are always skipped, so an
in-progress score can never pollute Elo / accuracy / predictions. Must run AFTER
sync_fifa.py (see rationale above).

Run with --dry-run to print decisions without writing.
"""
import re
import sys
import sqlite3
from datetime import datetime, timedelta, timezone

# Reuse the proven 365Scores plumbing + the orientation-aware fixture matcher.
from threefivescores_sync import (
    fetch_json, scan_current_feed, find_all_wc_finished_games,
    match_fixture, BASE, COMMON,
)

DB_PATH = 'fifa_2026.db'
DASH = '–'  # en dash, matching the score format Wikipedia-sourced rows use
LIVE_CLOCK = re.compile(r"\d+\s*'")  # e.g. "47'" -> match is in progress
RECHECK_DAYS = 3  # re-validate already-Completed fixtures for this many days


def log(msg):
    print(f"[livescore] {msg}", flush=True)


def looks_live(g):
    t = str(g.get('statusText', '')).lower()
    return bool(LIVE_CLOCK.search(t)) or 'half' in t or 'live' in t


def score_of(comp):
    """Integer score for a competitor, or None when unavailable (365 uses -1)."""
    try:
        f = float(comp.get('score'))
    except (TypeError, ValueError):
        return None
    return int(round(f)) if f >= 0 else None


def ensure_schema(cur):
    cols = {r[1] for r in cur.execute('PRAGMA table_info(matches)')}
    if 'score_source' not in cols:
        cur.execute('ALTER TABLE matches ADD COLUMN score_source TEXT')


def _is_recent(date_str, today):
    try:
        d = datetime.strptime((date_str or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        return False
    return 0 <= (today - d).days <= RECHECK_DAYS


def run(dry_run=False):
    from sync_fifa import normalize_team_name as N

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ensure_schema(cur)
    conn.commit()

    today = datetime.now(timezone.utc).date()

    # Candidates: fixtures still lacking a result, OR completed recently enough
    # that a transient Wikipedia error/lag could still exist (see module docstring).
    need = {}
    for mn, ht, at, status, date in cur.execute(
            "SELECT match_num, home_team, away_team, status, date FROM matches"):
        if status != 'Completed' or _is_recent(date, today):
            need[frozenset((N(ht), N(at)))] = mn

    # Finished WC game ids: current window (unconditional — always the freshest,
    # most likely-to-be-wrong-on-wiki window) + competition-history backfill
    # restricted to `need` so cost stays bounded (same discovery the xG sync uses).
    ids, comp_ids = scan_current_feed()
    for bg in find_all_wc_finished_games(comp_ids):
        if frozenset((N(bg['home']), N(bg['away']))) in need:
            ids.add(bg['id'])
    log(f"{len(ids)} candidate finished WC game(s) "
        f"(re-check window: {RECHECK_DAYS}d): {sorted(ids)}")

    changed = 0
    for gid in sorted(ids):
        try:
            g = fetch_json(f'{BASE}/game/?{COMMON}&gameId={gid}').get('game', {})
        except Exception as e:
            log(f"  game {gid} fetch failed: {e}")
            continue
        home = g.get('homeCompetitor', {}) or {}
        away = g.get('awayCompetitor', {}) or {}
        hn, an = home.get('name'), away.get('name')
        hs, as_ = score_of(home), score_of(away)
        # Diagnostic: always log what the feed actually returned for this game.
        log(f"  game {gid}: {hn} {hs}-{as_} {an} "
            f"status={g.get('statusText')!r} grp={g.get('statusGroup')}")
        if not hn or not an or hs is None or as_ is None:
            continue
        if looks_live(g):
            log("    -> in progress, skipping")
            continue
        parsed = {'home_name': hn, 'away_name': an,
                  'date': (g.get('startTime') or '')[:10]}
        m = match_fixture(cur, parsed, N)
        if m is None:
            log("    -> NO DB FIXTURE MATCH")
            continue
        mn, swapped = m
        home_g, away_g = (as_, hs) if swapped else (hs, as_)
        new_score = f"{home_g}{DASH}{away_g}"
        row = cur.execute("SELECT score, home_goals, away_goals, status, score_source "
                          "FROM matches WHERE match_num=?", (mn,)).fetchone()
        if row and row[0] == new_score and row[1] == home_g \
                and row[2] == away_g and row[3] == 'Completed' \
                and row[4] == '365scores':
            continue
        tag = 'DRY' if dry_run else 'SET'
        log(f"    -> [{tag}] #{mn} {new_score} Completed (365scores-verified)"
            f"{' (swapped)' if swapped else ''}")
        changed += 1
        if not dry_run:
            cur.execute("UPDATE matches SET score=?, home_goals=?, away_goals=?, "
                        "status='Completed', score_source='365scores' "
                        "WHERE match_num=?",
                        (new_score, home_g, away_g, mn))

    if dry_run:
        log(f"dry-run: {changed} match(es) would change; no writes.")
        conn.close()
        return

    conn.commit()
    log(f"{changed} match(es) confirmed/updated from 365Scores.")
    if changed:
        log("recomputing Elo & predictions to reflect new final results...")
        from sync_fifa import reset_and_recalculate_all_elo_and_predictions
        reset_and_recalculate_all_elo_and_predictions()
        log("done.")
    conn.close()


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv)
