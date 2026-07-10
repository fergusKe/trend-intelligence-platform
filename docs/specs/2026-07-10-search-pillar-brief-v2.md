# 搜尋支柱 spec — brief v2（平台側自建進階中文檢索：hybrid BM25+向量 RRF ＋ rerank ＋ 檢索評測；複用 P2b 向量基建，換 P3 PTT 語料）

> **精確度契約**：依 repo `CLAUDE.md`「Fable 5 design 精確度契約（8 條）」交辦；design 逐條自檢，開放問題收斂成決定不下推。
> **取代**：本 brief 取代 [`2026-07-10-search-pillar-brief.md`](2026-07-10-search-pillar-brief.md)（v1＝忠實拆解 ptt-search 單頁，已標 SUPERSEDED）。**方向翻案緣由（Fergus 2026-07-10 定案）**：ptt-search 原本工程亮點不足（ES `bool` query＋smartcn＋`more_like_this`＋`search_logs` 偏基礎），作為求職 portfolio 的「搜尋工程能力展示」深度不夠。新方向＝**在平台側真建一個進階中文檢索子系統**，與平台既有 RAG/召回基建同源、專注展示**檢索相關性工程**的深度。守 [[feedback_evolve_beyond_past_projects]]（參考是輸入非天花板；要有進化方向）。
> **框架上游（binding，不得抵觸）**：
> - [統一作品集 crosscut design](2026-07-10-unified-portfolio-crosscut-design.md)——§2.2（搜尋支柱 segment `/search`、icon `Search`、首頁）、**§2.3（⌘K 全站搜 vs 搜尋支柱邊界釘死＋站內離線示範語料）**、**§7（整合模式 Option A 四件套：預產 JSON＋架構圖＋MCP＋選配 live-demo 外連）＋§7.2（live-demo 慣例與誠實固定句式）**、§5（說明式 registry）、§8.2（ptt-search 取材：保留部署不退役）、§10 對照表。**拓撲鐵律（§6.4）不破**：前端純靜態 export，真運算（embedding/檢索/rerank/評測）在平台叢集/離線。
> - [Signal 設計系統 design](2026-07-10-frontend-design-system-design.md)——視覺 token/元件/字階地基（Recharts 圖表、Fira Code、fuse.js §7、lucide 無 emoji），不重定。
> - **P2b 基建（已鎖合約，主複用對象，唯讀）**：[P2 ML verticals design](2026-07-08-P2-ml-verticals-design.md)——§0 pin（pgvector 0.8.4／`intfloat/multilingual-e5-small` 384維多語含中文／sentence-transformers 5.6.0／psycopg 3.3.4＋pgvector-python 0.5.0）、§3.4（`ml` schema＋pgvector 化）、**§8（P2b-1 RAG 語料索引：`ml.rag_documents` schema＝`embedding vector(384)`＋`tsv tsvector` FTS＋HNSW＋GIN；e5 前綴 passage/query 封裝於 `embed.py`）**、**§9（P2b-2 hybrid `retrieve`：pgvector cosine top-40＋FTS top-40 → RRF 融合 k=60；CJK 誠實註記＝`simple` FTS 不分詞中文、靠 e5 向量補、pg_trgm 備援；§9 明確淘汰 cross-encoder rerank——那是 RAG 生成鏈的成本判斷，見下）**、服務形 FastAPI `ml/rag/service/`。
> - **P3 PTT 語料（已鎖合約，語料源，唯讀）**：[P3 ptt-ingest design](2026-07-08-P3-ptt-ingest-design.md) §Silver `lakehouse.silver.ptt_articles`（有 `content` 正文欄＋title＋author_id/nick＋board＋category＋post_date；Postgres serving 副本同構；additive-only 穩定性政策）。
> - **P6 召回（邊界釐清，唯讀）**：[P6 recommendation design](2026-07-09-P6-recommendation-design.md)——P6 用 pgvector+e5+RRF(k=60) 做 **GA4 商品推薦召回**（item2vec CF＋語意＋熱門）；資料面＝GA4 item，**與搜尋支柱的 PTT 文本檢索不重疊**，但同屬「pgvector+e5+RRF 平台範式」。搜尋支柱與 P6/P2b 用 `related` cross-link 互指，不重繪彼此。
> **接地鐵律（grounding-first，違者作廢）**：Fable 5 須**第一手 grep**：
> - **P2b 實作合約錨**（trend repo `ml/rag/service/src/rag_service/`——若 P2b 尚無實碼則鎖 P2 design 合約，同問 AI spec §0.3 誠實處理）：`retrieval.py`（hybrid RRF SQL 形狀）、`embed.py`（e5 前綴慣例）、`ml.rag_documents` DDL、FastAPI 服務形——證明「複用 P2b 檢索基建」可行，錨進 design。
> - P3 `silver.ptt_articles` 欄位級合約（`content` 長度分佈、language、board/category 值域）——確認可 embedding（content 非空率）。
> - ptt-search（`/Users/fergus/Desktop/workshop/fergus/data-workshop/fergus/ptt-search`）僅取「前身/基礎版對照」敘事素材（ES bool query/smartcn 作為「進化起點」對照），**不再是主體**。
> - 版本敏感處（pgvector HNSW、sentence-transformers rerank/cross-encoder 模型、e5、fuse.js）用 context7。
> **本階段只出 spec，plan 延後。**

---

## 一句話目標

搜尋支柱＝**平台側自建的進階中文檢索子系統展示**：用 P3 PTT 語料（`content`＋title）在平台側真跑 **hybrid 檢索**（BM25/FTS ＋ dense vector RRF 融合，複用 P2b pgvector+e5 基建）＋ **rerank 重排**（cross-encoder，檢索工程專屬進階層）＋ **檢索相關性評測**（recall@k／nDCG／MRR，BM25 vs vector vs hybrid vs +rerank 對比矩陣＝核心展示品），以 crosscut §7 四件套呈現（預產評測 JSON＋管線架構圖＋MCP＋live-demo 外連）。**與平台 RAG（P2b）/召回（P6）同源、專注檢索品質工程**；ptt-search 降為「前身/基礎版對照」敘事。拓撲鐵律不破：真運算在叢集/離線，前端純靜態讀 committed JSON。

## 為什麼這是 grounded 而非畫大餅（複用邊界＝本 spec 的靈魂）

平台**已有 hybrid 檢索的全部基建**：pgvector 0.8.4、e5-small 多語 embedding（含中文）、`ml.rag_documents` 的 `embedding+tsv` 雙通道 schema、hybrid RRF 融合 SQL（P2b §9 已實作 over YouTube 留言）、e5 前綴封裝、FastAPI 服務形。**搜尋支柱不重造這些**——換語料（P3 PTT `content`）、加檢索工程專屬的三個新亮點層（評測 harness／rerank／CJK 深化），把「平台會用 pgvector」進化成「平台懂檢索相關性工程」。這就是「進化非複刻」：P2b 的檢索是 RAG 生成的前置手段，搜尋支柱把檢索品質本身當主體展示。

## Fable 5 要收斂拍板的項目（逐一給明確決定）

1. **語料表落點（守 additive 的關鍵裁定）**：P2b `ml.rag_documents` 的 `doc_type CHECK IN ('comment','video_meta')`＋`UNIQUE(doc_type,source_id,embedding_model)`——加 PTT 要改 CHECK＝**改 P2b（可能違只 additive）**。**傾向＝平行新表 `ml.search_documents`（或 `ml.ptt_documents`）**：同 schema 模式（`embedding vector(384)`＋`tsv`＋HNSW＋GIN），複用 `embed.py`/RRF SQL 邏輯但獨立表，不改 P2b。Fable 5 確認並定表名/欄位/冪等鍵/chunk 策略（PTT 長文要不要切 chunk，對照 P2b `video_id#chunk_n`）。
2. **hybrid 檢索管線細設**：複用 P2b §9 retrieve 形（pgvector cosine top-N＋FTS `plainto_tsquery('simple')` top-N → RRF k=60），over PTT 語料；filter（board/category/date 透傳 WHERE）；**中文分詞誠實工程**（承接 P2b CJK 註記並深化：`simple` FTS 不分詞中文的處置——e5 向量補、pg_trgm、或引入中文分詞 FTS 方案如 zhparser/pg_jieba 作為對照實驗，拍板要不要 additive 引入還是誠實標 known-limit）。
3. **rerank 進階層拍板**：P2b §9 為 RAG 生成鏈的**成本判斷淘汰了 cross-encoder rerank**。搜尋支柱作為**檢索相關性工程展示**、且成本紅線不適用（portfolio 跑 infra 是目的），加一層 cross-encoder rerank（如 `bge-reranker` 系列，M4/CPU 可跑）對照展示「rerank 對 nDCG 的增益」有真實展示價值。Fable 5 拍板：模型選型（context7 查）、跑法（batch 離線）、**明標與 P2b 淘汰決策不衝突**（不同目的：P2b＝生成前置的成本取捨、搜尋＝檢索品質工程的展示；此對照本身是架構判斷力敘事）。若判定不做，須誠實論證並列進化方向。
4. **檢索評測 harness（核心展示品）**：相關性標註集怎麼來（拍板：LLM-judge 產 query-doc relevance 標註 vs 規則式 pseudo-relevance vs 小型人工集——grounded 判準）、指標定義（recall@k/nDCG@k/MRR 公式進 registry `formula` 可稽核）、**對比矩陣**（BM25-only／vector-only／hybrid／hybrid+rerank 四法 × 指標）＝評測結果預產成靜態 JSON 上頁。誠實標「評測集規模與方法侷限」。
5. **live-demo 部署拍板**：真檢索端點——**新建 Cloud Run 檢索 demo over PTT 語料**（對照問 AI spec §8 的 Cloud Run 形態：資料/索引烘入 image 或連輕量 PG）vs 沿用/取代 ptt-search 既有部署。守 crosscut §7.2 誠實固定句式＋hostname＋`rel="noopener noreferrer"`＋失效降級態文案。**注意 v1 admin 資安**（v1 design Opus 把關揪出 ptt-search admin 無認證——若新建端點務必無此問題；若沿用 ptt-search 須先收斂）。
6. **頁 IA（不再是單頁）**：crosscut §2.2 授權頁數——收斂 `/search` 支柱頁清單（傾向：檢索管線敘事／評測對比／中文處理工程／live-demo，可多頁或分區）；每頁版面型別（評測對比用 Recharts）。含 crosscut §2.3 的**站內離線示範**＝fuse.js 保留作「最陽春對照層」（三層對照敘事：fuse 字元模糊 → BM25 詞彙 → hybrid+rerank 語意，比 v1 的兩層對照更有料）。
7. **資料流與守門（全 additive，四件套落地）**：embedding backfill 跑法（M4 host `make` 批次，沿 P2b §71 backfill 慣例）、hybrid/rerank/評測引擎落點（`ml/search/` 或類）、評測結果 dataset（`search_*.json` 前綴，crosscut 決策 13 保留＝v1 用掉 `search_`；P4 信封）、MCP 工具 additive、CI。**不改 P2b/P6/P3 既有資產**。
8. **registry 條目＋⌘K 邊界＋與 P2b/P6 的 related**：每頁 `whyBuilt`/`whatItDoes` 硬性（阻擋級）；⌘K vs `/search` 邊界頁內 Explainer（承接 v1 §7.1 誠實聲明，深化為「站內 ⌘K＝fuse.js 導航搜；真 hybrid 檢索在平台側/live-demo」）；`related` cross-link 到 `/ai-lab`（P2b RAG「同一 hybrid 基建的另一種應用：檢索→生成」）與 `/reco`（P6「向量召回用於推薦」）。

## 硬約束（違者作廢）

- **拓撲鐵律**：`/search` 頁純靜態 export、build-time 讀 committed JSON、觸不到 k8s；真運算（embedding/檢索/rerank/評測）在平台叢集/離線批次；站內即時互動＝fuse.js（陽春對照層），真 hybrid 檢索在 live-demo 外連（獨立部署）。
- **主複用 P2b 不重造**：pgvector/e5/embed.py 前綴慣例/hybrid RRF SQL 形/FastAPI 服務形全複用；**一工一具**（向量檢索只 pgvector、不引 Faiss——同 P6 §18 判定；embedding 只 e5-small）。新建＝平行語料表＋rerank 層＋評測 harness＋前端。
- **只 additive**（EP-D）：不改 P2b `rag_documents`/graph、不改 P6 `reco_*`、不改 P3 `ptt_articles`／地基；dataset 前綴 `search_`、`ml.search_*` 表、dbt tag（若用）自有前綴。
- **grounding / 誠實**：評測集方法與規模侷限誠實標；rerank 與 P2b 淘汰決策的關係明標；CJK 分詞弱點承接 P2b known-limit 不藏；ptt-search 對照敘事誠實（前身非主體）。**說明式 registry 阻擋級**（缺 `whyBuilt`/`whatItDoes`＝gate fail）；**emoji→lucide**。
- **成本紅線不適用**（portfolio 跑 infra 是目的）——但仍守「一工一具」「M4/CPU 友善」（rerank/embedding 選 CPU 可跑的模型，不假設 GPU）。

## Scope

- **in**：語料表落點裁定、hybrid 檢索管線（複用 P2b over PTT）、rerank 進階層、檢索評測 harness 與對比矩陣、live-demo 部署、`/search` 頁 IA（含 fuse.js 陽春對照層）、資料流 additive（backfill/引擎/dataset/MCP/CI）、registry 條目、⌘K 邊界、與 P2b/P6 的 related、驗收。
- **out**：改 P2b/P6/P3 既有資產、Signal token 重定、⌘K palette 機制改動（沿 Signal §7）、P2b RAG 生成鏈改動（搜尋只用檢索面，不碰 generate 節點）。

## 產出

寫到 `docs/specs/2026-07-10-search-pillar-design-v2.md`；檔頭指向本 brief-v2＋精確度契約＋crosscut＋P2b/P3/P6。附「plan 期待查證點」（含 P2b 實作 import 錨、rerank 模型實測、評測集產法）與「本 spec 拍板 vs 下放」對照。**不 git commit**（Opus 把關後處理）。完成回報：檔案路徑、8 項拍板摘要、context7/grep 查證項（尤其 P2b hybrid retrieve/embed 合約錨、P3 content 欄、rerank 模型 context7）、給 Opus 覆核的風險點。
