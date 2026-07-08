# P2 三條 ML 垂直 — 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)（尤其「LLM／微調層與留言語料」專章 + M4 原生算力原則）+ **P0 design**（平台/GitOps/CI/監控慣例）+ **P1 design**（§6a **Gold marts 5 表合約** + **P1 留言 ingest 增補 design**——P2b/P2c 的語料來源）→ `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P2-ml-verticals-design.md` → （plan 延後）。
> **精確度要求**：每個開放問題在 design 收斂成明確決定；技術選型具體到工具版本、資料表/特徵 schema、DAG 結構、KServe/服務 manifest 形狀、檔案路徑。**版本用 context7 查證**（LangChain/LangGraph/HuggingFace transformers/PEFT/Ollama/pgvector）。
> **定位**：P2 是**ML 層（MLOps/LLMOps）**——在 P1 的乾淨 Gold + 留言資料上，蓋**三條各自完整的模型生命週期**，全部跑在 P0 的 k8s、用 P0 的 GitOps 部署、被 P0 的 Prometheus/Grafana 監控（**重算力原生跑 M4，見 NORTH_STAR M4 原則**）。這是「MLOps / ML 工程師」JD 的主戰場，也是本專案跟純 DE portfolio 的差異化。

## 為什麼（問題）
NORTH_STAR 定案 ML **三條都放**：(a) 傳統 tabular（MLflow+KServe+DVC+drift/重訓）、(b) LLMOps/RAG（LangGraph agentic + CRAG）、**(c) 微調（HuggingFace：A DistilBERT 情緒分類器＋B 小 LLM LoRA 標題生成器）**。P2 要把三條蓋成**業界標準的模型生命週期**——不是「跑得動的 notebook」，而是**可版本化資料 → 可追蹤訓練 → 可註冊晉升（Staging→Prod）→ k8s serving → 漂移監控/評估閘**的閉環，三條共用一套 MLOps 底盤（MLflow+DVC+KServe+MinIO+Postgres）。

取材專案 `youtube-analytics` **已有 (a)(b) 的核心邏輯**（RandomForest 預測 + Qdrant/RAG），但 recon 證實它們**都停在 demo 半成品**（見下「已查到的事實」）：模型在請求路徑上即時重訓、零持久化、零評估；RAG 索引函式從沒被呼叫過、向量庫跑記憶體模式、CrewAI 已註「暫停用」、零 LLMOps 監控。(c) 微調**是全新的**（原碼無）。**P2 的核心工作＝把 (a)(b) 半成品補成真正的 MLOps/LLMOps 閉環（取材純邏輯、重造工程層、並把 agent 框架換成 LangGraph），並新增 (c) 微調兩條**。

## 已鎖定決策（NORTH_STAR 2026-07-08 定案 + 前階段，勿翻案）
- **三條都做**：(a) tabular 影片表現時序預測、(b) LLMOps/RAG、**(c) 微調（A DistilBERT 情緒分類器＋B 小 LLM LoRA 標題生成器）**。
- **技術棧**：
  - tabular = **DVC** → **MLflow**（追蹤 + Registry, Staging→Prod）→ **KServe** → Airflow 重訓 + drift 監控。
  - LLMOps = **LangChain + LangGraph**（agentic RAG + **CRAG 自我校正**，**取代 CrewAI**）＋ **pgvector**（🔒 選定，複用 P1 Postgres，不用 Qdrant）＋ **本地 embedding**（🔒 選定，百萬留言不打外部 API）＋ **生成 LLM 可切換**（🔒 本地 **Ollama** 預設 / **Gemini API** fallback＋A-B）＋ hybrid 檢索 ＋ prompt 版本 ＋ 評估閘 ＋ 成本/延遲監控。
  - 微調 = **HuggingFace**（🔒 選定，可攜標準、M4 免費跑小模型）：A = DistilBERT（transformers Trainer）、B = 小 LLM **PEFT LoRA**（fp16，非 bitsandbytes 4-bit——後者 CUDA-only 跑不了 M4）。**不用 MLX**。
- **🔒 M4 原生算力原則（NORTH_STAR）**：kind 的 Linux VM 摸不到 Apple GPU → **微調、本地 LLM 推論（Ollama）、本地 embedding 批次一律原生跑 M4 host**；k8s 負責編排/serving-glue/lakehouse/監控 + CPU-feasible serving（DistilBERT）。產出模型（HF 標準格式）上 MLflow/MinIO、可攜雲端 GPU。RAG 服務（k8s）呼叫 host 上 Ollama 的接線界線 design 要畫清。
- **一個工作一個工具**：排程只 Airflow、DB 只 Postgres（含 pgvector）、監控只 Prom+Grafana、物件儲存只 MinIO、模型追蹤只 MLflow。**MLflow/DVC/KServe 的 backing store 一律複用 P1 既有的 Postgres + MinIO，不新增資料庫或物件儲存**。
- **部署**：沿用 P0 GitOps（ArgoCD app-of-apps）+ GitHub Actions CI + 雲端可攜 manifest；ML 服務進 `ml/` 目錄、走既有服務接入契約。
- **資料來源**：tabular = **P1 Gold marts**（§6a 5 表合約，additive-only）；**P2b RAG 語料 + P2c 微調訓練資料 = P1 留言 Silver 表**（P1 留言 ingest 增補 design 產出的 `silver_youtube_comments` 類表 + Gold `gold_video_lifecycle` 的 title/description）。**P2 不繞過既有層直接重抓**；缺欄走「對 Gold/Silver additive 加欄」並明列。
- **執行環境 = 本地 k8s**（kind）+ **M4 host（重算力）**，零雲成本；外部只允許 Gemini API（P2b 生成 fallback／P2c 弱標註可用）。

## 已查到的事實（recon `youtube-analytics`，2026-07-08，唯讀取材別重探；路徑省略共同前綴 `.../youtube-analytics/`）

### A. Tabular（取材 `pages/.hidden/8_🔮_影片表現預測.py`）
- **可直接取材的純函式**（無 `st.*` 依賴）：`extract_features()`（`:186-228`）、`train_prediction_model()` 本體（`:232-288`）、`predict_video_performance()`（`:291-316`）、`calculate_confidence()`（`:318`，用 `model.estimators_` 樹間 25/75 百分位當區間）。
- **17 個特徵**由 `title/description/tags/duration_minutes/published_at` 即時衍生（標題長度/emoji/關鍵字命中/描述長度/標籤數/時長 is_short/is_long/發布時段 is_prime_time…；硬編碼熱詞清單 `:199-200`）。**目標 = `view_count`（回歸）**（`:265`）。
- **工程層全空（＝P2a 要補的）**：**無 train/test split**（`model.fit(X_scaled, y)` 吃全量 `:280`）、**無任何持久化**（全專案 grep `joblib|pickle|mlflow|.pkl` 零命中）、**評估指標是硬編碼字串**（UI「±25%」`:792` 是寫死的，非算出）、靠 `@st.cache_resource`（`:231`）當唯一「快取」冷啟即重訓。所謂「爆紅機率」是把回歸預測值套一張硬編碼百分位→機率查表（`:327-357`），非學習得來。
- **資料來源 = 本地檔**（`DataManager.load_latest_data` 讀 `data/processed/*.parquet`，`src/data/manager.py:244-294`），非 DB。→ 對接新平台改吃 P1 Gold。

### B. LLMOps/RAG（取材 `src/ai/core/`）
- **服務層已完全無 Streamlit 依賴**（`src/ai/` grep `import streamlit` 零命中）→ `rag_pipeline.py` + `qdrant_manager.py` + `gemini_client.py` **可整包搬走**；耦合只在 page 層（`pages/.hidden/14_🤖_AI內容助手.py` 的 `@st.cache_resource`）。
- **向量庫**：Qdrant，**預設 `:memory:`**（`qdrant_manager.py:32,:78-81`），5 collection，**768 維 / COSINE**。
- **Embedding**：Google Gemini `models/embedding-001`（`gemini_client.py:59-62`，768 維）。
- **RAG pipeline**（`rag_pipeline.py`）：chunk 1000/overlap 200（`:59-66`）、top-k 5（先取 10 再截，`:159-170`）、score_threshold 0.7、**rerank 用 LLM-as-judge**（逐筆 Gemini 打分 `:190-219`，成本/延遲隱患）、context 上限 4000 字元。
- **生成 LLM**：主 = Gemini `gemini-2.0-flash-exp`（`gemini_client.py:22`）；另有 OpenAI `gpt-5-mini`（`openai_client.py:20`）但該路不接 RAG。**Agent 編排 = CrewAI**（`youtube_content_crew.py`），但 `content_assistant.py:54` 註「暫停用 CrewAI（相容性問題）」。
- **三個關鍵缺口（＝P2b 要補的）**：①**索引函式 `index_youtube_data()` 從沒被呼叫**（grep 僅見定義）→ `:memory:` Qdrant 開機是**空的**、RAG 檢索打空庫；②**零 LLMOps 監控**（src/ai grep `eval|cost|token_usage|latency|version` 無實作，無 token 計數/成本/prompt 版本/答案評估）；③**Gemini API key 硬編碼寫死在原始碼**（`gemini_client.py:37` 的 `os.getenv` 預設值）——🔴 **P2 絕不可沿用，必走 k8s Secret**。
- 索引語料來源（`_prepare_content` `:116-129`）：TITLE/DESCRIPTION/TAGS → 對接新平台 = Gold `gold_video_lifecycle` 的 `title/description/tags`。

## 設計進化方向（硬性寫進 design；本專案「參考是輸入非天花板」）
**原始碼預測靜態 `view_count`（回歸、無時序）。但 P1 給了時序資料**——`gold_video_lifecycle` 有 `first_views/latest_views/total_views_gained/peak_delta_views_per_hour/hours_on_chart`，`gold_video_velocity_hourly` 有每小時增速。**P2a 應改用「上榜早期訊號 → 預測後續表現」的時序題**，例如用「首次快照特徵 + 影片 metadata」預測 `total_views_gained` 或 `peak_delta_views_per_hour`（爆紅強度），或二分類「未來 N 小時是否翻倍」。理由：(1) 這才有真實 label（不是硬編碼查表）；(2) 趨勢每小時變→模型**真的會漂移**→drift 監控與自動重訓的故事是真的；(3) 展示「從 lakehouse 時序特徵工程」比「靜態欄位回歸」資深得多。Fable 5 在 design 收斂**最終預測目標與 label 定義**（含正負樣本/時間切割避免洩漏）。

## 範圍（簇；Fable 5 定簇內細節與先後）

**P2-0 共用 MLOps 底盤**（兩條共享，先立）
- `ml/` 目錄佈局；**MLflow**（tracking server + Model/Prompt Registry）部署在 k8s，**backend store 用 P1 的 Postgres（新 db/schema）、artifact store 用 P1 的 MinIO（新 bucket）**；**DVC** remote 指向 MinIO；ArgoCD 子 Application 接入（sync-wave 接在 P1 之後）。
- **開放問題**：MLflow 部署方式（官方 Helm chart vs plain manifest，對齊 P1 對 MinIO 的 plain-kustomize 選擇）？MLflow backend/artifact 具體接法（Postgres db 名、MinIO bucket 名、S3 endpoint env）？DVC remote 佈局與「資料版本化的到底是什麼」（Gold 匯出的訓練快照 parquet？RAG 語料快照？）？MLflow 是否同時當 **prompt/LLM 版本註冊**（P2b 共用，一個工具兩用）還是 P2b 另立？KServe 安裝模式——**KServe RawDeployment（純 k8s Deployment，不裝 Knative/Istio）vs Serverless（Knative+Istio，重）**？（成本紀律 + kind 資源 → 傾向 RawDeployment，但要 Fable 5 確認 KServe 版本對 RawDeployment 的支援度與 autoscaling 取捨）。

**P2a-1 特徵/label 工程（從 Gold，離線可重現）**
- 從 P1 Gold（`gold_video_lifecycle` 為主 + 視需要 `gold_video_velocity_hourly`）建訓練資料集；特徵取材 `extract_features()` 的衍生邏輯（標題/描述/標籤/時段…），label 依「設計進化方向」定。DVC 版本化該資料集。
- **開放問題**：特徵集最終清單（保留原 17 個哪些、時序新增哪些如 `first_views`/上榜時影片年齡 `first_seen_at - published_at`/初期 velocity）？**`duration` 缺口**——原模型用 `duration_minutes`，但 P1 Silver/Gold schema **沒有 duration 欄**（P1 §6a 未列）→ 決定：對 `gold_video_lifecycle` **additive 加 `duration_seconds`**（P1 Silver 本就抓 contentDetails，補一欄）還是**丟棄時長特徵**？（傾向加欄，時長對 Shorts/長片表現差異大）。時間切割怎麼防洩漏（label 是未來值，特徵只能用「首次快照時」已知的）？資料集怎麼從 Postgres Gold 匯出成 DVC 追蹤的 parquet（一支 Airflow task？）？

**P2a-2 訓練管線（DVC → sklearn → MLflow）**
- 正規訓練：train/test split（或時序 split）、RandomForest（或升級 model）、StandardScaler、**真實評估指標**（回歸 MAE/RMSE/R²、或分類 AUC/PR）、特徵重要性。全程 MLflow log（params/metrics/artifacts/model），註冊進 Model Registry，**閘門晉升 Staging→Prod**。取材 `course/udemy/機器學習工程與維運實戰` 的 `model/model_training.py`（MLflow Staging→Prod 骨架）。
- **開放問題**：訓練在 k8s 怎麼跑（Airflow KubernetesPodOperator 跑 training image vs KServe 無關的 Job）？split 策略（隨機 vs 時序 hold-out，時序題應後者）？晉升閘門條件（metric 門檻，取材 ML 實戰課的閘）？baseline 模型與比較（至少一個 dummy/線性 baseline 證明 RF 有價值）？特徵順序/schema 如何固定（recon 指出原碼靠 dict 插入序，StandardScaler/RF 對順序敏感——要顯式 schema）？

**P2a-3 KServe serving**
- 把 Prod 模型從 MLflow Registry 拉出，包成 KServe InferenceService（k8s 上）；提供推論 endpoint（給 P4 前端/批次打分用）。取材 MLOps 課 `10-cicd-for-models/.../02-dvc-docker-kserve-argocd.md`。
- **開放問題**：serving runtime（KServe 內建 sklearn/MLServer runtime vs 自訂 predictor image）？模型怎麼從 MLflow Registry 進 KServe（storageUri 指 MinIO artifact vs 自訂 image 烤模型）？InferenceService 由 ArgoCD 管（宣告式）還是 CD 動態更新？前處理（StandardScaler）在哪（KServe transformer vs 烤進 predictor）？

**P2a-4 drift 監控 + 自動重訓**
- 監控線上/新進資料的特徵/預測漂移；漂移超閾 → 觸發重訓 DAG → 新模型評估 → 過閘則晉升 + KServe rollout。取材 ML 實戰課 `model/model_drift.py` + `jobs/dags/model_drift_dag.py`。
- **開放問題**：drift 怎麼算（PSI/KS test/預測分佈偏移，取材課程）？監控排程（Airflow @daily？）？漂移指標怎麼進 Prometheus（給 Grafana + 告警）？重訓觸發是全自動還是「偵測→告警→人工核准晉升」（portfolio 展示自動閉環 vs 安全人工閘的取捨）？「趨勢每小時變」如何構造出可見的 drift demo？

**P2b-1 RAG 語料索引（補上從沒被呼叫的索引 job）+ 持久 pgvector 向量庫**
- 建一支真正會跑的 ingest：**主語料＝P1 留言 Silver 表**（真實觀眾聲音，百萬列，比只有標題/描述有料）＋輔以 Gold `gold_video_lifecycle` 的 `title/description/tags` → **本地 embedding** → **pgvector（P1 Postgres 內新 schema/表）**。取材 `rag_pipeline.py` 的 `index_youtube_data`/`_prepare_content` 邏輯，但補上呼叫端、換掉 `:memory:` Qdrant → pgvector、換掉 Gemini embedding → 本地。
- **🔒 已鎖定**：向量庫 = **pgvector**（複用 P1 Postgres、零新增常駐服務、對齊「DB 只 Postgres」紀律）；embedding = **本地模型**（百萬留言不打外部 API）。
- **開放問題**：本地 embedding 具體模型與**跑法**——sentence-transformers 類模型，(i) 原生跑 M4（MPS，批次快）寫回 pgvector，還是 (ii) 包成 KServe CPU InferenceService（一致故事但慢）？（M4 原則傾向 (i) 當離線批次 embedding job，KServe 留給線上/分類器）。embedding 維度/模型選型（多語？留言中英混雜）？索引 job 排程（留言 Silver 更新後觸發？@daily？）、chunk/collection 結構（留言短，是否還需 1000/200 chunk 或整則留言一 doc）？語料版本化是否納 DVC？

**P2b-2 RAG pipeline（LangGraph agentic + CRAG，取代原碼 CrewAI）**
- 檢索 + 生成串成一個 **LangGraph 狀態機**服務（k8s API）。**CRAG（Corrective RAG）**：檢索後自評相關性 → 不足則改寫查詢/重檢索/降級，避免打空庫或答非所問。**hybrid 檢索**（pgvector 向量 + 關鍵字）。生成 LLM **可切換**：本地 **Ollama**（原生跑 M4，預設）/ **Gemini API**（fallback＋A-B）。
- **🔒 已鎖定**：agent 框架 = LangChain+LangGraph（**砍 CrewAI 與 OpenAI 那路**）；RAG 型態 = agentic + CRAG + hybrid；生成 = Ollama 預設 / Gemini fallback。
- **開放問題**：LangGraph 圖節點結構（retrieve→grade→(rewrite→re-retrieve)*→generate→自評）具體形狀？rerank——原碼 **LLM-as-judge 逐筆打分**成本高，CRAG 的 grade 步是否取代它 / 或改 cross-encoder / 純向量分數？RAG 服務**呼叫 host Ollama 的接線**（k8s pod → `host.docker.internal:11434` 類，M4 原則的落地點——design 要畫清）？RAG 的**對外用途定義**（P4 展示什麼：「問這支影片觀眾在討論什麼」grounded 在真留言 / 「依爆紅內容生成標題建議」）？prompt 模板搬進版本管理（見 P2b-3）？

**P2b-3 LLMOps observability（原碼完全沒有——P2b 的差異化重點）**
- 補上原碼三大缺口的工程層：**prompt 版本管理**（MLflow Prompt Registry 或等價）、**評估閘**（檢索命中率 / 答案品質，離線 eval set）、**成本/延遲/token 監控**（進 Prometheus/Grafana）；**移除硬編碼 API key**（k8s Secret）。
- **開放問題**：prompt 版本用 MLflow（與 P2a 共用一個工具）還是輕量檔案版本？eval set 怎麼建（人工小集 + LLM-as-judge scoring，標註哪些指標）？成本/token 怎麼採集（在 RAG 服務內埋 middleware 記每次呼叫 token/耗時 → Prometheus counter/histogram）？eval 閘怎麼卡（新 prompt/新檢索設定要過離線 eval 才能上）？

**P2c-1 微調 A：留言情緒分類器（DistilBERT，必做）**
- **蒸餾 pattern**：用 LLM（Ollama 本地或 Gemini）幫**一小批**留言弱標註情緒（正/負/中）→ 微調 **DistilBertForSequenceClassification**（HuggingFace transformers Trainer）→ 全訓練/評估進 MLflow → 註冊晉升 → **KServe（CPU-feasible）serving** → 一支 batch task 對**全量留言打分**寫回一張表 → P4 儀表板「觀眾情緒」。展示「把貴又慢的 LLM 蒸餾成便宜快小模型」的真實產業 pattern。
- **算力**：DistilBERT 微調 CPU/MPS 可行（無需 GPU）；training 可原生跑 M4 或 k8s CPU Job（design 定，M4 原則傾向重的原生跑 host）。serving 走 KServe CPU（分類器夠輕）。
- **開放問題**：情緒 label 體系（3 類 vs 含「無關/廣告」多類）？弱標註規模（幾百/幾千則夠？標註 prompt）？如何驗證蒸餾品質（留一小份人工/LLM 標的 hold-out 當 test，報 accuracy/F1，對比「直接用 LLM 標全量」的成本/延遲差＝這條的賣點數字）？training 跑法（M4 原生 vs k8s CPU Job）？打分表 schema（`ml_comment_sentiment`：comment_id/video_id/label/score）？打分 batch 排程（留言 Silver 更新後）？

**P2c-2 微調 B：爆紅標題生成器（小 LLM LoRA，做）**
- **PEFT LoRA**：用 P1 Gold 的**真實爆紅影片標題**當語料（可搭配類別/關鍵字當條件）→ **PEFT LoRA（fp16，非 4-bit bitsandbytes）** 微調一個**小 LLM**（如 Qwen2/Llama-3.x 小尺寸、Phi）→ MLflow 追蹤 → 產出 adapter/合併模型（HF 標準格式，可攜）→ 提供「輸入主題→生成爆紅風格標題」的 demo。效果輸入→輸出直接可見。
- **算力**：**原生跑 M4**（HuggingFace PEFT on MPS，fp16 小模型免費、不需 GPU、不需 bitsandbytes）；產出模型上 MLflow/MinIO，**可攜雲端 GPU**（同套 code 換機器練更大）。serving——小 LLM 生成走 host Ollama（載入微調後的 GGUF）或 demo 用（P4 靜態產生範例，見拓撲約束）。
- **開放問題**：基座小模型選型（context7 查證當前可 LoRA 且 M4 記憶體吃得下的小模型；中文標題→需中文能力）？訓練資料構造（(主題/類別/關鍵字 → 標題) 的 instruction 格式；「爆紅」門檻＝取 Gold 高 velocity/high total_views_gained 的標題當正例）？LoRA 超參（r/alpha/target modules）交 design 給範圍？效果怎麼展示與評估（人工判讀 vs 對比 baseline 未微調模型的標題「爆紅感」；避免宣稱拿不出的量化戰績——標「可示範能力」而非「已驗證 CTR 提升」）？產出如何進 Ollama serving（LoRA merge → GGUF 匯出）？對 P4 是即時生成還是預先產範例（拓撲約束：Vercel 前端打不到 host Ollama → 傾向預先產範例匯出）？

**P2-X 對 P4 的輸出合約 + 可觀測性 + 驗收**（橫跨三條）
- 定義 **P2 三條的產出**要以什麼形狀給 P4 呈現層匯出：tabular = 對 Gold 影片的**預測分數表**（批次打分寫回 `ml_*` 表）；RAG = 可展示的問答/建議（預先產生範例）；**微調 A = 全量留言情緒打分表（`ml_comment_sentiment`）＋影片級情緒聚合；微調 B = 預先產生的爆紅標題範例集**。這是 P4「匯出資料檔」合約的 ML 半邊。
- ML 指標接 P0 Prometheus/Grafana（模型 serving QPS/延遲、drift 分數、RAG 成本/命中率）。
- **開放問題**：預測結果落地形狀（新增 `gold.ml_video_predictions` 表？由重訓後一支 batch-score task 寫入，P4 直接匯出它——最省且與「前端讀匯出檔」一致）？RAG 對 P4 是「前端即時呼叫 KServe/RAG API」還是「預先產生範例答案匯出成靜態檔」（平台不部署 → 前端在 Vercel 上**無法**即時打本地 k8s 服務！→ 傾向**預先批次產生 + 匯出靜態**，這對拓撲是硬約束，design 要正面處理）？

## 設計方向約束（硬性，寫進 design）
- **沿用 P0/P1 慣例**：服務進 `ml/`、kustomize `k8s/` + 子 Application、CI 複製既有模式、雲端可攜（無 storageClassName、ingress 抽換）。MLflow/DVC/KServe 的 store **複用 P1 Postgres+MinIO**，不新增。
- **一個工作一個工具**：排程只 Airflow、DB 只 Postgres（含 **pgvector**，已鎖定）、監控只 Prom+Grafana、物件儲存只 MinIO、模型追蹤只 MLflow（含 prompt 版本盡量收斂進 MLflow）。KServe 傾向 RawDeployment 免裝 service mesh。**agent 框架只 LangGraph、串流不進 P2（Kafka 是 P3）。**
- **🔒 M4 原生算力界線（硬性）**：kind 摸不到 Apple GPU → **微調（transformers/PEFT）、本地 LLM 推論（Ollama）、本地 embedding 批次原生跑 M4 host，不塞進 k8s pod 期待 GPU**。k8s 管編排/lakehouse/監控 + CPU serving（DistilBERT）。design 要標明每個重算力步「在 host 還在 k8s」、以及 k8s RAG 服務 → host Ollama 的接線方式。產出模型一律 HF 標準格式上 MLflow/MinIO（可攜雲端）。
- **消費 Gold 合約不繞道**：P2 讀 P1 Gold 5 表；缺欄走「對 Gold additive 加欄」並在 design 記錄（不改粒度/不刪欄）。
- **🔴 安全**：絕不沿用硬編碼 API key（原碼 `gemini_client.py:37`）；所有外部憑證走 k8s Secret（沿用 P1 §8 命令式 secret 姿態）。不 echo 任何 key。
- **拓撲硬約束**：**平台不部署、前端在 Vercel**（NORTH_STAR 呈現層段）→ 前端**無法**即時呼叫本地 k8s 的 KServe/RAG。P2 對 P4 的產出**必須能預先批次產生 + 匯出成靜態資料檔**；線上 serving（KServe/RAG API）是「本地 demo/截圖」用，不是 Vercel 前端的 runtime 依賴。design 要把這條界線畫清楚。
- **進化非複刻**：改進原碼的真實缺陷（無評估→真評估、無持久化→registry、空索引→真 ingest、無監控→LLMOps observability、靜態回歸→時序題）。README/design 誠實記錄取材 vs 重造的界線。
- **每步可測**：訓練有離線 eval、DVC 可重現、RAG 有 eval set、serving 有 smoke test。

## 交付與驗收（design 要回答的）
- 每簇開放問題**收斂成決定**或標「plan 前需實查」。（pgvector/本地 embedding/LangGraph/Ollama/HuggingFace/M4 原生 = **已鎖定不必再選**。）尤其拍板：**預測目標/label 定義**、**本地 embedding 模型與跑法（M4 原生批次 vs KServe）**、**LangGraph CRAG 圖節點結構**、**k8s RAG→host Ollama 接線**、**KServe RawDeployment vs Serverless**、**MLflow 是否兼任 prompt registry**、**duration 加欄 vs 丟棄**、**情緒 label 體系與弱標註規模**、**LoRA 基座小模型與超參**、**RAG/標題對 P4 靜態匯出 vs 線上呼叫**。
- 具體：特徵/label schema（欄位級）、訓練/漂移 DAG 結構、MLflow 實驗與 registry 佈局、KServe InferenceService manifest 形狀、向量庫 schema、RAG 服務 API 契約、LLMOps 指標清單、**對 P4 的匯出產出形狀**（`ml_*` 表 or 靜態檔）。
- 部署形狀：MLflow/KServe/向量庫/ML 服務在 k8s 怎麼裝、怎麼被 ArgoCD 管、sync-wave 接續 P1。
- 端到端驗收清單（接在 P1 之後：Gold 有資料 → 匯出訓練集 + DVC → 訓練 + MLflow 追蹤 → 晉升 → KServe 推論回應 → 批次打分寫 `ml_*` 表；RAG 索引真的進庫 → 檢索非空 → 生成 → eval 分數 → 成本指標可見）。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design。**本階段只出 spec，plan 延後**。對齊 NORTH_STAR P2 定義（含「LLM／微調層與留言語料」專章 + M4 原生原則）+ P0/P1 design 的平台/資料合約慣例。三條垂直共用 P2-0 底盤，design 可在一份文件內分 P2a/P2b/P2c 三大部；**若判定過大，建議拆兩份 sub-design：P2a+P2c-A（tabular + 分類器，皆走 MLflow→KServe 傳統 serving）與 P2b+P2c-B（LLMOps/RAG + LLM LoRA，皆走 LangGraph/Ollama/生成式）**——共用底盤 P2-0 只定義一次。
