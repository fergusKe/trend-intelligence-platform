# P3 進階 ingest（PTT 第二來源，Kafka 佇列範式）— Design（Fable 5 產出）

> **狀態**：design 完成，待 Opus 寫 implementation plan。
> **上游**：[`2026-07-08-P3-ptt-ingest-brief.md`](2026-07-08-P3-ptt-ingest-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) + [`2026-07-08-P0-platform-foundation-design.md`](2026-07-08-P0-platform-foundation-design.md) + [`2026-07-08-P1-data-pipeline-design.md`](2026-07-08-P1-data-pipeline-design.md)。已鎖定決策（**佇列範式 = Kafka，KRaft 單 broker、免 Zookeeper；不引入 RabbitMQ/Celery/Redis**；排程只 Airflow；lakehouse 複用 P1；沿用 P0 GitOps）全部沿用，未翻案。
> **版本查證日**：2026-07-08（Strimzi chart 對 `strimzi.io/charts/index.yaml`、Kafka 版本對 Strimzi `release-1.1.x/kafka-versions.yaml`、Python 套件對 PyPI 查證，非記憶；Strimzi CRD 形狀與 confluent-kafka API 以 context7 官方文件驗證）。
> **取材素材**：`ptt-crawler`（唯讀取材，brief 內含 recon 事實 file:line；本設計**取其容錯內核、重造其佇列/部署/落地層**，取材帳見 §11）。

---

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證方式 |
|---|---|---|
| Strimzi Kafka operator Helm chart | **1.1.0** | `strimzi.io/charts/index.yaml`（1.x 世代 = KRaft-only，ZooKeeper 支援已移除） |
| Kafka（Strimzi 管理） | **4.3.0**（Strimzi 1.1.x 的 default/supported 版） | `strimzi-kafka-operator` repo `release-1.1.x/kafka-versions.yaml` |
| confluent-kafka（Python client，producer/consumer/sensor 共用） | **2.15.0** | PyPI |
| beautifulsoup4（Silver parser） | **4.15.0** | PyPI |
| httpx | **0.28.1**（沿用 P1 ingest 選型） | PyPI |
| prometheus-client（consumer 指標） | 隨 lock 解析（成熟穩定，不另 pin 大版） | PyPI |
| pyiceberg / psycopg2 / dbt-postgres / MinIO / Postgres / Airflow | **全部沿用 P1 §0 pin**（不重複開版本） | P1 design |

CI actions 沿用 P0 pin。**P3 不新增任何 Secret**（Kafka 叢集內 plaintext listener、MinIO/Postgres 憑證複用 P1 的 `minio-root`/`lakehouse-postgres`）——`make pipeline-secrets` 零改動。

---

## 1. 為何 Kafka（範式論證；結論已由 Fergus 鎖定，此處是誠實取捨紀錄＝面試敘事）

P3 的存在理由 = **展示跟 P1 批次拉 API 刻意不同的第二 ingest 範式**：不可靠來源（爬蟲）＋佇列驅動分散式消費＋容錯＋反爬。三候選取捨：

| 候選 | 判定 |
|---|---|
| **Kafka + 常駐 consumer Deployment** ✅ | (a) 動用的正是 NORTH_STAR 保留給 P3 的**唯一**串流工具——不另添 broker；(b) 讓 P3 成為真正的**佇列驅動範式**：producer（批次、Airflow 觸發）與 consumer（常駐服務）**生命週期解耦**，consumer 掛掉訊息不掉、重啟續消費，這是 Airflow 批次做不到的故事；(c) at-least-once 用「寫 Bronze 成功後才手動 commit offset」實作，語意等價原碼 Celery `acks_late` 但機制是 Kafka 原生的 offset log；(d) Kafka 是 DE JD 高需求技能，KRaft 單 broker footprint 右尺寸化（同 P1 Spark「要嘛 k8s 原生用它、要嘛不該有它」的精神）。誠實代價：Kafka 是 log 不是 task queue——無 per-message ack/重投遞排程，503 這類暫時性失敗要 consumer 自己 in-process retry + DLQ（§5 設計進去），單向 URL 分派場景可接受。 |
| Celery + RabbitMQ（照搬原碼） | 淘汰：引入 RabbitMQ（第二個常駐 broker）+ Celery（第二套任務系統）雙重違反「一個工作一個工具」；NORTH_STAR 明文不授權。原碼可靠性樣板雖成熟（acks_late/persistent/fork-safe），但其中值得搬的語意（處理成功才確認）在 Kafka 上有同義原生機制，工具代價不值得。 |
| Airflow KubernetesPodOperator `.expand()` 動態映射 | 淘汰：跟 P1 同範式（都是 Airflow 排程拉），P3 差異化歸零——違背 P3 的存在目的。零新工具最紀律，但「紀律」不能取消這個 phase 的訴求本身。 |

**P1 vs P3 範式差異表（design 驗收要求，README/面試敘事直接用）**：

| | P1（YouTube） | P3（PTT） |
|---|---|---|
| 來源可靠性 | 官方 API、穩定 schema | 網頁爬蟲、可能 429/5xx/改版 |
| 觸發→執行 | Airflow task 內同步抓完 | Airflow 只觸發 producer；實際抓取由**常駐 consumer 非同步消費** |
| 失敗單位 | task（一 region-hour 整批） | **單一訊息（單篇文章）**：skip/retry/DLQ 逐篇隔離 |
| 確認語意 | task 成功/失敗 | **手動 offset commit（寫 Bronze 成功才 commit）= at-least-once** |
| 積壓可見性 | DAG 排隊 | **consumer group lag**（Kafka 經典可觀測性指標） |
| 擴縮 | 加 mapped task | 加 consumer replica（≤ partition 數），零程式改動 |

---

## 2. 兩個 k8s 關鍵決策

### ① Kafka 部署 = **Strimzi operator（Helm chart 1.1.0）+ Kafka/KafkaNodePool/KafkaTopic CRD（plain manifest 進 kustomize）**

P1 §1 的判準是：**帶 operator/CRD 的元件用 Helm chart 裝 operator（spark-operator 前例），單純 StatefulSet 服務用 plain manifest（MinIO 前例）**。Kafka 屬於前者：

| 候選 | 判定 |
|---|---|
| **Strimzi operator** ✅ | (a) Kafka 叢集宣告 = `Kafka` + `KafkaNodePool` CRD，topic 宣告 = `KafkaTopic` CRD——**全部進 git、ArgoCD sync，與 GitOps 敘事同構**（對照 spark-operator 的 SparkApplication）；(b) KRaft bootstrap（cluster-id 生成、controller quorum 設定、`kraftMetadata` 卷標記）由 operator 代管，手寫 manifest 這段最易錯；(c) **kafkaExporter 是 Kafka CR 內建欄位**——consumer group lag 進 Prometheus 免自架 exporter（§10 直接受益）；(d) topic 建立不需 init Job（Topic Operator 收斂 KafkaTopic CR），比 MinIO 還得跑 `mc` Job 更乾淨。operator 常駐成本一個小 controller pod，同 spark-operator 量級。 |
| plain KRaft StatefulSet manifest | 淘汰：cluster-id/quorum/listener advertised address 全手工，demo 叢集重建即踩雷；topic 建立還要 init Job；consumer lag 要另裝 kafka-exporter 一個 Deployment。省掉一個 operator 換來三處手工，違反「搬遷不照抄」精神。誠實註記：單 broker 場景手寫可行（finmind 走這路），但 Strimzi 是業界標準且與本 repo 的 operator 慣例一致。 |
| Bitnami Kafka chart | 淘汰：P1 已判定 Bitnami 授權變動後非可長期 pin 的源。 |

### ② Kafka 叢集形狀（右尺寸化）

- **Kafka CR `trend-kafka`**（namespace `data`）：annotations `strimzi.io/node-pools: enabled`、`strimzi.io/kraft: enabled`；`version: 4.3.0`。
- **KafkaNodePool `dual`**：`replicas: 1`、`roles: [controller, broker]`（單節點雙角色 = KRaft 單 broker 正規形狀，context7 驗證過的官方 pattern）；storage `type: jbod` 單卷 `persistent-claim` **10Gi、不寫 storageClassName**（P0 可攜鐵律）、`kraftMetadata: shared`；resources requests `500m/1.5Gi` limits `1/2Gi`。
- **listener**：單一 internal `plain` 9092（`tls: false`、無 authentication）——叢集內 demo 通訊，README 註記雲上改 TLS+SCRAM 是 CR 欄位級改動（Strimzi 代管憑證），程式端只換設定。
- **單 broker 必要 config**（副本數全 1）：`offsets.topic.replication.factor: 1`、`transaction.state.log.replication.factor: 1`、`transaction.state.log.min.isr: 1`、`default.replication.factor: 1`、`min.insync.replicas: 1`、`auto.create.topics.enable: "false"`（topic 只准宣告式建立）。
- **entityOperator**：只開 `topicOperator`（管 KafkaTopic）；`userOperator` 不開（無 KafkaUser 需求，要用才加）。
- **kafkaExporter**：`groupRegex: "ptt-.*"`、`topicRegex: "ptt\\..*"` → 輸出 `kafka_consumergroup_lag` 等指標（§10）。
- bootstrap 位址（Strimzi 命名慣例）：`trend-kafka-kafka-bootstrap.data:9092`（§14 實查 6 落地校準確切 svc 名）。

---

## 3. 總體形狀

### 資料流

```
Airflow ptt_ingest_daily（@daily）
  │ produce_article_urls（PythonOperator：列舉看板分頁 → 文章 URL）
  ▼
Kafka topic ptt.article-urls（3 partitions, RF=1, retention 7d; key=aid）
  │                                ┌─ 暫時性失敗重試耗盡 → ptt.crawl-dlq（14d）
  ▼  常駐 consumer Deployment ×2（group ptt-crawler，enable.auto.commit=false）
[抓原始 HTML：over18 cookie + 靜態 UA + 0.5~1.5s 延遲 + HTTP 三分類容錯]
  │  寫 Bronze 成功 → 手動 commit offset（at-least-once）
  ▼
[Bronze] MinIO s3://bronze/ptt/articles/board=<B>/date=<YYYY-MM-DD>/<AID>.json
  │        （raw HTML + _metadata 信封；決定性 key，重爬覆寫 = 冪等）
  │  Airflow wait_queue_drain（lag==0 sensor）之後
  ▼  parse_bronze_to_silver（PythonOperator：bs4 parser，取材 parsers/article.py）
[Silver] Iceberg lakehouse.silver.ptt_articles（正本；overwrite_filter 冪等）
  │  load_silver_to_postgres（pyiceberg → psycopg2 UPSERT，P1 §5 loader 模式）
  ▼
[Silver serving] Postgres lakehouse.silver.ptt_articles
  │  dbt run / dbt test（KubernetesPodOperator，沿用 P1 dbt image 專案）
  ▼
[Gold] Postgres gold.gold_ptt_board_daily（唯一 mart）→ Grafana / P4 匯出
```

**排程器界線（硬約束，寫死）**：排程器只有 Airflow 一個。producer/parse/loader/dbt 都是 Airflow task；**consumer 是常駐 Deployment ＝「服務」**（由 ArgoCD/k8s 管生命週期，如同 MinIO/Postgres），不是第二排程器——它不排任何工作，只被動消費佇列。Airflow 的 `wait_queue_drain` sensor 只**觀測** Kafka 狀態（lag），不指揮 consumer。

### 目錄結構（沿用 P0 服務接入契約 + NORTH_STAR domain 目錄）

```
ingestion/ptt/                        # P3 全部程式資產
├── pyproject.toml                    # ptt_ingest 套件（producer/consumer/parser 共用一包）
├── Dockerfile                        # consumer image（python:3.12-slim + ptt_ingest[consumer]）
├── src/ptt_ingest/
│   ├── config.py                     # 讀環境變數 + pipeline 常數（無硬編碼憑證）
│   ├── ua.py                         # ★ 內建靜態 UA 清單（取代 fake_useragent，零執行期連外）
│   ├── http.py                       # HTTP 三分類 + Retry-After（整檔搬 utils/http.py 語意）
│   ├── date_infer.py                 # BoardDateInferer 跨年推算（整檔搬 utils/time_range.py 語意）
│   ├── producer.py                   # 看板列舉/分頁/停止條件 → Kafka publish（Airflow 呼叫）
│   ├── consumer.py                   # poll 迴圈 / at-least-once commit / DLQ / SIGTERM 優雅關閉
│   ├── bronze.py                     # Bronze 信封組裝 + boto3 寫入（決定性 key）
│   ├── parser.py                     # HTML → 結構化欄位（取材 parsers/article.py，補測試）
│   └── lag.py                        # consumer group lag 計算（drain sensor 用，confluent-kafka watermark 法）
├── tests/                            # §13：parser fixtures / http 分類 / date_infer / producer 停止條件 / consumer 邏輯
│   └── fixtures/                     # 合成 PTT 文章頁 HTML（自製、不含真實個資）
├── kafka/                            # Kafka 叢集宣告（ArgoCD app: ptt-kafka）
│   ├── kustomization.yaml
│   ├── kafka.yaml                    # Kafka CR（§2②）
│   ├── nodepool.yaml                 # KafkaNodePool dual（replicas 1）
│   ├── topic-article-urls.yaml       # KafkaTopic ptt.article-urls
│   └── topic-crawl-dlq.yaml          # KafkaTopic ptt.crawl-dlq
└── k8s/                              # consumer 部署（ArgoCD app: ptt-ingest）
    ├── kustomization.yaml            # images: newTag ← ptt-ci 唯一改的檔
    ├── deployment.yaml               # consumer ×2 + probes + graceful shutdown
    ├── service.yaml                  # metrics port（ServiceMonitor 對準）
    └── servicemonitor.yaml
orchestration/airflow/
├── Dockerfile                        # += ptt_ingest 套件 + confluent-kafka + beautifulsoup4
└── dags/
    ├── ptt_ingest_daily.py           # 主 DAG（§8）
    ├── ptt_replay_dlq.py             # 手動 DLQ 重播 DAG（schedule=None）
    └── config/pipeline.yaml          # += ptt 區塊（看板清單等單一真源，§4）
lakehouse/dbt/models/
├── staging/stg_ptt_articles.sql      # + _sources.yml 增補 silver.ptt_articles source
└── marts/gold_ptt_board_daily.sql    # 唯一 Gold mart（§7）
platform/
├── argocd/apps/
│   ├── strimzi-operator.yaml         # wave 7（Helm 1.1.0）
│   ├── ptt-kafka.yaml                # wave 8（directory → ingestion/ptt/kafka）
│   ├── ptt-ingest.yaml               # wave 9（kustomize → ingestion/ptt/k8s）
│   └── ptt-monitoring.yaml           # wave 10（directory → platform/monitoring/ptt）
└── monitoring/ptt/                   # dashboard ConfigMap + PrometheusRule + kafka PodMonitor
.github/workflows/ptt-ci.yaml         # 複製 hello-ci 模式（§9）
scripts/verify-ptt.sh                 # 端到端驗收（§14）；Makefile += ptt-verify
```

### Namespace 與 sync-wave（接續 P1 的 3–6）

| wave | Application | namespace | 內容 |
|---|---|---|---|
| 7 | strimzi-operator | `strimzi`（watch `data`） | Helm chart 1.1.0，`watchNamespaces: [data]`；CRD 大，syncOptions 加 `ServerSideApply=true`（同 kube-prometheus-stack 前例） |
| 8 | ptt-kafka | `data` | Kafka CR + NodePool + 2 個 KafkaTopic（CRD 依賴 wave 7，資源註解 `SkipDryRunOnMissingResource=true` 沿用 P0 手法） |
| 9 | ptt-ingest | `data` | consumer Deployment/Service/ServiceMonitor |
| 10 | ptt-monitoring | `monitoring` | dashboard + PrometheusRule + PodMonitor |

syncPolicy 全沿用 P0 標準（automated prune+selfHeal+CreateNamespace+retry）。Kafka 放 `data` ns：與 MinIO/Postgres 同屬資料底座，consumer 同 ns 零跨界網路設定。

### Topic 佈局（決定）

| topic | partitions | RF | retention | 用途 |
|---|---|---|---|---|
| `ptt.article-urls` | **3** | 1 | 7d（`retention.ms: 604800000`） | 待爬文章 URL。partition 3 = 消費並行上限，consumer 2→3 replica 免 repartition；**key = `aid`**（均勻分佈；不用 board 當 key——Gossiping 量體會壓垮單一 partition；爬取無順序需求，犧牲 per-board 順序無代價） |
| `ptt.crawl-dlq` | 1 | 1 | 14d（`1209600000`） | 暫時性失敗重試耗盡的訊息 + 錯誤 metadata；人工檢視/`ptt_replay_dlq` 重播 |

**訊息 schema v1**（JSON value；key = aid bytes）：

```json
{"schema_version": 1, "board": "Gossiping", "aid": "M.1751904000.A.1B2",
 "url": "https://www.ptt.cc/bbs/Gossiping/M.1751904000.A.1B2.html",
 "post_date": "2026-07-08", "title": "<列表頁標題>",
 "enqueued_at": "<UTC ISO>", "producer_run_id": "<dag_run_id>"}
```

`post_date` 由 producer 的 `BoardDateInferer` 從列表頁推得（含跨年修正）——它是 **Bronze 決定性 key 的一部分**（§5），必須在訊息裡帶下去，consumer 不重推。

---

## 4. P3-2 producer（列舉看板 → Kafka；決定）

| 開放問題 | 決定 | 理由 |
|---|---|---|
| 跑法 | **PythonOperator**（`ptt_ingest.producer` 隨 Airflow image 安裝，同 P1 `yt_ingest` 模式） | KubernetesExecutor 下 PythonOperator 本來就是獨立 pod，KPO/一次性 Job 是多餘 indirection；P1 已立此慣例。 |
| 看板清單真源 | `dags/config/pipeline.yaml` 新增 `ptt:` 區塊（對齊 P1 regions 慣例）：`boards: [Gossiping, Stock, NBA]`、`days_back: 2`、`producer_concurrency: 5`、`request_delay: [0.5, 1.5]`、`timeout_seconds: 10` | 3 個看板（高流量+財經+體育，文字風格多樣）demo 足夠且對來源禮貌；加看板 = 改一行 YAML。`days_back: 2` = 每天重掃近兩日視窗，重疊部分重爬 = **推文數自然更新**（feature 非 bug，Bronze/Silver 冪等吸收）。 |
| 分頁/停止條件 | 整搬原碼語意：由 index 最新頁往舊遞減，該頁全部文章 `post_date < window_start` 即停；`asyncio.gather` 跨看板併發 + **共用 `Semaphore(5)`**（沿用原值） | 原碼驗證過的掃描邏輯；Semaphore 5 是對 ptt.cc 的總併發禮貌上限。 |
| 推進佇列 | confluent-kafka `Producer`：`acks=all`、`enable.idempotence=true`；全部發送後 `flush(timeout=60)`，`flush()` 回傳仍有 pending 即 task fail | 冪等 producer 免重複（broker 端去重）；flush 檢查保證「task 成功 = 訊息全部落 broker」。單 broker 下 acks=all 等價 acks=1，寫 all 是為了雲上多副本零改動。 |
| `BoardDateInferer` | **整檔搬語意 + 補單元測試**：PTT 列表只有 MM/DD，由新往舊掃、月份變大即 `year -= 1` | PTT 專屬硬知識、重寫成本高（brief recon 判定）；原碼無 tests，P3 補跨年 fixture 測試（12/31↔01/01 邊界）。 |
| 失敗頁處置 | 頁面級失敗線性退避重試 3 次（沿用原碼 `producer.py:194-218` 語意）；仍失敗 → 寫 MinIO `s3://bronze/ptt/_failed_pages/date=<D>/run=<run_id>.json`（取代原碼本地 `failed_pages.json`）；**單一看板失敗頁 > 50% → task fail**（系統性故障），否則 task 成功 + log warning | 失敗記錄進物件儲存供人工補爬（pod 檔案系統是揮發的）；50% 閾值區分「零星頁壞」與「被封/改版」。 |
| 去重 | producer **不去重**（同一文章跨 run 重複入列）——at-least-once 全鏈路一致，冪等由 Bronze 決定性 key 收斂 | 在 producer 加已爬記錄 = 引入狀態存儲 = 複雜度不成比例（YAGNI）；重複的成本只是一次禮貌延遲的 HTTP GET。 |

---

## 5. P3-3 consumer（爬取 → Bronze；決定）

### 部署形狀

- **Deployment `ptt-consumer` ×2**（`data` ns，image = `ghcr.io/<owner>/trend-intelligence-platform/ptt-consumer:sha-*`）；resources requests `100m/256Mi` limits `250m/512Mi`。
- consumer group **`ptt-crawler`**；`enable.auto.commit=false`、`auto.offset.reset=earliest`、**`max.poll.interval.ms=600000`**（單訊息最壞情況含 429 等待可能超過預設 5 分鐘，拉到 10 分鐘防误判 rebalance）。
- **迴圈 = 逐訊息序列處理**：`poll(1.0)` → 抓取 → 寫 Bronze → `commit(message=msg, asynchronous=False)` → 下一則。單 process 單 in-flight，速率天然被反爬延遲節流。
- **優雅關閉**：SIGTERM handler 設 stop flag → 處理完當前訊息 → `consumer.close()`（自動 leave group、已 commit 的 offset 不丟）；`terminationGracePeriodSeconds: 30`。
- **指標端口**：prometheus_client HTTP `:8000`（§10 指標清單）；liveness/readiness probe 都打 `GET /`（metrics 端口活著 = process 活著；不做深度健康檢查，Kafka 斷線由 lag 告警看見）。
- 環境變數：`KAFKA_BOOTSTRAP`（`trend-kafka-kafka-bootstrap.data:9092`）、MinIO endpoint + `minio-root` Secret 注入。**憑證零硬編碼**。

### at-least-once 語意（顯式合約，對應原碼 acks_late 精神）

```
訊息處理成功 ≡ Bronze 物件 put_object 成功返回
只有在此之後才 commit offset。
consumer crash / pod 重啟 → 未 commit 的訊息由（同 group 的）存活者重新消費 → 重爬 → 覆寫同一 Bronze key。
重複消費無害：Bronze key 決定性（下表），重寫 = 冪等。
```

### 抓取容錯（HTTP 三分類，整檔搬 `utils/http.py` 語意 + Kafka 化的處置）

| 分類 | 判定 | 處置（取代原碼 Celery retry） |
|---|---|---|
| 永久失敗 | 404 / 410（文章被刪）、其他 4xx | **skip**：記 `ptt_crawl_skip_total{reason}` 指標 + log，**直接 commit offset**（不寫 Bronze、不進 DLQ——被刪文是常態非故障） |
| 限流 | 429 | 讀 **`Retry-After`** header（無則 60s），`sleep(min(retry_after, 300))` 後原地重試；記 `ptt_http_responses_total{status_class="429"}` |
| 暫時失敗 | 5xx / timeout / 連線錯誤 | in-process 指數退避重試：base 5s、factor 2、jitter、**最多 3 次**（對照原碼固定 5s×3，進化成指數退避）；耗盡 → 訊息（原 value + `_error` 欄位：最後錯誤、嘗試次數、consumer id）發佈到 `ptt.crawl-dlq`，**然後 commit 原 offset**（故障隔離：單篇壞文不堵住 partition） |

單訊息總重試預算 ≤ 8 分鐘（< `max.poll.interval.ms`），超過即走 DLQ 路徑。

### 反爬設定值（合規邊界 §12 的機械化落地）

| 項目 | 值 | 來源 |
|---|---|---|
| over18 cookie | `over18=1`（PTT 公開年齡確認機制） | 原碼語意 |
| 請求間隨機延遲 | `uniform(0.5, 1.5)` 秒（每篇抓取前） | 原碼值沿用 |
| User-Agent | **內建靜態清單**：`ua.py` 維護 ~12 條當代主流桌面/行動瀏覽器 UA 字串，每請求 `random.choice`。**淘汰 `fake_useragent`**（執行期下載 UA 資料連外 = 供應鏈/網路依賴，brief 已判定）。更新途徑 = 改檔重建 image（有 CI 守門） | design 決定 |
| timeout | 10s（connect+read） | 原碼值沿用 |
| 全域併發 | producer Semaphore 5（列表頁）；consumer 2 replicas × 單 in-flight（文章頁），實效 ≈ 1 req/s 上下 | 右尺寸 + 禮貌 |

### Bronze 落地（修正原碼三問題：無 raw / 無分區鍵 / upsert 覆蓋）

| 項目 | 決定 |
|---|---|
| Key 佈局 | **`s3://bronze/ptt/articles/board=<board>/date=<post_date>/<aid>.json`**——決定性：board/aid 是 PTT 天然唯一鍵，`post_date` 來自訊息（producer 推定，含跨年修正），三者皆與抓取時刻無關 → 同一篇文任何時候重爬都落同一 key，**覆寫 = 冪等**（對齊 P1 §3「key 由 logical 值導出、非 now()」原則）。Hive 式 `board=`/`date=` 讓 Silver parse 按分區掃描零全桶 glob。 |
| 內容格式 | **JSON 信封（raw HTML 全文 + HTTP meta）**，對齊 P1 Bronze `_metadata` 信封慣例：`{"_metadata": {"schema_version": 1, "board", "aid", "url", "post_date", "fetched_at", "status_code", "attempt", "consumer_id", "enqueued_at", "producer_run_id"}, "html": "<!DOCTYPE html>…原文…"}`。淘汰裸 `.html` + S3 object metadata：user metadata 有 2KB 上限且讀取端要多一次 HEAD，信封單物件自含。 |
| 不 parse | Bronze **絕不含衍生欄位**（原碼在寫入前就 parse 掉 category/推噓/IP = 不可重放；本設計 parse 全部推遲到 Silver）——Bronze 鐵律：保原文可重放，parser 修 bug 後重放 Bronze 即可重建 Silver，不必重爬。 |

---

## 6. P3-4 Silver（parse → 清洗表；決定）

### parse 在哪跑：**Python（Airflow PythonOperator），不用 Spark**

| 候選 | 判定 |
|---|---|
| **輕量 Python task** ✅ | 量級誠實：3 看板 × 每日數百~數千篇，bs4 逐篇 parse 秒級-分鐘級完事。P1 動用 Spark 的正當性是**百萬列留言大表**（NORTH_STAR 明文），PTT 量體撐不起 executor 的 JVM 冷啟都不止這時間。**一致性 vs 右尺寸的取捨**：P1 已有 categories 維度「小到不過 Spark」的先例（P1 §3），本設計延用同一判準——**Iceberg/lakehouse 分層照走（架構一致），執行引擎按量體選（右尺寸）**。README 面試敘事照實寫：「什麼時候不用 Spark」跟「什麼時候用」是同一題的兩面。 |
| SparkApplication（對齊 P1 Bronze→Silver） | 淘汰：對此量體是純儀式；且 P3 的差異化賣點是 Kafka 範式，不需要第二個 Spark 展示位。若日後看板擴到重量級（如全站掃描），SparkApplication 模板/operator/RBAC P1 全部現成，切換是加一個 job 檔不是改架構。 |
| 在 consumer 內 parse | 淘汰：違反 Bronze/Silver 邊界（consumer 職責只到「原文落地」）；parser 改版要重放時，佇列裡沒有歷史訊息，Airflow batch parse 才能按分區重放。 |

**寫入路徑**：parse task（`ptt_ingest.parser` + pyiceberg，皆已在 Airflow image）：
1. boto3 列舉 `bronze/ptt/articles/board=*/date=<D>`（D ∈ 本次 crawl 視窗，由 `logical_date` + `days_back` 導出——與 producer 同一公式，決定性）；
2. 逐物件 parse → arrow table；parse 失敗的物件記 `_parse_errors`（log + 計數，不炸整批，>10% 失敗率才 task fail——防 PTT 改版靜默吞資料）；
3. **pyiceberg `table.overwrite(df, overwrite_filter="post_date >= '<start>' AND post_date <= '<end>'")`** → 重跑同視窗 = 整段覆寫 = **冪等**（等價 P1 Spark `overwritePartitions` 的 pyiceberg 版；pyiceberg 0.11 支援 partitioned write + filter overwrite，§14 實查 2 落地煙囪驗證）。

**Silver serving loader**：獨立 task `load_silver_to_postgres`（P1 §5 同款）：pyiceberg 掃同視窗 → psycopg2 `INSERT … ON CONFLICT (board, aid) DO UPDATE`（全欄更新——推文數會隨重爬增長，UPDATE 是語意正確的）。DDL `CREATE TABLE IF NOT EXISTS` 由 loader 持有。

### Silver schema — Iceberg 正本 `lakehouse.silver.ptt_articles`（Postgres serving 副本同構）

粒度：**一列 = 一篇文章（board, aid）**，重爬取最新狀態（推文數演進以最新為準；歷史快照 YAGNI——PTT 分析看討論熱度不看推文 velocity，跟 YouTube 快照粒度的取捨不同，誠實記錄）。

| 欄位 | 型別（Iceberg / PG） | 說明 |
|---|---|---|
| board | string / text | 分區鍵之一（identity） |
| aid | string / text | 文章 ID；PG 側 PK = (board, aid) |
| url | string / text | |
| title | string / text | |
| category | string / text | 標題 `[分類]` 抽取（原碼 parser 邏輯，移到 Silver 才算） |
| author_id / author_nick | string / text | 原碼單一 author 欄位 `id (nick)` **在此拆開**（進化：可分析欄位不塞複合字串） |
| post_ts | timestamptz | **文章頁內完整時間戳正規化**（原碼存原始字串——修正之）；parse 失敗 fallback `post_date` 00:00 + 記 warning |
| post_date | date | 分區鍵之一（identity；= Bronze 分區，追溯一致） |
| content | string / text | 正文（簽名檔/推文區切除，原碼邏輯） |
| ip | string / text | 發文 IP（頁面公開資訊） |
| comments_total / comments_push / comments_boo / comments_neutral | int | 推/噓/→ 計數（原碼 like/dislike 更名為 PTT 語意） |
| comments_score | int | push − boo |
| comments_json | string / text | 推文明細 JSON 字串（**保留不展平**：P3 的 Gold 只需計數；展平成獨立表留到 P2b 若要拿 PTT 推文當語料時再做——YAGNI，寫進 known-limit） |
| bronze_key | string / text | 追溯 Bronze 物件 |
| fetched_at | timestamptz | 該篇實際抓取時間（來自 Bronze `_metadata`） |
| ingested_at | timestamptz | parse 批次時間（freshness 依據，`loaded_at_field`） |

Iceberg partition spec：`identity(board), identity(post_date)`。

---

## 7. P3-5 Gold（唯一 mart；決定）

| 開放問題 | 決定 |
|---|---|
| 做哪張 | **`gold.gold_ptt_board_daily`**（看板×日討論熱度）。淘汰 trending_topics/sentiment：topic 抽取要 NLP（P2 的事，P3 不越界）；board daily 用純 SQL 聚合就完整回答「哪個看板哪天多熱」，正好餵 P4「PTT 討論熱度」面板。**YAGNI：就這一張。** |
| 怎麼建 | **dbt**（對齊 P1 慣例，同一個 dbt 專案/image 加 model，不另立管線）：`_sources.yml` 增補 source `silver.ptt_articles`（`loaded_at_field: ingested_at`，freshness warn 26h / error 50h——日更節奏）+ `stg_ptt_articles`（view，型別防衛）+ mart（table）。 |
| 跨 YouTube 交叉 | **P3 不做**（brief 傾向採納）：留面試敘事「PTT 文中 YouTube 連結抽取可 join 兩源」，實作是 scope creep。 |
| 對 P4 匯出 | 同 P1 Gold→CSV/Parquet 匯出合約（P4 spec 收斂細節）；本 mart 表名/粒度鍵/既列欄位比照 P1 §6a 穩定性政策：只允許 additive 變更。 |

**`gold.gold_ptt_board_daily`** — 粒度 `(board, post_date)`：

| 欄位 | 型別 | 定義 |
|---|---|---|
| board / post_date | text / date | 粒度鍵 |
| articles_count | bigint | count(*) |
| distinct_authors | bigint | count(distinct author_id) |
| comments_total / push_total / boo_total | bigint | sum |
| avg_comments_per_article | numeric | round(avg(comments_total), 1) |
| avg_comment_score | numeric | round(avg(comments_score), 2) |
| hot_articles_count | bigint | count(*) filter (comments_total >= 50)（爆文數，閾值寫 model 常數） |
| top_category | text | 該日該板文章數最多的 category（mode() within group） |

**dbt 測試合約**：generic——`board`/`post_date`/`articles_count` not_null；singular——`assert_unique_grain_ptt_board_daily.sql`（粒度鍵重複出列即 fail）、`assert_ptt_counts_non_negative.sql`（任一計數 < 0 出列）、`assert_ptt_push_boo_bounded.sql`（`push_total + boo_total <= comments_total` 違反出列）。staging 測試：`stg_ptt_articles` 的 `board`/`aid` not_null + `(board, aid)` 唯一（singular）。

---

## 8. Airflow 編排（決定）

### 主 DAG `ptt_ingest_daily`

`schedule="30 2 * * *"`（避開 YouTube hourly 整點）、`catchup=False`（列表頁只有「現在」的狀態，歷史不可回補——同 P1 mostPopular 判定）、`max_active_runs=1`、task `retries=2` + exponential backoff（producer/parse/loader；sensor 除外）。

```
produce_article_urls（PythonOperator：列舉 → publish → flush 檢查）
      ▼
wait_queue_drain（PythonSensor，mode="reschedule"，poke 60s，timeout 3h）
      │   ptt_ingest.lag：group ptt-crawler 對 ptt.article-urls 全 partition
      │   lag = high_watermark − committed（confluent-kafka watermark 法，context7 驗證）
      │   連續 2 次 poke lag==0 才通過（防 producer flush 與 watermark 觀測的邊界競態）
      ▼
parse_bronze_to_silver（PythonOperator：bs4 → pyiceberg overwrite_filter）
      ▼
load_silver_to_postgres（PythonOperator：pyiceberg → psycopg2 UPSERT）
      ▼
dbt_run → dbt_test（KubernetesPodOperator，沿用 P1 dbt image；dbt 以 `--select` 圈 ptt 模型 + source freshness）
```

**drain sensor 的角色**：這是批次（Airflow 下游 transform）與串流（Kafka consumer）的**顯式橋接點**——面試敘事的亮點而非 workaround。失敗模式健全：consumer 全掛 → lag 恆 > 0 → sensor timeout → DAG fail → 告警（§10 的 lag 告警同時也會先響）。sensor 用 `mode="reschedule"` 不佔 worker slot。timeout 3h 依量體估算（~5k 篇 × 2 consumer × ~1.25s/篇 ≈ 1 小時，3 倍餘裕）。

### 輔 DAG `ptt_replay_dlq`（手動，schedule=None）

params：`max_messages`（預設 500）。消費 `ptt.crawl-dlq`（group `ptt-dlq-replay`）→ 剝掉 `_error` 欄位 → 重發佈到 `ptt.article-urls` → commit。用途：來源故障平息後人工重播。**這不是第二排程器**——是一支手動觸發的 Airflow task，工具仍只 Airflow。

DAG 測試（`orchestration/airflow/tests/`）：DagBag import 零錯誤、依賴鏈斷言、`catchup=False`/`max_active_runs=1` 守門、`pipeline.yaml` ptt 區塊 schema 驗證（boards 非空、days_back ≥ 1）。

---

## 9. CI / GitOps 接入（複製既有模式，不自創）

| workflow | 觸發 paths | test | image | tag bump 落點（yq） |
|---|---|---|---|---|
| `ptt-ci.yaml`（新） | `ingestion/ptt/src/**`、`ingestion/ptt/tests/**`、`ingestion/ptt/{Dockerfile,pyproject.toml}`（**不含 k8s/、kafka/**） | ruff + pytest（§13 單元全套） | `…/ptt-consumer` | `ingestion/ptt/k8s/kustomization.yaml` 的 `images[0].newTag` |
| `airflow-ci.yaml`（改） | paths **增列 `ingestion/ptt/src/**` 與 pyproject** | 原 test + ptt 套件測試 | `…/airflow`（image 增裝 `ptt_ingest` + `confluent-kafka==2.15.0` + `beautifulsoup4==4.15.0`） | 不變 |
| `dbt-ci.yaml`（不改） | `lakehouse/dbt/**` 已涵蓋新 model | `dbt parse` | 不變 | 不變 |

已知且接受：改 `ingestion/ptt/src/**` 會同時觸發 ptt-ci 與 airflow-ci（兩個 image 都內含該套件，本來就都要重建）。迴圈防護沿用 P0 雙保險（paths 排除 bump 落點 + `[skip ci]`）。GHCR 新 package `ptt-consumer` 首推後手動設 public（P0 既知 gotcha）。

**librdkafka 依賴註記**：confluent-kafka 2.x PyPI 帶 manylinux wheel（內含 librdkafka），Airflow image（Debian 系）與 `python:3.12-slim` consumer image 皆直接 pip 裝即可；§14 實查 5 落地確認 wheel 可用性。

---

## 10. 可觀測性（決定）

### 指標三源

| 源 | 指標 | 部署 |
|---|---|---|
| **Strimzi kafkaExporter**（Kafka CR 內建欄位，§2②） | `kafka_consumergroup_lag{consumergroup="ptt-crawler", topic="ptt.article-urls"}`（經典 lag 指標）、`kafka_topic_partition_current_offset` | PodMonitor（`platform/monitoring/ptt/`）對準 exporter pod；淘汰自架 kafka-exporter Deployment（operator 已內建）與 broker JMX metricsConfig（lag+up 已夠，要用才加） |
| **consumer 自身**（prometheus_client :8000 + ServiceMonitor） | `ptt_crawl_success_total`、`ptt_crawl_skip_total{reason="gone|other_4xx"}`、`ptt_crawl_dlq_total`、`ptt_crawl_retry_total{kind="transient|ratelimit"}`、`ptt_http_responses_total{status_class="2xx|4xx|429|5xx"}`、`ptt_crawl_duration_seconds`（histogram）、`ptt_last_success_timestamp`（gauge） | `ingestion/ptt/k8s/servicemonitor.yaml` |
| **postgres-exporter 自訂查詢**（P1 既有部署，加 query） | `ptt_freshness_seconds`（`now()-max(ingested_at)`）、`ptt_silver_articles_24h{board}`、`ptt_gold_board_daily_rows` | P1 §9 同款 ConfigMap 增列 |

### 告警（PrometheusRule，`platform/monitoring/ptt/`）

| 規則 | 條件 | 級別 |
|---|---|---|
| `PttConsumerLagStuck` | `kafka_consumergroup_lag > 0` 持續 2h | warn（6h → critical）——consumer 掛掉/來源封鎖的第一訊號 |
| `PttCrawlFailureRateHigh` | `(dlq + skip{other_4xx}) / (success + dlq + skip)` 1h 比率 > 20% | warn——PTT 改版或被擋的訊號 |
| `Ptt429Spike` | `increase(ptt_http_responses_total{status_class="429"}[30m]) > 10` | warn——**反爬觸發即後退**的營運訊號（人工調低併發/延遲參數） |
| `PttDataStale` | `ptt_freshness_seconds > 30h` warn / `> 54h` critical | 日更節奏的新鮮度 |
| `PttConsumerDown` | consumer target `up == 0` 或 absent 10m | warn |

### Grafana

dashboard `ptt-ingest-health`（ConfigMap sidecar，P0 慣例）：consumer lag 曲線、爬取成功/skip/DLQ 比率、429 計數、每板 24h 文章數、Gold mart 列數、freshness。P4 的「PTT 討論熱度」面板吃 Gold mart（P4 spec 收斂）。

---

## 11. 取材帳（搬什麼 / 重造什麼 / 修什麼——「搬遷不照抄」落地）

| 原碼資產（brief recon file:line） | 處置 |
|---|---|
| HTTP 三分類 + Retry-After（`utils/http.py:21-57`、`tasks.py:20-29`） | **整檔搬語意**進 `ptt_ingest/http.py`（httpx 化）+ 補單元測試（§13） |
| `BoardDateInferer` 跨年推算（`utils/time_range.py:52-72`） | **整檔搬語意**進 `date_infer.py` + 補跨年測試——PTT 專屬硬知識 |
| 看板列舉/分頁/停止條件/Semaphore(5)（`producer.py:169-273`） | 搬語意；推進目標 `celery.send_task` → **confluent-kafka publish** |
| 頁面級失敗退避 + `failed_pages.json`（`producer.py:194-218`、`utils/retry.py`） | 搬語意；落點本地檔 → **MinIO `_failed_pages/`** |
| parser 抽取邏輯（`parsers/article.py`） | 搬語意進 `parser.py`；**執行時點從寫入前移到 Silver**；author 拆欄、date 正規化 timestamptz；**補單元測試（原碼零 tests）** |
| Celery acks_late/persistent/prefetch=1（`worker.py:14-32`） | **不搬機制、搬語意**：= 手動 offset commit + 單 in-flight 消費（§5） |
| Celery fork-safe `engine.dispose()`（`worker.py:50-52`） | **不需要**：consumer 是單 process 無 prefork，且不寫 DB（只寫 MinIO）——此樣板在新架構無對應物，誠實記錄 |
| RabbitMQ / Docker Swarm / MySQL upsert 落地 | **全部重造**：Kafka / k8s+ArgoCD / MinIO Bronze＋Iceberg Silver（修 recon 三問題：無 raw→信封保原文；無分區鍵→board/date Hive key；upsert 覆蓋→Bronze 不可變+Silver 冪等 overwrite） |
| `fake_useragent` 執行期連外（`producer.py:29,:44`） | **淘汰**→ 內建靜態 UA 清單（§5） |
| retry 固定 countdown 無指數退避（`tasks.py:13`） | **進化**：指數退避 + jitter + DLQ（§5） |

---

## 12. 反爬合規邊界（姿態聲明，README 同步）

- **只爬公開頁面**：ptt.cc 網頁版公開文章；over18 cookie 是 PTT 自身的公開年齡確認機制，非登入牆/付費牆繞過。
- **尊重來源**：honor `Retry-After`（§5 機械化）、請求間 0.5–1.5s 隨機延遲、全域併發上限（producer 5 / consumer 實效 ~1 req/s）、timeout 10s 不掛連線；429 告警設計成「觸發即人工後退」的營運迴路（§10）。
- **用途**：教育/portfolio demo，看板集刻意收斂 3 板、視窗 2 天，非全站鏡像。
- **資料節制**：作者欄只存頁面公開的 id/nick；測試 fixtures 用**自製合成 HTML**，不 commit 真實文章內容。
- **robots.txt 現況列 plan 前實查**（§14 實查 1）：若 ptt.cc robots 對一般 UA 全面 Disallow，姿態調整為進一步降速 + README 明示 demo 性質與速率上限；設計的速率參數全部集中 `pipeline.yaml`，調整零程式改動。

---

## 13. 測試策略（硬約束「每步可測」；原碼零 tests，P3 全補）

| 層 | 測試 | 跑在哪 |
|---|---|---|
| parser 單元 | `tests/test_parser.py` + 合成 HTML fixtures：正常文/被刪作者行/無分類標題/推噓混合/簽名檔切除/日期正規化/parse 失敗返回 error 物件 | ptt-ci + pr-checks |
| HTTP 三分類 | httpx mock（respx）：404→skip、429（有/無 Retry-After）→限流、5xx/timeout→transient、200→通過 | ptt-ci |
| 跨年推算 | `test_date_infer.py`：12/31→01/01 邊界、同年單調、視窗停止條件 | ptt-ci |
| producer 邏輯 | 分頁停止條件（頁內全部早於視窗即停）、Semaphore 上限、失敗頁 50% 閾值；Kafka publish 以注入 fake producer 驗 payload schema | ptt-ci |
| consumer 邏輯 | 核心迴圈依賴注入（`process_message(fetch_fn, write_fn, dlq_fn)` 純函式化）：成功→commit 順序斷言（**寫 Bronze 先於 commit**）、skip 路徑、retry 耗盡→DLQ→commit、SIGTERM 停止 | ptt-ci |
| Bronze key | 決定性測試：同 (board, aid, post_date) 任意時刻 → 同 key；信封 schema 驗證 | ptt-ci |
| lag 計算 | watermark/committed 組合的單元測試（fake 值） | ptt-ci |
| DAG | DagBag import、依賴鏈、catchup/max_active_runs 守門、pipeline.yaml ptt schema | airflow-ci |
| dbt | `dbt parse`（CI）+ §7 測試合約（叢集 runtime，dbt_test task = DQ gate） | dbt-ci / runtime |
| 端到端 | `scripts/verify-ptt.sh`（§14A） | 本機 `make ptt-verify` |

---

## 14. 端到端驗收 + plan 前需實查

### A. `make ptt-verify`（`scripts/verify-ptt.sh`；前置 = P1 `make pipeline-verify` 綠）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | ArgoCD 4 個新 app（strimzi-operator/ptt-kafka/ptt-ingest/ptt-monitoring）收斂 | 全 `Synced`+`Healthy` |
| 2 | Kafka 就緒 | Kafka CR status `Ready`；2 個 KafkaTopic `Ready`；`trend-kafka-dual-0` pod Running |
| 3 | consumer 就緒 | `ptt-consumer` 2/2 Running，metrics 端口回 200 |
| 4 | 觸發 `ptt_ingest_daily` | dagrun `success`（含 wait_queue_drain 通過 + dbt_test 綠） |
| 5 | Bronze | `mc ls bronze/ptt/articles/board=Gossiping/…` ≥ 1 物件；抽一物件驗信封含 `html` 與 `_metadata` |
| 6 | Silver | Postgres `SELECT count(*) FROM silver.ptt_articles` > 0；`post_ts` 非空比率 > 90% |
| 7 | Gold | `SELECT count(*) FROM gold.gold_ptt_board_daily` > 0 |
| 8 | lag 指標 | Prometheus query `kafka_consumergroup_lag{consumergroup="ptt-crawler"}` 有值且（run 完後）= 0 |
| 9 | 爬取指標 | `ptt_crawl_success_total` > 0 |
| 10 | **冪等** | 重跑步驟 4 同 logical date → Bronze 物件數不膨脹（覆寫）、silver/gold 列數不膨脹 |
| 11 | 容錯 demo | `kubectl delete pod` 殺一個 consumer 於消費中 → 訊息不丟（最終 lag 仍歸 0、Bronze 齊全）——**at-least-once 的可展示證據** |
| 12 | dashboard | Grafana `/api/search?query=PTT` 命中 ptt-ingest-health |

### B. plan 前需實查（設計已收斂，以下為落地校準）

1. **ptt.cc robots.txt / 頁面現況**：robots 政策查證（§12 姿態調整依據）；實抓 1-2 頁校準 parser selector 與 fixtures（原專案非 git 管理、可能落後現網 DOM）。
2. **pyiceberg 0.11.1 partitioned write + `overwrite_filter`** 對 JDBC(sql) catalog 的煙囪驗證（P1 實查 3 驗過「Spark 寫→pyiceberg 讀」；P3 是「pyiceberg 寫」方向，5 分鐘實證）。
3. **Strimzi 1.1.0 chart values**：`watchNamespaces` 確切 key、CRD 隨 chart 安裝時 ArgoCD 是否需 `ServerSideApply=true`（設計已預設加上，落地確認）。
4. **kafkaExporter 指標名/label 現值**（`kafka_consumergroup_lag` 為社群慣例名，以 runtime `/metrics` 實測為準）+ exporter 的 PodMonitor 對準目標（pod label）。
5. **confluent-kafka 2.15.0 manylinux wheel** 在 `apache/airflow:3.2.2` 與 `python:3.12-slim` 兩 image 的安裝驗證。
6. **Strimzi bootstrap Service 確切名**（`trend-kafka-kafka-bootstrap` 為命名慣例推導，`kubectl -n data get svc` 校準）。
7. 每板實際文章量體實測 → 校準 drain sensor timeout（3h 設計值）與 `PttDataStale` 閾值。

---

## 15. 落地後校驗（design 自檢摘要）

- brief 六簇開放問題全部收斂為決定，零 TBD/兩案並陳：**Kafka 部署 = Strimzi operator（§2①）**、**topic/offset 佈局（§3：2 topics、3+1 partitions、group `ptt-crawler`、手動 commit=at-least-once）**、**Bronze key = `bronze/ptt/articles/board=/date=/<aid>.json` 信封（§5）**、**Silver parse = Python 非 Spark（§6，右尺寸論證）**、**Gold = `gold_ptt_board_daily` 一張 dbt mart（§7）**、**UA = 內建靜態清單（§5）**。
- 硬約束對照：①沿用 P0/P1 慣例（`ingestion/ptt/`、kustomize+子 Application wave 7–10、CI 複製 hello-ci、無 storageClassName、lakehouse 複用 P1 MinIO/Iceberg/Postgres/dbt）②工具紀律（messaging 只 Kafka；排程只 Airflow——consumer 是服務非排程器，界線 §3/§8 寫明；無新 DB/儲存）③Bronze 保原文+決定性 key+冪等（修 recon 三問題，§5/§11）④反爬合規（§12：公開頁/Retry-After/延遲/UA 靜態化）⑤at-least-once 顯式（§5 合約框）⑥範式差異化論證（§1 差異表）⑦每步可測（§13，parser 測試補齊）。
- P3 與 P2 相互獨立（只依賴 P1 lakehouse），可並行實作；對 P4 的產出 = `gold_ptt_board_daily`（穩定性政策同 P1 §6a）。
- 新增常駐 footprint 誠實帳：Strimzi operator pod + Kafka broker pod ×1 + consumer pod ×2（NORTH_STAR：本專案 k8s 常駐是目的非壞味道）。
