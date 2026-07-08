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

> 目的：**design 要明確到寫 implementation plan 的人零誤解、未來規劃不漂**。派 Fable 5 出 design 時，dispatch prompt 與 brief header 都要求它滿足以下 8 條；產出後 Opus 逐條驗收才據以寫 plan。

1. **開放問題收斂成單一決定**——禁止 TBD／延後／「由 plan 定」／兩案並陳。真的非實查不能定，才標「plan 前需實查 X」並給**預設傾向**與判準。
2. **技術選型具體到版本 + context7 查證**——快速演進套件（k8s/ArgoCD/Airflow/MLflow/KServe/dbt/Iceberg/LangGraph/HuggingFace/PEFT/Ollama/pgvector/Kafka/Strimzi…）不得憑記憶，design 標明查證過的版本與用法。
3. **資料契約欄位級**——schema 列欄名/型別/鍵/分區；跨階段介面（Gold 5 表、`silver_youtube_comments` 等）標「穩定合約」。
4. **部署形狀具體**——manifest/CRD/DAG/InferenceService 形狀、ArgoCD sync-wave 位置、kustomize 佈局、檔案路徑都寫出來。
5. **沿用既有慣例不重造**——明講對齊哪一份既有 design 的哪個模式（Bronze key、Silver loader、secret 姿態…）。
6. **進化非複刻**——取材既有專案原始碼時，標清「取什麼邏輯 vs 重造哪個工程層」的界線。
7. **硬約束貫徹**——一個工作一個工具、M4 原生算力界線、拓撲（平台不部署／前端 Vercel／匯出檔為合約）、secret 走 k8s Secret 不硬編碼、非互動不向使用者提問。
8. **每步可測**——端到端驗收清單可實跑（有測試/smoke/DQ），不是敘述性「應該會動」。

## 目前狀態（2026-07-08 更新——此段是本專案的活狀態正本，接手先讀這段）

📐 **規劃階段：spec 產線進行中，尚無實作碼**（`docs/plans/` 仍空、五個程式目錄仍只有 scaffold）。

**已完成的 design（可據以寫 plan）**：
- **P0 平台底座** design（`docs/specs/2026-07-08-P0-platform-foundation-design.md`）：kind + ArgoCD app-of-apps + GitHub Actions/GHCR + kube-prometheus-stack。
- **P1 資料管線** design（`...-P1-data-pipeline-design.md`）：Airflow KubernetesExecutor + spark-operator + MinIO/Iceberg JDBC catalog；**§6a Gold marts 5 表合約**（`gold_trending_daily` / `gold_channel_performance` / `gold_category_daily` / `gold_video_velocity_hourly` / `gold_video_lifecycle`，additive-only，是 P2 介面）。

**brief 已備、design 產出中（3 隻 Fable 5 並行跑，產物是 design 檔，會 commit 進 `docs/specs/`）**：
- **P1 留言 ingest 增補**（`...-P1-comments-ingest-addendum-brief.md`）：additive 加抓 YouTube 留言（決策 B），正當化 Spark/Iceberg + 餵 RAG/微調；產出 `silver_youtube_comments` 是 P2b/P2c 上游合約。⚠️YouTube API quota 是硬約束（累積型抓 top 影片）。
- **P2 三條 ML 垂直**（`...-P2-ml-verticals-brief.md`）：(a) 時序 tabular 預測（DVC/MLflow/KServe/drift）、(b) LangGraph agentic RAG + CRAG（pgvector/本地 embedding/Ollama 預設·Gemini fallback）、(c) HuggingFace 微調 = A DistilBERT 情緒分類器（LLM 弱標註蒸餾→KServe CPU）+ B 小 LLM PEFT LoRA 標題生成器。
- **P3 PTT ingest**（`...-P3-ptt-ingest-brief.md`）：Kafka 佇列範式（KRaft 單 broker）驅動的分散式容錯爬蟲，跟 P1 批次刻意不同的第二 ingest。

**下一步**：3 份 design 落地後 → Opus 逐份寫 implementation plan（plan 全延後至 spec 完備）→ 交執行 session。P0 必先實作（其他跑在它上面）。

**關鍵鎖定決策**（正本在 NORTH_STAR「已鎖定決策清單」+「LLM／微調層與留言語料」專章 + M4 原生算力原則）：串流只 Kafka（P3，砍 RabbitMQ/Celery/Redis）· agent 框架 LangGraph（砍 CrewAI）· 向量庫 pgvector · embedding 本地 · 生成 Ollama/Gemini 可切 · 微調 HuggingFace（砍 MLX）· **重算力原生跑 M4 host**（kind 摸不到 Apple GPU）產出可攜雲端 · 呈現層 Next.js/Vercel（平台不部署，匯出 CSV/Parquet 為合約）· MCP server 為 P4/P5 加分。

## 目錄

```
platform/ ingestion/ lakehouse/ orchestration/ ml/   # 五層（對應 P0–P3，見 NORTH_STAR）
docs/architecture/  docs/specs/  docs/plans/
```
目錄為指示性佈局；每階段 spec 敲定該層最終結構。

## 慣例

- **Git commit 中文**：`動作(範圍)：說明`（例：`建置(platform)：kind 叢集 + ArgoCD bootstrap`）。
- **TDD**：先寫失敗測試 → 實作 → 綠。頻繁小 commit。
- **一個工作一個工具**（不亂的紀律，違反 = 走回 finmind 老路）：排程只 Airflow、DB 只 Postgres（向量庫用 pgvector 同顆）、監控只 Prometheus/Grafana、**串流只 Kafka 且只 P3**（砍 RabbitMQ/Celery/Redis）、agent 框架只 LangGraph（砍 CrewAI）、微調只 HuggingFace（砍 MLX）、**不用 ClickHouse**。
- **取材既有專案唯讀不改**：可複用素材在 NORTH_STAR「可複用素材地圖」，全在 `/Users/fergus/Desktop/workshop/fergus/` 底下（yt-trending / ga4-analytics / youtube-analytics / ptt-crawler / finmind + 三門課）。**唯讀取材，不改原專案**。
- **快速演進套件先查最新官方文件再寫**（k8s / ArgoCD / Airflow / MLflow / KServe / dbt / Iceberg 升級或新接時）。

## 卡住 / 要決策時

架構層級的翻案或重大取捨 → 回報 Fergus（或規劃 Opus session）確認，不自行改動已鎖定決策（見 NORTH_STAR「已鎖定決策清單」）。
