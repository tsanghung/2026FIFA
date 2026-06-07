"""
champion_predictor.py — 2026 FIFA World Cup title-race predictor.

Produces a daily, rolling champion (outright winner) probability for every team by
fusing three pillars, with the **betting market as the primary signal**:

  1. MARKET   (primary) — de-vigged outright "to win the World Cup" odds, cross-
                compared across the world's leading sportsbooks via The Odds API's
                `soccer_fifa_world_cup_winner` market. Falls back to a curated
                June-2026 snapshot when no API key / no response.
  2. AUTHORITY — the Opta supercomputer's published tournament-win probabilities
                (Stats Perform), the flagship public football forecast.
  3. MODEL (AI) — this system's own full-tournament Monte Carlo (group stage +
                knockout bracket) driven by the live Elo/Pi/Berrar/ensemble engine.
                This is the pillar that "learns from results": once matches are
                completed their actual outcomes feed the ratings, so the model
                share is automatically up-weighted as the tournament progresses.

The three are blended (market-weighted), then exponentially smoothed (EWMA) against
the previous day's value to damp single-day noise, and a daily snapshot is stored so
the homepage can chart each team's title-probability trend over time.

Sources (captured 2026-06-03):
  * Opta supercomputer — theanalyst.com "Who Will Win the 2026 FIFA World Cup?"
    Spain 16.1%, France 13.0%, England 11.2%, Argentina 10.4%, Morocco 1.9% ...
  * Market snapshot — aggregated Bet365 / Pinnacle / Betfair / DraftKings outrights
    (FOX Sports, SI, Yahoo, Covers), e.g. Spain +475, France +500, England +625,
    Brazil +800, Argentina +900, Portugal +1000, Germany +1400.
"""

import os
import sys
import math
import random
import sqlite3
from datetime import datetime

import requests

# Reuse the live prediction engine & helpers from the sync core.
from sync_fifa import (
    predict_match,
    get_home_field_advantage,
    normalize_team_name,
    poisson_pmf,  # noqa: F401  (kept for parity / potential reuse)
)

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')

# --------------------------------------------------------------------------------------
# Pillar 2 — Opta supercomputer tournament-win probabilities (2026-06-03 snapshot).
# Top values are the published figures; the long tail keeps the existing baseline so the
# field is complete. Everything is renormalised at runtime.
# --------------------------------------------------------------------------------------
OPTA_2026 = {
    'Spain': 0.161, 'France': 0.130, 'England': 0.112, 'Argentina': 0.104,
    'Brazil': 0.083, 'Portugal': 0.058, 'Germany': 0.050, 'Netherlands': 0.045,
    'Belgium': 0.030, 'Uruguay': 0.028, 'Croatia': 0.022, 'Morocco': 0.019,
    'Colombia': 0.018, 'USA': 0.0121, 'Switzerland': 0.012, 'Japan': 0.010,
    'Mexico': 0.010, 'Ecuador': 0.008, 'Senegal': 0.007, 'Austria': 0.006,
    'Norway': 0.005, 'Australia': 0.004, 'Ivory Coast': 0.003, 'Canada': 0.0052,
    'South Korea': 0.004,
}

# --------------------------------------------------------------------------------------
# Pillar 1 fallback — curated outright odds snapshot (American moneyline, 2026-06-03).
# Used only when The Odds API is unavailable. Converted to decimal then de-vigged.
# --------------------------------------------------------------------------------------
CURATED_AMERICAN_ODDS = {
    'Spain': 475, 'France': 500, 'England': 625, 'Brazil': 800, 'Argentina': 900,
    'Portugal': 1000, 'Germany': 1400, 'Netherlands': 2200, 'Belgium': 2200,
    'Uruguay': 2800, 'Croatia': 3300, 'Colombia': 4000, 'Morocco': 4000,
    'USA': 6600, 'Switzerland': 8000, 'Japan': 10000, 'Mexico': 8000,
    'Senegal': 10000, 'Ecuador': 15000, 'Austria': 15000, 'Norway': 12500,
    'South Korea': 20000, 'Australia': 25000, 'Ivory Coast': 25000, 'Canada': 15000,
}

# The leading global sportsbooks we cross-compare for the market consensus.
TOP_BOOKMAKERS = ['bet365', 'pinnacle', 'betfair_ex_uk', 'betfair', 'draftkings', 'williamhill']

# Blend weights interpolate from pre-tournament (market-led) to late-tournament
# (results/model-led) according to the fraction of matches already completed.
WEIGHTS_PRE = {'market': 0.55, 'opta': 0.25, 'model': 0.20}
WEIGHTS_END = {'market': 0.40, 'opta': 0.10, 'model': 0.50}
EWMA_ALPHA = 0.40  # weight on today's fresh reading vs. yesterday's smoothed value


def log(msg):
    print(f"[champion] {msg}")


def american_to_decimal(a):
    return (a / 100.0 + 1.0) if a > 0 else (100.0 / abs(a) + 1.0)


# ======================================================================================
# Schema
# ======================================================================================
def ensure_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS champion_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            team TEXT NOT NULL,
            market_prob REAL,
            opta_prob REAL,
            model_prob REAL,
            blended_raw REAL,
            blended_ewma REAL,
            rank INTEGER,
            delta REAL,
            UNIQUE(snapshot_date, team)
        )
    ''')
    conn.commit()


# ======================================================================================
# Data loading
# ======================================================================================
def load_team_ratings(cursor):
    cursor.execute('''
        SELECT name, elo_rating, fifa_rank, pi_rating_home, pi_rating_away,
               berrar_att, berrar_def, fbref_xg_diff, injury_count,
               sentiment_score, opta_win_prob
        FROM teams
    ''')
    teams = {}
    for r in cursor.fetchall():
        teams[r[0]] = {
            'elo': r[1] or 1400.0, 'rank': r[2] or 50,
            'pi_h': r[3] or 0.0, 'pi_a': r[4] or 0.0,
            'att': r[5] or 1.0, 'def': r[6] or 1.0,
            'xg': r[7] or 0.0, 'inj': r[8] or 0,
            'sent': r[9] or 0.0, 'opta': r[10] or 0.0,
        }
    return teams


def load_matches(cursor):
    cursor.execute('''
        SELECT match_num, group_or_stage, home_team, away_team, city,
               status, home_goals, away_goals
        FROM matches ORDER BY match_num
    ''')
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ======================================================================================
# Prediction cache (predict_match is expensive — memoise per pairing)
# ======================================================================================
class PredictionCache:
    def __init__(self, teams):
        self.teams = teams
        self.cache = {}

    def get(self, home, away, home_adv):
        key = (home, away, home_adv)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        th = self.teams.get(home)
        ta = self.teams.get(away)
        if th is None or ta is None:
            res = (1.25, 1.25, 0.4, 0.27, 0.33)  # neutral fallback
        else:
            p = predict_match(
                th['elo'], ta['elo'], th['pi_h'], ta['pi_a'],
                th['att'], ta['def'], ta['att'], th['def'],
                th['rank'], ta['rank'],
                th['xg'], th['inj'], th['sent'],
                ta['xg'], ta['inj'], ta['sent'],
                home_adv, th['opta'], ta['opta'],
            )
            res = (p['home_expected_goals'], p['away_expected_goals'],
                   p['home_win_prob'], p['draw_prob'], p['away_win_prob'])
        self.cache[key] = res
        return res


def _poisson(lamb):
    if lamb <= 0:
        return 0
    L = math.exp(-lamb)
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1


# ======================================================================================
# Knockout-bracket parsing
# ======================================================================================
import re

def parse_slot(text):
    """Parse a knockout placeholder into a resolvable token."""
    if not text:
        return ('LIT', text)
    m = re.match(r'Winner Group (\w)', text)
    if m:
        return ('GW', m.group(1))
    m = re.match(r'Runner-up Group (\w)', text)
    if m:
        return ('GR', m.group(1))
    m = re.match(r'3rd Group ([\w/]+)', text)
    if m:
        return ('G3', m.group(1).split('/'))
    m = re.match(r'Winner Match (\d+)', text)
    if m:
        return ('MW', int(m.group(1)))
    m = re.match(r'Loser Match (\d+)', text)
    if m:
        return ('ML', int(m.group(1)))
    # Already a real team name (e.g. once the tournament has progressed)
    return ('LIT', normalize_team_name(text))


def build_ko_structure(matches):
    """Returns {match_num: (home_slot, away_slot, city)} for matches 73-104, and the
    list of best-third R32 slots with their eligible group sets."""
    ko = {}
    third_slots = []  # (match_num, side, eligible_groups)
    for m in matches:
        mn = m['match_num']
        if mn < 73:
            continue
        hs = parse_slot(m['home_team'])
        as_ = parse_slot(m['away_team'])
        ko[mn] = (hs, as_, m.get('city'))
        for side, slot in (('home', hs), ('away', as_)):
            if slot[0] == 'G3':
                third_slots.append((mn, side, set(slot[1])))
    return ko, third_slots


def assign_thirds(qualified_groups, third_slots):
    """Bipartite matching: map each of the 8 best-third groups to a distinct R32 slot
    whose eligibility set contains it. Returns {(match_num, side): group_letter}."""
    slots = sorted(third_slots, key=lambda s: len(s[2]))  # most-constrained first
    groups = list(qualified_groups)
    assignment = {}
    used_groups = set()

    def backtrack(i):
        if i == len(slots):
            return True
        mn, side, elig = slots[i]
        for g in groups:
            if g in used_groups or g not in elig:
                continue
            used_groups.add(g)
            assignment[(mn, side)] = g
            if backtrack(i + 1):
                return True
            used_groups.discard(g)
            del assignment[(mn, side)]
        return False

    if backtrack(0):
        return assignment
    # Fallback: arbitrary best-effort assignment (should not happen for valid tables)
    leftover = [g for g in groups]
    for mn, side, elig in slots:
        cand = next((g for g in leftover if g in elig), leftover[0] if leftover else None)
        if cand:
            assignment[(mn, side)] = cand
            leftover.remove(cand)
    return assignment


# ======================================================================================
# Full-tournament Monte Carlo
# ======================================================================================
GROUP_LETTERS = list('ABCDEFGHIJKL')

def simulate_tournament(matches, cache, n_sims):
    """Returns champion_prob[team] and a dict of stage-reach probabilities."""
    # Pre-split fixtures
    group_matches = [m for m in matches if m['match_num'] <= 72]
    ko_struct, third_slots = build_ko_structure(matches)

    # Group letter comes straight from the DB's group_or_stage field (e.g. "Group A"),
    # with a team-membership fallback for safety.
    from sync_fifa import GROUPS_DATA
    team_group = {}
    for g, tlist in GROUPS_DATA.items():
        for t in tlist:
            team_group[normalize_team_name(t)] = g

    # Precompute expected goals for every group fixture (fixed pairings).
    group_pre = []
    for m in group_matches:
        h = normalize_team_name(m['home_team'])
        a = normalize_team_name(m['away_team'])
        adv = get_home_field_advantage(h, a, m.get('city'))
        eg_h, eg_a, _, _, _ = cache.get(h, a, adv)
        completed = (m['status'] == 'Completed' and m['home_goals'] is not None)
        stage = (m.get('group_or_stage') or '').strip()
        parts = stage.split()
        grp = parts[-1] if (stage.startswith('Group') and len(parts) >= 2) else None
        group_pre.append({
            'group': grp or team_group.get(h) or team_group.get(a),
            'h': h, 'a': a, 'eg_h': eg_h, 'eg_a': eg_a,
            'completed': completed,
            'hg': m['home_goals'], 'ag': m['away_goals'],
        })

    champ = {}
    stages = {s: {} for s in ('R32', 'R16', 'QF', 'SF', 'Final', 'Champion')}

    def bump(d, t):
        d[t] = d.get(t, 0) + 1

    ko_order = sorted(ko_struct.keys())

    for _ in range(n_sims):
        # ---- Group stage ----
        table = {g: {} for g in GROUP_LETTERS}  # group -> team -> [pts, gd, gf]

        def ensure(g, t):
            if g not in table:
                table[g] = {}
            if t not in table[g]:
                table[g][t] = [0, 0, 0]

        for gm in group_pre:
            g = gm['group']
            h, a = gm['h'], gm['a']
            if gm['completed']:
                hg, ag = gm['hg'], gm['ag']
            else:
                hg, ag = _poisson(gm['eg_h']), _poisson(gm['eg_a'])
            ensure(g, h); ensure(g, a)
            table[g][h][1] += hg - ag; table[g][h][2] += hg
            table[g][a][1] += ag - hg; table[g][a][2] += ag
            if hg > ag:
                table[g][h][0] += 3
            elif hg < ag:
                table[g][a][0] += 3
            else:
                table[g][h][0] += 1; table[g][a][0] += 1

        gw, gr, g3 = {}, {}, {}
        thirds = []  # (group, [pts,gd,gf], team)
        for g in GROUP_LETTERS:
            standings = sorted(
                table[g].items(),
                key=lambda kv: (kv[1][0], kv[1][1], kv[1][2], random.random()),
                reverse=True,
            )
            if len(standings) >= 3:
                gw[g] = standings[0][0]
                gr[g] = standings[1][0]
                g3[g] = standings[2][0]
                thirds.append((g, standings[2][1], standings[2][0]))

        # Best 8 of 12 third-placed teams
        thirds.sort(key=lambda x: (x[1][0], x[1][1], x[1][2], random.random()), reverse=True)
        qualified_third_groups = {t[0] for t in thirds[:8]}
        third_assign = assign_thirds(qualified_third_groups, third_slots)

        # ---- Knockout ----
        winners, losers = {}, {}

        def resolve(slot, mn, side):
            kind = slot[0]
            if kind == 'GW':
                return gw.get(slot[1])
            if kind == 'GR':
                return gr.get(slot[1])
            if kind == 'G3':
                grp = third_assign.get((mn, side))
                return g3.get(grp) if grp else None
            if kind == 'MW':
                return winners.get(slot[1])
            if kind == 'ML':
                return losers.get(slot[1])
            if kind == 'LIT':
                return slot[1]
            return None

        for mn in ko_order:
            hs, as_, city = ko_struct[mn]
            home = resolve(hs, mn, 'home')
            away = resolve(as_, mn, 'away')
            if home is None or away is None:
                continue
            # Stage bookkeeping
            if mn <= 88:
                bump(stages['R32'], home); bump(stages['R32'], away); st = 'R32'
            elif mn <= 96:
                bump(stages['R16'], home); bump(stages['R16'], away); st = 'R16'
            elif mn <= 100:
                bump(stages['QF'], home); bump(stages['QF'], away); st = 'QF'
            elif mn <= 102:
                bump(stages['SF'], home); bump(stages['SF'], away); st = 'SF'
            elif mn == 104:
                bump(stages['Final'], home); bump(stages['Final'], away); st = 'Final'
            else:
                st = '3P'  # third-place play-off

            adv = get_home_field_advantage(home, away, city)
            _, _, p_h, p_d, p_a = cache.get(home, away, adv)
            denom = p_h + p_a
            home_wins = random.random() < (p_h / denom if denom > 0 else 0.5)
            if home_wins:
                winners[mn], losers[mn] = home, away
            else:
                winners[mn], losers[mn] = away, home

        if 104 in winners:
            bump(stages['Champion'], winners[104])
            bump(champ, winners[104])

    # Normalise to probabilities
    champ_prob = {t: c / n_sims for t, c in champ.items()}
    stage_prob = {s: {t: c / n_sims for t, c in d.items()} for s, d in stages.items()}
    return champ_prob, stage_prob


# ======================================================================================
# Pillar 1 — market consensus
# ======================================================================================
def _devig(odds_map):
    """odds_map: {team: decimal_odds} -> de-vigged probabilities summing to 1."""
    implied = {t: 1.0 / o for t, o in odds_map.items() if o and o > 1.0}
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {t: v / total for t, v in implied.items()}


def fetch_market_api(api_key):
    """The Odds API outright winner market, cross-compared across leading books."""
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds/"
    params = {'apiKey': api_key, 'regions': 'us,uk,eu', 'markets': 'outrights', 'oddsFormat': 'decimal'}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"outright API 抓取失敗 ({type(e).__name__})，改用內建快照。")
        return None

    per_book = {}  # book -> {team: odds}
    for event in data if isinstance(data, list) else []:
        for bk in event.get('bookmakers', []):
            key = bk.get('key', '')
            for mkt in bk.get('markets', []):
                if mkt.get('key') != 'outrights':
                    continue
                for out in mkt.get('outcomes', []):
                    team = normalize_team_name(out.get('name', ''))
                    price = out.get('price')
                    if team and price:
                        per_book.setdefault(key, {})[team] = price
    if not per_book:
        log("outright API 無資料，改用內建快照。")
        return None

    # Prefer the leading books; if none matched, use whatever is available.
    chosen = {k: v for k, v in per_book.items() if k in TOP_BOOKMAKERS} or per_book
    devigged = [_devig(v) for v in chosen.values()]
    teams = set().union(*[set(d) for d in devigged]) if devigged else set()
    consensus = {t: sum(d.get(t, 0.0) for d in devigged) / len(devigged) for t in teams}
    total = sum(consensus.values())
    if total > 0:
        consensus = {t: v / total for t, v in consensus.items()}
    log(f"市場共識來自 {len(chosen)} 家莊家：{', '.join(sorted(chosen))}")
    return consensus


def market_from_curated():
    decimal_map = {t: american_to_decimal(a) for t, a in CURATED_AMERICAN_ODDS.items()}
    return _devig(decimal_map)


def get_market_probs(api_key):
    probs = fetch_market_api(api_key) if api_key else None
    if not probs:
        probs = market_from_curated()
        log("使用內建 2026-06 市場快照（Bet365/Pinnacle/Betfair/DraftKings 聚合）。")
    return probs


# ======================================================================================
# Blend + EWMA + persist
# ======================================================================================
def normalise(d):
    total = sum(d.values())
    return {k: v / total for k, v in d.items()} if total > 0 else d


def canonicalise_probability_map(probs, allowed_teams):
    """Fold aliases and discard non-qualified / non-registered teams."""
    folded = {}
    for raw_team, value in (probs or {}).items():
        if value is None:
            continue
        team = normalize_team_name(raw_team)
        if team not in allowed_teams:
            continue
        folded[team] = folded.get(team, 0.0) + float(value)
    return normalise(folded)


def completed_fraction(matches):
    done = sum(1 for m in matches if m['status'] == 'Completed')
    return done / max(1, len(matches))


def interp_weights(frac):
    return {k: WEIGHTS_PRE[k] + (WEIGHTS_END[k] - WEIGHTS_PRE[k]) * frac for k in WEIGHTS_PRE}


def previous_ewma(cursor, today):
    cursor.execute(
        'SELECT snapshot_date FROM champion_predictions WHERE snapshot_date < ? '
        'ORDER BY snapshot_date DESC LIMIT 1', (today,))
    row = cursor.fetchone()
    if not row:
        return {}, None
    prev_date = row[0]
    cursor.execute(
        'SELECT team, blended_ewma FROM champion_predictions WHERE snapshot_date = ?',
        (prev_date,))
    return {t: v for t, v in cursor.fetchall()}, prev_date


def run_champion_prediction(api_key=None, n_sims=10000, alpha=EWMA_ALPHA, store=True):
    api_key = api_key if api_key is not None else os.environ.get('THE_ODDS_API_KEY', '').strip()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    ensure_schema(conn)

    teams = load_team_ratings(cursor)
    matches = load_matches(cursor)
    frac = completed_fraction(matches)

    log(f"執行 {n_sims} 次完整賽事蒙地卡羅（已完賽 {frac*100:.0f}%）...")
    cache = PredictionCache(teams)
    model_probs, stage_probs = simulate_tournament(matches, cache, n_sims)

    official_teams = set(teams)
    market_probs = canonicalise_probability_map(get_market_probs(api_key), official_teams)
    opta_probs = canonicalise_probability_map(OPTA_2026, official_teams)
    model_probs = canonicalise_probability_map(model_probs, official_teams)

    w = interp_weights(frac)
    log(f"融合權重（市場/權威/模型）= {w['market']:.2f}/{w['opta']:.2f}/{w['model']:.2f}")

    all_teams = set(teams)
    blended_raw = {}
    for t in all_teams:
        blended_raw[t] = (w['market'] * market_probs.get(t, 0.0)
                          + w['opta'] * opta_probs.get(t, 0.0)
                          + w['model'] * model_probs.get(t, 0.0))
    blended_raw = normalise(blended_raw)

    today = datetime.now().strftime('%Y-%m-%d')
    prev_ewma, prev_date = previous_ewma(cursor, today)
    blended_ewma = {}
    for t, v in blended_raw.items():
        pe = prev_ewma.get(t)
        blended_ewma[t] = alpha * v + (1 - alpha) * pe if pe is not None else v
    blended_ewma = normalise(blended_ewma)

    ranked = sorted(blended_ewma.items(), key=lambda kv: kv[1], reverse=True)

    if store:
        placeholders = ','.join('?' for _ in official_teams)
        cursor.execute(
            f'DELETE FROM champion_predictions WHERE team NOT IN ({placeholders})',
            tuple(sorted(official_teams)),
        )
        # Fresh write for the day so retired/withdrawn teams never linger.
        cursor.execute('DELETE FROM champion_predictions WHERE snapshot_date = ?', (today,))
        for rank, (t, ev) in enumerate(ranked, 1):
            delta = ev - prev_ewma.get(t, ev)
            cursor.execute('''
                INSERT INTO champion_predictions
                    (snapshot_date, team, market_prob, opta_prob, model_prob,
                     blended_raw, blended_ewma, rank, delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date, team) DO UPDATE SET
                    market_prob=excluded.market_prob, opta_prob=excluded.opta_prob,
                    model_prob=excluded.model_prob, blended_raw=excluded.blended_raw,
                    blended_ewma=excluded.blended_ewma, rank=excluded.rank, delta=excluded.delta
            ''', (today, t, market_probs.get(t), opta_probs.get(t), model_probs.get(t),
                  blended_raw.get(t), ev, rank, delta))
        conn.commit()
        log(f"已寫入 {today} 快照（{len(ranked)} 隊），EWMA 對比前一快照 {prev_date or '無'}。")

    conn.close()
    return ranked, {'market': market_probs, 'opta': opta_probs, 'model': model_probs,
                    'stage': stage_probs, 'weights': w, 'date': today}


def print_report(ranked, meta, top_n=16):
    m, o, mo = meta['market'], meta['opta'], meta['model']
    print("\n" + "=" * 74)
    print(f" 🏆  2026 世界盃總冠軍預測 (Title Race)   —   {meta['date']}")
    print("=" * 74)
    print(f"{'#':>2}  {'隊伍':<16}{'融合':>7}{'市場':>8}{'Opta':>8}{'模型':>8}")
    print("-" * 74)
    for i, (t, ev) in enumerate(ranked[:top_n], 1):
        print(f"{i:>2}  {t:<16}{ev*100:>6.1f}%{m.get(t,0)*100:>7.1f}%"
              f"{o.get(t,0)*100:>7.1f}%{mo.get(t,0)*100:>7.1f}%")
    print("=" * 74)
    w = meta['weights']
    print(f"融合權重  市場 {w['market']:.0%} · 權威(Opta) {w['opta']:.0%} · 模型(AI) {w['model']:.0%}")
    print("市場為主；開賽後模型(AI)權重隨完賽比例自動上升。\n")


if __name__ == '__main__':
    n = int(os.environ.get('CHAMPION_SIMS', '10000'))
    ranked, meta = run_champion_prediction(n_sims=n)
    print_report(ranked, meta)
