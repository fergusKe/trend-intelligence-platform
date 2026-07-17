# P1 資料管線 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0 平台底座上建起端到端 YouTube 趨勢資料管線：Airflow（KubernetesExecutor）每小時抓 8 區 trending → MinIO Bronze（原始 JSON）→ spark-operator SparkApplication 轉 Iceberg Silver → pyiceberg loader UPSERT Postgres serving 副本 → dbt 產 Gold 5 marts（P2 資料合約）→ dbt test DQ gate → postgres-exporter/statsd 指標 + Grafana 兩個 dashboard，全程 GitOps（ArgoCD wave 3–6）+ 三支 CI（test→GHCR→bump）。

**Architecture:** 沿用 P0 服務接入契約：儲存底座（Postgres/MinIO）走 plain kustomize + 子 Application（wave 3），spark-operator/airflow 走 Helm 子 Application（wave 4/5），監控素材 directory 型（wave 6）。資料流 Bronze（MinIO 原始 JSON，決定性 key 冪等）→ Silver（Iceberg on MinIO，JDBC catalog on Postgres，overwritePartitions 冪等）→ Silver serving（Postgres，pyiceberg→UPSERT 冪等）→ Gold（dbt 5 marts）。一套 Postgres 三職責（Airflow metadata / Iceberg catalog / Silver serving + Gold）。

**Tech Stack:** Airflow Helm chart 1.22.0（apache/airflow:3.2.2，KubernetesExecutor + git-sync）· Kubeflow spark-operator 2.5.1 · spark:4.0.2-python3 + iceberg-spark-runtime-4.0_2.13 1.11.0 · MinIO RELEASE.2025-09-07T16-13-09Z · postgres:16.14 + postgres_exporter v0.20.1 · pyiceberg 0.11.1 · dbt-postgres 1.10.2 · GitHub Actions + GHCR · kustomize + yq。

## Global Constraints

以下為 P1 design（`docs/specs/2026-07-08-P1-data-pipeline-design.md`）§0/§2/§8 鎖定值 + 勘誤層（`docs/specs/2026-07-17-design-errata.md`）硬性規則，**每個 task 都隱含遵守**。

### 版本 pin 表（design §0 原樣照抄，Task 0 逐項驗證存在性）

| 元件 | 版本 | 查證方式 |
|---|---|---|
| Airflow 官方 Helm chart | **1.22.0**（appVersion **3.2.2**） | `airflow.apache.org/index.yaml` |
| Airflow（自訂 image base） | **`apache/airflow:3.2.2`**（跟 chart appVersion 對齊，不追 PyPI 3.3.0） | 同上 |
| Kubeflow spark-operator Helm chart | **2.5.1**（appVersion 2.5.1） | `kubeflow.github.io/spark-operator/index.yaml` |
| Spark（job image base） | **`spark:4.0.2-python3`**（Docker 官方 library image） | Docker Hub tags |
| iceberg-spark-runtime-4.0_2.13 | **1.11.0** | Maven Central |
| pyiceberg | **0.11.1**（extras `[s3fs,sql-postgres]`） | PyPI |
| dbt-postgres | **1.10.2**（讓它自解析相容的 dbt-core） | PyPI |
| MinIO | **`minio/minio:RELEASE.2025-09-07T16-13-09Z`** | Docker Hub tags |
| MinIO mc（bucket init Job） | **`minio/mc:RELEASE.2025-08-13T08-35-41Z`** | Docker Hub tags |
| PostgreSQL | **`postgres:16.14`** | Docker Hub tags |
| postgres_exporter | **v0.20.1**（`quay.io/prometheuscommunity/postgres-exporter`） | GitHub releases |
| hadoop-aws / aws-java-sdk-bundle jars | 對齊 spark:4.0.2 內建 Hadoop（範本用 3.4.1 / 1.12.780；Task 0 步驟 C3 校準） | 範本 + Task 0 校準 |

- **CI actions pin（沿用 P0 §0 實際值，勘誤 A1）**：`actions/checkout@v7`、`astral-sh/setup-uv@v8.3.2`、`docker/setup-qemu-action@v4`、`docker/setup-buildx-action@v4`、`docker/login-action@v4`、`docker/build-push-action@v7`；本階段新增 `actions/setup-java@v5`（temurin 17，Task 0 驗 tag 存在）。runner 內建 `yq`。
- **本 plan 補充 pin（design 未列、Task 0 一併驗證）**：`boto3==1.40.0`、`psycopg2-binary==2.9.10`、`httpx==0.28.1`（沿 P0）、`pytest==9.1.1`、`ruff==0.15.20`（沿 P0）、`pyspark==4.0.2`（spark 測試用，同 Spark 版）、PostgreSQL JDBC driver `42.7.7`（Iceberg JDBC catalog 必需，design 漏列——見 Self-Review 歧義 #2）、`pyyaml==6.0.3`。

### k8s 資源名 / DNS 合約（design §2 原樣照抄，全 plan 引用此表、不另創名）

| 資源 | 名稱 | ns | 叢集內位址 |
|---|---|---|---|
| MinIO StatefulSet + Service（ClusterIP） | `lakehouse-minio` | data | `http://lakehouse-minio.data.svc:9000`（S3 API；全設計唯一 S3 endpoint 字面值） |
| MinIO bucket-init Job | `minio-bucket-init` | data | —（PostSync hook，跑完即刪） |
| Postgres StatefulSet + Service（ClusterIP） | `lakehouse-postgres` | data | `lakehouse-postgres.data.svc:5432` |
| postgres-exporter Deployment + Service | `lakehouse-postgres-exporter` | data | `:9187`（ServiceMonitor 對準） |
| PVC（兩個 StatefulSet 的 volumeClaimTemplate） | `data`（模板名） | data | 各 10Gi，無 storageClassName |
| Helm release：spark-operator | `spark-operator`（= Application 名） | spark-operator | chart repo `https://kubeflow.github.io/spark-operator` |
| Helm release：airflow | `airflow`（= Application 名） | airflow | chart repo `https://airflow.apache.org` |
| Spark job 側 ServiceAccount（chart 依 `spark.jobNamespaces: [data]` 自建） | `spark-operator-spark`（`<release>-spark` 命名規則；Task 0 C2 校驗） | data | SparkApplication `driver./executor.serviceAccount` 引用 |

ArgoCD Application 名 = `platform/argocd/apps/` 檔名去 `.yaml`（`lakehouse-postgres`／`lakehouse-minio`／`spark-operator`／`airflow`／`pipeline-monitoring`）。Ingress：`airflow.localtest.me`（chart ingress values）；MinIO console 不開 ingress。

### Sync-wave（接續 P0 的 0/1/2；wave 3–6，禁改既有號）

| wave | Application | namespace | 內容 |
|---|---|---|---|
| 3 | lakehouse-postgres、lakehouse-minio | `data` | 儲存底座（Airflow/Spark/dbt 全依賴） |
| 4 | spark-operator | `spark-operator`（jobs 跑在 `data`） | Helm chart 2.5.1，`spark.jobNamespaces: [data]` |
| 5 | airflow | `airflow` | Helm chart 1.22.0（KubernetesExecutor + git-sync） |
| 6 | pipeline-monitoring | `monitoring` | dashboards / PrometheusRule / ServiceMonitor |

syncPolicy 沿 P0：`automated {prune, selfHeal}` + `CreateNamespace=true` + retry；CRD 依賴資源用 `SkipDryRunOnMissingResource=true` 註解。SparkApplication 模板不進 ArgoCD（Airflow runtime 提交）。

### Secrets 合約（design §8 原樣照抄；`make pipeline-secrets` 命令式建立、不進 git）

| Secret | ns | key（確切名） | 內容 |
|---|---|---|---|
| `youtube-api` | airflow | `YOUTUBE_API_KEY` | 唯一外部憑證，使用者提供 |
| `minio-root` | data、airflow | `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` | 隨機生成（`openssl rand -hex 20`）；key 直接用 AWS 標準名——同一份 Secret `envFrom` 即可餵 boto3/pyiceberg/S3A，MinIO 本體以 `valueFrom` 映射成 `MINIO_ROOT_USER/PASSWORD` |
| `lakehouse-postgres` | data、airflow | `postgres-password`、`airflow-password`、`pipeline-password`、`dbt-password`、`grafana-reader-password`、`connection`、`pipeline-dsn`（本 plan 補，見歧義 #1） | 各角色密碼（隨機生成）+ Airflow metadata connection string（key 名 `connection` 為 chart 約定）+ pipeline_writer 完整 DSN |
| `grafana-lakehouse-reader` | monitoring | `password` | `grafana_reader` 密碼（與 `lakehouse-postgres` 的 `grafana-reader-password` 同值，一次生成寫兩處） |
| `airflow-webserver-secret`（本 plan 補，見歧義 #6） | airflow | `webserver-secret-key` | 隨機生成；chart 不設會每次 deploy 換隨機值→pod 連環重啟（P0 Grafana 隨機密碼同型雷） |

**Env 注入合約**（design §8 原樣照抄；程式碼一律顯式讀 env，不靠隱式 default）：

| env 變數 | 來源 Secret/key | 消費者 | 注入途徑 |
|---|---|---|---|
| `YOUTUBE_API_KEY` | `youtube-api`/`YOUTUBE_API_KEY` | ingest task pods | Airflow chart `secret:` list |
| `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` | `minio-root` 同名 key | ingest/loader task pods；Spark driver+executor | chart `secret:`；SparkApplication `envFrom` |
| `AWS_ENDPOINT_URL` | 非 secret，值 = `http://lakehouse-minio.data.svc:9000` | 同上（boto3/pyiceberg 讀它連 MinIO；雲上刪除即回 AWS 原生解析 = 可攜） | `pipeline.yaml` → DAG 傳入 / Spark 模板以 `fs.s3a.endpoint` conf 寫死同值 |
| `LAKEHOUSE_PG_DSN` | `lakehouse-postgres`/`pipeline-dsn`，值 = `postgresql://pipeline_writer:<pw>@lakehouse-postgres.data.svc:5432/lakehouse` | loader、categories UPSERT、pyiceberg sql catalog（另加 `+psycopg2` driver 前綴） | chart `secret:` |
| `DBT_PG_PASSWORD`（host 用 `LAKEHOUSE_PG_HOST`，有 default） | `lakehouse-postgres`/`dbt-password` | dbt KPO pod（profiles.yml `env_var()`） | KPO `secrets=[Secret('env', …)]` |

### 勘誤層硬性規則（errata §C/§E/§F，全 task 隱含遵守）

- **runtime 在 M4**（SSH via Tailscale `100.74.192.11`）；開發/commit 在 M1。**所有 live 叢集步驟走 SSH、指令一律絕對路徑**；本 plan 中標註「（M4）」的步驟 = `ssh 100.74.192.11 '<指令>'` 執行，未標註者在 M1 本機跑（純檔案/單元測試/YAML 驗證）。
- **M4 runtime 指令一律加 PATH shim**：`PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin DOCKER_CONFIG=/tmp/docker-noauth`（非互動 keychain 鎖死，shim 使 credential helper 不可見）。
- **macOS bash 3.2**：shell script 中文訊息內變數一律 `${var}`（`$var（` 直接炸 unbound）。
- **GHCR 路徑一律小寫**：`ghcr.io/ferguske/trend-intelligence-platform/<name>`（本階段三個新 image：`airflow`、`spark-jobs`、`dbt`）。public repo 的 Actions 產物 package 自動公開，免手動改 visibility。
- **可攜鐵律**：不寫任何 `storageClassName`；ingress 零控制器專屬 annotation（只 `ingressClassName: nginx`）。`grep -r "alb.ingress\|nginx.ingress\|storageClassName"` 對本階段目錄須為空。
- **資源治理（errata §C）**：每個新常駐元件必須聲明 requests/limits（Task 0 B 有全帳）；重量元件配 `make demo-p1-up/down` 啟停（Task 14）。
- **Git commit 中文**：`動作(範圍)：說明`。TDD、頻繁小 commit。
- kind hostPort：80 照舊、443→8443（M4 的 443 被 Tailscale 佔）；驗證腳本 port-forward 用非常用 port（19090 等）避開 VS Code 自動轉發。

---

## File Structure（本 plan 產出的全部檔案）

```
Makefile                                        # += pipeline-secrets/pipeline-verify/pipeline-trigger/demo-p1-up/down（Task 1/14）
scripts/pipeline-secrets.sh                     # Task 1
scripts/verify-pipeline.sh                      # Task 14
.github/workflows/airflow-ci.yaml               # Task 7
.github/workflows/spark-ci.yaml                 # Task 11
.github/workflows/dbt-ci.yaml                   # Task 12
.github/workflows/pr-checks.yaml（既有，擴充）    # Task 14
ingestion/youtube/{pyproject.toml, src/yt_ingest/{__init__,client,bronze,categories}.py, tests/…}   # Task 6
orchestration/airflow/Dockerfile                # Task 7
orchestration/airflow/dags/{yt_trending_hourly,yt_categories_daily,yt_reprocess_range}.py           # Task 9
orchestration/airflow/dags/config/{pipeline.yaml, images.yaml}                                      # Task 8
orchestration/airflow/dags/templates/spark_silver.yaml                                              # Task 8
orchestration/airflow/tests/test_dags.py        # Task 9
lakehouse/postgres/k8s/{kustomization,statefulset,service,init-sql-configmap,exporter,exporter-queries-configmap,exporter-servicemonitor}.yaml   # Task 2
lakehouse/minio/k8s/{kustomization,statefulset,service,servicemonitor,bucket-init-job}.yaml         # Task 3
lakehouse/spark/{Dockerfile, pyproject.toml, jobs/silver_job.py, tests/test_silver_job.py, k8s/rbac.yaml}   # Task 11
lakehouse/dbt/{Dockerfile, dbt_project.yml, profiles.yml, macros/generate_schema_name.sql,
               models/staging/{_sources,_staging_schema}.yml + stg_*.sql,
               models/marts/_marts_schema.yml + gold_*.sql ×5, tests/*.sql ×6}                      # Task 12
platform/argocd/apps/{lakehouse-postgres,lakehouse-minio,spark-operator,airflow,pipeline-monitoring}.yaml   # Task 4/5/10/13
platform/argocd/apps/monitoring.yaml（既有，加 envFromSecrets）                                      # Task 13
platform/monitoring/pipeline/{statsd-servicemonitor,prometheusrule,pipeline-health-dashboard,
                              trending-insights-dashboard,grafana-datasource-lakehouse}.yaml        # Task 13
README.md（既有，補 P1 章節）                     # Task 15
```

**執行流程總覽**：Task 0 校準 → Task 1–14 建檔並各自局部驗證（單元測試在 M1 本機；涉叢集的 dry-run 標註 M4）→ Task 15 端到端整合（push main → 三支 CI → ArgoCD wave 3–6 收斂 → `make pipeline-verify` 10 檢查全綠）。分支模式沿 P0：在 feature branch 開發、任務級 commit，Task 15 才合回 main 觸發 CI/GitOps。

---

## Task 0: Pin 驗證 + 資源預算 + chart values 校準（preflight，errata §E/§C 硬性）

**Files:** 無（產出 = 驗證過的 pin 清單 + 資源預算確認 + 校準值記錄）

**Interfaces:**
- Produces: 全部版本 pin 確認存在；OrbStack VM 記憶體調至 10GiB（USER-CONFIRM）；Airflow chart values key 形狀、spark-operator SA 名、spark image Hadoop 版本三項校準值，供 Task 8/10/11 直接引用。

### A. Pin 存在性驗證（每條指令的預期輸出如註；**任一條驗證失敗 = STOP**，回報並以官方源當日實際版本重校準該 pin——連動改 Global Constraints 表與引用它的 task，不得帶著幽靈版本繼續）

- [ ] **Step A1: Helm chart 兩項**

```bash
curl -s https://airflow.apache.org/index.yaml | grep -A2 'version: 1.22.0'
# 預期：命中一段含 "version: 1.22.0"（上下文帶 appVersion: 3.2.2）；無輸出 = STOP
curl -s https://kubeflow.github.io/spark-operator/index.yaml | grep -B4 'version: 2.5.1'
# 預期：命中 spark-operator chart 條目含 "version: 2.5.1"；無輸出 = STOP
```

- [ ] **Step A2: Docker Hub image tags 五項**

```bash
curl -s "https://hub.docker.com/v2/repositories/library/spark/tags/4.0.2-python3" | jq -r '.name'
# 預期：4.0.2-python3（回 "null" 或 errinfo = STOP）
curl -s "https://hub.docker.com/v2/repositories/minio/minio/tags/RELEASE.2025-09-07T16-13-09Z" | jq -r '.name'
# 預期：RELEASE.2025-09-07T16-13-09Z
curl -s "https://hub.docker.com/v2/repositories/minio/mc/tags/RELEASE.2025-08-13T08-35-41Z" | jq -r '.name'
# 預期：RELEASE.2025-08-13T08-35-41Z
curl -s "https://hub.docker.com/v2/repositories/library/postgres/tags/16.14" | jq -r '.name'
# 預期：16.14
curl -s "https://hub.docker.com/v2/repositories/apache/airflow/tags/3.2.2" | jq -r '.name'
# 預期：3.2.2
```

- [ ] **Step A3: PyPI 八項**

```bash
for pkg_ver in pyiceberg/0.11.1 dbt-postgres/1.10.2 boto3/1.40.0 psycopg2-binary/2.9.10 httpx/0.28.1 pytest/9.1.1 pyspark/4.0.2 pyyaml/6.0.3; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://pypi.org/pypi/${pkg_ver}/json")
  echo "${pkg_ver}: ${code}"
done
# 預期：全部 200；任一 404 = STOP（boto3/psycopg2-binary 是本 plan 補 pin，404 時改抓
# curl -s https://pypi.org/pypi/<pkg>/json | jq -r .info.version 的當日最新 stable 並更新 Global Constraints）
```

- [ ] **Step A4: Maven Central 四個 jar**

```bash
for path in \
  "org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/1.11.0/iceberg-spark-runtime-4.0_2.13-1.11.0.jar" \
  "org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar" \
  "com/amazonaws/aws-java-sdk-bundle/1.12.780/aws-java-sdk-bundle-1.12.780.jar" \
  "org/postgresql/postgresql/42.7.7/postgresql-42.7.7.jar"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://repo1.maven.org/maven2/${path}")
  echo "${path}: ${code}"
done
# 預期：全部 200；hadoop-aws/aws-java-sdk-bundle 版本以 Step C3 校準結果為準（若 C3 得出非 3.4.1，改驗校準版）
```

- [ ] **Step A5: GitHub releases / actions tags 兩項**

```bash
curl -s https://api.github.com/repos/prometheus-community/postgres_exporter/releases/tags/v0.20.1 | jq -r '.tag_name'
# 預期：v0.20.1（"null" = STOP）
curl -s https://api.github.com/repos/actions/setup-java/git/ref/tags/v5 | jq -r '.ref'
# 預期：refs/tags/v5（P0 實證教訓：setup-uv@v8 這種 major-only tag 不存在就是不存在，404 = STOP，
# 改用 git/matching-refs/tags/v5 查實際最新 v5.x.y 全碼 tag）
```

### B. 全階段資源預算表（errata §C1；USER-CONFIRM 步驟在 B2）

- [ ] **Step B1: 對帳下表（本 plan 各 task 的 requests 值即出自此表，改任一邊都要同步）**

**常駐（steady-state requests，memory 為主）：**

| 元件 | cpu req | mem req | mem limit | 來源 task |
|---|---|---|---|---|
| P0 既有全部（ArgoCD+ingress+kube-prometheus+hello，實測） | — | ~3Gi | — | P0 |
| Postgres（lakehouse-postgres） | 250m | 512Mi | 1Gi | Task 2 |
| postgres-exporter | 50m | 64Mi | 128Mi | Task 2 |
| MinIO | 250m | 512Mi | 1Gi | Task 3 |
| spark-operator controller | 100m | 200Mi | 512Mi | Task 5 |
| Airflow scheduler | 250m | 512Mi | 1Gi | Task 10 |
| Airflow dag-processor | 200m | 512Mi | 1Gi | Task 10 |
| Airflow api-server | 200m | 512Mi | 1Gi | Task 10 |
| Airflow triggerer | 100m | 256Mi | 512Mi | Task 10 |
| Airflow statsd | 50m | 64Mi | 128Mi | Task 10 |
| **P1 常駐小計** | | **≈ +2.6Gi** | | |
| **常駐總計** | | **≈ 5.7Gi / 7.8Gi VM** | | |

**尖峰（ephemeral，每小時 DAG run）：**

| 元件 | 個數 × mem | 小計 |
|---|---|---|
| ingest task pods（動態映射 8 區） | 8 × 256Mi | 2.0Gi |
| Spark driver | 1 × 1.5Gi | 1.5Gi |
| Spark executor | 1 × 1.5Gi | 1.5Gi |
| dbt KPO pod | 1 × 256Mi | 0.25Gi |
| **最壞全重疊** | | **+5.3Gi → 11Gi ＞ 7.8Gi（爆）** |
| **實際尖峰**（設計已內建緩解：`max_active_runs=1` 防跨 run 重疊；DAG 依賴鏈使 ingest 8 pod 跑完才起 Spark、Spark 完才起 dbt——同時在空中的最多 = Spark driver+executor ≈ 3Gi，加上 loader/收尾殘留緩衝取 3.3Gi） | | **≈ +3.3Gi → ≈ 9Gi ＞ 7.8Gi（仍超）** |

結論：**必須擴 VM**。目標 10GiB：常駐 5.7Gi + 實際尖峰 3.3Gi ≈ 9Gi ＜ 10GiB，留 1Gi 餘裕。

- [ ] **Step B2: 擴 OrbStack VM 記憶體到 10GiB（★USER-CONFIRM：需 Fergus 執行/批准——會短暫重啟 OrbStack VM，連帶重啟他跑在 OrbStack 上的其他容器；請先確認時點）**

（M4）Fergus 批准後執行：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin orb config set memory_mib 10240
# 或 OrbStack UI → Settings → System → Memory → 10 GiB
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin orb config show | grep memory
```
Expected: `memory_mib: 10240`。之後 `make cluster-start`（若叢集被重啟）等 pod 收斂，`make verify` 複驗 P0 仍綠。

### C. Chart values / image 校準（design §12B 實查 1/2/5/6/7 前移到此）

- [ ] **Step C1: Airflow chart 1.22.0 values 逐 key 校對（design 預期零改動；不符則以實際 key 修 Task 10 values）**

```bash
helm repo add apache-airflow https://airflow.apache.org 2>/dev/null; helm repo update apache-airflow
helm show values apache-airflow/airflow --version 1.22.0 > /tmp/airflow-values.yaml
grep -n "apiServer:" /tmp/airflow-values.yaml | head -5        # 預期：ingress 區塊下有 apiServer:（Airflow 3 併 webserver 入 apiServer）
grep -n -A6 "^secret:" /tmp/airflow-values.yaml               # 預期：list 形狀 [{envName, secretName, secretKey}]
grep -n "metadataSecretName" /tmp/airflow-values.yaml          # 預期：存在；註解說明 key 必須名為 connection
grep -n -A2 "^statsd:" /tmp/airflow-values.yaml                # 預期：statsd.enabled 存在
grep -n -A8 "gitSync:" /tmp/airflow-values.yaml | head -20     # 預期：dags.gitSync.{enabled,repo,branch,subPath}
grep -n -A4 "^images:" /tmp/airflow-values.yaml | head -10     # 預期：images.airflow.{repository,tag}
grep -n "webserverSecretKeySecretName" /tmp/airflow-values.yaml  # 預期：存在（Task 1 建的 airflow-webserver-secret 對接點）
```

- [ ] **Step C2: spark-operator 2.5.1 jobNamespaces / SA 名校驗**

```bash
helm repo add spark-operator https://kubeflow.github.io/spark-operator 2>/dev/null; helm repo update spark-operator
helm show values spark-operator/spark-operator --version 2.5.1 | grep -n -A3 "jobNamespaces"
# 預期：spark.jobNamespaces 存在（list，default ["default"]）
helm template spark-operator spark-operator/spark-operator --version 2.5.1 \
  --set 'spark.jobNamespaces={data}' | grep -B3 -A6 "kind: ServiceAccount"
# 預期：data ns 出現名為 spark-operator-spark 的 ServiceAccount（<release>-spark 規則）。
# 若名稱不同：以實際名替換 Task 8 模板 serviceAccount 與本表 §2 合約行。
```

- [ ] **Step C3: spark:4.0.2-python3 內建 Hadoop 版本 → 定 hadoop-aws/aws-java-sdk-bundle 版**

```bash
docker run --rm spark:4.0.2-python3 ls /opt/spark/jars | grep hadoop-client
# 預期形如 hadoop-client-api-3.4.1.jar / hadoop-client-runtime-3.4.1.jar
# → hadoop-aws 取同版（3.4.1 為預設傾向）；aws-java-sdk-bundle 取該 hadoop-aws 版 POM 相依版（3.4.1 → 1.12.780）。
# 若非 3.4.1：更新 Task 11 Dockerfile ARG 與 Step A4 驗證路徑後重跑 A4。
```

- [ ] **Step C4: kube-prometheus-stack Grafana envFromSecrets / datasource sidecar key 確認（design §12B.6）**

```bash
helm show values prometheus-community/kube-prometheus-stack --version 87.10.1 > /tmp/kps-values.yaml
grep -n "envFromSecrets" /tmp/kps-values.yaml     # 預期：grafana.envFromSecrets（list，元素含 name/optional）
grep -n -A3 "datasources:" /tmp/kps-values.yaml | grep -n -B1 -A3 "sidecar" | head
grep -n -B2 -A6 "sidecar:" /tmp/kps-values.yaml | grep -A4 "datasources:" | head -8
# 預期：grafana.sidecar.datasources.enabled 預設 true、label 預設 grafana_datasource
# 若 key 不同：修 Task 13 的 datasource ConfigMap label 與 monitoring.yaml 增量 values。
```

- [ ] **Step C5: Airflow chart statsd svc 名/port 名 + worker SA 名（design §12B.2/7 前移）**

```bash
helm template airflow apache-airflow/airflow --version 1.22.0 \
  --set executor=KubernetesExecutor --set statsd.enabled=true --namespace airflow \
  > /tmp/airflow-rendered.yaml
grep -B6 "component: statsd" /tmp/airflow-rendered.yaml | grep -E "kind: Service|name:" | head
# 預期：Service 名 airflow-statsd；記下 metrics port 名（預設傾向 statsd-scrape，供 Task 13 ServiceMonitor）
grep -B2 -A4 "kind: ServiceAccount" /tmp/airflow-rendered.yaml | grep "name:" | sort -u
# 預期：含 airflow-worker（供 Task 11 RoleBinding subject；不同則以實際名替換）
```

> 本 task 無 commit（純校準；校準結果若改動 pin/名稱，隨受影響 task 的 commit 一併入版）。

---

## Task 1: `make pipeline-secrets`（命令式 Secret 邊界）

**Files:**
- Create: `scripts/pipeline-secrets.sh`
- Modify: `Makefile`（加 `pipeline-secrets` target）

**Interfaces:**
- Consumes: 使用者提供的 `YOUTUBE_API_KEY`；既有叢集（P0 `make cluster-up` 已跑）。
- Produces: Secrets 合約表全部五把 Secret（`youtube-api`／`minio-root`×2ns／`lakehouse-postgres`×2ns／`grafana-lakehouse-reader`／`airflow-webserver-secret`），冪等（重跑沿用既有密碼、不輪替）。Task 2/3/10/13 的 valueFrom/envFrom/metadataSecretName 全部對準這些名字。

- [ ] **Step 1: 建 scripts/pipeline-secrets.sh（bash-3.2 安全：中文訊息內一律 `${var}`）**

Create `scripts/pipeline-secrets.sh`：
```bash
#!/usr/bin/env bash
set -euo pipefail

YOUTUBE_API_KEY="${1:?用法：pipeline-secrets.sh <YOUTUBE_API_KEY>}"

# 冪等：secret 已存在則沿用其值（避免密碼輪替導致 Postgres 已初始化的角色失聯），不存在才生成
get_or_gen() {  # $1=ns $2=secret $3=key
  local v
  v=$(kubectl -n "$1" get secret "$2" -o "jsonpath={.data['$3']}" 2>/dev/null | base64 -d 2>/dev/null || true)
  if [ -z "${v}" ]; then v=$(openssl rand -hex 20); fi
  printf '%s' "${v}"
}

for ns in data airflow; do
  kubectl create namespace "${ns}" --dry-run=client -o yaml | kubectl apply -f -
done

MINIO_USER=$(get_or_gen data minio-root AWS_ACCESS_KEY_ID)
MINIO_PW=$(get_or_gen data minio-root AWS_SECRET_ACCESS_KEY)
PG_SUPER_PW=$(get_or_gen data lakehouse-postgres postgres-password)
AIRFLOW_PW=$(get_or_gen data lakehouse-postgres airflow-password)
PIPELINE_PW=$(get_or_gen data lakehouse-postgres pipeline-password)
DBT_PW=$(get_or_gen data lakehouse-postgres dbt-password)
GRAFANA_PW=$(get_or_gen data lakehouse-postgres grafana-reader-password)
WEBSERVER_KEY=$(get_or_gen airflow airflow-webserver-secret webserver-secret-key)

for ns in data airflow; do
  kubectl -n "${ns}" create secret generic minio-root \
    --from-literal=AWS_ACCESS_KEY_ID="${MINIO_USER}" \
    --from-literal=AWS_SECRET_ACCESS_KEY="${MINIO_PW}" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n "${ns}" create secret generic lakehouse-postgres \
    --from-literal=postgres-password="${PG_SUPER_PW}" \
    --from-literal=airflow-password="${AIRFLOW_PW}" \
    --from-literal=pipeline-password="${PIPELINE_PW}" \
    --from-literal=dbt-password="${DBT_PW}" \
    --from-literal=grafana-reader-password="${GRAFANA_PW}" \
    --from-literal=connection="postgresql://airflow:${AIRFLOW_PW}@lakehouse-postgres.data.svc:5432/airflow" \
    --from-literal=pipeline-dsn="postgresql://pipeline_writer:${PIPELINE_PW}@lakehouse-postgres.data.svc:5432/lakehouse" \
    --dry-run=client -o yaml | kubectl apply -f -
done

kubectl -n airflow create secret generic youtube-api \
  --from-literal=YOUTUBE_API_KEY="${YOUTUBE_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n airflow create secret generic airflow-webserver-secret \
  --from-literal=webserver-secret-key="${WEBSERVER_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n monitoring create secret generic grafana-lakehouse-reader \
  --from-literal=password="${GRAFANA_PW}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ pipeline secrets 就緒（youtube-api / minio-root ×2 / lakehouse-postgres ×2 / airflow-webserver-secret / grafana-lakehouse-reader）"
```

- [ ] **Step 2: Makefile 加 target**

Modify `Makefile`——`.PHONY` 行改為：
```makefile
.PHONY: cluster-up cluster-down cluster-stop cluster-start verify argocd-ui pipeline-secrets pipeline-verify pipeline-trigger demo-p1-up demo-p1-down
```
並在檔尾新增：
```makefile
pipeline-secrets:      ## make pipeline-secrets YOUTUBE_API_KEY=<key>（冪等；命令式、不進 git）
	@test -n "$(YOUTUBE_API_KEY)" || { echo "用法：make pipeline-secrets YOUTUBE_API_KEY=<key>"; exit 1; }
	./scripts/pipeline-secrets.sh "$(YOUTUBE_API_KEY)"
```

- [ ] **Step 3: 語法驗證 + 實跑（M4）**

M1 本機：
```bash
chmod +x scripts/pipeline-secrets.sh
bash -n scripts/pipeline-secrets.sh && echo "語法 OK"
```
（M4，需 P0 叢集在跑）：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make pipeline-secrets YOUTUBE_API_KEY=<真 key>
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n data get secret minio-root lakehouse-postgres
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get secret youtube-api minio-root lakehouse-postgres airflow-webserver-secret
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n monitoring get secret grafana-lakehouse-reader
# 重跑一次 make pipeline-secrets 確認冪等（密碼不變）：
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n data get secret lakehouse-postgres -o jsonpath="{.data['pipeline-password']}" > /tmp/pw1
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make pipeline-secrets YOUTUBE_API_KEY=<真 key>
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n data get secret lakehouse-postgres -o jsonpath="{.data['pipeline-password']}" > /tmp/pw2
diff /tmp/pw1 /tmp/pw2 && echo "冪等 OK"
```
Expected: 全部 secret 列出；`冪等 OK`。

- [ ] **Step 4: Commit**

```bash
git add scripts/pipeline-secrets.sh Makefile
git commit -m "建置(pipeline)：make pipeline-secrets 命令式 Secret 邊界（冪等、五把 secret）"
```

---

## Task 2: Postgres k8s（lakehouse-postgres + init SQL + postgres-exporter）

**Files:**
- Create: `lakehouse/postgres/k8s/kustomization.yaml`
- Create: `lakehouse/postgres/k8s/statefulset.yaml`
- Create: `lakehouse/postgres/k8s/service.yaml`
- Create: `lakehouse/postgres/k8s/init-sql-configmap.yaml`
- Create: `lakehouse/postgres/k8s/exporter.yaml`（Deployment + Service）
- Create: `lakehouse/postgres/k8s/exporter-queries-configmap.yaml`
- Create: `lakehouse/postgres/k8s/exporter-servicemonitor.yaml`

**Interfaces:**
- Consumes: Task 1 Secret `lakehouse-postgres`（data ns）。
- Produces: `lakehouse-postgres.data.svc:5432`（databases `airflow`/`lakehouse`、schemas `silver`/`gold`、四角色）；exporter `:9187` 出 `yt_freshness_seconds`/`yt_silver_rows_24h{region}`/`yt_gold_mart_rows{mart}` 三指標（design §9 SQL 即合約）。Task 4 的 lakehouse-postgres Application source 指向本目錄；Task 13 PrometheusRule 對準三指標。

- [ ] **Step 1: 建 kustomization.yaml**

Create `lakehouse/postgres/k8s/kustomization.yaml`：
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: data
resources:
  - statefulset.yaml
  - service.yaml
  - init-sql-configmap.yaml
  - exporter.yaml
  - exporter-queries-configmap.yaml
  - exporter-servicemonitor.yaml
```

- [ ] **Step 2: 建 statefulset.yaml（postgres:16.14，PVC 模板名 `data` 10Gi 無 storageClassName）**

Create `lakehouse/postgres/k8s/statefulset.yaml`：
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: lakehouse-postgres
  labels: {app: lakehouse-postgres}
spec:
  serviceName: lakehouse-postgres
  replicas: 1
  selector:
    matchLabels: {app: lakehouse-postgres}
  template:
    metadata:
      labels: {app: lakehouse-postgres}
    spec:
      containers:
        - name: postgres
          image: postgres:16.14
          ports:
            - {containerPort: 5432, name: pg}
          env:
            - name: POSTGRES_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: postgres-password}}
            - name: AIRFLOW_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: airflow-password}}
            - name: PIPELINE_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: pipeline-password}}
            - name: DBT_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: dbt-password}}
            - name: GRAFANA_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: grafana-reader-password}}
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          volumeMounts:
            - {name: data, mountPath: /var/lib/postgresql/data}
            - {name: init-sql, mountPath: /docker-entrypoint-initdb.d, readOnly: true}
          readinessProbe:
            exec: {command: ["pg_isready", "-U", "postgres"]}
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
      volumes:
        - name: init-sql
          configMap: {name: lakehouse-postgres-init, defaultMode: 0555}
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests: {storage: 10Gi}
```

- [ ] **Step 3: 建 service.yaml**

Create `lakehouse/postgres/k8s/service.yaml`：
```yaml
apiVersion: v1
kind: Service
metadata:
  name: lakehouse-postgres
  labels: {app: lakehouse-postgres}
spec:
  type: ClusterIP
  selector: {app: lakehouse-postgres}
  ports:
    - {name: pg, port: 5432, targetPort: 5432}
```

- [ ] **Step 4: 建 init-sql ConfigMap（design §4 明細：shell script 形式讓 env 可插值；只在空 PVC 首啟執行）**

Create `lakehouse/postgres/k8s/init-sql-configmap.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: lakehouse-postgres-init
  labels: {app: lakehouse-postgres}
data:
  01-init.sh: |
    #!/bin/bash
    set -euo pipefail
    # 角色與 database（密碼來自 Secret 注入的環境變數——因此用 .sh 而非 .sql，entrypoint 會以 shell 執行使 env 可插值）
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
      CREATE ROLE airflow LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
      CREATE ROLE pipeline_writer LOGIN PASSWORD '${PIPELINE_DB_PASSWORD}';
      CREATE ROLE dbt_runner LOGIN PASSWORD '${DBT_DB_PASSWORD}';
      CREATE ROLE grafana_reader LOGIN PASSWORD '${GRAFANA_DB_PASSWORD}';
      CREATE DATABASE airflow OWNER airflow;
      CREATE DATABASE lakehouse;
    EOSQL
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname lakehouse <<-EOSQL
      CREATE SCHEMA silver AUTHORIZATION pipeline_writer;
      CREATE SCHEMA gold AUTHORIZATION dbt_runner;
      -- postgres:16 起 public 對非 owner 預設不可寫；Iceberg JDBC catalog 表建於 public（pipeline_writer 連線）
      GRANT CREATE ON SCHEMA public TO pipeline_writer;
      -- dbt 自建 staging schema 需要 database 級 CREATE
      GRANT CREATE ON DATABASE lakehouse TO dbt_runner;
      -- 讀取路徑：dbt 讀 silver、grafana 讀 gold、exporter（pipeline_writer 連線）讀 gold
      GRANT USAGE ON SCHEMA silver TO dbt_runner;
      GRANT USAGE ON SCHEMA gold TO grafana_reader;
      GRANT USAGE ON SCHEMA gold TO pipeline_writer;
      -- dbt 每 run 重建 table，靠 default privileges 而非一次性 GRANT（design §4 兩條）
      ALTER DEFAULT PRIVILEGES FOR ROLE pipeline_writer IN SCHEMA silver GRANT SELECT ON TABLES TO dbt_runner;
      ALTER DEFAULT PRIVILEGES FOR ROLE dbt_runner IN SCHEMA gold GRANT SELECT ON TABLES TO grafana_reader;
      -- exporter 的 yt_gold_mart_rows 需要 pipeline_writer 讀 gold（§9 合約成立的必要補充，見 Self-Review 歧義 #3）
      ALTER DEFAULT PRIVILEGES FOR ROLE dbt_runner IN SCHEMA gold GRANT SELECT ON TABLES TO pipeline_writer;
    EOSQL
```

- [ ] **Step 5: 建 exporter.yaml（v0.20.1 + pipeline_writer DSN，k8s `$(VAR)` 依賴展開組 DSN）**

Create `lakehouse/postgres/k8s/exporter.yaml`：
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: lakehouse-postgres-exporter
  labels: {app: lakehouse-postgres-exporter}
spec:
  replicas: 1
  selector:
    matchLabels: {app: lakehouse-postgres-exporter}
  template:
    metadata:
      labels: {app: lakehouse-postgres-exporter}
    spec:
      containers:
        - name: exporter
          image: quay.io/prometheuscommunity/postgres-exporter:v0.20.1
          args: ["--extend.query-path=/etc/queries/queries.yaml"]
          ports:
            - {containerPort: 9187, name: metrics}
          env:
            - name: PIPELINE_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: lakehouse-postgres, key: pipeline-password}}
            - name: DATA_SOURCE_NAME
              value: "postgresql://pipeline_writer:$(PIPELINE_DB_PASSWORD)@lakehouse-postgres.data.svc:5432/lakehouse?sslmode=disable"
          volumeMounts:
            - {name: queries, mountPath: /etc/queries, readOnly: true}
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
      volumes:
        - name: queries
          configMap: {name: lakehouse-exporter-queries}
---
apiVersion: v1
kind: Service
metadata:
  name: lakehouse-postgres-exporter
  labels: {app: lakehouse-postgres-exporter}
spec:
  type: ClusterIP
  selector: {app: lakehouse-postgres-exporter}
  ports:
    - {name: metrics, port: 9187, targetPort: 9187}
```

- [ ] **Step 6: 建自訂查詢 ConfigMap（design §9 三條 SQL 即合約；exporter 指標名 = `<key>_<欄名>`，key 刻意取短使組合名精確等於合約名）**

Create `lakehouse/postgres/k8s/exporter-queries-configmap.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: lakehouse-exporter-queries
  labels: {app: lakehouse-postgres-exporter}
data:
  queries.yaml: |
    yt_freshness:
      query: "SELECT EXTRACT(EPOCH FROM (now() - max(ingested_at))) AS seconds FROM silver.video_snapshots"
      master: true
      metrics:
        - seconds:
            usage: "GAUGE"
            description: "Seconds since last silver ingest"
    yt_silver:
      query: "SELECT region, count(*) AS rows_24h FROM silver.video_snapshots WHERE captured_at > now() - interval '24 hours' GROUP BY region"
      master: true
      metrics:
        - region:
            usage: "LABEL"
        - rows_24h:
            usage: "GAUGE"
            description: "Silver rows in last 24h per region"
    yt_gold_mart:
      query: "SELECT 'gold_trending_daily' AS mart, count(*) AS rows FROM gold.gold_trending_daily UNION ALL SELECT 'gold_channel_performance', count(*) FROM gold.gold_channel_performance UNION ALL SELECT 'gold_category_daily', count(*) FROM gold.gold_category_daily UNION ALL SELECT 'gold_video_velocity_hourly', count(*) FROM gold.gold_video_velocity_hourly UNION ALL SELECT 'gold_video_lifecycle', count(*) FROM gold.gold_video_lifecycle"
      master: true
      metrics:
        - mart:
            usage: "LABEL"
        - rows:
            usage: "GAUGE"
            description: "Row count per gold mart"
```
> 得出的 Prometheus 指標名：`yt_freshness_seconds`、`yt_silver_rows_24h{region}`、`yt_gold_mart_rows{mart}`——與 design §9/§12A 步驟 8 逐字一致。首日 silver/gold 表尚不存在時 exporter 只 log error 不 crash（v0.20.1 行為，design 判定可接受降級）。

- [ ] **Step 7: 建 exporter ServiceMonitor**

Create `lakehouse/postgres/k8s/exporter-servicemonitor.yaml`：
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: lakehouse-postgres-exporter
  labels: {app: lakehouse-postgres-exporter}
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  selector:
    matchLabels: {app: lakehouse-postgres-exporter}
  endpoints:
    - {port: metrics, path: /metrics, interval: 30s}
```

- [ ] **Step 8: 驗證渲染 + 可攜守門**

```bash
kubectl kustomize lakehouse/postgres/k8s | grep -E "image:|kind:" | sort | uniq
grep -rn "storageClassName" lakehouse/postgres/k8s && echo "VIOLATION" || echo "portability OK"
python3 - <<'PY'
import yaml
d = yaml.safe_load(open('lakehouse/postgres/k8s/exporter-queries-configmap.yaml'))
q = yaml.safe_load(d['data']['queries.yaml'])
assert set(q) == {'yt_freshness', 'yt_silver', 'yt_gold_mart'}, q.keys()
print('exporter queries YAML OK:', sorted(q))
PY
```
Expected: 渲染含 `postgres:16.14`、`postgres-exporter:v0.20.1`；`portability OK`；`exporter queries YAML OK`。

- [ ] **Step 9: Commit**

```bash
git add lakehouse/postgres/k8s/
git commit -m "部署(lakehouse)：Postgres 16.14 StatefulSet + init SQL 四角色 + postgres-exporter 三自訂指標"
```

---

## Task 3: MinIO k8s（lakehouse-minio + bucket-init Job + ServiceMonitor）

**Files:**
- Create: `lakehouse/minio/k8s/kustomization.yaml`
- Create: `lakehouse/minio/k8s/statefulset.yaml`
- Create: `lakehouse/minio/k8s/service.yaml`
- Create: `lakehouse/minio/k8s/servicemonitor.yaml`
- Create: `lakehouse/minio/k8s/bucket-init-job.yaml`

**Interfaces:**
- Consumes: Task 1 Secret `minio-root`（data ns）。
- Produces: `http://lakehouse-minio.data.svc:9000`（S3 API）+ `bronze`/`silver` bucket（PostSync 自校）+ MinIO Prometheus 指標（`up{job}` 供 Task 13 `LakehouseComponentDown`）。Task 4 Application source 指向本目錄；Task 6 boto3、Task 8 Spark S3A、Task 9 pyiceberg 全打此 endpoint。

- [ ] **Step 1: 建 kustomization.yaml**

Create `lakehouse/minio/k8s/kustomization.yaml`：
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: data
resources:
  - statefulset.yaml
  - service.yaml
  - servicemonitor.yaml
  - bucket-init-job.yaml
```

- [ ] **Step 2: 建 statefulset.yaml（單 replica、PVC 模板名 `data` 10Gi 無 storageClassName、指標免 token）**

Create `lakehouse/minio/k8s/statefulset.yaml`：
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: lakehouse-minio
  labels: {app: lakehouse-minio}
spec:
  serviceName: lakehouse-minio
  replicas: 1
  selector:
    matchLabels: {app: lakehouse-minio}
  template:
    metadata:
      labels: {app: lakehouse-minio}
    spec:
      containers:
        - name: minio
          image: minio/minio:RELEASE.2025-09-07T16-13-09Z
          args: ["server", "/data"]
          ports:
            - {containerPort: 9000, name: s3}
          env:
            - name: MINIO_ROOT_USER
              valueFrom: {secretKeyRef: {name: minio-root, key: AWS_ACCESS_KEY_ID}}
            - name: MINIO_ROOT_PASSWORD
              valueFrom: {secretKeyRef: {name: minio-root, key: AWS_SECRET_ACCESS_KEY}}
            - name: MINIO_PROMETHEUS_AUTH_TYPE
              value: "public"   # ServiceMonitor 免 bearer token scrape（單機 demo，ClusterIP 不外露）
          volumeMounts:
            - {name: data, mountPath: /data}
          readinessProbe:
            httpGet: {path: /minio/health/ready, port: s3}
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests: {storage: 10Gi}
```

- [ ] **Step 3: 建 service.yaml 與 servicemonitor.yaml**

Create `lakehouse/minio/k8s/service.yaml`：
```yaml
apiVersion: v1
kind: Service
metadata:
  name: lakehouse-minio
  labels: {app: lakehouse-minio}
spec:
  type: ClusterIP
  selector: {app: lakehouse-minio}
  ports:
    - {name: s3, port: 9000, targetPort: 9000}
```

Create `lakehouse/minio/k8s/servicemonitor.yaml`（供 `LakehouseComponentDown` 的 `up` 指標；path 為 MinIO v2 cluster 指標）：
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: lakehouse-minio
  labels: {app: lakehouse-minio}
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  selector:
    matchLabels: {app: lakehouse-minio}
  endpoints:
    - {port: s3, path: /minio/v2/metrics/cluster, interval: 30s}
```

- [ ] **Step 4: 建 bucket-init Job（ArgoCD PostSync hook、mc 冪等）**

Create `lakehouse/minio/k8s/bucket-init-job.yaml`：
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-bucket-init
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  backoffLimit: 6
  template:
    metadata:
      labels: {app: minio-bucket-init}
    spec:
      restartPolicy: OnFailure
      containers:
        - name: mc
          image: minio/mc:RELEASE.2025-08-13T08-35-41Z
          envFrom:
            - secretRef: {name: minio-root}
          command: ["/bin/sh", "-c"]
          args:
            - >-
              mc alias set local http://lakehouse-minio.data.svc:9000
              "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" &&
              mc mb --ignore-existing local/bronze local/silver
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
```

- [ ] **Step 5: 驗證渲染 + 可攜守門**

```bash
kubectl kustomize lakehouse/minio/k8s | grep -E "image:|kind:" | sort | uniq
grep -rn "storageClassName" lakehouse/minio/k8s && echo "VIOLATION" || echo "portability OK"
```
Expected: 渲染含 `minio/minio:RELEASE.2025-09-07T16-13-09Z`、`minio/mc:RELEASE.2025-08-13T08-35-41Z`；`portability OK`。

- [ ] **Step 6: Commit**

```bash
git add lakehouse/minio/k8s/
git commit -m "部署(lakehouse)：MinIO 單節點 StatefulSet + bucket-init PostSync Job + ServiceMonitor"
```

---

## Task 4: ArgoCD 子 Application — lakehouse-postgres / lakehouse-minio（wave 3）

**Files:**
- Create: `platform/argocd/apps/lakehouse-postgres.yaml`
- Create: `platform/argocd/apps/lakehouse-minio.yaml`

**Interfaces:**
- Consumes: Task 2/3 的 kustomize 目錄。
- Produces: `data` ns 儲存底座被 ArgoCD 接管（wave 3）。root app 掃 `platform/argocd/apps/` 自動接手。

> **勘誤教訓**：kustomize 型 Application **不要寫 `directory:` 欄位**——ArgoCD 會剝掉 default 值欄位造成永久 OutOfSync 迴圈；hello.yaml 的形狀（無 directory）就是正確形狀，照抄。

- [ ] **Step 1: 建 lakehouse-postgres.yaml**

Create `platform/argocd/apps/lakehouse-postgres.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: lakehouse-postgres
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "3"
spec:
  project: default
  source:
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: lakehouse/postgres/k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: data
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 建 lakehouse-minio.yaml**

Create `platform/argocd/apps/lakehouse-minio.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: lakehouse-minio
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "3"
spec:
  project: default
  source:
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: lakehouse/minio/k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: data
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 3: 驗證 YAML + dry-run（M4）**

M1 本機：
```bash
python3 -c "import yaml; [list(yaml.safe_load_all(open(f))) for f in ['platform/argocd/apps/lakehouse-postgres.yaml','platform/argocd/apps/lakehouse-minio.yaml']]; print('YAML OK')"
grep -n "directory:" platform/argocd/apps/lakehouse-*.yaml && echo "VIOLATION（勿寫 directory 欄）" || echo "no directory field OK"
```
（M4）：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl apply --dry-run=client -f platform/argocd/apps/lakehouse-postgres.yaml -f platform/argocd/apps/lakehouse-minio.yaml
```
Expected: `YAML OK`；`no directory field OK`；dry-run 兩個 created。

- [ ] **Step 4: Commit**

```bash
git add platform/argocd/apps/lakehouse-postgres.yaml platform/argocd/apps/lakehouse-minio.yaml
git commit -m "部署(platform)：ArgoCD 子 app lakehouse-postgres + lakehouse-minio（wave 3）"
```

---

## Task 5: ArgoCD 子 Application — spark-operator（wave 4，Helm + RBAC 多源）

**Files:**
- Create: `platform/argocd/apps/spark-operator.yaml`

**Interfaces:**
- Consumes: kubeflow chart repo；Task 11 的 `lakehouse/spark/k8s/`（rbac.yaml，多源第二 source——**本 task 先寫 Application，Task 11 補齊該目錄後才可完整 sync**；在此之前該 source 是空目錄、ArgoCD 容忍）。
- Produces: spark-operator controller（`spark-operator` ns）+ `data` ns 的 job 側 SA `spark-operator-spark` + Airflow worker 對 SparkApplication 的 RBAC。Task 8 模板的 CRD/SA 依賴它。

> 設計 §2 只允許 5 個新 Application，而 `lakehouse/spark/k8s/rbac.yaml` 需要 GitOps 交付——用 ArgoCD **多源 Application**（`sources:`）讓 RBAC 隨 spark-operator app 一起收斂（語意也對：Spark 執行面的權限跟著 operator 走）。見 Self-Review 歧義 #4。CRD 巨大 → `ServerSideApply=true`（與 P0 kube-prometheus-stack 同型雷）。

- [ ] **Step 1: 建 spark-operator.yaml**

Create `platform/argocd/apps/spark-operator.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: spark-operator
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "4"
spec:
  project: default
  sources:
    - repoURL: https://kubeflow.github.io/spark-operator
      chart: spark-operator
      targetRevision: 2.5.1
      helm:
        valuesObject:
          spark:
            jobNamespaces: [data]
          controller:
            resources:
              requests: {cpu: 100m, memory: 200Mi}
              limits: {cpu: 500m, memory: 512Mi}
    - repoURL: https://github.com/fergusKe/trend-intelligence-platform
      targetRevision: main
      path: lakehouse/spark/k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: spark-operator
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 先放 rbac 目錄佔位（避免多源 path 不存在導致 app Degraded；真 rbac.yaml 在 Task 11）**

```bash
mkdir -p lakehouse/spark/k8s
touch lakehouse/spark/k8s/.gitkeep
```

- [ ] **Step 3: 驗證 YAML + dry-run（M4）**

M1 本機：
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/spark-operator.yaml'))); print('YAML OK')"
```
（M4）：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl apply --dry-run=client -f platform/argocd/apps/spark-operator.yaml
```
Expected: `YAML OK`；dry-run created。

- [ ] **Step 4: Commit**

```bash
git add platform/argocd/apps/spark-operator.yaml lakehouse/spark/k8s/.gitkeep
git commit -m "部署(platform)：ArgoCD 子 app spark-operator（Helm 2.5.1 多源含 spark RBAC，wave 4，SSA）"
```

---

## Task 6: `ingestion/youtube` 純 Python 套件（TDD）

**Files:**
- Create: `ingestion/youtube/pyproject.toml`
- Create: `ingestion/youtube/src/yt_ingest/__init__.py`
- Create: `ingestion/youtube/src/yt_ingest/client.py`
- Create: `ingestion/youtube/src/yt_ingest/bronze.py`
- Create: `ingestion/youtube/src/yt_ingest/categories.py`
- Create: `ingestion/youtube/tests/test_client.py`
- Create: `ingestion/youtube/tests/test_bronze.py`
- Create: `ingestion/youtube/tests/test_categories.py`

**Interfaces:**
- Produces: `yt_ingest.client.YouTubeClient`（`fetch_trending(region, max_results)` / `fetch_categories(region)`，403 quota → `QuotaExceededError`）、`yt_ingest.bronze.bronze_key()` / `write_bronze()`（決定性 key + `_metadata` 信封）、`yt_ingest.categories.upsert_categories()`。Task 7 Dockerfile 安裝本套件；Task 9 DAG import 這些函式。
- **依賴邊界（design §3 seam）**：本套件**不 import airflow**——quota fail-fast 以自訂 `QuotaExceededError` 表達，由 DAG 層 map 成 `AirflowFailException`（套件可獨立測試、可攜）。

- [ ] **Step 1: 建 pyproject.toml**

Create `ingestion/youtube/pyproject.toml`：
```toml
[project]
name = "yt-ingest"
version = "0.1.0"
description = "YouTube trending ingestion (bronze layer + categories dim)"
requires-python = ">=3.12"
dependencies = [
    "httpx==0.28.1",
    "boto3==1.40.0",
    "psycopg2-binary==2.9.10",
]

[dependency-groups]
dev = [
    "pytest==9.1.1",
    "ruff==0.15.20",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/yt_ingest"]
```

- [ ] **Step 2: 先寫失敗測試——client（httpx MockTransport：200 / 403 quota / 500）**

Create `ingestion/youtube/src/yt_ingest/__init__.py`（空檔）。

Create `ingestion/youtube/tests/test_client.py`：
```python
import httpx
import pytest

from yt_ingest.client import QuotaExceededError, YouTubeAPIError, YouTubeClient


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return YouTubeClient(api_key="test-key", transport=transport)


def test_fetch_trending_returns_raw_response():
    def handler(request):
        assert request.url.params["chart"] == "mostPopular"
        assert request.url.params["regionCode"] == "TW"
        assert request.url.params["maxResults"] == "50"
        assert request.url.params["part"] == "snippet,statistics,contentDetails"
        assert request.url.params["key"] == "test-key"
        return httpx.Response(200, json={"items": [{"id": "vid1"}]})

    resp = make_client(handler).fetch_trending(region="TW", max_results=50)
    assert resp == {"items": [{"id": "vid1"}]}


def test_quota_exceeded_raises_dedicated_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "quotaExceeded"}], "code": 403}
        })

    with pytest.raises(QuotaExceededError):
        make_client(handler).fetch_trending(region="TW")


def test_daily_limit_exceeded_raises_dedicated_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "dailyLimitExceeded"}], "code": 403}
        })

    with pytest.raises(QuotaExceededError):
        make_client(handler).fetch_trending(region="TW")


def test_server_error_raises_retryable_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(YouTubeAPIError):  # 讓 Airflow retry 機制接手
        make_client(handler).fetch_trending(region="TW")


def test_forbidden_non_quota_is_retryable_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "forbidden"}], "code": 403}
        })

    with pytest.raises(YouTubeAPIError):
        make_client(handler).fetch_trending(region="TW")


def test_fetch_categories():
    def handler(request):
        assert request.url.path.endswith("/videoCategories")
        assert request.url.params["regionCode"] == "JP"
        return httpx.Response(200, json={"items": [{"id": "10", "snippet": {"title": "Music"}}]})

    resp = make_client(handler).fetch_categories(region="JP")
    assert resp["items"][0]["id"] == "10"
```

- [ ] **Step 3: 失敗測試——bronze（key 決定性 + 信封欄位）與 categories（fake conn upsert）**

Create `ingestion/youtube/tests/test_bronze.py`：
```python
import json
from datetime import datetime, timezone

from yt_ingest.bronze import bronze_key, build_envelope, write_bronze


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})


LOGICAL = datetime(2026, 7, 8, 14, 0, 0, tzinfo=timezone.utc)
INGESTED = datetime(2026, 7, 8, 14, 3, 21, tzinfo=timezone.utc)


def test_bronze_key_is_deterministic_from_logical_hour():
    key = bronze_key("youtube_trending", "TW", LOGICAL)
    assert key == "youtube_trending/region=TW/date=2026-07-08/hour=14/snapshot.json"
    # 同 logical hour 重算 = 同 key（重跑覆寫 = 冪等）
    assert bronze_key("youtube_trending", "TW", LOGICAL) == key


def test_categories_key_layout():
    key = bronze_key("youtube_categories", "TW", LOGICAL, filename="categories.json", with_hour=False)
    assert key == "youtube_categories/region=TW/date=2026-07-08/categories.json"


def test_envelope_fields():
    env = build_envelope({"items": []}, region="TW", logical_hour=LOGICAL, ingested_at=INGESTED)
    md = env["_metadata"]
    assert md["region"] == "TW"
    assert md["logical_hour"] == "2026-07-08T14:00:00+00:00"
    assert md["ingestion_id"] == "TW_2026070814"
    assert md["ingested_at"] == "2026-07-08T14:03:21+00:00"
    assert md["source"] == "youtube_data_api_v3"
    assert env["response"] == {"items": []}


def test_write_bronze_puts_envelope_to_bucket():
    s3 = FakeS3()
    key = write_bronze(
        response={"items": [1]}, region="TW", logical_hour=LOGICAL, ingested_at=INGESTED,
        bucket="bronze", s3_client=s3,
    )
    assert key == "youtube_trending/region=TW/date=2026-07-08/hour=14/snapshot.json"
    put = s3.puts[0]
    assert put["Bucket"] == "bronze"
    assert put["ContentType"] == "application/json"
    body = json.loads(put["Body"])
    assert body["_metadata"]["ingestion_id"] == "TW_2026070814"
    assert body["response"] == {"items": [1]}
```

Create `ingestion/youtube/tests/test_categories.py`：
```python
from yt_ingest.categories import CATEGORIES_DDL, CATEGORIES_UPSERT, rows_from_response, upsert_categories


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.executed.append((sql, rows))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


RESP = {"items": [
    {"id": "10", "snippet": {"title": "Music"}},
    {"id": "20", "snippet": {"title": "Gaming"}},
]}


def test_rows_from_response():
    rows = rows_from_response(RESP, region="TW", updated_at="2026-07-08T00:00:00+00:00")
    assert rows == [
        ("10", "TW", "Music", "2026-07-08T00:00:00+00:00"),
        ("20", "TW", "Gaming", "2026-07-08T00:00:00+00:00"),
    ]


def test_upsert_executes_ddl_then_upsert_and_commits():
    conn = FakeConn()
    n = upsert_categories(conn, RESP, region="TW", updated_at="2026-07-08T00:00:00+00:00")
    assert n == 2
    sqls = [e[0] for e in conn.cur.executed]
    assert sqls[0] == CATEGORIES_DDL
    assert sqls[1] == CATEGORIES_UPSERT
    assert conn.committed


def test_ddl_and_upsert_shapes():
    assert "silver.youtube_categories" in CATEGORIES_DDL
    assert "PRIMARY KEY (category_id, region)" in CATEGORIES_DDL
    assert "ON CONFLICT (category_id, region) DO UPDATE" in CATEGORIES_UPSERT
```

- [ ] **Step 4: 跑測試確認失敗**

```bash
cd ingestion/youtube && uv lock && uv sync && uv run pytest tests/ -v
```
Expected: FAIL — `ModuleNotFoundError`（實作未建）。

- [ ] **Step 5: 實作 client.py**

Create `ingestion/youtube/src/yt_ingest/client.py`：
```python
"""YouTube Data API v3 client（httpx，顯式 timeout，錯誤分類）。

錯誤語意（design §3）：
- 403 且 reason ∈ {quotaExceeded, dailyLimitExceeded} → QuotaExceededError（DAG 層 map 成
  AirflowFailException fail-fast，不重試——重試燒 quota 又必然再失敗）
- 其他非 2xx → YouTubeAPIError（交給 Airflow retry：3 次 exponential backoff）
本模組不得 import airflow（套件獨立可測、可攜）。
"""
from __future__ import annotations

import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


class YouTubeAPIError(Exception):
    """非 quota 的 API/網路錯誤（可重試）。"""


class QuotaExceededError(Exception):
    """每日 quota 用罄（不可重試，fail-fast）。"""


class YouTubeClient:
    def __init__(self, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport)

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._client.get(path, params={**params, "key": self._api_key})
        except httpx.HTTPError as exc:
            raise YouTubeAPIError(f"HTTP error calling {path}: {exc}") from exc
        if resp.status_code == 403:
            reasons = {
                e.get("reason")
                for e in resp.json().get("error", {}).get("errors", [])
            }
            if reasons & QUOTA_REASONS:
                raise QuotaExceededError(f"quota exhausted: reasons={sorted(reasons)}")
            raise YouTubeAPIError(f"403 non-quota: reasons={sorted(reasons)}")
        if resp.status_code != 200:
            raise YouTubeAPIError(f"{path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def fetch_trending(self, region: str, max_results: int = 50) -> dict:
        return self._get("/videos", {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region,
            "maxResults": str(max_results),
        })

    def fetch_categories(self, region: str) -> dict:
        return self._get("/videoCategories", {"part": "snippet", "regionCode": region})
```

- [ ] **Step 6: 實作 bronze.py**

Create `ingestion/youtube/src/yt_ingest/bronze.py`：
```python
"""Bronze 寫入（boto3 put_object，決定性 key + _metadata 信封）。

key 由 Airflow logical_date 導出（非 now()）：重跑同 task = 覆寫同物件 = 冪等（design §3）。
"""
from __future__ import annotations

import json
from datetime import datetime


def bronze_key(prefix: str, region: str, logical_hour: datetime,
               filename: str = "snapshot.json", with_hour: bool = True) -> str:
    parts = [prefix, f"region={region}", f"date={logical_hour:%Y-%m-%d}"]
    if with_hour:
        parts.append(f"hour={logical_hour:%H}")
    parts.append(filename)
    return "/".join(parts)


def build_envelope(response: dict, region: str, logical_hour: datetime, ingested_at: datetime) -> dict:
    return {
        "_metadata": {
            "region": region,
            "logical_hour": logical_hour.isoformat(),
            "ingestion_id": f"{region}_{logical_hour:%Y%m%d%H}",
            "ingested_at": ingested_at.isoformat(),
            "source": "youtube_data_api_v3",
        },
        "response": response,
    }


def make_s3_client(endpoint_url: str | None = None):
    import boto3  # 延遲 import：測試用 FakeS3 不需要 boto3 連線

    return boto3.client("s3", endpoint_url=endpoint_url)


def write_bronze(response: dict, region: str, logical_hour: datetime, ingested_at: datetime,
                 bucket: str, s3_client=None, endpoint_url: str | None = None,
                 prefix: str = "youtube_trending", filename: str = "snapshot.json",
                 with_hour: bool = True) -> str:
    s3 = s3_client if s3_client is not None else make_s3_client(endpoint_url)
    key = bronze_key(prefix, region, logical_hour, filename=filename, with_hour=with_hour)
    body = json.dumps(build_envelope(response, region, logical_hour, ingested_at),
                      ensure_ascii=False)
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"),
                  ContentType="application/json")
    return key
```

- [ ] **Step 7: 實作 categories.py（DDL 與 §6a `silver.youtube_categories` 逐欄一致）**

Create `ingestion/youtube/src/yt_ingest/categories.py`：
```python
"""Categories 維度 → Postgres silver.youtube_categories UPSERT（維度小，不過 Spark/Iceberg——刻意決定，design §3）。"""
from __future__ import annotations

CATEGORIES_DDL = """CREATE TABLE IF NOT EXISTS silver.youtube_categories (
    category_id text NOT NULL,
    region text NOT NULL,
    category_name text,
    updated_at timestamptz,
    PRIMARY KEY (category_id, region)
)"""

CATEGORIES_UPSERT = """INSERT INTO silver.youtube_categories (category_id, region, category_name, updated_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (category_id, region) DO UPDATE SET
    category_name = EXCLUDED.category_name,
    updated_at = EXCLUDED.updated_at"""


def rows_from_response(response: dict, region: str, updated_at: str) -> list[tuple]:
    return [
        (item["id"], region, item.get("snippet", {}).get("title"), updated_at)
        for item in response.get("items", [])
    ]


def upsert_categories(conn, response: dict, region: str, updated_at: str) -> int:
    rows = rows_from_response(response, region, updated_at)
    with conn.cursor() as cur:
        cur.execute(CATEGORIES_DDL)
        cur.executemany(CATEGORIES_UPSERT, rows)
    conn.commit()
    return len(rows)


def connect(dsn: str):
    import psycopg2  # 延遲 import：單元測試用 FakeConn

    return psycopg2.connect(dsn)
```

- [ ] **Step 8: 跑測試確認綠 + lint**

```bash
cd ingestion/youtube && uv run pytest tests/ -v && uv run ruff check .
```
Expected: 全 passed（client 6 + bronze 4 + categories 3）；`All checks passed!`。

- [ ] **Step 9: Commit**

```bash
git add ingestion/youtube/
git commit -m "功能(ingestion)：yt_ingest 套件（httpx client quota fail-fast + bronze 決定性 key 信封 + categories UPSERT，TDD）"
```

---

## Task 7: Airflow 自訂 image + airflow-ci workflow

**Files:**
- Create: `orchestration/airflow/Dockerfile`
- Create: `.github/workflows/airflow-ci.yaml`

**Interfaces:**
- Consumes: Task 6 `yt_ingest` 套件（build context = repo root）。
- Produces: image `ghcr.io/ferguske/trend-intelligence-platform/airflow:sha-*`（含 yt_ingest + pyiceberg + psycopg2；`cncf-kubernetes` provider base 已內建）；CI bump `platform/argocd/apps/airflow.yaml` 的 `.spec.source.helm.valuesObject.images.airflow.tag`（Task 10 建該檔，首推前 bump 步驟會 fail——執行順序上 Task 10 檔案先進 repo 才推 main，見 Task 15）。

- [ ] **Step 1: 建 Dockerfile（build context = repo root）**

Create `orchestration/airflow/Dockerfile`：
```dockerfile
FROM apache/airflow:3.2.2
# build context = repo root（CI 的 context: "."）；yt_ingest 套件整包安裝
COPY ingestion/youtube /opt/yt_ingest
RUN pip install --no-cache-dir /opt/yt_ingest \
    "pyiceberg[s3fs,sql-postgres]==0.11.1" \
    "psycopg2-binary==2.9.10" \
    "httpx==0.28.1" \
    "boto3==1.40.0"
# DAG 不烤進 image（git-sync 送達）；cncf-kubernetes provider base image 已內建
```

- [ ] **Step 2: 本機 build + import 冒煙**

```bash
docker build -f orchestration/airflow/Dockerfile -t airflow-local:test .
docker run --rm airflow-local:test python -c "import yt_ingest.client, yt_ingest.bronze, yt_ingest.categories, pyiceberg, psycopg2, boto3; print('imports OK')"
```
Expected: build 成功；`imports OK`。

- [ ] **Step 3: 建 airflow-ci.yaml（複製 hello-ci 模式；test job 含 DagBag import 故需裝 airflow + constraints）**

Create `.github/workflows/airflow-ci.yaml`：
```yaml
name: airflow-ci
on:
  push:
    branches: [main]
    paths:
      - "ingestion/**"
      - "orchestration/airflow/Dockerfile"
      # 刻意不含 orchestration/airflow/dags/**（DAG 走 git-sync 即生效，不 rebuild image）
      # 刻意不含 platform/argocd/apps/airflow.yaml（bump 落點）→ 迴圈防護
  workflow_dispatch: {}
concurrency:
  group: airflow-ci
  cancel-in-progress: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - name: ingest 單元測試
        run: |
          uv sync
          uv run ruff check .
          uv run pytest tests/ -v
        working-directory: ingestion/youtube
      - name: DagBag import 測試（airflow + constraints）
        run: |
          uv venv /tmp/af-venv
          source /tmp/af-venv/bin/activate
          uv pip install "apache-airflow==3.2.2" "apache-airflow-providers-cncf-kubernetes" \
            --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.2.2/constraints-3.12.txt"
          uv pip install ./ingestion/youtube "pytest==9.1.1" "pyyaml==6.0.3"
          pytest orchestration/airflow/tests/ -v

  build-push-bump:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v7
      - id: vars
        run: |
          echo "TAG=sha-$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
          echo "IMAGE=ghcr.io/$(echo '${{ github.repository }}' | tr '[:upper:]' '[:lower:]')/airflow" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-qemu-action@v4
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: .
          file: orchestration/airflow/Dockerfile
          platforms: linux/amd64,linux/arm64   # arm64 必備（M4 kind 節點；勘誤 §F）
          push: true
          tags: |
            ${{ steps.vars.outputs.IMAGE }}:${{ steps.vars.outputs.TAG }}
            ${{ steps.vars.outputs.IMAGE }}:latest
      - name: Bump manifest tag（GitOps 交棒點）
        run: |
          yq -i '.spec.source.helm.valuesObject.images.airflow.tag = "${{ steps.vars.outputs.TAG }}"' platform/argocd/apps/airflow.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add platform/argocd/apps/airflow.yaml
          git commit -m "ci(airflow): bump image to ${{ steps.vars.outputs.TAG }} [skip ci]"
          git pull --rebase origin main
          git push origin main
```

- [ ] **Step 4: 驗證 workflow YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/airflow-ci.yaml')); print('workflow YAML OK')"
```
Expected: `workflow YAML OK`。

- [ ] **Step 5: Commit**

```bash
git add orchestration/airflow/Dockerfile .github/workflows/airflow-ci.yaml
git commit -m "整合(ci)：airflow 自訂 image（yt_ingest+pyiceberg）+ airflow-ci（test→GHCR→bump airflow.yaml）"
```

---

## Task 8: DAG config 單一真源 + SparkApplication 模板

**Files:**
- Create: `orchestration/airflow/dags/config/pipeline.yaml`
- Create: `orchestration/airflow/dags/config/images.yaml`
- Create: `orchestration/airflow/dags/templates/spark_silver.yaml`

**Interfaces:**
- Consumes: §2 資源名合約（endpoint/SA/catalog URI）；Task 0 C2 校準的 SA 名。
- Produces: `pipeline.yaml`（regions 等常數唯一真源，DAG 讀它、dbt accepted_values 靠 pytest 對帳）；`images.yaml`（spark-ci/dbt-ci 的 bump 落點，git-sync 送達）；`spark_silver.yaml`（SparkKubernetesOperator 的 Jinja 模板，單檔同時服務 hourly 與 reprocess 兩模式——見 Self-Review 歧義 #5）。

- [ ] **Step 1: 建 pipeline.yaml（design §3 確切形狀）**

Create `orchestration/airflow/dags/config/pipeline.yaml`：
```yaml
regions: [TW, JP, KR, HK, US, GB, SG, AU]
max_results: 50
bronze_bucket: bronze
s3_endpoint: http://lakehouse-minio.data.svc:9000
```

- [ ] **Step 2: 建 images.yaml（CI bump 檔；初始佔位 tag）**

Create `orchestration/airflow/dags/config/images.yaml`：
```yaml
spark_job:
  repository: ghcr.io/ferguske/trend-intelligence-platform/spark-jobs
  tag: sha-0000000   # spark-ci bump
dbt:
  repository: ghcr.io/ferguske/trend-intelligence-platform/dbt
  tag: sha-0000000   # dbt-ci bump
```

- [ ] **Step 3: 建 spark_silver.yaml 模板（design §5 全規格）**

Create `orchestration/airflow/dags/templates/spark_silver.yaml`：
```yaml
# SparkKubernetesOperator Jinja 模板（.yaml 在 template_ext 內，runtime 渲染）。
# 兩模式：hourly（無 start_hour param → 用 data_interval_start）；reprocess（params.start_hour/end_hour）。
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
metadata:
  {%- if params.start_hour is defined and params.start_hour %}
  name: yt-silver-rp-{{ ts_nodash | lower }}
  {%- else %}
  name: yt-silver-{{ data_interval_start.strftime('%Y%m%d%H') }}
  {%- endif %}
  namespace: data
spec:
  type: Python
  pythonVersion: "3"
  mode: cluster
  image: "{{ params.spark_image }}"
  imagePullPolicy: IfNotPresent
  mainApplicationFile: local:///opt/spark/jobs/silver_job.py
  arguments:
  {%- if params.start_hour is defined and params.start_hour %}
    - --start-hour
    - "{{ params.start_hour }}"
    - --end-hour
    - "{{ params.end_hour }}"
  {%- else %}
    - --date
    - "{{ data_interval_start.strftime('%Y-%m-%d') }}"
    - --hour
    - "{{ data_interval_start.strftime('%H') }}"
  {%- endif %}
  sparkVersion: "4.0.2"
  restartPolicy:
    type: Never          # 重試由 Airflow task 層負責，不雙層重試
  timeToLiveSeconds: 3600
  sparkConf:
    # Iceberg JDBC catalog（§4 合約；catalog 名 lakehouse）
    spark.sql.catalog.lakehouse: org.apache.iceberg.spark.SparkCatalog
    spark.sql.catalog.lakehouse.type: jdbc
    spark.sql.catalog.lakehouse.uri: jdbc:postgresql://lakehouse-postgres.data.svc:5432/lakehouse
    spark.sql.catalog.lakehouse.jdbc.user: pipeline_writer
    spark.sql.catalog.lakehouse.jdbc.password: "{{ params.pg_password }}"
    spark.sql.catalog.lakehouse.warehouse: s3a://silver/warehouse
    spark.sql.defaultCatalog: lakehouse
    # S3A → MinIO（憑證走 env，見 envFrom）
    spark.hadoop.fs.s3a.endpoint: http://lakehouse-minio.data.svc:9000
    spark.hadoop.fs.s3a.path.style.access: "true"
    spark.hadoop.fs.s3a.connection.ssl.enabled: "false"
    spark.hadoop.fs.s3a.aws.credentials.provider: com.amazonaws.auth.EnvironmentVariableCredentialsProvider
    spark.sql.session.timeZone: UTC
  driver:
    cores: 1
    memory: 1536m
    serviceAccount: spark-operator-spark
    envFrom:
      - secretRef: {name: minio-root}
  executor:
    instances: 1
    cores: 1
    memory: 1536m
    serviceAccount: spark-operator-spark
    envFrom:
      - secretRef: {name: minio-root}
```
> `params.pg_password` 由 DAG 從 `LAKEHOUSE_PG_DSN` env 解出注入（Iceberg JDBC catalog 無 env 讀取機制；密碼會出現在 rendered CRD spec——data ns 內、demo 規模可接受，README known-limit 註記，見 Self-Review 歧義 #7）。

- [ ] **Step 4: 驗證（模板渲染冒煙——本地 Jinja 渲染兩模式後 YAML parse）**

```bash
python3 - <<'PY'
import yaml
from datetime import datetime
from jinja2 import Template

src = open('orchestration/airflow/dags/templates/spark_silver.yaml').read()
ctx_common = {"data_interval_start": datetime(2026, 7, 8, 14), "ts_nodash": "20260708T140000"}
# hourly 模式
r1 = Template(src).render(params={"spark_image": "img:sha-abc", "pg_password": "pw"}, **ctx_common)
d1 = yaml.safe_load(r1)
assert d1["metadata"]["name"] == "yt-silver-2026070814", d1["metadata"]["name"]
assert d1["spec"]["arguments"] == ["--date", "2026-07-08", "--hour", "14"]
# reprocess 模式
r2 = Template(src).render(params={"spark_image": "img:sha-abc", "pg_password": "pw",
                                  "start_hour": "2026-07-08T10", "end_hour": "2026-07-08T14"}, **ctx_common)
d2 = yaml.safe_load(r2)
assert d2["metadata"]["name"] == "yt-silver-rp-20260708t140000"
assert d2["spec"]["arguments"][0] == "--start-hour"
assert d1["spec"]["driver"]["serviceAccount"] == "spark-operator-spark"
print("template renders OK (hourly + reprocess)")
PY
python3 -c "import yaml; yaml.safe_load(open('orchestration/airflow/dags/config/pipeline.yaml')); yaml.safe_load(open('orchestration/airflow/dags/config/images.yaml')); print('configs YAML OK')"
```
Expected: `template renders OK (hourly + reprocess)`；`configs YAML OK`。（本機需 `pip install jinja2 pyyaml` 或用 `uv run --with jinja2,pyyaml python3`。）

- [ ] **Step 5: Commit**

```bash
git add orchestration/airflow/dags/config/ orchestration/airflow/dags/templates/
git commit -m "功能(orchestration)：pipeline.yaml 單一真源 + images.yaml bump 檔 + SparkApplication 雙模式模板"
```

---

## Task 9: 三條 DAG + DAG 測試（TDD）

**Files:**
- Create: `orchestration/airflow/dags/yt_trending_hourly.py`
- Create: `orchestration/airflow/dags/yt_categories_daily.py`
- Create: `orchestration/airflow/dags/yt_reprocess_range.py`
- Create: `orchestration/airflow/tests/test_dags.py`

**Interfaces:**
- Consumes: Task 6 `yt_ingest`、Task 8 config/模板、env 注入合約（`YOUTUBE_API_KEY`/`AWS_*`/`LAKEHOUSE_PG_DSN`）。
- Produces: `yt_trending_hourly`（ingest ×8 → delete_stale → spark → load → dbt_run → dbt_test）、`yt_categories_daily`（@daily ×8 → bronze + UPSERT）、`yt_reprocess_range`（手動，範圍重處理）。loader 持有的 silver DDL 與 §6a 逐欄一致（= dbt source）。
- **DAG 層契約**：default_args `retries=3, retry_delay=1min, exponential, max 10min`；`catchup=False`、`max_active_runs=1`、`dagrun_timeout=45min`、task `execution_timeout=10min`；quota → `AirflowFailException`；spark 上游 `trigger_rule="all_done"`。

- [ ] **Step 1: 先寫失敗測試**

Create `orchestration/airflow/tests/test_dags.py`：
```python
"""DagBag import + 依賴鏈 + 守門 + config 一致性（design §11）。"""
import re
from pathlib import Path

import yaml
from airflow.models import DagBag

REPO_ROOT = Path(__file__).resolve().parents[3]
DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


def _bag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


def test_dagbag_imports_clean():
    bag = _bag()
    assert bag.import_errors == {}, bag.import_errors
    assert {"yt_trending_hourly", "yt_categories_daily", "yt_reprocess_range"} <= set(bag.dags)


def test_hourly_guards():
    dag = _bag().dags["yt_trending_hourly"]
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout.total_seconds() == 45 * 60
    assert dag.default_args["retries"] == 3
    assert dag.default_args["retry_exponential_backoff"] is True


def test_hourly_dependency_chain():
    dag = _bag().dags["yt_trending_hourly"]
    ids = set(dag.task_ids)
    assert {"ingest_trending", "delete_stale_sparkapp", "spark_bronze_to_silver",
            "load_silver_to_postgres", "dbt_run", "dbt_test"} <= ids
    get = dag.get_task
    assert "delete_stale_sparkapp" in [t.task_id for t in get("ingest_trending").downstream_list]
    assert "spark_bronze_to_silver" in [t.task_id for t in get("delete_stale_sparkapp").downstream_list]
    assert "load_silver_to_postgres" in [t.task_id for t in get("spark_bronze_to_silver").downstream_list]
    assert "dbt_run" in [t.task_id for t in get("load_silver_to_postgres").downstream_list]
    assert "dbt_test" in [t.task_id for t in get("dbt_run").downstream_list]
    # 部分 region 失敗不擋批：mapped ingest 之後第一個匯聚 task 是 all_done
    assert str(get("delete_stale_sparkapp").trigger_rule) == "all_done"


def test_categories_and_reprocess_guards():
    bag = _bag()
    daily = bag.dags["yt_categories_daily"]
    assert daily.catchup is False
    rp = bag.dags["yt_reprocess_range"]
    assert rp.schedule is None or str(rp.schedule) == "None"
    assert {"start_hour", "end_hour"} <= set(rp.params)


def test_regions_single_source_of_truth_vs_dbt():
    pipeline = yaml.safe_load((DAGS_DIR / "config" / "pipeline.yaml").read_text())
    regions = pipeline["regions"]
    assert regions == ["TW", "JP", "KR", "HK", "US", "GB", "SG", "AU"]
    schema = yaml.safe_load(
        (REPO_ROOT / "lakehouse" / "dbt" / "models" / "staging" / "_staging_schema.yml").read_text()
    )
    stg = next(m for m in schema["models"] if m["name"] == "stg_video_snapshots")
    region_col = next(c for c in stg["columns"] if c["name"] == "region")
    accepted = next(t for t in region_col["data_tests"] if isinstance(t, dict) and "accepted_values" in t)
    assert accepted["accepted_values"]["values"] == regions, "pipeline.yaml regions 與 dbt accepted_values 漂移"
```
> 跑法（M1，本機 venv 裝 airflow + constraints——與 airflow-ci test job 同款）：
```bash
uv venv /tmp/af-venv && source /tmp/af-venv/bin/activate
uv pip install "apache-airflow==3.2.2" "apache-airflow-providers-cncf-kubernetes" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.2.2/constraints-3.12.txt"
uv pip install ./ingestion/youtube "pytest==9.1.1" "pyyaml==6.0.3"
pytest orchestration/airflow/tests/ -v
```
Expected: FAIL（DAG 檔尚未建；`test_regions_...` 亦因 dbt schema 未建而 fail——該測試在 Task 12 後才全綠，本 task 結束時允許唯一這條 fail，Task 12 Step 9 回頭驗）。

- [ ] **Step 2: 建主 DAG yt_trending_hourly.py**

Create `orchestration/airflow/dags/yt_trending_hourly.py`：
```python
"""主管線：ingest ×8（動態映射）→ Spark Bronze→Silver → loader → dbt run → dbt test（DQ gate）。"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pendulum
import yaml
from airflow.exceptions import AirflowFailException
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from airflow.providers.cncf.kubernetes.secret import Secret
from airflow.sdk import DAG, get_current_context, task

CONFIG_DIR = Path(__file__).parent / "config"
PIPELINE = yaml.safe_load((CONFIG_DIR / "pipeline.yaml").read_text())
IMAGES = yaml.safe_load((CONFIG_DIR / "images.yaml").read_text())

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=10),
}


def _pg_password() -> str:
    """從 LAKEHOUSE_PG_DSN 解出密碼（模板 params.pg_password 用；無 env 時回空字串讓 DagBag import 可過）。"""
    dsn = os.environ.get("LAKEHOUSE_PG_DSN", "")
    if not dsn:
        return ""
    return unquote(urlsplit(dsn).password or "")


@task
def ingest_trending(region: str) -> str:
    from yt_ingest.bronze import write_bronze
    from yt_ingest.client import QuotaExceededError, YouTubeClient

    ctx = get_current_context()
    logical_hour = ctx["data_interval_start"]
    client = YouTubeClient(api_key=os.environ["YOUTUBE_API_KEY"])
    try:
        resp = client.fetch_trending(region=region, max_results=PIPELINE["max_results"])
    except QuotaExceededError as exc:
        # fail-fast：重試燒 quota 又必然再失敗（design §3）
        raise AirflowFailException(f"YouTube quota exhausted for {region}: {exc}") from exc
    return write_bronze(
        response=resp, region=region, logical_hour=logical_hour,
        ingested_at=pendulum.now("UTC"),
        bucket=PIPELINE["bronze_bucket"], endpoint_url=PIPELINE["s3_endpoint"],
    )


@task(trigger_rule="all_done")
def delete_stale_sparkapp():
    """重跑同 logical hour 先刪同名舊 SparkApplication（operator 對同名 apply 會拒，design §5）。"""
    from kubernetes import client, config

    ctx = get_current_context()
    name = "yt-silver-" + ctx["data_interval_start"].strftime("%Y%m%d%H")
    config.load_incluster_config()
    api = client.CustomObjectsApi()
    try:
        api.delete_namespaced_custom_object(
            group="sparkoperator.k8s.io", version="v1beta2",
            namespace="data", plural="sparkapplications", name=name,
        )
    except client.exceptions.ApiException as exc:
        if exc.status != 404:  # 404 = 無舊 app，正常
            raise


SILVER_DDL = """CREATE TABLE IF NOT EXISTS silver.video_snapshots (
    video_id text NOT NULL,
    region text NOT NULL,
    captured_at timestamptz NOT NULL,
    title text,
    description text,
    tags text,
    channel_id text,
    channel_title text,
    category_id text,
    published_at timestamptz,
    views bigint,
    likes bigint,
    comment_count bigint,
    like_ratio double precision,
    engagement_rate double precision,
    thumbnail_url text,
    ingestion_id text,
    ingested_at timestamptz,
    PRIMARY KEY (video_id, region, captured_at)
)"""

SILVER_COLUMNS = [
    "video_id", "region", "captured_at", "title", "description", "tags",
    "channel_id", "channel_title", "category_id", "published_at",
    "views", "likes", "comment_count", "like_ratio", "engagement_rate",
    "thumbnail_url", "ingestion_id", "ingested_at",
]

SILVER_UPSERT = f"""INSERT INTO silver.video_snapshots ({", ".join(SILVER_COLUMNS)}) VALUES %s
ON CONFLICT (video_id, region, captured_at) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in SILVER_COLUMNS if c not in ("video_id", "region", "captured_at"))}"""


def load_hours_to_postgres(start, end) -> int:
    """pyiceberg 掃 [start, end]（UTC 小時）→ psycopg2 execute_values UPSERT（ga4 extractor 模式）。"""
    import psycopg2
    from psycopg2.extras import execute_values
    from pyiceberg.catalog import load_catalog
    from pyiceberg.expressions import And, GreaterThanOrEqual, LessThanOrEqual

    dsn = os.environ["LAKEHOUSE_PG_DSN"]
    catalog = load_catalog(
        "lakehouse",
        **{
            "type": "sql",
            "uri": dsn.replace("postgresql://", "postgresql+psycopg2://", 1),
            "warehouse": "s3a://silver/warehouse",
            "s3.endpoint": PIPELINE["s3_endpoint"],
            "s3.access-key-id": os.environ["AWS_ACCESS_KEY_ID"],
            "s3.secret-access-key": os.environ["AWS_SECRET_ACCESS_KEY"],
        },
    )
    tbl = catalog.load_table("silver.video_snapshots")
    fmt = "%Y-%m-%dT%H:%M:%S+00:00"
    scan = tbl.scan(row_filter=And(
        GreaterThanOrEqual("captured_at", start.strftime(fmt)),
        LessThanOrEqual("captured_at", end.strftime(fmt)),
    ))
    records = scan.to_arrow().to_pylist()
    rows = [tuple(r[c] for c in SILVER_COLUMNS) for r in records]
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(SILVER_DDL)
            if rows:
                execute_values(cur, SILVER_UPSERT, rows, page_size=500)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


@task
def load_silver_to_postgres() -> int:
    ctx = get_current_context()
    hour = ctx["data_interval_start"]
    n = load_hours_to_postgres(hour, hour)
    if n == 0:
        raise RuntimeError(f"silver scan 為空（hour={hour.isoformat()}）——Spark 未產出？")
    return n


def make_dbt_operator(task_id: str, shell_command: str) -> KubernetesPodOperator:
    return KubernetesPodOperator(
        task_id=task_id,
        namespace="data",
        image=f"{IMAGES['dbt']['repository']}:{IMAGES['dbt']['tag']}",
        cmds=["/bin/sh", "-c"],
        arguments=[shell_command],
        secrets=[Secret(deploy_type="env", deploy_target="DBT_PG_PASSWORD",
                        secret="lakehouse-postgres", key="dbt-password")],
        get_logs=True,
        on_finished_action="delete_pod",
        container_resources={
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    )


with DAG(
    dag_id="yt_trending_hourly",
    schedule="0 * * * *",
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,   # mostPopular 無歷史，catchup 是資料謊言（design §7）——永遠不開
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=45),
    default_args=DEFAULT_ARGS,
    tags=["p1", "youtube"],
) as dag:
    ingest = ingest_trending.expand(region=PIPELINE["regions"])

    spark = SparkKubernetesOperator(
        task_id="spark_bronze_to_silver",
        namespace="data",
        application_file="templates/spark_silver.yaml",
        params={
            "spark_image": f"{IMAGES['spark_job']['repository']}:{IMAGES['spark_job']['tag']}",
            "pg_password": _pg_password(),
        },
    )

    dbt_run = make_dbt_operator("dbt_run", "dbt run --profiles-dir /app --project-dir /app")
    dbt_test = make_dbt_operator(
        "dbt_test",
        "dbt source freshness --profiles-dir /app --project-dir /app && dbt test --profiles-dir /app --project-dir /app",
    )

    ingest >> delete_stale_sparkapp() >> spark >> load_silver_to_postgres() >> dbt_run >> dbt_test
```

- [ ] **Step 3: 建 yt_categories_daily.py**

Create `orchestration/airflow/dags/yt_categories_daily.py`：
```python
"""Categories 維度 @daily：fetch ×8 → bronze（決定性 key）→ UPSERT silver.youtube_categories（不過 Spark，刻意）。"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pendulum
import yaml
from airflow.exceptions import AirflowFailException
from airflow.sdk import DAG, get_current_context, task

CONFIG_DIR = Path(__file__).parent / "config"
PIPELINE = yaml.safe_load((CONFIG_DIR / "pipeline.yaml").read_text())

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=10),
}


@task
def ingest_categories(region: str) -> int:
    from yt_ingest.bronze import write_bronze
    from yt_ingest.categories import connect, upsert_categories
    from yt_ingest.client import QuotaExceededError, YouTubeClient

    ctx = get_current_context()
    logical_date = ctx["data_interval_start"]
    client = YouTubeClient(api_key=os.environ["YOUTUBE_API_KEY"])
    try:
        resp = client.fetch_categories(region=region)
    except QuotaExceededError as exc:
        raise AirflowFailException(f"YouTube quota exhausted for {region}: {exc}") from exc
    write_bronze(
        response=resp, region=region, logical_hour=logical_date,
        ingested_at=pendulum.now("UTC"),
        bucket=PIPELINE["bronze_bucket"], endpoint_url=PIPELINE["s3_endpoint"],
        prefix="youtube_categories", filename="categories.json", with_hour=False,
    )
    conn = connect(os.environ["LAKEHOUSE_PG_DSN"])
    try:
        return upsert_categories(conn, resp, region=region,
                                 updated_at=pendulum.now("UTC").isoformat())
    finally:
        conn.close()


with DAG(
    dag_id="yt_categories_daily",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args=DEFAULT_ARGS,
    tags=["p1", "youtube"],
) as dag:
    ingest_categories.expand(region=PIPELINE["regions"])
```

- [ ] **Step 4: 建 yt_reprocess_range.py**

Create `orchestration/airflow/dags/yt_reprocess_range.py`：
```python
"""手動重處理（bronze 已有 → Silver/Gold 重算）：params start_hour/end_hour（UTC ISO 小時，含端點，如 2026-07-08T14）。
冪等由 overwritePartitions（Spark）與 UPSERT（loader）保證；ingest 不重跑（mostPopular 無歷史）。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pendulum
import yaml
from airflow.sdk import DAG, Param, get_current_context, task

from yt_trending_hourly import _pg_password, load_hours_to_postgres, make_dbt_operator
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator

CONFIG_DIR = Path(__file__).parent / "config"
IMAGES = yaml.safe_load((CONFIG_DIR / "images.yaml").read_text())

HOUR_FMT = "%Y-%m-%dT%H"


def _parse_hour(value: str) -> datetime:
    return datetime.strptime(value, HOUR_FMT).replace(tzinfo=timezone.utc)


@task
def load_range_to_postgres() -> int:
    ctx = get_current_context()
    start = _parse_hour(ctx["params"]["start_hour"])
    end = _parse_hour(ctx["params"]["end_hour"])
    if end < start:
        raise ValueError(f"end_hour {end} 早於 start_hour {start}")
    return load_hours_to_postgres(start, end)


with DAG(
    dag_id="yt_reprocess_range",
    schedule=None,
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=120),
    params={
        "start_hour": Param(type="string", description="UTC ISO 小時（含端點），如 2026-07-08T14"),
        "end_hour": Param(type="string", description="UTC ISO 小時（含端點）"),
    },
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=60),
    },
    tags=["p1", "youtube", "manual"],
) as dag:
    spark = SparkKubernetesOperator(
        task_id="spark_reprocess_range",
        namespace="data",
        application_file="templates/spark_silver.yaml",
        params={
            "spark_image": f"{IMAGES['spark_job']['repository']}:{IMAGES['spark_job']['tag']}",
            "pg_password": _pg_password(),
            # start_hour/end_hour 由 dag params 進 Jinja context（模板 reprocess 分支）
        },
    )
    dbt_run = make_dbt_operator("dbt_run", "dbt run --profiles-dir /app --project-dir /app")
    dbt_test = make_dbt_operator(
        "dbt_test",
        "dbt source freshness --profiles-dir /app --project-dir /app && dbt test --profiles-dir /app --project-dir /app",
    )
    spark >> load_range_to_postgres() >> dbt_run >> dbt_test
```
> 注意：`from yt_trending_hourly import …` 在 DAG folder 同層可 import（Airflow 把 dags/ 加進 sys.path）；DagBag 測試會守住這個假設。

- [ ] **Step 5: 跑 DAG 測試（除 config 一致性條外全綠）**

```bash
source /tmp/af-venv/bin/activate
pytest orchestration/airflow/tests/ -v
```
Expected: `test_dagbag_imports_clean`/`test_hourly_guards`/`test_hourly_dependency_chain`/`test_categories_and_reprocess_guards` PASS；`test_regions_single_source_of_truth_vs_dbt` FAIL（dbt schema 檔 Task 12 才建——Task 12 Step 9 回頭收綠）。

- [ ] **Step 6: Commit**

```bash
git add orchestration/airflow/dags/*.py orchestration/airflow/tests/
git commit -m "功能(orchestration)：三條 DAG（hourly 全鏈/categories/reprocess）+ DagBag 依賴鏈守門測試"
```

---

## Task 10: ArgoCD 子 Application — airflow（wave 5，Helm 1.22.0）

**Files:**
- Create: `platform/argocd/apps/airflow.yaml`

**Interfaces:**
- Consumes: Task 1 Secrets（airflow ns 五把）、Task 7 image（tag 由 airflow-ci bump 本檔）、repo public git-sync。
- Produces: Airflow（KubernetesExecutor + git-sync + statsd + ingress `airflow.localtest.me`）。Task 14 verify 對 api-server exec 觸發 DAG。
- **CI 合約**：airflow-ci 的 yq 路徑 = `.spec.source.helm.valuesObject.images.airflow.tag`（單 source，勿改成 sources 複數——見 Task 5 註）。

> Airflow chart 不需要 `ServerSideApply=true`（無超大 CRD——SSA 只在 CRD 超過 client-side annotation 上限時用，P0 kube-prometheus/本階段 spark-operator 才需要），刻意不加。
> ArgoCD + Airflow chart 已知雷：migration/createUser Job 走 helm hooks 在 ArgoCD 下不執行 → `useHelmHooks: false` 讓它變成一般資源由 ArgoCD apply。

- [ ] **Step 1: 建 airflow.yaml**

Create `platform/argocd/apps/airflow.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: airflow
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "5"
spec:
  project: default
  source:
    repoURL: https://airflow.apache.org
    chart: airflow
    targetRevision: 1.22.0
    helm:
      valuesObject:
        executor: KubernetesExecutor
        postgresql:
          enabled: false            # metadata 走共用 Postgres 的 airflow db（一套 Postgres 紀律）
        metadataSecretName: lakehouse-postgres   # chart 約定 key 名 connection（§8）
        webserverSecretKeySecretName: airflow-webserver-secret
        images:
          airflow:
            repository: ghcr.io/ferguske/trend-intelligence-platform/airflow
            tag: sha-0000000        # 佔位；airflow-ci bump
        dags:
          gitSync:
            enabled: true
            repo: https://github.com/fergusKe/trend-intelligence-platform
            branch: main
            subPath: orchestration/airflow/dags
        ingress:
          apiServer:
            enabled: true
            ingressClassName: nginx
            hosts:
              - name: airflow.localtest.me
        statsd:
          enabled: true
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
        secret:
          - envName: YOUTUBE_API_KEY
            secretName: youtube-api
            secretKey: YOUTUBE_API_KEY
          - envName: AWS_ACCESS_KEY_ID
            secretName: minio-root
            secretKey: AWS_ACCESS_KEY_ID
          - envName: AWS_SECRET_ACCESS_KEY
            secretName: minio-root
            secretKey: AWS_SECRET_ACCESS_KEY
          - envName: LAKEHOUSE_PG_DSN
            secretName: lakehouse-postgres
            secretKey: pipeline-dsn
        scheduler:
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
        dagProcessor:
          resources:
            requests: {cpu: 200m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
        apiServer:
          resources:
            requests: {cpu: 200m, memory: 512Mi}
            limits: {cpu: "1", memory: 1Gi}
        triggerer:
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: 500m, memory: 512Mi}
        workers:
          resources:              # KubernetesExecutor ephemeral task pod（含 ingest ×8）
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: "1", memory: 512Mi}
        createUserJob:
          useHelmHooks: false
          applyCustomEnv: false
        migrateDatabaseJob:
          useHelmHooks: false
          applyCustomEnv: false
  destination:
    server: https://kubernetes.default.svc
    namespace: airflow
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 驗證 YAML + 可攜守門 + dry-run（M4）**

M1 本機：
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/airflow.yaml'))); print('YAML OK')"
grep -n "storageClassName\|nginx.ingress\|alb.ingress" platform/argocd/apps/airflow.yaml && echo "VIOLATION" || echo "portability OK"
yq '.spec.source.helm.valuesObject.images.airflow.tag' platform/argocd/apps/airflow.yaml
```
（M4）：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl apply --dry-run=client -f platform/argocd/apps/airflow.yaml
```
Expected: `YAML OK`；`portability OK`；yq 印 `sha-0000000`（CI bump 路徑可達）；dry-run created。

- [ ] **Step 3: Commit**

```bash
git add platform/argocd/apps/airflow.yaml
git commit -m "部署(platform)：ArgoCD 子 app airflow（Helm 1.22.0，KubernetesExecutor + git-sync + statsd，wave 5）"
```

---

## Task 11: Spark job（silver_job.py + Dockerfile + RBAC + spark-ci，TDD）

**Files:**
- Create: `lakehouse/spark/pyproject.toml`
- Create: `lakehouse/spark/jobs/silver_job.py`
- Create: `lakehouse/spark/tests/test_silver_job.py`
- Create: `lakehouse/spark/Dockerfile`
- Create: `lakehouse/spark/k8s/rbac.yaml`（並刪 Task 5 的 `.gitkeep`）
- Create: `.github/workflows/spark-ci.yaml`

**Interfaces:**
- Consumes: Bronze 信封（Task 6 `build_envelope` 形狀 = 本 job 的顯式 StructType）；Task 8 模板的 args/conf。
- Produces: Iceberg 表 `lakehouse.silver.video_snapshots`（欄位 = §6a = Task 9 loader DDL）；image `…/spark-jobs:sha-*`；`data` ns 的 airflow-worker RBAC。

- [ ] **Step 1: 建 pyproject.toml（測試依賴）**

Create `lakehouse/spark/pyproject.toml`：
```toml
[project]
name = "spark-jobs"
version = "0.1.0"
description = "Bronze to Silver Spark job"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = [
    "pyspark==4.0.2",
    "pytest==9.1.1",
    "ruff==0.15.20",
]
```

- [ ] **Step 2: 先寫失敗測試（local SparkSession + fixture JSON）**

Create `lakehouse/spark/tests/test_silver_job.py`：
```python
import json
import sys
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jobs"))
from silver_job import ENVELOPE_SCHEMA, SILVER_COLUMNS, hours_from_args, read_bronze, transform  # noqa: E402


@pytest.fixture(scope="session")
def spark():
    s = (SparkSession.builder.master("local[1]").appName("silver-test")
         .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    yield s
    s.stop()


def envelope(region="TW", ingested="2026-07-08T14:03:21+00:00", items=None):
    return {
        "_metadata": {"region": region, "logical_hour": "2026-07-08T14:00:00+00:00",
                       "ingestion_id": f"{region}_2026070814", "ingested_at": ingested,
                       "source": "youtube_data_api_v3"},
        "response": {"items": items if items is not None else [
            {"id": "vid1",
             "snippet": {"publishedAt": "2026-07-01T00:00:00Z", "channelId": "ch1",
                          "title": "t1", "description": "d1",
                          "thumbnails": {"high": {"url": "http://img/1.jpg"}},
                          "channelTitle": "Chan 1", "tags": ["a", "b"], "categoryId": "10"},
             "statistics": {"viewCount": "1000", "likeCount": "100", "commentCount": "50"},
             "contentDetails": {"duration": "PT10M"}},
        ]},
    }


def write_fixture(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_transform_columns_and_formulas(spark, tmp_path):
    path = write_fixture(tmp_path, "a.json", envelope())
    df = transform(read_bronze(spark, [path]))
    assert df.columns == SILVER_COLUMNS
    row = df.collect()[0]
    assert row.video_id == "vid1" and row.region == "TW"
    assert row.captured_at.isoformat().startswith("2026-07-08T14:00:00")  # date_trunc hour
    assert row.tags == "a,b"
    assert row.views == 1000 and row.likes == 100 and row.comment_count == 50
    assert row.like_ratio == pytest.approx(0.1)
    assert row.engagement_rate == pytest.approx(0.15)
    assert row.description == "d1"  # 範本漏抓、本設計補上的 P2b 語料欄


def test_zero_views_gives_zero_ratios(spark, tmp_path):
    env = envelope()
    env["response"]["items"][0]["statistics"] = {"viewCount": "0", "likeCount": None, "commentCount": None}
    path = write_fixture(tmp_path, "z.json", env)
    row = transform(read_bronze(spark, [path])).collect()[0]
    assert row.views == 0 and row.likes == 0 and row.comment_count == 0  # fillna(0)
    assert row.like_ratio == 0.0 and row.engagement_rate == 0.0          # views=0 → 0.0


def test_dedupe_keeps_latest_per_video_region_hour(spark, tmp_path):
    # 同 (video_id, region, captured_at 小時) 兩筆（重跑殘留情境）→ 留 ingested_at 較新者
    p1 = write_fixture(tmp_path, "d1.json", envelope(ingested="2026-07-08T14:01:00+00:00"))
    env2 = envelope(ingested="2026-07-08T14:30:00+00:00")
    env2["response"]["items"][0]["statistics"]["viewCount"] = "2000"
    p2 = write_fixture(tmp_path, "d2.json", env2)
    df = transform(read_bronze(spark, [p1, p2]))
    rows = df.collect()
    assert len(rows) == 1
    assert rows[0].views == 2000


def test_empty_input_raises(spark, tmp_path):
    with pytest.raises(Exception):
        read_bronze(spark, [str(tmp_path / "nope" / "*.json")]).collect()


def test_hours_from_args_single_and_range():
    hours = hours_from_args(date="2026-07-08", hour="14", start_hour=None, end_hour=None)
    assert [h.strftime("%Y-%m-%dT%H") for h in hours] == ["2026-07-08T14"]
    hours = hours_from_args(date=None, hour=None, start_hour="2026-07-08T22", end_hour="2026-07-09T01")
    assert [h.strftime("%Y-%m-%dT%H") for h in hours] == [
        "2026-07-08T22", "2026-07-08T23", "2026-07-09T00", "2026-07-09T01"]
```

- [ ] **Step 3: 跑測試確認失敗（需 Java 17：`brew install temurin@17` 或既有 JDK）**

```bash
cd lakehouse/spark && uv lock && uv sync && uv run pytest tests/ -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'silver_job'`。

- [ ] **Step 4: 實作 jobs/silver_job.py**

Create `lakehouse/spark/jobs/silver_job.py`：
```python
"""Bronze（原始 JSON 信封）→ Iceberg Silver lakehouse.silver.video_snapshots。

- 顯式 schema（關推斷）；一物件一檔 → multiLine=true
- 去重鍵 (video_id, region, captured_at)——保小時粒度（velocity 命脈，design §5）
- overwritePartitions：重跑同小時 = 覆寫該分區 = 冪等
- 兩模式：--date/--hour（hourly）或 --start-hour/--end-hour（reprocess 範圍，UTC ISO 小時含端點）
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from pyspark.sql import DataFrame, SparkSession, functions as F
from pyspark.sql.types import ArrayType, LongType, StringType, StructField, StructType
from pyspark.sql.window import Window

ENVELOPE_SCHEMA = StructType([
    StructField("_metadata", StructType([
        StructField("region", StringType()),
        StructField("logical_hour", StringType()),
        StructField("ingestion_id", StringType()),
        StructField("ingested_at", StringType()),
        StructField("source", StringType()),
    ])),
    StructField("response", StructType([
        StructField("items", ArrayType(StructType([
            StructField("id", StringType()),
            StructField("snippet", StructType([
                StructField("publishedAt", StringType()),
                StructField("channelId", StringType()),
                StructField("title", StringType()),
                StructField("description", StringType()),
                StructField("thumbnails", StructType([
                    StructField("high", StructType([StructField("url", StringType())])),
                ])),
                StructField("channelTitle", StringType()),
                StructField("tags", ArrayType(StringType())),
                StructField("categoryId", StringType()),
            ])),
            StructField("statistics", StructType([
                StructField("viewCount", StringType()),
                StructField("likeCount", StringType()),
                StructField("commentCount", StringType()),
            ])),
            StructField("contentDetails", StructType([
                StructField("duration", StringType()),
            ])),
        ]))),
    ])),
])

SILVER_COLUMNS = [
    "video_id", "region", "captured_at", "title", "description", "tags",
    "channel_id", "channel_title", "category_id", "published_at",
    "views", "likes", "comment_count", "like_ratio", "engagement_rate",
    "thumbnail_url", "ingestion_id", "ingested_at",
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lakehouse.silver.video_snapshots (
    video_id string, region string, captured_at timestamp,
    title string, description string, tags string,
    channel_id string, channel_title string, category_id string,
    published_at timestamp,
    views bigint, likes bigint, comment_count bigint,
    like_ratio double, engagement_rate double,
    thumbnail_url string, ingestion_id string, ingested_at timestamp
) USING iceberg
PARTITIONED BY (region, hours(captured_at))
"""

HOUR_FMT = "%Y-%m-%dT%H"


def hours_from_args(date: str | None, hour: str | None,
                    start_hour: str | None, end_hour: str | None) -> list[datetime]:
    if date and hour is not None:
        return [datetime.strptime(f"{date}T{hour}", HOUR_FMT).replace(tzinfo=timezone.utc)]
    start = datetime.strptime(start_hour, HOUR_FMT).replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_hour, HOUR_FMT).replace(tzinfo=timezone.utc)
    if end < start:
        raise ValueError(f"end {end} < start {start}")
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(hours=1)
    return out


def bronze_paths(hours: list[datetime]) -> list[str]:
    return [
        f"s3a://bronze/youtube_trending/region=*/date={h:%Y-%m-%d}/hour={h:%H}/*.json"
        for h in hours
    ]


def read_bronze(spark: SparkSession, paths: list[str]) -> DataFrame:
    # multiLine：一 bronze 物件 = 一整個 JSON document（非 JSON lines）
    return spark.read.schema(ENVELOPE_SCHEMA).option("multiLine", "true").json(paths)


def transform(df: DataFrame) -> DataFrame:
    items = df.select(
        F.col("_metadata.region").alias("region"),
        F.col("_metadata.ingestion_id").alias("ingestion_id"),
        F.to_timestamp("_metadata.ingested_at").alias("ingested_at"),
        F.explode("response.items").alias("item"),
    )
    out = items.select(
        F.col("item.id").alias("video_id"),
        "region",
        F.date_trunc("hour", F.col("ingested_at")).alias("captured_at"),
        F.col("item.snippet.title").alias("title"),
        F.col("item.snippet.description").alias("description"),
        F.array_join(F.col("item.snippet.tags"), ",").alias("tags"),
        F.col("item.snippet.channelId").alias("channel_id"),
        F.col("item.snippet.channelTitle").alias("channel_title"),
        F.col("item.snippet.categoryId").alias("category_id"),
        F.to_timestamp(F.col("item.snippet.publishedAt")).alias("published_at"),
        F.coalesce(F.col("item.statistics.viewCount").cast(LongType()), F.lit(0)).alias("views"),
        F.coalesce(F.col("item.statistics.likeCount").cast(LongType()), F.lit(0)).alias("likes"),
        F.coalesce(F.col("item.statistics.commentCount").cast(LongType()), F.lit(0)).alias("comment_count"),
        F.col("item.snippet.thumbnails.high.url").alias("thumbnail_url"),
        "ingestion_id",
        "ingested_at",
    ).where(F.col("video_id").isNotNull())
    out = out.withColumn(
        "like_ratio",
        F.when(F.col("views") > 0, F.col("likes") / F.col("views")).otherwise(F.lit(0.0)),
    ).withColumn(
        "engagement_rate",
        F.when(F.col("views") > 0,
               (F.col("likes") + F.col("comment_count")) / F.col("views")).otherwise(F.lit(0.0)),
    )
    w = Window.partitionBy("video_id", "region", "captured_at").orderBy(F.col("ingested_at").desc())
    out = out.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).drop("_rn")
    return out.select(*SILVER_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--hour")
    parser.add_argument("--start-hour", dest="start_hour")
    parser.add_argument("--end-hour", dest="end_hour")
    args = parser.parse_args()
    hours = hours_from_args(args.date, args.hour, args.start_hour, args.end_hour)

    spark = SparkSession.builder.appName("yt-silver").getOrCreate()
    df = transform(read_bronze(spark, bronze_paths(hours)))
    spark.sql(CREATE_TABLE_SQL)
    df.writeTo("lakehouse.silver.video_snapshots").overwritePartitions()
    spark.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑測試確認綠 + lint**

```bash
cd lakehouse/spark && uv run pytest tests/ -v && uv run ruff check jobs/ tests/
```
Expected: 5 tests passed；`All checks passed!`。

- [ ] **Step 6: 建 Dockerfile（jar 版本 = Task 0 C3 校準值；ADD --chmod 免 curl 依賴）**

Create `lakehouse/spark/Dockerfile`：
```dockerfile
FROM spark:4.0.2-python3
# jar 版本合約：ICEBERG=§0 pin；HADOOP_AWS/AWS_SDK = Task 0 C3 校準（預設傾向 3.4.1/1.12.780）；
# postgresql JDBC = Iceberg JDBC catalog 必需
ARG ICEBERG_VERSION=1.11.0
ARG HADOOP_AWS_VERSION=3.4.1
ARG AWS_SDK_VERSION=1.12.780
ARG PG_JDBC_VERSION=42.7.7
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/${ICEBERG_VERSION}/iceberg-spark-runtime-4.0_2.13-${ICEBERG_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_VERSION}/aws-java-sdk-bundle-${AWS_SDK_VERSION}.jar /opt/spark/jars/
ADD --chmod=644 https://repo1.maven.org/maven2/org/postgresql/postgresql/${PG_JDBC_VERSION}/postgresql-${PG_JDBC_VERSION}.jar /opt/spark/jars/
COPY jobs/ /opt/spark/jobs/
USER spark
```

本機 build 冒煙：
```bash
cd lakehouse/spark && docker build -t spark-jobs:local . && \
docker run --rm spark-jobs:local ls /opt/spark/jars | grep -E "iceberg-spark-runtime|hadoop-aws|aws-java-sdk|postgresql" && \
docker run --rm spark-jobs:local ls /opt/spark/jobs/silver_job.py
```
Expected: 四個 jar 列出；`/opt/spark/jobs/silver_job.py`。

- [ ] **Step 7: 建 k8s/rbac.yaml（Task 5 多源 app 交付；SA 名以 Task 0 C5 校準為準）**

```bash
rm lakehouse/spark/k8s/.gitkeep
```
Create `lakehouse/spark/k8s/rbac.yaml`：
```yaml
# airflow ns 的 worker SA 對 data ns 的權限：SparkApplication CRUD + KPO 的 pod 生命週期 + log 讀
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: airflow-pipeline-runner
  namespace: data
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
rules:
  - apiGroups: ["sparkoperator.k8s.io"]
    resources: ["sparkapplications"]
    verbs: ["create", "get", "list", "watch", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["create", "get", "list", "watch", "patch", "delete"]   # KubernetesPodOperator（dbt pod）需要
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: airflow-pipeline-runner
  namespace: data
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: airflow-pipeline-runner
subjects:
  - kind: ServiceAccount
    name: airflow-worker      # chart 預設 <release>-worker；Task 0 C5 校驗、Task 15 live 複核
    namespace: airflow
```

- [ ] **Step 8: 建 spark-ci.yaml**

Create `.github/workflows/spark-ci.yaml`：
```yaml
name: spark-ci
on:
  push:
    branches: [main]
    paths:
      - "lakehouse/spark/jobs/**"
      - "lakehouse/spark/tests/**"
      - "lakehouse/spark/Dockerfile"
      - "lakehouse/spark/pyproject.toml"
      # 刻意不含 lakehouse/spark/k8s/**（RBAC 走 GitOps）；bump 落點在 orchestration/**（不觸發本 workflow）
  workflow_dispatch: {}
concurrency:
  group: spark-ci
  cancel-in-progress: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-java@v5
        with: {distribution: temurin, java-version: "17"}
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - run: uv sync
        working-directory: lakehouse/spark
      - run: uv run ruff check jobs/ tests/
        working-directory: lakehouse/spark
      - run: uv run pytest tests/ -v
        working-directory: lakehouse/spark

  build-push-bump:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v7
      - id: vars
        run: |
          echo "TAG=sha-$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
          echo "IMAGE=ghcr.io/$(echo '${{ github.repository }}' | tr '[:upper:]' '[:lower:]')/spark-jobs" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-qemu-action@v4
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: lakehouse/spark
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ${{ steps.vars.outputs.IMAGE }}:${{ steps.vars.outputs.TAG }}
            ${{ steps.vars.outputs.IMAGE }}:latest
      - name: Bump images.yaml spark_job.tag（git-sync 送達 DAG，不觸發任何 build）
        run: |
          yq -i '.spark_job.tag = "${{ steps.vars.outputs.TAG }}"' orchestration/airflow/dags/config/images.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add orchestration/airflow/dags/config/images.yaml
          git commit -m "ci(spark): bump image to ${{ steps.vars.outputs.TAG }} [skip ci]"
          git pull --rebase origin main
          git push origin main
```

- [ ] **Step 9: 驗證 + Commit**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/spark-ci.yaml')); list(yaml.safe_load_all(open('lakehouse/spark/k8s/rbac.yaml'))); print('YAML OK')"
git add lakehouse/spark/ .github/workflows/spark-ci.yaml
git commit -m "功能(lakehouse)：Spark silver job（顯式 schema/小時粒度去重/overwritePartitions，TDD）+ RBAC + spark-ci"
```

---

## Task 12: dbt 專案（staging + 5 marts + DQ 測試合約 + Dockerfile + dbt-ci）

**Files:**
- Create: `lakehouse/dbt/dbt_project.yml`、`lakehouse/dbt/profiles.yml`、`lakehouse/dbt/Dockerfile`
- Create: `lakehouse/dbt/macros/generate_schema_name.sql`
- Create: `lakehouse/dbt/models/staging/{_sources.yml, _staging_schema.yml, stg_video_snapshots.sql, stg_categories.sql}`
- Create: `lakehouse/dbt/models/marts/{_marts_schema.yml, gold_trending_daily.sql, gold_channel_performance.sql, gold_category_daily.sql, gold_video_velocity_hourly.sql, gold_video_lifecycle.sql}`
- Create: `lakehouse/dbt/tests/{assert_source_freshness_guard.sql, assert_views_non_negative.sql, assert_unique_grain_trending_daily.sql, assert_unique_grain_velocity.sql, assert_unique_grain_lifecycle.sql, assert_velocity_hours_positive.sql}`
- Create: `.github/workflows/dbt-ci.yaml`

**Interfaces:**
- Consumes: Postgres `silver.video_snapshots`/`silver.youtube_categories`（= Task 9 loader / Task 6 categories DDL）。
- Produces: `gold.gold_*` 五表（**§6a P2 資料合約，欄名/粒度逐欄照抄，additive-only**）；staging view 落 `staging.stg_*`；image `…/dbt:sha-*`；bump `images.yaml` `.dbt.tag`。

- [ ] **Step 1: 專案骨架三檔**

Create `lakehouse/dbt/dbt_project.yml`：
```yaml
name: lakehouse
version: "1.0.0"
profile: lakehouse
model-paths: ["models"]
macro-paths: ["macros"]
test-paths: ["tests"]
models:
  lakehouse:
    staging:
      +schema: staging
      +materialized: view
    marts:
      +schema: gold
      +materialized: table
```

Create `lakehouse/dbt/profiles.yml`：
```yaml
lakehouse:
  target: k8s
  outputs:
    k8s:
      type: postgres
      host: "{{ env_var('LAKEHOUSE_PG_HOST', 'lakehouse-postgres.data.svc') }}"
      port: 5432
      user: dbt_runner
      password: "{{ env_var('DBT_PG_PASSWORD') }}"
      dbname: lakehouse
      schema: gold
      threads: 4
```

Create `lakehouse/dbt/macros/generate_schema_name.sql`（標準「custom schema 作絕對值」版本——staging 落 `staging.`、marts 落 `gold.`，不出現 `gold_staging` 拼接）：
```sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

- [ ] **Step 2: sources + staging**

Create `lakehouse/dbt/models/staging/_sources.yml`：
```yaml
version: 2
sources:
  - name: silver
    database: lakehouse
    schema: silver
    tables:
      - name: video_snapshots
        loaded_at_field: ingested_at
        freshness:
          warn_after: {count: 2, period: hour}
          error_after: {count: 4, period: hour}
      - name: youtube_categories
        loaded_at_field: updated_at   # 該表無 ingested_at（design 收緊 pass 修正）
        freshness:
          warn_after: {count: 26, period: hour}
          error_after: {count: 50, period: hour}
```

Create `lakehouse/dbt/models/staging/stg_video_snapshots.sql`：
```sql
select
    video_id,
    region,
    captured_at,
    captured_at::date as trending_date,
    title,
    description,
    tags,
    channel_id,
    channel_title,
    category_id,
    published_at,
    coalesce(views, 0) as views,
    coalesce(likes, 0) as likes,
    coalesce(comment_count, 0) as comment_count,
    coalesce(like_ratio, 0) as like_ratio,
    coalesce(engagement_rate, 0) as engagement_rate,
    thumbnail_url,
    ingestion_id,
    ingested_at
from {{ source('silver', 'video_snapshots') }}
where video_id is not null
```

Create `lakehouse/dbt/models/staging/stg_categories.sql`：
```sql
select
    category_id,
    region,
    category_name,
    updated_at
from {{ source('silver', 'youtube_categories') }}
```

Create `lakehouse/dbt/models/staging/_staging_schema.yml`（region 清單與 `pipeline.yaml` 逐字一致——Task 9 pytest 對帳）：
```yaml
version: 2
models:
  - name: stg_video_snapshots
    columns:
      - name: video_id
        data_tests: [not_null]
      - name: region
        data_tests:
          - not_null
          - accepted_values:
              values: [TW, JP, KR, HK, US, GB, SG, AU]
      - name: captured_at
        data_tests: [not_null]
      - name: views
        data_tests: [not_null]
  - name: stg_categories
    columns:
      - name: category_id
        data_tests: [not_null]
      - name: region
        data_tests: [not_null]
```

- [ ] **Step 3: marts schema（generic tests 合約其餘部分）**

Create `lakehouse/dbt/models/marts/_marts_schema.yml`：
```yaml
version: 2
models:
  - name: gold_trending_daily
    columns:
      - name: region
        data_tests: [not_null]
      - name: trending_date
        data_tests: [not_null]
      - name: total_views
        data_tests: [not_null]
  - name: gold_video_velocity_hourly
    columns:
      - name: video_id
        data_tests: [not_null]
      - name: captured_at
        data_tests: [not_null]
      - name: delta_views
        data_tests: [not_null]
  - name: gold_video_lifecycle
    columns:
      - name: video_id
        data_tests: [not_null]
      - name: first_seen_at
        data_tests: [not_null]
  - name: gold_category_daily
    columns:
      - name: category_id
        data_tests:
          - relationships:
              to: ref('stg_categories')
              field: category_id
              config: {severity: warn}   # categories 維度 @daily 可能晚於首日 hourly 資料
```

- [ ] **Step 4: 五個 marts SQL（§6a 欄位級照抄；PG `round(double,int)` 不存在 → 一律 `::numeric` 後 round）**

Create `lakehouse/dbt/models/marts/gold_trending_daily.sql`（粒度 `(region, trending_date)`，聚合基於每影片當日最新快照）：
```sql
with latest_per_day as (
    select *,
        row_number() over (
            partition by video_id, region, trending_date
            order by captured_at desc
        ) as rn
    from {{ ref('stg_video_snapshots') }}
)
select
    region,
    trending_date,
    count(distinct video_id) as total_videos,
    sum(views) as total_views,
    sum(likes) as total_likes,
    round(avg(views)::numeric, 0) as avg_views_per_video,
    round(avg(like_ratio)::numeric, 4) as avg_like_ratio,
    round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate,
    count(distinct channel_id) as unique_channels,
    count(distinct category_id) as unique_categories
from latest_per_day
where rn = 1
group by region, trending_date
```

Create `lakehouse/dbt/models/marts/gold_channel_performance.sql`（粒度 `(channel_id, region)`）：
```sql
with latest_snapshot as (
    select *,
        row_number() over (partition by video_id, region order by captured_at desc) as rn
    from {{ ref('stg_video_snapshots') }}
),
per_video as (
    select * from latest_snapshot where rn = 1
),
days as (
    select channel_id, region, count(distinct trending_date) as days_on_chart
    from {{ ref('stg_video_snapshots') }}
    group by channel_id, region
),
agg as (
    select
        channel_id,
        max(channel_title) as channel_title,
        region,
        count(distinct video_id) as videos_trended,
        sum(views) as total_views,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate,
        string_agg(distinct category_id, ',') as categories
    from per_video
    group by channel_id, region
)
select
    a.channel_id,
    a.channel_title,
    a.region,
    a.videos_trended,
    a.total_views,
    a.avg_engagement_rate,
    d.days_on_chart,
    rank() over (partition by a.region order by a.total_views desc) as rank_in_region,
    a.categories
from agg a
join days d using (channel_id, region)
```

Create `lakehouse/dbt/models/marts/gold_category_daily.sql`（粒度 `(category_id, region, trending_date)`）：
```sql
with latest_per_day as (
    select *,
        row_number() over (
            partition by video_id, region, trending_date
            order by captured_at desc
        ) as rn
    from {{ ref('stg_video_snapshots') }}
),
agg as (
    select
        category_id,
        region,
        trending_date,
        count(distinct video_id) as video_count,
        sum(views) as total_views,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate
    from latest_per_day
    where rn = 1
    group by category_id, region, trending_date
)
select
    a.category_id,
    coalesce(c.category_name, a.category_id) as category_name,
    a.region,
    a.trending_date,
    a.video_count,
    a.total_views,
    a.avg_engagement_rate,
    round((a.total_views * 100.0
        / nullif(sum(a.total_views) over (partition by a.region, a.trending_date), 0))::numeric, 2)
        as view_share_pct
from agg a
left join {{ ref('stg_categories') }} c
    on a.category_id = c.category_id and a.region = c.region
```

Create `lakehouse/dbt/models/marts/gold_video_velocity_hourly.sql`（粒度 `(video_id, region, captured_at)`；LAG 骨架 + 缺口正規化；首快照不出列）：
```sql
with deltas as (
    select
        video_id, title, channel_title, region, captured_at,
        views, likes, comment_count,
        lag(views) over w as prev_views,
        lag(likes) over w as prev_likes,
        lag(comment_count) over w as prev_comments,
        lag(captured_at) over w as prev_captured_at
    from {{ ref('stg_video_snapshots') }}
    window w as (partition by video_id, region order by captured_at)
),
calc as (
    select
        video_id, title, channel_title, region, captured_at, views,
        views - prev_views as delta_views,
        likes - prev_likes as delta_likes,
        comment_count - prev_comments as delta_comments,
        round((extract(epoch from (captured_at - prev_captured_at)) / 3600.0)::numeric, 2)
            as hours_since_prev,
        prev_views
    from deltas
    where prev_views is not null
)
select
    video_id, title, channel_title, region, captured_at, views,
    delta_views, delta_likes, delta_comments,
    hours_since_prev,
    round((delta_views / nullif(hours_since_prev, 0))::numeric, 2) as delta_views_per_hour,
    case when prev_views = 0 then null
         else round((delta_views * 100.0 / prev_views)::numeric, 2)
    end as delta_views_pct,
    rank() over (
        partition by region, captured_at
        order by (delta_views / nullif(hours_since_prev, 0)) desc nulls last
    ) as velocity_rank
from calc
```

Create `lakehouse/dbt/models/marts/gold_video_lifecycle.sql`（粒度 `(video_id, region)`；文字欄取最新快照，peak 取 velocity ref）：
```sql
with snapshots as (
    select *,
        row_number() over (partition by video_id, region order by captured_at desc) as rn_desc,
        row_number() over (partition by video_id, region order by captured_at asc) as rn_asc
    from {{ ref('stg_video_snapshots') }}
),
bounds as (
    select
        video_id, region,
        min(captured_at) as first_seen_at,
        max(captured_at) as last_seen_at,
        count(*) as snapshots_count,
        round((extract(epoch from (max(captured_at) - min(captured_at))) / 3600.0)::numeric, 2)
            as hours_on_chart,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate
    from snapshots
    group by video_id, region
),
first_snap as (
    select video_id, region, views as first_views from snapshots where rn_asc = 1
),
last_snap as (
    select video_id, region, title, description, tags, channel_id, channel_title,
           category_id, published_at, views as latest_views
    from snapshots where rn_desc = 1
),
peak as (
    select video_id, region, max(delta_views_per_hour) as peak_delta_views_per_hour
    from {{ ref('gold_video_velocity_hourly') }}
    group by video_id, region
)
select
    b.video_id,
    b.region,
    l.title,
    l.description,
    l.tags,
    l.channel_id,
    l.channel_title,
    l.category_id,
    coalesce(c.category_name, l.category_id) as category_name,
    l.published_at,
    b.first_seen_at,
    b.last_seen_at,
    b.snapshots_count,
    b.hours_on_chart,
    f.first_views,
    l.latest_views,
    l.latest_views - f.first_views as total_views_gained,
    p.peak_delta_views_per_hour,
    b.avg_engagement_rate
from bounds b
join last_snap l using (video_id, region)
join first_snap f using (video_id, region)
left join peak p using (video_id, region)
left join {{ ref('stg_categories') }} c
    on l.category_id = c.category_id and b.region = c.region
```

- [ ] **Step 5: 六支 singular tests（不引 dbt_utils，自寫 SQL）**

Create `lakehouse/dbt/tests/assert_source_freshness_guard.sql`：
```sql
-- 與 source freshness 雙保險；這條在 dbt test 內直接擋 DAG
select max(ingested_at) as last_ingested_at
from {{ source('silver', 'video_snapshots') }}
having now() - max(ingested_at) > interval '4 hours'
```

Create `lakehouse/dbt/tests/assert_views_non_negative.sql`：
```sql
select video_id, region, captured_at, views, likes, comment_count
from {{ ref('stg_video_snapshots') }}
where views < 0 or likes < 0 or comment_count < 0
```

Create `lakehouse/dbt/tests/assert_unique_grain_trending_daily.sql`：
```sql
select region, trending_date, count(*)
from {{ ref('gold_trending_daily') }}
group by region, trending_date
having count(*) > 1
```

Create `lakehouse/dbt/tests/assert_unique_grain_velocity.sql`：
```sql
select video_id, region, captured_at, count(*)
from {{ ref('gold_video_velocity_hourly') }}
group by video_id, region, captured_at
having count(*) > 1
```

Create `lakehouse/dbt/tests/assert_unique_grain_lifecycle.sql`：
```sql
select video_id, region, count(*)
from {{ ref('gold_video_lifecycle') }}
group by video_id, region
having count(*) > 1
```

Create `lakehouse/dbt/tests/assert_velocity_hours_positive.sql`：
```sql
select video_id, region, captured_at, hours_since_prev
from {{ ref('gold_video_velocity_hourly') }}
where hours_since_prev <= 0
```

- [ ] **Step 6: Dockerfile**

Create `lakehouse/dbt/Dockerfile`：
```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir dbt-postgres==1.10.2
WORKDIR /app
COPY dbt_project.yml profiles.yml ./
COPY macros/ macros/
COPY models/ models/
COPY tests/ tests/
RUN useradd -u 1000 -m dbt && chown -R dbt /app
USER 1000
# KPO 以 dbt run/test --profiles-dir /app --project-dir /app 呼叫（Task 9）
```

- [ ] **Step 7: 本機 dbt parse（離線守門，同 dbt-ci）**

```bash
cd lakehouse/dbt && uv run --with dbt-postgres==1.10.2 --python 3.12 -- \
  env DBT_PG_PASSWORD=dummy dbt parse --profiles-dir . --project-dir .
```
Expected: `Performance info…` 結尾無 error（parse 不連 DB；`env_var('DBT_PG_PASSWORD')` 需給 dummy）。

- [ ] **Step 8: 建 dbt-ci.yaml**

Create `.github/workflows/dbt-ci.yaml`：
```yaml
name: dbt-ci
on:
  push:
    branches: [main]
    paths:
      - "lakehouse/dbt/**"
  workflow_dispatch: {}
concurrency:
  group: dbt-ci
  cancel-in-progress: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - name: dbt parse（離線編譯守門）
        run: |
          uv venv /tmp/dbt-venv
          source /tmp/dbt-venv/bin/activate
          uv pip install dbt-postgres==1.10.2
          DBT_PG_PASSWORD=dummy dbt parse --profiles-dir . --project-dir .
        working-directory: lakehouse/dbt

  build-push-bump:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v7
      - id: vars
        run: |
          echo "TAG=sha-$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
          echo "IMAGE=ghcr.io/$(echo '${{ github.repository }}' | tr '[:upper:]' '[:lower:]')/dbt" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-qemu-action@v4
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: lakehouse/dbt
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ${{ steps.vars.outputs.IMAGE }}:${{ steps.vars.outputs.TAG }}
            ${{ steps.vars.outputs.IMAGE }}:latest
      - name: Bump images.yaml dbt.tag
        run: |
          yq -i '.dbt.tag = "${{ steps.vars.outputs.TAG }}"' orchestration/airflow/dags/config/images.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add orchestration/airflow/dags/config/images.yaml
          git commit -m "ci(dbt): bump image to ${{ steps.vars.outputs.TAG }} [skip ci]"
          git pull --rebase origin main
          git push origin main
```

- [ ] **Step 9: 回頭收綠 Task 9 的 config 一致性測試 + Commit**

```bash
source /tmp/af-venv/bin/activate && pytest orchestration/airflow/tests/ -v
# Expected: 全綠（含 test_regions_single_source_of_truth_vs_dbt）
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/dbt-ci.yaml')); print('workflow YAML OK')"
git add lakehouse/dbt/ .github/workflows/dbt-ci.yaml
git commit -m "功能(lakehouse)：dbt 專案（staging+5 marts §6a 合約+DQ 測試 10 條）+ dbt-ci"
```

---

## Task 13: pipeline-monitoring（wave 6：statsd SM + PrometheusRule + 兩 dashboard + Postgres datasource）

**Files:**
- Create: `platform/monitoring/pipeline/statsd-servicemonitor.yaml`
- Create: `platform/monitoring/pipeline/prometheusrule.yaml`
- Create: `platform/monitoring/pipeline/pipeline-health-dashboard.yaml`
- Create: `platform/monitoring/pipeline/trending-insights-dashboard.yaml`
- Create: `platform/monitoring/pipeline/grafana-datasource-lakehouse.yaml`
- Create: `platform/argocd/apps/pipeline-monitoring.yaml`
- Modify: `platform/argocd/apps/monitoring.yaml`（grafana 加 `envFromSecrets`）

**Interfaces:**
- Consumes: Task 2 exporter 三指標、Airflow chart statsd（svc 名 `airflow-statsd`/port 名 `statsd-scrape`，Task 0 C5 校準）、Task 1 Secret `grafana-lakehouse-reader`。
- Produces: 告警三條（`YTDataStale` warn/critical、`YTPipelineTaskFailures`、`LakehouseComponentDown`）；dashboard title `YT Pipeline Health`/`YT Trending Insights`（§12A 步驟 9 以 `query=YT` 搜尋）；Grafana Postgres datasource `Lakehouse`（uid `lakehouse-postgres`，唯讀 `grafana_reader`）。

- [ ] **Step 1: statsd ServiceMonitor（跨 ns scrape airflow；P0 已設 `serviceMonitorNamespaceSelector: {}` 全叢集撿）**

Create `platform/monitoring/pipeline/statsd-servicemonitor.yaml`：
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: airflow-statsd
  namespace: monitoring
  labels: {app: airflow-statsd}
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  namespaceSelector:
    matchNames: [airflow]
  selector:
    matchLabels: {tier: airflow, component: statsd}
  endpoints:
    - {port: statsd-scrape, path: /metrics, interval: 30s}
```

- [ ] **Step 2: PrometheusRule（statsd 指標名 `airflow_ti_failures` 為 chart 預設映射；Task 15 live 校準 PromQL）**

Create `platform/monitoring/pipeline/prometheusrule.yaml`：
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: yt-pipeline
  namespace: monitoring
  labels: {app: yt-pipeline}
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  groups:
    - name: yt-pipeline
      rules:
        - alert: YTDataStale
          expr: yt_freshness_seconds > 10800
          for: 10m
          labels: {severity: warning}
          annotations: {summary: "Silver 資料超過 3 小時未更新"}
        - alert: YTDataStaleCritical
          expr: yt_freshness_seconds > 21600
          for: 10m
          labels: {severity: critical}
          annotations: {summary: "Silver 資料超過 6 小時未更新"}
        - alert: YTPipelineTaskFailures
          expr: increase(airflow_ti_failures[1h]) > 0
          labels: {severity: warning}
          annotations: {summary: "Airflow task 過去 1h 有失敗（含 dbt_test DQ gate）"}
        - alert: LakehouseComponentDown
          expr: up{job=~"lakehouse-minio|lakehouse-postgres-exporter"} == 0
          for: 5m
          labels: {severity: critical}
          annotations: {summary: "儲存底座元件 down（{{ $labels.job }}）"}
```

- [ ] **Step 3: pipeline-health dashboard（Prometheus datasource uid `prometheus`，沿 P0）**

Create `platform/monitoring/pipeline/pipeline-health-dashboard.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-pipeline-health
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  pipeline-health.json: |
    {
      "uid": "yt-pipeline-health",
      "title": "YT Pipeline Health",
      "schemaVersion": 39,
      "editable": true,
      "time": {"from": "now-24h", "to": "now"},
      "refresh": "1m",
      "panels": [
        {"id": 1, "title": "Silver freshness (s)", "type": "stat",
         "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "fieldConfig": {"defaults": {"thresholds": {"steps": [
           {"color": "green", "value": null}, {"color": "orange", "value": 10800}, {"color": "red", "value": 21600}]}}},
         "targets": [{"refId": "A", "expr": "yt_freshness_seconds"}]},
        {"id": 2, "title": "Task failures (1h increase)", "type": "timeseries",
         "gridPos": {"h": 6, "w": 9, "x": 6, "y": 0},
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "targets": [{"refId": "A", "expr": "increase(airflow_ti_failures[1h])"}]},
        {"id": 3, "title": "DAG run duration (s)", "type": "timeseries",
         "gridPos": {"h": 6, "w": 9, "x": 15, "y": 0},
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "targets": [{"refId": "A", "expr": "airflow_dagrun_duration_success{dag_id=\"yt_trending_hourly\"}"}]},
        {"id": 4, "title": "Silver rows 24h by region", "type": "timeseries",
         "gridPos": {"h": 8, "w": 12, "x": 0, "y": 6},
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "targets": [{"refId": "A", "expr": "yt_silver_rows_24h", "legendFormat": "{{region}}"}]},
        {"id": 5, "title": "Gold mart rows", "type": "timeseries",
         "gridPos": {"h": 8, "w": 12, "x": 12, "y": 6},
         "datasource": {"type": "prometheus", "uid": "prometheus"},
         "targets": [{"refId": "A", "expr": "yt_gold_mart_rows", "legendFormat": "{{mart}}"}]}
      ]
    }
```

- [ ] **Step 4: trending-insights dashboard（Postgres datasource uid `lakehouse-postgres`——P1 的「對外查詢」交付）**

Create `platform/monitoring/pipeline/trending-insights-dashboard.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-trending-insights
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  trending-insights.json: |
    {
      "uid": "yt-trending-insights",
      "title": "YT Trending Insights",
      "schemaVersion": 39,
      "editable": true,
      "time": {"from": "now-7d", "to": "now"},
      "refresh": "5m",
      "panels": [
        {"id": 1, "title": "Top velocity (delta views/hour)", "type": "table",
         "gridPos": {"h": 9, "w": 12, "x": 0, "y": 0},
         "datasource": {"type": "postgres", "uid": "lakehouse-postgres"},
         "targets": [{"refId": "A", "format": "table", "rawSql":
           "SELECT video_id, title, channel_title, region, captured_at, views, delta_views_per_hour FROM gold.gold_video_velocity_hourly ORDER BY delta_views_per_hour DESC NULLS LAST LIMIT 20"}]},
        {"id": 2, "title": "Channel ranking", "type": "table",
         "gridPos": {"h": 9, "w": 12, "x": 12, "y": 0},
         "datasource": {"type": "postgres", "uid": "lakehouse-postgres"},
         "targets": [{"refId": "A", "format": "table", "rawSql":
           "SELECT channel_title, region, videos_trended, total_views, days_on_chart, rank_in_region FROM gold.gold_channel_performance WHERE rank_in_region <= 10 ORDER BY region, rank_in_region"}]},
        {"id": 3, "title": "Category view share (%)", "type": "timeseries",
         "gridPos": {"h": 9, "w": 12, "x": 0, "y": 9},
         "datasource": {"type": "postgres", "uid": "lakehouse-postgres"},
         "targets": [{"refId": "A", "format": "time_series", "rawSql":
           "SELECT trending_date AS time, category_name AS metric, avg(view_share_pct) AS value FROM gold.gold_category_daily GROUP BY 1, 2 ORDER BY 1"}]},
        {"id": 4, "title": "Daily overview (total views, all regions)", "type": "stat",
         "gridPos": {"h": 9, "w": 12, "x": 12, "y": 9},
         "datasource": {"type": "postgres", "uid": "lakehouse-postgres"},
         "targets": [{"refId": "A", "format": "table", "rawSql":
           "SELECT sum(total_views) AS total_views, sum(total_videos) AS total_videos FROM gold.gold_trending_daily WHERE trending_date = (SELECT max(trending_date) FROM gold.gold_trending_daily)"}]}
      ]
    }
```

- [ ] **Step 5: Grafana Postgres datasource（sidecar datasource ConfigMap + envFromSecrets 注入密碼）**

Create `platform/monitoring/pipeline/grafana-datasource-lakehouse.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasource-lakehouse
  namespace: monitoring
  labels:
    grafana_datasource: "1"   # kube-prometheus-stack grafana datasource sidecar 預設 label（Task 0 C4 校準）
data:
  lakehouse-datasource.yaml: |
    apiVersion: 1
    datasources:
      - name: Lakehouse
        uid: lakehouse-postgres
        type: postgres
        access: proxy
        url: lakehouse-postgres.data.svc:5432
        user: grafana_reader
        jsonData:
          database: lakehouse
          sslmode: disable
        secureJsonData:
          password: $password   # Grafana provisioning env 展開；env 由 envFromSecrets 注入（secret key = password）
```

Modify `platform/argocd/apps/monitoring.yaml`——在 `grafana:` 區塊（`sidecar:` 同層）加：
```yaml
          envFromSecrets:
            - name: grafana-lakehouse-reader
              optional: true    # 未跑 pipeline-secrets 的純 P0 叢集不因缺 secret 卡 Grafana 啟動
```

- [ ] **Step 6: pipeline-monitoring 子 Application（wave 6，directory 型，形狀照抄 monitoring-dashboards）**

Create `platform/argocd/apps/pipeline-monitoring.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: pipeline-monitoring
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "6"
spec:
  project: default
  source:
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: platform/monitoring/pipeline
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 7: 驗證 + Commit**

```bash
python3 - <<'PY'
import json, yaml, glob
for f in glob.glob('platform/monitoring/pipeline/*.yaml') + ['platform/argocd/apps/pipeline-monitoring.yaml', 'platform/argocd/apps/monitoring.yaml']:
    docs = list(yaml.safe_load_all(open(f)))
    for d in docs:
        if d and d.get('kind') == 'ConfigMap':
            for k, v in d['data'].items():
                if k.endswith('.json'):
                    j = json.loads(v)
                    print(f, '→ dashboard title:', j['title'])
print('all YAML/JSON OK')
PY
grep -rn "storageClassName" platform/monitoring/pipeline && echo "VIOLATION" || echo "portability OK"
git add platform/monitoring/pipeline/ platform/argocd/apps/pipeline-monitoring.yaml platform/argocd/apps/monitoring.yaml
git commit -m "部署(monitoring)：pipeline 監控（statsd SM + 三告警 + YT 雙 dashboard + Postgres datasource，wave 6）"
```
Expected: 印出 `YT Pipeline Health` 與 `YT Trending Insights`；`all YAML/JSON OK`；`portability OK`。

---

## Task 14: verify-pipeline.sh（§12A 十檢查）+ Makefile targets + pr-checks 擴充

**Files:**
- Create: `scripts/verify-pipeline.sh`
- Modify: `Makefile`（`pipeline-verify`/`pipeline-trigger`/`demo-p1-up`/`demo-p1-down`）
- Modify: `.github/workflows/pr-checks.yaml`（paths + 三個 test job，不 build）

**Interfaces:**
- Consumes: 全叢集資源（Task 1–13）；P0 `make verify` 綠 + `make pipeline-secrets` 已跑為前置。
- Produces: `make pipeline-verify` 十檢查任一 fail 即非零退出；`make demo-p1-up/down` 分階段啟停（errata §D 第二層）。

- [ ] **Step 1: 建 scripts/verify-pipeline.sh（bash-3.2 安全；poll/trap 紀律照抄 scripts/verify.sh）**

Create `scripts/verify-pipeline.sh`：
```bash
#!/usr/bin/env bash
set -euo pipefail

fail() { echo "❌ $1"; exit 1; }
ok()   { echo "✅ $1"; }

PGEXEC="kubectl -n data exec lakehouse-postgres-0 -- psql -U postgres -d lakehouse -tAc"
AF_DEPLOY="deploy/airflow-api-server"   # chart 產出名；Task 15 校準
DAG_ID="yt_trending_hourly"

echo "[1/10] ArgoCD apps 收斂（10 個，timeout 900s）"
deadline=$(( $(date +%s) + 900 ))
while :; do
  json=$(kubectl -n argocd get applications -o json 2>/dev/null) || { [ "$(date +%s)" -gt "$deadline" ] && fail "ArgoCD 查詢持續失敗（timeout）"; sleep 10; continue; }
  total=$(echo "$json" | jq '.items | length')
  good=$(echo "$json" | jq '[.items[] | select(.status.sync.status=="Synced" and .status.health.status=="Healthy")] | length')
  [ "$total" = "10" ] && [ "$good" = "10" ] && break
  [ "$(date +%s)" -gt "$deadline" ] && fail "ArgoCD 未收斂：total=${total} synced+healthy=${good}（預期 10/10）"
  sleep 10
done
ok "10 個 app 全 Synced + Healthy"

echo "[2/10] 儲存底座：bronze/silver bucket 存在"
buckets=$(kubectl -n data exec lakehouse-minio-0 -- ls /data)
echo "${buckets}" | grep -q bronze || fail "bronze bucket 不存在"
echo "${buckets}" | grep -q silver || fail "silver bucket 不存在"
ok "bronze/silver bucket 存在"

echo "[3/10] 觸發一輪 ${DAG_ID} 並等 success（timeout 1800s）"
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags unpause "${DAG_ID}" >/dev/null 2>&1 || true
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags trigger "${DAG_ID}"
deadline=$(( $(date +%s) + 1800 ))
while :; do
  state=$(kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags list-runs "${DAG_ID}" -o json 2>/dev/null | jq -r '.[0].state')
  [ "${state}" = "success" ] && break
  [ "${state}" = "failed" ] && fail "dagrun failed（含 dbt_test DQ gate）"
  [ "$(date +%s)" -gt "$deadline" ] && fail "dagrun 未在 1800s 內完成（state=${state}）"
  sleep 20
done
ok "dagrun success（dbt_test 綠 = DQ gate 過）"

echo "[4/10] Bronze 有原始資料（TW 當前小時）"
hour_path="youtube_trending/region=TW/date=$(date -u +%F)/hour=$(date -u +%H)"
kubectl -n data exec lakehouse-minio-0 -- sh -c "find /data/bronze/${hour_path} -name 'snapshot.json*' | head -1" | grep -q snapshot.json \
  || fail "bronze 無 ${hour_path}/snapshot.json"
ok "bronze snapshot.json 存在（${hour_path}）"

echo "[5/10] Silver serving 有資料且為當前小時"
silver_count=$(${PGEXEC} "SELECT count(*) FROM silver.video_snapshots")
[ "${silver_count}" -gt 0 ] || fail "silver.video_snapshots 為空"
cur_hour=$(${PGEXEC} "SELECT count(*) FROM silver.video_snapshots WHERE captured_at = date_trunc('hour', now())")
[ "${cur_hour}" -gt 0 ] || fail "silver 無當前小時資料（Spark→pyiceberg→loader 鏈斷）"
ok "silver ${silver_count} 列，含當前小時 ${cur_hour} 列"

echo "[6/10] Gold 5 marts（velocity 首輪放寬為表存在）"
for mart in gold_trending_daily gold_channel_performance gold_category_daily gold_video_lifecycle; do
  c=$(${PGEXEC} "SELECT count(*) FROM gold.${mart}")
  [ "${c}" -gt 0 ] || fail "gold.${mart} 為空"
done
vel=$(${PGEXEC} "SELECT count(*) FROM gold.gold_video_velocity_hourly") || fail "gold_video_velocity_hourly 表不存在"
echo "  velocity 列數 = ${vel}（需第二輪快照後 > 0；首輪 0 屬正常）"
ok "gold marts 就緒"

echo "[7/10] 冪等：clear+rerun 同 logical date 後列數不膨脹"
before_silver=${silver_count}
before_gold=$(${PGEXEC} "SELECT count(*) FROM gold.gold_trending_daily")
run_lo=$(kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags list-runs "${DAG_ID}" -o json | jq -r '.[0].logical_date')
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow tasks clear "${DAG_ID}" -s "${run_lo}" -e "${run_lo}" -y
deadline=$(( $(date +%s) + 1800 ))
while :; do
  state=$(kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags list-runs "${DAG_ID}" -o json | jq -r '.[0].state')
  [ "${state}" = "success" ] && break
  [ "${state}" = "failed" ] && fail "重跑 failed"
  [ "$(date +%s)" -gt "$deadline" ] && fail "重跑未在 1800s 內完成"
  sleep 20
done
after_silver=$(${PGEXEC} "SELECT count(*) FROM silver.video_snapshots")
after_gold=$(${PGEXEC} "SELECT count(*) FROM gold.gold_trending_daily")
[ "${after_silver}" -le "${before_silver}" ] || fail "silver 列數膨脹：${before_silver} → ${after_silver}（非冪等）"
[ "${after_gold}" = "${before_gold}" ] || fail "gold_trending_daily 列數變動：${before_gold} → ${after_gold}"
ok "冪等 OK（silver ${after_silver} / gold ${after_gold} 未膨脹）"

echo "[8/10] 指標新鮮度 yt_freshness_seconds < 7200"
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 19090:9090 >/dev/null 2>&1 &
pf_pid=$!; trap 'kill "$pf_pid" 2>/dev/null || true' EXIT
sleep 4
fresh=$(curl -fsS 'http://localhost:19090/api/v1/query?query=yt_freshness_seconds' | jq -r '.data.result[0].value[1] // empty')
trap - EXIT; kill "$pf_pid" 2>/dev/null || true; wait "$pf_pid" 2>/dev/null || true
[ -n "${fresh}" ] || fail "yt_freshness_seconds 無值（exporter/ServiceMonitor 斷）"
[ "$(echo "${fresh} < 7200" | bc)" = "1" ] || fail "freshness 過期：${fresh}s"
ok "yt_freshness_seconds = ${fresh}"

echo "[9/10] Grafana 雙 dashboard 已載（sidecar 匯入最多等 180s）"
GRAFANA_PW=$(kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d)
deadline=$(( $(date +%s) + 180 ))
while :; do
  res=$(curl -fsS -u "admin:${GRAFANA_PW}" "http://grafana.localtest.me/api/search?query=YT" || echo "")
  echo "${res}" | grep -q "YT Pipeline Health" && echo "${res}" | grep -q "YT Trending Insights" && break
  [ "$(date +%s)" -gt "$deadline" ] && fail "Grafana 缺 YT dashboard（等了 180s）"
  sleep 10
done
ok "YT Pipeline Health + YT Trending Insights 已載"

echo "[10/10] 三個 image tag 可回溯（sha-* 且與 git bump 落點一致）"
af_tag=$(yq '.spec.source.helm.valuesObject.images.airflow.tag' platform/argocd/apps/airflow.yaml)
spark_tag=$(yq '.spark_job.tag' orchestration/airflow/dags/config/images.yaml)
dbt_tag=$(yq '.dbt.tag' orchestration/airflow/dags/config/images.yaml)
for t in "${af_tag}" "${spark_tag}" "${dbt_tag}"; do
  echo "${t}" | grep -q '^sha-' || fail "tag 非 sha-*（${t}）"
done
live_af=$(kubectl -n airflow get "${AF_DEPLOY}" -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "${live_af}" | grep -q "${af_tag}" || fail "airflow 部署 image 與 manifest 不一致（${live_af} vs ${af_tag}）"
ok "image 可回溯（airflow=${af_tag} spark=${spark_tag} dbt=${dbt_tag}）"

echo "🎉 全部 10 項管線驗收通過"
```

- [ ] **Step 2: Makefile 加 targets**

Modify `Makefile` 檔尾新增：
```makefile
pipeline-verify:       ## P1 端到端 10 檢查（前置：make verify 綠 + pipeline-secrets 已跑）
	./scripts/verify-pipeline.sh

pipeline-trigger:      ## 手動觸發一輪主 DAG
	kubectl -n airflow exec deploy/airflow-api-server -- airflow dags trigger yt_trending_hourly

demo-p1-down:          ## 暫停 P1 重量元件（GitOps 相容：關 auto-sync 再縮 0；騰記憶體給 host 重活）
	kubectl -n argocd patch application airflow --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
	kubectl -n airflow scale deploy --all --replicas=0
	kubectl -n airflow scale statefulset --all --replicas=0
	kubectl -n argocd patch application spark-operator --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
	kubectl -n spark-operator scale deploy --all --replicas=0

demo-p1-up:            ## 恢復：重開 auto-sync，ArgoCD selfHeal 收斂回來（1-3 分鐘）
	kubectl -n argocd patch application airflow --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
	kubectl -n argocd patch application spark-operator --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

- [ ] **Step 3: pr-checks.yaml 擴充（新三元件 test-only；沿用既有 test/portability-guard job 不動）**

Modify `.github/workflows/pr-checks.yaml`——`on.pull_request.paths` 追加：
```yaml
      - "ingestion/**"
      - "orchestration/airflow/**"
      - "lakehouse/**"
```
`jobs:` 追加三個 job（步驟與各 ci workflow 的 test job 逐字同款）：
```yaml
  test-ingestion-dags:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - run: |
          uv sync && uv run ruff check . && uv run pytest tests/ -v
        working-directory: ingestion/youtube
      - run: |
          uv venv /tmp/af-venv
          source /tmp/af-venv/bin/activate
          uv pip install "apache-airflow==3.2.2" "apache-airflow-providers-cncf-kubernetes" \
            --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.2.2/constraints-3.12.txt"
          uv pip install ./ingestion/youtube "pytest==9.1.1" "pyyaml==6.0.3"
          pytest orchestration/airflow/tests/ -v
  test-spark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-java@v5
        with: {distribution: temurin, java-version: "17"}
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - run: uv sync && uv run pytest tests/ -v
        working-directory: lakehouse/spark
  test-dbt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8.3.2
        with: {python-version: "3.12"}
      - run: |
          uv venv /tmp/dbt-venv && source /tmp/dbt-venv/bin/activate
          uv pip install dbt-postgres==1.10.2
          DBT_PG_PASSWORD=dummy dbt parse --profiles-dir . --project-dir .
        working-directory: lakehouse/dbt
```

- [ ] **Step 4: 語法驗證 + Commit**

```bash
chmod +x scripts/verify-pipeline.sh
bash -n scripts/verify-pipeline.sh && echo "verify-pipeline.sh 語法 OK"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pr-checks.yaml')); print('pr-checks YAML OK')"
make -n pipeline-verify pipeline-trigger demo-p1-down demo-p1-up >/dev/null && echo "make targets OK"
git add scripts/verify-pipeline.sh Makefile .github/workflows/pr-checks.yaml
git commit -m "驗收(pipeline)：verify-pipeline.sh 十檢查 + make pipeline-verify/demo-p1 啟停 + pr-checks 擴三 job"
```

---

## Task 15: 端到端整合（M4 runbook）+ live 校準 + README

**Files:**
- Modify: `README.md`（補 P1 章節）

**Interfaces:**
- Consumes: 前 14 task 全部產物。
- Produces: 完整可重現的 P1 管線（`make pipeline-verify` 十項全綠）+ 文件化 runbook + live 校準收尾。

- [ ] **Step 1: 合回 main 觸發三支 CI**

M1 本機（分支 → merge；直推 main 亦可，沿 P0 慣例）：
```bash
git push origin HEAD
gh pr create --fill && gh pr merge --squash --delete-branch   # 或 git push origin main
gh run list --limit 5   # 預期 airflow-ci / spark-ci / dbt-ci 各一 run
gh run watch --exit-status
```
Expected: 三支 CI 綠；出現三個 bot bump commit（airflow.yaml tag + images.yaml ×2，皆 `[skip ci]` 不再觸發）；GHCR 出現三個 public package（public repo 自動公開，免手動）。

- [ ] **Step 2: （M4）secrets + ArgoCD 收斂**

```bash
ssh 100.74.192.11
cd /Users/fergus/Desktop/workshop/fergus/data-workshop/fergus/trend-intelligence-platform
git pull --rebase origin main
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make pipeline-secrets YOUTUBE_API_KEY=<真 key>
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n argocd get applications -w   # 看 wave 3→4→5→6 依序收斂（~5-10 分鐘）
```
Expected: 10 個 Application 全 Synced+Healthy；`minio-bucket-init` Job 跑完自刪。

- [ ] **Step 3: （M4）live 校準清單（Task 0 標「live 複核」項，逐一收尾）**

```bash
# a) worker SA 名（RoleBinding subject）：
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get sa | grep worker
#    非 airflow-worker → 改 lakehouse/spark/k8s/rbac.yaml subject 後 commit
# b) statsd svc/port 名（ServiceMonitor）：
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get svc airflow-statsd -o jsonpath='{.spec.ports[*].name}'
# c) api-server deploy 名（verify-pipeline.sh AF_DEPLOY）：
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get deploy | grep api
# d) statsd 指標名前綴（PromQL：airflow_ti_failures / airflow_dagrun_duration_success）：
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow port-forward svc/airflow-statsd 19102:9102 >/dev/null 2>&1 &
sleep 3 && curl -s localhost:19102/metrics | grep -E "^airflow_(ti|dagrun)" | head; kill %1
#    不符 → 改 prometheusrule.yaml / pipeline-health dashboard 的 expr 後 commit
# e) pyiceberg sql catalog ↔ Spark JDBC catalog 互通煙囪（design §12B.3）：步驟 4 的 verify 檢查 5 即覆蓋
#    （serving 副本有資料 = Spark 寫入 → pyiceberg 讀出整鏈通）；失敗時單獨排查 catalog 表佈局。
# f) Grafana datasource 密碼展開：
curl -fsS -u "admin:$(PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d)" \
  "http://grafana.localtest.me/api/datasources/uid/lakehouse-postgres" | jq '.name'
#    預期 "Lakehouse"；panel 查詢失敗多半是 $password env 未展開 → 檢 envFromSecrets 是否生效（Task 0 C4）
```

- [ ] **Step 4: （M4）端到端驗收**

```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make pipeline-verify
```
Expected: `🎉 全部 10 項管線驗收通過`（檢查 6 velocity 首輪 0 屬正常；隔 1 小時第二輪後重跑，velocity > 0）。再驗 demo 啟停：
```bash
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make demo-p1-down && sleep 30
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get pods    # 預期空/Terminating
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin make demo-p1-up && sleep 120
PATH=/tmp/bin:/opt/homebrew/bin:/usr/bin:/bin kubectl -n airflow get pods    # 預期收斂回來
```

- [ ] **Step 5: 補 README P1 章節**

Modify `README.md` 新增（接既有內容後）：

````markdown
## P1 資料管線（YouTube 趨勢 lakehouse）

架構：Airflow（KubernetesExecutor，hourly ×8 區）→ MinIO Bronze（原始 JSON，決定性 key）→
SparkApplication（spark-operator）→ Iceberg Silver（JDBC catalog on Postgres）→
pyiceberg loader → Postgres silver serving → dbt → gold 5 marts（P2 資料合約）→ dbt test（DQ gate）。

```bash
make pipeline-secrets YOUTUBE_API_KEY=<key>   # 命令式 secret（不進 git；冪等）
make pipeline-trigger                          # 手動觸發一輪
make pipeline-verify                           # 端到端 10 檢查
make demo-p1-down / demo-p1-up                 # 暫停/恢復 P1 重量元件（跑 host 重活前先 down）
```

入口：Airflow http://airflow.localtest.me · Grafana `YT Pipeline Health` / `YT Trending Insights`。

### 範本債清理（搬遷不照抄，design §10 帳）

| 範本問題 | 本實作處置 |
|---|---|
| Silver 斷線（Spark 寫 Iceberg、dbt 讀 Postgres，不相通） | loader task 建 serving 副本，介面顯式化 |
| categories 無生產者 | `yt_categories_daily` 直送 Postgres |
| 日級去重打死 velocity | 去重鍵 `(video_id, region, captured_at)` 保小時粒度 |
| `docker exec` 觸發 Spark / dbt 任務必炸 / 死碼 exporter | spark-operator + KPO + postgres-exporter custom query |
| warehouse 跨桶錯置 / `.append()` 重複列 / `now()` 命名不冪等 / region 漂移 | 單一根 warehouse + overwritePartitions + 決定性 key + pipeline.yaml 單一真源 |

### Known limits

- `chart=mostPopular` 無歷史：某 region-hour 錯過 = 永久缺口（資料源特性）；catchup 永遠不開，重處理走 `yt_reprocess_range`（bronze 已有才有得重算）。
- Iceberg JDBC catalog 密碼經 DAG 注入 SparkApplication conf（rendered CRD 內可見，data ns 範圍；雲上換 REST catalog + IRSA 即消除）。
- velocity 需第二輪快照後才有資料。
````

- [ ] **Step 6: 可重現性最終驗證 + commit + push**

（M4）：
```bash
grep -rn "alb.ingress\|nginx.ingress\|storageClassName" lakehouse/ platform/ orchestration/ && echo "VIOLATION" || echo "可攜鐵律 OK"
```
M1：
```bash
git add README.md
git commit -m "文件(pipeline)：P1 README（runbook/範本債帳/known-limits）"
git push origin main
```
Expected: `可攜鐵律 OK`；（可選全重建證明：`make cluster-down && make cluster-up && make pipeline-secrets … && make pipeline-verify` 全綠——外部狀態僅 GHCR/git/API key）。

---

## Self-Review（planner 自檢，已執行）

**1. Spec coverage（design §§ → tasks）：**
- §0 版本 pin → Global Constraints + Task 0 A（存在性逐項驗證，errata §E）✅
- §1①②③ 三關鍵決策 → Task 10（KubernetesExecutor values）/ Task 5+8+11（spark-operator + SparkApplication）/ Task 3+2（MinIO plain manifest + JDBC catalog init SQL）✅
- §2 目錄/資源名/wave/ingress → File Structure + Global Constraints 表 + Task 4/5/10/13（wave 3/4/5/6）✅
- §3 ingest 決定 → Task 6（8 區單一真源讀 pipeline.yaml、quota fail-fast、決定性 key、信封）+ Task 9（動態映射、default_args 逐字、all_done）；categories @daily → Task 6 categories.py + Task 9 daily DAG ✅
- §4 MinIO/Iceberg/Postgres → Task 3（bucket-init PostSync、mc 冪等）+ Task 2（init SQL 四角色/兩條 default privileges/public GRANT/dbt CREATE）+ Task 8（catalog conf 逐 key）✅
- §5 Spark job → Task 11（顯式 schema、description 補抓、(video_id,region,captured_at) 去重、overwritePartitions、driver/executor 1c/1536m、SA、TTL、envFrom）+ Task 9（loader DDL/execute_values UPSERT、同名 app 先刪）✅
- §6/§6a dbt + 合約 → Task 12（staging/marts/schema 落點 macro、freshness 2h/4h 與 26h/50h、generic+singular 全 10 條、五 marts 欄位級照抄 §6a）；silver DDL 三處一致（Task 9 loader = Task 11 Iceberg DDL = Task 12 source 欄位）✅
- §7 編排 → Task 9（三 DAG、catchup=False、max_active_runs=1、dagrun_timeout 45m、execution_timeout 10m、reprocess params 形狀）+ Task 10（chart values 逐 key：metadataSecretName/gitSync subPath/ingress.apiServer/statsd/secret list）✅
- §8 CI/secrets → Task 7/11/12（三 workflow：paths 過濾、bump 落點不在觸發 paths、[skip ci]、concurrency、多架構 arm64）+ Task 1（secrets 表逐把）+ Task 14（pr-checks 擴充）✅
- §9 觀測 → Task 2（exporter 三 SQL 逐字）+ Task 13（三告警、雙 dashboard YT 前綴、datasource sidecar + envFromSecrets）✅
- §10 範本債 → 各 task 註記 + Task 15 README 帳 ✅
- §11 測試策略 → Task 6/9/11 TDD + Task 12 dbt parse/DQ + Task 14 端到端 ✅
- §12A 十檢查 → Task 14 逐項（1 收斂 10 app／2 bucket／3 觸發+poll／4 bronze／5 silver 當前小時／6 五 marts+velocity 放寬／7 clear+rerun 比列數／8 freshness<7200／9 /api/search?query=YT／10 tag 回溯）✅；§12B 實查 1/2/5/6/7 → Task 0 C1–C5；實查 3 → Task 15 Step 3e；實查 4 → dbt-postgres 自解析（Task 12 parse 即證）；實查 8 已消解（repo public，fergusKe 落地）✅
- errata §C 資源預算 → Task 0 B（全帳 + VM 10GiB USER-CONFIRM）；§D 啟停 → Task 14 demo-p1-up/down；§E pin 驗證 → Task 0 A；§F 環境事實 → Global Constraints + M4 標註 ✅

**2. Placeholder scan：** 無 TBD/「同 task N」；`sha-0000000` 為 design 明訂佔位 tag（CI 首跑 bump）。`<真 key>` 僅指使用者輸入的 YOUTUBE_API_KEY。全部 code step 完整可照抄。

**3. 名稱/型別一致性：** silver 18 欄三處一致（loader DDL＝Iceberg CREATE＝§6a＝dbt source 消費）；secret 名/key 名與 §8 表逐字一致（僅 additive 補 `pipeline-dsn`/`airflow-webserver-secret`）；image 全小寫 `ghcr.io/ferguske/...`；dashboard title `YT *` = verify 步驟 9 grep；exporter 指標名 = PromQL = §12A；regions 8 區 pipeline.yaml＝dbt accepted_values（pytest 對帳）。

**4. 設計歧義的解決（逐條）：**
1. **`LAKEHOUSE_PG_DSN` 注入來源**：design §8 說「組自 pipeline-password」但 chart `secret:` 只能映射既有 key → `lakehouse-postgres` secret **additive 補 key `pipeline-dsn`**（完整 DSN），env 直接映射之。
2. **PostgreSQL JDBC driver jar**：design §0 pin 表漏列，但 Iceberg JDBC catalog 在 Spark 端必需 → 補 `postgresql-42.7.7.jar`（Task 0 A4 驗證存在）。
3. **exporter 讀 gold 的權限**：design §4 只列兩條 default privileges，`yt_gold_mart_rows`（pipeline_writer 連線）讀不到 dbt_runner 建的 gold 表 → init SQL 補第三條 `ALTER DEFAULT PRIVILEGES … GRANT SELECT … TO pipeline_writer` + `GRANT USAGE ON SCHEMA gold TO pipeline_writer`。
4. **rbac.yaml 的 GitOps 交付**：design 限定 5 個新 Application、又要求 `lakehouse/spark/k8s/rbac.yaml` 存在 → spark-operator Application 用 **多源（`sources:`）** 掛第二個 git path（語意正確：Spark 執行面權限隨 operator）；airflow.yaml 保持單 `source`（CI bump 路徑合約）。
5. **單一模板服務 hourly 與 reprocess**：design 檔案清單只有一個 `spark_silver.yaml`、reprocess 又要「SparkApplication 帶範圍參數」→ 模板用 Jinja 條件分支（`params.start_hour` 有無）切換 name/arguments；silver_job.py 支援 `--start-hour/--end-hour` 範圍模式（overwritePartitions 天然覆寫多分區，冪等不變）。
6. **`airflow-webserver-secret`**：chart 未 pin webserver secret key 會每次 sync 生成隨機值造成元件重啟循環（P0 Grafana 同型雷）→ additive 補一把 secret + `webserverSecretKeySecretName`。
7. **Spark 端 JDBC catalog 密碼**：Iceberg catalog conf 無 env 機制 → DAG 從 `LAKEHOUSE_PG_DSN` 解出密碼經 `params.pg_password` 注入模板；密碼可見於 data ns 的 rendered CRD，記為 README known-limit（雲上 REST catalog 消除）。
8. **KPO pod 權限**：dbt KPO 跑在 data ns，airflow-worker SA 需 pods create/delete → 併入 rbac.yaml（design §5 只提 sparkapplications + pods/log，此為 KPO 成立的必要補充）。
9. **MinIO `up` 指標**：`LakehouseComponentDown` 需要 scrape MinIO → Task 3 補 ServiceMonitor + `MINIO_PROMETHEUS_AUTH_TYPE=public`（ClusterIP 不外露，可接受）。
10. **loader 空掃描視為失敗**：design 說 Spark 空輸入自然 fail；loader 若掃到 0 列（Spark 綠但沒寫進本小時）屬鏈路異常 → loader 顯式 raise，避免 silent 空轉綠燈。

**執行注意：** Task 5 依賴 Task 11 的 rbac 目錄（先 .gitkeep 佔位）；Task 9 的 config 一致性測試在 Task 12 後才全綠（兩處都有標註）；Task 15 前三支 CI 必須先綠（image tag 佔位 sha-0000000 在 bump 前叢集拉不到 image，airflow app 收斂依賴首次 CI bump）。
