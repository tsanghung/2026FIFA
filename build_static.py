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
import affiliate_config as aff
import site_config as site

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, 'fifa_2026.db')
OUT = os.path.join(HERE, 'docs')


def esc(s):
    return html.escape(str(s if s is not None else ''))


def pct(x):
    return f"{(x or 0) * 100:.0f}%"


def bet_link_for(row):
    """Affiliate (or homepage) URL to the bookmaker with the best home odds."""
    if not row['odds_home']:
        return None
    bk = aff.best_book_key(row['odds_home'], row['odds_home_pinnacle'],
                           row['odds_home_williamhill'], row['odds_home_draftkings'])
    return aff.get_affiliate_url(bk)


def load_data():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    matches = [dict(r) for r in cur.execute('''
        SELECT match_num, group_or_stage, date, time, home_team, away_team,
               pred_home_win_prob, pred_draw_prob, pred_away_win_prob, pred_score,
               odds_home, odds_draw, odds_away, status, score,
               odds_home_pinnacle, odds_home_williamhill, odds_home_draftkings
        FROM matches ORDER BY match_num ASC''')]
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
    con.close()
    metrics = {}
    mp = os.path.join(HERE, 'backtest_metrics.json')
    if os.path.exists(mp):
        with open(mp, encoding='utf-8') as f:
            metrics = json.load(f)
    return matches, teams, champs, metrics


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
  <a href="{site.SITE_URL}/#ratings">評級</a><a href="{site.SITE_URL}/monte.html">模擬器</a>
  <a href="{site.SITE_URL}/#accuracy">準確度</a></nav>
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
  <p>資料每日更新・模型經 ~5 萬場歷史回測校準。預測僅供參考，投注有風險，未滿 18 歲請勿參與。</p>
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
    bl = bet_link_for(m)
    bet = (f'<a class="bet" href="{esc(bl)}" target="_blank" rel="nofollow noopener">{aff.CTA_LABEL}</a>'
           if bl else '')
    score = esc(m['score']) if m['score'] else 'VS'
    return f'''<tr>
<td class="muted">#{m['match_num']}</td>
<td>{esc(d)} {esc(t)}</td>
<td class="team"><a href="{url}">{esc(a)}</a></td>
<td class="vs">{score}</td>
<td class="team"><a href="{url}">{esc(h)}</a></td>
<td>{pct(m['pred_away_win_prob'])}/{pct(m['pred_draw_prob'])}/{pct(m['pred_home_win_prob'])}</td>
<td><b>{esc(outcome_label(m))}</b></td>
<td>{esc(m['pred_score'] or '')}</td>
<td>{bet}</td>
</tr>'''


def build_index(matches, teams, champs, metrics):
    canonical = f"{site.SITE_URL}/"
    parts = [head(site.SITE_TITLE, site.SITE_DESC, canonical)]
    parts.append(f'''<section class="hero">
<h1>2026 FIFA 世界盃 AI 預測中心</h1>
<p>全 104 場賽事的勝負機率、賠率對比與最佳投注價值（EV）。集成 Elo／Pi-Rating／Berrar／Dixon-Coles
模型，並以約 5 萬場歷史國際賽回測校準。</p></section>''')
    parts.append(ad_unit())

    # Champion race
    if champs:
        parts.append('<section id="title"><h2>🏆 奪冠機率 Top 12</h2><div class="cards">')
        for c in champs:
            parts.append(f'<div class="card"><span>{esc(get_team_display_name(c["team"]))}</span>'
                         f'<b>{c["blended_ewma"]*100:.1f}%</b></div>')
        parts.append('</div></section>')

    # Schedule
    parts.append('<section id="schedule"><h2>📅 賽程預測與賠率</h2>')
    parts.append('<input id="q" class="filter" placeholder="搜尋隊伍 / 階段…" oninput="filt()">')
    parts.append('<div class="tablewrap"><table id="sched"><thead><tr>'
                 '<th>#</th><th>時間(台)</th><th>客</th><th>比分</th><th>主</th>'
                 '<th>客/和/主</th><th>預測</th><th>比分預測</th><th></th></tr></thead><tbody>')
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

    parts.append('''<script>
function filt(){var q=document.getElementById('q').value.toLowerCase();
document.querySelectorAll('#sched tbody tr').forEach(function(r){
r.style.display=r.innerText.toLowerCase().indexOf(q)>-1?'':'none';});}
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
    p.append('</select> <button id="run" class="bet">🚀 啟動 100,000 次模擬</button>')
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


def build_match(m, matches):
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
    bl = bet_link_for(m)

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

    p.append(f'<p class="lead">模型預測最可能結果：<b>{esc(pred)}</b>，預測比分 <b>{esc(m["pred_score"] or "—")}</b>。</p>')

    # Odds table
    if m['odds_home']:
        p.append('<h2>賠率（最佳）</h2><table class="odds"><thead><tr><th>客勝</th><th>和局</th><th>主勝</th></tr></thead>'
                 f'<tbody><tr><td>{m["odds_away"] or "-"}</td><td>{m["odds_draw"] or "-"}</td>'
                 f'<td>{m["odds_home"] or "-"}</td></tr></tbody></table>')
    if bl:
        p.append(f'<p><a class="bet big" href="{esc(bl)}" target="_blank" rel="nofollow noopener">'
                 f'{aff.CTA_LABEL}（最佳賠率莊家）</a></p>')
    p.append(ad_unit())

    if m['score']:
        p.append(f'<p class="muted">實際比分：{esc(m["score"])}</p>')
    p.append('</article>')
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
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:#0d1426;color:var(--mut);position:sticky;top:0}td.muted,.muted{color:var(--mut)}.team a{color:var(--txt)}.vs{color:var(--mut);text-align:center}
.bet{display:inline-block;background:var(--acc);color:#04240f;font-weight:700;padding:6px 10px;border-radius:8px}.bet.big{padding:12px 18px;font-size:16px}
.match h1{font-size:26px}.match .vs{color:var(--mut);font-size:18px}
.probs{margin:18px 0}.prob{display:grid;grid-template-columns:160px 1fr 56px;align-items:center;gap:10px;margin:8px 0}
.track{background:#0d1426;border-radius:8px;height:16px;overflow:hidden}.track i{display:block;height:100%}
.track .h{background:var(--h)}.track .a{background:var(--a)}.track .d{background:var(--d)}
.lead{font-size:17px}.odds{max-width:360px}.crumb{margin:6px 0 14px}
.ad{margin:20px 0;min-height:1px}.site-foot{max-width:1080px;margin:30px auto;padding:18px;color:var(--mut);font-size:13px;border-top:1px solid var(--line)}
@media(max-width:560px){.prob{grid-template-columns:110px 1fr 48px}.hero h1{font-size:24px}}
'''


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    matches, teams, champs, metrics = load_data()
    os.makedirs(os.path.join(OUT, 'match'), exist_ok=True)
    os.makedirs(os.path.join(OUT, 'assets'), exist_ok=True)

    write(os.path.join(OUT, 'index.html'), build_index(matches, teams, champs, metrics))
    for m in matches:
        write(os.path.join(OUT, 'match', f"{m['match_num']}.html"), build_match(m, matches))
    write(os.path.join(OUT, 'monte.html'), build_monte(sim_params()))
    write(os.path.join(OUT, 'assets', 'style.css'), CSS)

    # data.json (machine-readable)
    write(os.path.join(OUT, 'data.json'), json.dumps(matches, ensure_ascii=False))

    # SEO: sitemap + robots
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    urls = ([f"{site.SITE_URL}/", f"{site.SITE_URL}/monte.html"]
            + [f"{site.SITE_URL}/match/{m['match_num']}.html" for m in matches])
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f'<url><loc>{esc(u)}</loc><lastmod>{now}</lastmod></url>')
    sm.append('</urlset>')
    write(os.path.join(OUT, 'sitemap.xml'), '\n'.join(sm))
    write(os.path.join(OUT, 'robots.txt'), f"User-agent: *\nAllow: /\nSitemap: {site.SITE_URL}/sitemap.xml\n")
    write(os.path.join(OUT, '.nojekyll'), '')
    if site.CUSTOM_DOMAIN:
        write(os.path.join(OUT, 'CNAME'), site.CUSTOM_DOMAIN.strip())

    print(f"靜態站已產生於 docs/：1 首頁 + {len(matches)} 場比賽頁 + sitemap。SITE_URL={site.SITE_URL}")


if __name__ == '__main__':
    main()
