#!/usr/bin/env bash
# One-shot migration runner: Supabase (schema + data) + Cloudflare Pages (deploy + domain).
#
# Run this where the network can reach Supabase & Cloudflare:
#   - on your own machine, OR
#   - from the Claude web sandbox AFTER adding these hosts to the egress allowlist:
#       api.cloudflare.com, <ref>.supabase.co, db.<ref>.supabase.co
#
# Required env vars:
#   SUPABASE_URL            https://<ref>.supabase.co
#   SUPABASE_SERVICE_KEY    Supabase -> Settings -> API -> service_role key
#   CLOUDFLARE_API_TOKEN    Cloudflare token (Pages:Edit + DNS:Edit for the zone)
#   CLOUDFLARE_ACCOUNT_ID   Cloudflare -> right sidebar Account ID
# Optional:
#   SUPABASE_DB_URL         postgres URI -> if set, creates tables via apply_schema.py
#                           (otherwise run supabase/schema.sql in the SQL editor first)
#   CF_PAGES_PROJECT        Pages project name (default: worldcup2026)
#   CUSTOM_DOMAIN           default: sfiimfoan.simonsynapse.net
set -euo pipefail
cd "$(dirname "$0")/.."

CF_PAGES_PROJECT="${CF_PAGES_PROJECT:-worldcup2026}"
CUSTOM_DOMAIN="${CUSTOM_DOMAIN:-sfiimfoan.simonsynapse.net}"

req() { [ -n "${!1:-}" ] || { echo "ERROR: env $1 is required"; exit 1; }; }
req SUPABASE_URL; req SUPABASE_SERVICE_KEY
req CLOUDFLARE_API_TOKEN; req CLOUDFLARE_ACCOUNT_ID

echo "==> 1/5 Create tables (Supabase)"
if [ -n "${SUPABASE_DB_URL:-}" ]; then
  python migrate/apply_schema.py
else
  echo "    SUPABASE_DB_URL not set -> assuming supabase/schema.sql already run in SQL editor."
fi

echo "==> 2/5 Rebuild static site (docs/) from current DB"
python build_static.py >/dev/null

echo "==> 3/5 Push data to Supabase"
python supabase_sync.py

echo "==> 4/5 Deploy docs/ to Cloudflare Pages ($CF_PAGES_PROJECT)"
# creates the project on first deploy if it doesn't exist
npx --yes wrangler@latest pages project create "$CF_PAGES_PROJECT" \
    --production-branch main 2>/dev/null || true
npx --yes wrangler@latest pages deploy docs \
    --project-name "$CF_PAGES_PROJECT" --branch main

echo "==> 5/5 Attach custom domain ($CUSTOM_DOMAIN)"
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/${CF_PAGES_PROJECT}/domains" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data "{\"name\":\"${CUSTOM_DOMAIN}\"}" | python3 -c "import sys,json;d=json.load(sys.stdin);print('   domain attach:', 'OK' if d.get('success') else d.get('errors'))" || true

echo
echo "Done. Visit https://${CUSTOM_DOMAIN} (SSL provisioning may take a few minutes)."
echo "Remember to: (a) add SUPABASE_URL/SUPABASE_SERVICE_KEY to GitHub repo Secrets"
echo "             so the daily Action keeps Supabase in sync, and (b) disable GitHub Pages."
