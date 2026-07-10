# trend-intelligence-platform

> 端到端「趨勢智能」資料平台 — **DE + MLOps/LLMOps + DevOps** on Kubernetes

以 YouTube 熱門趨勢為主幹（PTT 論壇為第二來源），把原始資料從 **ingest → Lakehouse → 建模 → 上線監控**打通一條龍，全程跑在 **Kubernetes**、以 **GitOps** 部署、具備完整可觀測性。一個平台同時展示資料工程、模型維運、平台工程三種能力。

> 狀態：📐 **全專案 spec-only、實作待啟動**（`docs/plans/` 仍空、程式目錄僅 scaffold）。截至 **2026-07-10**，所有設計 spec 皆已完成並通過內建「精確度契約 8 條」：核心平台 **P0–P5**、電商擴充 **P6 推薦／P7 DMP／即時 Flink**（＋GA4 第二真來源）、**統一資料作品集四支柱**（Signal 設計系統／GA／搜尋／問 AI）、以及**進階增補**（P6 進階召回、P7 模型化標籤、觀測性強化、AI 維運事件敘事者）。**下一動作＝接手 session 走 `superpowers:writing-plans`，從 P0 起逐份寫 implementation plan**。架構正本見 [`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)；接手指南、完整 design 清單與寫 plan 硬序見 [`CLAUDE.md`](CLAUDE.md)。

---

## 架構總覽

```
[GitHub Actions]  build → test → lint → docker push → 改 k8s manifest tag
       │ git push
[ArgoCD GitOps]  監看 manifest → 自動 sync 到叢集
       ▼
┌─ Kubernetes（本地 kind）──────────────────────────────────────┐
│                                                               │
│  ── 資料層（DE）──────────────────────────────────────────    │
│   YouTube API（影片 metadata ＋ 留言語料，百萬列）─┐            │
│   PTT 爬蟲 ─→ Kafka(KRaft) ─→ consumer ───────────┴→ Bronze   │
│                MinIO/Iceberg(Bronze 原文) → Spark(Silver)      │
│                → dbt(Gold → PostgreSQL + pgvector)             │
│                Airflow 編排全鏈 + dbt 資料品質測試               │
│                                                               │
│  ── ML 層（MLOps / LLMOps）─────────────────────────────      │
│   (a) tabular：DVC → MLflow → KServe → drift/重訓（時序預測）   │
│   (b) RAG：LangGraph agentic + CRAG（pgvector · 本地 embedding │
│            · Ollama 預設/Gemini fallback）+ prompt 版本 + 評估  │
│   (c) 微調：HuggingFace — DistilBERT 情緒分類器 + 小 LLM LoRA   │
│                                                               │
│  ── 可觀測性 ────────────────────────────────────────────     │
│   Prometheus + Grafana（服務指標 + 模型 drift/成本 儀表板）     │
└───────────────────────────────────────────────────────────────┘
       │ 平台端 Airflow 匯出 DAG：Gold + ML 輸出 → 靜態 JSON（合約邊界；P4 定案）
       ▼
[Next.js on Vercel]  讀匯出資料渲染儀表板（唯一對外公開產物）＋ MCP server（Gold 開成 agent 工具）
```

> **重算力原生跑 M4 host**：kind 跑在 Docker Desktop 的 Linux VM 內、摸不到 Apple GPU，故微調 / 本地 LLM 推論（Ollama）/ 本地 embedding 批次原生跑 Mac；k8s 負責編排、lakehouse、監控與 CPU serving（分類器）。產出模型為 HuggingFace 標準格式，**可攜雲端 GPU**（同套 code 換機器練大模型）。
> **拓撲**：平台本身不部署（本地 kind 按需跑 + 截圖/GIF 佐證）；唯一對外部署物是前端（Vercel），平台↔前端以匯出資料檔為合約。

## 技術棧

| 分層 | 工具 |
|---|---|
| 容器 / 編排 | Docker · **Kubernetes**（本地 kind） |
| CI/CD / GitOps | **GitHub Actions** · **ArgoCD** |
| 資料管線編排 | **Apache Airflow** |
| Lakehouse | **MinIO/S3 + Apache Iceberg** · **Spark** · **dbt** |
| 串流 | **Kafka**（KRaft 單 broker，P3 佇列驅動爬蟲；唯一 messaging） |
| 儲存 | **PostgreSQL**（Gold）· **pgvector**（向量庫，同一顆 Postgres） |
| ML 生命週期（tabular） | **DVC** · **MLflow** · **KServe**（RawDeployment） |
| LLMOps / RAG | **LangChain + LangGraph**（agentic + CRAG）· 本地 embedding · **Ollama**/Gemini 可切 · prompt 版本 / 評估閘 / 成本監控 |
| 微調 | **HuggingFace**（transformers · PEFT LoRA）— 算力原生跑 M4，產出可攜雲端 |
| 推薦系統（P6，規劃中） | 召回（CF item2vec / pgvector 語意）· LTR 排序 · **Redis**（線上特徵/候選快取）· KServe 線上服務 · LangGraph 生成推薦理由 · A/B + hit@k/ndcg@k |
| 使用者畫像/DMP（P7，規劃中） | RFM/LTV/行為標籤 · **ClickHouse**（事件流欄式 OLAP）· 人群圈選 DSL |
| 即時特徵（規劃中） | **Flink**（GA4 `events_intraday` 有狀態事件時間特徵；以標註事件重放示範） |
| 真使用者資料源（規劃中） | 公開 **`ga4_obfuscated_sample_ecommerce`**（GA4 電商事件；帶入 user×item×interaction 三角） |
| 呈現層 | **Next.js**（部署 **Vercel**，讀匯出資料）· **MCP server**（FastMCP，加分）· **說明式 UI**（仿 ga-insight：InfoTooltip/ChartCaption/Explainer） |
| 可觀測性 | **Prometheus + Grafana** |

## 分階段藍圖

| 階段 | 內容 | 展示能力 | Spec |
|---|---|---|---|
| **P0** 平台底座 | k8s + ArgoCD GitOps + GitHub Actions CI + Prometheus/Grafana | DevOps / 平台 | ✅ design |
| **P1** 資料管線 | YouTube ingest（metadata＋留言）→ Lakehouse(Iceberg/Spark/dbt) → Postgres，Airflow 編排 | 資料工程 | ✅ design（＋留言增補 design） |
| **P2** ML 垂直 ×3 | (a) tabular 時序預測；(b) LangGraph/CRAG RAG；(c) HuggingFace 微調（分類器＋LLM LoRA） | MLOps / LLMOps | ✅ design |
| **P3** 進階 ingest | PTT 分散式容錯爬蟲第二來源，Kafka 佇列範式（跟 P1 批次刻意不同） | 爬蟲 / 串流硬實力 | ✅ design |
| **P4** 呈現層 | Next.js 儀表板讀匯出資料 → 部署 Vercel；平台端匯出 DAG；＋ MCP server | 前端/全端 + 整體展示 | ✅ design |
| **P5** 收尾 | 安全掃描（Trivy+gitleaks+CodeQL）、架構圖（Mermaid）、三 JD 面試敘事 | 整體打磨 | ✅ design |
| **P6** 推薦系統 | GA4 全漏斗 → 召回(CF/語意) → LTR 排序 → Redis 快取 + KServe 線上服務 → LangGraph 推薦理由 → A/B + 離線評估 | MLOps / 推薦系統 | ✅ design |
| **P7** 使用者畫像/DMP | 真使用者 RFM/LTV/行為標籤 → ClickHouse 事件 OLAP → 人群圈選 DSL → admin | DE / 資料分析 | ✅ design |
| **即時特徵層** | GA4 `events_intraday` → Flink 有狀態事件時間特徵 → 餵 P6 線上服務 | DE / 串流 | ✅ design |

> 上列 P6/P7/即時（2026-07-09 擴充）由「推薦需真使用者×商品×互動三角，YouTube/PTT 無真使用者」推動，引入公開 GA4 sample 為第二真來源（area02 真資料只當求職憑證、不進本 repo），並翻案加入 Redis/ClickHouse/Flink 三工具（各有獨特職務）。論證正本見 [`NORTH_STAR.md`](docs/architecture/NORTH_STAR.md) 對應段。

### 2026-07-10 擴充 spec（皆 ✅ design）

| 群組 | 內容 | Spec |
|---|---|---|
| **統一資料作品集四支柱** | 前端升為一站四支柱主題切換（趨勢/GA/搜尋/平台），取代 ga-insight、納入 ptt-search：`unified-portfolio-crosscut`（主契約）＋`frontend-design-system`（Signal 設計系統，pillar-agnostic 地基）＋`ga-pillar`（漏斗為核心）＋`search-pillar-v2`（自建 hybrid 中文檢索；v1 SUPERSEDED）＋`ask-ai`（agentic 問答，複用 P2b LangGraph） | ✅ design |
| **進階推薦/畫像增補** | `p6-advanced-recall`（序列 SASRec＋P5/T5 生成式，反幻覺三層，additive 接 RRF+LTR）＋`p7-model-based-tags`（K-Means 消費分群 additive 疊加規則式 value_tier，DB 表登錄不掛 MLflow） | ✅ design |
| **平台硬化** | `observability-hardening`（三柱補齊 OTel+Tempo/Loki+Alloy/手寫 burn-rate SLO×4＋P1 自癒）＋`ai-ops-incident-narrator`（告警觸發 AI SRE，反幻覺為主體，LangGraph+P2b LLMClient，棄 Dify/DeepSeek） | ✅ design |

> 論證正本見 [`NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)「統一資料作品集重定位」與「觀測性三柱翻案」兩段。

## 目錄結構

```
platform/        # P0：k8s manifests、ArgoCD、CI、監控（DevOps 底座）
ingestion/       # P1/P3：YouTube API（影片+留言）+ PTT 爬蟲
lakehouse/       # P1：Spark jobs、dbt 專案、儲存
orchestration/   # P1：Airflow DAGs
ml/              # P2：tabular（MLflow/KServe）+ RAG（LangGraph）+ 微調（HuggingFace）
frontend/        # P4：Next.js 儀表板（自成一體子目錄，部署 Vercel）
docs/
  architecture/  # 北極星架構正本
  specs/         # 各階段設計 spec
  plans/         # 實作計畫
```
> 目錄為指示性佈局；每階段的 spec 會敲定該層的最終結構（`frontend/` 待 P4）。

## 本地啟動（P0 spec 已定案，實作待啟動）

目標：`kind create cluster` → ArgoCD app-of-apps 指向本 repo → 各服務自動 sync。具體步驟見 P0 design（`docs/specs/2026-07-08-P0-platform-foundation-design.md`）；實作 plan 落地後補上一鍵指令。

## 靈感來源

本平台把多個個人資料工程練習專案（yt-trending / ga4-analytics / ptt-crawler / youtube-analytics / finmind）中最強的部分，收斂成一個連貫、乾淨、可展示的統一平台，並補齊業界標準的 MLOps/LLMOps/GitOps 缺口。取材**進化非複刻**：各 design 誠實記錄「取什麼邏輯 vs 重造哪個工程層」，並修掉原碼的真實缺陷（無評估→真評估、無持久化→Registry、空索引→真 ingest、CrewAI→LangGraph、靜態回歸→時序題）。
