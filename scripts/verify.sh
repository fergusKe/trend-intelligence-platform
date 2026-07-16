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
  json=$(kubectl -n argocd get applications -o json 2>/dev/null) || { [ "$(date +%s)" -gt "$deadline" ] && fail "ArgoCD 未收斂：kubectl 查詢持續失敗（timeout）"; sleep 10; continue; }
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
pf_pid=$!; trap 'kill "$pf_pid" 2>/dev/null || true' EXIT
sleep 4
val=$(curl -fsS 'http://localhost:9090/api/v1/query?query=up%7Bnamespace%3D%22apps%22%7D' | jq -r '.data.result | length') || val=0
trap - EXIT
kill "$pf_pid" 2>/dev/null || true
[ "$val" -ge 1 ] || fail "Prometheus 未 scrape apps namespace（up 結果空）"
ok "Prometheus 已 scrape apps（up=1）"

echo "[6/7] Grafana + dashboard 已載"
curl -fsS http://grafana.localtest.me/api/health | grep -q '"database": *"ok"' || fail "Grafana health 非 ok"
GRAFANA_PW=$(kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d)
curl -fsS -u "admin:$GRAFANA_PW" "http://grafana.localtest.me/api/search?query=Hello" | grep -q '"title": *"Hello Service"' || fail "Grafana 找不到 dashboard 'Hello Service'"
ok "Grafana health ok + dashboard 'Hello Service' 已載"

echo "[7/7] 部署 image 可回溯"
img=$(kubectl -n apps get deploy hello -o jsonpath='{.spec.template.spec.containers[0].image}')
newtag=$(yq '.images[0].newTag' platform/hello/k8s/kustomization.yaml)
echo "$img" | grep -q "sha-" || fail "deploy image tag 非 sha-*（$img）"
echo "$img" | grep -q "$newtag" || fail "deploy image tag 與 kustomization newTag 不一致（$img vs $newtag）"
ok "image 可回溯（$img）"

echo "🎉 全部 7 項驗收通過"
