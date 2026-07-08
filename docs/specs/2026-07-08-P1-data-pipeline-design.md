# P1 資料管線 — Design（Fable 5 產出）

> **狀態**：design 完成，待 Opus 寫 implementation plan。
> **上游**：[`2026-07-08-P1-data-pipeline-brief.md`](2026-07-08-P1-data-pipeline-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) + [`2026-07-08-P0-platform-foundation-design.md`](2026-07-08-P0-platform-foundation-design.md)。已鎖定決策（YouTube API 主幹 / MinIO+Iceberg+Spark+dbt / Gold 落 Postgres / 排程只 Airflow / Kafka 不引入 / 沿用 P0 GitOps）全部沿用，未翻案。
> **版本查證日**：2026-07-08（版本 pin 皆當日對官方源——helm index.yaml / PyPI / Maven Central / Docker Hub / GitHub releases——查證，非記憶）。
> **精確度收緊 pass（2026-07-08）**：§0 版本 12 項重新對源覆核（全符，零改動）；§2 新增 k8s 資源名/DNS/chart repo 合約表；§3 補 pipeline.yaml 欄位形狀、retry default_args、chart `secret:` 注入形狀、categories bronze 全 key；§4 init SQL 明細化（4 角色/default privileges/public schema 權限）、minio-root key 定為 AWS 標準名、pyiceberg SQLAlchemy URI；§5 SparkApplication 命名/TTL/SA/envFrom、loader DSN 與 `execute_values`；§6 profiles.yml 具體值、staging schema 落點（`generate_schema_name` 覆寫）、dbt_test command、檔案清單、**修 categories freshness 欄位矛盾**（該表無 `ingested_at`→`updated_at`）；§7 ingress/metadataSecretName 確切 values（context7 查證）、start_date/dagrun_timeout、reprocess params 形狀；§8 Secret key 名逐把列明 + 新增 env 注入合約表；§9 exporter 三條自訂查詢 SQL、dashboard ConfigMap 名；§12B 實查 1/2/4 補預設傾向或收窄。**§6a 五表合約、§3 Bronze key 決定性、§5 Silver loader 模式、§8 secret 姿態之錨點與契約內容原樣未動**；所有鎖定選型/章節編號/表欄命名不變。
> **參考素材**：`yt-trending-platform`（主範本，唯讀取材）+ `ga4-analytics-platform`（extractor 模式與 medallion 命名交叉參考）。範本為 docker-compose 版，本設計**搬遷不照抄**（§10 列範本債清理清單）。

---

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證方式 |
|---|---|---|
| Airflow 官方 Helm chart | **1.22.0**（appVersion **3.2.2**） | `airflow.apache.org/index.yaml` |
| Airflow（自訂 image base） | **`apache/airflow:3.2.2`**（跟 chart appVersion 對齊，不追 PyPI 3.3.0） | 同上 |
| Kubeflow spark-operator Helm chart | **2.5.1**（appVersion 2.5.1） | `kubeflow.github.io/spark-operator/index.yaml` |
| Spark（job image base） | **`spark:4.0.2-python3`**（Docker 官方 library image） | Docker Hub tags |
| iceberg-spark-runtime-4.0_2.13 | **1.11.0** | Maven Central |
| pyiceberg | **0.11.1**（extras `[s3fs,sql-postgres]`） | PyPI |
| dbt-postgres | **1.10.2**（讓它自解析相容的 dbt-core；見 §12 實查 4） | PyPI |
| MinIO | **`minio/minio:RELEASE.2025-09-07T16-13-09Z`** | Docker Hub tags |
| MinIO mc（bucket init Job） | **`minio/mc:RELEASE.2025-08-13T08-35-41Z`** | Docker Hub tags |
| PostgreSQL | **`postgres:16.14`** | Docker Hub tags |
| postgres_exporter | **v0.20.1**（`quay.io/prometheuscommunity/postgres-exporter`） | GitHub releases |
| hadoop-aws / aws-java-sdk-bundle jars | 對齊 spark:4.0.2 內建 Hadoop（範本用 3.4.1 / 1.12.780；見 §12 實查 5） | 範本 + 待落地校準 |

CI actions 沿用 P0 pin（checkout@v5 / setup-uv@v4 / buildx@v3 / login@v3 / build-push@v6，runner 內建 `yq`）。

---

## 1. 三個 k8s 關鍵決策（先拍板，細節在各簇）

### ① Airflow executor = **KubernetesExecutor**

| 候選 | 判定 |
|---|---|
| **KubernetesExecutor** ✅ | 每 task 一個 ephemeral pod，k8s-native、零常駐 worker、失敗隔離好；直接砍掉範本的 Redis + Celery worker 兩個常駐服務（「一個工作一個工具」——k8s 本身就是任務執行的資源層，不需要第二套 worker 佇列）。task pod 生滅在 `kubectl get pods -w` 可見，demo 價值高。 |
| CeleryExecutor+Redis（照搬 compose） | 淘汰：引入 Redis = 第二個佇列工具，違反工具紀律；常駐 worker 在 kind 上白耗資源；k8s 上屬「不必要的搬家不改裝」。 |
| LocalExecutor | 淘汰：任務全擠在 scheduler pod，失去 k8s 排程故事，且與 dbt/Spark 的 pod 化任務不一致。 |

### ② Spark on k8s = **Kubeflow spark-operator（SparkApplication CRD）+ Airflow `SparkKubernetesOperator`**

| 候選 | 判定 |
|---|---|
| **spark-operator** ✅ | (a) SparkApplication 是**宣告式 CRD**，與 ArgoCD/GitOps 敘事同構；(b) 業界標準的 Spark-on-k8s 途徑，Airflow provider（`cncf-kubernetes`，base image 內建）有第一級 `SparkKubernetesOperator` 支援；(c) 成本是**每次執行 ephemeral** 的 driver+executor pod，常駐的只有 operator controller 一個小 pod（~100m/200Mi），不違反「拒常駐叢集」精神（NORTH_STAR：本專案 k8s 常駐本來就是目的）；(d) 若不用分散式跑法，Spark 這個已鎖定工具本身就失去存在理由（400 rows/hr 用 pandas 就夠）——**要嘛用 k8s 原生方式跑 Spark，要嘛不該有 Spark**；鎖定已定，故選前者。 |
| `spark-submit --master k8s://` 從 Airflow pod 發 | 淘汰：Airflow image 得塞整套 Spark binary（image 肥大）、driver pod 由 spark-submit 命令式拉起（脫離宣告式）、RBAC 與 log 取回都要手工；operator 就是為了解決這些而生。 |
| 單 pod PySpark `local[*]`（KubernetesPodOperator） | 淘汰（但誠實記錄）：以資料量論這是最右尺寸的解，然而它讓「Spark on k8s」變成「一個裝了 pyspark 的容器」，DE JD 展示價值歸零。**右尺寸化落在資源配置而非架構**：executor `instances: 1`、driver/executor 各 1 cpu / 1.5Gi，總 footprint 與單 pod 方案同量級，擴縮是改一個宣告式欄位。README 面試敘事照實寫這段取捨。 |

**過度工程界線**：不開 dynamicAllocation、不裝 history server、不接 Spark Connect——資料量撐不起，要用才加。

### ③ MinIO = **plain kustomize manifests（單節點 StatefulSet）**；Iceberg catalog = **JDBC catalog on 共用 Postgres**

| 候選 | 判定 |
|---|---|
| **MinIO plain manifest** ✅ | 完全複用 P0 的「服務接入契約」（kustomize `k8s/` + 一個子 Application 檔），diff 透明、零 Helm 相依。單節點 + 單 PVC（10Gi、**不寫 storageClassName**）對 demo 足夠；bucket 初始化用 `mc` Job（ArgoCD PostSync hook）。 |
| MinIO 官方 Helm chart | 淘汰：多一層工具、values 面積大；新版 MinIO 社群 console 功能已被上游閹割，chart 的 console 相關 values 價值下降。 |
| MinIO Operator | 淘汰：多租戶場景的工具，單租戶 demo 是純過度工程。 |
| Bitnami chart/image | 淘汰：2025-08 Bitnami 授權變動後鏡像轉 `bitnamilegacy`，不再是可長期 pin 的免費源（範本的 `bitnami/spark` 也一併換成官方 `spark:` image）。 |
| **Iceberg JDBC catalog（Postgres）** ✅ | 零新增服務：catalog 元資料落在既有 Postgres（`lakehouse` db），Spark（iceberg-spark-runtime JDBC catalog）與 pyiceberg（`sql` catalog，同 `iceberg_tables` 表佈局）都吃得到；也是範本既有選型，搬遷成本最低。與「DB 只 Postgres」紀律同向。 |
| REST catalog | 淘汰：`apache/iceberg-rest-fixture` 明文是測試用 fixture；生產級 REST catalog（Polaris/Lakekeeper/Gravitino）每個都是一套新常駐服務 + 自己的儲存，違反「一個工作一個工具」。README 註記：多引擎共讀需求出現時（P2 之後），JDBC→REST 是宣告式設定搬移，Iceberg 表本體不動。 |
| Hive Metastore | 淘汰：再養一個 JVM 常駐服務 + 一個 schema，2026 年已無新專案採用理由。 |

---

## 2. 總體形狀

### 資料流

```
YouTube Data API v3 (videos.list chart=mostPopular ×8 regions, hourly)
        │  Airflow 動態映射 task ×8（KubernetesExecutor pod）
        ▼
[Bronze] MinIO s3://bronze/youtube_trending/region=XX/date=YYYY-MM-DD/hour=HH/snapshot.json
        │  （原始 JSON，一 region-hour 一物件，重跑覆寫 = 冪等）
        ▼  SparkApplication（spark-operator，driver+1 executor，per-run ephemeral）
[Silver] Iceberg 表 lakehouse.silver.video_snapshots（MinIO s3://silver/warehouse，
        │   PARTITIONED BY (region, hours(captured_at))，overwritePartitions = 冪等）
        │  pyiceberg 掃該小時 → psycopg2 UPSERT（ga4 範本 extractor 模式）
        ▼
[Silver serving] Postgres lakehouse.silver.video_snapshots（dbt 唯一讀取來源）
        │  dbt run（KubernetesPodOperator，dbt-postgres）
        ▼
[Gold]  Postgres lakehouse.gold.gold_*（5 marts = P2 資料合約）→ dbt test → Grafana
```

**架構修正（範本最大地雷）**：範本的 Spark 把 Silver 寫成「MinIO 上的 Iceberg」，但 dbt-postgres 與前端卻直接 `FROM silver.*` 讀 **Postgres**——兩者根本不相通，Gold 層永遠是空的（範本斷線，詳 §10）。本設計補上**顯式的 Silver serving 載入步**：Iceberg 是 lakehouse 正本（P2 ML 用 Spark/pyiceberg 讀它），Postgres `silver` schema 是 dbt 的 serving 副本，由管線內的 loader task 以 UPSERT 冪等維護——這正是 ga4 雙胞胎範本「warehouse gold 抽到 Postgres」的 extractor 模式，搬到 silver 邊界使用。

### 目錄結構（頂層 domain 目錄依 NORTH_STAR；接入方式依 P0 服務接入契約）

```
ingestion/
└── youtube/                      # 純 Python 套件（被 Airflow image 安裝），無自己的部署
    ├── pyproject.toml
    ├── src/yt_ingest/
    │   ├── client.py             # YouTube API：videos.list / videoCategories.list（httpx）
    │   ├── bronze.py             # 寫 MinIO bronze（boto3，決定性 key）
    │   └── categories.py         # categories 抓取 + Postgres upsert
    └── tests/                    # 單元測試（HTTP mock、key 佈局、quota fail-fast）
orchestration/
└── airflow/
    ├── Dockerfile                # FROM apache/airflow:3.2.2 + yt_ingest + pyiceberg + psycopg2 + boto3/httpx
    ├── dags/
    │   ├── yt_trending_hourly.py # 主 DAG（§7）
    │   ├── yt_categories_daily.py
    │   ├── yt_reprocess_range.py # 手動 backfill/重處理（§7）
    │   ├── config/
    │   │   ├── pipeline.yaml     # regions 等管線常數（單一真源）
    │   │   └── images.yaml       # spark-job / dbt image tag（CI bump 的檔，git-sync 送達）
    │   └── templates/
    │       └── spark_silver.yaml # SparkApplication 模板（SparkKubernetesOperator 讀）
    └── tests/                    # DagBag import、依賴斷言、config 一致性（§11）
lakehouse/
├── minio/k8s/                    # kustomization + statefulset + service + bucket-init job
├── postgres/k8s/                 # kustomization + statefulset + service + init-sql configmap
│                                 #  + postgres-exporter deployment + 自訂查詢 configmap + servicemonitor
├── spark/
│   ├── Dockerfile                # FROM spark:4.0.2-python3 + iceberg/hadoop-aws jars + job 碼
│   ├── jobs/silver_job.py        # Bronze→Silver（§5）
│   ├── tests/                    # 轉換邏輯單元測試（pyspark local，CI 跑）
│   └── k8s/                      # rbac.yaml：airflow worker SA 對 data ns 的 SparkApplication 權限
└── dbt/
    ├── Dockerfile                # python:3.12-slim + dbt-postgres==1.10.2 + 專案本體
    ├── dbt_project.yml / profiles.yml
    ├── models/staging/…  models/marts/…  tests/…（§6）
platform/
├── argocd/apps/                  # ★ 新增 5 個子 Application（下表）
│   ├── lakehouse-postgres.yaml   # wave 3
│   ├── lakehouse-minio.yaml      # wave 3
│   ├── spark-operator.yaml       # wave 4（Helm 2.5.1）
│   ├── airflow.yaml              # wave 5（Helm 1.22.0）
│   └── pipeline-monitoring.yaml  # wave 6（directory 型）
└── monitoring/pipeline/          # dashboards ×2（ConfigMap）+ PrometheusRule + statsd ServiceMonitor
.github/workflows/
├── airflow-ci.yaml  spark-ci.yaml  dbt-ci.yaml   # 皆複製 hello-ci 模式（§8）
Makefile                          # += pipeline-secrets / pipeline-verify / pipeline-trigger
scripts/verify-pipeline.sh        # 端到端驗收（§9）
```

### Namespace 與 sync-wave（接續 P0 的 0/1/2）

| wave | Application | namespace | 內容 |
|---|---|---|---|
| 3 | lakehouse-postgres、lakehouse-minio | `data` | 儲存底座（Airflow/Spark/dbt 全依賴） |
| 4 | spark-operator | `spark-operator`（jobs 跑在 `data`） | Helm chart 2.5.1，`spark.jobNamespaces: [data]` |
| 5 | airflow | `airflow` | Helm chart 1.22.0（KubernetesExecutor + git-sync） |
| 6 | pipeline-monitoring | `monitoring` | dashboards / PrometheusRule / ServiceMonitor |

所有 Application 的 syncPolicy 沿用 P0 標準：`automated {prune, selfHeal}` + `CreateNamespace=true` + retry；含 CRD 依賴的資源沿用 `SkipDryRunOnMissingResource=true` 註解手法（SparkApplication 模板不進 ArgoCD——它由 Airflow 在 runtime 提交，不是 GitOps 管的靜態資源）。

### k8s 資源名 / DNS 合約（全設計引用此表，不另創名）

| 資源 | 名稱 | ns | 叢集內位址 |
|---|---|---|---|
| MinIO StatefulSet + Service（ClusterIP） | `lakehouse-minio` | data | `http://lakehouse-minio.data.svc:9000`（S3 API；全設計唯一 S3 endpoint 字面值） |
| MinIO bucket-init Job | `minio-bucket-init` | data | —（PostSync hook，跑完即刪） |
| Postgres StatefulSet + Service（ClusterIP） | `lakehouse-postgres` | data | `lakehouse-postgres.data.svc:5432` |
| postgres-exporter Deployment + Service | `lakehouse-postgres-exporter` | data | `:9187`（ServiceMonitor 對準） |
| PVC（兩個 StatefulSet 的 volumeClaimTemplate） | `data`（模板名） | data | 各 10Gi，無 storageClassName |
| Helm release：spark-operator | `spark-operator`（= Application 名） | spark-operator | chart repo `https://kubeflow.github.io/spark-operator` |
| Helm release：airflow | `airflow`（= Application 名） | airflow | chart repo `https://airflow.apache.org` |
| Spark job 側 ServiceAccount（chart 依 `spark.jobNamespaces: [data]` 自建） | `spark-operator-spark`（`<release>-spark` 命名規則，context7 查證；§12 實查 2 落地校驗） | data | SparkApplication `driver./executor.serviceAccount` 引用 |

ArgoCD Application 名 = `platform/argocd/apps/` 檔名去 `.yaml`（`lakehouse-postgres`／`lakehouse-minio`／`spark-operator`／`airflow`／`pipeline-monitoring`）。

**Ingress**：`airflow.localtest.me`（Airflow UI，chart ingress values）、既有 `grafana.localtest.me`。MinIO console 不開 ingress（新版功能閹割後價值低，除錯用 port-forward）。全部維持 P0 鐵律：`ingressClassName: nginx`、零控制器專屬 annotation。

---

## 3. P1-1 YouTube ingest（決定）

| 開放問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| 抓幾個地區 | **8 區：`TW,JP,KR,HK,US,GB,SG,AU`**，定義在 `dags/config/pipeline.yaml` 單一真源；dbt `accepted_values` 與其一致性由 pytest 守門（§11）。`pipeline.yaml` 確切形狀：`regions: [TW, JP, KR, HK, US, GB, SG, AU]`、`max_results: 50`、`bronze_bucket: bronze`、`s3_endpoint: http://lakehouse-minio.data.svc:9000`（§2 資源名合約）——DAG 讀此檔，程式碼不 hardcode 任何一項 | 範本有 8 區（DAG 預設）vs 12 區（.env/dbt test）漂移——收斂成一處定義。quota 上 12 區也毫無壓力，選 8 是控制每小時 fan-out pod 數與 dashboard 面板密度；加區 = 改一行 YAML。 |
| quota 管理 | **不做 quota 額度系統**。數學：videos.list = 1 unit/call，8 區 × 24h = 192 units/day + categories 8 units/day ≈ **200 / 10,000（2%）**。防護只做兩件：①HTTP 403 `quotaExceeded`/`dailyLimitExceeded` → raise `AirflowFailException`（**fail-fast 不重試**，重試燒 quota 又必然再失敗）②其他 HTTP/網路錯誤交給 Airflow retry（3 次、exponential backoff）。 | 範本的 quota Counter 是死碼（從未被呼叫）且 hardcode 每次 2 units——刪除。用量監控間接由 freshness 告警涵蓋（quota 爆 → 資料停 → 告警）。 |
| 分頁 | **不分頁，每區 top 50**（`maxResults=50`，單次呼叫） | 範本同款；trending 分析的資訊量集中在頭部，200 名長尾對 marts 與 P2 特徵無增益。 |
| Bronze 格式 | **原始 JSON**（API response 原文 + `_metadata` 信封），**不是 Iceberg** | Bronze 的職責是不可變原始層、可重放；在 ingest task 裡寫 Iceberg 得把 Spark/pyiceberg 拖進 ingest 邊界，層次糊掉。Iceberg 從 Silver 開始。 |
| Bronze key 佈局 | `s3://bronze/youtube_trending/region=<XX>/date=<YYYY-MM-DD>/hour=<HH>/snapshot.json`——**一 region-hour 一個決定性物件**，key 由 Airflow `logical_date` 導出（非 `now()`） | 重跑同一 task = 覆寫同一物件 = **ingest 冪等**（範本用 `now()` 時間戳命名，重跑會堆重複檔）。Hive 式 partition key 讓 Spark 讀指定小時零掃描。 |
| API 金鑰 | k8s Secret `youtube-api`（`airflow` ns），`make pipeline-secrets` 命令式建立（P0 §7 姿態：不進 git），經 Airflow chart 的 `secret:` values 注入所有 task pod 環境變數。確切 values 形狀（context7 對 chart 文件查證）：`secret: [{envName: YOUTUBE_API_KEY, secretName: youtube-api, secretKey: YOUTUBE_API_KEY}, …]`（minio-root 的兩把 AWS key 同列注入，見 §8 env 合約表） | 沿用 P0「第一個真 secret 用 kubectl create secret 起步」的既定策略；不引入 sealed-secrets（要用才加）。 |
| 失敗重試/告警 | Airflow `retries=3` + exponential backoff（quota 錯誤除外，見上）；確切 default_args：`retries=3, retry_delay=timedelta(minutes=1), retry_exponential_backoff=True, max_retry_delay=timedelta(minutes=10)`。單一 region 失敗不擋其他 region（動態映射 task 彼此獨立），下游 Spark 用 `trigger_rule="all_done"` 收到什麼算什麼、輸入為空自然 fail；系統性失敗由 freshness PrometheusRule 告警（§9） | mostPopular API 無歷史——某 region-hour 錯過就是永久缺口，重試窗口內救不回就接受缺口，這是**資料源特性**，寫進 README known-limit。 |
| 實作形狀 | 重寫進 `ingestion/youtube/`：`client.py`（httpx、顯式 timeout、錯誤分類）+ `bronze.py`（boto3 put_object）。DAG 用 `PythonOperator` + **動態任務映射** `.expand(region=…)` | 範本的 `YouTubeToMinioHook` 有死掉的多 region 迴圈（永遠只收到單元素 list）；`urllib` 換 httpx（驗證過的成熟庫，錯誤語意清楚）。動態映射是 Airflow 3 的正規 fan-out，比範本的靜態 TaskGroup 迴圈乾淨。 |

**Categories 維度**：從 hourly 主線抽離成 `yt_categories_daily`（@daily）——categories 幾乎不變，範本卻每小時抓（浪費 quota）且 bronze 物件按月覆寫、**從未晉升到 silver**（下游 `stg_youtube_categories` 讀空表，範本斷線之一）。新 DAG：抓 8 區 categories → bronze `s3://bronze/youtube_categories/region=<XX>/date=<YYYY-MM-DD>/categories.json`（同 §3 決定性 key 紀律，date 由 logical_date 導出）→ 直接 UPSERT Postgres `silver.youtube_categories`（維度小到不需要過 Spark/Iceberg——刻意決定，寫進 model 文件）。

---

## 4. P1-2 MinIO + Iceberg（決定）

部署與 catalog 選型已在 §1③ 拍板。落地細節：

| 項目 | 決定 |
|---|---|
| MinIO 形狀 | 單 replica StatefulSet（`data` ns，資源名見 §2 合約）+ PVC 10Gi（**無 storageClassName**，kind 用預設 local-path，EKS 換 class 時 values 級改動）+ ClusterIP Service :9000。root 憑證從 Secret `minio-root`（key = `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`，§8）：容器 env `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` 各以 `valueFrom.secretKeyRef` 映射這兩把 key——同一份 Secret 同時餵 MinIO 本體與所有 S3 client，不維護兩套憑證。 |
| Bucket 初始化 | `mc` Job（ArgoCD **PostSync hook** + `hook-delete-policy: HookSucceeded`）：`mc mb --ignore-existing local/bronze local/silver`——冪等，每次 sync 後自校。 |
| Bucket 佈局 | `bronze/`：原始 JSON（§3 key 佈局）。`silver/`：Iceberg warehouse root `s3a://silver/warehouse`（表資料+metadata 都在其下）。**修正範本 bug**：範本 warehouse 設在 `s3a://bronze/iceberg-warehouse` 而表 LOCATION 又指 `s3a://silver/…`，跨桶錯置——收斂為 warehouse 單一根，表不再指定顯式 LOCATION。無 gold bucket（Gold 在 Postgres）。 |
| Iceberg catalog | JDBC catalog：catalog 名 `lakehouse`，backing = Postgres `lakehouse` db（`iceberg_tables` / `iceberg_namespace_properties` 由 Iceberg 自建於 `public` schema——連線角色用 `pipeline_writer`，init SQL 補 `GRANT CREATE ON SCHEMA public TO pipeline_writer`，postgres:16 起 public 對非 owner 預設不可寫）。Spark conf：`spark.sql.catalog.lakehouse=org.apache.iceberg.spark.SparkCatalog`、`type=jdbc`、`uri=jdbc:postgresql://lakehouse-postgres.data.svc:5432/lakehouse`、`warehouse=s3a://silver/warehouse` + S3A endpoint（`fs.s3a.endpoint=http://lakehouse-minio.data.svc:9000`）/`fs.s3a.path.style.access=true`/憑證（env from Secret）。pyiceberg 側用 `sql` catalog：`uri=postgresql+psycopg2://pipeline_writer:…@lakehouse-postgres.data.svc:5432/lakehouse`（SQLAlchemy 形式）+ `s3.endpoint` 同上（同表佈局互通；§12 實查 3 落地驗一次）。 |
| Postgres 形狀 | 單 replica StatefulSet（`data` ns）+ PVC 10Gi（無 storageClassName）+ init SQL ConfigMap（`docker-entrypoint-initdb.d` 掛載，只在空 PVC 首次啟動執行），內容明細：①建 database `airflow`（owner `airflow` 角色）與 `lakehouse`；②`lakehouse` 內建 schema `silver`/`gold`；③角色四個——`airflow`（metadata 專用）、`pipeline_writer`（loader/categories 寫入者，owner `silver` schema）、`dbt_runner`（owner `gold` schema + `GRANT CREATE ON DATABASE lakehouse`，供 dbt 自建 `staging` schema）、`grafana_reader`（唯讀 gold）；④預設權限——`ALTER DEFAULT PRIVILEGES FOR ROLE pipeline_writer IN SCHEMA silver GRANT SELECT ON TABLES TO dbt_runner`、`ALTER DEFAULT PRIVILEGES FOR ROLE dbt_runner IN SCHEMA gold GRANT SELECT ON TABLES TO grafana_reader`（dbt 每 run 重建 table，靠 default privileges 而非一次性 GRANT，否則 grafana 讀第二輪起壞）。各角色密碼取自 Secret 注入的環境變數（§8 key 表）。**一套 Postgres 三個職責（Airflow metadata / Iceberg catalog / Silver serving+Gold）**——「DB 只 Postgres」的字面實踐；demo 規模無隔離需求，README 註記雲上拆法。 |
| ArgoCD 管理 | 兩者各一個 kustomize 目錄 + 子 Application（wave 3），與 hello 同款接入。 |

---

## 5. P1-3 Spark Bronze→Silver（決定）

執行方式已在 §1② 拍板（spark-operator + SparkKubernetesOperator）。job 本體（`lakehouse/spark/jobs/silver_job.py`，取材範本 `bronze_to_silver.py` 並修編）：

| 項目 | 決定 |
|---|---|
| 輸入 | 參數 `--date YYYY-MM-DD --hour HH`（Airflow 傳 `{{ data_interval_start }}` 導出值）：只讀 `s3a://bronze/youtube_trending/region=*/date=<D>/hour=<H>/*.json`，**顯式 schema 讀取**（複活範本死碼 `utils/schema.py` 的 StructType，關 schema 推斷）。 |
| 轉換 | explode items → 取 snippet/statistics/contentDetails 欄位（**新增 `description`**——範本漏抓，P2b RAG 的關鍵語料）→ cast 數值 LongType、`fillna(0)` → 衍生 `like_ratio = likes/views`、`engagement_rate = (likes+comment_count)/views`（views=0 時 0.0，同範本公式）→ `captured_at = date_trunc('hour', ingested_at)`。 |
| 去重鍵 | **`(video_id, region, captured_at)`——保留小時粒度**。範本用 `(video_id, region, trending_date)` 把粒度壓成日級，直接把 velocity（時間窗增量，本專案核心賣點）打死（一天只剩一筆，LAG 無從算起）——這是範本最實質的邏輯 bug，修正之。 |
| 輸出 | Iceberg 表 `lakehouse.silver.video_snapshots`，`PARTITIONED BY (region, hours(captured_at))`，寫入用 **`overwritePartitions()`**（動態分區覆寫）：重跑同一小時 = 覆寫該小時分區 = **冪等**。範本用 `.append()` + 每次全桶 glob，重跑必產生重複列——修正之。 |
| SparkApplication 規格 | `metadata.name: yt-silver-{{ data_interval_start.strftime('%Y%m%d%H') }}`（DNS-1123、每 run 決定性且唯一——重跑同 logical hour 先刪同名舊 app 再提交，operator 對同名 apply 會拒）、`mode: cluster`、`type: Python`、`sparkVersion: "4.0.2"`、driver 1 core/1.5Gi、executor `instances: 1`×1 core/1.5Gi、driver/executor `serviceAccount: spark-operator-spark`（§2 合約；§12 實查 2 校驗）、`restartPolicy: Never`（重試由 Airflow task 層負責，不雙層重試）、`timeToLiveSeconds: 3600` 清理已完成 app。憑證注入：driver/executor `envFrom.secretRef: minio-root`（key 即 AWS 標準名，§8）。image = `ghcr.io/<owner>/trend-intelligence-platform/spark-jobs:sha-*`（CI 產物）。模板放 `dags/templates/spark_silver.yaml`，`SparkKubernetesOperator` 提交到 `data` ns 並 watch 到終態；image tag 由 DAG 從 `config/images.yaml` 讀入注入。 |
| RBAC | `lakehouse/spark/k8s/rbac.yaml`：Role+RoleBinding 授 `airflow` ns 的 worker ServiceAccount 對 `data` ns 的 `sparkapplications` CRUD + `pods/log` 讀。spark-operator chart 以 `spark.jobNamespaces: [data]` 自建 job 側 SA/RBAC（driver SA 名以 chart 產出為準，§12 實查 2）。 |
| Silver→Postgres loader | **不是 Spark 的事**：獨立 Airflow task `load_silver_to_postgres`（PythonOperator）用 pyiceberg 掃該小時 snapshot（`table.scan(row_filter=And(EqualTo('captured_at', <hour>)))` 級的分區過濾讀）→ psycopg2 `INSERT … ON CONFLICT (video_id, region, captured_at) DO UPDATE`（ga4 範本的 UPSERT 冪等模式；批次用 `psycopg2.extras.execute_values`）。連線 = env `LAKEHOUSE_PG_DSN`（`pipeline_writer` 角色 DSN，§8 env 合約）。資料量 ~400 列/時，pyiceberg→arrow→execute_values 綽綽有餘，不用為 loader 拖 Spark JDBC。首行前 `CREATE TABLE IF NOT EXISTS silver.video_snapshots (…§6a 欄位級 schema…, PRIMARY KEY (video_id, region, captured_at))`（DDL 由 loader 程式碼持有、與 §6a 表逐欄一致，冪等）。 |

---

## 6. P1-4 dbt Silver→Gold + 資料品質（決定）

| 開放問題 | 決定 |
|---|---|
| dbt 在 k8s 怎麼跑 | **KubernetesPodOperator** 跑自建 dbt image（`lakehouse/dbt/Dockerfile`：`python:3.12-slim` + `dbt-postgres==1.10.2` + 專案本體與 `profiles.yml` 烤進 image，`--profiles-dir /app`）。KPO 參數：`namespace="data"`（與資料同域）、`get_logs=True`、`on_finished_action="delete_pod"`、image 從 `config/images.yaml` 讀 `dbt.tag`。兩個 task：`dbt_run`（command `dbt run`）、`dbt_test`（command `dbt source freshness && dbt test`——freshness 先跑，任一非零退出 = task fail = DQ gate 擋 DAG；分開讓 DAG 上的 DQ gate 可見；不用 `dbt build` 混流）。淘汰：astronomer-cosmos（把 dbt 圖展開成 Airflow task——多一套依賴與心智模型，5 個 model 用不上）；dbt 裝進 Airflow image（依賴糾纏，違反 task pod 單一職責）。 |
| Gold 的 Postgres | 共用 `data` ns 的 lakehouse Postgres（§4），`lakehouse` db / `gold` schema。profiles.yml 具體：profile `lakehouse`、target `k8s`、`host: "{{ env_var('LAKEHOUSE_PG_HOST', 'lakehouse-postgres.data.svc') }}"`、`port: 5432`、`user: dbt_runner`、`password: "{{ env_var('DBT_PG_PASSWORD') }}"`（KPO 以 secretKeyRef 注入，§8）、`dbname: lakehouse`、`schema: gold`（fallback，實際落點由下行 +schema 決定）、`threads: 4`。 |
| 分層命名 | 對齊 ga4 範本精神但不照搬四層：**staging（view，`stg_` 前綴）→ marts（table，`gold_` 前綴，schema `gold`）**。schema 落點明確化：覆寫 `generate_schema_name`（`macros/generate_schema_name.sql`，標準「custom schema 作絕對值」版本）+ `dbt_project.yml` 設 `staging: {+schema: staging, +materialized: view}`、`marts: {+schema: gold, +materialized: table}` → staging view 落 `staging.stg_*`、marts 落 `gold.gold_*`（不出現 dbt 預設的 `gold_staging` 拼接 schema；`staging` schema 由 dbt 自建，權限見 §4 init SQL）。中間 bronze/silver 物理層由 MinIO/Iceberg/loader 承擔，dbt 不重複建層（ga4 是 BigQuery 單倉所以四層全在 dbt；本專案分層跨系統，dbt 只管 serving 側）。 |
| sources | **正規 `_sources.yml`**（修範本 hardcode `FROM silver.*` 之弊）：source `silver` = `video_snapshots`（`loaded_at_field: ingested_at`，**freshness warn 2h / error 4h**）、`youtube_categories`（該表無 `ingested_at` 欄——`loaded_at_field: updated_at`，freshness 依 @daily 節奏放寬為 **warn 26h / error 50h**）。DAG 內 `dbt_test` 前不單設 freshness task——freshness 檢查併入 `dbt_test` 步（command 見首行）。 |
| velocity SQL | 保留範本 `velocity_deltas` 的 LAG 骨架，但修正：①加 `hours_since_prev`（LAG captured_at 差）與 `delta_views_per_hour = delta_views / hours_since_prev`——範本的裸 delta 在缺小時時靜默失真，正規化後跨缺口可比②粒度修復後（§5 去重鍵）velocity 真的有資料可算。 |
| DQ 測試清單 | 見下（設計即測試合約）。 |

### dbt 測試合約（全列）

**generic tests（schema.yml）**
- `stg_video_snapshots`：`video_id`/`region`/`captured_at`/`views` not_null；`region` accepted_values（8 區，與 `pipeline.yaml` 由 pytest 對帳）
- `stg_categories`：`category_id`/`region` not_null
- `gold_video_velocity_hourly`：`video_id`/`captured_at`/`delta_views` not_null
- `gold_trending_daily`：`region`/`trending_date`/`total_views` not_null
- `gold_video_lifecycle`：`video_id` not_null；`first_seen_at` not_null
- `gold_category_daily.category_id` → relationships 到 `stg_categories.category_id`（**severity: warn**——categories 維度 @daily 可能晚於首日 hourly 資料）

**singular tests（tests/）**
- `assert_source_freshness_guard.sql`：`NOW() - MAX(ingested_at) > 4h` 出列即 fail（與 source freshness 雙保險，這條擋 DAG）
- `assert_views_non_negative.sql`
- `assert_unique_grain_trending_daily.sql` / `assert_unique_grain_velocity.sql` / `assert_unique_grain_lifecycle.sql`（各 mart 粒度鍵 group by having count>1；不引 dbt_utils 套件，5 條 SQL 自寫）
- `assert_velocity_hours_positive.sql`：`hours_since_prev <= 0` 出列即 fail

**dbt 專案檔案清單**（plan 據此開檔，不另創結構）：`models/staging/{_sources.yml, _staging_schema.yml, stg_video_snapshots.sql, stg_categories.sql}`、`models/marts/{_marts_schema.yml, gold_trending_daily.sql, gold_channel_performance.sql, gold_category_daily.sql, gold_video_velocity_hourly.sql, gold_video_lifecycle.sql}`、`macros/generate_schema_name.sql`、`tests/`（上列 6 支 singular SQL）。

---

## 6a. 資料模型：Bronze / Silver / Gold schema（Gold = P2 資料合約）

### Bronze（MinIO，原始 JSON）

物件 = YouTube API 原始 response 全文 + `_metadata` 信封：

```json
{
  "_metadata": {"region": "TW", "logical_hour": "2026-07-08T14:00:00+00:00",
                 "ingestion_id": "TW_2026070814",
                 "ingested_at": "<實際抓取 UTC ISO>", "source": "youtube_data_api_v3"},
  "response": { "items": [ …videos.list 原文（part=snippet,statistics,contentDetails）… ] }
}
```

不做欄位裁切（Bronze 鐵律：保原文可重放；`description`/`tags`/`contentDetails.duration` 等 P2 語料全數天然保留）。categories 物件同構（`videoCategories.list` 原文）。

### Silver — Iceberg 正本 `lakehouse.silver.video_snapshots`（Postgres serving 副本同構）

粒度：**一列 = (video_id, region, captured_at 小時)**。Postgres 側 PK 即此三欄。

| 欄位 | 型別（Iceberg / PG） | 說明 |
|---|---|---|
| video_id | string / text | YouTube 影片 ID |
| region | string / text | 8 區代碼 |
| captured_at | timestamptz | `date_trunc('hour', ingested_at)`，分區鍵之一 |
| title / description / tags | string / text | tags 為逗號串接字串；description 為 P2b RAG 語料 |
| channel_id / channel_title | string / text | |
| category_id | string / text | join categories 維度用 |
| published_at | timestamptz | 影片發布時間（P2a 特徵：上榜時影片年齡） |
| views / likes / comment_count | long / bigint | fillna(0) |
| like_ratio / engagement_rate | double / double precision | §5 公式 |
| thumbnail_url | string / text | |
| ingestion_id | string / text | `<region>_<YYYYMMDDHH>`（追溯 bronze 物件） |
| ingested_at | timestamptz | 實際抓取時間（freshness 依據） |

`silver.youtube_categories`（僅 Postgres）：`category_id text, region text, category_name text, updated_at timestamptz`，PK `(category_id, region)`。

### Gold marts（Postgres `gold` schema，dbt table materialization）— **P2 資料合約**

**穩定性政策**：以下五表的表名、粒度鍵、既列欄位是對 P2 的介面承諾——變更只允許**加欄位**（additive）；改粒度/刪欄/改語意必須開新版本表（`_v2`）並在 spec 記錄。P2a（表現預測）吃 4/5 的數值特徵與標籤，P2b（RAG）吃 5 的文字欄。

**1. `gold.gold_trending_daily`** — 粒度 `(region, trending_date)`（日聚合基於每影片當日最新快照）

| 欄位 | 型別 | 定義 |
|---|---|---|
| region | text | |
| trending_date | date | `captured_at::date` |
| total_videos | bigint | count(distinct video_id) |
| total_views / total_likes | bigint | sum（每影片取當日最新快照值） |
| avg_views_per_video | numeric | round(avg, 0) |
| avg_like_ratio / avg_engagement_rate | numeric | round(avg, 4) |
| unique_channels / unique_categories | bigint | count(distinct) |

**2. `gold.gold_channel_performance`** — 粒度 `(channel_id, region)`

| 欄位 | 型別 | 定義 |
|---|---|---|
| channel_id / channel_title | text | |
| region | text | |
| videos_trended | bigint | count(distinct video_id) |
| total_views | bigint | sum（每影片取最新快照） |
| avg_engagement_rate | numeric | round(avg, 4) |
| days_on_chart | bigint | count(distinct trending_date) |
| rank_in_region | bigint | rank() over (partition by region order by total_views desc) |
| categories | text | string_agg(distinct category_id) |

**3. `gold.gold_category_daily`** — 粒度 `(category_id, region, trending_date)`

| 欄位 | 型別 | 定義 |
|---|---|---|
| category_id | text | |
| category_name | text | coalesce(維度名, category_id) |
| region / trending_date | text / date | |
| video_count / total_views | bigint | |
| avg_engagement_rate | numeric | round(avg, 4) |
| view_share_pct | numeric | 該類別 views / 當區當日總 views × 100，round 2 |

**4. `gold.gold_video_velocity_hourly`** — 粒度 `(video_id, region, captured_at)`（時序核心賣點）

| 欄位 | 型別 | 定義 |
|---|---|---|
| video_id / title / channel_title / region | text | |
| captured_at | timestamptz | |
| views | bigint | 當時快照 |
| delta_views / delta_likes / delta_comments | bigint | 與前一快照差（LAG over (partition by video_id, region order by captured_at)） |
| hours_since_prev | numeric | captured_at 與前快照差（小時）；> 0 由 DQ 測試保證 |
| delta_views_per_hour | numeric | delta_views / hours_since_prev（缺口正規化） |
| delta_views_pct | numeric | 相對前值百分比；prev=0 → NULL |
| velocity_rank | bigint | rank() over (partition by region, captured_at order by delta_views_per_hour desc) |

（首快照無前值，不出列——`where prev_views is not null`。）

**5. `gold.gold_video_lifecycle`** — 粒度 `(video_id, region)`（P2a 特徵/標籤源 + P2b 文字語料源）

| 欄位 | 型別 | 定義 |
|---|---|---|
| video_id / region | text | |
| title / description / tags | text | 最新快照值（P2b RAG 語料） |
| channel_id / channel_title / category_id / category_name | text | |
| published_at | timestamptz | |
| first_seen_at / last_seen_at | timestamptz | min/max(captured_at) |
| snapshots_count | bigint | 快照數 |
| hours_on_chart | numeric | last_seen − first_seen（小時） |
| first_views / latest_views | bigint | 首/末快照 views（P2a：早期值當特徵、後期值當標籤） |
| total_views_gained | bigint | latest − first |
| peak_delta_views_per_hour | numeric | max 小時增速（爆紅強度標籤候選） |
| avg_engagement_rate | numeric | 全程平均 |

### dbt staging（view，銜接層）

`stg_video_snapshots`：source `silver.video_snapshots` 直取 + 型別防衛（coalesce 數值 0、濾 `video_id is null`）＋衍生 `trending_date`；`stg_categories`：source `silver.youtube_categories` 直取。marts 只准 `ref()` staging，不觸 source（dbt 慣例守門）。

---

## 7. P1-5 Airflow 編排（決定）

| 開放問題 | 決定 |
|---|---|
| executor | **KubernetesExecutor**（§1①） |
| 部署 | **官方 Helm chart 1.22.0**，ArgoCD 子 Application（wave 5），values 內嵌 `valuesObject`（P0 慣例）。關鍵 values：`executor: KubernetesExecutor`；`postgresql.enabled: false`（**不用 chart 內嵌 postgres**——metadata 走共用 Postgres 的 `airflow` db，`metadataSecretName` 指向命令式 Secret 裡的 connection string）；`statsd.enabled: true`（§9）；`images.airflow.{repository,tag}` = GHCR 自訂 image；UI ingress = `ingress.apiServer.{enabled: true, ingressClassName: nginx, hosts: [{name: airflow.localtest.me}]}`（Airflow 3 chart 將 webserver 併入 apiServer 區塊，context7 對 chart 文件查證；§12 實查 1 降為落地校準）；`metadataSecretName: lakehouse-postgres`（指向 `airflow` ns 那份 §8 Secret；chart 約定其中 connection string 的 key 必須名為 `connection`，值 = `postgresql://airflow:<pw>@lakehouse-postgres.data.svc:5432/airflow`）。 |
| metadata DB | 共用 Postgres 的 `airflow` database（§4）。淘汰 chart 內嵌 postgres：demo 叢集裡兩套 Postgres 直接違反工具紀律。 |
| DAG 進叢集 | **git-sync**（`dags.gitSync`：repo = 本 repo public https、branch `main`、`subPath: orchestration/airflow/dags`、無憑證——public repo 延續 P0 零 secret 姿態）。DAG/設定/SparkApplication 模板改動 = git push 即生效，**不用 rebuild image**；只有依賴/hook 碼改動才走 CI image 迴圈。淘汰 baked-in DAG image：每改一行 DAG 都要 build+bump，迭代摩擦大且與 git-sync 並存無意義。 |
| 自訂 image | `orchestration/airflow/Dockerfile`：`FROM apache/airflow:3.2.2`，加 `yt_ingest` 套件（build context = repo root）、`pyiceberg[s3fs,sql-postgres]`、`psycopg2-binary`、`httpx`、`boto3`。`cncf-kubernetes` provider base image 已內建（SparkKubernetesOperator/KPO 可用）。 |
| backfill | **catchup=False 永遠不開**——`chart=mostPopular` 是「當下快照」API，**歷史不可回補**，Airflow 層面的 catchup/backfill 對 ingest 無意義（會抓成「現在」的資料掛在過去的 logical date 上，資料謊言）。**重處理**（bronze 已有、Silver/Gold 重算）另立手動 DAG `yt_reprocess_range`（`schedule=None` + params `start_date`/`end_date`）：SparkApplication 帶範圍參數 → loader 範圍 UPSERT → dbt run+test。冪等性由 §5 的 overwritePartitions/UPSERT 保證。 |
| 排程細節 | 主 DAG `schedule="0 * * * *"`、`start_date=pendulum.datetime(2026, 7, 1, tz="UTC")`（靜態、過去；catchup=False 故不觸發回補）、`max_active_runs=1`（防重疊寫）、`dagrun_timeout=timedelta(minutes=45)`、task `execution_timeout=10min`、`retries=3`+exponential backoff（quota fail-fast 例外；確切 default_args 見 §3）。`yt_reprocess_range` params 形狀：`params={"start_hour": Param(type="string"), "end_hour": Param(type="string")}`（UTC ISO 小時，如 `2026-07-08T14`，含端點；DAG 內展開成逐小時清單驅動 Spark 範圍參數與 loader 範圍 UPSERT）。 |

### 主 DAG `yt_trending_hourly` 結構

```
ingest_trending（PythonOperator .expand(region=8)  ×8 pod）
      │ trigger_rule=all_done（部分 region 失敗不擋批；全失敗時 Spark 讀空輸入自然 fail）
      ▼
spark_bronze_to_silver（SparkKubernetesOperator → SparkApplication in data ns）
      ▼
load_silver_to_postgres（PythonOperator：pyiceberg → Postgres UPSERT）
      ▼
dbt_run（KubernetesPodOperator, dbt image）
      ▼
dbt_test（KubernetesPodOperator：dbt test + dbt source freshness）→ 失敗 = DAG 失敗 = 告警
```

輔 DAG：`yt_categories_daily`（@daily：fetch ×8 → bronze → UPSERT silver.youtube_categories）；`yt_reprocess_range`（手動）。**排程器只有 Airflow 這一個**，三條 DAG 都在其下（工具紀律針對「第二套排程系統」，不是 DAG 數量）。

---

## 8. CI / GitOps 接入（沿用 P0，不自創）

三支 workflow 全複製 `hello-ci.yaml` 模式（paths 過濾 + test job + build-push-bump + `[skip ci]` + concurrency group）：

| workflow | 觸發 paths | test 內容 | image | tag bump 落點（yq） |
|---|---|---|---|---|
| `airflow-ci.yaml` | `ingestion/**`、`orchestration/airflow/{Dockerfile,pyproject.toml}`（**不含 dags/**） | ruff + pytest（ingest 單元 + DagBag import） | `…/airflow` | `platform/argocd/apps/airflow.yaml` 的 `spec.source.helm.valuesObject.images.airflow.tag` |
| `spark-ci.yaml` | `lakehouse/spark/**`（不含 k8s/） | ruff + pytest（pyspark local 跑轉換邏輯） | `…/spark-jobs` | `orchestration/airflow/dags/config/images.yaml` 的 `spark_job.tag` |
| `dbt-ci.yaml` | `lakehouse/dbt/**` | `dbt parse`（離線編譯守門）+ ruff（若有 py macro 腳本） | `…/dbt` | 同上檔 `dbt.tag` |

迴圈防護不變：bump 落點路徑都不在各自觸發 paths 內 + `[skip ci]`。`images.yaml` 走 git-sync 送達 DAG（改它不觸發任何 build）；`airflow.yaml` 的 tag bump 由 ArgoCD 滾動 Airflow 元件。`pr-checks.yaml` 擴充：對上述 paths 跑對應 test job（不 build）。GHCR 三個新 package 首推後手動設 public（P0 既知 gotcha）。

**Secrets 邊界**（`make pipeline-secrets`，命令式、不進 git，冪等 `kubectl create … --dry-run=client -o yaml | kubectl apply`）：

| Secret | ns | key（確切名） | 內容 |
|---|---|---|---|
| `youtube-api` | airflow | `YOUTUBE_API_KEY` | 唯一外部憑證，使用者提供 |
| `minio-root` | data、airflow | `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` | 隨機生成（`openssl rand -hex 20`）；key 直接用 AWS 標準名——同一份 Secret `envFrom` 即可餵 boto3/pyiceberg/S3A，MinIO 本體以 `valueFrom` 映射成 `MINIO_ROOT_USER/PASSWORD`（§4） |
| `lakehouse-postgres` | data、airflow | `postgres-password`、`airflow-password`、`pipeline-password`、`dbt-password`、`grafana-reader-password`、`connection` | 各角色密碼（隨機生成）+ Airflow metadata connection string（`metadataSecretName` 引用，key 名 `connection` 為 chart 約定，§7） |
| `grafana-lakehouse-reader` | monitoring | `password` | `grafana_reader` 密碼（Grafana datasource 用，§9；與 `lakehouse-postgres` 的 `grafana-reader-password` 同值，由 `make pipeline-secrets` 一次生成寫兩處） |

**Env 注入合約**（誰拿到哪個變數、從哪來；程式碼一律顯式讀 env，不靠隱式 default）：

| env 變數 | 來源 Secret/key | 消費者 | 注入途徑 |
|---|---|---|---|
| `YOUTUBE_API_KEY` | `youtube-api`/`YOUTUBE_API_KEY` | ingest task pods | Airflow chart `secret:` list（§3 形狀） |
| `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` | `minio-root` 同名 key | ingest/loader task pods；Spark driver+executor | chart `secret:`；SparkApplication `envFrom`（§5） |
| `AWS_ENDPOINT_URL` | 非 secret，值 = `http://lakehouse-minio.data.svc:9000` | 同上（boto3/pyiceberg 讀它連 MinIO；雲上刪除即回 AWS 原生解析 = 可攜） | `pipeline.yaml`（§3）→ DAG 傳入 / Spark 模板以 `fs.s3a.endpoint` conf 寫死同值 |
| `LAKEHOUSE_PG_DSN` | 組自 `lakehouse-postgres`/`pipeline-password`，值 = `postgresql://pipeline_writer:<pw>@lakehouse-postgres.data.svc:5432/lakehouse` | loader（§5）、categories UPSERT（§3）、pyiceberg sql catalog（§4 另加 `+psycopg2` driver 前綴） | chart `secret:` |
| `DBT_PG_PASSWORD`（host 用 `LAKEHOUSE_PG_HOST`，有 default） | `lakehouse-postgres`/`dbt-password` | dbt KPO pod（profiles.yml `env_var()`，§6） | KPO `secrets=[Secret('env', …)]` |

README 寫明：這是 P0 §7 預告的「第一個真 secret」落地；sealed-secrets/external-secrets 仍不引入（要用才加）。

---

## 9. P1-6 可觀測性 + 對外查詢（決定）

| 開放問題 | 決定 |
|---|---|
| 管線指標怎麼出 | **兩源，各管其分**：①**Airflow 官方路徑** chart `statsd.enabled: true`（statsd-exporter 隨 chart 部署）+ 我方一個 ServiceMonitor 對準 statsd svc → DAG/task 成功失敗、時長等執行面指標。②**資料面指標走 postgres-exporter 自訂查詢**（image v0.20.1，部署在 `lakehouse/postgres/k8s/`，自訂查詢 ConfigMap `lakehouse-exporter-queries`）三條，SQL 即合約：`yt_freshness_seconds` = `SELECT EXTRACT(EPOCH FROM (now() - max(ingested_at))) AS seconds FROM silver.video_snapshots`；`yt_silver_rows_24h{region}` = `SELECT region, count(*) AS rows FROM silver.video_snapshots WHERE captured_at > now() - interval '24 hours' GROUP BY region`；`yt_gold_mart_rows{mart}` = 5 個 `SELECT '<mart>' AS mart, count(*) AS rows FROM gold.<mart>` UNION ALL（exporter 連線用 `grafana_reader` 不夠——它也要讀 silver，改用 `pipeline_writer` DSN；空表/表不存在首日容錯：查詢對 `silver.video_snapshots` 不存在時 exporter 只 log error 不 crash，屬可接受降級）。範本的自訂 `metrics_exporter.py` **不搬**——recon 證實它是從未被呼叫、port 也沒人綁的整組死碼（§10）；資料面真相在 DB 裡，用既有 exporter 的 custom query 拿，不自養 exporter 進程。 |
| 新鮮度/DQ 失敗 → 告警 | PrometheusRule（`platform/monitoring/pipeline/`）：`YTDataStale`（`yt_freshness_seconds > 3h` warn、`> 6h` critical）、`YTPipelineTaskFailures`（statsd 的 task 失敗計數 1h 增量 > 0 → warn；dbt_test 失敗即 DAG 失敗，被此規則涵蓋）、`LakehouseComponentDown`（minio/postgres `up == 0`）。Alertmanager 用 P0 既有部署，不接通知通道（demo 看 UI）。 |
| Grafana | 兩個 dashboard（ConfigMap sidecar，P0 慣例，沿用 P0 的 sidecar label；ConfigMap 名 `grafana-dashboard-pipeline-health`、`grafana-dashboard-trending-insights`，dashboard title 帶 `YT` 前綴供 §12A 步驟 9 搜尋）：①**pipeline-health**：DAG 成功率、task 失敗、freshness、每區 24h 筆數、mart 列數。②**trending-insights**（**即 P1 的「對外查詢」交付**）：直讀 Postgres gold——各區 top velocity 影片、頻道排行、類別佔比、每日總覽。Postgres datasource 以 sidecar datasource ConfigMap 佈建，唯讀 `grafana_reader`，密碼經 Grafana env 注入（chart values 引用 `grafana-lakehouse-reader` Secret；確切 values key §12 實查 6）。 |
| 前端/API | **P1 不做**。NORTH_STAR 本就列 Next.js dashboard 為選配；Grafana 讀 gold 已滿足「展示可查詢」。範本的 Next.js 前端不搬（它還依賴不存在的 silver Postgres 表）。留 P4 選配。 |

---

## 10. 範本債清理清單（硬約束③「搬遷不照抄」的落地帳）

recon（2026-07-08 對 `yt-trending-platform` 全面盤點）發現並於本設計處置：

| # | 範本問題 | 處置 |
|---|---|---|
| 1 | **Silver 斷線**：Spark 寫 Iceberg-on-MinIO，dbt/前端卻讀 Postgres `silver.*`——根本不相通，Gold 永遠空 | §2/§5：loader task 建立 Silver serving 副本，介面顯式化 |
| 2 | **`silver.youtube_categories` 無生產者**（bronze 有抓但從未晉升） | §3：`yt_categories_daily` DAG 直送 Postgres |
| 3 | **velocity 被日級去重打死**（silver 粒度壓成 1 列/video/日，LAG 無資料可算） | §5：去重鍵改 `(video_id, region, captured_at)` 保小時粒度 |
| 4 | **Spark 以 `docker exec` 觸發**（依賴 docker socket，k8s 上不可用） | §1②：spark-operator + SparkKubernetesOperator |
| 5 | **dbt 任務必炸**（DAG `cd /opt/dbt` 但無 mount、Airflow image 無 dbt） | §6：獨立 dbt image + KPO |
| 6 | **自訂 metrics exporter 整組死碼**（無呼叫點、無 http server，Grafana 面板讀空） | §9：刪除；資料面指標改 postgres-exporter custom query |
| 7 | **Iceberg warehouse 跨桶錯置**（warehouse 在 bronze 桶、表 LOCATION 在 silver 桶） | §4：warehouse 單一根 `s3a://silver/warehouse` |
| 8 | **region 清單漂移**（DAG 8 區 vs .env/dbt 12 區）；`utils/schema.py` 死碼；`.append()` 重跑產重複列；bronze `now()` 命名不冪等；`:latest` image 未 pin；deprecated `days_ago` | §3/§5/§0：單一真源 + 顯式 schema 複活 + overwritePartitions + 決定性 key + 全 pin + Airflow 3 正規寫法 |
| 9 | **brief 前提更正**：brief 提到「`data_pipeline.py` 與 daily DAG 職責重疊」——recon 證實範本內**不存在** `data_pipeline.py`、也只有唯一一條 DAG；該項無需去重，實際要清的是上列 1–8 | 記錄於此，避免 plan 去找不存在的檔 |

（進化方向對照 ga4 雙胞胎：正規 `_sources.yml` + source freshness 是 ga4 範本也沒做的，本設計補上；extractor UPSERT 冪等模式則直接繼承。）

---

## 11. 測試策略（硬約束⑥「每步可測」）

| 層 | 測試 | 跑在哪 |
|---|---|---|
| ingest 單元 | `ingestion/youtube/tests/`：API client（httpx mock：正常/403 quota fail-fast/5xx retry 語意）、bronze key 決定性、`_metadata` 信封 | airflow-ci + pr-checks |
| DAG | `orchestration/airflow/tests/`：DagBag import 零錯誤、三 DAG 的依賴鏈斷言、`catchup=False`/`max_active_runs=1` 守門、**config 一致性測試**（`pipeline.yaml` regions == dbt accepted_values 清單，防漂移復發） | airflow-ci + pr-checks |
| Spark 轉換 | `lakehouse/spark/tests/`：pyspark local session 餵固定 bronze JSON fixture → 斷言欄位、去重、衍生指標公式、空輸入行為 | spark-ci + pr-checks |
| dbt | `dbt parse`（CI 離線守門）+ 全部 DQ 測試（§6 合約）每小時在叢集內跑（`dbt_test` task 即 DQ gate） | dbt-ci / 叢集 runtime |
| 端到端 | `scripts/verify-pipeline.sh`（§12 前的驗收清單） | 本機 `make pipeline-verify` |

---

## 12. 端到端驗收清單 + plan 前需實查

### A. `make pipeline-verify`（`scripts/verify-pipeline.sh`，全自動、任一步 fail 即非零退出；前置 = P0 `make verify` 綠 + `make pipeline-secrets` 已跑）

| # | 檢查 | 要點 | 預期 |
|---|---|---|---|
| 1 | ArgoCD apps 收斂 | 輪詢 applications（timeout 900s） | P0 的 5 個 + 新 5 個全 `Synced`+`Healthy` |
| 2 | 儲存底座 | `mc ls` 經 port-forward（或 kubectl exec） | `bronze`/`silver` bucket 存在 |
| 3 | 觸發一輪 | `kubectl -n airflow exec <api-server> -- airflow dags trigger yt_trending_hourly` 後輪詢 dagrun 狀態 | dagrun `success`（含 dbt_test 綠 = DQ gate 過） |
| 4 | Bronze 有原始資料 | `mc ls bronze/youtube_trending/region=TW/…` 當前小時 | ≥1 個 `snapshot.json` |
| 5 | Silver（Iceberg + serving） | Postgres：`SELECT count(*) FROM silver.video_snapshots`（Iceberg 正本不在腳本內另起 Spark 驗——由步驟 3 的 spark task 成功 + 實查 3 煙囪驗證覆蓋；serving 副本有資料即證明「Spark 寫入→pyiceberg 讀出」整鏈通） | > 0，且 `captured_at` 為當前小時 |
| 6 | Gold marts | `SELECT count(*)` 5 個 `gold.gold_*` | 全部 > 0（velocity 需第二輪後 > 0，腳本對它放寬為表存在＋第二輪斷言列數） |
| 7 | 冪等 | 重跑步驟 3 同一 logical date（clear+rerun） | silver/gold 列數不膨脹 |
| 8 | 指標新鮮度 | Prometheus query `yt_freshness_seconds` | 有值且 < 7200 |
| 9 | dashboards | Grafana `/api/search?query=YT` | 命中 pipeline-health + trending-insights |
| 10 | 可回溯 | 三個 image tag 形如 `sha-*` 且與 git 中 bump 落點一致 | 同 P0 第 7 步精神 |

可重現性：`make cluster-down && make cluster-up && make pipeline-secrets YOUTUBE_API_KEY=… && make pipeline-verify` 全綠（外部狀態僅 GHCR/git/API key）。雲端可攜對照表沿用 P0 §9，新增行：MinIO↔S3 = 只換 endpoint/憑證 env（S3A 與 boto3 都吃 env，程式碼零改動）；storage class 全設計無一處寫死（`grep -r storageClassName` 守門沿用）。

### B. plan 前需實查（設計已收斂，以下為落地校準點）

1. **Airflow chart 1.22.0 values 落地校準**（設計已按 context7 查證寫入預設：ingress = `ingress.apiServer.*`（§7）、secret 注入 = `secret:` list（§3）、`metadataSecretName` key 名 `connection`（§7）——實查僅為對 1.22.0 實際 values.yaml 逐 key 校對，預期零改動）。
2. **spark-operator 2.5.1 chart 產出的 job 側 ServiceAccount 名**（預設傾向：`spark-operator-spark`，即 `<release>-spark` 命名規則，context7 查證；`spark.jobNamespaces` values 路徑已證即此名）。SparkApplication `driver.serviceAccount` 先按此寫，裝完 `kubectl -n data get sa` 校對。
3. **pyiceberg 0.11.1 `sql` catalog 與 Java JDBC catalog 的表佈局互通**：落地先跑一次「Spark 寫 → pyiceberg 讀」煙囪驗證（設計依官方文件判定相容，此為 5 分鐘實證）。
4. **dbt-postgres 1.10.2 解析到的 dbt-core 版本**（PyPI metadata 為 `dbt-core >=1.8,<2.0`——預設傾向解析到 1.10.x 線；`uv pip compile` 一次定 lock，image 內 pin）。
5. **spark:4.0.2-python3 image 內建 Hadoop 版本**（決定 hadoop-aws/aws-java-sdk-bundle jar 版本，範本值 3.4.1/1.12.780 為起點）。
6. **kube-prometheus-stack Grafana 的 datasource sidecar + Secret env 注入**確切 values（`grafana.envFromSecret` 或等價 key）。
7. **statsd-exporter 的 svc 名/port 與指標名前綴**（ServiceMonitor 與 pipeline-health dashboard 的 PromQL 以 runtime 實測為準）。
8. P0 的 **GitHub repo/`<GITHUB_OWNER>` 佔位**仍未建（P0 實查 1 未消化前，git-sync repo URL 同樣佔位）。

---

## 13. 落地後校驗（design 自檢摘要）

- 六簇開放問題全部收斂為決定（§3–§9 決策表）；三個 k8s 關鍵決策 §1 拍板並列淘汰方案。
- 硬約束對照：①部署全走 P0 慣例（kustomize `k8s/`+子 Application / Helm 子 Application、wave 3–6、CI 複製 hello-ci 模式）②排程只 Airflow（三 DAG 一排程器）/DB 只一套 Postgres（三職責共用）/無 ClickHouse/無 Kafka/無第二佇列（Celery+Redis 已砍）③搬遷不照抄（§10 九項範本債處置，含 brief 前提更正）④Gold = P2 合約（§6a 五 marts 欄位級定義 + 穩定性政策）⑤獨立 demo 可重現（§12A 步驟 + 可重現性宣告）⑥每步可測（§11）⑦雲端可攜（無 storageClassName/零 ingress 註解/S3 端點 env 化）。
- 零 secret 姿態的演進：P0 零 secret → P1 四個命令式 Secret（§8），邊界與 P0 §7 預告一致。
