"""
update_result.py — 手動輸入正賽比分,並讓前後端資料全部同步更新

流程(一次到位)
----------------
1. 寫入 manual_results.json(持久,daily sync 會沿用)
2. 套用到 fifa_2026.db(matches 標記 Completed + 比分)
3. 重算全庫預測與評級(Elo/Pi/Berrar 回饋)→ 賽程預測同步
4. 結算投注(bet_tracker)→ 投注實測同步
5. 即時準確度評分(prediction_eval)→ 預測 vs 結果差異與原因
6. 重建靜態站(build_static)→ 前端頁面同步

用法
----
    python update_result.py <match_num> <home_goals> <away_goals>
    python update_result.py --remove <match_num>      # 撤銷某筆手動賽果後重算

執行後請 commit 這些檔案:manual_results.json fifa_2026.db docs
  BET_TRACKING.md PRED_ACCURACY.md prediction_metrics_live.json（GitHub Action 會自動 commit）。
"""

import sys
import sqlite3

import manual_results
import sync_fifa
import prediction_eval
from manual_results import OVERRIDE_PATH

DB_PATH = sync_fifa.DB_PATH


def recompute_everything():
    # 1) 套用手動覆蓋(此處以手動為準)
    conn = sqlite3.connect(DB_PATH)
    applied = manual_results.apply_overrides(conn, respect_existing=False)
    conn.close()
    print(f"✅ 已套用 {applied} 筆手動賽果到資料庫")

    # 2) 重算全庫預測與評級
    sync_fifa.reset_and_recalculate_all_elo_and_predictions()
    print("✅ 已重算全 104 場預測與動態評級")

    # 3) 結算投注
    try:
        import bet_tracker
        c = sqlite3.connect(DB_PATH)
        bet_tracker.init_tables(c)
        bet_tracker.seed(c)
        bet_tracker.settle(c)
        bet_tracker.build_report(c)
        c.close()
        print("✅ 已結算投注並更新 BET_TRACKING.md")
    except Exception as e:
        print(f"⚠️ 投注結算略過:{e}")

    # 4) 即時準確度評分
    c = sqlite3.connect(DB_PATH)
    metrics, details = prediction_eval.evaluate(c)
    c.close()
    prediction_eval.write_report(metrics, details)
    if metrics['n']:
        print(f"✅ 即時準確度:命中 {metrics['accuracy']*100:.0f}% / "
              f"RPS {metrics['rps']:.3f}（隨機 {metrics['rps_uniform']:.3f}）")

    # 5) 重建靜態站
    try:
        import build_static
        build_static.main()
        print("✅ 已重建靜態站 docs/")
    except Exception as e:
        print(f"⚠️ 靜態站重建略過:{e}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == '--remove':
        if len(args) != 2:
            print("用法:python update_result.py --remove <match_num>")
            sys.exit(1)
        mn = int(args[1])
        manual_results.remove_override(mn)
        conn = sqlite3.connect(DB_PATH)
        manual_results.clear_match_result(conn, mn)
        conn.close()
        print(f"已撤銷場次 #{mn} 的手動賽果並還原為未開賽,重算中…")
        recompute_everything()
        return

    if len(args) != 3:
        print("用法:python update_result.py <match_num> <home_goals> <away_goals>")
        sys.exit(1)

    mn, hg, ag = int(args[0]), int(args[1]), int(args[2])
    if hg < 0 or ag < 0 or hg > 30 or ag > 30:
        print("比分數值不合理(0–30)。")
        sys.exit(1)

    # 驗證場次存在並顯示對戰
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT home_team, away_team FROM matches WHERE match_num=?', (mn,)).fetchone()
    conn.close()
    if not row:
        print(f"找不到場次 #{mn}")
        sys.exit(1)

    manual_results.set_override(mn, hg, ag)
    print(f"📝 場次 #{mn} {row[0]} {hg}-{ag} {row[1]} 已記錄到 {OVERRIDE_PATH}")
    recompute_everything()


if __name__ == '__main__':
    main()
