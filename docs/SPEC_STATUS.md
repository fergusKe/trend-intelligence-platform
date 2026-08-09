# SPEC_STATUS.md — spec ↔ 實作 對帳台帳

> **這是本專案「做到哪裡」的單一真源。** README / CLAUDE.md 指向這裡，不複述這裡的內容（理由見 [`RULES.md`](RULES.md) §7）。
> 本檔由 `scripts/gates/check_spec_ledger.py` 對帳：`docs/specs/` 下每一份 `.md` 都必須在下方表格**有且只有一行**，
> 缺行、多行、狀態值打錯、標「已實作」卻拿不出證據，一律紅燈。**新增 spec 的同一個 commit 就要在這裡表態。**

## 現查數字

以下數字由 `scripts/gates/check_docs_drift.py` 每次 CI 現查對帳；不一致就紅。
要更新：`make gates-write`（等同 `python scripts/gates/check_docs_drift.py --write`）。

> 刻意**不**把「追蹤檔案總數」放進來對帳：它每加一個檔案就會紅，訊噪比太差，
> 而一個常常誤叫的閘的下場是被關掉。閘要對帳的是「會被引用來做決策的數字」，不是所有數字。

| 指標 | 值 |
|---|---|
| `docs/specs/*.md` 份數 | <!-- fact:spec_count=44 --> |
| `docs/plans/*.md` 份數 | <!-- fact:plan_count=2 --> |
| 追蹤中的 `*.py` 檔數 | <!-- fact:code_file_count=24 --> |
| 測試函式數（`def test_`） | <!-- fact:test_function_count=37 --> |
| GitHub Actions workflow 數 | <!-- fact:workflow_count=7 --> |

## 狀態值定義（fail-closed：只認這四個，其餘一律紅）

| 狀態 | 意思 | 證據欄要求 |
|---|---|---|
| `已實作` | 磁碟上有對應產出 | 一或多個 glob，**每一個都要對得到至少一個 git 追蹤檔** |
| `已規劃未實作` | spec 寫完了，程式一行都沒有 | 必須是 `—` |
| `已作廢` | 被新版取代 | 恰一個現存 spec 檔名（指出被誰取代） |
| `勘誤層` | 不是 spec，是跨 spec 的勘誤/補丁文件 | 必須是 `—` |

**「已實作」的操作型定義**：證據 glob 對得到追蹤檔。刻意不看 plan 有沒有寫、不看 checkbox、不看 commit 訊息——
只看磁碟上真的有東西。這個判準證明得了「有產出」，證明不了「產出正確」；後者是測試的工作，不是台帳的。

> ⚠️ **brief 與 design 各算一份**。同一個主題通常有 `-brief.md` + `-design.md` 兩檔，
> 所以「份數」是檔數不是主題數。目前 44 份檔 ≈ 22 個主題。

## 台帳

<!-- ledger:begin -->

| spec 檔 | 狀態 | 實作證據 / 取代者 |
|---|---|---|
| `2026-07-08-P0-platform-foundation-brief.md` | 已實作 | `platform/bootstrap/**`, `platform/argocd/**` |
| `2026-07-08-P0-platform-foundation-design.md` | 已實作 | `platform/bootstrap/**`, `platform/argocd/apps/**`, `platform/hello/**`, `.github/workflows/hello-ci.yaml` |
| `2026-07-08-P1-comments-ingest-addendum-brief.md` | 已規劃未實作 | — |
| `2026-07-08-P1-comments-ingest-design.md` | 已規劃未實作 | — |
| `2026-07-08-P1-data-pipeline-brief.md` | 已實作 | `ingestion/youtube/src/**`, `orchestration/airflow/dags/**` |
| `2026-07-08-P1-data-pipeline-design.md` | 已實作 | `ingestion/youtube/src/**`, `lakehouse/spark/jobs/**`, `lakehouse/dbt/models/marts/**`, `orchestration/airflow/dags/**` |
| `2026-07-08-P2-ml-verticals-brief.md` | 已規劃未實作 | — |
| `2026-07-08-P2-ml-verticals-design.md` | 已規劃未實作 | — |
| `2026-07-08-P3-ptt-ingest-brief.md` | 已規劃未實作 | — |
| `2026-07-08-P3-ptt-ingest-design.md` | 已規劃未實作 | — |
| `2026-07-08-P4-presentation-layer-brief.md` | 已規劃未實作 | — |
| `2026-07-08-P4-presentation-layer-design.md` | 已規劃未實作 | — |
| `2026-07-08-P5-polish-hardening-brief.md` | 已規劃未實作 | — |
| `2026-07-08-P5-polish-hardening-design.md` | 已規劃未實作 | — |
| `2026-07-09-P6-ga4-ingestion-foundation-brief.md` | 已規劃未實作 | — |
| `2026-07-09-P6-ga4-ingestion-foundation-design.md` | 已規劃未實作 | — |
| `2026-07-09-P6-realtime-features-brief.md` | 已規劃未實作 | — |
| `2026-07-09-P6-realtime-features-design.md` | 已規劃未實作 | — |
| `2026-07-09-P6-recommendation-brief.md` | 已規劃未實作 | — |
| `2026-07-09-P6-recommendation-design.md` | 已規劃未實作 | — |
| `2026-07-09-P7-dmp-brief.md` | 已規劃未實作 | — |
| `2026-07-09-P7-dmp-design.md` | 已規劃未實作 | — |
| `2026-07-09-ga4-extension-crosscut.md` | 已規劃未實作 | — |
| `2026-07-10-ai-ops-incident-narrator-brief.md` | 已規劃未實作 | — |
| `2026-07-10-ai-ops-incident-narrator-design.md` | 已規劃未實作 | — |
| `2026-07-10-ask-ai-brief.md` | 已規劃未實作 | — |
| `2026-07-10-ask-ai-design.md` | 已規劃未實作 | — |
| `2026-07-10-frontend-design-system-brief.md` | 已規劃未實作 | — |
| `2026-07-10-frontend-design-system-design.md` | 已規劃未實作 | — |
| `2026-07-10-ga-pillar-brief.md` | 已規劃未實作 | — |
| `2026-07-10-ga-pillar-design.md` | 已規劃未實作 | — |
| `2026-07-10-observability-hardening-brief.md` | 已規劃未實作 | — |
| `2026-07-10-observability-hardening-design.md` | 已規劃未實作 | — |
| `2026-07-10-p6-advanced-recall-brief.md` | 已規劃未實作 | — |
| `2026-07-10-p6-advanced-recall-design.md` | 已規劃未實作 | — |
| `2026-07-10-p7-model-based-tags-brief.md` | 已規劃未實作 | — |
| `2026-07-10-p7-model-based-tags-design.md` | 已規劃未實作 | — |
| `2026-07-10-search-pillar-brief-v2.md` | 已規劃未實作 | — |
| `2026-07-10-search-pillar-brief.md` | 已作廢 | `2026-07-10-search-pillar-brief-v2.md` |
| `2026-07-10-search-pillar-design-v2.md` | 已規劃未實作 | — |
| `2026-07-10-search-pillar-design.md` | 已作廢 | `2026-07-10-search-pillar-design-v2.md` |
| `2026-07-10-unified-portfolio-crosscut-brief.md` | 已規劃未實作 | — |
| `2026-07-10-unified-portfolio-crosscut-design.md` | 已規劃未實作 | — |
| `2026-07-17-design-errata.md` | 勘誤層 | — |

<!-- ledger:end -->

## 這張表現在說了什麼

- **P0 平台底座**與 **P1 資料管線**是唯二有磁碟產出的：kind + ArgoCD app-of-apps + 監控、
  YouTube ingest → Iceberg Bronze → Spark Silver → dbt Gold 5 表 → Airflow 三支 DAG。
- **P1 留言 ingest 增補**（`silver_youtube_comments`）雖然屬於 P1，但**沒有任何實作**——
  它是 P2b RAG / P2c 微調的上游合約，動 P2 之前要先補。
- 其餘每一份 spec 都是「已規劃未實作」。這不是壞消息，是**這個 repo 的實際形狀**：
  spec 的產出速度遠快於實作，而在有這張表之前，這個落差在任何載體上都看不出來。

## 維護

```bash
python scripts/gates/check_spec_ledger.py     # 對帳；缺行/證據對不到 → exit 1
python scripts/gates/check_docs_drift.py      # 文件宣稱 vs 磁碟事實
python scripts/gates/check_docs_drift.py --write   # 回填上面那張「現查數字」
python scripts/gates/positive_control.py      # 證明上面兩支閘在該紅時真的會紅
```
