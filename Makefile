.PHONY: cluster-up cluster-down cluster-stop cluster-start verify argocd-ui pipeline-secrets pipeline-verify pipeline-trigger demo-p1-up demo-p1-down dev-lean-down dev-lean-up
ARGOCD_VERSION := v3.4.4

cluster-up:            ## 一鍵：叢集 → ArgoCD → root app（之後全靠 GitOps 收斂）
	kind get clusters | grep -q '^trend-platform$$' || \
	  kind create cluster --config platform/bootstrap/kind-cluster.yaml
	kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply --server-side --force-conflicts -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/$(ARGOCD_VERSION)/manifests/install.yaml  # SSA：applicationsets CRD 超過 client-side 256KB annotation 上限
	kubectl -n argocd delete netpol --all --ignore-not-found  # kind 內建 netpol 執法器會丟棄 ArgoCD ingress-only netpol 的 DNS/UDP 回包→controller 全癱；kind 單機叢集刪之無安全損失
	kubectl -n argocd rollout status deploy/argocd-server --timeout=180s
	kubectl apply -f platform/bootstrap/root-app.yaml
	@echo "Bootstrap 完成。之後由 ArgoCD 收斂（~3-5 分鐘），跑 make verify 驗收。"

cluster-down:
	kind delete cluster --name trend-platform

cluster-stop:          ## 暫停整座叢集（狀態保留）——跑 Ollama/微調等 host 重活前先執行，釋放 VM 記憶體
	docker ps --filter "name=trend-platform" -q | xargs docker stop

cluster-start:         ## 恢復叢集（pod 重新收斂約 1-3 分鐘，可用 make verify 複驗）
	docker ps -a --filter "name=trend-platform" -q | xargs docker start

verify:
	./scripts/verify.sh

argocd-ui:             ## port-forward + 印初始密碼
	@kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
	kubectl -n argocd port-forward svc/argocd-server 8081:443

pipeline-secrets:      ## 佈 secrets（冪等；命令式、不進 git）。key 來源：.env 的 YOUTUBE_API_KEY，或 YOUTUBE_API_KEY=<key> 覆蓋
	@KEY="$(YOUTUBE_API_KEY)"; \
	if [ -z "$$KEY" ] && [ -f .env ]; then set -a; . ./.env; set +a; KEY="$$YOUTUBE_API_KEY"; fi; \
	test -n "$$KEY" || { echo "需要 YOUTUBE_API_KEY：填進 .env（見 .env.example）或 make pipeline-secrets YOUTUBE_API_KEY=<key>"; exit 1; }; \
	./scripts/pipeline-secrets.sh "$$KEY"

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

dev-lean-down:         ## 開發精簡：縮非必要 app（監控/hello）騰記憶體，保留 P1 需要的 airflow/spark/postgres/minio。16GB M4 開發預設
	# 先關 app-of-apps 的 platform-root auto-sync——否則 selfHeal 會把子 app 的 automated 補回、復活被縮的 workload。
	kubectl -n argocd patch application platform-root --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'
	# 再逐一關子 app auto-sync 並縮 0（monitoring 三件走 monitoring ns；hello 走 apps ns）。node-exporter DaemonSet 各 ~50Mi 留著不動。
	for app in monitoring monitoring-dashboards pipeline-monitoring hello; do \
		kubectl -n argocd patch application $$app --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'; \
	done
	kubectl -n monitoring scale deploy,statefulset --all --replicas=0 || true
	kubectl -n apps scale deploy,statefulset --all --replicas=0 || true

dev-lean-up:           ## 恢復全套：重開 platform-root ＋ 各子 app auto-sync，ArgoCD selfHeal 收斂回來（1-3 分鐘）
	kubectl -n argocd patch application platform-root --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
	for app in monitoring monitoring-dashboards pipeline-monitoring hello; do \
		kubectl -n argocd patch application $$app --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'; \
	done
