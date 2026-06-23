# 遷移：前端 → Cloudflare Pages，後端 → Supabase

目前架構:每日 GitHub Action 算出資料 → 寫入 SQLite `fifa_2026.db` → `build_static.py`
產生 `docs/` 靜態網站 → GitHub Pages 代管。

遷移後:
- **後端(資料)** → **Supabase Postgres**(資料的權威來源 + 自動 REST API,供未來動態功能)
- **前端(靜態站)** → **Cloudflare Pages**(取代 GitHub Pages)

每日流程不變(仍在 GitHub Actions 算資料);新增的 `🚀 Deploy` workflow 會在每次 sync
後把資料推到 Supabase、並把網站部署到 Cloudflare Pages。**未設定密鑰前所有步驟都是安全 no-op。**

---

## A. Supabase(後端)

1. 在 Supabase 專案 → **SQL Editor**,貼上並執行 `supabase/schema.sql`(自動產生,鏡射 SQLite 結構;
   含 RLS:公開表可匿名讀取,`bets`/`bet_legs` 個人資料僅 service key 可存取)。
2. 取得連線資訊(Project Settings → API):
   - **Project URL**:`https://<ref>.supabase.co`
   - **service_role key**(機密,僅伺服器端用)
3. 把以下加進 GitHub repo → Settings → Secrets and variables → Actions → **Secrets**:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
4. 之後每次 sync 會自動 upsert 全部資料表到 Supabase(冪等,以主鍵 upsert)。
   手動測試:`SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python supabase_sync.py`

> schema 有變更時重新產生:`python migrate/gen_supabase_schema.py`,再到 Supabase 重跑 SQL。

## B. Cloudflare Pages(前端)

**方式一(推薦,全自動、走 GitHub Action)**
1. Cloudflare → 建立一個 **Pages** 專案(Direct Upload 即可,名稱例如 `2026fifa`)。
2. 建立 **API Token**:範本「Edit Cloudflare Workers」或自訂含 **Account → Cloudflare Pages → Edit** 權限。
3. 取得 **Account ID**(任一網域/Workers 頁右側)。
4. GitHub repo → Actions **Secrets** 加:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
5. GitHub repo → Actions **Variables** 加:
   - `SITE_URL` = 你的新網址(先用 `https://<project>.pages.dev`,有自訂網域再換)
   - `CF_PAGES_PROJECT` = Pages 專案名稱(若不是 `2026fifa`)
6. 之後 `🚀 Deploy` workflow 會用正確的 `SITE_URL` 重建並部署 `docs/` 到 Cloudflare Pages。

**方式二(免密鑰,走 Cloudflare 儀表板 Git 整合)**
1. Cloudflare Pages → Connect to Git → 選此 repo。
2. Build command 留空、**Build output directory = `docs`**(網站已預先建好並提交)。
3. 每次 push 到 `main`(含每日 sync 的提交)Cloudflare 會自動部署。
4. 仍建議設 repo 變數 `SITE_URL` 為新網址,讓 canonical/sitemap 指向新網域。

## C. 切換與收尾
- 確認新站正常後,可在 GitHub repo Settings → Pages 關閉 GitHub Pages(或保留作鏡像)。
- 自訂網域:在 Cloudflare Pages 專案 → Custom domains 綁定,並把 `SITE_URL` 改成該網域。

---

## 需要你提供 / 操作的東西(總表)
| 項目 | 放哪 | 用途 |
|---|---|---|
| `SUPABASE_URL` | GitHub **Secret** | 連 Supabase |
| `SUPABASE_SERVICE_KEY` | GitHub **Secret** | 寫入 Supabase(機密) |
| 執行 `supabase/schema.sql` | Supabase SQL Editor | 建表 |
| `CLOUDFLARE_API_TOKEN` | GitHub **Secret** | 部署 Pages |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub **Secret** | 部署 Pages |
| `SITE_URL` | GitHub **Variable** | 新網址(canonical/sitemap) |
| `CF_PAGES_PROJECT` | GitHub **Variable**(選填) | Pages 專案名 |

> 機密請直接加在 GitHub Secrets,**不要貼在對話裡**。
