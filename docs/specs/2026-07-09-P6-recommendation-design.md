# P6 推薦系統（核心垂直）— Design（Fable 5 產出）

> **狀態**：design 完成，待寫 implementation plan。
> **上游**：[`2026-07-09-P6-recommendation-brief.md`](2026-07-09-P6-recommendation-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)「GA4 第二真來源 ＋ 三工具翻案」段（Redis 條）+ **GA4 地基 design（已鎖合約，勿改）**：[`2026-07-09-P6-ga4-ingestion-foundation-design.md`](2026-07-09-P6-ga4-ingestion-foundation-design.md) §4 `silver.ga4_events`／§5.1 `gold_ga4_user_item_interactions`（刻意不加權）／§5.2 `gold_ga4_item_catalog`（文字欄＝embedding 輸入源）＋ [`2026-07-08-P2-ml-verticals-design.md`](2026-07-08-P2-ml-verticals-design.md)（DVC/MLflow/KServe/pgvector/drift/LangGraph 慣例正本）＋ [`2026-07-08-P4-presentation-layer-design.md`](2026-07-08-P4-presentation-layer-design.md) §3-4（匯出合約，additive-only）。brief 已鎖定決策 1–7 全部沿用，未翻案。
> **定位**：一條完整工業級推薦生命週期——多路召回 → LTR 排序 → 線上服務（**Redis feature/候選快取＝接縫 A 單一真源** + KServe）→ LangGraph 推薦理由 → A/B（labeled event-replay）＋離線評估 → 重訓/drift → 前端展示。**Redis 是本垂直唯一新增線上元件**（線上特徵/候選快取 <50ms，不當第二 OLTP/排程/佇列）。
> **版本查證日**：2026-07-09（lightgbm/gensim/redis-py 對 PyPI、Redis image 對 Docker Hub、LGBMRanker/redis-py API 面對 context7 官方文件；其餘沿用 P2 §0 已查證 pin，查證日 2026-07-08）。

---

## 0. 版本 pin 表

| 元件 | 版本 | 查證方式 | 備註 |
|---|---|---|---|
| LightGBM | **4.6.0** | PyPI（2026-07-09）；`LGBMRanker`（objective 預設 `lambdarank`、`fit(group=…, eval_at=…)`）API 面 context7 查證 | LTR 主線；進 ml-batch image |
| gensim | **4.4.0** | PyPI（2026-07-09） | item2vec（`Word2Vec` skip-gram）；進 ml-batch image |
| redis-py | **8.0.1** | PyPI（2026-07-09）；hash/pipeline/EXPIRE API 面 context7 查證 | reco-service 與 load_redis 共用；即時層 Flink 是 Java sink 不吃此 pin |
| Redis server image | **`redis:8.4.4`** | Docker Hub tags（2026-07-09） | 8.8.0 剛出、8.4 線 patch 成熟；licensing 註記見 §12 |
| KServe / MLflow / pgvector / LangGraph / langchain-ollama / sentence-transformers / e5-small / Ollama | v0.19.0 / 3.14.0 / 0.8.4 / 1.2.8 / 1.1.0 / 5.6.0 / `intfloat/multilingual-e5-small` / v0.31.1 | 沿用 P2 §0（2026-07-08 查證） | 零升級；KServe 加一個 `lightgbm` modelFormat InferenceService |
| Airflow / dbt / Postgres / MinIO / google-cloud-bigquery | 沿用 P1 §0 + 地基 §0 | — | 零升級 |

**刻意不引入**：`implicit`/ALS 庫（CF 收斂 item2vec，§1①）；Faiss（向量檢索已有 pgvector，一工一具）；Feast（feature store＝Redis schema 合約自持，NORTH_STAR 刻意省略清單）；`redis_exporter`（單機 demo 快取的監控由 reco-service 側指標＋`redis-cli INFO` 驗收承擔，不為它開第二個 exporter）；k6/locust（負載測試用 `scripts/reco_loadtest.py`——httpx+asyncio，零新依賴）。

---

## 1. 開放問題收斂總表（9 題全拍板，禁 TBD）

| # | 題 | 決定 |
|---|---|---|
| 1 | 召回路數 | **3 路**：item2vec CF ＋ pgvector 語意 ＋ 熱門 fallback（全域＋類別熱門，兼冷啟降級路）。RRF（k=60，沿 P2 §9 hybrid 慣例）融合去重成候選池 ≤200。 |
| 2 | CF 演算法 | **item2vec**（gensim 4.4.0 `Word2Vec` skip-gram on session 互動序列）。淘汰 ALS：要再拖 `implicit` 一個依賴、產出是分解矩陣而非可入 pgvector 的向量；淘汰純 item-item 共現：沒有 embedding 可展示、與語意路無法共用向量檢索基建。item2vec 讓 CF/語意兩路共用同一套 pgvector HNSW 檢索（最少新依賴，brief 傾向照收）。 |
| 3 | 互動加權表 | **W = view 1 / cart 3 / checkout 4 / purchase 5**（連續加權，用於 user 向量聚合、加權熱門、歷史互動分）＋ **LTR grade g = none 0 / view 1 / cart 2 / checkout 3 / purchase 4**（lambdarank 需要小整數等級，`label_gain=[0,1,3,7,15]`）。兩表都是本 spec 定義（接縫 B：地基刻意不加權，下游不得假設已加權），單一真源 `ml/reco/params.yaml`（§3）。 |
| 4 | 排序模型 | **LightGBM 4.6.0 `LGBMRanker`（objective=lambdarank）**主線：M4/CPU 友善、免 GPU、`feature_importances_` 可解釋、業界 LTR 標準。Wide&Deep 列進化方向（README 一行：需 GPU 訓練與 embedding 層 serving，雲 GPU 節點到位才值得）。 |
| 5 | Redis 部署形狀 | **單機 Deployment + PVC（1Gi）+ ConfigMap redis.conf**，`ml` ns。Sentinel/Cluster 是 portfolio 規模的過度工程——ADR 誠實註記「單點是刻意取捨，服務端有 §7 降級路徑兜底」。schema 欄位級 = §6（接縫 A 單一真源）。 |
| 6 | 微服務切分 | **召回＋特徵組裝＋編排收在一個 `reco-service`**；排序模型推論歸 **KServe InferenceService**（模型 serving 統一姿態，沿 P2 §6）。不另立 recall-service/ranking-service 兩個自建服務（跨服務網路跳無收益）；可切分邊界＝service 內 `RecallRouter`/`FeatureAssembler`/`RankerClient` 三個模組介面（§7），未來切分＝模組升級成服務、合約已定。 |
| 7 | A/B 流量來源 | **事件重放（labeled event-replay）**：test 窗 `silver.ga4_events` 逐 session 重放模擬請求，誠實標註 `traffic_type: "labeled_event_replay"`（非真線上流量，使用者不曾看到推薦，hit 是反事實命中代理）。與即時層的重放護欄同一姿態（realtime brief 鎖定決策 5）。淘汰合成流量：造假分佈、與任何真實行為無對照價值。 |
| 8 | 理由進匯出 | **熱門集＋相似商品集＋分群代表集離線預生成理由，存 `ml.reco_reasons` 進匯出 JSON**（前端直接展示帶理由的推薦）；線上即時生成留 reco-service `include_reason=true` 本地 demo/MCP 佐證面。 |
| 9 | 時間切分 | **test = 最後 14 天**（label 窗 2021-01-18～2021-01-31）；訓練 label 窗 = 2021-01-04～2021-01-17（14 天），訓練特徵窗 = 2020-11-01～2021-01-03。全部按 `event_date` 切，特徵窗嚴格早於 label 窗（防洩漏正本，沿 P2 §4 τ 思路）。**展示 artifacts（Redis 灌注/候選/匯出）用全窗資料**——評估物防洩漏、展示物用全量，兩者分開（§4 eval/full 雙 artifact）。 |

---

## 2. 總體形狀

### 資料流（離線 → Redis/KServe → 線上 → 匯出）

```
gold_ga4_user_item_interactions ─┬→ 互動加權（§3，本 spec 定義）
gold_ga4_item_catalog（文字欄）──┤
silver.ga4_events（序列/重放源）─┘
        │ reco_build_artifacts DAG（schedule=None，§10）
        ▼
[離線] item2vec 向量 + e5 語意向量 → Postgres pgvector（ml.reco_item_i2v / ml.reco_item_semantic）
        │ 候選預算（RRF）→ ml.reco_candidates；user/item 特徵 → ml.reco_user_features
        ▼ load_redis（PG 是單一真源，Redis 是可隨時全量重建的投影）
[線上] Redis（feat:* / cand:*，接縫 A schema §6）←──（即時層 Flink 寫 feat:user:rt:*，只此一鍵）
        │
reco-service（FastAPI：召回→特徵組裝→呼叫 KServe reco-ranker v2 infer→理由 opt-in）
        │                         KServe InferenceService（LightGBM，MLflow @prod → s3://ml-models）
        ▼
A/B 事件重放（reco_ab_replay DAG）→ ml.reco_ab_* ；離線評估 → ml.reco_eval_metrics
        ▼
P4 匯出 DAG additive ＋4 檔 → frontend /reco 頁（三層說明 UI）＋ MCP ＋2 工具
```

### 新增檔案佈局（全 additive；未列 = 不動）

```
ml/reco/
├── offline/                    # Python 套件 ml_reco（裝進既有 ml-batch image，同 P2 ml_tabular 模式）
│   ├── pyproject.toml  params.yaml  dvc.yaml     # params = 權重表/超參/切分窗單一真源
│   ├── src/ml_reco/
│   │   ├── sequences.py        # silver 事件 → session 序列（item2vec 語料）
│   │   ├── i2v.py              # gensim Word2Vec 訓練 → ml.reco_item_i2v
│   │   ├── semantic.py         # catalog 文字 → e5 embedding → ml.reco_item_semantic
│   │   ├── candidates.py       # 三路召回預算 + RRF → ml.reco_candidates
│   │   ├── features.py         # RECO_FEATURE_SCHEMA 常數 + user/item 特徵計算（含 rt 欄位離線重算）
│   │   ├── redis_load.py       # PG → Redis 灌注（§6 schema 的唯一離線寫入者）
│   │   ├── ltr.py              # LTR 資料集構造 + LGBMRanker 訓練 + gate + MLflow 註冊
│   │   ├── evaluate.py         # hit@k/ndcg@k/recall@k/MAP → ml.reco_eval_metrics
│   │   ├── replay.py           # A/B 事件重放器 + 摘要 + z-test
│   │   ├── segments.py         # 展示用 4 分群 + 分群代表推薦
│   │   └── reasons.py          # 理由批次生成入口（呼叫 service 圖，host make target）
│   └── tests/
├── service/                    # reco-service（沿 P2 rag-service 目錄模式）
│   ├── Dockerfile  pyproject.toml
│   ├── src/reco_service/{api.py, recall.py, features.py, ranker_client.py,
│   │                     reason_graph.py, redis_client.py, metrics.py, settings.py}
│   ├── k8s/                    # deployment + service + ingress(reco.localtest.me) + servicemonitor
│   └── tests/
├── redis/k8s/                  # kustomization + deployment + service + pvc + configmap(redis.conf)
└── kserve/reco-ranker.yaml     # 放進既有 ml/kserve/ kustomization（additive，零新 ArgoCD app）
orchestration/airflow/dags/{reco_build_artifacts.py, reco_retrain.py, reco_ab_replay.py}
orchestration/exporter/src/exporter/datasets.py    # additive ＋4 dataset 條目（§11）
frontend/src/app/reco/page.tsx ＋ components/explainers/{InfoTooltip,ChartCaption,Explainer}.tsx
mcp-server/server.py            # additive ＋2 工具（§11）
platform/argocd/apps/{reco-redis.yaml, reco-service.yaml}   # 2 個新子 Application
platform/monitoring/reco/       # dashboard ×1 + PrometheusRule + postgres-exporter 查詢 additive
Makefile += reco-secrets / reco-verify / reco-loadtest / gen-reco-reasons / promote-reco-ranker
scripts/{verify-reco.sh, reco_loadtest.py}
```

### ArgoCD sync-wave（接續 P2 的 7–11）

| wave | Application | ns | 內容 |
|---|---|---|---|
| 12 | reco-redis | ml | `ml/reco/redis/k8s/`（Deployment/PVC/ConfigMap/Service；auth Secret 命令式 §12） |
| 13 | reco-service | ml | `ml/reco/service/k8s/`（CI bump kustomization，同 P0 hello / P2 rag-service 模式） |
| —（既有 10） | kserve-models | ml | additive 加 `reco-ranker.yaml`（零新 app） |

---

## 3. 互動加權（本 spec 是加權唯一定義處——接縫 B 落地）

**單一真源 `ml/reco/params.yaml`**（DVC 追蹤；DAG 與服務經套件常數讀同一份）：

```yaml
interaction_weights:            # W：連續加權（user 向量聚合 / 加權熱門 / 歷史互動分）
  view_item: 1
  add_to_cart: 3
  begin_checkout: 4
  purchase: 5
ltr_grades:                     # g：lambdarank 等級（none=0 隱含）
  view_item: 1
  add_to_cart: 2
  begin_checkout: 3
  purchase: 4
ltr_label_gain: [0, 1, 3, 7, 15]   # 2^g − 1（LightGBM lambdarank 預設語意）
recency_decay_days: 14             # user 向量時間衰減 exp(−Δdays/14)
split:
  train_feature_end: 2021-01-03
  train_label: [2021-01-04, 2021-01-17]
  test_label:  [2021-01-18, 2021-01-31]
```

**取捨說明**：W 取 1/3/4/5（brief 傾向）——cart→checkout 增量小（3→4）因兩者行為意圖接近、checkout→purchase 保留跳點；不取指數級（1/10/100）因 sample 漏斗率低（view→purchase ~2%），指數權重會讓少數 purchase 淹沒瀏覽訊號、冷啟劣化。W 與 g 分離：lambdarank 的 `label_gain` 已對 g 做指數放大（2^g−1），若直接拿 W 當 grade 會二次放大。CF 隱式回饋 confidence 的落點＝user 向量聚合權重與 LTR 特徵 `weighted_hist_interaction`（§5），不進 item2vec 語料本身（skip-gram 吃序列不吃權重——事件重複出現即天然頻次加權）。

---

## 4. 召回層（三路；決定）

### 4.1 路 1：item2vec CF（gensim `Word2Vec`）

| 項目 | 決定 |
|---|---|
| 語料 | `silver.ga4_events` 按 `(user_pseudo_id, ga_session_id)` 分組、`event_ts_micros` 排序的 `item_id` 序列（一 session 一句）；`ga_session_id` null → fallback `(user_pseudo_id, event_date)` 分組。長度 ≥2 才入語料；同 item 連續重複壓成一次（頁面重整噪音）。 |
| 超參 | `Word2Vec(vector_size=64, window=5, sg=1, negative=10, min_count=3, epochs=10, workers=4, seed=42)`——64 維對數千 item 的目錄充足，且與語意 384 維分表共存（§4.4）。超參進 params.yaml。 |
| 訓練窗 | **雙 artifact**：`eval`（只用 train 特徵窗 ≤2021-01-03，供 LTR 訓練與離線評估——防洩漏）／`full`（全窗，供 Redis 灌注與前端展示）。同一 entrypoint `--window eval|full`。 |
| 執行處 | **k8s KPO（ml-batch image，CPU）**——語料百萬級序列、gensim CPU 分鐘級，不觸 M4 重算力界線（M4 只留給真重活，沿 P2 §1④ 判準）；host `dvc repro` 跑同一 entrypoint（可重現層）。 |

### 4.2 路 2：pgvector 語意召回（接縫 C 落地：embedding 本體在此造）

- 輸入文字 = `passage: {item_name} | {item_category}`（`gold_ga4_item_catalog` 文字欄；e5 前綴慣例沿 P2 §8.1，封裝進 `semantic.py`）。
- 模型 = `multilingual-e5-small`（沿 P2 pin；catalog 是英文 Google Merchandise 商品名，e5 多語含英文覆蓋）。數千 items × e5-small = k8s KPO CPU 秒~分鐘級，不需 host。
- 查詢側：相似商品 = item 對 item 的 cosine top-N（見 4.4 索引）。

### 4.3 路 3：熱門 fallback（冷啟降級路）

- **加權熱門分** = Σ over 互動列（`W(event_name) × interaction_count`），全窗；`pop:global` top100 ＋ `pop:cat:{item_category}` 每類 top100（catalog 的 `item_category` 值域）。
- 冷啟語意：user 無任何互動足跡（Redis feat:user miss）→ 直接回熱門（global，若 rt 特徵有 `top_cat_1h` 則類別熱門優先）；item 無向量（min_count 淘汰的長尾）→ 只靠語意路與熱門路覆蓋。

### 4.4 pgvector 表（沿 P2 §8.2 HNSW 慣例，兩表因維度不同）

| 表 | 欄位 | 索引 |
|---|---|---|
| `ml.reco_item_i2v` | `item_id text, window text CHECK IN ('eval','full'), embedding vector(64) NOT NULL, model_version text, trained_at timestamptz, PK(item_id, window)` | `USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)` |
| `ml.reco_item_semantic` | `item_id text PK, embedding vector(384) NOT NULL, embedding_model text, indexed_at timestamptz` | 同上 |

DDL 由各 job 首行 `CREATE TABLE IF NOT EXISTS` 持有（P1 loader 慣例）；寫入 UPSERT 冪等。

### 4.5 候選預算與融合

- `candidates.py`：對每個 item（seed）算 i2v top50 ＋ 語意 top50（pgvector `ORDER BY embedding <=> …` cosine）→ 落 `ml.reco_candidates(seed_type text CHECK IN ('item','pop_global','pop_cat'), seed_id text, source text CHECK IN ('i2v','sem','pop'), rank int, item_id text, score double precision, batch_id text, built_at timestamptz, PK(seed_type, seed_id, source, rank))`。
- **線上融合在 reco-service 做**（RRF k=60，對 user 的多個 seed item 的多路候選清單融合去重 → 候選池 ≤200 → 進 LTR）。RRF 只決定「誰進排序」，最終順序交 LTR——召回融合分不出現在最終排序（職責分離）。
- 已購 item 從候選剔除（`purchase` 足跡；重複購買推薦列進化方向）。

---

## 5. 排序層（LTR；決定）

### 5.1 RECO_FEATURE_SCHEMA v1（`features.py` ordered 常數，沿 P2 §4 FEATURE_SCHEMA 模式：訓練時序列化 `feature_schema.json` 隨 model artifact 存，serving 端載入斷言欄序一致，漂移 fail-fast）

| 群 | 特徵（22 欄） | 來源 |
|---|---|---|
| user 離線（6） | `recency_days`（null→窗長 92 補）、`orders_count`、`sessions_count`、`active_days`、`log1p_monetary`、`distinct_items_viewed` | `gold_ga4_user_rfm` → Redis `feat:user` |
| item（7） | `log1p_users_viewed`、`log1p_users_purchased`、`view_to_cart_user_rate`、`view_to_purchase_user_rate`（null→0）、`log1p_price_latest`、`days_since_first_seen`、`days_since_last_seen` | `gold_ga4_item_catalog` → Redis `feat:item` |
| 交互（4） | `i2v_cos_user_item`（user_vec·item_vec cosine；任一缺→0）、`weighted_hist_interaction`（該 user 對該 item 的 Σ W×count，多數為 0）、`seed_same_category`（候選類別 == user top 加權類別）、`recall_src`（i2v=0/sem=1/pop=2；多路命中取最小） | 線上組裝計算 |
| rt（5） | `rt_views_1h`、`rt_carts_1h`、`rt_events_30m`、`rt_item_matches_top_cat`（候選類別==`top_cat_1h`）、`has_rt`（0/1 旗標） | Redis `feat:user:rt`（即時層寫入）；**訓練時由 `silver.ga4_events` point-in-time 重算**（該 user 該請求時點前 1h/30m 的事件窗）——training-serving 一致性由「同一定義、兩個計算面」保證，缺席（Flink 未部署/TTL 過期）→ 全 0 ＋ `has_rt=0`，模型把 rt 當可缺特徵學 |

### 5.2 訓練資料構造（時間切分防洩漏）

- **query group = (user_pseudo_id, 訓練 label 窗)**：取 label 窗（2021-01-04～01-17）內有互動的 user；每個 user 一個 group。
- **候選 = eval-window 召回**（i2v `eval` artifact ＋語意＋熱門，特徵窗資料跑 §4.5 融合，top 200）；**grade** = 該 user 在 label 窗對該候選 item 的最高漏斗階段 g（§3），未互動候選 = 0。全 0 group（召回全 miss）剔除並記剔除率（诚实 metadata）。
- rt 特徵 point-in-time：以該 user label 窗首個事件時點為模擬請求時點回算。
- 匯出 parquet：host `dvc repro`（`ml/reco/dvc.yaml`：`export → train_i2v → embed_semantic → build_candidates → build_ltr_dataset → train_ranker → evaluate`）；排程走 KPO 同 entrypoint 寫 `s3://ml-datasets/dataset=reco_ltr/exported_at=<ISO>/`（沿 P2 §1③ DVC=離線可重現層分工）。

### 5.3 訓練、gate、Registry

- `LGBMRanker(objective="lambdarank", n_estimators=400, learning_rate=0.05, num_leaves=63, min_child_samples=20, label_gain=[0,1,3,7,15], random_state=42)`；`fit(X, y, group=…, eval_set=…, eval_group=…, eval_at=[5,10], callbacks=[early_stopping(50)])`。
- **baseline 兩個同 run 附帶**（沿 P2 §5 防「為什麼不用簡單解」）：①加權熱門排序（無模型）②召回 RRF 融合分直接排序。
- **評估（test：特徵窗 ≤01-17 / label 窗 01-18～01-31）**：`ndcg@10`（主）、`hit@10`、`recall@10/@50`、`MAP@10`——`evaluate.py` 自寫（k 級集合運算 ~60 行，不為 4 個指標拖評估框架），寫 `ml.reco_eval_metrics(eval_date date, model text, variant text, metric text, k int, value double precision, PK(eval_date, model, variant, metric, k))`，同步 log MLflow。
- **晉升閘門（自動 → `@staging`）**三條全過（沿 P2 §5 三條結構）：①`ndcg@10 ≥ 0.15`（絕對地板，實跑後校準進 params）②`ndcg@10 >` 加權熱門 baseline（相對地板——LTR 必須贏過無模型解）③若 `@prod` 存在：同 test 窗重評 ≥ prod − 0.02。experiment `reco_ltr`、registered model **`reco-ranker`**、alias `@staging`/`@prod`（人工 `make promote-reco-ranker VERSION=n`，四步腳本沿 P2 §7：smoke 重評→掛 alias→mc 複製 `s3://ml-models/reco-ranker/v<n>/`→yq bump `storageUri` + commit）。MLflow artifacts：`model.bst`、`feature_schema.json`、**`reference_stats.json`**（訓練請求特徵分佈 10-bin 直方，§10 drift PSI 的比較基準，沿 P2 §5 同款）、特徵重要度圖。

### 5.4 KServe serving（沿 P2 §6 manifest 形狀）

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: reco-ranker
  namespace: ml
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  predictor:
    serviceAccountName: kserve-s3-sa          # 複用 P2 §3.5 Secret/SA，零新憑證
    minReplicas: 1
    model:
      modelFormat: {name: lightgbm}           # KServe 內建 lightgbm runtime
      protocolVersion: v2
      storageUri: s3://ml-models/reco-ranker/v1/   # promote 腳本 yq bump 唯一落點
      resources:
        requests: {cpu: "100m", memory: "256Mi"}
        limits:   {cpu: "1",    memory: "512Mi"}
```

模型檔 = booster `model.bst`（text 格式）放版本目錄（lightgbm runtime 吃 .bst；payload 形狀 §15 實查 1）。in-cluster 呼叫 `http://reco-ranker-predictor.ml.svc.cluster.local/v2/models/reco-ranker/infer`（raw 模式 predictor Service 名 §15 實查 2）；外部 demo URL `reco-ranker-ml.localtest.me`（domainTemplate 沿 P2 §3.3）。

---

## 6. ★ 接縫 A：Redis feature/候選 schema（**本 spec 是單一真源**——即時 Flink 層引用本節，不得 fork）

### 6.0 全域約定

- **單一 Redis**：`reco-redis.ml.svc:6379`，db 0，AUTH 走 Secret（§12）。
- **key 命名** = `{namespace}:{entity}[:{qualifier}]`，namespace ∈ `feat|cand|meta`。
- **value 編碼**：Hash 純量欄一律 UTF-8 十進位字串（Redis 原生慣例）；向量欄 = **float32 little-endian raw bytes**（64 維 = 256 bytes，讀側 `numpy.frombuffer`）；清單類 = minified JSON UTF-8 字串。
- **TTL 政策**：離線鍵**無 TTL**（生命週期由批次全量覆寫管理——靜態資料集下手動刷新，TTL 過期只會把好資料變降級，是自傷）；**rt 鍵 TTL 7200s**（即時特徵天然易腐，過期即回離線基線）。maxmemory 護欄見 §12。
- **寫入者矩陣**：`redis_load.py`（離線批次）寫 `feat:user`/`feat:item`/`cand:*`/`meta:*`；**Flink sink 只寫 `feat:user:rt:*`**（唯一即時寫入面；at-least-once + HSET 覆寫冪等，對齊 realtime brief 傾向 6）；reco-service **唯讀**。
- **版本協商**：讀寫雙方啟動時檢查 `meta:reco:schema_version`，不符 → fail-fast（服務拒起、Flink job 拒提交）。加欄 = additive（Hash 新 field 不破舊讀者）；改語意/刪欄 = bump version ＋ 雙方同步升級。

### 6.1 `feat:user:{user_pseudo_id}` — Hash（離線 user 特徵；寫入者 redis_load，無 TTL）

| field | 編碼 | 定義 |
|---|---|---|
| `recency_days` | int str | `gold_ga4_user_rfm.recency_days`（null→`-1` 哨兵，讀側轉窗長補值） |
| `orders_count` / `sessions_count` / `active_days` / `distinct_items_viewed` | int str | 同名 RFM 欄直投 |
| `monetary_total` | float str | 同名欄 |
| `top_categories` | JSON `[{"c":"Apparel","w":123.0},…]` | W 加權互動分 top-3 類別 |
| `recent_items` | JSON `[{"i":"<item_id>","w":8.2,"t":1611964800000},…]` | W×exp(−Δdays/14) 加權分 top-10 item（召回 seed；t=最後互動 epoch ms） |
| `user_vec` | bytes（float32 LE ×64） | normalize(Σ W(event)·exp(−Δdays/14)·i2v_full(item))；足跡全在 min_count 淘汰名單 → field 缺席 |
| `batch_id` / `updated_at` | str / ISO str | 灌注批次自述 |

### 6.2 `feat:user:rt:{user_pseudo_id}` — Hash（**即時特徵；寫入者 = Flink sink，TTL 7200s**）

即時層 Flink 每次視窗觸發：`HSET` 整組 mapping ＋ `EXPIRE 7200`（key 級 TTL，不用 Redis 8 hash-field TTL——降低對 server 版本語意的耦合，且整組特徵同生共死語意正確）。

| field | 編碼 | 定義（事件時間語意，Flink 端計算） |
|---|---|---|
| `views_1h` | int str | 近 60 分鐘 `view_item` 事件數（滑窗） |
| `carts_1h` | int str | 近 60 分鐘 `add_to_cart` 事件數 |
| `events_30m` | int str | 近 30 分鐘漏斗事件總數（session 活躍度） |
| `top_cat_1h` | str | 近 60 分鐘 view 次數最高的 `item_category`（平手取字典序小，決定性） |
| `top_cat_views_1h` | int str | 上欄的次數 |
| `last_item_id` / `last_event_name` | str | 最後一個漏斗事件 |
| `last_event_ts_ms` | int str（epoch ms） | 同上事件時間 |
| `rt_updated_at_ms` | int str（epoch ms） | sink 寫入處理時間（監控 lag 用） |

### 6.3 `feat:item:{item_id}` — Hash（item 特徵；寫入者 redis_load，無 TTL）

| field | 編碼 | 定義 |
|---|---|---|
| `item_name` / `item_category` | str | catalog 直投（理由生成的事實源） |
| `price_latest` | float str | 同名欄 |
| `users_viewed` / `users_purchased` / `units_sold` | int str | 同名欄 |
| `view_to_cart_user_rate` / `view_to_purchase_user_rate` | float str（null→`-1` 哨兵） | 同名欄 |
| `first_seen_date` / `last_seen_date` | ISO date str | 同名欄 |
| `item_vec` | bytes（float32 LE ×64） | i2v_full 向量（交互特徵用；長尾缺席） |
| `batch_id` / `updated_at` | str | 批次自述 |

### 6.4 候選鍵 — String（minified JSON；寫入者 redis_load，無 TTL）

| key | value 形狀 | 內容 |
|---|---|---|
| `cand:i2v:{item_id}` | `[{"i":"<item_id>","s":0.83},…]`（≤50，s=cosine，降序） | item2vec 相似候選 |
| `cand:sem:{item_id}` | 同上 | 語意相似候選 |
| `cand:pop:global` | 同上（≤100，s=W 加權熱門分 min-max 正規化） | 全域熱門 |
| `cand:pop:cat:{item_category}` | 同上 | 類別熱門（category 原字串，含空格照用——Redis key 無此限制） |

### 6.5 `meta:reco:*` — String（無 TTL）

`meta:reco:schema_version`＝`"1"`；`meta:reco:batch`＝`{"batch_id":"…","loaded_at":"<ISO>","source_anchor":"2021-01-31","users":…,"items":…}`（灌注自述，驗收與 debug 用）。

### 6.6 離線＋即時合併規則（線上讀路徑；三方共識的「讀」半邊）

1. 一次 pipeline（redis-py `pipeline()`，2 RTT 內）：`HGETALL feat:user:{id}` ＋ `HGETALL feat:user:rt:{id}` ＋（seed 決定後）`MGET cand:*` ＋ 批次 `HGETALL feat:item:*`。
2. **兩鍵欄位集合由 schema 設計保證不相交**（離線欄 vs rt 欄零同名）→ 合併 = 簡單 union，**不存在覆蓋衝突**；rt key miss/過期 → rt 特徵全 0 ＋ `has_rt=0`（模型已學會此缺席模式，§5.1）。
3. `feat:user` miss（冷啟 user）→ 跳過個人化召回，走熱門路（rt 有 `top_cat_1h` 則類別熱門優先）＋ `degraded_paths+=["cold_user"]`。
4. 讀延遲預算：Redis in-cluster RTT 毫秒級、pipeline 化後特徵/候選讀取 **p99 < 50ms**（brief 的 <50ms 落在此段；§14 負載測試以 `stage=features` histogram 佐證）。

**記憶體帳（誠實）**：users ~27 萬 × (feat:user ~1KB) ≈ 270MB ＋ items 數千 × (feat + cand×2) ≈ 20MB ＋ pop 鍵忽略不計 → 峰值 ~300MB，`maxmemory 768mb` 有 2.5× 裕度（§12）。

---

## 7. 線上服務層：reco-service（決定）

| 項目 | 決定 |
|---|---|
| 形狀 | FastAPI（沿 P2 rag-service 模式）：k8s Deployment 1 replica、ingress `reco.localtest.me`、ServiceMonitor。 |
| API | `POST /recommend {user_pseudo_id, k?=10, include_reason?=false, exclude_purchased?=true, variant?="full"}` → `{items:[{item_id, item_name, item_category, score, recall_sources[], reason?}], degraded_paths[], has_rt, latency_ms, timings{recall,features,rank,reason}, model_version, schema_version}`；`variant ∈ {"full","pop"}`（`pop`=加權熱門 baseline 臂，A/B 重放與對照 demo 用，§9.2）；`GET /healthz`（Redis PING ＋ KServe readiness ＋ PG 連線三子檢查）；`GET /metrics`。 |
| 內部模組（可切分邊界） | `recall.py`（`RecallRouter.get_candidates(user_ctx) -> list[Candidate]`：seed 取 `recent_items`＋`last_item_id`(rt)，fan-out `cand:*`，RRF 融合 ≤200）→ `features.py`（`FeatureAssembler.assemble(user_ctx, candidates) -> ndarray`，RECO_FEATURE_SCHEMA 斷言）→ `ranker_client.py`（`RankerClient.rank(matrix) -> scores`，KServe v2 infer，timeout 2s）。三介面即未來微服務切分線，合約已定、切分 = 搬運不重設計。 |
| 排序降級 | KServe 不可達/逾時 → 以 `weighted_hist_interaction`＋RRF 融合分排序（無模型降級），`degraded_paths+=["ranker_down"]`——不 500、誠實回報。 |
| Redis 降級 | Redis 不可達 → 回服務啟動時從 Postgres 快照載入的 in-memory 全域熱門 top100，`degraded_paths+=["redis_down"]`。單機 Redis（§1⑤）的單點由此兜底，README 記為刻意設計。 |
| 理由 | `include_reason=true` → 對 top-3 items 走 §8 LangGraph 圖（線上生成 = 本地 demo 面；批次預生成才是前端資料源）。 |
| Prometheus | `reco_requests_total{outcome=ok\|degraded\|error}`、`reco_request_duration_seconds{stage=recall\|features\|rank\|reason}`（histogram）、`reco_redis_hits_total{kind=feat_user\|feat_rt\|cand\|feat_item}` / `reco_redis_miss_total{kind}`、`reco_degraded_total{path}`、`reco_candidates_size`（histogram）。 |

---

## 8. 推薦理由生成（複用 P2 LangGraph CRAG 圖範式；決定）

### 圖結構（LangGraph 1.2.8 `StateGraph`，沿 P2 §9 形狀——retrieve 換成特徵組裝、grade 換成事實充足性檢查）

```
START → assemble_facts → grade_facts ──(充足)──→ generate → verify ──(過)──→ END
                              │                              │
                              └─(不足)→ template_reason      └─(幻覺)→ template_reason → END
```

| 節點 | 行為 |
|---|---|
| `assemble_facts` | 從 Redis/PG 拉**結構化真實特徵**：item（name/category/price/users_viewed/漏斗率）＋召回來源事實（「與你互動過的 {seed_item_name} 的 i2v/語意相似，cosine=s」「{category} 類熱門第 n 名」）＋ user 足跡摘要（top_categories）。**LLM 只拿得到這張事實清單，拿不到任何自由文本語料**。 |
| `grade_facts` | 純程式檢查（非 LLM）：必要欄（item_name、至少一條召回來源事實）齊 → 充足；否則直接走模板。 |
| `generate` | prompt = **`prompts:/reco-reason@prod`**（MLflow Prompt Registry，沿 P2 §10）：中性口吻（portfolio 展示，非露露）、繁中一句話 ≤60 字、只准引用事實清單、禁編造數字與形容詞級宣稱。LLM = **Ollama `qwen3.5:9b` host 預設 / Gemini `gemini-2.5-flash` fallback**（`ollama-host.ml.svc` ExternalName 接線與 provider 切換沿 P2 §9，零新接線）。 |
| `verify` | **anti-hallucination 驗證器（純程式）**：①理由中出現的商品名/類別字串必須 ∈ 事實清單字面值 ②理由中出現的每個數字（regex 抽取）必須 ∈ 事實數字集（±四捨五入容差）③長度/語言檢查。違者退 `template_reason`。 |
| `template_reason` | 規則模板降級（誠實可用，非 LLM）：「與你瀏覽過的 {seed} 同為 {category} 類的相似商品」／「{category} 類熱門商品」。`degraded=true` 如實標。 |

State（TypedDict）：`item_id, facts, facts_ok, reason, verified, degraded, provider, token_usage, timings`。

**批次預生成**（開放問題 8 落地）：`make gen-reco-reasons`（host 跑，走完整圖，Ollama 零成本）：全域熱門 top50 ＋ 相似商品展示集（§11 挑選的 seed×top10）＋ 分群代表 top10×4 群 → 寫 `ml.reco_reasons(id bigserial PK, subject_type text CHECK IN ('similar','popular','segment'), subject_id text, item_id text, reason text, facts jsonb, provider text, degraded boolean, generated_at timestamptz, UNIQUE(subject_type, subject_id, item_id))`——冪等鍵防重跑膨脹；`facts` 欄保留生成當下事實快照（可稽核：理由能對回事實）。

---

## 9. A/B（事件重放）＋離線評估（決定）

### 9.1 離線評估

§5.3 已定：`ml.reco_eval_metrics` 表、hit@k/ndcg@k/recall@k/MAP@10、時間切分 test = 後 14 天、variant 維度（`ltr` / `pop_baseline` / `rrf_baseline` ＋單路 `recall_i2v_only`/`recall_sem_only` 的 recall@200 對照——各召回路貢獻可比）。

### 9.2 A/B 事件重放框架

| 項目 | 決定 |
|---|---|
| 流量源 | test 窗（2021-01-18～01-31）`silver.ga4_events`，按 session 重放。**誠實標註**：所有產出（表/匯出 JSON/前端）帶 `traffic_type: "labeled_event_replay"` 常數欄——非真線上流量、使用者不曾看到推薦、hit 是反事實命中代理。 |
| bucket 切分 | `crc32(user_pseudo_id) % 100`：0–49 → arm A、50–99 → arm B（決定性、可重現、user 級一致）。 |
| 兩臂 | **A = 完整管線**（三路召回＋LTR）；**B = 加權熱門 baseline**（業界標準對照——證明個人化的增量）。兩臂都經 reco-service 真 HTTP 呼叫（B 走 `?variant=pop` 內部旗標）→ 重放同時就是線上服務的真負載。 |
| 請求模擬 | 每個 session 的**首事件時點**發一次推薦請求（k=10）；特徵凍結在 anchor 2021-01-17 的離線灌注（重放前 `redis_load --anchor 2021-01-17`），**rt 特徵關閉（has_rt=0）**——rt 對照效果屬即時層 spec 的實驗，本層不混因子。 |
| 主指標 | **session hit rate**：該 session 剩餘事件中實際互動的 item ∈ 推薦 top10 的 session 比例（點擊代理）；次指標 = purchase-hit rate（轉換代理）、ndcg@10（以 session 實際互動 grade 計）。 |
| 護欄指標 | p99 延遲 ≤ 300ms、`degraded_paths` 率 ≤ 10%、KServe 錯誤率 ≤ 1%——重放中任一超標 = 重放 DAG fail（護欄可執行，非敘述）。 |
| 停止規則 | **固定樣本**：全 test 窗重放一輪即停（重放的誠實形狀——樣本天然有界，不做序貫窺視）；報告 two-proportion z-test 的 p 值與 95% CI（`replay.py` 自寫 ~20 行，不拖 scipy 之外的統計庫；scipy ml-batch 已有）。 |
| 產出表 | `ml.reco_ab_results(arm text, user_pseudo_id text, session_id bigint, requested_at timestamptz, recommended jsonb, hit_any boolean, hit_purchase boolean, ndcg double precision, latency_ms int, degraded boolean, replay_id text, PK(replay_id, arm, user_pseudo_id, session_id))`；`ml.reco_ab_summary(replay_id text, arm text, sessions bigint, hit_rate, purchase_hit_rate, ndcg_mean, p95_latency_ms, p_value, ci_low, ci_high, traffic_type text DEFAULT 'labeled_event_replay', created_at, PK(replay_id, arm))`。 |

---

## 10. 重訓 DAG ＋ drift（沿 P2 §7 慣例；靜態資料的誠實形狀）

| DAG | schedule | 任務鏈 | 說明 |
|---|---|---|---|
| `reco_build_artifacts` | **None（手動）** | `build_i2v → build_semantic → build_candidates → build_user_features → load_redis → validate_redis` | 靜態歷史資料集下「每日重算」是資料謊言（與地基 §1① 判斷同源、方向相反的第三例：mostPopular 禁 catchup、GA4 回放要 catchup、reco 離線物**不排程**——README 敘事點「排程形狀取決於資料源語意」）。`validate_redis` 斷言 §6.5 meta、抽查 key 存在與 schema_version。 |
| `reco_retrain` | None（手動/drift 觸發） | `export_ltr_dataset → train_and_gate → notify` | 沿 P2 §7 三段形狀；過閘自動掛 `@staging`，`@prod` 人工（GitOps 純度，同 P2 論證）。 |
| `reco_ab_replay` | None（手動） | `replay_ab → summarize → drift_check` | drift 掛重放尾而非每日排程——靜態資料集沒有每日新流量，「每日 drift」會永久靜止；**drift 的觸發面 = 每次重放/演示流量之後**（誠實）。 |

**drift 計算**（`drift_check`，寫既有 `ml.ml_drift_metrics` 表 additive `model='reco-ranker'` 列，沿 P2 §7 PSI 模式）：①重放期間請求特徵分佈 vs 訓練 `reference_stats.json` 的每特徵 PSI ②重放 hit@10 vs 訓練時離線 hit@10 的退化幅度。觸發 `(PSI>0.2 特徵數 ≥ 2) OR (hit@10 退化 > 20%)` → `TriggerDagRunOperator(reco_retrain)`。**演示旋鈕**：`replay --date-range` 限縮重放窗（如只重放最後 3 天，聖誕後行為位移）→ PSI 真的動 → 告警/重訓鏈路現場可演（README 註明演示手段，同 P2 §7 姿態）。Prometheus 經既有 postgres-exporter 自訂查詢 additive：`reco_feature_psi{feature}`、`reco_replay_hit_rate{arm}`、`reco_table_rows{table}`。

---

## 11. P4 匯出 ＋ 前端展示頁 ＋ MCP（接縫 D：additive-only，不動既有 11 檔/10 工具/8 頁）

### 匯出（exporter `datasets.py` additive ＋4 條目；P4 §4 政策內合法動作）

| 檔案 | 來源表 | 內容形狀 |
|---|---|---|
| `reco_similar.json` | `ml.reco_candidates` JOIN catalog JOIN `ml.reco_reasons(subject_type='similar')` | 展示集 seed 20 個（全域熱門 top20 當 seed）× 兩路各 top10：`{seed:{item_id,name,category}, similar:[{item_id,name,category,source,score,reason?}]}` |
| `reco_popular.json` | `cand:pop` 的 PG 正本（`ml.reco_candidates seed_type IN ('pop_global','pop_cat')`）＋ reasons | 全域 top50 ＋ 每類 top10，帶理由 |
| `reco_segments.json` | `ml.reco_segment_recs` ＋ reasons | 4 展示分群 × top10 ＋分群定義文字 |
| `reco_eval.json` | `ml.reco_eval_metrics` ＋ `ml.reco_ab_summary` | 離線指標（variant×metric×k）＋ A/B 兩臂摘要（含 `traffic_type` 誠實欄與 p 值） |

統一信封/穩定性政策/meta.json datasets 條目全沿 P4 §3-4（加檔=合法 additive）。**展示分群**（`segments.py`，寫 `ml.reco_segment_recs(segment text, rank int, item_id text, score double precision, batch_id text, PK(segment, rank))`）：`buyer_repeat`（orders≥2）/`buyer_once`（=1）/`browser_active`（0 單且 active_days≥3）/`cold`（其餘），群代表推薦 = 群內 W 加權熱門 top20 → 以群質心 user 特徵過 LTR → top10。**與 P7 邊界**：此為展示用簡化分群，P7 DMP 標籤體系落地後 additive 替換群定義，`segment` 字串 key 介面不變（跨 spec 接縫註記，P7 brief 可引用）。

### 前端 `/reco` 頁（P4 第 9 頁，additive；Recharts/CSS Modules/RegionTabs 慣例沿 P4 §5，本頁無 region 維度不掛 RegionTabs）

區塊：①相似商品瀏覽器（挑 seed → 兩路相似並排＋理由卡）②熱門榜（全域/類別 tab）③分群代表推薦 ④離線評估圖（variant×ndcg@10/hit@10 BarChart）⑤ A/B 重放結果卡（兩臂 hit rate ＋ CI ＋ p 值，**頂部誠實 banner：事件重放非真流量**）⑥線上能力佐證區（負載測試截圖/GIF ＋「線上服務在叢集內、本站為批次匯出」誠實文字）。

**三層說明式 UI（硬性交付）**：新建 `frontend/src/components/explainers/` 三個零依賴 client 元件——`InfoTooltip`（ⓘ popover：設定值語意，如「k=10 指每次推薦返回的商品數」）、`ChartCaption`（圖下常駐小字：視覺語法＋單行公式，如「hit@10 = 推薦 top10 命中該 session 後續實際互動的 session 比例」）、`Explainer`（`<details>` 摺疊：**定義類 `open` 預設展開**（什麼是召回/排序/hit@k——強迫先看懂分類）、**方法論類預設收合**（item2vec 怎麼訓、A/B 重放怎麼做、為何非真流量））。語意文字直接引用地基 Gold marts dbt description（§5 已備好的「這是什麼」素材）。元件供 P7/即時層頁面複用；既有 8 頁回填屬 P4 迭代不在本 spec（真空由 NORTH_STAR 記錄，本 spec 只交付元件＋本頁用好用滿）。

### MCP（additive ＋2 工具，讀新 JSON 檔，沿 P4 §7 慣例）

`get_recommendations(seed_item_id: str | None, segment: str | None, limit: int = 10)`（讀 reco_similar/reco_segments/reco_popular；docstring 明講「批次預產推薦＋理由，非即時線上推論」）；`get_reco_metrics()`（讀 reco_eval.json；docstring 含「A/B 為事件重放非真流量」）。

---

## 12. 部署形狀：Redis manifest ＋ Secrets ＋ CI ＋ 監控

### Redis（`ml/reco/redis/k8s/`，plain kustomize，wave 12）

- **Deployment**（replicas 1，`redis:8.4.4`，args `["redis-server","/etc/redis/redis.conf","--requirepass","$(REDIS_PASSWORD)"]`，env from Secret）＋ **PVC 1Gi**（RDB 落點）＋ **Service** `reco-redis.ml.svc:6379` ＋ **ConfigMap `redis.conf`**：

```
maxmemory 768mb
maxmemory-policy allkeys-lru      # 最後護欄：記憶體壓力逐出 → 服務走 §7 降級路徑，不 OOM
save 900 1                        # RDB 快照（重啟免全量重灌）；appendonly no（快取語意，AOF 是過度持久化）
```

- 資源 requests 100m/896Mi、limits 500m/1Gi。readinessProbe `redis-cli -a $REDIS_PASSWORD ping`。
- **licensing 誠實註記（ADR）**：Redis 8.x 為 RSALv2/SSPLv1/**AGPLv3** 三授權，AGPLv3 為 OSI 認可；本專案叢集內自用非對外提供服務，無散布義務問題。替代品 Valkey（BSD）淘汰理由：redis-py 一等支援、官方 image、JD 關鍵字識別度——非技術差異，如實記錄。
- **單機 ADR**：無 Sentinel/Cluster（demo 規模的 HA 是儀式）；資料可由 `reco_build_artifacts` 從 PG 正本全量重建（Redis 是投影不是 SoR），失聯期間 §7 降級。

### Secrets（`make reco-secrets`，命令式冪等，沿 P0 §7/P2 §3.5 姿態）

| Secret | ns | 內容 |
|---|---|---|
| `reco-redis-auth` | ml、airflow | `REDIS_PASSWORD`（redis server、reco-service、redis_load、Flink sink（即時層）四方共用；即時層引用不另建） |

（KServe S3/`lakehouse-postgres-ml`/`gemini-api` 全複用 P2 既有，零新增。）

### CI（沿既有模式）

| workflow | 觸發 paths | 內容 |
|---|---|---|
| `ml-batch-ci.yaml`（既有，改） | paths ＋= `ml/reco/offline/**`；test ＋= ml_reco pytest；Dockerfile ＋裝 `ml_reco`＋`lightgbm==4.6.0 gensim==4.4.0 redis==8.0.1` | 既有 image 迴圈 |
| `reco-service-ci.yaml`（新） | `ml/reco/service/**`（不含 k8s/） | ruff ＋ pytest → build `…/reco-service` → bump `ml/reco/service/k8s/kustomization.yaml`（P0 hello 同款） |

### 監控（`platform/monitoring/reco/`）

Grafana dashboard ×1（reco：QPS/p95 分 stage/Redis hit-miss 比/降級率/candidates size/PSI/兩臂 hit rate）；PrometheusRule：`RecoServingDown`（up==0，critical）、`RecoDegradedRateHigh`（degraded/total 1h > 0.3，warn）、`RecoRedisMissRateHigh`（feat_user miss 比 > 0.5 持續 30m，warn——灌注斷檔哨兵）、`RecoFeatureDriftHigh`（PSI>0.2 特徵 ≥2，warn）。

---

## 13. 取材界線表（進化非複刻：取什麼邏輯 vs 重造哪個工程層）

| 課程素材（brief §課程演算法地圖） | 取的邏輯 | 重造的工程層 |
|---|---|---|
| item2vec（word2vec on 行為序列） | session 序列當句子、skip-gram 學 item 共現語意 | 課程手刻/Spark 版 → **gensim 官方庫**（validated library）；向量落 **pgvector**（非課程 Faiss/LSH——檢索基建複用 P1 Postgres）；DVC/MLflow 版本化與 eval/full 雙 artifact 防洩漏（課程無） |
| LTR pointwise-pairwise-listwise | lambdarank graded relevance ＋ group 結構 | 主線收斂 LightGBM 官方 `LGBMRanker`（非課程自建 GBDT/FTRL）；grade 表接自家漏斗語意（§3）；gate/alias/GitOps 晉升鏈（課程無） |
| Redis 特徵快取／召回-排序切分 | online feature store 概念、兩階段架構、候選預算 | schema 升級成**欄位級跨 spec 合約**（接縫 A，即時層引用）；單 service 右尺寸（拒課程微服務拆分展演）；k8s manifest/GitOps/降級路徑全自持 |
| Airflow＋MLflow 重訓 | 重訓觸發閉環概念 | 沿 P2 §7 既有慣例（staging 自動/prod 人工），drift 觸發面改掛重放後（靜態資料誠實形狀，課程假設持續流量） |
| LLM 生成推薦理由 | 「推薦＋自然語言理由」產品形狀 | LangGraph 圖＋**程式化 anti-hallucination 驗證器**＋模板降級＋Prompt Registry（課程直呼 LLM 無防護）；理由對回 `facts` 快照可稽核 |
| gRPC-ONNX serving | —（不取） | KServe v2 protocol 已覆蓋此職務，不另開 gRPC/ONNX 出口（一工一具） |

---

## 14. 測試策略 ＋ 端到端驗收

### 單元/CI 層（每步可測）

| 層 | 測試 |
|---|---|
| `sequences.py`/`i2v.py` | 固定 fixture 事件 → 序列構造斷言（session 切分/null fallback/連續去重/≥2 過濾）；Word2Vec 以小語料訓練斷言向量維度與決定性 seed |
| `features.py` | RECO_FEATURE_SCHEMA 黃金樣本（固定輸入→固定向量+欄序斷言）；rt point-in-time 回算與 serving 定義等價測試（同一事件 fixture 兩路計算結果一致——training-serving skew 守門）；哨兵值（-1）與 null 補值路徑 |
| `redis_load.py`/`redis_client.py` | fakeredis fixture：§6 每個 key pattern 的欄位級寫/讀 round-trip；向量 bytes round-trip（frombuffer 還原）；schema_version 不符 fail-fast；TTL 只掛 rt 鍵斷言 |
| `recall.py` | RRF 融合純函式；冷啟路徑；已購剔除 |
| LTR | grade 對映/label_gain/group 構造斷言；時間切分洩漏守門（label 窗樣本的特徵不含 label 窗事件——fixture 級斷言）；gate 三條件真值表 |
| `replay.py` | bucket 決定性；hit 判定；z-test 數值對照已知案例；護欄超標 fail 路徑 |
| reason graph | fake LLM 注入（沿 P2 §14 LangGraph 測試模式）：facts 不足→模板、幻覺（編造數字/名稱）→verify 攔截退模板、provider fallback、字面驗證器單元測試 |
| service | httpx TestClient：/recommend 合約形狀、Redis down→in-memory 熱門降級、KServe down→融合分降級、degraded_paths 如實 |
| DAG/dbt | DagBag 零錯誤；三 DAG schedule=None 守門；exporter 新 4 dataset 的黃金測試（含 absent 路徑，沿 P4 §9） |
| 前端/MCP | check-data.mjs 涵蓋 4 新檔；explainers 元件 render 測試（定義類 open 預設斷言）；MCP ＋2 工具 fixture 測試 |

### `make reco-verify`（`scripts/verify-reco.sh`；前置 = 地基 `make ga4-verify` 綠＋回放收斂、P2 底盤在位、`make reco-secrets`）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | ArgoCD reco-redis/reco-service 收斂；PVC Bound | `Synced+Healthy` |
| 2 | 觸發 `reco_build_artifacts` → 全綠 | pgvector 兩表 count>0＋HNSW 索引存在；`redis-cli` 抽查 `HGETALL feat:user:<樣本>`（欄位齊）、`GET cand:pop:global`（JSON 可解析）、`meta:reco:schema_version`=1 |
| 3 | 冪等 | 重跑 build DAG → PG 表列數與 Redis `DBSIZE` 不膨脹 |
| 4 | 訓練閉環 | 觸發 `reco_retrain` → MLflow `reco_ltr` run＋gate 過→`reco-ranker@staging`；ndcg@10 > 加權熱門 baseline（gate ②的實跑證明） |
| 5 | 晉升＋serving | `make promote-reco-ranker` → InferenceService Ready → v2 infer 200 回分數 |
| 6 | 線上端到端 | `POST reco.localtest.me/recommend` → k=10、recall_sources 非空、latency_ms 有值；`include_reason=true` → top-3 帶理由且理由字串中的名稱/數字 ∈ facts（anti-hallucination 實證） |
| 7 | 降級實證 | scale reco-redis 到 0 → /recommend 仍 200＋`degraded_paths=["redis_down"]`；復原後 kill KServe pod → `ranker_down` 降級 |
| 8 | rt 合併 | 手動 `HSET feat:user:rt:<樣本> views_1h 5 …`＋`EXPIRE 7200` → /recommend 回 `has_rt: true`（接縫 A 讀路徑可用性——Flink 未到位前的模擬寫入驗證） |
| 9 | A/B 重放 | 觸發 `reco_ab_replay` → `ml.reco_ab_summary` 兩臂＋p 值＋`traffic_type='labeled_event_replay'`；護欄未破 |
| 10 | 負載測試（<50ms 佐證） | `make reco-loadtest`（50 併發×60s）→ 報表：`stage=features` p99 < 50ms、端到端 p95 ≤ 150ms、成功率 >99%；截圖存 `frontend/public/architecture/` |
| 11 | 匯出＋前端 | export DAG 後 `latest/` ＋4 檔；`cd frontend && npm run build` 綠；`/reco` 頁三層說明元件呈現（定義類展開） |
| 12 | drift 鏈 | 重放後 `ml.ml_drift_metrics` 有 `model='reco-ranker'` 列；`--date-range` 演示旋鈕跑一輪 PSI 上升可見 |
| 13 | 主線無損 | 既有 11 匯出檔 byte 級不變（除 meta datasets additive 條目）；P4 既有 8 頁 build 綠；YT/GA4 DAG 不受影響 |
| 14 | 憑證紀律 | `grep -rE "requirepass .*[a-zA-Z0-9]{8}|AIza" ml/reco/` 為空（密碼只在 Secret） |

---

## 15. plan 前需實查（設計已收斂，落地校準點，皆帶預設傾向）

1. **KServe v0.19 lightgbm runtime 的模型檔名與 v2 payload 形狀**（傾向：目錄放 `model.bst`（`Booster.save_model` text 格式）、infer 吃 float32 2D tensor 同 sklearn 款；以 `helm show values`＋一次煙囪定案，同 P2 實查 5 手法）。
2. **RawDeployment 下 predictor in-cluster Service 名**（傾向 `reco-ranker-predictor.ml.svc.cluster.local`；kubectl get svc 一眼定案，寫進 service settings 預設）。
3. **gensim 4.4.0 × numpy 2.x × ml-batch image（py3.12 slim）相容**（傾向：manylinux wheel 直裝可用；衝突則 `uv pip compile` 降 gensim 4.3 線，API 面不變）。
4. **redis-py 8.0.1 對 Redis server 8.4 的 RESP3/AUTH 預設**（傾向：開箱即通；`decode_responses=False` 全程 bytes（向量欄需要），讀側自行 decode 純量欄）。
5. **test 窗重放量級**（一條 SQL：test 窗 sessions 數；傾向數萬 session、單機重放 30–60 分鐘；過長則抽樣 50% session 並記錄抽樣率——統計檢定樣本仍充足）。
6. **item2vec min_count=3 的詞表覆蓋率**（傾向 >80% items；偏低降 min_count=2；未覆蓋長尾由語意/熱門路兜底，本就設計在內）。
7. **LTR 絕對地板值校準**（§5.3 的 ndcg@10 ≥ 0.15 是文獻量級預估；首次實跑後把實際 baseline 數字寫回 params.yaml，gate 邏輯不變）。
8. **`pipeline_writer`/`ml_writer` 對 ml.reco_* 新表的權限**（傾向 P2 ml-db-init 的 `ALTER DEFAULT PRIVILEGES` 已涵蓋；缺則 additive GRANT，同 P4 實查 1 手法）。

---

## 16. known-limits（誠實段）＋落地後校驗

**known-limits（README 全列）**：
1. **A/B 是 labeled event-replay**：使用者從未看到推薦，hit 是「後續自然行為落在推薦集」的反事實代理——能證明排序品質與系統能力，不能證明真實 CTR/成效增量（不宣稱）。
2. **靜態歷史資料集**：離線物不排程（§10 論證）；drift 是重放觸發的機制展示，非持續生產流量的真漂移。
3. **Redis 單機單點**：刻意取捨（§12 ADR），失聯走降級路徑；PG 是單一真源可全量重建。
4. **rt 特徵在本 spec 驗收時來自模擬寫入**（驗收 #8）：真 Flink 寫入屬即時層 spec；缺席時模型以 has_rt=0 路徑服務（設計內行為，非故障）。
5. **負載測試數字是本地 kind 單機叢集數字**：佐證架構與延遲量級，非生產容量宣稱。
6. **分群為展示用簡化規則**：P7 標籤體系的前導佔位，介面（segment key）穩定。
7. **重複購買/多樣性（MMR）/序列模型（SASRec 級）**：列進化方向不實作（README 一行各記進化路徑）。

**落地後校驗（對精確度契約 8 條）**：
- ①開放問題 9 題全收斂單一決定（§1 總表），零 TBD/兩案並陳；實查 8 點皆帶預設傾向與判準（§15）。
- ②新 pin 四項（lightgbm/gensim/redis-py/redis image）PyPI/Docker Hub/context7 當日查證（§0）；其餘沿 P2/地基已查證 pin。
- ③資料契約欄位級：Redis schema §6（key/field/編碼/TTL/寫入者矩陣/版本協商，標**接縫 A 單一真源**）、PG 新表 7 張（§4.4/§5.3/§8/§9/§11）、RECO_FEATURE_SCHEMA 22 欄（§5.1）、匯出 4 檔（§11）；上游地基/P2/P4 合約原樣引用勿改。
- ④部署形狀具體：InferenceService manifest 全文（§5.4）、Redis manifest＋redis.conf（§12）、sync-wave 12/13（§2）、DAG×3 形狀（§10）、CI 兩支（§12）、檔案佈局到檔名（§2）。
- ⑤沿用慣例明講：pgvector HNSW=P2 §8.2、KServe manifest/S3 SA=P2 §6/§3.5、MLflow alias+Prompt Registry=P2 §1②/§10、DVC 分工=P2 §1③、drift 表與 PSI=P2 §7、LangGraph 圖=P2 §9、RRF=P2 §9、匯出信封=P4 §3、secret 命令式=P0 §7、DDL loader 持有=P1 §5。
- ⑥進化非複刻：取材界線表 §13 逐素材列界線；資料源只用 GA4 地基 Gold/Silver（公開 sample，area02 零進入）。
- ⑦硬約束貫徹：Redis 唯一新線上元件且職務唯一（線上特徵/候選快取；非 OLTP/排程/佇列——寫入者矩陣鎖死）；離線仍 Postgres+pgvector；排程只 Airflow、agent 只 LangGraph；M4 界線（本垂直全 CPU-feasible 歸 k8s，LLM 理由生成走 host Ollama 既有接線）；拓撲（KServe/Redis 叢集內，前端走匯出合約＋MCP/負載測試/截圖佐證）；additive（地基合約/P4 11 檔/10 工具/8 頁零觸碰）；A/B 誠實標非真流量（常數欄+前端 banner+MCP docstring 三處烙印）；理由 anti-hallucination（程式驗證器+facts 快照可稽核）。
- ⑧每步可測：單元測試分層（§14）、14 步可執行驗收含降級/冪等/rt 合併/負載實證、閘門與護欄全部數字化可斷言。
