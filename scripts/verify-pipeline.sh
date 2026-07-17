#!/usr/bin/env bash
set -euo pipefail

fail() { echo "❌ $1"; exit 1; }
ok()   { echo "✅ $1"; }

PGEXEC="kubectl -n data exec lakehouse-postgres-0 -- psql -U postgres -d lakehouse -tAc"
AF_DEPLOY="deploy/airflow-api-server"   # chart 產出名；Task 15 校準
DAG_ID="yt_trending_hourly"

# Airflow 3.2 CLI 每次呼叫都把 alembic plugin 初始化的 [info] log 印到 stdout，
# 污染 `-o json` 輸出（JSON 前多 6 行時間戳 log）→ jq 直接 parse error。
# 濾掉開頭 ISO 時間戳（^YYYY-MM-DDThh…）的 log 行，只留乾淨 JSON 再交給 jq。
list_runs_json() {  # $1=dag_id → 印去 log 後的乾淨 JSON 陣列
  kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags list-runs "$1" -o json 2>/dev/null \
    | grep -vE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
}

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

echo "[3/10 前置] 確保 yt_categories_daily 至少成功跑過一輪（最終 review 補：Critical 2——只有這支 DAG 建 silver.youtube_categories，stg_categories.sql 這個 view 沒有它先落地會炸）"
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags unpause yt_categories_daily >/dev/null 2>&1 || true
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags trigger yt_categories_daily
deadline=$(( $(date +%s) + 600 ))
while :; do
  state=$(list_runs_json yt_categories_daily | jq -r '.[0].state')
  [ "${state}" = "success" ] && break
  [ "${state}" = "failed" ] && fail "yt_categories_daily 前置跑 failed（silver.youtube_categories 無法建立，stg_categories 必炸）"
  [ "$(date +%s)" -gt "$deadline" ] && fail "yt_categories_daily 前置跑未在 600s 內完成（state=${state}）"
  sleep 10
done
ok "yt_categories_daily 前置完成（silver.youtube_categories 已就緒）"

echo "[3/10] 觸發一輪 ${DAG_ID} 並等 success（timeout 1800s）"
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags unpause "${DAG_ID}" >/dev/null 2>&1 || true
# 最終 review 補：先捕捉本次觸發用的整點小時，後面查詢一律用這個值而非查詢當下的 now()
# ——check 5 若在觸發後、跨過下一個整點才查會誤判成 fail（假陽性）。
TRIGGER_HOUR=$(date -u +"%Y-%m-%d %H:00:00+00")
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow dags trigger "${DAG_ID}"
deadline=$(( $(date +%s) + 1800 ))
while :; do
  state=$(list_runs_json "${DAG_ID}" | jq -r '.[0].state')
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

echo "[5/10] Silver serving 有資料且為觸發時使用的整點小時"
silver_count=$(${PGEXEC} "SELECT count(*) FROM silver.video_snapshots")
[ "${silver_count}" -gt 0 ] || fail "silver.video_snapshots 為空"
# 最終 review 補：比對 TRIGGER_HOUR（觸發當下捕捉的整點）而非查詢當下 date_trunc('hour', now())
# ——若驗收跑過整點邊界，now() 會跑到下一小時，跟實際那輪 dagrun 的資料對不上而假性 fail。
cur_hour=$(${PGEXEC} "SELECT count(*) FROM silver.video_snapshots WHERE captured_at = '${TRIGGER_HOUR}'::timestamptz")
[ "${cur_hour}" -gt 0 ] || fail "silver 無觸發小時（${TRIGGER_HOUR}）資料（Spark→pyiceberg→loader 鏈斷）"
ok "silver ${silver_count} 列，含觸發小時 ${cur_hour} 列"

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
run_lo=$(list_runs_json "${DAG_ID}" | jq -r '.[0].logical_date')
kubectl -n airflow exec "${AF_DEPLOY}" -- airflow tasks clear "${DAG_ID}" -s "${run_lo}" -e "${run_lo}" -y
deadline=$(( $(date +%s) + 1800 ))
while :; do
  state=$(list_runs_json "${DAG_ID}" | jq -r '.[0].state')
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
