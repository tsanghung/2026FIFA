"""
manual_results.py — 手動賽果覆蓋層(persistent override)

為什麼需要
----------
每日 sync 會爬維基百科真實比分並 `force_recreate` 重建 matches 表;任何手動寫入
若沒留存,隔天就被覆蓋。本模組把手動輸入的比分存成 `manual_results.json`(進版控),
並在每次 sync 重建後「補回」尚未有真實比分的場次,確保前後端資料一致且持久。

語意
----
- 手動覆蓋只填「維基還沒有真實比分(status != Completed)」的場次(respect_existing=True);
  一旦維基有了官方比分,官方結果優先,手動值自動讓位。
- `update_result.py` 寫入時用 respect_existing=False(當下以手動為準)。
"""

import os
import json
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDE_PATH = os.path.join(HERE, 'manual_results.json')


def load_overrides():
    """回傳 {match_num(int): {'home_goals': int, 'away_goals': int}}。"""
    if not os.path.exists(OVERRIDE_PATH):
        return {}
    try:
        with open(OVERRIDE_PATH, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for k, v in (raw or {}).items():
        try:
            out[int(k)] = {'home_goals': int(v['home_goals']),
                           'away_goals': int(v['away_goals'])}
        except (KeyError, ValueError, TypeError):
            continue
    return out


def set_override(match_num, home_goals, away_goals):
    """新增/更新一筆手動賽果並寫回 JSON。"""
    data = {}
    if os.path.exists(OVERRIDE_PATH):
        try:
            with open(OVERRIDE_PATH, encoding='utf-8') as f:
                data = json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
    data[str(int(match_num))] = {'home_goals': int(home_goals),
                                 'away_goals': int(away_goals)}
    with open(OVERRIDE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    return data


def remove_override(match_num):
    """移除一筆手動賽果(例如維基已有官方比分後想清掉)。"""
    if not os.path.exists(OVERRIDE_PATH):
        return
    try:
        with open(OVERRIDE_PATH, encoding='utf-8') as f:
            data = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        return
    data.pop(str(int(match_num)), None)
    with open(OVERRIDE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def clear_match_result(conn, match_num):
    """把某場次在 DB 中還原為未開賽(撤銷手動賽果用)。
    下一次 daily sync 會從維基重抓官方比分(若已有)。"""
    cur = conn.cursor()
    cur.execute(
        "UPDATE matches SET home_goals=NULL, away_goals=NULL, score=?, status='Scheduled' "
        "WHERE match_num=?",
        (f"Match {int(match_num)}", int(match_num)))
    conn.commit()


def apply_overrides(conn, respect_existing=True):
    """
    把手動賽果寫進 matches 表。回傳實際套用筆數。
    respect_existing=True:只填尚未 Completed 的場次(官方比分優先)。
    """
    overrides = load_overrides()
    if not overrides:
        return 0
    cur = conn.cursor()
    applied = 0
    for mn, sc in overrides.items():
        row = cur.execute('SELECT status FROM matches WHERE match_num=?', (mn,)).fetchone()
        if not row:
            continue
        if respect_existing and row[0] == 'Completed':
            continue
        hg, ag = sc['home_goals'], sc['away_goals']
        cur.execute(
            "UPDATE matches SET home_goals=?, away_goals=?, score=?, status='Completed' "
            "WHERE match_num=?",
            (hg, ag, f"{hg}-{ag}", mn))
        applied += 1
    conn.commit()
    return applied
