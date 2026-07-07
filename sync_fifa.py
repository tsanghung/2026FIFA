import os
import sqlite3
import re
import math
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from model_config import CFG


def load_seed_elo():
    """#6 Data-driven Elo seeds (keyed by canonical/normalised team names),
    produced by backtest.py from ~50k historical internationals. Falls back to
    the hand-typed INITIAL_ELO when the file is absent."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'team_ratings_seed.json')
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def seeded_initial_elo(raw_team):
    """Prefer the data-driven seed (looked up by normalised name); else INITIAL_ELO."""
    norm = normalize_team_name(raw_team)
    if norm in SEED_ELO:
        return SEED_ELO[norm]
    return INITIAL_ELO.get(raw_team, 1400.0)


SEED_ELO = load_seed_elo()

# Configuration
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync.log')

# Stable mapping of Wikipedia footballbox index to match number
INDEX_TO_MATCH_NUM = {
    0: 1, 1: 2, 2: 25, 3: 28, 4: 53, 5: 54, 6: 3, 7: 8, 8: 26, 9: 27, 10: 51, 11: 52,
    12: 7, 13: 5, 14: 30, 15: 29, 16: 49, 17: 50, 18: 4, 19: 6, 20: 32, 21: 31, 22: 59,
    23: 60, 24: 10, 25: 9, 26: 33, 27: 34, 28: 55, 29: 56, 30: 11, 31: 12, 32: 35,
    33: 36, 34: 57, 35: 58, 36: 16, 37: 15, 38: 39, 39: 40, 40: 63, 41: 64, 42: 14,
    43: 13, 44: 38, 45: 37, 46: 65, 47: 66, 48: 17, 49: 18, 50: 42, 51: 41, 52: 61,
    53: 62, 54: 19, 55: 20, 56: 43, 57: 44, 58: 69, 59: 70, 60: 23, 61: 24, 62: 47,
    63: 48, 64: 71, 65: 72, 66: 22, 67: 21, 68: 45, 69: 46, 70: 67, 71: 68, 72: 73,
    73: 76, 74: 74, 75: 75, 76: 78, 77: 77, 78: 79, 79: 80, 80: 82, 81: 81, 82: 84,
    83: 83, 84: 85, 85: 88, 86: 86, 87: 87, 88: 90, 89: 89, 90: 91, 91: 92, 92: 93,
    93: 94, 94: 95, 95: 96, 96: 97, 97: 98, 98: 99, 99: 100, 100: 101, 101: 102,
    102: 103, 103: 104
}

# Predefined groups & teams (Drawn Dec 5, 2025)
GROUPS_DATA = {
    'A': ['Mexico', 'South Korea', 'South Africa', 'Czechia'],
    'B': ['Canada', 'Switzerland', 'Qatar', 'Bosnia-Herzegovina'],
    'C': ['Brazil', 'Morocco', 'Scotland', 'Haiti'],
    'D': ['USA', 'Paraguay', 'Australia', 'Türkiye'],
    'E': ['Germany', 'Ecuador', 'Ivory Coast', 'Curaçao'],
    'F': ['Netherlands', 'Japan', 'Tunisia', 'Sweden'],
    'G': ['Belgium', 'Iran', 'Egypt', 'New Zealand'],
    'H': ['Spain', 'Uruguay', 'Saudi Arabia', 'Cape Verde'],
    'I': ['France', 'Senegal', 'Norway', 'Iraq'],
    'J': ['Argentina', 'Algeria', 'Austria', 'Jordan'],
    'K': ['Portugal', 'Colombia', 'Uzbekistan', 'DR Congo'],
    'L': ['England', 'Croatia', 'Ghana', 'Panama']
}

# Elite initial Elo ratings for the 48 teams based on standard strength & tiers
INITIAL_ELO = {
    # Top Tier (1600+)
    'Argentina': 1700, 'France': 1680, 'Spain': 1670, 'England': 1660, 
    'Brazil': 1650, 'Belgium': 1630, 'Portugal': 1620, 'Netherlands': 1610,
    # Strong Tier (1500 - 1600)
    'Uruguay': 1580, 'Colombia': 1570, 'Croatia': 1560, 'Morocco': 1550, 
    'Germany': 1540, 'USA': 1530, 'Mexico': 1535, 'Switzerland': 1520, 'Japan': 1515,
    'South Korea': 1500, 'Ecuador': 1490,
    # Mid Tier (1400 - 1500)
    'Austria': 1480, 'Sweden': 1470, 'Ukraine': 1460, 'Türkiye': 1450, 
    'Norway': 1445, 'Czechia': 1440, 'Czech Republic': 1440, 'Senegal': 1435, 
    'Australia': 1430, 'Iran': 1425, 'IR Iran': 1425, 'Ivory Coast': 1420, 
    "Côte d'Ivoire": 1420, 'Paraguay': 1415, 'Canada': 1410, 'Tunisia': 1405, 
    'Scotland': 1400,
    # Mid-Low Tier (1300 - 1400)
    'Algeria': 1380, 'Egypt': 1375, 'Bosnia-Herzegovina': 1360, 'Bosnia and Herzegovina': 1360,
    'Saudi Arabia': 1355, 'Qatar': 1350, 'Uzbekistan': 1345, 'Panama': 1340, 
    'South Africa': 1335, 'Cape Verde': 1330, 'Cabo Verde': 1330, 'DR Congo': 1320, 
    'Congo DR': 1320, 'Ghana': 1310, 'Iraq': 1300,
    # Debut/Lower Tier (1200 - 1300)
    'Haiti': 1280, 'Jordan': 1270, 'Curaçao': 1250, 'New Zealand': 1240
}

# Predefined teams confederations
CONFEDERATIONS = {
    'Mexico': 'Concacaf', 'South Korea': 'AFC', 'South Africa': 'CAF', 'Czechia': 'UEFA', 'Czech Republic': 'UEFA',
    'Canada': 'Concacaf', 'Switzerland': 'UEFA', 'Qatar': 'AFC', 'Bosnia-Herzegovina': 'UEFA', 'Bosnia and Herzegovina': 'UEFA',
    'Brazil': 'CONMEBOL', 'Morocco': 'CAF', 'Scotland': 'UEFA', 'Haiti': 'Concacaf',
    'USA': 'Concacaf', 'Paraguay': 'CONMEBOL', 'Australia': 'AFC', 'Türkiye': 'UEFA',
    'Germany': 'UEFA', 'Ecuador': 'CONMEBOL', 'Ivory Coast': 'CAF', "Côte d'Ivoire": 'CAF', 'Curaçao': 'Concacaf',
    'Netherlands': 'UEFA', 'Japan': 'AFC', 'Tunisia': 'CAF', 'Sweden': 'UEFA',
    'Belgium': 'UEFA', 'Iran': 'AFC', 'IR Iran': 'AFC', 'Egypt': 'CAF', 'New Zealand': 'OFC',
    'Spain': 'UEFA', 'Uruguay': 'CONMEBOL', 'Saudi Arabia': 'AFC', 'Cape Verde': 'CAF', 'Cabo Verde': 'CAF',
    'France': 'UEFA', 'Senegal': 'CAF', 'Norway': 'UEFA', 'Iraq': 'AFC',
    'Argentina': 'CONMEBOL', 'Algeria': 'CAF', 'Austria': 'UEFA', 'Jordan': 'AFC',
    'Portugal': 'UEFA', 'Colombia': 'CONMEBOL', 'Uzbekistan': 'AFC', 'DR Congo': 'CAF', 'Congo DR': 'CAF',
    'England': 'UEFA', 'Croatia': 'UEFA', 'Ghana': 'CAF', 'Panama': 'Concacaf'
}

# 2026 FIFA World Ranking as of April 1, 2026 (for prediction and seeding reference)
FIFA_RANKS = {
    'France': 1, 'Spain': 2, 'Argentina': 3, 'England': 4, 'Portugal': 5,
    'Brazil': 6, 'Netherlands': 7, 'Morocco': 8, 'Belgium': 9, 'Germany': 10,
    'Croatia': 11, 'Colombia': 13, 'Senegal': 14, 'Mexico': 15, 'USA': 16,
    'Uruguay': 17, 'Japan': 18, 'Switzerland': 19, 'Iran': 20, 'IR Iran': 20,
    'South Korea': 23, 'Austria': 24, 'Sweden': 25, 'Australia': 26, 
    'Türkiye': 27, 'Turkey': 27, 'Ecuador': 29, 'Norway': 30, 'Egypt': 34, 
    'Panama': 38, 'Ivory Coast': 39, "Côte d'Ivoire": 39, 'Canada': 40, 
    'Tunisia': 41, 'Scotland': 44, 'Paraguay': 45, 'Qatar': 46, 'Algeria': 48, 
    'Iraq': 54, 'Saudi Arabia': 56, 'South Africa': 59, 'Ghana': 60, 
    'DR Congo': 61, 'Congo DR': 61, 'Cape Verde': 64, 'Cabo Verde': 64, 
    'Uzbekistan': 66, 'Jordan': 68, 'Bosnia-Herzegovina': 70, 
    'Bosnia and Herzegovina': 70, 'Curaçao': 82, 'Haiti': 84, 'New Zealand': 86
}

# 2026 host cities -> host nation. A match grants genuine home-field advantage
# ONLY when one of the two teams is the host nation playing inside its own country.
# Every other fixture is played on a neutral ground (the vast majority of the WC).
HOST_CITY_COUNTRY = {
    # Mexico
    'Mexico City': 'Mexico', 'Zapopan': 'Mexico', 'Guadalajara': 'Mexico',
    'Guadalupe': 'Mexico', 'Monterrey': 'Mexico',
    # Canada
    'Toronto': 'Canada', 'Vancouver': 'Canada',
    # USA
    'Arlington': 'USA', 'Atlanta': 'USA', 'East Rutherford': 'USA',
    'Foxborough': 'USA', 'Houston': 'USA', 'Inglewood': 'USA',
    'Kansas City': 'USA', 'Miami Gardens': 'USA', 'Philadelphia': 'USA',
    'Santa Clara': 'USA', 'Seattle': 'USA',
}
HOST_NATIONS = {'USA', 'Canada', 'Mexico'}

def get_home_field_advantage(home_team, away_team, city):
    """Returns the home-field advantage sign from the nominal home team's view:
       +1 if the nominal home team is a host playing at home,
       -1 if the nominal away team is the host playing at home,
        0 for a neutral venue (no host nation involved, or venue unknown)."""
    venue_country = HOST_CITY_COUNTRY.get((city or '').strip())
    if not venue_country:
        return 0
    if home_team == venue_country and home_team in HOST_NATIONS:
        return 1
    if away_team == venue_country and away_team in HOST_NATIONS:
        return -1
    return 0

def log(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')

def normalize_team_name(name):
    name = name.strip()
    mapping = {
        'Czech Republic': 'Czechia',
        'Congo DR': 'DR Congo',
        'IR Iran': 'Iran',
        "Côte d'Ivoire": 'Ivory Coast',
        'Cabo Verde': 'Cape Verde',
        'Bosnia and Herzegovina': 'Bosnia-Herzegovina',
        'Bosnia & Herzegovina': 'Bosnia-Herzegovina',
        # Common Wikipedia/feed variants that previously failed to join the teams
        # table (e.g. Match 23 'Turkey' vs 'United States' fell back to 1400 Elo).
        'Turkey': 'Türkiye',
        'Turkiye': 'Türkiye',
        'United States': 'USA',
        'United States of America': 'USA',
        'Korea Republic': 'South Korea',
        'Republic of Korea': 'South Korea',
        'Korea, South': 'South Korea',
    }
    return mapping.get(name, name)


# Canonical set of the 48 real, confirmed national teams (post-normalization).
# Anything else parsed as a home/away name is presumptively a Wikipedia bracket
# placeholder for an undecided knockout slot ("Winner Match 101", "TBD", ...).
_REAL_TEAM_NAMES = {normalize_team_name(t) for grp in GROUPS_DATA.values() for t in grp}

# Schedule/result columns written by the Wikipedia parse loop below — kept as a
# single list so the snapshot/restore safety net (see _snapshot_schedule /
# _restore_corrupted_schedule) always matches exactly what that INSERT touches.
SCHEDULE_COLS = ('group_or_stage', 'date', 'time', 'home_team', 'away_team',
                  'stadium', 'city', 'score', 'home_goals', 'away_goals', 'status')


def _is_placeholder_team(name):
    """True when `name` isn't one of the 48 real teams — i.e. we don't yet know
    who's actually playing (a still-undecided knockout bracket slot)."""
    return name not in _REAL_TEAM_NAMES


def _snapshot_schedule(db_path):
    """{match_num: {col: value}} snapshot of every fixture's schedule/result
    fields, taken right before force_recreate drops the table.

    Why: Wikipedia's footballbox count/order occasionally shifts mid-tournament
    (editors restructure the article as each round completes — e.g. moving
    finished rounds' tables to a sub-article), which can make the position-based
    box -> match_num mapping (INDEX_TO_MATCH_NUM) misfire for an undecided
    future knockout slot. The one dynamic safety check the parser has (reading
    a "Match N"/"Report N" number off the box itself) only fires once that box
    has a score or report link — a box for a not-yet-played fixture (still
    showing bracket placeholder team names) has neither, so a mapping slip is
    invisible to that check. Observed in production: a run that found 89 boxes
    instead of 104 stamped match #89 (Round of 16) with the Final's own
    placeholder content ('Winner Match 101' vs 'Winner Match 102', dated the
    day the Final is actually scheduled) — and, because the table is fully
    dropped and rebuilt from only the boxes that WERE found, match_num 90-104
    vanished from the database entirely rather than merely being wrong.

    _restore_corrupted_schedule uses this snapshot to detect and undo exactly
    that failure mode after the fresh parse, without touching legitimately
    still-undecided slots (which have never had real teams to fall back to)."""
    snap = {}
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cols = ', '.join(SCHEDULE_COLS)
        for row in con.execute(f"SELECT match_num, {cols} FROM matches"):
            snap[row['match_num']] = {c: row[c] for c in SCHEDULE_COLS}
        con.close()
    except Exception as e:
        log(f"賽程快照失敗(略過,本次無安全網可用): {e}")
    return snap


def _restore_corrupted_schedule(db_path, snapshot, parsed_this_run):
    """Restore the last confirmed-good row (from `snapshot`) for any match_num
    that regressed in this run's fresh Wikipedia parse:
      - Wikipedia produced NOTHING for it this run (its box vanished/shifted
        out of reach entirely), or
      - Wikipedia produced a PLACEHOLDER team name where we previously had BOTH
        real teams on record — a genuine regression, not a slot that has simply
        never had real teams yet (those correctly keep showing the fresh
        placeholder parse: there's nothing better to fall back to).
    Only touches the schedule/result columns (SCHEDULE_COLS); predictions and
    advanced stats for the restored row are recomputed/refilled by the rest of
    the pipeline as usual. Returns the number of fixtures restored."""
    if not snapshot:
        return 0
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    restored = 0
    for mn, old in snapshot.items():
        new = parsed_this_run.get(mn)
        if new is None:
            need_restore = True
        else:
            old_had_real_teams = (not _is_placeholder_team(old['home_team'])
                                   and not _is_placeholder_team(old['away_team']))
            new_is_placeholder = (_is_placeholder_team(new['home_team'])
                                   or _is_placeholder_team(new['away_team']))
            need_restore = old_had_real_teams and new_is_placeholder
        if need_restore:
            cols = ', '.join(SCHEDULE_COLS)
            qs = ', '.join('?' * len(SCHEDULE_COLS))
            cur.execute(
                f"INSERT OR REPLACE INTO matches (match_num, {cols}) VALUES (?, {qs})",
                (mn,) + tuple(old[c] for c in SCHEDULE_COLS))
            restored += 1
            log(f"  賽程安全網還原 #{mn}: {old['home_team']} vs {old['away_team']} "
                f"({old['group_or_stage']}, {old['date']}) — 本次維基解析結果為遺失或退化為佔位文字。")
    con.commit()
    con.close()
    if restored:
        log(f"賽程安全網:共 {restored} 場從同步前快照還原。")
    return restored


def init_db(force_recreate=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if force_recreate:
        log("重新建立資料表以啟用進階預測與 Elo 系統欄位...")
        cursor.execute('DROP TABLE IF EXISTS matches')
        cursor.execute('DROP TABLE IF EXISTS groups')
        cursor.execute('DROP TABLE IF EXISTS teams')
    
    # Create teams table with elo_rating, fifa_rank, pi_rating, and berrar ratings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            confederation TEXT,
            elo_rating REAL NOT NULL DEFAULT 1400.0,
            fifa_rank INTEGER NOT NULL DEFAULT 50,
            pi_rating_home REAL NOT NULL DEFAULT 0.0,
            pi_rating_away REAL NOT NULL DEFAULT 0.0,
            berrar_att REAL NOT NULL DEFAULT 1.0,
            berrar_def REAL NOT NULL DEFAULT 1.0
        )
    ''')
    
    # Dynamic schema migration for existing teams table
    cursor.execute("PRAGMA table_info(teams)")
    cols = [row[1] for row in cursor.fetchall()]
    migration_needed = False
    
    fields_to_add = [
        ("pi_rating_home", "REAL NOT NULL DEFAULT 0.0"),
        ("pi_rating_away", "REAL NOT NULL DEFAULT 0.0"),
        ("berrar_att", "REAL NOT NULL DEFAULT 1.0"),
        ("berrar_def", "REAL NOT NULL DEFAULT 1.0")
    ]
    for col_name, col_def in fields_to_add:
        if col_name not in cols:
            cursor.execute(f"ALTER TABLE teams ADD COLUMN {col_name} {col_def}")
            migration_needed = True
            
    if migration_needed:
        conn.commit()
        log("已動態擴充 teams 資料表，加入 Pi-Rating 與 Berrar 欄位。")
    
    # Create groups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_letter TEXT NOT NULL,
            team_name TEXT NOT NULL,
            FOREIGN KEY (team_name) REFERENCES teams(name)
        )
    ''')
    
    # Create matches table with advanced prediction, pre-match Elo, betting odds, EV and Kelly stake
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_num INTEGER PRIMARY KEY,
            group_or_stage TEXT NOT NULL,
            date TEXT,
            time TEXT,
            home_team TEXT,
            away_team TEXT,
            stadium TEXT,
            city TEXT,
            score TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            status TEXT NOT NULL,
            home_pre_match_elo REAL,
            away_pre_match_elo REAL,
            pred_home_win_prob REAL,
            pred_draw_prob REAL,
            pred_away_win_prob REAL,
            pred_home_expected_goals REAL,
            pred_away_expected_goals REAL,
            pred_score TEXT,
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            ev_home REAL,
            ev_draw REAL,
            ev_away REAL,
            kelly_home REAL,
            kelly_draw REAL,
            kelly_away REAL,
            odds_source TEXT DEFAULT 'unknown',
            odds_last_update DATETIME DEFAULT NULL,
            odds_bookmaker_keys TEXT DEFAULT NULL,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    
    # Seed teams and groups
    for group_letter, teams in GROUPS_DATA.items():
        for team in teams:
            normalized_name = normalize_team_name(team)
            conf = CONFEDERATIONS.get(team, 'Unknown')
            elo = seeded_initial_elo(team)
            rank = FIFA_RANKS.get(team, 50)
            cursor.execute('''
                INSERT OR IGNORE INTO teams 
                (name, confederation, elo_rating, fifa_rank, pi_rating_home, pi_rating_away, berrar_att, berrar_def) 
                VALUES (?, ?, ?, ?, 0.0, 0.0, 1.0, 1.0)
            ''', (normalized_name, conf, elo, rank))
            cursor.execute('INSERT OR IGNORE INTO groups (group_letter, team_name) VALUES (?, ?)', (group_letter, normalized_name))
            
    conn.commit()
    conn.close()
    log("資料庫與 48 支隊伍初始評級及排名載入成功。")

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()

def poisson_pmf(k, lamb):
    if lamb <= 0:
        return 1.0 if k == 0 else 0.0
    return (lamb ** k) * math.exp(-lamb) / math.factorial(k)

def normal_cdf(x):
    # Standard normal cumulative distribution function (CDF) in pure Python
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def calculate_pi_change(home_pi_h, away_pi_a, home_goals, away_goals):
    c = 1.0 / 39.0
    lam = 0.07  # Learning rate
    gamma_factor = 0.7  # Reverse update weight
    d_const = 0.25  # Marginal returns factor
    
    gd_expected = c * (home_pi_h - away_pi_a)
    gd_actual = home_goals - away_goals
    error = gd_actual - gd_expected
    
    psi = 1.0 + d_const * math.log(1.0 + abs(gd_actual))
    
    if gd_actual > 0:
        delta_home_h = psi * lam * error
        delta_away_a = -psi * lam * error * gamma_factor
    elif gd_actual < 0:
        delta_home_h = psi * lam * error * gamma_factor
        delta_away_a = -psi * lam * error
    else:
        delta_home_h = psi * lam * error * 0.5
        delta_away_a = -psi * lam * error * 0.5
        
    return delta_home_h, delta_away_a

def predict_pi_model(home_pi_h, away_pi_a, home_adv_goals=0.0):
    c = 1.0 / 39.0
    sigma = 1.3  # Standard deviation of goal difference
    # home_adv_goals shifts the expected goal difference only on genuine host games.
    gd_expected = c * (home_pi_h - away_pi_a) + home_adv_goals
    
    prob_home = 1.0 - normal_cdf((0.5 - gd_expected) / sigma)
    prob_away = normal_cdf((-0.5 - gd_expected) / sigma)
    prob_draw = normal_cdf((0.5 - gd_expected) / sigma) - normal_cdf((-0.5 - gd_expected) / sigma)
    
    total = prob_home + prob_draw + prob_away
    if total > 0:
        prob_home /= total
        prob_draw /= total
        prob_away /= total
        
    return prob_home, prob_draw, prob_away

def calculate_berrar_change(home_att, away_def, away_att, home_def, home_goals, away_goals):
    K = 0.08  # SGD learning rate
    # Neutral baseline: home-field advantage is modelled separately (Elo/Pi),
    # so the rating-update expectation must stay symmetric to avoid biasing
    # attack/defence ratings on neutral-venue games.
    avg_home = 1.25
    avg_away = 1.25
    
    lambda_home = avg_home * home_att * away_def
    lambda_away = avg_away * away_att * home_def
    
    err_home = home_goals - lambda_home
    err_away = away_goals - lambda_away
    
    delta_home_att = K * err_home
    delta_away_def = K * err_home
    
    delta_away_att = K * err_away
    delta_home_def = K * err_away
    
    return delta_home_att, delta_away_def, delta_away_att, delta_home_def

def predict_berrar_model(home_att, away_def, away_att, home_def):
    # Symmetric neutral baseline (home advantage handled in the Elo/Pi models).
    avg_home = 1.25
    avg_away = 1.25
    
    lambda_home = avg_home * home_att * away_def
    lambda_away = avg_away * away_att * home_def
    
    prob_home = 0.0
    prob_draw = 0.0
    prob_away = 0.0
    
    for h in range(8):
        h_prob = poisson_pmf(h, lambda_home)
        for a in range(8):
            a_prob = poisson_pmf(a, lambda_away)
            joint = h_prob * a_prob
            if h > a:
                prob_home += joint
            elif h == a:
                prob_draw += joint
            else:
                prob_away += joint
                
    total = prob_home + prob_draw + prob_away
    if total > 0:
        prob_home /= total
        prob_draw /= total
        prob_away /= total
        
    return prob_home, prob_draw, prob_away, lambda_home, lambda_away

def predict_dixon_coles_model(lambda_home, lambda_away, rho=None):
    if rho is None:
        rho = CFG.RHO
    prob_home = 0.0
    prob_draw = 0.0
    prob_away = 0.0
    
    max_prob = -1.0
    best_score = "0-0"
    # Track the most likely exact score *within each outcome class* so the caller can
    # report a scoreline consistent with the predicted 1X2 winner (avoids the
    # "winner=home but score=1-1" contradiction and the global collapse toward 1-1).
    modal_by_outcome = {'home': (None, "1-0"), 'draw': (None, "1-1"), 'away': (None, "0-1")}

    for h in range(8):
        h_prob = poisson_pmf(h, lambda_home)
        for a in range(8):
            a_prob = poisson_pmf(a, lambda_away)
            joint = h_prob * a_prob

            # Dixon-Coles tau adjustment
            tau = 1.0
            if h == 0 and a == 0:
                tau = 1.0 - lambda_home * lambda_away * rho
            elif h == 1 and a == 0:
                tau = 1.0 + lambda_away * rho
            elif h == 0 and a == 1:
                tau = 1.0 + lambda_home * rho
            elif h == 1 and a == 1:
                tau = 1.0 - rho

            joint *= max(0.0, tau)

            if h > a:
                prob_home += joint
                key = 'home'
            elif h == a:
                prob_draw += joint
                key = 'draw'
            else:
                prob_away += joint
                key = 'away'

            if joint > (modal_by_outcome[key][0] or -1.0):
                modal_by_outcome[key] = (joint, f"{h}-{a}")

            if joint > max_prob:
                max_prob = joint
                best_score = f"{h}-{a}"

    total = prob_home + prob_draw + prob_away
    if total > 0:
        prob_home /= total
        prob_draw /= total
        prob_away /= total

    modal_scores = {k: v[1] for k, v in modal_by_outcome.items()}
    return prob_home, prob_draw, prob_away, best_score, modal_scores

def predict_opta_model(home_opta, away_opta):
    """Derives a single-match 1X2 prior from the Opta supercomputer tournament-win
    probabilities. This is the only genuinely independent opinion in the ensemble
    (the Elo/Pi/Berrar models all derive from the same in-house strength tiers),
    so it is folded in as a separate vote rather than baked into the Elo input.

    Returns None when either side is not covered by Opta (default ~0.001), in which
    case the caller renormalises the remaining models.
    """
    if not home_opta or not away_opta or home_opta < 0.002 or away_opta < 0.002:
        return None
    r = home_opta / (home_opta + away_opta)
    # Draw mass peaks (~0.30) for evenly matched sides and vanishes for blowouts.
    prob_draw = 0.30 * (1.0 - abs(2.0 * r - 1.0))
    prob_home = (1.0 - prob_draw) * r
    prob_away = (1.0 - prob_draw) * (1.0 - r)
    return prob_home, prob_draw, prob_away

def predict_match(home_elo, away_elo, home_pi_h, away_pi_a, home_att, away_def, away_att, home_def,
                  home_rank=50, away_rank=50,
                  home_xg_diff=0.0, home_injuries=0, home_sentiment=0.0,
                  away_xg_diff=0.0, away_injuries=0, away_sentiment=0.0,
                  home_adv=0, home_opta=0.0, away_opta=0.0,
                  completion_ratio=0.0, is_knockout=False):
    """
    Ensemble Predictive Brain: Combines Model A (Elo Poisson), Model B (Pi Normal CDF),
    Model C (Berrar Poisson), and Model D (Dixon-Coles Joint Model with Hybrid Lambda)
    to output highly calibrated win/draw/loss probabilities.

    All tunable constants come from model_config.CFG so backtest.py can calibrate them.
    """
    # Home-field advantage is only ever non-zero on genuine host games.
    HOME_ADV_ELO = CFG.HOME_ADV_ELO
    HOME_ADV_GOALS = CFG.HOME_ADV_GOALS

    # 1. Elo Model (Model A)
    elo_diff = home_elo - away_elo
    rank_diff = away_rank - home_rank

    # 外部情報動態修正 Elo (#5: sentiment weight defaults to 0 — dead feature).
    # xG-diff is collinear with Elo/FIFA-rank, so its weight is kept modest.
    home_correction = (home_xg_diff * CFG.W_XG) + (home_sentiment * CFG.W_SENTIMENT) - (home_injuries * CFG.W_INJURY)
    away_correction = (away_xg_diff * CFG.W_XG) + (away_sentiment * CFG.W_SENTIMENT) - (away_injuries * CFG.W_INJURY)

    effective_elo = elo_diff + (rank_diff * CFG.RANK_WEIGHT) + home_correction - away_correction + (home_adv * HOME_ADV_ELO)

    # #7 Separate home/away baselines + calibratable spread => modal scores vary
    # instead of collapsing to 1-1 everywhere.
    lambda_elo_home = CFG.LAMBDA_BASE_HOME * (10 ** (effective_elo / CFG.LAMBDA_DIVISOR))
    lambda_elo_away = CFG.LAMBDA_BASE_AWAY * (10 ** (-effective_elo / CFG.LAMBDA_DIVISOR))
    
    p_elo_h, p_elo_d, p_elo_a = 0.0, 0.0, 0.0
    for h in range(8):
        h_prob = poisson_pmf(h, lambda_elo_home)
        for a in range(8):
            a_prob = poisson_pmf(a, lambda_elo_away)
            joint = h_prob * a_prob
            if h > a: p_elo_h += joint
            elif h == a: p_elo_d += joint
            else: p_elo_a += joint
            
    total_elo = p_elo_h + p_elo_d + p_elo_a
    if total_elo > 0:
        p_elo_h /= total_elo
        p_elo_d /= total_elo
        p_elo_a /= total_elo
        
    # 2. Pi-Rating Model (Model B)
    p_pi_h, p_pi_d, p_pi_a = predict_pi_model(home_pi_h, away_pi_a, home_adv * HOME_ADV_GOALS)

    # 3. Berrar Model (Model C)
    p_ber_h, p_ber_d, p_ber_a, lambda_b_home, lambda_b_away = predict_berrar_model(home_att, away_def, away_att, home_def)

    # 4. Dixon-Coles Model with Hybrid Lambdas (Model D)
    lambda_mix_home = 0.5 * lambda_elo_home + 0.5 * lambda_b_home
    lambda_mix_away = 0.5 * lambda_elo_away + 0.5 * lambda_b_away
    p_dc_h, p_dc_d, p_dc_a, best_score, dc_modal_scores = predict_dixon_coles_model(lambda_mix_home, lambda_mix_away)

    # 5. Opta supercomputer prior (Model E) — independent external opinion
    p_opta = predict_opta_model(home_opta, away_opta)

    # 6. Ensemble Weighted Fusion
    if p_opta is not None:
        p_op_h, p_op_d, p_op_a = p_opta
        # #4 Dynamic weighting: interpolate early(prior-heavy)->late(model-heavy).
        if CFG.DYNAMIC_WEIGHTS:
            r = max(0.0, min(1.0, completion_ratio))
            w = [e * (1.0 - r) + l * r for e, l in zip(CFG.W_EARLY, CFG.W_LATE)]
            sw = sum(w) or 1.0
            w = [x / sw for x in w]
        else:
            w = CFG.W_ENSEMBLE_OPTA
        we, wp, wb, wd, wo = w
        final_h = we * p_elo_h + wp * p_pi_h + wb * p_ber_h + wd * p_dc_h + wo * p_op_h
        final_d = we * p_elo_d + wp * p_pi_d + wb * p_ber_d + wd * p_dc_d + wo * p_op_d
        final_a = we * p_elo_a + wp * p_pi_a + wb * p_ber_a + wd * p_dc_a + wo * p_op_a
    else:
        # Opta not available for this fixture: drop the Opta term and renormalise.
        we, wp, wb, wd = CFG.W_ENSEMBLE_NOOPTA
        final_h = we * p_elo_h + wp * p_pi_h + wb * p_ber_h + wd * p_dc_h
        final_d = we * p_elo_d + wp * p_pi_d + wb * p_ber_d + wd * p_dc_d
        final_a = we * p_elo_a + wp * p_pi_a + wb * p_ber_a + wd * p_dc_a

    # #2 Draw calibration: footballs draws (~25%) were systematically under-pointed
    # (0/104 fixtures had draw as argmax). Inflate draw mass then renormalise.
    final_d *= CFG.DRAW_INFLATION
    # Knockout games are cagier over 90' (the prediction target) — see the
    # KO_DRAW_INFLATION rationale in model_config.py.
    if is_knockout:
        final_d *= CFG.KO_DRAW_INFLATION

    final_sum = final_h + final_d + final_a
    if final_sum > 0:
        final_h /= final_sum
        final_d /= final_sum
        final_a /= final_sum
        
    # Report a scoreline consistent with the ENSEMBLE's most likely outcome, not the
    # standalone Dixon-Coles global argmax (which collapsed toward 1-1 and could
    # contradict the predicted winner). Pick the modal exact score within the winning class.
    if final_h >= final_d and final_h >= final_a:
        predicted_score = dc_modal_scores['home']
    elif final_a >= final_d and final_a >= final_h:
        predicted_score = dc_modal_scores['away']
    else:
        predicted_score = dc_modal_scores['draw']

    return {
        'home_expected_goals': lambda_mix_home,
        'away_expected_goals': lambda_mix_away,
        'home_win_prob': final_h,
        'draw_prob': final_d,
        'away_win_prob': final_a,
        'predicted_score': predicted_score
    }

def mov_multiplier(goal_diff, elo_diff):
    """World-Football-Elo margin-of-victory multiplier (#3).
    Bigger wins move ratings more; a damping term keeps a strong favourite's big
    win from over-inflating its rating (Hjorth-Goldberg standard)."""
    gd = abs(goal_diff)
    if gd <= 1:
        g = 1.0
    elif gd == 2:
        g = 1.5
    else:
        g = (11.0 + gd) / 8.0
    # Damp by how expected the result was (winner perspective).
    damp = 2.0 / (2.0 + 0.001 * (elo_diff if goal_diff > 0 else -elo_diff))
    return g * damp


def calculate_elo_change(home_elo, away_elo, home_goals, away_goals):
    # Base K-factor for World Cup matches (calibratable via model_config).
    K = CFG.ELO_K

    # Expected result based on Elo difference
    E_home = 1.0 / (1.0 + 10 ** ((away_elo - home_elo) / 400.0))
    E_away = 1.0 / (1.0 + 10 ** ((home_elo - away_elo) / 400.0))

    # Actual score
    if home_goals > away_goals:
        S_home, S_away = 1.0, 0.0
    elif home_goals < away_goals:
        S_home, S_away = 0.0, 1.0
    else:
        # Draw
        S_home, S_away = 0.5, 0.5

    # #3 Margin-of-victory scaling: a blowout shifts ratings more than a 1-0.
    g = mov_multiplier(home_goals - away_goals, home_elo - away_elo) if CFG.ELO_MOV_ENABLED else 1.0

    delta_home = K * g * (S_home - E_home)
    delta_away = K * g * (S_away - E_away)

    return delta_home, delta_away

def update_ev_and_kelly(match_data):
    """
    Given match predictions and odds, calculates the Expected Value (EV) and Kelly stake sizes.
    """
    prob_home = match_data['pred_home_win_prob']
    prob_draw = match_data['pred_draw_prob']
    prob_away = match_data['pred_away_win_prob']
    
    odds_h = match_data['odds_home']
    odds_d = match_data['odds_draw']
    odds_a = match_data['odds_away']
    
    results = {
        'ev_home': None, 'ev_draw': None, 'ev_away': None,
        'kelly_home': None, 'kelly_draw': None, 'kelly_away': None
    }
    
    if odds_h and odds_h > 1.0 and prob_home:
        ev = (prob_home * odds_h) - 1.0
        results['ev_home'] = ev
        results['kelly_home'] = max(0.0, ev / (odds_h - 1.0)) if ev > 0 else 0.0
        
    if odds_d and odds_d > 1.0 and prob_draw:
        ev = (prob_draw * odds_d) - 1.0
        results['ev_draw'] = ev
        results['kelly_draw'] = max(0.0, ev / (odds_d - 1.0)) if ev > 0 else 0.0
        
    if odds_a and odds_a > 1.0 and prob_away:
        ev = (prob_away * odds_a) - 1.0
        results['ev_away'] = ev
        results['kelly_away'] = max(0.0, ev / (odds_a - 1.0)) if ev > 0 else 0.0
        
    return results

def reset_and_recalculate_all_elo_and_predictions():
    """
    To ensure math integrity, we reset all teams to initial Elo, Pi-Ratings (0.0), 
    and Berrar Ratings (Att=1.0, Def=1.0), and chronologically process matches 
    in match_num order, updating all rating systems and generating ensemble predictions.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Reset team ratings in DB to initial states (data-driven seeds when available)
    for team in INITIAL_ELO:
        normalized_name = normalize_team_name(team)
        elo = seeded_initial_elo(team)
        cursor.execute('''
            UPDATE teams
            SET elo_rating = ?, pi_rating_home = 0.0, pi_rating_away = 0.0, berrar_att = 1.0, berrar_def = 1.0
            WHERE name = ?
        ''', (elo, normalized_name))
    conn.commit()
    
    # 2. Get all matches sorted by match_num
    cursor.execute('SELECT * FROM matches ORDER BY match_num ASC')
    # Column names mapping
    colnames = [description[0] for description in cursor.description]
    matches = [dict(zip(colnames, row)) for row in cursor.fetchall()]
    
    log(f"正在重算資料庫中所有 {len(matches)} 場比賽的動態 Elo、Pi-Rating、Berrar 與卜瓦松/Dixon-Coles 集成勝率預測...")

    # #4 Tournament completion ratio drives dynamic ensemble weighting.
    _real = [m for m in matches if m.get('status') in ('Completed', 'Scheduled')]
    _done = [m for m in _real if m.get('status') == 'Completed']
    completion_ratio = (len(_done) / len(_real)) if _real else 0.0

    for match in matches:
        match_num = match['match_num']
        home = normalize_team_name(match['home_team'])
        away = normalize_team_name(match['away_team'])
        status = match['status']
        
        # Check if they are valid national teams (not placeholders like "Winner Group A")
        cursor.execute('SELECT elo_rating, fifa_rank, pi_rating_home, pi_rating_away, berrar_att, berrar_def, fbref_xg_diff, injury_count, sentiment_score, opta_win_prob FROM teams WHERE name = ?', (home,))
        row_home = cursor.fetchone()
        cursor.execute('SELECT elo_rating, fifa_rank, pi_rating_home, pi_rating_away, berrar_att, berrar_def, fbref_xg_diff, injury_count, sentiment_score, opta_win_prob FROM teams WHERE name = ?', (away,))
        row_away = cursor.fetchone()
        
        home_elo = row_home[0] if row_home else 1400.0
        home_rank = row_home[1] if row_home else 50
        home_pi_h = row_home[2] if row_home else 0.0
        home_pi_a = row_home[3] if row_home else 0.0
        home_att = row_home[4] if row_home else 1.0
        home_def = row_home[5] if row_home else 1.0
        home_xg_diff = row_home[6] if (row_home and len(row_home) > 6) else 0.0
        home_injuries = row_home[7] if (row_home and len(row_home) > 7) else 0
        home_sentiment = row_home[8] if (row_home and len(row_home) > 8) else 0.0
        home_opta = row_home[9] if (row_home and len(row_home) > 9) else 0.0

        away_elo = row_away[0] if row_away else 1400.0
        away_rank = row_away[1] if row_away else 50
        away_pi_h = row_away[2] if row_away else 0.0
        away_pi_a = row_away[3] if row_away else 0.0
        away_att = row_away[4] if row_away else 1.0
        away_def = row_away[5] if row_away else 1.0
        away_xg_diff = row_away[6] if (row_away and len(row_away) > 6) else 0.0
        away_injuries = row_away[7] if (row_away and len(row_away) > 7) else 0
        away_sentiment = row_away[8] if (row_away and len(row_away) > 8) else 0.0
        away_opta = row_away[9] if (row_away and len(row_away) > 9) else 0.0

        # Genuine home-field advantage only on host-nation games at home venues.
        home_adv = get_home_field_advantage(home, away, match.get('city'))

        # Write pre-match Elo into matches
        cursor.execute('''
            UPDATE matches 
            SET home_pre_match_elo = ?, away_pre_match_elo = ? 
            WHERE match_num = ?
        ''', (home_elo, away_elo, match_num))
        
        # Calculate prediction with ensemble predictive brain
        pred = predict_match(home_elo, away_elo, home_pi_h, away_pi_a, home_att, away_def, away_att, home_def, home_rank, away_rank,
                             home_xg_diff, home_injuries, home_sentiment,
                             away_xg_diff, away_injuries, away_sentiment,
                             home_adv, home_opta, away_opta, completion_ratio,
                             is_knockout=not str(match.get('group_or_stage') or '').startswith('Group'))
        
        # Calculate EV and Kelly if odds exist in current record
        odds_h = match['odds_home']
        odds_d = match['odds_draw']
        odds_a = match['odds_away']
        
        betting_data = {
            'pred_home_win_prob': pred['home_win_prob'],
            'pred_draw_prob': pred['draw_prob'],
            'pred_away_win_prob': pred['away_win_prob'],
            'odds_home': odds_h,
            'odds_draw': odds_d,
            'odds_away': odds_a
        }
        ev_kelly = update_ev_and_kelly(betting_data)
        
        if status == 'Completed' and row_home and row_away:
            # Match is completed, run actual Elo, Pi-Rating, and Berrar updates!
            home_goals = match['home_goals']
            away_goals = match['away_goals']
            
            # 1. Elo Change
            delta_elo_h, delta_elo_a = calculate_elo_change(home_elo, away_elo, home_goals, away_goals)
            new_home_elo = home_elo + delta_elo_h
            new_away_elo = away_elo + delta_elo_a
            
            # 2. Pi-Rating Change
            delta_pi_h, delta_pi_a = calculate_pi_change(home_pi_h, away_pi_a, home_goals, away_goals)
            new_home_pi_h = home_pi_h + delta_pi_h
            new_away_pi_a = away_pi_a + delta_pi_a
            
            # 3. Berrar Rating Change
            d_h_att, d_a_def, d_a_att, d_h_def = calculate_berrar_change(
                home_att, away_def, away_att, home_def, home_goals, away_goals
            )
            new_home_att = max(0.1, home_att + d_h_att)
            new_away_def = max(0.1, away_def + d_a_def)
            new_away_att = max(0.1, away_att + d_a_att)
            new_home_def = max(0.1, home_def + d_h_def)
            
            # Update teams table
            cursor.execute('''
                UPDATE teams 
                SET elo_rating = ?, pi_rating_home = ?, berrar_att = ?, berrar_def = ? 
                WHERE name = ?
            ''', (new_home_elo, new_home_pi_h, new_home_att, new_home_def, home))
            
            cursor.execute('''
                UPDATE teams 
                SET elo_rating = ?, pi_rating_away = ?, berrar_att = ?, berrar_def = ? 
                WHERE name = ?
            ''', (new_away_elo, new_away_pi_a, new_away_att, new_away_def, away))
            
            # Keep match predictions, but set EV and Kelly to NULL as match is already completed
            cursor.execute('''
                UPDATE matches 
                SET pred_home_win_prob = ?, pred_draw_prob = ?, pred_away_win_prob = ?,
                    pred_home_expected_goals = ?, pred_away_expected_goals = ?, pred_score = ?,
                    ev_home = NULL, ev_draw = NULL, ev_away = NULL,
                    kelly_home = NULL, kelly_draw = NULL, kelly_away = NULL
                WHERE match_num = ?
            ''', (pred['home_win_prob'], pred['draw_prob'], pred['away_win_prob'],
                  pred['home_expected_goals'], pred['away_expected_goals'], pred['predicted_score'],
                  match_num))
        else:
            # Match is scheduled/live, update prediction results, EV and Kelly
            cursor.execute('''
                UPDATE matches 
                SET pred_home_win_prob = ?, pred_draw_prob = ?, pred_away_win_prob = ?,
                    pred_home_expected_goals = ?, pred_away_expected_goals = ?, pred_score = ?,
                    ev_home = ?, ev_draw = ?, ev_away = ?,
                    kelly_home = ?, kelly_draw = ?, kelly_away = ?
                WHERE match_num = ?
            ''', (pred['home_win_prob'], pred['draw_prob'], pred['away_win_prob'],
                  pred['pred_home_expected_goals'] if 'pred_home_expected_goals' in pred else pred['home_expected_goals'], 
                  pred['pred_away_expected_goals'] if 'pred_away_expected_goals' in pred else pred['away_expected_goals'], 
                  pred['predicted_score'] if 'predicted_score' in pred else pred['pred_score'],
                  ev_kelly['ev_home'], ev_kelly['ev_draw'], ev_kelly['ev_away'],
                  ev_kelly['kelly_home'], ev_kelly['kelly_draw'], ev_kelly['kelly_away'],
                  match_num))
            
    conn.commit()
    conn.close()
    log("資料庫中所有賽事的動態評級與集成預測重新計算完成！")

def _snapshot_stat_cols(db_path):
    """Advanced per-match stats (xG family, from 365Scores) and score-source
    provenance live in `matches`, which force_recreate drops every sync. They
    used to be refilled from the live feed each run — so one source hiccup
    silently wiped every stored stat (observed: 0/88 completed games had xG).
    Snapshot them before the rebuild and restore after, same idea as
    manual_results for scores. Returns {match_num: {col: value}}."""
    cols = ('home_xg', 'away_xg', 'home_possession', 'away_possession',
            'home_shots', 'away_shots', 'home_xgot', 'away_xgot',
            'home_sot', 'away_sot', 'home_corners', 'away_corners',
            'home_big_chances', 'away_big_chances', 'score_source')
    snap = {}
    try:
        con = sqlite3.connect(db_path)
        have = {r[1] for r in con.execute('PRAGMA table_info(matches)')}
        keep = [c for c in cols if c in have]
        if keep:
            for row in con.execute(
                    f"SELECT match_num, {', '.join(keep)} FROM matches"):
                vals = {c: v for c, v in zip(keep, row[1:]) if v is not None}
                if vals:
                    snap[row[0]] = vals
        con.close()
    except Exception as e:
        log(f"統計快照失敗(略過,將由 365Scores 重填): {e}")
    return snap


def _restore_stat_cols(db_path, snap):
    if not snap:
        return
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        have = {r[1] for r in cur.execute('PRAGMA table_info(matches)')}
        for col in ('home_xg', 'away_xg', 'home_possession', 'away_possession',
                    'home_shots', 'away_shots', 'home_xgot', 'away_xgot',
                    'home_sot', 'away_sot', 'home_corners', 'away_corners',
                    'home_big_chances', 'away_big_chances'):
            if col not in have:
                cur.execute(f'ALTER TABLE matches ADD COLUMN {col} REAL')
        if 'score_source' not in have:
            cur.execute('ALTER TABLE matches ADD COLUMN score_source TEXT')
        n = 0
        for mn, vals in snap.items():
            sets = ', '.join(f'{c}=?' for c in vals)
            cur.execute(f'UPDATE matches SET {sets} WHERE match_num=?',
                        tuple(vals.values()) + (mn,))
            n += cur.rowcount
        con.commit()
        con.close()
        log(f"已還原 {len(snap)} 場的進階統計(跨重建持久化)。")
    except Exception as e:
        log(f"統計還原失敗: {e}")


def parse_and_sync():
    # Preserve advanced stats and the confirmed schedule/bracket across the
    # destructive rebuild below (see _snapshot_schedule for why the latter matters).
    _stat_snapshot = _snapshot_stat_cols(DB_PATH)
    _schedule_snapshot = _snapshot_schedule(DB_PATH)
    # Make sure advanced database is initialized
    init_db(force_recreate=True)
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/2026_FIFA_World_Cup'
    
    log("正在從維基百科獲取 2026 FIFA 世界盃最新賽程與比分...")
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        log(f"連線維基百科失敗: {e}")
        return
        
    s = BeautifulSoup(r.text, 'html.parser')
    boxes = s.find_all('div', class_='footballbox')
    
    if len(boxes) != 104:
        log(f"警告: 預期有 104 場比賽，但網頁上解析到 {len(boxes)} 場。將會盡量解析。")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    inserted_count = 0
    _parsed_this_run = {}  # match_num -> {'home_team', 'away_team'}, for the schedule safety net

    for i, box in enumerate(boxes):
        # Fallback mapping
        match_num = INDEX_TO_MATCH_NUM.get(i)
        
        # Try dynamic parsing of match number as secondary validation
        score_el = box.find(class_='fscore')
        score_txt = clean_text(score_el.get_text()) if score_el else ""
        
        m_score = re.search(r'Match\s+(\d+)', score_txt)
        fgoals = box.find(class_='fgoals')
        goals_txt = clean_text(fgoals.get_text()) if fgoals else ""
        m_report = re.search(r'Report\s+(\d+)', goals_txt)
        
        if m_report:
            match_num = int(m_report.group(1))
        elif m_score:
            match_num = int(m_score.group(1))
            
        if not match_num:
            log(f"無法識別索引 {i} 的場次編號，跳過此場。")
            continue
            
        # Parse teams
        home_el = box.find(class_='fhome')
        away_el = box.find(class_='faway')
        home_team = clean_text(home_el.get_text()) if home_el else ""
        away_team = clean_text(away_el.get_text()) if away_el else ""
        
        # Normalize names
        home_team = normalize_team_name(home_team)
        away_team = normalize_team_name(away_team)
        _parsed_this_run[match_num] = {'home_team': home_team, 'away_team': away_team}


        # Parse date and time
        date_el = box.find(class_='fdate')
        time_el = box.find(class_='ftime')
        
        # Clean date text
        date_txt = clean_text(date_el.get_text()) if date_el else ""
        m_date = re.search(r'\((\d{4}-\d{2}-\d{2})\)', date_txt)
        if m_date:
            match_date = m_date.group(1)
        else:
            match_date = date_txt
            
        match_time = clean_text(time_el.get_text()) if time_el else ""
        
        # Parse location (stadium and city)
        location_div = box.find(class_='fright')
        location_txt = clean_text(location_div.get_text()) if location_div else ""
        stadium, city = "", ""
        if "," in location_txt:
            parts = location_txt.split(",", 1)
            stadium = parts[0].strip()
            city = parts[1].strip()
        else:
            stadium = location_txt
            
        # Determine group or stage
        if match_num <= 72:
            group_letter = "Group"
            for g, tm_list in GROUPS_DATA.items():
                normalized_list = [normalize_team_name(t) for t in tm_list]
                if home_team in normalized_list or away_team in normalized_list:
                    group_letter = f"Group {g}"
                    break
            group_or_stage = group_letter
        elif match_num <= 88:
            group_or_stage = "Round of 32"
        elif match_num <= 96:
            group_or_stage = "Round of 16"
        elif match_num <= 100:
            group_or_stage = "Quarter-finals"
        elif match_num <= 102:
            group_or_stage = "Semi-finals"
        elif match_num == 103:
            group_or_stage = "Third-place play-off"
        elif match_num == 104:
            group_or_stage = "Final"
        else:
            group_or_stage = "Knockout"
            
        # Parse score & status
        home_goals = None
        away_goals = None
        status = "Scheduled"
        
        score_cleaned = score_txt.replace('\u2013', '-').replace('\u2212', '-').replace(' ', '')
        
        if "Match" in score_txt or not score_cleaned or score_cleaned.lower() == 'v':
            score_db = f"Match {match_num}"
        else:
            score_db = score_txt
            # Extract goals
            m_score_parse = re.match(r'^(\d+)-(\d+)', score_cleaned)
            if m_score_parse:
                home_goals = int(m_score_parse.group(1))
                away_goals = int(m_score_parse.group(2))
                status = "Completed"
                # 預測標的是「正賽 90 分鐘」的勝/平/負。淘汰賽會踢延長賽 ⟺ 90 分鐘
                # 必為平局,而維基 footballbox 對這類場次顯示的是「延長賽後」總比分
                # (如 3–2 (a.e.t.))。若直接沿用,模型會把 90 分鐘平局的比賽當勝負
                # 去更新 Elo/Pi/Berrar 與準確度,污染所有評級。90 分鐘確切比分無法
                # 從文字得知,但必為 X–X 且 X ≤ min(進球數),取 min 為最合理近似;
                # 對模型最關鍵的「結果=和、淨勝=0」則是精確的。score 文字保留原樣
                # 供顯示,只正規化進球數欄位。
                if re.search(r'a\.?\s*e\.?\s*t|pen', score_txt, re.IGNORECASE):
                    g90 = min(home_goals, away_goals)
                    home_goals = away_goals = g90
            else:
                status = "Completed" # Fallback
                
        # Initially insert all matches into SQLite
        cursor.execute('''
            INSERT OR REPLACE INTO matches (
                match_num, group_or_stage, date, time, home_team, away_team, 
                stadium, city, score, home_goals, away_goals, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (match_num, group_or_stage, match_date, match_time, home_team, away_team, 
              stadium, city, score_db, home_goals, away_goals, status))
        inserted_count += 1
            
    conn.commit()
    conn.close()
    
    log(f"成功爬取並寫入 {inserted_count} 場基礎賽事數據到資料庫。")

    # Undo any fixture that regressed to a missing row or placeholder bracket
    # text this run (see _snapshot_schedule for why this can happen).
    _restore_corrupted_schedule(DB_PATH, _schedule_snapshot, _parsed_this_run)

    # Restore the advanced stats snapshotted before the rebuild (365Scores then
    # only needs to top up genuinely new games instead of refilling everything).
    _restore_stat_cols(DB_PATH, _stat_snapshot)

    # 執行第二階段模型先驗與 Reddit 輿情同步；非即時 FBref/SofaScore/Opta 抓取。
    try:
        log("正在同步第二階段模型先驗與 Reddit 輿情...")
        import subprocess
        subprocess.run(["python", "external_intelligence.py"], check=True)
    except Exception as e:
        log(f"同步模型先驗與 Reddit 輿情失敗: {e}，將使用現有的資料庫快取數據。")

    # Re-apply persistent manual score overrides that Wikipedia has not yet reflected,
    # so manual updates survive the daily force_recreate (official scores still win).
    try:
        import manual_results
        _oc = sqlite3.connect(DB_PATH)
        _n = manual_results.apply_overrides(_oc, respect_existing=True)
        _oc.close()
        if _n:
            log(f"已套用 {_n} 筆手動賽果覆蓋(維基尚無官方比分的場次)。")
    except Exception as e:
        log(f"套用手動賽果覆蓋時發生錯誤: {e}")

    # Run the comprehensive dynamic recalculation engine (Elo rating history and predictions)
    reset_and_recalculate_all_elo_and_predictions()

if __name__ == '__main__':
    log("開始執行 2026 FIFA 賽程、預測與 Elo 自動更新同步任務...")
    parse_and_sync()
    
    # Proactively trigger odds crawler to sync odds at the same time
    try:
        log("正在觸發即時賠率爬蟲，同步各大博弈平台即時賠率...")
        import subprocess
        subprocess.run(["python", "odds_crawler.py"], check=True)
        log("即時賠率與博弈分析值更新成功！")
    except Exception as e:
        log(f"自動執行賠率爬蟲時發生錯誤: {e}")

    # Roll the daily champion (title-race) prediction: market + Opta + AI Monte Carlo.
    try:
        log("正在計算每日總冠軍預測（賭盤 + Opta + AI 蒙地卡羅）...")
        import champion_predictor
        champion_predictor.run_champion_prediction()
        log("總冠軍奪冠機率每日快照更新成功！")
        # Regenerate the auto trend report from the rolling snapshots.
        import champion_trend_report
        champion_trend_report.main()
    except Exception as e:
        log(f"自動執行總冠軍預測時發生錯誤: {e}")

    log("同步任務結束。")

