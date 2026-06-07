"""
champion_trend_report.py — auto-generated daily title-race trend report.

Reads the rolling `champion_predictions` snapshots and writes CHAMPION_TREND.md:
  * current Top-15 ranking with each pillar and the 1-day delta,
  * biggest 1-day movers (up / down),
  * window movers (first snapshot -> latest), once >= 2 days exist,
  * market-vs-model divergence (where our AI disagrees with the books = value),
  * a compact multi-day trend table for the leaders.

Pure stdlib + sqlite3 — runs unattended in CI with no extra dependencies.
"""

import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CHAMPION_TREND.md')


def _pct(x):
    return f"{(x or 0.0) * 100:.1f}%"


def _arrow(d):
    d = d or 0.0
    if d > 0.0005:
        return f"▲ +{d*100:.2f}%"
    if d < -0.0005:
        return f"▼ {d*100:.2f}%"
    return "—"


def build_report():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    has = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='champion_predictions'"
    ).fetchone()
    if not has:
        conn.close()
        return None

    dates = [r[0] for r in cur.execute(
        "SELECT DISTINCT snapshot_date FROM champion_predictions ORDER BY snapshot_date")]
    if not dates:
        conn.close()
        return None
    latest = dates[-1]
    n_days = len(dates)

    rows = cur.execute(
        "SELECT rank, team, blended_ewma, market_prob, opta_prob, model_prob, delta "
        "FROM champion_predictions WHERE snapshot_date = ? ORDER BY rank", (latest,)
    ).fetchall()

    # Full history per team for window movers & trend table
    hist = {}
    for d, t, ev in cur.execute(
            "SELECT snapshot_date, team, blended_ewma FROM champion_predictions"):
        hist.setdefault(t, {})[d] = ev
    conn.close()

    lines = []
    lines.append("# 🏆 2026 世界盃總冠軍 — 每日走勢分析報告")
    lines.append("")
    lines.append(f"> 自動產生於 {datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ "
                 f"最新快照 **{latest}** ｜ 已累積 **{n_days}** 天快照")
    lines.append("")
    lines.append("融合來源：**賭盤（交叉比對）為主** · Opta 超級電腦 · 本系統 AI 全賽事蒙地卡羅。"
                 "每日 EWMA 平滑。")
    lines.append("")

    # ---- Current ranking ----
    lines.append("## 目前奪冠機率排行 (Top 15)")
    lines.append("")
    lines.append("| # | 隊伍 | 融合 | 賭盤 | Opta | AI 模型 | 日變動 |")
    lines.append("|--:|:--|--:|--:|--:|--:|:--|")
    for rank, team, ev, mk, op, mo, dl in rows[:15]:
        lines.append(f"| {rank} | {team} | **{_pct(ev)}** | {_pct(mk)} | "
                     f"{_pct(op)} | {_pct(mo)} | {_arrow(dl)} |")
    lines.append("")

    # ---- 1-day movers ----
    movers = [(t, dl) for (_, t, _, _, _, _, dl) in rows if dl is not None]
    risers = sorted(movers, key=lambda x: x[1], reverse=True)[:5]
    fallers = sorted(movers, key=lambda x: x[1])[:5]
    if any(abs(d) > 0.0005 for _, d in movers):
        lines.append("## 最大變動（近 1 日）")
        lines.append("")
        lines.append("**🔺 上升**：" + " · ".join(
            f"{t} {_arrow(d)}" for t, d in risers if d > 0.0005) or "（無）")
        lines.append("")
        lines.append("**🔻 下滑**：" + " · ".join(
            f"{t} {_arrow(d)}" for t, d in fallers if d < -0.0005) or "（無）")
        lines.append("")

    # ---- Window movers (first -> latest) ----
    if n_days >= 2:
        first = dates[0]
        deltas = []
        for t, series in hist.items():
            if first in series and latest in series:
                deltas.append((t, series[latest] - series[first]))
        up = sorted(deltas, key=lambda x: x[1], reverse=True)[:5]
        dn = sorted(deltas, key=lambda x: x[1])[:5]
        lines.append(f"## 區間變動（{first} → {latest}）")
        lines.append("")
        lines.append("**📈 期間上升**：" + (" · ".join(
            f"{t} (+{d*100:.2f}%)" for t, d in up if d > 0.0005) or "（無）"))
        lines.append("")
        lines.append("**📉 期間下滑**：" + (" · ".join(
            f"{t} ({d*100:.2f}%)" for t, d in dn if d < -0.0005) or "（無）"))
        lines.append("")

    # ---- Market vs model divergence ----
    div = [(t, (mo or 0) - (mk or 0), mk, mo)
           for (_, t, ev, mk, op, mo, dl) in rows if (ev or 0) > 0.003]
    model_bull = sorted(div, key=lambda x: x[1], reverse=True)[:5]
    model_bear = sorted(div, key=lambda x: x[1])[:5]
    lines.append("## 市場 vs AI 模型 分歧（潛在價值點）")
    lines.append("")
    lines.append("AI 模型比賭盤**更看好**（模型 − 市場，正值越大越可能被低估）：")
    lines.append("")
    for t, d, mk, mo in model_bull:
        if d > 0.002:
            lines.append(f"- **{t}**：模型 {_pct(mo)} vs 賭盤 {_pct(mk)}（+{d*100:.1f}pp）")
    lines.append("")
    lines.append("AI 模型比賭盤**更看衰**：")
    lines.append("")
    for t, d, mk, mo in model_bear:
        if d < -0.002:
            lines.append(f"- **{t}**：模型 {_pct(mo)} vs 賭盤 {_pct(mk)}（{d*100:.1f}pp）")
    lines.append("")

    # ---- Trend table for leaders ----
    show_dates = dates[-7:]
    top_teams = [t for (_, t, *_rest) in rows[:6]]
    lines.append(f"## 領先群走勢（近 {len(show_dates)} 天，融合奪冠率）")
    lines.append("")
    lines.append("| 隊伍 | " + " | ".join(show_dates) + " |")
    lines.append("|:--|" + "--:|" * len(show_dates))
    for t in top_teams:
        cells = [_pct(hist.get(t, {}).get(d)) if hist.get(t, {}).get(d) is not None else "·"
                 for d in show_dates]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines.append("")

    if n_days < 3:
        lines.append("> ℹ️ 快照天數較少，走勢線索仍在累積中；約 3–5 天後趨勢會更清楚。")
        lines.append("")

    lines.append("---")
    lines.append("*本報告由 `champion_trend_report.py` 每日自動產生，請勿手動編輯。*")
    return "\n".join(lines)


def main():
    report = build_report()
    if report is None:
        print("[trend] 尚無 champion_predictions 資料，略過報告產生。")
        return
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"[trend] 已產生走勢報告 -> {OUT_PATH}")


if __name__ == '__main__':
    main()
