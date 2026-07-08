# trend-intelligence-platform

> 端到端「趨勢智能」資料平台 — **DE + MLOps/LLMOps + DevOps** on Kubernetes

以 YouTube 熱門趨勢為主幹（PTT 論壇為第二來源），把原始資料從 **ingest → Lakehouse → 建模 → 上線監控**打通一條龍，全程跑在 **Kubernetes**、以 **GitOps** 部署、具備完整可觀測性。一個平台同時展示資料工程、模型維運、平台工程三種能力。

> 狀態：🏗️ **規劃中（scaffold 階段）**。架構已定案，逐階段實作中。詳見 [`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)。

---

## 架構總覽

```
[GitHub Actions]  build → test → lint → docker push → 改 k8s manifest tag
       │ git push
[ArgoCD GitOps]  監看 manifest → 自動 sync 到叢集
       ▼
┌─ Kubernetes（本地 kind/k3d）──────────────────────────────┐
│                                                            │
│  ── 資料層（DE）───────────────────────────────────────    │
│   YouTube API ─┐                                           │
│   PTT 爬蟲 ────┴→ (Kafka) → MinIO/Iceberg(Bronze)          │
│                    → Spark(Silver) → dbt(Gold→Postgres)    │
│                    Airflow 編排全鏈 + dbt 資料品質測試        │
│                                                            │
│  ── ML 層（MLOps / LLMOps）────────────────────────────    │
│   (a) tabular：DVC → MLflow(追蹤+登錄) → KServe → drift/重訓 │
│   (b) LLMOps：RAG(向量庫) → 生成服務 → prompt 版本 + 評估     │
│                                                            │
│  ── 可觀測性 ─────────────────────────────────────────     │
│   Prometheus + Grafana（服務指標 + 模型 drift 儀表板）        │
└────────────────────────────────────────────────────────────┘
```

## 技術棧

| 分層 | 工具 |
|---|---|
| 容器 / 編排 | Docker · **Kubernetes**（本地） |
| CI/CD / GitOps | **GitHub Actions** · **ArgoCD** |
| 資料管線編排 | **Apache Airflow** |
| Lakehouse | **MinIO/S3 + Apache Iceberg** · **Spark** · **dbt** |
| 儲存 | **PostgreSQL** |
| ML 生命週期 | **DVC** · **MLflow** · **KServe** |
| LLMOps | 向量庫（Qdrant/pgvector）· RAG · prompt 版本 / 評估 |
| 可觀測性 | **Prometheus + Grafana** |

## 分階段藍圖

| 階段 | 內容 | 展示能力 |
|---|---|---|
| **P0** 平台底座 | k8s + ArgoCD GitOps + GitHub Actions CI + Prometheus/Grafana | DevOps / 平台 |
| **P1** 資料管線 | YouTube ingest → Lakehouse(Iceberg/Spark/dbt) → Postgres，Airflow 編排 | 資料工程 |
| **P2** ML 垂直 ×2 | (a) MLflow+KServe tabular 影片表現預測；(b) LLMOps/RAG | MLOps / LLMOps |
| **P3** 進階 ingest | PTT 分散式爬蟲第二來源（＋選配 Kafka 串流） | 爬蟲 / 串流硬實力 |
| **P4** 收尾 | 安全掃描、架構圖、面試敘事 | 整體打磨 |

## 目錄結構

```
platform/        # P0：k8s manifests、ArgoCD、CI、監控（DevOps 底座）
ingestion/       # P1/P3：YouTube API + PTT 爬蟲
lakehouse/       # P1：Spark jobs、dbt 專案、儲存
orchestration/   # P1：Airflow DAGs
ml/              # P2：tabular（MLflow/KServe）+ LLMOps（RAG）
docs/
  architecture/  # 北極星架構正本
  specs/         # 各階段設計 spec
  plans/         # 實作計畫
```
> 目錄為指示性佈局；每階段的 spec 會敲定該層的最終結構。

## 本地啟動（規劃中，待 P0 spec 落地）

目標：`kind create cluster` → ArgoCD 指向本 repo → 各服務自動 sync。詳細啟動步驟待 P0 spec 完成後補上。

## 靈感來源

本平台是把多個個人資料工程練習專案（yt-trending / ga4-analytics / ptt / youtube-analytics / finmind）中最強的部分，收斂成一個連貫、乾淨、可展示的統一平台，並補齊業界標準的 MLOps/GitOps 缺口。
