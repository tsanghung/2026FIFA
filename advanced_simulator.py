import os
import sys
import math
import random
import sqlite3
import time

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
    print(f" 🎲  {title:^62}  🎲")
    print("=" * 70)

def get_poisson_random(lamb):
    """
    Using Knuth's algorithm to sample from a Poisson distribution in pure Python
    """
    if lamb <= 0:
        return 0
    L = math.exp(-lamb)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1

def run_monte_carlo(home_team, away_team, home_lambda, away_lambda, num_iterations=100000):
    """
    Executes a high-speed Monte Carlo simulation for 100,000 matches.
    Aggregates Moneyline, Over/Under 2.5, and Both Teams to Score (BTTS).
    """
    home_win_count = 0
    draw_count = 0
    away_win_count = 0
    
    ou_over_count = 0  # Total goals > 2.5
    btts_count = 0     # Both teams score >= 1
    
    score_frequencies = {}
    home_goal_sum = 0
    away_goal_sum = 0
    
    # Executing the simulation loop
    for _ in range(num_iterations):
        h_goals = get_poisson_random(home_lambda)
        a_goals = get_poisson_random(away_lambda)
        
        home_goal_sum += h_goals
        away_goal_sum += a_goals
        
        # 1. Moneyline
        if h_goals > a_goals:
            home_win_count += 1
        elif h_goals == a_goals:
            draw_count += 1
        else:
            away_win_count += 1
            
        # 2. Over / Under 2.5
        if (h_goals + a_goals) > 2.5:
            ou_over_count += 1
            
        # 3. Both Teams to Score (BTTS)
        if h_goals > 0 and a_goals > 0:
            btts_count += 1
            
        # Record score frequency
        score = f"{h_goals}-{a_goals}"
        score_frequencies[score] = score_frequencies.get(score, 0) + 1
        
    # Calculate probabilities
    p_home = home_win_count / num_iterations
    p_draw = draw_count / num_iterations
    p_away = away_win_count / num_iterations
    p_over = ou_over_count / num_iterations
    p_under = 1.0 - p_over
    p_btts = btts_count / num_iterations
    
    # Calculate Standard Error (SE) using Central Limit Theorem: SE = sqrt(p*(1-p)/N)
    se_home = math.sqrt(p_home * (1 - p_home) / num_iterations)
    se_draw = math.sqrt(p_draw * (1 - p_draw) / num_iterations)
    se_away = math.sqrt(p_away * (1 - p_away) / num_iterations)
    
    # Sort scores by frequency
    sorted_scores = sorted(score_frequencies.items(), key=lambda x: x[1], reverse=True)
    
    return {
        'p_home': p_home, 'p_draw': p_draw, 'p_away': p_away,
        'se_home': se_home, 'se_draw': se_draw, 'se_away': se_away,
        'p_over': p_over, 'p_under': p_under, 'p_btts': p_btts,
        'avg_home_goals': home_goal_sum / num_iterations,
        'avg_away_goals': away_goal_sum / num_iterations,
        'top_scores': sorted_scores[:5]
    }

def main():
    while True:
        clear_screen()
        print_header("2026 FIFA 世界盃蒙地卡羅萬次模擬器 (量化極致版)")
        print("  📢 本系統採用 100,000 次虛擬隨機對戰，模擬包含勝負、大小盤及BTTS！")
        print("-" * 70)
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT match_num, home_team, away_team, 
                   home_pre_match_elo, away_pre_match_elo
            FROM matches 
            ORDER BY match_num ASC LIMIT 20
        ''')
        matches = cursor.fetchall()
        
        print(f"{'場次':<4} | {'對戰組合':<36} | {'主隊 Elo':<10} | {'客隊 Elo':<10}")
        print("-" * 70)
        for m in matches:
            num, home, away, h_elo, a_elo = m
            h_elo_val = f"{h_elo:.1f}" if h_elo else "1400.0"
            a_elo_val = f"{a_elo:.1f}" if a_elo else "1400.0"
            print(f"#{num:<3} | {home + ' vs ' + away:<36} | {h_elo_val:<10} | {a_elo_val:<10}")
            
        print("-" * 70)
        match_input = input("請輸入欲進行蒙地卡羅模擬的場次編號 (輸入 'Q' 離開): ").strip()
        
        if match_input.upper() == 'Q':
            print("\n👋 感謝使用蒙地卡羅模擬器！祝賽門兄弟旗開得勝！")
            conn.close()
            break
            
        if not match_input.isdigit():
            print("❌ 輸入無效，請重新選擇。")
            conn.close()
            time.sleep(1.5)
            continue
            
        match_num = int(match_input)
        
        # Fetch detailed team ranks and all ratings (Elo, Pi-Rating, Berrar Ratings)
        cursor.execute('''
            SELECT m.home_team, m.away_team, 
                   t_h.elo_rating, t_h.fifa_rank, t_h.pi_rating_home, t_h.berrar_att, t_h.berrar_def,
                   t_a.elo_rating, t_a.fifa_rank, t_a.pi_rating_away, t_a.berrar_att, t_a.berrar_def
            FROM matches m
            LEFT JOIN teams t_h ON m.home_team = t_h.name
            LEFT JOIN teams t_a ON m.away_team = t_a.name
            WHERE m.match_num = ?
        ''', (match_num,))
        
        match_detail = cursor.fetchone()
        if not match_detail:
            print("❌ 找不到該場次，請輸入清單中的數字。")
            conn.close()
            time.sleep(1.5)
            continue
            
        (home, away, h_elo, h_rank, home_pi_h, home_att, home_def,
         a_elo, a_rank, away_pi_a, away_att, away_def) = match_detail
        
        # Default placeholder values if not seeded
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
        
        conn.close()
        
        # Elo Lambdas
        elo_diff = h_elo - a_elo
        rank_diff = a_rank - h_rank
        effective_elo_diff = elo_diff + (rank_diff * 4.0)
        lambda_elo_home = 1.25 * (10 ** (effective_elo_diff / 1000.0))
        lambda_elo_away = 1.25 * (10 ** (-effective_elo_diff / 1000.0))
        
        # Berrar Lambdas
        avg_home = 1.25
        avg_away = 1.05
        lambda_berrar_home = avg_home * home_att * away_def
        lambda_berrar_away = avg_away * away_att * home_def
        
        # Hybrid lambdas (50% Elo, 50% Berrar)
        home_lambda = 0.5 * lambda_elo_home + 0.5 * lambda_berrar_home
        away_lambda = 0.5 * lambda_elo_away + 0.5 * lambda_berrar_away
        
        clear_screen()
        print_header(f"⚽ 正在對戰：{home} vs {away} ⚽")
        print(f"   [戰力指標] 主隊 Elo: {h_elo:.1f} (Rank #{h_rank}) | 客隊 Elo: {a_elo:.1f} (Rank #{a_rank})")
        print(f"   [進球期望] 主隊 xG: {home_lambda:.3f} | 客隊 xG: {away_lambda:.3f}")
        print("\n🎲 正在啟動蒙地卡羅運算引擎，執行 100,000 次隨機抽樣模擬...")
        
        start_time = time.time()
        sim = run_monte_carlo(home, away, home_lambda, away_lambda, num_iterations=100000)
        duration = time.time() - start_time
        
        print(f"✅ 運算完成！耗時 {duration:.3f} 秒。")
        print("=" * 70)
        print(f" 📊  100,000 次對戰結果頻率匯總 (大數法則收斂結果)：")
        print("-" * 70)
        
        # 1. Moneyline
        print(f"👑 【獨贏盤 (Moneyline)】")
        print(f"   👉 主隊獲勝勝率: {sim['p_home']*100:.2f}% (標準誤差 SE: ±{sim['se_home']*100:.4f}%)")
        print(f"   👉 雙方打平機率: {sim['p_draw']*100:.2f}% (標準誤差 SE: ±{sim['se_draw']*100:.4f}%)")
        print(f"   👉 客隊獲勝勝率: {sim['p_away']*100:.2f}% (標準誤差 SE: ±{sim['se_away']*100:.4f}%)")
        print("-" * 70)
        
        # 2. Over / Under 2.5
        print(f"⚽ 【大小分盤 (Over/Under 2.5)】")
        print(f"   👉 大分 (Total Goals > 2.5) 機率: {sim['p_over']*100:.2f}%")
        print(f"   👉 小分 (Total Goals <= 2.5) 機率: {sim['p_under']*100:.2f}%")
        print("-" * 70)
        
        # 3. Both Teams to Score (BTTS)
        print(f"🔥 【雙方皆進球 (Both Teams to Score)】")
        print(f"   👉 是 (BTTS - Yes) 機率: {sim['p_btts']*100:.2f}%")
        print(f"   👉 否 (BTTS - No) 機率: {(1 - sim['p_btts'])*100:.2f}%")
        print("-" * 70)
        
        # 4. Top Scores
        print(f"🎯 【最常出現的五大精確比分】")
        for i, (score, freq) in enumerate(sim['top_scores'], 1):
            prob = freq / 100000
            bar = "■" * int(prob * 100)
            print(f"   #{i}  比分 {score:<5} | 出現機率: {prob*100:>5.2f}% {bar}")
            
        print("=" * 70)
        print(f"💡 [期望值提示] 模擬平均進球的主隊為 {sim['avg_home_goals']:.2f} 球，客隊為 {sim['avg_away_goals']:.2f} 球。")
        input("\n[ 按 Enter 鍵返回模擬器選單 ]")

if __name__ == '__main__':
    main()
