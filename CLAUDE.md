# CLAUDE.md — trend-intelligence-platform 接手指南

> 你（Claude）被指派接手這個專案。**開工前必讀正本：[`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)**——專案定位、鎖定決策、分階段藍圖、可複用素材地圖全在那裡。本檔只放「怎麼接手、怎麼跑」的薄索引。

## 這是什麼

**求職 portfolio 專案**：一個端到端「趨勢智能」資料平台，展示 **DE（資料工程）＋ MLOps/LLMOps ＋ DevOps（k8s + GitOps）** 三種能力。主幹 = YouTube 趨勢；跑在**本地 Kubernetes**。

⚠️ **關鍵心態**：這是 portfolio，**「用 k8s、跑常駐服務」是目的本身，不是成本浪費**。不要套用「serverless 比較省、避免常駐叢集」那套邏輯來砍架構——這裡就是要展示能操作 server-based / k8s / MLOps 全套。但也**不要過度工程**（見 NORTH_STAR 的「一個工作一個工具」紀律；反面教材是 finmind 的 32 容器）。

## 開場 60 秒（接手先做這個）

1. 讀 [`docs/architecture/NORTH_STAR.md`](docs/architecture/NORTH_STAR.md)（架構正本 + 已鎖定決策 + 素材地圖）。
2. 看 `docs/specs/` 有哪些階段 spec 已出、`docs/plans/` 有哪些 plan 已寫、`git log` 看做到哪。
3. 確認你要做的階段（P0→P4 依序，P0 平台底座必須先做）。

## 工作流（誰做什麼）

```
Opus（規劃）帶 brainstorm + 寫北極星 + 逐階段交 Fable 5 出 spec + 據 spec 寫 implementation plan
  → Fable 5 讀 brief/北極星 → 出 docs/specs/<date>-P<n>-<topic>-design.md
  → 執行 session 讀 plan 逐 task 實作（TDD、頻繁 commit）
```
- **spec**：`docs/specs/YYYY-MM-DD-P<n>-<topic>-design.md`
- **plan**：`docs/plans/YYYY-MM-DD-P<n>-<topic>-implementation.md`

## 目前狀態

🏗️ **Scaffold 階段**。已完成：目錄骨架、北極星架構正本、README、本檔。**尚未有任何階段 spec / 實作碼**。下一步：**P0（平台底座）出 spec**。

## 目錄

```
platform/ ingestion/ lakehouse/ orchestration/ ml/   # 五層（對應 P0–P3，見 NORTH_STAR）
docs/architecture/  docs/specs/  docs/plans/
```
目錄為指示性佈局；每階段 spec 敲定該層最終結構。

## 慣例

- **Git commit 中文**：`動作(範圍)：說明`（例：`建置(platform)：kind 叢集 + ArgoCD bootstrap`）。
- **TDD**：先寫失敗測試 → 實作 → 綠。頻繁小 commit。
- **一個工作一個工具**（不亂的紀律，違反 = 走回 finmind 老路）：排程只 Airflow、DB 只 Postgres、監控只 Prometheus/Grafana、串流要用才加 Kafka、**不用 ClickHouse**。
- **取材既有專案唯讀不改**：可複用素材在 NORTH_STAR「可複用素材地圖」，全在 `/Users/fergus/Desktop/workshop/fergus/` 底下（yt-trending / ga4-analytics / youtube-analytics / ptt-crawler / finmind + 三門課）。**唯讀取材，不改原專案**。
- **快速演進套件先查最新官方文件再寫**（k8s / ArgoCD / Airflow / MLflow / KServe / dbt / Iceberg 升級或新接時）。

## 卡住 / 要決策時

架構層級的翻案或重大取捨 → 回報 Fergus（或規劃 Opus session）確認，不自行改動已鎖定決策（見 NORTH_STAR「已鎖定決策清單」）。
