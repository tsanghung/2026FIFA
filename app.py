import os
import sqlite3
import math
import random
import time
import re
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# 1. Page Config & Premium Sleek Dark Theme
st.set_page_config(
    page_title="2026 FIFA 世界盃集成預測與博弈決策面板",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Team translation dictionary using Traditional Chinese (Taiwanese idioms)
TEAM_TRANSLATIONS = {
    # Group A
    'Mexico': '墨西哥', 'South Korea': '南韓', 'South Africa': '南非', 'Czechia': '捷克', 'Czech Republic': '捷克',
    # Group B
    'Canada': '加拿大', 'Switzerland': '瑞士', 'Qatar': '卡達', 'Bosnia-Herzegovina': '波赫', 'Bosnia and Herzegovina': '波赫',
    # Group C
    'Brazil': '巴西', 'Morocco': '摩洛哥', 'Scotland': '蘇格蘭', 'Haiti': '海地',
    # Group D
    'USA': '美國', 'United States': '美國', 'Paraguay': '巴拉圭', 'Australia': '澳洲', 'Türkiye': '土耳其', 'Turkey': '土耳其',
    # Group E
    'Germany': '德國', 'Ecuador': '厄瓜多', 'Ivory Coast': '象牙海岸', "Côte d'Ivoire": '象牙海岸', 'Curaçao': '庫拉索',
    # Group F
    'Netherlands': '荷蘭', 'Japan': '日本', 'Tunisia': '突尼西亞', 'Sweden': '瑞典',
    # Group G
    'Belgium': '比利時', 'Iran': '伊朗', 'IR Iran': '伊朗', 'Egypt': '埃及', 'New Zealand': '紐西蘭',
    # Group H
    'Spain': '西班牙', 'Uruguay': '烏拉圭', 'Saudi Arabia': '沙烏地阿拉伯', 'Cape Verde': '維德角', 'Cabo Verde': '維德角',
    # Group I
    'France': '法國', 'Senegal': '塞內加爾', 'Norway': '挪威', 'Iraq': '伊拉克',
    # Group J
    'Argentina': '阿根廷', 'Algeria': '阿爾及利亞', 'Austria': '奧地利', 'Jordan': '約旦',
    # Group K
    'Portugal': '葡萄牙', 'Colombia': '哥倫比亞', 'Uzbekistan': '烏茲別克', 'DR Congo': '剛果民主共和國', 'Congo DR': '剛果民主共和國',
    # Group L
    'England': '英格蘭', 'Croatia': '克羅埃西亞', 'Ghana': '迦納', 'Panama': '巴拿馬'
}

def get_team_display_name(eng_name):
    if not eng_name:
        return ""
    eng_name_clean = eng_name.strip()
    zh_name = TEAM_TRANSLATIONS.get(eng_name_clean, eng_name_clean)
    if zh_name != eng_name_clean:
        return f"{zh_name} ({eng_name_clean})"
    
    # Translate common placeholder names for knockouts
    placeholder_map = {
        'Winner Group A': 'A組第一', 'Runner-up Group A': 'A組第二',
        'Winner Group B': 'B組第一', 'Runner-up Group B': 'B組第二',
        'Winner Group C': 'C組第一', 'Runner-up Group C': 'C組第二',
        'Winner Group D': 'D組第一', 'Runner-up Group D': 'D組第二',
        'Winner Group E': 'E組第一', 'Runner-up Group E': 'E組第二',
        'Winner Group F': 'F組第一', 'Runner-up Group F': 'F組第二',
        'Winner Group G': 'G組第一', 'Runner-up Group G': 'G組第二',
        'Winner Group H': 'H組第一', 'Runner-up Group H': 'H組第二',
        'Winner Group I': 'I組第一', 'Runner-up Group I': 'I組第二',
        'Winner Group J': 'J組第一', 'Runner-up Group J': 'J組第二',
        'Winner Group K': 'K組第一', 'Runner-up Group K': 'K組第二',
        'Winner Group L': 'L組第一', 'Runner-up Group L': 'L組第二'
    }
    for k, v in placeholder_map.items():
        if k in eng_name_clean:
            return f"{v} ({eng_name_clean})"
            
    return eng_name_clean

def convert_to_taiwan_time(date_str, time_str):
    if not date_str:
        return "", ""
    if not time_str:
        return date_str, ""
        
    # 清洗 unicode 減號 / hyphen
    time_clean = time_str.replace('\u2212', '-').replace('−', '-').strip()
    
    # 提取時間與 UTC 偏移 (格式如 1:00 p.m. UTC-6 或 12:00 p.m. UTC-4)
    pattern = r'(\d+):(\d+)\s*(a\.m\.|p\.m\.|am|pm)?\s*(?:UTC([+-]\d+))?'
    match = re.search(pattern, time_clean, re.IGNORECASE)
    if not match:
        return date_str, time_clean
        
    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3)
    tz_offset = match.group(4)
    
    # 處理 am/pm 轉換為 24 小時制
    if ampm:
        ampm = ampm.lower().replace('.', '')
        if ampm == 'pm' and hour < 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
            
    # 解析日期並結合時間
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except Exception:
        return date_str, time_clean
        
    dt = dt.replace(hour=hour, minute=minute)
    
    # 預設偏移量 (如果沒有 UTC 標註則不進行時區調整，只輸出 HH:mm)
    if tz_offset:
        offset = int(tz_offset)
        # 台灣是 UTC+8，時間差為 8 - offset
        td_offset = timedelta(hours=8 - offset)
        dt_taiwan = dt + td_offset
        return dt_taiwan.strftime('%Y-%m-%d'), dt_taiwan.strftime('%H:%M')
    else:
        return date_str, f"{hour:02d}:{minute:02d}"

# Custom Glassmorphism Sleek Dark CSS
st.markdown("""
<style>
    /* Sleek Dark Mode General styling */
    .stApp {
        background-color: #0d0f13;
        color: #e2e8f0;
    }
    
    /* Title text styling */
    h1, h2, h3 {
        font-family: 'Outfit', 'Inter', sans-serif;
        font-weight: 700;
        background: linear-gradient(135deg, #38bdf8 0%, #a855f7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    /* Classy Card Container */
    .glass-card {
        background: rgba(30, 41, 59, 0.45);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 20px;
        backdrop-filter: blur(12px);
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #38bdf8;
    }
    
    /* Highlight Winner Source Badge */
    .platform-badge {
        font-size: 0.75rem;
        font-weight: 600;
        padding: 2px 6px;
        border-radius: 4px;
        color: #ffffff;
    }
    
    .badge-365 { background-color: #10b981; }
    .badge-wh { background-color: #3b82f6; }
    .badge-dk { background-color: #ec4899; }
</style>
""", unsafe_allow_html=True)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def check_and_update_db_schema():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(teams)")
        cols = [row[1] for row in cursor.fetchall()]
        new_fields = [
            ("fbref_xg_diff", "REAL NOT NULL DEFAULT 0.0"),
            ("injury_count", "INTEGER NOT NULL DEFAULT 0"),
            ("sentiment_score", "REAL NOT NULL DEFAULT 0.0"),
            ("opta_win_prob", "REAL NOT NULL DEFAULT 0.0")
        ]
        updated = False
        for col_name, col_def in new_fields:
            if col_name not in cols:
                cursor.execute(f"ALTER TABLE teams ADD COLUMN {col_name} {col_def}")
                updated = True
        if updated:
            conn.commit()
        conn.close()
    except Exception:
        pass

# 每次啟動 Web 時自動自我修復資料庫欄位
check_and_update_db_schema()

def poisson_pmf(k, lamb):
    if lamb <= 0:
        return 1.0 if k == 0 else 0.0
    return (lamb ** k) * math.exp(-lamb) / math.factorial(k)

def get_poisson_random(lamb):
    if lamb <= 0:
        return 0
    L = math.exp(-lamb)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1

# Helper to format best odds platform source
def get_odds_badge_html(best, b, w, d):
    if not best: return ""
    if best == b: return '<span class="platform-badge badge-365">Bet365</span>'
    if best == w: return '<span class="platform-badge badge-wh">WHill</span>'
    if best == d: return '<span class="platform-badge badge-dk">DKings</span>'
    return '<span class="platform-badge" style="background-color: #64748b;">Mixed</span>'

# Header
st.title("🏆 2026 FIFA 世界盃量化分析與集成預測決策中樞")
st.write("由 **小賽 (🤖 Antigravity)** 精雕細琢，整合了 Elo、Pi-Rating、Berrar Rating 與 Dixon-Coles 平局修正之極致博弈大腦。")

# 2. Sidebar Configuration Control panel
st.sidebar.header("⚙️ 量化決策控制台")

kelly_strategy = st.sidebar.selectbox(
    "💰 資金控管策略 (Kelly Fraction)",
    ["半凱利 (50% - 推薦)", "全凱利 (100% - 激進)", "四分之一凱利 (25% - 保守)"],
    index=0
)

# Set kelly multiplier based on selection
if "半凱利" in kelly_strategy:
    kelly_fraction = 0.5
    kelly_name = "半凱利 (50%)"
elif "全凱利" in kelly_strategy:
    kelly_fraction = 1.0
    kelly_name = "全凱利 (100%)"
else:
    kelly_fraction = 0.25
    kelly_name = "四分之一凱利 (25%)"

betting_mode = st.sidebar.selectbox(
    "🏦 分析開盤莊家 (Bookmaker Mode)",
    ["🥇 跨平台最佳套利組合", "🟢 僅限 Bet365", "🔵 僅限 William Hill", "🔴 僅限 DraftKings"],
    index=0
)

# Map selections to db columns
mode_map = {
    "🥇 跨平台最佳套利組合": "",
    "🟢 僅限 Bet365": "_bet365",
    "🔵 僅限 William Hill": "_williamhill",
    "🔴 僅限 DraftKings": "_draftkings"
}
col_suffix = mode_map[betting_mode]

st.sidebar.markdown("---")
st.sidebar.subheader("📅 數據同步日誌")
if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync.log')):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync.log'), 'r', encoding='utf-8') as f:
        logs = f.readlines()
        latest_logs = logs[-5:] if len(logs) >= 5 else logs
        for line in reversed(latest_logs):
            st.sidebar.caption(line.strip())
else:
    st.sidebar.caption("尚無同步日誌")

# Tabs
tab_val, tab_sched, tab_monte, tab_teams = st.tabs([
    "🔥 EV+ 價值投注決策中樞", 
    "📅 完整賽程預測與賠率對比", 
    "🎲 蒙地卡羅即時沙盤模擬", 
    "📊 參賽隊伍戰力動態評級"
])

# ================= TAB 1: EV+ Value Bets =================
with tab_val:
    st.header(f"🔥 {betting_mode} ─ 高價值投注篩選面版")
    st.write(f"當前資金決策已套用 **{kelly_name}** 風控模型。篩選結果僅顯示期望值大於零 ($EV > 0$) 的價值投資標的。")
    
    conn = get_db_connection()
    query = f'''
        SELECT match_num, group_or_stage, home_team, away_team, 
               pred_home_win_prob, odds_home{col_suffix}, ev_home{col_suffix}, kelly_home{col_suffix},
               pred_draw_prob, odds_draw{col_suffix}, ev_draw{col_suffix}, kelly_draw{col_suffix},
               pred_away_win_prob, odds_away{col_suffix}, ev_away{col_suffix}, kelly_away{col_suffix},
               odds_home_bet365, odds_home_williamhill, odds_home_draftkings,
               odds_draw_bet365, odds_draw_williamhill, odds_draw_draftkings,
               odds_away_bet365, odds_away_williamhill, odds_away_draftkings
        FROM matches
        WHERE ev_home{col_suffix} > 0 OR ev_draw{col_suffix} > 0 OR ev_away{col_suffix} > 0
    '''
    
    try:
        df_val = pd.read_sql_query(query, conn)
    except Exception as e:
        st.error(f"資料庫讀取失敗：{e}。請確認是否已跑過 `sync_fifa.py` 初始化。")
        df_val = pd.DataFrame()
        
    conn.close()
    
    if df_val.empty:
        st.info("💡 目前沒有找到任何正期望值 (EV > 0) 的選項。莊家開盤非常嚴密，或是需要觸發賠率重新同步！")
    else:
        # Prepare value bet rows
        val_rows = []
        for index, row in df_val.iterrows():
            match_num = int(row['match_num'])
            h_name = get_team_display_name(row['home_team'])
            a_name = get_team_display_name(row['away_team'])
            matchup_disp = f"{h_name} vs {a_name}"
            
            # Sub-function to lookup source
            def get_source_str(best_odds, b, w, d):
                if not best_odds: return "未知"
                srcs = []
                if best_odds == b: srcs.append("Bet365")
                if best_odds == w: srcs.append("WilliamHill")
                if best_odds == d: srcs.append("DraftKings")
                return "/".join(srcs) if srcs else "綜合"
            
            # Home Win EV+
            ev_h = row[f'ev_home{col_suffix}']
            if ev_h and ev_h > 0:
                o_h = row[f'odds_home{col_suffix}']
                src = get_source_str(o_h, row['odds_home_bet365'], row['odds_home_williamhill'], row['odds_home_draftkings']) if col_suffix == "" else betting_mode.split(" ")[1]
                val_rows.append({
                    "場次": f"#{match_num}",
                    "客場": a_name,
                    "主場": h_name,
                    "推薦選項": "主勝 (Home Win)",
                    "小賽預測勝率": f"{row['pred_home_win_prob']*100:.1f}%",
                    "最佳賠率": f"{o_h:.2f}",
                    "期望值 (EV)": f"{ev_h:+.2%}",
                    "建議下注比例": f"{row[f'kelly_home{col_suffix}']*kelly_fraction:.2%}",
                    "來源莊家": src
                })
                
            # Draw EV+
            ev_d = row[f'ev_draw{col_suffix}']
            if ev_d and ev_d > 0:
                o_d = row[f'odds_draw{col_suffix}']
                src = get_source_str(o_d, row['odds_draw_bet365'], row['odds_draw_williamhill'], row['odds_draw_draftkings']) if col_suffix == "" else betting_mode.split(" ")[1]
                val_rows.append({
                    "場次": f"#{match_num}",
                    "客場": a_name,
                    "主場": h_name,
                    "推薦選項": "和局 (Draw)",
                    "小賽預測勝率": f"{row['pred_draw_prob']*100:.1f}%",
                    "最佳賠率": f"{o_d:.2f}",
                    "期望值 (EV)": f"{ev_d:+.2%}",
                    "建議下注比例": f"{row[f'kelly_draw{col_suffix}']*kelly_fraction:.2%}",
                    "來源莊家": src
                })
                
            # Away Win EV+
            ev_a = row[f'ev_away{col_suffix}']
            if ev_a and ev_a > 0:
                o_a = row[f'odds_away{col_suffix}']
                src = get_source_str(o_a, row['odds_away_bet365'], row['odds_away_williamhill'], row['odds_away_draftkings']) if col_suffix == "" else betting_mode.split(" ")[1]
                val_rows.append({
                    "場次": f"#{match_num}",
                    "客場": a_name,
                    "主場": h_name,
                    "推薦選項": "客勝 (Away Win)",
                    "小賽預測勝率": f"{row['pred_away_win_prob']*100:.1f}%",
                    "最佳賠率": f"{o_a:.2f}",
                    "期望值 (EV)": f"{ev_a:+.2%}",
                    "建議下注比例": f"{row[f'kelly_away{col_suffix}']*kelly_fraction:.2%}",
                    "來源莊家": src
                })
                
        if val_rows:
            df_display = pd.DataFrame(val_rows)
            
            # Show summary metrics
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.markdown('<div class="glass-card">💡 推薦投注選項數<div class="metric-value">{} 場</div></div>'.format(len(df_display)), unsafe_allow_html=True)
            with col_m2:
                # Find maximum EV
                max_ev_row = df_display.sort_values(by="期望值 (EV)", ascending=False).iloc[0]
                matchup_max = f"{max_ev_row['主場']} vs {max_ev_row['客場']}"
                st.markdown('<div class="glass-card">🔥 最大期望回報 (EV)<div class="metric-value">{}</div><div style="font-size:0.85rem">{} ({})</div></div>'.format(max_ev_row['期望值 (EV)'], matchup_max, max_ev_row['推薦選項']), unsafe_allow_html=True)
            with col_m3:
                # Max stake
                max_stake_row = df_display.sort_values(by="建議下注比例", ascending=False).iloc[0]
                matchup_max_stake = f"{max_stake_row['主場']} vs {max_stake_row['客場']}"
                st.markdown('<div class="glass-card">🛡️ 風控最重建議投注比<div class="metric-value">{}</div><div style="font-size:0.85rem">{} ({})</div></div>'.format(max_stake_row['建議下注比例'], matchup_max_stake, max_stake_row['推薦選項']), unsafe_allow_html=True)
                
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info("💡 目前沒有符合 EV > 0 條件的下注選擇。")

# ================= TAB 2: Match Schedule =================
with tab_sched:
    st.header("📅 2026 FIFA 世界盃賽程預測與賠率對比")
    st.write("並列顯示三大莊家在該場的 Decimal 賠率。如果沒有 API 即時開盤，將自動調用動態微隨機游走模擬賠率。")
    
    conn = get_db_connection()
    query = '''
        SELECT m.match_num, m.group_or_stage, m.date, m.time, m.home_team, m.away_team, 
               m.pred_home_win_prob, m.pred_draw_prob, m.pred_away_win_prob, m.pred_score,
               m.odds_home, m.odds_draw, m.odds_away, m.status, m.score,
               m.odds_home_bet365, m.odds_home_williamhill, m.odds_home_draftkings,
               m.odds_draw_bet365, m.odds_draw_williamhill, m.odds_draw_draftkings,
               m.odds_away_bet365, m.odds_away_williamhill, m.odds_away_draftkings,
               t_h.injury_count as home_injuries, t_h.sentiment_score as home_sentiment,
               t_a.injury_count as away_injuries, t_a.sentiment_score as away_sentiment
        FROM matches m
        LEFT JOIN teams t_h ON m.home_team = t_h.name
        LEFT JOIN teams t_a ON m.away_team = t_a.name
        ORDER BY m.match_num ASC
    '''
    df_sched = pd.read_sql_query(query, conn)
    conn.close()
    
    # Simple filters
    filter_stage = st.multiselect(
        "篩選賽事階段 (Stage Filter)",
        options=list(df_sched['group_or_stage'].unique()),
        default=[]
    )
    
    display_df = df_sched.copy()
    if filter_stage:
        display_df = display_df[display_df['group_or_stage'].isin(filter_stage)]
        
    # Render table nicely
    rows_html = []
    for idx, r in display_df.iterrows():
        match_num = int(r['match_num'])
        h_name = get_team_display_name(r['home_team'])
        a_name = get_team_display_name(r['away_team'])
        
        # 標註預測勝率較高的一方 (在國家名稱後面加個 👑 符號標示醒目)
        if r['pred_home_win_prob'] > r['pred_away_win_prob']:
            h_name = f"{h_name} 👑"
        elif r['pred_away_win_prob'] > r['pred_home_win_prob']:
            a_name = f"{a_name} 👑"
        
        # 轉換日期與時間為台灣時間 (UTC+8)
        tw_date, tw_time = convert_to_taiwan_time(r['date'], r['time'])
        
        # Win probabilities
        prob_str = f"{r['pred_home_win_prob']*100:.1f}% / {r['pred_draw_prob']*100:.1f}% / {r['pred_away_win_prob']*100:.1f}%"
        
        # Best Odds source rendering
        def get_source_label(best, b, w, d):
            if not best: return "-"
            label = f"{best:.2f}"
            if best == b: label += " (365)"
            elif best == w: label += " (WH)"
            elif best == d: label += " (DK)"
            return label
            
        b_h = get_source_label(r['odds_home'], r['odds_home_bet365'], r['odds_home_williamhill'], r['odds_home_draftkings'])
        b_d = get_source_label(r['odds_draw'], r['odds_draw_bet365'], r['odds_draw_williamhill'], r['odds_draw_draftkings'])
        b_a = get_source_label(r['odds_away'], r['odds_away_bet365'], r['odds_away_williamhill'], r['odds_away_draftkings'])
        
        status_str = "已完賽" if r['status'] == "Completed" else "未開賽"
        score_str = r['score'] if r['score'] else "VS"
        
        # 提取外部情報變量
        h_inj = int(r['home_injuries']) if 'home_injuries' in r and pd.notnull(r['home_injuries']) else 0
        h_sent = float(r['home_sentiment']) if 'home_sentiment' in r and pd.notnull(r['home_sentiment']) else 0.0
        a_inj = int(r['away_injuries']) if 'away_injuries' in r and pd.notnull(r['away_injuries']) else 0
        a_sent = float(r['away_sentiment']) if 'away_sentiment' in r and pd.notnull(r['away_sentiment']) else 0.0

        rows_html.append({
            "場次": f"#{match_num}",
            "賽事階段": r['group_or_stage'],
            "時間 (台灣時間)": f"{tw_date} {tw_time}",
            "客場": a_name,
            "客隊情報 🏥💬": f"{a_inj} 🏥 / {a_sent:+.2f} 💬",
            "主場": h_name,
            "主隊情報 🏥💬": f"{h_inj} 🏥 / {h_sent:+.2f} 💬",
            "狀態": status_str,
            "比分": score_str,
            "小賽勝率(主/和/客)": prob_str,
            "預測比分": r['pred_score'],
            "最佳主勝賠率": b_h,
            "最佳和局賠率": b_d,
            "最佳客勝賠率": b_a
        })
        
    st.dataframe(pd.DataFrame(rows_html), use_container_width=True, hide_index=True)

# ================= TAB 3: Monte Carlo Simulator =================
with tab_monte:
    st.header("🎲 100,000 次蒙地卡羅即時對戰模擬器")
    st.write("選擇任意一場世界盃對決，即時在瀏覽器跑 10萬次 隨機抽樣，估算獨贏、大小分與精確比分分佈！")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch scheduled matches for selection
    cursor.execute('''
        SELECT m.match_num, m.home_team, m.away_team, 
               t_h.elo_rating, t_h.fifa_rank, t_h.pi_rating_home, t_h.berrar_att, t_h.berrar_def,
               t_h.fbref_xg_diff, t_h.injury_count, t_h.sentiment_score,
               t_a.elo_rating, t_a.fifa_rank, t_a.pi_rating_away, t_a.berrar_att, t_a.berrar_def,
               t_a.fbref_xg_diff, t_a.injury_count, t_a.sentiment_score
        FROM matches m
        LEFT JOIN teams t_h ON m.home_team = t_h.name
        LEFT JOIN teams t_a ON m.away_team = t_a.name
        WHERE m.status = 'Scheduled'
        ORDER BY m.match_num ASC
    ''')
    matches_list = cursor.fetchall()
    conn.close()
    
    if not matches_list:
        st.info("目前沒有未開賽的賽程可供模擬。")
    else:
        # Construct option display with translations
        match_options = {
            f"#{m[0]} {get_team_display_name(m[1])} vs {get_team_display_name(m[2])}": m 
            for m in matches_list
        }
        selected_match_str = st.selectbox("請選擇欲模擬的場次：", list(match_options.keys()))
        
        selected_match = match_options[selected_match_str]
        (match_num, home, away, 
         h_elo, h_rank, home_pi_h, home_att, home_def, h_xg_diff, h_injuries, h_sentiment,
         a_elo, a_rank, away_pi_a, away_att, away_def, a_xg_diff, a_injuries, a_sentiment) = selected_match
         
        h_elo = h_elo if h_elo else 1400.0
        h_rank = h_rank if h_rank else 50
        home_pi_h = home_pi_h if home_pi_h else 0.0
        home_att = home_att if home_att else 1.0
        home_def = home_def if home_def else 1.0
        h_xg_diff = h_xg_diff if h_xg_diff else 0.0
        h_injuries = h_injuries if h_injuries else 0
        h_sentiment = h_sentiment if h_sentiment else 0.0
        
        a_elo = a_elo if a_elo else 1400.0
        a_rank = a_rank if a_rank else 50
        away_pi_a = away_pi_a if away_pi_a else 0.0
        away_att = away_att if away_att else 1.0
        away_def = away_def if away_def else 1.0
        a_xg_diff = a_xg_diff if a_xg_diff else 0.0
        a_injuries = a_injuries if a_injuries else 0
        a_sentiment = a_sentiment if a_sentiment else 0.0
        
        # Calculate Hybrid Lambdas with external intelligence corrections
        elo_diff = h_elo - a_elo
        rank_diff = a_rank - h_rank
        
        h_correction = (h_xg_diff * 40.0) + (h_sentiment * 15.0) - (h_injuries * 12.0)
        a_correction = (a_xg_diff * 40.0) + (a_sentiment * 15.0) - (a_injuries * 12.0)
        
        effective_elo_diff = elo_diff + (rank_diff * 4.0) + h_correction - a_correction
        lambda_elo_home = 1.25 * (10 ** (effective_elo_diff / 1000.0))
        lambda_elo_away = 1.25 * (10 ** (-effective_elo_diff / 1000.0))
        
        avg_home = 1.25
        avg_away = 1.05
        lambda_berrar_home = avg_home * home_att * away_def
        lambda_berrar_away = avg_away * away_att * home_def
        
        home_lambda = 0.5 * lambda_elo_home + 0.5 * lambda_berrar_home
        away_lambda = 0.5 * lambda_elo_away + 0.5 * lambda_berrar_away
        
        # Show parameters with translations
        st.markdown(f"**【戰力參數】** **{get_team_display_name(home)}** (主) Elo: {h_elo:.1f} (Rank #{h_rank}) | **{get_team_display_name(away)}** (客) Elo: {a_elo:.1f} (Rank #{a_rank})")
        st.markdown(f"**【主隊情報】** xG差: `{h_xg_diff:+.2f}` | 傷兵: `{h_injuries} 🏥` | 輿情指數: `{h_sentiment:+.2f} 💬` (情報修正: `{h_correction:+.1f}` Elo)")
        st.markdown(f"**【客隊情報】** xG差: `{a_xg_diff:+.2f}` | 傷兵: `{a_injuries} 🏥` | 輿情指數: `{a_sentiment:+.2f} 💬` (情報修正: `{a_correction:+.1f}` Elo)")
        st.markdown(f"**【進球期望】** **{get_team_display_name(home)}** xG: `{home_lambda:.3f}` | **{get_team_display_name(away)}** xG: `{away_lambda:.3f}`")
        
        if st.button("🚀 啟動 100,000 次蒙地卡羅模擬"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Simulations loop
            home_win_count = 0
            draw_count = 0
            away_win_count = 0
            ou_over_count = 0
            btts_count = 0
            score_frequencies = {}
            
            # Chunk loop to simulate progress bar
            chunks = 10
            sims_per_chunk = 10000
            
            start_time = time.time()
            
            for chunk in range(chunks):
                status_text.text(f"正在跑第 {(chunk+1)*10000} 次模擬...")
                for _ in range(sims_per_chunk):
                    h_goals = get_poisson_random(home_lambda)
                    a_goals = get_poisson_random(away_lambda)
                    
                    if h_goals > a_goals:
                        home_win_count += 1
                    elif h_goals == a_goals:
                        draw_count += 1
                    else:
                        away_win_count += 1
                        
                    if (h_goals + a_goals) > 2.5:
                        ou_over_count += 1
                        
                    if h_goals > 0 and a_goals > 0:
                        btts_count += 1
                        
                    score = f"{h_goals}-{a_goals}"
                    score_frequencies[score] = score_frequencies.get(score, 0) + 1
                    
                progress_bar.progress((chunk + 1) / chunks)
                
            duration = time.time() - start_time
            status_text.text(f"✅ 模擬完成！耗時 {duration:.2f} 秒。")
            
            p_home = home_win_count / 100000
            p_draw = draw_count / 100000
            p_away = away_win_count / 100000
            p_over = ou_over_count / 100000
            p_under = 1.0 - p_over
            p_btts = btts_count / 100000
            
            # Standard error
            se_home = math.sqrt(p_home * (1 - p_home) / 100000)
            
            # Display results in columns
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                st.markdown(f"""
                <div class="glass-card">
                    <h4>👑 獨贏勝率 (Moneyline)</h4>
                    <p><b>主勝 ({get_team_display_name(home)})</b>: <span style='color:#38bdf8;font-weight:700'>{p_home*100:.2f}%</span> (SE: ±{se_home*100:.3f}%)</p>
                    <p><b>雙方和局 (Draw)</b>: {p_draw*100:.2f}%</p>
                    <p><b>客勝 ({get_team_display_name(away)})</b>: {p_away*100:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col_c2:
                st.markdown(f"""
                <div class="glass-card">
                    <h4>⚽ 大小分 (Over/Under 2.5)</h4>
                    <p><b>大球 (Goals > 2.5)</b>: <span style='color:#a855f7;font-weight:700'>{p_over*100:.2f}%</span></p>
                    <p><b>小球 (Goals <= 2.5)</b>: {p_under*100:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col_c3:
                st.markdown(f"""
                <div class="glass-card">
                    <h4>🔥 雙方皆進球 (BTTS)</h4>
                    <p><b>是 (Yes)</b>: <span style='color:#10b981;font-weight:700'>{p_btts*100:.2f}%</span></p>
                    <p><b>否 (No)</b>: {(1 - p_btts)*100:.2f}%</p>
                </div>
                """, unsafe_allow_html=True)
                
            # Plot top 5 scores with Plotly
            sorted_scores = sorted(score_frequencies.items(), key=lambda x: x[1], reverse=True)[:5]
            scores_labels = [x[0] for x in sorted_scores]
            scores_pct = [round((x[1] / 100000) * 100, 2) for x in sorted_scores]
            
            fig = go.Figure(go.Bar(
                x=scores_pct,
                y=scores_labels,
                orientation='h',
                marker=dict(
                    color='rgba(168, 85, 247, 0.6)',
                    line=dict(color='rgba(168, 85, 247, 1.0)', width=1)
                )
            ))
            
            fig.update_layout(
                title="🎯 最常出現的五大精確比分百分比 (%)",
                xaxis_title="機率 (%)",
                yaxis_title="比分",
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                height=300,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            
            st.plotly_chart(fig, use_container_width=True)

# ================= TAB 4: Team Ratings =================
with tab_teams:
    st.header("📊 2026 FIFA 參賽隊伍戰力評級榜單")
    st.write("顯示 48 支隊伍最新的 Elo 等級分、Pi-Rating（區分主/客場）以及 Berrar 攻防雙因子。支持動態排序。")
    
    conn = get_db_connection()
    query = '''
        SELECT name as 隊伍名稱, confederation as 所屬足協, 
               elo_rating as Elo等級分, pi_rating_home as Pi主場評級, pi_rating_away as Pi客場評級, 
               berrar_att as Berrar攻擊因子, berrar_def as Berrar防守因子, fifa_rank as FIFA排名
        FROM teams
        ORDER BY elo_rating DESC
    '''
    df_teams = pd.read_sql_query(query, conn)
    conn.close()
    
    # Filter by confederation
    confed_options = ["全部"] + list(df_teams['所屬足協'].unique())
    selected_confed = st.selectbox("按足協篩選：", confed_options)
    
    display_teams = df_teams.copy()
    if selected_confed != "全部":
        display_teams = display_teams[display_teams['所屬足協'] == selected_confed]
        
    # Apply team translations to the display column
    display_teams['隊伍名稱'] = display_teams['隊伍名稱'].apply(get_team_display_name)
    
    st.dataframe(
        display_teams.style.format({
            "Elo等級分": "{:.1f}",
            "Pi主場評級": "{:+.2f}",
            "Pi客場評級": "{:+.2f}",
            "Berrar攻擊因子": "{:.2f}",
            "Berrar防守因子": "{:.2f}"
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Plot Scatter Plot of Berrar Att vs Def using Plotly
    st.subheader("📈 隊伍攻防實力分佈 (Berrar Attack vs Defense)")
    
    fig_scatter = px.scatter(
        display_teams,
        x="Berrar攻擊因子",
        y="Berrar防守因子",
        hover_name="隊伍名稱",
        color="所屬足協",
        title="Berrar 攻擊與防守乘數散點圖 (防守力越低越強)",
        labels={"Berrar攻擊因子": "攻擊因子 (愈高愈強)", "Berrar防守因子": "防守因子 (愈低愈強)"},
        template="plotly_dark"
    )
    
    fig_scatter.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)"
    )
    
    st.plotly_chart(fig_scatter, use_container_width=True)
