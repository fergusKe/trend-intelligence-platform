# GA4 Ingestion 地基（P6/P7/即時 三垂直共用前置）— Fable 5 design brief（GA4 擴充第 1 波／地基）

> **交付流程**：讀本 brief +「Fable 5 design 精確度契約 8 條」（在 [`CLAUDE.md`](../../CLAUDE.md) §Fable 5 design 精確度契約）+ [`NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段 + **P1 design §6a Gold 5 表合約 + §5 Silver→Postgres loader**（`2026-07-08-P1-data-pipeline-design.md`）+ **P1 留言 design 的 Silver 合約**（`2026-07-08-P1-comments-ingest-design.md`）+ **P4 匯出合約**（`2026-07-08-P4-presentation-layer-design.md` §3）+ 下方「已查到的事實」→ `superpowers:brainstorming`（**非互動、開放問題全收斂**）→ 產出 `docs/specs/2026-07-09-P6-ga4-ingestion-foundation-design.md`。**只出 design。**
> **git 紀律**：只寫 design markdown、不跑 git、不動 code。**語言**：繁體中文。

---

## 定位

這是 GA4 擴充的**地基 spec**（像 Looma Spec 1 之於後續 spec）：把公開 GA4 電商事件資料從 BigQuery **全漏斗萃取**，落成 **P6 推薦 / P7 DMP / 即時特徵層三者共用的 GA4 事件與 item 資料合約**。**先鎖定這份的欄位級合約，wave-2 三份（P6/P7/即時）才有穩定介面可依賴。**

**為什麼需要它**：推薦要「真使用者 × 商品 × 互動」三角，YouTube/PTT 只有商品＋聚合、無真使用者。GA4 電商事件（`user_pseudo_id` ＋ view/cart/purchase）帶入真三角。這是 `llm-workshop/ga-insight` 的資料形狀。

**這是本 repo 第一個 GCP Service Account 憑證接法**——P1 主幹是 YouTube API（httpx + API key），無 BQ/SA 慣例，本 spec 新訂。

## 已鎖定決策（勿翻案）

1. **資料源 = 公開 `bigquery-public-data.ga4_obfuscated_sample_ecommerce`**（Google Merchandise Store；事件級、`user_pseudo_id` 穩定、可公開分享）。**不用 area02 真資料**（客戶機密不進公開 portfolio repo；area02 只當 Fergus 求職憑證）。
2. **偷技術不偷資料**：取材 web-agency `services/analytics-api/reference_store/extract_funnel.py`（`:25-57`）的**全漏斗 item_id 萃取邏輯**（`view_item`/`add_to_cart`/`begin_checkout`/`purchase` 都從 `items[]` UNNEST 出 `item_id`，**不像 ga-insight 只萃 purchase** → 稀疏），但**跑在公開 sample 上**。標清「取什麼邏輯 vs 重造哪個工程層」（進化非複刻）。
3. **SA 憑證姿態**：SA JSON **進 k8s Secret 掛成 volume**（非 env——`GOOGLE_APPLICATION_CREDENTIALS` 吃**檔案路徑**）＋ env 指向掛載路徑；沿用 P0/P1 的「**命令式 `kubectl create secret`、文件化、不進 git**」紀律。取材姊妹專案 `ga4-analytics-platform` 的 dbt-bigquery `profiles.yml`（`method: service-account` + keyfile）＋ `extractor.py` BQ→PG UPSERT 模式（**唯讀取材**）。
4. **沿用 P1 medallion 慣例**：Bronze → Silver → Gold；**Silver = Iceberg 正本 + Postgres serving 副本雙寫**（複用 P1 §5 `load_silver_to_postgres` 的 `INSERT … ON CONFLICT … DO UPDATE` + `execute_values` loader 模式，不另造）；dbt **staging（view，`stg_` 前綴）→ marts（table，`gold_` 前綴，schema `gold`）**。
5. **一工一具守**：排程只 Airflow、DB 只 Postgres（＋pgvector 同顆）、匯出走 P4 JSON 合約。**ClickHouse/Redis/Flink 是下游 P6/P7/即時 spec 的事，本地基 spec 一律不引入**（地基只鎖 batch 資料合約）。
6. **公開 sample 只有 daily export、無 `events_intraday_*` 表** → **地基只做 batch daily ingest**；即時場景由即時層 spec 以「標註的事件重放」示範，不在本 spec。
7. **additive-only**：GA4 表用**新命名空間**（`gold_ga4_*` / `silver_ga4_*`），**不碰既有 YouTube Gold 5 表、不改既有粒度**（守 P1 §6a 穩定合約政策）。
8. **拓撲**：前端 Vercel 純靜態、打不到本地 k8s → GA4 產出進前端仍走「批次表 → P4 匯出 DAG → 靜態 JSON」。地基不開任何線上端點。

## 範圍

1. **GA4 BQ 萃取器**（取材 `extract_funnel.py` 邏輯 + `ga4-analytics` extractor 工程層）：讀 `events_YYYYMMDD` 萬用字元（`_TABLE_SUFFIX BETWEEN`），全漏斗 UNNEST——每個電商事件從 `items[]` 展開 `item_id`/`item_name`/`item_category`/`price`/`quantity`，帶 `user_pseudo_id`/`event_name`/`event_timestamp`/`ga_session_id`。UPSERT 進 Postgres（決定性 SQL + 冪等鍵）。附 GA4 `event_params`/`items` 的 UNNEST macro（取材 `get_event_param.sql`）。
2. **Silver GA4 事件表合約（欄位級，穩定合約）**：`silver_ga4_events`——粒度、欄名/型別/PK/分區全列。design 收斂「一列一 event vs 一列一 (event, item) 展開」（見開放問題）。
3. **Gold GA4 marts（供 P6/P7 消費，穩定合約，additive-only）**：至少涵蓋
   - **user × item 互動源**（P6 召回/CF 的輸入矩陣源）；
   - **item 目錄維度**（P6 item 特徵、P7 標籤的 item 側）；
   - **user session / RFM 源**（P7 RFM/LTV/行為標籤的輸入）。
   每張列粒度/欄位級 schema，標「是 P6/P7 介面、只可加欄」。
4. **Airflow DAG**：`ga4_daily`（或類名）DAG 結構——`extract_ga4 → load_to_postgres → dbt_run → dbt_test`，`default_args`/`schedule`/`catchup`/`max_active_runs` 具體值（對齊 P1 DAG 慣例）。
5. **SA Secret 落地**：`make ga4-secrets`（命令式、冪等、文件化不進 git）建立 SA JSON Secret；Helm chart `secret:`/volume values 形狀（掛 volume + `GOOGLE_APPLICATION_CREDENTIALS` env 指向掛載路徑）。
6. **dbt DQ 測試**：GA4 marts 的 singular/generic 測試（PK 唯一、item_id 非空、事件名白名單、金額非負等）。

## 開放問題（design 收斂，禁 TBD）

1. **Silver 粒度**：一列一 event（items 存 JSONB 陣列）vs 一列一 (event, item) 展開列。**傾向 event-item 展開**（推薦與 item 級 OLAP 都要 item 粒度；展開列下游最省事）——design 定並說明取捨。
2. **`user_pseudo_id` 去識別**：sample 已去識別 → **直接用、不再 hash**，誠實揭露「公開去識別資料集」。design 確認。
3. **daily vs intraday**：公開 sample 只有 daily → **地基 batch-only**（收斂），即時交即時層 spec。
4. **item 語意 embedding 落點**：`item_name`/`item_category` → pgvector 向量？**傾向地基只落結構化 catalog、語意 embedding 交 P6 召回 spec**（避免地基膨脹、embedding 屬召回演算法決策）——design 定界線。
5. **Gold GA4 表數量與邊界**：幾張、各粒度、各自服務哪個下游（P6 哪張、P7 哪張）。收斂成明確清單。
6. **與 P1 Gold 5 表的關係**：GA4 表獨立命名空間（`gold_ga4_*`），design 明寫「不 JOIN、不改 YouTube 5 表；兩個資料域並存，僅共用 dbt/Postgres/Airflow 基建」。
7. **BQ 成本/量控**：sample 資料量、萃取窗口（幾天）、避免全表掃描的分區裁剪。design 定預設窗口與 dry-run 位元組上限護欄。

## 設計約束（硬性）

- 精確度契約 8 條自檢。
- 一工一具（本 spec 不碰 ClickHouse/Redis/Flink）；SA 走 k8s Secret 掛 volume 不硬編碼；拓撲（匯出 JSON 為合約、前端打不到 k8s）；additive-only 不改既有 5 表合約；M4 界線（BQ 萃取是 IO-bound、跑 k8s pod 即可，不涉 GPU）。
- 沿用 P1 loader/dbt/secret 慣例、明講對齊哪個既有模式；取材 `ga4-analytics`/`extract_funnel.py` 唯讀、標「取邏輯 vs 重造工程層」界線。
- **前端說明式 UI（跨 P4/P6/P7 要求，本地基先知會不落地）**：地基不做前端頁；但 design 在 Gold marts 的 dbt `description`/欄位註解裡**為下游 Explainer 備好「這是什麼」的資料語意文字**（下游 P6/P7 前端會用 InfoTooltip/ChartCaption/Explainer 呈現），讓下游有現成素材。

## 交付與驗收

- GA4 BQ 萃取器（全漏斗 UNNEST）+ `event_params`/`items` macro。
- `silver_ga4_events` 欄位級 schema（穩定合約標記）。
- Gold GA4 marts 清單 + 各欄位級 schema（標「P6/P7 介面、additive-only」）。
- `ga4_daily` Airflow DAG 形狀（具體 args/schedule）。
- `make ga4-secrets` + Helm volume/Secret values 形狀。
- dbt DQ 測試清單。
- **端到端可跑驗收**：公開 sample 一天資料 → 萃取 → Postgres Gold → 可查出 user×item×event 互動列（非敘述性）。
- plan-前實查點清單（帶預設傾向）。

## 已查到的事實（檔:行，免重探）

- **P1 §6a Gold 5 表穩定合約政策**（`2026-07-08-P1-data-pipeline-design.md:289`）：表名/粒度鍵/既列欄位是對下游承諾，**變更只允許加欄（additive）**，改粒度/刪欄開 `_v2`。→ GA4 表守同政策、且用獨立 `gold_ga4_*` 命名空間不碰 5 表。
- **P1 Silver→Postgres loader**（`P1-...:214`）：獨立 Airflow task `load_silver_to_postgres`（PythonOperator）→ pyiceberg 掃分區 → `psycopg2` `INSERT … ON CONFLICT (…) DO UPDATE`（`execute_values` 批次）。→ GA4 Silver 落 Postgres 複用此 pattern。
- **P1 dbt 佈局**（`P1-...:224,245`）：staging（view，`stg_`）→ marts（table，`gold_`，schema `gold`），`generate_schema_name` 覆寫；profile `lakehouse`/target `k8s`/user `dbt_runner`/threads 4。
- **P1 DAG 慣例**（`P1-...:180,374`）：`retries=3, retry_exponential_backoff=True, max_retry_delay=10m`；主 DAG `schedule="0 * * * *", catchup=False, max_active_runs=1, dagrun_timeout=45m`；輔 DAG `@daily`/手動。
- **P1 secret 落地**（`P1-...:179`）：`make pipeline-secrets` 命令式建 Secret，Helm `secret:` values 陣列注入 pod env（形狀 `{envName, secretName, secretKey}`）。**注意 GA4 SA 是檔案掛 volume、非 env 值**——需擴此形狀成 volume mount。
- **P0 secret 邊界策略**（`2026-07-08-P0-platform-foundation-design.md:483-487`）：P1 起第一個真 secret 用「命令式 `kubectl create secret`（文件化、不進 git）」起步。→ GA4 SA 沿用同起手式。
- **P2 secret 擴充**（`2026-07-08-P2-ml-verticals-design.md:210-219`）：`make ml-secrets` 冪等 apply 多把 Secret；KServe S3 用官方註解形狀。→ GA4 `make ga4-secrets` 對齊此冪等風格。
- **姊妹專案 `ga4-analytics-platform`（唯讀取材）**：
  - `extractor/extractor.py:216-288` `GoldExtractor(pg_conn, bq_client, project_id, dataset)`：`self._bq.query(sql).to_dataframe()` → `psycopg2` UPSERT。**唯一現成的 BQ client → Postgres 慣例**。
  - `dbt/models/staging/stg_ga4_events.sql:25,52`：`events_*` + `_TABLE_SUFFIX BETWEEN …`、`events_intraday_*` 讀法（**公開 sample 無 intraday 表 → 砍該段**）。
  - `dbt/macros/get_event_param.sql:1-14`：`get_string_param`/`get_int_param`/`get_float_param` UNNEST `event_params` 的標準 macro。
  - `dbt/profiles.yml:1-11`：dbt-bigquery `method: service-account, keyfile: env_var(GOOGLE_APPLICATION_CREDENTIALS)`。
- **web-agency 全漏斗萃取邏輯（唯讀取材）**：`services/analytics-api/reference_store/extract_funnel.py:25-57`——`view_item`/`add_to_cart`/`purchase` 都 UNNEST `items[].item_id`（相對 ga-insight `reference/ga-insight/scripts/fetch_full_data.py` 只萃 purchase 的稀疏做法）。
- **本 repo 無既有 BQ client 慣例**：P1 全文唯一提 BigQuery 處是 `P1-...:224`（講 ga4 範本是 BQ 單倉、僅對照）。→ BQ 接法為本 spec 新建。

## 尾註

非互動、進化非複刻（取邏輯不取資料、公開 sample 非 area02）、一工一具（地基不碰三新工具）、SA k8s Secret 掛 volume、additive-only 不動既有合約、拓撲守。只寫 design markdown。開放問題全收斂並附預設傾向。
