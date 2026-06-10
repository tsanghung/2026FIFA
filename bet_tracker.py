"""
bet_tracker.py — 個人投注紀錄與「實際比賽結果 vs 投注」勝率比較

用途
----
1. 把個人下注的「過關（parlay / 全部過關）」彩票記錄進資料庫（bets / bet_legs 兩張表）。
2. 每當比賽有結果（matches.home_goals 不為 NULL）就自動結算每一注、每一張彩票。
3. 產出「實際結果 vs 投注」勝率比較報表（命中率、ROI、損益），並寫出 BET_TRACKING.md。

說明
----
- 這是「個人投注追蹤」工具，僅供自己對帳用，不會出現在對外的研究網站 docs/ 裡，
  符合「網站只提供研究資訊、不提供賭博管道」的定位。
- 「全部過關 (parlay)」＝所有腿（leg）全中才算贏，任一腿輸整張即輸。
  總賠率＝各腿賠率相乘；中獎派彩＝本金 × 總賠率。

可直接執行：
    python bet_tracker.py            # 建表、補登既有彩票、結算、印出報表
    python bet_tracker.py --report   # 只印報表（不重新補登）
"""

import os
import sys
import sqlite3
from datetime import datetime

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BET_TRACKING.md')


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_tables(conn):
    """建立 bets / bet_legs 兩張表（若不存在）。"""
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bets (
            bet_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            bet_type    TEXT    NOT NULL DEFAULT 'parlay',   -- parlay=全部過關 / single=單場
            stake       REAL    NOT NULL,                    -- 本金
            currency    TEXT    NOT NULL DEFAULT 'NTD',
            placed_date TEXT    NOT NULL,
            total_odds  REAL,                                -- 各腿賠率相乘（任一腿缺賠率則為 NULL）
            status      TEXT    NOT NULL DEFAULT 'open',     -- open/won/lost/void
            payout      REAL,                                -- 結算派彩
            profit      REAL,                                -- 派彩 - 本金
            settled_at  TEXT,
            UNIQUE(name, placed_date)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bet_legs (
            leg_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            bet_id     INTEGER NOT NULL,
            match_num  INTEGER NOT NULL,
            pick_side  TEXT    NOT NULL,                     -- home/away/draw
            pick_team  TEXT    NOT NULL,
            odds       REAL,                                 -- 下注當下的賠率快照
            model_prob REAL,                                 -- 模型對該選項的預測勝率快照
            result     TEXT    NOT NULL DEFAULT 'pending',   -- won/lost/push/pending
            UNIQUE(bet_id, match_num),
            FOREIGN KEY(bet_id) REFERENCES bets(bet_id)
        )
    ''')
    conn.commit()


def record_bet(conn, name, stake, placed_date, legs, bet_type='parlay', currency='NTD'):
    """
    記錄一張彩票（idempotent，用 name+placed_date 唯一）。
    legs: list of dict，每筆 {'match_num', 'pick_side'} 必填；
          odds / pick_team / model_prob 留空時自動由 matches 表帶入。
    回傳 bet_id。
    """
    cur = conn.cursor()
    cur.execute('SELECT bet_id FROM bets WHERE name=? AND placed_date=?', (name, placed_date))
    existing = cur.fetchone()
    if existing:
        return existing[0]

    # 先補齊每一腿的賠率 / 隊名 / 模型機率快照
    filled = []
    for leg in legs:
        mn = leg['match_num']
        side = leg['pick_side']
        row = cur.execute(
            '''SELECT home_team, away_team,
                      pred_home_win_prob, pred_away_win_prob, pred_draw_prob,
                      odds_home, odds_away, odds_draw
               FROM matches WHERE match_num=?''', (mn,)
        ).fetchone()
        if not row:
            raise ValueError(f"找不到場次 #{mn}")
        home, away, ph, pa, pd, oh, oa, od = row
        pick_team = leg.get('pick_team') or (home if side == 'home' else away if side == 'away' else '和局')
        odds = leg.get('odds')
        if odds is None:
            odds = oh if side == 'home' else oa if side == 'away' else od
        model_prob = leg.get('model_prob')
        if model_prob is None:
            model_prob = ph if side == 'home' else pa if side == 'away' else pd
        filled.append((mn, side, pick_team, odds, model_prob))

    # 總賠率：所有腿都有賠率才算得出來
    odds_list = [f[3] for f in filled]
    total_odds = None
    if all(o is not None for o in odds_list):
        total_odds = 1.0
        for o in odds_list:
            total_odds *= o

    cur.execute(
        '''INSERT INTO bets (name, bet_type, stake, currency, placed_date, total_odds, status)
           VALUES (?,?,?,?,?,?, 'open')''',
        (name, bet_type, stake, currency, placed_date, total_odds)
    )
    bet_id = cur.lastrowid
    for (mn, side, pick_team, odds, model_prob) in filled:
        cur.execute(
            '''INSERT INTO bet_legs (bet_id, match_num, pick_side, pick_team, odds, model_prob)
               VALUES (?,?,?,?,?,?)''',
            (bet_id, mn, side, pick_team, odds, model_prob)
        )
    conn.commit()
    return bet_id


def _actual_outcome(home_goals, away_goals):
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return 'home'
    if home_goals < away_goals:
        return 'away'
    return 'draw'


def settle(conn):
    """依 matches 實際比分結算每一腿與每張彩票。"""
    cur = conn.cursor()
    legs = cur.execute(
        '''SELECT l.leg_id, l.bet_id, l.match_num, l.pick_side,
                  m.home_goals, m.away_goals
           FROM bet_legs l JOIN matches m ON m.match_num = l.match_num'''
    ).fetchall()

    for leg_id, bet_id, mn, pick_side, hg, ag in legs:
        outcome = _actual_outcome(hg, ag)
        if outcome is None:
            result = 'pending'
        else:
            result = 'won' if outcome == pick_side else 'lost'
        cur.execute('UPDATE bet_legs SET result=? WHERE leg_id=?', (result, leg_id))

    # 每張彩票（全部過關）的結算
    for (bet_id,) in cur.execute('SELECT bet_id FROM bets').fetchall():
        leg_results = [r[0] for r in cur.execute(
            'SELECT result FROM bet_legs WHERE bet_id=?', (bet_id,)).fetchall()]
        stake, total_odds = cur.execute(
            'SELECT stake, total_odds FROM bets WHERE bet_id=?', (bet_id,)).fetchone()

        if any(r == 'lost' for r in leg_results):
            status, payout = 'lost', 0.0
        elif all(r == 'won' for r in leg_results) and leg_results:
            status = 'won'
            payout = (stake * total_odds) if total_odds else None
        else:
            status, payout = 'open', None

        if status == 'open':
            cur.execute(
                'UPDATE bets SET status=?, payout=NULL, profit=NULL, settled_at=NULL WHERE bet_id=?',
                (status, bet_id))
        else:
            profit = (payout - stake) if payout is not None else None
            cur.execute(
                'UPDATE bets SET status=?, payout=?, profit=?, settled_at=? WHERE bet_id=?',
                (status, payout, profit, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), bet_id))
    conn.commit()


def _fmt(x, suffix='', dash='—'):
    return f"{x:.2f}{suffix}" if isinstance(x, (int, float)) else dash


def build_report(conn):
    """產出文字報表並寫入 BET_TRACKING.md。回傳報表字串。"""
    cur = conn.cursor()
    bets = cur.execute(
        '''SELECT bet_id, name, bet_type, stake, currency, placed_date,
                  total_odds, status, payout, profit
           FROM bets ORDER BY placed_date, bet_id''').fetchall()

    lines = []
    lines.append("# 🎟️ 個人投注追蹤 ─ 實際結果 vs 投注 勝率比較\n")
    lines.append(f"_更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（台灣時間）_\n")

    # 彩票層級統計
    n_total = len(bets)
    n_settled = sum(1 for b in bets if b[7] in ('won', 'lost'))
    n_won = sum(1 for b in bets if b[7] == 'won')
    n_open = sum(1 for b in bets if b[7] == 'open')
    total_stake = sum(b[3] for b in bets)
    settled_stake = sum(b[3] for b in bets if b[7] in ('won', 'lost'))
    total_payout = sum(b[8] for b in bets if b[7] in ('won', 'lost') and b[8] is not None)
    net = total_payout - settled_stake if n_settled else 0.0
    win_rate = (n_won / n_settled * 100) if n_settled else None
    roi = (net / settled_stake * 100) if settled_stake else None

    lines.append("## 📊 總覽（彩票層級）\n")
    lines.append(f"- 彩票張數：{n_total}（已結算 {n_settled}、未開獎 {n_open}）")
    lines.append(f"- 已結算命中：{n_won}/{n_settled}　勝率：{_fmt(win_rate, '%') if win_rate is not None else '尚無已結算彩票'}")
    lines.append(f"- 總投注本金：{total_stake:.0f} 元（已結算 {settled_stake:.0f} 元）")
    lines.append(f"- 已結算派彩：{total_payout:.0f} 元　淨損益：{net:+.0f} 元　ROI：{_fmt(roi, '%') if roi is not None else '—'}\n")

    # 每張彩票明細
    lines.append("## 🧾 彩票明細\n")
    status_zh = {'open': '⏳ 未開獎', 'won': '✅ 中獎', 'lost': '❌ 未中', 'void': '➖ 作廢'}
    for (bid, name, btype, stake, cur_unit, placed, todds, status, payout, profit) in bets:
        type_zh = '全部過關' if btype == 'parlay' else '單場'
        lines.append(f"### #{bid}　{name}　[{type_zh}]")
        head = (f"- 本金 {stake:.0f} {cur_unit}　總賠率 {_fmt(todds, '', '待補')}　"
                f"狀態 {status_zh.get(status, status)}")
        if status == 'won' and payout is not None:
            head += f"　派彩 {payout:.0f}　損益 {profit:+.0f}"
        elif status == 'lost':
            head += f"　損益 {-stake:+.0f}"
        elif status == 'open' and todds:
            head += f"　（全中可派彩 {stake * todds:.0f}）"
        lines.append(head)

        legs = cur.execute(
            '''SELECT l.match_num, l.pick_team, l.pick_side, l.odds, l.model_prob, l.result,
                      m.home_team, m.away_team, m.home_goals, m.away_goals, m.date
               FROM bet_legs l JOIN matches m ON m.match_num=l.match_num
               WHERE l.bet_id=? ORDER BY m.date, l.match_num''', (bid,)).fetchall()
        lines.append("")
        lines.append("| 場次 | 對戰 | 投注 | 賠率 | 模型勝率 | 實際比分 | 結果 |")
        lines.append("|---|---|---|---|---|---|---|")
        res_zh = {'won': '✅ 中', 'lost': '❌ 槓', 'push': '➖ 和', 'pending': '⏳ 待開'}
        for (mn, pteam, pside, odds, mprob, result,
             home, away, hg, ag, mdate) in legs:
            score = f"{hg}:{ag}" if hg is not None else "—"
            mprob_s = f"{mprob*100:.0f}%" if mprob is not None else "—"
            odds_s = _fmt(odds, '', '待補')
            lines.append(f"| #{mn} | {home} vs {away} | {pteam}勝 | {odds_s} | {mprob_s} | {score} | {res_zh.get(result, result)} |")
        lines.append("")

    # 腿（單場）層級命中率 + 模型對照
    leg_rows = cur.execute(
        '''SELECT result, model_prob FROM bet_legs''').fetchall()
    settled_legs = [r for r in leg_rows if r[0] in ('won', 'lost')]
    leg_won = sum(1 for r in settled_legs if r[0] == 'won')
    leg_hit = (leg_won / len(settled_legs) * 100) if settled_legs else None
    # 模型對「我所投注選項」的平均預期勝率（作為對照基準）
    probs = [r[1] for r in leg_rows if r[1] is not None]
    model_avg = (sum(probs) / len(probs) * 100) if probs else None

    lines.append("## 🎯 單場（腿）層級：實際 vs 模型\n")
    lines.append(f"- 已開獎場次：{len(settled_legs)}　實際命中率：{_fmt(leg_hit, '%') if leg_hit is not None else '尚無已開獎場次'}")
    lines.append(f"- 模型對「所投選項」的平均預測勝率：{_fmt(model_avg, '%') if model_avg is not None else '—'}")
    if leg_hit is not None and model_avg is not None:
        diff = leg_hit - model_avg
        verdict = "實際優於模型預期 👍" if diff >= 0 else "實際低於模型預期 👎"
        lines.append(f"- 落差：{diff:+.1f} 個百分點（{verdict}）")
    lines.append("")
    lines.append("> 說明：本表為個人對帳用途，網站只提供研究資訊、不提供賭博管道。")

    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)
    return report


# ── 既有投注：開幕週的兩張過關彩票 ──────────────────────────────
SEED_BETS = [
    {
        'name': '墨西哥 & 南韓 雙過關',
        'stake': 200, 'placed_date': '2026-06-10', 'bet_type': 'parlay',
        'legs': [
            {'match_num': 1, 'pick_side': 'home'},   # Mexico 勝 South Africa
            {'match_num': 2, 'pick_side': 'home'},   # South Korea 勝 Czechia
        ],
    },
    {
        'name': '加拿大 & 美國 雙過關',
        'stake': 200, 'placed_date': '2026-06-10', 'bet_type': 'parlay',
        'legs': [
            {'match_num': 7,  'pick_side': 'home'},   # Canada 勝 Bosnia-Herzegovina
            {'match_num': 19, 'pick_side': 'home'},   # USA 勝 Paraguay
        ],
    },
]


def seed(conn):
    for b in SEED_BETS:
        record_bet(conn, b['name'], b['stake'], b['placed_date'], b['legs'],
                   bet_type=b.get('bet_type', 'parlay'))


def main():
    only_report = '--report' in sys.argv
    conn = get_connection()
    init_tables(conn)
    if not only_report:
        seed(conn)
    settle(conn)
    report = build_report(conn)
    conn.close()
    print(report)
    print(f"\n✅ 報表已寫入 {REPORT_PATH}")


if __name__ == '__main__':
    main()
