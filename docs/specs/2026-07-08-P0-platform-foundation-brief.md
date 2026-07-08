# P0 平台底座 — 交給 Fable 5 的 spec brief

> **交付流程**：Fable 5 讀本 brief + [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) → `superpowers:brainstorming` → 產出 `docs/specs/2026-07-08-P0-platform-foundation-design.md` → 回 Opus 寫 implementation plan。
> **精確度要求**：每個「開放問題」在 design 收斂成明確決定（定不了才標「plan 前需實查」）；技術選型要具體到工具版本與檔案路徑，不留模糊給 plan。
> **定位**：P0 是整個平台的**底座**——之後 P1（資料管線）、P2（ML）全部跑在它上面、用它部署、被它監控。**P0 必須先做**。本身就是一份 DevOps/平台工程 portfolio 作品。

## 為什麼（問題）
NORTH_STAR 定案：一個平台、三層疊，DevOps/k8s 是底座（不是 side project）。P0 要交付「一個本地 k8s 叢集，能用 GitOps 自動部署服務、有完整可觀測性」——之後每個階段的服務只要 push 進 repo，就會被自動 build、部署、監控。驗收標準是一條**端到端貫通**：改一行 code → CI 自動 build+推 image+改 manifest → ArgoCD 自動 sync → 服務上線 → Grafana 看得到它的指標。

## 已鎖定決策（brainstorm + Opus 拍板，勿翻案）
- **本地 k8s = kind**（Docker-based，local + CI 最主流；非 minikube/k3d）。
- **GitOps = ArgoCD**，app-of-apps pattern，watch **本 repo** 的 `platform/` 目錄（單 repo GitOps）。
- **CI = GitHub Actions**：build → test → lint → docker build → 推 **GHCR**（ghcr.io，與 GitHub Actions 原生整合、public 免費）→ 改 manifest image tag → commit 回 repo（觸發 ArgoCD sync）。
- **可觀測性 = kube-prometheus-stack**（Helm；Prometheus + Grafana + 預設 dashboards）。
- **ingress = nginx-ingress**（kind 相容）。
- **雲端可攜（硬約束）**：核心 manifest **不綁死 ALB-specific 註解**；ingress 做成可抽換（kind 用 nginx / 未來 EKS 換 ALB 只改 ingress 層）；storage class 不寫死。README 要能宣稱「設計為可移植到 EKS」。
- **驗收 hello service = 最小 FastAPI**（一個 `/healthz` + 一個帶 Prometheus 指標的 `/metrics`），純為打通端到端，不含業務邏輯。

## 已查到的事實（recon，免重探）
參考素材全在 `/Users/fergus/Desktop/workshop/fergus/` 底下（**唯讀取材，不改原專案**）：
- **`data-workshop/fergus/yt-trending-platform/.github/workflows/`**：現成的 GitHub Actions PR-test + deploy 雙 workflow（唯一有 CI/CD 的既有專案）→ CI 骨架範本。其 `monitoring/` + `metrics_exporter.py` = Prometheus/Grafana + 自訂 exporter 範本。
- **`course/udemy/Abhishek/終極 DevOps 專案實施/.github/workflows/ci.yaml`**：Abhishek 的 CI 樣板（build→lint→test→docker build/push→`sed` 改 manifest tag→git push 回主分支）——**這正是 P0-3 要仿的 GitOps CI 模式**（但改推 GHCR、目標 kind 不是 EKS）。其 `kubernetes/<service>/{deploy,svc}.yaml` = 手寫 Deployment+Service 範本；`kubernetes/frontendproxy/ingress.yaml` = ingress 範本（但它是 ALB，我們要改 nginx）。ArgoCD 本身在課程是「叢集上另裝、指向 repo」，repo 內只留 GitOps 應用側證據。
- **課程環境確認**：DevOps 課目標是 **AWS EKS**（非本地）、MLOps 課走通用 k8s/KServe/SageMaker——**兩課都不用 kind**，我們選 kind 是刻意為了本地零成本 + 長期可掛。技能相通（manifest/ArgoCD/Helm 幾乎一致），只差叢集 bootstrap + ingress + storage class。

## 範圍（簇；Fable 5 定簇內細節與先後）

**P0-1 本地 kind 叢集 + namespace 佈局**
- kind 叢集設定（`kind: Cluster` config，多節點？port mapping 給 ingress？）、namespace 佈局（建議 `argocd` / `monitoring` / `apps`）、安裝 nginx-ingress。
- **開放問題**：kind 叢集要幾個 node（單 control-plane 夠 demo 還是 1+2 worker 較像生產）？kind config 的 extraPortMappings 怎麼設讓 nginx-ingress 對本機可達？叢集 bootstrap 是 Makefile 一鍵（`make cluster-up`）還是 shell script？叢集建立本身要不要納入 GitOps（叢集外的 bootstrap 一定是命令式，界線畫哪）？

**P0-2 ArgoCD + app-of-apps GitOps**
- ArgoCD 安裝（Helm 或 manifest）、app-of-apps root Application 指向 `platform/`、之後每個平台元件（monitoring、hello service）當子 Application。
- **開放問題**：ArgoCD 自身怎麼裝（命令式 bootstrap vs 自我管理）？app-of-apps 的目錄結構長怎樣（`platform/argocd/apps/*.yaml`？）？sync policy（自動 sync + self-heal + prune 開哪些）？repo 是 public 還 private（影響 ArgoCD repo 存取設定）？

**P0-3 GitHub Actions CI（build→test→lint→docker→改 tag→commit）**
- 針對 hello service 的 CI workflow：Python build + pytest + ruff/lint + docker build → 推 GHCR（tag = git sha 或 run_id）→ 改對應 manifest 的 image tag → commit 回 repo。
- **開放問題**：image tag 策略（`sha` / `run_id` / semver）？改 manifest 用 `sed` 還 `kustomize edit set image` 還 yq？CI commit 回 repo 會不會觸發無限迴圈（需 `[skip ci]` 或路徑過濾）？GHCR 認證（`GITHUB_TOKEN` 權限 vs PAT）？多服務時 CI 是 monorepo path-filter 還每服務一 workflow（P0 只有 hello service，但要為 P1+ 預留擴充形狀）？

**P0-4 可觀測性（kube-prometheus-stack）**
- Helm 裝 kube-prometheus-stack（Prometheus + Grafana + Alertmanager + node-exporter + kube-state-metrics）；讓 hello service 的 `/metrics` 被 scrape（ServiceMonitor）；Grafana 一個顯示 hello service 指標的 dashboard。
- **開放問題**：kube-prometheus-stack 由 ArgoCD 管（GitOps）還是命令式 helm install（P0 底座的雞生蛋問題怎麼處理）？Grafana dashboard 怎麼版本化（ConfigMap sidecar vs Helm values）？scrape hello service 用 ServiceMonitor（需 CRD，kube-prometheus-stack 自帶）？監控自身的 storage（emptyDir 夠 demo 還是要 PVC）？

**P0-5 hello service 端到端驗收**
- 最小 FastAPI（`/healthz` + Prometheus `/metrics`）、Dockerfile、k8s manifest（Deployment+Service+ServiceMonitor+Ingress）、放 `platform/` 或 `apps/`。
- **開放問題**：hello service 放哪個目錄（它是「驗收 demo」，P1 起會被真服務取代——放 `platform/hello/` 當底座自測 vs `apps/hello/`）？驗收腳本（自動化 e2e：起叢集→bootstrap→push→等 sync→curl healthz→查 Grafana API 有指標）要做到多自動？

## 設計方向約束（硬性，寫進 design）
- **一切宣告式、GitOps 管理**：除了「叢集 bootstrap + ArgoCD 自身安裝」這種必然命令式的 bootstrap，其餘都進 repo 由 ArgoCD sync（界線在 design 明確畫出）。
- **雲端可攜**：ingress 抽換、不綁 ALB、storage class 不寫死（見已鎖定決策）。
- **secrets 不落 git**：GHCR/ArgoCD 需要的憑證用 k8s Secret + 文件說明（P0 可先用命令式建 secret，別 commit；若要展示進階可提 sealed-secrets 但別過度工程）。
- **一個工作一個工具**（NORTH_STAR 紀律）：排程之後才用 Airflow、DB 之後才用 Postgres；P0 只碰叢集/GitOps/CI/監控，不提前引入。
- **可獨立 demo + 可重現**：`make cluster-up` → bootstrap → 端到端通，要能在乾淨機器一鍵重跑。
- **每步可測**：CI 有測試、驗收有 e2e 腳本。

## 交付與驗收（design 要回答的）
- 每簇開放問題**收斂成決定**或標「plan 前需實查」。
- 具體目錄結構（`platform/` 底下長怎樣：argocd/monitoring/hello 各自 manifest）。
- kind config、ArgoCD app-of-apps、GitHub Actions workflow、kube-prometheus-stack values 的具體形狀（可貼關鍵片段）。
- 「雞生蛋」bootstrap 順序寫清楚（叢集→ingress→ArgoCD→app-of-apps→monitoring→hello）。
- 端到端驗收清單（可測步驟 + 預期輸出）。

## 交付流程尾註
Fable 5 走 `superpowers:brainstorming` 出 design；Opus 據以寫 implementation plan（`superpowers:writing-plans`），再由執行 session 走 `superpowers:subagent-driven-development`。本 brief 對齊 [`../architecture/NORTH_STAR.md`](../architecture/NORTH_STAR.md) 的 P0 定義與「已鎖定決策清單」。
