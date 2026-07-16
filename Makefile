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
