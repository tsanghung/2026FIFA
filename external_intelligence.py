import os
import sqlite3
import re
import math
import requests

# DB configuration
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fifa_2026.db')

# Model-prior expected goal difference per match (xG - xGA).
# These values are internal priors, not a live FBref feed.
MODEL_PRIOR_XG_DIFF = {
    'Argentina': 1.25, 'France': 1.15, 'Spain': 1.10, 'England': 1.05,
    'Brazil': 0.95, 'Belgium': 0.85, 'Portugal': 0.90, 'Netherlands': 0.80,
    'Uruguay': 0.75, 'Colombia': 0.70, 'Croatia': 0.65, 'Morocco': 0.60,
    'Germany': 0.55, 'USA': 0.50, 'Switzerland': 0.45, 'Japan': 0.40,
    'South Korea': 0.35, 'Ecuador': 0.30, 'Austria': 0.25, 'Sweden': 0.20,
    'Ukraine': 0.15, 'Türkiye': 0.10, 'Norway': 0.08, 'Czechia': 0.05,
    'Senegal': 0.12, 'Australia': 0.08, 'Iran': 0.05, 'Ivory Coast': 0.02,
    'Paraguay': -0.05, 'Canada': -0.02, 'Tunisia': -0.08, 'Scotland': -0.05,
    'Algeria': -0.10, 'Egypt': -0.08, 'Bosnia-Herzegovina': -0.15,
    'Saudi Arabia': -0.12, 'Qatar': -0.10, 'Uzbekistan': -0.15, 'Panama': -0.18,
    'South Africa': -0.20, 'Cape Verde': -0.22, 'DR Congo': -0.25,
    'Ghana': -0.15, 'Iraq': -0.18, 'Haiti': -0.35, 'Jordan': -0.28,
    'Curaçao': -0.40, 'New Zealand': -0.30
}

# Model-prior injury/suspension counts for key nations.
# Replace with a real injury feed before presenting them as sourced injury data.
MODEL_PRIOR_INJURY_COUNT = {
    'France': 2, 'England': 1, 'Brazil': 2, 'Germany': 3, 'Argentina': 1,
    'Spain': 1, 'Portugal': 2, 'Netherlands': 1, 'Belgium': 2, 'Uruguay': 1
}

# Legacy model prior used by the per-match ensemble. The title-race predictor uses
# its own sourced Opta snapshot from The Analyst; this table is not a live Opta feed.
MODEL_PRIOR_OPTA_WIN_PROB = {
    'Argentina': 0.141, 'France': 0.128, 'Spain': 0.105, 'England': 0.098,
    'Brazil': 0.089, 'Portugal': 0.062, 'Netherlands': 0.055, 'Germany': 0.048,
    'Uruguay': 0.032, 'Colombia': 0.028, 'Morocco': 0.025, 'Croatia': 0.020, 
    'USA': 0.018, 'Switzerland': 0.015, 'Japan': 0.012, 'South Korea': 0.010, 
    'Ecuador': 0.009, 'Austria': 0.007, 'Senegal': 0.006, 'Australia': 0.005, 
    'Iran': 0.004, 'Ivory Coast': 0.003
}

def setup_database_schema():
    """Dynamically extends the teams table to include external analysis features."""
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
        print("[Success] Added external fields (fbref_xg_diff, injury_count, sentiment_score, opta_win_prob) to teams table.")
    conn.close()

def get_model_prior_xg_diff(team_name):
    """Returns the internal model-prior expected goals difference per match.

    Previously a +/-0.05 random jitter was
    added on every run, which — combined with the daily full-DB rebuild — made every
    prediction wobble day to day with no underlying signal. Until a real source is
    wired in, a stable model prior is strictly better than injected noise.
    """
    return round(MODEL_PRIOR_XG_DIFF.get(team_name, 0.0), 2)

def get_model_prior_injury_count(team_name):
    """Returns the internal model-prior injured/suspended player count.

    The previous 15% random change re-rolled every daily sync and silently shifted
    predictions; a real injury feed should replace this, not random walk it.
    """
    return MODEL_PRIOR_INJURY_COUNT.get(team_name, 0)

def analyze_reddit_sentiment(team_name):
    """
    Crawls r/soccer and r/Sportsbook using free JSON endpoints.
    Scores posts based on a tailored sports sentiment word lexicon.
    """
    positive_words = {'win', 'strong', 'fit', 'ready', 'boost', 'victory', 'favorite', 'champion', 'great', 'superb', 'back', 'form', 'class'}
    negative_words = {'injury', 'injured', 'out', 'ban', 'banned', 'conflict', 'clash', 'doubtful', 'miss', 'broken', 'lose', 'poor', 'bad', 'disaster', 'scandal', 'doubt'}
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    subreddits = ['soccer', 'Sportsbook']
    total_score = 0.0
    post_count = 0
    
    for sub in subreddits:
        query = f"{team_name}"
        url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&restrict_sr=1&sort=new&limit=5"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for post in data.get('data', {}).get('children', []):
                    p_data = post.get('data', {})
                    title = p_data.get('title', '').lower()
                    selftext = p_data.get('selftext', '').lower()
                    ups = p_data.get('score', 1)
                    
                    # Tokenize
                    all_text = f"{title} {selftext}"
                    words = set(re.findall(r'\b\w+\b', all_text))
                    
                    pos_hits = len(words.intersection(positive_words))
                    neg_hits = len(words.intersection(negative_words))
                    
                    # Weight by post popularity (log scale)
                    weight = math.log1p(ups)
                    post_score = (pos_hits - neg_hits) * weight
                    total_score += post_score
                    post_count += 1
        except Exception:
            pass
            
    if post_count == 0:
        return 0.0
        
    # Scale and normalize score between -1.0 and 1.0 using tanh
    normalized = math.tanh(total_score / 15.0)
    return round(normalized, 2)

def get_model_prior_opta_prob(team_name):
    """Returns the legacy Opta-like model prior used by match-level features."""
    return MODEL_PRIOR_OPTA_WIN_PROB.get(team_name, 0.001)

def run_external_intelligence_sync():
    """Sync model prior features and Reddit sentiment to the teams database."""
    print("[Sync] Start syncing model prior features and Reddit sentiment...")
    setup_database_schema()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all registered teams
    cursor.execute("SELECT name FROM teams")
    teams = [row[0] for row in cursor.fetchall()]
    
    success_count = 0
    for team in teams:
        xg_diff = get_model_prior_xg_diff(team)
        injuries = get_model_prior_injury_count(team)
        sentiment = analyze_reddit_sentiment(team)
        opta_prob = get_model_prior_opta_prob(team)
        
        cursor.execute('''
            UPDATE teams 
            SET fbref_xg_diff = ?, injury_count = ?, sentiment_score = ?, opta_win_prob = ?
            WHERE name = ?
        ''', (xg_diff, injuries, sentiment, opta_prob, team))
        success_count += 1
        
    conn.commit()
    conn.close()
    print(f"[Success] Updated {success_count} teams with external intelligence data.")

if __name__ == '__main__':
    run_external_intelligence_sync()
