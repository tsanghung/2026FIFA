import os
import sys
import sqlite3

# Enforce UTF-8 output on Windows to prevent UnicodeEncodeError (cp950)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')

# Global Kelly strategy settings (Full, Half, Quarter Kelly)
KELLY_FRACTION = 0.5
KELLY_NAME = "半凱利 (50%)"

def get_connection():
    return sqlite3.connect(DB_PATH)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(title):
    print("=" * 75)
    print(f" ⚽  {title:^68}  ⚽")
    print("=" * 75)

def list_upcoming_matches():
    clear_screen()
    print_header("2026 FIFA 世界盃賽程預測與跨平台最佳套利賠率")
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Verify columns exist, otherwise run crawler to initialize
    try:
        cursor.execute('SELECT odds_home_bet365 FROM matches LIMIT 1')
    except sqlite3.OperationalError:
        conn.close()
        import subprocess
        subprocess.run(["python", "odds_crawler.py"], check=True)
        conn = get_connection()
        cursor = conn.cursor()

    cursor.execute('''
        SELECT match_num, group_or_stage, home_team, away_team, 
               pred_home_win_prob, pred_draw_prob, pred_away_win_prob, pred_score,
               odds_home, odds_draw, odds_away,
               odds_home_bet365, odds_home_williamhill, odds_home_draftkings,
               odds_draw_bet365, odds_draw_williamhill, odds_draw_draftkings,
               odds_away_bet365, odds_away_williamhill, odds_away_draftkings
        FROM matches
        ORDER BY match_num ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    print(f"{'場次':<4} | {'階段/組別':<9} | {'對戰組合':<28} | {'預測勝率(主/和/客)':<18} | {'比分':<4} | {'最佳主勝':<8} | {'最佳和局':<8} | {'最佳客勝':<8}")
    print("-" * 110)
    
    for row in rows[:20]: # Show first 20 for readability
        (num, stage, home, away, ph, pd, pa, pred_score, oh, od, oa,
         oh_b, oh_w, oh_d, od_b, od_w, od_d, oa_b, oa_w, oa_d) = row
         
        matchup = f"{home} vs {away}"
        probs = f"{ph*100:.1f}%/{pd*100:.1f}%/{pa*100:.1f}%"
        
        # Helper to find where the best odds come from
        def get_source(best, b, w, d):
            if not best: return ""
            if best == b: return "365"
            if best == w: return "WH"
            if best == d: return "DK"
            return ""
            
        src_h = get_source(oh, oh_b, oh_w, oh_d)
        src_d = get_source(od, od_b, od_w, od_d)
        src_a = get_source(oa, oa_b, oa_w, oa_d)
        
        disp_h = f"{oh:.2f}({src_h})" if oh else "VS"
        disp_d = f"{od:.2f}({src_d})" if od else "VS"
        disp_a = f"{oa:.2f}({src_a})" if oa else "VS"
        
        print(f"#{num:<3} | {stage:<9} | {matchup:<28} | {probs:<18} | {pred_score:^4} | {disp_h:<8} | {disp_d:<8} | {disp_a:<8}")
        
    if len(rows) > 20:
        print(f"\n💡 註：賠率括號中代號分別為：365=Bet365, WH=William Hill, DK=DraftKings (僅顯示前 20 場)")
    input("\n[ 按 Enter 鍵回到主選單 ]")

def update_odds():
    clear_screen()
    print_header("手動更新/追蹤特定平台之賽事賠率")
    
    match_num = input("請輸入想要更新賠率的場次編號 (例如 1): ").strip()
    if not match_num.isdigit():
        print("❌ 輸入無效，編號必須為數字。")
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    match_num = int(match_num)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT home_team, away_team, pred_home_win_prob, pred_draw_prob, pred_away_win_prob,
               odds_home_bet365, odds_draw_bet365, odds_away_bet365,
               odds_home_williamhill, odds_draw_williamhill, odds_away_williamhill,
               odds_home_draftkings, odds_draw_draftkings, odds_away_draftkings
        FROM matches WHERE match_num = ?
    ''', (match_num,))
    match = cursor.fetchone()
    
    if not match:
        print("❌ 找不到此場次！")
        conn.close()
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    (home, away, p_h, p_d, p_a,
     oh_b, od_b, oa_b, oh_w, od_w, oa_w, oh_d, od_d, oa_d) = match
     
    # Query advanced team ratings
    cursor.execute('''
        SELECT elo_rating, pi_rating_home, berrar_att, berrar_def 
        FROM teams WHERE name = ?
    ''', (home,))
    row_home = cursor.fetchone()
    cursor.execute('''
        SELECT elo_rating, pi_rating_away, berrar_att, berrar_def 
        FROM teams WHERE name = ?
    ''', (away,))
    row_away = cursor.fetchone()
    
    h_elo, h_pi, h_att, h_def = row_home if row_home else (1400.0, 0.0, 1.0, 1.0)
    a_elo, a_pi, a_att, a_def = row_away if row_away else (1400.0, 0.0, 1.0, 1.0)
     
    print(f"\n⚽ 場次 #{match_num}：{home} vs {away}")
    print(f"🎯 小賽集成預測勝率 -> 主勝: {p_h*100:.2f}%, 和局: {p_d*100:.2f}%, 客勝: {p_a*100:.2f}%")
    print(f"📊 【{home}】(主) -> Elo: {h_elo:.1f} | Pi-Rating(主場): {h_pi:+.2f} | Berrar 攻/防: {h_att:.2f}/{h_def:.2f}")
    print(f"📊 【{away}】(客) -> Elo: {a_elo:.1f} | Pi-Rating(客場): {a_pi:+.2f} | Berrar 攻/防: {a_att:.2f}/{a_def:.2f}")
    print("-" * 75)
    print("📊 目前資料庫中三大博弈巨頭實時賠率狀態：")
    print(f"   👉 Bet365:      主勝: {oh_b if oh_b else '無':<5} | 和局: {od_b if od_b else '無':<5} | 客勝: {oa_b if oa_b else '無'}")
    print(f"   👉 William Hill: 主勝: {oh_w if oh_w else '無':<5} | 和局: {od_w if od_w else '無':<5} | 客勝: {oa_w if oa_w else '無'}")
    print(f"   👉 DraftKings:   主勝: {oh_d if oh_d else '無':<5} | 和局: {od_d if od_d else '無':<5} | 客勝: {oa_d if oa_d else '無'}")
    print("-" * 75)
    
    print("請選擇你要更新賠率的平台：")
    print("  [1] Bet365")
    print("  [2] William Hill")
    print("  [3] DraftKings")
    p_choice = input("請選擇平台 (1-3): ").strip()
    
    p_key = None
    if p_choice == '1': p_key = 'bet365'
    elif p_choice == '2': p_key = 'williamhill'
    elif p_choice == '3': p_key = 'draftkings'
    else:
        print("❌ 無效選擇！")
        conn.close()
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    print(f"\n錄入 【{p_key.upper()}】 平台之賠率：")
    try:
        oh = float(input(f" 👉 請輸入主勝賠率: "))
        od = float(input(f" 👉 請輸入和局賠率: "))
        oa = float(input(f" 👉 請輸入客勝賠率: "))
    except ValueError:
        print("❌ 賠率必須為數字。")
        conn.close()
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    # Calculate EV and Kelly for this platform
    evh = (p_h * oh) - 1.0
    evd = (p_d * od) - 1.0
    eva = (p_a * oa) - 1.0
    
    kh = max(0.0, evh / (oh - 1.0)) if evh > 0 else 0.0
    kd = max(0.0, evd / (od - 1.0)) if evd > 0 else 0.0
    ka = max(0.0, eva / (oa - 1.0)) if eva > 0 else 0.0
    
    # Save platform specific odds
    cursor.execute(f'''
        UPDATE matches 
        SET odds_home_{p_key} = ?, odds_draw_{p_key} = ?, odds_away_{p_key} = ?,
            ev_home_{p_key} = ?, ev_draw_{p_key} = ?, ev_away_{p_key} = ?,
            kelly_home_{p_key} = ?, kelly_draw_{p_key} = ?, kelly_away_{p_key} = ?
        WHERE match_num = ?
    ''', (oh, od, oa, evh, evd, eva, kh, kd, ka, match_num))
    
    # Re-evaluate best odds (cross-platform max)
    cursor.execute('''
        SELECT odds_home_bet365, odds_home_williamhill, odds_home_draftkings,
               odds_draw_bet365, odds_draw_williamhill, odds_draw_draftkings,
               odds_away_bet365, odds_away_williamhill, odds_away_draftkings
        FROM matches WHERE match_num = ?
    ''', (match_num,))
    
    all_o = cursor.fetchone()
    oh_b, oh_w, oh_d, od_b, od_w, od_d, oa_b, oa_w, oa_d = all_o
    
    best_h = max([x for x in [oh_b, oh_w, oh_d] if x is not None], default=oh)
    best_d = max([x for x in [od_b, od_w, od_d] if x is not None], default=od)
    best_a = max([x for x in [oa_b, oa_w, oa_d] if x is not None], default=oa)
    
    ev_h = (p_h * best_h) - 1.0
    ev_d = (p_d * best_d) - 1.0
    ev_a = (p_a * best_a) - 1.0
    
    k_h = max(0.0, ev_h / (best_h - 1.0)) if ev_h > 0 else 0.0
    k_d = max(0.0, ev_d / (best_d - 1.0)) if ev_d > 0 else 0.0
    k_a = max(0.0, ev_a / (best_a - 1.0)) if ev_a > 0 else 0.0
    
    cursor.execute('''
        UPDATE matches
        SET odds_home = ?, odds_draw = ?, odds_away = ?,
            ev_home = ?, ev_draw = ?, ev_away = ?,
            kelly_home = ?, kelly_draw = ?, kelly_away = ?
        WHERE match_num = ?
    ''', (best_h, best_d, best_a, ev_h, ev_d, ev_a, k_h, k_d, k_a, match_num))
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 平台 【{p_key.upper()}】 賠率已成功更新，並動態校準了跨平台最優套利值！")
    input("\n[ 按 Enter 鍵回到主選單 ]")

def show_value_bets():
    clear_screen()
    print_header("篩選高勝率「正期望值 (EV+)」價值投注篩選面板")
    print("請選擇欲進行分析篩選的模式：")
    print("  [1] 🥇 跨平台最佳套利組合分析 (Best Cross-Platform Value)")
    print("  [2] 🟢 僅篩選 Bet365 獨贏盤")
    print("  [3] 🔵 僅篩選 William Hill 獨贏盤")
    print("  [4] 🔴 僅篩選 DraftKings 獨贏盤")
    print("-" * 50)
    choice = input("請選擇篩選模式 (1-4): ").strip()
    
    mode_name = "跨平台最佳套利組合"
    col_prefix = ""
    
    if choice == '2':
        mode_name = "Bet365 單平台"
        col_prefix = "_bet365"
    elif choice == '3':
        mode_name = "William Hill 單平台"
        col_prefix = "_williamhill"
    elif choice == '4':
        mode_name = "DraftKings 單平台"
        col_prefix = "_draftkings"
    
    clear_screen()
    print_header(f"🔥 {mode_name} ─ 高價值投注推薦選項 (採用 {KELLY_NAME})")
    
    conn = get_connection()
    cursor = conn.cursor()
    
    query = f'''
        SELECT match_num, home_team, away_team, 
               pred_home_win_prob, odds_home{col_prefix}, ev_home{col_prefix}, kelly_home{col_prefix},
               pred_draw_prob, odds_draw{col_prefix}, ev_draw{col_prefix}, kelly_draw{col_prefix},
               pred_away_win_prob, odds_away{col_prefix}, ev_away{col_prefix}, kelly_away{col_prefix},
               odds_home_bet365, odds_home_williamhill, odds_home_draftkings,
               odds_draw_bet365, odds_draw_williamhill, odds_draw_draftkings,
               odds_away_bet365, odds_away_williamhill, odds_away_draftkings
        FROM matches
        WHERE ev_home{col_prefix} > 0 OR ev_draw{col_prefix} > 0 OR ev_away{col_prefix} > 0
    '''
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        conn.close()
        print("\n ⚠️  資料庫中缺少多平台追蹤數據，請先運行賠率爬蟲腳本！")
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    conn.close()
    
    if not rows:
        print(f"\n ⚠️  目前在【{mode_name}】中沒有找到任何正期望值 (EV > 0) 的選項。請先更新賠率！")
        input("\n[ 按 Enter 鍵回到主選單 ]")
        return
        
    print(f"{'場次':<4} | {'對戰組合':<28} | {'推薦選項':<6} | {'預測勝率':<8} | {'最佳賠率':<8} | {'期望值 (EV)':<10} | {'建議下注比例':<10} | {'來源平台'}")
    print("-" * 100)
    
    for row in rows:
        (num, home, away, ph, oh, evh, kh, pd, od, evd, kd, pa, oa, eva, ka,
         oh_b, oh_w, oh_d, od_b, od_w, od_d, oa_b, oa_w, oa_d) = row
        matchup = f"{home} vs {away}"
        
        def find_bk(best_odds, b, w, d):
            if not best_odds: return "未知"
            platforms = []
            if best_odds == b: platforms.append("Bet365")
            if best_odds == w: platforms.append("WilliamHill")
            if best_odds == d: platforms.append("DraftKings")
            return "/".join(platforms) if platforms else "綜合"

        if evh and evh > 0:
            bk_src = find_bk(oh, oh_b, oh_w, oh_d) if col_prefix == "" else mode_name.split(" ")[0]
            print(f"#{num:<3} | {matchup:<28} | 主勝   | {ph*100:>7.1f}% | {oh:>8.2f} | {evh:>+10.2%} | {kh*KELLY_FRACTION:>10.2%} | {bk_src}")
        if evd and evd > 0:
            bk_src = find_bk(od, od_b, od_w, od_d) if col_prefix == "" else mode_name.split(" ")[0]
            print(f"#{num:<3} | {matchup:<28} | 和局   | {pd*100:>7.1f}% | {od:>8.2f} | {evd:>+10.2%} | {kd*KELLY_FRACTION:>10.2%} | {bk_src}")
        if eva and eva > 0:
            bk_src = find_bk(oa, oa_b, oa_w, oa_d) if col_prefix == "" else mode_name.split(" ")[0]
            print(f"#{num:<3} | {matchup:<28} | 客勝   | {pa*100:>7.1f}% | {oa:>8.2f} | {eva:>+10.2%} | {ka*KELLY_FRACTION:>10.2%} | {bk_src}")
            
    print(f"\n💡 註：目前顯示的建議下注比例採用「{KELLY_NAME}」策略。你可以在主選單隨時切換策略以防禦回撤！")
    input("\n[ 按 Enter 鍵回到主選單 ]")

def reset_odds():
    clear_screen()
    print_header("清除賽事賠率設定")
    match_num = input("請輸入要清除賠率的場次編號 (輸入 'all' 清除所有場次): ").strip()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # List of all target platforms and default columns
    cols = [
        "odds_home", "odds_draw", "odds_away", "ev_home", "ev_draw", "ev_away", "kelly_home", "kelly_draw", "kelly_away",
        "odds_home_bet365", "odds_draw_bet365", "odds_away_bet365", "ev_home_bet365", "ev_draw_bet365", "ev_away_bet365", "kelly_home_bet365", "kelly_draw_bet365", "kelly_away_bet365",
        "odds_home_williamhill", "odds_draw_williamhill", "odds_away_williamhill", "ev_home_williamhill", "ev_draw_williamhill", "ev_away_williamhill", "kelly_home_williamhill", "kelly_draw_williamhill", "kelly_away_williamhill",
        "odds_home_draftkings", "odds_draw_draftkings", "odds_away_draftkings", "ev_home_draftkings", "ev_draw_draftkings", "ev_away_draftkings", "kelly_home_draftkings", "kelly_draw_draftkings", "kelly_away_draftkings"
    ]
    
    set_clause = ", ".join([f"{col} = NULL" for col in cols])
    
    if match_num.lower() == 'all':
        cursor.execute(f'UPDATE matches SET {set_clause}')
        conn.commit()
        print("✅ 所有場次的賠率資料及三大平台獨立追蹤資料皆已成功清除。")
    elif match_num.isdigit():
        match_num = int(match_num)
        cursor.execute(f'UPDATE matches SET {set_clause} WHERE match_num = ?', (match_num,))
        conn.commit()
        print(f"✅ 場次 #{match_num} 的所有平台賠率資料皆已成功清除。")
    else:
        print("❌ 輸入無效。")
        
    conn.close()
    input("\n[ 按 Enter 鍵回到主選單 ]")

def change_kelly_strategy():
    global KELLY_FRACTION, KELLY_NAME
    clear_screen()
    print_header("⚙️ 設定資金控管策略 (Kelly Fractional Strategy)")
    print(f"目前設定為：{KELLY_NAME}")
    print("-" * 50)
    print("  [1] 全凱利 (Full Kelly - 100%)       --> 最大化幾何增長，但波動與風險極大")
    print("  [2] 半凱利 (Half Kelly - 50% - 推薦) --> 最優風險與回報平衡，強烈推薦")
    print("  [3] 四分之一凱利 (Quarter Kelly - 25%) --> 適合保守投資或高波動信心低賽局")
    print("  [B] 返回主選單")
    print("-" * 50)
    choice = input("請選擇策略 (1-3 或 B): ").strip()
    if choice == '1':
        KELLY_FRACTION = 1.0
        KELLY_NAME = "全凱利 (100%)"
        print("✅ 策略已成功切換為：全凱利 (100%)")
    elif choice == '2':
        KELLY_FRACTION = 0.5
        KELLY_NAME = "半凱利 (50%)"
        print("✅ 策略已成功切換為：半凱利 (50%)")
    elif choice == '3':
        KELLY_FRACTION = 0.25
        KELLY_NAME = "四分之一凱利 (25%)"
        print("✅ 策略已成功切換為：四分之一凱利 (25%)")
    elif choice.lower() == 'b':
        return
    else:
        print("❌ 無效選擇，保持原設定。")
    import time
    time.sleep(1)

def run_odds_crawler_cli():
    clear_screen()
    print_header("觸發實時賠率同步更新任務")
    print("正在執行三大平台賠率同步與重新校準程序，請稍候...")
    print("-" * 50)
    
    try:
        import subprocess
        subprocess.run(["python", "odds_crawler.py"], check=True)
        print("\n✅ 實時賠率數據抓取與套利計算成功完成！")
    except Exception as e:
        print(f"\n❌ 同步失敗: {e}")
        
    input("\n[ 按 Enter 鍵回到主選單 ]")

def main():
    while True:
        clear_screen()
        print("=" * 75)
        print("  ⚽  2026 FIFA 世界盃 5 大博弈分析與多莊家資金套利決策系統 (小賽版) ⚽ ")
        print("=" * 75)
        print(f"  📢 當前資金控管策略：{KELLY_NAME}")
        print("-" * 75)
        print("  [1] 查看賽程預測、分組與三大平台跨平台套利賠率 (Stage 1 & 2)")
        print("  [2] 手動錄入/追蹤特定平台 (Bet365 / William Hill / DraftKings) 賠率")
        print("  [3] 篩選高勝率值「正期望值 (EV+) 價值投注」(跨平台/單平台)")
        print("  [4] 自動同步抓取三大平台即時賠率 (API/實時模擬更新)")
        print("  [5] 清除賽事賠率紀錄")
        print("  [C] 設定/切換資金控管策略 (全凱利 / 半凱利 / 四分之一凱利)")
        print("  [6] 離開系統")
        print("-" * 75)
        
        choice = input("請輸入選項 (1-6 或 C): ").strip()
        
        if choice == '1':
            list_upcoming_matches()
        elif choice == '2':
            update_odds()
        elif choice == '3':
            show_value_bets()
        elif choice == '4':
            run_odds_crawler_cli()
        elif choice == '5':
            reset_odds()
        elif choice.lower() == 'c':
            change_kelly_strategy()
        elif choice == '6':
            print("\n⚽ 祝賽門兄弟博弈投資大捷，把把紅單！小賽與你下次見！👋")
            break
        else:
            print("❌ 無效選擇，請重新輸入。")
            import time
            time.sleep(1)

if __name__ == '__main__':
    main()
