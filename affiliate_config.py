"""
affiliate_config.py — per-match affiliate ("去下注") link configuration.

Fill in your own affiliate tracking URLs below (from each bookmaker's affiliate
dashboard, e.g. bet365 Partners / DraftKings / William Hill via Income Access).
Leave a value blank to fall back to that bookmaker's public homepage (the link
still works but earns no commission).

⚠️ Legal / compliance notes:
  * Sports-betting affiliate programmes require approval and are restricted in many
    jurisdictions — make sure you are eligible and licensed where applicable.
  * Streamlit Community Cloud's free tier is intended for community/non-commercial
    use; heavy monetisation may breach their terms. For serious revenue, host on
    your own domain.
  * Always show a responsible-gambling / 18+ disclosure (the app does this).
"""

# Master switch for the whole feature.
AFFILIATE_ENABLED = True

# Paste your FULL affiliate tracking URL per bookmaker. Blank => homepage fallback.
AFFILIATE_LINKS = {
    'pinnacle': '',
    'williamhill': '',
    'draftkings': '',
}

# Public homepage fallbacks (used when no tracking URL is set above).
BOOKMAKER_HOME = {
    'pinnacle': 'https://www.pinnacle.com/',
    'williamhill': 'https://www.williamhill.com/',
    'draftkings': 'https://sportsbook.draftkings.com/',
}

# Call-to-action text shown on the link.
CTA_LABEL = '前往下注 ↗'

# Maps the schedule table's best-odds source tags to bookmaker keys.
SOURCE_TAG_TO_KEY = {'PIN': 'pinnacle', 'WH': 'williamhill', 'DK': 'draftkings'}


def get_affiliate_url(bookmaker_key):
    """Return the affiliate (or fallback homepage) URL for a bookmaker key, or
    None when the feature is disabled / the bookmaker is unknown."""
    if not AFFILIATE_ENABLED:
        return None
    key = (bookmaker_key or '').lower()
    return AFFILIATE_LINKS.get(key) or BOOKMAKER_HOME.get(key)


def best_book_key(best, pinnacle, williamhill, draftkings):
    """Identify which bookmaker offered the best odds value."""
    if not best:
        return None
    if best == pinnacle:
        return 'pinnacle'
    if best == williamhill:
        return 'williamhill'
    if best == draftkings:
        return 'draftkings'
    return 'pinnacle'
