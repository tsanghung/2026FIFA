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


# 結果代碼 → 中文
_SIDE_ZH = {'home': '主勝', 'away': '客勝', 'draw': '和局'}


def analyze_divergence(m):
    """
    賽後分析單場「模型預測 vs 真實結果」的落差與原因。
    m: dict，需含 home, away, ph, pd, pa, pred_score, elo_h, elo_a,
       pick_side, pick_team, hg, ag。
    回傳 (命中?bool, 原因字串)；若尚未開賽回傳 (None, '⏳ 待開賽')。
    """
    hg, ag = m['hg'], m['ag']
    if hg is None or ag is None:
        return None, '⏳ 待開賽'

    actual = _actual_outcome(hg, ag)                      # home/away/draw
    probs = {'home': m['ph'] or 0, 'draw': m['pd'] or 0, 'away': m['pa'] or 0}
    fav = max(probs, key=probs.get)                       # 模型最看好的結果
    fav_p = probs[fav] * 100
    pick = m['pick_side']
    hit = (actual == pick)

    win_name = m['home'] if actual == 'home' else m['away'] if actual == 'away' else '雙方'
    elo_gap = abs((m['elo_h'] or 0) - (m['elo_a'] or 0))

    # 命中：照預測押中
    if hit:
        sc = f"（賽前估比分 {m['pred_score']}，實際 {hg}:{ag}）" if m['pred_score'] else ""
        conf = "高信心" if fav_p >= 60 else "中信心" if fav_p >= 45 else "低信心(本就難料卻押中)"
        return True, f"✅ 命中：模型賽前看好{_SIDE_ZH[pick]}（{fav_p:.0f}%，{conf}），結果如預期 {sc}"

    # 未命中：分類冷門原因
    reasons = []
    if actual == 'draw':
        reasons.append(f"爆和局：你押{m['pick_team']}贏，最後 {hg}:{ag} 言和；"
                       f"模型其實也給了和局 {probs['draw']*100:.0f}% 的不低機率")
    else:
        reasons.append(f"翻盤：你押{m['pick_team']}贏，最後由{win_name}勝出（{hg}:{ag}）")

    # 信心層級 → 屬「合理變異」還是「真大冷門」
    if fav_p >= 60:
        reasons.append(f"屬大冷門：模型高度看好{_SIDE_ZH[fav]}（{fav_p:.0f}%）仍翻車，"
                       f"多半是紅牌、定位球、門將神勇或臨場狀態等模型無法預知的單場因素")
    elif fav_p < 45 or (sorted(probs.values(), reverse=True)[0] - sorted(probs.values(), reverse=True)[1]) < 0.10:
        reasons.append(f"屬合理變異：三方機率接近（主{probs['home']*100:.0f}/和{probs['draw']*100:.0f}/客{probs['away']*100:.0f}），"
                       f"模型信心本就低，押這種場次風險高")
    else:
        reasons.append(f"中等意外：模型看好{_SIDE_ZH[fav]}（{fav_p:.0f}%）但非壓倒性")

    if elo_gap < 60:
        reasons.append(f"兩隊實力接近（Elo 僅差 {elo_gap:.0f}），本是五五波")
    return False, "❌ " + "；".join(reasons)


def build_report(conn):
    """產出文字報表並寫入 BET_TRACKING.md。回傳報表字串。"""
    cur = conn.cursor()
    bets = cur.execute(
        '''SELECT bet_id, name, bet_type, stake, currency, placed_date,
                  total_odds, status, payout, profit
           FROM bets ORDER BY placed_date, bet_id''').fetchall()

    lines = []
    lines.append("# 🎟️ 照預測投注 → 真實結果 落差分析\n")
    lines.append(f"_更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（台灣時間）_\n")
    lines.append("> 投注策略：**照模型預測下注**。下面比對「模型賽前怎麼說」與「球真的怎麼踢」，"
                 "並在每場開賽後自動分析落差原因。\n")

    # 收集所有腿的賽後分析（含 model 完整數據）
    all_legs = cur.execute(
        '''SELECT l.bet_id, l.match_num, l.pick_team, l.pick_side, l.result,
                  m.home_team, m.away_team, m.home_goals, m.away_goals, m.date,
                  m.pred_home_win_prob, m.pred_draw_prob, m.pred_away_win_prob,
                  m.pred_score, m.home_pre_match_elo, m.away_pre_match_elo
           FROM bet_legs l JOIN matches m ON m.match_num=l.match_num
           ORDER BY m.date, l.match_num''').fetchall()

    def leg_to_m(row):
        return {
            'home': row[5], 'away': row[6], 'hg': row[7], 'ag': row[8],
            'ph': row[10], 'pd': row[11], 'pa': row[12], 'pred_score': row[13],
            'elo_h': row[14], 'elo_a': row[15],
            'pick_side': row[3], 'pick_team': row[2],
        }

    # 單場層級命中統計
    played = [r for r in all_legs if r[7] is not None]
    hits = sum(1 for r in played if r[4] == 'won')
    leg_hit = (hits / len(played) * 100) if played else None

    # 彩票層級
    n_total = len(bets)
    n_settled = sum(1 for b in bets if b[7] in ('won', 'lost'))
    n_won = sum(1 for b in bets if b[7] == 'won')
    n_open = sum(1 for b in bets if b[7] == 'open')

    lines.append("## 📊 總覽\n")
    lines.append(f"- 投注張數：{n_total} 張過關（已開獎 {n_settled}、未開獎 {n_open}）")
    if n_settled:
        lines.append(f"- 過關命中：{n_won}/{n_settled} 張（{n_won/n_settled*100:.0f}%）")
    if played:
        lines.append(f"- 單場層級：模型預測命中 {hits}/{len(played)} 場（{leg_hit:.0f}%）")
    else:
        lines.append("- ⏳ 四場皆未開賽（6/11、6/12 陸續開打），開賽後此處自動更新命中率與原因。")
    lines.append("")

    # 每張彩票明細
    lines.append("## 🧾 投注明細（照預測押）\n")
    status_zh = {'open': '⏳ 未開獎', 'won': '✅ 全過關', 'lost': '❌ 未過關', 'void': '➖ 作廢'}
    for (bid, name, btype, stake, cur_unit, placed, todds, status, payout, profit) in bets:
        type_zh = '全部過關' if btype == 'parlay' else '單場'
        lines.append(f"### #{bid}　{name}　[{type_zh}]　{status_zh.get(status, status)}")
        lines.append("")
        lines.append("| 場次 | 對戰 | 我押 | 模型賽前預測 | 實際比分 | 命中 |")
        lines.append("|---|---|---|---|---|---|")
        res_zh = {'won': '✅', 'lost': '❌', 'pending': '⏳'}
        for row in all_legs:
            if row[0] != bid:
                continue
            mn, pteam, pside = row[1], row[2], row[3]
            home, away, hg, ag = row[5], row[6], row[7], row[8]
            ph, pd, pa, pred_score = row[10], row[11], row[12], row[13]
            probs = {'home': ph or 0, 'draw': pd or 0, 'away': pa or 0}
            fav = max(probs, key=probs.get)
            pred_str = f"{_SIDE_ZH[fav]} {probs[fav]*100:.0f}%・比分 {pred_score}"
            score = f"{hg}:{ag}" if hg is not None else "—"
            lines.append(f"| #{mn} | {home} vs {away} | {pteam}勝 | {pred_str} | {score} | {res_zh.get(row[4], row[4])} |")
        lines.append("")

    # 逐場落差原因
    lines.append("## 🔍 逐場落差與原因（賽後自動產生）\n")
    if not played:
        lines.append("⏳ 尚無已開賽場次。6/11、6/12 比完後，這裡會逐場列出"
                     "「模型怎麼預測、實際怎麼踢、為何有落差」。\n")
    else:
        for row in all_legs:
            m = leg_to_m(row)
            hit, reason = analyze_divergence(m)
            if hit is None:
                continue
            lines.append(f"- **#{row[1]} {m['home']} vs {m['away']}**（{row[9]}）：{reason}")
        lines.append("")

    lines.append("> 說明：本檔為個人對帳/檢討用途，不會放上對外研究網站，"
                 "網站只提供研究資訊、不提供賭博管道。")

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
