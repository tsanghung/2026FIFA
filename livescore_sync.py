#!/usr/bin/env python3
"""livescore_sync.py — pull FINAL match scores from 365Scores into `matches`.

Why
---
sync_fifa.py sources scores from Wikipedia, which is often hours behind, so the
site shows "VS" long after a match ends. 365Scores (already consumed for xG in
threefivescores_sync.py) publishes finals much sooner. This module reuses the
exact same finished-game discovery as the xG sync, then reads each game's score
from the game-detail endpoint and writes it back (status -> 'Completed', score,
home_goals, away_goals) so ended matches stop showing "VS".

Only FINAL results are written, and live games (a running match clock in the
status) are skipped, so an in-progress score can never pollute Elo / accuracy /
predictions. Must run AFTER sync_fifa.py, which rebuilds `matches` from Wikipedia
each run (otherwise the rebuild would wipe what we wrote).

Run with --dry-run to print decisions without writing.
"""
import re
import sys
import sqlite3

# Reuse the proven 365Scores plumbing + the orientation-aware fixture matcher.
from threefivescores_sync import (
    fetch_json, scan_current_feed, find_all_wc_finished_games,
    match_fixture, BASE, COMMON,
)

DB_PATH = 'fifa_2026.db'
DASH = '–'  # en dash, matching the score format Wikipedia-sourced rows use
LIVE_CLOCK = re.compile(r"\d+\s*'")  # e.g. "47'" -> match is in progress


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


def run(dry_run=False):
    from sync_fifa import normalize_team_name as N

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Fixtures that still lack a final result -> candidates to fill.
    need = {}
    for mn, ht, at, status in cur.execute(
            "SELECT match_num, home_team, away_team, status FROM matches"):
        if status != 'Completed':
            need[frozenset((N(ht), N(at)))] = mn

    # Finished WC game ids: current window + competition-history backfill (same
    # discovery the xG sync uses, so we get exactly the games it gets).
    ids, comp_ids = scan_current_feed()
    for bg in find_all_wc_finished_games(comp_ids):
        if frozenset((N(bg['home']), N(bg['away']))) in need:
            ids.add(bg['id'])
    log(f"{len(ids)} candidate finished WC game(s): {sorted(ids)}")

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
        row = cur.execute("SELECT score, home_goals, away_goals, status "
                          "FROM matches WHERE match_num=?", (mn,)).fetchone()
        if row and row[0] == new_score and row[1] == home_g \
                and row[2] == away_g and row[3] == 'Completed':
            continue
        tag = 'DRY' if dry_run else 'SET'
        log(f"    -> [{tag}] #{mn} {new_score} Completed"
            f"{' (swapped)' if swapped else ''}")
        changed += 1
        if not dry_run:
            cur.execute("UPDATE matches SET score=?, home_goals=?, away_goals=?, "
                        "status='Completed' WHERE match_num=?",
                        (new_score, home_g, away_g, mn))

    if dry_run:
        log(f"dry-run: {changed} match(es) would change; no writes.")
        conn.close()
        return

    conn.commit()
    log(f"{changed} match(es) updated from 365Scores.")
    if changed:
        log("recomputing Elo & predictions to reflect new final results...")
        from sync_fifa import reset_and_recalculate_all_elo_and_predictions
        reset_and_recalculate_all_elo_and_predictions()
        log("done.")
    conn.close()


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv)
