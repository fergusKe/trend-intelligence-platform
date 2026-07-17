.PHONY: cluster-up cluster-down cluster-stop cluster-start verify argocd-ui pipeline-secrets pipeline-verify pipeline-trigger demo-p1-up demo-p1-down
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

pipeline-secrets:      ## make pipeline-secrets YOUTUBE_API_KEY=<key>（冪等；命令式、不進 git）
	@test -n "$(YOUTUBE_API_KEY)" || { echo "用法：make pipeline-secrets YOUTUBE_API_KEY=<key>"; exit 1; }
	./scripts/pipeline-secrets.sh "$(YOUTUBE_API_KEY)"
