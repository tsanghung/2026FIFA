"""
prediction_eval.py — 本屆世界盃「正式預測」即時準確度評分

用途
----
針對已完成(status='Completed')且有預測機率的場次,計算一組嚴謹的評分指標,
讓「優化模型」是用證據衡量、而非憑感覺:
  - 命中率 (argmax 1X2 是否正確)
  - RPS  (Ranked Probability Score,有序三分類的標準指標,越低越好)
  - 多分類 Brier、Log-loss
  - 精確比分命中率、進球差 MAE、總進球 MAE
  - 校準 (高信心的預測是否真的比較常中)

輸出 PRED_ACCURACY.md 與 prediction_metrics_live.json,並在每日 sync 自動更新。

重要:賽事初期樣本極小(n<20),所有指標僅供參考,不應據此調整已用 5 萬場歷史
回測校準的參數(會 overfit)。本工具的價值是隨賽事累積、長期追蹤模型表現。
"""

import os
import json
import math
import sqlite3
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'fifa_2026.db')
MD_PATH = os.path.join(HERE, 'PRED_ACCURACY.md')
JSON_PATH = os.path.join(HERE, 'prediction_metrics_live.json')

# 機率向量順序固定為 [home, draw, away]
_ORDER = ('home', 'draw', 'away')


def _outcome(hg, ag):
    if hg > ag:
        return 'home'
    if hg < ag:
        return 'away'
    return 'draw'


def _rps(probs, actual_idx):
    """有序三分類 RPS。probs 為 [home,draw,away];actual_idx 為實際類別索引。"""
    obs = [0.0, 0.0, 0.0]
    obs[actual_idx] = 1.0
    cum_p = cum_o = 0.0
    total = 0.0
    for i in range(len(probs) - 1):          # r-1 個累積項
        cum_p += probs[i]
        cum_o += obs[i]
        total += (cum_p - cum_o) ** 2
    return total / (len(probs) - 1)


def load_completed(conn):
    rows = conn.execute('''
        SELECT match_num, home_team, away_team, home_goals, away_goals,
               pred_home_win_prob, pred_draw_prob, pred_away_win_prob, pred_score
        FROM matches
        WHERE status='Completed' AND home_goals IS NOT NULL
          AND pred_home_win_prob IS NOT NULL
        ORDER BY match_num ASC''').fetchall()
    return rows


def evaluate(conn):
    rows = load_completed(conn)
    n = len(rows)
    metrics = {
        'n': n,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if n == 0:
        metrics.update({'accuracy': None, 'rps': None, 'brier': None,
                        'logloss': None, 'exact_score_acc': None,
                        'gd_mae': None, 'tg_mae': None, 'rps_uniform': None})
        return metrics, []

    hits = exact_hits = 0
    sum_rps = sum_brier = sum_ll = sum_gd = sum_tg = sum_rps_unif = 0.0
    details = []
    # 校準桶:依「最高機率」分組
    cal_buckets = {}

    for (mn, home, away, hg, ag, ph, pd, pa, pred_score) in rows:
        probs = [ph or 0.0, pd or 0.0, pa or 0.0]
        s = sum(probs) or 1.0
        probs = [p / s for p in probs]                      # 防呆正規化
        actual = _outcome(hg, ag)
        ai = _ORDER.index(actual)

        pred_idx = max(range(3), key=lambda i: probs[i])
        hit = (pred_idx == ai)
        hits += hit

        sum_rps += _rps(probs, ai)
        sum_rps_unif += _rps([1/3, 1/3, 1/3], ai)
        sum_brier += sum((probs[i] - (1.0 if i == ai else 0.0)) ** 2 for i in range(3))
        sum_ll += -math.log(max(probs[ai], 1e-12))

        # 比分相關
        actual_score = f"{hg}-{ag}"
        exact = (pred_score == actual_score)
        exact_hits += exact
        if pred_score and '-' in pred_score:
            try:
                pgh, pga = (int(x) for x in pred_score.split('-'))
                sum_gd += abs((pgh - pga) - (hg - ag))
                sum_tg += abs((pgh + pga) - (hg + ag))
            except ValueError:
                pass

        # 校準
        top_p = probs[pred_idx]
        bkt = f"{int(top_p * 10) * 10}-{int(top_p * 10) * 10 + 10}%"
        b = cal_buckets.setdefault(bkt, {'n': 0, 'hit': 0, 'sum_p': 0.0})
        b['n'] += 1
        b['hit'] += hit
        b['sum_p'] += top_p

        details.append({
            'match_num': mn, 'home': home, 'away': away,
            'probs': [round(p, 3) for p in probs],
            'pred_outcome': _ORDER[pred_idx], 'pred_score': pred_score,
            'actual': actual, 'actual_score': actual_score,
            'hit': bool(hit), 'exact': bool(exact),
        })

    metrics.update({
        'accuracy': hits / n,
        'rps': sum_rps / n,
        'rps_uniform': sum_rps_unif / n,
        'brier': sum_brier / n,
        'logloss': sum_ll / n,
        'exact_score_acc': exact_hits / n,
        'gd_mae': sum_gd / n,
        'tg_mae': sum_tg / n,
        'calibration': {k: {'n': v['n'], 'win_rate': v['hit'] / v['n'],
                            'avg_pred': v['sum_p'] / v['n']}
                        for k, v in sorted(cal_buckets.items())},
    })
    return metrics, details


def write_report(metrics, details):
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    L = []
    L.append("# 🎯 本屆世界盃「正式預測」即時準確度\n")
    L.append(f"_更新:{metrics['generated_at']}　已評估場次:{metrics['n']}_\n")
    if metrics['n'] == 0:
        L.append("尚無已完成且有預測的場次。\n")
        _flush(L)
        return
    if metrics['n'] < 20:
        L.append("> ⚠️ 樣本極小,以下數字僅供參考,**不應據此調整回測校準過的參數**(會 overfit)。\n")

    acc = metrics['accuracy'] * 100
    L.append("## 總指標\n")
    L.append(f"- 1X2 命中率:**{acc:.0f}%**（{round(metrics['accuracy']*metrics['n'])}/{metrics['n']}）")
    L.append(f"- RPS：**{metrics['rps']:.3f}**（越低越好;隨機基準 {metrics['rps_uniform']:.3f}）")
    L.append(f"- Brier：{metrics['brier']:.3f}　Log-loss：{metrics['logloss']:.3f}")
    L.append(f"- 精確比分命中率：{metrics['exact_score_acc']*100:.0f}%　"
             f"進球差 MAE：{metrics['gd_mae']:.2f}　總進球 MAE：{metrics['tg_mae']:.2f}\n")

    verdict = "優於隨機" if metrics['rps'] < metrics['rps_uniform'] else "尚未優於隨機"
    L.append(f"> RPS {metrics['rps']:.3f} vs 隨機 {metrics['rps_uniform']:.3f} → **{verdict}**。\n")

    L.append("## 逐場\n")
    L.append("| # | 對戰 | 預測(主/和/客) | 預測比分 | 實際 | 1X2 | 比分 |")
    L.append("|---|---|---|---|---|---|---|")
    for d in details:
        p = d['probs']
        L.append(f"| {d['match_num']} | {d['home']} vs {d['away']} | "
                 f"{p[0]*100:.0f}/{p[1]*100:.0f}/{p[2]*100:.0f} | {d['pred_score']} | "
                 f"{d['actual_score']} | {'✅' if d['hit'] else '❌'} | "
                 f"{'✅' if d['exact'] else '—'} |")
    L.append("")
    _flush(L)


def _flush(lines):
    with open(MD_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")


def main():
    conn = sqlite3.connect(DB_PATH)
    metrics, details = evaluate(conn)
    conn.close()
    write_report(metrics, details)
    if metrics['n']:
        print(f"已評估 {metrics['n']} 場 | 命中率 {metrics['accuracy']*100:.0f}% | "
              f"RPS {metrics['rps']:.3f}（隨機 {metrics['rps_uniform']:.3f}）")
    else:
        print("尚無已完成且有預測的場次。")
    print(f"報表:{MD_PATH}")


if __name__ == '__main__':
    main()
