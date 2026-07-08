# 北極星架構 — trend-intelligence-platform

> 本檔是整個專案的**架構正本**。所有 spec / plan / 實作決策以本檔為準；本檔沒定的細節，由各階段 spec 收斂。
> 定位：**求職 portfolio**（不是要低成本營運的產品）。因此「用 k8s、跑常駐服務」是**目的本身**，不是壞味道——這條跟一般 SaaS 的成本紅線無關。

---

## 一句話定位

**端到端「趨勢智能」資料平台**：以 YouTube 熱門趨勢為主幹（PTT 爬蟲為第二來源），從 ingest → Lakehouse → 建模，同時展示 **DE（資料工程）＋ MLOps/LLMOps（模型維運）＋ DevOps（k8s + GitOps）** 三層一體，全程跑在**本地 Kubernetes**、GitOps 部署、完整可觀測性。

一個平台打三種職缺：投**資料工程師**講 DE 層、投 **MLOps** 講 ML 層、投**平台/DevOps** 講整體。

---

## 核心設計原則（不亂的保證）

這個專案刻意涵蓋 DE+MLOps+DevOps 三種能力，但**不做成三個散專案，也不做成 finmind 那種 32 容器怪物**。紀律如下：

1. **一個平台、三層疊，不是三個並排專案**。DevOps/k8s 是**底座**（整個平台跑的方式），不是獨立 side project——「我整個平台都 GitOps 部署、有完整監控」比「我有一個玩具 DevOps demo」資深得多。
2. **一個工作只用一個工具**（亂的真正來源是工具冗餘，不是能力廣度）：
   - 排程只用 **Airflow**（不要再加 Celery/APScheduler/RabbitMQ 當排程）。
   - 資料庫只用 **PostgreSQL**（OLTP + Gold 聚合都它；**不用 ClickHouse、不用 DuckDB**）。
   - 監控只用 **Prometheus + Grafana**（不要 9 件套 UI 堆疊）。
   - 串流工具**只用 Kafka、且只在 P3**（KRaft 單 broker、免 Zookeeper）：P3 的佇列驅動爬蟲用它，**不引入 RabbitMQ、不引入 Celery、不引入 Redis**（一種 messaging 範式就好）。P1/P2 不用串流。
3. **一個資料主幹（YouTube）餵所有層**。同一份資料同時餵 DE lakehouse、tabular 模型、LLM/RAG——這樣才不會長成兩個 domain。
4. **層與層邊界乾淨**：每層有明確輸入/輸出介面，可獨立理解、獨立 demo。
5. **分階段交付**：P0→P5 每階段獨立可展示、各一份 spec，疊上去。

---

## 為什麼主幹是 YouTube（而非 PTT / 金融）

因為 ML 三條線（**tabular 時序預測** / **LLM/RAG** / **微調**）橫跨數字與文字兩種模態，資料必須「同時有數字、也有文字」：

| 要展示的 | 需要的資料 | YouTube | PTT |
|---|---|---|---|
| DE lakehouse（Medallion/dbt/時序） | 結構化 + 隨時間變的數字 | ✅ 觀看/讚/互動/velocity，每小時更新 | 🔶 文字為主，數值弱 |
| tabular 模型（RandomForest→MLflow→KServe） | 特徵→明確預測目標的數值題 | ✅ 用影片特徵預測會不會爆 | ❌ 沒有乾淨的數值預測目標 |
| LLMOps / RAG | 大量文字語料 | ✅ 標題/描述/字幕 | ✅ 論壇文字（強） |

YouTube 是唯一「一個題材餵滿三塊」的來源，且資料每小時更新、趨勢會變 → 模型**真的會漂移** → drift 監控與自動重訓的故事是真的，不是演的。API 資料也穩定可重現（爬蟲會因網站改版而壞，是 demo 地雷）。

**PTT 爬蟲**當**第二 ingest 範式**（P3）：補上「處理不可靠來源＋佇列＋容錯＋反爬」這塊硬實力。真實 DE 工作 ingest 其實**以 API/DB/串流/檔案為主，爬蟲是加分的稀有技能**，所以 API 主幹更具代表性、爬蟲當加分。

---

## 目標技術棧（來自三門課的業界交集）

| 分層 | 工具 | 階段 |
|---|---|---|
| 容器 / 編排 | Docker, **Kubernetes**（本地 kind/k3d/minikube）, HPA | P0 |
| CI / CD / GitOps | **GitHub Actions**（build+test+lint+docker）, **ArgoCD**（pull-based GitOps） | P0 |
| 可觀測性 | **Prometheus + Grafana** | P0 |
| 資料管線編排 | **Apache Airflow** | P1 |
| YouTube ingest | 影片 metadata（API）**＋ 留言語料 `commentThreads.list`（百萬列量級，是 Spark/Iceberg 的真實理由）** | P1 |
| Lakehouse | **MinIO/S3 + Apache Iceberg**, **Spark**（Bronze→Silver；留言大表是 Spark 的正當負載）, **dbt**（Silver→Gold, DQ 測試） | P1 |
| 儲存 | **PostgreSQL**（Gold；向量庫用 **pgvector** 同一顆 Postgres） | P1 |
| 串流 | **Kafka**（KRaft 單 broker，佇列驅動爬蟲；**唯一** messaging，不加 RabbitMQ/Celery/Redis） | P3 |
| ML 生命週期（tabular） | **DVC**（資料版本）→ **MLflow**（追蹤+Registry, Staging→Prod）→ **KServe**（k8s serving）→ Airflow 重訓 + drift 監控 | P2 |
| ML 生命週期（LLMOps/RAG） | **LangChain + LangGraph**（agentic RAG + CRAG 自我校正，取代 CrewAI）＋ **pgvector** 向量庫 ＋ **本地 embedding**（百萬留言不打外部 API）＋ **生成可切換**（本地 Ollama 預設 / Gemini API fallback＋A-B）＋ hybrid 檢索 ＋ prompt 版本 ＋ 評估閘 ＋ 成本/延遲監控 | P2 |
| ML 生命週期（微調） | **HuggingFace**（可攜、標準、M4 免費跑小模型）：**(A) DistilBERT 留言情緒分類器**（LLM 弱標註→蒸餾→KServe CPU serving）＋ **(B) 小 LLM LoRA 標題生成器**（PEFT LoRA fp16，真實爆紅標題當語料）。微調算力**原生跑 M4/Metal**（kind 的 Linux VM 摸不到 Apple GPU），產出模型上 MLflow/MinIO、可攜雲端 GPU | P2 |
| 呈現層（對外） | **Next.js**（讀匯出資料、部署 **Vercel**）；平台端 Gold→CSV/Parquet 匯出 DAG | P4 |
| 對外資料介面（加分） | **MCP server**（FastMCP 把 Gold 趨勢資料開成工具，讓 Claude 等 agent 直接查）＝差異化 add-on | P4/P5 |
| 收尾加分 | 安全掃描（**Trivy＋gitleaks＋CodeQL**，課程缺口）, 架構圖（Mermaid×4）, 面試敘事（三 JD one-pager＋`DECISIONS.md` ADR-lite） | P5 |

**刻意省略以避免過度工程**：Kubeflow、Feast、Seldon、Terraform、service mesh、多雲、~~ClickHouse~~、多套排程器、~~**RabbitMQ/Celery/Redis**~~（串流只 Kafka）、**CrewAI**（agent 編排改 LangGraph）、**MLX**（微調框架收斂到 HuggingFace；MLX 僅在日後想在 Mac 上練更大模型時才當加分項，其輸出本就可攜故不衝突）、**Streamlit**（呈現統一 Next.js）。〔**2026-07-09**：ClickHouse/Redis 已由「GA4 第二真來源 ＋ 三工具翻案」段各以獨特職務正當化，不再省略；Flink 亦於該段加入即時特徵層。仍省略：Kubeflow/Feast/Seldon/Terraform/service mesh/多雲/多套排程器/CrewAI/Streamlit〕

---

## 分階段藍圖（P0–P5，每階段一份 spec）

| 階段 | 目錄 | 內容 | 打哪種 JD | 獨立可 demo |
|---|---|---|---|---|
| **P0 平台底座** | `platform/` | 本地 k8s 叢集 + namespace 佈局 + **ArgoCD GitOps** + **GitHub Actions CI** 骨架 + **Prometheus/Grafana**。驗收：一個 hello service 用 GitOps 上線、有儀表板 | DevOps/平台 | ✅ |
| **P1 資料管線** | `ingestion/` `lakehouse/` `orchestration/` | YouTube API ingest（影片 metadata **＋留言語料**）→ MinIO/Iceberg Bronze → Spark Silver → dbt Gold(Postgres) → Airflow 編排 + dbt DQ 測試。**留言百萬列＝Spark/Iceberg 的真實負載，同時餵 P2 RAG 語料與微調訓練資料** | 資料工程師 | ✅ 完整 lakehouse |
| **P2 三條 ML 垂直** | `ml/` | **(a) tabular**：DVC→MLflow→KServe→drift/重訓（影片表現時序預測，取材 youtube-analytics 的 RandomForest）。**(b) LLMOps/RAG**：LangGraph agentic RAG + CRAG over 留言/文字，pgvector + 本地 embedding + 生成可切換（Ollama/Gemini）+ 評估閘 + 成本監控。**(c) 微調**：HuggingFace（A DistilBERT 情緒分類器＋B 小 LLM LoRA 標題生成器），算力原生跑 M4、產出上 MLflow 可攜雲端 | MLOps / LLMOps | ✅ 完整模型生命週期 |
| **P3 進階 ingest** | `ingestion/` | PTT 分散式爬蟲當第二來源（取材 ptt-crawler 的容錯內核）；**佇列範式鎖定 Kafka**（KRaft 單 broker，consumer 手動 commit offset＝at-least-once），跟 P1 批次刻意不同的串流 ingest | 差異化（爬蟲硬實力＋Kafka） | ✅ |
| **P4 呈現層** | `frontend/` + `orchestration/`（匯出 DAG） | Next.js 儀表板讀「Gold/ML 匯出資料」→ **部署 Vercel**（唯一對外可見產物）；平台端加 Gold→匯出（CSV/Parquet）步。**平台本身不部署**（本地 kind 按需跑） | 前端/全端 + 展示整體 | ✅ 公開網址 |
| **P5 收尾** | 全域 | CI 補安全掃描、架構圖、README 打磨、面試敘事 | 全部 | — |

**建置順序**：P0 必須先做（其他都跑在它上面）。P1 → P2 → P3 依序；P4 呈現層吃 P1 Gold + P2 ML 匯出（可在 P2 後做）；P5 收尾最後。P2 的三條垂直 (a)(b)(c) 已收斂成**單一份 design**（`0032afc`），實作時可切成三個並行 task 群。

### 呈現層與部署拓撲（P4；2026-07-08 定案）

**問題**：平台跑在本地 k8s，別人看不到；只給 repo 不夠有說服力。**決策**：
- **平台不上雲**（求職展示不值得常駐雲成本）→ 本地 kind 按需 `make cluster-up` 跑，用**截圖/GIF/架構圖**佐證「真的會操作 k8s/GitOps/監控」。
- **前端上雲**：`frontend/`（Next.js）**部署 Vercel**，是唯一對外公開、可點連結的產物——「示範網站 + 背後架構」一次講完。
- **合約邊界 = 匯出資料檔**：平台端一支 Airflow DAG 把 Gold marts（＋P2 ML 輸出）匯出成 **CSV/Parquet**，前端純讀該檔渲染（JAMstack「預先算好資料 → 靜態呈現」範式，公開資料儀表板常態）。前端對平台的唯一依賴＝這包檔的 schema。
- **monorepo 不拆 repo**：前端住同一 repo 的 `frontend/` 子目錄（自成一體、獨立部署），一個連結講完整條龍、不重演「散落多 repo」問題；Vercel 設 root dir = `frontend/` 原生支援子目錄部署。**不用 Streamlit**（分析與呈現統一 Next.js）。
- 匯出目標（committed 靜態檔 vs 免費 Neon serving DB vs 物件儲存）由 P4 spec 收斂。

---

## 可複用素材地圖（別重造，從既有專案取材）

全部在 `/Users/fergus/Desktop/workshop/fergus/` 底下，**唯讀取材，不改原專案**。

| 來源專案 | 取什麼 | 用於 |
|---|---|---|
| `data-workshop/fergus/yt-trending-platform` | **lakehouse 底盤主範本**：Airflow3(Celery+Redis) 的 `x-airflow-common`、MinIO/Iceberg、PySpark `bronze_to_silver`、dbt medallion marts、Prometheus/Grafana + exporter、**GitHub Actions PR/deploy workflow**、YouTube API hook。docker-compose 13 服務是 k8s 化的起點 | P0/P1 |
| `data-workshop/fergus/ga4-analytics-platform` | yt-trending 的雙胞胎 blueprint（同 Airflow common + dbt medallion + extractor + Gemini 週報敘事）→ 交叉驗證範本、LLM 敘事報表可借 | P1/P2(b) |
| `data-workshop/fergus/youtube-analytics` | **ML 兩條的料**：`pages/.hidden/8_影片表現預測.py` 的 RandomForest+StandardScaler（tabular）、`src/ai/core/{rag_pipeline,qdrant_manager}.py` + agents（RAG/LLMOps）。注意：原碼耦合在 Streamlit，需**抽離**成獨立服務 | P2(a)(b) |
| `data-workshop/fergus/ptt-crawler` | **分散式爬蟲範本**：`crawler/{producer,tasks,worker}.py` 的 asyncio producer + Celery 可靠性（acks_late/persistent/fork engine.dispose）+ 失敗頁退避重試 | P3 |
| `data-workshop/fergus/finmind-system` | **只取 Kafka 串流 pattern（選配）**；其餘當**反面教材**（32 容器/ClickHouse/4 套排程=過度工程，勿學）。`ARCHITECTURE_REVIEW.md` 有它自己的自省清單 | 後期選配 |
| `course/udemy/Abhishek/終極 DevOps 專案實施` | GitHub Actions CI (`.github/workflows/ci.yaml`)、k8s manifests、ALB ingress、ArgoCD GitOps 流程、OTel/Prometheus/Grafana 觀測性 | P0 |
| `course/udemy/Abhishek/MLOps 從零到英雄` | MLOps 技術棧與決策地圖：`10-cicd-for-models/02-Realtime-MLOps-Project/02-dvc-docker-kserve-argocd.md`（DVC+Docker+KServe+ArgoCD）、serving 四路比較 | P2 |
| `course/udemy/機器學習工程與維運實戰` | **唯一可跑的 ML 工程骨架**：`model/model_training.py`(MLflow Staging→Prod)、`model/model_drift.py` + `jobs/dags/model_drift_dag.py`(Airflow 漂移)、feature pipeline、pytest 分層 | P2(a) |

---

## 已鎖定決策清單（brainstorm 產出，勿再翻案，除非 Fergus 明確改）

- ✅ 架構 = 一個平台、三層疊（DevOps 底座 / DE 資料層 / MLOps ML 層），**不拆散專案**。
- ✅ 主幹 = **YouTube**；PTT 爬蟲 = 第二 ingest 範式（P3）；finmind 金融 = 不當主幹（Kafka 串流可後期選配）。
- ✅ ML = **三條都放**：(a) 傳統 MLflow+KServe tabular、(b) LLMOps/RAG、**(c) 微調（A 分類器＋B LLM LoRA）**。理由：三種情況都 cover，不被認為某技術沒碰過。
- ✅ **留言 ingest（決策 B）**：P1 加抓 YouTube 留言（`commentThreads.list`），百萬列量級**同時**餵三處——正當化 Spark/Iceberg（有真實大表負載）、當 RAG 語料、當微調訓練資料。一份 ingest 打三個目的。
- ✅ **LLM/agent 框架 = LangChain + LangGraph**（取代 CrewAI）；RAG 走 **agentic + CRAG（自我校正）+ hybrid 檢索**；向量庫 **pgvector**（複用 P1 Postgres，不新增常駐服務）。
- ✅ **embedding 本地**（百萬留言不打外部 API）；**生成 LLM 可切換**（本地 Ollama 預設 / Gemini API fallback＋A-B 比較）。
- ✅ **微調框架 = HuggingFace**（可攜、業界標準技能、M4 免費跑小模型 fp16 LoRA）：**A = DistilBERT 留言情緒分類器**（LLM 弱標註一小批→蒸餾成便宜快模型→KServe CPU serving→全量留言打分）、**B = 小 LLM LoRA 標題生成器**（PEFT LoRA，真實爆紅標題當語料，輸入主題→生成爆紅風格標題）。**不用 MLX**（除非日後想在 Mac 練更大模型才當加分；其 fuse 輸出本可攜 HF Hub/GGUF，故不衝突）。
- ✅ **M4 原生算力原則**：kind 跑在 Docker Desktop 的 Linux VM 內、**摸不到 Apple Metal/MPS GPU**→ 重算力（微調、本地 LLM 推論/Ollama、本地 embedding 批次）**原生跑 M4 host**；k8s 負責編排/serving-glue/lakehouse/監控＋CPU-feasible 模型（DistilBERT 分類器）。產出模型（HuggingFace 標準格式）上 MLflow/MinIO、**可攜雲端 GPU 節點**（同一套 code M4 練小模型、雲端練大模型）——本地/原生只是「哪台機器執行」的實作細節，非架構限制。
- ✅ **MCP server（加分 add-on）**：P4/P5 用 FastMCP 把 Gold 趨勢資料開成 MCP 工具（讓 Claude 等 agent 直接查我方資料），差異化亮點。
- ✅ 執行環境 = **本地 k8s**（kind/k3d/minikube，零雲端成本）。
- ✅ 排程只 Airflow / DB 只 Postgres / 監控只 Prom+Grafana / 串流要用才加 Kafka / **砍 ClickHouse**。〔**2026-07-09 翻案**：串流/Redis/ClickHouse 三條見下「GA4 第二真來源 ＋ 三工具翻案」段——各因解決 P1–P5 做不到的獨特工作（線上快取/事件 OLAP/即時事件時間）而正當化；排程仍只 Airflow、OLTP 仍只 Postgres 不變〕
- ✅ 名稱 = `trend-intelligence-platform`（直白描述型）。
- ✅ 交付 = P0–P5 六階段、各一份 spec、疊上去。
- ✅ **呈現/部署拓撲（2026-07-08 定案）**：**monorepo**（前端住 `frontend/` 自成一體子目錄，不拆 repo）；**平台不部署**（本地 kind 按需跑 + 截圖/GIF 佐證）；**前端 Next.js 部署 Vercel**（root dir=`frontend/`），唯一對外公開產物；平台↔前端以**匯出資料檔（CSV/Parquet）為合約邊界**；**不用 Streamlit**（分析＋呈現統一 Next.js）。細節見上「呈現層與部署拓撲」段。

---

## LLM／微調層與留言語料（2026-07-08 定案細節）

### 留言 ingest（P1，決策 B）——一份資料打三個目的
YouTube Data API `commentThreads.list` 抓熱門影片留言（百萬列量級）。這是**把 Spark/Iceberg 用得名正言順**的關鍵：影片 metadata 只有幾千列、根本用不到 Spark；留言大表才是 Spark 分散式清洗、Iceberg 大表管理的真實負載。同一份留言接著：
- **餵 P2b RAG 語料**（真實觀眾聲音，比只有標題/描述更有料的問答基礎）；
- **餵 P2c 微調訓練資料**（A 情緒分類的原料、弱標註對象）。
Bronze 存原始 API JSON、Silver 清洗成留言表（video_id/comment_id/text/like_count/published_at/author_hash…），去識別（作者只留 hash）。

### P2b LLMOps/RAG——LangGraph agentic + CRAG
取代原碼 CrewAI（且原碼已註「暫停用」）。核心進化：**LangGraph 狀態機編排** agentic RAG，走 **CRAG（Corrective RAG）**——檢索後先自評相關性，不足則改寫查詢/重檢索，避免打空庫或答非所問；**hybrid 檢索**（向量 + 關鍵字）。向量庫用 **pgvector**（複用 P1 Postgres，不新增 Qdrant 常駐服務、仍是可展示的向量檢索能力）。**embedding 本地**（百萬留言打外部 API 太貴/慢）；**生成 LLM 可切換**：預設本地 **Ollama**（原生跑 M4，成本零、留言量大適合），**Gemini API** 當 fallback 與 A-B 品質對照。LLMOps 差異化＝原碼完全沒有的工程層：prompt 版本、評估閘（檢索命中/答案品質離線 eval）、token/成本/延遲進 Prometheus、**API key 走 k8s Secret（絕不沿用原碼硬編碼）**。

### P2c 微調——HuggingFace 兩條，效果可見
| | 主題 | 流程 | 亮點 |
|---|---|---|---|
| **A（必做）** | 留言情緒分類器 | LLM 弱標註一小批留言 → 微調 **DistilBERT** → **KServe（CPU-feasible）serving** → 全量留言批次打分 → 儀表板「觀眾情緒」 | **「把貴又慢的 LLM 蒸餾成便宜又快的小模型」＝真實產業 pattern**；最通用的微調技能 |
| **B（做）** | 爆紅標題生成器 | 真實爆紅標題當語料 → **PEFT LoRA（fp16，小 LLM）** 微調 → 輸入主題 → 生成爆紅風格標題 | **「LoRA 微調生成式 LLM」＝最熱技能**；輸入→輸出效果直接可見 |

兩條都用 **HuggingFace**（可攜、標準、M4 免費跑小模型），都接 MLflow 追蹤/Registry、都吃 P1 留言/Gold。**算力原生跑 M4**（見下 M4 原則），產出是標準 HF 模型 → 上 MLflow/MinIO → 可攜雲端 GPU。

### M4 原生算力原則（重要架構誠實）
kind 跑在 Docker Desktop 的 Linux VM 內，**摸不到 Apple Metal/MPS GPU**。因此：
- **重算力原生跑 M4 host**：微調（HuggingFace PEFT on MPS）、本地 LLM 推論（Ollama）、本地 embedding 批次。
- **k8s 負責**：編排（Airflow）、serving-glue（KServe）、lakehouse、監控，＋ **CPU-feasible 模型 serving**（DistilBERT 分類器 CPU 就能跑）。
- **RAG 服務接線**：k8s 內的 RAG 服務生成步要呼叫 host 上的 Ollama（`host.docker.internal` 類接法）或 Gemini API——這條界線 design 要畫清楚。
- **可攜性故事**：HuggingFace 模型（＋若用 MLX，其 fuse 輸出 HF Hub/GGUF）都是標準格式 → 換台機器（雲端 GPU 節點）就能跑 → **本地原生只是「哪台機器執行」的實作細節，非能力限制**。這正是「微調成果能上雲」的價值所在。



---

## GA4 第二真來源 ＋ P6/P7/即時 三垂直 ＋ 三工具翻案（2026-07-09 定案）

> **地位**：本段是「已鎖定決策清單」的**上位增補**。它翻案了原清單的「串流只 Kafka 且只 P3、砍 Redis、不用 ClickHouse」三條——**經 Fergus 逐一以價值判準批准**（架構層翻案照 CLAUDE.md §卡住/要決策時 已回報並拍板）。原清單相關行保留原文並標「見本段翻案」，以留審計軌跡（為何曾禁、為何現在正當）。

### 為什麼擴充：推薦系統需要「真使用者 × 商品 × 互動」三角，YouTube/PTT 只有商品＋聚合

- 推薦的資料三角 = **使用者 × 商品 × 互動**。YouTube/PTT 資料只有**商品（影片/文章）＋聚合指標**；`author_hash` 是隱私雜湊、**無穩定使用者身分、無真互動矩陣**。→ 內容式/item-item 推薦做得了；**協同過濾（CF）這類需要 user×item 互動矩陣的主流推薦做不了**。
- （共留言二部圖 `author_hash × video` 是真實、隱私安全但**極稀疏**的互動訊號，可當補充、不足以撐起一條完整推薦垂直。）
- **誠實路徑**：不假裝有使用者，改引入 **GA4 電商事件資料**（`user_pseudo_id` ＋ `view_item`/`add_to_cart`/`purchase`），帶來真正的 user×item×interaction 三角。這正是 `llm-workshop/ga-insight` 的資料形狀。

### 資料立場（鎖定）：公開 GA4 sample 當 repo 脊椎；area02 真資料當求職憑證、不進本 repo

- **repo 訓練/展示脊椎 = 公開 `bigquery-public-data.ga4_obfuscated_sample_ecommerce`**（Google Merchandise Store：事件級、`user_pseudo_id` 穩定、**可公開分享、招募方認得**）。
- **area02 真實 GA4**（球鞋 marketplace、破億量級）留作 **Fergus 履歷/提案憑證 ＋ web-agency 私有 demo**；**客戶機密不進公開 portfolio repo**（Nike/Jordan 商標與客戶機密不曝光；SA 憑證 local/gitignored/從未 commit）。
- **偷技術不偷資料**：取材 web-agency `services/analytics-api/reference_store/extract_funnel.py`（`:25-57`）的「**全漏斗 item_id 萃取**」——view/cart/purchase 三事件都 UNNEST，不像 ga-insight 只萃 purchase（→ 稀疏 purchase-matrix；view→buy 僅 ~0.39%）——但**跑在公開 sample 上**，area02 資料本身不進 repo。

### 三個新垂直（掛在 P5 之後；序號 P6/P7 ＋ 即時層）

| 階段 | 目錄 | 內容 | 打哪種 JD | 獨立可 demo |
|---|---|---|---|---|
| **P6 推薦系統**（核心） | `ml/reco/` | 全漏斗萃取 → **召回**（CF item2vec / pgvector 語意）→ **LTR 排序** → **線上服務**（Redis 特徵/候選快取 ＋ KServe）→ **LangGraph 生成推薦理由** → **A/B ＋ hit@k/ndcg@k 離線評估** | MLOps / 推薦系統 | ✅ 完整推薦生命週期 |
| **P7 使用者畫像/DMP** | `ml/dmp/` | 真使用者 **RFM/LTV/行為標籤** → **ClickHouse 事件 OLAP** → **人群圈選 DSL** → admin 圈人 | DE / 資料分析 | ✅ 標籤體系 + 圈選 |
| **即時特徵層** | `ingestion/streaming/` | GA4 `events_intraday_*` 近即時匯出 → **Flink 有狀態事件時間特徵** → 餵 P6 線上服務 | DE / 串流 | ✅ 即時特徵 |
| **GA4 ingestion 地基**（P6/P7 共用前置） | `ingestion/ga4/` | 公開 sample → BQ 全漏斗萃取 → 落 Silver/Gold 的 GA4 事件與 item 合約（P6/P7/即時共用） | DE | ✅ GA4 資料契約 |

### 三工具翻案（每個都過 Fergus 價值判準：有獨特能解決的功能才加，非為選而選）

> ADR-lite（每條供 P5 `DECISIONS.md` 收攏）：**加它做什麼 ｜ 解決什麼 P1–P5 做不到的 ｜ 為何不用替代 ｜ 誠實註記**。

| 工具 | 加它做什麼 | 解決什麼（P1–P5 既有工具做不到） | 為何不用替代 | 誠實護欄 |
|---|---|---|---|---|
| **＋Redis** | 線上服務 **<50ms 特徵/候選快取** | 線上特徵存（online feature store）＝KServe/pgvector 都不做這件事 | 每次打 Postgres 取特徵延遲不夠；這是**推薦線上服務最常見的正典架構**，開發本身有價值 | 純線上快取用途，不當第二個 OLTP/排程/佇列 |
| **＋ClickHouse** | GA4 **事件流互動式 OLAP**（切片/漏斗/留存秒回） | 對億級事件做互動式分析＝Postgres 掃事件表會慢；DMP 圈選 DSL 要快 | Postgres 是 OLTP+Gold 聚合，不是欄式 OLAP 引擎 | **非**十億級 bitmap 圈人（我方規模不需 bitmap）——ADR 誠實註記「用的是 ClickHouse 的欄式 OLAP 正典用途，非 Metrica 的 bitmap 規模」 |
| **＋Flink** | **有狀態事件時間即時特徵**（滑窗/session/去重） | 即時特徵計算＝Airflow 批次做不到、Spark 批次也非即時 | GA4 有**真**即時匯出（`events_intraday`）→「考慮即時數據情況」下選 Flink 正當；選 Flink 而非 Spark Structured Streaming 因**低延遲事件時間**語意 | 以**明確標註的事件重放**（labeled event-replay of sample）示範，**不假裝有真線上流量** |

### 對「一個工作一個工具」紀律的關係（不是推翻紀律，是紀律的正確套用）

- 原紀律的真正目的是**拒絕冗餘工具**（finmind 32 容器教訓），**不是拒絕任何新工具**。
- Redis/ClickHouse/Flink 各自解決一個 P1–P5 工具**做不到的獨特工作**（線上快取 / 事件欄式 OLAP / 即時事件時間計算），**不是與既有工具功能重疊的冗餘** → **通過「一工一具」而非違反它**。
- **仍守的邊界**：不因此再開第二個排程器（仍只 Airflow）、第二個 OLTP（仍只 Postgres）、第二個 agent 框架（仍只 LangGraph）、第二個微調框架（仍只 HuggingFace）。翻案**只限這三個各有獨特職務的工具**。

### 拓撲誠實（延續 P4 鐵律，P6/P7 同守）

- 前端仍是 **Vercel 純靜態匯出，打不到本地 k8s** → P6 線上服務/P7 DMP 產出要進前端，仍走「**批次表 → 匯出 DAG → 靜態 JSON**」這條路；Redis/KServe/ClickHouse/Flink 是**叢集內服務**，以**負載測試 ＋ MCP 工具 ＋ 截圖/GIF** 佐證，**不是公開靜態站的 runtime 依賴**。
- Gold 5 表合約（P1 §6a）與 P4 匯出信封（11 表）**只能加欄/加表**（additive-only）；P6/P7 新產出**加新表或加欄**，不改既有粒度。
- **BQ/GA4 是本 repo 第一個 GCP SA 憑證**：姿態 = **SA JSON 進 k8s Secret 掛 volume ＋ `GOOGLE_APPLICATION_CREDENTIALS` 指向掛載路徑**（因它吃檔案路徑、非 env 值），沿用「**命令式 `kubectl create secret`、不進 git**」的既定紀律。取材姊妹專案 `ga4-analytics-platform` 的 dbt-bigquery `profiles.yml`（`method: service-account` + keyfile）＋ `extractor.py` 的 BQ client UPSERT 模式（**唯讀取材**）。

### 前端說明式 UI（跨 P4/P6/P7 新要求）

- **現況真空**：P4 目前**完全沒有「每頁解釋這是什麼/怎麼看」的元件**（只有 3 處技術性 tooltip ＋ footer `FreshnessBanner` 誠實聲明）。新增此要求是**填真空、不撞既有模式**。
- **仿 `llm-workshop/ga-insight` 的三層說明分類法**（讓招募方一眼看懂每個地方在幹嘛）：
  - **(a) `InfoTooltip`**（表單/設定旁 ⓘ）＝**設定值語意**（此滑桿/選單代表什麼）。
  - **(b) `ChartCaption`**（圖表下方常駐小字）＝**圖表視覺語法 / 單行公式**（線粗細、節點編號、流失率＝…）。
  - **(c) `Explainer`**（可摺疊）＝**完整方法論 / 定義表**，且分「**定義類預設展開**（強迫先看懂分類）、**方法論類預設收合**（給想深入者選看）」兩種預設狀態。
- 每個新頁/新圖都帶 **ExplainerSection 精神**（這是什麼／為什麼看／怎麼用）。這是跨 P4/P6/P7 的硬性交付項，Fable 5 brief 每份都要帶。

### 待辦序（2026-07-09）

1. **更新三份文件**（本檔／`CLAUDE.md`／`README.md`）記錄本擴充 ← 進行中。
2. **寫 Fable 5 brief**（照精確度契約 8 條 header）：**GA4 ingestion 地基**（先鎖 GA4 資料契約）→ **P6 推薦 ＋ P7 DMP ＋ 即時 Flink 層**（三份平行，吃地基合約）。兩波派工。
3. **派 Fable 5 出 design**，規劃者逐份把關、對齊跨 spec 接縫（像 Looma crosscut 那樣集中裁定共用擴充點）。

---

## 工作流（誰做什麼）

> 本專案自成一體：**接手的 session 同時扮演規劃者與執行者**（走 superpowers 全流程），不依賴外部特定 session；下列「規劃者」＝你接手後自己戴的帽子。

1. **規劃者**：帶 brainstorm／維護本北極星／交 Fable 5 出 spec／據 spec 寫 implementation plan。**此階段已完成到「P0–P5 六份 design 全出」**，接手者從「寫 plan」起步即可。
2. **Fable 5**（design 模型）：讀階段 brief＋北極星 → 出 `docs/specs/<date>-P<n>-<topic>-design.md`。
3. **執行**：讀 plan 逐 task 實作（TDD、頻繁 commit）。

**下一步**：**P0–P5 六份 design 全數完成**（P0 `7999f0d`／P1 `432fb6a`／P1-留言 `17da698`／P2 `0032afc`／P3 `24132ee`／P4 `934cf54`／P5 `04b5874`，皆達精確度契約 8 條）→ **接手 session 走 `superpowers:writing-plans` 逐份寫 implementation plan**（spec 已完備，P0 必先）→ 同一或另一 session 執行。

**⚠️ 2026-07-09 擴充（規劃中）**：P0–P5 之外**新增 GA4 第二真來源 ＋ P6 推薦／P7 DMP／即時 Flink 三垂直**（見上「GA4 第二真來源 ＋ 三工具翻案」段）。這幾份 **design 尚未產出**——待寫 Fable 5 brief（GA4 地基先、P6/P7/即時後）→ 派 Fable 5 出 design → 才輪到寫 plan。故「規劃階段收束」**只對 P0–P5 成立**；P6/P7/即時的 spec 產線是**新開的一輪**。
