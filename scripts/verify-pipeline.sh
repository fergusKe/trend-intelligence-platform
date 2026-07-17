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
