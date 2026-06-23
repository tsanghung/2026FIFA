"""
site_config.py — settings for the static site produced by build_static.py.

Fill these in for production (custom domain + AdSense). Sensible defaults let the
site build and work immediately on GitHub/Cloudflare Pages without a domain.

Every value can be overridden by an environment variable of the same name, so the
Cloudflare Pages build can point SITE_URL at the new domain without editing code.
"""
import os

# Public base URL of the deployed static site (used for canonical links + sitemap).
# e.g. "https://worldcup2026.simonsynapse.net" or your *.pages.dev URL.
# Override via the SITE_URL env var (set this as a repo Variable for the Action).
# `or` (not a default arg) so an empty env value falls back instead of blanking it.
SITE_URL = (os.environ.get("SITE_URL") or "https://sfiimfoan.simonsynapse.net").rstrip("/")

SITE_TITLE = os.environ.get("SITE_TITLE") or "2026 世界盃 AI 預測 ・ 賠率 ・ 比分"
SITE_DESC = ("2026 FIFA 世界盃全 104 場 AI 勝負預測、來源標示賠率對比與期望值（EV）研究。"
             "Elo/Pi/Berrar/Dixon-Coles 集成模型，經 5 萬場歷史回測校準。")
SITE_LANG = "zh-Hant"

# Google AdSense publisher id, e.g. "ca-pub-1234567890123456". Leave blank to omit
# all AdSense markup (it cannot be verified on *.streamlit.app — needs this domain).
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT") or ""

# Optional custom domain. If set, a CNAME file is written for GitHub Pages.
CUSTOM_DOMAIN = os.environ.get("CUSTOM_DOMAIN") or ""

# Link back to the interactive Streamlit tool (advanced features: Monte Carlo, etc.).
STREAMLIT_APP_URL = os.environ.get("STREAMLIT_APP_URL") or "https://2026fifa.streamlit.app/"
