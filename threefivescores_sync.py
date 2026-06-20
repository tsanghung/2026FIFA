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
BASE = 'https://webws.365scores.com/web'
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


def find_finished_wc_games():
    """Return list of dicts {id, comp} for finished World Cup games in the feed."""
    data = fetch_json(f'{BASE}/games/current/?{COMMON}&sports=1')
    out = []
    for g in data.get('games', []):
        comp = (g.get('competitionDisplayName') or g.get('competitionName') or '')
        if not is_world_cup(comp):
            continue
        finished = (g.get('statusGroup') in (3, 4)
                    or 'End' in str(g.get('statusText', ''))
                    or 'Final' in str(g.get('statusText', '')))
        if finished and g.get('id'):
            out.append({'id': g['id'], 'comp': comp})
    return out


def _num(x):
    try:
        return float(str(x).replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def fetch_game_stats(game_id):
    """Pull per-team xG/possession/shots for one finished game. Returns dict or None."""
    g = fetch_json(f'{BASE}/game/?{COMMON}&gameId={game_id}').get('game', {})
    home = g.get('homeCompetitor', {}) or {}
    away = g.get('awayCompetitor', {}) or {}
    if not home.get('name') or not away.get('name'):
        return None

    hid, aid = home.get('id'), away.get('id')
    # competitorNum: 1 = home, 2 = away (365Scores convention). competitorId is a
    # fallback when a feed variant omits competitorNum.
    home_xg = away_xg = 0.0
    n_shots_h = n_shots_a = 0
    for ev in (g.get('chartEvents', {}) or {}).get('events', []) or []:
        xg = _num(ev.get('xg')) or 0.0
        num = ev.get('competitorNum')
        cid = ev.get('competitorId')
        if num == 1 or (num is None and cid == hid):
            home_xg += xg
            n_shots_h += 1
        elif num == 2 or (num is None and cid == aid):
            away_xg += xg
            n_shots_a += 1

    res = {
        'game_id': game_id,
        'home_name': home['name'], 'away_name': away['name'],
        'home_id': hid, 'away_id': aid,
        'date': (g.get('startTime') or '')[:10],
        'home_xg': round(home_xg, 2), 'away_xg': round(away_xg, 2),
        'home_shots': n_shots_h or None, 'away_shots': n_shots_a or None,
        'home_possession': None, 'away_possession': None,
        'has_chart': bool((g.get('chartEvents', {}) or {}).get('events')),
    }

    # Possession (and a shots fallback) from the dedicated stats endpoint.
    try:
        st = fetch_json(f'{BASE}/game/stats/?{COMMON}&games={game_id}')
        for s in st.get('statistics', []) or []:
            name = str(s.get('name', '')).lower()
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
    except Exception as e:
        log(f"  stats endpoint failed for {game_id}: {e}")

    return res


def ensure_schema(cur):
    cols = {r[1] for r in cur.execute('PRAGMA table_info(matches)')}
    for col in ('home_xg', 'away_xg', 'home_possession', 'away_possession',
                'home_shots', 'away_shots'):
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
    from sync_fifa import normalize_team_name, reset_and_recalculate_all_elo_and_predictions
    try:
        from external_intelligence import MODEL_PRIOR_XG_DIFF
    except Exception:
        MODEL_PRIOR_XG_DIFF = {}

    log("locating finished World Cup games on 365Scores...")
    games = find_finished_wc_games()
    log(f"found {len(games)} finished WC game(s) in feed: {[g['id'] for g in games]}")
    if not games:
        log("nothing to sync.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Always add the columns: in --dry-run nothing is committed (and the probe
    # workflow has no push step), so this only affects the ephemeral runner copy
    # while letting _report_blend read home_xg/away_xg without crashing.
    ensure_schema(cur)

    matched = 0
    for g in games:
        try:
            p = fetch_game_stats(g['id'])
        except Exception as e:
            log(f"  game {g['id']} fetch failed: {e}")
            continue
        if not p:
            continue
        m = match_fixture(cur, p, normalize_team_name)
        tag = 'DRY' if dry_run else 'SYNC'
        if m is None:
            log(f"  [{tag}] {p['home_name']} vs {p['away_name']} "
                f"xG {p['home_xg']}-{p['away_xg']}  -> NO DB FIXTURE MATCH")
            continue
        mn, swapped = m
        hx, ax = (p['away_xg'], p['home_xg']) if swapped else (p['home_xg'], p['away_xg'])
        hp, ap = ((p['away_possession'], p['home_possession']) if swapped
                  else (p['home_possession'], p['away_possession']))
        hs, ss = ((p['away_shots'], p['home_shots']) if swapped
                  else (p['home_shots'], p['away_shots']))
        log(f"  [{tag}] match #{mn} {p['home_name']} vs {p['away_name']}"
            f"{' (swapped)' if swapped else ''}  xG {hx}-{ax}  poss {hp}-{ap}  shots {hs}-{ss}")
        matched += 1
        if not dry_run:
            cur.execute(
                "UPDATE matches SET home_xg=?, away_xg=?, home_possession=?, "
                "away_possession=?, home_shots=?, away_shots=? WHERE match_num=?",
                (hx, ax, hp, ap, hs, ss, mn))

    log(f"matched {matched}/{len(games)} games to fixtures.")

    if dry_run:
        # Show what the per-team xG-diff blend WOULD produce, without writing.
        _report_blend(cur, MODEL_PRIOR_XG_DIFF, normalize_team_name, dry=True)
        conn.close()
        log("dry-run complete; no DB writes.")
        return

    conn.commit()
    _report_blend(cur, MODEL_PRIOR_XG_DIFF, normalize_team_name, dry=False)
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
