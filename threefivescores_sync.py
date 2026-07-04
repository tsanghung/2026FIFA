#!/usr/bin/env python3
"""365Scores in-tournament xG / stats sync.

The only advanced-stats source we can actually reach for free (FBref/Sofascore/
FotMob are Cloudflare-walled or token-gated — see probe_sources.yml). 365Scores
exposes, for each finished match:
  - per-shot xG / xGOT       -> game/?gameId=...  -> game.chartEvents.events[]
  - team stats (possession,  -> game/stats/?games=... -> statistics[]
    shots ...)

What this module does:
  1. Find finished FIFA World Cup games from the current-games feed.
  2. For each, pull per-team xG (summed over shots), possession and shots.
  3. Match the game to a fixture in `matches` (by team names, orientation-aware)
     and store the numbers for DISPLAY (home_xg/away_xg/possession/shots).
  4. Blend each team's live xG-differential into `teams.fbref_xg_diff` (the
     existing model feature) with shrinkage toward the pre-tournament prior, so
     a single noisy game can't swing predictions. Then recompute Elo/predictions.

Run with `--dry-run` to print everything it parsed/matched and write nothing.
"""
import sys
import json
import sqlite3
import urllib.request
import urllib.error

DB_PATH = 'fifa_2026.db'
ROOT = 'https://webws.365scores.com'
BASE = ROOT + '/web'
COMMON = 'appTypeId=5&langId=1&timezoneName=Asia/Taipei&userCountryId=1'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# How strongly the pre-tournament prior is held vs live xG. After this many games
# of live data, the live signal carries ~half the weight. Keeps early-tournament
# (1-2 game) samples from over-swinging a calibrated feature.
PRIOR_WEIGHT = 3.0


def log(msg):
    print(f"[365xG] {msg}", flush=True)


def fetch_json(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def is_world_cup(name):
    return bool(name) and ('World Cup' in name or '世界' in name)


def _finished(g):
    return (g.get('statusGroup') in (3, 4)
            or 'End' in str(g.get('statusText', ''))
            or 'Final' in str(g.get('statusText', '')))


def scan_current_feed():
    """One fetch of the current-games feed -> (finished WC game ids, WC competition ids)."""
    data = fetch_json(f'{BASE}/games/current/?{COMMON}&sports=1')
    ids, comps = set(), set()
    for g in data.get('games', []):
        name = (g.get('competitionDisplayName') or g.get('competitionName') or '')
        if not is_world_cup(name):
            continue
        if g.get('competitionId'):
            comps.add(g['competitionId'])
        if _finished(g) and g.get('id'):
            ids.add(g['id'])
    return ids, comps


def find_all_wc_finished_games(comp_ids):
    """Backfill enumerator: all finished games for the WC competition(s), INCLUDING
    ones that have aged out of the rolling 'current' window. Returns list of
    {id, home, away} read straight from the competition game list (no detail fetch)."""
    out = {}
    for cid in comp_ids:
        url = f'{BASE}/games/?{COMMON}&competitions={cid}&showOdds=false'
        pages = 0
        while url and pages < 8:
            try:
                data = fetch_json(url)
            except Exception as e:
                log(f"  [backfill] competition {cid} fetch failed: {e}")
                break
            for g in data.get('games', []):
                if not (_finished(g) and g.get('id')):
                    continue
                hc = g.get('homeCompetitor', {}) or {}
                ac = g.get('awayCompetitor', {}) or {}
                if hc.get('name') and ac.get('name'):
                    out[g['id']] = {'id': g['id'], 'home': hc['name'], 'away': ac['name']}
            nxt = (data.get('paging') or {}).get('nextPage')
            if nxt and nxt.startswith('/'):
                url = ROOT + nxt
            elif nxt and nxt.startswith('http'):
                url = nxt
            else:
                url = None
            pages += 1
        log(f"  [backfill] competition {cid}: enumerated {len(out)} finished game(s)")
    return list(out.values())


def _num(x):
    try:
        return float(str(x).replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def fetch_game_stats(game_id, discover=False):
    """Pull per-team advanced stats for one finished game. Returns dict or None.

    Free-data optimization: the two endpoints we already hit for xG expose more
    predictively useful numbers at zero extra cost — per-shot xGOT (xG-on-target:
    shot-placement quality, only defined for on-target shots), shots on target,
    corners and big chances. All are parsed defensively by name pattern and left
    NULL when a feed variant omits them, so nothing breaks if 365Scores renames
    or hides a stat. With `discover=True` (dry-run) every stat name the API
    actually returned is logged, so the daily probe workflow doubles as a
    discovery tool for further free fields."""
    g = fetch_json(f'{BASE}/game/?{COMMON}&gameId={game_id}').get('game', {})
    home = g.get('homeCompetitor', {}) or {}
    away = g.get('awayCompetitor', {}) or {}
    if not home.get('name') or not away.get('name'):
        return None

    hid, aid = home.get('id'), away.get('id')
    # competitorNum: 1 = home, 2 = away (365Scores convention). competitorId is a
    # fallback when a feed variant omits competitorNum.
    home_xg = away_xg = 0.0
    home_xgot = away_xgot = 0.0
    n_shots_h = n_shots_a = 0
    n_sot_h = n_sot_a = 0
    for ev in (g.get('chartEvents', {}) or {}).get('events', []) or []:
        xg = _num(ev.get('xg')) or 0.0
        xgot = _num(ev.get('xgot'))
        num = ev.get('competitorNum')
        cid = ev.get('competitorId')
        if num == 1 or (num is None and cid == hid):
            home_xg += xg
            n_shots_h += 1
            if xgot is not None:
                home_xgot += xgot
                n_sot_h += 1
        elif num == 2 or (num is None and cid == aid):
            away_xg += xg
            n_shots_a += 1
            if xgot is not None:
                away_xgot += xgot
                n_sot_a += 1

    res = {
        'game_id': game_id,
        'home_name': home['name'], 'away_name': away['name'],
        'home_id': hid, 'away_id': aid,
        'date': (g.get('startTime') or '')[:10],
        'home_xg': round(home_xg, 2), 'away_xg': round(away_xg, 2),
        'home_xgot': round(home_xgot, 2) or None, 'away_xgot': round(away_xgot, 2) or None,
        'home_shots': n_shots_h or None, 'away_shots': n_shots_a or None,
        'home_sot': n_sot_h or None, 'away_sot': n_sot_a or None,
        'home_possession': None, 'away_possession': None,
        'home_corners': None, 'away_corners': None,
        'home_big_chances': None, 'away_big_chances': None,
        'has_chart': bool((g.get('chartEvents', {}) or {}).get('events')),
    }

    # Possession / corners / big chances (and shots fallbacks) from the stats endpoint.
    try:
        st = fetch_json(f'{BASE}/game/stats/?{COMMON}&games={game_id}')
        seen_names = set()
        for s in st.get('statistics', []) or []:
            name = str(s.get('name', '')).lower()
            seen_names.add(name)
            cid = s.get('competitorId')
            side = 'home' if cid == hid else ('away' if cid == aid else None)
            if side is None:
                continue
            if 'possession' in name:
                pct = s.get('valuePercentage')
                val = round(pct * 100, 1) if pct is not None else _num(s.get('value'))
                res[f'{side}_possession'] = val
            elif name in ('shots', 'total shots') and not res.get(f'{side}_shots'):
                res[f'{side}_shots'] = _num(s.get('value'))
            elif 'on target' in name and not res.get(f'{side}_sot'):
                res[f'{side}_sot'] = _num(s.get('value'))
            elif 'corner' in name:
                res[f'{side}_corners'] = _num(s.get('value'))
            elif 'big chance' in name:
                res[f'{side}_big_chances'] = _num(s.get('value'))
        if discover and seen_names:
            log(f"  [discover] game {game_id} stat names: {sorted(seen_names)}")
    except Exception as e:
        log(f"  stats endpoint failed for {game_id}: {e}")

    return res


# All per-match advanced-stat columns synced from 365Scores. Single source of
# truth shared by the schema migration and the UPDATE below.
STAT_COLS = ('home_xg', 'away_xg', 'home_possession', 'away_possession',
             'home_shots', 'away_shots', 'home_xgot', 'away_xgot',
             'home_sot', 'away_sot', 'home_corners', 'away_corners',
             'home_big_chances', 'away_big_chances')


def ensure_schema(cur):
    cols = {r[1] for r in cur.execute('PRAGMA table_info(matches)')}
    for col in STAT_COLS:
        if col not in cols:
            cur.execute(f'ALTER TABLE matches ADD COLUMN {col} REAL')


def _ymd(s):
    """Extract the set of integer groups from a date string, order-insensitive, so
    '2026-06-19' and feed formats like '19/06/2026' compare equal."""
    import re
    return {int(x) for x in re.findall(r'\d+', str(s or ''))}


def match_fixture(cur, parsed, normalize):
    """Find (match_num, swapped) for a parsed game, orientation-aware. None if no
    match. A (home, away) pair is unique across the tournament, so names+orientation
    are the primary key; date is only a tiebreaker if several fixtures collide."""
    h = normalize(parsed['home_name'])
    a = normalize(parsed['away_name'])
    rows = cur.execute(
        "SELECT match_num, home_team, away_team, date FROM matches").fetchall()
    same, swapped = [], []
    for mn, ht, at, date in rows:
        ht_n, at_n = normalize(ht), normalize(at)
        if ht_n == h and at_n == a:
            same.append((mn, date))
        elif ht_n == a and at_n == h:
            swapped.append((mn, date))

    def pick(cands):
        if len(cands) == 1:
            return cands[0][0]
        pd = _ymd(parsed.get('date'))
        for mn, date in cands:
            if pd and pd == _ymd(date):
                return mn
        return cands[0][0]

    if same:
        return pick(same), False
    if swapped:
        return pick(swapped), True
    return None


def run(dry_run=False):
    from sync_fifa import normalize_team_name as N, reset_and_recalculate_all_elo_and_predictions
    try:
        from external_intelligence import MODEL_PRIOR_XG_DIFF
    except Exception:
        MODEL_PRIOR_XG_DIFF = {}

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Always add the columns: in --dry-run nothing is committed (probe has no push
    # step), so this only touches the ephemeral runner copy while letting the
    # missing-xG query and _report_blend read the columns without crashing.
    ensure_schema(cur)
    conn.commit()

    log("scanning 365Scores current feed for finished World Cup games...")
    ids, comp_ids = scan_current_feed()
    log(f"current feed: finished WC {sorted(ids)}; WC competition id(s) {sorted(comp_ids)}")

    # Backfill: any completed fixture still missing xG (e.g. games that aged out of
    # the rolling 'current' window before we captured them) is filled from the
    # competition's full game history. Fixtures missing only the NEWER stat
    # columns (xGOT/SOT/corners/big chances) are re-processed too, but only
    # within a 7-day window — a feed variant that simply doesn't publish those
    # fields would otherwise be re-fetched forever.
    missing = {frozenset((N(h), N(a))) for h, a in cur.execute(
        "SELECT home_team, away_team FROM matches "
        "WHERE status='Completed' AND ("
        "  home_xg IS NULL OR away_xg IS NULL"
        "  OR (home_xgot IS NULL AND date >= date('now', '-7 day'))"
        ")").fetchall()}
    if missing and comp_ids:
        log(f"{len(missing)} completed fixture(s) missing xG -> backfilling from competition history...")
        for bg in find_all_wc_finished_games(comp_ids):
            if frozenset((N(bg['home']), N(bg['away']))) in missing:
                ids.add(bg['id'])
    log(f"{len(ids)} game(s) to process: {sorted(ids)}")
    if not ids:
        log("nothing to sync.")
        conn.close()
        return

    matched = 0
    for gid in sorted(ids):
        try:
            p = fetch_game_stats(gid, discover=dry_run)
        except Exception as e:
            log(f"  game {gid} fetch failed: {e}")
            continue
        if not p:
            continue
        tag = 'DRY' if dry_run else 'SYNC'
        if not p.get('has_chart'):
            # No shot chart -> no xG. Don't write a misleading 0-0; leave NULL so a
            # later run can still fill it once 365Scores publishes the chart.
            log(f"  [{tag}] {p['home_name']} vs {p['away_name']} (game {gid}) -> no xG chart, skipping")
            continue
        m = match_fixture(cur, p, N)
        if m is None:
            log(f"  [{tag}] {p['home_name']} vs {p['away_name']} "
                f"xG {p['home_xg']}-{p['away_xg']}  -> NO DB FIXTURE MATCH")
            continue
        mn, swapped = m

        def sided(base):
            h, a = p[f'home_{base}'], p[f'away_{base}']
            return (a, h) if swapped else (h, a)

        vals = {}
        for base in ('xg', 'possession', 'shots', 'xgot', 'sot',
                     'corners', 'big_chances'):
            vals[f'home_{base}'], vals[f'away_{base}'] = sided(base)
        log(f"  [{tag}] match #{mn} {p['home_name']} vs {p['away_name']}"
            f"{' (swapped)' if swapped else ''}  xG {vals['home_xg']}-{vals['away_xg']}"
            f"  xGOT {vals['home_xgot']}-{vals['away_xgot']}"
            f"  SOT {vals['home_sot']}-{vals['away_sot']}"
            f"  poss {vals['home_possession']}-{vals['away_possession']}"
            f"  shots {vals['home_shots']}-{vals['away_shots']}"
            f"  corners {vals['home_corners']}-{vals['away_corners']}")
        matched += 1
        if not dry_run:
            setters = ', '.join(f'{c}=?' for c in STAT_COLS)
            cur.execute(f"UPDATE matches SET {setters} WHERE match_num=?",
                        tuple(vals[c] for c in STAT_COLS) + (mn,))

    log(f"matched {matched}/{len(ids)} game(s) to fixtures.")

    if dry_run:
        _report_blend(cur, MODEL_PRIOR_XG_DIFF, N, dry=True)
        conn.close()
        log("dry-run complete; no DB writes.")
        return

    conn.commit()
    _report_blend(cur, MODEL_PRIOR_XG_DIFF, N, dry=False)
    conn.commit()
    conn.close()

    log("recomputing Elo & predictions with blended xG...")
    reset_and_recalculate_all_elo_and_predictions()
    log("done.")


def _report_blend(cur, prior_map, normalize, dry):
    """Compute each team's live mean xG-diff from stored match xG and blend toward
    the pre-tournament prior. Writes teams.fbref_xg_diff unless dry."""
    rows = cur.execute(
        "SELECT home_team, away_team, home_xg, away_xg FROM matches "
        "WHERE home_xg IS NOT NULL AND away_xg IS NOT NULL").fetchall()
    agg = {}  # team -> [sum_diff, n]
    for ht, at, hx, ax in rows:
        h, a = normalize(ht), normalize(at)
        agg.setdefault(h, [0.0, 0]); agg.setdefault(a, [0.0, 0])
        agg[h][0] += (hx - ax); agg[h][1] += 1
        agg[a][0] += (ax - hx); agg[a][1] += 1
    for team, (s, n) in sorted(agg.items()):
        live = s / n if n else 0.0
        prior = prior_map.get(team, 0.0)
        blended = round((PRIOR_WEIGHT * prior + n * live) / (PRIOR_WEIGHT + n), 3)
        log(f"  xg-diff {team:<22} prior={prior:+.2f} live={live:+.2f} (n={n}) -> {blended:+.3f}")
        if not dry:
            cur.execute("UPDATE teams SET fbref_xg_diff=? WHERE name=?", (blended, team))


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv)
