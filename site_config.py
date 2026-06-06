"""
site_config.py — settings for the static site produced by build_static.py.

Fill these in for production (custom domain + AdSense). Sensible defaults let the
site build and work immediately on GitHub/Cloudflare Pages without a domain.
"""

# Public base URL of the deployed static site (used for canonical links + sitemap).
# e.g. "https://worldcup2026.example.com" or your *.pages.dev / *.github.io URL.
SITE_URL = "https://tsanghung.github.io/2026fifa"

SITE_TITLE = "2026 世界盃 AI 預測 ・ 賠率 ・ 比分"
SITE_DESC = ("2026 FIFA 世界盃全 104 場 AI 勝負預測、即時賠率對比與最佳投注價值（EV）。"
             "Elo/Pi/Berrar/Dixon-Coles 集成模型，經 5 萬場歷史回測校準。")
SITE_LANG = "zh-Hant"

# Google AdSense publisher id, e.g. "ca-pub-1234567890123456". Leave blank to omit
# all AdSense markup (it cannot be verified on *.streamlit.app — needs this domain).
ADSENSE_CLIENT = ""

# Optional custom domain. If set, a CNAME file is written for GitHub Pages.
CUSTOM_DOMAIN = ""

# Link back to the interactive Streamlit tool (advanced features: Monte Carlo, etc.).
STREAMLIT_APP_URL = "https://2026fifa.streamlit.app/"
