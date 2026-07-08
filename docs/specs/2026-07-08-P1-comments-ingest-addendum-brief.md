# P1 留言 ingest 增補（決策 B）— 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)（「LLM／微調層與留言語料」專章）+ **既有 P1 design**（`2026-07-08-P1-data-pipeline-design.md`——本增補**沿用**它的 Bronze key 決定性、Spark Bronze→Silver、Iceberg/MinIO、Airflow、Silver loader、dbt 慣例）→ `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P1-comments-ingest-design.md`（或直接增補進 P1 design 的新章節，Fable 5 定）→（plan 延後）。
> **精確度要求**：schema 欄位級、API quota 策略具體、Bronze/Silver key 佈局明確、DAG 結構具體。**API 用法用 context7 查證**（YouTube Data API v3 `commentThreads`/`comments`）。
> **定位**：這是 P1 的**additive 擴充**——在既有「影片 metadata ingest」旁，加一條**留言 ingest**。**不改動既有 P1 的 5 表 Gold 合約、不改影片 metadata 管線**；只新增 Bronze/Silver 留言資產（＋最小 Gold）。

## 為什麼（問題）
NORTH_STAR 決策 B：**加抓 YouTube 留言**，一份 ingest 打三個目的：
1. **正當化 Spark/Iceberg**——影片 metadata 只有幾千列，根本用不到 Spark；**留言是百萬列量級的真實大表**，才讓「Spark 分散式清洗 + Iceberg 大表管理」名正言順（否則 lakehouse 是殺雞用牛刀，面試會被問穿）。
2. **餵 P2b RAG 語料**——真實觀眾聲音，比只有標題/描述有料得多的問答/檢索基礎。
3. **餵 P2c 微調訓練資料**——A 情緒分類器的原料（弱標註對象）、全量打分對象。

**這是 lakehouse 故事的關鍵拼圖**：沒有留言，P1 的 Spark/Iceberg 是為技術而技術；有了留言，整條 DE 管線的重型工具都有真實負載撐著。

## 已鎖定決策（NORTH_STAR + 既有 P1，勿翻案）
- **留言來源 = YouTube Data API v3 `commentThreads.list`**（頂層留言）＋視需要 `comments.list`（回覆）。與既有影片 metadata 同一把 API key/hook（沿用 P1 §8 secret 姿態）。
- **走既有 medallion**：Bronze 存**原始 API JSON**（不 parse）→ Spark Silver 清洗成留言表 → 最小 Gold。用 P1 同一套 MinIO/Iceberg/Postgres/Airflow，**不另立資料棧**。
- **Bronze 保原文、決定性 key、冪等**（沿用 P1 §3）。
- **去識別**：留言作者**只留 hash**（不存真實 author display name / channel id 明文）——公開資料仍禮貌去識別，且 portfolio 不需要真實身分。
- **Spark 是這條的正當負載**：留言 Bronze→Silver 清洗用 Spark（對齊 P1，且這裡是 Spark 真的該上場的地方）。
- **執行環境 = 本地 k8s**（kind），零雲成本。

## 尚無取材原始碼（誠實）
recon 未發現既有專案有抓 YouTube 留言的碼（`youtube-analytics` 只有影片 metadata + 本地 parquet）。**這條是新寫的**——沒有「取材 vs 重造」問題，但要沿用既有 P1 design 的**結構慣例**（Bronze key 形狀、Spark job 骨架、Silver loader 模式、dbt）。Fable 5 讀 P1 design 抓那些慣例來套。

## 🔴 首要約束：YouTube API quota（design 必須正面處理）
YouTube Data API v3 預設 quota **10,000 units/天**；`commentThreads.list` 每次呼叫 **1 unit**、回傳最多 **100 則**留言。要湊到「百萬列」＝上萬次呼叫＝**單日 quota 不可能一次抓完**。design **必須**給出策略，不能假裝無限：
- **選抓哪些影片的留言**（不是全部影片都抓）：例如只抓每日 trending top-N 影片、或 velocity 最高的一批；用 quota 預算反推「每天抓幾支影片 × 每支抓幾頁」。
- **增量累積**：留言隨時間累積成大表（跨多天 ingest 疊加達到百萬量級），不是單日暴力抓。這**同時**讓 Iceberg 的「大表、分區、時間演進」故事更真。
- **quota 用盡的降級**：達上限就停、記錄進度、隔日續抓（對齊爬蟲的「斷點續傳」精神，但這裡是 API 分頁 token）。
- design 要算給看：假設每天抓 top-N 支 × 每支 M 頁，幾天累積到可用於 RAG/微調的量級。**誠實標明這是「累積型」而非「一次性」ingest**。

## 範圍（簇；Fable 5 定簇內細節與先後）

**C1 留言 Bronze ingest（API JSON 原始層）**
- Airflow DAG（或延伸既有影片 ingest DAG）：對選定影片集呼叫 `commentThreads.list` 分頁 → 原始 JSON response 寫 MinIO Bronze。決定性 key（重抓冪等）。quota 預算與續抓進度管理。
- **開放問題**：影片選取策略（trending top-N？velocity 高？依 quota 預算）？Bronze key 佈局（`s3://bronze/youtube_comments/video_id=<X>/ingest_date=<YYYY-MM-DD>/page=<token>.json` 類，對齊 P1 §3 決定性 key）？分頁 token / 續抓進度存哪（Postgres 小狀態表？MinIO？）？要不要抓回覆（`comments.list`）還是只頂層留言（頂層足夠餵 RAG/微調，回覆是 scope creep→傾向只頂層）？quota 用盡降級的具體機制？抓留言的排程與影片 metadata ingest 的關係（同 DAG 串接 vs 獨立 DAG）？

**C2 留言 Silver（Spark 清洗 → 留言表）**
- Spark job 讀 Bronze 原始 JSON → 展平清洗成 `silver_youtube_comments`（Iceberg 正本 + Postgres serving 副本，對齊 P1 §5 loader）。**Spark 在這裡是正當的**（百萬列展平/去重/清洗）。作者去識別（hash）。
- **開放問題**：Silver schema 欄位（建議：`comment_id`(PK)/`video_id`/`text`/`like_count`/`published_at`(timestamptz)/`author_hash`/`is_reply`/`reply_count`/`ingest_date`(分區鍵)/`language`?）？去重鍵（`comment_id`）與冪等？作者 hash 演算法（salted SHA？salt 存 Secret）？語言偵測要不要（留言中英混雜，P2b/P2c 可能要分流）？文字清洗程度（保原文給 RAG，只去控制字元/emoji 正規化到什麼程度）？Iceberg 分區策略（`ingest_date` / `video_id`？大表分區是這條的展示點）？Spark 資源（kind 上 spark-operator，對齊 P1）？

**C3 最小 Gold（可選 mart）+ 對下游的介面**
- **YAGNI**：留言的主要消費者是 P2b（RAG 讀 Silver）與 P2c（微調讀 Silver），**未必需要 Gold mart**。但可做一張最小 mart 餵 P4 一個「留言熱度/情緒」面板的骨架（情緒來自 P2c 微調 A 的打分表，非本階段）。
- **開放問題**：要不要 Gold mart（傾向：先只到 Silver，Gold 留給 P2c 情緒打分後才有意義的 `gold_video_comment_sentiment`——那屬 P2 產出，非 P1）？本階段對下游的介面就是 `silver_youtube_comments` 表 schema（P2b/P2c 依賴它，等同一個合約，要標穩定）？是否對既有 5 表 Gold 之一 additive 加「留言數」欄（如 `gold_video_lifecycle.comment_count`）？

**C-X DQ + 可觀測性 + 驗收**
- dbt DQ 測試（對齊 P1）：`comment_id` 唯一、`video_id` 外鍵存在、`published_at` 非空、無明文作者名。Airflow/Prometheus：留言 ingest 筆數、quota 使用量、Silver 新鮮度。
- **開放問題**：quota 使用量怎麼當指標進 Prometheus（給 Grafana 看還剩多少）？DQ 測試清單？去識別的驗證（測試斷言 Silver 無明文作者欄）？

## 設計方向約束（硬性，寫進 design）
- **純 additive**：不改既有 P1 的 5 表 Gold 合約、不改影片 metadata 管線、不改既有 Bronze/Silver。只新增留言資產。
- **沿用 P0/P1 慣例**：Bronze 保原文 + 決定性 key、Spark Bronze→Silver、Iceberg/MinIO、Silver 雙寫（Iceberg 正本 + Postgres 副本）、Airflow 編排、dbt DQ、kustomize + ArgoCD 子 Application、雲端可攜、secret 走 k8s Secret。
- **quota 誠實**：不假裝能無限抓；累積型 ingest + 選擇性抓 top 影片 + quota 降級，design 算給看。
- **去識別**：作者明文不落地，只存 hash。
- **Spark 名正言順**：這條要能回答「為什麼你的 lakehouse 需要 Spark」——留言大表就是答案，design 要把這個敘事點寫出來。
- **每步可測**：Bronze 冪等重抓不膨脹、Silver 去重、DQ 測試、去識別斷言。

## 交付與驗收（design 要回答的）
- quota 策略、影片選取、Bronze/Silver key 與 schema、續抓進度機制**收斂成決定**。
- 具體：Bronze key 佈局、`silver_youtube_comments` 欄位級 schema（下游合約）、Spark 清洗 job 結構、DAG 結構、DQ 測試清單、去識別演算法、Prometheus 指標。
- 部署形狀：留言 ingest/Spark job 在既有 P1 k8s/Airflow/spark-operator 上怎麼接、ArgoCD sync-wave 位置。
- 端到端驗收：選定影片 → `commentThreads.list` 分頁 → Bronze 有原始 JSON（冪等）→ Spark → `silver_youtube_comments` 有清洗留言（去重、去識別）→ DQ 綠 → quota 指標可見 → 多日累積量級達可餵 RAG/微調。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design（或增補進 P1 design，Fable 5 判）。**本階段只出 spec，plan 延後**。對齊既有 P1 design 的一切結構慣例，本增補是 additive。此增補的 Silver 留言表是 **P2b/P2c 的上游合約**，schema 要標穩定。
