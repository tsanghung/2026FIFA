#!/usr/bin/env python3
"""final_standings.py — 2026 世界盃最終排名(FIFA 官方排名法)。

排序規則
--------
1. 主序:到達的最終輪次越深越前(冠軍 > 亞軍 > 季軍 > 殿軍 > 八強 > 十六強
   > 三十二強 > 小組賽)。冠/亞/季/殿由決賽與季軍戰結果直接決定。
2. 次序(同一輪淘汰者之間):全賽事總積分 → 淨勝球 → 進球數 → 隊名。

積分/進失球採 **FIFA 官方口徑**(與本站其他「90 分鐘結果」統計不同):
  * 延長賽分出勝負的比賽 → 以延長賽最終比分計為勝/負;
  * 點球大戰決勝的比賽 → 該場計為和局,比分取延長賽結束時的平手比分。

這是 `matches` 表的 `score` 文字欄位(如 "3–1 (a.e.t.)"、"0–0 (a.e.t., 4–3 p)")
在此模組中被解析的原因:`home_goals`/`away_goals` 欄位為了餵給「預測 90 分鐘勝負」
的模型,已把所有延長賽/點球場正規化為平手,不適用於官方最終排名。

用法
----
    python final_standings.py            # 重算並寫入 final_standings 表
    from final_standings import compute_final_standings, load_matches
"""
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'fifa_2026.db')

# 由淺到深的賽事輪次;index 越大代表走得越遠。
STAGE_ORDER = ['Group', 'Round of 32', 'Round of 16', 'Quarter-finals',
               'Semi-finals', 'Third-place play-off', 'Final']

# 同輪淘汰者所屬的「最終名次段」與其英文 stage_reached 標籤。
BUCKET_LABEL = {
    'QF': 'Quarter-finals', 'R16': 'Round of 16',
    'R32': 'Round of 32', 'GRP': 'Group stage',
}


def _stage_index(stage):
    s = stage or ''
    return next((i for i, name in enumerate(STAGE_ORDER) if s.startswith(name)), 0)


def real_scoreline(score_text):
    """回傳 (home_goals, away_goals, decisive):以 FIFA 口徑解析 `score` 文字。
    decisive=True 表示分出勝負(含延長賽);False 表示以點球決勝,該場計為和局。
    無法解析時回傳 None。"""
    txt = (score_text or '').replace('−', '-')
    m = re.match(r'^\s*(\d+)\s*[–\-]\s*(\d+)', txt)
    if not m:
        return None
    hg, ag = int(m.group(1)), int(m.group(2))
    # 兩隊延長賽進球相等 ⇒ 點球決勝 ⇒ 和局;不等 ⇒ 分出勝負。
    return hg, ag, (hg != ag)


def _winner_loser(m):
    """回傳 (勝隊, 負隊);點球決勝(無法從比分判斷)時回傳 (None, None)。"""
    hg, ag = m.get('home_goals'), m.get('away_goals')
    if hg is not None and ag is not None and hg != ag:
        return (m['home_team'], m['away_team']) if hg > ag else (m['away_team'], m['home_team'])
    r = real_scoreline(m.get('score'))
    if r and r[2]:
        rh, ra, _ = r
        return (m['home_team'], m['away_team']) if rh > ra else (m['away_team'], m['home_team'])
    return None, None


def tournament_complete(matches):
    """所有 104 場皆完賽,且決賽有結果時為 True。"""
    fin = [m for m in matches if (m.get('group_or_stage') or '') == 'Final']
    if not fin or fin[0].get('status') != 'Completed':
        return False
    return all(m.get('status') == 'Completed' for m in matches)


def compute_final_standings(matches, confederations=None):
    """回傳 48 隊的最終排名 list[dict];賽事尚未全部完成時回傳 []。
    每個 dict:position, team, confederation, stage_reached, stage_bucket,
    played, won, drawn, lost, gf, ga, gd, points。"""
    if not tournament_complete(matches):
        return []
    confederations = confederations or {}
    team_set = {t for m in matches for t in (m['home_team'], m['away_team'])
                if not re.search(r'Match |Winner|Loser|TBD', str(t))}

    # 每隊到達的最深輪次。
    furthest = {}
    for m in matches:
        if m.get('status') != 'Completed':
            continue
        idx = _stage_index(m.get('group_or_stage'))
        for t in (m['home_team'], m['away_team']):
            if t in team_set:
                furthest[t] = max(furthest.get(t, -1), idx)

    # 冠/亞/季/殿由決賽與季軍戰直接決定。
    final = next(m for m in matches if (m.get('group_or_stage') or '') == 'Final')
    third = next(m for m in matches if (m.get('group_or_stage') or '') == 'Third-place play-off')
    champion, runner_up = _winner_loser(final)
    third_place, fourth_place = _winner_loser(third)
    fixed = {champion, runner_up, third_place, fourth_place}

    # 全賽事戰績(FIFA 口徑:延長賽計勝負、點球計和)。
    rec = {t: {'p': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0} for t in team_set}
    for m in matches:
        if m.get('status') != 'Completed':
            continue
        r = real_scoreline(m.get('score'))
        if not r:
            continue
        hg, ag, decisive = r
        is_draw = not decisive
        for t, gf, ga in ((m['home_team'], hg, ag), (m['away_team'], ag, hg)):
            if t not in rec:
                continue
            R = rec[t]
            R['p'] += 1
            R['gf'] += gf
            R['ga'] += ga
            if is_draw:
                R['d'] += 1
            elif gf > ga:
                R['w'] += 1
            else:
                R['l'] += 1
    for R in rec.values():
        R['gd'] = R['gf'] - R['ga']
        R['points'] = 3 * R['w'] + R['d']

    # 依到達輪次分段(冠亞季殿以外)。
    buckets = {}
    for t, idx in furthest.items():
        if t in fixed:
            continue
        key = {3: 'QF', 2: 'R16', 1: 'R32'}.get(idx, 'GRP')
        buckets.setdefault(key, []).append(t)

    def tie_key(t):
        R = rec[t]
        return (-R['points'], -R['gd'], -R['gf'], t)

    ordered = [(champion, 'Champion'), (runner_up, 'Runner-up'),
               (third_place, 'Third place'), (fourth_place, 'Fourth place')]
    for bucket in ('QF', 'R16', 'R32', 'GRP'):
        for t in sorted(buckets.get(bucket, []), key=tie_key):
            ordered.append((t, BUCKET_LABEL[bucket]))

    standings = []
    for pos, (t, stage_reached) in enumerate(ordered, 1):
        R = rec[t]
        bucket = ('FINAL4' if pos <= 4 else
                  next(k for k, v in BUCKET_LABEL.items() if v == stage_reached))
        standings.append({
            'position': pos, 'team': t,
            'confederation': confederations.get(t, ''),
            'stage_reached': stage_reached, 'stage_bucket': bucket,
            'played': R['p'], 'won': R['w'], 'drawn': R['d'], 'lost': R['l'],
            'gf': R['gf'], 'ga': R['ga'], 'gd': R['gd'], 'points': R['points'],
        })
    return standings


# ------------------------------------------------------------------ DB helpers

def load_matches(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        'SELECT match_num, group_or_stage, home_team, away_team, score, '
        'home_goals, away_goals, status FROM matches ORDER BY match_num')]


def load_confederations(con):
    return {r[0]: r[1] for r in con.execute('SELECT name, confederation FROM teams')}


def ensure_table(con):
    con.execute('''
        CREATE TABLE IF NOT EXISTS final_standings (
            position INTEGER PRIMARY KEY,
            team TEXT NOT NULL,
            confederation TEXT,
            stage_reached TEXT,
            stage_bucket TEXT,
            played INTEGER, won INTEGER, drawn INTEGER, lost INTEGER,
            gf INTEGER, ga INTEGER, gd INTEGER, points INTEGER
        )''')


def persist(con, standings):
    ensure_table(con)
    con.execute('DELETE FROM final_standings')
    con.executemany(
        'INSERT INTO final_standings (position, team, confederation, stage_reached, '
        'stage_bucket, played, won, drawn, lost, gf, ga, gd, points) '
        'VALUES (:position, :team, :confederation, :stage_reached, :stage_bucket, '
        ':played, :won, :drawn, :lost, :gf, :ga, :gd, :points)', standings)
    con.commit()


def load_standings(con):
    """回傳 final_standings 表內容;表不存在或空時回傳 []。"""
    try:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            'SELECT * FROM final_standings ORDER BY position')]
        return rows
    except sqlite3.OperationalError:
        return []


def main():
    con = sqlite3.connect(DB_PATH)
    matches = load_matches(con)
    confeds = load_confederations(con)
    standings = compute_final_standings(matches, confeds)
    if not standings:
        print('賽事尚未全部完成,最終排名暫不產生。')
        con.close()
        return
    persist(con, standings)
    print(f'已寫入 final_standings({len(standings)} 隊)。前八名:')
    for s in standings[:8]:
        print(f"  {s['position']:2d}. {s['team']:20s} {s['stage_reached']:14s} "
              f"{s['won']}-{s['drawn']}-{s['lost']} GD{s['gd']:+d} Pts{s['points']}")
    con.close()


if __name__ == '__main__':
    main()
