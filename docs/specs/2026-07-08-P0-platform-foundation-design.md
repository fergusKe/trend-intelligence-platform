# P0 平台底座 — Design（Fable 5 產出）

> **狀態**：design 完成，待 Opus 寫 implementation plan。
> **上游**：[`2026-07-08-P0-platform-foundation-brief.md`](2026-07-08-P0-platform-foundation-brief.md) + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md)。已鎖定決策（kind / ArgoCD app-of-apps / GitHub Actions+GHCR / kube-prometheus-stack / nginx-ingress）全部沿用，未翻案。
> **版本查證日**：2026-07-08（以下版本 pin 皆當日對官方源查證，非記憶）。

---

## 0. 版本 pin 表（已查證）

| 元件 | 版本 | 查證方式 |
|---|---|---|
| kind | **v0.32.0** | GitHub releases latest |
| kind node image | **`kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5`** | v0.32.0 release notes 標明之預設 image（帶 digest pin） |
| ArgoCD | **v3.4.4**，`https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.4/manifests/install.yaml` | releases latest + URL 200 已驗 |
| ingress-nginx Helm chart | **4.15.1**（= controller v1.15.1） | chart index.yaml 對照 appVersion |
| kube-prometheus-stack Helm chart | **87.10.1** | prometheus-community releases |
| hello service | Python 3.12 + FastAPI + `prometheus-fastapi-instrumentator` | — |

CI actions pin：`actions/checkout@v5`、`astral-sh/setup-uv@v4`、`docker/setup-buildx-action@v3`、`docker/login-action@v3`、`docker/build-push-action@v6`。GitHub ubuntu-latest runner 內建 `yq`（改 manifest 用，不需額外安裝）。

---

## 1. 總體形狀與目錄結構

單 repo GitOps：ArgoCD watch 本 repo，root Application 指向 `platform/argocd/apps/`（app-of-apps）。hello service 是**平台常駐金絲雀**（不是用完即丟的 demo；P1 起真服務上線後它續留當底座自測——`make verify` 永遠打得到它）。

```
trend-intelligence-platform/
├── Makefile                          # cluster-up / cluster-down / verify / argocd-ui
├── scripts/
│   └── verify.sh                     # 端到端驗收腳本（§8）
├── .github/workflows/
│   ├── hello-ci.yaml                 # main push：test→build→GHCR→bump tag→commit
│   └── pr-checks.yaml                # PR：lint + test（不 build push）
└── platform/
    ├── bootstrap/                    # ★ 命令式邊界：只有這個目錄的東西用 kubectl/kind 手打
    │   ├── kind-cluster.yaml         # kind Cluster config（3 node）
    │   └── root-app.yaml             # app-of-apps root Application
    ├── argocd/
    │   └── apps/                     # root app 的 source path；每檔一個子 Application
    │       ├── ingress-nginx.yaml    # Helm chart 4.15.1（wave 0）
    │       ├── monitoring.yaml       # kube-prometheus-stack 87.10.1（wave 1）
    │       ├── monitoring-dashboards.yaml  # 指向 platform/monitoring/dashboards/（wave 2）
    │       └── hello.yaml            # 指向 platform/hello/k8s/（wave 2）
    ├── monitoring/
    │   └── dashboards/
    │       └── hello-service-dashboard.yaml   # ConfigMap（grafana_dashboard: "1"）
    └── hello/
        ├── pyproject.toml
        ├── Dockerfile
        ├── src/hello/main.py
        ├── tests/test_main.py
        └── k8s/
            ├── kustomization.yaml    # images: newTag ← CI 唯一改的檔
            ├── deployment.yaml
            ├── service.yaml
            ├── servicemonitor.yaml
            └── ingress.yaml
```

**hello 位置定案**：`platform/hello/`（非 `apps/hello/`）。理由：repo 頂層已按 NORTH_STAR 立了五個 domain 目錄（`ingestion/` `lakehouse/` `ml/` `orchestration/` `platform/`），P1+ 真服務進各自 domain 目錄，不需要第六個頂層 `apps/`；hello 是底座自測設施，歸屬 platform。**未來服務接入契約**：任一目錄底下放 kustomize 化的 `k8s/` + 在 `platform/argocd/apps/` 加一個子 Application 檔，即被 GitOps 接管——這就是 P1 服務的上線形狀。

**Namespace 佈局**：`argocd` / `ingress-nginx` / `monitoring` / `apps`（hello 跑在 `apps`）。各子 Application 用 `CreateNamespace=true` 自建，不另寫 Namespace manifest。

**主機名路由**：全用 `*.localtest.me`（公共 DNS 永遠解到 127.0.0.1，零 /etc/hosts 編輯）：`hello.localtest.me`、`grafana.localtest.me`。ArgoCD UI 不走 ingress（§3 說明）。

---

## 2. P0-1 kind 叢集（決定）

### 開放問題收斂

| 問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| 幾個 node | **1 control-plane + 2 worker** | 展示多節點排程與 node-exporter 多實例（portfolio 訴求「像生產」）；單節點省資源但示範性弱。資源代價可控（~6GB RAM 級）。 |
| extraPortMappings | **control-plane 上 80→80、443→443，`listenAddress: 127.0.0.1`** | kind 官方 ingress 配方：ingress controller 以 hostPort 綁在帶 `ingress-ready=true` label 的節點。綁 127.0.0.1 避免筆電對區網開 80。若本機 80 被佔，改 hostPort 8080/8443 是唯一要動的檔（已在檔內註解）。 |
| bootstrap 形式 | **Makefile 為唯一入口**（`make cluster-up`），內部直接呼叫 kind/kubectl，不另寫 shell script 層 | 步驟少（3 條命令 + 2 個 wait），script 層是多餘 indirection；`verify.sh` 例外（邏輯多，獨立成檔）。 |
| 叢集建立納入 GitOps？ | **不納入**。命令式邊界 = `platform/bootstrap/` 全部內容：①kind create ②ArgoCD install ③root-app apply。此外一切（含 ingress-nginx、監控）皆 ArgoCD 管 | 叢集與 ArgoCD 自身是 GitOps 的先決條件，必然命令式；界線收最窄。 |

### `platform/bootstrap/kind-cluster.yaml`

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: trend-platform
nodes:
  - role: control-plane
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
    labels:
      ingress-ready: "true"          # ingress-nginx nodeSelector 對準這個
    extraPortMappings:
      - containerPort: 80
        hostPort: 80                  # 本機 80 被佔時改 8080，其餘不動
        listenAddress: "127.0.0.1"
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        listenAddress: "127.0.0.1"
        protocol: TCP
  - role: worker
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
  - role: worker
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
```

### Makefile（關鍵 target）

```makefile
ARGOCD_VERSION := v3.4.4

cluster-up:            ## 一鍵：叢集 → ArgoCD → root app（之後全靠 GitOps 收斂）
	kind get clusters | grep -q '^trend-platform$$' || \
	  kind create cluster --config platform/bootstrap/kind-cluster.yaml
	kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/$(ARGOCD_VERSION)/manifests/install.yaml
	kubectl -n argocd rollout status deploy/argocd-server --timeout=180s
	kubectl apply -f platform/bootstrap/root-app.yaml
	@echo "Bootstrap 完成。之後由 ArgoCD 收斂（~3-5 分鐘），跑 make verify 驗收。"

cluster-down:
	kind delete cluster --name trend-platform

verify:
	./scripts/verify.sh

argocd-ui:             ## port-forward + 印初始密碼
	@kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
	kubectl -n argocd port-forward svc/argocd-server 8081:443
```

`cluster-up` 冪等（重跑不炸），乾淨機器前置需求只有：Docker、kind、kubectl、make。

---

## 3. P0-2 ArgoCD + app-of-apps（決定）

### 開放問題收斂

| 問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| ArgoCD 自身怎麼裝 | **命令式 `kubectl apply` pinned v3.4.4 install.yaml**（URL 已驗 200），不自我管理 | 自我管理（ArgoCD 管 ArgoCD）是加分花活但引入升級死鎖風險，P0 不做；列 P4 選配。不 vendor install.yaml 進 repo（4 萬行噪音），版本 pin 在 Makefile 一處。不用 Helm 裝 ArgoCD（多一個工具層，manifest 即夠）。 |
| app-of-apps 目錄 | root app source = `platform/argocd/apps/`（directory 型，`recurse: false`），每個子 Application 一檔 | 一檔一元件，diff 清楚；不用 Helm 模板化 app-of-apps（YAGNI，元件才 4 個）。 |
| sync policy | **全部 Application（含 root）：`automated: {prune: true, selfHeal: true}` + retry**；monitoring 另加 `ServerSideApply=true` | prune+selfHeal 才是完整 GitOps 故事（git 是唯一真源、手改會被扳回）——portfolio 就要秀這個。kube-prometheus-stack CRD 超過 annotation 大小限制，**必須** ServerSideApply。 |
| repo public/private | **public**（求職 portfolio，本來就要被看） | 連帶效應：ArgoCD 匿名 https 拉 repo（零 repo credential）、GHCR public image（kind 節點免 imagePullSecret）→ **P0 全程零 secret**（§7）。private 方案（repo secret + imagePullSecret）寫進 README 附錄即可，不實作。 |
| ArgoCD UI 曝露 | **只 port-forward（`make argocd-ui`），不開 ingress** | ArgoCD server 走 https，nginx 前置需要 `backend-protocol: HTTPS` 這類 **nginx 專屬註解**或開 insecure mode——兩者都髒了「ingress 零控制器專屬註解」的可攜承諾。UI 是管理面不是服務面，port-forward 夠用。 |

### `platform/bootstrap/root-app.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-root
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: default
  source:
    repoURL: https://github.com/<GITHUB_OWNER>/trend-intelligence-platform   # ★ plan 前需實查：repo 尚未建 remote
    targetRevision: main
    path: platform/argocd/apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    retry:
      limit: 10
      backoff: {duration: 15s, factor: 2, maxDuration: 3m}
```

### 子 Application：ingress-nginx（wave 0）

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: default
  source:
    repoURL: https://kubernetes.github.io/ingress-nginx
    chart: ingress-nginx
    targetRevision: 4.15.1
    helm:
      valuesObject:
        controller:
          hostPort: {enabled: true}          # 對接 kind extraPortMappings
          nodeSelector: {ingress-ready: "true"}
          tolerations:
            - key: node-role.kubernetes.io/control-plane
              operator: Exists
              effect: NoSchedule
          service: {type: ClusterIP}          # kind 無 LB；EKS 換法見 §9
          watchIngressWithoutClass: false
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-nginx
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

（淘汰方案：vendor kind 官方 `provider/kind/deploy.yaml` 進 repo——可行且是驗證過的配方，但 Helm values 形式把「kind 專屬的部分」集中成一個 valuesObject，EKS 抽換只動這一檔，可攜性敘事更乾淨。values 內容即官方 kind provider manifest 的等價物。）

### 雞生蛋界線與順序（正本）

```
[命令式，一次性，make cluster-up]
  1. kind create cluster          （叢集本身）
  2. kubectl apply ArgoCD v3.4.4  （GitOps 引擎自身）
  3. kubectl apply root-app.yaml  （把方向盤交給 git 的那一下）
────────────────────────────────────────────
[宣告式，之後永遠走 git commit → ArgoCD sync]
  wave 0: ingress-nginx（Helm 4.15.1）
  wave 1: monitoring = kube-prometheus-stack 87.10.1（ServerSideApply；帶入 ServiceMonitor CRD）
  wave 2: monitoring-dashboards（ConfigMap）＋ hello（Deployment/Service/ServiceMonitor/Ingress）
```

sync-wave 標在子 Application metadata 上做**排序提示**；真正的健壯性靠每個 app 的 automated retry——特別是 hello 的 ServiceMonitor 依賴 wave 1 的 CRD，在 `servicemonitor.yaml` 資源上加 `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true` 註解，讓 CRD 尚未就位時 dry-run 不炸、retry 收斂（這是官方建議的 CRD 先後解法）。

---

## 4. P0-3 GitHub Actions CI（決定）

### 開放問題收斂

| 問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| image tag 策略 | **`sha-<7碼 short sha>`**（如 `sha-a1b2c3d`），main 另推 `latest` 浮動 tag 純供人肉 docker pull | 不可變、可回溯到 commit；semver 對內部服務是儀式負擔；run_id（Abhishek 用法）查不回 commit。tag 由 workflow 一個 env 算出，build 與 manifest 更新共用同一變數，杜絕兩處算法漂移。 |
| 改 manifest 工具 | **kustomization.yaml 的 `images:` 區塊當 tag 載體，CI 用 `yq` 改 `newTag`** | sed 是 regex 賭博（Abhishek 原版 `s|image: .*|...|` 會誤傷多容器）；`kustomize edit` 語意同 yq 但 runner 沒預裝 kustomize binary、yq 有預裝。宣告式載體（kustomize）＋結構化編輯（yq）= 兩全。ArgoCD 原生吃 kustomize 目錄。 |
| CI 迴圈防護 | **雙保險**：①workflow `paths` 過濾只認 `platform/hello/` 的 src/tests/Dockerfile/pyproject（**不含 `k8s/`**）②bump commit 訊息帶 `[skip ci]`（GitHub 原生支援） | 單靠 `[skip ci]` 太脆（訊息被改就迴圈）；paths 過濾是結構性保證。 |
| GHCR 認證 | **`GITHUB_TOKEN`**，job 級 `permissions: {contents: write, packages: write}`；不用 PAT | 同 repo 推 image＋推 commit，GITHUB_TOKEN 全夠。⚠️ gotcha：GITHUB_TOKEN 的 push **不會觸發其他 workflow**（GitHub 防迴圈設計）——對我們是 feature 不是 bug（ArgoCD 拉 git，不靠 workflow 接力）。 |
| 多服務擴充形狀 | **每服務一支 workflow + paths 過濾**（monorepo path-filter 模式）；P0 先立 `hello-ci.yaml` 當範本 | 每服務獨立 workflow 檔在 Actions UI 一眼一條產線、失敗隔離；P1 新服務 = 複製改路徑。共用邏輯膨脹時再抽 reusable workflow（YAGNI）。 |
| 併發 | `concurrency: {group: hello-ci, cancel-in-progress: false}` + push 前 `git pull --rebase` | 連push時 bump commit 不互撞。 |

### `.github/workflows/hello-ci.yaml`（關鍵形狀）

```yaml
name: hello-ci
on:
  push:
    branches: [main]
    paths:
      - "platform/hello/src/**"
      - "platform/hello/tests/**"
      - "platform/hello/Dockerfile"
      - "platform/hello/pyproject.toml"
      # 刻意不含 platform/hello/k8s/ → bump commit 不會再觸發
concurrency:
  group: hello-ci
  cancel-in-progress: false
env:
  IMAGE: ghcr.io/${{ github.repository }}/hello   # ghcr.io/<owner>/trend-intelligence-platform/hello
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v4
        with: {python-version: "3.12"}
      - run: uv sync
        working-directory: platform/hello
      - run: uv run ruff check .
        working-directory: platform/hello
      - run: uv run pytest tests/ -v
        working-directory: platform/hello

  build-push-bump:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write        # push bump commit
      packages: write        # push GHCR
    steps:
      - uses: actions/checkout@v5
      - id: tag
        run: echo "TAG=sha-$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: platform/hello
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ steps.tag.outputs.TAG }}
            ${{ env.IMAGE }}:latest
      - name: Bump manifest tag（GitOps 交棒點）
        run: |
          yq -i '.images[0].newTag = "${{ steps.tag.outputs.TAG }}"' platform/hello/k8s/kustomization.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add platform/hello/k8s/kustomization.yaml
          git commit -m "ci(hello): bump image to ${{ steps.tag.outputs.TAG }} [skip ci]"
          git pull --rebase origin main
          git push origin main
```

`pr-checks.yaml`：`on: pull_request` 同 paths（＋`k8s/**`），只跑 test job（lint+pytest），不 build 不 push。

**GHCR 首推 gotcha（寫進 README runbook）**：public repo 首次推出的 GHCR package 預設仍是 **private** → kind 節點拉不動。一次性手動：GitHub → Packages → hello → Change visibility → Public。這是 P0 唯一的手動 UI 步驟；不做的替代（imagePullSecret）列附錄。

---

## 5. P0-4 可觀測性（決定）

### 開放問題收斂

| 問題 | 決定 | 理由 / 淘汰方案 |
|---|---|---|
| 誰管 kube-prometheus-stack | **ArgoCD 管（GitOps）**，子 Application 直指 Helm chart 87.10.1，values 用 `valuesObject` 內嵌在 Application 檔 | 命令式 helm install 會在「一切宣告式」的臉上開洞；ArgoCD 裝好後完全有能力管它（雞生蛋只存在於 ArgoCD 自身，§3 已畫界）。values 內嵌單檔 diff 直觀，不用 multi-source valueFiles（多一層 indirection）。 |
| ServiceMonitor 發現 | chart values 設 **`serviceMonitorSelectorNilUsesHelmValues: false`** + `serviceMonitorNamespaceSelector: {}` → Prometheus 撿**全叢集所有** ServiceMonitor，hello 的 ServiceMonitor 不必知道 helm release 名 | 預設行為只認帶 `release: monitoring` label 的 ServiceMonitor——服務側被迫耦合監控側的 release 名，醜。放開 selector 是官方 values 註解明載的用法。 |
| Grafana dashboard 版本化 | **sidecar ConfigMap**（chart 預設開）：dashboard JSON 包成帶 `grafana_dashboard: "1"` label 的 ConfigMap，放 `platform/monitoring/dashboards/`，由獨立子 Application `monitoring-dashboards`（directory 型）sync | dashboard 進 git、改 dashboard = git diff（GitOps 故事完整）。塞 helm values 會讓 Application 檔爆長；Grafana UI 手做不進版控（淘汰）。獨立成第二個 app 是因為一個 Application 一個 source（helm chart 與 raw manifest 不混）。 |
| 監控 storage | **emptyDir（chart 預設，storageSpec 不設）** | demo 叢集重建即重來，PVC 是假持久（kind 刪叢集照樣沒）；**刻意不寫 storageClassName**——這正是可攜約束，EKS 版在 README 給 storageSpec 範例。 |
| Grafana 登入 | chart 預設 `admin/prom-operator`（公開預設值，非 secret），README 標注「僅本地 demo；雲上改 `admin.existingSecret`」 | 自訂密碼反而變成「git 裡的 secret」違反 §7。 |

### 子 Application：monitoring（wave 1，關鍵 values）

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  project: default
  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    targetRevision: 87.10.1
    helm:
      valuesObject:
        prometheus:
          prometheusSpec:
            serviceMonitorSelectorNilUsesHelmValues: false   # 撿全叢集 ServiceMonitor
            podMonitorSelectorNilUsesHelmValues: false
            serviceMonitorNamespaceSelector: {}
            retention: 24h
            # storageSpec 刻意不設 → emptyDir；EKS 版見 README 可攜章節
        grafana:
          ingress:
            enabled: true
            ingressClassName: nginx
            hosts: [grafana.localtest.me]
          sidecar:
            dashboards: {enabled: true, label: grafana_dashboard}
        alertmanager: {enabled: true}
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true, ServerSideApply=true]   # CRD 過大，SSA 必須
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

### hello dashboard（`platform/monitoring/dashboards/hello-service-dashboard.yaml`）

ConfigMap（namespace `monitoring`，label `grafana_dashboard: "1"`），data 內嵌 dashboard JSON。面板最小集（吃 `prometheus-fastapi-instrumentator` 的標準指標）：

1. RPS：`sum(rate(http_requests_total{handler!~"/metrics|/healthz"}[5m]))`
2. p95 延遲：`histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
3. 4xx/5xx 率、4. `kube_pod_container_status_restarts_total{namespace="apps"}`（重啟數，來自 kube-state-metrics）

JSON 取材參考：`yt-trending-platform/monitoring/grafana/dashboards/pipeline-health.json`（同為 file-provisioned dashboard，改 datasource 為 chart 內建 Prometheus uid 慣例）。

---

## 6. P0-5 hello service（決定）

### 開放問題收斂

| 問題 | 決定 |
|---|---|
| 放哪 | `platform/hello/`，**常駐金絲雀**（見 §1，不會被 P1 取代刪除）。 |
| 驗收自動化程度 | **兩段式**：①`make verify`（`scripts/verify.sh`）全自動驗叢集側端到端（§8）②CI→GitOps 迴圈驗證是**文件化 runbook**（改一行→push→觀察），不寫成自動腳本——自動腳本得替使用者產 commit 推 main，副作用大於價值（YAGNI）。 |

### 服務本體

- FastAPI + **`prometheus-fastapi-instrumentator`**（成熟套件直接給 `http_requests_total` / `http_request_duration_seconds` histogram，不手刻 middleware）：
  ```python
  from fastapi import FastAPI
  from prometheus_fastapi_instrumentator import Instrumentator

  app = FastAPI()
  Instrumentator().instrument(app).expose(app)   # GET /metrics

  @app.get("/healthz")
  def healthz():
      return {"status": "ok"}
  ```
- 測試（pytest + httpx TestClient）：`/healthz` 200 + body、`/metrics` 200 且含 `http_request`。
- Dockerfile：`python:3.12-slim`、uv 裝依賴、non-root user、`uvicorn hello.main:app --host 0.0.0.0 --port 8000`。

### k8s manifests（kustomize）

`kustomization.yaml`（CI 唯一觸碰的檔）：

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: apps
resources: [deployment.yaml, service.yaml, servicemonitor.yaml, ingress.yaml]
images:
  - name: ghcr.io/<GITHUB_OWNER>/trend-intelligence-platform/hello
    newTag: sha-0000000   # 佔位；首次 CI run 會 bump 成真 tag
```

- **deployment.yaml**：replicas 2（rolling update 可觀察）、`readinessProbe`/`livenessProbe` 都打 `/healthz`、resources requests `50m/64Mi` limits `200m/128Mi`、`securityContext: {runAsNonRoot: true}`。
- **service.yaml**：ClusterIP，port 80 → targetPort 8000，port name `http`（ServiceMonitor 引用 port 名非數字）。
- **servicemonitor.yaml**：`endpoints: [{port: http, path: /metrics, interval: 15s}]`；資源註解 `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true`（§3 CRD 先後解法）。
- **ingress.yaml**：`ingressClassName: nginx` + host `hello.localtest.me` + path `/` Prefix。**零 annotation**（可攜鐵律：不用任何 nginx/ALB 專屬註解；Abhishek 範本的 `alb.ingress.kubernetes.io/*` 即反例）。

### 子 Application：hello（wave 2）

source path `platform/hello/k8s`（ArgoCD 自動辨識 kustomize），destination namespace `apps`，sync policy 同 §3 標準（automated+prune+selfHeal+CreateNamespace+retry）。

**首次上線順序注意**：kustomization 佔位 tag `sha-0000000` 在 GHCR 不存在 → repo 首次 push 到 GitHub 後 CI 會立即跑第一輪、產生真 image + bump commit；`make cluster-up` 在那之後任何時點執行都收斂。若順序顛倒（先起叢集後推 repo），hello 短暫 ImagePullBackOff，CI 跑完 + ArgoCD 下一輪 poll（≤3 分鐘)自癒——這本身就是 GitOps 自癒的 demo，README 如實寫。

---

## 7. Secrets 姿態（硬約束③）

**P0 設計成零 secret**：public repo（ArgoCD 匿名拉）＋ public GHCR image（節點匿名拉）＋ Grafana 用 chart 公開預設密碼 ＋ ArgoCD 初始密碼由叢集內自動生成（`make argocd-ui` 現場讀，不落地）。git 裡沒有任何憑證，也沒有「假裝是設定的密碼」。

README 寫明**secret 邊界策略**：P1 起第一個真 secret（YouTube API key）出現時，用「命令式 `kubectl create secret`（文件化、不進 git）」起步，屆時再評估 sealed-secrets / external-secrets（P0 不預裝——一個工作一個工具，硬約束④）。

---

## 8. 端到端驗收清單

### A. `scripts/verify.sh`（`make verify`，全自動，任一步 fail 即非零退出）

| # | 檢查 | 命令要點 | 預期 |
|---|---|---|---|
| 1 | 節點就緒 | `kubectl get nodes` | 3 節點 `Ready` |
| 2 | ArgoCD apps 收斂 | `kubectl -n argocd get applications -o json` 輪詢（timeout 600s） | 5 個 app（root+4 子）全 `Synced` + `Healthy` |
| 3 | hello 健康 | `curl -fsS http://hello.localtest.me/healthz` | HTTP 200，`{"status":"ok"}` |
| 4 | hello 指標 | `curl -fsS http://hello.localtest.me/metrics` | 含 `http_requests_total` |
| 5 | Prometheus 已 scrape | port-forward `svc/monitoring-kube-prometheus-prometheus 9090` → `/api/v1/query?query=up{namespace="apps"}` | 結果非空且 value=1 |
| 6 | Grafana 起來＋dashboard 已載 | `curl -fsS http://grafana.localtest.me/api/health`；`/api/search?query=Hello`（basic auth 預設帳密） | health `ok`；search 命中 hello dashboard |
| 7 | 部署 image 可回溯 | `kubectl -n apps get deploy hello -o jsonpath='{...image}'` | tag 形如 `sha-*` 且等於 kustomization.yaml 的 newTag |

（第 5 步 svc 名依 release 名 `monitoring` 推得；plan 實作時以 `kubectl -n monitoring get svc` 實際名為準。）

### B. CI→GitOps 迴圈 runbook（文件化手動驗證，一次性）

1. 改 `platform/hello/src/hello/main.py` 回傳值（如加欄位）→ commit + push main。
2. Actions：`hello-ci` 綠（test → build-push-bump）；repo 出現 bot commit `ci(hello): bump image to sha-xxxxxxx [skip ci]`，**且該 commit 不再觸發 workflow**。
3. ≤3 分鐘內 ArgoCD hello app `OutOfSync→Syncing→Synced`；`kubectl -n apps get pods -w` 看到 rolling update。
4. `curl hello.localtest.me/healthz` 回傳新欄位。
5. Grafana hello dashboard RPS 面板有曲線（verify 腳本的 curl 也算流量）。

### C. 可重現性

`make cluster-down && make cluster-up && make verify` 全綠（唯一外部狀態 = GHCR image + git repo，皆在叢集外）。

---

## 9. 雲端可攜（硬約束②，README 要能宣稱）

| 層 | kind（本設計） | 換 EKS 時動什麼 |
|---|---|---|
| 叢集 | `platform/bootstrap/kind-cluster.yaml` | 換 eksctl/Terraform（P0 範圍外）；`platform/argocd/` 以下**零改動** |
| ingress controller | `apps/ingress-nginx.yaml`（hostPort+nodeSelector values） | 只改這一檔：刪 kind 專屬 values 改 `service.type: LoadBalancer`，或整檔換 AWS Load Balancer Controller 的 Application |
| 各服務 Ingress | `ingressClassName: nginx`、**零控制器專屬 annotation** | 若留 nginx：不動；若換 ALB：只改 ingressClassName（＋屆時才加 alb 註解） |
| storage | 不寫任何 storageClassName（監控 emptyDir） | 需要持久化時 values 加 storageSpec + 目標叢集的 class 名 |
| DNS | `*.localtest.me` | 換真域名，只改 ingress host 與 grafana values |

設計驗證點：`grep -r "alb.ingress" platform/` 與 `grep -r "storageClassName" platform/` 皆須為空（可列入 pr-checks 當守門，plan 可選）。

---

## 10. 「plan 前需實查」清單（全部收斂後僅剩這些外部前置/落地校準）

1. **GitHub repo 尚未建立**（`git remote -v` 為空，2026-07-08 查證）：需先建 public repo 並 push，才有 root-app `repoURL`、CI、GHCR。design 中 `<GITHUB_OWNER>` 佔位符屆時代入。
2. **GHCR package 首推後手動設 public**（§4 gotcha，一次性 UI 操作，寫進 plan 的 task 與 README）。
3. verify.sh 第 5/6 步的 **監控 svc 實際名稱**（`monitoring-kube-prometheus-prometheus` 為 release 名推導，落地時 `kubectl -n monitoring get svc` 校準一次）。
4. 本機 **80/443 端口占用檢查**（被佔則 kind-cluster.yaml 改 8080/8443，檔內已註解）。

以上皆為環境前置或落地校準，無未收斂的設計決策。

---

## 11. 落地後校驗（design 自檢摘要）

- 五簇開放問題全部收斂為決定（§2–§6 各簇決策表）；已鎖定決策零翻案。
- 硬約束對照：①宣告式界線 §3（命令式僅 bootstrap 三步）②可攜 §9 ③零 secret §7 ④P0 未引入 Airflow/Postgres/sealed-secrets 等任何超綱工具 ⑤`make cluster-up` §2 ⑥CI 測試 §4 + 驗收 §8。
- 對參考素材的「進化方向」：Abhishek sed→kustomize+yq、DockerHub PAT→GHCR GITHUB_TOKEN、ALB 註解→零註解 ingress、run_id tag→git sha tag；yt-trending 靜態 prometheus.yml→ServiceMonitor CRD 動態發現。
