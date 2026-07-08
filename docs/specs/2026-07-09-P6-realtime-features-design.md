# P6 即時特徵層（Flink，GA4 串流情境）— Design（Fable 5 產出）

> **狀態**：design 完成，待寫 implementation plan。
> **上游**：[`2026-07-09-P6-realtime-features-brief.md`](2026-07-09-P6-realtime-features-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段（Flink 條）+ [`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md)（下稱「地基」；§4 Silver `ga4_events` = 事件重放源、§5.3 `gold_ga4_sessions`／§5.1 `gold_ga4_user_item_interactions` = 離線對照、§13 無 intraday = 誠實護欄根因）+ [`2026-07-08-P3-ptt-ingest-design.md`](2026-07-08-P3-ptt-ingest-design.md)（Strimzi 單 broker KRaft、決定性 key、at-least-once 慣例）+ [`2026-07-08-P0-platform-foundation-design.md`](2026-07-08-P0-platform-foundation-design.md)（GitOps/監控/secret 慣例）+ [`2026-07-08-P4-presentation-layer-design.md`](2026-07-08-P4-presentation-layer-design.md) §3-4（匯出合約/MCP）。brief 已鎖定決策 1–8 全部沿用，未翻案。
> **接縫 A 注意**：撰寫本 design 時 `2026-07-09-P6-recommendation-design.md` **尚未產出**——Redis feature schema 依 P6 推薦 brief §共用契約-接縫 A 的形狀**假設**（§6 全列假設內容），P6 design 產出後以其為單一真源、本 spec 的 sink 對齊之（差異吸收點在 §6 的 key-builder 單點）。
> **版本查證日**：2026-07-09（Flink Kubernetes Operator 版本與 `FlinkDeployment` CRD 形狀、Flink 2.0 DataStream/watermark/state-backend 設定鍵、KafkaSource 形狀皆對官方文件（context7）查證；confluent-kafka 沿用 P3 pin）。

---

## ⚠️ 誠實護欄正本（最高優先，通篇適用）

**本層的串流輸入是「標註事件重放（labeled event-replay）」，不是真線上流量。** 公開 sample 只有 daily export、無 `events_intraday_*`（地基 §13 known-limit 根因）。本 design 展示的是兩件真東西：
1. **架構就緒性**——若有真 intraday 流（GA4→GTM SS→Pub/Sub→Kafka），這套 Flink 拓撲**換 source topic 即可直接接上**，job 邏輯零改（event-time 語意本來就不依賴資料「新鮮」）。
2. **event-time 正確性**——重放保留原始 `event_ts_micros` 當 event-time，Flink 的滑窗/session 視窗/去重輸出與批次 Gold/Silver 離線重算**收斂**（§7 可執行判準），證明串流計算可信。

「事件重放示範、非真線上流量」的標註落點（缺一即違約）：topic 命名含 `replay`（§4）、訊息信封 `_replay` 段（§4）、README、前端 `/streaming` 頁 Explainer 首段（§10）、MCP 工具回傳 `disclaimer` 欄（§10）、所有截圖/GIF 圖說。

---

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| Flink Kubernetes Operator（Helm chart） | **1.12.0** | 官方文件 release-1.12（context7）；chart repo = `https://downloads.apache.org/flink/flink-kubernetes-operator-1.12.0/` | CRD `FlinkDeployment` `apiVersion: flink.apache.org/v1beta1` |
| Flink | **2.0.0**（`flinkVersion: v2_0`） | operator 1.12 的 `FlinkVersion` enum 最高支援 **v2_0**（context7 查證：v1_17–v2_0 有效，v1_15/v1_16 已 deprecated）→ 選 operator 支援上限的 Flink 2.0 | image `flink:2.0.0-java17`（確切 tag §14 實查 2） |
| flink-connector-kafka | **4.0.0-2.0**（`<connector>-<flink>` 版式） | 官方 connector 版式；確切最新 patch §14 實查 3 對 Maven Central 校準 | KafkaSource + KafkaSink 同一 artifact |
| flink-s3-fs-presto（checkpoint 用 S3 plugin） | 隨 Flink 2.0.0 發行版（`flink-s3-fs-presto-2.0.0.jar`） | Flink 官方 S3 文件（context7）：checkpoint 走 s3 filesystem plugin | Dockerfile 啟用（§8），指向 MinIO |
| Jedis（Redis Java client） | **5.x**（design 傾向 5.2.x；§14 實查 8 定 patch） | 成熟穩定 client；官方無維護中的 Flink Redis connector（§6 誠實註記） | 只用 HSET/EXPIRE/pipeline |
| Java / build | **JDK 17 + Maven** | Flink 2.0 官方支援 Java 17 | CI 用 temurin 17 |
| confluent-kafka（Python，重放產生器） | **2.15.0** | 沿用 P3 §0 pin | 已在 Airflow image（P3 裝入） |
| Strimzi / Kafka broker | 1.1.0 / 4.3.0 | 沿用 P3 §0，**零升級零改 broker** | 本 spec 只加 `KafkaTopic` CR |
| psycopg2 / pyiceberg / MinIO / Postgres / Airflow | 全部沿用 P1/P3 pin | — | 零升級 |

**刻意不引入**：Flink SQL/Table API 主線（§2②）；官方已死的 bahir flink-connector-redis（§6）；flink-connector-jdbc（驗證輸出走 KafkaSink→既有 Python loader 模式，不賭 JDBC connector 對 Flink 2.0 的支援節奏，§7）；PyFlink（§2②）；Flink HA 之外的第二套 HA 機制。

---

## 1. 三個關鍵決策（先拍板，細節在各簇）

### ① Flink on k8s = **Flink Kubernetes Operator 1.12.0 + `FlinkDeployment`（application mode）**（開放問題 1）

| 候選 | 判定 |
|---|---|
| **Flink Kubernetes Operator（Helm 1.12.0）+ `FlinkDeployment` CRD application mode** ✅ | (a) 與本 repo「帶 operator/CRD 的元件用 Helm 裝 operator」判準完全同構（P1 spark-operator、P3 Strimzi 前例）——Flink 叢集宣告 = 一份 CR 進 git、ArgoCD sync，GitOps 敘事一致；(b) application mode = 一 job 一叢集，job 生命週期即 CR 生命週期，`upgradeMode: last-state` 配 Kubernetes HA 給出「改 CR → operator 帶 checkpoint 滾動升級」的正規運維展示（面試考點）；(c) operator 是業界標準（取代手寫 standalone manifest 的社群共識），CRD 運維本身就是 JD 素材。 |
| standalone session cluster manifest | 淘汰：JobManager/TaskManager Deployment、HA、升級與 job 提交全手工；session mode 還要第二步 REST 提交 jar（誰做這步？又回到「第二個排程器」的泥坑）。與 P3 §2① 淘汰手寫 KRaft manifest 同一邏輯。 |
| operator + session cluster + `FlinkSessionJob` | 淘汰：session cluster 的價值是多 job 共享叢集，本層只有一支常駐 job——application mode 是官方對單 job 的建議形狀，少一層 indirection。 |

**Flink 版本連動決策**：operator 1.12 的 `FlinkVersion` enum 上限 = `v2_0` → pin **Flink 2.0.0**（不追 2.1/2.2——operator 不認的版本進不了 CR；若 §14 實查 1 發現 operator 1.13+ 已出且支援 v2_1+，升級是兩個欄位改動，架構零變）。選 2.x 而非 1.20 LTS：Flink 2.0 是現行主版本、設定鍵已全面換代（`state.backend.type` / `execution.checkpointing.dir`，本 design 全用新鍵），portfolio 展示「會用當代 Flink」。

### ② API 層 = **DataStream API（Java 17）**，不用 Table/SQL、不用 PyFlink（開放問題 2）

| 候選 | 判定 |
|---|---|
| **DataStream API（Java 17 + Maven）** ✅ | 本層的展示核心正是 DataStream 才露得出來的底層掌握度：`WatermarkStrategy.forBoundedOutOfOrderness` + idleness、`EventTimeSessionWindows`、`KeyedProcessFunction` + event-time timer、`ValueState`/`MapState` + `StateTtlConfig`、自訂 `RichSinkFunction`（含 `CheckpointedFunction` flush 合約）。Table/SQL 把這些全藏掉，等於放棄本 spec 的存在理由。Java 是 Flink 第一公民（本 repo 第一個 JVM 程式資產——「Flink JVM 是 k8s 原生負載」的 M4 界線由此自然成立）。 |
| Table/SQL API | 淘汰為主線；**列進化方向**（README 一句話）：同一 topic 上可另掛 Flink SQL 滑窗查詢當對照展示，本版不做（scope 紀律——主線已含 4 個 pattern + 對照 harness）。 |
| PyFlink | 淘汰：keyed state / 自訂 sink / 測試 harness 在 PyFlink 都是二等支援，且「Python 包 JVM」對串流 JD 是減分敘事。repo 的 Python 慣例不適用於此——工具跟著工作走。 |

### ③ 狀態後端 = **RocksDB + 增量 checkpoint → MinIO（S3）**（開放問題 3）

| 候選 | 判定 |
|---|---|
| **RocksDB（`state.backend.type: rocksdb`）+ `execution.checkpointing.incremental: true` + checkpoint 到 MinIO** ✅ | portfolio 狀態量小，heap 也跑得動——但 RocksDB 是「大狀態生產姿態」的正確工程展示（brief 傾向明言），且增量 checkpoint、TM 本地磁碟 spill、state TTL 的行為都只有 RocksDB 路徑才真實。checkpoint 存 MinIO = 複用既有物件儲存（新 bucket `flink`，§8），零新儲存元件。 |
| hashmap（heap） | 淘汰：對本量級可行但展示價值低；「量小就 heap」的右尺寸邏輯在**執行引擎**成立（P3 Silver 用 Python），在**狀態後端**不成立——這裡選的是姿態不是算力。誠實註記進 README：本資料量 RocksDB 非必要，是刻意的生產姿態展示。 |
| forst（Flink 2.0 新的分離式狀態後端） | 淘汰：太新、運維面資料少，demo 風險不值；列進化方向一句話。 |

**checkpoint 策略定值**：間隔 **30s**、`execution.checkpointing.mode: EXACTLY_ONCE`（引擎內部語意；端到端見 §6 一致性）、timeout 5m、`execution.checkpointing.dir: s3p://flink/checkpoints/ga4-realtime-features`、savepoint `s3p://flink/savepoints/ga4-realtime-features`、Kubernetes HA `high-availability.storageDir: s3p://flink/ha/ga4-realtime-features`（支撐 `upgradeMode: last-state`）。

---

## 2. 總體形狀

### 資料流

```
Postgres silver.ga4_events（地基 §4 合約；serving 副本，與 Iceberg 正本同構）
        │  ga4_replay（Airflow 手動 DAG，schedule=None；§4）
        │  按 event_ts_micros 決定性排序 → 加速重放（預設 60×，event-time 保原始時間戳）
        │  ＋ 去重示範用重複注入 ＋ 尾端 watermark sentinel
        ▼
Kafka topic ga4.events.replay（沿 P3 Strimzi trend-kafka；加 topic 不改 broker）
        │  KafkaSource（offsets 存 checkpoint = Flink 原生語意，對照 P3 手動 commit）
        ▼
Flink job ga4-realtime-features（FlinkDeployment application mode，常駐；§5）
        │  watermark(bounded 30s + idleness 60s) → 去重(keyed state) →
        │  F1 user×category 滑窗 ／ F2 item 熱度滑窗 ／ F3a 當前 session 狀態(ProcessFunction+timer)
        │  ／ F3b session 視窗最終聚合(EventTimeSessionWindows 30m gap)
        ├────────────► Redis sink（接縫 A；feat:rt:* HASH + TTL；§6）──► P6 線上服務讀
        └────────────► KafkaSink ga4.rt.verification（驗證輸出；§7）
                              │  ga4_realtime_correctness（Airflow 手動 DAG）
                              ▼
                    Postgres stream.flink_* 三表 → SQL 對照 silver 重算 + gold_ga4_sessions
                              ▼
                    ga4_realtime_correctness.json（P4 匯出合約 additive）→ 前端 /streaming 頁 + MCP
```

**排程器界線（硬約束重申）**：Flink job 是**常駐串流服務**（ArgoCD/operator 管生命週期，同 P3 consumer 的定位）、不受 Airflow 排程；Airflow 只做兩件批次事——觸發重放（`ga4_replay`）與跑對照（`ga4_realtime_correctness`），都是手動 DAG（P3 `ptt_replay_dlq` 先例）。排程器仍只有 Airflow 一個；messaging 仍只有 Kafka 一個（Redis 是 P6 feature store 出口、非 messaging）；Flink 是**唯一**新串流計算引擎，職務 = 有狀態 event-time 特徵（Airflow 批次做不到、Spark 在本 repo 是批次角色）。

**M4 界線（明寫）**：Flink 是 JVM 負載，**k8s 原生跑在 kind 節點容器內即可**，不涉 Apple GPU、不需繞道 host 原生執行——與 P2「重算力上 M4 host」是相反象限：這裡沒有重算力，只有狀態與 IO，正是 k8s 常駐服務的本命場景。

### 新增檔案佈局（全 additive；未列 = 不動）

```
ingestion/streaming/                     # NORTH_STAR 指定的即時層目錄
├── flink-job/                           # Java 17 + Maven（本 repo 第一個 JVM 資產）
│   ├── pom.xml                          # flink 2.0.0(provided) + flink-connector-kafka 4.0.0-2.0 + jedis + 測試 harness
│   ├── Dockerfile                       # FROM flink:2.0.0-java17；啟用 s3-presto plugin；COPY job jar → /opt/flink/usrlib/
│   └── src/main/java/…/                 # ReplayEnvelope(反序列化+sentinel 判別)/DedupFunction/
│   │                                    # UserCategoryWindow(F1)/ItemPopularityWindow(F2)/
│   │                                    # LiveSessionFeatureFn(F3a)/SessionAggWindow(F3b)/
│   │                                    # FeatureUpdate(統一 sink 記錄)/RedisFeatureSink/VerificationRecord/JobMain
│   └── src/test/java/…                  # §12 harness 測試
├── replay/                              # Python 套件 ga4_replay（裝進 Airflow image，同 ga4_ingest 模式）
│   ├── pyproject.toml
│   ├── src/ga4_replay/{reader.py, pacer.py, producer.py, sentinel.py}
│   └── tests/
├── kafka/                               # KafkaTopic CR ×2（掛 trend-kafka，label strimzi.io/cluster）
│   ├── kustomization.yaml
│   ├── topic-events-replay.yaml
│   └── topic-rt-verification.yaml
└── k8s/
    ├── kustomization.yaml
    ├── rbac.yaml                        # data ns 的 flink SA + Role/RoleBinding（operator 官方 quickstart 形狀）
    └── flinkdeployment.yaml             # §8 CRD 全文；CI 的 yq bump 落點 = .spec.image
orchestration/airflow/
├── Dockerfile                           # += ga4_replay 套件（confluent-kafka P3 已裝，零新 pin）
└── dags/
    ├── ga4_replay.py                    # §4（schedule=None）
    ├── ga4_realtime_correctness.py      # §7（schedule=None）
    └── config/pipeline.yaml             # += ga4_replay: 區塊（speedup/dup_ratio/topic 常數單一真源）
platform/
├── argocd/apps/
│   ├── flink-operator.yaml              # wave 14（Helm 1.12.0，ServerSideApply）
│   ├── ga4-streaming.yaml               # wave 15（kustomize → ingestion/streaming/{kafka,k8s}）
│   └── streaming-monitoring.yaml        # wave 16（platform/monitoring/streaming）
└── monitoring/streaming/                # PodMonitor + PrometheusRule + Grafana dashboard ConfigMap
ingestion/ptt/kafka/kafka.yaml           # ★唯一觸碰的 P3 資產：kafkaExporter regex additive 放寬（§9）
.github/workflows/streaming-ci.yaml      # §8（JDK17 + mvn verify + image + yq bump）
frontend/…/streaming/                    # /streaming 靜態頁（§10；P4 additive）
scripts/verify-streaming.sh              # §13；Makefile += streaming-verify
```

**sync-wave**：flink-operator **14** → ga4-streaming **15**（CR 依賴 wave 14 CRD，資源加 `SkipDryRunOnMissingResource=true` 註解，P0 慣例）→ streaming-monitoring **16**。與 P2（7–11）/P3（7–10）互不依賴；P6 推薦 design（未出）自行配號，同號互不依賴亦合法（P0 §3 規則）。

### Topic 佈局（接縫 J：Kafka topic schema 本 spec 定義；接縫 L：沿 P3 broker）

| topic | partitions | RF | retention | 用途 |
|---|---|---|---|---|
| `ga4.events.replay` | **3** | 1 | 3d（`retention.ms: 259200000`） | 重放事件。**key = `user_pseudo_id`**（同使用者同 partition → per-user 有序，session/ProcessFunction 的狀態存取局部性最佳；跨 user 亂序由 watermark 吸收）。**topic 名內建 `replay` = 標註語意的第一落點。** |
| `ga4.rt.verification` | 1 | 1 | 3d | Flink 驗證輸出（§7）；單 partition 保全域序，量級小（日回放 ~數萬則）。 |

單 broker 副本設定沿 Kafka CR 既有 config（P3 §2② 已設 RF=1 全域），KafkaTopic CR 零特殊欄位。

---

## 3. 重放訊息 schema v1（欄位級；接縫 J 合約）

JSON value（key = `user_pseudo_id` bytes）。`rows` 部分 = 地基 §4 Silver 全欄照搬（**架構就緒性：真 intraday 流會帶的事件欄位這裡全帶**，下游 job 不依賴任何 replay-only 欄位做特徵計算）：

```json
{
  "schema_version": 1,
  "event_date": "2020-11-01",
  "event_ts_micros": 1604190000123456,
  "event_name": "add_to_cart",
  "user_pseudo_id": "1234567.8901234567",
  "ga_session_id": 1604189000,
  "item_id": "GGOEGAAX0037",
  "item_name": "…", "item_category": "…",
  "price": 16.99, "quantity": 1, "item_revenue": null,
  "transaction_id": null,
  "device_category": "mobile", "geo_country": "United States",
  "_replay": {
    "run_id": "<dag_run_id>",
    "replay_date": "2020-11-01",
    "speedup": 60,
    "replayed_at": "<UTC ISO，重放當下>",
    "duplicate": false,
    "sentinel": false
  }
}
```

- **event-time 正本 = `event_ts_micros`**（原始 μs epoch，地基 §4 PK 成分）；`_replay.replayed_at` 是 processing-time 紀錄，**任何特徵計算不得使用**（測試守門，§12）。
- `_replay.duplicate: true` = 重複注入的複本（§4，去重示範用）；`sentinel: true` = 尾端 watermark 推進哨兵（§4），兩者都是**顯式標註**——重放的人造性全部寫在信封裡，不藏。
- 語意版本政策：additive-only；改欄位語意開 `schema_version: 2`。

---

## 4. 事件重放產生器（`ga4_replay` DAG；決定）

| 開放問題 | 決定 | 理由 |
|---|---|---|
| 讀哪份 Silver | **Postgres serving 副本 `silver.ga4_events`**（psycopg2 server-side cursor） | 重放需要 `ORDER BY event_ts_micros` 全序掃描——PG 有索引與排序引擎，一日 ~萬級展開列秒級完成；pyiceberg 無排序掃描（要自己全載記憶體排）。兩副本由地基 loader 合約保證同構，讀哪份不影響合約語意。 |
| 觸發形狀 | **Airflow 手動 DAG `ga4_replay`（`schedule=None`）+ params**（P3 `ptt_replay_dlq` 先例） | 常駐重放服務是資源謊言（沒有真流量，卻養一個永遠在放假資料的服務）；手動 DAG = 「demo 時按一下」的誠實形狀，且 params/日誌/重跑都有 UI。排程器仍只 Airflow。 |
| params | `replay_date`（預設 `2020-11-01`）、`speedup`（預設 **60**，範圍 10–600）、`dup_ratio`（預設 **0.01**）、`max_gap_seconds`（預設 **300**，見下） | 單日重放為預設單位（92 天任選一天）；60× = 1 小時壓 1 分鐘、全日尖峰段 ~20 分鐘內放完（task `execution_timeout=90min` 綽綽有餘）。常數預設值進 `pipeline.yaml ga4_replay:` 區塊（單一真源）。 |
| 決定性排序 | `ORDER BY event_ts_micros, user_pseudo_id, event_name, item_id`（PK 四鍵全序） | 同 μs 多列時 tiebreak 決定性 → 同 params 兩次重放 = byte 級同序（冪等驗收 §13-10 的前提）。 |
| 節奏（速率與 event-time 交互，開放問題 5） | 逐列發送，睡 `min((ts[i+1]-ts[i])/speedup, max_gap_seconds/speedup)`；**event-time 永遠保原始值不動**——speedup 只壓縮 processing-time 間距 | watermark/視窗全在 event-time 域運作，與重放速率**解耦**（這正是 event-time 語意的展示點：60× 或 600× 重放，視窗結果 bit 級相同，§13-10 驗證）。`max_gap_seconds` cap 防深夜長空檔把 demo 拖死（cap 只影響等待感，不影響任何計算結果——誠實註記）。 |
| 重複注入（去重示範） | 每列以 `dup_ratio` 機率（**seed = run_id 的決定性 PRNG**）在原列後追發一份 `_replay.duplicate: true` 複本 | 給 F4 去重一個可量測的工作量：`注入數 ≈ 丟棄數`（§7 report 斷言）。決定性 seed → 重放冪等仍成立。 |
| **watermark sentinel（有界重放的視窗閉合）** | 全部資料發完後，向 **3 個 partition 各發一則** `sentinel: true` 訊息：`event_ts_micros = max_ts + (30min gap + 30s bound + 1s)`，key=`_sentinel:<partition>`、顯式指定 partition | KafkaSource 是無界流——最後一批 session 視窗（gap 30m）不會自己關。sentinel 把**每個 partition** 的 event-time 推過 `最後事件+gap+bound`，watermark 合併後越過所有視窗終點 → 視窗全數 fire，離線對照才有完整比對集。job 內 sentinel 走完 timestamp 指派後即被 filter（不進去重/特徵/sink，只記 `ga4_sentinels_seen_total`）。**誠實註記**：真 intraday 流不需要 sentinel（時間自然前進）——它是「有界重放」專屬的收尾機制，README 寫明。 |
| producer 設定 | confluent-kafka：`acks=all`、`enable.idempotence=true`、發送完 `flush(60)` 檢查（P3 §4 同款） | 沿用已定慣例。 |

---

## 5. Flink job `ga4-realtime-features`（DataStream；決定）

### 5.1 source 與 watermark

- `KafkaSource<ReplayEnvelope>`：bootstrap `trend-kafka-kafka-bootstrap.data:9092`（P3 §2 慣例名）、topic `ga4.events.replay`、group `ga4-flink-features`、`OffsetsInitializer.committedOffsets(OffsetResetStrategy.EARLIEST)`。**offset 真源 = Flink checkpoint**（KafkaSource 原生語意；`commit.offsets.on.checkpoint` 保持預設 true——commit 只為 kafkaExporter lag 可觀測性，**不是**恢復依據）。這與 P3「手動 commit = at-least-once」形成刻意對照：README 敘事點「同一個 broker 上，兩種 offset 管理姿態各自對應消費者的容錯模型」。
- 反序列化失敗（壞 JSON/缺欄）：**不炸 job**——deserializer 回 null 略過 + `ga4_deser_errors_total` counter（毒訊息隔離；重放源自我方 Silver，常態應為 0，>0 即告警訊號）。
- **WatermarkStrategy**（source 上指派，per-partition 生成後合併——多 partition 消費的正確形狀，context7 查證）：
  - `TimestampAssigner`：`event_ts_micros / 1000`（→ ms epoch）。
  - `forBoundedOutOfOrderness(Duration.ofSeconds(30))`——**30s 是 event-time 域的亂序容忍**：重放全序發送、按 user keying 分 partition，跨 partition 交錯是唯一亂序源，30s 事件時間裕度覆蓋（60× 下折合 0.5s 處理時間的交錯）。
  - `.withIdleness(Duration.ofSeconds(60))`——重放結束/間歇時 idle partition 不得扣住 watermark（processing-time 60s 判 idle）。
- 遲到資料：視窗一律 `sideOutputLateData` → 只計數 `ga4_late_events_total`（重放場景常態應為 0；真流接上時此指標就是亂序監控位）。

### 5.2 F4 去重（keyed state；最前置 operator）

- `keyBy(PK 四鍵串接：user_pseudo_id|event_ts_micros|event_name|item_id)`（= 地基 §4 冪等鍵，合約一致）→ `KeyedProcessFunction`，`ValueState<Boolean> seen`：
  - 首見 → 置位、放行；再見 → 丟棄 + `ga4_dedup_duplicates_dropped_total`。
  - `StateTtlConfig`：**TTL 6h（processing-time，OnCreateAndWrite）**——覆蓋整場重放＋餘裕；**誠實註記**：Flink state TTL 只有 processing-time 語意（無 event-time TTL），對重放示範足夠、真流上 6h 也對（重複只會近距離出現）。RocksDB compaction filter 清理。
- 去重後的流 = F1/F2/F3 共同輸入 → **at-least-once source ＋ 重複注入都被吸收**，下游計數與 Silver（PK 天然去重）可精確對照——這是 §7 決定性判準成立的根。

### 5.3 特徵集（開放問題 4 收斂：**4 個，涵蓋滑動視窗 × session 視窗 × ProcessFunction+timer × 狀態去重 四種 pattern**）

| # | 特徵 | pattern | 定義（欄位級） |
|---|---|---|---|
| **F1** | 使用者近 5 分鐘同類別瀏覽次數 | **SlidingEventTimeWindows** | `keyBy(user_pseudo_id, item_category)` → `window(SlidingEventTimeWindows.of(5min, 1min))` → `filter(event_name='view_item')` 前置 → `AggregateFunction` 計數 → 輸出 `(user_pseudo_id, item_category, window_end, view_count_5m)` |
| **F2** | item 近 15 分鐘熱度 | **SlidingEventTimeWindows** | `keyBy(item_id)` → `window(SlidingEventTimeWindows.of(15min, 1min))` → 聚合 `(pop_15m = 全漏斗事件數, purchase_15m = purchase 事件數)` → 輸出 `(item_id, window_end, pop_15m, purchase_15m)`。**不加權**（接縫 B：加權是 P6 演算法決策，即時層與地基同守「未染色計數」） |
| **F3a** | 使用者**當前 session** 加購未購件數＋深度（**live**） | **KeyedProcessFunction + event-time timer + MapState** | `keyBy(user_pseudo_id)`；state：`MapState<item_id, Boolean> carted`、`ValueState<Integer> sessionEvents`、`ValueState<Long> sessionStart/lastTs`。每事件：更新計數；`add_to_cart` → carted.put；`purchase` → carted.remove(該 item)；每事件重註冊 event-time timer = `lastTs + 30min`；timer 觸發 = session 結束 → 清 state ＋ 發 Redis 清除更新。每事件即時輸出 `FeatureUpdate`（`session_cart_pending = carted 大小`、`session_events`、`session_started_at`）——**「當前 session」的 live 語意只有 timer+state 做得出來（session window 只在關窗才 fire）**，這是本 job 的 ProcessFunction 考點 |
| **F3b** | session 最終聚合（驗證用） | **EventTimeSessionWindows** | `keyBy(user_pseudo_id)` → `window(EventTimeSessionWindows.withGap(30min))` → `AggregateFunction+ProcessWindowFunction` 輸出 `(user_pseudo_id, session_start_ts, session_end_ts, events_count, items_carted, items_purchased, cart_pending_final, session_revenue)` → **只進驗證 sink**（§7），不進 Redis（live 職責已由 F3a 承擔；F3b 的存在理由 = session 視窗語意展示 + 與 Gold 對照的最終真值） |

gap 取 **30min** = GA4 session 逾時預設值（與 `ga_session_id` 的生成規則同源，§7 對照的語意基礎）。F1/F2 視窗輸出同時流向 Redis sink（每 slide 更新）與驗證 sink（僅整點 `window_end`，§7 過濾）。

### 5.4 拓撲與資源

```
KafkaSource(watermark) ─ filter(sentinel) ─ keyBy(PK4) DedupFn
   ├─ keyBy(user,cat)  SlidingWindow 5m/1m ──┐
   ├─ keyBy(item)      SlidingWindow 15m/1m ─┼─ map→FeatureUpdate ─ union ─ RedisFeatureSink
   ├─ keyBy(user)      LiveSessionFn(F3a) ───┘        └（F1/F2 整點、F3b 全量）→ KafkaSink(ga4.rt.verification)
   └─ keyBy(user)      SessionWindow 30m(F3b) ────────────────────────────────┘
```

`parallelism: 2`（= TM slots；kind 單機右尺寸）；operator chaining 預設。所有自訂函式註冊 Flink metric group counters（§9 清單）。

---

## 6. Redis sink（接縫 A 消費方；決定）

### 一致性（開放問題 6 收斂）：**at-least-once + 冪等寫**

- sink 語意：`DeliveryGuarantee` 等價 at-least-once——`RedisFeatureSink extends RichSinkFunction<FeatureUpdate> implements CheckpointedFunction`：Jedis pipeline 批次寫（batch 100 或 200ms flush），**`snapshotState()` 強制 flush**（checkpoint 完成前掛起寫全部落 Redis → 重放 checkpoint 後的重寫只是覆寫同值）。
- 冪等成立理由：每筆 `FeatureUpdate` 是**絕對值覆寫**（HSET 定值，非 INCR）——重複套用同一更新 = 同一終態。**設計守門：sink 路徑禁止任何 Redis 增量命令（INCR/APPEND）**，測試斷言（§12）。
- 淘汰 exactly-once（2PC/事務 sink）：Redis 無跨 key 事務性 sink 生態，自造 2PC 是過度工程；特徵覆寫天然冪等使 at-least-once 端到端等效 exactly-once（sink 值域層面）。與 P3 at-least-once 姿態同一家族，README 對照敘事。
- **無官方 Redis connector 的誠實註記**：Apache Bahir 的 flink-connector-redis 已停維——自寫 ~80 行薄 sink（Jedis 是千錘百鍊的 client，sink 只是 glue）是業界常態做法，非造輪子（薄 glue ≠ 重依賴重寫）。

### 寫入 schema（★ 接縫 A——**假設形狀，P6 推薦 design 產出後以其為單一真源**）

P6 推薦 brief §接縫 A 只給了 key 風格示意（`feat:user:{user_pseudo_id}`）。本 design 採**即時特徵獨立 key 前綴 `feat:rt:`**的假設（不與離線特徵共寫同一 key——避免 TTL 互相踩踏與雙寫方所有權糾纏；讀取端合併），欄位級如下：

| key | 型別 | fields | TTL |
|---|---|---|---|
| `feat:rt:user:{user_pseudo_id}` | HASH | `cat_view_5m:<item_category>`＝int（F1，每類別一 field）；`session_events`＝int、`session_cart_pending`＝int、`session_started_at`＝ms epoch（F3a；session timer 清除時 HDEL 這三欄）；`updated_at`＝ms epoch（**event-time**） | **1800s**，每次寫 `EXPIRE` 續期 |
| `feat:rt:item:{item_id}` | HASH | `pop_15m`＝int、`purchase_15m`＝int（F2）；`updated_at`＝ms epoch | 1800s 同上 |

- **合併規則假設**：離線特徵（P6 批次寫 `feat:user:{id}`/`feat:item:{id}`）與即時特徵**分 key、讀取端合併**；Flink 永不觸碰 `feat:`（無 `rt:`）鍵空間。
- **需回報 P6 對齊的點**（不 fork、單點吸收）：(1) `feat:rt:` 前綴與分 key vs 同 key 合寫的裁定——若 P6 定同 key 合寫，改動收斂在 `RedisFeatureSink` 的 key-builder 與「HSET 不帶 EXPIRE」兩處，job 邏輯零改；(2) TTL 值；(3) `cat_view_5m:<category>` 的 field 命名法。§14 實查 6 列為 plan 前對齊項。
- **Redis 部署歸屬 P6**（其 brief 開放問題 5：單機 Deployment+PVC 傾向）——本 spec 只引用假設 DNS `redis.data.svc:6379`（實查 6 校準）；本 spec 的整合測試用 job 測試容器內起 redis（不依賴 P6 先落地，§12）。
- **event-time `updated_at` 的誠實揭露**：重放場景下此值是 2020 年的事件時間——讀取端做新鮮度判斷會視為 stale，**這是對的**（重放資料本來就不新鮮）；真 intraday 流接上時該值自然是「剛剛」。寫進 known-limit 與 /streaming Explainer。

---

## 7. 正確性對照（接縫 K；決定）

### 驗證輸出（KafkaSink → `ga4.rt.verification`）

`VerificationRecord` JSON，三種 kind（`DeliveryGuarantee.AT_LEAST_ONCE`；下游 UPSERT 去重）：

| kind | 欄位 | 發出時機 |
|---|---|---|
| `sliding_user_cat` | user_pseudo_id, item_category, window_end, view_count_5m | 僅 `window_end` 整點（job 內過濾，控量） |
| `sliding_item` | item_id, window_end, pop_15m, purchase_15m | 僅整點 |
| `session` | user_pseudo_id, session_start_ts, session_end_ts, events_count, items_carted, items_purchased, cart_pending_final, session_revenue | F3b 關窗即發（全量） |

### `ga4_realtime_correctness` DAG（手動；`consume → load → compare → export_report`）

1. **consume_verification**：confluent-kafka（group `ga4-verify-loader`，P3 手動 commit 慣例）讀 `ga4.rt.verification` 至 watermark 尾 → psycopg2 UPSERT 進 Postgres `stream` schema 三表：`flink_user_cat_window`（PK user+category+window_end）、`flink_item_window`（PK item+window_end）、`flink_session_agg`（PK user+session_start_ts）。UPSERT = at-least-once 驗證流的去重收口。
2. **compare**（SQL，對照兩個真值源）：
   - **判準 A（決定性，滑窗）**：對每筆 `flink_item_window`／`flink_user_cat_window`，用 `silver.ga4_events` 重算同視窗計數（`event_ts ∈ (window_end - size, window_end]`，Silver PK 天然去重）——**要求 mismatch = 0（100% 精確相等）**。這是 event-time 正確性的硬證明：兩條路徑（串流增量 vs 批次重算）同一資料同一語意必須同值。
   - **判準 B（決定性，session 規則重算）**：SQL gaps-and-islands 在 `silver.ga4_events` 上重算「per user、30min gap」sessionization（與 F3b 同規則）→ 與 `flink_session_agg` 全欄比對——**要求 100% 相等**（同規則兩實作必收斂）。
   - **判準 C（語意對照，vs Gold；接縫 K 正身）**：`flink_session_agg` ↔ `gold_ga4_sessions`（地基 §5.3）以 (user, 時間跨度重疊) 配對，分類 1:1／split／merge：**1:1 配對率 ≥ 90%（預設傾向，§14 實查 7 以 gold session 間隔分佈校準），1:1 對內 `events_count` 等值率報告值**。差異根因誠實記錄：gold 按 `ga_session_id` 分組（GA4 自身 sessionization，且濾掉 null session）、Flink 按 30min gap——兩者語意近似但非同義，**mismatch 是資訊不是 bug**（報告列 split/merge 明細）。
   - **去重斷言**：Prometheus 抓 `ga4_dedup_duplicates_dropped_total` ≥ 注入數 × 0.9（sentinel/邊界寬容），且判準 A/B 的 100% 本身就證明重複未污染計數。
3. **export_report**：產 `ga4_realtime_correctness.json`（P4 統一信封：`dataset/generated_at/source_tables/status/row_count` + sections `sliding_item/sliding_user_cat/session_rule_exact/session_vs_gold/dedup/replay_meta{run_id,speedup,replay_date}` + **`disclaimer: "labeled event-replay of public GA4 sample; not live traffic"`**）→ 走 P4 匯出路徑（MinIO → host `make export-sync` → 人審 commit）。P4 的 11 檔清單 **additive +1**（P4 §4 政策內）。

---

## 8. 部署形狀（`FlinkDeployment` CRD 全文級）＋ CI

### `ingestion/streaming/k8s/flinkdeployment.yaml`

```yaml
apiVersion: flink.apache.org/v1beta1
kind: FlinkDeployment
metadata:
  name: ga4-realtime-features
  namespace: data
spec:
  image: ghcr.io/<owner>/trend-intelligence-platform/ga4-flink-job:sha-<tag>   # CI yq bump 落點
  flinkVersion: v2_0
  serviceAccount: flink                      # rbac.yaml 建（operator quickstart 形狀）
  flinkConfiguration:
    taskmanager.numberOfTaskSlots: "2"
    state.backend.type: rocksdb              # Flink 2.0 新鍵（context7 查證）
    execution.checkpointing.interval: 30s
    execution.checkpointing.mode: EXACTLY_ONCE
    execution.checkpointing.incremental: "true"
    execution.checkpointing.dir: s3p://flink/checkpoints/ga4-realtime-features
    execution.checkpointing.savepoint-dir: s3p://flink/savepoints/ga4-realtime-features
    high-availability.type: kubernetes
    high-availability.storageDir: s3p://flink/ha/ga4-realtime-features
    s3.endpoint: http://minio.data.svc:9000
    s3.path.style.access: "true"
    metrics.reporter.prom.factory.class: org.apache.flink.metrics.prometheus.PrometheusReporterFactory
    metrics.reporter.prom.port: "9249"
  podTemplate:
    spec:
      containers:
        - name: flink-main-container
          env:                                # MinIO 憑證走既有 secret（P1 minio-root），零硬編碼
            - name: AWS_ACCESS_KEY_ID
              valueFrom: {secretKeyRef: {name: minio-root, key: root-user}}
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom: {secretKeyRef: {name: minio-root, key: root-password}}
            - name: KAFKA_BOOTSTRAP
              value: trend-kafka-kafka-bootstrap.data:9092
            - name: REDIS_URL
              value: redis://redis.data.svc:6379        # 接縫 A 假設 DNS，實查 6 校準
  jobManager:
    resources: {requests: {memory: 1024m, cpu: "0.5"}, limits: {memory: 1280m, cpu: "1"}}
  taskManager:
    replicas: 1
    resources: {requests: {memory: 1536m, cpu: "0.5"}, limits: {memory: 2048m, cpu: "1"}}
  job:
    jarURI: local:///opt/flink/usrlib/ga4-realtime-features.jar
    parallelism: 2
    upgradeMode: last-state                   # 帶 checkpoint 滾動升級（HA 已配齊）
    state: running
```

（secret key 名 `root-user`/`root-password` 依 P1 `minio-root` 實際欄位，plan 落地校準；憑證經 env 注入、CR 內零明碼——P0 §7 姿態。）

### image（`ingestion/streaming/flink-job/Dockerfile`）

`FROM flink:2.0.0-java17`（確切 tag 實查 2）→ `mkdir plugins/s3-fs-presto && cp opt/flink-s3-fs-presto-2.0.0.jar plugins/s3-fs-presto/`（plugin 進 image、部署決定性，不用 `ENABLE_BUILT_IN_PLUGINS` 執行期 env）→ `COPY target/ga4-realtime-features.jar /opt/flink/usrlib/`。

### GitOps / CI

| 件 | 形狀 |
|---|---|
| `flink-operator.yaml`（wave 14） | Helm chart 1.12.0，repo `https://downloads.apache.org/flink/flink-kubernetes-operator-1.12.0/`；namespace `flink-operator`；values `watchNamespaces: [data]`（確切 key 實查 1）；CRD 大 → syncOptions `ServerSideApply=true`（kube-prometheus-stack/Strimzi 前例） |
| `ga4-streaming.yaml`（wave 15） | kustomize：`ingestion/streaming/kafka` + `ingestion/streaming/k8s` 兩 base；FlinkDeployment/KafkaTopic 資源加 `SkipDryRunOnMissingResource=true` |
| `streaming-monitoring.yaml`（wave 16） | `platform/monitoring/streaming/`（PodMonitor + PrometheusRule + dashboard ConfigMap） |
| `streaming-ci.yaml`（新） | 觸發 paths `ingestion/streaming/flink-job/**`（**不含 k8s/、kafka/**）；job：temurin JDK17 + `mvn -B verify`（§12 單元/harness 全套）→ buildx 出 `ga4-flink-job` image → **yq bump `ingestion/streaming/k8s/flinkdeployment.yaml` 的 `.spec.image`**（CR 非 kustomize images transformer 管轄——對 CRD 用 yq 直改 spec 欄位，等價 P3 bump newTag 的落點紀律）；迴圈防護 = paths 排除 bump 落點 + `[skip ci]`（P0 雙保險）；GHCR 新 package 首推手動設 public（P0 gotcha） |
| `airflow-ci.yaml`（改） | paths 增列 `ingestion/streaming/replay/**`；image 增裝 `ga4_replay` 套件（confluent-kafka 已在，零新 pin） |
| `pr-checks.yaml`（改） | 增 java test job（mvn verify，不 build image）與 ga4_replay pytest |

**唯一觸碰的既有資產**：`ingestion/ptt/kafka/kafka.yaml` 的 kafkaExporter regex additive 放寬（§9）。broker 本體/nodepool/既有 topic 零改動（接縫 L 守約：加 topic 不改 broker）。

---

## 9. 可觀測性（決定）

| 源 | 指標 | 接法 |
|---|---|---|
| **Flink PrometheusReporter**（:9249，JM/TM 皆有） | 系統：`flink_taskmanager_job_task_operator_currentInputWatermark`（watermark 推進）、`currentEmitEventTimeLag`、`numRecordsIn/OutPerSecond`、`flink_jobmanager_job_lastCheckpointDuration/Size`、`numberOfFailedCheckpoints`、`numRestarts`、busyTimeMsPerSecond。自訂（operator metric group）：`ga4_dedup_duplicates_dropped_total`、`ga4_late_events_total`、`ga4_deser_errors_total`、`ga4_sentinels_seen_total`、`ga4_redis_writes_total`、`ga4_redis_errors_total` | PodMonitor（`platform/monitoring/streaming/`）selector 對準 operator 生成的 JM/TM pod label（確切 label 實查 5），port 9249 |
| **kafkaExporter**（P3 既有） | `kafka_consumergroup_lag{consumergroup="ga4-flink-features"}`、verification loader group lag | **additive 放寬 Kafka CR regex**：`groupRegex: "(ptt\|ga4)-.*"`、`topicRegex: "(ptt\|ga4)\\..*"`——監控設定欄位改動、非 broker 部署變更（誠實劃界）；Flink 靠 checkpoint 時 commit → lag 有觀測值（§5.1 註記） |
| **operator metrics** | FlinkDeployment 狀態/reconcile | operator Helm 內建，ServiceMonitor 由 chart values 開啟（實查 1 確認 key） |

**告警（PrometheusRule）**：`FlinkCheckpointFailing`（`increase(numberOfFailedCheckpoints[15m]) > 0`，warn）；`FlinkJobRestarting`（`increase(numRestarts[1h]) > 3`，warn）；`FlinkRedisSinkErrors`（`increase(ga4_redis_errors_total[15m]) > 0`，warn）；`FlinkDeserErrors`（同形，warn——重放源是自家 Silver，>0 即 schema 漂移訊號）。**刻意不設 watermark 停滯告警**：重放是間歇性 demo，watermark 停在 sentinel 是常態非故障（真流接上才補此告警，README 註記）。

**Grafana dashboard `ga4-realtime-features`**（ConfigMap sidecar，P0 慣例）：watermark 推進曲線（對 sentinel 目標線）、records in/out、checkpoint 時長/大小、去重丟棄 vs 注入、Redis 寫入/錯誤、consumer lag、restarts。**Flink Web UI**：JM `rest` service 既有（operator 建）——`kubectl port-forward svc/ga4-realtime-features-rest 8081` 看 checkpoint/watermark/背壓（README runbook；截圖素材源，§10）。

---

## 10. 前端／展示（開放問題 7 收斂）

**v1 = 批次對照 JSON 一頁靜態展示 ＋ MCP 工具 ＋ Flink UI 截圖/GIF。不做即時輪詢儀表**——前端是 Vercel 靜態、打不到叢集，任何「偽即時」儀表都是拓撲謊言（brief 傾向採納）。線上串流能力的佐證分工：

| 佐證 | 內容 |
|---|---|
| `/streaming` 靜態頁（P4 additive 新頁） | 讀 `/data/ga4_realtime_correctness.json`。**三層說明式 UI（硬性）**：**Explainer（定義類，預設展開，置頂）**——首段原文：「本頁資料來自**對公開 GA4 sample 的標註事件重放（labeled event-replay）**，**不是真線上流量**。展示的是：若有真即時流（GA4 intraday→Kafka），這套 Flink event-time 拓撲可直接接上；以及串流計算與批次重算的收斂證明。」＋方法論 Explainer（預設收合：watermark/視窗/去重是什麼）；**ChartCaption**——每張對照表下方單行公式（如「mismatch = |串流計數 − 批次重算計數| > 0 的視窗數」）；**InfoTooltip**——speedup/gap/bound 等參數語意。內容：判準 A/B/C 結果卡、session split/merge 明細表、去重統計、重放參數。 |
| MCP 工具（P4 FastMCP additive +1） | `get_stream_correctness()`：回傳對照 JSON 全文，**回應固定含 `disclaimer` 欄**（重放語意標註）。仍守 P4 拓撲：MCP 在 Horizon 讀公開 `/data/*.json`，不碰叢集。 |
| 截圖/GIF（repo `docs/img/streaming/`，P5 執行期產） | Flink UI checkpoint 頁、watermark 推進、job graph；`redis-cli HGETALL feat:rt:item:<id>` 前後對比；殺 TM pod 恢復 GIF（§13-8）。每張圖說含「事件重放示範」字樣。 |

---

## 11. 沿用慣例與取材界線（進化非複刻）

| 既有資產 | 沿用什麼 | 本 spec 新造什麼 |
|---|---|---|
| P3 Kafka（Strimzi trend-kafka） | broker/nodepool/exporter 整套不動；KafkaTopic CR 宣告式建 topic；bootstrap DNS 慣例；confluent-kafka producer `acks=all`+idempotence+flush 檢查；手動 DAG 先例（`ptt_replay_dlq`→`ga4_replay`/`ga4_realtime_correctness`） | topic ×2；**offset 姿態刻意對照**：P3 手動 commit vs Flink checkpoint 內建（README 敘事） |
| 地基（GA4） | Silver `ga4_events` 欄位照搬進訊息 schema（合約一致）；PK 四鍵 = 去重鍵；`gold_ga4_sessions` = 對照真值；Postgres serving 副本讀取 | 重放語意信封 `_replay`；sentinel 機制 |
| P0/P1 GitOps/監控/儲存 | Helm-operator 判準、sync-wave 接續、ServerSideApply/SkipDryRun、PodMonitor/PrometheusRule/dashboard ConfigMap、MinIO（新 bucket `flink` 進 P1 mc init Job 清單 additive）、`minio-root` secret 注入 | FlinkDeployment CRD（本 repo 第一個 Flink 資產）、第一個 JVM CI（Maven） |
| P4 匯出/MCP | 統一 JSON 信封、export-sync 人審 commit、additive-only、FastMCP 工具形狀 | correctness 報告 dataset、`/streaming` 頁 |
| 課程串流素材（NORTH_STAR 素材地圖） | 只取「滑窗/session/去重」的**題目形狀**當代表性特徵選題參考 | 全部實作、拓撲、對照方法為本 spec 原生；無任何課程專案結構複刻 |

---

## 12. 測試策略（每步可測）

| 層 | 測試 | 跑在哪 |
|---|---|---|
| Java：反序列化 | 正常信封/壞 JSON→null+counter/sentinel 判別/`_replay.replayed_at` **未被任何特徵路徑讀取**（靜態斷言：TimestampAssigner 只讀 event_ts_micros） | streaming-ci |
| Java：去重 | `KeyedOneInputStreamOperatorTestHarness`：首見放行/重複丟棄+計數/TTL 過期後重見放行（時間推進） | streaming-ci |
| Java：F1/F2 視窗 | harness 餵亂序 event-time 序列 → 斷言各 window_end 計數；遲到事件（watermark 後）進 side output 計數不進主流 | streaming-ci |
| Java：F3a | timer harness：view→cart→purchase 序列的 `session_cart_pending` 演進；30min 無事件 timer 清 state + 發清除更新；跨 session 邊界重置 | streaming-ci |
| Java：F3b | session 視窗合併（兩段 <30min 間隔合一）、sentinel 推 watermark 後關窗 fire | streaming-ci |
| Java：Redis sink | mock Jedis：命令全為 HSET/HDEL/EXPIRE（**無 INCR 守門**）；同一 FeatureUpdate 重複套用終態不變（冪等）；snapshotState flush 順序斷言 | streaming-ci |
| Python：重放 | 排序決定性（PK tiebreak）；pacing 數學（speedup/cap）；dup 注入決定性（seed=run_id）；sentinel ts 公式（max+30m+30s+1s）與 per-partition 指派；信封 schema | airflow-ci |
| DAG | DagBag import；兩 DAG `schedule=None` 守門；params 預設值 = `pipeline.yaml ga4_replay:` 區塊（單一真源）；correctness DAG 依賴鏈 | airflow-ci |
| 對照 SQL | SQL builder 單元（視窗邊界半開區間 `(end-size, end]`、gaps-and-islands 正確性用小 fixture 在 CI Postgres service container 跑） | airflow-ci |
| 整合（本機） | flink-job `mvn verify` 含 MiniCluster 整合測試：testcontainers 起 Kafka+Redis → 餵 20 事件含 dup+sentinel → 斷言 Redis 終態與驗證輸出 | streaming-ci |
| 端到端 | `scripts/verify-streaming.sh`（§13） | `make streaming-verify` |

---

## 13. 端到端驗收（`make streaming-verify`；前置 = 地基 `make ga4-verify` 綠 + 回放至少 1 日資料在 Silver + P6 Redis 已部署或本 spec 測試 Redis 起立）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | ArgoCD 3 新 app 收斂 | flink-operator/ga4-streaming/streaming-monitoring 全 `Synced`+`Healthy` |
| 2 | FlinkDeployment 就緒 | CR status `JOB_STATUS: RUNNING`；`mc ls flink/checkpoints/…` 有新鮮 checkpoint（30s 間隔證據） |
| 3 | KafkaTopic ×2 `Ready` | Strimzi Topic Operator 收斂 |
| 4 | 觸發 `ga4_replay`（2020-11-01, speedup=60, dup_ratio=0.01） | dagrun `success`；Kafka 有訊息（offset 前進） |
| 5 | watermark 收斂 | Prometheus `currentInputWatermark` 達 sentinel 目標值（= 視窗全關） |
| 6 | Redis 特徵可讀 | `HGETALL feat:rt:item:<驗證腳本從 silver 取的高熱 item>` 非空且 TTL ∈ (0,1800]；`feat:rt:user:*` 抽樣有 session 欄位 |
| 7 | 觸發 `ga4_realtime_correctness` → 報告斷言 | 判準 A mismatch=0；判準 B 100% 相等；判準 C 1:1 率 ≥ 0.9（實查 7 校準後定版）；dedup dropped ≥ 注入 × 0.9 |
| 8 | **容錯 demo** | 重放進行中 `kubectl delete pod`（TM）→ job 自 checkpoint 恢復、重放完後判準 A/B 仍 100%——**RocksDB checkpoint + at-least-once + 冪等 sink 的可展示證據**（P3 驗收 #11 同型） |
| 9 | **速率無關性（event-time 正確性核心證據）** | 以 speedup=600 重放同一日 → correctness 報告與 speedup=60 逐 byte 等值（視窗結果與重放速率解耦） |
| 10 | 冪等 | 同 params 重跑 `ga4_replay`+correctness → `stream.*` 三表列數不膨脹（UPSERT）、Redis 終態同值、報告等值 |
| 11 | 主線無損 | `yt_trending_hourly` 與 `ga4_daily` 最近 dagrun 仍 success（additive 可執行證明） |
| 12 | 匯出+展示 | `ga4_realtime_correctness.json` 過 P4 validate；`/streaming` 頁本地 build 渲染含 Explainer 揭露首段；MCP 工具回傳含 `disclaimer` |

---

## 14. plan 前需實查（設計已收斂，以下為落地校準點，皆帶預設傾向）

1. **operator 1.12.0 Helm values**：`watchNamespaces` 確切 key、operator ServiceMonitor 開關、CRD 隨 chart 安裝的 ServerSideApply 必要性（傾向：與 Strimzi 同型處理即可）；同時查是否已有 1.13+ 支援 `v2_1`/`v2_2`（傾向：留 1.12.0/v2_0，穩定優先；若有則兩欄位升級）。
2. **Flink 官方 image 確切 tag**（傾向 `flink:2.0.0-java17`；以 Docker Hub tags 為準）＋ s3 plugin jar 路徑名（傾向 `opt/flink-s3-fs-presto-2.0.0.jar`）。
3. **flink-connector-kafka 對 Flink 2.0 的最新版**（傾向 `4.0.0-2.0`；Maven Central 校準 patch）。
4. **Flink 2.0 設定鍵複核**：`execution.checkpointing.savepoint-dir` 確切鍵名（2.0 鍵名大換代，逐鍵對 config 文件複核；`state.backend.type`/`execution.checkpointing.dir`/`incremental` 已 context7 查證）＋ PrometheusReporterFactory 類名。
5. **operator 生成 pod 的 label 集**（PodMonitor selector 用；傾向 `app: <deployment-name>` + `component: jobmanager|taskmanager`，runtime `kubectl get pod --show-labels` 校準）。
6. **接縫 A 對齊（最重要的跨 spec 校準）**：P6 推薦 design 產出後，比對其 Redis schema 定稿與本 §6 假設——差異吸收點限 `RedisFeatureSink` key-builder/TTL/EXPIRE 三處；Redis 部署 DNS（假設 `redis.data.svc:6379`）同步校準。**若 P6 design 晚於本層落地，本層以 §6 假設先行、標記 schema `rt-v0`，P6 定稿時做一次 key 遷移（TTL 30 分鐘的資料自然汰換，零遷移成本）。**
7. **gold session 間隔分佈量測**（一條 SQL：session 內事件 gap 分佈 + 跨 session 間隔 <30min 佔比）→ 校準判準 C 的 1:1 預期率（傾向 ≥90%）與 README 差異敘事的實際數字。
8. **Jedis patch 版 + Flink 測試 harness artifact 座標**（`flink-streaming-java` test-jar / `flink-test-utils` 對 2.0 的正確 GAV）＋ testcontainers redis/kafka module 版本。
9. **MinIO `minio-root` secret 的確切 key 名**（P1 落地值）與 mc init Job bucket 清單 additive 改法。
10. **單日重放量體實測**（silver 2020-11-01 展開列數 → 重放時長/驗證表列數），校準 task timeout（90min 設計值）與 dashboard 面板量程。

---

## 15. known-limits（誠實段）＋ 落地後校驗

**known-limits（README 全列）**：
1. **輸入是標註事件重放、非真線上流量**（正本見開頭護欄段）；展示標的 = 架構就緒性 + event-time 正確性，非「我有即時流量」。
2. **sentinel 是有界重放專屬的收尾機制**——真 intraday 流時間自然前進、不需要它；接真流 = 移除 sentinel 邏輯（一個 filter 分支）＋補 watermark 停滯告警。
3. **state TTL 是 processing-time 語意**（Flink 無 event-time TTL）；對重放與真流都足夠（重複只近距離出現），如實記錄。
4. **Redis `updated_at` 在重放下是 2020 年 event-time**——讀取端新鮮度判斷會視為 stale，這是語意誠實非 bug（§6）。
5. **判準 C 的 gold 對照是語意近似**（`ga_session_id` vs 30min-gap），split/merge 差異是兩種 sessionization 定義的資訊，報告如實列（精確性由判準 A/B 的 100% 承擔）。
6. **pacing cap（`max_gap_seconds`）壓縮長空檔的 processing-time 等待**，不影響任何 event-time 計算結果。
7. **單 broker/parallelism 2 的右尺寸規模**——擴縮路徑（加 partition/TM replica/parallelism）是設定級改動，README 一句話。
8. **operator 1.12 支援上限 Flink v2_0**——追新版是 operator/CR 兩欄位升級，非架構變更。
9. **RocksDB 對本狀態量非必要**，是刻意的生產姿態展示（§1③ 誠實註記）。

**落地後校驗（design 自檢，對精確度契約 8 條）**：
- ① 開放問題 7 題全收斂單一決定（§1①②③/§5.3/§4 速率/§6 一致性/§10），零 TBD/兩案並陳；實查點全部帶預設傾向與判準（§14）。
- ② 版本具體且查證：operator 1.12.0 + FlinkDeployment v1beta1 + FlinkVersion enum、Flink 2.0 設定鍵、KafkaSource/watermark 形狀皆 context7 查證（§0 表列查證方式）；未能當場定 patch 的（connector/Jedis/image tag）列實查並給傾向。
- ③ 資料合約欄位級：重放訊息 schema v1（§3）、Redis feature schema（§6，標**假設**與單一真源歸屬）、驗證記錄三 kind 與 `stream.*` 三表 PK（§7）、報告 JSON 信封（§7）。
- ④ 部署形狀具體：FlinkDeployment CRD 全文（§8）、Helm/wave 14–16、CI workflow 與 yq bump 落點、Dockerfile、topic CR 佈局（§2）。
- ⑤ 沿用慣例明講出處（§11 表）：Strimzi/決定性 key/手動 DAG/MinIO secret/匯出信封/PodMonitor 全對齊既有 design 章節。
- ⑥ 進化非複刻：課程串流素材只取題目形狀（§11 末列）；對 P3 的 offset 姿態是對照敘事非重複。
- ⑦ 硬約束貫徹：誠實護欄通篇六個落點（開頭段）；一工一具（Flink 唯一新串流引擎、Airflow 唯一排程器——兩支手動 DAG、Kafka 唯一 messaging——Redis 僅 feature 出口）；拓撲（Flink/Redis 叢集內、前端靜態走匯出、MCP 讀 JSON）；M4 界線明寫（§2）；secret 走既有 k8s Secret；additive（唯一觸碰 P3 的是 exporter regex 且劃界說明）；接縫 A 不 fork（§6 假設 + 單點吸收 + 回報項）。
- ⑧ 每步可測：單元/harness/整合分層（§12）、12 步端到端驗收含容錯與**速率無關性**兩個可展示證據（§13）、對照判準 A/B 為 100% 硬判準、C 為校準後定版的量化判準。
