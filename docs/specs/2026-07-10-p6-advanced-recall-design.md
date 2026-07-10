# P6 進階召回（序列推薦 SASRec baseline ＋ P5/T5 LLM 生成式主秀 ＋ FP-Growth 購物籃）— Design（Fable 5 產出）

> **狀態**：design 完成，待規劃者把關後寫 implementation plan。
> **上游**：[`2026-07-10-p6-advanced-recall-brief.md`](2026-07-10-p6-advanced-recall-brief.md)（工作合約正本）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §15）＋ **[P6 推薦 design](2026-07-09-P6-recommendation-design.md)（主複用對象，唯讀、only-additive）**：§4.1 item2vec 序列定義／§4.5 `ml.reco_candidates`＋RRF／§5.1 `RECO_FEATURE_SCHEMA v1` 22 欄／§5.2 時間切分／§5.3 晉升閘／§6 Redis 接縫 A／§10 DAG／§11 匯出＋`/reco` 頁 ＋ **[P6 GA4 地基 design](2026-07-09-P6-ga4-ingestion-foundation-design.md)**（§4 `silver.ga4_events` 穩定合約／§5.2 `gold_ga4_item_catalog`）＋ **[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)**（§0 pin 表／§1④ M4 界線／§12 HuggingFace 微調基建範本）＋ [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md) §5（說明式 registry 阻擋級）＋ NORTH_STAR（一工一具／M4 原則／拓撲鐵律）。
> **定位**：在 P6 既有三路召回（item2vec／語意／熱門）＋RRF＋LTR 管線上 **additive 加兩條電商核心召回路**：①序列 next-item（SASRec baseline ＋ P5/T5 生成式主秀，兩模型並訓對比，P5/T5 輸出限定 `item_<id>` token＝結構性防幻覺）②FP-Growth 購物籃「買了X也買Y」。產出接進同一 RRF+LTR+評估+匯出框架。**不改既有三路、不改 LTR objective、不改 22 欄語意、不改既有表粒度。**
> **版本查證日**：2026-07-10（mlxtend/RecBole 對 PyPI 當日查證；transformers `prefix_allowed_tokens_fn`／PEFT `trainable_token_indices`／mlxtend `fpgrowth`+`association_rules`／RecBole SASRec 評估慣例對 context7 官方文件查證；torch/transformers/PEFT 沿 P2 §0 已查證 pin）。

---

## 0. 版本 pin 表 ＋ 接地現況

### 0.1 接地現況誠實記錄（同問 AI design §0.3 姿態——本 spec 的錨是「design 合約」非實碼）

- **P6 推薦垂直今日無實碼**（`ml/` 空、`docs/plans/` 無 P6 plan）：本 spec 引用的 `ml.reco_candidates` DDL、`RECO_FEATURE_SCHEMA v1`、`sequences.py`、Redis schema **全部是 P6 design 的合約錨**（各節逐一標出處），不是可 grep 的實碼。裁定：**本 spec 的 plan 排在 P6 推薦 plan 之後（或同一 plan 批次的後段 task）**；plan 期實查點 #1＝P6 落地後核對實際模組路徑與 DDL（§13）。
- **`silver.ga4_events` 尚未回放落地、本機 `bq` 未授權**（2026-07-10 實測 `bq query` 回 no active account）：序列長度分佈／`transaction_id` 籃分佈**今日無法第一手量測**——不編數字，全部列 §13 plan 前實查（帶預設傾向與降級判準）。schema 面可鎖：地基 §4 欄位級合約明載 `ga_session_id`（nullable）／`event_ts_micros`（PK 成分）／`transaction_id`（僅 purchase 有值），序列與購物籃**結構上可行**。
- 課程素材第一手讀畢：「越賣越多」`prompt.txt` 22 條模板（sequential 10 seen＋1 unseen）＋`utils.py`（`load_prompt_template :60-87`／leave-one-out `load_test :269-289`（`history=items[:-1]`,`target='item_'+items[-1]`）／`ndcg_at_k :233-244`（leave-one-out 單 ground truth IDCG=1）／`hit_at_k :247-253`）；「Spark 企业级」`Chapter_12/FP-Growth/src/main/scala/com/imooc/FPGrowth.scala`（Spark `ml.fpm.FPGrowth` `setMinSupport(0.5)/setMinConfidence(0.6)`）。取材界線見 §11。

### 0.2 版本 pin

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| mlxtend | **0.25.0** | PyPI（2026-07-10）；`fpgrowth(df, min_support, use_colnames, max_len)`＋`association_rules(fi, metric, min_threshold, num_itemsets=…)` API 面 context7 查證（`num_itemsets` 是現行必帶參數） | **本 spec 唯一新 pin**；進 ml-batch image |
| torch | 2.12.1（MPS） | 沿 P2 §0 | SASRec 自寫模型的唯一依賴 |
| transformers / PEFT | 5.13.0 / 0.19.1 | 沿 P2 §0；`generate(prefix_allowed_tokens_fn=Callable[[int, torch.Tensor], list[int]])` 與 PEFT `trainable_token_indices`（新增 token 只訓新 embedding 列）context7 查證 | P5/T5 微調＋受限解碼 |
| datasets / accelerate | 5.0.0 / 1.14.0 | 沿 P2 §0 | — |
| T5 基座 | `google-t5/t5-small`（60M，encoder-decoder） | HF Hub 長青模型；transformers 5.x 原生支援 | 選型論證 §5 |
| lightgbm / gensim / redis-py / KServe / MLflow / pgvector | 沿 P6 推薦 design §0 | — | 零升級 |

**刻意不引入**：**RecBole**（1.2.1，PyPI 最後 release 2025-02-24——落後 P2 pin 的 torch 2.12 一年半；且其資料層（atomic files＋框架內綁定的 LS split）與我方 §5.2 時間窗＋「兩模型同一 held-out」協定衝突，為一個 ~200 行模型拖整框架還要對抗它的切分機制——判定見 §4）；**Spark FP-Growth**（課程載體，常駐叢集明拒——mlxtend 純 Python 對數千~萬級籃綽綽有餘）；**Faiss**（向量檢索仍 pgvector，本 spec 甚至不新增向量表）；**TRL**（P2 §12 用它是 causal chat 場景；T5 seq2seq 用 transformers 原生 `Seq2SeqTrainer`，不硬搬）；**pyfpgrowth**（無 association_rules 指標面、維護停滯，mlxtend 一站含頻繁項集＋規則指標）。

---

## 1. 開放問題收斂總表（brief 8 項全拍板，禁 TBD）

| # | 題 | 決定 |
|---|---|---|
| 1 | 序列資料構造 | **與 item2vec 共用同一序列定義**（P6 §4.1 逐字沿用，單一真源 `sequences.py`）；leave-one-out 訓練樣本；eval/full 雙 artifact 對齊 §5.2 時間窗；max_len=20、單一詞表=catalog 全集、OOV 誠實計分母。細節 §3。 |
| 2 | SASRec | **自寫 PyTorch（~200 行）**，淘汰 RecBole（§0.2/§4）；d=64、2 層 2 head、CE full-softmax；M4 host（MPS）訓練；MLflow `reco-sasrec`。 |
| 3 | P5/T5 | 基座 **t5-small**（淘汰 Qwen3.5-2B，§5）；**一 item 一 special token `item_<id>`**（淘汰 SentencePiece 自然拆分——那才是幻覺面）；LoRA（q/v）＋`trainable_token_indices` 訓新 token embedding；**受限解碼三層**（單步 logits 排名／`prefix_allowed_tokens_fn`／生成後驗證 ∈ catalog）；MLflow `reco-p5t5`。 |
| 4 | 兩模型定位 | **同一 held-out、同一詞表、full-ranking 同口徑對比**；**production seq 召回路只開一個模型**（`params.yaml seq_candidate_model`，預設傾向 p5t5＝主秀；由晉升閘實測定奪，**不預設贏家**）；落選者留評估對比＋前端敘事。閘含「必須贏 last-item i2v」——序列建模無增益則 seq 路誠實不開。§6。 |
| 5 | FP-Growth | 籃＝**`transaction_id` 分組的 purchase item 集**（淘汰 session 共現——與 i2v 路重複且非「買了」語意）；mlxtend 0.25.0、`max_len=2`（規則恆 1→1）；新表 `ml.reco_fbt_rules` 為規則正本＋同步寫 `ml.reco_candidates source='fbt'`（兩者都要：規則表供特徵/前端稽核，candidates 供融合）。§7。 |
| 6 | 接進 RRF+LTR | `source` CHECK **擴列舉** `('i2v','sem','pop','seq','fbt')`、`seed_type` 擴 `+'user'`（純列舉放寬＝非破壞 additive）；`recall_src` additive seq=3／fbt=4（「取最小」語意不變）；**RECO_FEATURE_SCHEMA v1→v2：尾端 append 3 欄**（`seq_rrf`/`fbt_confidence`/`fbt_lift`），`feature_schema.json` version bump、serving 既有 fail-fast 斷言天然守門；RRF 融合零改碼。§8。 |
| 7 | 評估/A-B/消融 | seq 頭對頭（hit@10/ndcg@10，test 窗 leave-one-out，附 pop＋last-item-i2v 兩 baseline）；**召回消融＝4 組候選配置各自重訓 LTR** 比 test ndcg@10（誠實報每路增益，負增益也如實）；A/B replay additive 一輪 `full(5路)` vs `base3(3路，同一 v2 ranker)`；全部寫既有 `ml.reco_eval_metrics`（additive variant，零改表）。§9。 |
| 8 | 資料流/服務/匯出/前端/守門 | DVC +6 stage；DAG additive（`build_fbt_rules` 進 `reco_build_artifacts`；host 工序進 M4 界線帳）；**服務＝批次預產進 `reco_candidates`＋Redis `cand:seq:*`/`cand:fbt:*`**（守拓撲鐵律；無線上 T5 端點，SASRec KServe 列進化方向）；匯出 +2 檔；`/reco` 頁 +3 區塊（crosscut registry 阻擋級、lucide 不 emoji）；MCP +2 工具；CI/測試 §12。 |

---

## 2. 總體形狀

### 資料流（additive 疊加在 P6 §2 之上；標 ★ 的是本 spec 新增）

```
silver.ga4_events ──(既有)── sequences.py session 序列（單一真源，item2vec 已用）
        │                        │
        │                 ★ leave-one-out 樣本構造（eval/full 雙窗）
        │                        ├─★ train_sasrec（M4 host，MPS）──→ MLflow reco-sasrec
        │                        └─★ finetune_p5t5（M4 host，LoRA+item tokens）→ MLflow reco-p5t5
        │                              │ ★ build_seq_candidates（host 批次推論，受限解碼）
        │                              ▼
        ├─(purchase, transaction_id)─★ build_fbt_rules（k8s KPO，mlxtend）→ ml.reco_fbt_rules
        │                              │
        ▼                              ▼
ml.reco_candidates（source additive +'seq'/'fbt'）──→ redis_load（★ +cand:seq:*/cand:fbt:*）
        │
reco-service RecallRouter（★ fan-out 兩鍵；RRF k=60 零改碼）→ FeatureAssembler（★ v2 +3 欄）
        │                                                        → KServe reco-ranker（v2 重訓，objective 不變）
        ▼
★ evaluate_seq / evaluate_ablation → ml.reco_eval_metrics（additive variant）
        ▼
P4 匯出 additive ＋2 檔（reco_sequential.json / reco_fbt.json）→ /reco 頁 +3 區塊 ＋ MCP +2 工具
```

### 新增檔案佈局（全 additive 進 P6 §2 佈局；未列 = 不動）

```
ml/reco/offline/src/ml_reco/
├── seq_dataset.py        # ★ session 序列 → leave-one-out 樣本 + 詞表（吃 sequences.py，不另建序列定義）
├── sasrec.py             # ★ 自寫 SASRec 模型 + 訓練 entrypoint（torch，MPS/CPU 自動）
├── p5t5.py               # ★ T5 item-token 微調 + 受限解碼推論 entrypoint（transformers/PEFT）
├── fbt.py                # ★ transaction 籃構造 + mlxtend FP-Growth + 規則落表 + candidates 寫入
├── seq_candidates.py     # ★ production seq model 批次推論 → ml.reco_candidates（source='seq'）
└── evaluate_seq.py       # ★ 序列頭對頭 + 召回消融（複用 evaluate.py 的 k 級集合運算）
ml/reco/offline/params.yaml   # additive `seq:` / `fbt:` 區塊（§3/§5/§7 超參單一真源）
ml/reco/offline/dvc.yaml      # additive +6 stage（§10）
orchestration/airflow/dags/reco_build_artifacts.py   # additive +1 task（build_fbt_rules）
orchestration/exporter/src/exporter/datasets.py      # additive +2 dataset 條目
frontend/src/app/reco/page.tsx                        # additive +3 區塊（registry 條目同步更新）
mcp-server/server.py                                  # additive +2 工具
Makefile += train-sasrec / finetune-p5t5 / seq-candidates / fbt-rules（host/dev 便捷面）
```

### M4 host ↔ k8s 界線帳（additive 進 P2 §1④ 總表）

| 工作 | 執行處 | 理由 |
|---|---|---|
| SASRec 訓練 | **M4 host**（MPS；dvc stage） | 重算力歸 host（分鐘級，torch MPS）；k8s CPU 同 entrypoint 可跑（模型小）——歸 host 因與 p5t5 同一條 dvc 鏈 |
| P5/T5 LoRA 微調 | **M4 host**（MPS，bf16） | 微調原生跑 host（P2 原則核心） |
| P5/T5 批次推論（全量 user 候選） | **M4 host**（`make seq-candidates`） | 60M encoder-decoder × 十萬級 user——MPS 批次；host→PG 走既有 `make pg-tunnel` |
| FP-Growth 規則挖掘 | **k8s KPO**（ml-batch image，CPU） | 純 Python 秒~分鐘級，排程紀律不破口 |
| 序列/消融評估 | **k8s KPO** ＋ host `dvc repro` 同 entrypoint | CPU-feasible |

---

## 3. 序列資料構造（拍板 1；防洩漏對齊 P6 §5.2）

| 項目 | 決定 |
|---|---|
| 序列定義（單一真源） | **逐字沿用 P6 §4.1 item2vec 語料定義，同一個 `sequences.py` 函式**：`silver.ga4_events` 按 `(user_pseudo_id, ga_session_id)` 分組、`event_ts_micros` 排序取 `item_id`；`ga_session_id` null → fallback `(user_pseudo_id, event_date)`；同 item 連續重複壓一次；長度 ≥2 才入。`seq_dataset.py` **只允許 import `sequences.build_session_sequences()`，禁止第二份序列構造實作**（CI 守門測試斷言兩消費者對同 fixture 產出逐 token 相等，§12）。 |
| 時間窗（雙 artifact，鏡像 i2v eval/full） | **`eval`**＝session 全部事件 `event_date ≤ 2021-01-03`（P6 特徵窗）——供 LTR 訓練集的 seq 候選（label 窗 01-04~17 的 grade 對模型不可見＝防洩漏）與 §9 頭對頭評估的訓練面；**`full`**＝全 92 天——供 serving 候選/Redis/匯出。**`test`**＝session 全部事件落在 01-18~01-31（P6 test label 窗）——只當 held-out 評估集，不入任何訓練。跨窗 session（事件橫跨邊界）按「session 最後事件日」歸窗，歸 test 窗者不入 eval/full 訓練樣本（full 的展示候選不受影響——它服務展示非評估）。 |
| 訓練樣本 | SASRec＝autoregressive 全位置 next-item（causal mask 一次訓整條序列，標準做法）；P5/T5＝**leave-one-out**（`history=seq[:-1]`, `target=seq[-1]`，課程 `utils.py:269-289` 同式）。驗證集＝訓練窗 sessions 決定性抽 10%（`crc32(user_pseudo_id + ':' + session_key) % 10 == 0`）做 leave-one-out early-stopping／model selection。 |
| max_len / padding | **max_len=20**（history 取尾 20；GA4 session 天然短，P99 分佈 §13 實查——若 P99 > 20 調 params 不改碼）。SASRec left-pad（PAD id=0）；P5/T5 history token 串 max 20 個 item token（prompt 總長 <64 token，`max_length=64` 截尾）。 |
| 詞表 / OOV | **單一詞表＝`gold_ga4_item_catalog` item_id 全集**（決定性排序 by item_id；存 `item_vocab.json` 隨兩模型 artifact 進 MLflow，SASRec id 映射與 P5/T5 special token 同源）。訓練窗未出現的 item：token/embedding 存在但未訓——如實標模型侷限。test 目標為訓練窗未見 item → **樣本保留、記為結構性 miss**（計入分母不剔除——「模型不可能命中的樣本」也是誠實分數的一部分；剔除率寫 eval metadata）。history 中 OOV（理論不發生——詞表=全集）防衛映射 `<unk>`。 |
| 不做的 | **不合成使用者、不用 LLM 生成虛擬互動補冷啟/補短序列（明拒**，課程若干做法違 grounding）；不建第二種「user 級跨 session」訓練語料（會產生第二序列定義，違單一真源——跨 session 建模列進化方向）。 |

`params.yaml` additive：`seq: {max_len: 20, val_holdout_pct: 10, min_seq_len: 2}`。

---

## 4. SASRec baseline（拍板 2；自寫 PyTorch）

**選型判定（context7＋PyPI 查證）**：

| 候選 | 判定 |
|---|---|
| **自寫 PyTorch ~200 行** ✅ | ①評估協定必須「SASRec 與 P5/T5 同一 held-out、同一詞表、full-ranking」——RecBole 的切分（`eval_args split LS` leave-one-out）綁在框架資料層（atomic files），與我方 §3 時間窗＋自訂樣本對齊要繞過框架；②P6 已有「自寫 evaluate ~60 行不拖評估框架」先例（§5.3），同一右尺寸判斷；③RecBole 1.2.1 為 2025-02 舊 release（PyPI 查證），對 torch 2.12/新 numpy 的相容是額外風險面。**自寫的只是模型定義**（Kang & McAuley 2018 標準架構，課程級教材皆有）——torch 本身是 validated library，不是造輪子；「不重造又不硬塞」的正確落點。 |
| RecBole | 淘汰（上列①③；為一個 baseline 模型拖整框架＝硬塞）。但**沿用其公開慣例當超參錨**：`MAX_ITEM_LIST_LENGTH`、`embedding_size: 64`、CE loss（`train_neg_sample_args: ~` 全 softmax 不抽負樣本）、`valid_metric: NDCG@10`（context7 對 RecBole sequential 官方 config 查證）——「架構與口徑照業界基準，載體自持」。 |

**架構與訓練（超參進 params.yaml `seq.sasrec:`）**：item embedding 64（與 i2v 64 同量級，非共享權重）＋可學位置嵌入（max_len 20）；`nn.TransformerEncoder` 2 層、2 heads、d_ff 256、dropout 0.2、**causal mask**；輸出層與 item embedding tied（標準 SASRec）；loss＝CE over 全詞表 softmax（詞表數千，free）；AdamW lr 1e-3、batch 256、epochs ≤200、early-stop 驗證 hit@10 patience 10、seed 42。device 判斷 `mps → cuda → cpu`。訓練 M4 host（`make train-sasrec`＝dvc stage `train_sasrec`），分鐘級。

**MLflow**：experiment `reco_seq`、registered model **`reco-sasrec`**、artifacts＝`model.pt`＋`item_vocab.json`＋超參＋驗證曲線。晉升閘見 §6。**輸出**＝依 §6 params 決定是否當 production seq 路；未當選時只出評估數字（不寫 candidates）。

---

## 5. P5/T5 LLM 生成式主秀（拍板 3；item-token 受限＝結構性防幻覺）

### 5.1 基座與微調

| 項目 | 決定 |
|---|---|
| 基座 | **`google-t5/t5-small`（60M）**。淘汰 P2 的 Qwen3.5-2B：P5 範式是 **seq2seq 原生**（課程直系：encoder 吃 prompt、decoder 出 item token），causal 2B 對「單 token 目標生成」是 ~30 倍算力零敘事增益；t5-small M4 分鐘~小時級、受限解碼在 decoder 首步天然乾淨。誠實註記：t5-small 是英文預訓練——prompt 模板本就是英文（課程模板），item token 是全新 token 無語言負擔；「LLM 生成式推薦」的敘事主體是**範式（P5）＋受限解碼**，不是模型尺寸。 |
| item tokenization | **一 item 一 special token `item_<item_id>`**（如 `item_GGOEGAAX0037`；`tokenizer.add_special_tokens({'additional_special_tokens': […]})` → `model.resize_token_embeddings(len(tokenizer))`，context7 PEFT 官方款）。詞表增量＝catalog 全集（§13 實查精確數，預設數千——t5-small 原詞表 32128，+數千 embedding 列＝數 MB）。**淘汰課程原做法**（數字 id 靠 SentencePiece 自然拆 subword）：GA4 item_id 是 SKU 字串，subword 拆分讓不同 item 共享片段 → 解碼可組合出**不存在的 SKU**＝幻覺面；一 item 一 token 使「生成空間 ≡ 合法 item 空間」成為**結構性質**而非後驗補救。 |
| prompt 模板 | 取材 `prompt.txt` sequential seen 模板改我方語境 **3 式輪替**（資料增強，課程同法；進 DVC 版本化 `seq_prompts.txt` 同課程分號格式）：去 `{user_id}`（匿名裝置 id 無語意可學）與 `{dataset}`（單一資料域）。定稿式樣：①`A user has interacted with items {history} . What is the next recommendation ?`②`Here is the browsing and purchase history of a user : {history} . Predict the next item for the user .`③`After interacting with items {history} , what is the next item to recommend ?`；`{history}`＝item token 空格串（尾 20）；target＝單一 item token。 |
| 微調 | **PEFT LoRA**（沿 P2 §12 基建範式）：`LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, target_modules=["q","v"]`（T5 注意力投影命名；§13 實查 `named_modules()` 確認）`, trainable_token_indices={'shared': <新增 item token ids>})`——**只訓 LoRA 低秩層＋新 token 的 embedding 列**（context7 PEFT 官方 pattern；T5 embedding 模組名 `shared`、lm_head tied——若 `trainable_token_indices` 對 T5 tied 權重有相容問題，備援 `modules_to_save=["shared","lm_head"]`，§13）。Trainer＝**transformers `Seq2SeqTrainer`**（seq2seq 正典；不硬搬 TRL）。精度 **bf16 on MPS**（T5 家族 fp16 有已知溢位 NaN 史；M4 原生 bf16；§13 sanity，備援 fp32——60M 撐得起）。lr 1e-3、epochs 5、batch 64、seed 42。M4 host `make finetune-p5t5`＝dvc stage。 |
| MLflow | experiment `reco_seq`、registered **`reco-p5t5`**、artifacts＝merged adapter（或 adapter+base ref）＋`item_vocab.json`＋`seq_prompts.txt` 快照＋eval 數字。 |

### 5.2 受限解碼（反幻覺硬約束的落地——三層，全部可測）

1. **生產批次推論＝單步 logits 排名**：target 恆為單一 item token → `encoder(prompt)` → decoder 首步 logits → **mask 到 item-token id 集** → softmax → top-50。一次 forward 得到合法空間上的 exact top-N（單步生成下 beam search 無增益，這是最誠實也最省的解碼）。
2. **通用機制展示路徑**＝`model.generate(…, prefix_allowed_tokens_fn=fn, num_beams=10)`：`fn(batch_id, input_ids)` 於 step 0 回 item-token id list、step 1 回 `[eos_token_id]`（context7 查證簽名 `Callable[[int, torch.Tensor], list[int]]`）。留此路徑證明機制對「多 token 目標」同樣成立（進化方向：bundle 生成），單元測試覆蓋。
3. **生成後驗證（defense-in-depth）**：decode → strip `item_` 前綴 → 斷言 `item_id ∈ gold_ga4_item_catalog` 集合；**非法 → 丟棄＋計數**（Prometheus `reco_seq_illegal_generations_total`，postgres 側 eval metadata 同記）。By construction 此計數應恆 0——**「恆 0 的驗證器」本身就是可稽核的反幻覺證據**（驗收斷言 §12）。

**明標（README／前端 Explainer 同句）**：「P5/T5 的『生成』被限定在合法 item token 空間內＝**限定 item 空間的生成 ≠ 自由生成 SKU**；讓 LLM 自由輸出任意商品編號再撈字串比對的做法**明拒**（不可驗證、幻覺面開放）。」

**Serving**：批次預產 only（§8/§10）；**不開線上 T5 端點**（拓撲鐵律＋M4 界線——T5 推論在 host，k8s 摸不到 MPS；KServe huggingfaceserver CPU 跑 T5 可行但為 demo 加常駐推理 pod 無收益，列進化方向連同 SASRec KServe）。

---

## 6. 兩序列模型定位與對比（拍板 4）

| 項目 | 決定 |
|---|---|
| 對比口徑 | **同一 test held-out**（§3 test 窗 leave-one-out 樣本）、**同一詞表**、**full-ranking**（對全 item 排名，不抽樣負例——sampled metrics 有偏，誠實口徑）、同指標 hit@10/ndcg@10（單 ground truth，IDCG=1，課程 `utils.py` 同式；complements P6 `evaluate.py` 集合運算複用）。 |
| production seq 召回路 | **只開一個模型**寫 `reco_candidates source='seq'`——兩個高度相關模型同時進 RRF 會對同質候選重複計票（變相加權，污染融合語意）。`params.yaml seq.seq_candidate_model: p5t5`（**預設傾向 p5t5＝主秀**）；**由晉升閘實測定奪，不預設贏家**：若 SASRec 過閘而 p5t5 未過、或 SASRec hit@10 相對高出 >10%，切 params 為 sasrec 並在前端敘事如實標（「LLM 生成式在本資料上輸給經典序列模型」也是誠實展示）。 |
| 晉升閘（兩模型同款，自動 → `@staging`，沿 P6 §5.3 三條結構） | ①hit@10 > 加權熱門 baseline（無模型地板）②**hit@10 > last-item i2v baseline**（用 P6 §4.1 eval i2v 向量、以 session 最後一 item 的 cosine top-k 當推薦——「序列建模是否勝過純 item-item」的真門檻；**輸了＝seq 召回路不開啟**，寫 known-limit，兩模型仍留評估展示）③絕對地板 hit@10 ≥ 0.05（文獻量級預估，首次實跑校準進 params，同 P6 §5.3 姿態）。`@prod` 人工（沿 `make promote-*` 四步腳本模式）。 |
| 前端敘事 | `/reco` 新區塊並排兩模型指標＋「參數量 60M vs ~1M」「生成式（受限解碼）vs 判別式（softmax 排名）」對照卡（§10）；數字全部從 `ml.reco_eval_metrics` 匯出，**不手寫**。 |

---

## 7. FP-Growth 購物籃關聯召回（拍板 5）

| 項目 | 決定 |
|---|---|
| 籃定義 | **`transaction_id` 分組的 purchase item 集**：`SELECT transaction_id, array_agg(DISTINCT item_id) FROM silver.ga4_events WHERE event_name='purchase' AND transaction_id IS NOT NULL GROUP BY transaction_id`（地基 §4：`transaction_id` 僅 purchase 有值——合約直接可用）。**全部籃入 TransactionEncoder**（含單品籃——它們天然不產多品項集，但保住 support 分母＝「共購率」的正確語意；砍單品籃會人為膨脹 support）。淘汰 session 共現籃：view 共現≠購買關聯，且該訊號已被 item2vec 路吃掉（重複召回無增量）。 |
| 演算法與庫 | **mlxtend 0.25.0 `fpgrowth`**（k8s KPO CPU，純 Python）：`TransactionEncoder` → `fpgrowth(df, min_support=<§下>, use_colnames=True, max_len=2)` → `association_rules(fi, metric='confidence', min_threshold=0.05, num_itemsets=n_baskets)`（context7 查證 API 面含 `num_itemsets`）。**`max_len=2` ⇒ 規則恆 1→1**＝「買了X也買Y」語意（高階項集/多前件列進化方向）。**不引 Spark**（課程 `FPGrowth.scala` 是 Spark `ml.fpm` 載體——取 min_support/min_confidence 語意與演算法選型，拒常駐叢集）。 |
| 參數（params.yaml `fbt:`） | `min_cooccur: 5`（絕對共購次數地板；`min_support = min_cooccur / n_baskets` 執行時換算——靜態資料集下絕對次數比相對比例穩健）、`min_confidence: 0.05`（寬進）、**`min_lift: 1.0`（嚴出：lift ≤ 1＝獨立/負相關，不配叫「也買」）**、`topn_per_antecedent: 20`（按 lift desc）。實跑校準 §13（多品籃過少 → min_cooccur 降 3 並誠實標訊號薄）。 |
| 規則正本表 | `ml.reco_fbt_rules(antecedent_item text, consequent_item text, support double precision, confidence double precision, lift double precision, cooccur_count bigint, window text CHECK (window IN ('eval','full')), batch_id text, built_at timestamptz, PRIMARY KEY (antecedent_item, consequent_item, window))`——DDL 由 `fbt.py` 首行 `CREATE TABLE IF NOT EXISTS` 持有（P1 loader 慣例）；UPSERT 冪等。eval/full 雙窗同 §3 紀律（eval 窗規則餵 LTR 訓練特徵，防洩漏）。 |
| 進 candidates | 同批寫 `ml.reco_candidates`：`seed_type='item', seed_id=<antecedent>, source='fbt', rank=<lift desc 序>, score=<lift 原值>`（RRF 只吃 rank；score 存 lift 供稽核）。 |
| 線上 seed 語意 | user 的 **cart 以上足跡 item**（`feat:user.recent_items` 中 W≥3 者，即 add_to_cart/checkout/purchase）→ `MGET cand:fbt:{item_id}`——「買了/加購了X → 推薦也買Y」；純瀏覽 item 不觸發 fbt（語意誠實：規則是購買共現）。已購剔除沿 P6 §4.5 既有邏輯。 |

---

## 8. 接進 RRF+LTR（拍板 6；only-additive 的落地帳）

### 8.1 `ml.reco_candidates`（P6 §4.5 合約的 additive 擴充）

- `source` CHECK：`('i2v','sem','pop')` → **`('i2v','sem','pop','seq','fbt')`**；`seed_type` CHECK：`('item','pop_global','pop_cat')` → **＋`'user'`**（seq 候選以 user 為 seed：`seed_type='user', seed_id=user_pseudo_id, source='seq', rank 1..50, score=<合法空間 softmax 機率>`）。
- **落法（因 §0.1 P6 無實碼，兩情境都定）**：P6 plan 未落地 → 兩 plan 對齊後 DDL 一次含 5 值；P6 已先落地 → `ALTER TABLE ml.reco_candidates DROP CONSTRAINT <source_check>, ADD CONSTRAINT … CHECK (source IN (…5 值…))`——**純列舉放寬，既有列全數照過＝非破壞 additive**（`seed_type` 同法）。表粒度、PK、既有欄、既有寫入者全部零改。
- 候選生成輸入（seq）：user 的**最後一條 session 序列**（尾 20；與訓練分佈一致——模型學的就是 session 內 next-item）。最後 session 不存在（無 ≥2 足跡）→ 該 user 無 `cand:seq` 鍵，RecallRouter miss＝空列表，其餘路兜底（零新降級碼）。跨 session 長歷史建模列進化方向（§3 單一序列定義紀律）。

### 8.2 RECO_FEATURE_SCHEMA v1 → v2（22 → 25 欄，尾端 append）

| 新欄（3） | 定義 | 訓練面 / 服務面（同一定義兩計算面，沿 P6 §5.1 rt 欄同款紀律） |
|---|---|---|
| `seq_rrf` | 候選在該 user 的 seq top50 中 → `1/(60+rank)`；否則 0（與 RRF k=60 同常數——分數模型無關、跨模型可比、有界） | 訓練＝eval 窗 seq 候選；服務＝讀 `cand:seq:{user}` 的 rank |
| `fbt_confidence` | user 的 fbt seed 集對該候選的規則 confidence 取 **max**；無規則 → 0 | 訓練＝eval 窗規則表；服務＝`cand:fbt` 命中列的規則值（隨候選 JSON 帶出，見 8.3） |
| `fbt_lift` | 同上取 lift max；無 → 0 | 同上 |

- 既有 22 欄**順序與語意一字不動**；`recall_src` 值域 additive **seq=3／fbt=4**（「多路命中取最小」原語意保留——新值更大，既有三路的相對序不受影響）。
- `feature_schema.json` version `"1"` → `"2"` 隨新 ranker artifact 序列化；serving 端**既有 fail-fast 斷言**（P6 §5.1）天然守門：v1 模型＋v2 組裝器（或反向）＝啟動即拒，不會靜默錯位。
- **v2 ranker**＝`reco_retrain` 既有鏈重訓（dataset builder 產 25 欄）；**LTR objective（lambdarank）、label_gain、grade 表、group 構造、gate 三條結構全部零改**。

### 8.3 Redis（接縫 A additive；schema_version 維持 `"1"`——P6 §6.0 明文「加欄/新 key＝additive 不 bump」）

| 新 key | 形狀 | 寫入者 |
|---|---|---|
| `cand:seq:{user_pseudo_id}` | String，minified JSON `[{"i":"<item_id>","s":0.031,"r":1},…]`（≤50；s=合法空間 softmax 機率、r=rank） | `redis_load.py`（仍是唯一離線寫入者；寫入者矩陣不變） |
| `cand:fbt:{item_id}` | 同上形（≤20；`[{"i":…,"s":<lift>,"r":…,"c":<confidence>}]`——c/s 隨鍵帶出，FeatureAssembler 免二次查表） | 同上 |

無 TTL（離線鍵政策沿 §6.0）。**記憶體帳 additive（誠實）**：`cand:seq` ≈（有 ≥2 足跡的 user 數，預設傾向 ~8 萬，§13 實查）×~1.5KB ≈ **~120MB**；`cand:fbt` 數千鍵忽略不計 → 峰值 ~300MB → **~420MB**，`maxmemory 768mb` 裕度 2.5× → ~1.8×，仍安全；旋鈕＝top50→top20（params）可再砍半，**不改 maxmemory、不動既有鍵**。

### 8.4 明標不改清單（規劃者覆核用）

三路召回碼與超參／RRF k=60 融合邏輯（多兩路 rank list 天然吸納，零改碼）／LTR objective・label_gain・grade／既有 22 欄語意與序／`reco_candidates` 粒度與 PK／Redis 既有鍵與 TTL 政策與寫入者矩陣／reco-service API 合約（`recall_sources[]` 多出 `'seq'/'fbt'` 值＝合約內 additive）／三條 DAG 的 schedule 語意／P4 既有匯出檔／`ml.reco_eval_metrics`・`ml.reco_ab_*` 表結構。

---

## 9. 評估／A-B／消融（拍板 7；沿 P6 §5.3/§9 框架 additive）

| 面 | 決定 |
|---|---|
| 序列頭對頭 | test 窗 leave-one-out（§3）、full-ranking hit@10/ndcg@10；四個 variant 寫 `ml.reco_eval_metrics(model='reco-seq', variant IN ('sasrec','p5t5','pop','lastitem_i2v'))`——既有 PK `(eval_date, model, variant, metric, k)` 直接容納，**零改表**。結構性 miss（目標 item 訓練窗未見）比率記 eval metadata（MLflow run tag＋匯出 JSON 誠實欄）。 |
| 召回消融（「每條召回路值多少」） | **4 組候選配置各自跑 `build_ltr_dataset → train_ranker → test 評估`**：`ltr_base3`（既有三路）／`ltr_base3_seq`／`ltr_base3_fbt`／`ltr_all5`——LightGBM 分鐘級可負擔，比「共用一個 ranker 置零特徵」乾淨（特徵置零殘留訓練期資訊）。同 test 窗 ndcg@10/hit@10/recall@50 寫 eval_metrics additive variants。**誠實紀律：某路增益 ≈0 或為負也如實寫、前端如實畫**（「fbt 覆蓋窄但精準／seq 增益有限」若為真相就是真相）。 |
| A/B 事件重放 additive | 新一輪 replay（新 `replay_id`）：**A＝full（5 路召回＋v2 ranker）vs B＝base3（3 路召回＋同一 v2 ranker）**——ranker 恆定，delta 純歸因於新召回路。`variant` API 值 additive `'base3'`（reco-service RecallRouter 按 variant 跳過 seq/fbt fan-out；v2 特徵欄自然為 0）。bucket/protocol/護欄/z-test/`traffic_type='labeled_event_replay'` 誠實標記全沿 P6 §9.2 零改；rt 特徵仍關閉。原 `full vs pop` 重放照舊不動。 |
| 資料侷限誠實段（README＋前端 Explainer 同源） | ①92 日靜態窗、session 天然短（多數 history=1~2，§13 實查分佈）→ 序列模型在此資料上部分退化為條件 item-item——**這是資料性質不是實作缺陷，如實陳述**；②多品籃佔比低（GA4 sample purchase 稀疏）→ fbt 是「窄而準」的路，覆蓋 item 數如實報；③device 級匿名 id 無跨裝置縫合；④**不以合成互動/虛擬使用者補任何缺口（明拒）**——冷啟仍走既有熱門路。 |

---

## 10. 資料流／服務／匯出／前端／守門（拍板 8；全 additive）

| 面 | 決定 |
|---|---|
| DVC（`ml/reco/dvc.yaml` additive +6 stage） | `build_fbt_rules`（deps=export；k8s/host 同 entrypoint）→ `train_sasrec`／`finetune_p5t5`（host MPS；deps=export＋sequences）→ `build_seq_candidates`（host；deps=finetune_p5t5[或 sasrec，依 params]）→ `evaluate_seq`／`evaluate_ablation`。既有 7 stage 名稱、deps、outs 零改；新 stage 只讀既有 stage 的 outs。 |
| DAG | `reco_build_artifacts` additive +1 task：`build_candidates → build_fbt_rules → build_user_features → load_redis`（KPO，CPU）；`redis_load.py` additive 讀兩個新 source 寫兩個新 key pattern（寫入者矩陣不變）。**seq 候選＝host 工序**（M4 界線帳 §2）：DAG 不含 host 步，`validate_redis` 對 `cand:seq:*` 缺席＝**warning 非 fail**（host 工序未跑時 DAG 仍收斂；README 記操作序：`make finetune-p5t5 && make seq-candidates` → 觸發 build DAG）。`reco_retrain`／`reco_ab_replay` 形狀零改（v2 由 features.py 版本、replay 由 variant 參數承載）。三 DAG schedule 全部維持 None（靜態資料誠實形狀，P6 §10 論證原樣）。 |
| 服務 | **批次預產 only**（守拓撲鐵律）：RecallRouter additive fan-out `cand:seq:{user}`（一鍵）＋ `cand:fbt:{seed items}`（W≥3 足跡）；RRF/排序/降級路徑零改。無線上 seq 模型端點（§5.2 末）；`/recommend` 回應的 `recall_sources[]`/`timings` 天然涵蓋新路。 |
| 匯出（P4 §4 additive +2 檔） | `reco_sequential.json`＝展示 user 樣例 20 個（匿名 id、footprint 序列 join catalog 名稱 → seq top10）＋兩模型頭對頭指標＋結構性 miss 率＋資料侷限誠實欄；`reco_fbt.json`＝top100 規則（antecedent/consequent join 名稱＋support/confidence/lift）＋籃統計（n_baskets/多品籃佔比）。既有 4 檔零改；`reco_eval.json` 的 additive variants 自然流入（形狀本就是 variant×metric×k）。統一信封沿 P4 §3。 |
| 前端 `/reco` additive +3 區塊 | ⑦**「下一步推薦」**（樣例瀏覽器：足跡序列 → 推薦；SASRec vs P5/T5 指標 BarChart；Explainer 方法論類：「受限解碼——為什麼這個 LLM 編不出不存在的商品」＝結構性防幻覺敘事）⑧**「一起買」**（規則表＋lift/confidence 散點；ChartCaption：`lift = P(Y|X)/P(Y)，>1 才是正相關`）⑨**召回消融卡**（4 組 ndcg@10 對比 bar＋每路增益如實標）。三層說明元件沿 P6 §11 既有；**crosscut §5 registry 阻擋級**：`/reco` 條目更新 `whatItDoes`＋`aiVsComputed`（seq/fbt 統計與消融＝程式算；P5/T5 候選＝模型生成**但受限解碼＋程式驗證**——照實分類）；coverage gate 現有 vitest 守門天然涵蓋。**icon 一律 lucide**（`ListOrdered`/`ShoppingBasket` 級），零 emoji。 |
| MCP additive +2 工具 | `get_bought_together(item_id: str \| None, limit: int = 10)`（讀 reco_fbt.json；docstring：「規則來自歷史交易共購統計（support/confidence/lift），批次預產非即時」）；`get_sequential_examples(limit: int = 5)`（讀 reco_sequential.json；docstring 含「批次預產、匿名樣例、事件重放非真流量」誠實句）。既有 10＋2 工具零改。 |
| CI / Secrets / 監控 | `ml-batch-ci` paths 既涵蓋 `ml/reco/offline/**`；image +`mlxtend==0.25.0`（唯一依賴增量）。Secrets 零新增。監控 additive：postgres-exporter +`reco_fbt_rules_rows`、`reco_seq_candidate_users`；Prometheus `reco_seq_illegal_generations_total`（**=0 是驗收斷言**）。Grafana reco dashboard +1 row（seq/fbt 列數、非法生成計數、消融最新值），零新 dashboard。 |

---

## 11. 取材界線表（進化非複刻）

| 素材（唯讀） | 取的邏輯 | 重造的工程層 |
|---|---|---|
| 越賣越多 `prompt.txt` | P5 sequential 模板句式與「多模板輪替＝資料增強」；分號分隔模板檔格式 | 去 `{user_id}`/`{dataset}` 佔位（匿名 id 無語意／單一資料域）；模板進 DVC 版本化；只取 sequential 任務（straightforward 任務不取——無 user 語意可學） |
| 越賣越多 `utils.py:269-311` | leave-one-out 構造（`history=[:-1]`,`target=[-1]`）、`max_his` 尾截、`item_` 前綴 token 慣例 | txt 檔資料層 → `silver.ga4_events`＋`sequences.py` 單一真源；sequential_indexing 重編號（`:125-176`）**不取**——我方 item_id 原字串直接當 token，免二次映射表 |
| 越賣越多 `utils.py:233-266` | hit@k／ndcg@k（leave-one-out 單 ground truth IDCG=1）口徑 | 併入我方 `evaluate_seq.py`（複用 P6 evaluate.py 集合運算）；寫 `ml.reco_eval_metrics`＋MLflow（課程 print 級輸出 → 表化/版本化） |
| 課程 T5 微調（train-llm/models） | 「T5-small＋item token＋seq2seq 生成推薦」範式本身 | 全量微調 → **PEFT LoRA＋trainable_token_indices**（P2 §12 基建）；無約束 generate → **受限解碼三層＋生成後驗證**（課程直生直比對＝幻覺面，工程層全重造）；MLflow registry/晉升閘（課程無） |
| Spark 企业级 `Chapter_12/FPGrowth.scala` | FP-Growth 選型、min_support/min_confidence 參數語意、頻繁項集→關聯規則兩段式 | Spark `ml.fpm` 常駐載體 → **mlxtend 純 Python on k8s CPU**；`setMinSupport(0.5)` 玩具值 → 絕對共購次數地板換算；+lift 嚴出門檻＋規則正本表＋eval/full 雙窗防洩漏（課程無） |
| RecBole（context7 文件，未引庫） | SASRec 超參基準（embedding 64／CE 全 softmax／NDCG@10 選模）與 full-ranking 評估口徑 | 框架不引（§4 判定）；模型自寫 ~200 行對齊論文/基準慣例 |

---

## 12. 測試策略＋端到端驗收

### 單元/CI 層（每步可測）

| 層 | 測試 |
|---|---|
| `seq_dataset.py` | **同一序列定義守門**：對同 fixture，`sequences.build_session_sequences()` 的輸出與 i2v 語料逐 token 相等（禁第二實作的可執行證明）；leave-one-out 構造斷言；max_len 尾截；時間窗歸屬（跨窗 session 歸 test 不入訓練）；**洩漏守門**：eval artifact 訓練樣本 max(event_date) ≤ 2021-01-03 斷言 |
| `sasrec.py` | 小 fixture 訓練收斂 smoke（loss 下降）；causal mask 斷言（位置 t 的 logits 不受 t+1 輸入影響——擾動測試）；seed 決定性；PAD 不入 loss |
| `p5t5.py` | tokenizer round-trip（`item_<id>` 不被拆分＝單 token 斷言）；**受限解碼**：單步 mask 後 top-N 全 ∈ item token 集；`prefix_allowed_tokens_fn` step0/step1 回傳集合斷言；**生成後驗證器**：注入非法 token 的 fake 輸出 → 丟棄＋計數（驗證器有效性的反例測試）；prompt 模板格式化 |
| `fbt.py` | 已知小籃 fixture → 頻繁項集/規則數值對照手算（support/confidence/lift）；lift ≤1 排除斷言；`max_len=2` ⇒ 規則恆 1→1；單品籃入分母不產規則；UPSERT 冪等 |
| features v2 | 25 欄黃金樣本（固定輸入→固定向量+欄序）；v1 model＋v2 schema → fail-fast 斷言；`seq_rrf`/`fbt_*` 訓練面 vs 服務面同 fixture 等值（training-serving skew 守門，沿 P6 rt 欄測試模式） |
| candidates/Redis | source/seed_type 新值寫入合法、舊值不受影響；`cand:seq`/`cand:fbt` round-trip（fakeredis）；schema_version 仍 "1" 斷言 |
| service | `variant='base3'` 跳過新路徑＋v2 特徵為 0；`recall_sources` 含 'seq'/'fbt' |
| 匯出/前端/MCP | 2 新檔黃金測試（含 absent 路徑）；registry 條目 coverage gate（既有阻擋級）；MCP 2 工具 fixture；`check-data.mjs` 涵蓋新檔 |

### 端到端驗收（additive 進 `make reco-verify`，前置＝P6 既有 14 步綠）

| # | 檢查 | 預期 |
|---|---|---|
| A1 | `dvc repro build_fbt_rules` → `ml.reco_fbt_rules` | count>0、全列 lift>1、window 兩值齊；重跑不膨脹（冪等） |
| A2 | `make finetune-p5t5 && make train-sasrec` | MLflow `reco_seq` 兩 run；`reco-p5t5`/`reco-sasrec` 註冊；`item_vocab.json` artifact 在 |
| A3 | `dvc repro evaluate_seq` | eval_metrics 四 variant（sasrec/p5t5/pop/lastitem_i2v）hit@10/ndcg@10 齊；閘判定輸出（過/不過＋依據數字） |
| A4 | **反幻覺實證** | 批次推論全量後 `reco_seq_illegal_generations_total == 0`；抽 100 條 seq 候選斷言 item_id ∈ catalog |
| A5 | `make seq-candidates` → 觸發 build DAG → Redis | `reco_candidates` 有 source='seq'/'fbt' 列；`GET cand:seq:<樣本>`/`cand:fbt:<樣本>` JSON 可解析；`DBSIZE` 增量符合記憶體帳量級 |
| A6 | `reco_retrain`（v2） | 25 欄 dataset、`feature_schema.json` version=2、gate 過 → `reco-ranker@staging`；serving 斷言相容 |
| A7 | `dvc repro evaluate_ablation` | 4 組 variant ndcg@10 入表；前端消融卡數字與表一致 |
| A8 | replay additive 輪 | `full vs base3` 兩臂＋p 值＋護欄未破；`traffic_type` 誠實欄在 |
| A9 | 匯出+前端 | 2 新檔進 `latest/`；`npm run build` 綠；registry gate 綠；⑦⑧⑨ 區塊 lucide icon、Explainer 呈現 |
| A10 | **主線無損** | P6 既有 4 匯出檔 byte 級不變（除 meta additive）；既有三路召回單測全綠；`full vs pop` 舊 replay 結果表不受影響 |

---

## 13. plan 期待查證點（設計已收斂；落地校準，皆帶預設傾向與判準）

1. **P6 推薦 plan/實碼落地後對錨**：`ml_reco` 實際模組路徑、`reco_candidates` DDL 現況（3 值 CHECK 已建 → ALTER 放寬遷移；未建 → 一次 5 值）、`sequences.py` 函式簽名（預設傾向：與 P6 design §2 佈局一致，零偏移）。
2. **session 序列分佈**（silver 落地後一條 SQL）：長度 ≥2 佔比、P50/P99（預設傾向：≥2 佔比 30–40%、P99 <20——若 P99>20 調 `seq.max_len`；若 ≥2 session 過少（<5 萬條）如實標訓練集規模並降 batch/epoch）。
3. **transaction 籃分佈**：n_baskets、多品籃佔比、每籃 item P95（預設傾向：數千~萬級 transaction、多品籃 20–40%；多品籃 <500 → `fbt.min_cooccur` 降 3＋前端誠實標「訊號薄」）。
4. **catalog item 數＝P5/T5 詞表增量與 SASRec 詞表**（預設傾向：數千；t5-small +數千 token ≈ 數 MB embedding，無虞）。
5. **T5 `trainable_token_indices={'shared': …}` 相容**（tied lm_head 情境；預設傾向：可——PEFT 官方 pattern；不可 → 備援 `modules_to_save=["shared","lm_head"]`，記憶體仍可負擔）；`named_modules()` 確認 target_modules `["q","v"]` 命名。
6. **bf16 on MPS 訓練 sanity**（預設傾向：可；NaN → fp32，60M 無壓力）。
7. **mlxtend 0.25.0 `association_rules(num_itemsets=…)` 實跑 smoke**（context7 已錨簽名；1 分鐘）。
8. **全量 seq 批次推論時長**（有 ≥2 足跡 user 數 × top50；預設傾向：~8 萬 user、M4 MPS <1h；過長 → 候選 user 集限縮為「近 30 日活躍」並記錄限縮率）。
9. **transformers 5.13 `generate(prefix_allowed_tokens_fn=…)` smoke**（context7 錨自官方 main；預設傾向：可用）。
10. **seq 晉升閘絕對地板校準**（首跑後把 pop/lastitem_i2v 實測值寫回 params，閘邏輯不變——同 P6 §15-7 手法）。

---

## 14. 本 spec 拍板 vs 下放對照

| 已拍板（本 spec 定死） | 下放（plan/實跑校準，帶預設） |
|---|---|
| 序列定義單一真源＝item2vec 同函式；eval/full/test 窗歸屬規則；leave-one-out 構造 | max_len 數值微調（P99 實查） |
| SASRec 自寫（拒 RecBole）＋架構超參集；P5/T5 基座 t5-small（拒 Qwen3.5-2B）＋一 item 一 token（拒 subword 拆分）＋LoRA 配置＋受限解碼三層 | target_modules/embedding 模組名的 `named_modules()` 確認；bf16/fp32 擇一 |
| production seq 路單模型＋params 切換＋「必須贏 lastitem_i2v」閘結構 | 閘絕對地板數值；勝者實測定奪 |
| 籃＝transaction_id purchase；mlxtend＋max_len=2＋lift>1 嚴出；規則表 DDL | min_cooccur/min_confidence 數值校準 |
| source/seed_type CHECK 擴列舉落法（兩情境）；schema v2 三新欄定義與序；Redis 兩新 key 形狀；記憶體帳與旋鈕 | 候選 user 集規模（實查後如需限縮） |
| 評估口徑（full-ranking/同 held-out）；消融＝4 組重訓；replay full vs base3 | — |
| 匯出 2 檔形狀、前端 3 區塊、MCP 2 工具、驗收 A1–A10 | 展示樣例挑選（20 user 樣例的抽樣準則） |

---

## 15. known-limits（誠實段）＋精確度契約自檢

**known-limits（README 全列）**：
1. GA4 sample session 短、92 日窗——序列模型部分退化為條件 item-item 是資料性質；跨 session 長歷史、bundle 多 token 生成、SASRec/T5 線上端點（KServe）皆列進化方向。
2. fbt 覆蓋窄（多品籃佔比低）——「窄而準」如實標；高階項集不做。
3. P5/T5 的「LLM 生成式」是**受限 item 空間內的生成**——明標非自由生成；其價值在範式與反幻覺工程，不宣稱效果必勝經典模型（實測填數）。
4. seq 候選是 host 批次工序，DAG 對其缺席容忍（warning）——M4 界線的誠實邊界。
5. 訓練窗未見 item 的結構性 miss 計入分母——分數天然偏保守，如實揭露。
6. 不合成使用者/互動（明拒）；冷啟由既有熱門路兜底，本 spec 不新增冷啟機制。

**自檢（8 條）**：①8 項全收斂單一決定（§1），實查點全帶預設傾向（§13）；②新 pin 唯一（mlxtend 0.25.0，PyPI 當日）＋transformers/PEFT/mlxtend/RecBole API 面 context7 查證（§0）；③資料契約欄位級：`reco_fbt_rules` DDL、schema v2 25 欄、Redis 2 新 key、candidates 擴列舉、匯出 2 檔（§7/§8/§10）；④部署形狀具體：dvc stage/DAG task/make target/檔案佈局到檔名（§2/§10）；⑤沿用慣例明講：序列=P6 §4.1、時間窗=P6 §5.2、閘結構=P6 §5.3、微調=P2 §12、DDL loader 持有=P1、registry=crosscut §5；⑥取材界線表 §11 逐素材；⑦硬約束貫徹：only-additive（§8.4 不改清單）、反幻覺結構性（§5.2 三層＋恆 0 斷言）、一工一具（拒 RecBole/Spark/Faiss/TRL 硬搬）、拓撲（批次預產、前端靜態）、不造假（§3/§9 明拒條款）、emoji→lucide；⑧每步可測（§12 單元＋A1–A10 可執行驗收）。

---

## 16. Opus 把關註記（PASS）

> 規劃者（Opus 4.8）獨立覆核。**親跑 context7 覆核最吃重的兩個承重宣稱（P5/T5 反幻覺整套故事的技術支點）、逐條裁定風險點、五鐵律。判定 PASS，commit 進 trend repo（不加 footer）。**

### 16.1 獨立 context7 覆核（規劃者親查，非採信 §0.2）

覆核挑「若錯則 P5/T5『結構性防幻覺＋item-token 可訓』整套故事崩」的兩個承重宣稱：

| 宣稱 | 規劃者獨立查證（context7，2026-07-10） | 判定 |
|---|---|---|
| **`generate(prefix_allowed_tokens_fn=…)` 每步限定 allowed tokens** | `/huggingface/transformers` 確認簽名 `Callable[[int, torch.Tensor], list[int]]`、經 `PrefixConstrainedLogitsProcessor`「constraints the beam search to allowed tokens only at each step」；Emu3 影像生成範例正是「限定輸出到固定 token 集（visual_tokens）」＝我方限定 item token 的同型 | ✅ 屬實。受限解碼第 2 層機制成立 |
| **PEFT `trainable_token_indices` 只訓新增 special token embedding（LoRA）** | `/huggingface/peft` 顯示**與 §5.1 完全同型的官方 pattern**：`add_special_tokens`→`resize_token_embeddings`→`LoraConfig(trainable_token_indices={'embed_tokens': ids})`，只訓新 token embedding 存進 adapter、比全 embedding 微調省 VRAM | ✅ 屬實。「加數千 item token 只訓其 embedding」可行 |

即：受限解碼（單步 mask／`prefix_allowed_tokens_fn`／生成後驗證 ∈ catalog）＋一 item 一 special token（拒 subword 拆分＝真幻覺面）＋`trainable_token_indices` 三者，技術上皆站得住——**「生成空間 ≡ 合法 item 空間」是結構性質**成立。其餘 §0.2 宣稱（mlxtend `num_itemsets`、RecBole 舊 release、torch/transformers pin）為 API 面或沿 P2 pin，隨 §13 plan 實查即可。

### 16.2 Fable 5 給的風險點逐條裁定

1. **`source`/`seed_type` CHECK 擴列舉＝additive（風險 1）**：**確認，PASS**。放寬 CHECK 列舉（加 'seq'/'fbt'/'user'）非破壞——既有列全數照過；兩情境落法（P6 未落地→DDL 一次 5 值；已落地→`ALTER DROP+ADD CONSTRAINT`）正確；表粒度/PK/既有欄/寫入者零改。schema v1→v2 尾端 append 3 欄、既有 22 欄序與語意零動、`feature_schema.json` version bump 走既有 fail-fast——additive 邊界守住。
2. **反幻覺結構性（風險 2）**：**PASS**，見 16.1。三層皆結構性（mask 集合／prefix_fn／後驗證），`reco_seq_illegal_generations_total==0` 是驗收硬斷言（A4）；「自由生成任意 SKU」§5.2 明拒。`trainable_token_indices` 對 T5 tied lm_head 的相容有備援（`modules_to_save`，§13-5），非阻擋。
3. **序列與 item2vec 同一定義＋推論吃 last session（風險 5）**：**PASS，session-internal 是正確 v1 邊界**。靠「只准 import `sequences.py`＋CI 逐 token 等值守門」強制單一序列定義；推論輸入＝user 最後一條 session（與訓練分佈一致——模型學 session 內 next-item）。跨 session 長歷史＝第二序列定義，誠實列進化方向而非塞進 v1——守單一真源紀律。此為合理邊界非缺陷。
4. **production seq 單模型入 RRF（風險 6）**：**PASS，正確收斂**。兩個高度相關序列模型同時進 RRF＝對同質候選重複計票污染融合——只開一個（params 切換、預設 p5t5 主秀、由閘實測定奪不預設贏家），落選者留評估對比。與 brief「P5/T5 進 candidates」的輕微張力由 brief 同段「傾向 winner 進」授權收斂。
5. **無 Spark 常駐/無 Faiss/唯一新 pin mlxtend（風險 3）＋無造假資料（風險 4）**：**PASS**。合成使用者/LLM 補冷啟 §3/§9/§15 三處明拒；結構性 miss 計入分母（誠實保守計分）。

### 16.3 規劃者五鐵律覆核

- **接地誠實**：§0.1 無實碼鎖 design 合約（ask-ai §0.3 precedent）＋本機 bq 未授權**不編序列/籃分佈數字**（全列 §13 帶預設傾向與降級判準）；課程逐行號取材。✅
- **拓撲鐵律**：批次預產 only、無線上 T5 端點、前端靜態讀匯出 JSON 零 live 依賴、seq 候選＝host 工序（DAG 對缺席 warning 容忍）。✅
- **一工一具／validated library**：自寫 SASRec（僅模型定義 ~200 行，torch 是 validated lib＝非造輪；拒 RecBole 理由扎實）、mlxtend 非 Spark、拒 Faiss/TRL 硬搬——合 [[feedback_use_validated_libraries]]「不重造又不硬塞」。✅
- **only-additive**：見 16.2-①；§8.4 不改清單完整（LTR objective/label_gain/grade/RRF k=60/既有三路/表粒度全零改）。✅
- **反幻覺（核心正確性面）／不造假**：見 16.1／16.2-②⑤。✅

**額外肯定的判斷力**：「必須贏 last-item i2v baseline」閘——序列建模無增益則 seq 路**誠實不開**（GA4 sample session 短、多數 history=1-2，序列可能真輸給 item-item，設計誠實預備此結果）；一 item 一 token 拒 subword（精準識別真幻覺面）；召回消融＝4 組各自重訓 LTR（拒「置零特徵」殘留訓練資訊）；A/B replay ranker 恆定純歸因召回路。皆資深訊號。

### 16.4 判定

**PASS。** 八項全拍板、兩承重反幻覺宣稱獨立證實、CHECK 擴列舉/schema v2/Redis 皆真 additive、棄 RecBole/Spark/Faiss 徹底、不造假資料、拓撲守住。commit 進 trend repo（不加 footer）。**plan 佇列位置**：本 spec 依賴 **P6 推薦 plan**（鎖其 reco_candidates/feature schema/sequences.py/Redis 合約）→ plan 序在 **P6 推薦 plan 之後（或同批次後段 task）**；與 P7 模型化標籤 spec 互不依賴（不同子系統，可平行）。與整體硬序合流：P0→P2b-1→…P6 推薦 plan→本 P6 進階召回 plan。
