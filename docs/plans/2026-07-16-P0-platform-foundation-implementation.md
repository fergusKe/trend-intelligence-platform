# P0 平台底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建起一個本地 kind Kubernetes 叢集，由 ArgoCD app-of-apps 以 GitOps 收斂 ingress-nginx / kube-prometheus-stack / 一個常駐 `hello` 金絲雀服務，並用 GitHub Actions CI（test→GHCR→bump manifest）閉環展示「push → 自動部署」。

**Architecture:** 單一 public repo 即 GitOps 真源。命令式邊界收到最窄的三步（`make cluster-up`：kind 建叢集 → kubectl 裝 ArgoCD → apply root-app），之後一切走 `git commit → ArgoCD sync`。root Application 掃 `platform/argocd/apps/` 目錄，每個子 Application 一檔，用 sync-wave 0/1/2 排序。P0 全程零 secret（public repo 匿名拉 git、public GHCR 匿名拉 image、Grafana/ArgoCD 密碼叢集內隨機生成現場讀）。

**Tech Stack:** kind v0.32.0 · ArgoCD v3.4.4 · ingress-nginx Helm 4.15.1 · kube-prometheus-stack Helm 87.10.1 · FastAPI 0.139.0 + prometheus-fastapi-instrumentator 8.0.2 · uv 0.11 · GitHub Actions + GHCR · kustomize（ArgoCD 原生）+ yq。

## Global Constraints

以下為 P0 design（`docs/specs/2026-07-08-P0-platform-foundation-design.md`）鎖定值，**每個 task 都隱含遵守**，版本一字不改（design §0 於 2026-07-08 對官方源查證）：

- **版本 pin（禁漂）**：kind `v0.32.0`；kind node image `kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5`；ArgoCD `v3.4.4`；ingress-nginx chart `4.15.1`；kube-prometheus-stack chart `87.10.1`；FastAPI `0.139.0`；`prometheus-fastapi-instrumentator` `8.0.2`；uvicorn `0.50.2`；pytest `9.1.1`；httpx `0.28.1`；ruff `0.15.20`；uv base image `ghcr.io/astral-sh/uv:0.11`；Python `>=3.12`。
- **CI actions pin**：`actions/checkout@v7`、`astral-sh/setup-uv@v8`、`docker/setup-buildx-action@v4`、`docker/login-action@v4`、`docker/build-push-action@v7`。
- **具體落地值**：`GITHUB_OWNER = fergusKe`；repoURL `https://github.com/fergusKe/trend-intelligence-platform`；**GHCR image 路徑一律小寫** `ghcr.io/ferguske/trend-intelligence-platform/hello`（owner 的大寫 K 在 registry 路徑必須小寫，manifest 與 CI 都遵守）。
- **命令式邊界**：只有 `platform/bootstrap/` 三步用 kubectl/kind 手打；其餘全 ArgoCD 管。
- **零 secret**：git 內不得出現任何憑證。P0 不引入 sealed-secrets/external-secrets/Airflow/Postgres 等任何超綱工具（一個工作一個工具）。
- **可攜鐵律**：ingress **零控制器專屬 annotation**（禁 `alb.ingress.*` / `nginx.ingress.*`）；監控 **不寫任何 `storageClassName`**（emptyDir）。`grep -r "alb.ingress\|storageClassName" platform/` 須為空。
- **wave 編號地基（下游禁改）**：P0 佔 wave 0–2；P1 起用 3+，不重排既有號。
- **主機名**：`*.localtest.me`（公共 DNS 解到 127.0.0.1，零 /etc/hosts）。
- **Git commit 中文**：`動作(範圍)：說明`。TDD、頻繁小 commit。

---

## File Structure（本 plan 產出的全部檔案）

```
Makefile                                   # cluster-up/down/verify/argocd-ui（Task 5）
scripts/verify.sh                          # 端到端驗收（Task 11）
.github/workflows/hello-ci.yaml            # main push CI（Task 10）
.github/workflows/pr-checks.yaml           # PR lint+test+可攜守門（Task 10）
platform/bootstrap/kind-cluster.yaml       # kind 3-node config（Task 4）
platform/bootstrap/root-app.yaml           # app-of-apps root（Task 5）
platform/argocd/apps/ingress-nginx.yaml    # wave 0（Task 6）
platform/argocd/apps/monitoring.yaml       # wave 1（Task 7）
platform/argocd/apps/monitoring-dashboards.yaml  # wave 2（Task 8）
platform/argocd/apps/hello.yaml            # wave 2（Task 9）
platform/monitoring/dashboards/hello-service-dashboard.yaml  # ConfigMap（Task 8）
platform/hello/pyproject.toml              # Task 1
platform/hello/uv.lock                     # Task 1（uv lock 產生）
platform/hello/src/hello/__init__.py       # Task 1
platform/hello/src/hello/main.py           # Task 1
platform/hello/tests/test_main.py          # Task 1
platform/hello/Dockerfile                  # Task 2
platform/hello/k8s/kustomization.yaml      # Task 3（CI 唯一改的檔）
platform/hello/k8s/deployment.yaml         # Task 3
platform/hello/k8s/service.yaml            # Task 3
platform/hello/k8s/servicemonitor.yaml     # Task 3
platform/hello/k8s/ingress.yaml            # Task 3
README.md（既有，補章節）                    # Task 12
```

**執行流程總覽**（因 GitOps 特性，manifest/CI 先寫好 commit → push 觸發 CI 產 image → 設 GHCR public → `make cluster-up` → `make verify` 全綠）：Task 1–11 建檔並各自局部驗證；Task 12 才做完整端到端整合（推 main → CI → 叢集收斂 → verify）。

---

## Task 0: 環境前置（preflight）

**Files:** 無（安裝工具 + 環境校驗；產出 = 可執行環境）

**Interfaces:**
- Produces: 可用的 `kind` / `kubectl` / `yq` / `docker` / `uv` / `gh`；已確認 remote `origin` = `https://github.com/fergusKe/trend-intelligence-platform`。

- [ ] **Step 1: 確認既有工具**

Run:
```bash
for t in docker uv gh jq make; do printf "%s: " "$t"; command -v "$t" >/dev/null && echo OK || echo MISSING; done
```
Expected: 全部 `OK`（本機已驗：docker 29.4.0 / uv 0.11.19 / gh 2.93.0 / jq 1.7.1 / make 3.81）。

- [ ] **Step 2: 安裝缺的工具（kind / kubectl / yq）**

Run（macOS + Homebrew）：
```bash
brew install kind kubernetes-cli yq
kind --version && kubectl version --client && yq --version
```
Expected: `kind version 0.32.0`（若 brew 給更新版，改用 pinned 安裝：`go install sigs.k8s.io/kind@v0.32.0` 或下載 v0.32.0 release binary，維持 Global Constraints 版本）；`kubectl` client 版印出；`yq (mikefarah) v4.x`。

- [ ] **Step 3: 端口與 remote 校驗**

Run:
```bash
lsof -iTCP:80 -sTCP:LISTEN -n -P || echo "80 free"
lsof -iTCP:443 -sTCP:LISTEN -n -P || echo "443 free"
git remote -v
gh auth status
```
Expected: 80/443 皆 free（若被佔，記錄下來——Task 4 的 kind-cluster.yaml 需改 8080/8443）；remote `origin` 指向 `github.com/fergusKe/trend-intelligence-platform`；`gh auth status` 已登入。

- [ ] **Step 4: 確認乾淨起點**

Run:
```bash
git status --short
find platform ingestion lakehouse ml orchestration -type f
```
Expected: working tree 乾淨；scaffold 目錄只有 `.gitkeep`（確認未殘留舊實作）。

> 本 task 無 commit（純環境準備）。

---

## Task 1: hello 服務本體（FastAPI + 測試，TDD）

**Files:**
- Create: `platform/hello/pyproject.toml`
- Create: `platform/hello/src/hello/__init__.py`
- Create: `platform/hello/src/hello/main.py`
- Create: `platform/hello/tests/test_main.py`
- Create: `platform/hello/uv.lock`（`uv lock` 產生）

**Interfaces:**
- Produces: FastAPI `app`（`hello.main:app`），路由 `GET /healthz` → `{"status":"ok"}`、`GET /metrics`（instrumentator）。Task 2 Dockerfile 以 `hello.main:app` 為 uvicorn entrypoint；Task 3 probe 打 `/healthz`、ServiceMonitor scrape `/metrics`。

- [ ] **Step 1: 建 pyproject.toml**

Create `platform/hello/pyproject.toml`：
```toml
[project]
name = "hello"
version = "0.1.0"
description = "Platform canary service"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.139.0",
    "uvicorn==0.50.2",
    "prometheus-fastapi-instrumentator==8.0.2",
]

[dependency-groups]
dev = [
    "pytest==9.1.1",
    "httpx==0.28.1",
    "ruff==0.15.20",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hello"]
```

- [ ] **Step 2: 建套件 __init__ 與失敗測試**

Create `platform/hello/src/hello/__init__.py`（空檔）。

Create `platform/hello/tests/test_main.py`：
```python
from fastapi.testclient import TestClient

from hello.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_exposes_http_requests():
    client.get("/healthz")  # 先打一次讓 counter 有值
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_request" in resp.text
```

- [ ] **Step 3: 產生 lockfile 並跑測試確認失敗**

Run:
```bash
cd platform/hello && uv lock && uv sync
uv run pytest tests/ -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'hello.main'`（main.py 尚未建）。

- [ ] **Step 4: 實作 main.py**

Create `platform/hello/src/hello/main.py`：
```python
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()
Instrumentator().instrument(app).expose(app)  # GET /metrics


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```

- [ ] **Step 5: 跑測試確認綠 + lint**

Run:
```bash
cd platform/hello && uv run pytest tests/ -v && uv run ruff check .
```
Expected: 2 passed；ruff `All checks passed!`。

- [ ] **Step 6: Commit**

```bash
git add platform/hello/pyproject.toml platform/hello/uv.lock \
  platform/hello/src/hello/__init__.py platform/hello/src/hello/main.py \
  platform/hello/tests/test_main.py
git commit -m "功能(platform)：hello 金絲雀 FastAPI 服務 + /healthz /metrics 測試"
```

---

## Task 2: hello Dockerfile（映像可建可跑）

**Files:**
- Create: `platform/hello/Dockerfile`

**Interfaces:**
- Consumes: Task 1 的 `pyproject.toml` / `uv.lock` / `src/`。
- Produces: 映像跑起來 listen `:8000`，`GET /healthz` 回 200。Task 3 deployment `containerPort: 8000`、runAsUser 1000 對齊本檔 `USER 1000`。

- [ ] **Step 1: 建 Dockerfile**

Create `platform/hello/Dockerfile`：
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src/ src/
RUN uv sync --frozen --no-dev
RUN useradd -u 1000 -m app
USER 1000
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "hello.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: build 映像**

Run:
```bash
cd platform/hello && docker build -t hello:local .
```
Expected: build 成功，最後 `naming to docker.io/library/hello:local`。

- [ ] **Step 3: run 並打 /healthz（驗證 test）**

Run:
```bash
docker run -d --rm -p 8000:8000 --name hello-test hello:local
sleep 3
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/metrics | grep -m1 http_request
docker stop hello-test
```
Expected: `{"status":"ok"}`；grep 命中一行 `http_request...`。

- [ ] **Step 4: Commit**

```bash
git add platform/hello/Dockerfile
git commit -m "建置(platform)：hello Dockerfile（uv frozen + 非 root UID 1000）"
```

---

## Task 3: hello k8s manifests（kustomize）

**Files:**
- Create: `platform/hello/k8s/kustomization.yaml`
- Create: `platform/hello/k8s/deployment.yaml`
- Create: `platform/hello/k8s/service.yaml`
- Create: `platform/hello/k8s/servicemonitor.yaml`
- Create: `platform/hello/k8s/ingress.yaml`

**Interfaces:**
- Consumes: Task 2 映像 `ghcr.io/ferguske/trend-intelligence-platform/hello`。
- Produces: `apps` namespace 的 Deployment `hello`（2 replica）、Service `hello`（port 80→8000，port 名 `http`）、ServiceMonitor（port `http` path `/metrics`）、Ingress（host `hello.localtest.me`）。Task 9 hello 子 Application source path 指向本目錄；Task 10 CI 用 `yq` 改 `kustomization.yaml` 的 `images[0].newTag`。

> **關鍵：** `kustomization.yaml` 的 `images.name` 與 `deployment.yaml` 的 `image` 前綴**必須逐字一致且全小寫** `ghcr.io/ferguske/trend-intelligence-platform/hello`，否則 `newTag` 改寫不生效。

- [ ] **Step 1: 建 kustomization.yaml**

Create `platform/hello/k8s/kustomization.yaml`：
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: apps
resources:
  - deployment.yaml
  - service.yaml
  - servicemonitor.yaml
  - ingress.yaml
images:
  - name: ghcr.io/ferguske/trend-intelligence-platform/hello
    newTag: sha-0000000   # 佔位；首次 CI run 會 bump 成真 tag
```

- [ ] **Step 2: 建 deployment.yaml**

Create `platform/hello/k8s/deployment.yaml`：
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello
  labels: {app: hello}
spec:
  replicas: 2
  selector:
    matchLabels: {app: hello}
  template:
    metadata:
      labels: {app: hello}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: hello
          image: ghcr.io/ferguske/trend-intelligence-platform/hello:sha-0000000
          ports:
            - {containerPort: 8000, name: http}
          readinessProbe:
            httpGet: {path: /healthz, port: http}
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            initialDelaySeconds: 10
            periodSeconds: 10
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
```

- [ ] **Step 3: 建 service.yaml / servicemonitor.yaml / ingress.yaml**

Create `platform/hello/k8s/service.yaml`：
```yaml
apiVersion: v1
kind: Service
metadata:
  name: hello
  labels: {app: hello}
spec:
  type: ClusterIP
  selector: {app: hello}
  ports:
    - {name: http, port: 80, targetPort: 8000}
```

Create `platform/hello/k8s/servicemonitor.yaml`：
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: hello
  labels: {app: hello}
  annotations:
    argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
spec:
  selector:
    matchLabels: {app: hello}
  endpoints:
    - {port: http, path: /metrics, interval: 15s}
```

Create `platform/hello/k8s/ingress.yaml`（**零 annotation**）：
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hello
spec:
  ingressClassName: nginx
  rules:
    - host: hello.localtest.me
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: hello
                port: {name: http}
```

- [ ] **Step 4: 驗證 kustomize 渲染 + 可攜守門**

Run:
```bash
kubectl kustomize platform/hello/k8s | grep -E "image:|ingressClassName:"
grep -rn "alb.ingress\|nginx.ingress\|storageClassName" platform/hello/k8s && echo "VIOLATION" || echo "portability OK"
```
Expected: 渲染出 `image: ghcr.io/ferguske/trend-intelligence-platform/hello:sha-0000000` 與 `ingressClassName: nginx`；可攜守門印 `portability OK`（無專屬 annotation / storageClassName）。

- [ ] **Step 5: Commit**

```bash
git add platform/hello/k8s/
git commit -m "部署(platform)：hello k8s manifests（kustomize，2 replica，零 annotation ingress）"
```

---

## Task 4: kind 叢集 config（3 node）

**Files:**
- Create: `platform/bootstrap/kind-cluster.yaml`

**Interfaces:**
- Produces: kind 叢集 `trend-platform`（1 control-plane + 2 worker），control-plane 帶 `ingress-ready=true` label、80/443 hostPort 綁 127.0.0.1。Task 5 Makefile `cluster-up` 引用本檔；Task 6 ingress-nginx nodeSelector 對準 `ingress-ready`。

- [ ] **Step 1: 建 kind-cluster.yaml**

Create `platform/bootstrap/kind-cluster.yaml`：
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

- [ ] **Step 2: 建叢集驗證 config 有效**

Run:
```bash
kind create cluster --config platform/bootstrap/kind-cluster.yaml
kubectl get nodes
```
Expected: 3 個 node，roughly 1 分鐘內全 `Ready`（control-plane + 2 worker）。

- [ ] **Step 3: 確認 ingress-ready label + hostPort**

Run:
```bash
kubectl get nodes -l ingress-ready=true
docker ps --filter name=trend-platform-control-plane --format '{{.Ports}}' | grep -o '127.0.0.1:80'
```
Expected: control-plane 節點列出；`127.0.0.1:80` 命中（hostPort 綁定成立）。

- [ ] **Step 4: 拆叢集（保持乾淨，Task 5 用 Makefile 重建）**

Run:
```bash
kind delete cluster --name trend-platform
```
Expected: `Deleting cluster "trend-platform"`。

- [ ] **Step 5: Commit**

```bash
git add platform/bootstrap/kind-cluster.yaml
git commit -m "建置(platform)：kind 3-node 叢集 config（ingress-ready + 80/443 hostPort）"
```

---

## Task 5: Makefile + ArgoCD bootstrap（root app）

**Files:**
- Create: `Makefile`
- Create: `platform/bootstrap/root-app.yaml`

**Interfaces:**
- Consumes: Task 4 kind config。
- Produces: `make cluster-up`（kind → ArgoCD v3.4.4 → apply root-app），`make cluster-down` / `make verify` / `make argocd-ui`。root Application `platform-root` watch `platform/argocd/apps/`（directory recurse:false）。Task 6–9 子 Application 落在該目錄即被接管。

- [ ] **Step 1: 建 root-app.yaml**

Create `platform/bootstrap/root-app.yaml`：
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
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: platform/argocd/apps
    directory: {recurse: false}
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    retry:
      limit: 10
      backoff: {duration: 15s, factor: 2, maxDuration: 3m}
```

- [ ] **Step 2: 建 Makefile**

Create `Makefile`：
```makefile
.PHONY: cluster-up cluster-down verify argocd-ui
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

- [ ] **Step 3: 驗證 YAML 語法 + Makefile target**

Run:
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/bootstrap/root-app.yaml')))" && echo "root-app YAML OK"
make -n cluster-up
```
Expected: `root-app YAML OK`；`make -n cluster-up` 印出 4 條命令（dry-run，不實跑）。

- [ ] **Step 4: 實跑 cluster-up 到 ArgoCD 就緒**

Run:
```bash
make cluster-up
kubectl -n argocd get applications
```
Expected: bootstrap 完成訊息；`platform-root` Application 存在（此時子 app 目錄尚空/未 push，`platform-root` 可能 Synced 但無子資源——正常）。

> 註：此時子 Application 檔（Task 6–9）尚未 push 到 main，root app 掃到空目錄。完整收斂在 Task 12。此 step 只驗證 bootstrap 三步成立。

- [ ] **Step 5: Commit**

```bash
git add Makefile platform/bootstrap/root-app.yaml
git commit -m "建置(platform)：Makefile cluster-up + ArgoCD v3.4.4 root app（app-of-apps）"
```

---

## Task 6: 子 Application — ingress-nginx（wave 0）

**Files:**
- Create: `platform/argocd/apps/ingress-nginx.yaml`

**Interfaces:**
- Produces: ingress-nginx controller（Helm 4.15.1），hostPort+nodeSelector 對接 kind。Task 3/8 的 Ingress（`ingressClassName: nginx`）靠它生效。

- [ ] **Step 1: 建 ingress-nginx.yaml**

Create `platform/argocd/apps/ingress-nginx.yaml`：
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
          hostPort: {enabled: true}
          nodeSelector: {ingress-ready: "true"}
          tolerations:
            - key: node-role.kubernetes.io/control-plane
              operator: Exists
              effect: NoSchedule
          service: {type: ClusterIP}
          watchIngressWithoutClass: false
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-nginx
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 驗證 YAML + dry-run（叢集已在 Task 5 起）**

Run:
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/ingress-nginx.yaml')))" && echo "YAML OK"
kubectl apply --dry-run=client -f platform/argocd/apps/ingress-nginx.yaml
```
Expected: `YAML OK`；dry-run 印 `application.argoproj.io/ingress-nginx created (dry run)`。

- [ ] **Step 3: Commit**

```bash
git add platform/argocd/apps/ingress-nginx.yaml
git commit -m "部署(platform)：ArgoCD 子 app ingress-nginx（Helm 4.15.1，wave 0）"
```

---

## Task 7: 子 Application — monitoring（wave 1）

**Files:**
- Create: `platform/argocd/apps/monitoring.yaml`

**Interfaces:**
- Produces: kube-prometheus-stack（Helm 87.10.1），Prometheus 撿全叢集 ServiceMonitor、Grafana 走 ingress `grafana.localtest.me` + dashboard sidecar、帶入 `ServiceMonitor` CRD。Task 3 servicemonitor / Task 8 dashboard ConfigMap 依賴它。

- [ ] **Step 1: 建 monitoring.yaml**

Create `platform/argocd/apps/monitoring.yaml`：
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
            serviceMonitorSelectorNilUsesHelmValues: false
            podMonitorSelectorNilUsesHelmValues: false
            serviceMonitorNamespaceSelector: {}
            retention: 24h
            # storageSpec 刻意不設 → emptyDir（可攜鐵律；EKS 版見 README）
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
    syncOptions: [CreateNamespace=true, ServerSideApply=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 驗證 YAML + 可攜守門 + dry-run**

Run:
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/monitoring.yaml')))" && echo "YAML OK"
grep -n "storageClassName" platform/argocd/apps/monitoring.yaml && echo "VIOLATION" || echo "no storageClassName OK"
kubectl apply --dry-run=client -f platform/argocd/apps/monitoring.yaml
```
Expected: `YAML OK`；`no storageClassName OK`；dry-run created。

- [ ] **Step 3: Commit**

```bash
git add platform/argocd/apps/monitoring.yaml
git commit -m "部署(platform)：ArgoCD 子 app monitoring（kube-prometheus-stack 87.10.1，wave 1，SSA）"
```

---

## Task 8: hello dashboard ConfigMap + monitoring-dashboards 子 app（wave 2）

**Files:**
- Create: `platform/monitoring/dashboards/hello-service-dashboard.yaml`
- Create: `platform/argocd/apps/monitoring-dashboards.yaml`

**Interfaces:**
- Consumes: Task 7 Grafana sidecar（label `grafana_dashboard`）、Prometheus datasource uid `prometheus`。
- Produces: Grafana dashboard title **`Hello Service`** uid `hello-service`（Task 11 verify step 6 對準此字串）。

- [ ] **Step 1: 建 dashboard ConfigMap**

Create `platform/monitoring/dashboards/hello-service-dashboard.yaml`：
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hello-service-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  hello-service-dashboard.json: |
    {
      "uid": "hello-service",
      "title": "Hello Service",
      "schemaVersion": 39,
      "editable": true,
      "time": {"from": "now-1h", "to": "now"},
      "refresh": "10s",
      "panels": [
        {
          "id": 1,
          "title": "RPS",
          "type": "timeseries",
          "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "targets": [
            {"refId": "A", "expr": "sum(rate(http_requests_total{handler!~\"/metrics|/healthz\"}[5m]))"}
          ]
        },
        {
          "id": 2,
          "title": "p95 latency",
          "type": "timeseries",
          "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "targets": [
            {"refId": "A", "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))"}
          ]
        },
        {
          "id": 3,
          "title": "4xx/5xx rate",
          "type": "timeseries",
          "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "targets": [
            {"refId": "A", "expr": "sum(rate(http_requests_total{status=~\"4..|5..\"}[5m])) / sum(rate(http_requests_total[5m]))"}
          ]
        },
        {
          "id": 4,
          "title": "Pod restarts (apps)",
          "type": "timeseries",
          "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
          "datasource": {"type": "prometheus", "uid": "prometheus"},
          "targets": [
            {"refId": "A", "expr": "kube_pod_container_status_restarts_total{namespace=\"apps\"}"}
          ]
        }
      ]
    }
```

- [ ] **Step 2: 建 monitoring-dashboards 子 app**

Create `platform/argocd/apps/monitoring-dashboards.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-dashboards
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  project: default
  source:
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: platform/monitoring/dashboards
    directory: {recurse: false}
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 3: 驗證 dashboard JSON 有效 + YAML**

Run:
```bash
python3 -c "import yaml,json; d=yaml.safe_load(open('platform/monitoring/dashboards/hello-service-dashboard.yaml')); json.loads(d['data']['hello-service-dashboard.json']); print('dashboard JSON valid, title=', json.loads(d['data']['hello-service-dashboard.json'])['title'])"
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/monitoring-dashboards.yaml')))" && echo "app YAML OK"
```
Expected: `dashboard JSON valid, title= Hello Service`；`app YAML OK`。

- [ ] **Step 4: Commit**

```bash
git add platform/monitoring/dashboards/hello-service-dashboard.yaml platform/argocd/apps/monitoring-dashboards.yaml
git commit -m "部署(platform)：hello Grafana dashboard ConfigMap + monitoring-dashboards 子 app（wave 2）"
```

---

## Task 9: 子 Application — hello（wave 2）

**Files:**
- Create: `platform/argocd/apps/hello.yaml`

**Interfaces:**
- Consumes: Task 3 kustomize 目錄 `platform/hello/k8s`。
- Produces: hello 服務被 ArgoCD 接管，跑在 `apps` namespace。

- [ ] **Step 1: 建 hello.yaml**

Create `platform/argocd/apps/hello.yaml`：
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: hello
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  project: default
  source:
    repoURL: https://github.com/fergusKe/trend-intelligence-platform
    targetRevision: main
    path: platform/hello/k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: apps
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
    retry: {limit: 10, backoff: {duration: 15s, factor: 2, maxDuration: 3m}}
```

- [ ] **Step 2: 驗證 YAML + dry-run**

Run:
```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('platform/argocd/apps/hello.yaml')))" && echo "YAML OK"
kubectl apply --dry-run=client -f platform/argocd/apps/hello.yaml
```
Expected: `YAML OK`；dry-run created。

- [ ] **Step 3: Commit**

```bash
git add platform/argocd/apps/hello.yaml
git commit -m "部署(platform)：ArgoCD 子 app hello（kustomize，wave 2）"
```

---

## Task 10: GitHub Actions CI（hello-ci + pr-checks）

**Files:**
- Create: `.github/workflows/hello-ci.yaml`
- Create: `.github/workflows/pr-checks.yaml`

**Interfaces:**
- Consumes: Task 1 hello 服務、Task 3 `kustomization.yaml`（bump 對象）。
- Produces: main push → test→build→GHCR→`yq` bump `newTag`→bot commit（`[skip ci]`）。這是 GitOps 交棒點：CI 推 image + 改 manifest，ArgoCD 拉 git 部署。

> **小寫 gotcha：** `github.repository` = `fergusKe/trend-intelligence-platform`（保留大寫 K），但 GHCR 路徑必須小寫。用一個 step 算出小寫 `IMAGE`，讓 build tag 與 kustomization `images.name`（`ferguske`）一致。

- [ ] **Step 1: 建 hello-ci.yaml**

Create `.github/workflows/hello-ci.yaml`：
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
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8
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
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v7
      - id: vars
        run: |
          echo "TAG=sha-$(git rev-parse --short=7 HEAD)" >> "$GITHUB_OUTPUT"
          echo "IMAGE=ghcr.io/$(echo '${{ github.repository }}' | tr '[:upper:]' '[:lower:]')/hello" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v7
        with:
          context: platform/hello
          push: true
          tags: |
            ${{ steps.vars.outputs.IMAGE }}:${{ steps.vars.outputs.TAG }}
            ${{ steps.vars.outputs.IMAGE }}:latest
      - name: Bump manifest tag（GitOps 交棒點）
        run: |
          yq -i '.images[0].newTag = "${{ steps.vars.outputs.TAG }}"' platform/hello/k8s/kustomization.yaml
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add platform/hello/k8s/kustomization.yaml
          git commit -m "ci(hello): bump image to ${{ steps.vars.outputs.TAG }} [skip ci]"
          git pull --rebase origin main
          git push origin main
```

- [ ] **Step 2: 建 pr-checks.yaml（含可攜守門）**

Create `.github/workflows/pr-checks.yaml`：
```yaml
name: pr-checks
on:
  pull_request:
    paths:
      - "platform/hello/**"        # 含 k8s/**：manifest 改動也要過閘
      - "platform/argocd/**"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v8
        with: {python-version: "3.12"}
      - run: uv sync
        working-directory: platform/hello
      - run: uv run ruff check .
        working-directory: platform/hello
      - run: uv run pytest tests/ -v
        working-directory: platform/hello
  portability-guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: no controller-specific annotation / storageClassName
        run: |
          if grep -rn "alb.ingress\|storageClassName" platform/; then
            echo "可攜鐵律違反：發現專屬 annotation 或 storageClassName"; exit 1
          fi
          echo "portability OK"
```

- [ ] **Step 3: 驗證 workflow YAML**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/hello-ci.yaml')); yaml.safe_load(open('.github/workflows/pr-checks.yaml')); print('workflows YAML OK')"
```
Expected: `workflows YAML OK`。

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/hello-ci.yaml .github/workflows/pr-checks.yaml
git commit -m "整合(ci)：hello-ci（test→GHCR→bump）+ pr-checks（test+可攜守門）"
```

---

## Task 11: verify.sh 端到端驗收腳本

**Files:**
- Create: `scripts/verify.sh`

**Interfaces:**
- Consumes: 全部叢集資源（Task 4–9）。
- Produces: `make verify` 的 7 檢查（design §8A），任一 fail 即非零退出。

- [ ] **Step 1: 建 verify.sh**

Create `scripts/verify.sh`：
```bash
#!/usr/bin/env bash
set -euo pipefail

fail() { echo "❌ $1"; exit 1; }
ok()   { echo "✅ $1"; }

echo "[1/7] 節點就緒"
ready=$(kubectl get nodes --no-headers | awk '$2=="Ready"' | wc -l | tr -d ' ')
[ "$ready" = "3" ] || fail "節點 Ready 數 = $ready（預期 3）"
ok "3 節點 Ready"

echo "[2/7] ArgoCD apps 收斂（timeout 600s）"
deadline=$(( $(date +%s) + 600 ))
while :; do
  json=$(kubectl -n argocd get applications -o json)
  total=$(echo "$json" | jq '.items | length')
  good=$(echo "$json" | jq '[.items[] | select(.status.sync.status=="Synced" and .status.health.status=="Healthy")] | length')
  [ "$total" = "5" ] && [ "$good" = "5" ] && break
  [ "$(date +%s)" -gt "$deadline" ] && fail "ArgoCD 未收斂：total=$total synced+healthy=$good（預期 5/5）"
  sleep 10
done
ok "5 個 app 全 Synced + Healthy"

echo "[3/7] hello 健康"
curl -fsS http://hello.localtest.me/healthz | grep -q '"status":"ok"' || fail "hello /healthz 非 ok"
ok "hello /healthz 200 ok"

echo "[4/7] hello 指標"
curl -fsS http://hello.localtest.me/metrics | grep -q http_requests_total || fail "hello /metrics 無 http_requests_total"
ok "hello /metrics 含 http_requests_total"

echo "[5/7] Prometheus 已 scrape apps"
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090 >/dev/null 2>&1 &
pf_pid=$!; sleep 4
val=$(curl -fsS 'http://localhost:9090/api/v1/query?query=up%7Bnamespace%3D%22apps%22%7D' | jq -r '.data.result | length')
kill "$pf_pid" 2>/dev/null || true
[ "$val" -ge 1 ] || fail "Prometheus 未 scrape apps namespace（up 結果空）"
ok "Prometheus 已 scrape apps（up=1）"

echo "[6/7] Grafana + dashboard 已載"
curl -fsS http://grafana.localtest.me/api/health | grep -q '"database": *"ok"' || fail "Grafana health 非 ok"
GRAFANA_PW=$(kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d)
curl -fsS -u "admin:$GRAFANA_PW" "http://grafana.localtest.me/api/search?query=Hello" | grep -q '"title":"Hello Service"' || fail "Grafana 找不到 dashboard 'Hello Service'"
ok "Grafana health ok + dashboard 'Hello Service' 已載"

echo "[7/7] 部署 image 可回溯"
img=$(kubectl -n apps get deploy hello -o jsonpath='{.spec.template.spec.containers[0].image}')
newtag=$(yq '.images[0].newTag' platform/hello/k8s/kustomization.yaml)
echo "$img" | grep -q "sha-" || fail "deploy image tag 非 sha-*（$img）"
echo "$img" | grep -q "$newtag" || fail "deploy image tag 與 kustomization newTag 不一致（$img vs $newtag）"
ok "image 可回溯（$img）"

echo "🎉 全部 7 項驗收通過"
```

- [ ] **Step 2: 賦權 + 語法檢查**

Run:
```bash
chmod +x scripts/verify.sh
bash -n scripts/verify.sh && echo "verify.sh 語法 OK"
command -v shellcheck >/dev/null && shellcheck scripts/verify.sh || echo "（無 shellcheck，跳過）"
```
Expected: `verify.sh 語法 OK`。

- [ ] **Step 3: Commit**

```bash
git add scripts/verify.sh
git commit -m "驗收(platform)：verify.sh 端到端 7 檢查（make verify）"
```

---

## Task 12: 端到端整合 + README runbook

**Files:**
- Modify: `README.md`（補「本地啟動 / CI→GitOps runbook / 可攜 / secret 邊界」章節）

**Interfaces:**
- Consumes: 前 11 task 全部產物。
- Produces: 完整可重現的 P0 平台（`make cluster-down && make cluster-up && make verify` 全綠）+ 文件化 runbook。

- [ ] **Step 1: 推所有 P0 檔到 main，觸發首次 CI**

Run:
```bash
git push origin main
gh run watch --exit-status || gh run list --workflow=hello-ci.yaml --limit 1
```
Expected: `hello-ci` run 綠（test → build-push-bump）；repo 出現 bot commit `ci(hello): bump image to sha-xxxxxxx [skip ci]`，且該 commit **不再觸發** workflow。

- [ ] **Step 2: 設 GHCR package 為 public（一次性手動 UI）**

手動：GitHub → 你的頭像 → Packages → `hello` → Package settings → Change visibility → **Public**。

Run（確認可匿名拉）：
```bash
docker pull ghcr.io/ferguske/trend-intelligence-platform/hello:latest
```
Expected: pull 成功（不需 docker login）。若仍 `denied`，表示 package 尚未設 public，重做本 step。

- [ ] **Step 3: 起叢集並等 ArgoCD 收斂**

Run:
```bash
git pull --rebase origin main          # 取回 bot 的 bump commit
make cluster-up
# 校準 §10-3：確認監控 svc / secret 實際名
sleep 90 && kubectl -n monitoring get svc,secret | grep -E "prometheus|grafana" | head
```
Expected: bootstrap 完成；`monitoring-kube-prometheus-prometheus` svc 與 `monitoring-grafana` secret 存在（若名稱不同，回頭校準 `scripts/verify.sh` step 5/6 的名稱後重跑）。

- [ ] **Step 4: 跑完整驗收**

Run:
```bash
make verify
```
Expected: `🎉 全部 7 項驗收通過`（若 ArgoCD 仍在收斂，verify step 2 會輪詢至多 600s）。

- [ ] **Step 5: CI→GitOps 迴圈手動驗證（design §8B runbook）**

Run:
```bash
# 改回傳值製造一次真部署
python3 - <<'PY'
import re,pathlib
p=pathlib.Path("platform/hello/src/hello/main.py")
s=p.read_text().replace('return {"status": "ok"}','return {"status": "ok", "v": 2}')
p.write_text(s)
PY
# 對應改測試
sed -i '' 's/{"status": "ok"}/{"status": "ok", "v": 2}/' platform/hello/tests/test_main.py
cd platform/hello && uv run pytest tests/ -v && cd -
git add platform/hello/src/hello/main.py platform/hello/tests/test_main.py
git commit -m "功能(platform)：hello 回傳加 v 欄位（驗 CI→GitOps 迴圈）"
git push origin main
gh run watch --exit-status
```
Expected: CI 綠 + 新 bump commit；≤3 分鐘 ArgoCD `hello` app `OutOfSync→Synced`、`kubectl -n apps get pods -w` 見 rolling update；`curl hello.localtest.me/healthz` 回傳含 `"v":2`。

- [ ] **Step 6: 補 README 章節**

Modify `README.md`，新增以下內容（接在既有內容後；若 README 已有對應段落則更新）：

````markdown
## 本地啟動（P0 平台底座）

前置：Docker、kind v0.32.0、kubectl、yq、make、uv、gh（見 `docs/plans/2026-07-16-P0-platform-foundation-implementation.md` Task 0）。

```bash
make cluster-up     # kind 叢集 → ArgoCD v3.4.4 → root app（app-of-apps）
make verify         # 端到端 7 檢查全綠
make argocd-ui      # 印 ArgoCD 初始密碼 + port-forward 8081（https://localhost:8081）
make cluster-down   # 拆叢集
```

服務入口（`*.localtest.me` 公共 DNS 解到 127.0.0.1，零 /etc/hosts）：
- hello: http://hello.localtest.me/healthz
- Grafana: http://grafana.localtest.me（帳號 `admin`，密碼：`kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d`）

> 本機 80/443 被佔時：改 `platform/bootstrap/kind-cluster.yaml` 的 `hostPort` 為 8080/8443（其餘不動）。

## CI → GitOps 閉環（怎麼看「push 就自動部署」）

1. 改 `platform/hello/src/hello/main.py` → `git push origin main`。
2. GitHub Actions `hello-ci`：test → build GHCR image（tag `sha-<short>`）→ `yq` bump `platform/hello/k8s/kustomization.yaml` 的 `newTag` → bot commit（`[skip ci]`，GITHUB_TOKEN 推的 commit 不觸發 workflow）。
3. ArgoCD 拉 git，`hello` app `OutOfSync→Synced`，rolling update 上線新版。
4. 全程零 secret：public repo（ArgoCD 匿名拉）+ public GHCR image（節點匿名拉）+ Grafana/ArgoCD 密碼叢集內隨機生成現場讀。

> **首次上線一次性手動步驟**：GHCR package 首推預設 private → GitHub Packages → `hello` → Change visibility → **Public**（否則 kind 節點 ImagePullBackOff）。

## Secret 邊界策略

P0 零 secret。P1 起第一個真 secret（YouTube API key）出現時，用命令式 `kubectl create secret`（文件化、不進 git）起步，屆時再評估 sealed-secrets / external-secrets（P0 不預裝——一個工作一個工具）。

## 雲端可攜（kind → EKS 要動什麼）

| 層 | 換 EKS 時 |
|---|---|
| 叢集 | 換 eksctl/Terraform；`platform/argocd/` 以下零改動 |
| ingress | 只改 `platform/argocd/apps/ingress-nginx.yaml`：刪 kind 專屬 values 改 `service.type: LoadBalancer`（或換 ALB controller Application） |
| 各服務 Ingress | `ingressClassName: nginx` + 零控制器專屬 annotation，留 nginx 不動 |
| storage | 監控 emptyDir → values 加 `storageSpec` + 目標叢集 storageClass |
| DNS | `*.localtest.me` → 換真域名，只改 ingress host 與 grafana values |
````

- [ ] **Step 7: 可重現性最終驗證 + commit**

Run:
```bash
grep -rn "alb.ingress\|storageClassName" platform/ && echo "VIOLATION" || echo "可攜鐵律 OK"
make cluster-down && make cluster-up && make verify
git add README.md
git commit -m "文件(platform)：P0 README runbook（啟動/CI-GitOps/secret 邊界/可攜）"
git push origin main
```
Expected: `可攜鐵律 OK`；重建叢集後 `make verify` 仍 `🎉 全部 7 項驗收通過`（證明唯一外部狀態 = GHCR image + git repo，皆在叢集外）。

---

## Self-Review（planner 自檢，已執行）

**1. Spec coverage（design §2–§9 逐段對照）：**
- §2 kind 叢集 → Task 4（config）+ Task 5（Makefile cluster-up）✅
- §3 ArgoCD + app-of-apps → Task 5（root-app）+ Task 6/7/8/9（子 app，sync-wave 0/1/2）✅
- §4 GitHub Actions CI → Task 10（hello-ci + pr-checks，含小寫 IMAGE gotcha、`[skip ci]`、paths 過濾、yq bump）✅
- §5 可觀測性 → Task 7（monitoring values）+ Task 8（dashboard ConfigMap，title `Hello Service`/uid `hello-service`/datasource uid `prometheus`）✅
- §6 hello 服務 → Task 1（FastAPI+測試）+ Task 2（Dockerfile）+ Task 3（k8s manifests）✅
- §7 零 secret → Global Constraints + Task 12 README 段 ✅
- §8A verify → Task 11（7 檢查照抄判準）；§8B runbook → Task 12 Step 5 + README；§8C 可重現 → Task 12 Step 7 ✅
- §9 可攜 → Task 3/7 守門 + pr-checks portability-guard + Task 12 README 表 ✅
- §10 四前置 → Task 0（remote/ports/tools）+ Task 12 Step 2（GHCR public）+ Step 3（svc/secret 名校準）✅

**2. Placeholder scan：** 無 TBD/TODO；`sha-0000000` 是 design 明訂的佔位 tag（首次 CI bump），非 plan placeholder。所有 code step 皆完整可照抄。

**3. Type/名稱一致性：** image 路徑全小寫 `ghcr.io/ferguske/trend-intelligence-platform/hello`（kustomization `images.name`＝deployment `image` 前綴＝CI 算出的 IMEAGE）；port 名 `http` 貫穿 service/servicemonitor/deployment；dashboard title `Hello Service` ＝ verify step 6 grep 字串；repoURL 三處（root-app/monitoring-dashboards/hello）一致；wave 0/1/2 與 design §3 一致。

**執行注意：** Task 4/5 之後叢集常駐；Task 6–9 的 dry-run 需叢集在（Task 5 已起）。若中途 `cluster-down`，Task 12 會重建。
