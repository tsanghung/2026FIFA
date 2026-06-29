// Cloudflare Worker — punctual trigger for the GitHub Actions data sync.
//
// Why: GitHub's own `schedule` (cron) is best-effort and was lagging by hours,
// so the site fell behind. Cloudflare Cron Triggers fire on time. This Worker
// simply calls GitHub's workflow_dispatch API on a cron schedule; all the heavy
// work (scrape scores, run the model, rebuild, deploy) still happens on GitHub
// Actions — we only make the *trigger* reliable.
//
// Secrets (set with `wrangler secret put ...`):
//   GH_PAT       GitHub fine-grained PAT, repo tsanghung/2026FIFA, Actions: R/W  (required)
//   TRIGGER_KEY  random string; enables the manual GET test endpoint            (optional)

const GH_DISPATCH =
  'https://api.github.com/repos/tsanghung/2026FIFA/actions/workflows/daily_sync.yml/dispatches';

async function triggerSync(env) {
  const res = await fetch(GH_DISPATCH, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GH_PAT}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      'User-Agent': 'fifa2026-sync-cron',
    },
    // ref = branch to run on. We do NOT set force_calibrate, so the heavy daily
    // calibration stays on GitHub's own 07:00 run, not on every 2h trigger.
    body: JSON.stringify({ ref: 'main' }),
  });
  const detail = res.ok ? '' : ` ${await res.text()}`;
  console.log(`workflow_dispatch -> ${res.status}${detail}`);
  return res;
}

export default {
  // Fired by the cron schedule in wrangler.toml ([triggers].crons).
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerSync(env));
  },

  // Optional manual test: GET https://<worker-url>/?key=<TRIGGER_KEY>
  async fetch(req, env) {
    if (!env.GH_PAT) {
      return new Response('GH_PAT secret is not set', { status: 500 });
    }
    const key = new URL(req.url).searchParams.get('key');
    if (!env.TRIGGER_KEY || key !== env.TRIGGER_KEY) {
      return new Response('forbidden', { status: 403 });
    }
    const res = await triggerSync(env);
    return new Response(res.ok ? 'dispatched ✅' : `failed: ${res.status}`, {
      status: res.ok ? 200 : 502,
    });
  },
};
