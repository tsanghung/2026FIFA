"""
display_utils.py — presentation helpers shared by the Streamlit app (app.py) and
the static-site generator (build_static.py): Chinese team names, display-name
formatting, and Wikipedia-time -> Taiwan-time conversion.
"""

import re
from datetime import datetime, timedelta

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
    time_clean = time_str.replace('−', '-').replace('−', '-').strip()

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
