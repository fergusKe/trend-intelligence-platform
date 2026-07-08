# P3 進階 ingest（PTT 第二來源）— 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) + **P0 design**（平台/GitOps/CI/監控慣例）+ **P1 design**（Bronze→Silver→Gold medallion、MinIO/Iceberg、Airflow、服務接入契約——P3 要對齊同一套 lakehouse）→ `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P3-ptt-ingest-design.md` → （plan 延後）。
> **精確度要求**：每個開放問題在 design 收斂成明確決定；技術選型具體到工具版本、佇列/消費者形狀、Bronze/Silver schema、DAG/consumer 結構、檔案路徑。
> **定位**：P3 是**第二 ingest 範式**——跟 P1「批次拉 API」**刻意不同**的一條 ingest（處理不可靠來源 + 佇列 + 分散式消費 + 容錯 + 反爬）。這是本專案對純 DE portfolio 的**差異化硬實力**（爬蟲是稀有加分技能），也是唯一會動用 NORTH_STAR 保留的串流工具的階段。

## 為什麼（問題）
NORTH_STAR：真實 DE ingest 以 API/DB/串流/檔案為主、**爬蟲是加分稀有技能**；P3 補上「處理不可靠來源＋佇列＋容錯＋反爬」。**關鍵**：P3 若又做成「Airflow 批次拉頁面」就跟 P1 同範式、零差異化——P3 的存在價值就是**展示一個跟 P1 不同的 ingest 範式**（佇列驅動的分散式消費 / 串流）。

取材專案 `ptt-crawler` **已有一套成熟的分散式爬蟲可靠性實作**（Celery acks_late + fork-safe + HTTP 三分類容錯 + PTT 反爬），但 recon 證實它**綁在 Docker Swarm + RabbitMQ + Celery + MySQL 覆蓋式落地**（見下「已查到的事實」），跟本平台的 k8s / lakehouse / 工具紀律**不相容**。**P3 的核心工作＝把「可靠性 pattern」搬到 k8s 上一個符合工具紀律的佇列範式、並把輸出改成 lakehouse Bronze→Silver**（取材其容錯內核，重造其佇列/部署/落地層）。

## 已鎖定決策（NORTH_STAR + 前階段，勿翻案）
- **PTT 爬蟲 = 第二 ingest 範式**（P3）；主幹仍是 YouTube（P1），P3 是加分不是主線。
- **🔒 佇列範式 = Kafka（2026-07-08 Fergus 拍板鎖定，不再是「候選」）**：KRaft 單 broker、免 Zookeeper。**不引入 RabbitMQ、不引入 Celery、不引入 Redis**（NORTH_STAR：串流只 Kafka、且只在 P3）。下方「首要決策」表保留三候選的比較**僅供 design 論證取捨用**，結論已定＝Kafka；Fable 5 不需再選，只需把 Kafka 方案的細節收斂完整（Strimzi vs plain manifest、topic 佈局、offset 語意等）。
- **一個工作一個工具**：排程只 Airflow、DB 只 Postgres、物件儲存只 MinIO、監控只 Prom+Grafana。messaging 就 **Kafka 一個**。
- **對齊 P1 lakehouse**：PTT 資料走同一套 medallion（Bronze 原始 → Silver 清洗 → 視需要 Gold），用同一個 MinIO/Iceberg/Postgres/Airflow，不另立資料棧。
- **部署**：沿用 P0 GitOps（ArgoCD app-of-apps）+ GitHub Actions CI + 雲端可攜 manifest；服務進 `ingestion/`（PTT 子目錄）。
- **執行環境 = 本地 k8s**（kind），零雲成本。

## 已查到的事實（recon `ptt-crawler`，2026-07-08，唯讀取材別重探；路徑省略共同前綴 `.../ptt-crawler/`；⚠️非 git repo、無 tests 目錄）

### A. 分散式架構與可靠性（現況 = Docker Swarm + Celery + RabbitMQ）
- **producer = 一次性 async batch**（`asyncio.run` 跑完即結束，非常駐）：`crawler/producer.py:224-273`；所有 enabled 看板併發 `asyncio.gather`（`:251`）、跨看板共用 `asyncio.Semaphore(5)`（`:239,:269`）。分頁由新往舊遞減直到早於 `start_date`（`:169-191,:141`）。**推進佇列用 `celery.send_task("crawler.tasks.crawl_article", queue="ptt")`**（`:181,:206`）。
- **Celery 可靠性設定**（全集中 `crawler/worker.py:14-32`）：`task_acks_late=True`（`:29`）、`task_reject_on_worker_lost=True`（`:30`）、`task_default_delivery_mode="persistent"`（`:31`）、durable Exchange/Queue（`:12,:21`）、`worker_prefetch_multiplier=1`（`:26`）、`task_ignore_result=True`（`:27`）。**retry 在 task 層**：`max_retries=3, default_retry_delay=5`（`crawler/tasks.py:13`），**固定 countdown 無指數退避**（`:22,:25,:60`）。
- **broker = RabbitMQ**（AMQP，`crawler/config.py:9-15`）；**無 result backend**（結果直接 upsert MySQL）。RabbitMQ 被 crawler 與 Airflow(CeleryExecutor) **雙重共用**（獨立 vhost，`services/airflow.yml:4-7`、`services/infra.yml:43-60`）。
- **DB fork-safe（Celery prefork 正解）**：全域 `create_engine(..., pool_pre_ping=True)`（`config.py:67`）+ **`@worker_process_init.connect → engine.dispose()`**（`worker.py:50-52`）+ worker_ready 冷啟重試 60s 等 MySQL（`worker.py:35-47`）。
- **反爬/容錯**：over18 cookie（`producer.py:47`、`utils/http.py:36`）、請求前隨機延遲 0.5~1.5s（`producer.py:42-43`、`config.py:31-32`）、`fake_useragent` 每請求換 UA（`producer.py:29,:44`；⚠️**執行期下載 UA 資料會連外**）、timeout 10s（`config.py:33`）。**HTTP 錯誤三分類**（容錯內核）：`TransientFetchError`（`utils/http.py:21-26`），404/410→永久 skip、429→讀 `Retry-After`、5xx/timeout→transient（`utils/http.py:40-54`），task 端據此 retry vs skip（`tasks.py:20-29`）。頁面級失敗線性退避重試 3 次（`producer.py:177-178,:194-218`）+ 失敗頁寫 `failed_pages.json` 供人工補爬（`utils/retry.py:16-29`）。

### B. 資料輸出形狀（現況 = MySQL 覆蓋式，非 lakehouse-friendly）
- 落地 = **MySQL 8.4 單表 `articles`**（`crawler/config.py:42-64`），複合 PK `board+aid`（`:49-50`），寫入 **`INSERT ... ON DUPLICATE KEY UPDATE` 覆蓋全欄**（`crawler/tasks.py:53-57`）。
- 欄位（已 parse 過，非原始）：`board/aid/author/title/category/content/date(原始字串未正規化)/ip/comments_total/comments_like/comments_dislike/comments_neutral/comments_score/url/crawl_time/comments(JSON)`（`config.py:49-64`、`parsers/article.py`）。
- **對 lakehouse Bronze 不友善的三點**：①**無 raw HTML/response 保存**（寫入前已 parse 衍生 category/推噓計數/IP，`parsers/article.py:68,:84-116`）；②**upsert 覆蓋、無 append/無版本快照**（違 Bronze 不可變）；③**無分區鍵**（只有單一 `crawl_time`，無 run_id/ingest_date partition）。→ 當第二 ingest 進 Bronze **需改寫落地層**。

### C. 對新平台的取材評估
- 現況部署 = **獨立常駐 Celery worker Deployment**（Swarm `replicas:2`，`services/stack.yml:108-134`）+ Airflow **只當觸發器**（DAG task 內 `asyncio.run(run_board)` 把 URL 丟進 RabbitMQ，不透過 KPO、不直接爬，`airflow/dags/ptt_daily_crawl.py:33-47`）。**全庫無任何 k8s 資產**（grep 僅 Swarm）。
- **最該偷的 3 段**（recon 判定）：①Celery fork-safe + at-least-once 樣板（`worker.py:14-32` + `:50-52`）；②HTTP 三分類 + Retry-After（`utils/http.py:21-57` + `tasks.py:20-29`）；③`BoardDateInferer` PTT 跨年份推算（`utils/time_range.py:52-72`，PTT 版面只有 MM/DD，往舊掃月份變大即 `year-=1`——PTT 專屬硬知識、重寫成本高）+ 頁面級失敗退避（`producer.py:194-218`）。②③與傳輸/佇列無關，可整檔搬；①的語意（at-least-once）要看選哪個佇列範式而重新實作。
- **最大搬遷成本**：RabbitMQ 是額外常駐 broker（`services/infra.yml:24-60`），與工具紀律衝突；Swarm→k8s 整套換；producer(Job 語意) vs worker(Deployment 語意) 生命週期不同；輸出覆蓋式無 raw（見 B）。

## 首要決策 → 已鎖定 Kafka（下表僅供 design 論證取捨，不需再選）

P3 的差異化＝「佇列驅動的分散式容錯 ingest」。**結論已定＝Kafka**（Fergus 2026-07-08 拍板）；下表保留三候選比較，讓 design 能在文件裡誠實論證「為何 Kafka 而非其他」（面試敘事需要），但**不是要 Fable 5 重選**：

| 候選 | 說明 | 取捨 |
|---|---|---|
| **Kafka + consumer Deployment（傾向）** | Airflow 排程一支 producer（列舉看板→文章 URL）**發佈到 Kafka topic**；一組常駐 consumer Deployment 消費、爬取、寫 Bronze。at-least-once 用**手動 offset commit（寫 Bronze 成功後才 commit）** 取代 Celery acks_late。 | ✅ 動用的正是 NORTH_STAR 保留給 P3 的**唯一**串流工具；✅ 讓 P3 成為跟 P1 批次**真正不同的串流範式**（P3 的存在理由）；✅ 避開 RabbitMQ+Celery **兩個**工具；✅ Kafka 是高需求技能。❌ Kafka 當 task queue 稍不典型（Kafka 是 log 非 task queue，但單向 URL 分派場景可接受）；❌ Celery acks_late 樣板不能直接搬（要用 offset 手動 commit 重實作 at-least-once）。footprint 右尺寸化（KRaft 單 broker、無 Zookeeper）同 P1 Spark 精神。 |
| Celery worker Deployment + RabbitMQ | 照搬原碼可靠性樣板（acks_late 等最省事） | ❌ 引入 RabbitMQ = 第二個常駐 broker + Celery = 第二套佇列系統，跟「排程只 Airflow / 串流才加 Kafka」直接衝突（NORTH_STAR 沒授權 RabbitMQ）；範式上 Celery+MQ 跟一般 Airflow 生態並存顯冗餘。可靠性樣板雖成熟但工具代價過高。 |
| Airflow KubernetesPodOperator 動態映射 | producer 列舉 URL → Airflow `.expand()` 每頁/批一個 pod 爬取 | ❌ **跟 P1 同範式**（都是 Airflow 拉），P3 差異化歸零——違背 P3 的存在目的；✅ 零新工具、最紀律。若最終選它，design 要誠實說明「放棄佇列範式差異化、改以規模化 pod 容錯為賣點」的取捨。 |

## 範圍（簇；Fable 5 定簇內細節與先後）

**P3-1 佇列/串流底座**（依首要決策）
- 若 Kafka：k8s 上部署 Kafka（**Strimzi operator**——宣告式 CRD、與 spark-operator/GitOps 同構 vs plain KRaft manifest；KRaft 免 Zookeeper、單 broker demo 足夠）；topic 佈局（`ptt.article.urls` 待爬、可選 `ptt.crawl.dlq` 死信）。
- **開放問題**：Strimzi vs plain manifest（對齊 P1 對 spark-operator 用 Helm、對 MinIO 用 plain 的判準）？Kafka 版本、KRaft、單 broker PVC（無 storageClassName，沿用 P1）？topic 數/分區/保留策略？consumer group/offset 語意寫清楚（at-least-once = 寫 Bronze 後才 commit）？由 ArgoCD 管、sync-wave 接續 P1/P2？

**P3-2 producer（列舉看板 → 佇列）**
- 取材 `producer.py` 的看板列舉/分頁/停止條件/`BoardDateInferer`，但推進目標從 `celery.send_task` 改為發佈 Kafka（或選定佇列）。以 Airflow 排程（@daily 或指定）觸發，producer 本身是 batch（Job/PythonOperator 語意）。
- **開放問題**：producer 跑法（Airflow PythonOperator vs KubernetesPodOperator vs 一次性 Job）？看板清單設定單一真源（對齊 P1 `pipeline.yaml` 慣例）？`asyncio.Semaphore` 併發上限沿用 5？`BoardDateInferer` 跨年推算整檔搬（PTT 專屬硬知識）？失敗頁 `failed_pages.json` 改存哪（MinIO？供重跑）？

**P3-3 consumer（爬取 → Bronze 原始層）**
- 常駐 consumer Deployment 消費佇列，對每篇文章：反爬（over18/隨機延遲/UA/timeout）+ HTTP 三分類容錯（整檔搬 `utils/http.py`）→ **抓原始 HTML/response 寫 MinIO Bronze**（不在此 parse，對齊 P1「Bronze 保原文」鐵律）。at-least-once 由「寫 Bronze 成功後才 commit offset」保證。
- **開放問題**：Bronze key 佈局（`s3://bronze/ptt/board=<X>/date=<YYYY-MM-DD>/aid=<AID>.html` 決定性 key，重爬覆寫＝冪等，對齊 P1 §3 key 決定性）？raw 存 HTML 全文還是連 HTTP meta 一起（信封）？consumer 副本數/consumer group？`fake_useragent` **執行期連外**問題——改**內建靜態 UA 清單**避免 runtime 外部依賴（design 決定）？反爬延遲/UA/over18 整段搬 `utils/http.py`？失敗處理（transient→佇列重試/DLQ、404/410→skip 記錄）？

**P3-4 Silver（parse → 清洗表）**
- 把 Bronze 原始 HTML 過 parser（取材 `parsers/article.py` 的抽取邏輯：author/title/category/推噓計數/IP/comments）→ Silver（Iceberg 正本 + Postgres serving 副本，對齊 P1 §5 loader 模式）。`date` 原始字串在此正規化成 timestamptz。去重鍵 `(board, aid)` 或加 crawl 批次。
- **開放問題**：parse 在哪跑（Spark job 對齊 P1 Bronze→Silver vs 輕量 Python task——PTT 量小，可能不需 Spark，但一致性 vs 右尺寸的取捨要講）？Silver schema（沿用原欄位 + 正規化 date + 加 ingest 分區鍵，補 recon 指出的缺分區鍵問題）？comments JSON 展平還是保留？去重/冪等鍵？

**P3-5 Gold（最小 mart）+ 對 P4 的產出**
- 給 PTT 一個**最小 Gold mart** 讓 P3 成為完整可 demo 的切片、並餵 P4 呈現層一個「PTT 討論熱度」面板：例如 `gold_ptt_board_daily`（看板×日：文章數、總推噓、平均分、熱門分類）或 `gold_ptt_trending_topics`。**YAGNI**：只做一張、夠展示即可。
- **開放問題**：做哪一張 mart（board daily 熱度 vs topic/sentiment）？dbt 建（對齊 P1 dbt 慣例）還是直接 SQL？要不要跟 YouTube 交叉（PTT 有沒有討論到熱門影片——加分但可能 scope creep，傾向 P3 不做、留敘事）？對 P4 匯出形狀（同 P1 Gold→CSV/Parquet 匯出合約）？

**P3-X 可觀測性 + 驗收**
- 接 P0 Prometheus/Grafana：consumer lag（Kafka 的話 = consumer group lag，經典指標）、爬取成功/失敗率、Bronze/Silver 新鮮度、每看板筆數。
- **開放問題**：Kafka consumer lag 怎麼進 Prometheus（Strimzi 自帶 exporter / kafka-exporter）？爬蟲成功率/反爬觸發（429 次數）怎麼當指標？告警規則（lag 堆積、爬取失敗率高）？

## 設計方向約束（硬性，寫進 design）
- **沿用 P0/P1 慣例**：服務進 `ingestion/`、kustomize `k8s/` + 子 Application、CI 複製既有模式、雲端可攜（無 storageClassName、ingress 抽換）。lakehouse 複用 P1 的 MinIO/Iceberg/Postgres/Airflow，不另立資料棧。
- **一個工作一個工具**：新增 messaging 至多一個（首要決策）；排程仍只 Airflow（producer 由 Airflow 觸發，consumer 是常駐 Deployment——這是「服務」不是「第二排程器」，界線寫清楚）；DB 只 Postgres；物件儲存只 MinIO。
- **Bronze 保原文、冪等落地**：改寫原碼的 MySQL 覆蓋式→MinIO Bronze 原始 HTML + 決定性 key（重爬冪等），修正 recon 指出的「無 raw / 無分區鍵 / upsert 覆蓋」三問題。
- **反爬合規邊界**：只爬公開頁面、尊重 `Retry-After`、合理延遲、不繞過付費牆/登入牆（over18 是 PTT 公開機制）。`fake_useragent` 執行期連外改**內建靜態 UA 清單**。design 註記爬蟲的合規/禮貌姿態（robots/延遲/不打爆來源）。
- **at-least-once 語意明確**：不論選哪個佇列，「處理成功才 ack/commit」的語意要顯式（Kafka=寫 Bronze 後 commit offset；對應原碼 acks_late 精神）。冪等由 Bronze 決定性 key 保證。
- **範式差異化是 P3 的存在理由**：design 要明確論證所選範式跟 P1 批次的不同（否則 P3 無意義）。
- **每步可測**：parser 單元測試（原碼**無 tests**，P3 要補）、consumer 容錯測試（HTTP 三分類 mock）、端到端。

## 交付與驗收（design 要回答的）
- 首要決策 + 各簇開放問題**收斂成決定**或標「plan 前需實查」。尤其拍板：**佇列/執行範式（Kafka vs 其他）**、**Bronze key 佈局**、**Silver parse 在 Spark 還 Python**、**做哪一張 Gold mart**、**Kafka 部署（Strimzi vs manifest）**、**UA 靜態化**。
- 具體：佇列 topic/consumer 佈局、Bronze/Silver/Gold schema、producer/consumer 結構、反爬與容錯設定值、DAG 結構、可觀測性指標清單、對 P4 匯出形狀。
- 部署形狀：Kafka（或選定佇列）/producer/consumer 在 k8s 怎麼裝、怎麼被 ArgoCD 管、sync-wave 接續。
- 端到端驗收清單（producer 發佈 URL → consumer 爬取 → Bronze 有原始 HTML → Silver 有清洗表 → Gold mart 有資料 → consumer lag/成功率指標可見 → 冪等重跑不膨脹）。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design。**本階段只出 spec，plan 延後**。對齊 NORTH_STAR P3 定義 + P0/P1 design 的平台/lakehouse 慣例。P3 與 P2 相互獨立（都只依賴 P1 Gold/lakehouse），可並行出 design。
