# P6 進階召回 spec — brief（序列推薦 SASRec baseline + P5/T5 LLM 生成式主秀 ＋ FP-Growth 購物籃關聯；兩條新召回路接進現有 RRF+LTR）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，**開放問題一律收斂成決定、不下推**。
> **緣起（Fergus 2026-07-10 令）**：評估 8 門推薦/DMP 課後，Fergus 判「電商推薦比較有價值、有 user_id 串起來」，選定補兩個 spec 自標「進化方向未做」的真缺口：**①序列推薦（next-item，SASRec baseline + P5/T5 LLM 生成式主秀，Fergus 定案兩者都做）②FP-Growth 購物籃關聯召回（『買了X也買Y』）**。守 [[feedback_evolve_beyond_past_projects]]（參考是輸入非天花板）。
> **參考立場**：課程只參考做法——序列 P5/T5 範式取材「越賣越多的祕密」`src/basic_skills/train-llm/prompt.txt`＋`utils.py`（leave-one-out、`item_<id>` token 受限＝結構性防幻覺）；FP-Growth 取材「Spark 企业级个性化推荐系统」`videoCode/Chapter_12/FP-Growth`。**碼不照抄、憑證勿引；重型 infra（Hive/HBase/Spark 常駐叢集）全拒**。

---

## 框架上游（binding，不得抵觸）

- **[P6 推薦 design](2026-07-09-P6-recommendation-design.md)**（主複用對象，**唯讀、只 additive 疊加**）：§4 召回三路（item2vec CF §4.1／pgvector 語意 §4.2／熱門 §4.3）、§4.5 候選融合（`ml.reco_candidates` 表，`source CHECK IN ('i2v','sem','pop')`、線上 RRF k=60 → 候選池 ≤200 → LTR）、§5.1 `RECO_FEATURE_SCHEMA v1`（22 欄，含 `recall_src` i2v=0/sem=1/pop=2）、§5.3 `LGBMRanker` lambdarank＋registered model `reco-ranker`＋評估 ndcg@10/hit@10/recall@10,50/MAP@10、§5.2 訓練資料時間切分（特徵窗 ≤2021-01-03／label 窗 01-04~17／test 01-18~31 防洩漏）、DVC `ml/reco/dvc.yaml`（export→train_i2v→embed_semantic→build_candidates→build_ltr_dataset→train_ranker→evaluate）、DAG `reco_build_artifacts`/`reco_retrain`/`reco_ab_replay`（schedule=None）、匯出 `reco_similar/popular/segments/eval.json`＋前端 `/reco` 頁。**本 spec 是這條管線的 additive 擴充：加兩條召回路（`source` 值 additive）、加對應模型與表、餵進同一 RRF+LTR、同一評估/匯出框架——不改既有三路、不改 LTR 合約語意、不改既有表粒度。**
- **[P6 GA4 地基 design](2026-07-09-P6-ga4-ingestion-foundation-design.md)**（資料源，唯讀）：**序列源＝`silver.ga4_events`**（§4，粒度 `(user_pseudo_id, event_ts_micros, event_name, item_id)`，含 `ga_session_id`／`event_ts_micros`／`item_id`／`transaction_id`）——item2vec §4.1 已用「按 `(user_pseudo_id, ga_session_id)` 分組、`event_ts_micros` 排序的 item_id 序列」，**序列推薦用同一份序列**；**購物籃源＝`transaction_id` 非空的 purchase 事件**（§4:212 `transaction_id` 僅 purchase 有值）分組成一籃；`gold_ga4_item_catalog`（§5.2，item_id 值域＝P5/T5 的 item token 詞表源、FP-Growth 的 item 全集）。
- **[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)**（微調基建，唯讀複用）：§12 HuggingFace 微調棧（PEFT LoRA fp16、M4 原生 MPS、產出上 MLflow registry 可攜）＝**P5/T5 微調的基建範本**；§1④ 重算力 M4/k8s CPU 分工判準（gensim/小模型 CPU、微調 M4 host）；MLflow registry alias @staging/@prod＋晉升閘（P6 §5.3 同款）。
- **NORTH_STAR**：一工一具（向量檢索只 pgvector 不引 Faiss、agent 框架只 LangGraph、微調只 HuggingFace）、M4 原生算力原則、拓撲鐵律（前端純靜態讀匯出 JSON、真運算叢集/離線）、成本紅線不適用（跑 infra 是目的，但 M4/CPU 友善、不假設 GPU）。

## 接地鐵律（grounding-first，違者作廢）

Fable 5 須**第一手 grep/讀**：
- **P6 §4.5 `ml.reco_candidates` DDL 與 `source` CHECK**、§5.1 `RECO_FEATURE_SCHEMA v1` 22 欄（尤其 `recall_src`）、§5.2 時間切分窗、§5.3 `reco-ranker` 晉升閘、§4.1 item2vec 的 session 序列建構法（序列推薦要**沿用同一序列定義**避免兩套語料）——證明「加召回路 additive、不動 LTR 合約」可行，錨進 design。**P6 尚無實碼（`ml/` 空）**→鎖 P6 design 合約，同問 AI §0.3 誠實處理。
- **`silver.ga4_events` 序列/購物籃可行性**：確認 session 序列長度分佈（≥2 才可訓 next-item）、`transaction_id` 非空率與每籃 item 數分佈（FP-Growth 要多 item 籃才有關聯）——地基 §4 欄位級合約 + §12B 缺席率實查點。
- **課程取材**（唯讀、碼不照抄）：「越賣越多」`src/basic_skills/train-llm/prompt.txt`（22 條 P5 模板 `sequential; seen; …has interacted with items {history}. What is the next recommendation?; {target}`）＋`utils.py:60-87 load_prompt_template`／`:269-311` leave-one-out（`history=items[:-1]`, `target=items[-1]`）／`:233-266` hit@k/ndcg；「Spark 企业级」`videoCode/Chapter_12/{FP-Growth,Apriori}`（關聯規則 support/confidence/lift）。
- **版本敏感處**（HuggingFace T5/SASRec 實作庫、mlxtend/pyfpgrowth vs Spark FP-Growth、sentence-transformers）用 context7。
**本階段只出 spec，plan 延後。**

---

## 一句話目標

P6 進階召回＝在現有三路召回（item2vec/語意/熱門）＋RRF＋LTR 管線上，**additive 加兩條電商核心召回路**：**①序列推薦**（next-item，**SASRec baseline ＋ P5/T5 LLM 生成式主秀**兩模型並訓對比，輸出下一步候選，P5/T5 輸出限定 `item_<id>` token＝結構性防幻覺）＋**②FP-Growth 購物籃關聯**（`transaction_id` 組籃 → 頻繁項集/關聯規則 → 『買了X也買Y』候選）。兩路產出寫進 `ml.reco_candidates`（`source` 值 additive）→ 同一 RLF k=60 融合 → 同一 LTR 排序 → 同一評估/匯出/前端框架。把電商推薦故事補成「CF＋語意＋熱門＋**購物籃**＋**序列**」完整召回層，並秀「LLM 生成式序列 vs 經典 SASRec」對比＝資深 MLOps/LLMOps 敘事。

## 為什麼 grounded 而非畫大餅（複用邊界＝本 spec 的靈魂）

序列源、購物籃源、item 詞表、微調基建、召回融合框架、LTR、評估、匯出**全部現成**：序列＝item2vec 已用的同一份 `silver.ga4_events` session 序列；購物籃＝`transaction_id` 分組；P5/T5 微調＝P2 §12 HuggingFace/LoRA/M4 基建；候選/融合/排序/評估/匯出＝P6 既有管線加 `source` 值。**本 spec 不重造任何一個**——加兩個模型/一個關聯規則表、把輸出接進既有 RRF+LTR。這就是進化非複刻：把「進化方向未做」的序列與購物籃補成實作，且用 item-token 受限的 P5/T5 把 LLM 生成式推薦做得結構性防幻覺（呼應我方 grounding 執念）。

## Fable 5 要收斂拍板的項目（逐一給明確決定，不下推）

1. **序列資料構造（防洩漏，沿 P6 §5.2 窗）**：session 序列從 `silver.ga4_events` 按 `(user_pseudo_id, ga_session_id)` `event_ts_micros` 排序取 `item_id`（**沿用 item2vec §4.1 同一序列定義**，null session fallback `(user, event_date)`，連續重複壓一次，長度 ≥2）；leave-one-out 訓練（`history=seq[:-1]`, `target=seq[-1]`）；**train/test 時間切分對齊 P6 §5.2**（特徵窗訓、label/test 窗評，避免與 LTR 評估洩漏）。拍板序列最大長度、padding、item 詞表（catalog item_id 全集，OOV 處理）。
2. **SASRec baseline（經典序列，PyTorch）**：拍板架構（self-attention sequential，embedding dim 對齊生態、層數/head、causal mask）、實作庫（context7 查——自寫 ~200 行 vs 成熟庫如 RecBole/自寫；守「不重造又不硬塞」[[feedback_use_validated_libraries]]）、M4 host 訓練（PyTorch MPS）、MLflow registry `reco-sasrec`、輸出 = 每 user/session 的 next-item top-N 候選。
3. **P5/T5 LLM 生成式主秀（HuggingFace 微調，item-token 受限）**：拍板基座（T5-small 沿課程 vs 我方 P2 Qwen 系列——T5 較輕且課程範式直接，context7 查 seq2seq 微調現況）、**item tokenization 方案**（`item_<id>` 加進 tokenizer 特殊 token vs sentinel 映射——決定詞表大小與 OOV）、prompt 模板（取材 `prompt.txt` 的 sequential 模板改我方語境）、LoRA 微調（沿 P2 §12 fp16 M4）、**受限解碼＝結構性防幻覺**（beam/constrained decoding 只允許生成合法 `item_<id>` token；生成後**驗證 item_id ∈ catalog**，非法丟棄並記錄——呼應 ask-ai 反幻覺紀律，明標「輸出限定 item 空間 ≠ 自由生成 SKU」）、MLflow registry `reco-p5t5`、輸出 = next-item top-N。
4. **兩序列模型的定位與對比（Fergus 定案兩者都做）**：**P5/T5＝主秀召回路**（進 `ml.reco_candidates` source='seq'）、**SASRec＝對照 baseline**（同離線評估 hit@k/ndcg@k 並列，秀「LLM 生成式 vs 經典序列」）。拍板：兩者都進候選還是只 winner 進 production 召回（傾向 winner 進、另一個留評估對比＋前端敘事）；評估口徑統一（sequential next-item 的 hit@10/ndcg@10 對 held-out 末筆）。
5. **FP-Growth 購物籃關聯召回**：拍板籃定義（`transaction_id` 分組的 purchase item 集 vs session 內共現——傾向 transaction_id 真購物籃）、演算法與庫（context7 查 mlxtend vs Spark FP-Growth vs pyfpgrowth——守輕量，傾向 mlxtend/純 Python on k8s CPU，不引 Spark 常駐）、參數（min_support/min_confidence/lift 門檻，實跑校準）、輸出表 `ml.reco_fbt_rules(antecedent_item text, consequent_item text, support/confidence/lift double, …)` 或直接寫 `ml.reco_candidates` source='fbt'（拍板落法）、seed 語意（user 近期購買/加購 item → 關聯 item 候選）。
6. **接進 RRF+LTR（additive，不改 LTR 合約）**：`ml.reco_candidates.source` CHECK **additive 加 'seq'/'fbt'**（改 CHECK 約束＝需確認是 additive 擴列舉非破壞——拍板落法，可能新表或 CHECK 擴充）；`RECO_FEATURE_SCHEMA` 的 `recall_src` additive 加值（seq=3/fbt=4）＋**是否加新交互特徵**（如 `seq_rank`/`fbt_lift`/`fbt_confidence` 當 LTR 特徵——若加＝schema v1→v2 additive 加欄，序列化 `feature_schema.json` 版本升、serving 斷言相容）；RRF k=60 天然吸納新召回路（多一路 rank 融合，零改融合邏輯）。**明標不改**：既有三路、LTR objective、既有 22 欄語意。
7. **評估/A-B/消融（additive，沿 P6 §5.3/§5.6）**：序列模型 next-item 評估（hit@10/ndcg@10 held-out 末筆）＋FP-Growth 召回貢獻；**召回消融**（有/無 seq、有/無 fbt 對最終 LTR ndcg@10 的增益＝「每條召回路值多少」的誠實展示）；寫 `ml.reco_eval_metrics`（additive variant）；event-replay A/B additive 對照（完整管線 vs 無新召回路）。誠實標：序列/FP-Growth 在 GA4 sample（92 日、購物籃量級）的資料侷限。
8. **資料流/服務/匯出/守門（全 additive）**：DVC `dvc.yaml` additive 加 stage（`train_sasrec`/`finetune_p5t5`/`build_fbt_rules`/`build_seq_candidates`）；DAG additive（併入 `reco_build_artifacts`/`reco_retrain`）；**服務落法拍板**（序列候選批次預產進 `reco_candidates`＋匯出，同 reason 批次範式 vs 線上 KServe——傾向批次預產守拓撲鐵律，P5/T5 推論 M4 host 批次）；前端 `/reco` additive 加區塊（「下一步推薦」序列＋「一起買」購物籃，含說明式 registry `whyBuilt`/`whatItDoes` 阻擋級、LLM生成式 vs 經典對比敘事、emoji→lucide）；匯出 dataset additive（`reco_sequential.json`/`reco_fbt.json` 或併入既有）；MCP additive；CI（模型測試 fake 注入、item-token 合法性斷言、FP-Growth 純函式測、schema 相容測）。**逐一標不改哪些既有資產**。

## 硬約束（違者作廢）

- **only-additive**：不改 P6 既有三路召回、`reco-ranker` LTR objective、既有 22 欄特徵語意、既有表粒度、既有 DAG/dvc stage 語意；新召回路以 `source` additive 值、新模型/表/stage net-new、feature schema 加欄升版（序列化相容）落地。
- **P5/T5 反幻覺（結構性）**：輸出限定 `item_<id>` token 空間 + 生成後驗證 `item_id ∈ gold_ga4_item_catalog`，非法丟棄並記錄——**明標「限定 item 空間的生成 ≠ 自由生成 SKU」**，這是接受 LLM 生成式推薦的前提（自由生成任意 SKU 的做法明拒，呼應 [[ask-ai check_numbers]] 紀律）。
- **一工一具／M4 原則**：向量仍 pgvector（不引 Faiss）、微調仍 HuggingFace、序列 SASRec 用 PyTorch MPS/M4、FP-Growth 用輕量 Python on k8s CPU（**不引 Spark 常駐叢集**——課程的 Spark FP-Growth 是重型反例）；重算力 M4 host、CPU-feasible 上 k8s。
- **拓撲鐵律**：真運算（訓練/推論/FP-Growth）叢集或 M4 host；前端純靜態讀匯出 JSON、零 live 依賴；線上 reco-service 僅叢集內 demo/負載測試佐證。
- **grounding/誠實**：**不造假互動/不合成使用者**（課程「LLM 生成虛擬行為補冷啟」明拒——違 grounding，同我方一貫紀律）；序列/FP-Growth 的 GA4 sample 資料侷限誠實標；召回消融如實報每路增益（某路無效也如實）；SASRec vs P5/T5 對比不預設贏家、實測填數。**說明式 registry 阻擋級**；emoji→lucide。
- **成本紅線不適用**（portfolio 跑 infra 是目的）——但 M4/CPU 友善、不假設 GPU（T5-small/SASRec 小模型 M4 可訓）。

## context7 必查清單

- **SASRec 實作**（自寫 self-attention sequential vs RecBole；PyTorch MPS 相容）。
- **T5/seq2seq 推薦微調**（HuggingFace T5-small + PEFT LoRA、特殊 token 加入 tokenizer、**constrained/prefix beam decoding 限定 token 集**的現況 API）。
- **FP-Growth**（mlxtend `fpgrowth`/`association_rules` vs pyfpgrowth；輕量 Python，避 Spark）。
- **推薦序列評估**（leave-one-out next-item 的 hit@k/ndcg@k 標準做法）。

## Scope

- **in**：序列資料構造、SASRec baseline、P5/T5 LLM 生成式主秀（item-token 受限+反幻覺驗證）、兩序列模型定位對比、FP-Growth 購物籃召回、接進 RRF+LTR（additive source/feature）、評估/A-B/消融、資料流/服務/匯出/前端/守門 additive。
- **out**：改 P6 既有三路/LTR objective/表粒度、引 Spark 常駐/Faiss/第二 agent 框架、LLM 自由生成任意 SKU、造假互動補冷啟、two-tower/GNN/多目標排序/MMR 重排（不同 gap，本 spec 不含——列進化方向即可）、改 Signal token/前端 live 依賴。

## 產出

寫到 `docs/specs/2026-07-10-p6-advanced-recall-design.md`；檔頭指向本 brief＋精確度契約＋P6 推薦/地基 design＋P2。附「plan 期待查證點」（P6 實作 import 錨、序列/購物籃資料實測分佈、P5/T5 item-token 詞表大小、FP-Growth 參數校準、SASRec 庫選型實裝）與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項（尤其 P6 reco_candidates/feature schema 合約錨、silver.ga4_events 序列/transaction_id 可行性、P5/T5 constrained decoding、FP-Growth 庫）、給 Opus 覆核的風險點（尤其：additive 有無誤改 LTR/召回合約、P5/T5 反幻覺是否真做到 item 空間受限+驗證、有無引 Spark 常駐、有無造假資料、序列與 item2vec 是否共用同一序列定義）。
