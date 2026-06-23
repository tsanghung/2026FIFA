# 遷移：前端 → Cloudflare Pages，後端 → Supabase

目前:GitHub Action 每日算資料 → SQLite `fifa_2026.db` → `build_static.py` 產生 `docs/`
→ GitHub Pages 代管。

目標(依你的決定):
- **前端 100% Cloudflare Pages**(走 Cloudflare 儀表板 Git 整合,**不經 GitHub Action**)
- **後端 Supabase Postgres**(資料權威來源 + 自動 API)
- **自訂網域**:`simonsynapse.net`(子網域**不含任何 FIFA 字串**,建議 `sfiimfoan.simonsynapse.net`)
- **GitHub Pages**:遷移完成後**關閉**

---

## A. 後端 → Supabase
> ✅ 已在本機用 **PostgreSQL 16** 實測:`schema.sql` 套用無誤(9 表 + RLS),且把**全部現有資料**
> 載入並**重跑兩次 upsert**,行數完全一致(冪等)。你照下面做即可。

1. 建表(二選一):
   - **方式 a**:Supabase → **SQL Editor**,貼上並執行 `supabase/schema.sql`。
   - **方式 b(一行指令)**:`pip install psycopg2-binary`,然後
     `SUPABASE_DB_URL='postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres' python migrate/apply_schema.py`
   - schema 鏡射 SQLite;含 RLS:公開表可匿名讀、`bets`/`bet_legs` 個人資料僅 service key 可存取。
2. Project Settings → API,取得:**Project URL**(`https://<ref>.supabase.co`)、**service_role key**、**anon key**。
3. 把以下加進 GitHub repo → Settings → Secrets and variables → Actions → **Secrets**
   (D1:每日 sync 就在 GitHub Actions 跑,會自動 `supabase_sync.py` 把全部表冪等 upsert 到 Supabase):
   - `SUPABASE_URL`、`SUPABASE_SERVICE_KEY`
   - 手動測試:`SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python supabase_sync.py`
   - schema 有變更:`python migrate/gen_supabase_schema.py` → 到 Supabase 重跑 SQL。

## B. 前端 → Cloudflare Pages(Git 整合,免 GitHub Action)
1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → 選此 repo。
   - 專案名稱用**不含 FIFA** 的名字,例如 `worldcup2026`(會成為 `worldcup2026.pages.dev`)。
2. 設定:**Build command 留空**、**Build output directory = `docs`**(網站已預先建好並提交)。
3. **Environment variables**(Pages 專案 → Settings → Environment variables)新增:
   - `SITE_URL = https://sfiimfoan.simonsynapse.net`（canonical/sitemap 用)
   - 若 build command 留空則不會用到,但若日後改成在 CF build 才需要。目前 `docs/` 是預建的,
     canonical 由「運算端」build 時的 `SITE_URL` 決定 → 把 `SITE_URL` 設在運算端(D 段)。
4. 每次 push 到 `main`(運算端提交新的 `docs/`),Cloudflare 自動部署。

## C. 自訂網域 + 關閉 GitHub Pages
1. Cloudflare Pages 專案 → **Custom domains** → 加 `sfiimfoan.simonsynapse.net`
   (simonsynapse.net 的 DNS 若已在 Cloudflare,會自動建 CNAME)。
2. 把運算端的 `SITE_URL` 設為 `https://sfiimfoan.simonsynapse.net`,重建一次 `docs/`。
3. 確認新站正常後:GitHub repo → **Settings → Pages → 關閉**(Source 設為 None)。

## D. ✅ 每日運算(compute)— 已採用 D1
資料不是靜態的:每天要跑 **Python 管線**(維基爬蟲 + Elo/Pi/Berrar/Dixon-Coles + 蒙地卡羅
總冠軍 + 9,900+ 場歷史回測 + 產生 `docs/`)。Cloudflare Pages 只放靜態檔、Workers 跑 JS,
這條 Python 管線無法原封不動搬上去,因此**已採用 D1**:

- **GitHub Actions 純當「隱形排程」**:每日 sync 照舊運算 → 產生 `docs/`(用正式 `SITE_URL`)
  → `supabase_sync.py` 把全部表 upsert 到 Supabase → 提交 `docs/` 回 repo →
  **Cloudflare Pages Git 整合自動部署**。使用者只看到 Cloudflare + Supabase。
- 已接好:`daily_sync.yml` 含「Push data to Supabase」步驟與正式 `SITE_URL` 建置;`deploy.yml` 已移除。
- 若日後要「完全不碰 GitHub」(D2:改寫到 Cloudflare Workers/Containers 跑 Python),再另議——
  那是大重構(SQLite→Supabase 全面改寫、塞進 CF 執行上限),非必要不建議。

---

## 需要你提供 / 操作（總表）
| 項目 | 放哪 | 用途 |
|---|---|---|
| 執行 `supabase/schema.sql` | Supabase SQL Editor | 建表 |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | GitHub **Secret** | 每日 sync 寫入 Supabase |
| Cloudflare Pages 專案(連 Git,output=`docs`) | Cloudflare 儀表板 | 前端代管 |
| `sfiimfoan.simonsynapse.net` | Cloudflare Custom domains | 自訂網域 |
| `SITE_URL=https://sfiimfoan.simonsynapse.net` | GitHub **Variable** | canonical/sitemap |
| 關閉 GitHub Pages | GitHub Settings → Pages | 收尾 |

> 機密一律放各平台的 Secret/環境變數,**不要貼在對話裡**。
