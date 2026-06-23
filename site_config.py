"""
site_config.py — settings for the static site produced by build_static.py.

Fill these in for production (custom domain + AdSense). Sensible defaults let the
site build and work immediately on GitHub/Cloudflare Pages without a domain.

Every value can be overridden by an environment variable of the same name, so the
Cloudflare Pages build can point SITE_URL at the new domain without editing code.
"""
import os

# Public base URL of the deployed static site (used for canonical links + sitemap).
# e.g. "https://worldcup2026.example.com" or your *.pages.dev / *.github.io URL.
# Override via the SITE_URL env var (set this in Cloudflare Pages / the Action).
SITE_URL = os.environ.get("SITE_URL", "https://tsanghung.github.io/2026FIFA").rstrip("/")

SITE_TITLE = os.environ.get("SITE_TITLE", "2026 世界盃 AI 預測 ・ 賠率 ・ 比分")
SITE_DESC = ("2026 FIFA 世界盃全 104 場 AI 勝負預測、來源標示賠率對比與期望值（EV）研究。"
             "Elo/Pi/Berrar/Dixon-Coles 集成模型，經 5 萬場歷史回測校準。")
SITE_LANG = "zh-Hant"

# Google AdSense publisher id, e.g. "ca-pub-1234567890123456". Leave blank to omit
# all AdSense markup (it cannot be verified on *.streamlit.app — needs this domain).
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "")

# Optional custom domain. If set, a CNAME file is written for GitHub Pages.
CUSTOM_DOMAIN = os.environ.get("CUSTOM_DOMAIN", "")

# Link back to the interactive Streamlit tool (advanced features: Monte Carlo, etc.).
STREAMLIT_APP_URL = os.environ.get("STREAMLIT_APP_URL", "https://2026fifa.streamlit.app/")
