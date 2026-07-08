# P1 留言 ingest 增補 — Design（Fable 5 產出）

> **狀態**：design 完成，待 Opus 寫 implementation plan。
> **上游**：[`2026-07-08-P1-comments-ingest-addendum-brief.md`](2026-07-08-P1-comments-ingest-addendum-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)（決策 B）+ [`2026-07-08-P1-data-pipeline-design.md`](2026-07-08-P1-data-pipeline-design.md)（以下稱「P1 design」）。已鎖定決策（commentThreads.list / medallion 沿用 / 去識別 hash / Spark 正當負載 / 本地 kind）全部沿用，未翻案。
> **定位**：**純 additive**——不改 5 表 Gold 合約、不改影片 metadata 管線、不改既有 Bronze/Silver 資產。只新增留言的 Bronze/Silver 資產與其編排/DQ/觀測。
> **API 查證日**：2026-07-08（context7 對 developers.google.com/youtube/v3 官方文件查證，非記憶）：`commentThreads.list` **quota = 1 unit/call**、`maxResults` 1–100（預設 20）、`pageToken` 分頁、`order` = `time`（預設）/`relevance`、`textFormat` = `plainText`/`html`（預設 html）、filter 用 `videoId`；錯誤語意：403 `commentsDisabled`（該影片關留言）、403 `quotaExceeded`、404 `videoNotFound`。**`snippet.textOriginal` 只回給留言作者本人**——第三方抓取只能拿 `textDisplay`，故本設計一律 `textFormat=plainText` 取乾淨純文字。

---

## 0. 版本 pin：**零新 pin**

本增補不引入任何新元件。Airflow 3.2.2 / spark:4.0.2-python3 / iceberg-spark-runtime 1.11.0 / pyiceberg 0.11.1 / dbt-postgres 1.10.2 / MinIO / Postgres 16.14 全部復用 P1 design §0——這是「additive 擴充」的最直接證據：既有平台不加一磚一瓦就能承載百萬列新負載。

---

## 1. 三個關鍵決策（先拍板，細節在各簇）

### ① 編排 = **獨立 daily DAG `yt_comments_daily` + 單 pod 順序 ingest**（不併主線、不做 dynamic mapping）

| 候選 | 判定 |
|---|---|
| **獨立 @daily DAG，ingest 為單一 PythonOperator pod 順序處理選定影片** ✅ | (a) 頻率不同（主線 hourly、留言 daily 一批）；(b) **失敗隔離**——留言 quota/API 異常絕不拖垮 trending 主線（硬約束「不改影片管線」的編排面落實）；(c) quota 是**全域共享資源**，單 process 內維護 in-memory 預算計數器最簡單正確；~200 支影片順序抓（每支數秒）單 pod 十幾分鐘跑完，無平行化必要。 |
| 併入主線 `yt_trending_hourly` 尾端 | 淘汰：hourly 抓留言 quota 立刻爆表（見 §3 數學）；且任何留言步失敗都會把主線 DAG 打紅，違反 additive 隔離。 |
| 動態任務映射 `.expand(video=…)`（~200 pod） | 淘汰：quota 計數器要跨 pod 協調（DB 行鎖或 XCom 聚合），複雜度暴增；200 個 KubernetesExecutor pod 的排程開銷遠大於順序迴圈省下的時間。fan-out 在主線（8 region）已展示過，這裡不重複炫技。 |

### ② 去識別邊界 = **Bronze 落地前的「作者欄位遮蔽」（ingest 邊界，Python 端）**

brief 兩條鐵律在此相撞：「Bronze 保原文」vs「作者明文不落地」。**收斂：隱私約束位階高於保原文慣例**——Bronze 物件是 API response 原文的**唯一例外**是作者身分四欄位：

- `snippet.topLevelComment.snippet.authorChannelId.value` → 取代為 `sha256(salt ‖ value)` 的 hex 前 16 字元（下稱 author_hash，演算法 §5）；
- `authorDisplayName` / `authorProfileImageUrl` / `authorChannelUrl` → 取代為固定字串 `"__redacted__"`。

理由：(a) 被遮蔽欄位對下游三個目的（Spark 負載、RAG 語料、微調原料）**全部無用**，可重放性實質不受影響；(b) hash 在 ingest 端算，**salt secret 只需注入 Airflow ingest pod（既有 `youtube-api` Secret 加一鍵），Spark job 完全不碰 secret**；(c)「無明文作者」的保證從第一落地字節就成立，不存在「Bronze 有明文、只防 Silver」的半套去識別。`_metadata` 信封記 `redaction` 自述（§4），對重放者誠實。這是刻意決定，寫進 README 面試敘事。

### ③ Silver 寫入語意 = **Iceberg `MERGE INTO`（comment_id 為鍵）**，非 overwritePartitions

| 候選 | 判定 |
|---|---|
| **MERGE INTO lakehouse.silver.youtube_comments ON comment_id** ✅ | 留言與影片快照的本質差異：快照粒度含時間（每小時新列），留言是**實體**（同一 comment_id 跨日重訪時 like_count/text 會更新）。MERGE 一次解決三件事：重跑同日冪等（MATCHED→UPDATE 等值覆寫）、跨日重疊去重（watermark 邊界重抓的同留言→UPDATE 而非重複列）、增量更新語意（like_count 隨時間演進）。**這正是展示點**：百萬列 Iceberg 表上的 MERGE upsert 是 Spark 分散式 shuffle-join 的真實負載——「為何 lakehouse 需要 Spark」的具體答案（§10 敘事）。 |
| overwritePartitions（沿用主線 §5 手法） | 淘汰：若分區=ingest_date，同 comment_id 會落在多個分區產生跨分區重複，Iceberg 正本不乾淨，P2b/P2c 讀正本還得自己去重——合約失格。快照表適用的手法不硬套實體表。 |
| append + 下游去重 | 淘汰：Bronze→Silver 的職責就是去重清洗，把髒留給消費者是失職。 |

---

## 2. 總體形狀

### 資料流（新增部分加粗；既有主線原樣不動）

```
Postgres silver.video_snapshots（既有，選片依據）
        │  select_videos：8 區 × 當日 top-25 by comment_count，跨區去重 ≈ 150–200 支
        ▼
YouTube Data API v3 commentThreads.list（videoId=…, order=time, textFormat=plainText, maxResults=100）
        │  ingest_comments：單 pod 順序分頁抓取；quota 預算計數器；watermark 早停；作者欄遮蔽（§1②）
        ▼
[Bronze] MinIO s3://bronze/youtube_comments/video_id=<VID>/ingest_date=<YYYY-MM-DD>/page=<NNNN>.json
        │  （遮蔽後原始 JSON；重跑 = prefix purge + 重寫 = 冪等）
        ▼  SparkApplication comments_silver_job（driver + 2 executors，per-run ephemeral）
[Silver] Iceberg 表 lakehouse.silver.youtube_comments（MERGE INTO by comment_id，
        │   PARTITIONED BY (days(published_at))）——★ P2b/P2c 上游合約（§5 schema）
        │  pyiceberg 掃 ingest_date=D → psycopg2 UPSERT ON CONFLICT (comment_id)
        ▼
[Silver serving] Postgres lakehouse.silver.youtube_comments（dbt DQ / P2b pgvector 的所在地）
        │  dbt run+test --selector comments_only（KubernetesPodOperator）
        ▼
（無 Gold——§6 刻意決定）→ Grafana comments-pipeline dashboard（quota / 累積列數 / freshness）
```

### 新增檔案佈局（全 additive；未列 = 不動）

```
ingestion/youtube/src/yt_ingest/
    comments.py            # commentThreads 分頁抓取迴圈：watermark 早停、page cap、quota 計數、錯誤分類
    redact.py              # 作者欄遮蔽 + salted hash（純函式，可單測）
    comments_bronze.py     # Bronze prefix purge + page=NNNN.json 寫入（boto3）
    progress.py            # ops.comment_ingest_progress / ops.comment_ingest_runs 的 DDL 與讀寫（psycopg2）
ingestion/youtube/tests/  # ＋遮蔽斷言、watermark 早停、budget 停止、403 分類、key 決定性（§9）
orchestration/airflow/dags/
    yt_comments_daily.py             # 主 DAG（§7）
    yt_comments_reprocess_range.py   # 手動重處理（bronze 已有 → Spark+loader+dbt 重算）
    config/pipeline.yaml             # ＋ comments: 區塊（§3 常數單一真源）
    templates/spark_comments_silver.yaml  # SparkApplication 模板（image tag 仍由 images.yaml 注入）
lakehouse/spark/jobs/comments_silver_job.py   # ＋ tests fixture（同一 spark image，spark-ci 既有 paths 涵蓋）
lakehouse/dbt/
    selectors.yml                    # ★ default selector 排除 tag:comments（§6 隔離手法，主線 DAG 檔零改動）
    models/staging/stg_youtube_comments.sql（+ schema/_sources.yml additive 增列）
    tests/assert_no_plaintext_author.sql 等（§6 清單）
platform/monitoring/pipeline/comments-dashboard.yaml   # 第三個 dashboard（既有 pipeline-monitoring app 收）
lakehouse/postgres/k8s/…             # postgres-exporter 自訂查詢 ConfigMap additive 加 4 條 query（§8）
scripts/verify-comments.sh           # make comments-verify（§9）
```

**零新 ArgoCD Application、零新 CI workflow、零新 Secret 物件**：三支既有 CI 的 paths 過濾天然涵蓋上述目錄；部署面只 additive 改既有 ConfigMap/目錄；secret 只在既有 `youtube-api` 加一鍵（§8）。

---

## 3. C1 Bronze ingest（決定）

| 開放問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| 影片選取策略 | **每區當日 top-25 by 最新快照 `comment_count`，8 區跨區去重**（同片多區上榜只抓一次）。來源 = 直接查 Postgres `silver.video_snapshots`（當 logical date 的最新快照）。清單估 150–200 支/日。 | 按 `comment_count` 排序比 views/velocity 更直接對準「留言收集量最大化」目的。淘汰 velocity 排序（gold_video_velocity 是主線 dbt 產物，選片依賴它會把留言 DAG 耦到主線 dbt 成功；silver serving 只依賴主線 loader，耦合面最小）。淘汰全量影片（quota 不允許，見下）。top-N/區數為 `pipeline.yaml` `comments:` 常數，調整 = 改一行 YAML。 |
| quota 預算（🔴 首要約束，算給看） | **`daily_unit_budget: 4000`**（唯一 API key 上 10,000/天的 40%）。數學：影片主線固定 ~200 units/天（P1 §3）；留言每呼叫 1 unit 拿 ≤100 則 → 預算硬上限 = 4,000 頁 = **40 萬則/天封頂**。實際估算：首訪影片平均 8–15 頁（page cap 20）、重訪影片 watermark 早停 1–3 頁 → 日常 ~1,500–2,500 units、**~10–15 萬則新留言/天**。總用量 ≤ 4,200/10,000，buffer 58%。**百萬列 = 約 8–14 天累積**——誠實標明：這是**累積型 ingest**，不是單日暴力抓；跨多天疊加正好讓 Iceberg「大表、分區、隨時間演進」的故事是真的。 | 不做「假裝無限」：預算是 ingest process 內的 in-memory 計數器（每次呼叫 +1），達預算即優雅停止（見降級列）。預算值進 `pipeline.yaml` 單一真源。 |
| 分頁與增量 | **`order=time`（新→舊）+ per-video watermark 早停**：progress 表存該影片已見最新 `published_at`（watermark）；重訪時從第一頁往舊抓，一旦整頁留言 `published_at` ≤ watermark 即停——只花 1–3 units 拿到增量。首訪抓到 **page cap = 20 頁**（2,000 則/支封頂，長尾留言對語料邊際價值低）或 `nextPageToken` 耗盡為止。`maxResults=100`、`textFormat=plainText`、`part=snippet`（不帶 `replies`）。 | `order=time` 是發布時間序，舊留言不會被按讚頂回來造成漏抓窗；`pageInfo.totalResults` 不可靠（官方已知），一律只信 `nextPageToken`。known-limit：已抓留言事後被**編輯**（updatedAt 變、publishedAt 不變）不會重抓——對趨勢語料無實質影響，README 記錄。 |
| 抓回覆？ | **只頂層留言**（`commentThreads.list`），**不用 `comments.list`**。thread 的 `totalReplyCount` 存進 Silver 當熱度信號。 | 頂層已足夠餵 RAG/微調（brief 傾向確認）；回覆是 scope creep 且 quota 加倍。未來要加：schema 已預留 `is_reply`（§5），additive 演進。 |
| Bronze key 佈局 | `s3://bronze/youtube_comments/video_id=<VID>/ingest_date=<YYYY-MM-DD>/page=<NNNN>.json`——page 用**四位序號**（0000 起）非 pageToken（token 不透明、非決定性，不能當 key）。**冪等機制：重跑同 (video_id, ingest_date) 先 purge 該 prefix 再從第 0 頁重走分頁鏈**——頁數比上次少（留言被刪）也不殘留舊頁。 | 對齊 P1 §3「決定性 key、重抓冪等」：key 由 logical date + 序號導出，不含 `now()`、不含 token。Hive 式 partition path 讓 Spark 讀指定 ingest_date 零掃描。 |
| 續抓進度存哪 | **Postgres 新 schema `ops`**（`lakehouse` db）：`ops.comment_ingest_progress`（video_id PK、watermark_published_at、last_page_index、next_page_token、total_fetched、status、updated_at）+ `ops.comment_ingest_runs`（run_date PK、units_used、videos_selected/processed、comments_fetched、stopped_reason）。**DDL 全由 ingest 程式碼持有**（`CREATE SCHEMA IF NOT EXISTS ops` + `CREATE TABLE IF NOT EXISTS`，冪等）——Postgres init SQL ConfigMap **零改動**。 | 淘汰 Airflow Variable（無 per-video 粒度、無交易）；淘汰 MinIO JSON（無查詢、並發弱）。Postgres 已是三職責共用（P1 §4），加第四個小職責（ingest 操作狀態）仍是「DB 只 Postgres」；`ops` schema 隔離、不污染 silver/gold。runs 表同時是 §8 quota 指標的資料源——一份狀態兩用。 |
| status 枚舉 | `pending` / `in_progress` / `done`（本日抓完）/ `budget_stopped`（預算中斷，隔日續）/ `comments_disabled` / `not_found` | 降級與跳過都是顯式狀態，可觀測、可續抓。 |
| quota 用盡降級 | 兩層：**①軟預算**——計數器達 `daily_unit_budget` → 當前影片寫回 `next_page_token`+`status=budget_stopped`、剩餘影片留 `pending`，task **正常結束（success）**，`stopped_reason=budget` 記入 runs 表；隔日 run 續抓（進度都在 progress 表）。**②硬 403 `quotaExceeded`**——同樣優雅收尾（記錄進度、success、`stopped_reason=quota_403`），**不 retry**（重試必然再 403 且燒配額）。 | 與主線 quota fail-fast 姿態**刻意不同**且要寫進敘事：主線 hourly 快照錯過=永久缺口，fail 才會告警；留言是累積型，quota 用盡是**設計內狀態**而非故障，紅 DAG 是誤報。異常可見性由 §8 quota 指標與 `stopped_reason` 承擔。403 `commentsDisabled`/404 `videoNotFound` → 標 status、跳下一支、不計失敗；其他 HTTP/網路錯誤 → 該影片本輪跳過（progress 保留原狀，隔日自然重試），連續 10 支同類錯誤 → raise（系統性故障 fail DAG）。 |
| 與主線的排程關係 | **獨立 DAG（§1①）**，`schedule="30 1 * * *"`（UTC，錯開整點主線）、`catchup=False`（同主線理由：留言集是「當下狀態」，歷史不可回補）、`max_active_runs=1`。 | — |

`pipeline.yaml` 新增區塊（單一真源，數值即上表）：

```yaml
comments:
  top_n_per_region: 25
  page_cap_per_video: 20
  daily_unit_budget: 4000
  max_results_per_page: 100
  order: time
  consecutive_error_limit: 10
```

### Bronze 物件信封（`_metadata` + 遮蔽後 response 原文）

```json
{
  "_metadata": {
    "video_id": "dQw4w9WgXcQ",
    "ingest_date": "2026-07-08",
    "page_index": 3,
    "page_token_used": "<本頁使用的 pageToken，僅追溯用>",
    "ingestion_id": "dQw4w9WgXcQ_20260708_p0003",
    "ingested_at": "<實際抓取 UTC ISO>",
    "source": "youtube_data_api_v3.commentThreads",
    "redaction": {"algo": "sha256_salted_v1",
                   "fields": ["authorChannelId.value(hashed)", "authorDisplayName",
                              "authorProfileImageUrl", "authorChannelUrl"]}
  },
  "response": { "items": [ …commentThreads.list 原文（僅上列作者欄遮蔽）… ] }
}
```

---

## 4. C2 Spark Bronze→Silver（決定）

`lakehouse/spark/jobs/comments_silver_job.py`，經 spark-operator SparkApplication 提交（模板 `templates/spark_comments_silver.yaml`），全套沿用 P1 §1②/§5 慣例：

| 項目 | 決定 |
|---|---|
| 輸入 | 參數 `--ingest-date YYYY-MM-DD`：讀 `s3a://bronze/youtube_comments/video_id=*/ingest_date=<D>/*.json`，**顯式 StructType schema**（關推斷；schema 涵蓋 `_metadata` 信封 + commentThread 資源，含遮蔽後欄位）。空輸入（當日零新留言/預算跳過）→ 記 log 後正常結束（非 fail——留言日批空集是合法狀態，與主線空輸入語意不同，因為上游有預算跳過的正常路徑）。 |
| 轉換 | explode `response.items` → 每 thread 取 `snippet.topLevelComment` → 欄位映射（§5 schema）→ 文字清洗：**僅**去控制字元（`\p{Cc}` 除 `\n`/`\t`）+ Unicode NFC 正規化 + trim；**不去 emoji、不改寫內文**（emoji 是 P2c 情緒信號、原文忠實度是 RAG 語料底線）→ `lang_bucket` 衍生（下列）→ 批內去重（同 comment_id 跨頁重疊取 `published_at` 最新解析批的任一列，`dropDuplicates(["comment_id"])`）。 |
| `lang_bucket` 衍生 | **零依賴啟發式**（Spark 內建 regexp，不裝 langdetect/fasttext）：CJK 字元數（`\p{Han}\p{Hiragana}\p{Katakana}\p{Hangul}`）÷ 字母類字元總數 ≥ 0.3 → `zh`；拉丁字母佔比 ≥ 0.7 → `en`；其餘 → `other`。**明確定位為粗分流 bucket 而非 ISO 語言偵測**（P2b/P2c 分流夠用；要精確語言時以 additive 新欄位演進，本欄語意不變）。 |
| 寫入 | **`MERGE INTO lakehouse.silver.youtube_comments t USING batch s ON t.comment_id = s.comment_id WHEN MATCHED THEN UPDATE SET *（含 ingest_date/ingested_at 更新為本批值）WHEN NOT MATCHED THEN INSERT *`**。冪等性論證見 §1③。表 `PARTITIONED BY (days(published_at))`——語意分區（留言發布時間橫跨多年，時間範圍查詢/未來過期治理都吃這個），分區演進故事寫進敘事。 |
| SparkApplication 規格 | driver 1 core/1.5Gi、executor **`instances: 2`** × 1 core/2Gi（比主線多一顆 executor：百萬列 MERGE shuffle-join 的右尺寸，也是「多 executor 分散式」的具象展示；擴縮仍是改一個宣告式欄位）、`mode: cluster`、`restartPolicy: Never`、`timeToLiveSeconds` 同主線。image = 既有 `spark-jobs` image（同一 Dockerfile 多放一支 job，spark-ci 既有 paths 觸發 rebuild）。RBAC 復用 P1 §5（同 ns、同 CRD 權限，零新增）。 |
| Secret | **Spark job 零 secret 新增**——author hash 已在 ingest 端算完（§1②），job 只需既有 MinIO/Postgres（JDBC catalog）憑證，與主線 silver job 完全同款注入。 |
| Silver→Postgres loader | 沿用 P1 §5 loader 模式：獨立 Airflow task `load_comments_silver_to_postgres`（PythonOperator）——pyiceberg 掃 `ingest_date = <D>` 的列（MERGE 時 MATCHED 也更新 ingest_date 為本批值，故此過濾恰好取得「本批觸及的全部列」，含更新列）→ psycopg2 `INSERT … ON CONFLICT (comment_id) DO UPDATE`。首行前 `CREATE TABLE IF NOT EXISTS`（DDL 由 loader 持有，含 PK 與 `video_id` btree 索引）。日批 ~10–15 萬列 executemany 分批（每 5,000 列）寫入，體量安全。 |

---

## 5. `silver_youtube_comments` schema（★ P2b/P2c 上游合約，標穩定）

**粒度：一列 = 一則頂層留言（comment_id 全表唯一）。** Iceberg 正本 `lakehouse.silver.youtube_comments`（分區 `days(published_at)`）；Postgres serving 副本 `lakehouse` db `silver.youtube_comments` 同構，PK `comment_id`。

**穩定性政策（與 P1 §6a Gold 同款）**：表名、粒度鍵、既列欄位語意是對 P2b（RAG 語料）/P2c（微調原料）的介面承諾——變更只允許**加欄位**（additive）；改粒度/刪欄/改語意必須開 `_v2` 新表並記錄於 spec。

| 欄位 | 型別（Iceberg / PG） | 來源與定義 |
|---|---|---|
| comment_id | string / text **PK** | `items[].snippet.topLevelComment.id` |
| video_id | string / text | `items[].snippet.videoId`（btree 索引；留言屬影片級，**無 region 欄**——同片多區上榜只抓一次，region 歸屬經 video_id join `silver.video_snapshots` 取得） |
| text | string / text | `topLevelComment.snippet.textDisplay`（`textFormat=plainText` 取得）經 §4 最小清洗；**保留 emoji 與原始大小寫**。非 `textOriginal`（API 只回作者本人，查證於首註） |
| like_count | long / bigint | `topLevelComment.snippet.likeCount`，null→0 |
| total_reply_count | long / bigint | thread `snippet.totalReplyCount`，null→0（熱度信號；回覆本體不抓） |
| published_at | timestamptz | `topLevelComment.snippet.publishedAt`（**分區鍵**；not null——API 必回） |
| updated_at | timestamptz | `topLevelComment.snippet.updatedAt`（編輯偵測留痕） |
| author_hash | string / text | ingest 端已算好之遮蔽值直取（演算法見下）；not null |
| is_reply | boolean | 本階段**常數 false**（只抓頂層）；預留欄位讓未來加回覆時 schema 零變更 |
| lang_bucket | string / text | `zh` / `en` / `other`（§4 啟發式；粗分流語意，非 ISO 偵測） |
| ingest_date | date | 本批（最近一次觸及）的 ingest 日期——loader 增量過濾鍵，MERGE 時隨批更新 |
| ingested_at | timestamptz | 最近一次抓取時間（freshness 依據） |
| ingestion_id | string / text | `<video_id>_<YYYYMMDD>`（追溯 Bronze prefix） |

### 去識別演算法（`redact.py`，純函式可單測）

```
author_hash = hex(SHA-256(AUTHOR_HASH_SALT || authorChannelId.value))[:16]
```

- **輸入鍵選 `authorChannelId.value`**（穩定不可變）而非 displayName（可改名）：同一作者跨留言/跨影片 hash 一致，保留「同作者」分析信號但不可逆推身分。authorChannelId 缺席（罕見邊界）→ fallback `hex(SHA-256(salt || "dn:" || authorDisplayName))[:16]`。
- **salt**：256-bit 隨機值，存既有 `youtube-api` Secret 新鍵 `AUTHOR_HASH_SALT`（§8）。**生成一次後永不輪替**（`make pipeline-secrets` 冪等：鍵已存在則保留）——輪替不破壞去重（鍵是 comment_id）但會斬斷跨批作者連結性，故凍結。
- **可逆性保留（刻意）**：對「已知明文」的 channel id（如影片上傳者，明文在 `silver.video_snapshots.channel_id`）可持 salt 重算 hash 做**單向比對**（例如 P2 想標記「上傳者本人回覆」）——能力不因今日 YAGNI 而喪失，故本階段不加 `author_is_uploader` 欄。
- 16 hex 字元 = 64 bit：對本專案量級（≪ 10^7 作者）碰撞機率可忽略（生日界 ~10^-4 @ 500 萬作者），且明確非密碼學匿名化研究等級——README 誠實敘述「禮貌去識別」定位。

---

## 6. C3 Gold 與 dbt（決定）

| 開放問題 | 決定 | 理由 |
|---|---|---|
| Gold mart 要不要 | **不建**。本階段對下游的介面就是 `silver_youtube_comments`（§5 合約）。 | YAGNI：留言的消費者是 P2b（RAG 直讀 Silver/pgvector）與 P2c（微調直讀 Silver）；「留言情緒 mart」`gold_video_comment_sentiment` 要等 P2c 情緒打分才有內容，屬 P2 產出。空殼 mart 是為分層而分層。 |
| 對 5 表 Gold additive 加留言欄？ | **不加**（連 additive 都不加）。 | 影片層級的 `comment_count` 統計已在 `silver.video_snapshots`（API statistics 來的）；「我方實際抓到幾則」是 ops 覆蓋率指標（§8 Prometheus），不是分析語意，放進 mart 會混淆兩者。零觸碰 Gold = additive 承諾的最強形式。 |
| dbt 資產與主線隔離 | 留言 dbt 資產全掛 **tag `comments`**；新增 **`selectors.yml`**：`default: true` 的 selector 排除 `tag:comments`（主線 `dbt run`/`dbt test` 無參數呼叫自動走 default selector → **主線 DAG 檔案零改動**）；留言 DAG 用顯式 `--selector comments_only` 跑自己的 run+test。 | 不隔離的話：留言表尚未首建時主線 hourly `dbt run` 會因 staging view 引用不存在的表而炸——additive 變成破壞。淘汰「主線 command 加 `--exclude`」（要動主線 DAG 檔一行）；淘汰獨立 dbt project（工具冗餘）。⚠️ `selectors.yml default: true` 行為列 §9 plan 前實查 #1。 |
| staging | `stg_youtube_comments`（view）：source `silver.youtube_comments` 直取 + 型別防衛（coalesce 數值 0、濾 `comment_id is null`）。source 定義 additive 增列於既有 `_sources.yml`（`loaded_at_field: ingested_at`，freshness **warn 26h / error 50h**——daily 節奏，且只在 comments selector 的 test 步跑，不影響主線 2h/4h freshness）。 | — |

### dbt 測試合約（tag:comments 全列）

**generic tests**
- `stg_youtube_comments`：`comment_id` **unique + not_null**；`video_id`/`text`/`published_at`/`author_hash`/`ingested_at` not_null；`lang_bucket` accepted_values `['zh','en','other']`；`is_reply` accepted_values `[false]`（本階段常數守門，未來加回覆時放開即顯式合約變更）
- `video_id` → **relationships 到 `stg_video_snapshots.video_id`（severity: error）**——選片直接來自該表，外鍵天然成立；fail = 真 bug

**singular tests**
- `assert_no_plaintext_author.sql`（★去識別驗證）：兩段斷言合一——①查 `information_schema.columns`：`silver.youtube_comments` 不存在名稱匹配 `%author%` 且非 `author_hash` 的欄位；②`author_hash !~ '^[0-9a-f]{16}$'` 出列即 fail（格式守門，明文人名/URL 不可能通過）
- `assert_comment_counts_non_negative.sql`：`like_count < 0 OR total_reply_count < 0` 出列即 fail
- `assert_comment_published_not_future.sql`：`published_at > now() + interval '1 day'` 出列即 fail（API 時間戳理智檢查）
- `assert_comments_freshness_guard.sql`：`now() - max(ingested_at) > 50h` 出列即 fail（與 source freshness 雙保險，這條擋留言 DAG）

---

## 7. DAG 結構（具體）

### 主 DAG `yt_comments_daily`（`30 1 * * *`、catchup=False、max_active_runs=1、retries=3+exponential backoff——quota 兩類降級不走 retry，§3）

```
select_videos（PythonOperator）
      查 silver.video_snapshots：logical date 當日、每區最新快照 top-25 by comment_count
      跨區去重 → upsert ops.comment_ingest_progress（新片 status=pending；帶出昨日 budget_stopped/pending 殘量並優先排入）
      → XCom 推影片清單（~200 個 id + watermark，KB 級，XCom 安全）
      ▼
ingest_comments（PythonOperator，單 pod 順序，execution_timeout=60min）
      逐支影片：分頁抓取（order=time / plainText / maxResults=100）→ 遮蔽（redact.py）
      → Bronze prefix purge + page=NNNN.json；watermark 早停 / page cap / 預算計數
      → 寫回 progress + runs 統計（units_used / comments_fetched / stopped_reason）
      ▼
spark_comments_silver（SparkKubernetesOperator → SparkApplication，data ns）
      comments_silver_job.py --ingest-date {{ ds }} → MERGE INTO silver.youtube_comments
      ▼
load_comments_silver_to_postgres（PythonOperator：pyiceberg where ingest_date={{ ds }} → UPSERT）
      ▼
dbt_comments（KubernetesPodOperator，既有 dbt image）
      dbt run --selector comments_only && dbt test --selector comments_only
      && dbt source freshness --select source:silver.youtube_comments
      失敗 = DAG 失敗 = 告警（DQ gate）
```

任務間依賴全部線性（`>>`）。**續抓的本質**：進度活在 `ops.comment_ingest_progress`（Postgres），不活在 Airflow 狀態——DAG 每日 run 是無狀態 worker，撿起 progress 表的 pending/budget_stopped 續跑；這是 brief「斷點續傳（API 分頁 token 版）」的落地。

### 手動 DAG `yt_comments_reprocess_range`（schedule=None，params `start_date`/`end_date`）

Bronze 已有的日期範圍重放：逐日 SparkApplication（MERGE 冪等）→ loader 範圍 UPSERT → dbt_comments。**不重新呼叫 API**（零 quota）。對齊主線 `yt_reprocess_range` 模式，獨立成檔不動主線。

---

## 8. 部署 / CI / secret 接入（零新件盤點）

| 面向 | 接法 |
|---|---|
| ArgoCD | **零新 Application**。dashboard 新檔進 `platform/monitoring/pipeline/`（wave 6 directory 型 app 自動收）；postgres-exporter 自訂查詢 ConfigMap additive 加條目（wave 3 app 內既有資源改動）；其餘全是 git-sync 送達的 DAG/config/模板與 CI image 內容物。 |
| CI | **零新 workflow**。`airflow-ci`（paths `ingestion/**`）跑新增單元測試；`spark-ci`（paths `lakehouse/spark/**`）跑 comments job 轉換測試並 rebuild spark-jobs image；`dbt-ci`（paths `lakehouse/dbt/**`）`dbt parse` 守門 selectors/新 model。 |
| Secret | 既有 `youtube-api` Secret **加一鍵 `AUTHOR_HASH_SALT`**（`make pipeline-secrets` additive：`openssl rand -hex 32` 生成；**鍵已存在則保留不重生**——salt 凍結語意 §5）。Spark/dbt/loader 全走既有憑證注入，無新 secret 面。 |
| Prometheus 指標（postgres-exporter 自訂查詢，沿用 P1 §9 模式，不自養 exporter） | `yt_comments_quota_units_used{run_date=today}`（from `ops.comment_ingest_runs`）、`yt_comments_quota_budget`（常數列，同表）、`yt_comments_rows_total`（count from `silver.youtube_comments` serving）、`yt_comments_freshness_seconds`（`now()-max(ingested_at)`）、`yt_comments_videos_backlog`（progress 表 pending+budget_stopped 計數）。 |
| PrometheusRule（additive 加進既有 pipeline rules） | `YTCommentsStale`：freshness > 30h warn / > 54h critical。`YTCommentsQuotaNearBudget`：units_used / budget > 0.9 → warn（quota 可見性的告警面）。`YTCommentsBacklogGrowing`：backlog 連續 3 日 > 100 → warn（預算長期不足的信號，答案是調 YAML 預算或縮 top-N）。 |
| Grafana | 新 dashboard **`comments-pipeline`**（ConfigMap sidecar）：quota 用量 vs 預算（bar+threshold）、累積列數成長曲線（百萬列進度——**面試 demo 主圖**）、freshness、backlog、當日抓取影片數/則數、lang_bucket 佔比。 |

---

## 9. 測試策略與端到端驗收

### 單元/CI 層（每步可測）

| 層 | 測試 |
|---|---|
| `redact.py` | 遮蔽後 JSON 深掃無 `authorDisplayName` 原值/URL 欄殘留；hash 決定性（同輸入同 salt 同輸出）；不同 salt 不同輸出；fallback 路徑；`_metadata.redaction` 信封正確 |
| `comments.py` | httpx mock：分頁鏈遍歷、watermark 早停（整頁 ≤ watermark 即停）、page cap、預算計數器到限優雅停止並回報 stopped_reason、403 quotaExceeded / commentsDisabled / 404 分類處置、連續錯誤上限 raise |
| `comments_bronze.py` | key 決定性（`page=0000` 格式、由 logical date 導出）；重跑 purge-then-write 冪等（mock S3 斷言舊頁不殘留） |
| `progress.py` | DDL 冪等；pending/budget_stopped 撿取順序 |
| DAG | DagBag import 零錯誤；兩新 DAG 依賴鏈斷言；`catchup=False`/`max_active_runs=1` 守門；`pipeline.yaml comments:` 鍵存在性與型別 |
| Spark | pyspark local + 固定 Bronze fixture：欄位映射、`dropDuplicates`、lang_bucket 三值案例（純中/純英/混合/emoji-only）、控制字元清洗保 emoji、空輸入正常結束、MERGE 冪等（同 fixture 跑兩次列數不變）|
| dbt | `dbt parse`（CI）+ §6 測試合約（runtime DQ gate） |

### `make comments-verify`（`scripts/verify-comments.sh`；前置 = P1 `make pipeline-verify` 綠）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | 觸發 `yt_comments_daily`（`airflow dags trigger`）輪詢 dagrun | `success`（含 dbt_comments 綠 = DQ gate 過） |
| 2 | Bronze | `mc ls bronze/youtube_comments/video_id=*/ingest_date=<今日>/` ≥ 1 個 `page=0000.json`；抽一物件斷言 `_metadata.redaction` 存在且 response 內無 `"authorDisplayName": "`（非 `__redacted__`）明文值 |
| 3 | Silver 正本+serving | Postgres `SELECT count(*) FROM silver.youtube_comments` > 0；`SELECT count(*) FROM silver.youtube_comments WHERE author_hash !~ '^[0-9a-f]{16}$'` = 0 |
| 4 | 冪等 | clear+rerun 同一 logical date → Bronze 物件數、Silver/serving 列數皆不膨脹 |
| 5 | quota 指標 | Prometheus `yt_comments_quota_units_used` 有值且 ≤ `yt_comments_quota_budget` |
| 6 | 進度狀態 | `ops.comment_ingest_runs` 有今日列、`stopped_reason ∈ {completed, budget, quota_403}` |
| 7 | dashboard | Grafana `/api/search?query=comments` 命中 `comments-pipeline` |
| 8 | 主線無損 | `yt_trending_hourly` 最近 dagrun 仍 success 且主線 dbt_test 未執行任何 tag:comments 測試（log 斷言）——additive 的可執行證明 |

**量級驗收分兩級**：單日功能驗收如上（分鐘級）；「百萬列」是**累積型指標**——dashboard 成長曲線 + README 記錄實際達成日（預估 8–14 天，§3 數學），不進自動化腳本。

### plan 前需實查（設計已收斂，落地校準）

1. **dbt `selectors.yml` `default: true`** 在 dbt-postgres 1.10.2 所解析 dbt-core 版的確切行為（無參數 `dbt run`/`dbt test` 是否自動套用 default selector）——若不支援，fallback 已定：主線 dbt task command 加 `--exclude tag:comments`（一行，design 已誠實標注此為次選）。
2. **Iceberg 1.11.0 + Spark 4.0.2 `MERGE INTO`** on JDBC catalog 煙囪驗證（標準功能，5 分鐘實證）＋ `days()` 分區轉換下 MERGE 行為。
3. **pyiceberg 0.11.1 對 `ingest_date` 等值過濾掃描**（row filter pushdown）實測。
4. `commentThreads.list` 對關留言影片的 403 `commentsDisabled` 實際 response body 形狀（錯誤分類的 parse 依據）。

---

## 10. 面試敘事點 + known-limits（誠實段）

**「為什麼你的 lakehouse 需要 Spark？」的標準答案（寫進 README）**：影片 metadata 每天只有幾千列，pandas 就能處理——單獨看它，Spark/Iceberg 是殺雞用牛刀。留言表把負載變真：**每天 10–15 萬列新增、跨週累積百萬列、寫入語意是全表 MERGE upsert（shuffle join）、分區隨 `published_at` 自然演進**——分散式清洗、大表分區管理、ACID upsert 三件事都有真實需求。同一份留言同時餵 P2b RAG 語料與 P2c 微調原料：一份 ingest、三個目的。

**known-limits（README 全列）**：
1. **累積型 ingest**：百萬列靠 8–14 天疊加，非單日暴力抓——quota 10,000/天是硬牆，預算 4,000 是自律線；這不是缺陷而是「在配額約束下設計吞吐」的展示。
2. **留言刪除不同步**：Silver 是「觀測時點的留言存在集」（MERGE 只 update/insert 不 delete），非 YouTube 即時鏡像。
3. **留言編輯不重抓**：watermark 以 `published_at` 為準，事後編輯（updatedAt 變）的舊留言不會更新。
4. **只頂層留言**：回覆不抓（totalReplyCount 保留熱度信號）；schema 已預留 `is_reply` 演進位。
5. **去識別是「禮貌去識別」**：salted hash（64-bit 截斷）阻擋 casual 逆推與明文落地，非差分隱私等級；Bronze 亦遮蔽（§1②），全管線無作者明文。
6. **lang_bucket 是啟發式粗分流**，非語言偵測模型。

## 11. 落地後校驗（design 自檢摘要）

- brief 四簇（C1/C2/C3/C-X）開放問題**全部收斂為單一決定**，無 TBD/兩案並陳；三個關鍵取捨 §1 拍板並列淘汰方案。
- 硬約束對照：①純 additive（零觸碰 5 表 Gold/主線 DAG 檔/既有 Bronze-Silver；隔離靠 selectors.yml + 獨立 DAG；驗收 #8 可執行證明）②沿用 P0/P1 慣例（決定性 key/Spark 骨架/雙寫 loader/dbt DQ/kustomize+ArgoCD/零新 Application/secret 姿態）③quota 誠實（§3 數學算給看、預算+降級+續抓、指標可見）④去識別（ingest 邊界遮蔽、salt Secret、DQ 斷言、驗收斷言）⑤Spark 名正言順（§1③/§10 敘事）⑥每步可測（§9 分層測試 + 8 步驗收）。
- `silver_youtube_comments` 合約（§5）欄位級定案並附穩定性政策，P2b/P2c 可直接依賴。
