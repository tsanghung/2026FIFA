"""
backtest.py — historical calibration & accuracy-evaluation harness (#1, #2, #6, #8).

What it does
------------
1. Loads ~50k historical international results (martj42/international_results).
2. Replays them chronologically through the SAME rating engine used in production
   (Elo + Pi + Berrar from sync_fifa.py), so there is zero model drift between
   what we evaluate here and what ships.
3. At every match inside the evaluation window it snapshots the pre-match rating
   state + the real outcome, then scores the ensemble with:
       - RPS  (Ranked Probability Score — the proper metric for ordered 1X2)
       - log-loss, Brier, argmax accuracy, and DRAW recall (the metric the old
         model scored 0 on: it never predicted a draw).
4. Coordinate-descends the prediction parameters (draw inflation, home advantage,
   lambda baselines/spread, Dixon-Coles rho, ensemble weights) to minimise RPS,
   and writes the winners to `calibrated_params.json` (loaded by model_config).
5. Writes `backtest_metrics.json` (baseline vs calibrated) for the app's accuracy
   tab, and `team_ratings_seed.json` — data-driven current Elo for the 48 World
   Cup teams, replacing the hand-typed INITIAL_ELO seeds (#6).

Run:  python backtest.py
"""

import os
import csv
import json
import math
import urllib.request

import sync_fifa as eng
from model_config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, 'historical_results.csv')
CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CALIB_PATH = os.path.join(HERE, 'calibrated_params.json')
METRICS_PATH = os.path.join(HERE, 'backtest_metrics.json')
SEED_PATH = os.path.join(HERE, 'team_ratings_seed.json')

EVAL_START = "2016-01-01"   # record/score matches from here; ratings still warm up on all prior history


def ensure_csv():
    if not os.path.exists(CSV_PATH):
        print(f"下載歷史國際賽資料 ... {CSV_URL}")
        urllib.request.urlretrieve(CSV_URL, CSV_PATH)
    return CSV_PATH


def load_matches():
    rows = []
    with open(ensure_csv(), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                hg, ag = int(r['home_score']), int(r['away_score'])
            except (ValueError, KeyError, TypeError):
                continue
            rows.append((r['date'], r['home_team'].strip(), r['away_team'].strip(),
                         hg, ag, (r.get('neutral', 'FALSE').upper() == 'TRUE')))
    rows.sort(key=lambda x: x[0])
    return rows


class Ratings:
    """Per-team rating store mirroring the teams-table fields."""
    def __init__(self):
        self.elo, self.pi_h, self.pi_a, self.att, self.df = {}, {}, {}, {}, {}

    def get(self, t):
        if t not in self.elo:
            self.elo[t] = 1500.0
            self.pi_h[t] = 0.0
            self.pi_a[t] = 0.0
            self.att[t] = 1.0
            self.df[t] = 1.0
        return t


def outcome(hg, ag):
    return 'H' if hg > ag else ('A' if ag > hg else 'D')


def predict_probs(s):
    """Run the production ensemble on a snapshot dict (Opta absent -> 4-model path)."""
    p = eng.predict_match(
        s['eh'], s['ea'], s['ph'], s['pa'], s['ath'], s['dfa'], s['ata'], s['dfh'],
        home_rank=50, away_rank=50, home_adv=s['adv'], home_opta=0.0, away_opta=0.0)
    return p['home_win_prob'], p['draw_prob'], p['away_win_prob']


def rps(ph, pd, pa, actual):
    o = {'H': (1, 0, 0), 'D': (0, 1, 0), 'A': (0, 0, 1)}[actual]
    cP = [ph, ph + pd]
    cO = [o[0], o[0] + o[1]]
    return ((cP[0] - cO[0]) ** 2 + (cP[1] - cO[1]) ** 2) / 2.0


def evaluate(snaps):
    """Score every snapshot with the current CFG; return a metrics dict."""
    n = len(snaps)
    R = LL = BR = hit = draw_hit = draw_tot = 0.0
    bins = {}
    for s in snaps:
        ph, pd, pa = predict_probs(s)
        act = s['act']
        R += rps(ph, pd, pa, act)
        probs = {'H': ph, 'D': pd, 'A': pa}
        p_act = max(min(probs[act], 1 - 1e-12), 1e-12)
        LL += -math.log(p_act)
        y = {'H': 0, 'D': 0, 'A': 0}; y[act] = 1
        BR += sum((probs[k] - y[k]) ** 2 for k in probs)
        pred = max(probs, key=probs.get)
        hit += (pred == act)
        if act == 'D':
            draw_tot += 1
            draw_hit += (pred == 'D')
        b = round(probs[pred], 1)
        bins.setdefault(b, [0, 0]); bins[b][0] += 1; bins[b][1] += (pred == act)
    return {
        'n': n, 'rps': R / n, 'log_loss': LL / n, 'brier': BR / n,
        'accuracy': hit / n,
        'draw_recall': (draw_hit / draw_tot) if draw_tot else 0.0,
        'draw_total': int(draw_tot),
        'calibration': {f"{k:.1f}": [int(v[1]), int(v[0])] for k, v in sorted(bins.items())},
    }


def replay():
    """Single chronological pass: warm up ratings on all history, snapshot eval window."""
    R = Ratings()
    snaps = []
    for date, h_raw, a_raw, hg, ag, neutral in load_matches():
        # Normalise to canonical DB names so renamed teams (Czech Republic->Czechia,
        # Turkey->Türkiye, ...) accumulate one continuous rating history.
        h = eng.normalize_team_name(h_raw)
        a = eng.normalize_team_name(a_raw)
        R.get(h); R.get(a)
        if date >= EVAL_START:
            snaps.append({
                'eh': R.elo[h], 'ea': R.elo[a],
                'ph': R.pi_h[h], 'pa': R.pi_a[a],
                'ath': R.att[h], 'dfh': R.df[h], 'ata': R.att[a], 'dfa': R.df[a],
                'adv': 0 if neutral else 1, 'act': outcome(hg, ag),
            })
        # ---- update ratings with the production functions ----
        de_h, de_a = eng.calculate_elo_change(R.elo[h], R.elo[a], hg, ag)
        R.elo[h] += de_h; R.elo[a] += de_a
        dpi_h, dpi_a = eng.calculate_pi_change(R.pi_h[h], R.pi_a[a], hg, ag)
        R.pi_h[h] += dpi_h; R.pi_a[a] += dpi_a
        dha, dad, daa, dhd = eng.calculate_berrar_change(R.att[h], R.df[a], R.att[a], R.df[h], hg, ag)
        R.att[h] = max(0.1, R.att[h] + dha); R.df[a] = max(0.1, R.df[a] + dad)
        R.att[a] = max(0.1, R.att[a] + daa); R.df[h] = max(0.1, R.df[h] + dhd)
    return R, snaps


def coordinate_descent(snaps):
    """Greedily tune prediction params to minimise mean RPS over the snapshots."""
    grid = {
        'DRAW_INFLATION':   [1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0],
        'HOME_ADV_ELO':     [0.0, 40.0, 70.0, 90.0, 120.0],
        'LAMBDA_BASE_HOME': [1.25, 1.35, 1.45, 1.55, 1.65],
        'LAMBDA_BASE_AWAY': [1.0, 1.1, 1.15, 1.25, 1.35],
        'LAMBDA_DIVISOR':   [600.0, 800.0, 1000.0, 1200.0],
        'RHO':              [-0.18, -0.12, -0.06, 0.0],
    }
    best = evaluate(snaps)['rps']
    for _ in range(3):  # passes until stable
        improved = False
        for param, choices in grid.items():
            cur = getattr(CFG, param)
            best_val, best_here = cur, best
            for v in choices:
                setattr(CFG, param, v)
                r = evaluate(snaps)['rps']
                if r < best_here - 1e-9:
                    best_here, best_val = r, v
            setattr(CFG, param, best_val)
            if best_here < best - 1e-9:
                best, improved = best_here, True
        if not improved:
            break
    # Light ensemble-weight search (4-model / no-Opta path).
    weight_candidates = [
        [0.25, 0.25, 0.20, 0.30], [0.22, 0.22, 0.16, 0.40],
        [0.30, 0.25, 0.15, 0.30], [0.20, 0.30, 0.20, 0.30],
        [0.28, 0.22, 0.20, 0.30], [0.25, 0.20, 0.15, 0.40],
    ]
    best_w = CFG.W_ENSEMBLE_NOOPTA
    for w in weight_candidates:
        CFG.W_ENSEMBLE_NOOPTA = w
        r = evaluate(snaps)['rps']
        if r < best - 1e-9:
            best, best_w = r, w
    CFG.W_ENSEMBLE_NOOPTA = best_w
    return best


def write_seeds(R):
    """#6 Data-driven Elo seeds for the 48 World Cup teams from the full replay.
    Keyed by the canonical (normalised) DB names that prediction lookups use."""
    targets = {eng.normalize_team_name(k) for k in eng.INITIAL_ELO}
    rev = {name: round(elo, 1) for name, elo in R.elo.items() if name in targets}
    with open(SEED_PATH, 'w', encoding='utf-8') as f:
        json.dump(rev, f, ensure_ascii=False, indent=2, sort_keys=True)
    return rev


def main():
    print(f"讀取歷史比賽並重放（評估窗起點 {EVAL_START}）...")
    R, snaps = replay()
    print(f"評估樣本數: {len(snaps)} 場")

    # Pristine baseline = the original hard-coded prediction parameters, scored on
    # the same rating snapshots, so the before/after isolates the calibration gain.
    ORIG = {'DRAW_INFLATION': 1.0, 'HOME_ADV_ELO': 70.0, 'LAMBDA_BASE_HOME': 1.25,
            'LAMBDA_BASE_AWAY': 1.25, 'LAMBDA_DIVISOR': 1000.0, 'RHO': -0.12,
            'W_ENSEMBLE_NOOPTA': [0.25, 0.25, 0.20, 0.30]}
    for k, v in ORIG.items():
        setattr(CFG, k, v)
    base = evaluate(snaps)
    print("\n=== 基線（原始預設參數）===")
    print(f"  RPS={base['rps']:.4f}  LogLoss={base['log_loss']:.4f}  "
          f"命中率={base['accuracy']:.1%}  和局召回={base['draw_recall']:.1%} "
          f"(共 {base['draw_total']} 場和局)")

    print("\n座標下降校準中 ...")
    coordinate_descent(snaps)
    cal = evaluate(snaps)
    print("\n=== 校準後 ===")
    print(f"  RPS={cal['rps']:.4f}  LogLoss={cal['log_loss']:.4f}  "
          f"命中率={cal['accuracy']:.1%}  和局召回={cal['draw_recall']:.1%}")

    tuned = ['DRAW_INFLATION', 'HOME_ADV_ELO', 'LAMBDA_BASE_HOME', 'LAMBDA_BASE_AWAY',
             'LAMBDA_DIVISOR', 'RHO', 'W_ENSEMBLE_NOOPTA', 'ELO_MOV_ENABLED', 'W_SENTIMENT']
    out = {k: getattr(CFG, k) for k in tuned}
    with open(CALIB_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n已寫入校準參數 -> {os.path.basename(CALIB_PATH)}")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    with open(METRICS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'eval_start': EVAL_START, 'baseline': base, 'calibrated': cal}, f,
                  ensure_ascii=False, indent=2)
    print(f"已寫入指標 -> {os.path.basename(METRICS_PATH)}")

    seeds = write_seeds(R)
    print(f"已寫入 {len(seeds)} 支世界盃球隊的資料驅動 Elo 種子 -> {os.path.basename(SEED_PATH)}")


if __name__ == '__main__':
    main()
