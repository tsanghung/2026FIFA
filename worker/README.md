# fifa2026-sync-cron — 準點觸發資料同步的 Cloudflare Worker

GitHub 自家的 `schedule`(cron)是 best-effort、常延遲數小時,導致網站更新落後。
這支 Worker 用 **Cloudflare Cron Triggers**(準點)每 2 小時呼叫一次 GitHub 的
`workflow_dispatch` API,觸發既有的 `daily_sync` 工作流程。**真正的抓分／算分／重建／
部署仍在 GitHub Actions 上跑**,Worker 只負責「準時觸發」。

```
Cloudflare Worker (cron, 每2h) ──POST──▶ GitHub workflow_dispatch
                                              └─▶ daily_sync.yml 跑完整同步 + Deploy Hook 部署
```

## 一次性部署步驟

> 需要:Node.js（本機已有即可）。所有指令在 `worker/` 目錄下執行。

1. **建立 GitHub Fine-grained PAT**(給 Worker 用來觸發):
   - GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
   - Repository access:**Only select repositories → `tsanghung/2026FIFA`**
   - Permissions → Repository permissions → **Actions: Read and write**
   - Expiration 選長一點(例如 1 年),產生後**複製 token**(只會顯示一次)

2. **進到 worker 目錄**
   ```bash
   cd worker
   ```

3. **登入 Cloudflare**(二選一)
   ```bash
   npx wrangler login            # 開瀏覽器授權
   # 或:export CLOUDFLARE_API_TOKEN=<你的 Cloudflare API Token>
   ```

4. **設定機密(把 PAT 交給 Worker,不會進版控)**
   ```bash
   npx wrangler secret put GH_PAT
   # 貼上步驟 1 的 GitHub PAT,按 Enter
   ```

5. **(選用)啟用手動測試端點**
   ```bash
   npx wrangler secret put TRIGGER_KEY
   # 貼上一段隨機字串(例如用 openssl rand -hex 16 產生)
   ```

6. **部署**
   ```bash
   npx wrangler deploy
   ```
   部署後會顯示 Worker 網址,例如 `https://fifa2026-sync-cron.<你的子網域>.workers.dev`。

## 驗證

- **看 cron 是否觸發**:`npx wrangler tail`,等到整點 cron 後,log 會出現
  `workflow_dispatch -> 204`(204 = 成功)。
- **想立刻測**(需做了步驟 5):瀏覽器開
  `https://fifa2026-sync-cron.<你的子網域>.workers.dev/?key=<TRIGGER_KEY>`
  → 回應 `dispatched ✅`,且 GitHub → Actions 立刻會出現一筆 `daily_sync` 執行。

## 注意事項

- **GitHub 端已對應調整**:已移除每 2 小時的 GitHub `schedule`(改由本 Worker 觸發),
  GitHub 只保留**每日 07:00 UTC**那班 —— 做每日校準,並在 Worker 萬一掛掉時當安全網。
  所以**請務必完成本 Worker 部署**,否則更新頻率會掉到一天一次。
- **頻率**:維持每 2 小時即可。要改頻率就編輯 `wrangler.toml` 的 `crons`。
  別調太密 —— Cloudflare Pages 免費約 **500 builds/月**,每 2 小時約 360/月,安全。
- **PAT 過期**:Fine-grained PAT 到期後 Worker 會觸發失敗(log 顯示 401);屆時重設一次
  `wrangler secret put GH_PAT` 即可。
