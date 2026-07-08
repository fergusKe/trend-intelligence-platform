# P2 三條 ML 垂直 — Design（Fable 5 產出）

> **狀態**：design 完成，待 Opus 寫 implementation plan。
> **上游**：[`2026-07-08-P2-ml-verticals-brief.md`](2026-07-08-P2-ml-verticals-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)（LLM／微調層專章 + M4 原生算力原則）+ [`P0 design`](2026-07-08-P0-platform-foundation-design.md)（GitOps/CI/監控慣例）+ [`P1 design`](2026-07-08-P1-data-pipeline-design.md)（§6a Gold 5 表合約、Silver loader、secret 姿態）+ [`P1 留言 ingest 增補 brief`](2026-07-08-P1-comments-ingest-addendum-brief.md)（`silver_youtube_comments` 為 P2b/P2c 上游語料合約——該 design 可能並行產出，本檔以 brief 的 schema 意圖為 seam，見 §2 資料依賴）。
> **已鎖定決策全部沿用，未翻案**：三條都做／DVC+MLflow+KServe／LangChain+LangGraph+CRAG+hybrid（砍 CrewAI 與 OpenAI 路）／pgvector（複用 P1 Postgres）／本地 embedding／生成 Ollama 預設+Gemini fallback／HuggingFace 微調（A DistilBERT＋B PEFT LoRA fp16，非 4-bit）／M4 原生算力／backing store 複用 P1 Postgres+MinIO。
> **版本查證日**：2026-07-08（PyPI JSON API / GitHub releases / Docker Hub tags / context7 官方文件，非記憶）。
> **2026-07-08 本地模型刷新**：兩個本地槽升 Qwen3.5（微調基座 `Qwen3-1.7B`→**`Qwen3.5-2B`**（dense）；RAG 生成 `qwen3:8b`→**`qwen3.5:9b`**）——理由與淘汰見 §8生成LLM／§12基座，架構故事與 M4 界線不變。前沿大模型（DeepSeek/GLM/Kimi/MiniMax）評估後排除本地槽（資料中心級，16GB M4 跑不動），僅為未來「換 Gemini API fallback」的候選軸。Embedding（e5-small）複查後維持。
> **檔案判定**：單檔承載。P2-0 底盤只定義一次（§3），P2a（§4–7）/P2b（§8–10）/P2c（§11–12）各自成章、可獨立轉 plan；拆兩份 sub-design 的跨參照成本高於單檔篇幅成本。

---

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證方式 |
|---|---|---|
| MLflow（server image base + client） | **3.14.0**（`ghcr.io/mlflow/mlflow:v3.14.0` 基底自建 image；client 用 `mlflow-skinny==3.14.0`） | PyPI |
| DVC | **3.67.1** + `dvc-s3==3.3.0` | PyPI |
| KServe | **v0.19.0**（2026-06-14 release；Helm charts `oci://ghcr.io/kserve/charts/…`，chart 確切名 §15 實查 1） | GitHub releases |
| cert-manager（KServe webhook 憑證前置） | **v1.20.3** | GitHub releases |
| pgvector | **0.8.4**；Postgres image 換 **`pgvector/pgvector:0.8.4-pg16`**（同 PG16 major，PVC 資料相容） | GitHub tags + Docker Hub tags |
| LangChain / LangGraph | **langchain 1.3.11 / langchain-core 1.4.8 / langgraph 1.2.8** | PyPI |
| LangChain 整合包 | **langchain-ollama 1.1.0 / langchain-google-genai 4.2.7** | PyPI |
| transformers / PEFT / TRL | **5.13.0 / 0.19.1 / 1.7.1**（三者相容矩陣 §15 實查 3） | PyPI |
| sentence-transformers | **5.6.0** | PyPI |
| torch | **2.12.1**（MPS 後端；k8s 側裝 CPU wheel） | PyPI |
| datasets / evaluate / accelerate | **5.0.0 / 0.4.6 / 1.14.0** | PyPI |
| Ollama（host 原生安裝） | **v0.31.1** | GitHub releases |
| psycopg / pgvector-python | **3.3.4 / 0.5.0** | PyPI |

CI actions 沿用 P0 pin。Airflow/Spark/dbt/MinIO/Postgres 版本沿用 P1 §0（Postgres 僅換 image 發行版，見 §3.4）。

---

## 1. 五個關鍵決策（先拍板，細節在各簇）

### ① KServe = **RawDeployment（Standard）模式，不裝 Knative/Istio/Gateway API**

| 候選 | 判定 |
|---|---|
| **RawDeployment** ✅ | InferenceService 只產生原生 Deployment/Service/HPA/Ingress；ingress 走 inferenceservice-config 的 `ingressClassName: nginx`（官方文件明載此 key 專屬 raw 模式）＋ `ingressDomain: localtest.me`——與 P0 nginx-ingress 零控制器註解鐵律完全同構。前置只需 cert-manager（webhook 憑證）。kind 資源省下整套 service mesh。取捨：無 scale-to-zero/revision 金絲雀（Knative 專屬）——demo 叢集 minReplicas=1 本來就不需要 scale-to-zero；金絲雀敘事由 MLflow alias + GitOps rollout 承擔，README 誠實記錄。 |
| Serverless（Knative+Istio） | 淘汰：kind 上多兩套常駐控制平面（~2GB+），只為 scale-to-zero 與 revision split；違反「一個工作一個工具」（ingress 已有 nginx，再來 istio ingressgateway 是第二套）。 |
| Gateway API 模式 | 淘汰：v0.19 的 Standard 快裝走 Gateway API+Istio；我方已有 nginx Ingress，用 raw+Ingress 即可，不為新 API 換掉既有 ingress 層。 |

### ② MLflow = **plain kustomize manifests + 自建 image**（對齊 P1 對 MinIO 的選擇）

| 候選 | 判定 |
|---|---|
| **plain manifest** ✅ | 完全複用 P0 服務接入契約（kustomize `k8s/` + 子 Application）。image：`FROM ghcr.io/mlflow/mlflow:v3.14.0` + `psycopg2-binary` + `boto3`（官方 image 不含 PG driver 與 S3 依賴）。單 replica Deployment + Service + Ingress `mlflow.localtest.me`。 |
| community Helm chart（burakince/mlflow） | 淘汰：第三方個人維護 chart（image 也是個人 repo `burakince/mlflow`），供應鏈信任面差；values 面積大。 |
| Databricks 托管 / 自組 helm | 淘汰：前者違零雲成本；後者是自造 chart 的白工。 |

**backend/artifact 具體接法**：backend store = P1 共用 Postgres 新 **database `mlflow`**（`postgresql://mlflow_user:…@lakehouse-postgres.data:5432/mlflow`）；artifact store = P1 MinIO 新 bucket **`mlflow-artifacts`**，server 以 **`--serve-artifacts`（proxied artifact access）** 起——host 側 client（M4 訓練）只需 `MLFLOW_TRACKING_URI=http://mlflow.localtest.me`，**不需持有 MinIO 憑證**，把 host↔叢集的憑證面收到最小。`--artifacts-destination s3://mlflow-artifacts`，S3 endpoint/憑證只在 server pod env（Secret 注入）。

**Registry 語意（誠實修正課程素材）**：MLflow 3 已**移除 Stage（Staging/Production）機制**，正規做法是 **registered model alias**。本設計以 alias **`@staging` / `@prod`** 實作 brief 的「Staging→Prod 晉升」，README 註記與課程 `model_training.py`（stage 版）的差異。**MLflow 同時兼任 Prompt Registry**（🔒收斂：一個工具兩用，不另立）——`mlflow.genai.register_prompt` / `load_prompt("prompts:/<name>@prod")` / `set_prompt_alias`（context7 對 3.x 官方文件驗證過的 API 面）。

### ③ DVC 定位 = **「可重現離線訓練管線 + 資料快照版本化」，不進 Airflow 排程迴圈**

DVC 版本化的東西（remote = MinIO 新 bucket **`dvc`**，經 `dvc-s3`，endpoint 走 §3.6 的 MinIO API ingress）：
1. **tabular 訓練資料快照**（`ml/tabular/data/train.parquet`——由 dvc stage 從 Gold 匯出）；
2. **微調資料集**（弱標註留言 jsonl、標題 instruction pairs jsonl、人工/雙標 test set）；
3. **RAG eval set**（`evalset.yaml` 小，直接進 git；其引用的 frozen 語料快照進 DVC）。

`dvc.yaml` pipeline（`export → features → train → evaluate`）**在 M4 host 跑 `dvc repro`**（訓練本來就在 host，見 ④）。**排程重訓（Airflow）不跑 DVC**——pod 內 git commit 是反模式；重訓 DAG 呼叫同一批 Python entrypoint，資料集快照寫 MinIO bucket **`ml-datasets`** 決定性路徑（`dataset=video_perf/exported_at=<ISO>/train.parquet`）並把路徑 log 進 MLflow run params（可追溯），事後可 `dvc import-url` 收編。兩條路徑共用同一份程式碼，README 記錄這條「DVC=離線可重現層、MLflow=線上追蹤層」的分工。

### ④ M4 host ↔ k8s 執行界線總表（🔒 M4 原生算力原則的落地帳）

| 工作 | 執行處 | 理由 |
|---|---|---|
| tabular 訓練/重訓（sklearn） | **k8s**（Airflow KPO，ml-batch image）＋ host `dvc repro` 皆可 | CPU 輕負載，兩邊同 entrypoint；排程重訓走 k8s |
| tabular 批次打分 / drift 計算 | **k8s**（Airflow KPO） | CPU 輕 |
| 留言 embedding **初始 backfill**（百萬列） | **M4 host**（MPS，`make embed-backfill`） | 重算力；MPS 對 CPU 約一個量級加速 |
| 留言 embedding **每日增量** | **k8s**（Airflow KPO，CPU） | 增量僅日級數千~數萬列，e5-small CPU 可承受；讓排程紀律不破口 |
| DistilBERT 微調 | **M4 host**（MPS，`make train-sentiment`） | 重算力原生跑 host（原則） |
| LLM LoRA 微調（Qwen3.5-2B fp16） | **M4 host**（MPS） | kind 摸不到 Apple GPU（原則核心） |
| 本地 LLM 推論（Ollama：RAG 生成/grade、標題生成） | **M4 host**（Ollama 原生 daemon） | 同上 |
| 情緒批次打分（DistilBERT 推論） | **k8s**（Airflow KPO，CPU）；百萬列歷史 backfill 在 host | 分類器 CPU-feasible |
| KServe serving（video-predictor / sentiment） | **k8s** | CPU-feasible serving 歸 k8s（原則） |
| RAG 服務（LangGraph 狀態機 API） | **k8s**（Deployment），生成步跨線呼叫 host Ollama（§9 接線） | 編排/glue 歸 k8s |
| MLflow / KServe / 監控 / 匯出 | **k8s** | 平台層 |

**host→叢集存取面**（host 跑的工作需要的三條線，全部收斂）：MLflow = `http://mlflow.localtest.me`（HTTP ingress，零憑證面——artifact 走 proxy）；MinIO S3 API = `http://minio-api.localtest.me`（**新增 MinIO API Ingress**，additive manifest 進 `lakehouse/minio/k8s/`，DVC remote/mc 用，憑證 = 既有 `minio-root`）；Postgres = `make pg-tunnel`（`kubectl port-forward svc/lakehouse-postgres 15432:5432`，TCP 無法走 nginx HTTP ingress，port-forward 是 demo 正解）。host 憑證放 repo 根 `.env.ml`（gitignored，`make ml-secrets` 同步生成），**絕不硬編碼**（原碼 `gemini_client.py:37` 反例，本設計零沿用）。

**k8s→host 存取面**（唯一一條）：RAG 服務等 pod 呼叫 host Ollama，走 §9 的 ExternalName Service 接線。

### ⑤ 對 P4 的產出 = **一律落 Postgres `ml` schema 表**（拓撲硬約束的正面處理）

平台不部署、前端在 Vercel → **前端永遠打不到本地 k8s 的任何線上端點**。因此 P2 對 P4 的合約統一為**四張批次產生的表 + 一張 dbt mart**（§13），P4 的匯出 DAG 把它們與 Gold marts 一起匯成靜態檔。KServe 推論端點與 RAG API 是「本地 demo/截圖/面試現場」用途，**不是 P4 的 runtime 依賴**——RAG 問答與 LoRA 標題全部**預先批次產生範例**寫表。這條界線寫進 README 的架構誠實章。

---

## 2. 總體形狀

### 資料依賴（消費既有層合約，不繞道）

```
P1 Gold（5 表合約，§6a）─┬─ gold_video_lifecycle（+additive duration_seconds，§4）──┐
                          └─ gold_video_velocity_hourly ─────────────────────────────┤
                                                                                      ├─→ P2a 特徵/label（§4）
P1 留言增補 silver_youtube_comments（增補 brief 定義的表名/意圖為 seam：              │
  comment_id PK / video_id / text / like_count / published_at(timestamptz)           ├─→ P2b RAG 語料（§8）
  / author_hash / ingest_date；若並行 design 定名有出入，以其 design 為準，           ├─→ P2c-A 弱標註原料（§11）
  本檔引用點集中在 §8.2 語料 SQL 與 §11 弱標註抽樣 SQL 兩處，改表名即收斂）           │
gold_video_lifecycle.title/description/tags ─────────────────────────────────────────┴─→ P2b 輔語料 / P2c-B 標題語料（§12）
```

**缺欄 additive 清單**（消費不繞道原則的落地，全部走「加欄」不改粒度/不刪欄）：
1. `silver.video_snapshots` **加 `duration_seconds bigint`**（Spark 解析 `contentDetails.duration` ISO-8601——Bronze 保原文本就有料，P1 §5 轉換清單加一欄；歷史回填走既有 `yt_reprocess_range` DAG）。
2. `gold.gold_video_lifecycle` **加 `duration_seconds bigint`**（最新快照值）。理由：時長對 Shorts/長片表現差異大，brief 傾向已明示；成本 = Spark job 一行解析 + dbt 一欄透傳。

### 目錄結構（頂層 `ml/` domain 目錄；接入依 P0 服務接入契約）

```
ml/
├── mlflow/
│   ├── Dockerfile                    # FROM ghcr.io/mlflow/mlflow:v3.14.0 + psycopg2-binary + boto3
│   └── k8s/                          # kustomization + deployment + service + ingress(mlflow.localtest.me)
├── kserve/                           # InferenceService manifests（ArgoCD 管，宣告式）
│   ├── kustomization.yaml
│   ├── video-predictor.yaml          # §6
│   ├── comment-sentiment.yaml        # §11
│   └── s3-secret-sa.yaml             # KServe S3 憑證 Secret 註解 + ServiceAccount（§3.5）
├── db/
│   └── k8s/                          # ml-db-init Job（PostSync hook）：CREATE EXTENSION vector /
│                                     #   CREATE SCHEMA ml / mlflow db / ml 角色——冪等 psql script ConfigMap
├── batch/                            # ★ 單一共用批次 image（Airflow KPO 用）
│   ├── Dockerfile                    # python:3.12-slim + torch(cpu) + transformers + sentence-transformers
│   │                                 #   + scikit-learn + mlflow-skinny + psycopg + pgvector + boto3
│   └── pyproject.toml                # 裝 ml_tabular / ml_rag_index / ml_sentiment 三個本地套件
├── tabular/                          # P2a：純 Python 套件 ml_tabular
│   ├── pyproject.toml
│   ├── dvc.yaml  params.yaml         # export → features → train → evaluate（host 跑 dvc repro）
│   ├── src/ml_tabular/
│   │   ├── dataset.py                # Gold → 訓練資料集 SQL 匯出（§4）
│   │   ├── features.py               # 特徵工程（顯式 FEATURE_SCHEMA 常數，§4）
│   │   ├── train.py                  # 訓練 + MLflow log + 註冊 + gate（§5）
│   │   ├── score.py                  # 批次打分 → ml.ml_video_predictions（§6）
│   │   └── drift.py                  # PSI/品質回算 → ml.ml_drift_metrics（§7）
│   └── tests/
├── rag/
│   ├── indexer/                      # P2b-1：套件 ml_rag_index（雙模式：host MPS / k8s CPU）
│   │   ├── src/ml_rag_index/{corpus.py,embed.py,write_pg.py}
│   │   └── tests/
│   ├── service/                      # P2b-2：FastAPI + LangGraph 服務
│   │   ├── Dockerfile  pyproject.toml
│   │   ├── src/rag_service/{graph.py,retrieval.py,llm.py,metrics.py,api.py}
│   │   ├── k8s/                      # deployment + service + ingress(rag.localtest.me) + servicemonitor
│   │   │                             #   + ollama-host externalname service（§9 接線）
│   │   └── tests/
│   └── eval/                         # P2b-3：evalset.yaml + run_eval.py + judge prompts
├── finetune/
│   ├── sentiment/                    # P2c-A：weak_label.py / train.py / evaluate.py / dvc.yaml
│   └── title_lora/                   # P2c-B：build_dataset.py / train_lora.py / export_gguf.sh /
│                                     #   gen_showcase.py / Modelfile
└── exports/                          # （P4 接口文件：四表 + mart 的 schema 描述，README 級）
orchestration/airflow/dags/
├── ml_score_hourly.py  ml_sentiment_daily.py  ml_embed_incremental.py
├── ml_drift_daily.py   ml_retrain.py          # §7/§13 DAG 結構
platform/argocd/apps/                 # ★ 新增 8 個子 Application（下表）
platform/monitoring/ml/               # dashboards ×3 + PrometheusRule + postgres-exporter 自訂查詢擴充
.github/workflows/
├── ml-batch-ci.yaml  rag-service-ci.yaml  mlflow-ci.yaml     # 複製 P1 CI 模式（§14）
Makefile                              # += ml-secrets / pg-tunnel / embed-backfill / weak-label /
                                      #    train-sentiment / train-lora / export-gguf / rag-eval /
                                      #    promote-model / gen-showcase / ml-verify
scripts/verify-ml.sh
```

### Namespace 與 sync-wave（接續 P1 的 3–6）

| wave | Application | namespace | 內容 |
|---|---|---|---|
| 7 | cert-manager | `cert-manager` | Helm chart v1.20.3（KServe webhook 前置；`installCRDs: true`） |
| 8 | kserve-crd | `kserve` | KServe CRDs chart v0.19.0 |
| 8 | ml-db-init | `data` | PostSync hook Job（冪等 SQL，§3.4）——**必須先於 mlflow**（它建 `mlflow` db） |
| 9 | kserve | `kserve` | controller chart v0.19.0：`deploymentMode: RawDeployment`、inferenceservice-config `ingress: {ingressClassName: nginx, ingressDomain: localtest.me, enableGatewayApi: false}`（確切 values 路徑 §15 實查 1） |
| 9 | mlflow | `ml` | plain kustomize（§1②） |
| 10 | kserve-models | `ml` | `ml/kserve/`：InferenceService ×2 + S3 Secret/SA（宣告式模型版本載體） |
| 10 | rag-service | `ml` | `ml/rag/service/k8s/`：Deployment/Service/Ingress/ServiceMonitor + ollama-host ExternalName（獨立 Application——CI bump 它的 kustomization，同 P0 hello 模式） |
| 11 | ml-monitoring | `monitoring` | dashboards ×3 + PrometheusRule + statsd/exporter 擴充 |

InferenceService 資源沿用 P0 的 `SkipDryRunOnMissingResource=true` 註解（CRD 在 wave 8 才到）。P1 的 `lakehouse-postgres`（wave 3）**image 換 `pgvector/pgvector:0.8.4-pg16`**（§3.4）。

---

## 3. P2-0 共用 MLOps 底盤（決定）

### 3.1 MLflow 佈局

| 項目 | 決定 |
|---|---|
| experiments | `tabular_video_predictor` / `sentiment_distilbert` / `title_lora` / `rag_eval`（四條實驗線，一比一對應垂直＋RAG 評估） |
| registered models | `video-predictor`（sklearn pyfunc）/ `comment-sentiment`（transformers）/ `title-gen`（LoRA adapter + GGUF artifact 掛同 run） |
| aliases | `@staging`（自動閘門後自動掛）/ `@prod`（人工晉升掛，§7 晉升流程） |
| prompts（Prompt Registry） | `rag-answer` / `rag-grade` / `rag-rewrite` / `sentiment-weak-label` / `title-topic-extract`——alias `@prod` 供 runtime 載入（`load_prompt("prompts:/rag-answer@prod", cache_ttl_seconds=60)`） |
| server 旗標 | `mlflow server --backend-store-uri postgresql://… --artifacts-destination s3://mlflow-artifacts --serve-artifacts --host 0.0.0.0`；S3 env：`MLFLOW_S3_ENDPOINT_URL=http://lakehouse-minio.data:9000` + `minio-root` 憑證 |

### 3.2 DVC（§1③ 已拍板）——remote `s3://dvc`，config 裡 `endpointurl = http://minio-api.localtest.me`，憑證走 `.env.ml`（`AWS_ACCESS_KEY_ID/SECRET…` local config 不進 git）。

### 3.3 KServe 安裝（§1① 已拍板）——cert-manager → kserve-crd → kserve controller 三個 Helm 子 Application；`kserve.controller.deploymentMode: RawDeployment` 為全域預設（InferenceService 免逐個註解）。Raw 模式 URL 形狀 = domainTemplate 預設 `{{ .Name }}-{{ .Namespace }}.{{ .IngressDomain }}` → `video-predictor-ml.localtest.me` / `comment-sentiment-ml.localtest.me`（nginx Ingress 自動產生，零手寫 ingress）。autoscaling = raw 模式原生 HPA，本設計 minReplicas=1、不設 HPA target（demo 無負載，要用才加）。

### 3.4 Postgres pgvector 化 + `ml` schema（對 P1 資產的兩個 additive 變更）

| 變更 | 內容 | 風險處置 |
|---|---|---|
| image 換發行版 | `postgres:16.14` → **`pgvector/pgvector:0.8.4-pg16`**（官方 pgvector image = PG16 + 預編譯 extension，drop-in） | 同 major（16）PVC 資料相容；ArgoCD 滾動 = 單 replica 短暫中斷（demo 可接受）。淘汰：initContainer 自編譯（脆）；sidecar 另起向量 DB（違「DB 只 Postgres」）。 |
| `ml-db-init` Job | PostSync hook（`hook-delete-policy: HookSucceeded`）跑冪等 psql：`CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;`（lakehouse db）＋ `CREATE SCHEMA IF NOT EXISTS ml;`＋ `mlflow` database（`SELECT 'CREATE DATABASE mlflow' WHERE NOT EXISTS(…)\gexec`）＋ 角色 `ml_writer`（ml schema 讀寫 + silver/gold 唯讀）、`mlflow_user`（mlflow db owner）；`grafana_reader` GRANT 擴至 ml schema | P1 init ConfigMap 只在首次 initdb 生效——既有 PVC 不重跑，所以**一切 P2 DDL 走這個 hook Job**，不改 P1 init SQL 的既有段落 |

`ml` schema 的表（`ml.ml_*` 由各 job 首行 `CREATE TABLE IF NOT EXISTS` 持有 DDL，同 P1 loader 慣例）：`ml_video_predictions`（§6）、`ml_comment_sentiment`（§11）、`rag_documents`（§8）、`ml_rag_showcase`（§10）、`ml_title_examples`（§12）、`ml_drift_metrics`（§7）。

### 3.5 Secrets 邊界（`make ml-secrets`，沿用 P1 §8 命令式姿態，冪等 apply）

| Secret | ns | 內容 |
|---|---|---|
| `gemini-api` | ml、airflow | `GEMINI_API_KEY`（唯一新增外部憑證；RAG fallback / 弱標註 / LLM judge） |
| `minio-root`（複製） | ml | MLflow server artifact 直寫用（host client 不需要——proxy 模式） |
| `lakehouse-postgres-ml` | ml、airflow | `ml_writer` / `mlflow_user` 連線串（由 ml-db-init 產生的角色） |
| `kserve-s3` | ml | KServe storage Secret：`AWS_ACCESS_KEY_ID/SECRET` + 註解 `serving.kserve.io/s3-endpoint: lakehouse-minio.data:9000`、`s3-usehttps: "0"`（context7 驗證過的官方形狀）；綁 ServiceAccount `kserve-s3-sa`，InferenceService 引用 |
| host `.env.ml`（非 k8s） | repo 根，gitignored | `GEMINI_API_KEY` / MinIO 憑證 / `MLFLOW_TRACKING_URI` / tunnel 後 PG 連線串 |

### 3.6 MinIO 增量（additive 進 P1 資產）：bucket-init Job 的 `mc mb --ignore-existing` 清單加 `mlflow-artifacts` / `dvc` / `ml-datasets` / `ml-models`；`lakehouse/minio/k8s/` 加一個 API Ingress（`minio-api.localtest.me` → :9000，零註解）。

---

## 4. P2a-1 特徵/label 工程（決定）

### 預測目標與 label 定義（brief 進化方向的收斂拍板）

| 項目 | 決定 |
|---|---|
| **任務型態** | **二分類**：`doubled_in_24h`——影片上榜後 24 小時內觀看數是否相對「上榜首快照」翻倍。淘汰回歸 `total_views_gained`（重尾難評估、對 demo 不直觀）與回歸 `peak_delta_views_per_hour`（同前）；二分類有乾淨的 AUC/PR 評估、天然的校準敘事、且 label 定義**絕對**（不隨母體分佈漂移——分位數式 label 會讓「drift 偵測」與「label 定義」互相污染）。 |
| **label 公式** | 取 `t0 = first_seen_at`（`gold_video_lifecycle`）；`v0 = first_views`；`v24 =` `gold_video_velocity_hourly` 中 `captured_at ∈ (t0+20h, t0+30h]` **最接近 t0+24h** 的快照 views；`label = (v24 ≥ 2·v0)`。無該窗口快照（提前掉榜/缺口）→ **樣本剔除**（不猜、不外插；剔除率進資料集 metadata）。 |
| **特徵時間窗（防洩漏正本）** | **τ = t0 + 3h**：特徵只准用 (a) 影片 metadata（發布即知）(b) 首快照值 (c) `captured_at ≤ t0+3h` 的 velocity 快照。`3h < 20h` 窗口下界 → 結構性不可能洩漏 label 期資訊。打分側同守則：影片上榜滿 3h 才打分（§6）。 |
| **樣本粒度** | 一列 = `(video_id, region)`（同 lifecycle 粒度）；同影片跨區是不同樣本（各區觀眾行為不同，這是特徵不是洩漏）。 |

### 特徵集 `features_v1`（顯式 schema——修原碼「dict 插入序」缺陷）

| 群 | 特徵 | 來源/定義 |
|---|---|---|
| 標題/描述/標籤 | `title_len_chars`、`title_word_count`、`title_emoji_count`、`title_punct_count`（!？?！合計）、`desc_len_chars`、`tag_count` | `gold_video_lifecycle.title/description/tags`（上榜時值） |
| 時長 | `duration_seconds`、`is_short`（<60s） | **additive 新欄**（§2） |
| 發布時間 | `publish_hour_local`（0-23）、`publish_dow`（0-6）、`is_prime_time`（19–23 local） | `published_at` 依 **region→IANA tz 常數表**（TW=Asia/Taipei…8 區，`features.py` 單一真源）轉當地時間——修原碼 UTC 時段語意含糊 |
| 上榜早期訊號（時序新增） | `video_age_hours_at_entry`（`first_seen_at − published_at`）、`log1p_first_views`、`log1p_early_velocity_3h`（τ 窗內 `delta_views_per_hour` 均值；不足 2 快照 → 0 並帶 `has_early_velocity` 旗標）、`early_engagement_rate`（首快照） | lifecycle + velocity_hourly |
| 類別 | `region` one-hot（8）、`category_id` one-hot（全域 top-10 + `other`，清單凍結進 params.yaml） | |
| **刪除** | 原碼硬編碼熱詞清單（`:199-200`）與「爆紅機率查表」（`:327-357`） | 前者是過擬合的手工特徵、後者是假機率——範本債，README 記錄不搬 |

**FEATURE_SCHEMA**：`features.py` 內一個 ordered `list[FeatureSpec(name, dtype, source)]` 常數；訓練時序列化成 JSON 隨 MLflow model artifact 存（`feature_schema.json`），打分側載入並斷言欄位名/序一致——schema 漂移直接 fail-fast。

**資料集匯出**：`ml_tabular.dataset:export` 一支 SQL（velocity CTE 算 v24 與 early_velocity + join lifecycle）→ parquet。雙路徑：host `dvc repro` 的 `export` stage 寫 `ml/tabular/data/`（DVC 追蹤）；排程重訓寫 `s3://ml-datasets/dataset=video_perf/exported_at=<ISO>/`（§1③）。時間切割欄 `t0` 一併存列。

---

## 5. P2a-2 訓練管線（決定）

| 開放問題 | 決定 |
|---|---|
| 在 k8s 怎麼跑 | **Airflow KubernetesPodOperator + `ml-batch` image**（重訓 DAG 內，§7）。淘汰獨立 k8s Job（脫離排程器視野）與 SparkML（殺雞牛刀）。host 側 `dvc repro` 跑同一 `ml_tabular.train:main`。 |
| split 策略 | **時序 hold-out**：按 `t0` 排序，前 80% train、後 20% test（時序題禁隨機 split——未來資訊會透過同期樣本洩漏）；train 內再切尾 10% 當 early-stopping/校準 val。 |
| 模型 | sklearn **`Pipeline(ColumnTransformer(StandardScaler→數值欄, passthrough→one-hot), RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced", n_jobs=-1))`**——scaler **烤進 pipeline**（單一 artifact，serving 免 transformer，§6）。超參進 `params.yaml`（DVC 追蹤）。 |
| baseline | ①`DummyClassifier(strategy="prior")` ②`LogisticRegression(class_weight="balanced")`（同 ColumnTransformer）——兩個 baseline 同 run 附帶訓練並 log metrics，證明 RF 的增量價值（面試防「為什麼不用線性」）。 |
| 評估指標 | test 集：**ROC-AUC（主）**、PR-AUC、Brier score、F1@0.5、混淆矩陣 + 特徵重要性（`feature_importances_` bar chart PNG）全 log MLflow。 |
| 晉升閘門（自動 → `@staging`） | 三條全過：①ROC-AUC ≥ **0.65**（絕對地板）②ROC-AUC ≥ LogisticRegression baseline（相對地板）③若 `@prod` 存在：ROC-AUC ≥ prod 模型在**同一 test 窗**重評分數 − 0.02（防退步；prod 重評由 train.py 順帶做）。過閘 → `mlflow.register_model` + `set_registered_model_alias("video-predictor", "staging", v)`；不過 → run 標 `gate: failed`，Prometheus 事件（§7）。 |
| `@prod` 晉升 | **人工**：`make promote-model MODEL=video-predictor VERSION=n`（§7 晉升流程，GitOps 純度考量）。 |
| MLflow log 面 | params（全超參+資料集路徑+git sha）/ metrics（上表）/ artifacts（model、feature_schema.json、**訓練集特徵分佈參考直方圖 `reference_stats.json`**——§7 drift 的比較基準、混淆矩陣/重要性圖）/ `mlflow.models.infer_signature` 簽名。 |

---

## 6. P2a-3 KServe serving（決定）

| 開放問題 | 決定 |
|---|---|
| serving runtime | **KServe 內建 `modelFormat: mlflow` + `protocolVersion: v2`**（MLServer mlflow runtime，context7 驗證過的官方形狀）。淘汰自訂 predictor image（要自維護 HTTP 層）與 sklearn runtime（吃 joblib 裸檔，丟失 MLflow 模型格式的簽名/依賴宣告）。 |
| 模型怎麼進 KServe | **穩定路徑 + 版本目錄**：晉升時把 MLflow model artifact 複製到 `s3://ml-models/video-predictor/v<N>/`（MLflow proxy 下真實 artifact 路徑不穩定、且 KServe 不解析 `models:/` URI——複製到我方控制的決定性路徑是解耦點）；InferenceService `storageUri` 指該版本目錄。 |
| 由誰更新 | **ArgoCD 宣告式**：`storageUri` 寫在 `ml/kserve/video-predictor.yaml`（git），晉升腳本 yq bump → commit → ArgoCD sync → KServe 滾動。與 P0「CI bump kustomization tag」同構，模型版本 = git 歷史可回溯。 |
| 前處理在哪 | **烤進 sklearn Pipeline**（§5）——v2 inference protocol 直接吃數值特徵向量。特徵組裝（SQL→向量）屬呼叫端（批次打分 job / demo 腳本），用同一 `features.py`。不用 KServe transformer（多一個 pod，YAGNI）。 |

**InferenceService manifest 形狀**（`ml/kserve/video-predictor.yaml`）：

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: video-predictor
  namespace: ml
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  predictor:
    serviceAccountName: kserve-s3-sa          # 綁 kserve-s3 Secret（§3.5）
    minReplicas: 1
    model:
      modelFormat: {name: mlflow}
      protocolVersion: v2
      storageUri: s3://ml-models/video-predictor/v1/   # ★ promote 腳本 yq bump 的唯一落點
      resources:
        requests: {cpu: "100m", memory: "512Mi"}
        limits:   {cpu: "1",    memory: "1Gi"}
```

**批次打分（P4 合約的 tabular 半邊）**：DAG `ml_score_hourly`（`"35 * * * *"`，錯開 P1 主 DAG）：KPO 跑 `ml_tabular.score`——選 `first_seen_at ≤ now−3h` 且未打分的 `(video_id, region)` → 組 τ 窗特徵 → **直接從 MLflow `models:/video-predictor@prod` 載入模型打分**（批次走 in-process，不繞 HTTP——KServe 端點是線上 demo 面，批次打 HTTP 是自找延遲）→ UPSERT：

`ml.ml_video_predictions`：`video_id text, region text, first_seen_at timestamptz, features_at timestamptz, p_doubled_24h double precision, predicted_label boolean, model_version text, scored_at timestamptz`，PK `(video_id, region)`（一影片一次打分，τ 時點定格——可回測）。

---

## 7. P2a-4 drift 監控 + 自動重訓（決定）

| 開放問題 | 決定 |
|---|---|
| drift 怎麼算 | **PSI 為主、KS 為輔，外加真實品質回算**。`ml_tabular.drift`（自寫 ~80 行 + scipy KS；淘汰 evidently——為 3 個指標拖一整套框架違工具紀律）：①**特徵 PSI**：近 7 天打分母體的每個數值特徵分佈 vs 訓練參考 `reference_stats.json`（10-bin，等寬邊界凍結在參考裡）②**預測分佈**：`p_doubled_24h` 均值/正類率 7 天窗位移 ③**品質回算（本設計的差異化）**：label 24h 即成熟 → 每天把「已滿 24h 的預測」對回真實 `doubled_in_24h`，算 **rolling 7d ROC-AUC 與正類召回**——不只監控輸入漂移，直接監控真實效能衰退。 |
| 排程 | DAG `ml_drift_daily`（`@daily`）：KPO 算指標 → 寫 `ml.ml_drift_metrics(metric_date date, model text, metric text, feature text NULL, value double precision, PK(metric_date,model,metric,coalesce(feature,'')))` → 末端 BranchPythonOperator 依觸發條件 `TriggerDagRunOperator(ml_retrain)`。 |
| 指標怎麼進 Prometheus | **postgres-exporter 自訂查詢**（P1 §9 既有姿態，零新 exporter）：`ml_feature_psi{model,feature}`、`ml_rolling_auc{model}`、`ml_prediction_pos_rate{model}`、`ml_staging_candidate{model}`。staging candidate 的資料源：`train_and_gate` 過閘時寫一列 `metric='staging_candidate'` 進 `ml.ml_drift_metrics`（exporter 單 DSN 只對 lakehouse db，讀不到 mlflow db 的 alias 表——狀態由生產者落地到 lakehouse 側）。PrometheusRule：`MLFeatureDriftHigh`（≥2 特徵 PSI>0.2，warn）、`MLModelQualityDegraded`（rolling_auc<0.60，critical）、`MLStagingCandidateReady`（info——提示人工晉升）。 |
| 重訓觸發全自動 or 人工閘 | **偵測→重訓→評估→掛 `@staging` 全自動；`@prod` 晉升人工**。理由：(a) GitOps 純度——KServe rollout 走 git bump，pod 自動 commit git 是反模式；(b) portfolio 同時展示「自動閉環管線」與「生產安全的人工晉升閘」兩個成熟敘事，比全自動更資深。觸發條件：`(PSI>0.2 的特徵數 ≥ 2) OR (rolling_auc < 0.60)`；`ml_retrain` 另供手動觸發（`schedule=None` 亦可由 drift 觸發）。 |
| `ml_retrain` DAG 結構 | `export_dataset`（KPO → s3://ml-datasets 快照）→ `train_and_gate`（KPO：§5 訓練+閘門+掛 staging）→ `notify`（過閘與否都寫 metrics；不自動動 prod）。 |
| 晉升流程（人工步的全貌） | `make promote-model MODEL=video-predictor VERSION=n`：①跑 smoke 重評（test 窗分數印給人看）②`set_registered_model_alias(…, "prod", n)` ③mc 複製 artifact → `s3://ml-models/video-predictor/v<n>/` ④yq bump `storageUri` + git commit/push → ArgoCD 滾動 KServe。單一腳本四步，冪等可重跑。 |
| drift demo 怎麼構造 | 不造假資料。兩條真路徑：①趨勢母體自然週期性位移（entertainment/音樂榜單季節性——PSI 真的會動）②**演示旋鈕**：打分側支援 `--regions` 參數，臨時把打分母體限縮到單一 region（如只 JP）→ 特徵分佈立即位移 → 告警/重訓全鏈路現場可演。README 註明後者是演示手段非生產行為。 |

---

## 8. P2b-1 RAG 語料索引 + pgvector（決定）

### 8.1 Embedding 模型與跑法

| 開放問題 | 決定 |
|---|---|
| 模型 | **`intfloat/multilingual-e5-small`**（384 維，118M 參數，100+ 語言）。理由：留言 8 區中英日韓混雜 → 多語必要；384 維 × 百萬列 = ~1.5GB 向量 + HNSW 索引，單顆 Postgres 舒服；小模型讓「k8s CPU 跑增量」成立（§1④ 界線的前提）。淘汰：`bge-m3`（1024 維×2.2GB 模型，backfill 慢 3–4×，維度膨脹 2.7×，demo 語料下檢索增益不值）；Gemini embedding API（🔒已鎖定本地，百萬列打外部 API 違成本與速率現實）。**e5 前綴慣例**：索引側 `passage: <text>`、查詢側 `query: <text>`（封裝進 `embed.py`，呼叫端不可能忘）。**（2026-07-08 複查：小型多語 embedding 無非換不可的新選手，維持本選型；換模型只需走 `embedding_model` 欄全量重嵌，無鎖定成本。）** |
| 跑法 | **雙模式同套件 `ml_rag_index`**（§1④）：初始 backfill = host M4 MPS（`make embed-backfill`，batch 256）；日增量 = Airflow KPO CPU（`--incremental`：`WHERE NOT EXISTS (SELECT 1 FROM ml.rag_documents …)`）。device 偵測 `mps→cuda→cpu` 自動（同 code 可攜雲 GPU，M4 原則的可攜性故事）。 |
| 語料版本化 | 索引表自帶 `embedding_model` 欄（換模型 = 全量重嵌，靠欄位隔離新舊）；不納 DVC（活表非快照；RAG eval 用的 frozen 快照才進 DVC，§10）。 |

### 8.2 語料構成與向量庫 schema

| 項目 | 決定 |
|---|---|
| 主語料 | `silver_youtube_comments`（Postgres serving 副本；§2 seam）——**一則留言 = 一個 doc，不 chunk**（留言中位數 <200 字元，chunk 1000/200 是長文設定，對留言純屬儀式；超長截 512 token 由 embedder 自然處理）。過濾：`length(text) ≥ 5` 且非純 URL/emoji（清洗規則在 `corpus.py`，可測）。 |
| 輔語料 | `gold_video_lifecycle` 的 `title+description+tags` 合成 `video_meta` doc——**chunk 800 字元 / overlap 100**（description 可達數千字元）。 |
| 表 schema | `ml.rag_documents`：`doc_id bigserial PK`、`doc_type text CHECK IN ('comment','video_meta')`、`source_id text`（comment_id 或 `video_id#chunk_n`）、`video_id text`、`region text`、`content text`、`meta jsonb`（like_count/published_at/title…）、`embedding vector(384) NOT NULL`、`tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED`、`embedding_model text`、`indexed_at timestamptz`；`UNIQUE(doc_type, source_id, embedding_model)` = 冪等鍵。 |
| 索引 | `CREATE INDEX … USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);` + `GIN(tsv)` + btree`(video_id)`。HNSW（非 IVFFlat）：增量寫入不需重 train、召回穩定，百萬列建索引記憶體 ~2GB 可承受。 |
| 排程 | DAG `ml_embed_incremental`（`@daily`，排留言 ingest DAG 之後 1h；冪等鍵保證重跑不膨脹）。原碼 `index_youtube_data()` 從沒被呼叫的缺陷，在此以「DAG 排程 + 驗收清單斷言列數>0」雙重補上。 |

---

## 9. P2b-2 LangGraph agentic CRAG pipeline（決定）

### 圖結構（收斂拍板；LangGraph 1.2.8 `StateGraph` + `add_conditional_edges`，context7 驗過 v1 API 面）

```
START → retrieve → grade ──(relevant_ratio ≥ 0.4 且 relevant ≥ 2)──→ generate → END
                     │
                     ├─(不足 且 retries < 1)→ rewrite → retrieve   （回圈，上限 1 次改寫）
                     │
                     └─(不足 且 retries ≥ 1)→ degraded_answer → END
```

| 節點 | 行為 |
|---|---|
| `retrieve` | **hybrid**：①pgvector cosine top-40（e5 `query:` 前綴）②FTS `plainto_tsquery('simple', q)` top-40 → **RRF 融合（k=60）** 取 top-8。可選 filter：`video_id`/`region`（API 參數透傳 WHERE）。自寫 SQL（psycopg + pgvector-python），淘汰 langchain-postgres vectorstore 抽象——hybrid RRF 本就要自訂 SQL，抽象層反而礙事。**CJK 誠實註記**：`simple` config 不分詞中文，關鍵字通道對 zh 弱 → 由多語向量通道補（e5 對 zh 強）；`pg_trgm` 已裝備援，README 記 known-limit。 |
| `grade` | CRAG 自評：**一次呼叫**批量評 8 篇（structured output：`[{doc_id, relevant: bool}]`），prompt = `prompts:/rag-grade@prod`。**取代原碼 LLM-as-judge 逐筆 rerank**（8 次呼叫 → 1 次；且 grade 產出直接驅動 CRAG 分支，一石二鳥）。淘汰 cross-encoder rerank（再養一個模型，收益不成比例）。 |
| `rewrite` | 查詢改寫（`prompts:/rag-rewrite@prod`），`retries += 1`，回 `retrieve`。上限 1 次（demo 語料下二次改寫邊際收益趨零，且限界保 p99 延遲）。 |
| `generate` | `prompts:/rag-answer@prod`（帶 grounding 指示：只依 context 作答、引 doc_id、不足就明說）→ 產出 answer + sources。 |
| `degraded_answer` | 兩次檢索仍 <2 相關 → **誠實降級**：回「語料不足以回答」+ 已找到的最佳線索，`degraded=true`。不硬答（反幻覺紀律）。 |

**State**（TypedDict）：`question, question_rewritten, video_id?, region?, docs, graded, relevant_ratio, retries, answer, sources, provider, degraded, token_usage, timings`。

### 生成 LLM 切換與 host Ollama 接線（M4 原則落地點，畫清）

| 項目 | 決定 |
|---|---|
| 預設/後備 | 預設 **Ollama `qwen3.5:9b`**（host 原生，多語含 zh 強、q4 ~7GB RAM、**262K context** 對 RAG 塞檢索結果有利、M4 22–28 tok/s；升自原 `qwen3:8b`）；fallback **Gemini `gemini-2.5-flash`**（`langchain-google-genai`，key 從 `gemini-api` Secret env）。切換：①自動——Ollama 連線錯誤/逾時 30s → 當次 request 改走 Gemini（`provider` 欄如實回報）②手動 A-B——API 參數 `provider: ollama\|gemini` 強制指定。`grade`/`rewrite`/`generate` 三節點共用同一 provider 決策（一次請求一個 provider，A-B 對照才乾淨）。 |
| **k8s→host 接線** | `ml` ns 建 **ExternalName Service**：`ollama-host.ml.svc` → `host.docker.internal`；RAG 服務 env `OLLAMA_BASE_URL=http://ollama-host.ml.svc:11434`。原理：kind node 是 Docker Desktop 容器，pod 的 DNS 經 CoreDNS forward 到 node resolv.conf 指向 Docker 內嵌 DNS，`host.docker.internal` 由 Docker Desktop 解析並轉發到 host loopback。**接線抽象點**：只有這一個 Service + 一個 env——換雲（Ollama 跑 GPU 節點）= 改 Service 定義，服務程式碼零改動。若 pod 內解析失敗（環境差異），fallback 手法 = Service+手寫 EndpointSlice 指 host gateway IP（§15 實查 2 一次煙囪驗證定案）。host 側 `OLLAMA_HOST=0.0.0.0` 於 `make ml-host-setup` 寫明。 |
| 服務形狀 | FastAPI（`ml/rag/service/`，k8s Deployment 1 replica，ingress `rag.localtest.me`）。API：`POST /ask {question, video_id?, region?, provider?, top_k?=8}` → `{answer, sources[{doc_id,doc_type,video_id,excerpt}], provider, degraded, token_usage{prompt,completion}, latency_ms, prompt_versions}`；`GET /healthz`（含 pgvector 連線 + Ollama 可達性子檢查）；`GET /metrics`。 |
| 對外用途定義（P4 展示什麼） | 兩個 grounded 場景：①「這支影片的觀眾在討論什麼／情緒傾向？」（留言 doc 為主）②「這區最近爆紅內容有什麼共同點？」（video_meta doc 為主）。**皆預先批次產生寫 `ml.ml_rag_showcase`**（§10）；線上 API 是本地 demo 面（§1⑤ 拓撲約束）。標題生成**不走 RAG**（那是 P2c-B 的微調模型職責，邊界不糊）。 |

---

## 10. P2b-3 LLMOps observability（決定；原碼三大缺口的工程層補齊）

| 開放問題 | 決定 |
|---|---|
| prompt 版本 | **MLflow Prompt Registry**（§1② 已拍板一工具兩用）。runtime 以 `@prod` alias 載入（cache TTL 60s）；每次回應附 `prompt_versions`（可追溯）。變更流程：`register_prompt` 新版 → **過 eval 閘**（下）→ `set_prompt_alias(…, "prod", v)`——閘門由 `make rag-promote-prompt NAME=rag-answer VERSION=n` 腳本強制（先跑 eval、分數達標才掛 alias，不達標拒絕）。 |
| eval set 怎麼建 | `ml/rag/eval/evalset.yaml`（git 版本化）：**30 題**（zh 12 / en 12 / 混合 6；每題含 `question`、`filter`、`expected_source_ids`（人工標的黃金 doc，對 frozen 語料快照）與/或 `must_mention` 關鍵字）。frozen 語料快照（`rag_documents` 匯出 parquet）進 DVC——eval 可重現不受活表漂移影響。 |
| eval 指標與閘門 | ①**檢索命中率**：`hit_rate@8 ≥ 0.70`（expected_source 落在 top-8）②**答案品質**：LLM-as-judge = Gemini flash（temperature 0，rubric prompt 版本化進 Prompt Registry）評 faithfulness（1–5，grounded 於 sources）與 relevance（1–5），閘門 `faithfulness_avg ≥ 3.5 AND relevance_avg ≥ 3.5` ③降級率 ≤ 20%。全部 log MLflow experiment `rag_eval`（params=prompt versions+檢索參數；一次 eval = 一個 run，A-B 對照 = 兩個 run 並排）。`make rag-eval` host 跑（需活服務+Ollama）。 |
| 成本/token/延遲採集 | RAG 服務內 `prometheus-client`（middleware + graph 節點計時）：`rag_requests_total{provider,outcome=ok\|degraded\|error}`、`rag_request_duration_seconds`（histogram，含 per-node timings label `stage=retrieve\|grade\|generate`）、`rag_tokens_total{provider,kind=prompt\|completion}`（Ollama 回應的 `eval_count`/`prompt_eval_count`；Gemini 的 usage_metadata）、`rag_cost_usd_total{provider}`（單價常數表：ollama=0、gemini=官方牌價，`llm.py` 內常數含出處註解）、`rag_relevant_ratio`（histogram）。ServiceMonitor 進 `ml-monitoring`。 |
| API key | k8s Secret `gemini-api` → env（§3.5）；程式 `os.environ["GEMINI_API_KEY"]` **無預設值**（缺就 fail-fast）——原碼 `gemini_client.py:37` 硬編碼預設值反例的直接矯正，並有測試斷言（§14）。 |

**showcase 批次**：`make gen-rag-showcase`（host 跑，走完整 graph）：evalset 題目 + 每區 top 影片各一題自動生成 → 寫 `ml.ml_rag_showcase(id bigserial PK, question text, answer text, sources jsonb, provider text, degraded boolean, token_usage jsonb, latency_ms int, generated_at timestamptz)`——P4 匯出的 RAG 半邊。

---

## 11. P2c-A 留言情緒分類器（DistilBERT 蒸餾，決定）

| 開放問題 | 決定 |
|---|---|
| label 體系 | **3 類：`positive / neutral / negative`**。淘汰加第 4 類「無關/廣告」：弱標註者對「無關」的判準一致性最差（噪音源）、下游儀表板只消費情緒比例、spam 過濾是獨立關切（不該塞進情緒模型）。 |
| 弱標註規模與流程 | **train 5,000 / val 500 / test 500**（分層抽樣：region 均勻 × like_count 分層，抽樣 SQL 固定 seed）。標註者 = **Gemini 2.5 Flash**（structured output，prompt=`prompts:/sentiment-weak-label@prod`，batch 20 則/呼叫；~300 次呼叫，成本零頭）。**test 集雙標**：Flash + Gemini 2.5 Pro 各標一次，**只保留一致樣本**（預期 ~85% 留存，report Cohen's κ）→ test 是「乾淨標籤」，蒸餾品質的量尺才可信。Ollama qwen3.5:9b 為離線備援標註者（零成本路徑，README 記）。資料集 jsonl 進 DVC。 |
| 基座與訓練 | **`distilbert-base-multilingual-cased`**（134M；留言多語，英文版 distilbert 直接淘汰）+ `DistilBertForSequenceClassification(num_labels=3)`。transformers **Trainer**：3 epochs、lr 5e-5、batch 32、max_len 256、weighted CE（處理類別不平衡）。**跑法 = M4 host MPS**（`make train-sentiment`，5.5k 樣本 <15 分鐘；同 code `--device cpu` 可進 k8s，界線表 §1④）。MLflow：experiment `sentiment_distilbert`，log params/per-epoch metrics/最終 test 指標/`transformers` flavor model。 |
| 蒸餾品質驗證（賣點數字） | test（乾淨標籤）上報 **accuracy + macro-F1**；閘門 **macro-F1 ≥ 0.70** 才 `register_model("comment-sentiment")` + `@staging`。**成本/延遲對照表**（README + MLflow artifact，實測填數不宣稱）：「Gemini Flash 標 100 萬則」的 token 成本與吞吐 vs 「DistilBERT k8s CPU pod 批次打分」的耗時與成本（=0）——蒸餾 pattern 的核心敘事以實測數字呈現。 |
| serving | KServe **`modelFormat: huggingface`**（huggingfaceserver runtime，CPU）`args: [--model_name=sentiment, --task=sequence_classification]`；`storageUri: s3://ml-models/comment-sentiment/v<N>/`；資源 requests 500m/1Gi、limits 1/2Gi；晉升同 §7 流程（alias + yq bump）。線上端點 = demo 面。（runtime task 旗標名 §15 實查 4。） |
| 批次打分 | DAG `ml_sentiment_daily`（`@daily`，排 embed DAG 後）：KPO 直載 `models:/comment-sentiment@prod`（in-process，同 §6 批次不繞 HTTP 的理由）→ 打當日新留言 → UPSERT。歷史百萬列 backfill = host `make sentiment-backfill`（MPS）。 |
| 打分表 schema | `ml.ml_comment_sentiment`：`comment_id text PK, video_id text, region text, label text CHECK IN('positive','neutral','negative'), confidence double precision, model_version text, scored_at timestamptz`。 |
| 影片級聚合 | **dbt mart `gold.gold_video_sentiment`**（dbt 新增 source `ml` schema——additive）：粒度 `(video_id, region)`：`scored_comments bigint, pos_ratio, neu_ratio, neg_ratio numeric, sentiment_score numeric(=pos_ratio−neg_ratio), top_liked_negative_comment_id text, updated_at`。DQ：ratio 三欄和 = 1（±0.001）、`comment_id` relationships 到 silver 留言表（warn）。 |

---

## 12. P2c-B 爆紅標題生成器（小 LLM PEFT LoRA，決定）

| 開放問題 | 決定 |
|---|---|
| 基座 | **`Qwen/Qwen3.5-2B`**（2026-02 Qwen3.5 小模型家族的 **dense** 變體，直系接替原 Qwen3-1.7B）。理由：fp16/bf16 權重 ~4GB + LoRA 啟用值 → 16GB 級 M4 舒適；**201 語言**（zh/en/ja/ko 榜單標題更穩）；dense 架構（非 MoE → 避開 Qwen3.5 MoE 變體與 PEFT/transformers 5.x fused-expert 的已知不相容）；`unsloth/Qwen3.5-2B-Base` 已出 → llama.cpp/GGUF 出口鏈證實可用。淘汰：**Qwen3.5-4B**（fp16 ~8GB + activation，16GB M4 訓練偏緊且慢——非否決，列為「有更大 M4／雲 GPU 就升」的延伸選項）；**前沿大模型 DeepSeek V4 / GLM-5.1（744B）/ Kimi K2.6 / MiniMax M3**（資料中心級 MoE，16GB M4 跑不動、且違 M4 原生微調原則——它們只在「換掉 Gemini API fallback」那條成本軸才有意義，與本地基座無關）；Llama-3.x 小尺寸（zh 弱於 Qwen）；Phi 小模型（zh 弱、社群 GGUF 生態較窄）。**fp16/bf16 全程，不碰 bitsandbytes**（🔒 CUDA-only；且 Qwen3.5 官方明示 QLoRA 4-bit 量化誤差偏高、不論 MoE/dense 皆不建議——與本決策同向）。 |
| 訓練資料構造 | 正例定義（「爆紅」門檻）：`gold_video_lifecycle` 中 **`doubled_in_24h = true`（§4 label 復用）OR `peak_delta_views_per_hour ≥ 該 region P75`**，標題去重（同影片跨區取一），目標 **≥ 1,500 pairs**（8 區 × 每日 top50 × 數週累積，含門檻過濾後的現實估計；不足則放寬到 P60 並記錄）。**instruction 反向構造**（backtranslation pattern）：Gemini Flash 從每個標題抽 `{topic, keywords[]}`（prompt=`prompts:/title-topic-extract@prod`）→ 樣本 = chat 格式：system（「你是爆紅標題寫手…」）/ user（`主題:{topic}\n關鍵字:{keywords}\n地區:{region}\n類別:{category_name}`）/ assistant（真實標題）。jsonl 進 DVC；10% 留 held-out。 |
| LoRA 超參 | PEFT `LoraConfig`：**r=16, lora_alpha=32, lora_dropout=0.05, target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]**（Qwen3.5-2B 為 dense、投影層沿用 Qwen 家族命名 → 此列表適用；plan 前以實際 `named_modules()` 確認一次，或退用 Unsloth `target_modules="all-linear"` 自動涵蓋。r=16 對 2B 是充足容量）；訓練 **TRL `SFTTrainer`**（completion-only loss——只對 assistant 段算 loss，validated library 不手刻 mask）：lr 2e-4 cosine、3 epochs、per_device_batch 2 × grad_accum 8（等效 16）、max_len 512、fp16 on MPS。`make train-lora`（host）。MLflow：experiment `title_lora`，log 超參/loss 曲線/adapter artifact（數十 MB）。 |
| 效果展示與評估（不造假紀律） | **對照式 LLM-judge win-rate**：held-out 20 主題 × (微調後 vs 未微調基座) 各生 3 標題 → Gemini judge 盲評「哪組更像該區爆紅標題」（rubric 版本化）→ report **win-rate**（目標 ≥60%，未達照實 report）+ 人工目視樣本表進 MLflow artifact。**明標「可示範能力」，絕不宣稱 CTR/成效**（拿不出線上實驗就不說）。 |
| 產出與 serving | `merge_and_unload()` 合併 → HF 標準格式 → MLflow registry `title-gen`（可攜雲端 GPU 的正本）→ `convert_hf_to_gguf.py`（llama.cpp，f16）→ `ollama create title-gen -f Modelfile`（host；Modelfile 含 chat template + system prompt）。**線上生成只在 host Ollama = 本地 demo**；對 P4 一律預產。 |
| 對 P4 | `make gen-title-showcase`：30 個主題（近期各區熱門 topic 抽樣）× tuned/base 兩組 → 寫 **`ml.ml_title_examples`**：`id bigserial PK, topic text, keywords jsonb, region text, category text, generated_title text, model text CHECK IN('title-gen','base'), model_version text, generated_at timestamptz`（含 base 對照組——P4 可做 before/after 並排展示）。 |

---

## 13. P2-X 對 P4 輸出合約 + 監控整合（橫跨三條）

### P4 匯出合約（ML 半邊；全部 = Postgres 表，P4 匯出 DAG 統一收）

| 產出 | 表 | 粒度 | 生產者 |
|---|---|---|---|
| 影片爆紅預測 | `ml.ml_video_predictions` | (video_id, region) | `ml_score_hourly`（hourly） |
| 留言情緒（明細） | `ml.ml_comment_sentiment` | comment_id | `ml_sentiment_daily` |
| 影片情緒聚合 | `gold.gold_video_sentiment`（dbt mart） | (video_id, region) | dbt run（掛既有 dbt DAG 尾） |
| RAG 問答範例 | `ml.ml_rag_showcase` | 題 | `make gen-rag-showcase`（人工觸發批次） |
| 爆紅標題範例（含 base 對照） | `ml.ml_title_examples` | 主題×模型 | `make gen-title-showcase`（人工觸發批次） |

**穩定性政策**（同 P1 §6a）：表名/粒度鍵/既列欄位是對 P4 的介面承諾，變更只允許 additive。線上端點（KServe ×2、RAG API）**明文排除在合約外**（§1⑤）。

### Airflow DAG 總表（P2 新增 5 條；排程器仍只 Airflow）

| DAG | schedule | 任務鏈 |
|---|---|---|
| `ml_score_hourly` | `35 * * * *` | KPO score（§6） |
| `ml_embed_incremental` | `@daily`（留言 ingest 後） | KPO embed（§8） |
| `ml_sentiment_daily` | `@daily`（embed 後） | KPO score_sentiment（§11） |
| `ml_drift_daily` | `@daily` | KPO drift → branch → trigger retrain（§7） |
| `ml_retrain` | None（drift 觸發/手動） | export → train_and_gate → notify（§7） |

（host 側 make targets 不在 Airflow 內——M4 界線表 §1④ 的誠實邊界：**排程自動化的都在 k8s；host 重算力步是人工觸發的離線工序**，README 架構誠實章記錄。）

### Grafana dashboards ×3 + 告警（`platform/monitoring/ml/`，ConfigMap sidecar 慣例）

1. **ml-lifecycle**：特徵 PSI 熱圖、rolling AUC、預測正類率、staging candidate 提示、各 `ml_*` 表列數/新鮮度（postgres-exporter 自訂查詢擴充：`ml_table_rows{table}`、`ml_scored_freshness_seconds`）。
2. **llmops**：RAG QPS/延遲（分 stage）、token 用量、`rag_cost_usd_total`、降級率、provider 分佈、relevant_ratio 分佈。
3. **ml-serving**：KServe predictor pod up/重啟、`kube_pod_container_*`（kube-state-metrics 既有）＋ MLServer/huggingfaceserver `/metrics`（PodMonitor，§15 實查 4 確認指標名）。

PrometheusRule：§7 三條 + `RAGDegradedRateHigh`（degraded/total 1h > 0.3，warn）+ `MLServingDown`（predictor up==0，critical）+ `RAGCostBudget`（gemini 日成本 > $1，warn——成本護欄）。

---

## 14. CI / 測試策略（沿用 P0/P1 模式不自創）

| workflow | 觸發 paths | test | image | tag bump 落點 |
|---|---|---|---|---|
| `ml-batch-ci.yaml` | `ml/{batch,tabular,rag/indexer,finetune}/**` | ruff + pytest（三套件） | `…/ml-batch` | `orchestration/airflow/dags/config/images.yaml` 加 `ml_batch.tag`（P1 既有檔，git-sync 送達） |
| `rag-service-ci.yaml` | `ml/rag/service/**`（不含 k8s/） | ruff + pytest | `…/rag-service` | `ml/rag/service/k8s/kustomization.yaml` `images.newTag`（P0 hello 同款） |
| `mlflow-ci.yaml` | `ml/mlflow/Dockerfile` | `docker build` 成功即過（無 app 碼） | `…/mlflow` | `ml/mlflow/k8s/kustomization.yaml` |

pr-checks 擴充同 P1。迴圈防護（paths 不含 bump 落點 + `[skip ci]`）照抄。

**單元測試面（每步可測）**：`features.py` 黃金樣本測試（固定輸入→固定向量+schema 斷言）；label SQL 對 fixture 資料庫斷言（含「窗口缺失剔除」「τ 洩漏防護」案例）；PSI 函式數值測試；`corpus.py` 清洗規則；RRF 融合純函式測試；**LangGraph 圖測試**（fake LLM + fake retriever 注入，斷言：relevant 路徑、rewrite 迴圈上限、degraded 誠實降級、provider fallback）；prompt 格式化測試；**secret 紀律測試**（斷言 `llm.py`/settings 對缺失 env 是 raise 而非預設值——原碼反例的守門）；weak-label 解析與雙標一致性過濾測試；LoRA dataset builder chat 格式測試。**runtime 煙囪**（`make ml-verify`）見 §15。

---

## 15. 端到端驗收清單 + plan 前需實查

### A. `make ml-verify`（`scripts/verify-ml.sh`；前置 = P1 `make pipeline-verify` 綠 + `make ml-secrets` + Gold/留言有數日資料）

| # | 檢查 | 預期 |
|---|---|---|
| 1 | ArgoCD 8 個新 app 收斂 | 全 `Synced+Healthy` |
| 2 | pgvector/ml schema | `SELECT extversion FROM pg_extension WHERE extname='vector'` = 0.8.4；`ml` schema 存在 |
| 3 | MLflow 活著 | `curl mlflow.localtest.me/api/2.0/mlflow/experiments/search` 200 |
| 4 | 訓練閉環（tabular） | 觸發 `ml_retrain` → MLflow 出現 run + `video-predictor@staging` 存在 |
| 5 | 晉升 + serving | `make promote-model …` → InferenceService Ready → v2 endpoint `curl …/v2/models/video-predictor/infer` 200 且回機率 |
| 6 | 批次打分 | `ml.ml_video_predictions` 列數 >0 且冪等（重跑不膨脹） |
| 7 | RAG 索引非空 | `SELECT count(*) FROM ml.rag_documents` >0；HNSW 索引存在 |
| 8 | RAG 問答 | `POST rag.localtest.me/ask` → 非空 answer + sources；殺 Ollama 再問 → `provider=gemini`（fallback 實證）；問無關題 → `degraded=true`（誠實降級實證） |
| 9 | RAG eval | `make rag-eval` → hit_rate ≥0.7、faithfulness ≥3.5，MLflow `rag_eval` 有 run |
| 10 | LLMOps 指標 | Prometheus 查得 `rag_tokens_total`、`rag_cost_usd_total` |
| 11 | 情緒閉環 | train→gate→打分：`ml.ml_comment_sentiment` >0；`gold.gold_video_sentiment` ratio 和=1 |
| 12 | LoRA 產物 | MLflow `title-gen` 有 adapter artifact；`ollama run title-gen "主題:…"` 出標題；`ml.ml_title_examples` 有 tuned+base 兩組 |
| 13 | drift 指標 | `ml_feature_psi` 有值；`--regions JP` 演示旋鈕跑一輪後 PSI 上升可見 |
| 14 | 去憑證紀律 | `grep -rE "AIza|GEMINI_API_KEY *= *[\"']" ml/` 為空（無硬編碼 key） |

### B. plan 前需實查（設計已收斂，以下為落地校準點）

1. **KServe v0.19.0 Helm chart 確切名與 values 路徑**（docs 舊版示例為 `kserve-crd`+`kserve-resources`；GHCR tags list 需 token，plan 時 `helm show values oci://ghcr.io/kserve/charts/…` 校準 deploymentMode/ingress config 的 key）。
2. **kind pod → `host.docker.internal` 可達性煙囪**（§9 接線；不通則 EndpointSlice 指 host gateway IP 備案，5 分鐘實證）。
3. **transformers 5.13.0 × PEFT 0.19.1 × TRL 1.7.1 相容矩陣**與 MPS fp16 訓練實跑（transformers 5.x 是新 major，`uv pip compile` 定 lock；SFTTrainer API 面以 lock 版本文件為準）。
4. **huggingfaceserver（KServe 0.19）sequence-classification task 旗標名與 /metrics 指標名**（§11 serving args、§13 PodMonitor 的 PromQL 以 runtime 實測為準）。
5. **MLServer mlflow runtime 對 sklearn Pipeline(ColumnTransformer) 的 v2 payload 形狀**（infer 請求欄位序 = feature_schema.json 序，落地煙囪一次）。
6. **`pgvector/pgvector:0.8.4-pg16` 對既有 PVC 的滾動**（同 major 應 drop-in，落地驗一次 + `CREATE EXTENSION`）。
7. **Qwen3.5-2B → GGUF 轉換鏈 + LoRA target_modules 確認**（`unsloth/Qwen3.5-2B-Base` 已有 GGUF 前例佐證支援；仍實跑一次 `convert_hf_to_gguf.py` 對 merged LoRA 輸出，並以 `named_modules()` 確認 dense 投影層命名與 §12 超參一致）。
8. **`silver_youtube_comments` 最終表名/欄名**（留言增補 design 並行產出；本檔引用點集中 §8.2 與 §11 抽樣 SQL，對齊成本 = 兩處）。
9. Ollama `qwen3.5:9b` 在目標 M4 記憶體下的實際吞吐（~7GB q4；影響 grade+generate p95；過慢則降 `qwen3.5:4b`，決策點寫進 plan）。

---

## 16. 落地後校驗（design 自檢摘要）

- brief 全部開放問題收斂為決定，無 TBD/兩案並陳：預測目標/label（§4 binary doubled_in_24h + τ=3h 防洩漏）、duration（additive 加欄）、訓練跑法（KPO+host 雙路）、split（時序 hold-out）、閘門（三條件）、serving（mlflow modelFormat v2 + 穩定路徑 + GitOps bump）、前處理（烤進 pipeline）、drift（PSI+KS+品質回算；staging 自動/prod 人工）、embedding（multilingual-e5-small，backfill host MPS/增量 k8s CPU）、向量庫 schema（§8.2 HNSW）、CRAG 圖（§9 retrieve→grade→(rewrite×1)→generate/degraded）、rerank（batched grade 取代 LLM-as-judge 逐筆）、Ollama 接線（ExternalName→host.docker.internal）、prompt registry（MLflow 兼任）、eval set/閘門（30 題+hit_rate/faithfulness 閾值）、成本採集（Prometheus 四指標族）、情緒 label（3 類）、弱標註（5k/500/500 雙標 test）、LoRA 基座（Qwen3.5-2B dense）與超參（r16/α32/全投影）、GGUF→Ollama 出口、P4 匯出（五表合約、線上端點明文排除）。
- 硬約束對照：①M4 界線總表 §1④ 逐工作標明 host/k8s + 唯一 k8s→host 接線 §9 ②拓撲硬約束正面處理 §1⑤/§13（P4 = 預產表，端點排除在合約外）③消費 Gold/Silver 不繞道，缺欄 additive 清單 §2 ④backing store 全複用 P1 Postgres+MinIO（新 db/schema/bucket，零新服務）⑤一個工作一個工具（排程只 Airflow §13、DB 只 Postgres 含 pgvector、監控只 Prom+Grafana、模型與 prompt 追蹤只 MLflow、agent 框架只 LangGraph、無 Kafka/串流）⑥安全：零硬編碼 key + fail-fast 測試守門 §10/§14/§15A14 ⑦每步可測 §14/§15 ⑧進化非複刻：真 label 取代查表、registry 取代零持久化、真 ingest 取代空索引、LLMOps 監控從零到全、時序題取代靜態回歸——取材 vs 重造界線在各簇註明。
- 部署形狀：8 個子 Application + wave 7–11 接續 P1（§2）；InferenceService manifest 形狀 §6；CI 三支複製既有模式 §14。
