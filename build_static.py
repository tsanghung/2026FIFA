"""
build_static.py — generate a fully static, SEO-friendly site from fifa_2026.db.

Why static?
-----------
The data updates once a day and is ~99% read-only display, so a static site is a
far better fit than a live Streamlit server for the monetisation goal:
  * Google actually indexes it (Streamlit JS apps don't rank) -> organic traffic.
  * Free + custom-domain + AdSense-friendly on GitHub Pages / Cloudflare Pages.
  * Instant load, no cold starts.

Output (docs/):
  index.html              dashboard: champion race, full schedule, ratings, accuracy
  match/<n>.html          one page per fixture (SEO long-tail: "A vs B 預測")
  assets/style.css
  data.json               machine-readable predictions/odds
  sitemap.xml, robots.txt, .nojekyll, (CNAME if a custom domain is set)

Run:  python build_static.py     (also wired into the daily GitHub Action)
"""

import os
import re
import json
import html
import sqlite3
from datetime import datetime, timezone, timedelta

from display_utils import get_team_display_name, convert_to_taiwan_time
import external_predictions
import bet_tracker
import site_config as site

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'fifa_2026.db')
OUT = os.path.join(HERE, 'docs')


def esc(s):
    return html.escape(str(s if s is not None else ''))


def pct(x):
    return f"{(x or 0) * 100:.0f}%"


def flip_score(s):
    """DB stores scores as 'home-away'; the tables/pages list teams as 客(away) then
    主(home), so flip to 'away-home' for display. Returns None for non-scores
    (e.g. 'Match 31', '', 'VS') so the caller can show a placeholder."""
    m = re.match(r'^\s*(\d+)\s*[–\-−]\s*(\d+)\s*$', str(s or ''))
    return f"{m.group(2)}-{m.group(1)}" if m else None


def odds_source_label(row):
    source = (row.get('odds_source') or 'unknown').lower()
    labels = {
        'api': 'API 實盤',
        'simulated': '模型模擬',
        'manual': '手動輸入',
        'unknown': '來源未標示',
    }
    detail = row.get('odds_bookmaker_keys')
    suffix = f'：{detail}' if detail else ''
    return labels.get(source, source.upper()) + suffix


def load_data():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    # xG/possession/shots columns are added by threefivescores_sync; include them
    # only if present so the build also works on a DB that predates them.
    have = {r[1] for r in cur.execute('PRAGMA table_info(matches)')}
    XG_COLS = ('home_xg', 'away_xg', 'home_possession', 'away_possession',
               'home_shots', 'away_shots')
    extra = ''.join(f', {c}' for c in XG_COLS if c in have)
    matches = [dict(r) for r in cur.execute(f'''
        SELECT match_num, group_or_stage, date, time, home_team, away_team,
               pred_home_win_prob, pred_draw_prob, pred_away_win_prob, pred_score,
               odds_home, odds_draw, odds_away, status, score,
               odds_home_pinnacle, odds_home_williamhill, odds_home_draftkings,
               odds_source, odds_last_update, odds_bookmaker_keys{extra}
        FROM matches ORDER BY match_num ASC''')]
    for mm in matches:
        for c in XG_COLS:
            mm.setdefault(c, None)
    teams = [dict(r) for r in cur.execute(
        'SELECT name, elo_rating, fifa_rank FROM teams ORDER BY elo_rating DESC')]
    champs = []
    try:
        d = cur.execute('SELECT MAX(snapshot_date) FROM champion_predictions').fetchone()[0]
        if d:
            champs = [dict(r) for r in cur.execute(
                'SELECT team, blended_ewma FROM champion_predictions '
                'WHERE snapshot_date=? ORDER BY blended_ewma DESC LIMIT 12', (d,))]
    except Exception:
        pass
    try:
        external_predictions.ensure_default_data(con)
        external_sources = external_predictions.load_sources(con)
        external_consensus = external_predictions.load_champion_consensus(con, limit=12)
    except Exception:
        external_sources = []
        external_consensus = []
    con.close()
    metrics = {}
    mp = os.path.join(HERE, 'backtest_metrics.json')
    if os.path.exists(mp):
        with open(mp, encoding='utf-8') as f:
            metrics = json.load(f)
    # Live tournament accuracy (this World Cup's completed matches), if available.
    lp = os.path.join(HERE, 'prediction_metrics_live.json')
    if os.path.exists(lp):
        try:
            with open(lp, encoding='utf-8') as f:
                live = json.load(f)
            if live.get('n'):
                metrics['live'] = live
        except Exception:
            pass
    return matches, teams, champs, metrics, external_sources, external_consensus


def load_bets():
    """讀取個人投注（bets/bet_legs）與每腿的模型預測，供投注實測頁使用。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        bets = [dict(r) for r in cur.execute(
            'SELECT * FROM bets ORDER BY placed_date, bet_id')]
    except sqlite3.OperationalError:
        con.close()
        return []
    for b in bets:
        b['legs'] = [dict(r) for r in cur.execute('''
            SELECT l.match_num, l.pick_team, l.pick_side, l.result,
                   m.home_team, m.away_team, m.home_goals, m.away_goals, m.date,
                   m.pred_home_win_prob, m.pred_draw_prob, m.pred_away_win_prob,
                   m.pred_score, m.home_pre_match_elo, m.away_pre_match_elo
            FROM bet_legs l JOIN matches m ON m.match_num=l.match_num
            WHERE l.bet_id=? ORDER BY m.date, l.match_num''', (b['bet_id'],))]
    con.close()
    return bets


# ---------------------------------------------------------------- HTML helpers

def head(title, desc, canonical, og_extra=""):
    adsense = ""
    if site.ADSENSE_CLIENT:
        adsense = (f'<script async '
                   f'src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={site.ADSENSE_CLIENT}" '
                   f'crossorigin="anonymous"></script>')
    return f'''<!DOCTYPE html>
<html lang="{site.SITE_LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="robots" content="index,follow">
{og_extra}
{adsense}
<link rel="stylesheet" href="{rel_assets(canonical)}assets/style.css">
</head>
<body>
<header class="site-head">
  <a class="brand" href="{site.SITE_URL}/">⚽ {esc(site.SITE_TITLE)}</a>
  <nav><a href="{site.SITE_URL}/#schedule">賽程</a><a href="{site.SITE_URL}/#title">奪冠</a>
  <a href="{site.SITE_URL}/#sources">來源</a>
  <a href="{site.SITE_URL}/#ratings">評級</a><a href="{site.SITE_URL}/monte.html">模擬器</a>
  <a href="{site.SITE_URL}/bets.html">投注實測</a>
  <a href="{site.SITE_URL}/#accuracy">準確度</a><a href="{site.SITE_URL}/#live-accuracy">即時準確度</a></nav>
</header>
<main>'''


def rel_assets(canonical):
    # match pages live one level deeper
    return '../' if '/match/' in canonical else ''


def ad_unit():
    if not site.ADSENSE_CLIENT:
        return ''
    return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" '
            f'data-ad-client="{site.ADSENSE_CLIENT}" data-ad-format="auto" '
            f'data-full-width-responsive="true"></ins>'
            f'<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script></div>')


def foot():
    yr = datetime.now().year
    return f'''</main>
<footer class="site-foot">
  <p>資料每日更新・模型經 ~5 萬場歷史回測校準。本站僅提供研究與數據分析，不提供任何投注服務；賠率僅作價值研究參考，並標示 API、手動、模擬或未標示來源。</p>
  <p>進階互動工具（蒙地卡羅模擬器等）：<a href="{site.STREAMLIT_APP_URL}" rel="nofollow">開啟 App</a>
   ｜ © {yr} {esc(site.SITE_TITLE)}</p>
</footer>
</body></html>'''


def outcome_label(row):
    p = {'主勝': row['pred_home_win_prob'] or 0, '和局': row['pred_draw_prob'] or 0,
         '客勝': row['pred_away_win_prob'] or 0}
    return max(p, key=p.get)


def match_row_html(m):
    a = get_team_display_name(m['away_team'])
    h = get_team_display_name(m['home_team'])
    d, t = convert_to_taiwan_time(m['date'], m['time'])
    url = f"{site.SITE_URL}/match/{m['match_num']}.html"
    # Display scores as 客-主 (away-home) to match the 客 | 比分 | 主 column order.
    fs = flip_score(m['score'])
    score = esc(fs) if fs else 'VS'
    pred = flip_score(m['pred_score'])
    pred_disp = esc(pred) if pred else ''
    return f'''<tr data-twdate="{esc(d)}">
<td class="muted">#{m['match_num']}</td>
<td>{esc(d)} {esc(t)}</td>
<td class="team"><a href="{url}">{esc(a)}</a></td>
<td class="vs">{score}</td>
<td class="team"><a href="{url}">{esc(h)}</a></td>
<td>{pct(m['pred_away_win_prob'])}/{pct(m['pred_draw_prob'])}/{pct(m['pred_home_win_prob'])}</td>
<td><b>{esc(outcome_label(m))}</b></td>
<td>{pred_disp}</td>
</tr>'''


def _sync_badge(source):
    mode = (source.get('sync_mode') or '').lower()
    if mode == 'auto':
        return 'AUTO'
    if mode == 'partial_pdf':
        return 'PDF'
    if mode == 'manual_snapshot':
        return 'SNAPSHOT'
    return 'REVIEW'


def external_payload(external_sources, external_consensus):
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'external_sources': external_sources,
        'external_champion_consensus': external_consensus,
    }


def build_source_board(external_sources, external_consensus):
    if not external_sources and not external_consensus:
        return ''

    auto_count = sum(1 for s in external_sources if s.get('sync_mode') == 'auto')
    partial_count = sum(1 for s in external_sources if s.get('sync_mode') in ('partial_pdf', 'manual_snapshot'))
    review_count = sum(1 for s in external_sources if s.get('sync_mode') == 'manual_review')

    parts = ['<section id="sources" class="source-board">']
    parts.append('<div class="section-head"><div><h2>External Source Board / 外部模型來源看板</h2>')
    parts.append('<p class="muted">每個外部模型都標示免費性、同步模式、資料覆蓋範圍與快照狀態；避免把文章、商業頁或人工快照誤寫成即時 API。</p></div>')
    parts.append('<div class="source-summary">')
    parts.append(f'<span><b>{auto_count}</b> AUTO</span>')
    parts.append(f'<span><b>{partial_count}</b> PARTIAL</span>')
    parts.append(f'<span><b>{review_count}</b> REVIEW</span>')
    parts.append('</div></div>')

    parts.append('<div class="source-grid">')
    for s in external_sources:
        badge = _sync_badge(s)
        direct = '免費可抓' if s.get('free_direct') else '需人工確認'
        parts.append(
            '<article class="source-card">'
            f'<div class="source-top"><a href="{esc(s.get("source_url", ""))}" rel="nofollow">{esc(s.get("source_name", ""))}</a>'
            f'<span class="source-badge {badge.lower()}">{badge}</span></div>'
            f'<div class="source-meta">{esc(direct)} · {esc(s.get("trust_tier", ""))}</div>'
            f'<p>{esc(s.get("coverage", ""))}</p>'
            f'<small>Snapshot: {esc(s.get("snapshot_date") or "-")} · Status: {esc(s.get("last_sync_status") or "-")}</small>'
            '</article>'
        )
    parts.append('</div>')

    if external_consensus:
        parts.append('<h3>跨模型奪冠共識 Top 12</h3>')
        parts.append('<div class="tablewrap"><table><thead><tr>'
                     '<th>#</th><th>隊伍</th><th>平均奪冠率</th><th>來源數</th><th>來源</th>'
                     '</tr></thead><tbody>')
        for idx, row in enumerate(external_consensus, 1):
            parts.append(
                '<tr>'
                f'<td class="muted">{idx}</td>'
                f'<td>{esc(get_team_display_name(row.get("team", "")))}</td>'
                f'<td><b>{float(row.get("avg_prob") or 0) * 100:.1f}%</b></td>'
                f'<td>{esc(row.get("source_count", 0))}</td>'
                f'<td class="muted">{esc(row.get("sources", ""))}</td>'
                '</tr>'
            )
        parts.append('</tbody></table></div>')
    parts.append('</section>')
    return ''.join(parts)


def build_index(matches, teams, champs, metrics, external_sources=None, external_consensus=None):
    external_sources = external_sources or []
    external_consensus = external_consensus or []
    canonical = f"{site.SITE_URL}/"
    parts = [head(site.SITE_TITLE, site.SITE_DESC, canonical)]
    parts.append(f'''<section class="hero">
<h1>2026 FIFA 世界盃 AI 預測中心</h1>
<p>全 104 場賽事的勝負機率、賠率對比與最佳投注價值（EV）。集成 Elo／Pi-Rating／Berrar／Dixon-Coles
模型，並以約 5 萬場歷史國際賽回測校準。</p>
<p><a class="btn" href="{site.SITE_URL}/bets.html">🎟️ 投注實測：照預測下注 vs 真實結果 →</a></p></section>''')
    parts.append(ad_unit())

    # Champion race
    if champs:
        parts.append('<section id="title"><h2>🏆 奪冠機率 Top 12</h2><div class="cards">')
        for c in champs:
            parts.append(f'<div class="card"><span>{esc(get_team_display_name(c["team"]))}</span>'
                         f'<b>{c["blended_ewma"]*100:.1f}%</b></div>')
        parts.append('</div></section>')

    parts.append(build_source_board(external_sources, external_consensus))

    # Schedule
    parts.append('<section id="schedule"><h2>📅 賽程預測與賠率</h2>')
    # Date dropdown (Taiwan-time match dates) — filter schedule to one day.
    tw_dates = sorted({d for d in (convert_to_taiwan_time(m['date'], m['time'])[0] for m in matches)
                       if re.match(r'^\d{4}-\d{2}-\d{2}$', d or '')})
    date_opts = ''.join(f'<option value="{d}">{d}</option>' for d in tw_dates)
    parts.append('<div class="schedctl">')
    parts.append(f'<select id="datesel" class="filter" onchange="filt()">'
                 f'<option value="">📅 全部日期（台灣時間）</option>{date_opts}</select>')
    parts.append('<input id="q" class="filter" placeholder="搜尋隊伍 / 階段…" oninput="filt()">')
    parts.append('</div>')
    parts.append('<div class="tablewrap"><table id="sched"><thead><tr>'
                 '<th>#</th><th class="sortable" onclick="sortTime(this)">時間(台)<span class="arr"></span></th><th>客</th><th>比分</th><th>主</th>'
                 '<th>客/和/主</th><th>預測</th><th>比分預測(客-主)</th></tr></thead><tbody>')
    for m in matches:
        parts.append(match_row_html(m))
    parts.append('</tbody></table></div></section>')
    parts.append(ad_unit())

    # Ratings
    parts.append('<section id="ratings"><h2>📊 球隊實力評級（Elo）</h2><div class="tablewrap"><table><thead>'
                 '<tr><th>#</th><th>球隊</th><th>Elo</th><th>FIFA 排名</th></tr></thead><tbody>')
    for i, t in enumerate(teams[:48], 1):
        parts.append(f'<tr><td class="muted">{i}</td><td>{esc(get_team_display_name(t["name"]))}</td>'
                     f'<td>{t["elo_rating"]:.0f}</td><td>{t["fifa_rank"]}</td></tr>')
    parts.append('</tbody></table></div></section>')

    # Accuracy
    if metrics.get('calibrated'):
        c = metrics['calibrated']
        parts.append(f'''<section id="accuracy"><h2>🎯 模型準確度</h2>
<div class="cards">
<div class="card"><span>命中率</span><b>{c['accuracy']*100:.1f}%</b></div>
<div class="card"><span>RPS（越低越好）</span><b>{c['rps']:.3f}</b></div>
<div class="card"><span>回測場數</span><b>{c['n']:,}</b></div>
</div>
<p class="muted">RPS 0.17 屬職業級（足球模型常見 0.19–0.21，隨機約 0.33）；以 {metrics.get('eval_start','')} 起的歷史賽事評估。</p>
</section>''')

    # Live tournament accuracy — this World Cup's completed matches so far.
    lv = metrics.get('live')
    if lv:
        warn = '（樣本小，僅供參考）' if lv['n'] < 20 else ''
        hits = lv.get('hits', round(lv['accuracy'] * lv['n']))
        cf = lv.get('acc_by_conf', {})
        def _ct(tier):
            t = cf.get(tier) or {}
            return f"{t.get('hit', 0)}/{t.get('n', 0)}" if t.get('n') else "—"
        draw_note = ''
        dr = lv.get('draw_rate')
        dr_hist = lv.get('draw_rate_hist', 0.222)
        dr_card = ''
        if dr is not None:
            elevated = dr > dr_hist + 0.10
            mark = ' 🔺' if elevated else ''
            dr_card = (f'<div class="card"><span>本屆和局率{mark}</span><b>{dr*100:.0f}%</b>'
                       f'<span>歷史 {dr_hist*100:.0f}%・{lv.get("draws_actual",0)}/{lv["n"]}</span></div>')
            if elevated:
                draw_note = (f" 本屆和局率 {dr*100:.0f}%（{lv.get('draws_actual',0)}/{lv['n']}）"
                             f"遠高於歷史 {dr_hist*100:.0f}%（全體國際賽與世界盃皆約 22%），"
                             f"統計上屬異常偏移；多為早期小組賽變異，會隨場次回歸——"
                             f"故維持校準不動，僅持續追蹤。和局亦是足球模型的結構性盲點"
                             f"（歷史 5 萬場和局召回僅 ~0.6%），強行多猜和局會讓整體命中率下降。")
        parts.append(f'''<section id="live-accuracy"><h2>📡 本屆即時準確度{warn}</h2>
<div class="cards">
<div class="card"><span>已評估場次</span><b>{lv['n']}</b></div>
<div class="card"><span>勝負命中率</span><b>{lv['accuracy']*100:.0f}%</b><span>{hits}/{lv['n']}</span></div>
<div class="card"><span>RPS（越低越好）</span><b>{lv['rps']:.3f}</b></div>
<div class="card"><span>隨機基準 RPS</span><b>{lv['rps_uniform']:.3f}</b></div>
{dr_card}
</div>
<p class="muted">依信心分層命中：高信心(≥60%) <b>{_ct('high')}</b>、中信心(45–60%) <b>{_ct('mid')}</b>、低信心(&lt;45%) <b>{_ct('low')}</b>。{draw_note}
本屆已完賽場次的「正式預測」即時評分；RPS 低於隨機基準代表模型有效。每日自動更新。</p>
</section>''')

    parts.append('''<script>
function filt(){var q=document.getElementById('q').value.toLowerCase();
var ds=document.getElementById('datesel').value;
document.querySelectorAll('#sched tbody tr').forEach(function(r){
var okText=r.innerText.toLowerCase().indexOf(q)>-1;
var okDate=!ds||r.getAttribute('data-twdate')===ds;
r.style.display=(okText&&okDate)?'':'none';});}
function sortTime(th){
 var tb=document.querySelector('#sched tbody');
 var rows=[].slice.call(tb.querySelectorAll('tr'));
 var asc=th.getAttribute('data-asc')!=='1';
 th.setAttribute('data-asc',asc?'1':'0');
 rows.sort(function(a,b){
  var x=a.cells[1].innerText.trim(), y=b.cells[1].innerText.trim();
  return asc?(x>y?1:x<y?-1:0):(x<y?1:x>y?-1:0);});
 rows.forEach(function(r){tb.appendChild(r);});
 th.querySelector('.arr').textContent=asc?' ▲':' ▼';}
</script>''')
    parts.append(foot())
    return ''.join(parts)


def sim_params():
    """Per-match Poisson lambdas for the client-side Monte Carlo simulator.
    Replicates app.py's tab_monte hybrid-lambda formula EXACTLY so the static-site
    JS and the Streamlit app produce the same numbers."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute('''
        SELECT m.match_num, m.home_team, m.away_team,
               t_h.elo_rating he, t_h.fifa_rank hr, t_h.berrar_att hat, t_h.berrar_def hdf,
               t_h.fbref_xg_diff hxg, t_h.injury_count hinj, t_h.sentiment_score hsent,
               t_a.elo_rating ae, t_a.fifa_rank ar, t_a.berrar_att aat, t_a.berrar_def adf,
               t_a.fbref_xg_diff axg, t_a.injury_count ainj, t_a.sentiment_score asent
        FROM matches m
        LEFT JOIN teams t_h ON m.home_team = t_h.name
        LEFT JOIN teams t_a ON m.away_team = t_a.name
        WHERE m.status = 'Scheduled' ORDER BY m.match_num ASC''').fetchall()
    con.close()

    def nz(v, d=0.0):
        return v if v is not None else d

    out = []
    for r in rows:
        he, hr = nz(r['he'], 1400.0), nz(r['hr'], 50)
        ae, ar = nz(r['ae'], 1400.0), nz(r['ar'], 50)
        hat, hdf = nz(r['hat'], 1.0), nz(r['hdf'], 1.0)
        aat, adf = nz(r['aat'], 1.0), nz(r['adf'], 1.0)
        hc = nz(r['hxg']) * 40.0 + nz(r['hsent']) * 15.0 - nz(r['hinj']) * 12.0
        ac = nz(r['axg']) * 40.0 + nz(r['asent']) * 15.0 - nz(r['ainj']) * 12.0
        eff = (he - ae) + (ar - hr) * 4.0 + hc - ac
        le_h = 1.25 * (10 ** (eff / 1000.0))
        le_a = 1.25 * (10 ** (-eff / 1000.0))
        lb_h = 1.25 * hat * adf
        lb_a = 1.05 * aat * hdf
        out.append({
            'n': r['match_num'],
            'a': get_team_display_name(r['away_team']),
            'h': get_team_display_name(r['home_team']),
            'lh': round(0.5 * le_h + 0.5 * lb_h, 4),
            'la': round(0.5 * le_a + 0.5 * lb_a, 4),
        })
    return out


def build_monte(sims):
    canonical = f"{site.SITE_URL}/monte.html"
    title = "蒙地卡羅對戰模擬器 | 2026 世界盃 AI 預測"
    desc = "在瀏覽器即時跑 10 萬次蒙地卡羅模擬，估算任一場世界盃對決的獨贏、大小分(2.5)、雙方進球與精確比分機率。"
    p = [head(title, desc, canonical)]
    p.append('<section><h1>🎲 蒙地卡羅對戰模擬器</h1>'
             '<p class="muted">選一場未開賽對決，瀏覽器即時跑 10 萬次隨機抽樣（卜瓦松進球模型），'
             '估算獨贏、大小分、雙方皆進球與精確比分分佈。</p>')
    if not sims:
        p.append('<p>目前沒有未開賽的賽程可供模擬。</p></section>')
        p.append(foot())
        return ''.join(p)
    p.append('<select id="m" class="filter">')
    for s in sims:
        p.append(f'<option value="{s["n"]}">#{s["n"]} {esc(s["a"])} vs {esc(s["h"])}</option>')
    p.append('</select> <button id="run" class="btn">🚀 啟動 100,000 次模擬</button>')
    p.append('<p id="xg" class="muted"></p>')
    p.append('<div id="out" class="cards"></div>')
    p.append('<div id="scores"></div></section>')
    p.append(ad_unit())
    p.append('<script>const SIM=' + json.dumps(sims, ensure_ascii=False) + ';</script>')
    p.append('''<script>
function pois(l){var L=Math.exp(-l),k=0,p=1;do{k++;p*=Math.random();}while(p>L);return k-1;}
function run(){
 var n=+document.getElementById('m').value, s=SIM.find(x=>x.n==n);
 document.getElementById('xg').innerHTML='進球期望 xG — '+s.a+': <b>'+s.la.toFixed(2)+'</b> ｜ '+s.h+': <b>'+s.lh.toFixed(2)+'</b>';
 var N=100000,hw=0,dr=0,aw=0,ov=0,bt=0,sc={};
 for(var i=0;i<N;i++){var hg=pois(s.lh),ag=pois(s.la);
  if(hg>ag)hw++;else if(hg==ag)dr++;else aw++;
  if(hg+ag>2.5)ov++; if(hg>0&&ag>0)bt++;
  var k=hg+'-'+ag; sc[k]=(sc[k]||0)+1;}
 var pf=x=>(x/N*100).toFixed(2)+'%';
 var seh=Math.sqrt((hw/N)*(1-hw/N)/N)*100;
 document.getElementById('out').innerHTML=
  card('👑 獨贏 Moneyline','主勝 '+s.h+'：<b>'+pf(hw)+'</b> (±'+seh.toFixed(3)+'%)<br>和局：'+pf(dr)+'<br>客勝 '+s.a+'：'+pf(aw))
 +card('⚽ 大小分 2.5','大球：<b>'+pf(ov)+'</b><br>小球：'+pf(N-ov))
 +card('🔥 雙方皆進球','是：<b>'+pf(bt)+'</b><br>否：'+pf(N-bt));
 var top=Object.entries(sc).sort((a,b)=>b[1]-a[1]).slice(0,6);
 var html='<h2>最可能比分 (客-主)</h2><div class="tablewrap"><table><thead><tr><th>比分</th><th>機率</th><th></th></tr></thead><tbody>';
 top.forEach(e=>{var pc=e[1]/N*100;html+='<tr><td>'+e[0]+'</td><td>'+pc.toFixed(2)+'%</td><td style="width:50%"><div class="track"><i class="h" style="width:'+Math.min(100,pc*4)+'%"></i></div></td></tr>';});
 document.getElementById('scores').innerHTML=html+'</tbody></table></div>';
}
function card(t,b){return '<div class="card" style="min-width:240px"><span>'+t+'</span><div>'+b+'</div></div>';}
document.getElementById('run').onclick=run; run();
</script>''')
    p.append(foot())
    return ''.join(p)


def build_match(m, matches, live_details=None):
    a = get_team_display_name(m['away_team'])
    h = get_team_display_name(m['home_team'])
    a_en, h_en = esc(m['away_team']), esc(m['home_team'])
    d, t = convert_to_taiwan_time(m['date'], m['time'])
    canonical = f"{site.SITE_URL}/match/{m['match_num']}.html"
    title = f"{a_en} vs {h_en} 預測・賠率・比分 | 2026 世界盃 #{m['match_num']}"
    pred = outcome_label(m)
    desc = (f"{a_en} 對 {h_en}（2026 世界盃 {esc(m['group_or_stage'])}）AI 預測：客勝 "
            f"{pct(m['pred_away_win_prob'])}、和局 {pct(m['pred_draw_prob'])}、主勝 "
            f"{pct(m['pred_home_win_prob'])}，預測比分 {esc(m['pred_score'] or '')}。台灣時間 {esc(d)} {esc(t)}。")

    # JSON-LD SportsEvent for rich results
    ld = {
        "@context": "https://schema.org", "@type": "SportsEvent",
        "name": f"{m['away_team']} vs {m['home_team']}",
        "sport": "Soccer", "startDate": m['date'],
        "competitor": [{"@type": "SportsTeam", "name": m['away_team']},
                       {"@type": "SportsTeam", "name": m['home_team']}],
    }
    og = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'

    p = [head(title, desc, canonical, og)]
    p.append(f'<nav class="crumb"><a href="{site.SITE_URL}/#schedule">← 全部賽程</a></nav>')
    p.append(f'<article class="match"><div class="muted">{esc(m["group_or_stage"])}・{esc(d)} {esc(t)}（台灣時間）</div>')
    p.append(f'<h1>{esc(a)} <span class="vs">vs</span> {esc(h)}</h1>')

    def bar(lbl, v, cls):
        return (f'<div class="prob"><span>{lbl}</span><div class="track">'
                f'<i class="{cls}" style="width:{(v or 0)*100:.0f}%"></i></div>'
                f'<b>{pct(v)}</b></div>')
    p.append('<div class="probs">')
    p.append(bar(f'客勝（{esc(a)}）', m['pred_away_win_prob'], 'a'))
    p.append(bar('和局', m['pred_draw_prob'], 'd'))
    p.append(bar(f'主勝（{esc(h)}）', m['pred_home_win_prob'], 'h'))
    p.append('</div>')

    pscore = flip_score(m['pred_score'])
    p.append(f'<p class="lead">模型預測最可能結果：<b>{esc(pred)}</b>，預測比分（{esc(a)}-{esc(h)}）<b>{esc(pscore or "—")}</b>。</p>')

    # Odds table (research / value reference only — no betting channel)
    if m['odds_home']:
        source = esc(odds_source_label(m))
        p.append(f'<h2>賠率（{source}，研究參考）</h2><table class="odds"><thead><tr><th>客勝</th><th>和局</th><th>主勝</th></tr></thead>'
                 f'<tbody><tr><td>{m["odds_away"] or "-"}</td><td>{m["odds_draw"] or "-"}</td>'
                 f'<td>{m["odds_home"] or "-"}</td></tr></tbody></table>')
        if m.get('odds_last_update'):
            p.append(f'<p class="muted">賠率更新時間：{esc(m["odds_last_update"])}</p>')
    p.append(ad_unit())

    # Completed match: show actual result + model-vs-reality divergence reason.
    if m.get('status') == 'Completed' and flip_score(m['score']):
        score_disp = flip_score(m['score'])   # 客-主 to match the "客 vs 主" header
        p.append(f'<h2>賽果 vs 預測</h2><p class="lead">實際比分（{esc(a)}-{esc(h)}）：<b>{esc(score_disp)}</b></p>')
        # Post-match advanced stats from 365Scores (away-home order to match header).
        hx, ax = m.get('home_xg'), m.get('away_xg')
        if hx is not None and ax is not None:
            bits = [f'預期進球 xG（{esc(a)}-{esc(h)}）：<b>{ax:.2f}-{hx:.2f}</b>']
            hp, ap = m.get('home_possession'), m.get('away_possession')
            if hp is not None and ap is not None:
                bits.append(f'控球 {ap:.0f}%-{hp:.0f}%')
            hs, ss = m.get('home_shots'), m.get('away_shots')
            if hs is not None and ss is not None:
                bits.append(f'射門 {int(ss)}-{int(hs)}')
            p.append('<p class="lead">' + '，'.join(bits) + '。<span class="muted">數據來源：365Scores</span></p>')
        det = (live_details or {}).get(m['match_num'])
        if det and det.get('reason'):
            cls = 'ok' if det.get('hit') else 'miss'
            p.append(f'<ul class="reasons"><li class="{cls}">{esc(det["reason"])}</li></ul>')
    p.append('</article>')
    p.append(foot())
    return ''.join(p)


def _leg_to_m(leg):
    return {
        'home': leg['home_team'], 'away': leg['away_team'],
        'hg': leg['home_goals'], 'ag': leg['away_goals'],
        'ph': leg['pred_home_win_prob'], 'pd': leg['pred_draw_prob'],
        'pa': leg['pred_away_win_prob'], 'pred_score': leg['pred_score'],
        'elo_h': leg['home_pre_match_elo'], 'elo_a': leg['away_pre_match_elo'],
        'pick_side': leg['pick_side'], 'pick_team': leg['pick_team'],
    }


def build_bets(bets):
    """投注實測頁：照模型預測下注 → 真實結果 落差與原因分析（公開對外）。"""
    canonical = f"{site.SITE_URL}/bets.html"
    title = "投注實測：照預測下注 vs 真實結果 | 2026 世界盃 AI"
    desc = ("公開實測：完全照本站 AI 模型預測下注，逐場比對模型賽前預測與真實比賽結果，"
            "並分析每一場落差原因（命中／爆冷／合理變異）。研究與透明度展示，非投注服務。")
    p = [head(title, desc, canonical)]
    p.append('<section class="hero"><h1>🎟️ 投注實測：照預測下注 vs 真實結果</h1>'
             '<p>這裡公開記錄「<b>完全照本站 AI 模型預測</b>下注」的實際結果，逐場比對模型賽前怎麼說、'
             '球真的怎麼踢，並自動分析落差原因。目的是<b>透明驗證模型</b>，本站不提供任何投注服務。</p></section>')

    if not bets:
        p.append('<p class="muted">目前尚無投注紀錄。</p>')
        p.append(foot())
        return ''.join(p)

    # 統計
    all_legs = [lg for b in bets for lg in b['legs']]
    played = [lg for lg in all_legs if lg['home_goals'] is not None]
    hits = sum(1 for lg in played if lg['result'] == 'won')
    n_settled = sum(1 for b in bets if b['status'] in ('won', 'lost'))
    n_won = sum(1 for b in bets if b['status'] == 'won')
    total_stake = sum(b['stake'] for b in bets)

    leg_hit = f"{hits/len(played)*100:.0f}%" if played else '—'
    parlay_hit = f"{n_won}/{n_settled}" if n_settled else '—'
    p.append('<div class="cards">')
    p.append(f'<div class="card"><span>投注張數</span><b>{len(bets)}</b></div>')
    p.append(f'<div class="card"><span>總投注</span><b>NT${total_stake:.0f}</b></div>')
    p.append(f'<div class="card"><span>單場命中率</span><b>{leg_hit}</b></div>')
    p.append(f'<div class="card"><span>過關命中</span><b>{parlay_hit}</b></div>')
    p.append('</div>')

    side_zh = {'home': '主勝', 'away': '客勝', 'draw': '和局'}
    res_emoji = {'won': '✅', 'lost': '❌', 'pending': '⏳'}
    status_zh = {'open': '⏳ 未開獎', 'won': '✅ 全過關', 'lost': '❌ 未過關', 'void': '➖ 作廢'}

    p.append('<h2 id="tickets">投注明細（照預測押）</h2>')
    for b in bets:
        type_zh = '全部過關' if b['bet_type'] == 'parlay' else '單場'
        p.append(f'<h3>{esc(b["name"])}　<span class="muted">[{type_zh}・本金 '
                 f'NT${b["stake"]:.0f}・{esc(b["placed_date"])}]</span>　{status_zh.get(b["status"], b["status"])}</h3>')
        p.append('<div class="tablewrap"><table><thead><tr>'
                 '<th>場次</th><th>對戰</th><th>我押</th><th>模型賽前預測</th><th>實際比分(客-主)</th><th>命中</th>'
                 '</tr></thead><tbody>')
        for lg in b['legs']:
            a = get_team_display_name(lg['away_team'])
            h = get_team_display_name(lg['home_team'])
            pick = get_team_display_name(lg['pick_team'])
            probs = {'home': lg['pred_home_win_prob'] or 0,
                     'draw': lg['pred_draw_prob'] or 0,
                     'away': lg['pred_away_win_prob'] or 0}
            fav = max(probs, key=probs.get)
            # Display scores as 客-主 (away-home) to match the "客 vs 主" matchup column.
            pred_str = f"{side_zh[fav]} {probs[fav]*100:.0f}%・{esc(flip_score(lg['pred_score']) or '')}"
            score = f"{lg['away_goals']}-{lg['home_goals']}" if lg['home_goals'] is not None else '—'
            url = f"{site.SITE_URL}/match/{lg['match_num']}.html"
            p.append(f'<tr><td class="muted">#{lg["match_num"]}</td>'
                     f'<td class="team"><a href="{url}">{esc(a)} vs {esc(h)}</a></td>'
                     f'<td><b>{esc(pick)}勝</b></td><td>{pred_str}</td>'
                     f'<td>{esc(score)}</td><td>{res_emoji.get(lg["result"], lg["result"])}</td></tr>')
        p.append('</tbody></table></div>')

    p.append('<h2 id="analysis">逐場落差與原因</h2>')
    if not played:
        p.append('<p class="muted">⏳ 尚無已開賽場次。各場（6/11、6/12 起）比完後，'
                 '這裡會自動逐場列出「模型怎麼預測、實際怎麼踢、為何有落差」。</p>')
    else:
        p.append('<ul class="reasons">')
        for lg in all_legs:
            hit, reason = bet_tracker.analyze_divergence(_leg_to_m(lg))
            if hit is None:
                continue
            a = get_team_display_name(lg['away_team'])
            h = get_team_display_name(lg['home_team'])
            cls = 'ok' if hit else 'miss'
            p.append(f'<li class="{cls}"><b>#{lg["match_num"]} {esc(a)} vs {esc(h)}</b>'
                     f'（{esc(lg["date"])}）<br>{esc(reason)}</li>')
        p.append('</ul>')

    p.append('<p class="muted" style="margin-top:24px">說明：本頁為模型透明度驗證與研究用途，'
             '記錄個人照預測下注的結果，<b>不提供任何投注管道或導流</b>。</p>')
    p.append(foot())
    return ''.join(p)


CSS = '''
:root{--bg:#0b1020;--panel:#121a30;--line:#1f2c4d;--txt:#e8edf7;--mut:#8aa0c8;--acc:#21d07a;--h:#3aa0ff;--a:#ff6b6b;--d:#f4c542}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,"Noto Sans TC",Segoe UI,Roboto,sans-serif;line-height:1.6}
a{color:var(--h);text-decoration:none}main{max-width:1080px;margin:0 auto;padding:16px}
.site-head{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:9}
.brand{font-weight:800;font-size:18px;color:var(--txt)}.site-head nav a{margin-left:14px;color:var(--mut)}
.hero h1{font-size:30px;margin:.2em 0}.hero p{color:var(--mut);max-width:760px}
h2{margin-top:34px;border-left:4px solid var(--acc);padding-left:10px}
.cards{display:flex;flex-wrap:wrap;gap:10px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:130px;display:flex;flex-direction:column}
.card span{color:var(--mut);font-size:13px}.card b{font-size:22px}
.filter{width:100%;max-width:340px;padding:10px 12px;margin:8px 0 12px;border-radius:10px;border:1px solid var(--line);background:#0d1426;color:var(--txt)}
th.sortable{cursor:pointer;user-select:none}th.sortable:hover{color:var(--txt)}.arr{color:var(--acc);font-size:12px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:#0d1426;color:var(--mut);position:sticky;top:0}td.muted,.muted{color:var(--mut)}.team a{color:var(--txt)}.vs{color:var(--mut);text-align:center}
.btn{display:inline-block;background:var(--acc);color:#04240f;font-weight:700;padding:10px 16px;border-radius:8px;cursor:pointer;border:0}
.match h1{font-size:26px}.match .vs{color:var(--mut);font-size:18px}
.probs{margin:18px 0}.prob{display:grid;grid-template-columns:160px 1fr 56px;align-items:center;gap:10px;margin:8px 0}
.track{background:#0d1426;border-radius:8px;height:16px;overflow:hidden}.track i{display:block;height:100%}
.track .h{background:var(--h)}.track .a{background:var(--a)}.track .d{background:var(--d)}
.lead{font-size:17px}.odds{max-width:360px}.crumb{margin:6px 0 14px}
.section-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;flex-wrap:wrap}
.source-summary{display:flex;gap:8px;flex-wrap:wrap}.source-summary span{background:#0d1426;border:1px solid var(--line);border-radius:8px;padding:8px 10px;color:var(--mut)}
.source-summary b{display:block;color:var(--txt);font-size:20px;line-height:1}
.source-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:14px 0 20px}
.source-card{background:linear-gradient(180deg,#121a30,#0d1426);border:1px solid var(--line);border-radius:12px;padding:14px;min-height:150px}
.source-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.source-top a{font-weight:800;color:var(--txt)}
.source-badge{font-size:11px;font-weight:900;border-radius:999px;padding:3px 8px;color:#06101d;background:var(--mut)}
.source-badge.auto{background:var(--acc)}.source-badge.pdf{background:var(--d)}.source-badge.snapshot{background:var(--h);color:#fff}.source-badge.review{background:#718096;color:#fff}
.source-meta{color:var(--acc);font-size:12px;margin-top:8px;text-transform:uppercase;letter-spacing:.04em}
.source-card p{color:var(--mut);margin:8px 0}.source-card small{color:#7184aa}
.schedctl{display:flex;flex-wrap:wrap;gap:10px}.schedctl .filter{margin:8px 0;flex:1 1 240px}
.reasons{list-style:none;padding:0}.reasons li{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:12px 14px;margin:10px 0;line-height:1.7}
.reasons li.ok{border-left-color:var(--acc)}.reasons li.miss{border-left-color:var(--a)}
.ad{margin:20px 0;min-height:1px}.site-foot{max-width:1080px;margin:30px auto;padding:18px;color:var(--mut);font-size:13px;border-top:1px solid var(--line)}
@media(max-width:560px){.prob{grid-template-columns:110px 1fr 48px}.hero h1{font-size:24px}}
'''


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    matches, teams, champs, metrics, external_sources, external_consensus = load_data()
    os.makedirs(os.path.join(OUT, 'match'), exist_ok=True)
    os.makedirs(os.path.join(OUT, 'assets'), exist_ok=True)

    write(os.path.join(OUT, 'index.html'), build_index(
        matches, teams, champs, metrics, external_sources, external_consensus))
    live_details = {d['match_num']: d for d in (metrics.get('live', {}).get('details') or [])}
    for m in matches:
        write(os.path.join(OUT, 'match', f"{m['match_num']}.html"),
              build_match(m, matches, live_details))
    write(os.path.join(OUT, 'monte.html'), build_monte(sim_params()))
    write(os.path.join(OUT, 'bets.html'), build_bets(load_bets()))
    write(os.path.join(OUT, 'assets', 'style.css'), CSS)

    # data.json (machine-readable)
    write(os.path.join(OUT, 'data.json'), json.dumps(matches, ensure_ascii=False))
    write(os.path.join(OUT, 'external_predictions.json'),
          json.dumps(external_payload(external_sources, external_consensus), ensure_ascii=False))

    # SEO: sitemap + robots
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    urls = ([f"{site.SITE_URL}/", f"{site.SITE_URL}/monte.html", f"{site.SITE_URL}/bets.html"]
            + [f"{site.SITE_URL}/match/{m['match_num']}.html" for m in matches])
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f'<url><loc>{esc(u)}</loc><lastmod>{now}</lastmod></url>')
    sm.append('</urlset>')
    write(os.path.join(OUT, 'sitemap.xml'), '\n'.join(sm))
    write(os.path.join(OUT, 'robots.txt'), f"User-agent: *\nAllow: /\nSitemap: {site.SITE_URL}/sitemap.xml\n")
    write(os.path.join(OUT, '.nojekyll'), '')
    # AdSense ownership file (ca-pub-XXXX -> pub-XXXX).
    if site.ADSENSE_CLIENT:
        pub = site.ADSENSE_CLIENT.replace('ca-', '')
        write(os.path.join(OUT, 'ads.txt'), f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")
    if site.CUSTOM_DOMAIN:
        write(os.path.join(OUT, 'CNAME'), site.CUSTOM_DOMAIN.strip())

    print(f"靜態站已產生於 docs/：1 首頁 + {len(matches)} 場比賽頁 + sitemap。SITE_URL={site.SITE_URL}")


if __name__ == '__main__':
    main()
