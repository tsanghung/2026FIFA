import os
import sqlite3
import math
import random
import time
import re
import html
import textwrap
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from sklearn.preprocessing import StandardScaler

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

# Custom Futuristic HUD / Mission Control Theme
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;700;800&family=Rajdhani:wght@500;600;700&display=swap');

    :root {
        --bg-main: #050914;
        --bg-panel: rgba(8, 19, 38, 0.92);
        --bg-panel-soft: rgba(10, 26, 51, 0.72);
        --border-cyan: rgba(56, 189, 248, 0.34);
        --text-main: #e8f3ff;
        --text-muted: #8fb6d9;
        --cyan: #38bdf8;
        --green: #24f6a7;
        --magenta: #ff3d71;
        --amber: #f8c14a;
    }

    .stApp {
        background:
            linear-gradient(180deg, rgba(6, 12, 26, 0.98), rgba(3, 7, 15, 0.98)),
            repeating-linear-gradient(0deg, rgba(56, 189, 248, 0.03) 0, rgba(56, 189, 248, 0.03) 1px, transparent 1px, transparent 32px),
            repeating-linear-gradient(90deg, rgba(56, 189, 248, 0.025) 0, rgba(56, 189, 248, 0.025) 1px, transparent 1px, transparent 32px);
        color: var(--text-main);
        font-family: "Rajdhani", "Segoe UI", system-ui, sans-serif;
    }

    h1, h2, h3 {
        font-family: "Orbitron", "Rajdhani", "Segoe UI", sans-serif;
        font-weight: 800;
        letter-spacing: 0.04em;
        color: var(--text-main);
        text-transform: uppercase;
    }

    p, label, span, div {
        letter-spacing: 0;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(6, 14, 28, 0.98), rgba(3, 8, 18, 0.98));
        border-right: 1px solid rgba(56, 189, 248, 0.18);
    }

    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
        color: var(--cyan);
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid rgba(56, 189, 248, 0.18);
    }

    .stTabs [data-baseweb="tab"] {
        height: 42px;
        border-radius: 6px 6px 0 0;
        color: var(--text-muted);
        border: 1px solid rgba(56, 189, 248, 0.18);
        background: rgba(8, 19, 38, 0.62);
        font-family: "Rajdhani", "Segoe UI", system-ui, sans-serif;
        font-weight: 700;
        letter-spacing: 0.04em;
    }

    .stTabs [aria-selected="true"] {
        color: var(--green) !important;
        border-color: rgba(36, 246, 167, 0.52);
        box-shadow: inset 0 -2px 0 var(--green), 0 0 18px rgba(36, 246, 167, 0.12);
    }

    .glass-card {
        background: linear-gradient(180deg, rgba(11, 27, 51, 0.92), rgba(6, 16, 32, 0.96));
        border: 1px solid var(--border-cyan);
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 16px;
        box-shadow: inset 0 0 32px rgba(14, 165, 233, 0.06), 0 18px 44px rgba(0, 0, 0, 0.26);
    }

    .metric-value {
        font-family: "Orbitron", "Rajdhani", sans-serif;
        font-size: 2rem;
        font-weight: 800;
        color: var(--green);
        text-shadow: 0 0 18px rgba(36, 246, 167, 0.28);
    }

    .platform-badge {
        font-size: 0.75rem;
        font-weight: 700;
        padding: 3px 7px;
        border-radius: 4px;
        color: #ffffff;
        letter-spacing: 0.04em;
    }

    .badge-365 { background-color: #0f9f72; }
    .badge-wh { background-color: #2375d8; }
    .badge-dk { background-color: #d82e73; }

    .mission-header {
        border: 1px solid rgba(56, 189, 248, 0.32);
        border-radius: 8px;
        padding: 18px 20px;
        margin: 10px 0 18px 0;
        background: linear-gradient(135deg, rgba(8, 20, 42, 0.95), rgba(4, 11, 24, 0.98));
        box-shadow: inset 0 0 44px rgba(56, 189, 248, 0.08), 0 20px 70px rgba(0, 0, 0, 0.28);
    }

    .mission-kicker {
        color: var(--green);
        font-family: "Orbitron", "Rajdhani", sans-serif;
        font-size: 0.78rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }

    .mission-title {
        font-family: "Orbitron", "Rajdhani", sans-serif;
        font-size: clamp(1.7rem, 4vw, 3.2rem);
        line-height: 1.05;
        font-weight: 800;
        letter-spacing: 0.05em;
        color: var(--text-main);
        margin-top: 6px;
    }

    .mission-subtitle {
        color: var(--text-muted);
        max-width: 860px;
        font-size: 1.05rem;
        margin-top: 8px;
    }

    .hud-grid {
        display: grid;
        grid-template-columns: 280px minmax(360px, 1fr) 320px;
        gap: 14px;
        align-items: stretch;
    }

    .hud-card {
        background: var(--bg-panel);
        border: 1px solid var(--border-cyan);
        border-radius: 8px;
        padding: 16px;
        min-height: 118px;
        box-shadow: inset 0 0 28px rgba(56, 189, 248, 0.06);
        position: relative;
        overflow: hidden;
    }

    .hud-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        width: 3px;
        height: 100%;
        background: linear-gradient(180deg, var(--green), var(--cyan), var(--magenta));
        opacity: 0.82;
    }

    .hud-label {
        color: #82caff;
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-weight: 700;
    }

    .hud-value {
        font-family: "Orbitron", "Rajdhani", sans-serif;
        color: var(--text-main);
        font-size: 1.7rem;
        font-weight: 800;
        line-height: 1.06;
        margin-top: 8px;
    }

    .hud-positive {
        color: var(--green);
        text-shadow: 0 0 18px rgba(36, 246, 167, 0.32);
    }

    .radar-panel {
        min-height: 362px;
        background:
            repeating-linear-gradient(0deg, rgba(56, 189, 248, 0.06) 0, rgba(56, 189, 248, 0.06) 1px, transparent 1px, transparent 28px),
            repeating-linear-gradient(90deg, rgba(56, 189, 248, 0.05) 0, rgba(56, 189, 248, 0.05) 1px, transparent 1px, transparent 28px),
            radial-gradient(circle at 50% 46%, rgba(17, 73, 116, 0.72), rgba(6, 16, 32, 0.96) 68%);
    }

    .radar-field {
        position: relative;
        min-height: 270px;
    }

    .radar-ring {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        border: 1px solid rgba(45, 212, 191, 0.42);
        border-radius: 50%;
        box-shadow: 0 0 38px rgba(45, 212, 191, 0.10);
    }

    .radar-ring.one { width: 250px; height: 250px; }
    .radar-ring.two { width: 170px; height: 170px; }
    .radar-ring.three { width: 92px; height: 92px; }

    .radar-sweep {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 142px;
        height: 2px;
        background: linear-gradient(90deg, rgba(36, 246, 167, 0.95), transparent);
        transform-origin: left center;
        animation: radarSweep 5.5s linear infinite;
        box-shadow: 0 0 18px rgba(36, 246, 167, 0.62);
    }

    .radar-dot {
        position: absolute;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--green);
        box-shadow: 0 0 14px var(--green);
        animation: pulseDot 2.4s ease-in-out infinite;
    }

    .radar-dot.magenta {
        background: var(--magenta);
        box-shadow: 0 0 14px var(--magenta);
        animation-delay: 0.7s;
    }

    .prob-strip {
        display: grid;
        grid-template-columns: var(--home-prob, 1fr) var(--draw-prob, 1fr) var(--away-prob, 1fr);
        height: 24px;
        border-radius: 5px;
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }

    .prob-home { background: var(--green); }
    .prob-draw { background: var(--cyan); }
    .prob-away { background: var(--magenta); }

    @keyframes radarSweep {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    @keyframes pulseDot {
        0%, 100% { transform: scale(0.9); opacity: 0.72; }
        50% { transform: scale(1.35); opacity: 1; }
    }

    @media (max-width: 1100px) {
        .hud-grid {
            grid-template-columns: 1fr;
        }
    }
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

def fmt_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.1f}%"

def fmt_signed_pct(value):
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):+.2%}"

def get_latest_log_line():
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync.log')
    if not os.path.exists(log_path):
        return "No sync log"
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        return lines[-1] if lines else "No sync log"
    except Exception:
        return "Sync log unavailable"

def build_value_bet_rows(df_source, suffix, fraction, mode_name):
    rows = []
    if df_source.empty:
        return rows

    def get_source_str(best_odds, b, w, d):
        if not best_odds:
            return "Unknown"
        srcs = []
        if best_odds == b:
            srcs.append("Bet365")
        if best_odds == w:
            srcs.append("William Hill")
        if best_odds == d:
            srcs.append("DraftKings")
        return " / ".join(srcs) if srcs else "Mixed"

    for _, row in df_source.iterrows():
        match_num = int(row['match_num'])
        h_name = get_team_display_name(row['home_team'])
        a_name = get_team_display_name(row['away_team'])
        matchup = f"{h_name} vs {a_name}"

        candidates = [
            ("Home Win", row.get(f'pred_home_win_prob'), row.get(f'odds_home{suffix}'), row.get(f'ev_home{suffix}'), row.get(f'kelly_home{suffix}'),
             row.get('odds_home_bet365'), row.get('odds_home_williamhill'), row.get('odds_home_draftkings')),
            ("Draw", row.get(f'pred_draw_prob'), row.get(f'odds_draw{suffix}'), row.get(f'ev_draw{suffix}'), row.get(f'kelly_draw{suffix}'),
             row.get('odds_draw_bet365'), row.get('odds_draw_williamhill'), row.get('odds_draw_draftkings')),
            ("Away Win", row.get(f'pred_away_win_prob'), row.get(f'odds_away{suffix}'), row.get(f'ev_away{suffix}'), row.get(f'kelly_away{suffix}'),
             row.get('odds_away_bet365'), row.get('odds_away_williamhill'), row.get('odds_away_draftkings')),
        ]
        for pick, prob, odds, ev, kelly, b, w, d in candidates:
            if ev is not None and not pd.isna(ev) and ev > 0:
                source = get_source_str(odds, b, w, d) if suffix == "" else mode_name.split(" ", 1)[-1]
                rows.append({
                    "match_num": match_num,
                    "matchup": matchup,
                    "pick": pick,
                    "prob": float(prob) if prob is not None and not pd.isna(prob) else 0.0,
                    "odds": float(odds) if odds is not None and not pd.isna(odds) else 0.0,
                    "ev": float(ev),
                    "kelly": float(kelly) * fraction if kelly is not None and not pd.isna(kelly) else 0.0,
                    "source": source,
                    "home": h_name,
                    "away": a_name,
                })
    return rows

# Header
st.markdown("""
<div class="mission-header">
    <div class="mission-kicker">FIFA 2026 Quantitative Mission Control</div>
    <div class="mission-title">World Cup Decision HUD</div>
    <div class="mission-subtitle">
        Elo / Pi-Rating / Berrar / Dixon-Coles ensemble intelligence with market odds, EV+, Kelly risk telemetry and Taiwan-time schedule control.
    </div>
</div>
""", unsafe_allow_html=True)

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
tab_overview, tab_title, tab_val, tab_sched, tab_monte, tab_teams, tab_ai = st.tabs([
    "MISSION CONTROL",
    "TITLE RACE",
    "EV+ VALUE",
    "MATCH SCHEDULE",
    "MONTE CARLO",
    "TEAM RATING",
    "AI DEEP LEARNING"
])

# ================= TAB 0: Mission Control Overview =================
with tab_overview:
    conn = get_db_connection()
    try:
        counts = pd.read_sql_query('''
            SELECT
                COUNT(*) AS total_matches,
                SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled_matches,
                SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed_matches
            FROM matches
        ''', conn).iloc[0]

        team_count = pd.read_sql_query('SELECT COUNT(*) AS team_count FROM teams', conn).iloc[0]['team_count']

        next_match_df = pd.read_sql_query('''
            SELECT match_num, group_or_stage, date, time, home_team, away_team,
                   pred_home_win_prob, pred_draw_prob, pred_away_win_prob,
                   odds_home, odds_draw, odds_away
            FROM matches
            WHERE status = 'Scheduled'
            ORDER BY date ASC, match_num ASC
            LIMIT 1
        ''', conn)

        top_query = f'''
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
        overview_val_df = pd.read_sql_query(top_query, conn)
    except Exception as e:
        st.error(f"Mission Control 資料讀取失敗：{e}")
        counts = pd.Series({"total_matches": 0, "scheduled_matches": 0, "completed_matches": 0})
        team_count = 0
        next_match_df = pd.DataFrame()
        overview_val_df = pd.DataFrame()
    finally:
        conn.close()

    value_rows = build_value_bet_rows(overview_val_df, col_suffix, kelly_fraction, betting_mode)
    top_pick = max(value_rows, key=lambda item: item["ev"], default=None)
    top_kelly = max(value_rows, key=lambda item: item["kelly"], default=None)

    if next_match_df.empty:
        next_match = None
        next_home = "TBD"
        next_away = "TBD"
        next_stage = "No scheduled match"
        next_time = "-"
        home_prob = draw_prob = away_prob = 1
    else:
        next_match = next_match_df.iloc[0]
        next_home = get_team_display_name(next_match['home_team'])
        next_away = get_team_display_name(next_match['away_team'])
        next_stage = next_match['group_or_stage']
        tw_date, tw_time = convert_to_taiwan_time(next_match['date'], next_match['time'])
        next_time = f"{tw_date} {tw_time}".strip()
        home_prob = max(float(next_match['pred_home_win_prob'] or 0), 0.01)
        draw_prob = max(float(next_match['pred_draw_prob'] or 0), 0.01)
        away_prob = max(float(next_match['pred_away_win_prob'] or 0), 0.01)

    top_pick_title = top_pick["pick"] if top_pick else "No EV+ Signal"
    top_pick_match = top_pick["matchup"] if top_pick else "Market is quiet"
    top_pick_ev = fmt_signed_pct(top_pick["ev"]) if top_pick else "-"
    top_pick_source = top_pick["source"] if top_pick else "-"
    top_kelly_value = f"{top_kelly['kelly']:.2%}" if top_kelly else "-"
    top_kelly_match = top_kelly["matchup"] if top_kelly else "No stake signal"
    latest_log = get_latest_log_line()
    feed_state = "API / LIVE" if os.environ.get('THE_ODDS_API_KEY', '').strip() else "SIMULATED FEED"

    queue_rows = sorted(value_rows, key=lambda item: item["ev"], reverse=True)[:4]
    queue_html = ""
    if queue_rows:
        for item in queue_rows:
            queue_html += f"""
            <div style="display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid rgba(56,189,248,.14);padding:8px 0;">
                <span>{html.escape(item['matchup'])}<br><span style="color:#8fb6d9;font-size:.82rem;">{html.escape(item['pick'])} · {html.escape(item['source'])}</span></span>
                <b class="hud-positive">{fmt_signed_pct(item['ev'])}</b>
            </div>
            """
    else:
        queue_html = '<div style="color:#8fb6d9;">No positive EV signal in current mode.</div>'

    st.html(textwrap.dedent(f"""
    <div class="hud-grid">
        <div>
            <div class="hud-card">
                <div class="hud-label">Best Opportunity</div>
                <div class="hud-value">{html.escape(top_pick_title)}</div>
                <div class="hud-positive" style="font-family:Orbitron,Rajdhani,sans-serif;font-size:1.8rem;margin-top:8px;">{top_pick_ev}</div>
                <div style="color:#8fb6d9;margin-top:8px;">{html.escape(top_pick_match)}</div>
                <div style="color:#82caff;font-size:.85rem;margin-top:8px;">Source: {html.escape(top_pick_source)}</div>
            </div>
            <div class="hud-card">
                <div class="hud-label">Risk Mode</div>
                <div class="hud-value">{html.escape(kelly_name)}</div>
                <div style="color:#8fb6d9;margin-top:8px;">Top stake signal: {top_kelly_value}</div>
                <div style="color:#82caff;font-size:.85rem;margin-top:6px;">{html.escape(top_kelly_match)}</div>
            </div>
            <div class="hud-card">
                <div class="hud-label">Market Feed</div>
                <div class="hud-value">{feed_state}</div>
                <div style="color:#8fb6d9;margin-top:8px;">{html.escape(betting_mode)}</div>
            </div>
        </div>

        <div class="hud-card radar-panel">
            <div class="hud-label">Dynamic Match Scan</div>
            <div class="hud-value">{html.escape(next_stage)}</div>
            <div class="radar-field">
                <div class="radar-ring one"></div>
                <div class="radar-ring two"></div>
                <div class="radar-ring three"></div>
                <div class="radar-sweep"></div>
                <div class="radar-dot" style="left:63%;top:25%;"></div>
                <div class="radar-dot magenta" style="left:31%;top:64%;"></div>
                <div style="position:absolute;right:8px;top:8px;text-align:right;">
                    <div class="hud-value" style="font-size:3rem;">{int(counts['total_matches'] or 0)}</div>
                    <div class="hud-label">Matches Tracked</div>
                </div>
                <div style="position:absolute;left:8px;bottom:8px;right:8px;">
                    <div style="color:#8fb6d9;margin-bottom:8px;">Next: {html.escape(next_home)} vs {html.escape(next_away)} · {html.escape(next_time)}</div>
                    <div class="prob-strip" style="--home-prob:{home_prob}fr;--draw-prob:{draw_prob}fr;--away-prob:{away_prob}fr;">
                        <div class="prob-home"></div><div class="prob-draw"></div><div class="prob-away"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;color:#8fb6d9;font-size:.86rem;margin-top:6px;">
                        <span>Home {fmt_pct(home_prob)}</span><span>Draw {fmt_pct(draw_prob)}</span><span>Away {fmt_pct(away_prob)}</span>
                    </div>
                </div>
            </div>
        </div>

        <div>
            <div class="hud-card">
                <div class="hud-label">EV+ Queue</div>
                {queue_html}
            </div>
            <div class="hud-card">
                <div class="hud-label">System State</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px;">
                    <div><div class="hud-value">{int(team_count or 0)}</div><div style="color:#8fb6d9;">Teams</div></div>
                    <div><div class="hud-value">{len(value_rows)}</div><div style="color:#8fb6d9;">EV+ Picks</div></div>
                    <div><div class="hud-value">{int(counts['scheduled_matches'] or 0)}</div><div style="color:#8fb6d9;">Scheduled</div></div>
                    <div><div class="hud-value">{int(counts['completed_matches'] or 0)}</div><div style="color:#8fb6d9;">Completed</div></div>
                </div>
            </div>
            <div class="hud-card">
                <div class="hud-label">Last Sync Signal</div>
                <div style="color:#8fb6d9;margin-top:8px;font-size:.92rem;">{html.escape(latest_log)}</div>
            </div>
        </div>
    </div>
    """))

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
        
    import affiliate_config as _aff

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

        # 各場次聯盟連結：連到提供最佳主勝賠率的莊家
        _bk = _aff.best_book_key(r['odds_home'], r['odds_home_bet365'],
                                 r['odds_home_williamhill'], r['odds_home_draftkings'])
        bet_url = _aff.get_affiliate_url(_bk) if r['odds_home'] else None
        
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
            "最佳客勝賠率": b_a,
            "🎯 下注": bet_url
        })

    _col_cfg = {}
    if _aff.AFFILIATE_ENABLED:
        _col_cfg["🎯 下注"] = st.column_config.LinkColumn("🎯 下注", display_text=_aff.CTA_LABEL)
    st.dataframe(pd.DataFrame(rows_html), use_container_width=True, hide_index=True,
                 column_config=_col_cfg)
    st.caption("⚠️ 投注有風險，請理性博彩，未滿 18 歲請勿參與。「前往下注」為合作夥伴連結。")

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

# ================= TAB 5: AI Deep Learning Predictions =================
with tab_ai:
    st.header("AI Deep Learning 智能預測引擎")
    st.write("基於 PyTorch 多層神經網路，融合 Elo/Pi-Rating/Berrar/集成預測/市場賠率/外部情報等 41 維特徵，"
             "透過 Monte Carlo Dropout 量化不確定性，輸出每場賽事的完整分析報告。")

    st.sidebar.subheader("AI 模型訓練控制")
    n_epochs_ai = st.sidebar.slider("訓練輪數 (Epochs)", 50, 500, 200, step=50)
    k_folds_ai = st.sidebar.slider("交叉驗證折數", 2, 5, 3)
    mc_samples_ai = st.sidebar.slider("MC Dropout 採樣次數", 50, 200, 100, step=50)

    if st.sidebar.button("訓練 / 重新訓練模型", type="primary"):
        try:
            from dl_predictor import train_model
        except Exception:
            st.error("⚠️ AI 深度學習引擎需要 PyTorch，雲端部署為符合資源上限未安裝。"
                     "請於本機執行 `pip install -r requirements-full.txt` 後再使用此分頁。")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()
        all_epochs_data = []

        def progress_cb(fold, epoch, total, train_loss, val_loss, acc):
            pct = (epoch + 1) / total
            status_text.text(
                f"Fold {fold+1}/{k_folds_ai} | Epoch {epoch+1}/{total} | "
                f"Loss: {val_loss:.4f} | Acc: {acc:.2%}"
            )
            progress_bar.progress(pct)
            all_epochs_data.append({
                'fold': fold, 'epoch': epoch, 'train_loss': train_loss,
                'val_loss': val_loss, 'accuracy': acc
            })

        model, scaler, hist = train_model(
            n_epochs=n_epochs_ai, k_folds=k_folds_ai, progress_callback=progress_cb
        )

        progress_bar.progress(1.0)

        if model is None:
            st.error(f"訓練失敗：{hist.get('error', '未知錯誤')}")
        else:
            st.success("模型訓練完成！")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("訓練樣本數", hist['n_training_samples'])
            with col2:
                st.metric("最佳驗證損失", f"{hist['best_val_loss']:.4f}")
            with col3:
                final_acc = hist['accuracy'][-1] if hist['accuracy'] else 0
                st.metric("最終準確率", f"{final_acc:.2%}")

            import pandas as pd
            hist_df = pd.DataFrame(all_epochs_data)
            if not hist_df.empty:
                fig_loss = go.Figure()
                fig_loss.add_trace(go.Scatter(
                    x=hist_df['epoch'], y=hist_df['train_loss'],
                    mode='lines', name='Training Loss',
                    line=dict(color='#38bdf8')
                ))
                fig_loss.add_trace(go.Scatter(
                    x=hist_df['epoch'], y=hist_df['val_loss'],
                    mode='lines', name='Validation Loss',
                    line=dict(color='#ff3d71')
                ))
                fig_loss.update_layout(
                    title="訓練損失曲線",
                    xaxis_title="Epoch",
                    yaxis_title="Loss",
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_loss, use_container_width=True)

    st.markdown("---")
    st.subheader("賽事預測結果")

    if st.button("執行 AI 預測所有賽事", type="primary"):
        model_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dl_model.pth')
        if not os.path.exists(model_file):
            st.warning("模型尚未訓練，請先點擊側邊欄的「訓練模型」按鈕。")
        else:
            try:
                from dl_predictor import predict_all_matches, get_feature_importance, WorldCupPredictor, MODEL_PATH, SCALER_PATH
                import torch as torch_import
            except Exception:
                st.error("⚠️ AI 深度學習引擎需要 PyTorch，雲端部署為符合資源上限未安裝。"
                         "請於本機執行 `pip install -r requirements-full.txt` 後再使用此分頁。")
                st.stop()

            with st.spinner("正在執行 Monte Carlo 採樣預測..."):
                results, err = predict_all_matches(n_mc_samples=mc_samples_ai)

            if err:
                st.error(f"預測失敗：{err}")
            else:
                scheduled = [r for r in results if r['status'] == 'Scheduled']
                completed = [r for r in results if r['status'] == 'Completed']

                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                with col_s1:
                    st.metric("總賽事數", len(results))
                with col_s2:
                    st.metric("未開賽", len(scheduled))
                with col_s3:
                    high_conf = sum(1 for r in scheduled if r['confidence_level'] == 'HIGH')
                    st.metric("高信心預測", high_conf)
                with col_s4:
                    if completed:
                        correct = sum(1 for r in completed
                                     if r['home_goals_actual'] is not None
                                     and r['away_goals_actual'] is not None
                                     and ((r['home_goals_actual'] > r['away_goals_actual'] and r['predicted_label'] == 0) or
                                          (r['home_goals_actual'] == r['away_goals_actual'] and r['predicted_label'] == 1) or
                                          (r['home_goals_actual'] < r['away_goals_actual'] and r['predicted_label'] == 2)))
                        st.metric("完賽準確率", f"{correct/len(completed):.0%}")
                    else:
                        st.metric("完賽準確率", "N/A")

                st.markdown("---")

                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    status_filter = st.selectbox("篩選狀態", ["全部", "未開賽", "已完賽"])
                with filter_col2:
                    conf_filter = st.selectbox("篩選信心度", ["全部", "HIGH", "MEDIUM", "LOW"])

                filtered = results.copy()
                if status_filter == "未開賽":
                    filtered = [r for r in filtered if r['status'] == 'Scheduled']
                elif status_filter == "已完賽":
                    filtered = [r for r in filtered if r['status'] == 'Completed']
                if conf_filter != "全部":
                    filtered = [r for r in filtered if r['confidence_level'] == conf_filter]

                for r in filtered:
                    h_name = get_team_display_name(r['home_team'])
                    a_name = get_team_display_name(r['away_team'])
                    matchup = f"{h_name} vs {a_name}"
                    conf_icon = {"HIGH": "", "MEDIUM": "", "LOW": ""}.get(r['confidence_level'], "")

                    with st.expander(
                        f"#{r['match_num']} {matchup} -- {r['predicted_outcome']} "
                        f"{conf_icon} {r['confidence']:.0%} (預測比分: {r['pred_score']})",
                        expanded=False
                    ):
                        probs = [r['home_win_prob'], r['draw_prob'], r['away_win_prob']]
                        stds = [r['home_win_std'], r['draw_std'], r['away_win_std']]
                        labels = [f"主勝 ({h_name})", "和局 (Draw)", f"客勝 ({a_name})"]
                        colors = ['#24f6a7', '#38bdf8', '#ff3d71']

                        fig_prob = go.Figure()
                        for i in range(3):
                            fig_prob.add_trace(go.Bar(
                                name=labels[i],
                                x=[labels[i]],
                                y=[probs[i] * 100],
                                error_y=dict(type='data', array=[stds[i] * 100], visible=True),
                                marker_color=colors[i],
                            ))
                        fig_prob.update_layout(
                            title="預測勝率分佈 (含 MC Dropout 標準差)",
                            yaxis_title="機率 (%)",
                            template="plotly_dark",
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            height=250,
                            margin=dict(l=20, r=20, t=40, b=20),
                            showlegend=False,
                        )
                        st.plotly_chart(fig_prob, use_container_width=True)

                        c1, c2, c3, c4, c5 = st.columns(5)
                        with c1:
                            st.metric("主勝率", f"{probs[0]:.1%}", delta=f"+/-{stds[0]:.1%}")
                        with c2:
                            st.metric("和局率", f"{probs[1]:.1%}", delta=f"+/-{stds[1]:.1%}")
                        with c3:
                            st.metric("客勝率", f"{probs[2]:.1%}", delta=f"+/-{stds[2]:.1%}")
                        with c4:
                            st.metric("信心度", f"{r['confidence']:.0%}")
                        with c5:
                            st.metric("信心等級", r['confidence_level'])

                        if r['status'] == 'Completed' and r['home_goals_actual'] is not None:
                            actual_score = f"{r['home_goals_actual']}-{r['away_goals_actual']}"
                            actual_label = (
                                "主勝" if r['home_goals_actual'] > r['away_goals_actual']
                                else "客勝" if r['home_goals_actual'] < r['away_goals_actual']
                                else "和局"
                            )
                            pred_correct = (
                                (r['home_goals_actual'] > r['away_goals_actual'] and r['predicted_label'] == 0) or
                                (r['home_goals_actual'] == r['away_goals_actual'] and r['predicted_label'] == 1) or
                                (r['home_goals_actual'] < r['away_goals_actual'] and r['predicted_label'] == 2)
                            )
                            st.info(f"實際比分: {actual_score} ({actual_label}) | "
                                    f"AI 預測: {'正確' if pred_correct else '錯誤'} | "
                                    f"AI 預測比分: {r['pred_score']}")

                        st.markdown("**關鍵影響因素 (Top 10)**")
                        try:
                            from dl_predictor import load_all_match_features
                            X_all, match_info_all = load_all_match_features()
                            match_idx = None
                            for idx, info in enumerate(match_info_all):
                                if info['match_num'] == r['match_num']:
                                    match_idx = idx
                                    break
                            if match_idx is not None:
                                checkpoint = torch_import.load(MODEL_PATH, weights_only=False)
                                model_fi = WorldCupPredictor(input_dim=checkpoint['input_dim'])
                                model_fi.load_state_dict(checkpoint['model_state_dict'])
                                model_fi.eval()
                                scaler_data = np.load(SCALER_PATH)
                                scaler_fi = StandardScaler()
                                scaler_fi.mean_ = scaler_data['mean']
                                scaler_fi.scale_ = scaler_data['scale']
                                scaler_fi.var_ = scaler_data['var']
                                scaler_fi.n_features_in_ = int(scaler_data['n_features_in'])
                                scaler_fi.n_samples_seen_ = int(scaler_data['n_samples_seen'])
                                feat_vec = X_all[match_idx].reshape(1, -1)
                                feat_scaled = scaler_fi.transform(feat_vec)
                                feat_imp = get_feature_importance(feat_scaled[0], model_fi)
                                imp_names = [f[0] for f in feat_imp]
                                imp_values = [f[1] for f in feat_imp]
                                fig_imp = go.Figure(go.Bar(
                                    x=imp_values,
                                    y=imp_names,
                                    orientation='h',
                                    marker=dict(
                                        color='rgba(248, 193, 74, 0.7)',
                                        line=dict(color='rgba(248, 193, 74, 1.0)', width=1)
                                    )
                                ))
                                fig_imp.update_layout(
                                    title="特徵重要性 (Gradient-based)",
                                    xaxis_title="重要性分數",
                                    template="plotly_dark",
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)",
                                    height=300,
                                    margin=dict(l=20, r=20, t=40, b=20),
                                    yaxis={'categoryorder': 'total ascending'},
                                )
                                st.plotly_chart(fig_imp, use_container_width=True)
                        except Exception as e:
                            st.caption(f"特徵重要性計算中: {e}")

                        st.markdown("**AI 分析摘要**")
                        diff_home_away = r['home_win_prob'] - r['away_win_prob']
                        if abs(diff_home_away) < 0.1:
                            analysis = (
                                f"本場比賽雙方實力相當接近，AI 模型預測結果具有{'較高' if r['confidence_level'] == 'HIGH' else '一定'}的不確定性。"
                                f"預測比分為 {r['pred_score']}，建議關注和局可能性。"
                            )
                        elif diff_home_away > 0:
                            analysis = (
                                f"AI 模型認為 {h_name} 在本場比賽中佔據優勢，主勝機率達 {r['home_win_prob']:.1%}。"
                                f"預測比分為 {r['pred_score']}。"
                                f"{'信心充足，建議重点关注。' if r['confidence_level'] == 'HIGH' else '但仍需留意不確定性因素。'}"
                            )
                        else:
                            analysis = (
                                f"AI 模型認為 {a_name} 在本場比賽中更具優勢，客勝機率達 {r['away_win_prob']:.1%}。"
                                f"預測比分為 {r['pred_score']}。"
                                f"{'信心充足，建議重点关注。' if r['confidence_level'] == 'HIGH' else '但仍需留意不確定性因素。'}"
                            )
                        st.info(analysis)


# ================= TAB: Title Race (總冠軍預測) =================
with tab_title:
    st.header("🏆 總冠軍預測 (Title Race)")
    st.write(
        "以**賭盤為主**、融合**權威超級電腦 (Opta)** 與**本系統 AI 全賽事蒙地卡羅模型**，"
        "預測每隊奪冠機率。每日滾動更新並以 EWMA 平滑，下方可追蹤奪冠機率的歷史走勢。"
    )

    cp_conn = get_db_connection()
    has_table = cp_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='champion_predictions'"
    ).fetchone()

    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("🔄 重新計算奪冠機率", type="primary"):
            try:
                import champion_predictor as _cp
                with st.spinner("執行 10,000 次完整賽事蒙地卡羅並融合市場/權威..."):
                    _cp.run_champion_prediction(n_sims=10000)
                st.success("已更新今日奪冠機率快照！")
                st.rerun()
            except Exception as e:
                st.error(f"計算失敗：{e}")

    if not has_table:
        st.info("尚無奪冠機率資料。請點擊「重新計算奪冠機率」產生第一份快照。")
    else:
        latest_date = cp_conn.execute(
            "SELECT MAX(snapshot_date) FROM champion_predictions"
        ).fetchone()[0]
        df = pd.read_sql_query(
            "SELECT * FROM champion_predictions WHERE snapshot_date = ? ORDER BY rank",
            cp_conn, params=(latest_date,)
        )
        with col_b:
            st.caption(f"最新快照日期：{latest_date} ｜ 融合來源：賭盤(交叉比對) · Opta 超級電腦 · 本系統 AI 模型")

        if not df.empty:
            # ---- Top-3 favourite cards ----
            top3 = df.head(3)
            cards = st.columns(3)
            medals = ["🥇", "🥈", "🥉"]
            for i, (_, row) in enumerate(top3.iterrows()):
                with cards[i]:
                    name = get_team_display_name(row['team'])
                    delta = row['delta'] or 0.0
                    st.metric(
                        f"{medals[i]} {name}",
                        f"{row['blended_ewma']*100:.1f}%",
                        f"{delta*100:+.2f}% vs 前一日",
                    )

            # ---- Full ranking table ----
            st.subheader("奪冠機率排行 (Top 20)")
            show = df.head(20).copy()

            def _arrow(d):
                d = d or 0.0
                if d > 0.0005:
                    return f"▲ {d*100:+.2f}%"
                if d < -0.0005:
                    return f"▼ {d*100:+.2f}%"
                return "—"

            table = pd.DataFrame({
                "#": show['rank'],
                "隊伍": show['team'].apply(get_team_display_name),
                "融合奪冠率": (show['blended_ewma'] * 100).map("{:.1f}%".format),
                "賭盤": (show['market_prob'].fillna(0) * 100).map("{:.1f}%".format),
                "Opta": (show['opta_prob'].fillna(0) * 100).map("{:.1f}%".format),
                "AI 模型": (show['model_prob'].fillna(0) * 100).map("{:.1f}%".format),
                "日變動": show['delta'].apply(_arrow),
            })
            st.dataframe(table, use_container_width=True, hide_index=True)

            # ---- Trend chart over time ----
            hist = pd.read_sql_query(
                "SELECT snapshot_date, team, blended_ewma FROM champion_predictions "
                "ORDER BY snapshot_date", cp_conn
            )
            n_days = hist['snapshot_date'].nunique()
            if n_days >= 2:
                st.subheader("奪冠機率走勢 (Top 6)")
                top_teams = df.head(6)['team'].tolist()
                fig = go.Figure()
                for t in top_teams:
                    sub = hist[hist['team'] == t]
                    fig.add_trace(go.Scatter(
                        x=sub['snapshot_date'], y=sub['blended_ewma'] * 100,
                        mode='lines+markers', name=get_team_display_name(t),
                    ))
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="日期", yaxis_title="奪冠機率 (%)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(t=40),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("📈 累積 2 天以上的每日快照後，這裡會顯示奪冠機率走勢圖。")

            st.caption(
                "方法論：賭盤為主（The Odds API 交叉比對 Bet365/Pinnacle/Betfair/DraftKings，去水後取共識；"
                "無 API 時用內建 2026-06 快照）。權威為 Opta 超級電腦。AI 模型為本系統 Elo/Pi/Berrar 集成驅動的"
                "全賽事蒙地卡羅；開賽後依實際成績更新評級，模型權重隨完賽比例自動上升。每日以 EWMA(α=0.4) 平滑。"
            )
