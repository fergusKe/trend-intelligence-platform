# P1 資料管線 — 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) + **P0 design**（`2026-07-08-P0-platform-foundation-design.md`，沿用其平台/GitOps/CI 慣例）→ `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P1-data-pipeline-design.md` → （plan 延後）。
> **精確度要求**：每個開放問題在 design 收斂成明確決定；技術選型具體到工具版本、資料表 schema、DAG 結構、檔案路徑。
> **定位**：P1 是**資料層（DE）**——平台的地基。把 YouTube 熱門趨勢資料從 ingest 打到可查詢的 Gold 層，全部跑在 P0 的 k8s 上、用 P0 的 GitOps 部署、被 P0 的 Prometheus/Grafana 監控。這是「資料工程師」JD 的主戰場。

## 為什麼（問題）
NORTH_STAR 定案主幹 = YouTube。P1 要交付一條**現代 Lakehouse ELT 管線**：YouTube API 每小時抓多地區熱門影片 → Bronze（原始）→ Silver（清洗）→ Gold（可查詢 marts），Airflow 編排、dbt 建模與資料品質測試。**這條管線在 `yt-trending-platform` 已經有一個很完整的 docker-compose 版本**——P1 的核心工作是**把它收斂、清理、搬上 P0 的 k8s 平台**（不是從零造），並補齊資料品質與可觀測性，讓它成為 P2（ML）的乾淨資料來源。

## 已鎖定決策（NORTH_STAR，勿翻案）
- **主幹資料 = YouTube Data API v3**（`chart=mostPopular`，多地區）。PTT 爬蟲留給 P3，不在 P1。
- **Lakehouse**：MinIO（S3 相容，**部署在叢集內**）+ Apache Iceberg（Bronze/Silver）+ Spark（Bronze→Silver）+ dbt（Silver→Gold）。
- **儲存**：Gold 落 **PostgreSQL**（不用 ClickHouse）。
- **編排**：**Apache Airflow**（唯一排程器，不加 Celery/APScheduler 當業務排程）。
- **串流 Kafka = 本階段不引入**（P1 走批次；要用留到後期選配，NORTH_STAR 紀律「要用才加」）。
- **部署**：沿用 P0 的 GitOps（ArgoCD app-of-apps）+ GitHub Actions CI + 雲端可攜 manifest。

## 已查到的事實（recon，免重探；唯讀取材別重造）
主範本 `data-workshop/fergus/yt-trending-platform`（recon 判定為「最乾淨現代的 lakehouse 骨架」，13 服務 docker-compose）：
- **ingest**：`ingestion/youtube_api.py` + Airflow hook `airflow/plugins/hooks/youtube_hook.py`（`YouTubeToMinioHook`，抓 12 地區 mostPopular → MinIO Bronze 原始 JSON/Iceberg）。
- **編排**：`airflow/dags/yt_trending_pipeline.py`（Airflow 3.2，compose 版是 **CeleryExecutor + Redis**——搬 k8s 要重新選 executor，見開放問題）。
- **Bronze→Silver**：`spark/jobs/bronze_to_silver.py`（PySpark 4.x：去重、衍生 `like_ratio`/`engagement_rate`）→ Silver Parquet/Iceberg。
- **Silver→Gold**：`dbt/models/marts/*`（dbt-postgres 5 個 mart：`trending`/`channel`/`category`/`velocity_snapshots`/`velocity_deltas`）→ PostgreSQL 16 Gold。含 dbt DQ 測試。
- **可觀測性**：`monitoring/` + 自訂 `metrics_exporter.py` + postgres-exporter（P0 已裝 kube-prometheus-stack，P1 接上即可）。
- **velocity 演算法**：`velocity_deltas.sql`（時間窗觀看數增量排行）——時序趨勢的核心賣點，保留。

雙胞胎範本 `data-workshop/fergus/ga4-analytics-platform`（同 Airflow3+dbt medallion+extractor blueprint）：`airflow/dags/ga4_pipeline.py` 的 extractor 模式（把 warehouse gold 抽到 Postgres）、`dbt/models/{staging,bronze,silver,gold}/` 四層命名可交叉參考。

**注意**：兩範本都是 docker-compose；P1 要搬上 **k8s（P0）**，executor/儲存/Spark 執行方式都要重新為 k8s 決定（見開放問題），不是照抄 compose。

## 範圍（簇；Fable 5 定簇內細節與先後）

**P1-1 YouTube ingest（API → Bronze）**
- Airflow DAG 每小時抓多地區 mostPopular → MinIO Bronze（Iceberg 或原始 JSON）。取材 `youtube_hook.py`。
- **開放問題**：抓幾個地區（12 全抓 vs 精選 3-5 控 quota）？YouTube API quota 管理（每日 10k units 上限怎麼配、超額退避）？Bronze 存原始 JSON 還是直接 Iceberg？API 金鑰用 k8s Secret（沿用 P0 secret 慣例）？ingest 失敗的重試/告警（Airflow retry + Prometheus）？

**P1-2 MinIO + Iceberg（Lakehouse 儲存層）**
- 叢集內部署 MinIO（S3 相容）、Iceberg catalog（哪種 catalog？）、Bronze/Silver bucket 佈局。
- **開放問題**：MinIO 部署方式（Helm chart vs manifest，單節點 demo 夠嗎，PVC storage class 沿用 P0 雲端可攜約束）？Iceberg catalog 用哪種（REST catalog / JDBC catalog on Postgres / Hive）？Bronze/Silver 的 bucket + table 佈局？MinIO 由 ArgoCD 管（GitOps）？

**P1-3 Spark（Bronze → Silver）**
- PySpark job 去重 + 衍生指標（like_ratio/engagement_rate）→ Silver Iceberg。取材 `bronze_to_silver.py`。
- **開放問題**：Spark 在 k8s 怎麼跑（**Spark on k8s operator** vs `spark-submit --master k8s` vs 單純 PySpark 跑在一個 pod）？——這是 P1 最關鍵的 k8s 決策，要衡量「展示 Spark-on-k8s 能力」vs「過度工程」（資料量其實不大）。Spark job 由 Airflow 觸發（KubernetesPodOperator / SparkKubernetesOperator）？Iceberg 讀寫的 Spark 設定？

**P1-4 dbt（Silver → Gold）+ 資料品質**
- dbt-postgres 把 Silver 建成 Gold marts（trending/channel/category/velocity）+ dbt tests（not_null/unique/relationships/自訂 volume anomaly）。取材 `dbt/models/marts/*`。
- **開放問題**：dbt 在 k8s 怎麼跑（Airflow KubernetesPodOperator 跑 dbt image）？Gold 的 Postgres 部署（沿用/共用哪個 Postgres，P0 有沒有已裝的）？medallion 分層命名（staging/silver/gold 對齊 ga4 範本）？DQ 測試涵蓋哪些（列出關鍵 test）？velocity_deltas 的 SQL 保留？

**P1-5 Airflow 編排（把上面串成 DAG）**
- Airflow 部署在 k8s + 一條主 DAG（ingest → spark silver → dbt gold → DQ test），依賴設計、backfill、排程。
- **開放問題**：Airflow 在 k8s 的 **executor（KubernetesExecutor 最 k8s-native，每 task 一 pod vs CeleryExecutor+Redis 照搬 compose）**？Airflow 部署用官方 Helm chart？metadata DB（獨立 Postgres）？DAG 怎麼進叢集（git-sync sidecar vs baked image）？由 ArgoCD 管？backfill 策略？

**P1-6 資料層可觀測性 + 對外查詢**
- 接上 P0 的 Prometheus/Grafana：管線指標（DAG 成功率、資料新鮮度、每地區筆數、DQ 失敗）+ 一個 Gold 資料的 Grafana dashboard。可選：一個極簡查詢 API 或直接 Grafana 讀 Postgres。
- **開放問題**：管線指標怎麼出（Airflow StatsD→Prometheus / 自訂 exporter 取材 `metrics_exporter.py`）？「資料新鮮度」「DQ 失敗」怎麼變成 Prometheus 指標 + 告警？P1 要不要做前端/API（NORTH_STAR 的 Next.js dashboard 是選配，P1 可先用 Grafana 讀 Postgres 展示，前端留後期）？

## 設計方向約束（硬性，寫進 design）
- **沿用 P0 慣例**：服務進 `platform/`（或 P0 design 定的 apps 目錄）、走 ArgoCD sync、CI 走 GitHub Actions→GHCR、manifest 雲端可攜。不自創另一套部署方式。
- **一個工作一個工具**：排程只 Airflow、DB 只 Postgres、無 ClickHouse、無第二排程器、Kafka 不引入。
- **搬遷不照抄**：yt-trending 是 compose 版範本，P1 要為 k8s 重新決定 executor/Spark/儲存的執行方式，並**清理範本的重複碼**（recon 指出 yt-trending 有 `data_pipeline.py` 與單獨 daily DAG 職責重疊之類問題，搬遷時去重）。
- **Gold 是 P2 的資料合約**：Gold marts 的 schema 要穩定、有文件——P2 的模型（影片表現預測、RAG）會吃它。design 要明列 Gold 表結構當**對 P2 的介面合約**。
- **可獨立 demo + 可重現**：接在 P0 的 `make cluster-up` 之後，`make pipeline-up` 或 ArgoCD sync 後能跑出一條有資料的管線。
- **每步可測**：dbt tests + Airflow DAG 測試 + ingest 單元測試。

## 交付與驗收（design 要回答的）
- 每簇開放問題**收斂成決定**或標「plan 前需實查」。尤其三個 k8s 關鍵決策要拍板：**Airflow executor、Spark on k8s 執行方式、MinIO/Iceberg catalog**。
- 具體資料模型：Bronze/Silver/Gold 各層 schema，**Gold marts 明列（當 P2 合約）**。
- DAG 結構圖 + 依賴 + 排程 + backfill。
- 部署形狀：各元件（MinIO/Airflow/Spark/dbt/Postgres）在 k8s 怎麼裝、怎麼被 ArgoCD 管。
- 端到端驗收清單（跑一輪 → Bronze 有原始資料 → Silver 有清洗 → Gold 有 marts → dbt tests 綠 → Grafana 看得到新鮮度）。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design。**本階段只出 spec，plan 延後**。對齊 [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) P1 定義 + P0 design 的平台慣例。
