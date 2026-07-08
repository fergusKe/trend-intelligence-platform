# P6 GA4 ingestion 地基（P6/P7/即時 三垂直共用前置）— Design（Fable 5 產出）

> **狀態**：design 完成，待寫 implementation plan。
> **上游**：[`2026-07-09-P6-ga4-ingestion-foundation-brief.md`](2026-07-09-P6-ga4-ingestion-foundation-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段 + [`2026-07-08-P1-data-pipeline-design.md`](2026-07-08-P1-data-pipeline-design.md)（以下稱「P1 design」）+ [`2026-07-08-P1-comments-ingest-design.md`](2026-07-08-P1-comments-ingest-design.md)（Silver 合約範式）+ [`2026-07-08-P4-presentation-layer-design.md`](2026-07-08-P4-presentation-layer-design.md) §3（匯出合約）+ [`2026-07-08-P0-platform-foundation-design.md`](2026-07-08-P0-platform-foundation-design.md) §7（secret 邊界）+ [`2026-07-08-P2-ml-verticals-design.md`](2026-07-08-P2-ml-verticals-design.md) §3.5（`make ml-secrets` 冪等風格）。brief 已鎖定決策 1–8 全部沿用，未翻案。
> **定位**：**GA4 擴充的地基 spec**——把公開 `bigquery-public-data.ga4_obfuscated_sample_ecommerce` 全漏斗萃取，落成 P6 推薦 / P7 DMP / 即時特徵層三者共用的 GA4 事件與 item 資料合約。**純 additive**：不碰 YouTube Gold 5 表、不改既有粒度、不動主線 DAG 檔。地基不引入 ClickHouse/Redis/Flink、不開任何線上端點。
> **版本查證日**：2026-07-09（google-cloud-bigquery 對 PyPI 當日查證；Airflow chart volume values 形狀對官方 chart docs（context7）查證；其餘沿用 P1 已查證 pin）。

---

## 0. 版本 pin 表

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| google-cloud-bigquery | **3.42.2** | PyPI（2026-07-09） | **本 spec 唯一新 pin**；裝進 Airflow image |
| Airflow chart / image | 1.22.0 / `apache/airflow:3.2.2` | 沿用 P1 §0 | 零升級 |
| pyiceberg | 0.11.1（`[s3fs,sql-postgres]`，P1 既裝） | 沿用 P1 §0 | Silver 建置與 loader 都用它 |
| dbt-postgres | 1.10.2 | 沿用 P1 §0 | GA4 marts 跑在既有 dbt image |
| PostgreSQL / MinIO | 16.14 / P1 pin | 沿用 P1 §0 | 零升級 |

**刻意不引入**：`dbt-bigquery`（§1② 拍板不用——BQ 不是我方 warehouse，只是外部來源）；`pandas`/`db-dtypes`（萃取用 `RowIterator` 逐列迭代即可，不為一天萬列級資料拖 dataframe 依賴——這是對姊妹專案 `to_dataframe()` 模式的刻意簡化）；`google-cloud-bigquery-storage`（Storage Read API 加速對本量級無感，要用才加）。

---

## 1. 三個關鍵決策（先拍板，細節在各簇）

### ① DAG 重放形狀 = **`catchup=True` 的有界 backfill**（對靜態歷史資料集的誠實排程）

公開 sample 是**固定歷史窗**（`events_20201101`–`events_20210131`，92 個日分表，此後永不再長）。「每天排程抓昨天」對它是資料謊言——昨天沒有新資料。

| 候選 | 判定 |
|---|---|
| **`ga4_daily`：`@daily`、`start_date=2020-11-01`、`end_date=2021-01-31`、`catchup=True`、`max_active_runs=1`** ✅ | 每個 dagrun 處理自己 logical date 那**一個日分表**（`_TABLE_SUFFIX = ds_nodash`，完美分區裁剪）；催動一次 unpause 即自動回放 92 天，資料備齊即收斂、不再排新 run。**與 P1 主線 `catchup=False` 的理由鏡像對稱**：mostPopular 是「當下快照、歷史不可回補」故 catchup 是謊言；GA4 sample 是「純歷史、未來不再來」故 catchup 才是唯一誠實形狀——兩條 DAG 並列正好展示「catchup 該不該開取決於資料源語意」的判斷力（README 敘事點）。 |
| `schedule="0 3 * * *"` 每日排程 + 內部映射「今天→sample 第 N 天」 | 淘汰：logical date 與資料日期脫鉤，重跑語意混亂（clear 某 run 不知對應哪天資料）、Airflow 原生 backfill/clear 機制全部失效，等於自己重造 catchup。 |
| `schedule=None` 手動一次性全量 | 淘汰：失去「一 run 一天、逐日冪等、單日可 clear 重放」的營運形狀，也失去 92 次 extract→load→dbt→DQ 的執行軌跡（面試時 Airflow UI 上 92 個綠格子本身就是展示品）。 |

一次性回放時長：92 run × 每 run ~2–4 分鐘（pod 啟動為主，資料量本身秒級）≈ **3–6 小時背景跑完**，known-limit 誠實記錄（§13）。

### ② BQ 接法 = **Python 萃取器（google-cloud-bigquery），UNNEST 全部在 BQ SQL 端做；不引入 dbt-bigquery**

| 候選 | 判定 |
|---|---|
| **`ingestion/ga4/` Python 套件發決定性 SQL（UNNEST/GROUP BY 在 BQ 端）→ Bronze → Silver** ✅ | (a) UNNEST 展開在 BQ 端做是**唯一合理位置**——BQ 原生欄式引擎掃 nested 欄位，出來的已是扁平列，網路傳輸與後續處理最省；(b) 沿用姊妹專案 `ga4-analytics-platform/extractor.py` 的「BQ client → psycopg2 UPSERT」工程慣例（唯讀取材，§10 界線表）；(c) 我方 dbt 是 **dbt-postgres 對 serving 庫**（P1 §6），BQ 只是外部資料源不是 warehouse——staging→marts 全部發生在 Postgres 端。 |
| 引入 dbt-bigquery、staging 跑在 BQ（姊妹專案原架構） | 淘汰：等於開第二個 warehouse target——dbt 專案要維護兩個 profile/兩套 source、CI 的 `dbt parse` 要能同時解析兩 adapter，且 BQ 端 staging 產物還得再落一次地。姊妹專案那樣做是因為它**整個 warehouse 就是 BQ**；我方 warehouse 是 Iceberg+Postgres，BQ 只當唯讀來源。「一工一具」：dbt 只對一個 adapter。`get_event_param.sql` 的 UNNEST 邏輯以 Python SQL-builder 形式重生（§3），巨集邏輯照取、工程層重造。 |
| Airflow Google provider（`BigQueryHook`/operators） | 淘汰：整包 `apache-airflow-providers-google` 是重依賴（拉進數十個 GCP client），我方只要一個 `client.query()`；直接 pin `google-cloud-bigquery` 一個套件，錯誤處理與 dry-run 護欄自己持有，測試也不用 mock Airflow hook 層。 |

### ③ Silver 建置 = **Python + pyiceberg（非 Spark）**——P3 右尺寸先例的直接套用

| 候選 | 判定 |
|---|---|
| **PythonOperator 內用 pyiceberg 建表 + 按日分區 overwrite** ✅ | 單日展開列 ~萬級、全窗總量 ~百萬級（實查 §12B-4），與 P3 PTT「Silver 右尺寸用 Python（非 Spark）」同一個量級判斷。pyiceberg `overwrite(df, overwrite_filter=<當日>)` = 重跑冪等（對應 P1 Spark `overwritePartitions` 語意）。Iceberg 正本仍在——P6 訓練/P7 批次要上 Spark 讀它隨時可以，**正本格式不因建置工具右尺寸而降級**。 |
| SparkApplication（沿 P1 主線 §5） | 淘汰：留言 design §10 已把「為何 lakehouse 需要 Spark」的正當性掛在百萬列 MERGE shuffle 上；GA4 單日萬列的 explode 早在 BQ 端做完，Spark 在這裡是純儀式。P3 已立過右尺寸先例，重複套用即可，不再辯論。 |
| 萃取器直寫 Postgres、跳過 Iceberg | 淘汰：違反 brief 鎖定決策 4「Silver = Iceberg 正本 + Postgres serving 副本雙寫」；P6 推薦訓練（可能上 Spark/大批掃描）要吃 Iceberg 正本，serving 副本只服務 dbt/線上下游。 |

---

## 2. 總體形狀

### 資料流

```
bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_YYYYMMDD（公開、不可變、92 日分表）
        │  extract_ga4（PythonOperator）：dry-run 位元組護欄 → 決定性 SQL
        │  （全漏斗 4 事件 UNNEST items + GROUP BY 冪等鍵，§3）→ maximum_bytes_billed 硬上限
        ▼
[Bronze] MinIO s3://bronze/ga4_events/date=YYYY-MM-DD/events.json
        │  （查詢結果快照 + _metadata 信封含 BQ job 位元組統計；一日一決定性物件，重跑覆寫 = 冪等）
        ▼  build_silver（PythonOperator，pyiceberg——§1③ 右尺寸）
[Silver] Iceberg 表 lakehouse.silver.ga4_events（PARTITIONED BY event_date，
        │   overwrite_filter 當日分區 = 冪等）——★ 穩定合約（§4）
        │  load_silver_to_postgres（PythonOperator：pyiceberg 掃當日 → psycopg2 UPSERT，P1 §5 loader 模式）
        ▼
[Silver serving] Postgres lakehouse.silver.ga4_events（dbt 唯一讀取來源）
        │  dbt run --selector ga4_only（KubernetesPodOperator，既有 dbt image）
        ▼
[Gold]  Postgres lakehouse.gold.gold_ga4_*（4 marts = P6/P7 資料合約，§5）→ dbt test（DQ gate）
```

**與 YouTube 資料域的關係（開放問題 6 收斂）**：GA4 與 YouTube 是**並存的兩個資料域，僅共用基建**（同一套 Airflow/MinIO/Iceberg catalog/Postgres/dbt project/監控）。GA4 的 staging/marts **不 `ref()`、不 `source()` 任何 YouTube 資產，反之亦然**；不 JOIN、不改 YouTube Gold 5 表（連 additive 加欄都不加）。dbt 隔離手法沿用留言 design §6：GA4 資產全掛 **tag `ga4`**，default selector 排除之（§6）。

### 新增檔案佈局（全 additive；未列 = 不動）

```
ingestion/ga4/                        # 純 Python 套件（裝進 Airflow image），無自己的部署
    pyproject.toml
    src/ga4_ingest/
        sql.py          # 決定性 SQL builder：全漏斗 UNNEST 查詢 + event_params 萃取 helper（§3）
        bq.py           # BQ client 建立（ADC 走 GOOGLE_APPLICATION_CREDENTIALS）、dry-run 護欄、query_and_wait
        bronze.py       # _metadata 信封組裝 + boto3 決定性 key 寫入
        silver.py       # Bronze→Iceberg：schema 定義、create_table_if_not_exists、按日 overwrite
        loader.py       # pyiceberg 掃當日 → psycopg2 execute_values UPSERT（DDL 由本檔持有）
    tests/              # §11 單元測試
orchestration/airflow/
    Dockerfile          # ＋ ga4_ingest 套件 + google-cloud-bigquery==3.42.2（僅此改動）
    dags/ga4_daily.py   # §7
    dags/config/pipeline.yaml   # ＋ ga4: 區塊（§3 常數單一真源）
lakehouse/dbt/
    models/staging/stg_ga4_events.sql（+ _sources.yml、_staging_schema.yml additive 增列）
    models/marts/ga4/{_ga4_marts_schema.yml, gold_ga4_user_item_interactions.sql,
                      gold_ga4_item_catalog.sql, gold_ga4_sessions.sql, gold_ga4_user_rfm.sql}
    selectors.yml       # default 排除清單 ＋ tag:ga4；新增 selector ga4_only（§6 接縫注意）
    tests/assert_ga4_*.sql（§6 清單）
platform/argocd/apps/airflow.yaml    # valuesObject additive：workers volume + env（§8）
lakehouse/postgres/k8s/…             # postgres-exporter 自訂查詢 ConfigMap additive 加 3 條（§9）
Makefile                             # += ga4-secrets / ga4-verify
scripts/verify-ga4.sh                # §11
```

**零新 ArgoCD Application、零新 CI workflow、零新 image**：`airflow-ci` paths（`ingestion/**`）天然涵蓋 `ingestion/ga4/`；`dbt-ci` 涵蓋 dbt 改動；Airflow image 改 Dockerfile 走既有 airflow-ci 迴圈。**這是本 repo 第一個 GCP SA 憑證接法**（P0 §7 預告的 secret 邊界策略第二次落地），新增一個 Secret（§8）。

---

## 3. GA4 BQ 萃取器（決定）

| 開放問題 | 決定 | 理由 |
|---|---|---|
| 事件白名單 | **恰好 4 個全漏斗事件：`view_item` / `add_to_cart` / `begin_checkout` / `purchase`**，且 `items[].item_id IS NOT NULL` | 這是對 `extract_funnel.py` 邏輯的**進化**：它抓 view/cart（purchase 另路重用）、ga-insight 只抓 purchase（稀疏矩陣病灶，brief 點名）；本設計四事件一次到位＋補 `begin_checkout`，漏斗四階完整。**不納入** `page_view`/`session_start` 等無 items 事件——粒度是 event-item 展開（開放問題 1），無 item 的事件會產生 NULL item_id 破壞粒度純度；P7 若需全 session 事實，以 additive 新 Silver 表演進（§13 known-limit 3）。 |
| Silver 粒度（開放問題 1） | **一列一 (event, item) 展開列**，並在 BQ 端 `GROUP BY` 冪等鍵去重（同一事件內同 item 多列 → `SUM(quantity)`/`SUM(item_revenue)` 聚合） | 照 brief 傾向收斂。取捨：JSONB 陣列方案保留了原始巢狀，但 P6 互動矩陣、P7 item OLAP、dbt 聚合**全部**要 item 粒度——展開列讓每個下游省一次 lateral join；反向（從展開列還原事件級）在 gold 用 `event_ts_micros` group 回去即可，資訊無損。GROUP BY 去重讓「冪等鍵＝物理粒度」嚴格成立（§4 PK），UPSERT 語意乾淨。 |
| `user_pseudo_id`（開放問題 2） | **直接用、不再 hash**。 | sample 本身已由 Google 去識別並公開授權（obfuscated）；再 hash 一層是安全劇場、還斬斷與官方文件/教學對照的可讀性。與留言管線的 `author_hash`（真實使用者→必須遮蔽）判準一致：**遮蔽義務跟著「原始資料是否可識別」走**，不是跟著欄位名走。dbt description 誠實揭露「公開去識別資料集」（§5）。 |
| 分區裁剪 + 成本護欄（開放問題 7） | 每 run 只掃**一個日分表**：`_TABLE_SUFFIX = '<ds_nodash>'`。兩層護欄：①先 `QueryJobConfig(dry_run=True)` 取 `total_bytes_processed`，超過 `dry_run_limit_bytes` → `AirflowFailException`（fail-fast 不重試——量爆代表 SQL 寫壞，重試無意義，對齊 P1 quota fail-fast 姿態）；②真查詢帶 `maximum_bytes_billed`（BQ 端硬拒超額）。兩值進 `pipeline.yaml` 單一真源。成本數學：單日 shard 遠低於 512 MiB、92 天全窗總掃描 ~個位數 GB（實查 §12B-4 量測），對 BQ 免費層 1 TB/月是 <1% 量級；查詢計費掛使用者自己的 GCP 專案（SA 所屬），公開資料集讀取本身免費。 | dry-run 免費且回傳精確掃描量——寫進 Bronze 信封成為每 run 的成本審計軌跡。 |
| event_params 萃取 helper | `sql.py` 提供 `string_param(key)` / `int_param(key)` 兩個純函式，輸出與姊妹專案 `get_event_param.sql` 巨集**逐字等價**的子查詢片段：`(SELECT ep.value.string_value FROM UNNEST(event_params) AS ep WHERE ep.key = '<key>' LIMIT 1)`（int 版取 `int_value`）。 | 巨集邏輯照取、載體重造（dbt-on-BQ 巨集 → Python SQL-builder），因我方 dbt 不接 BQ（§1②）。float 版（`get_float_param` 的 COALESCE 邏輯）本 spec 用不到，不預造。 |
| intraday | **砍**——公開 sample 無 `events_intraday_*` 表（brief 鎖定決策 6）；姊妹專案 `stg_ga4_events.sql:31-54` 的 intraday CTE 段不取。即時場景由即時層 spec 以標註事件重放示範。 | — |

### 萃取 SQL（決定性；`sql.py::build_funnel_query(ds_nodash)` 的輸出合約）

```sql
WITH exploded AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date)                    AS event_date,
    event_timestamp                                     AS event_ts_micros,
    event_name,
    user_pseudo_id,
    -- 下兩欄由 sql.py 的 int_param / string_param helper 展開（§3 helper 決定）：
    (SELECT ep.value.int_value    FROM UNNEST(event_params) AS ep
       WHERE ep.key = 'ga_session_id'  LIMIT 1)         AS ga_session_id,
    (SELECT ep.value.string_value FROM UNNEST(event_params) AS ep
       WHERE ep.key = 'transaction_id' LIMIT 1)         AS transaction_id,
    device.category                                     AS device_category,
    geo.country                                         AS geo_country,
    traffic_source.source                               AS first_touch_source,
    traffic_source.medium                               AS first_touch_medium,
    it.item_id, it.item_name, it.item_category,
    it.price, it.quantity, it.item_revenue
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`,
       UNNEST(items) AS it
  WHERE _TABLE_SUFFIX = '{ds_nodash}'
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
    AND it.item_id IS NOT NULL
)
SELECT
  event_date, event_ts_micros, event_name, user_pseudo_id, item_id,
  MAX(ga_session_id)      AS ga_session_id,
  MAX(transaction_id)     AS transaction_id,
  MAX(device_category)    AS device_category,
  MAX(geo_country)        AS geo_country,
  MAX(first_touch_source) AS first_touch_source,
  MAX(first_touch_medium) AS first_touch_medium,
  MAX(item_name)          AS item_name,
  MAX(item_category)      AS item_category,
  MAX(price)              AS price,
  SUM(quantity)           AS quantity,
  SUM(item_revenue)       AS item_revenue
FROM exploded
GROUP BY event_date, event_ts_micros, event_name, user_pseudo_id, item_id
```

聚合函式全用 `MAX`/`SUM`（決定性），**不用 `ANY_VALUE`**（非決定性，違反「決定性 SQL + 冪等鍵」）。`traffic_source.*` 是 GA4 export 的**使用者首觸來源**（user-scoped first touch，非本事件的 session 來源）——語意如實寫進欄位註解，P7 當「獲客來源標籤」用恰好正確。

### Bronze 物件（`_metadata` 信封 + 查詢結果列）

Key：`s3://bronze/ga4_events/date=<YYYY-MM-DD>/events.json`（一日一決定性物件，由 logical date 導出、不含 `now()`；重跑覆寫 = 冪等，對齊 P1 §3 決定性 key 紀律）。

```json
{
  "_metadata": {
    "source": "bigquery-public-data.ga4_obfuscated_sample_ecommerce",
    "table_suffix": "20201101",
    "logical_date": "2020-11-01",
    "ingestion_id": "ga4_20201101",
    "ingested_at": "<實際執行 UTC ISO>",
    "row_count": 12345,
    "bq_job": {"total_bytes_processed": 0, "total_bytes_billed": 0, "cache_hit": false}
  },
  "rows": [ { …§4 欄名 snake_case… } ]
}
```

**Bronze「保原文」語意的誠實調整**（比照留言 design §1② 的顯式例外先例）：本管線的真正不可變正本是**公開 BQ 資料集本身**（Google 託管、任何人可重讀）；Bronze 物件是「決定性 SQL 的結果快照」，重放 = 重跑同一 SQL 必得同一結果。因此 Bronze 在此的職責是**斷網重放層 + 成本審計軌跡**（`bq_job` 統計），不是唯一原文備份。此界線寫進 README。

---

## 4. `silver_ga4_events` schema（★ P6/P7/即時 三垂直共用合約，標穩定）

**粒度：一列 = 一個 (電商事件, item) 展開組合。** Iceberg 正本 `lakehouse.silver.ga4_events`（`PARTITIONED BY (event_date)` identity 日分區）；Postgres serving 副本 `lakehouse` db `silver.ga4_events` 同構。
**PK（PG）＝冪等鍵 = `(user_pseudo_id, event_ts_micros, event_name, item_id)`**。

**穩定性政策（與 P1 §6a / 留言 §5 同款）**：表名、粒度鍵、既列欄位語意是對 P6/P7/即時層的介面承諾——變更只允許**加欄位**（additive）；改粒度/刪欄/改語意必須開 `_v2` 新表並記錄於 spec。

| 欄位 | 型別（Iceberg / PG） | 來源與定義 |
|---|---|---|
| event_date | date / date | `PARSE_DATE(event_date)`；**分區鍵**、loader 增量過濾鍵 |
| event_ts_micros | long / bigint | 原始 `event_timestamp`（μs epoch）；**PK 成分**——保留原始精度，不因 timestamp cast 產生歧義 |
| event_ts | timestamptz | `TIMESTAMP_MICROS(event_ts_micros)`，silver 建置時衍生（下游好讀） |
| event_name | string / text | 白名單 4 值（DQ 守門） |
| user_pseudo_id | string / text | GA4 匿名裝置級 ID（**公開去識別資料集，直接使用**，開放問題 2）；not null |
| ga_session_id | long / bigint | `event_params.ga_session_id`；nullable（缺席率實查 §12B-6） |
| item_id | string / text | `items[].item_id`；not null（萃取端已濾） |
| item_name | string / text | `items[].item_name` |
| item_category | string / text | `items[].item_category` |
| price | double / double precision | `items[].price`（USD 計價欄；sample 幣別單一） |
| quantity | long / bigint | `SUM(items[].quantity)`；view 類事件常為 null——**保 null 不補 0**（「未提供」≠「0 件」，語意誠實；gold 聚合端 coalesce） |
| item_revenue | double / double precision | `SUM(items[].item_revenue)`；實務上僅 purchase 事件有值 |
| transaction_id | string / text | `event_params.transaction_id`；僅 purchase 有值（P7 訂單計數用） |
| device_category | string / text | `device.category`（desktop/mobile/tablet） |
| geo_country | string / text | `geo.country` |
| first_touch_source / first_touch_medium | string / text | `traffic_source.source/medium`——**使用者首觸獲客來源**（user-scoped），非本次 session 來源；語意入欄位註解 |
| ingestion_id | string / text | `ga4_<YYYYMMDD>`（追溯 Bronze 物件） |
| ingested_at | timestamptz | 實際萃取執行時間 |

寫入語意：Iceberg 端 `overwrite(df, overwrite_filter=EqualTo('event_date', <當日>))` = 重跑覆寫當日分區（對應 P1 §5 overwritePartitions 冪等語意）；PG 端 loader `INSERT … ON CONFLICT (user_pseudo_id, event_ts_micros, event_name, item_id) DO UPDATE`（`execute_values` 每 5,000 列一批，P1 §5 / 留言 §4 同款）。serving 副本另建 btree 索引：`(item_id)`、`(event_date)`（P6/P7 探索查詢友善；dbt 全表掃不受影響）。DDL 由 `loader.py` 首行 `CREATE TABLE IF NOT EXISTS` 持有（P1 loader 慣例）。

---

## 5. Gold GA4 marts（★ P6/P7 介面合約，additive-only）— 開放問題 5 收斂：**恰好 4 張**

全部：Postgres `gold` schema、dbt table materialization、tag `ga4`、只准 `ref('stg_ga4_events')` 不觸 source 不觸任何 YouTube 資產。穩定性政策同 §4。**每張的 dbt `description` 即下游 Explainer 的「這是什麼」素材**（跨 P4/P6/P7 前端說明式 UI 要求——地基不做頁，但語意文字在 schema.yml 備好，下游 InfoTooltip/ChartCaption/Explainer 直接引用）。以下「說明」欄文字即 schema.yml description 的定稿內容。

### 5.1 `gold.gold_ga4_user_item_interactions` — 粒度 `(user_pseudo_id, item_id, event_name, event_date)`【P6 介面：召回/CF 輸入矩陣源】

> **description（Explainer 素材）**：「使用者×商品×互動」三角的原子表：每列 = 某匿名使用者、某商品、某漏斗階段、某天的互動彙總。推薦系統的協同過濾（CF）與共現召回直接以本表為輸入矩陣。**刻意不加權**——view/cart/purchase 的權重是推薦演算法的決策（P6 spec），地基只提供未染色的計數。資料來自 Google 公開去識別電商資料集（Google Merchandise Store）。

| 欄位 | 型別 | 定義 |
|---|---|---|
| user_pseudo_id / item_id / event_name / event_date | text / text / text / date | 粒度鍵 |
| interaction_count | bigint | 展開列計數 |
| sessions_count | bigint | count(distinct ga_session_id)（null session 不計） |
| total_quantity | bigint | sum(coalesce(quantity,0)) |
| total_revenue | numeric | sum(coalesce(item_revenue,0))；僅 purchase 列非零 |
| first_event_ts / last_event_ts | timestamptz | min/max(event_ts) |

### 5.2 `gold.gold_ga4_item_catalog` — 粒度 `item_id`【P6 item 特徵 + P7 item 側標籤】

> **description**：商品目錄維度：每列 = 一個商品在全觀測窗（2020-11-01～2021-01-31）的身分與漏斗表現。`item_name`/`item_category` 是 P6 語意 embedding 的**文字輸入源**（embedding 本體屬 P6 召回 spec，開放問題 4 界線）；各階段觸達人數與轉換率是 item 冷熱/長尾分析的底。

| 欄位 | 型別 | 定義 |
|---|---|---|
| item_id | text | 粒度鍵 |
| item_name | text | 最後一次出現的非空名（`last_value` over event_ts，決定性） |
| item_category | text | 同上取法 |
| price_min / price_max / price_latest | numeric | 全窗最低/最高/最後觀測價 |
| first_seen_date / last_seen_date | date | min/max(event_date) |
| users_viewed / users_carted / users_checked_out / users_purchased | bigint | 各階段 count(distinct user_pseudo_id) |
| view_events / cart_events / checkout_events / purchase_events | bigint | 各階段互動列數 |
| units_sold | bigint | purchase 列 sum(coalesce(quantity,0)) |
| revenue_total | numeric | purchase 列 sum(coalesce(item_revenue,0)) |
| view_to_cart_user_rate / cart_to_purchase_user_rate / view_to_purchase_user_rate | numeric | 階段人數比（分母 0 → NULL，round 4）——**商品級漏斗轉換率** |

### 5.3 `gold.gold_ga4_sessions` — 粒度 `(user_pseudo_id, ga_session_id)`【P7 行為標籤 + 即時層離線對照】

> **description**：漏斗活躍 session 事實表：每列 = 一段帶電商互動的匿名使用者工作階段。**誠實界定：本表只含出現過漏斗事件的 session**（純瀏覽 session 不在地基事件白名單內，§13 known-limit 3）。即時特徵層（Flink session 視窗）以本表為**離線對照組**驗證串流計算正確性；P7 以它衍生 session 頻率/深度行為標籤。`ga_session_id` 為 null 的展開列不入本表（量級由 DQ 監看）。

| 欄位 | 型別 | 定義 |
|---|---|---|
| user_pseudo_id / ga_session_id | text / bigint | 粒度鍵 |
| session_date | date | min(event_date) |
| session_start_ts / session_end_ts | timestamptz | min/max(event_ts)（僅漏斗事件的跨度，非 GA 完整 session 時長） |
| funnel_events_count | bigint | 展開列數 |
| items_viewed / items_carted / items_purchased | bigint | 各階段 count(distinct item_id) |
| did_view / did_cart / did_checkout / did_purchase | boolean | 階段觸達旗標（session 漏斗分析直接可用） |
| session_revenue | numeric | purchase 列 sum(coalesce(item_revenue,0)) |
| device_category / geo_country | text | max()（session 內恆定，決定性取法） |

### 5.4 `gold.gold_ga4_user_rfm` — 粒度 `user_pseudo_id`【P7 介面：RFM/LTV/畫像輸入】

> **description**：使用者級 RFM 原料表：每列 = 一個匿名使用者在全觀測窗的 Recency/Frequency/Monetary 度量與漏斗足跡。**本表是「源」不是「分數」**——分群切點與標籤體系是 P7 DMP 的決策，地基只出可重算的度量。⚠️ 資料集是靜態歷史窗，`recency_days` 一律**相對 `data_anchor_date`（全資料集最大 event_date）計算**，不是相對今天——否則所有使用者 recency 都是五年起跳的無意義數字。

| 欄位 | 型別 | 定義 |
|---|---|---|
| user_pseudo_id | text | 粒度鍵 |
| first_seen_date / last_seen_date | date | min/max(event_date) |
| active_days | bigint | count(distinct event_date) |
| sessions_count | bigint | count(distinct ga_session_id)（null 不計） |
| view_events / cart_events / checkout_events / purchase_events | bigint | 各階段互動列數 |
| distinct_items_viewed / distinct_items_purchased | bigint | 各階段 count(distinct item_id) |
| orders_count | bigint | count(distinct transaction_id)（purchase 列） |
| units_purchased | bigint | purchase 列 sum(coalesce(quantity,0)) |
| monetary_total | numeric | purchase 列 sum(coalesce(item_revenue,0)) |
| last_purchase_date | date | max(event_date) where purchase；無購買 → NULL |
| recency_days | bigint | `data_anchor_date - last_purchase_date`；無購買 → NULL |
| aov | numeric | monetary_total / nullif(orders_count,0)，round 2 |
| data_anchor_date | date | max(event_date) over 全表——錨點自述欄，讓 recency 語意自帶解釋 |

### 與 P4 匯出合約的關係（拓撲守則）

地基**不新增匯出 dataset**——P4 的 11 檔清單零改動。P6/P7 各自的 design 屆時按 P4 §4 additive 政策（只加檔/加欄）把自己的前端資料接進 `export_frontend_data`；前端仍走「批次表 → 匯出 DAG → 靜態 JSON」，本地基不開任何線上端點（Vercel 打不到本地 k8s）。

---

## 6. dbt 佈局與 DQ 測試（決定）

| 項目 | 決定 | 理由 |
|---|---|---|
| staging | `stg_ga4_events`（view，`staging` schema）：source `silver.ga4_events` 直取 + 型別防衛（濾 `item_id is null`/`user_pseudo_id is null`、數值 coalesce 交 marts 端做——staging 保 null 語意）＋衍生無 | 對齊 P1 §6「staging view / marts table」與 `generate_schema_name` 既有覆寫，零新巨集。 |
| source 定義 | `_sources.yml` additive 增列 `silver.ga4_events`，**`freshness: null`（顯式不設）** | **開 wall-clock freshness 是範疇錯誤**：靜態歷史資料集回放完成後永無新資料，freshness 告警會永久紅。資料完整性改由 §6 singular 測試（觀測窗邊界 + 列數下限）承擔。此決定寫進 `_sources.yml` 註解，防止後人「補上 freshness」好心辦壞事。 |
| 隔離手法 | GA4 全資產（staging+marts+tests）掛 **tag `ga4`**；`selectors.yml` 的 default selector 排除清單**加上 `tag:ga4`**（既有留言 design §6 已建此檔並排除 `tag:comments`——本設計 additive 加一條排除）；新增 selector **`ga4_only`**（`tag:ga4`）供 `ga4_daily` DAG 顯式使用 | 主線 hourly `dbt run` 不因 GA4 表未建而炸（與留言同一防護邏輯）。**跨 spec 接縫**：若留言 plan 尚未執行（`selectors.yml` 不存在），GA4 plan 負責建檔並同時涵蓋兩個排除——兩個 plan 以「檔案已存在則 additive 修改」的冪等寫法互不阻塞。 |
| marts 目錄 | `models/marts/ga4/` 子目錄 | 物理隔離可見；`dbt_project.yml` 的 marts 設定天然繼承（table + gold schema）。 |

### dbt 測試合約（tag:ga4 全列）

**generic tests（`_staging_schema.yml` / `_ga4_marts_schema.yml`）**
- `stg_ga4_events`：`user_pseudo_id`/`event_ts_micros`/`event_name`/`event_date`/`item_id`/`ingested_at` not_null；`event_name` accepted_values `['view_item','add_to_cart','begin_checkout','purchase']`
- `gold_ga4_user_item_interactions`：粒度四欄 not_null；`interaction_count` not_null
- `gold_ga4_item_catalog`：`item_id` unique + not_null
- `gold_ga4_sessions`：`user_pseudo_id`/`ga_session_id` not_null
- `gold_ga4_user_rfm`：`user_pseudo_id` unique + not_null；`data_anchor_date` not_null

**singular tests（`tests/`，不引 dbt_utils，沿 P1 自寫慣例）**
- `assert_unique_grain_ga4_events.sql`：staging 四鍵 group by having count>1 出列即 fail（serving PK 之外的邏輯層雙保險）
- `assert_unique_grain_ga4_interactions.sql` / `assert_unique_grain_ga4_sessions.sql`：各 mart 粒度鍵重複檢查
- `assert_ga4_amounts_non_negative.sql`：`price < 0 OR quantity < 0 OR item_revenue < 0` 出列即 fail
- `assert_ga4_event_date_in_window.sql`：`event_date NOT BETWEEN '2020-11-01' AND '2021-01-31'` 出列即 fail（觀測窗邊界守門——抓 `_TABLE_SUFFIX`/PARSE_DATE 類 bug，取代 wall-clock freshness 的資料理智檢查職責）
- `assert_ga4_purchase_revenue_coverage.sql`：purchase 展開列中 `item_revenue IS NULL` 佔比 > 90% 出列即 fail（revenue 萃取整體失效的哨兵；個別 null 容忍）
- `assert_ga4_session_flag_consistency.sql`：`did_purchase = true AND items_purchased = 0`（或反向）出列即 fail（旗標與計數自洽）

---

## 7. `ga4_daily` Airflow DAG（決定；形狀對齊 P1 §7 慣例）

```python
DAG(
    dag_id="ga4_daily",
    schedule="@daily",
    start_date=pendulum.datetime(2020, 11, 1, tz="UTC"),
    end_date=pendulum.datetime(2021, 1, 31, tz="UTC"),   # 有界回放（§1①；端點含入行為實查 §12B-5）
    catchup=True,                                          # 對靜態歷史資料集的誠實形狀（§1①）
    max_active_runs=1,                                     # 串行回放，防寫入交錯
    dagrun_timeout=timedelta(minutes=30),
    default_args=dict(retries=3, retry_delay=timedelta(minutes=1),
                      retry_exponential_backoff=True,
                      max_retry_delay=timedelta(minutes=10)),   # P1 §3 同款
    tags=["ga4"],
)
```

```
extract_ga4（PythonOperator，execution_timeout=10min）
      │  dry-run 護欄 → build_funnel_query(ds_nodash) → query_and_wait(maximum_bytes_billed)
      │  → Bronze events.json（信封含 bq_job 統計）
      ▼
build_silver（PythonOperator）
      │  讀 Bronze 當日物件 → pyarrow table → pyiceberg overwrite(當日分區) = 冪等
      ▼
load_silver_to_postgres（PythonOperator）
      │  pyiceberg 掃 event_date = ds → psycopg2 ON CONFLICT UPSERT（execute_values）
      ▼
dbt_run_ga4（KubernetesPodOperator，既有 dbt image：dbt run --selector ga4_only）
      ▼
dbt_test_ga4（KPO：dbt test --selector ga4_only）→ 失敗 = DAG 失敗 = 告警（DQ gate）
```

相對 brief 的四步驟形狀（`extract → load → dbt_run → dbt_test`）多一個顯式 `build_silver`——保住 P1「Bronze→Silver（Iceberg 正本）→ serving 載入」的階段分離，brief「或類名」的裁量範圍內。空日防衛：某日分表 4 事件展開列為 0（理論上不會發生）→ Bronze 寫空 rows 信封、Silver overwrite 空分區、後續照走（合法狀態，非 fail——比照留言 §4 空輸入語意）。**重處理**：不另立 reprocess DAG——`catchup` 回放本身就是範圍重放機制，單日重算 = Airflow UI clear 該 dagrun（全鏈冪等保證），README 記操作法。**每 run 跑 dbt 的取捨**：92 次全量 mart 重建（table materialization）在此資料量是秒級小事，換到的是「每一天的資料都過了 DQ gate 才算落地」的 P1 同款紀律；不做「只在最後一天跑 dbt」的最佳化（省 3 小時背景時間、賠掉逐日 DQ 語意，不值）。

---

## 8. SA Secret 落地（本 repo 第一個 GCP SA 憑證接法；沿 P0 §7 / P1 §8 / P2 §3.5 姿態）

**姿態**：SA JSON **進 k8s Secret 掛 volume**（非 env 值——`GOOGLE_APPLICATION_CREDENTIALS` 吃**檔案路徑**）＋ env 指向掛載路徑；命令式建立、文件化、不進 git。取材姊妹專案 `profiles.yml` 的 `keyfile: env_var('GOOGLE_APPLICATION_CREDENTIALS')` 姿態（取「憑證經 env 指路」的形，不取 dbt-bigquery 的體）。

### `make ga4-secrets`（冪等 apply，對齊 P2 `make ml-secrets` 風格）

```make
ga4-secrets:  ## 用法：make ga4-secrets GA4_SA_JSON=/path/to/sa.json
	@test -n "$(GA4_SA_JSON)" || (echo "GA4_SA_JSON=<SA JSON 路徑> 必填"; exit 1)
	kubectl -n airflow create secret generic gcp-sa-ga4 \
	  --from-file=sa.json=$(GA4_SA_JSON) \
	  --dry-run=client -o yaml | kubectl apply -f -
```

- Secret **只建在 `airflow` ns**（唯一消費者是 KubernetesExecutor task pod；Spark/dbt/ml 全都不碰 BQ）。
- SA 需求文件化進 README：使用者自備 GCP 專案、SA 授 **`roles/bigquery.jobUser`**（對自己專案）即可——公開資料集讀取不需任何 dataset 級授權；查詢位元組計費掛此專案（免費層 1 TB/月，本管線全窗 <1%）。
- SA JSON 檔本體放 repo 外（建議 `~/.gcp/`），**永不落 repo**；`.gitignore` 加 `*.sa.json` 防呆。

### Helm values 形狀（`platform/argocd/apps/airflow.yaml` valuesObject additive；chart 1.22.0）

```yaml
workers:                       # KubernetesExecutor task pod 模板由 workers 段生成
  extraVolumes:
    - name: gcp-sa-ga4
      secret:
        secretName: gcp-sa-ga4
        optional: true         # ★ 未跑 ga4-secrets 時 YT 主線 task pod 照常起（volume 掛空）
  extraVolumeMounts:
    - name: gcp-sa-ga4
      mountPath: /var/secrets/gcp
      readOnly: true
env:
  - name: GOOGLE_APPLICATION_CREDENTIALS
    value: /var/secrets/gcp/sa.json     # 非 secret 值（只是路徑），env 直寫合規
```

- `optional: true` 是**啟用順序解耦**的關鍵：GA4 是可選擴充，secret 缺席不得癱瘓既有主線（additive 承諾的部署面落實）。extract 任務端顯式防衛：檔案不存在 → 明確錯誤訊息指向 `make ga4-secrets`（fail-fast、可診斷）。
- 取捨誠實：volume 掛給**所有** task pod（含 YT 主線）而非只 GA4 任務。淘汰替代案「DAG 內 `executor_config` pod_override 逐任務掛」——最小權限較優，但 secret 形狀藏進 DAG 程式碼、脫離 GitOps values 可見面，且單租戶 demo 的越權面只有自己；values 級宣告式與 P1 `secret:` 注入姿態同構，勝出。README 註記多租戶時應改 pod_override。
- BQ client 端零設定：`bigquery.Client()` 走 ADC 讀 `GOOGLE_APPLICATION_CREDENTIALS`，billing project 自動取 SA JSON 的 `project_id`——不新增 project id 設定項。

---

## 9. 監控 / CI 接入（零新件盤點）

| 面向 | 接法 |
|---|---|
| CI | **零新 workflow**：`airflow-ci`（paths `ingestion/**` + Airflow Dockerfile）涵蓋 `ingestion/ga4/` 與 image 依賴變更；`dbt-ci` 的 `dbt parse` 守門新 model/selector。 |
| ArgoCD | **零新 Application**：`airflow.yaml` valuesObject additive（§8）由既有 airflow app 滾動；exporter ConfigMap 改動屬既有 wave 3 app。 |
| Prometheus 指標（postgres-exporter 自訂查詢 ConfigMap additive 加 3 條，沿 P1 §9 模式） | `ga4_silver_rows_total` = `SELECT count(*) FROM silver.ga4_events`；`ga4_replay_max_event_date` = `SELECT EXTRACT(EPOCH FROM max(event_date)::timestamp) FROM silver.ga4_events`（回放進度：到 2021-01-31 即收斂完成）；`ga4_gold_mart_rows{mart}` = 4 個 mart count 的 UNION ALL。 |
| 告警 | **不加 GA4 專屬 PrometheusRule**：wall-clock freshness 對靜態資料集無意義（§6）；任務失敗已被既有 `YTPipelineTaskFailures`（statsd task 失敗計數，不分 DAG）涵蓋。 |
| Grafana | **不建新 dashboard、不加 panel**——地基無前端交付；回放進度用 Prometheus 查詢與驗收腳本看。P6/P7 的展示面由各自 spec 負責。 |

---

## 10. 取材界線表（進化非複刻：取什麼邏輯 vs 重造哪個工程層）

| 素材（唯讀） | 取的邏輯 | 重造的工程層 |
|---|---|---|
| web-agency `extract_funnel.py:25-57` | **全漏斗 items UNNEST**（view/cart 都展開 item_id，非 ga-insight 只萃 purchase 的稀疏做法）；`it.item_id IS NOT NULL` 過濾；event_params 子查詢取 `ga_session_id` | 事件清單 +`begin_checkout`+`purchase` 四階補全；`ORDER BY event_timestamp` 移除（下游不需來源排序，省 BQ shuffle）；dataclass 記憶體傳遞 → Bronze/Silver medallion 落地；**跑在公開 sample 上，area02 資料與專案 ID 零進入** |
| `ga4-analytics-platform/extractor/extractor.py:216-288` | BQ client → psycopg2 **UPSERT（ON CONFLICT DO UPDATE）冪等模式**；`CREATE TABLE IF NOT EXISTS` 由 loader 持有 | `to_dataframe()` → `RowIterator` 逐列（砍 pandas/db-dtypes 依賴）；「BQ 直抽 gold」→ 我方 medallion（gold 由 dbt 在 Postgres 算，BQ 只當 source）；`executemany` → `execute_values`（P1 loader 既定款） |
| `ga4-analytics-platform/dbt/models/staging/stg_ga4_events.sql:25-28` | `events_*` + `_TABLE_SUFFIX` 萬用字元讀法；`PARSE_DATE`/`TIMESTAMP_MICROS` 轉換 | 90 天滾動窗 → 單日等值裁剪（`= ds_nodash`，配 catchup 逐日回放）；`:31-54` intraday CTE 段**整段不取**（sample 無 intraday 表）；dbt-on-BQ model → Python SQL builder |
| `ga4-analytics-platform/dbt/macros/get_event_param.sql:1-14` | `event_params` UNNEST 子查詢萃取邏輯（string/int 兩式逐字等價） | dbt 巨集 → `sql.py` 純函式（我方 dbt 不接 BQ，§1②）；float 版 COALESCE 式用不到不預造 |
| `ga4-analytics-platform/dbt/profiles.yml:1-11` | SA 憑證「`GOOGLE_APPLICATION_CREDENTIALS` env 指向 keyfile」姿態 | dbt-bigquery profile 本體不取；keyfile 落點從本機路徑 → k8s Secret volume 掛載（§8） |
| P1 design §5 / 留言 design §4 | Silver→Postgres loader 模式（pyiceberg 掃分區 → ON CONFLICT + execute_values）；決定性 Bronze key；DQ gate 進 DAG | 直接沿用不重造（照 P1 模式引用，非新發明） |

---

## 11. 測試策略與端到端驗收

### 單元/CI 層（每步可測）

| 層 | 測試 |
|---|---|
| `sql.py` | SQL builder 決定性（同 ds 同輸出）；白名單 4 事件都在 `IN (…)`；`_TABLE_SUFFIX` 等值裁剪存在；param helper 輸出與 `get_event_param.sql` 巨集片段逐字等價（防手滑改壞）；GROUP BY 鍵 = 冪等鍵四欄 |
| `bq.py` | mock client：dry-run 超限 → `AirflowFailException`（fail-fast 不重試）；`maximum_bytes_billed` 有掛上 job_config；SA 檔缺席 → 可診斷錯誤訊息 |
| `bronze.py` | key 決定性（由 logical date 導出、無 `now()`）；`_metadata` 信封欄位齊（含 `bq_job` 統計）；空 rows 信封合法 |
| `silver.py` / `loader.py` | 固定 rows fixture → Iceberg schema 對映（型別逐欄）；overwrite 同分區兩次列數不變（冪等）；loader UPSERT SQL 的 conflict 鍵 = §4 PK；DDL 與 §4 schema 逐欄一致 |
| DAG | DagBag import 零錯誤；依賴鏈斷言（5 task 線性）；`catchup=True`/`max_active_runs=1`/`end_date` 守門測試（**注意：與主線 catchup=False 守門測試方向相反，測試各測各的 DAG**）；`pipeline.yaml ga4:` 鍵存在性與型別 |
| dbt | `dbt parse`（CI 離線守門，含 selectors 解析）＋ §6 測試合約（runtime DQ gate） |

### `make ga4-verify`（`scripts/verify-ga4.sh`；前置 = P1 `make pipeline-verify` 綠 + `make ga4-secrets` 已跑）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | unpause `ga4_daily` → 輪詢首個 dagrun（logical date 2020-11-01，timeout 15m） | `success`（含 dbt_test_ga4 綠 = DQ gate 過） |
| 2 | Bronze | `mc ls bronze/ga4_events/date=2020-11-01/events.json` 存在；信封 `row_count > 0` 且 `bq_job.total_bytes_billed ≤ pipeline.yaml 的 max_bytes_billed`（成本護欄可執行證明） |
| 3 | Silver serving | `SELECT count(*) FROM silver.ga4_events WHERE event_date='2020-11-01'` > 0；`event_name` 至少含 `view_item` 與 `purchase` 兩值（漏斗兩端都有料） |
| 4 | **Gold 三角驗收（brief 核心驗收，非敘述性）** | `SELECT user_pseudo_id, item_id, event_name, event_date, interaction_count FROM gold.gold_ga4_user_item_interactions LIMIT 5` 回非空列——**user×item×event 互動列可查**；另 3 marts `count(*)` 全 > 0 |
| 5 | 冪等 | clear 2020-11-01 dagrun → rerun → Bronze 物件數、silver/gold 列數皆不膨脹 |
| 6 | 主線無損（additive 可執行證明，比照留言驗收 #8） | `yt_trending_hourly` 最近 dagrun 仍 success；主線 dbt task log 無任何 tag:ga4 資產（selector 隔離生效） |
| 7 | 回放進度指標 | Prometheus `ga4_replay_max_event_date` 有值且遞增（回放推進中） |

**全窗回放**是背景累積（3–6 小時，§1①），驗收腳本只驗單日全鏈 + 冪等 + 隔離；回放收斂（max_event_date = 2021-01-31、92 dagrun 全綠）進 README 完成檢查表，不進自動化腳本（同留言「百萬列是累積型指標」的處理先例）。

---

## 12. plan 前需實查（設計已收斂，以下為落地校準點，皆帶預設傾向）

1. **Airflow chart 1.22.0 的 KubernetesExecutor pod 模板是否吃 `workers.extraVolumes`/`extraVolumeMounts`**（預設傾向：是——chart 文件（context7）確認 workers 段有此二鍵且 KubernetesExecutor 模板由 workers 段生成；若 1.22.0 已把 K8sExecutor 專屬 extras 分家到 `workers.kubernetes.*`（main 分支文件出現此形狀），改用對應鍵即可，掛載內容零變）。
2. **pyiceberg 0.11.1 `overwrite(df, overwrite_filter=EqualTo('event_date', …))` 煙囪驗證**（預設傾向：可用——0.9+ 已支援 filtered overwrite；5 分鐘實證，並確認 identity date 分區下的分區裁剪）。
3. **sample 欄位覆蓋率抽測**（一條 SQL）：`items.price`/`item_revenue` 非空比例、`event_params.transaction_id` 於 purchase 事件的存在性、`traffic_source.source` 非空比例、（預設傾向：price 高覆蓋、item_revenue/transaction_id 僅 purchase 且高覆蓋、traffic_source 大多非空；若 transaction_id 覆蓋率過低 → `orders_count` 語意降級為「購買事件日計數」並改欄位註解，schema 不變）。
4. **單日 shard 位元組數與全窗總量**（dry-run 92 天加總；預設傾向：單日 ≪ 512 MiB、全窗個位數 GB——若單日超出，調 `pipeline.yaml` 兩個護欄值，護欄機制不變）。
5. **Airflow 3.2 `end_date` 端點含入行為**（預設傾向：`end_date` 當日 run 會排——若實測排到 2021-01-30 為止，`end_date` 改 `2021-02-01` 補端點，一行修正）。
6. **`ga_session_id` null 比例**（預設傾向：極低——sessions mart 的排除量級誠實寫進 mart description 的數字位）。
7. **google-cloud-bigquery 3.42.2 與 `apache/airflow:3.2.2` base image 的依賴相容**（protobuf/grpcio 版本域；預設傾向：相容——`uv pip compile` 一次定 lock，image 內 pin，同 P1 實查 4 手法）。

---

## 13. known-limits（誠實段）＋ 落地後校驗

**known-limits（README 全列）**：
1. **靜態歷史資料集**：觀測窗固定 2020-11～2021-01，回放收斂後管線進入穩態（不再有新 run）。「daily 排程」展示的是形狀與冪等紀律，不是持續進料——這是公開可分享性（不用 area02 客戶機密）換來的刻意取捨。
2. **回放是一次性 3–6 小時背景作業**（92 run 串行）；單日可隨時 clear 重放。
3. **只含漏斗事件**：`page_view`/`session_start` 等無 item 事件不在地基白名單，`gold_ga4_sessions` 是「漏斗活躍 session」而非 GA 完整 session 集、`session_start_ts/end_ts` 是漏斗事件跨度。P7 若需全 session 事實，開 additive 新 Silver 表（如 `silver.ga4_sessions_v1`），不改本合約。
4. **`user_pseudo_id` 是裝置級匿名 ID**（Google 已去識別）：跨裝置同人無法縫合——對推薦/RFM demo 無礙，對「真實身分圖」是能力邊界，如實敘述。
5. **金額欄承 GA4 export 的 float 精度**（非 decimal 記帳精度）；分析用途足夠，README 註記。
6. **`first_touch_source/medium` 是使用者首觸**（user-scoped），非 session 級來源歸因。
7. **item 語意 embedding 不在地基**（開放問題 4 收斂）：`gold_ga4_item_catalog` 只落結構化文字欄當 embedding 輸入源；向量化與 pgvector 落點屬 P6 召回 spec 的演算法決策。

**落地後校驗（design 自檢，對精確度契約 8 條）**：
- ①開放問題 7 題全收斂為單一決定（§1/§3–§7），零 TBD/兩案並陳；實查點全部帶預設傾向與判準（§12）。
- ②新引入套件唯一（google-cloud-bigquery 3.42.2，PyPI 當日查證）；chart values 形狀 context7 查證；其餘沿用 P1 已查證 pin（§0）。
- ③資料合約欄位級：Silver 1 表（§4，PK/分區/型別全列）+ Gold 4 表（§5，粒度/欄位/定義全列），皆標穩定合約與 additive-only 政策。
- ④部署形狀具體：DAG args 逐項（§7）、Helm values 逐鍵（§8）、Makefile target 全文（§8）、exporter 查詢 SQL（§9）、檔案佈局（§2）。
- ⑤沿用慣例明講出處：Bronze 決定性 key（P1 §3）、Silver 雙寫 loader（P1 §5）、dbt 分層與 schema 落點（P1 §6）、tag+selector 隔離（留言 §6）、secret 命令式冪等（P0 §7/P2 §3.5）、右尺寸 Python Silver（P3 先例）。
- ⑥取材界線表（§10）逐素材列「取邏輯 vs 重造工程層」；資料源只用公開 sample，area02 零進入。
- ⑦硬約束貫徹：地基零 ClickHouse/Redis/Flink、零線上端點（前端走 P4 匯出合約，§5 末）、additive-only（零觸碰 YouTube 5 表與主線 DAG）、SA 走 Secret volume 不硬編碼、M4 界線（BQ 萃取 IO-bound，k8s pod 即可，不涉 GPU）、非互動零提問。
- ⑧每步可測：單元測試分層（§11）、dbt DQ 合約（§6）、`make ga4-verify` 7 步可執行驗收（含 user×item×event 三角查詢、冪等、主線無損、成本護欄斷言）。
