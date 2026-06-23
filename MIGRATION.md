# 遷移：前端 → Cloudflare Pages，後端 → Supabase

目前:GitHub Action 每日算資料 → SQLite `fifa_2026.db` → `build_static.py` 產生 `docs/`
→ GitHub Pages 代管。

目標(依你的決定):
- **前端 100% Cloudflare Pages**(走 Cloudflare 儀表板 Git 整合,**不經 GitHub Action**)
- **後端 Supabase Postgres**(資料權威來源 + 自動 API)
- **自訂網域**:`simonsynapse.net`(子網域**不含任何 FIFA 字串**,建議 `worldcup2026.simonsynapse.net`)
- **GitHub Pages**:遷移完成後**關閉**

---

## A. 後端 → Supabase
1. Supabase → **SQL Editor**,貼上並執行 `supabase/schema.sql`(自動產生,鏡射 SQLite;含 RLS:
   公開表可匿名讀、`bets`/`bet_legs` 個人資料僅 service key 可存取)。
2. Project Settings → API,取得:**Project URL**(`https://<ref>.supabase.co`)、**service_role key**、**anon key**。
3. 之後由「運算端」(見 D 段)以 `supabase_sync.py` 冪等 upsert 全部資料表到 Supabase。
   - schema 有變更:`python migrate/gen_supabase_schema.py` → 到 Supabase 重跑 SQL。

## B. 前端 → Cloudflare Pages(Git 整合,免 GitHub Action)
1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → 選此 repo。
   - 專案名稱用**不含 FIFA** 的名字,例如 `worldcup2026`(會成為 `worldcup2026.pages.dev`)。
2. 設定:**Build command 留空**、**Build output directory = `docs`**(網站已預先建好並提交)。
3. **Environment variables**(Pages 專案 → Settings → Environment variables)新增:
   - `SITE_URL = https://worldcup2026.simonsynapse.net`（canonical/sitemap 用)
   - 若 build command 留空則不會用到,但若日後改成在 CF build 才需要。目前 `docs/` 是預建的,
     canonical 由「運算端」build 時的 `SITE_URL` 決定 → 把 `SITE_URL` 設在運算端(D 段)。
4. 每次 push 到 `main`(運算端提交新的 `docs/`),Cloudflare 自動部署。

## C. 自訂網域 + 關閉 GitHub Pages
1. Cloudflare Pages 專案 → **Custom domains** → 加 `worldcup2026.simonsynapse.net`
   (simonsynapse.net 的 DNS 若已在 Cloudflare,會自動建 CNAME)。
2. 把運算端的 `SITE_URL` 設為 `https://worldcup2026.simonsynapse.net`,重建一次 `docs/`。
3. 確認新站正常後:GitHub repo → **Settings → Pages → 關閉**(Source 設為 None)。

## D. ⚠️ 每日運算(compute)要放哪 — 需要你拍板
資料不是靜態的:每天要跑 **Python 管線**(維基爬蟲 + Elo/Pi/Berrar/Dixon-Coles + 蒙地卡羅
總冠軍 + 9,900+ 場歷史回測 + 產生 `docs/`)。**Cloudflare Pages 只放靜態檔、Workers 跑 JS
(Python 仍 beta 且套件受限)**,所以這條 Python 管線**無法原封不動搬上 Cloudflare**。三條路:

- **D1（推薦・零重寫）**:保留 GitHub Actions 純當「**隱形排程**」——只負責運算,把資料
  `upsert` 到 Supabase、並把 `docs/` 提交回 repo(Cloudflare Git 整合自動部署)。
  使用者只看到 Cloudflare + Supabase;GitHub 只是看不見的建置箱。免費、已可運作。
- **D2（真・零 GitHub,工程大）**:把運算改到 **Cloudflare Containers/Workers(Python)** +
  Cron Trigger。需要:① 全面把 `sqlite3` 改成直接讀寫 Supabase Postgres;② 把爬蟲/回測
  塞進 CF 執行環境與其 CPU/記憶體上限;③ 可能需付費方案。風險高、需數天重構。
- **D3（你自管排程）**:在你掌控的小主機/排程(VPS、cron、或任何容器服務)跑現有 Python,
  寫入 Supabase + 觸發 Cloudflare 部署。前端/後端仍 100% 在 Cloudflare/Supabase。

> 我的建議:**D1**——前端與資料 100% 在你的 Cloudflare/Supabase 上,GitHub 只剩一個沒人看見、
> 免費的排程器。若你堅持「完全不碰 GitHub」,就走 **D2**(我會分階段重構,但要有工程量與風險的心理準備)。

---

## 需要你提供 / 操作（總表）
| 項目 | 放哪 | 用途 |
|---|---|---|
| 執行 `supabase/schema.sql` | Supabase SQL Editor | 建表 |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | 運算端密鑰(D 段) | 寫入 Supabase |
| Cloudflare Pages 專案(連 Git,output=`docs`) | Cloudflare 儀表板 | 前端代管 |
| `worldcup2026.simonsynapse.net` | Cloudflare Custom domains | 自訂網域 |
| `SITE_URL=https://worldcup2026.simonsynapse.net` | 運算端環境變數 | canonical/sitemap |
| 關閉 GitHub Pages | GitHub Settings → Pages | 收尾 |

> 機密一律放各平台的 Secret/環境變數,**不要貼在對話裡**。
