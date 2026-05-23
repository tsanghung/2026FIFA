import os
import sys
import sqlite3
import random
import time
import math

# Enforce UTF-8 output on Windows to prevent UnicodeEncodeError (cp950)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(title):
    print("=" * 70)
    print(f" 🏟️  {title:^62}  🏟️")
    print("=" * 70)

def migrate_database():
    """
    Schema Migration: Dynamically add statistics columns to the 'matches' table
    if they do not already exist. This ensures 100% backward compatibility.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    columns_to_add = [
        ("attacks_home", "INTEGER DEFAULT 0"),
        ("attacks_away", "INTEGER DEFAULT 0"),
        ("dangerous_attacks_home", "INTEGER DEFAULT 0"),
        ("dangerous_attacks_away", "INTEGER DEFAULT 0"),
        ("possession_home", "INTEGER DEFAULT 50"),
        ("possession_away", "INTEGER DEFAULT 50"),
        ("shots_on_target_home", "INTEGER DEFAULT 0"),
        ("shots_on_target_away", "INTEGER DEFAULT 0"),
        ("saves_home", "INTEGER DEFAULT 0"),
        ("saves_away", "INTEGER DEFAULT 0"),
        ("attack_index_home", "REAL DEFAULT 0.0"),
        ("attack_index_away", "REAL DEFAULT 0.0"),
        ("defense_index_home", "REAL DEFAULT 0.0"),
        ("defense_index_away", "REAL DEFAULT 0.0")
    ]
    
    cursor.execute("PRAGMA table_info(matches)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    
    migrated = False
    for col_name, col_type in columns_to_add:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE matches ADD COLUMN {col_name} {col_type}")
            migrated = True
            
    if migrated:
        conn.commit()
    conn.close()

def trigger_recalculation():
    """
    Invokes the sequential Elo rating update and prediction recalibration engine.
    """
    try:
        from sync_fifa import reset_and_recalculate_all_elo_and_predictions
        reset_and_recalculate_all_elo_and_predictions()
        print("\n⚡ [動態重算引擎] 成功重新校準世界盃所有後續賽事之勝率、賠率與凱利推薦！")
    except Exception as e:
        print(f"\n⚠️ 觸發重算時發生錯誤: {e}")
        print("正在嘗試使用外部子程序執行...")
        try:
            import subprocess
            subprocess.run(["python", "-c", "from sync_fifa import reset_and_recalculate_all_elo_and_predictions; reset_and_recalculate_all_elo_and_predictions()"], check=True)
            print("⚡ [動態重算引擎] 子程序校準成功！")
        except Exception as e2:
            print(f"❌ 無法執行重新校準: {e2}")

def calculate_analytics_indices(h_goals, a_goals, h_attacks, a_attacks, h_danger, a_danger, h_shots, a_shots, h_saves, a_saves, h_poss, a_poss):
    """
    Calculates advanced quant Attack and Defense indices based on live stats.
    """
    # Attack Index = Attacks*0.15 + Dangerous*0.45 + Shots*2.0 + Goals*15.0
    att_home = h_attacks * 0.15 + h_danger * 0.45 + h_shots * 2.0 + h_goals * 15.0
    att_away = a_attacks * 0.15 + a_danger * 0.45 + a_shots * 2.0 + a_goals * 15.0
    
    # Defense Index = (Opponent Attacks - Opponent Dangerous)*0.1 + Saves*3.0 + (100 - Opponent Possession)*0.4
    def_home = max(0.0, (a_attacks - a_danger) * 0.1 + h_saves * 3.0 + (100 - a_poss) * 0.4 + (5.0 if a_goals == 0 else 0.0))
    def_away = max(0.0, (h_attacks - h_danger) * 0.1 + a_saves * 3.0 + (100 - h_poss) * 0.4 + (5.0 if h_goals == 0 else 0.0))
    
    return round(att_home, 1), round(att_away, 1), round(def_home, 1), round(def_away, 1)

def show_matches():
    clear_screen()
    print_header("2026 FIFA 世界盃賽事狀態監控面板")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT match_num, group_or_stage, home_team, away_team, 
               home_goals, away_goals, status, score
        FROM matches
        ORDER BY match_num ASC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    print(f"{'場次':<4} | {'階段/組別':<10} | {'對戰組合':<30} | {'比分':<6} | {'狀態':<10}")
    print("-" * 70)
    for r in rows[:30]:  # Show first 30 for clarity
        num, stage, home, away, h_g, a_g, status, score_str = r
        score_disp = score_str if score_str else "VS"
        status_disp = "已結束" if status == "Completed" else "未開賽"
        print(f"#{num:<3} | {stage:<10} | {home + ' vs ' + away:<30} | {score_disp:^6} | {status_disp:<10}")
    
    if len(rows) > 30:
        print(f"... 還有 {len(rows) - 30} 場賽事未顯示 ...")
    input("\n[ 按 Enter 鍵回到主選單 ]")

def manual_update():
    clear_screen()
    print_header("手動錄入賽事實時統計與結果")
    
    match_num = input("請輸入欲更新的場次編號 (例如 1): ").strip()
    if not match_num.isdigit():
        print("❌ 輸入無效，編號必須為數字。")
        time.sleep(1.5)
        return
        
    match_num = int(match_num)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT home_team, away_team FROM matches WHERE match_num = ?", (match_num,))
    row = cursor.fetchone()
    if not row:
        print("❌ 找不到該場次。")
        conn.close()
        time.sleep(1.5)
        return
        
    home, away = row
    print("-" * 50)
    print(f"🏟️ 正在錄入賽事數據：{home} vs {away}")
    print("-" * 50)
    
    try:
        h_goals = int(input(f" 👉 【{home}】最終進球數: ").strip())
        a_goals = int(input(f" 👉 【{away}】最終進球數: ").strip())
        
        print("\n💡 下列為選填數據（直接按 Enter 將代入合理行業平均值）：")
        h_poss_inp = input(f" 👉 【{home}】控球率 % (例如 55): ").strip()
        h_poss = int(h_poss_inp) if h_poss_inp else 50
        a_poss = 100 - h_poss
        
        h_att_inp = input(f" 👉 【{home}】進攻次數 (例如 105): ").strip()
        h_att = int(h_att_inp) if h_att_inp else random.randint(85, 120)
        
        a_att_inp = input(f" 👉 【{away}】進攻次數 (例如 95): ").strip()
        a_att = int(a_att_inp) if a_att_inp else random.randint(85, 120)
        
        h_danger_inp = input(f" 👉 【{home}】危險進攻次數 (例如 62): ").strip()
        h_danger = int(h_danger_inp) if h_danger_inp else int(h_att * random.uniform(0.4, 0.6))
        
        a_danger_inp = input(f" 👉 【{away}】危險進攻次數 (例如 48): ").strip()
        a_danger = int(a_danger_inp) if a_danger_inp else int(a_att * random.uniform(0.4, 0.6))
        
        h_shots_inp = input(f" 👉 【{home}】射正次數 (例如 6): ").strip()
        h_shots = int(h_shots_inp) if h_shots_inp else max(h_goals, random.randint(1, 8))
        
        a_shots_inp = input(f" 👉 【{away}】射正次數 (例如 3): ").strip()
        a_shots = int(a_shots_inp) if a_shots_inp else max(a_goals, random.randint(1, 8))
        
        h_saves_inp = input(f" 👉 【{home}】守門員撲救次數 (例如 2): ").strip()
        h_saves = int(h_saves_inp) if h_saves_inp else max(0, a_shots - a_goals)
        
        a_saves_inp = input(f" 👉 【{away}】守門員撲救次數 (例如 4): ").strip()
        a_saves = int(a_saves_inp) if a_saves_inp else max(0, h_shots - h_goals)
        
    except ValueError:
        print("❌ 輸入資料型態有誤，必須為整數數字。")
        conn.close()
        time.sleep(1.5)
        return
        
    # Calculate attack/defense indices
    att_h, att_a, def_h, def_a = calculate_analytics_indices(
        h_goals, a_goals, h_att, a_att, h_danger, a_danger, h_shots, a_shots, h_saves, a_saves, h_poss, a_poss
    )
    
    score_str = f"{h_goals}:{a_goals}"
    
    cursor.execute('''
        UPDATE matches
        SET score = ?, home_goals = ?, away_goals = ?, status = 'Completed',
            possession_home = ?, possession_away = ?,
            attacks_home = ?, attacks_away = ?,
            dangerous_attacks_home = ?, dangerous_attacks_away = ?,
            shots_on_target_home = ?, shots_on_target_away = ?,
            saves_home = ?, saves_away = ?,
            attack_index_home = ?, attack_index_away = ?,
            defense_index_home = ?, defense_index_away = ?
        WHERE match_num = ?
    ''', (score_str, h_goals, a_goals, h_poss, a_poss, h_att, a_att, h_danger, a_danger,
          h_shots, a_shots, h_saves, a_saves, att_h, att_a, def_h, def_a, match_num))
    
    conn.commit()
    conn.close()
    
    print("\n✅ 比賽數據已成功寫入 SQLite 資料庫！")
    print("-" * 50)
    print(f"📊 【{home}】攻擊指數: {att_h} | 防守指數: {def_h}")
    print(f"📊 【{away}】攻擊指數: {att_a} | 防守指數: {def_a}")
    print("-" * 50)
    
    # Trigger Elo recalculation and predictive recalibration
    trigger_recalculation()
    input("\n[ 按 Enter 鍵回到主選單 ]")

def simulate_live_match():
    clear_screen()
    print_header("2026 FIFA 世界盃 ─ 動態隨機實時模擬引擎")
    
    match_num = input("請選擇欲進行現場文字直播模擬的場次編號 (例如 1): ").strip()
    if not match_num.isdigit():
        print("❌ 輸入無效。")
        time.sleep(1.5)
        return
        
    match_num = int(match_num)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.home_team, m.away_team, 
               t_h.elo_rating, t_h.fifa_rank, t_h.pi_rating_home, t_h.berrar_att, t_h.berrar_def,
               t_a.elo_rating, t_a.fifa_rank, t_a.pi_rating_away, t_a.berrar_att, t_a.berrar_def
        FROM matches m
        LEFT JOIN teams t_h ON m.home_team = t_h.name
        LEFT JOIN teams t_a ON m.away_team = t_a.name
        WHERE m.match_num = ?
    ''', (match_num,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        print("❌ 找不到該場次。")
        time.sleep(1.5)
        return
        
    (home, away, h_elo, h_rank, home_pi_h, home_att, home_def,
     a_elo, a_rank, away_pi_a, away_att, away_def) = row
     
    h_elo = h_elo if h_elo else 1400.0
    h_rank = h_rank if h_rank else 50
    home_pi_h = home_pi_h if home_pi_h else 0.0
    home_att = home_att if home_att else 1.0
    home_def = home_def if home_def else 1.0
    
    a_elo = a_elo if a_elo else 1400.0
    a_rank = a_rank if a_rank else 50
    away_pi_a = away_pi_a if away_pi_a else 0.0
    away_att = away_att if away_att else 1.0
    away_def = away_def if away_def else 1.0
    
    # Elo Lambdas
    elo_diff = h_elo - a_elo
    rank_diff = a_rank - h_rank
    effective_elo = elo_diff + (rank_diff * 4.0)
    lambda_elo_home = 1.25 * (10 ** (effective_elo / 1000.0))
    lambda_elo_away = 1.25 * (10 ** (-effective_elo / 1000.0))
    
    # Berrar Lambdas
    avg_home = 1.25
    avg_away = 1.05
    lambda_berrar_home = avg_home * home_att * away_def
    lambda_berrar_away = avg_away * away_att * home_def
    
    # Hybrid lambdas (50% Elo, 50% Berrar)
    h_lambda = 0.5 * lambda_elo_home + 0.5 * lambda_berrar_home
    a_lambda = 0.5 * lambda_elo_away + 0.5 * lambda_berrar_away
    
    # Run dynamic live match minute loop
    h_goals, a_goals = 0, 0
    h_att, a_att = 0, 0
    h_danger, a_danger = 0, 0
    h_shots, a_shots = 0, 0
    h_saves, a_saves = 0, 0
    h_poss = 50
    
    events_pool = [
        "中場激烈的球權爭奪中，雙方互有攻守。",
        "傳球失誤！在中圈附近被攔截！",
        "在邊線展開短傳配合，試圖尋找防守漏洞。",
        "前場精彩的二過一配合！但可惜越位在先。",
        "防守球員做出一次極為關鍵的乾淨滑鏟，化解了反擊威脅！",
        "外圍嘗試遠射，可惜偏出立柱。"
    ]
    
    clear_screen()
    print("=" * 70)
    print(f" 🔴 LIVE 實況文字直播動態展開：{home} vs {away} 🏟️")
    print("=" * 70)
    print(" 🏁 比賽開始！主審吹響了開場哨音！")
    print("-" * 70)
    time.sleep(1.0)
    
    for minute in range(1, 91):
        # Possession random walk based on strengths
        pos_shift = random.randint(-4, 4)
        h_poss = max(30, min(70, h_poss + pos_shift))
        a_poss = 100 - h_poss
        
        # Determine which team attacks based on strength lambda
        event_roll = random.random()
        
        if event_roll < (h_lambda * 0.05):
            # Home Attack
            h_att += 1
            if random.random() < 0.55:
                h_danger += 1
                if random.random() < 0.40:
                    h_shots += 1
                    # Shot!
                    if random.random() < 0.30:
                        h_goals += 1
                        print(f" ⚽ 【{minute}' GOAL!!!】{home} 破門得分！場上比分變更為 【{home} {h_goals}:{a_goals} {away}】！")
                        time.sleep(0.8)
                    else:
                        a_saves += 1
                        print(f" 🧤 【{minute}' 撲救！】{home} 發動精妙射門，但被 {away} 守門員飛身神勇化解！")
                else:
                    print(f" ⚠️ 【{minute}' 險境】{home} 突入禁區橫傳，可惜接應隊員慢了一步被解圍！")
        
        elif event_roll < ((h_lambda + a_lambda) * 0.05):
            # Away Attack
            a_att += 1
            if random.random() < 0.55:
                a_danger += 1
                if random.random() < 0.40:
                    a_shots += 1
                    # Shot!
                    if random.random() < 0.30:
                        a_goals += 1
                        print(f" ⚽ 【{minute}' GOAL!!!】{away} 破門得分！場上比分變更為 【{home} {h_goals}:{a_goals} {away}】！")
                        time.sleep(0.8)
                    else:
                        h_saves += 1
                        print(f" 🧤 【{minute}' 撲救！】{away} 外圍發炮，被 {home} 守門員穩穩單掌托出底線！")
                else:
                    print(f" ⚠️ 【{minute}' 險境】{away} 在前場獲得自由球機會，吊入禁區被門將摘下！")
        
        else:
            # Minor random commentary every 15 mins
            if minute % 15 == 0:
                cmt = random.choice(events_pool)
                print(f" ⏱️ 【{minute}' 賽況】{cmt}")
                
        # Real-time dashboard update speed (very responsive)
        time.sleep(0.04)
        
    print("-" * 70)
    print(f" 🛑 嗶─ 嗶─ 嗶─！全場比賽結束！最終比分為 【{home} {h_goals}：{a_goals} {away}】")
    print("=" * 70)
    
    # Calculate index
    att_h, att_a, def_h, def_a = calculate_analytics_indices(
        h_goals, a_goals, h_att, a_att, h_danger, a_danger, h_shots, a_shots, h_saves, a_saves, h_poss, a_poss
    )
    
    print(" 📊 【本場戰略量化分析報告】")
    print(f"   👉 控球率: {home} {h_poss}% - {a_poss}% {away}")
    print(f"   👉 進攻次數: {home} {h_att} - {a_att} {away}")
    print(f"   👉 危險進攻: {home} {h_danger} - {a_danger} {away}")
    print(f"   👉 射正/撲救: {home} {h_shots}/{h_saves} - {a_shots}/{a_saves} {away}")
    print(f"   ⚡ 【{home}】攻擊指數: {att_h} | 防守指數: {def_h}")
    print(f"   ⚡ 【{away}】攻擊指數: {att_a} | 防守指數: {def_a}")
    print("=" * 70)
    
    save_choice = input("是否要將此模擬結果正式寫入 SQLite 資料庫並動態校準後續所有預測？(Y/N): ").strip().upper()
    if save_choice == 'Y':
        conn = get_connection()
        cursor = conn.cursor()
        score_str = f"{h_goals}:{a_goals}"
        
        cursor.execute('''
            UPDATE matches
            SET score = ?, home_goals = ?, away_goals = ?, status = 'Completed',
                possession_home = ?, possession_away = ?,
                attacks_home = ?, attacks_away = ?,
                dangerous_attacks_home = ?, dangerous_attacks_away = ?,
                shots_on_target_home = ?, shots_on_target_away = ?,
                saves_home = ?, saves_away = ?,
                attack_index_home = ?, attack_index_away = ?,
                defense_index_home = ?, defense_index_away = ?
            WHERE match_num = ?
        ''', (score_str, h_goals, a_goals, h_poss, a_poss, h_att, a_att, h_danger, a_danger,
              h_shots, a_shots, h_saves, a_saves, att_h, att_a, def_h, def_a, match_num))
        
        conn.commit()
        conn.close()
        print("\n✅ 數據已寫入資料庫！")
        trigger_recalculation()
    else:
        print("\n⚠️ 模擬結果已被捨棄，資料庫未作任何變更。")
        
    input("\n[ 按 Enter 鍵返回主選單 ]")

def main():
    migrate_database()
    while True:
        clear_screen()
        print("=" * 70)
        print(" 🏟️   2026 FIFA 世界盃開賽實況數據錄入與分析系統 (小賽版) 🏟️")
        print("=" * 70)
        print("  [1] 監控目前所有賽事狀態與比分紀錄")
        print("  [2] 手動錄入賽事完賽數據 (進球數、控球、攻擊與防守指數)")
        print("  [3] 動態文字實況直播模擬器 (萬次卜瓦松隨機實時模擬戰況)")
        print("  [4] 返回/離開系統")
        print("-" * 70)
        
        choice = input("請輸入選項 (1-4): ").strip()
        
        if choice == '1':
            show_matches()
        elif choice == '2':
            manual_update()
        elif choice == '3':
            simulate_live_match()
        elif choice == '4':
            print("\n⚽ 賽事追蹤完成！祝賽門兄弟博弈長青！👋")
            break
        else:
            print("❌ 無效選擇，請重新輸入。")
            time.sleep(1)

if __name__ == '__main__':
    main()
