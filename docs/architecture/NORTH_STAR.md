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
   - 串流**要用才加 Kafka**（P1 可先不用，資料量/即時性撐得起故事再加）。
3. **一個資料主幹（YouTube）餵所有層**。同一份資料同時餵 DE lakehouse、tabular 模型、LLM/RAG——這樣才不會長成兩個 domain。
4. **層與層邊界乾淨**：每層有明確輸入/輸出介面，可獨立理解、獨立 demo。
5. **分階段交付**：P0→P4 每階段獨立可展示、各一份 spec，疊上去。

---

## 為什麼主幹是 YouTube（而非 PTT / 金融）

因為要同時放 **tabular 模型**和 **LLM/RAG** 兩條 ML 線，資料必須「同時有數字、也有文字」：

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
| Lakehouse | **MinIO/S3 + Apache Iceberg**, **Spark**（Bronze→Silver）, **dbt**（Silver→Gold, DQ 測試） | P1 |
| 儲存 | **PostgreSQL**（Gold） | P1 |
| 串流（選配） | Kafka（要用才加） | P1/後期 |
| ML 生命週期（tabular） | **DVC**（資料版本）→ **MLflow**（追蹤+Registry, Staging→Prod）→ **KServe**（k8s serving）→ Airflow 重訓 + drift 監控 | P2 |
| ML 生命週期（LLMOps） | 向量庫（Qdrant/pgvector）+ RAG pipeline + prompt/版本管理 + 評估閘 + 成本/延遲監控 | P2 |
| 呈現層（對外） | **Next.js**（讀匯出資料、部署 **Vercel**）；平台端 Gold→CSV/Parquet 匯出 DAG | P4 |
| 收尾加分 | 安全掃描（Trivy/SonarQube，課程缺口）, 架構圖, 面試敘事 | P5 |

**刻意省略以避免過度工程**：Kubeflow、Feast、Seldon、Terraform、service mesh、多雲、ClickHouse、多套排程器。

---

## 分階段藍圖（P0–P5，每階段一份 spec）

| 階段 | 目錄 | 內容 | 打哪種 JD | 獨立可 demo |
|---|---|---|---|---|
| **P0 平台底座** | `platform/` | 本地 k8s 叢集 + namespace 佈局 + **ArgoCD GitOps** + **GitHub Actions CI** 骨架 + **Prometheus/Grafana**。驗收：一個 hello service 用 GitOps 上線、有儀表板 | DevOps/平台 | ✅ |
| **P1 資料管線** | `ingestion/` `lakehouse/` `orchestration/` | YouTube API ingest → MinIO/Iceberg Bronze → Spark Silver → dbt Gold(Postgres) → Airflow 編排 + dbt DQ 測試 | 資料工程師 | ✅ 完整 lakehouse |
| **P2 兩條 ML 垂直** | `ml/` | **(a) tabular**：DVC→MLflow→KServe→drift/重訓（影片表現預測，取材 youtube-analytics 的 RandomForest）。**(b) LLMOps**：RAG over YouTube 文字 + prompt 版本 + 評估 + 成本監控（取材 youtube-analytics 的 Qdrant/RAG） | MLOps / LLMOps | ✅ 完整模型生命週期 |
| **P3 進階 ingest** | `ingestion/` | PTT 分散式爬蟲當第二來源（取材 ptt-crawler 的 Celery 可靠性），可選加 Kafka 串流 | 差異化（爬蟲硬實力） | ✅ |
| **P4 呈現層** | `frontend/` + `orchestration/`（匯出 DAG） | Next.js 儀表板讀「Gold/ML 匯出資料」→ **部署 Vercel**（唯一對外可見產物）；平台端加 Gold→匯出（CSV/Parquet）步。**平台本身不部署**（本地 kind 按需跑） | 前端/全端 + 展示整體 | ✅ 公開網址 |
| **P5 收尾** | 全域 | CI 補安全掃描、架構圖、README 打磨、面試敘事 | 全部 | — |

**建置順序**：P0 必須先做（其他都跑在它上面）。P1 → P2 → P3 依序；P4 呈現層吃 P1 Gold + P2 ML 匯出（可在 P2 後做）；P5 收尾最後。P2 的 (a)(b) 兩條可並行或分兩份 sub-spec。

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
- ✅ ML = **兩條都放**：(a) 傳統 MLflow+KServe tabular、(b) LLMOps/RAG。理由：兩種情況都 cover，不被認為某技術沒碰過。
- ✅ 執行環境 = **本地 k8s**（kind/k3d/minikube，零雲端成本）。
- ✅ 排程只 Airflow / DB 只 Postgres / 監控只 Prom+Grafana / 串流要用才加 Kafka / **砍 ClickHouse**。
- ✅ 名稱 = `trend-intelligence-platform`（直白描述型）。
- ✅ 交付 = P0–P5 六階段、各一份 spec、疊上去。
- ✅ **呈現/部署拓撲（2026-07-08 定案）**：**monorepo**（前端住 `frontend/` 自成一體子目錄，不拆 repo）；**平台不部署**（本地 kind 按需跑 + 截圖/GIF 佐證）；**前端 Next.js 部署 Vercel**（root dir=`frontend/`），唯一對外公開產物；平台↔前端以**匯出資料檔（CSV/Parquet）為合約邊界**；**不用 Streamlit**（分析＋呈現統一 Next.js）。細節見上「呈現層與部署拓撲」段。

---

## 工作流（誰做什麼）

1. **Opus（規劃）** 帶 brainstorm、寫本北極星、逐階段交 Fable 5 出 spec、再據 spec 寫 implementation plan。
2. **Fable 5** 讀階段 brief/北極星 → 出 `docs/specs/<date>-P<n>-<topic>-design.md`。
3. **執行 session** 讀 plan 逐 task 實作（TDD、頻繁 commit）。

**下一步**：P2（兩條 ML 垂直）出 spec（P0/P1 design 已完成；P4 呈現層拓撲已定案，待 P2 後接）。
