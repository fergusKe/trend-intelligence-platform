# 即時特徵層（Flink，GA4 串流情境）— Fable 5 design brief（GA4 擴充第 2 波／即時層，掛 P6）

> **交付流程**：讀本 brief +「Fable 5 design 精確度契約 8 條」（[`CLAUDE.md`](../../CLAUDE.md) §Fable 5 design 精確度契約）+ [`NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段（Flink 條）+ **GA4 地基 design**：[`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md)（§4 Silver `ga4_events` = 事件重放源、§5.3 `gold_ga4_sessions` = 離線對照組）+ **P6 推薦 design（Redis feature schema = 接縫 A 單一真源）**：`2026-07-09-P6-recommendation-design.md`（Fable 5 若尚未產出，讀 `2026-07-09-P6-recommendation-brief.md` §共用契約-接縫 A）+ **P3 Kafka design**（`2026-07-08-P3-ptt-ingest-design.md`：Strimzi 單 broker KRaft、手動 commit at-least-once、Bronze 決定性 key 慣例）+ 下方「已查到的事實」→ `superpowers:brainstorming`（**非互動、開放問題全收斂**）→ 產出 `docs/specs/2026-07-09-P6-realtime-features-design.md`。**只出 design。**
> **git 紀律**：只寫 design markdown、不跑 git、不動 code。**語言**：繁體中文。

---

## 定位

**即時特徵層**：以 GA4 串流情境為背景，用 **Flink 有狀態事件時間（stateful event-time）計算**產出即時特徵，寫進 P6 的 Redis feature store，供 P6 線上推薦服務讀取。打 **DE / 串流 JD**，補上「批次之外還能做即時/串流特徵」這塊硬實力。掛在 **P6 推薦垂直**之下（即時特徵是推薦線上服務的輸入）。

**為什麼 Flink 正當**（NORTH_STAR 三工具翻案已批准，本 spec 落地）：**GA4 有真即時匯出**（`events_intraday_*` 近即時、client→GA4/GTM Server-Side→Pub/Sub→stream 的低延遲路徑真實存在）→「考慮即時數據情況」下引入串流特徵計算是有價值的真實情境。**選 Flink 勝 Spark Structured Streaming** ＝低延遲事件時間語意（event-time window、watermark、狀態管理）是 Flink 的本命強項。

## 已鎖定決策（勿翻案）

1. **誠實護欄（最高優先，不可違反）**：公開 sample **只有 daily export、無 events_intraday**（地基已鎖 batch-only）。→ 即時層以 **`silver.ga4_events` 的「標註事件重放（labeled event-replay）」** 當串流輸入示範——**明確標示「這是 sample 事件重放、非真線上流量」**（README + 前端 + design 通篇）。**不宣稱有真即時流量**。展示的是「若有真 intraday 流，這套 Flink 拓撲即可直接接上」的**架構就緒性**。
2. **＋Flink 翻案落地於此**（NORTH_STAR 已批准）：Flink ＝有狀態事件時間即時特徵（滑窗計數/session 視窗/去重）。**Airflow 仍是唯一排程器**——Flink job 是常駐串流 job（不受 Airflow 排程）；其部署/監控整合走既有 GitOps/Prometheus 紀律敘事，**不新增第二個排程器**。
3. **串流傳輸沿用 P3 Kafka**（一工一具）：事件重放 → Kafka topic（Strimzi 單 broker KRaft，P3 已建）→ Flink 消費。**不新增第二個 messaging**（Redis 只當 P6 feature store 出口、非 messaging）。
4. **出口 = P6 的 Redis feature store（接縫 A）**：Flink 算出的即時特徵寫進 **P6 定義的同一個 Redis**，schema **以 P6 推薦 design 的接縫 A 為單一真源**（本 spec 引用、不另定義；若發現需擴充欄位，回報並與 P6 對齊，不 fork）。
5. **正確性驗證 = 對照 `gold_ga4_sessions`（地基 §5.3）**：Flink 的 session 視窗/計數結果與批次 Gold session 表**離線對照**驗證串流計算正確（同一份 sample、兩條路徑應收斂）——這是「串流結果可信」的誠實證明，也是 Flink event-time 正確性的展示點。
6. **拓撲守**：Flink + Redis 是叢集內，**前端 Vercel 靜態不變**。即時層對前端的展示＝「即時特徵儀表/串流計算正確性對照」批次匯出 JSON（或純 MCP/截圖佐證）——線上串流能力以 **Flink Web UI 截圖 + 負載/重放 GIF + MCP** 佐證，非公開靜態站 runtime 依賴。
7. **M4 界線**：Flink JVM 天然跑 k8s（不涉 Apple GPU），此條不受 M4 限制——design 明寫「Flink 是 k8s 原生負載、非重算力繞道 host」。
8. **前端說明式 UI（硬性，跨 P4/P6/P7）**：任何即時層前端展示帶 ga-insight 式三層說明——特別是**要講清楚「這是事件重放示範、非真流量」**（Explainer 誠實揭露），讓招募方不誤解。

## 範圍

1. **事件重放產生器**：讀 `silver.ga4_events`（或 Iceberg 正本）→ 按 `event_ts_micros` 排序 → 以可控速率（design 定：加速倍率）重放進 Kafka topic（event-time 保留原始時間戳，processing-time 是重放當下）。**明確標註 replay 語意**。topic schema 欄位級。
2. **Flink 有狀態事件時間 job**：
   - **event-time + watermark**：以原始 `event_ts_micros` 為 event-time，watermark 策略（有界亂序）定案。
   - **特徵計算（design 收斂幾個代表性特徵）**：例如「使用者近 N 分鐘瀏覽同類別次數」（滑動視窗）、「使用者當前 session 加購未購件數」（session 視窗）、「item 近 N 分鐘熱度」（滑動計數）、事件去重（狀態）。
   - **狀態管理**：keyed state、狀態後端（design 定：RocksDB vs heap）、checkpoint 策略。
3. **Redis 出口（接縫 A）**：Flink sink → P6 Redis feature schema（引用 P6 design）。TTL、即時特徵 vs 離線特徵合併規則以 P6 為準。
4. **正確性對照**：Flink 輸出 vs `gold_ga4_sessions`/`gold_ga4_user_item_interactions` 的離線重算對照測試（同 sample 兩路徑收斂）。
5. **部署 + 監控**：Flink on k8s（design 定：Flink Kubernetes Operator vs standalone session cluster）、GitOps（ArgoCD）、Prometheus 指標（Flink metrics reporter → 既有 Prom）、Flink Web UI。
6. **前端/展示**：即時特徵儀表或串流正確性對照（批次匯出 JSON 或 MCP/截圖），**通篇標「事件重放示範」**。

## 開放問題（design 收斂，禁 TBD，皆附傾向）

1. **Flink on k8s 形狀**：Flink Kubernetes Operator（CRD `FlinkDeployment`）vs standalone session cluster manifest。傾向 **Flink Kubernetes Operator**（業界標準、GitOps 友善、可展示 CRD 運維）——design 定 operator 版本（context7 查證）+ `FlinkDeployment` 形狀。
2. **Flink API 層**：DataStream API vs Table/SQL API。傾向 **DataStream API**（展示 event-time/watermark/keyed-state 底層掌握度，是串流 JD 的核心考點；Table API 藏掉太多）——design 定，可補一個 Flink SQL 對照展示。
3. **狀態後端**：RocksDB vs heap。傾向 **RocksDB**（展示大狀態/checkpoint 運維，即使 portfolio 量小也是正確工程姿態）——design 定 checkpoint 間隔/存儲（MinIO S3 checkpoint）。
4. **代表性特徵集**：算哪幾個（傾向 3-4 個涵蓋 滑動視窗+session 視窗+狀態去重 三種 pattern，證明掌握不同視窗語意）。
5. **重放速率**：加速倍率（傾向可調、預設如 60×——1 小時真實壓成 1 分鐘）。事件重放的 event-time/watermark 與加速重放的交互定案。
6. **Redis sink 一致性**：at-least-once vs exactly-once。傾向 **at-least-once + 冪等寫（Redis SET 天然冪等）**（沿 P3 手動 commit at-least-once 姿態，特徵覆寫冪等無害）——design 定。
7. **展示前端 v1**：即時儀表（需輪詢批次匯出）vs 純 MCP+截圖。傾向 **v1 純 MCP + Flink Web UI 截圖 + 串流正確性對照批次 JSON**（前端靜態打不到即時流，勉強做即時儀表是拓撲謊言）——design 定，誠實說明。

## 共用契約（跨 spec 接縫）

- **接縫 A（消費方）｜Redis feature schema**：以 **P6 推薦 design 為單一真源**（本 spec 引用不定義）。Flink sink 寫入格式、key 命名、TTL 全對齊 P6。若需擴欄 → 回報對齊 P6，不 fork。
- **接縫 J｜事件重放源**：`silver.ga4_events`（地基 §4）；Kafka topic schema 本 spec 定義。
- **接縫 K｜正確性對照**：`gold_ga4_sessions`/`gold_ga4_user_item_interactions`（地基 §5.3/§5.1）為離線對照真值。
- **接縫 L｜Kafka 沿用 P3**：Strimzi 單 broker（P3 已建），本 spec 加 topic 不改 broker 部署。

## 設計約束（硬性）

- 精確度契約 8 條自檢。
- **誠實護欄最高優先**：通篇標「事件重放示範、非真線上流量」；不宣稱真 intraday 流。展示架構就緒性 + event-time 正確性。
- 一工一具（Flink 唯一新串流計算引擎、有獨特職務；Airflow 仍唯一排程器、Kafka 仍唯一 messaging、Redis 只當 P6 feature 出口）。
- 拓撲：Flink+Redis 叢集內、前端 Vercel 靜態；即時能力以 MCP/截圖/Flink UI 佐證。
- 沿用 P3 Kafka（at-least-once/決定性 key）、既有 GitOps/Prometheus/MinIO checkpoint 慣例，明講對齊。
- 進化非複刻：Flink 拓撲取材課程串流邏輯（若有）標界線；不複刻。
- Redis schema 不 fork P6（接縫 A 單一真源）。

## 交付與驗收

- 事件重放產生器（Kafka topic schema + 重放速率 + replay 語意標註）。
- Flink DataStream job（event-time/watermark/3-4 代表性特徵/keyed state/checkpoint）。
- Flink on k8s 部署（operator + `FlinkDeployment` CRD 形狀 + GitOps）。
- Redis sink（對齊 P6 接縫 A schema）。
- 正確性對照測試（Flink 輸出 vs Gold session/interaction 離線重算收斂）。
- Prometheus 指標接入 + Flink Web UI。
- 展示佐證（MCP/截圖/對照 JSON，標事件重放）。
- 端到端可跑驗收：重放 sample 一段事件 → Flink 算即時特徵 → 寫 Redis → 讀出驗證 → 與 Gold 離線對照收斂 → Flink UI 顯示 checkpoint/watermark 推進。
- plan-前實查點清單（帶預設傾向，尤其 Flink Kubernetes Operator 版本/CRD + Flink 版本 context7 查證）。

## 已查到的事實（免重探）

- **GA4 地基已鎖合約**（`2026-07-09-P6-ga4-ingestion-foundation-design.md`）：§4 `silver.ga4_events`（event-item 展開、`event_ts_micros` 原始 μs epoch = event-time 源、PK 四鍵）；§5.3 `gold_ga4_sessions`（漏斗活躍 session、`session_start_ts/end_ts`/旗標，= 串流 session 視窗離線對照）；§5.1 `gold_ga4_user_item_interactions`（滑窗計數離線對照）。§13：無 intraday（誠實護欄根因）。
- **P3 Kafka 慣例**（`2026-07-08-P3-ptt-ingest-design.md`）：Strimzi 單 broker KRaft（免 Zookeeper）、consumer 手動 commit offset = at-least-once、Bronze 信封決定性 key。→ 事件重放 topic 沿用此 Strimzi broker，加 topic 不改部署。
- **P6 Redis feature schema**（`2026-07-09-P6-recommendation-brief.md` §共用契約-接縫 A；design 產出後以 design 為準）：即時特徵寫入的 key 命名/value 結構/TTL/合併規則的單一真源。
- **NORTH_STAR Flink 翻案理由**（三工具翻案表 Flink 條）：GA4 有真 intraday 匯出 → 即時情境正當；選 Flink 勝 Spark SS（低延遲 event-time）；**用標註事件重放示範、不假裝真流量**。
- **既有 GitOps/監控**（P0）：ArgoCD app-of-apps + kube-prometheus-stack + MinIO（S3 checkpoint 存儲可用）。
- **前端說明式 UI 範本**（`llm-workshop/ga-insight`）：三層說明；即時層**特別用 Explainer 誠實揭露「事件重放非真流量」**，避免招募方誤解展示性質。

## 尾註
非互動、開放問題全收斂附傾向、**誠實護欄最高優先（事件重放非真流量）**、一工一具（Flink 唯一新串流引擎·Airflow 仍唯一排程·Kafka 仍唯一 messaging）、拓撲守、Redis schema 不 fork P6（接縫 A）、正確性對照 Gold（接縫 K）、Flink 版本/operator context7 查證。只寫 design markdown。
