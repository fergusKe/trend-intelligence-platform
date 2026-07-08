# P6 推薦系統（核心垂直）— Fable 5 design brief（GA4 擴充第 2 波／P6 主垂直）

> **交付流程**：讀本 brief +「Fable 5 design 精確度契約 8 條」（[`CLAUDE.md`](../../CLAUDE.md) §Fable 5 design 精確度契約）+ [`NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段 + **GA4 地基 design（已鎖定合約，本 spec 上游）**：[`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md)（尤其 §4 Silver `ga4_events`、§5.1 `gold_ga4_user_item_interactions`、§5.2 `gold_ga4_item_catalog`）+ **P2 ML design**（`2026-07-08-P2-ml-verticals-design.md`：DVC/MLflow/KServe/drift/LangGraph CRAG 慣例）+ **P4 匯出合約**（`2026-07-08-P4-presentation-layer-design.md` §3-4）+ 下方「已查到的事實」→ `superpowers:brainstorming`（**非互動、開放問題全收斂**）→ 產出 `docs/specs/2026-07-09-P6-recommendation-design.md`。**只出 design。**
> **git 紀律**：只寫 design markdown、不跑 git、不動 code。**語言**：繁體中文。

---

## 定位

P6 的**核心垂直**：以 GA4 地基的 user×item×interaction 三角，做一條**完整的工業級推薦生命週期**——召回（recall）→ 排序（ranking）→ 線上服務（online serving）→ 推薦理由生成 → A/B ＋ 離線評估。打 **MLOps / 推薦系統 JD**。這是 web-agency serverless 架構做不完整（無常駐線上服務）、trend 平台 k8s 才能做完整的那條。

**上游合約已鎖**（地基 design）：`gold_ga4_user_item_interactions`（user×item×event×date，**刻意不加權**）＝CF/共現召回矩陣源；`gold_ga4_item_catalog`（item_id + `item_name`/`item_category` 文字欄 + 漏斗表現）＝item 特徵 + **語意 embedding 的文字輸入源**（embedding 本體在本 spec 造）。

## 已鎖定決策（勿翻案）

1. **資料源只用 GA4 地基產出的 Gold/Silver 合約**（公開 sample，area02 零進入）。**互動加權在本 spec 定義**（地基刻意不加權）：view/cart/checkout/purchase 的權重是 P6 演算法決策——design 定明確權重表（例如 view=1/cart=3/checkout=4/purchase=5，或收斂成可調參數 + 預設），並說明取捨。
2. **＋Redis 翻案落地於此**（NORTH_STAR 已批准）：Redis ＝線上服務 **<50ms 特徵/候選快取**（online feature store + 預算候選集）。純線上快取用途，**不當第二個 OLTP/排程/佇列**；離線特徵/訓練資料仍在 Postgres+Iceberg。
3. **線上服務走叢集內 service（KServe），前端仍 Vercel 靜態不變**：P6 對 P4 的合約＝「**批次產生的推薦表 → P4 匯出 DAG → 靜態 JSON**」（例如熱門/相似商品/分群代表推薦，前端可展示）；**KServe 線上推論端點 + Redis 是叢集內能力**，以**負載測試 + MCP 工具 + 截圖/GIF** 佐證，**不是公開靜態站的 runtime 依賴**（守 P2 §「Vercel 打不到本地 k8s」鐵律）。
4. **沿用 P2 MLOps 慣例不重造**：DVC 離線訓練管線 + MLflow 追蹤/Registry（alias `@staging`/`@prod`）+ KServe RawDeployment serving + Airflow 重訓 DAG + drift（PSI+KS+rolling 指標）。推薦理由生成**複用 P2 的 LangGraph CRAG 圖範式**（retrieve→grade→generate，把 retrieve 換成推薦候選+item 特徵）。
5. **微調/embedding 算力守 M4 原生界線**：item/語意 embedding 批次、任何模型訓練走 M4 host；k8s 負責編排/serving-glue/CPU-feasible serving（守 NORTH_STAR M4 原則）。
6. **一工一具仍守**：排程只 Airflow、離線 DB 只 Postgres（向量 pgvector 同顆）、agent 只 LangGraph、微調只 HuggingFace。Redis 是這條垂直**唯一**新增的線上元件，且有獨特職務（線上特徵/候選快取）。
7. **前端說明式 UI（硬性，跨 P4/P6/P7）**：P6 的任何前端頁/圖表帶 ga-insight 式三層說明——(a) `InfoTooltip`（設定值語意）/(b) `ChartCaption`（圖表視覺語法/單行公式）/(c) `Explainer`（方法論/定義，定義類預設展開·方法論類預設收合）。地基已在 Gold marts 的 dbt description 備好「這是什麼」語意文字，前端直接引用。

## 範圍（一條完整推薦生命週期）

1. **召回層（多路，design 收斂路數與各自演算法）**：
   - **協同過濾/共現**：以 `gold_ga4_user_item_interactions` 為矩陣源（item2vec / ALS / item-item 共現，design 收斂用哪個/幾路）。
   - **語意召回**：`gold_ga4_item_catalog` 的 `item_name`/`item_category` → 本地 embedding（e5 或同款，守 M4）→ **pgvector**（複用 P1 Postgres，HNSW，沿 P2 §pgvector 慣例）→ 相似商品召回。
   - **冷啟/熱門 fallback**：無互動 user/item 的降級路（熱門、類別熱門）。
2. **排序層（LTR）**：召回候選 → 特徵組裝（user 特徵 + item 特徵 + 交互特徵）→ 排序模型（design 收斂：GBDT/LightGBM pointwise vs pairwise/listwise LTR vs Wide&Deep——選一條主線落地、其餘列進化方向）。訓練走 DVC + MLflow，模型上 Registry。
3. **線上服務層**：
   - **Redis 特徵/候選快取**：離線算好的 user/item 特徵向量 + 預算召回候選集寫進 Redis（key/value schema 欄位級定義）；線上請求 <50ms 讀取。
   - **KServe 推論**：排序模型 InferenceService（沿 P2 §KServe manifest 形狀，RawDeployment）；召回→排序微服務切分（design 定切分邊界）。
   - **這是即時 Flink 特徵層的下游**：Flink 算的即時特徵寫進**同一個 Redis**（跨 spec 接縫，見下「共用契約」）；本 spec 定義 Redis feature schema、即時層寫入、線上服務讀取三方共識。
4. **推薦理由生成（LLM-native）**：複用 P2 LangGraph CRAG 圖 → 給定 (user, 推薦 item, item 特徵) → 生成一句自然語言推薦理由（露露口吻不適用，此為 portfolio 展示，中性口吻）。生成 LLM 走 Ollama 預設/Gemini fallback（守 P2）。守 anti-hallucination（理由只引 item 真實特徵，不編造）。
5. **A/B ＋ 離線評估**：
   - **離線評估**：hit@k / ndcg@k / recall@k / MAP，時間切分（train/test 按 event_date 切，防洩漏——`data_anchor_date` 前 N 天訓練、後 M 天測試）。
   - **A/B 框架**：design 定 bucket 切分 + 指標（線上點擊/轉換代理指標）+ 護欄指標 + 停止規則（portfolio 用合成流量/事件重放示範，誠實標註非真線上流量）。
6. **前端展示頁**：讀 P6 匯出的批次推薦 JSON（相似商品/熱門/分群推薦），帶三層說明式 UI；線上服務能力以 MCP 工具 + 負載測試截圖佐證。

## 開放問題（design 收斂，禁 TBD，皆附傾向）

1. **召回路數**：幾路（傾向 3 路：共現 CF + pgvector 語意 + 熱門 fallback）。各路演算法定案。
2. **CF 演算法**：item2vec（word2vec on 互動序列）vs ALS 矩陣分解 vs item-item 共現。傾向 **item2vec**（可展示 embedding + 跟語意召回共用向量檢索基建，最少新依賴）——design 定並說明。
3. **互動加權表**：view/cart/checkout/purchase 權重（傾向 1/3/4/5，且 CF 用隱式回饋 confidence）。
4. **排序模型**：GBDT LTR（LightGBM）vs Wide&Deep。傾向 **LightGBM LTR（lambdarank）**（M4 友善、無需 GPU、可解釋特徵重要度、業界標準）——design 定主線，Wide&Deep 列進化方向。
5. **Redis 部署形狀**：k8s 內 Redis（單機 vs Sentinel）。傾向**單機 Deployment + PVC**（portfolio 規模，Sentinel/Cluster 是過度工程，誠實 ADR 註記）。Redis feature schema 欄位級。
6. **召回/排序微服務切分**：單一 service vs 召回+排序兩 service。傾向**兩階段一 service 內**（portfolio 規模，避免跨服務網路跳；但保留「可切分」的介面邊界說明）——design 定。
7. **A/B 流量來源**：合成流量 vs 事件重放。傾向**事件重放**（重用即時層的 sample 事件重放基建，一致且誠實）——design 定，明確標「非真線上流量」。
8. **推薦理由是否進批次匯出**：離線為熱門/相似商品預生成理由存表 vs 純線上生成。傾向**熱門集離線預生成進匯出 JSON**（前端可直接展示帶理由的推薦，線上生成留 MCP demo）——design 定。
9. **時間切分點**：train/test 切分的 N/M 天（傾向後 14 天當 test）。

## 共用契約（跨 spec 接縫，design 必須明訂——即時層/P7 會引用）

- **接縫 A｜Redis feature schema（P6 ↔ 即時 Flink）**：即時 Flink 層算的 event-time 特徵（如「近 1 小時瀏覽同類別次數」）寫進 Redis，P6 線上服務讀取。**本 spec 是 Redis feature schema 的單一真源**——定 key 命名（如 `feat:user:{user_pseudo_id}`）、value 結構（欄位級）、TTL、離線特徵 vs 即時特徵的合併規則。即時層 brief 會引用本節。
- **接縫 B｜interactions 不加權**（地基 §5.1 明訂）：本 spec 是**加權的唯一定義處**，下游不得假設地基已加權。
- **接縫 C｜item_catalog 文字欄 = embedding 輸入源**（地基 §5.2）：語意 embedding 在本 spec 造，地基只出文字。
- **接縫 D｜P6→P4 匯出**：只加檔/加欄（P4 §4 additive），不改既有 11 檔。

## 設計約束（硬性）

- 精確度契約 8 條自檢。
- 一工一具（Redis 是唯一新線上元件、有獨特職務；離線仍 Postgres+pgvector）；M4 算力界線；拓撲（線上服務叢集內、前端 Vercel 靜態走匯出合約、打不到 k8s）；additive（不改地基合約、不改 P4 既有匯出）。
- 沿用 P2 DVC/MLflow/KServe/drift/LangGraph 慣例，明講對齊哪個模式。
- 進化非複刻：取材課程演算法（item2vec/LTR/Redis 快取/生成理由）標「取什麼邏輯 vs 重造工程層」；不複刻任何課程專案結構。
- A/B 用事件重放**誠實標註非真線上流量**（同即時層護欄）。
- 推薦理由守 anti-hallucination（只引真實 item 特徵）。

## 交付與驗收

- 召回層（多路 + 各演算法 + pgvector 語意）+ 離線 recall@k。
- 排序層（LTR 模型 + 特徵組裝 + MLflow Registry）+ 離線 ndcg@k/hit@k。
- 線上服務（Redis feature schema 欄位級 + KServe InferenceService manifest + 召回/排序切分）。
- Redis 部署形狀（manifest/PVC/values）。
- 推薦理由 LangGraph 圖（沿 P2）+ anti-hallucination 驗收。
- A/B 框架（bucket/主指標/護欄/停止規則）+ 事件重放來源（標非真流量）。
- 重訓 DAG（Airflow，沿 P2）+ drift 監控。
- 前端展示頁（批次推薦 JSON + 三層說明式 UI）+ 線上能力 MCP/負載測試佐證。
- 端到端可跑驗收：GA4 Gold → 訓練 → Registry → KServe+Redis 線上回一組推薦（含理由）→ 離線 hit@k/ndcg@k 數字。
- plan-前實查點清單（帶預設傾向）。

## 已查到的事實（免重探）

- **GA4 地基已鎖合約**（`2026-07-09-P6-ga4-ingestion-foundation-design.md`）：§4 `silver.ga4_events`（event-item 展開，PK `(user_pseudo_id,event_ts_micros,event_name,item_id)`）；§5.1 `gold_ga4_user_item_interactions`（**刻意不加權**，欄 `interaction_count/sessions_count/total_quantity/total_revenue/first_event_ts/last_event_ts`）；§5.2 `gold_ga4_item_catalog`（`item_name`/`item_category` 文字 + `users_viewed/carted/checked_out/purchased` + `view_to_cart_user_rate` 等漏斗率）。
- **P2 可複用慣例**（`2026-07-08-P2-ml-verticals-design.md`）：pgvector HNSW（`m=16, ef_construction=64`，`vector_cosine_ops`）；KServe InferenceService（RawDeployment、`protocolVersion: v2`、`storageUri: s3://ml-models/...`、sync-option 註解）；MLflow alias `@staging`/`@prod` + Prompt Registry；DVC `export→features→train→evaluate` 在 M4 host、重訓 DAG `export_dataset→train_and_gate→notify`；drift PSI+KS+rolling AUC，表 `ml.ml_drift_metrics`；LangGraph CRAG 圖 `retrieve→grade→(generate|rewrite|degraded)`，state TypedDict，Ollama `qwen3` host/Gemini fallback via `ollama-host.ml.svc` ExternalName。
- **P4 匯出合約**（`2026-07-08-P4-presentation-layer-design.md` §3-4）：統一 JSON 信封（`dataset/generated_at/source_tables/status/row_count/rows`）；`export_frontend_data` DAG（`check_freshness→export_datasets→write_meta→validate_exports`）；k8s→MinIO→host `make export-sync`→人審 commit；additive-only。
- **課程演算法地圖**（供取材，標「取邏輯不複刻」）：召回（item2vec/ALS/DeepWalk/LSH-Faiss/BERT-CLIP embedding）；排序（GBDT/FTRL/Wide&Deep/LTR pointwise-pairwise-listwise）；serving（Redis 特徵快取/gRPC-ONNX/召回-排序微服務切分）；MLOps（Airflow+MLflow 重訓）；LLM-native（T5 next-item/LoRA Yes-No 偏好/生成推薦理由/對話式 agent）。
- **前端說明式 UI 範本**（`llm-workshop/ga-insight`）：三層 = widget `help=`（設定語意）/ `st.caption`（圖表視覺語法+單行公式）/ `st.expander`（方法論，定義類 `expanded=True`·方法論類收合）。Next.js 映射：`InfoTooltip`/`ChartCaption`/`Explainer`。

## 尾註
非互動、開放問題全收斂附傾向、一工一具（Redis 唯一新線上元件有獨特職務）、拓撲守（線上叢集內、前端匯出合約）、沿用 P2 慣例、進化非複刻、A/B 誠實標非真流量、anti-hallucination。定義好接縫 A（Redis schema）供即時層引用。只寫 design markdown。
