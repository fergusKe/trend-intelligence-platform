# 搜尋支柱 design v2（平台側自建進階中文檢索：jieba 分詞 FTS ＋ e5 向量 RRF hybrid ＋ bge-reranker 重排 ＋ 檢索評測 harness；複用 P2b 基建、換 P3 PTT 語料）

> **上游**：[brief v2](2026-07-10-search-pillar-brief-v2.md)（工作合約正本）＋ repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」（自檢見 §15）＋ [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)（binding：§2.2/§2.3/§5/§7/§7.2/§8.2/§10；拓撲鐵律）＋ [P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)（**主複用對象**：§0 pin/§1④ M4 界線/§8 rag_documents＋e5/§9 hybrid RRF/§10 eval 慣例）＋ [P3 ptt-ingest design](2026-07-08-P3-ptt-ingest-design.md)（§6 Silver `ptt_articles` 語料合約）＋ [P6 recommendation design](2026-07-09-P6-recommendation-design.md)（pgvector+e5+RRF 平台範式的邊界互指）＋ [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)（視覺地基、§7 fuse.js）＋ [問 AI design](2026-07-10-ask-ai-design.md)（§0.3 「P2b 無實碼」誠實處理先例、§8 Cloud Run live-demo 形態先例）。
> **取代**：[v1 design](2026-07-10-search-pillar-design.md)（已標 SUPERSEDED）。**沿用的 v1 殘值**：拓撲鐵律落法、fuse.js 站內離線示範全套契約（v1 §5，本檔引用不重寫）、⌘K 邊界句式骨架、live-demo 誠實固定句式、`search_ptt_titles.json` dataset 合約（v1 §5.1）、Opus 揪出的 ptt-search admin 資安（v1 §2 事實 15——本檔 §7 以「新端點零 admin 面＋舊端點不外連」正面解決）。
> **定位（鐵律）**：`/search` 支柱＝**平台側真建的進階中文檢索子系統展示**——P3 PTT 語料上跑 hybrid 檢索（jieba 分詞 FTS ＋ e5 向量 → RRF）＋ cross-encoder rerank ＋ 檢索相關性評測（recall@k/nDCG/MRR 四法對比矩陣＝核心展示品），以 crosscut §7 四件套呈現。**與 P2b（檢索→生成）/P6（向量召回→推薦）同一套 pgvector+e5+RRF 平台範式，本支柱把「檢索品質工程」本身當主體**；ptt-search 降為前身對照敘事。
> **一句話**：新平行語料表 `ml.search_documents`（chunk＋雙 tsv＋HNSW）、三詞彙/向量通道五法對比（raw-FTS／jieba-FTS／vector／hybrid／hybrid+rerank）、LLM-judge pooling 標註集、評測結果與 per-query 對照預產成 `search_*.json` 靜態上頁（3 頁 IA），live-demo＝新建 Cloud Run `search-live`（連 Neon 輕量 PG 跑同一段 RRF SQL＋rerank toggle）。真運算全在叢集/host 離線；前端純靜態。
> 產出日期：2026-07-10。**本階段只出 spec，plan 延後**；`ml/`、`frontend/` 均尚無實作碼，以下全是「建立時即照此」。

---

## 0. 接地與版本查證（2026-07-10 第一手）

### 0.1 版本敏感宣稱（context7／PyPI／官方文件當日查證；沿既有 pin 者不重議）

| 宣稱 | 查證結果 | 來源 |
|---|---|---|
| **sentence-transformers `CrossEncoder`**：`CrossEncoder(model, device='cpu'\|'mps', activation_fn=torch.nn.Sigmoid(), max_length=…)`；`.predict(pairs, batch_size)`／`.rank(query, docs, top_k)` 回 `[{corpus_id, score}]` | ✅ 官方文件 API 面逐項確認（含 device/mps、batch_size、activation_fn 參數）——rerank 層**零新依賴**（sentence-transformers 5.6.0 已在 P2 §0 pin、已進 ml/batch image） | context7 `/websites/sbert_net`（cross_encoder 模型頁＋package reference） |
| **`BAAI/bge-reranker-v2-m3`**：568M 參數多語 cross-encoder（based on bge-m3，含中文）；官方明示 CPU 可跑（`devices='cpu'`）、fp16 加速可選、`normalize=True` sigmoid 到 0–1；備選 `bge-reranker-base` 278M（zh/en，XLM-RoBERTa-base） | ✅ FlagEmbedding 官方 docs 原文（「lightweight, 568M, multilingual, based on bge-m3」）；本設計以 sentence-transformers CrossEncoder 載入（標準 cross-encoder 架構），不引 FlagEmbedding 依賴 | context7 `/flagopen/flagembedding`（bge_reranker_v2 doc＋tutorial 5.2） |
| **pgvector hybrid**：官方 README 明載 hybrid search＝向量＋PG 全文檢索，融合技術點名 **Reciprocal Rank Fusion 或 cross-encoder**；查詢側 `SET hnsw.ef_search`（預設 40）＋ **`hnsw.iterative_scan = 'strict_order'`**（0.8.x；filter 命中率低時自動掃更多索引） | ✅ 本設計的「hybrid RRF＋rerank」正是 pgvector 官方文件點名的正典組合；版本沿 P2 §0 pin **0.8.4** 不重議 | context7 `/pgvector/pgvector`（README hybrid search／HNSW tuning） |
| **jieba 0.42.1**：`jieba.set_dictionary('dict.txt.big')` 官方明示用於繁體中文更佳分詞；`cut_for_search` 搜尋引擎模式；`jieba.initialize()` 顯式預載；純 Python 零編譯 | ✅ PyPI 當日查證 0.42.1（多年穩定版）＋官方 README（context7）——**應用層分詞**的地基 | context7 `/fxsjy/jieba` ＋ PyPI JSON API |
| **Neon（live-demo 輕量 PG）**：官方文件明列 pgvector 支援（最新支援版 ≥0.8.0，可指定版本安裝）、HNSW 索引、`SET hnsw.ef_search` | ✅ 官方 docs 頁當日確認——live 端點可跑與平台同構的 pgvector SQL；確切 extversion＝plan 實查 4 | neon.com/docs/extensions/pgvector（2026-07-10） |
| e5（`intfloat/multilingual-e5-small` 384 維含中文）／pgvector 0.8.4／sentence-transformers 5.6.0／psycopg 3.3.4＋pgvector-python 0.5.0 | 沿 **P2 §0 pin**（2026-07-08 已查證）零翻案 | P2 §0/§8.1 |
| fuse.js 7.4.2／Next 16 `output:'export'`／route groups／Recharts 3／lucide | 沿 **Signal §0 ＋ crosscut §0** 已證 pin，本檔零新增前端依賴 | Signal §0／crosscut §0 |
| FastAPI **0.139** | 沿問 AI design §8 pin（live 端點同形） | 問 AI §8 |
| ptt-search 前身事實 | 本日 spot-check 第一手：`backend/app/api/search.py:68-88` bool 組裝（`multi_match {fields:["title^2","content"]}`＋filter 分離）、`backend/app/es/index.py:10,12` `analyzer: smartcn`——v1 §2 十五條事實表仍有效，本檔僅取前身對照敘事 | 本機唯讀 grep（2026-07-10） |

### 0.2 P2b 複用可行性接地（誠實記錄；沿問 AI §0.3 同款處理）

**實況**：`ml/` 目錄空、`docs/plans/` 空、全 repo `*.py` 無任何 rag/embedding 實碼——**P2b（`ml_rag_index`/`rag_service`）目前只存在於 P2 design 合約，無實碼可 grep**。brief 要求的 `retrieval.py`/`embed.py`/DDL 實作錨今日不可能取得；可鎖的是 **P2 design 的合約錨**，並以「窄介面＋單一真源＋plan 序＋降級路徑」處理：

| 複用面 | P2 design 合約錨（唯讀） | 本 spec 只吃的窄介面 | 複用方式 |
|---|---|---|---|
| e5 embedding＋前綴封裝 | `ml/rag/indexer/src/ml_rag_index/embed.py`（P2 §2 檔案佈局；§8.1「索引側 `passage: `、查詢側 `query: `封裝進 embed.py，呼叫端不可能忘」；雙模式 device `mps→cuda→cpu`） | `embed_passages(texts) / embed_query(q) -> vector(384)`（函式名以實碼為準，plan 實查 1 對齊；語意合約＝前綴封裝＋e5-small＋384 維） | **import 複用**（`ml_search_index` 依賴 `ml_rag_index` 套件）——e5 前綴慣例單一真源，不複製 |
| 語料表 schema 模式 | P2 §8.2 `ml.rag_documents`：`embedding vector(384)`＋`tsv tsvector GENERATED('simple')`＋HNSW`(m=16,ef_construction=64)`＋GIN＋`UNIQUE(…, embedding_model)` 冪等鍵 | schema **模式**（欄型/索引/冪等鍵形狀） | **同構新表**（§2）——不共表、不改 CHECK |
| hybrid RRF 檢索形 | P2 §9 retrieve 節點：pgvector cosine top-40（e5 `query:` 前綴）＋FTS `plainto_tsquery('simple')` top-40 → RRF k=60 取 top-8；自寫 SQL（明拒 vectorstore 抽象）；CJK 誠實註記（simple 不分詞中文） | SQL **形**（雙通道 rank → `Σ 1/(60+r)` 融合）＋參數（top-40/k=60） | **合約複用非 import**——P2b `retrieval.py` 綁 `rag_documents` 表名且屬 rag_service 服務內部，本支柱在 `ml_search_retrieval` 重掛同形 SQL 於 `search_documents`（§4），並以單元測試斷言融合函式數值同構 |
| M4/k8s 執行界線與 backfill 慣例 | P2 §1④：初始 backfill＝host MPS make target、日增量＝k8s KPO CPU、device 自動偵測 | 同款雙模式 | 慣例複用（§10） |
| 評測慣例 | P2 §10：evalset git 版本化＋frozen 語料快照進 DVC＋LLM-judge（Gemini flash temp 0、rubric 版本化）＋MLflow 一 eval 一 run | 同款結構 | 慣例複用（§6） |

**plan 序（鎖定）**：P2b-1 indexer（`ml_rag_index`，至少 `embed.py`）的 implementation plan **先行**於本支柱 plan——search indexer 直接 import。**降級路徑**（僅當 Fergus 明令改序）：`ml_search_index` 暫置同構 `embed.py`（同前綴合約＋同測試），P2b 落地時替換為 import 並刪除，記入 plan 的 debt 清單——預設不走此路。

### 0.3 P3 語料合約接地（欄位級；P3 同樣無實碼——鎖 design 合約）

`lakehouse/` 目錄空——P3 亦未實作；語料合約鎖 **P3 §6 Silver schema**（已鎖合約、additive-only 穩定性政策）：

- **表**：`silver.ptt_articles`（Postgres serving 副本，與 Iceberg 正本同構）；粒度＝一列一文章 `(board, aid)` PK；重爬取最新狀態（推文數會 UPDATE）。
- **本 spec 消費的欄**（P3 §6 全部實存）：`board, aid, url, title, category, author_id, post_ts, post_date, content`（**正文欄——簽名檔/推文區已切除**）, `comments_total/…/comments_score, ingested_at`。
- **量體**（P3 §5 config）：3 看板（Gossiping/Stock/NBA）× `days_back: 2` 日更 → 每日數百~數千篇，累積數月＝萬篇級。
- **plan 期實查 2（帶預設傾向）**：`content` 非空率／字元長度分佈／language 純度（PTT 繁體為主、Gossiping 有貼圖文）。預設傾向：非空率 >95%、長度中位數 200–800 字元、長尾數千字元——chunk 參數 §2 以此設定，實跑後校準。`comments_json` 推文明細 P3 刻意不展平（其 known-limit）——**v1 語料只用正文＋標題，推文語料列進化方向**。

### 0.4 對 P2b/P6 的邊界（不重疊、related 互指）

| | P2b RAG（`/ai-lab`） | P6 推薦（`/reco`） | **搜尋支柱（`/search/*`）** |
|---|---|---|---|
| 語料/資料面 | YouTube 留言＋video_meta（`ml.rag_documents`） | GA4 商品 catalog＋互動（`ml.reco_item_*`） | **PTT 文章正文（`ml.search_documents`）** |
| 檢索的角色 | RAG 生成的前置手段 | 推薦召回的一路 | **主體展示品（檢索品質工程）** |
| rerank | §9 明文淘汰（生成鏈成本判斷，grade 節點已擔負 relevance 過濾） | 無（融合後交 LTR 排序） | **有（品質工程專屬層，§5）** |
| 評測 | hit_rate@8＋LLM-judge faithfulness（答案品質導向） | ndcg@10 等（推薦離線評估） | **檢索相關性四法對比矩陣（§6）** |
| 互指 | registry `related` →「同一 hybrid 基建：檢索→生成」 | `related` →「向量召回用於推薦」 | 兩者皆指（§11） |

三者共用同一「pgvector＋e5＋RRF(k=60)」平台範式、資料面零交集、任何圖表只在一個支柱有正本（crosscut §4 鐵律）。

---

## 1. 關鍵決策總表（brief 8 項全收斂為單一決定；細節在各節）

| # | brief 項 | 決定 | 一句理由 |
|---|---|---|---|
| 1 | 語料表落點＋chunk | **平行新表 `ml.search_documents`**（P2 §8.2 同構模式＋搜尋專屬欄；§2 DDL 欄位級）；PTT 正文 **chunk 800 字元/overlap 100**（沿 P2 §8.2 video_meta 既例），embed 輸入 `passage: {title}\n{chunk}`，檢索後 chunk→文章去重 | 改 `rag_documents` CHECK＝動 P2b 資產違 additive、且污染其 CRAG eval 母體；新表才裝得下分詞欄/過濾欄 |
| 2 | hybrid 管線＋中文分詞 | 沿 P2 §9 形（cosine top-40＋FTS top-40→RRF k=60）over 新表；**CJK 深化＝應用層 jieba 預分詞**（`dict.txt.big` 繁體詞典＋`cut_for_search`），分詞結果落 `content_seg`→`tsv_seg` 第二詞彙通道，查詢側同款分詞——**淘汰 zhparser/pg_jieba**（需重編譯共用 Postgres image＝動 P1/P2 地基）；`ts_rank_cd` 非 BM25 誠實標（§3/§4） | 不碰 DB image 就把「simple 不分詞中文」的 P2b known-limit 變成可量測的修復；分詞器可版本化可測 |
| 3 | rerank | **做**：`BAAI/bge-reranker-v2-m3`（568M 多語 cross-encoder；sentence-transformers `CrossEncoder` 載入＝零新依賴）hybrid top-40 → rerank → top-10；host MPS（評測/showcase）＋Cloud Run CPU（live toggle）；**與 P2b §9 淘汰不衝突明標**（§5 對照表——P2b＝生成鏈成本取捨、本支柱＝檢索品質工程本體且 portfolio 成本紅線不適用）；增益不預設、實測填數（沿 P2c win-rate 誠實紀律） | pgvector 官方文件點名 cross-encoder 為 hybrid 融合正典；「同平台兩處對 rerank 相反決策各自成立」本身是架構判斷力敘事 |
| 4 | 評測 harness | **50 題（LLM 合成 35＋人工 15）× 五法 pooling（各 top-20 聯集）× LLM-judge 分級標註（0–3，Gemini flash temp 0、rubric 版本化）＋人工抽查 κ**；指標 recall@10/nDCG@10/MRR@10 公式進 registry `formula`；**對比矩陣（raw-FTS/jieba-FTS/vector/hybrid/hybrid+rerank × 指標＋p50 延遲）＝核心展示品**，預產 `search_eval_matrix.json`；侷限（pool bias/judge bias/規模）誠實標（§6） | pooling＋graded judge 是 TREC 式標準方法的右尺寸版；50 題是「方法正確、規模誠實」的 demo 平衡點 |
| 5 | live-demo | **新建 Cloud Run `search-live`**（鏡像問 AI §8 形態）**連 Neon 免費層 PG（pgvector）**跑與平台同構的 hybrid RRF SQL＋rerank toggle；**不沿用 ptt-search**（語料是別顆 DB 的另一資料集、無 hybrid/rerank 可示範、admin 無認證未收斂）；新端點**零 admin 面**＝v1 資安發現的正面解法；ptt-search 部署保留（crosscut §8.2）但 v1 不外連（§7） | 「live demo 跑的就是平台同一段 SQL」敘事完整；crosscut §7.2 v1 配置的目標端點修訂已列 Opus 知會（§16.1） |
| 6 | 頁 IA | **3 頁**：`/search`（管線敘事＋三層對照 demo＋前身對照＋評測摘要）、`/search/relevance`（對比矩陣＋方法論＋per-query 對照）、`/search/chinese`（中文分詞工程解剖）；fuse.js 陽春層沿 v1 §5 契約原樣，升級為**三層對照敘事**（fuse 字元模糊→分詞 FTS→hybrid+rerank）（§8） | 評測工程與中文工程各自撐得起一頁；單頁塞五個主題會退化成長捲軸目錄 |
| 7 | 資料流/守門 | 引擎落 `ml/search/{indexer,retrieval,eval,live}`；初始 backfill host MPS `make search-embed-backfill`＋日增量 KPO DAG `search_index_daily`（沿 P2 §1④ 界線）；評測/showcase＝host make target（沿 P2 §13「LLM/host 批次不進 Airflow」）；dataset 4 檔 `search_*` 前綴；MCP +2；CI additive（§10） | 全 additive；喝 P4 同一口井 |
| 8 | registry/⌘K/related | 3 頁 registry 正典文案本檔給齊（§9，沿 v1 Opus 核准的「spec 給正典」慣例）；⌘K 邊界句式深化（§11）；`related` → `/ai-lab`＋`/reco`＋`/ptt`（§11） | gate 阻擋級要求的內容品質不留給 plan 賭 |

**貫穿裁定**：①一工一具——向量檢索只 pgvector（不引 Faiss，同 P6 判定）、embedding 只 e5-small、分詞只 jieba、rerank 只 bge-reranker 一顆、排程只 Airflow；②全 additive——不改 `ml.rag_documents`/P2b graph/`ml.reco_*`/`silver.ptt_articles`/exporter 既有條目，一切前綴 `search_`/`ml.search_*`；③M4/CPU 友善——rerank/embedding 全程 CPU 可跑（MPS 是加速非前提），不假設 GPU；④站上零 live 檢索運算——純靜態讀 committed JSON，真檢索只在叢集/host 離線與 live-demo 外連。

---

## 2. 語料表 `ml.search_documents`（brief 項 1）

### 2.1 落點裁定

| 候選 | 判定 |
|---|---|
| **平行新表 `ml.search_documents`** ✅ | 不動 P2b 資產；可加搜尋專屬欄（`content_seg`/`tsv_seg` 分詞通道、`board/category/post_date/comments_score` 過濾欄——filter 透傳 WHERE 需要真欄位非 `meta jsonb` 撈）；P2b eval 母體（留言＋video_meta）不被 PTT 長文污染；表名進 `ml.search_*` 命名空間（crosscut 決策 13） |
| 改 `rag_documents` 的 `doc_type CHECK` 加 `'ptt_article'` | 淘汰：改既有表 CHECK＋`UNIQUE(doc_type,source_id,embedding_model)` 語意＝動 P2b 介面（違只 additive）；P2b CRAG graph/evalset 假設語料＝留言域，混入 PTT 使其 hit_rate 基準漂移 |
| 另立資料庫/schema | 淘汰：`ml` schema 已是 P2 §3.4 建好的 ML 資產正位；另立＝無謂邊界 |

### 2.2 DDL（欄位級合約；DDL 由 indexer `write_pg.py` 首行 `CREATE TABLE IF NOT EXISTS` 持有，沿 P1/P2 loader 慣例）

```sql
CREATE TABLE IF NOT EXISTS ml.search_documents (
  doc_id          bigserial PRIMARY KEY,
  board           text        NOT NULL,          -- 過濾欄（denorm 自 silver.ptt_articles）
  aid             text        NOT NULL,
  chunk_no        int         NOT NULL,          -- 0 起
  source_id       text        NOT NULL,          -- '<board>#<aid>#<chunk_no>' 決定性
  title           text        NOT NULL,
  content         text        NOT NULL,          -- chunk 原文（不含 title）
  content_seg     text        NOT NULL,          -- jieba 分詞（title＋chunk），空白 join
  category        text,
  post_date       date        NOT NULL,          -- 過濾欄
  post_ts         timestamptz,
  comments_score  int,                           -- 索引當時快照（known-limit，§2.4）
  url             text,
  embedding       vector(384) NOT NULL,          -- e5 'passage: {title}\n{chunk}'
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', left(title,200) || ' ' || content)) STORED,
  tsv_seg         tsvector GENERATED ALWAYS AS (to_tsvector('simple', content_seg)) STORED,
  embedding_model text        NOT NULL,          -- 'intfloat/multilingual-e5-small'
  seg_dict        text        NOT NULL,          -- 'jieba-0.42.1/dict.txt.big'（+自訂詞典 hash，若有）
  indexed_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, embedding_model)            -- 冪等鍵（沿 P2 §8.2 形）
);
CREATE INDEX IF NOT EXISTS search_documents_hnsw    ON ml.search_documents USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX IF NOT EXISTS search_documents_tsv     ON ml.search_documents USING gin (tsv);
CREATE INDEX IF NOT EXISTS search_documents_tsv_seg ON ml.search_documents USING gin (tsv_seg);
CREATE INDEX IF NOT EXISTS search_documents_board_date ON ml.search_documents (board, post_date);
```

- `tsv`（raw simple 通道）**刻意保留**：它是「不分詞的中文 FTS 有多弱」的可實跑對照組（評測 arm 1＋`/search/chinese` 頁解剖素材），不是生產通道。
- 量級：萬篇級文章 × 1–3 chunk ≈ 1–5 萬列 × 384 維 ≈ 向量 <100MB＋HNSW——單顆 Postgres 零壓力（P2 §8.2 百萬列都收）。

### 2.3 chunk 與清洗（`corpus.py`/`chunk.py`，規則可測）

| 項 | 決定 |
|---|---|
| 過濾 | `content` 去空白後 <20 字元的文章跳過（公告/純連結文）；純轉錄新聞不特判（誠實：語料即 PTT 現實）。過濾率記入 backfill log 與 `search_corpus_stats.json` |
| chunk | `len(content) ≤ 800` → 單 chunk（chunk_no=0）；否則 800 字元/overlap 100 滑窗（沿 P2 §8.2 video_meta 800/100 既例，同 repo 慣例不另創參數）。**plan 實查 2 校準**：若 P3 實跑長度中位 <400，多數文章單 chunk，參數不動、僅記分佈 |
| embed 輸入 | `passage: {title}\n{chunk}`——title 前置給每個 chunk 主題錨（e5 前綴走 `ml_rag_index.embed` 封裝，§0.2） |
| `content_seg` | `jieba.cut_for_search(title + '\n' + chunk)` 空白 join；`jieba.set_dictionary(dict.txt.big)`（繁體詞典，§0.1 官方明示）＋`jieba.initialize()` 顯式預載（避免首篇延遲）；自訂 userdict 留接縫（PTT 詞彙如「鄉民」「五樓」，plan 實查 5 決定是否加、加了進 `seg_dict` 版本串） |
| 檢索後去重 | 通道排名與 RRF 皆在 **chunk 級**；融合後 `DISTINCT ON (board, aid)` 取每文最佳 chunk（最高融合分）→ top-k 為**文章數**——標準 passage-to-doc 映射，rerank 亦以最佳 chunk 為輸入 |

### 2.4 known-limits（誠實標，registry `caveats` 收錄）

①`comments_score` 為索引當時快照（P3 重爬會 UPDATE silver，本表不追——embedding 不依賴它，只影響展示排序旁註）；②PTT 文章可編輯，索引以首見版本為準，全量重建走 `make search-reindex`（TRUNCATE＋backfill）；③推文明細（`comments_json`）不進語料（P3 未展平 known-limit 的下游承接），列進化方向。

---

## 3. 中文分詞工程（brief 項 2 的 CJK 深化；`/search/chinese` 頁的工程本體）

### 3.1 問題（承接 P2b §9 known-limit，深化為可量測）

PG `to_tsvector('simple', '台積電法說會後外資大買')` 產出**單一 token**（simple config 按空白/標點切，中文整句不切）——`plainto_tsquery('simple','台積電')` 對它**零命中**。P2b 的處置是「e5 向量通道補、pg_trgm 備援、README 記 known-limit」（其語料是短留言＋多語混雜，夠用）；搜尋支柱把這個洞當**主展示品修**。

### 3.2 方案裁定

| 候選 | 判定 |
|---|---|
| **應用層 jieba 預分詞 → `content_seg` 空白 join → `to_tsvector('simple')`** ✅ | 分詞後 token 以空白隔開，simple config 正常建倒排——**與 DB 內分詞 extension 效果同構**，但：零動 Postgres image、分詞器版本進 `seg_dict` 欄可稽核、分詞邏輯是可單測的純函式、查詢側同一函式保證索引/查詢對稱。繁體：`dict.txt.big`（官方繁體建議詞典）。成本：`content_seg` 存雙份文字（萬篇級語料 <50MB，可忽略） |
| zhparser / pg_jieba（PG extension 內建分詞 FTS config） | 淘汰：`pgvector/pgvector:0.8.4-pg16` 官方 image 只含 pgvector，二者皆需自編譯進自建 DB image——換共用 Postgres image＝動 P1/P2 地基資產（違只 additive），且為單一支柱把 C extension 供應鏈風險引進全平台 DB；效果與應用層預分詞同構、無淨增益。**對照敘事保留**：`/search/chinese` 頁把此取捨寫成工程判斷（「分詞放應用層 vs DB 層」），不是不知道有 zhparser |
| pg_trgm 三元組 | 不作主通道（無詞義只有字元 n-gram、噪音高）；P2b 已裝備援的事實如實敘述 |
| 換 ES/smartcn | 淘汰：違「一工一具」與拓撲（本平台 DB 只 Postgres）；smartcn 是前身（ptt-search）敘事的位置 |

### 3.3 查詢側對稱＋誠實標

- 查詢：`q → jieba.cut_for_search(q) → plainto_tsquery('simple', ' '.join(tokens))` over `tsv_seg`；排序 `ts_rank_cd(tsv_seg, query)`。同一 `segment.py` 函式服務索引/查詢/live 端點三處（單一真源）。
- **`ts_rank_cd` 不是 BM25**（無 k1/b 飽和與長度正規化參數）——評測矩陣詞彙 arm 一律標 **「FTS (ts_rank_cd)」不冒稱 BM25**；registry `formula` 與頁面 caveat 明寫差異；「知道 ts_rank 與 BM25 的差別」本身進 `/search/chinese` 誠實段。真 BM25（如 ParadeDB pg_search）列進化方向。
- 簡繁 caveat：jieba 詞典簡體為主、`dict.txt.big` 補繁體常用詞；PTT 口語/流行語未登錄詞率＝plan 實查 5（抽 100 篇人工目視），userdict 為既留接縫。

---

## 4. hybrid 檢索管線（brief 項 2；複用 P2 §9 形 over 新表）

### 4.1 五個檢索法（arm；評測矩陣的行）

| arm | 通道 | 定位 |
|---|---|---|
| `fts_raw` | `tsv @@ plainto_tsquery('simple', q)`，`ts_rank_cd` | 對照組——P2b 同款 raw 通道，展示中文失效 |
| `fts_seg` | `tsv_seg @@ plainto_tsquery('simple', seg(q))`，`ts_rank_cd` | 詞彙主通道（§3） |
| `vector` | `embedding <=> embed_query(q)` cosine，`SET hnsw.ef_search=100` | 語意通道（e5 `query:` 前綴） |
| `hybrid` | `fts_seg` top-40 ＋ `vector` top-40 → **RRF k=60**（生產預設） | 平台範式（P2 §9／P6 同款 k） |
| `hybrid_rerank` | `hybrid` top-40（chunk→文章去重後）→ bge-reranker → top-10 | 品質工程頂層（§5） |

### 4.2 SQL 形（合約級；最終字面由 plan 落）

```sql
WITH vec AS (
  SELECT doc_id, board, aid,
         row_number() OVER (ORDER BY embedding <=> %(qvec)s::vector) AS r
  FROM ml.search_documents
  WHERE (%(board)s::text IS NULL OR board = %(board)s)
    AND (%(date_from)s::date IS NULL OR post_date >= %(date_from)s)
    AND (%(date_to)s::date   IS NULL OR post_date <= %(date_to)s)
  ORDER BY embedding <=> %(qvec)s::vector LIMIT 40
), lex AS (
  SELECT doc_id, board, aid,
         row_number() OVER (ORDER BY ts_rank_cd(tsv_seg, plainto_tsquery('simple', %(q_seg)s)) DESC) AS r
  FROM ml.search_documents
  WHERE tsv_seg @@ plainto_tsquery('simple', %(q_seg)s)
    AND (同上 filter 透傳)
  LIMIT 40
), fused AS (
  SELECT COALESCE(v.doc_id, l.doc_id) AS doc_id,
         COALESCE(1.0/(60+v.r), 0) + COALESCE(1.0/(60+l.r), 0) AS rrf_score,
         v.r AS vec_rank, l.r AS lex_rank
  FROM vec v FULL OUTER JOIN lex l USING (doc_id)
)
SELECT DISTINCT ON (d.board, d.aid) d.*, f.rrf_score, f.vec_rank, f.lex_rank
FROM fused f JOIN ml.search_documents d USING (doc_id)
ORDER BY d.board, d.aid, f.rrf_score DESC
-- 外層再按 rrf_score DESC LIMIT %(top_k)s
```

- filter（board/category/date）**兩通道皆透傳 WHERE**（P2 §9 同法）；filter 命中率低時 `SET hnsw.iterative_scan='strict_order'`（pgvector 0.8.x，§0.1 查證——比 P2b 多走一步的查詢工程細節，進頁面敘事）。
- 每筆結果攜 `vec_rank/lex_rank/rrf_score`（＋rerank 後 `rerank_score`）——**分數分解透明化**是 live UI 與 showcase 的教學核心（沿問 AI trace 全揭露精神）。
- 自寫 SQL（psycopg＋pgvector-python，P2 §9 明拒 vectorstore 抽象的同判定）。落點 `ml/search/retrieval/src/ml_search_retrieval/retrieve.py`；RRF 融合另拆純函式（給 fused ranks 算分）供單測數值斷言與 P2 §9 同構。

---

## 5. rerank 層（brief 項 3）

| 項 | 決定 |
|---|---|
| 模型 | **`BAAI/bge-reranker-v2-m3`**（568M 多語 cross-encoder，based on bge-m3，中文強；§0.1 查證）。備選降級 `bge-reranker-base`（278M，zh/en）——降級判準見 plan 實查 3。淘汰：LLM-as-reranker（每 query 一次 LLM 呼叫，延遲/成本/不可重現三輸，且 P2b grade 已示範過該範式）；ms-marco MiniLM 系（英文域，zh 弱） |
| 載入 | sentence-transformers **`CrossEncoder('BAAI/bge-reranker-v2-m3', activation_fn=torch.nn.Sigmoid(), max_length=1024, device=…)`**——**零新依賴**（5.6.0 已 pin 已進 batch image）；分數 0–1（sigmoid）。`max_length=1024`（chunk 800 字元中文 ≈ 千 token 級，512 會截斷過半；p50 過慢的降級判準見 plan 實查 3） |
| 輸入 | pairs＝`(q, title + '\n' + best_chunk_content)`（文章去重後的最佳 chunk，§2.3）；top-40 → `.predict(pairs, batch_size=8)` → 依分數重排取 top-10 |
| 跑法 | **離線為主**：評測（§6）與 showcase 預產（§10）在 **M4 host MPS**（`make search-eval`/`gen-search-showcase`；fp16 MPS ~1.1GB，16GB M4 舒適）；**live 端點 CPU**（§7，per-request top-40 一批，UI 可 toggle）。k8s KPO **不跑 rerank**（日增量索引用不到；界線沿 P2 §1④） |
| **與 P2b §9 淘汰決策的關係（明標，registry/頁面雙落點）** | P2b §9 淘汰 cross-encoder rerank 的原文脈絡＝**RAG 生成鏈**：grade 節點（LLM 批量自評）已擔負 relevance 過濾並驅動 CRAG 分支，「再養一個模型收益不成比例」——那是生成前置的成本取捨。搜尋支柱的目的＝**檢索排序品質本身**：rerank 對 nDCG 的增益（或無增益）就是展示品，且 portfolio 成本紅線不適用。**兩個決策同時成立、互不推翻**——此對照寫進 `/search` 頁 `predecessor`/`pipeline` 敘事與 `/architecture` 整合卡素材：「同一平台在兩個語境對同一技術做出相反且各自正確的取捨」 |
| 誠實紀律 | **不預設 rerank 必贏**：對比矩陣實測填數，若 `hybrid_rerank` 未勝 `hybrid` 照實上頁並分析（judge 偏好/語料短文/截斷），沿 P2c「win-rate 未達照實 report」同款 |

---

## 6. 檢索評測 harness（brief 項 4；核心展示品）

### 6.1 標註集產法（拍板：LLM-judge 分級標註＋pooling＋人工抽查）

| 步 | 決定 |
|---|---|
| 題集 | **50 題** `ml/search/eval/queries.yaml`（git 版本化）：**35 題 LLM 合成**——從 frozen 語料分層抽樣文章（3 board × category × 長度分層，固定 seed），Gemini flash 依「使用者會用什麼 query 找到這篇」生成（prompt 版本化 `search-querygen`，MLflow Prompt Registry additive 掛載，沿 P2 §10）；**15 題人工手寫**——含口語改寫、錯字、同義詞、跨文章主題題（合成題觸不到的形態）。每題記 `query_id/query/origin/seed_aid?` |
| pooling | 每題跑**五 arm 各 top-20 → 聯集**（預期 40–80 篇/題）——TREC pooling 右尺寸版；**pool 外文件不標**（recall 分母＝pool 內相關集，上界性質誠實標） |
| 標註 | **LLM-judge 分級 0–3**（3=直接回答查詢意圖／2=部分相關／1=沾邊／0=無關）：Gemini flash temp 0、rubric prompt 版本化（`search-judge`）、每 pair 獨立評（不見排名，防位置偏誤）。二值化 `rel ≥ 2` 供 recall/MRR；nDCG 用分級原值 |
| 人工抽查 | **5 題 × 全 pool 人工雙標** → report 一致率＋Cohen's κ（`search_eval_matrix.json` meta 附）；κ < 0.6 → rubric 迭代重標（判準寫進 plan） |
| 可重現 | frozen 語料快照（`search_documents` 匯出 parquet）＋qrels（`qrels.json`）進 **DVC**（沿 P2 §10 慣例）；評測對快照跑，不受活表漂移影響 |

### 6.2 指標（公式進 registry `formula`，可稽核）

| 指標 | 公式（k=10） |
|---|---|
| `recall@10` | `|top10 ∩ rel| / |rel|`，`rel = {d ∈ pool : grade(d) ≥ 2}`；per-query 後 macro 平均 |
| `MRR@10` | `mean_q(1 / rank_first_rel)`（top-10 無相關＝0） |
| `nDCG@10` | `DCG@10 / IDCG@10`，`DCG = Σ_i (2^grade_i − 1) / log2(i+1)` |
| `p50_latency_ms` | 各 arm 檢索（含 rerank）host 實測中位（50 題，暖機後） |

### 6.3 對比矩陣（＝核心展示品）與落地

- **矩陣**：5 arm（§4.1）× 4 指標 → `ml.search_eval_metrics(eval_date date, variant text, metric text, k int, value double precision, corpus_snapshot text, PRIMARY KEY(eval_date, variant, metric, k))`（形沿 P6 `reco_eval_metrics`）＋ MLflow experiment **`search_eval`**（params＝arm 參數/seg_dict/embedding_model/rerank 模型；一次評測一 run，A-B＝兩 run 並排，沿 P2 §10）。
- **sanity 閘（非晉升閘——評測是展示品不是模型上線）**：`fts_seg` 的 nDCG@10 > `fts_raw`（分詞增益必須為正，否則管線有 bug）；`hybrid ≥ max(fts_seg, vector) − 0.02`（融合不應明顯輸單通道）。違反＝`make search-eval` 非零退出、不寫表（沿問 AI「壞批次不上站」）。rerank arm **無閘**（§5 誠實紀律，輸贏照實上頁）。
- **per-query showcase**：12 題（人工題優先、含 rerank 翻盤/未翻盤各若干）× 各 arm top-3 → `ml.search_query_showcase(id bigserial PK, query_id text, query text, variant text, rank int, board text, aid text, title text, snippet text, scores jsonb, judged_grade int, generated_at timestamptz)`——`/search/relevance` 的對照卡資料源。
- **侷限誠實標（registry caveats＋頁面方法論卡固定內容）**：①pool 深度 20/arm，pool 外未標（recall 為上界估計）②judge 為 LLM（Gemini），與向量通道雖非同源模型仍可能偏好語意匹配——以人工抽查 κ 量化此風險③50 題規模＝方法示範級非 benchmark 級④合成題與語料同源（seed 文章），人工 15 題緩解。

---

## 7. live-demo：新建 Cloud Run `search-live`（brief 項 5；鏡像問 AI §8 形態）

### 7.1 目標端點裁定

| 候選 | 判定 |
|---|---|
| **新建 Cloud Run `search-live`** ✅ | 示範主體就是本支柱造的 hybrid+rerank（ptt-search 沒有）；語料＝本平台 P3 管線產物（敘事一致）；**零 admin 面**（正面回應 v1 §2 事實 15——該發現的根因是「檢索服務攜帶無認證 admin」，新端點只有 `/search`/`/healthz`/`/metrics`/`/`，reindex/管理全在平台側離線）；形態直接鏡像問 AI §8 已拍板的 Cloud Run 慣例 |
| 沿用 ptt-search 部署 | 淘汰：admin 無認證資安未收斂（v1 Opus 已升級為上線 gating）；索引的是另一顆 DB 的飲料板語料；ES bool+smartcn 是「前身」不是 v2 要展示的能力。**ptt-search 部署本身保留不退役**（crosscut §8.2），但 v1 不從作品集外連它（前身對照卡純敘事＋截圖；若 Fergus 日後要外連，前置 gate＝其 admin 面收斂，沿 v1 Opus 裁定原文） |

**knock-on（Opus 知會，§16.1）**：crosscut §7.2 v1 配置「搜尋支柱 ✅（ptt-search 既有部署）」與 §3.1 `pillars.ts` 草樣需一行修訂為 search-live——brief-v2 明文授權本拍板，crosscut 該句屬被取代的 v1 前提。

### 7.2 資料層裁定：連 Neon 輕量 PG（同構 SQL）

| 候選 | 判定 |
|---|---|
| **Neon 免費層 PG＋pgvector** ✅ | live 端點跑的是**與平台一字不差的 `ml_search_retrieval` SQL**（pgvector cosine＋tsv_seg＋RRF）——「demo 即生產同構」敘事完整；Neon 官方支援 pgvector ≥0.8＋HNSW＋ef_search（§0.1 查證）；免費層 0.5GB > 語料快照（<200MB）；scale-to-zero 成本 0；唯讀角色 `search_live_ro` 最小權限 |
| 索引/資料烘入 image（in-process numpy 暴搜＋自帶詞彙索引） | 淘汰：向量檢索換成 numpy＝live 展示的不再是 pgvector 路徑（削弱敘事、且逼出第二套檢索實作違一工一具）。**列為 Neon 不可用時的降級路徑**：改烘 PG data dir 進 container（同 SQL、冷啟更慢），plan 實查 4 定案 |
| 回連本地叢集 | 淘汰：拓撲鐵律（Cloud Run 摸不到本地 k8s；問 AI §8 同一事實） |

**灌檔**：`make search-live-seed`——host 從 `ml.search_documents` 匯出快照灌 Neon 同構表（含 HNSW/GIN 重建）；快照批次記 `snapshot_id`，UI 誠實標「語料＝平台 {snapshot_date} 快照，非即時同步」。

### 7.3 服務形（鏡像問 AI §8 逐項）

| 項 | 拍板 |
|---|---|
| 形態 | Cloud Run service **`search-live`**（region `asia-east1`）：FastAPI 0.139＋`ml_search_retrieval`（同套件）＋e5-small（query embedding，CPU ~百 ms 級）＋bge-reranker（CPU，lazy load）＋單檔 UI |
| API | `POST /search {q(≤200 字元), board?, category?, date_from?, date_to?, mode: 'fts_raw'\|'fts_seg'\|'vector'\|'hybrid' = 'hybrid', rerank: bool = true, top_k: int ≤ 20 = 10}` → `{results: [{board, aid, title, snippet, url, post_date, comments_score, scores: {vec_rank?, lex_rank?, rrf_score?, rerank_score?}}], mode, rerank, latency_ms, snapshot_id}`；`GET /healthz`（含 Neon 連線子檢查）；`GET /metrics`；`GET /`＝UI。**無任何 admin/寫入 route** |
| UI | 單檔 `index.html`（vanilla JS 零框架零 CDN，同問 AI）：輸入框＋board/日期 filter＋**mode 切換 chip（四法）＋rerank toggle**＋結果列（title/snippet/分數分解 badge：lex#/vec#/RRF/rerank）＋latency badge。頁首誠實帶：「此為獨立部署的 live 示範（Cloud Run＋Neon Postgres）；跑的是與平台同一段 hybrid RRF SQL；閒置後首次請求需冷啟（含載入 rerank 模型）數十秒」＋範例 query chips（自 queries.yaml 人工題烘入 6 顆） |
| 資源/成本 | `min-instances=0`、`max-instances=1`、`concurrency=4`、`timeout=60s`、`memory=4Gi`（reranker fp32 CPU ~2.3GB＋e5＋headroom）；image 含兩模型權重（~3GB，冷啟拉取慢——誠實標，ONNX int8 列進化方向）；GCP billing alert 沿問 AI plan 實查同批設 |
| 憑證/安全 | Neon 連線串（唯讀角色）走 Cloud Run env（deploy workflow 自 GitHub secret 注入）、缺即 fail-fast（P2b 紀律）；SQL 全參數化；pydantic 邊界（q ≤200、top_k ≤20）；**rate-limit 接縫**沿問 AI §8：`live/rate_limit.py` no-op middleware＋env `SEARCH_DAILY_LIMIT`（未設＝無限制）＋429 schema `{status:'rate_limited', retry_after}` 先定義，實作 follow-up |
| 部署 | `.github/workflows/search-live-deploy.yaml`：**`workflow_dispatch` 手動**（同問 AI——對外部署謹慎）：build→GHCR→`gcloud run deploy`；URL 產出後回填 `pillars.ts search.liveDemo`（§8.4） |
| 前端呈現 | `LiveDemoCard(pillar='search')` 落點＝`/search` 頁區塊＋`/architecture` 整合卡一行（crosscut §7.2/§7.4）；固定誠實句式原文＋hostname＋`target="_blank" rel="noopener noreferrer"`＋lucide `ExternalLink`；URL 未回填/失效 → 降級態文案：「live demo 目前離線；hybrid 檢索的完整行為見下方評測對比與 per-query 對照（離線批次產生）」（沿 crosscut §12.4 同型） |

---

## 8. 頁 IA（brief 項 6；crosscut §2.2 授權 `/search`＋`/search/<page>`）

### 8.1 路由與檔案落點

```
frontend/src/app/(search)/search/
├── page.tsx              # /search           支柱首頁：管線敘事＋三層對照＋前身＋評測摘要
├── relevance/page.tsx    # /search/relevance 檢索評測工程
└── chinese/page.tsx      # /search/chinese   中文分詞工程
frontend/src/components/search-pillar/
├── SearchPipelineDiagram.tsx   # inline SVG（RSC；沿 P4 /architecture SVG 慣例，不引 mermaid）
├── ThreeTierCompareCard.tsx    # 三層對照表（RSC）
├── OfflineSearchDemo.tsx       # fuse.js 陽春層——v1 §5.3 行為契約原樣沿用（'use client'）
├── EvalMatrixChart.tsx         # Recharts grouped bar（'use client'，Signal chart token）
└── QueryShowdownCard.tsx       # per-query 各法對照卡（RSC）
```

`pillars.ts`：`navGroups: [{ label: '搜尋工程', routes: ['/search', '/search/relevance', '/search/chinese'] }]`；`liveDemo: { url: '<search-live Cloud Run URL，deploy 後回填>', deployment: 'Cloud Run + FastAPI + Neon Postgres (pgvector) + bge-reranker', note: '真 hybrid 檢索：jieba 分詞 FTS＋e5 向量 RRF＋cross-encoder 重排' }`。

### 8.2 各頁區塊（＝registry block id；版面沿 Signal §5 treatment）

| 頁 | 順序 | block | 內容 |
|---|---|---|---|
| `/search` | 0 | `PageHeader entryId="search"` | 問句 h1＋whyBuilt 常駐＋頁級 Explainer（defaultOpen，首句＝⌘K 邊界聲明 §11） |
| | 1 | `pipeline` | 全寬：管線 SVG——`silver.ptt_articles` → 清洗/chunk → jieba `content_seg`＋e5 embedding → `ml.search_documents`（雙 tsv＋HNSW）→ hybrid RRF → rerank → 評測/showcase/live；圖說標「真運算在平台叢集與 M4 host 離線批次；本頁為預產結果」 |
| | 2 | `three-tier-demo` | 2-col：左＝`OfflineSearchDemo`（fuse.js 陽春層，v1 契約）＋右＝`LiveDemoCard`；上方 `ThreeTierCompareCard` 三欄對照（fuse 字元模糊／jieba 分詞 FTS／hybrid+rerank 語意——執行位置/索引/中文處理/排序依據/規模/角色 六維） |
| | 3 | `eval-summary` | 評測摘要卡：hybrid_rerank vs fts_raw 的 nDCG@10 對比大數字＋「完整對比矩陣 → /search/relevance」 |
| | 4 | `predecessor` | 前身對照卡：ptt-search（ES bool `title^2`＋smartcn＋more_like_this——v1 §2 事實敘事）→ 本平台進化點（分詞可稽核/hybrid 融合/rerank/可量測評測）；含「P2b 淘汰 rerank vs 本支柱採用」的取捨敘事（§5）；純敘事＋截圖、v1 不外連（§7.1） |
| `/search/relevance` | 0 | `PageHeader entryId="search-relevance"` | |
| | 1 | `eval-matrix` | `EvalMatrixChart`：5 arm × nDCG@10/recall@10/MRR@10 grouped bar＋p50 延遲表（`search_eval_matrix.json`） |
| | 2 | `methodology` | 方法論卡：50 題構成/pooling/LLM-judge 分級 rubric/人工抽查 κ；**侷限四條**（§6.3）原文 |
| | 3 | `query-showcase` | `QueryShowdownCard` × 12：每題五 arm top-3 並排＋rerank 前後名次變化標記（`search_query_showcase.json`） |
| `/search/chinese` | 0 | `PageHeader entryId="search-chinese"` | |
| | 1 | `why-simple-fails` | 解剖卡：`to_tsvector('simple','…繁體例句…')` 實際輸出（單 token）→ 為何 `fts_raw` 對中文近乎失明；接 P2b known-limit 承接敘事 |
| | 2 | `segmentation` | jieba 應用層分詞：dict.txt.big/cut_for_search/`seg_dict` 版本欄；**zhparser/pg_jieba 對照取捨表**（DB 層 vs 應用層，§3.2 論證上頁） |
| | 3 | `vector-complement` | e5 向量補位案例：同義/口語 query 在 `fts_seg` miss、`vector` hit 的真實例（showcase 資料抽） |
| | 4 | `honest-limits` | 誠實卡：ts_rank_cd≠BM25、簡繁詞典 caveat、未登錄詞、pool/judge 侷限 cross-ref |

lucide icons（plan 期以 lockfile 校準擇實存者，非阻擋）：頁 `Search`（crosscut 已定）/`Gauge`（relevance）/`Languages`（chinese）；區塊 `GitBranch`（pipeline）/`SplitSquareHorizontal`（three-tier）/`BarChart4` 或 `ChartColumnBig`（eval-matrix）/`FlaskConical`（methodology）/`Scissors`（segmentation）。無 emoji。

### 8.3 datasets（exporter `datasets.py` append 4 條目；P4 信封同構、absent 容忍）

| dataset | 源 | rows 形（欄位級） | cap |
|---|---|---|---|
| `search_ptt_titles.json` | **v1 §5.1 合約原樣**（`silver.ptt_articles` top-1000 標題） | v1 row schema 零改 | ≤300KB（v1 斷言沿用） |
| `search_eval_matrix.json` | `ml.search_eval_metrics` 最新 `eval_date` | `{variant, metric, k, value, eval_date, corpus_snapshot}`＋meta：`{n_queries, pool_depth, judge_model, human_check_kappa, seg_dict, embedding_model, rerank_model}` | ≤50KB |
| `search_query_showcase.json` | `ml.search_query_showcase` | `{query_id, query, origin, variant, rank, board, aid, title, snippet(≤120字), url, scores, judged_grade}` | 12 題 × ≤5 arm × top-3；≤200KB |
| `search_corpus_stats.json` | SQL aggregate over `ml.search_documents` | `{articles, chunks, filtered_out, boards:[{board, articles}], content_len_hist:[{bin_lo,bin_hi,count}], avg_chunks_per_article, embedding_model, seg_dict, indexed_through}` | ≤50KB |

`check-data.mjs` append 各檔專屬 cap 斷言；`frontend/src/lib/types.ts` 加 TS 鏡像。P3/評測未跑 → `status:"absent"`，頁面骨架誠實顯示（P4 容忍路徑原樣）。

---

## 9. 說明式 registry 條目（brief 項 8；正典文案，`frontend/src/content/registry/search.ts`，schema 照 crosscut §5.2 零改；plan 照抄可潤飾不可刪意）

```ts
export const searchPages = {
  search: {
    pillar: 'search', route: '/search',
    questionTitle: '一套進階中文檢索系統是怎麼從零到可量測地搭起來的？',
    whyBuilt:
      '展示檢索相關性工程的深度：不只「會呼叫搜尋 API」，而是在自家平台語料上真建 hybrid 檢索' +
      '（jieba 分詞 FTS＋多語向量 RRF 融合）、cross-encoder 重排、與可稽核的相關性評測——' +
      '並與早期作品 ptt-search（ES 基礎版）對照出進化軌跡。',
    whatItDoes:
      '本頁提供：①檢索管線全景圖（P3 PTT 語料 → 分詞/向量雙通道索引 → RRF → rerank）' +
      '②三層搜尋對照互動區（站內 fuse.js 模糊搜／live demo 真 hybrid 檢索外連）' +
      '③評測結果摘要與前身系統對照。',
    howToRead:
      '本站站內搜尋（⌘K）是 client-side fuse.js 導航搜；真 hybrid 檢索（分詞 FTS＋向量＋rerank）' +
      '在平台叢集離線跑，live 版見外連 demo。先玩區塊②感受三層差異，再看管線圖與評測數字。',
    canDo: '看懂詞彙/語意雙通道為何要融合、RRF 怎麼融、rerank 值不值、以及這些判斷如何被評測數字支撐。',
    problem: '「接了向量資料庫」和「能量測並改進檢索相關性」是兩種深度；沒有評測的檢索優化是盲飛。',
    formula: 'RRF(d) = Σ_channel 1/(60 + rank_channel(d))',
    dataSource: ['search_eval_matrix.json ← ml.search_eval_metrics（host 離線評測）',
                 'search_ptt_titles.json ← silver.ptt_articles（P3 管線）',
                 'live demo ← search-live（Cloud Run＋Neon Postgres，平台語料快照）'],
    caveats: [
      '本頁所有檢索結果與指標皆離線批次預產；本站不做任何 live 檢索運算。',
      'fuse.js 示範是字元級模糊比對（無分詞、無倒排索引），刻意作為最陽春對照層。',
      'comments_score 為索引當時快照；文章編輯以首次索引版本為準。',
    ],
    aiVsComputed: 'computed',
    blocks: {
      pipeline: { questionTitle: '一篇 PTT 文章怎麼變成可檢索的向量與詞彙索引？',
        howToRead: '正文清洗切塊（800 字元/重疊 100）後走兩條路：jieba 分詞進 FTS 倒排、e5 嵌入進 pgvector HNSW；查詢時兩通道各取 40 名以 RRF 融合，可再交 cross-encoder 重排。',
        dataSource: ['search_corpus_stats.json'], aiVsComputed: 'computed' },
      'three-tier-demo': { questionTitle: '同樣打一個關鍵字，三種搜尋差在哪？',
        howToRead: '左＝瀏覽器內 fuse.js（字元相似度、可容錯字）；右外連＝真 hybrid 檢索（分詞＋語意＋重排）。六維對照表列出執行位置、索引、中文處理、排序依據、規模與角色。',
        dataSource: ['search_ptt_titles.json', 'live demo（search-live 獨立部署）'], aiVsComputed: 'computed' },
      'eval-summary': { questionTitle: '這套管線比不分詞的基線好多少？',
        howToRead: '大數字為 hybrid+rerank 與 raw FTS 的 nDCG@10 對比；完整五法矩陣與方法論在「檢索評測」頁。',
        formula: 'nDCG@10 = DCG@10 / IDCG@10', dataSource: ['search_eval_matrix.json'],
        caveats: ['評測集 50 題、pool 深度 20/法——方法示範級規模，非公開 benchmark。'], aiVsComputed: 'computed' },
      predecessor: { questionTitle: '這套系統是從哪裡進化來的？',
        howToRead: '前身 ptt-search 用 Elasticsearch bool 查詢（title^2）＋smartcn 分詞＋more_like_this——正確但基礎。本平台版把分詞變成可版本化的應用層函式、把單引擎排序升級為雙通道 RRF＋rerank、並補上前身沒有的相關性評測。有趣的對照：平台 RAG（P2b）基於成本取捨淘汰了 rerank，本支柱基於展示目的採用它——同一技術、兩個語境、兩個都對的決策。',
        dataSource: ['ptt-search repo（唯讀取材）'], caveats: ['前身系統的線上部署不在本頁外連範圍。'], aiVsComputed: 'none' },
    },
  },
  'search-relevance': {
    pillar: 'search', route: '/search/relevance',
    questionTitle: '怎麼證明一個檢索系統「變好了」？',
    whyBuilt:
      '檢索優化沒有評測就是主觀故事。本頁展示一套右尺寸的相關性評測：LLM-judge 分級標註＋pooling' +
      '＋recall/nDCG/MRR 對比矩陣，並誠實揭露方法侷限——這是搜尋工程裡最常被跳過的一環。',
    whatItDoes:
      '本頁提供：①五種檢索法（raw FTS／分詞 FTS／向量／hybrid／hybrid+rerank）× 三指標＋延遲的對比矩陣' +
      '②標註集產法與品質控制（人工抽查 κ）③12 題 per-query 五法並排對照（含 rerank 前後名次變化）。',
    howToRead:
      '先看矩陣抓整體結論（分詞增益／融合增益／rerank 增益各自多大），再進 per-query 卡看個案為什麼。' +
      '所有數字由程式離線計算，標註集與語料快照版本化可重現。',
    canDo: '學到一套不依賴人工大規模標註也能可信比較檢索法的流程，以及怎麼誠實呈現它的侷限。',
    problem: '沒有 qrels 就比不出 recall；全人工標註對 side project 不現實——需要方法上站得住的折衷。',
    formula: 'recall@10 = |top10 ∩ rel| / |rel|（rel = judge 分級 ≥2）; MRR@10 = mean(1/rank_first_rel); nDCG@10 = Σ(2^grade−1)/log2(i+1) / IDCG',
    dataSource: ['search_eval_matrix.json ← ml.search_eval_metrics', 'search_query_showcase.json ← ml.search_query_showcase'],
    caveats: [
      'pool 深度 20/法，pool 外文件未標註——recall 屬上界估計。',
      '標註者是 LLM（Gemini flash，rubric 版本化、temp 0）；以 5 題全 pool 人工雙標的 κ 量化其可信度。',
      '50 題規模為方法示範級；合成題與語料同源，由 15 題人工題緩解。',
      '詞彙排序用 PostgreSQL ts_rank_cd，並非 BM25（無 k1/b 飽和參數）——矩陣標籤如實寫 FTS。',
    ],
    aiVsComputed: 'mixed',
    aiVsComputedNote: '相關性標註由 LLM-judge 產生（Gemini 2.5 Flash、temp 0、rubric 版本化、離線批次）；指標計算與排名全由程式算。',
    blocks: {
      'eval-matrix': { questionTitle: '五種檢索法，誰在哪個指標贏？',
        howToRead: '每組長條＝一種檢索法；縱軸為指標值。看三個落差：raw→分詞（分詞增益）、單通道→hybrid（融合增益）、hybrid→+rerank（重排增益）。延遲表提醒品質是有價格的。',
        formula: 'RRF k=60；rerank = bge-reranker-v2-m3 over hybrid top-40', dataSource: ['search_eval_matrix.json'], aiVsComputed: 'computed' },
      methodology: { questionTitle: '這些數字是怎麼來的、可以信到什麼程度？',
        howToRead: '50 題（35 LLM 合成＋15 人工）→ 五法各取 top-20 聯集成 pool → LLM-judge 0–3 分級 → 人工抽查 5 題全 pool 算 κ。侷限四條原文列出，不藏。',
        dataSource: ['search_eval_matrix.json（meta 段）'], aiVsComputed: 'mixed',
        aiVsComputedNote: '標註為 LLM 產生；抽查一致率由人工完成。' },
      'query-showcase': { questionTitle: '個案裡 rerank 到底改變了什麼？',
        howToRead: '每卡一題：五法 top-3 並排，rerank 後名次上升/下降以箭頭標示；judged_grade 徽章顯示該結果的標註分級。留意 rerank 沒有改善（甚至變差）的題——那些卡片照實保留。',
        dataSource: ['search_query_showcase.json'], aiVsComputed: 'mixed',
        aiVsComputedNote: '排名與分數程式算；相關性徽章來自 LLM-judge 標註。' },
    },
  },
  'search-chinese': {
    pillar: 'search', route: '/search/chinese',
    questionTitle: '為什麼中文全文檢索不能直接用資料庫預設功能？',
    whyBuilt:
      '中文不以空白斷詞，PostgreSQL simple 分詞器會把整句當一個 token——這是平台 RAG（P2b）誠實記錄的' +
      'known-limit。本頁展示把這個洞真正修掉的工程：應用層 jieba 分詞、繁體詞典、查詢/索引對稱、' +
      '以及「為什麼不裝資料庫分詞外掛」的取捨。',
    whatItDoes:
      '本頁提供：①simple 分詞器對中文失效的實際解剖 ②jieba 應用層分詞方案（詞典版本可稽核）' +
      '③DB 層外掛（zhparser/pg_jieba）vs 應用層分詞的取捨對照 ④向量通道如何補詞彙通道的死角 ⑤誠實限制清單。',
    howToRead:
      '從第一卡的實際 tsvector 輸出開始（眼見為憑），順著「失效→分詞→補位→限制」讀完就是一條完整的' +
      '中文檢索工程決策鏈。',
    canDo: '理解 CJK 檢索的核心坑與務實解法；學到「效果同構時，把複雜度放在應用層而非資料庫層」的取捨框架。',
    problem: '多數教學直接跳到向量檢索，跳過了詞彙通道在精確詞命中上的不可替代性——與讓它為中文工作的成本。',
    dataSource: ['search_corpus_stats.json（seg_dict 版本）', 'search_query_showcase.json（補位案例）'],
    caveats: [
      'jieba 詞典以簡體為主，dict.txt.big 補繁體常用詞；PTT 口語/新詞的未登錄詞仍會切錯（userdict 為既留接縫）。',
      'ts_rank_cd 非 BM25；真 BM25（如 ParadeDB pg_search）列進化方向。',
      '簡繁正規化（索引前 OpenCC 轉換）未做，列進化方向。',
    ],
    aiVsComputed: 'computed',
    blocks: {
      'why-simple-fails': { questionTitle: 'simple 分詞器看到中文時發生什麼事？',
        howToRead: "卡內展示 to_tsvector('simple', …) 對同一句中英文的真實輸出：英文正常切詞、中文整句成單一 token——因此關鍵詞查詢對中文幾乎永遠 miss。",
        formula: "to_tsvector('simple', '台積電法說會') → '台積電法說會':1（單 token）", dataSource: ['（靜態解剖內容，可在任一 PostgreSQL 重現）'], aiVsComputed: 'none' },
      segmentation: { questionTitle: '分詞放在應用層還是資料庫層？',
        howToRead: '本平台選應用層：jieba 分詞後以空白 join 再進 simple 分詞器，效果與 DB 外掛同構，但不必重編譯資料庫映像、分詞器版本進表可稽核、且索引/查詢共用同一個可單測的函式。對照表列出 zhparser/pg_jieba 路線的成本。',
        dataSource: ['search_corpus_stats.json（seg_dict）'], aiVsComputed: 'computed' },
      'vector-complement': { questionTitle: '分詞修好了，為什麼還需要向量通道？',
        howToRead: '詞彙通道只命中「說了同樣的詞」；口語改寫、同義詞、跨詞序表達要靠多語向量（e5）。案例卡取自評測 showcase：同一題分詞 FTS miss、向量 hit 的真實對照。',
        dataSource: ['search_query_showcase.json'], aiVsComputed: 'computed' },
      'honest-limits': { howToRead: '本頁方案的已知限制與下一步（未登錄詞/簡繁/BM25/推文語料），逐條列於卡內，含指回評測頁侷限的交叉連結。',
        dataSource: ['（工程判斷）'], aiVsComputed: 'none' },
    },
  },
} as const;
```

三頁條目經 crosscut §5.5 gate 六斷言自動守門（缺欄＝CI 紅）；`OfflineSearchDemo` 常駐誠實標語沿 v1 §5.3 正典原文。

---

## 10. 資料流、引擎落點與守門（brief 項 7；全 additive）

### 10.1 目錄（沿 P2 §2 佈局慣例）

```
ml/search/
├── indexer/                      # 套件 ml_search_index（雙模式：host MPS backfill / k8s CPU 增量）
│   ├── pyproject.toml            # deps: jieba==0.42.1, ml_rag_index（e5 embed 單一真源）, psycopg, pgvector
│   ├── src/ml_search_index/{corpus.py, chunk.py, segment.py, write_pg.py}
│   └── tests/
├── retrieval/                    # 套件 ml_search_retrieval（五 arm SQL＋RRF 純函式＋rerank 封裝）
│   ├── pyproject.toml            # deps: sentence-transformers（CrossEncoder）, psycopg, pgvector, ml_search_index（segment 查詢側）
│   ├── src/ml_search_retrieval/{retrieve.py, fuse.py, rerank.py}
│   └── tests/
├── eval/                         # 套件 ml_search_eval
│   ├── queries.yaml              # 50 題（git）；qrels.json＋frozen 快照進 DVC
│   ├── src/ml_search_eval/{pooling.py, judge.py, metrics.py, run_eval.py, showcase.py}
│   └── tests/
└── live/                         # search-live（Cloud Run）
    ├── Dockerfile  pyproject.toml
    ├── src/search_live/{api.py, settings.py, rate_limit.py}
    └── ui/index.html
```

### 10.2 執行界線與排程（沿 P2 §1④/§13）

| 工作 | 執行處 | 載體 |
|---|---|---|
| 初始 embedding backfill（萬篇級） | **M4 host MPS** | `make search-embed-backfill`（沿 P2 §1④ backfill 慣例；device 自動 `mps→cuda→cpu`） |
| 日增量索引 | **k8s**（Airflow KPO，CPU） | **新 DAG `search_index_daily`**（`"0 5 * * *"`，排 P3 `ptt_ingest_daily` 02:30 之後；冪等 `WHERE NOT EXISTS` by `source_id`；KPO 用 ml-batch image）——P2 §13 DAG 總表 additive 第 6 條 |
| 評測（five-arm＋judge＋rerank） | **M4 host** | `make search-eval`（需 Gemini key＋MPS；sanity 閘非零退出不寫表） |
| showcase 預產 | **M4 host** | `make gen-search-showcase`（沿 P2 `gen-rag-showcase`/P6 `gen-reco-reasons` 慣例——LLM/host 批次不進 Airflow） |
| 全量重建 | **M4 host** | `make search-reindex`（TRUNCATE＋backfill；文章編輯/換 embedding model 用） |
| live 語料灌檔 | **M4 host** | `make search-live-seed`（→ Neon） |
| live image/部署 | GH Actions | `search-live-deploy.yaml`（workflow_dispatch，§7.3） |

### 10.3 與既有資產的接點（逐條標 additive 性質）

| 接點 | 變更 | 性質 |
|---|---|---|
| `ml/batch` 共用 KPO image（P2 §2） | pyproject 加裝 `ml_search_index`（連帶 jieba ~+60MB 詞典） | **既定接縫 additive**——P2 §2 明文該 image 就是「裝本地套件的共用批次 image」，追加套件＝設計內擴充非資產改動；若 Opus 判邊界過線，fallback＝`ml/search/Dockerfile` 自有 KPO image（§16.2） |
| `ml-batch-ci.yaml` paths | append `ml/search/{indexer,retrieval}/**` | 一行 additive（image 內容變了就該重建，機制同構）；`search-ci.yaml` 新增（ruff＋pytest over `ml/search/**`；live/** 變更加 build image） |
| `ml-db-init` Job（P2 §3.4） | 無需變更 | `ml` schema/`ml_writer`（ml 讀寫＋silver 唯讀）已涵蓋本支柱三表與 `silver.ptt_articles` SELECT——plan 實查 8 驗 GRANT 實況 |
| exporter `datasets.py`／`check-data.mjs`／`types.ts` | append 4 條目（§8.3） | EP-D append 紀律 |
| MCP（P4 §7） | +2 工具：`get_search_eval_matrix`／`get_search_query_showcase`（讀公開 JSON；docstring 明講「離線批次預產、非即時檢索」） | additive；`search_ptt_titles`/`corpus_stats` 不進 MCP（v1 裁定沿用＋stats 無問答價值） |
| MLflow | experiment `search_eval`＋prompts `search-querygen`/`search-judge`（@prod alias，晉升走 `make search-promote-prompt` 鏡像 P2 §10） | additive 掛同一 registry |
| Grafana/Prometheus | postgres-exporter 自訂查詢 +2：`search_documents_rows`、`search_index_freshness_seconds`（`now()-max(indexed_at)`）；掛進既有 ml-lifecycle dashboard 一列 | P1 §9 姿態，零新 exporter |
| P2 §13 DAG 總表／`make ml-verify` | DAG +1；verify 腳本 +3 斷言（§12 #2/#3/#4） | additive |

---

## 11. ⌘K 邊界與 related（brief 項 8）

- **頁級 Explainer 首句（正典，逐字；深化 v1 §7.1）**：「本站站內搜尋（⌘K）是 client-side fuse.js 導航搜；真 hybrid 檢索（jieba 分詞 FTS＋e5 向量＋RRF＋rerank）在平台叢集離線跑，live 版見本頁外連 demo。」
- **palette 銜接**：3 頁 page 條目經 crosscut §2.3① registry 派生自動進 ⌘K（零本檔動作）；**`search_*` 四個 dataset 全部不進 `build-search-index.mjs`**——`search_ptt_titles` 沿 v1 §7.2 裁定（Opus 已核准「裁到零」），eval/showcase/stats 是數據非導航條目，同理不進。進化方向沿 v1（`/search?q=` 預填，繫 Signal URL-as-state）。
- **related（本支柱側 v1 落齊；反向連結由對方頁 plan 落 registry 時 additive 補——knock-on 知會 §16.6）**：
  - `/search` → `{route:'/ai-lab', label:'同一套 pgvector＋e5 hybrid 基建的另一種應用：檢索→生成（RAG）'}`、`{route:'/reco', label:'向量召回用於推薦（P6，GA4 商品域）'}`、`{route:'/ptt', label:'語料從哪來：PTT Kafka ingest 管線'}`
  - `/search/relevance` → `{route:'/ai-lab', label:'RAG 端的評測（hit_rate＋faithfulness）——不同目的的另一套量尺'}`
  - `/search/chinese` → `{route:'/ai-lab', label:'P2b 對 CJK 的原始 known-limit 記錄'}`

---

## 12. 驗收清單（每條可實跑；隨搜尋支柱 plan 生效，前置＝P3 有數日資料＋P2b-1 indexer 落地）

| # | 檢查 | 方法 | 預期 |
|---|---|---|---|
| 1 | 語料表非空＋冪等 | backfill 後 `SELECT count(*) FROM ml.search_documents` >0；重跑增量 DAG 同 logical date 列數不膨脹；HNSW/GIN×2 索引存在 | 綠 |
| 2 | 分詞增益煙囪 | 固定中文 query（如「台積電」）：`fts_raw` 0 命中、`fts_seg` >0 命中（SQL 直跑斷言） | **可實跑的分詞價值證明** |
| 3 | hybrid 煙囪 | `retrieve(q, mode='hybrid')` 回 top-10，每筆含 `vec_rank/lex_rank/rrf_score`；帶 board filter 結果全屬該板 | 綠 |
| 4 | RRF 數值同構 | `fuse.py` 純函式單測：對固定 ranks 斷言 `Σ 1/(60+r)` 與 P2 §9 參數一致 | 綠 |
| 5 | rerank 行為 | `rerank.py` 對固定 (q, docs) 回 0–1 分數且排序穩定（固定 seed/eval mode）；MPS 與 CPU 分數一致（atol 1e-3） | 綠 |
| 6 | 評測閉環 | `make search-eval` → `ml.search_eval_metrics` 5 arm × 4 指標齊、MLflow `search_eval` 有 run、sanity 閘（`fts_seg` nDCG > `fts_raw`）通過；人為壞資料反例＝非零退出不寫表 | 正例綠、反例紅 |
| 7 | showcase／datasets | `gen-search-showcase` 後 exporter 跑 → 4 檔 JSON 信封齊、cap 斷言過、absent 態（清空表重匯）頁面骨架誠實顯示 | 綠 |
| 8 | 3 頁靜態匯出＋gate | `next build` 後 `out/search{,/relevance,/chinese}/` 存在、無括號路徑；`npm run gate:explainers` 正例綠；刪 `search-chinese` 任一 `whyBuilt` 反例紅 | 符合 |
| 9 | ⌘K 邊界 | palette 無 `search_*` dataset 條目；`out/search/` 含 §11 首句全文 | 符合 |
| 10 | live 端點 | 部署後 `POST /search`（四 mode × rerank on/off）200 且分數分解齊；`GET /api/admin` 等任意 admin 路徑 404；q >200 字元 422；`SEARCH_DAILY_LIMIT` 設 1 時第 2 次請求回 429 schema（follow-up 實作後） | 符合 |
| 11 | live 同構 | live 回應 top-10 與 host 對同快照跑 `ml_search_retrieval` 相同 query 的結果一致（同 SQL 同參數） | **「demo 即生產同構」證明** |
| 12 | 誠實句式 | grep LiveDemoCard 固定句式全文＋`rel="noopener noreferrer"`；`/search/relevance` 侷限四條與 `aiVsComputedNote` 上頁；`fts_*` 標籤無「BM25」字樣 | 符合 |
| 13 | 去憑證紀律 | `grep -rE "AIza|GEMINI_API_KEY *= *[\"']|postgresql://.*:.*@" ml/search/` 為空 | 綠 |

---

## 13. plan 期待查證點（皆帶預設傾向與降級；非阻擋本 design 收斂）

1. **P2b import 錨**：P2b-1 plan 落地後對齊 `ml_rag_index.embed` 實際函式簽名（本檔語意合約＝passage/query 前綴封裝＋384 維）；簽名不合 → `ml_search_index` 內 10 行 adapter，不 fork embed 邏輯。
2. **P3 content 實跑分佈**：非空率/長度 hist/過濾率 → 校準 chunk 參數（預設 800/100 不動）與 `search_corpus_stats` bin 邊界。
3. **bge-reranker-v2-m3 實測吞吐**：host MPS（評測 50 題 × 40 docs）與 Cloud Run CPU（單次 top-40）p50；**判準：live p50 >4s → 降 `bge-reranker-base`（278M）或 `max_length 1024→512`**（誠實記錄取捨）；HuggingFace 權重下載烘 image 的體積實測。
4. **Neon 免費層實況**：pgvector extversion（≥0.8 即可，SQL 面相容 0.8.4）、HNSW 建索引記憶體、冷啟延遲；不可用 → 降級「PG data dir 烘入 container」（§7.2，同 SQL）。
5. **jieba 未登錄詞抽查**：100 篇抽樣目視切詞品質；PTT 詞彙 userdict 要不要加（加了 `seg_dict` 版本串隨之變、需全量 reindex——預設 v1 不加）。
6. **judge 人工抽查 κ**：<0.6 → rubric 迭代重標（§6.1 判準）。
7. **lucide icon 名**（§8.2 清單）：lockfile 落定擇實存者，5 分鐘校準。
8. **GRANT 實況**：`ml_writer` 對 `silver.ptt_articles` SELECT（P2 §3.4 設計已含 silver 唯讀，驗一次）；exporter 角色對 `ml.search_*` SELECT（P4 慣例同批）。
9. **ml-batch image 體積**：+jieba 詞典（~60MB）與既有依賴的層疊；超出接受線（無硬限，記錄即可）不阻擋。
10. **`search_query_showcase.json` 實測體積**：>200KB → snippet 120→80 字或題數 12→8（降階序）。

---

## 14. 本 spec 拍板 vs 下放對照

| 主題 | 本 spec 拍板 | 下放（plan） |
|---|---|---|
| 語料表 | 新表落點/DDL 全欄/索引/冪等鍵/chunk 800·100/清洗規則/去重法/known-limits | DDL 字面落地、chunk 參數依實查 2 校準 |
| 中文分詞 | 應用層 jieba（dict.txt.big＋cut_for_search）/`content_seg`+`tsv_seg`/查詢對稱/zhparser 淘汰論證/ts_rank≠BM25 誠實 | userdict 要不要加（實查 5）、segment.py 實作 |
| hybrid | 五 arm 定義/RRF SQL 形＋k=60＋top-40/filter 透傳/ef_search=100＋iterative_scan/分數分解欄 | SQL 最終字面、參數微調 |
| rerank | 模型（v2-m3）/載入法（CrossEncoder 零新依賴）/max_length 1024/輸入形/跑法界線/與 P2b 淘汰關係明標/不預設贏 | 吞吐實測與降級判準執行（實查 3） |
| 評測 | 題集 50（35+15）/pooling 20/judge 分級 rubric＋人工 κ/三指標公式/矩陣 5×4/sanity 閘/DVC 快照/侷限四條 | 題目撰寫、rubric prompt 落字、κ 實測 |
| live-demo | 新建 search-live（棄沿用 ptt-search）＋Neon 同構 SQL/API·UI·資源·安全·rate-limit 接縫·部署全形/零 admin 面/降級路徑 | URL 回填、billing alert、Neon 實查 4 |
| 頁 IA/registry | 3 頁路由/區塊表/元件落點/4 datasets 欄位級/registry 三頁正典文案/⌘K 邊界句式/related 清單 | SVG 繪製、文案潤飾（不可刪意）、反向 related 知會 |
| 資料流/守門 | 目錄/雙模式界線/DAG +1/make targets ×6/CI・MCP・監控・exporter 接點逐條/驗收 13 條 | CI yaml 落地、ml-batch paths append 實施 |

---

## 15. 精確度契約 8 條自檢

1. **開放問題收斂**：brief 8 項全落單一決定（§1 總表＋§2–§11 細節），零 TBD/兩案並陳；§13 十點皆「plan 期實查＋預設傾向＋降級判準」；P2b/P3 無實碼的處理走「鎖 design 合約錨＋窄介面＋plan 序＋降級路徑」（§0.2/§0.3），非把問題下推。
2. **版本＋context7**：§0.1 全表——CrossEncoder API/bge-reranker-v2-m3/jieba/pgvector hybrid＋iterative_scan/Neon pgvector 皆 2026-07-10 當日查證；e5/pgvector 0.8.4/sentence-transformers/fuse.js/FastAPI 沿 P2/Signal/問 AI 已證 pin 不重議；rerank 層**零新 Python 重依賴**（jieba 為唯一新增，純 Python）。
3. **欄位級契約**：`ml.search_documents` DDL 全欄（§2.2）、三張 ml 表 schema（§6.3）、4 datasets rows 形（§8.3）、live API request/response（§7.3）、registry 三頁全欄正典（§9）、指標公式（§6.2）。
4. **部署/檔案形狀具體**：目錄樹（§10.1）、DAG schedule/make targets（§10.2）、CI workflow 與 paths（§10.3）、Cloud Run 資源參數與 deploy workflow（§7.3）、頁面/元件檔落點（§8.1）。
5. **沿用慣例不重造**：P2 §8.2 schema 模式/§9 RRF 形＋k/§1④ M4 界線/§10 eval＋prompt registry/§13 host 批次慣例；P4 信封/absent/check-data/MCP；P6 eval_metrics 表形＋Faiss 淘汰同判；問 AI §0.3 無實碼處理＋§8 Cloud Run 形；v1 fuse 契約與 dataset 原樣；crosscut registry/gate/LiveDemoCard/route groups 零改。
6. **進化非複刻**：ptt-search 只取前身敘事（§8.2 `predecessor`）；對 P2b＝「換語料＋加三層」明標新建 vs 複用（§0.2 表）；rerank 與 P2b 相反決策的語境對照（§5）；分詞從 known-limit 到可量測修復（§3）。
7. **硬約束貫徹**：拓撲（3 頁純靜態讀 committed JSON、真運算叢集/host、live 為外連獨立端點）；一工一具（向量只 pgvector、embedding 只 e5、分詞只 jieba、rerank 一顆、排程只 Airflow、DB 只 Postgres——Neon 是 live 專用同構副本非第二引擎，§16.3 供覆核）；只 additive（§10.3 逐條）；M4/CPU 友善（rerank/embedding 全程 CPU 可跑）；誠實（矩陣不冒稱 BM25、rerank 不預設贏、評測侷限四條、live 冷啟/快照如實標）；emoji→lucide；非互動不提問（全檔零待問）。
8. **每步可測**：§12 十三條全給命令/斷言與預期，含分詞增益煙囪（#2）、live 同構證明（#11）、gate 與 sanity 閘反例（#6/#8）。

---

## 16. 給 Opus 的把關提示（覆核建議點）

1. **live-demo 目標端點改判**（§7.1）：crosscut §7.2 v1 配置寫「搜尋支柱 ✅ ptt-search 既有部署」——本檔依 brief-v2 授權改為新建 `search-live`，ptt-search 保留部署但 v1 不外連（其 admin 資安 gating 因此自然解除）。需在 crosscut §7.2/§3.1 補一行修訂註記（additive），並知會 Fergus「作品集不再外連 ptt-search」。
2. **ml/batch image 追加套件＋ml-batch-ci paths append**（§10.3）：對「不改 P2 資產」的邊界解讀——本檔判為 P2 §2 設計內的擴充接縫（該 image 本就是共用批次載體）；若判過線，fallback＝`ml/search` 自有 KPO image（多一個 image 的代價，設計其餘零變）。
3. **Neon 引入**（§7.2）：live-demo 專用的雲上同構 PG 副本——「DB 只 Postgres」未破（仍是 Postgres）、成本 0（免費層＋scale-to-zero），但確實是平台外的第二個資料存放點；替代案（PG 烘入 container）已備。值得確認 Fergus 對「多一個免費雲資源」的接受度。
4. **rerank 與 P2b §9 的相反決策**（§5）：本檔以「不同語境兩個都對」處理並寫進頁面敘事——請覆核此對照的呈現不會被讀成「P2b 當初錯了」（文案已刻意中性）。
5. **plan 序依賴**（§0.2）：本支柱 plan 前置＝P2b-1 indexer plan（`ml_rag_index.embed` 單一真源）；若排程衝突，降級路徑存在但預設不走——排 plan 佇列時留意。
6. **反向 related**（§11）：`/ai-lab`/`/reco`/`/ptt` 頁的 registry 條目歸 P4/P6/P3 各自 plan——反向連結需各該 plan additive 補一行，本檔只能知會不能代改。
7. **評測 sanity 閘的第二條**（`hybrid ≥ max(單通道) − 0.02`，§6.3）：RRF 理論上可能在特定題集輸最強單通道更多——若實跑觸發，正確動作是調 top-N/k 並記錄而非放寬閘；plan 落地時把「調參紀錄」寫進 runbook 防止直接改閘值。

---

## 17. Opus 把關註記（2026-07-10；PASS）

規劃 session（Opus 4.8）依既有四份 design 同款把關流程覆核本 design v2：獨立 context7 覆核承重宣稱、逐項裁定 §16 風險點、驗拓撲/一工一具/additive/grounding 誠實/資安五道鐵律。**結論：PASS，可 commit。**

### 17.1 承重宣稱獨立覆核（非轉抄 Fable 5 §0.1，Opus 當日自查）

| 宣稱 | Opus 獨立覆核 | 判定 |
|---|---|---|
| **sentence-transformers `CrossEncoder` 載入任意 HF cross-encoder＝零新依賴＋CPU 可跑** | context7 `/websites/sbert_net` package reference 逐項確認：`CrossEncoder(model_name_or_path, device='cpu'\|'mps', activation_fn=…, max_length=…)`（device 參數明列 `"cpu"`/`"mps"`；`activation_fn`/`max_length` 皆列名參數）；`.predict(pairs)` 配 `torch.nn.Sigmoid()` 回 0–1；`.rank(query, docs, top_k, batch_size)` 回 `[{corpus_id, score, text?}]`；官方明述「download a pre-trained CrossEncoder model… construct a model from the Hugging Face Hub with that name」＝**任意 HF cross-encoder（含 bge-reranker-v2-m3）可名載入**——rerank 層零新依賴＋CPU 宣稱**成立** | ✅ CONFIRMED（rerank 層＝本支柱 marquee 能力，此為整個 §5＋live-demo §7 的地基） |
| **jieba `dict.txt.big` 繁體分詞＋`cut_for_search`** | context7 `/fxsjy/jieba` 官方 README 逐字確認：`jieba.set_dictionary('dict.txt.big')`「for better Traditional Chinese segmentation」、`cut_for_search` 搜尋引擎模式——`/search/chinese` 整頁 CJK 工程地基**成立** | ✅ CONFIRMED |
| pgvector hybrid＝RRF/cross-encoder 官方正典＋`iterative_scan`；Neon pgvector ≥0.8＋HNSW；e5/0.8.4/FastAPI 等沿 pin | 沿 P2/問 AI/Signal 已證 pin，Fable 5 §0.1 當日查證表接受（RRF 融合形在問 AI/P6 已多次覆核） | ✅ 接受 |

兩個新 marquee 宣稱（CrossEncoder 零依賴 rerank、jieba 繁體分詞）皆 Opus 第一手 context7 獨立確認，非僅信 Fable 5 回報。

### 17.2 §16 風險點逐項裁定

1. **live-demo 目標改判（crosscut §7.2 knock-on）**——**核准**。brief-v2（Opus 撰）已明文授權新建 search-live；crosscut §7.2「搜尋支柱 ✅ ptt-search 既有部署」是 v1 前提，search v2 翻案後屬被取代句。Opus 已於 crosscut §7.2 補 additive 改判註記（指向本 design §7，並收束 §8.2 待裁決 #4＋line 131 草樣）保持 spec 語料一致。**須知會 Fergus：作品集 v1 不再外連 ptt-search**（見回報）。
2. **ml/batch image 追加 jieba＋ml-batch-ci paths append**——**核准**（判為 P2 §2 設計內接縫：該 image 本就是「裝本地套件的共用批次載體」，追加套件＝按設計意圖用接縫，非改 P2b 自有套件；jieba ~60MB 詞典對 P2b 批次的膨脹可忽略）。fallback（`ml/search` 自有 KPO image）為乾淨逃生口，無阻擋。
3. **Neon 引入**——**核准 spec，但列為需 Fergus 知會的決策點（非阻擋）**。Neon＝live-demo 專用雲上同構 PG 副本（免費層＋scale-to-zero＝成本 0、唯讀角色），仍是 Postgres 故「DB 只 Postgres」未破；但確為平台外第二資料存放點，較問 AI §8（Cloud Run＋Gemini、無 DB）多一個外部資源。判定不阻擋 spec 收斂，因：①成本 0 ②降級路徑（PG 烘入 container、同 SQL）已備 ③live-demo-only 非平台基建 ④§13 實查 4 已列 plan 期定案。**Fergus 決策點**：接受多一個免費雲資源（Neon）vs 走烘入 container 降級——見回報。
4. **rerank 與 P2b §9 相反決策的呈現**——**核准，且嘉許**。Opus 讀 §5 line 220＋registry `predecessor` line 385：框架「同一技術、兩個語境、兩個都對」明確歸因 P2b＝生成鏈成本取捨（grade 節點已擔 relevance）、本支柱＝檢索品質工程本體＋成本紅線不適用；文案中性，讀作架構判斷力敘事而非「P2b 當初錯了」。此對照是**加分項**（展示同平台跨語境的取捨判斷）。
5. **plan 序依賴 P2b-1 → search**——**核准，並更新硬排序**。search indexer `import ml_rag_index.embed`（e5 前綴單一真源），故 P2b-1 indexer plan 必先行。此與問 AI plan 同依賴 → **plan 佇列硬序：P2b-1 indexer plan → {問 AI plan ∥ search plan}**（兩者皆吃 P2b-1，彼此無序）。已記 memory。
6. **反向 related（`/ai-lab`/`/reco`/`/ptt`）**——**核准處理**。反向連結歸 P4/P6/P3 各自 plan additive 補一行，本 design 只知會不代改（正確邊界）。plan 期 knock-on，現無動作。
7. **sanity 閘第二條**——**核准**。RRF 是穩健性優於峰值的取捨，不保證每題集勝最強單通道；−0.02 容差合理，「觸發＝調參並記錄、不放寬閘」的紀律正確，plan runbook 落實。

### 17.3 Opus 自查五鐵律（超出 §16 清單）

- **grounding 誠實（本次最關鍵）**：§0.2/§0.3 誠實記錄 **P2b 與 P3 皆無實碼**（`ml/`/`lakehouse/` 空），鎖 design 合約錨＋窄介面＋plan 序＋降級路徑，鏡像問 AI §0.3 先例。✅ 未從記憶捏造實碼細節。
- **拓撲鐵律**：3 頁純靜態讀 committed JSON、真運算叢集/host、live＝外連獨立端點（Neon 是 live 專用副本非站上運算）。✅
- **一工一具**：向量只 pgvector（不引 Faiss，同 P6）、embedding 只 e5、分詞只 jieba、rerank 一顆、排程只 Airflow、DB 只 Postgres。§16.3 誠實處理 Neon「第二存放點」nuance。✅
- **只 additive**：新表 `ml.search_documents`（不動 `rag_documents` CHECK）、新 DAG、append datasets/MCP/CI/監控，§10.3 逐條標。✅
- **資安**：§12 #13 去憑證 grep 閘、Neon 串走 GH secret→Cloud Run env fail-fast、SQL 全參數化、search-live **零 admin 面**——正面解決 v1 揪出的 ptt-search admin 無認證發現（不碰 ptt-search separate repo）。✅ 邊界處理正確。

**綜合：PASS。** 兩承重宣稱獨立 confirmed、七風險點皆裁、五鐵律皆過、grounding 對 P2b/P3 無實碼誠實處理。commit 至 trend repo（不加 Co-Authored-By footer，per 專案 repo 規則）。**留待 Fergus 兩決策點**（Neon 接受度、作品集不再外連 ptt-search 的確認）＋**plan 佇列硬序**（P2b-1 → search∥問 AI）記入 memory。
