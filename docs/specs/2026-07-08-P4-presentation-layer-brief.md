# P4 呈現層（Next.js/Vercel + 匯出 DAG + MCP server）— 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)（「呈現層與部署拓撲」段 + MCP add-on）+ **P1 design §6a Gold 5 表合約** + **P2 design §13 P4 匯出合約（ML 五表）** + **P3 design 的 `gold_ptt_board_daily`** → `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P4-presentation-layer-design.md` →（plan 延後）。
> **精確度**：務必滿足 [`../../CLAUDE.md`](../../CLAUDE.md)「Fable 5 design 精確度契約（8 條）」——開放問題收斂成決定、版本 context7 查證（Next.js/Vercel/圖表庫/FastMCP）、schema/路由/元件級具體、檔案路徑到位。
> **定位**：P4 是**對外門面**——把平台跑出來的資料，變成一個可點連結、會說故事的公開產物。**它是全專案唯一部署上雲的東西（Vercel）**；平台本身不部署。P4 = 三塊：①平台端**匯出 DAG**（Gold+ML 表 → 靜態檔）②`frontend/` **Next.js 儀表板**（讀匯出檔、部署 Vercel）③**MCP server**（把 Gold 開成 agent 工具，加分差異化）。

## 為什麼現在就能出 spec（合約已鎖）
P4 的唯一上游依賴＝**匯出資料 schema**，而它**已經被 P1/P2/P3 的 design 鎖死了**（不需等實作）。這正是我們刻意把「匯出檔＝合約邊界」的目的：前端只依賴 schema、不依賴平台有沒有跑起來。下方「已鎖定的匯出來源」就是完整清單。

## 已鎖定決策（NORTH_STAR + 前階段，勿翻案）
- **monorepo，前端住 `frontend/` 自成一體子目錄**；Vercel root dir = `frontend/`。**不用 Streamlit**。
- **平台不部署、前端上 Vercel**：前端**永遠打不到本地 k8s** 的任何線上端點（KServe/RAG API/MCP-on-k8s 都不行）→ 前端只讀**預先批次產生的匯出檔**（JAMstack 範式）。
- **合約邊界 = 匯出資料檔（CSV/Parquet）**：平台端一支 Airflow DAG 把 Gold + ML 表匯出，前端純讀。
- **MCP server 用 FastMCP** 把 Gold 趨勢資料開成 MCP 工具（讓 Claude 等 agent 直接查我方資料）。

## 已鎖定的匯出來源（P4 匯出 DAG 要收的全部表；欄位級 schema 見各階段 design，勿改契約）
**P1 Gold（§6a，5 表，additive-only）**：`gold_trending_daily` / `gold_channel_performance` / `gold_category_daily` / `gold_video_velocity_hourly` / `gold_video_lifecycle`。
**P2 ML（§13，5 項，additive-only；線上端點明文排除）**：`ml.ml_video_predictions`（影片爆紅預測，PK video_id×region）/ `ml.ml_comment_sentiment`（留言情緒明細，PK comment_id）/ `gold.gold_video_sentiment`（影片情緒聚合 dbt mart，video_id×region）/ `ml.ml_rag_showcase`（RAG 問答範例，含 sources/provider/token_usage/latency）/ `ml.ml_title_examples`（爆紅標題範例，含 tuned+base 對照組）。
**P3 Gold（1 表）**：`gold.gold_ptt_board_daily`（PTT 看板×日熱度）。

## 範圍（簇；Fable 5 定簇內細節與先後）

**P4-1 平台端匯出 DAG（Gold+ML 表 → 靜態檔）**
- 一支 Airflow DAG（`export_frontend_data` 類）把上列 ~11 張表匯出成前端可讀格式，落到匯出目標。掛在既有 dbt/ML DAG 之後（資料新後才匯出）。
- **開放問題（要收斂）**：**匯出目標**——(i) commit 進 repo 的靜態檔（`frontend/public/data/` 或 `frontend/data/`，build 時讀，最簡零基建、但大表進 git 不雅）、(ii) 免費 Neon serving DB（前端/MCP 可即時查、但多一個外部依賴）、(iii) 物件儲存（S3/R2 公開讀）？（傾向：**committed 靜態 Parquet/JSON 給前端 build 時讀**＝最簡、與「前端純讀」一致、零常駐；大表可先聚合/抽樣再匯出。Fable 5 權衡並定。）**格式**（CSV vs Parquet vs 前端友善的 JSON）？哪些表要**預聚合/抽樣**再匯出（velocity_hourly、comment_sentiment 明細可能太大，前端只需聚合）？匯出檔的 schema 描述文件放哪（P2 已建 `ml/exports/` README 級接口文件——對齊）？匯出 job 在 k8s 怎麼跑（KPO？）、頻率？

**P4-2 `frontend/` Next.js 儀表板（部署 Vercel）**
- 自成一體 Next.js app，讀匯出資料渲染多個面板，部署 Vercel（root dir=`frontend/`）。
- **開放問題**：Next.js 版本/範式（App Router + RSC，build 時讀 committed 檔＝SSG 最合拓撲）用 context7 查證；圖表庫選型（輕量、可 SSR、免費）；**頁面/面板清單**（依資料源設計：趨勢榜 trending_daily、頻道表現、分類熱度、影片生命週期＋爆紅預測、觀眾情緒 gold_video_sentiment、RAG 問答 showcase、**爆紅標題 before/after 並排**（tuned vs base）、PTT 看板熱度）；前端怎麼讀匯出檔（build-time import vs runtime fetch）；資料更新節奏（平台重匯出 → 前端 rebuild/redeploy 觸發方式）；「平台架構」怎麼在前端也講一頁（截圖/GIF/架構圖嵌入，因平台不部署——這是 portfolio 的敘事點）；設計系統/RWD 範圍（YAGNI，先乾淨可讀）。

**P4-3 MCP server（FastMCP，加分差異化）**
- 把 Gold 趨勢資料開成 MCP 工具（如 `get_trending(region, date)` / `get_channel_performance` / `query_sentiment(video_id)` 等），讓 Claude 等 agent 直接查我方資料。
- **開放問題（含一個真拓撲決策）**：**MCP server 跑哪裡**——(i) 純本地 demo（host 跑、面試現場/截圖用，同 KServe 端點的定位）、(ii) 部署 serverless（Vercel serverless function / Cloudflare Worker）讀同一份匯出資料＝**真的可被遠端 Claude 連線查**（更亮眼、與「前端上雲」一致）？（傾向 (ii) 若匯出目標可被 serverless 讀到；否則 (i)。）FastMCP 版本 context7 查證；工具清單（哪幾張 Gold 開成工具、參數 schema）；讀資料來源（與 P4-1 匯出目標一致——若 committed 靜態則 MCP 讀檔、若 Neon 則查 DB）；auth（公開只讀 vs token）；MCP 與前端共用 `frontend/` 還是獨立小服務？

**P4-X 驗收**
- **開放問題**：端到端驗收（平台匯出 DAG 產出檔 → 前端本地 `next dev` 讀到、`next build` 過 → Vercel 部署可點 → MCP server `list_tools`/呼叫回真資料）；Vercel 設定（root dir、build command、env）；截圖/GIF 佐證平台端的產線。

## 設計方向約束（硬性，寫進 design）
- **拓撲鐵律**：前端 = 純讀預產靜態；**不得**在前端 runtime 呼叫本地 k8s 任何端點。線上 serving（KServe/RAG）只本地 demo。
- **`frontend/` 自足**：可獨立 `cd frontend && npm i && npm run build`，不依賴 repo 其他部分的 runtime（只依賴匯出檔的 schema）。
- **消費匯出合約不繞道**：P4 只吃上列 11 表的 additive 合約；缺欄回頭走各階段「additive 加欄」，不在 P4 私接平台內部。
- **誠實敘事**：平台不部署 → 前端明講「架構跑在本地 k8s，此處展示其產出＋附架構圖/截圖」，不假裝整套雲上跑（portfolio 誠實，對齊 README 誠實章）。
- **成本紀律（此處反而適用）**：呈現層別堆常駐服務——靜態優先、serverless 次之，不為 MCP 架一個常駐後端。
- **每步可測**：前端有 build smoke、MCP 有 list_tools/呼叫測試、匯出 DAG 有產出斷言。

## 交付與驗收（design 要回答的）
- 尤其拍板：**匯出目標（committed 靜態 / Neon / 物件儲存）**、**匯出格式與哪些表要預聚合**、**前端頁面清單與讀檔方式**、**MCP server 跑哪裡（本地 demo vs serverless 上雲）**、**Vercel 設定**。
- 具體：匯出 DAG 結構與檔案佈局、`frontend/` 目錄結構與頁面/元件、MCP 工具清單與參數 schema、版本 pin、驗收清單。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design。**本階段只出 spec，plan 延後**。P4 吃 P1 Gold + P2 ML + P3 mart 的匯出合約（皆已鎖），與它們解耦（只依賴 schema）。滿足 CLAUDE.md 精確度契約 8 條。
