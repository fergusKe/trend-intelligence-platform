# CLAUDE.md — trend-intelligence-platform 接手指南

> 你（Claude）被指派接手這個專案。**開工前必讀正本：[`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)**——專案定位、鎖定決策、分階段藍圖、可複用素材地圖全在那裡。本檔只放「怎麼接手、怎麼跑」的薄索引。

## 這是什麼

**求職 portfolio 專案**：一個端到端「趨勢智能」資料平台，展示 **DE（資料工程）＋ MLOps/LLMOps ＋ DevOps（k8s + GitOps）** 三種能力。主幹 = YouTube 趨勢；跑在**本地 Kubernetes**。

⚠️ **關鍵心態**：這是 portfolio，**「用 k8s、跑常駐服務」是目的本身，不是成本浪費**。不要套用「serverless 比較省、避免常駐叢集」那套邏輯來砍架構——這裡就是要展示能操作 server-based / k8s / MLOps 全套。但也**不要過度工程**（見 NORTH_STAR 的「一個工作一個工具」紀律；反面教材是 finmind 的 32 容器）。

## 開場 60 秒（接手先做這個）

1. 讀 [`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)（架構正本 + 已鎖定決策 + 素材地圖）。
2. 看 `docs/specs/` 有哪些階段 spec 已出、`docs/plans/` 有哪些 plan 已寫、`git log` 看做到哪。
3. 確認你要做的階段（P0→P5 依序，P0 平台底座必須先做）。

## 工作流（誰做什麼）— 走 superpowers skills

本專案沿用 **superpowers** 這套工作流（它是本機全域 plugin，任何 session 直接 invoke，無需 vendoring）。**不要**複製其他專案的重裝治理層（CORE_RULES / 雙 harness 同步 / memory 系統）——本專案是單人 portfolio，`NORTH_STAR.md` + 本檔 + `docs/{specs,plans}` 就夠。

```
規劃：superpowers:brainstorming → 出設計 → docs/specs/<date>-P<n>-<topic>-design.md
實作：superpowers:writing-plans → 出 docs/plans/<date>-P<n>-<topic>-implementation.md
執行：superpowers:subagent-driven-development（每 task 一個 subagent + 兩階段 review）
      或 superpowers:executing-plans（inline 批次執行 + checkpoint）
```
- 每個 P0–P5 階段各跑一輪這個循環，產出獨立可驗收的小 task（TDD、頻繁 commit）。
- **spec**：`docs/specs/YYYY-MM-DD-P<n>-<topic>-design.md`
- **plan**：`docs/plans/YYYY-MM-DD-P<n>-<topic>-implementation.md`
- 查快速演進套件（k8s/ArgoCD/Airflow/MLflow/KServe/dbt/Iceberg）用 context7 先查最新官方文件再寫。

### Fable 5 design 精確度契約（每份 design 必達；派 Fable 5 前把本段連結進 brief header）

> 目的：**design 要明確到寫 implementation plan 的人零誤解、未來規劃不漂**。派 Fable 5 出 design 時，dispatch prompt 與 brief header 都要求它滿足以下 8 條；產出後**規劃者（你）逐條驗收**才據以寫 plan。（P0–P5 六份 design 已全數通過此契約；本段供日後若有新增/修改 design 時沿用。）

1. **開放問題收斂成單一決定**——禁止 TBD／延後／「由 plan 定」／兩案並陳。真的非實查不能定，才標「plan 前需實查 X」並給**預設傾向**與判準。
2. **技術選型具體到版本 + context7 查證**——快速演進套件（k8s/ArgoCD/Airflow/MLflow/KServe/dbt/Iceberg/LangGraph/HuggingFace/PEFT/Ollama/pgvector/Kafka/Strimzi…）不得憑記憶，design 標明查證過的版本與用法。
3. **資料契約欄位級**——schema 列欄名/型別/鍵/分區；跨階段介面（Gold 5 表、`silver_youtube_comments` 等）標「穩定合約」。
4. **部署形狀具體**——manifest/CRD/DAG/InferenceService 形狀、ArgoCD sync-wave 位置、kustomize 佈局、檔案路徑都寫出來。
5. **沿用既有慣例不重造**——明講對齊哪一份既有 design 的哪個模式（Bronze key、Silver loader、secret 姿態…）。
6. **進化非複刻**——取材既有專案原始碼時，標清「取什麼邏輯 vs 重造哪個工程層」的界線。
7. **硬約束貫徹**——一個工作一個工具、M4 原生算力界線、拓撲（平台不部署／前端 Vercel／匯出檔為合約）、secret 走 k8s Secret 不硬編碼、非互動不向使用者提問。
8. **每步可測**——端到端驗收清單可實跑（有測試/smoke/DQ），不是敘述性「應該會動」。

## 目前狀態（2026-07-17 更新——此段是本專案的活狀態正本，接手先讀這段 ＋ NORTH_STAR）

🚀 **P0 已實作完成並部署**：plan `docs/plans/2026-07-16-P0-platform-foundation-implementation.md` 全 13 task 執行完、最終全分支 review READY、已合回 main；kind 叢集跑在 **M4 runtime**（開發在 M1、SSH 過去，見 errata §F）；hello-ci 全迴路通（GHCR image + bump commit）。下一動作＝寫 P1 plan。

⚠️ **寫任何 plan 前必讀 [`docs/specs/2026-07-17-design-errata.md`](docs/specs/2026-07-17-design-errata.md)**——design 三路審查的勘誤補丁層（Fergus 拍板取捨、資源治理契約、pin 再驗證前置 task、P0 實跑教訓/M4 環境事實）；與 design 本文衝突時以 errata 為準。

📐 其餘階段仍 spec-only。全部 design 皆已達「Fable 5 精確度契約 8 條」；每份 design 尾段有 plan-前實查點清單（皆帶預設傾向）。

### 已完成 design 全清單（依批次；檔在 `docs/specs/`）

**① 核心平台 P0–P5**（2026-07-08，6 份）——細節見本節末各階段條列。這是骨幹，P0 必先實作。

**② 電商擴充 P6/P7**（2026-07-09，4 份 design ＋ 1 跨切）：`P6-ga4-ingestion-foundation`（引入公開 `ga4_obfuscated_sample_ecommerce` 為第二真來源，建 user×item×interaction 三角；area02 真資料只當求職憑證、**不進本 repo**）、`P6-recommendation`（召回 item2vec/pgvector→RRF→LightGBM LTR→KServe+Redis→LangGraph 生成推薦理由→A/B）、`P6-realtime-features`（Flink 有狀態事件時間即時特徵）、`P7-dmp`（RFM/行為標籤/ClickHouse 事件 OLAP/圈選 DSL）；跨切 `ga4-extension-crosscut`。三工具翻案（＋Redis/＋ClickHouse/＋Flink）論證正本在 NORTH_STAR「GA4 第二真來源 ＋ 三工具翻案」段。

**③ 統一資料作品集四支柱**（2026-07-10）：`unified-portfolio-crosscut`（主契約：前端升為一站四支柱主題切換，取代 ga-insight、納入 ptt-search）、`frontend-design-system`（Signal 設計系統，Tailwind v4 `@theme`＋shadcn，pillar-agnostic 地基）、`ga-pillar`（GA 分析支柱，銷售漏斗為核心、比 ga-insight 更完整）、`search-pillar-v2`（平台側自建進階中文檢索 hybrid BM25+向量 RRF+cross-encoder rerank；**v1 已 SUPERSEDED**）、`ask-ai`（問 AI agentic 分析問答，複用 P2b LangGraph 擴 Send fan-out＋雙 guardrail＋reflection）。論證正本在 NORTH_STAR「統一資料作品集重定位」段。

**④ 進階增補**（2026-07-10）：`p6-advanced-recall`（序列 SASRec baseline＋P5/T5 生成式主秀，反幻覺三層＋一 item 一 special token，additive 接進現有 RRF+LTR）、`p7-model-based-tags`（K-Means 消費分群 additive 疊加、不取代規則式 value_tier，DB 表登錄不掛 MLflow）、`observability-hardening`（三柱補齊 OTel+Tempo／Loki+Alloy／手寫 burn-rate SLO×4 ＋ P1 留言管線自癒；論證正本在 NORTH_STAR「觀測性三柱翻案」段）、`ai-ops-incident-narrator`（Alertmanager 告警觸發 AI SRE，反幻覺為主體、數字/時間戳程式取自 PromQL/Loki，棄 Dify/DeepSeek 走 LangGraph+P2b LLMClient）。

### 寫 plan 的硬序（接手 session 照此序寫 implementation plan）

1. **P0 平台底座必先**（k8s+ArgoCD+CI+監控，其他全跑在它上面）。
2. **P1**（＋留言 ingest 增補）→ **P2/P3** 吃 P1 產物（Gold 5 表 ＋ `silver_youtube_comments` 合約）。
3. **P2b（RAG/LLMOps 基建）→ 問 AI 支柱 → AI 維運敘事者**：後兩者都複用 P2b LangGraph 基建；aiops plan 另需**觀測性強化 plan 先行**。
4. **P4 呈現層**吃 P1+P2+P3 匯出合約；**四支柱前端**（`frontend-design-system` Signal 為地基先行 → GA/搜尋/問 AI 三支柱）疊在 P4 之上。
5. **P5 收尾**（安全掃描/架構圖/JD 敘事）在 P0–P4 實作後。
6. **P6 推薦 → P6 進階召回**；**P7 DMP → P7 模型化標籤**（進階兩者互不依賴、可平行）。
7. **觀測性強化 plan 先於 aiops plan**。

### 跨 plan 協調點（別讓兩 plan 各解一次）

- **`alertmanagerConfigMatcherStrategy: {type: None}`**：觀測性強化的 Discord AlertmanagerConfig CRD 與 aiops 的 webhook CRD **共用同一縫**（operator 預設 `OnNamespace` 會讓第二個 receiver 收不到告警）→ 兩 plan 必須收斂為同一解。
- **P6 進階召回**擴 `ml.reco_candidates` 的 `source` CHECK 列舉 ＋ RECO_FEATURE_SCHEMA v1→v2（尾端加 3 欄、皆 additive）→ 與 P6 推薦 plan 的 schema 版本要對齊。
- **P7 模型化標籤**用投影法（`ALTER`+`UPDATE` `gold.dmp_user_profiles`，規則層 dbt 檔零編輯）→ 不與 P7 DMP plan 的 dbt 模型衝突。

**六份核心 P0–P5 design 細節**（沿用前記錄、內容未變，供接手直接照抄驗收）：
- **P0 平台底座**（`...-P0-platform-foundation-design.md`）：kind + ArgoCD app-of-apps + GitHub Actions/GHCR + kube-prometheus-stack。**收緊 pass `7999f0d`**（修 Grafana 隨機密碼行為、CI actions 版本、Dockerfile/驗收補到可照抄；錨點與 sync-wave 0/1/2 零變動）。
- **P1 資料管線**（`...-P1-data-pipeline-design.md`）：Airflow KubernetesExecutor + spark-operator + MinIO/Iceberg JDBC catalog；**§6a Gold marts 5 表合約**（`gold_trending_daily`/`gold_channel_performance`/`gold_category_daily`/`gold_video_velocity_hourly`/`gold_video_lifecycle`，additive-only，是 P2 介面）。**收緊 pass `432fb6a`**（修 §6 freshness `loaded_at_field` 對不存在欄的矛盾、補 k8s DNS/env 注入/角色 GRANT+`ALTER DEFAULT PRIVILEGES` 合約；§6a/§3/§5/§8 錨點一字未動）。
- **P1 留言 ingest 增補**（`...-P1-comments-ingest-design.md`，`17da698`）：additive 加抓 YouTube 留言（決策 B）；quota 4000u 累積型（8–14 天湊百萬列）、Bronze 邊界遮蔽去識別、Silver `silver_youtube_comments`（13 欄，MERGE by comment_id）是 P2b/P2c 上游合約。不動既有 5 表。
- **P2 三條 ML 垂直**（`...-P2-ml-verticals-design.md`，`0032afc`，504 行）：(a) 時序預測 label=`doubled_in_24h`、τ=t0+3h 防洩漏、drift PSI+KS+rolling AUC；(b) LangGraph CRAG（e5-small 本地 embedding·pgvector HNSW·Ollama qwen3:8b/Gemini fallback·k8s→host ExternalName）；(c) 微調 A=distilbert-multilingual 3類 macro-F1≥0.70、B=Qwen3-1.7B LoRA fp16→GGUF→Ollama。對 P4=五表匯出合約，線上端點排除（Vercel 打不到本地 k8s）。
- **P3 PTT Kafka ingest**（`...-P3-ptt-ingest-design.md`，`24132ee`）：Strimzi 單 broker KRaft、手動 commit at-least-once、Bronze 信封決定性 key、Silver 右尺寸用 Python（非 Spark）、一張 `gold_ptt_board_daily`。
- **P4 呈現層**（`...-P4-presentation-layer-design.md`，`934cf54`）：匯出 DAG `export_frontend_data`→MinIO→host `make export-sync`→人審 commit 進 `frontend/public/data/`（**committed 靜態 minified JSON**，否決 Neon/物件儲存，k8s 不持 GitHub 權杖）；前端 **Next.js 16.2 App Router `output:'export'` 純靜態**（拓撲鐵律編譯期強制）+ Recharts，8 頁；MCP = **FastMCP 3.2 部署 Prefect Horizon（上雲，可被遠端 Claude 查）**，10 工具讀公開 `/data/*.json`，不可用則降級本地 demo 零改碼；Vercel root dir=`frontend/` 零 env。ML 表缺席 `status:"absent"` 容忍（P1 完成即可先上線）。
- **P5 收尾**（`...-P5-polish-hardening-design.md`，`04b5874`）：CI 安全掃描 **Trivy+gitleaks+CodeQL**（**image gate 卡 GitOps 交棒點**=CRITICAL-with-fix 沒清就不 bump manifest）；架構圖 **Mermaid 4 張**；面試敘事 **三份 JD one-pager + `DECISIONS.md`（ADR-lite 16 條）**。§1 專表畫清「現可定 vs 執行期對真 artifact 做（掃真 image/截 8 圖+1 GIF）」界線，初版禁量化成果。

**下一步**：見上方「寫 plan 的硬序」——接手 session 走 `superpowers:writing-plans`，從 P0 起逐份寫 implementation plan（spec 已完備）→ 同一或另一 session 執行。各 design 尾段有 plan-前實查點清單（皆帶預設傾向）。

**關鍵鎖定決策**（正本在 NORTH_STAR「已鎖定決策清單」+「LLM／微調層與留言語料」+「GA4 第二真來源 ＋ 三工具翻案」+ M4 原生算力原則）：Kafka（P3 佇列）· **＋Redis/ClickHouse/Flink（2026-07-09 翻案，各有獨特職務，見上）** · agent 框架 LangGraph（砍 CrewAI）· 向量庫 pgvector · embedding 本地 · 生成 Ollama/Gemini 可切 · 微調 HuggingFace（砍 MLX）· **重算力原生跑 M4 host**（kind 摸不到 Apple GPU）產出可攜雲端 · 呈現層 Next.js/Vercel（平台不部署，匯出 JSON 為合約，前端打不到本地 k8s）· MCP server 為 P4/P5 加分 · **前端說明式 UI**（仿 ga-insight 三層：InfoTooltip/ChartCaption/Explainer，跨 P4/P6/P7 硬性）。

## 目錄

```
platform/ ingestion/ lakehouse/ orchestration/ ml/   # 五層（對應 P0–P3，見 NORTH_STAR）
docs/architecture/  docs/specs/  docs/plans/
```
目錄為指示性佈局；每階段 spec 敲定該層最終結構。

## 慣例

- **Git commit 中文**：`動作(範圍)：說明`（例：`建置(platform)：kind 叢集 + ArgoCD bootstrap`）。
- **TDD**：先寫失敗測試 → 實作 → 綠。頻繁小 commit。
- **一個工作一個工具**（不亂的紀律，違反 = 走回 finmind 老路）：排程只 Airflow、DB 只 Postgres（向量庫用 pgvector 同顆）、監控只 Prometheus/Grafana、agent 框架只 LangGraph（砍 CrewAI）、微調只 HuggingFace（砍 MLX）。
  - **⚠️ 2026-07-09 翻案（Fergus 批准）**：原「串流只 Kafka 且只 P3、砍 Redis、不用 ClickHouse」三條，因 GA4 第二真來源帶入 P6 推薦/P7 DMP/即時三垂直而翻案——**＋Redis**（線上服務 <50ms 特徵/候選快取）、**＋ClickHouse**（GA4 事件流欄式 OLAP）、**＋Flink**（有狀態事件時間即時特徵）各解決一個 P1–P5 做不到的獨特工作，屬「一工一具」的正確套用（拒冗餘，非拒新工具），**非**違反紀律。正本論證見 NORTH_STAR「GA4 第二真來源 ＋ 三工具翻案」段。仍守：排程只 Airflow、OLTP 只 Postgres、agent 只 LangGraph、微調只 HuggingFace 不變。
- **取材既有專案唯讀不改**：可複用素材在 NORTH_STAR「可複用素材地圖」，全在 `/Users/fergus/Desktop/workshop/fergus/` 底下（yt-trending / ga4-analytics / youtube-analytics / ptt-crawler / finmind + 三門課）。**唯讀取材，不改原專案**。
- **快速演進套件先查最新官方文件再寫**（k8s / ArgoCD / Airflow / MLflow / KServe / dbt / Iceberg 升級或新接時）。

## 卡住 / 要決策時

架構層級的翻案或重大取捨 → 回報 Fergus 確認，不自行改動已鎖定決策（見 NORTH_STAR「已鎖定決策清單」）。一般階段內的設計問題，接手 session 自行照精確度契約收斂即可。
