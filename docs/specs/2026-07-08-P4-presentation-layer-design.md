# P4 呈現層 design（匯出 DAG + Next.js/Vercel 儀表板 + MCP server）

> **上游**：[P4 brief](2026-07-08-P4-presentation-layer-brief.md) + [NORTH_STAR](../architecture/NORTH_STAR.md)「呈現層與部署拓撲」段 + MCP add-on。**消費（勿改）**：P1 design §6a Gold 5 表、P2 design §13 ML 五項、P3 design §7 `gold_ptt_board_daily`——共 11 表 additive 合約。
> **精確度**：本 design 依 CLAUDE.md「Fable 5 design 精確度契約（8 條）」產出，逐條對照見 §11。
> **一句話**：P4 = 全專案唯一上雲的門面——平台端一支匯出 DAG 把 11 表預聚合成 committed 靜態 JSON，`frontend/`（Next.js 16 純靜態匯出）部署 Vercel 讀它，FastMCP server 部署 Prefect Horizon 讀同一份公開 JSON 供遠端 Claude 直查；平台本體不部署，誠實敘事烙在每一頁。
> 產出日期：2026-07-08。plan 延後（本階段只出 spec）。

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證來源 |
|---|---|---|
| Next.js | **16.2.x**（context7 `/vercel/next.js` 版本列表最新 16.2 線；App Router + `output: 'export'` 靜態匯出，`next export` 已於 v14 移除、v13.4 起 App Router 支援靜態匯出） | context7 |
| React | 19.x（隨 create-next-app 16 一併鎖定） | 同上 |
| Recharts | **3.3.0**（context7 `/recharts/recharts` 最新版本標籤） | context7 |
| TypeScript / Node | TS 5.x（create-next-app 預設）；**Node 22 LTS**（本地 + Vercel build image 同版） | — |
| fastmcp（Python） | **3.2.x**（context7 `/prefecthq/fastmcp` 最新 v3.2.4；`mcp.run(transport="http")`、`@mcp.tool` 型別註記自動出 schema、部署面現名 **Prefect Horizon**（原 FastMCP Cloud），entrypoint `file.py:mcp`、URL 形如 `https://<name>.fastmcp.app/mcp`、push main 自動重佈） | context7 |
| httpx | 平台既用版本（P1 ingest 已 pin），MCP server 複用 | 既有 |
| Python | 3.12（對齊平台全域） | 既有 |

> npm 生態確切 minor/patch 由 plan 時 `npx create-next-app@latest` 的 lockfile 定案（§10B 實查 4）；**major 線（Next 16 / React 19 / Recharts 3）此處鎖定不再議**。

---

## 1. 三個關鍵決策（先拍板，細節在各簇）

### ① 匯出目標 = **committed 靜態 JSON**（DAG 落 MinIO `exports` bucket，host 同步進 `frontend/public/data/` 成 git 正本）

三案收斂：
- **(i) committed 靜態檔 ✅ 採用**——零外部依賴、零常駐、與「前端純讀預產資料」拓撲鐵律同構；預聚合後全包 <15MB，git 完全裝得下（「大表不雅」由 §3 預聚合解掉，不是換儲存解）。
- (ii) 免費 Neon ❌ 淘汰——多一個外部服務依賴 + 前端/MCP 要帶憑證 + 免費層閒置自動暫停（demo 當場冷啟動打臉）+ 違「DB 只 Postgres 一顆」的工具紀律精神（第二顆常駐 DB）。
- (iii) 物件儲存公開讀 ❌ 淘汰——本地 MinIO 不對公網（平台不部署鐵律）；雲 bucket 則引入唯一一個雲儲存帳號與成本面，而資料本來就要進前端，繞一圈無收益。

**誰把檔案 commit 進 git**：k8s 內**不持有 GitHub 寫權杖**（憑證擴散＋GitOps 自寫自觸發環路，兩個都是反模式）。收斂為：DAG 寫 MinIO → host 跑 `make export-sync` 拉 `latest/` 進 `frontend/public/data/` → **人審 diff → commit → push**。這與「平台本地按需跑」的誠實敘事一致：資料更新頻率＝平台開機跑一輪的頻率，網站上的每一版資料都有 git 歷史可考。

### ② 前端 = **Next.js 16 App Router + `output: 'export'` 純靜態**（build 時 fs 讀 committed JSON）

Server Components 在 `next build` 時執行（context7 查證：靜態匯出下 RSC 於 build 期渲染成靜態 HTML + 客戶端導航 payload）——`src/lib/data.ts` 用 `fs.readFile` 讀 `public/data/*.json`，資料烙進 HTML；圖表為 `'use client'` 元件收 props。`output: 'export'` 是拓撲鐵律的最強實作：**產物只有 `out/` 靜態檔，物理上不存在 runtime server，可以打 k8s 的程式碼寫不出來**。runtime fetch 案淘汰（引入 client 載入態與失效面，資料明明 build 時就在手上）。

### ③ MCP server = **FastMCP 3 部署 Prefect Horizon（原 FastMCP Cloud），資料源 = 已部署前端的公開 `/data/*.json`**

真拓撲決策收斂為 **(ii) serverless 上雲**：`frontend/public/data/` 部署後即是公開 HTTPS JSON——MCP server 用 httpx 讀**同一份合約檔**，與前端喝同一口井，零第二資料通道。跑在 Prefect Horizon（免費個人層、GitHub repo 直連、entrypoint `mcp-server/server.py:mcp`、push main 自動重佈）→ 得到 `https://<name>.fastmcp.app/mcp`，**遠端 Claude 真的連得上** = 差異化亮點成立。本地開發/面試現場用同一份碼跑 stdio（`fastmcp run mcp-server/server.py`）。不架任何常駐後端（成本紀律）；Horizon 若不可用，降級為本地 stdio-only，程式碼零改動（§10B 實查 3）。

---

## 2. 總體形狀

### 資料流（單向，一條龍）

```
[本地 k8s] Postgres gold.* / ml.*（11 表 additive 合約：P1 §6a ×5 + P2 §13 ×5 + P3 gold_ptt_board_daily）
     │  Airflow DAG export_frontend_data（@daily 05:00 UTC + 手動；PythonOperator，跑在 Airflow image）
     ▼
MinIO s3://exports/frontend/{latest/, dt=YYYY-MM-DD/}   （10 資料檔 + meta.json，冪等覆寫）
     │  make export-sync（host：boto3 經 minio-api.localtest.me 拉 latest/，P2 §3.6 既有 ingress）
     ▼
frontend/public/data/*.json（git 正本；人審 diff → commit → push）
     │  Vercel（root dir = frontend/；ignoreCommand 使非 frontend/ 變更不觸發 build）
     ▼
https://trend-intelligence.vercel.app（next build 產 out/ 純靜態；/data/*.json 同站公開可讀）
     │                                        ▲
     └─→ 瀏覽者（8 個面板頁）                  │ httpx GET + 15min TTL cache
                     Prefect Horizon 上的 FastMCP server（https://<name>.fastmcp.app/mcp）
```

**更新節奏**：平台按需跑（`make cluster-up`）→ DAG 自動或手動匯出 → `export-sync` + push → Vercel 自動 rebuild（分鐘級）→ MCP 下一次 cache 過期即讀到新資料。全程無任何元件 runtime 依賴本地 k8s。

### 目錄結構（新增三塊；既有五層目錄零侵入，僅 additive）

```
frontend/                              # ★ 自足 Next.js app（Vercel root dir；cd frontend && npm i && npm run build 獨立成立）
├── package.json  next.config.ts  tsconfig.json  vercel.json  eslint.config.mjs
├── public/
│   ├── data/                          # 匯出檔 git 正本（export-sync 整包覆寫；§4 檔案合約）
│   └── architecture/                  # 架構圖 SVG + ArgoCD/Grafana/Airflow/MLflow 截圖 + 終端 GIF
├── scripts/check-data.mjs             # 資料合約守門（CI + build 前跑）
└── src/
    ├── app/                           # 8 頁（§5 頁面清單）
    ├── components/                    # RegionTabs / KpiTile / DataTable / TitleCompare / RagCard / Heatmap / FreshnessBanner
    │   └── charts/                    # 'use client' Recharts 包裝（§5 圖表對應表）
    └── lib/                           # data.ts（fs loader）/ types.ts（合約 TS 鏡像）/ format.ts
mcp-server/                            # ★ FastMCP 獨立小服務（Python；不與 frontend/ 混居——Node app 保持自足）
│                                      #   目錄名帶連字號：叫 `mcp/` 會 shadow Python `mcp` SDK 套件 import（gotcha）
├── server.py  settings.py  requirements.txt
└── tests/（fixtures/*.json + test_tools.py）
orchestration/
├── exporter/                          # ★ Python 套件，裝進 Airflow image（同 yt_ingest 模式，無自己的部署）
│   ├── pyproject.toml
│   ├── src/exporter/{datasets.py, export.py, meta.py}
│   └── tests/
└── airflow/dags/export_frontend_data.py
lakehouse/minio/k8s/                   # bucket-init Job 的 mc mb 清單 += `exports`（additive，P2 §3.6 同款）
Makefile                               # += export-trigger / export-sync / present-verify
scripts/{export_sync.py, verify-present.sh}
```

---

## 3. P4-1 平台端匯出 DAG（決定）

| 開放問題 | 決定 |
|---|---|
| DAG | `export_frontend_data`：`schedule="0 5 * * *"`（UTC；排在 P2 各 @daily ML DAG 與 P3 02:30 之後）、`catchup=False`、`max_active_runs=1`、`retries=2`+exponential backoff（沿用 P1 §7 排程慣例）。**上游就緒判定用「新鮮度檢查 task」而非跨 DAG sensor**：叢集按需開機、各 DAG 完成時刻漂移，sensor 鏈脆；freshness gate 直接驗資料本身。 |
| 執行形態 | **PythonOperator（KubernetesExecutor pod，跑 Airflow image）**，不開 KPO、不建新 image——預聚合後每檔千列級，psycopg2 讀 + json 寫 + boto3 上傳，Airflow image 依賴（psycopg2/boto3）P1 已備齊。exporter 碼以 `orchestration/exporter/` 套件裝進 Airflow image（同 `yt_ingest` 模式，改碼走 airflow-ci image 迴圈；datasets 定義改動即 DAG 行為改動，可測）。 |
| 連線/權限 | 讀庫用既有 `LAKEHOUSE_PG_DSN`（`pipeline_writer`）；寫 MinIO 用既有 `minio-root` Secret `envFrom`（AWS 標準 key 名，P1 §8 env 合約，零新 Secret）。`pipeline_writer` 對 `ml` schema 的 SELECT 為 §10B 實查 1（預設已含；缺則 additive `GRANT`）。 |
| 落點與冪等 | `s3://exports/frontend/latest/<file>.json`（覆寫 = 冪等，前端/同步只認 latest）＋ `s3://exports/frontend/dt=YYYY-MM-DD/<file>.json`（每日留底可回看）。bucket `exports` 進 bucket-init 清單（additive）。 |
| 格式 | **minified JSON（UTF-8、欄名 = DB 欄名 snake_case 原樣、timestamp 一律 UTC ISO-8601 字串、numeric 出為 number）**。淘汰 CSV（型別/巢狀丟失，前端還要 parse 庫）與 Parquet（瀏覽器/Node 讀取要拖 wasm 或 duckdb 級依賴＝為格式加基建，違工具紀律精神）。NORTH_STAR「CSV/Parquet」字樣是佔位，brief 已明文重開此題，此處定案 JSON。 |
| ML 表缺席容忍 | P2 未跑/表不存在 → 該 dataset **仍寫檔**（`{"rows": []}`）並在 meta.json 標 `status: "absent"`；前端面板顯示「此資料尚未由平台產出」而非 build 失敗。**P4 因此可在僅 P1 完成時就先上線**（誠實展示產線現況），P2/P3 跑起來後資料自然補齊。 |

### DAG 結構

```
check_freshness（PythonOperator：silver.video_snapshots max(ingested_at) < 26h 且 count>0，
      │          否則 fail——匯陳舊資料上網站比匯不出更糟；gold 5 表 count>0）
      ▼
export_datasets（PythonOperator：迭代 exporter.datasets.DATASETS 清單
      │          → 逐個跑 SQL → 轉 JSON → 上傳 latest/ + dt=/；ML 缺表走 absent 路徑）
      ▼
write_meta（PythonOperator：彙整各 dataset rows/status/新鮮度 → meta.json 上傳）
      ▼
validate_exports（PythonOperator：回讀 latest/ 全部 11 檔——JSON 可解析、必要 key 在、
                  非 absent 者 rows>0、單檔 ≤3MB、全包 ≤15MB，任一違反 = task fail = 告警）
```

### 資料集清單（10 資料檔；預聚合/裁切在 SQL 層做完，前端零運算）

| 檔案 | 來源表（合約） | 視窗/裁切（拍板） | 內容形狀 | 預估列數 |
|---|---|---|---|---|
| `trending_daily.json` | `gold.gold_trending_daily` | 近 **90** 天、全 8 區 | 全欄平鋪 | ≤720 |
| `category_daily.json` | `gold.gold_category_daily` | 近 **60** 天、全區全類別 | 全欄平鋪 | ~7k |
| `channels.json` | `gold.gold_channel_performance` | **`rank_in_region <= 50`**（每區 top50） | 全欄平鋪 | ≤400 |
| `videos.json` | `gold.gold_video_lifecycle` **LEFT JOIN** `ml.ml_video_predictions` USING (video_id, region) | 每區 **top100** by `latest_views` | lifecycle 全欄 + `p_doubled_24h`/`predicted_label`/`model_version`/`scored_at`（無預測 = null） | ≤800 |
| `velocity_top.json` | `gold.gold_video_velocity_hourly`（篩自 lifecycle 每區 top10 by `peak_delta_views_per_hour`） | 每影片**前 72 個快照** | 巢狀：`{region → [{video_id,title,channel_title, series:[{captured_at,views,delta_views_per_hour,velocity_rank}]}]}` | ≤5,760 點 |
| `sentiment_videos.json` | `gold.gold_video_sentiment` JOIN lifecycle（補 title/channel_title） | 每區 **top100** by `scored_comments` | mart 全欄 + 標題欄 | ≤800 |
| `sentiment_daily.json` | `ml.ml_comment_sentiment` **匯出時 SQL 聚合** | `region × scored_at::date × label` 計數（明細百萬列**不出庫**——brief 點名的預聚合對象） | `{region,date,positive,neutral,negative}` | 小 |
| `rag_showcase.json` | `ml.ml_rag_showcase` | 全表（策展批次，數十列） | 全欄（含 sources/provider/token_usage/latency_ms——LLMOps 佐證數據本身是賣點） | ~數十 |
| `title_examples.json` | `ml.ml_title_examples` | 全表 | 全欄（tuned/base 兩組供並排） | ~60 |
| `ptt_board_daily.json` | `gold.gold_ptt_board_daily` | 近 **90** 天 | 全欄平鋪 | ~數百 |

`gold_video_velocity_hourly` 與 `ml_comment_sentiment` 兩張大表**只以聚合/裁切形態出庫**；其餘 9 表窗口/名次裁切。11 張合約表全數被消費、零繞道（`ml_video_predictions` 併入 `videos.json` 仍是走合約表 JOIN）。

### 統一檔案信封（每個資料檔同構）

```json
{ "dataset": "trending_daily", "generated_at": "<UTC ISO>", "source_tables": ["gold.gold_trending_daily"],
  "status": "ok", "row_count": 720, "rows": [ { …欄名=DB 欄名… } ] }
```

---

## 4. 匯出檔案合約（P4 內部的「§6a」；穩定性政策 additive）

- **合約正本** = `orchestration/exporter/src/exporter/datasets.py`（每個 dataset 一個宣告式條目：name / sql / caps / output file，docstring 帶欄位說明）；前端 `frontend/src/lib/types.ts` 是它的 TS 鏡像，MCP `mcp-server/server.py` 是它的工具化投影——**三處欄位一致性由 §9 的 check-data / pytest 守門**。`ml/exports/` README（P2 既建）增補一行指向本節與 datasets.py，不另立第二份 schema 文件。
- **穩定性政策**（同 P1 §6a）：檔名、信封 key、`rows[]` 既有欄位是對前端與 MCP 的介面承諾——變更只允許加欄/加檔；改名/刪欄/改語意須開 `_v2` 檔名並記錄於本 spec。
- `meta.json` schema：

```json
{ "exported_at": "<UTC ISO>", "export_run_id": "<airflow run_id>",
  "regions": ["TW","JP","KR","HK","US","GB","SG","AU"],
  "source_freshness": { "silver_max_ingested_at": "<UTC ISO>", "silver_row_count": 123456 },
  "datasets": [ { "name": "trending_daily", "file": "trending_daily.json", "rows": 720,
                  "status": "ok", "source_tables": ["gold.gold_trending_daily"], "window_days": 90 } ] }
```

`regions` 由 exporter 讀 `dags/config/pipeline.yaml`（P1 單一真源）寫入——前端與 MCP 的區域清單**都吃 meta.json**，不各自硬編碼（加區 = 改一行 YAML，三端跟著動）。

---

## 5. P4-2 `frontend/` Next.js 儀表板（決定）

| 開放問題 | 決定 |
|---|---|
| 範式 | App Router + RSC，`next.config.ts`：`output: 'export'`、`images: { unoptimized: true }`（靜態匯出無 image optimizer，圖片本就是本地資產）。無 middleware、無 route handler、無 server action——`output:'export'` 下這些直接 build fail = 拓撲鐵律的編譯期守門。 |
| 讀檔方式 | **build-time fs 讀**：`src/lib/data.ts` 的 `loadDataset<T>(name)`（`server-only` 標記 + `fs.readFile(path.join(process.cwd(), 'public/data', file))` + 信封斷言，檔缺/壞 = build fail）。頁面 RSC await 它、把裁好的 props 傳給 client 圖表元件。 |
| 圖表庫 | **Recharts 3.3.0**（React 原生宣告式、免費 MIT、`'use client'` 元件即用；面板圖型全在其射程）。heatmap Recharts 無原生——PTT 頁用**自製 CSS grid heatmap**（一個 `<div>` 網格上色，不為一張圖加庫）。 |
| 樣式 | **CSS Modules + `globals.css` design tokens（深色單主題）**，零 CSS 框架——YAGNI（brief 明文「先乾淨可讀」），也免去 Tailwind 4 這個額外快速演進依賴的查證/升級面。字體用系統字疊（`system-ui`），不掛 webfont。 |
| region 切換 | **client-side filter**（`RegionTabs` client 元件 `useState`，預設 `TW`；資料檔本就含全 8 區）。淘汰 `/[region]/` 動態路由——8 倍頁面數換不到任何東西，靜態匯出下 searchParams 也不可用於 server。 |
| 語言 | 介面**繁體中文**、技術名詞英文原文（台灣求職市場；與 repo 文件語言一致）。不裝 i18n。 |
| 更新觸發 | git push（含 `frontend/public/data/` 變更）→ Vercel 自動 build。無 webhook/cron rebuild——資料只在人 push 時變，天然對齊。 |
| 平台敘事頁 | `/architecture` 專頁（見頁面表）＋**每頁 footer `FreshnessBanner`**（RSC 讀 meta.json）：「資料由本地 Kubernetes 平台批次產出，匯出於 {exported_at}——本站為純靜態展示，平台本體不對公網」＝誠實敘事烙在每一頁。 |

### 頁面清單（`src/app/`，8 頁全靜態）

| 路由 | 面板 | 吃的資料檔 | 主要視覺 |
|---|---|---|---|
| `/` 總覽 | KPI tiles（最新日 total_videos/total_views/avg_engagement）＋各區當日摘要卡＋「最高爆紅機率影片」「情緒最負面影片」兩張 highlight 卡 | trending_daily, videos, sentiment_videos, meta | KpiTile + 迷你 AreaChart |
| `/trends` 趨勢 | 觀看/影片數 90 天時序（region 切換）＋分類佔比堆疊＋分類排行 | trending_daily, category_daily | LineChart、stacked AreaChart、BarChart |
| `/channels` 頻道 | top50 排行表（可排序）＋ videos_trended × total_views 散點 | channels | DataTable + ScatterChart |
| `/videos` 影片與預測 | 生命週期表（hours_on_chart/total_views_gained）＋ velocity top10 sparkline ＋ **`p_doubled_24h` 爆紅預測 badge 欄**（含 model_version tooltip） | videos, velocity_top | DataTable + sparkline LineChart |
| `/sentiment` 觀眾情緒 | 影片 sentiment_score 分歧條（正右負左）＋日情緒堆疊面積＋最負面留言影片列表 | sentiment_videos, sentiment_daily | diverging BarChart、stacked AreaChart |
| `/ai-lab` AI Lab | RAG 問答卡片牆（question/answer/sources 摺疊/provider/latency/token）＋**爆紅標題 before/after 並排**（同 topic 的 base vs tuned 左右對照，`TitleCompare`） | rag_showcase, title_examples | 卡片 UI（無圖表） |
| `/ptt` PTT 熱度 | 看板×日 heatmap（articles_count 上色）＋爆文數/推噓趨勢 | ptt_board_daily | CSS grid Heatmap + LineChart |
| `/architecture` 平台架構 | 架構圖 SVG（P0–P4 全景）＋截圖牆（ArgoCD app tree/Grafana/Airflow graph/MLflow runs/kind 終端 GIF）＋誠實敘事文＋tech stack 清單＋repo/design docs 連結＋ **MCP 連線指引**（Horizon URL + 一行設定範例） | 靜態資產 | — |

靜態資產紀律：截圖 PNG 單張 ≤300KB、GIF ≤3MB（`check-data.mjs` 順手掃 `public/` 總量 ≤25MB，防 repo 肥大）。

---

## 6. Vercel 設定（決定）

| 設定 | 值 |
|---|---|
| 專案名 / URL | `trend-intelligence` → `https://trend-intelligence.vercel.app`（名稱被占則 `trend-intelligence-platform`；定案值回填 §7 `DATA_BASE_URL` 預設——§10B 實查 2） |
| Root Directory | **`frontend/`**（dashboard 設定；"Include files outside root directory" 保持關——強制自足性） |
| Framework Preset | Next.js（自動偵測）；Build Command / Output 用 preset 預設（`output:'export'` 由 preset 原生處理；異常備援 = 顯式 Output Directory `out`，§10B 實查 5） |
| Node | 22.x |
| 環境變數 | **無**（全靜態、零 secret——沒有能洩漏的東西） |
| 跳過無關 build | `frontend/vercel.json`：`{ "ignoreCommand": "git diff --quiet HEAD^ HEAD -- ." }`（ignoreCommand 於 Root Directory 下執行——平台側 commit 不觸發前端 build；context7 Vercel monorepo 文件查證 Ignored Build Step 機制） |
| Git 整合 | production branch = `main`；PR 自動 preview deployment（改版面先看 preview 再進 main，白拿的 review 流程） |

---

## 7. P4-3 MCP server（FastMCP；決定）

| 開放問題 | 決定 |
|---|---|
| 跑哪裡 | **Prefect Horizon（原 FastMCP Cloud）**：GitHub 帳號登入 → 選本 repo → entrypoint **`mcp-server/server.py:mcp`** → 得 `https://<name>.fastmcp.app/mcp`，push main 自動重佈（context7 查證流程）。**遠端 Claude 可直連** = 亮點；同碼本地 `fastmcp run mcp-server/server.py`（stdio）供 Claude Code/Desktop demo（`claude mcp add`）。零常駐自架後端。 |
| 與前端關係 | **獨立小服務 `mcp-server/`**（Python 不混進 Node app，frontend/ 自足性不破）。目錄名**必須帶連字號**：叫 `mcp/` 會 shadow FastMCP 所依賴的 Python `mcp` SDK 套件 import（gotcha，寫進 README）。 |
| 讀資料 | httpx GET `{DATA_BASE_URL}/data/<file>.json`（`DATA_BASE_URL` env，預設 = §6 生產 URL）＋ **in-process TTL cache 15 分鐘**（dict + monotonic 時戳，資料日更、無需更花俏）。與前端喝同一份合約檔——不開第二資料通道、不碰任何 DB/k8s。 |
| auth | **公開唯讀、不開 auth**——工具只回網站上本就公開的靜態資料，無秘密可護；加 auth = 加摩擦零收益。 |
| 依賴 | `mcp-server/requirements.txt`：`fastmcp>=3.2,<4`、`httpx`（Horizon 自動偵測依賴，context7 查證）。 |
| region 參數 | 型別 `str`（非硬編碼 Literal enum）——**runtime 對 meta.json 的 `regions` 驗證**，錯誤丟 `ToolError` 附合法清單；docstring 列出 8 區。單一真源在 pipeline.yaml → meta.json，加區不改 MCP 碼。 |

### 工具清單（10 支；`@mcp.tool`，型別註記自動生 JSON schema——context7 查證 FastMCP 3 行為）

| 工具 | 參數（型別/預設） | 回傳 | 資料檔 |
|---|---|---|---|
| `list_datasets` | — | meta.json 全文（探索入口：有哪些資料、多新、幾列） | meta |
| `get_trending` | `region: str = "TW"`, `days: int = 30` | 每日趨勢彙總列 | trending_daily |
| `get_category_breakdown` | `region: str = "TW"`, `days: int = 30`, `top: int = 10` | 分類熱度＋view_share_pct | category_daily |
| `get_channel_leaderboard` | `region: str = "TW"`, `limit: int = 10` | 頻道排行 | channels |
| `get_top_videos` | `region: str = "TW"`, `sort: Literal["p_doubled_24h","latest_views","total_views_gained"] = "p_doubled_24h"`, `limit: int = 10` | 影片生命週期＋爆紅預測 | videos |
| `get_video_velocity` | `region: str = "TW"`, `video_id: str \| None = None` | velocity top10 時序（指定 video_id 則單支） | velocity_top |
| `get_audience_sentiment` | `region: str = "TW"`, `limit: int = 10` | 影片級情緒排行＋日情緒分佈摘要 | sentiment_videos, sentiment_daily |
| `get_viral_title_examples` | `topic_keyword: str \| None = None` | tuned/base 標題配對（LoRA 成果） | title_examples |
| `get_ptt_heat` | `board: str \| None = None`, `days: int = 30` | 看板×日熱度 | ptt_board_daily |
| `get_rag_showcase` | `keyword: str \| None = None` | 預產 RAG 問答範例（關鍵字過濾 question/answer） | rag_showcase |

**誠實紀律**：`get_rag_showcase` docstring 明講「回傳的是平台離線 RAG pipeline 預先批次產生的問答範例，非即時檢索」——不假裝線上 RAG（拓撲鐵律 + README 誠實章對齊）。`status:"absent"` 的 dataset，對應工具回明確訊息「該資料尚未由平台產出」而非空列表裝死。

---

## 8. CI / GitOps 接入（沿用 P0/P1 模式不自創）

| workflow | 觸發 paths | 內容 | image / bump |
|---|---|---|---|
| `frontend-ci.yaml`（新） | `frontend/**` | `npm ci` → `npm run lint` → `node scripts/check-data.mjs` → `npm run build` | **無**（部署歸 Vercel，CI 只當 merge 守門） |
| `mcp-ci.yaml`（新） | `mcp-server/**` | ruff + pytest | **無**（部署歸 Horizon） |
| `airflow-ci.yaml`（既有，改） | 觸發 paths += `orchestration/exporter/**`；test job += exporter pytest | exporter 進 Airflow image（Dockerfile 加一行 install） | 既有 `…/airflow` 迴圈不變 |

`pr-checks.yaml` 擴充：對上述 paths 跑對應 test job（不 build image）。無新 ArgoCD Application、無新 sync-wave——P4 平台側只有一條 DAG（git-sync 送達）＋一個套件（進既有 image）＋一個 bucket 清單項，GitOps 面零新資源。

---

## 9. 測試策略（每步可測）

| 層 | 測試 | 跑在 |
|---|---|---|
| exporter 單元 | dataset SQL 對 fixture Postgres 的黃金測試（對齊 P2 label-SQL 測試模式）：窗口裁切、top-N、velocity 巢狀形狀、sentiment 聚合計數、**ML 缺表 → absent 信封路徑**、單檔大小上限斷言、meta 完整性（11 條目、regions 來自 pipeline.yaml） | airflow-ci |
| DAG | DagBag import 零錯誤、任務鏈斷言（freshness→export→meta→validate）、`catchup=False`/`max_active_runs=1` 守門（既有模式照抄） | airflow-ci |
| 前端資料合約 | `scripts/check-data.mjs`：11 檔存在、JSON 可解析、信封 key 齊、非 absent 者 rows>0、欄位含 types.ts 要求的必要欄、單檔 ≤3MB、`public/` 總量 ≤25MB | frontend-ci + 本地 prebuild |
| 前端 build smoke | `next build` 綠（`output:'export'` 下同時是拓撲守門：任何 server 功能直接 fail）＋ ESLint | frontend-ci |
| 拓撲守門 | `check-data.mjs` 加一條：grep `frontend/src/` 不得出現 `.svc`、`localtest.me`、`host.docker.internal` 字串（防手滑接內網端點） | frontend-ci |
| MCP 單元 | pytest + fixtures JSON（monkeypatch fetch 層）：10 工具 list 斷言、每工具形狀斷言、region 驗證錯誤路徑、TTL cache 命中、absent dataset 訊息路徑 | mcp-ci |
| MCP 煙囪 | in-memory `Client(mcp)` 連 server 實例 `list_tools` == 10 並實呼 `get_trending`（FastMCP 3 client 直連 server 物件，免起網路） | mcp-ci |

---

## 10. 端到端驗收清單 + plan 前需實查

### A. `make present-verify`（`scripts/verify-present.sh`；前置 = P1 `make pipeline-verify` 綠、gold 有數日資料；P2/P3 可缺席——absent 路徑照驗）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | 觸發 `export_frontend_data` | DAG 綠；`mc ls exports/frontend/latest/` = 11 檔 |
| 2 | `make export-sync` | `frontend/public/data/` 11 檔更新；git diff 可審 |
| 3 | 前端自足 build | `cd frontend && npm ci && npm run lint && node scripts/check-data.mjs && npm run build` 全綠、產出 `out/` |
| 4 | 本地瀏覽 | `npx serve out` → 8 頁可點、region 切換動、`/ai-lab` 標題 before/after 並排呈現、`/videos` 有預測 badge（或 absent 提示） |
| 5 | Vercel 生產 | push 後公網 URL 8 頁 200；`GET /data/meta.json` 200 |
| 6 | ignoreCommand | 推一個只動平台側的 commit → Vercel 顯示 build skipped |
| 7 | MCP 本地 | `fastmcp run mcp-server/server.py` + client `list_tools` = 10；`get_trending("TW")` 回非空 rows |
| 8 | MCP 雲端 | Horizon URL `/mcp` 由 Claude 連線 → 工具呼叫回與網站一致的真資料 |
| 9 | 誠實敘事 | `/architecture` 有架構圖＋截圖牆；每頁 footer 有 `exported_at`；`get_rag_showcase` docstring 含「預產範例」字樣 |
| 10 | 拓撲斷言 | `out/` 內 grep 無任何 `.svc`/`localtest.me` 端點字串；`frontend/` 無 env secret |

### B. plan 前需實查（設計已收斂，以下為落地校準點，皆帶預設傾向）

1. **`pipeline_writer` 對 `ml` schema 的 SELECT**——預設 P2 §3.4 grants 已涵蓋；缺則在 P2 init SQL additive 加 `GRANT USAGE ON SCHEMA ml` + `GRANT SELECT ON ALL TABLES`（含 default privileges）。
2. **Vercel 專案名可用性**——預設 `trend-intelligence`；被占改 `trend-intelligence-platform`，並回填 `mcp-server/settings.py` 的 `DATA_BASE_URL` 預設值。
3. **Prefect Horizon 免費個人層現況**——context7 文件已示 entrypoint/自動重佈流程；若條款變更不可免費用，**降級為本地 stdio-only demo，程式碼零改動**，只少「遠端可連」亮點（架構誠實頁改寫一句）。
4. **create-next-app@latest 確切 minor**——major 16 已鎖，lockfile 定案 minor/patch。
5. **Vercel preset 對 `output:'export'` 的行為**——預設 preset 自動處理；異常則顯式設 Output Directory = `out`（5 分鐘校準）。

---

## 11. 落地後校驗（design 自檢摘要）

- **精確度契約 8 條對照**：①brief 全部開放問題收斂為單一決定，零 TBD/兩案並陳（匯出目標=committed JSON、格式=JSON、預聚合=velocity/sentiment 兩大表＋全表窗口裁切、讀檔=build-time fs、MCP=Horizon 上雲、Vercel root dir=frontend/）；實查僅 §10B 五點且皆帶預設。②版本 pin §0 全 context7 查證（Next 16.2/Recharts 3.3.0/fastmcp 3.2/Vercel 設定機制）。③資料契約欄位級：§3 資料集表 + §3 統一信封 + §4 meta schema + 上游 11 表原樣引用（P1 §6a/P2 §13/P3 §7 勿改）。④部署形狀具體：DAG 四 task 鏈、檔案佈局、Vercel 逐項設定、Horizon entrypoint、目錄樹到檔名。⑤沿用慣例：exporter=yt_ingest 套件模式、DAG 排程=P1 §7 慣例、Secret=P1 §8 既有兩把零新增、bucket-init=P2 §3.6 同款、CI=hello-ci 模式。⑥進化非複刻：不適用（P4 無取材原碼）；對 NORTH_STAR「CSV/Parquet」佔位字樣的偏離已明文論證（§3 格式）。⑦硬約束：拓撲鐵律以 `output:'export'` 編譯期強制＋grep 守門；frontend/ 自足（驗收 #3）；11 表合約全消費不繞道；誠實敘事（§5 FreshnessBanner/§7 誠實紀律/驗收 #9）；成本紀律（靜態 + 兩個免費託管、零常駐、零雲憑證）。⑧每步可測：§9 全層測試 + §10A 十步可實跑清單。
- **邊界**：P4 對上游只讀不寫；上游缺欄回各階段 additive 加欄，不在 P4 私接；P5（安全掃描/README 打磨）不在本 spec。
