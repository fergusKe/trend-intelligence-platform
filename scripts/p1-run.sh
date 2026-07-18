#!/usr/bin/env bash
# P1 主管線一鍵驗收：觸發 yt_trending_hourly → 盯每個 task 到終態 → 印 Gold 五表計數。
# 用法：make p1-run（或直接 ./scripts/p1-run.sh）。前置：叢集已起、pipeline-secrets 已佈、airflow 健康。
set -uo pipefail

DAG=yt_trending_hourly
POLL_MAX="${POLL_MAX:-60}"       # 最多 60 次
POLL_SEC="${POLL_SEC:-30}"       # 每 30 秒
PGPOD=lakehouse-postgres-0

# 全新叢集上 DAG 預設 paused（trigger 會建 run 但 scheduler 不排 task → ingest 永遠 0/8）。先確保 unpause（冪等）。
echo "== 確保 $DAG 已 unpause =="
kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow dags unpause "$DAG" >/dev/null 2>&1 || true

# 一次一支 DAG（lean 紀律）：暫停 categories DAG，避免兩管線同節點搶記憶體讓 spark executor 排不進去。
kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow dags pause yt_categories_daily >/dev/null 2>&1 || true

echo "== 觸發 $DAG =="
TRG=$(kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
      airflow dags trigger "$DAG" -o plain 2>&1)
RID=$(echo "$TRG" | grep -oE "manual__[0-9T:.+-]+" | head -1)
[ -z "$RID" ] && { echo "取不到 run_id；trigger 輸出："; echo "$TRG" | tail -5; exit 1; }
echo "run_id=$RID"

stateof() {
  echo "$1" | awk -v t="$2" '$0 ~ ("[[:space:]]"t"[[:space:]]") {
    for(i=1;i<=NF;i++){s=$i;
      if(s ~ /^(success|failed|running|queued|up_for_retry|upstream_failed|scheduled|restarting|deferred|skipped|up_for_reschedule)$/){print s; exit}}
  }' | head -1
}
isterm() { case "$1" in success|failed|upstream_failed|skipped) return 0;; *) return 1;; esac; }

RESULT=running
for i in $(seq 1 "$POLL_MAX"); do
  ST=$(kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
       airflow tasks states-for-dag-run "$DAG" "$RID" -o plain 2>/dev/null)
  IOK=$(echo "$ST" | grep -c "ingest_trending.*success")
  SP=$(stateof "$ST" spark_bronze_to_silver); LO=$(stateof "$ST" load_silver_to_postgres)
  DR=$(stateof "$ST" dbt_run); DT=$(stateof "$ST" dbt_test)
  printf '[%4ds] ingest=%s/8 spark=%s load=%s dbt_run=%s dbt_test=%s\n' \
         "$((i*POLL_SEC))" "$IOK" "${SP:-·}" "${LO:-·}" "${DR:-·}" "${DT:-·}"
  if isterm "$DT"; then RESULT="$DT"; break; fi
  if [ "$SP" = failed ] || [ "$LO" = failed ] || [ "$DR" = failed ]; then RESULT="failed(上游)"; break; fi
  sleep "$POLL_SEC"
done

echo ""
echo "== 最終 task 狀態（run=$RID）=="
kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow tasks states-for-dag-run "$DAG" "$RID" -o plain 2>/dev/null \
  | grep -E "ingest_trending|spark_bronze|dbt_run|dbt_test|load_silver|delete_stale" \
  | awk '{s="";for(i=1;i<=NF;i++){if($i~/^(success|failed|running|queued|up_for_retry|upstream_failed|scheduled|restarting|deferred|skipped|up_for_reschedule)$/)s=$i} print "  "$2, s}' | sort | uniq -c

echo ""
echo "== Gold 五表計數 =="
kubectl -n data exec "$PGPOD" -- psql -U pipeline_writer -d lakehouse -tAc "
select 'silver.video_snapshots       = '||count(*) from silver.video_snapshots
union all select 'gold_trending_daily          = '||count(*) from gold.gold_trending_daily
union all select 'gold_channel_performance     = '||count(*) from gold.gold_channel_performance
union all select 'gold_category_daily          = '||count(*) from gold.gold_category_daily
union all select 'gold_video_lifecycle         = '||count(*) from gold.gold_video_lifecycle
union all select 'gold_video_velocity_hourly   = '||count(*) from gold.gold_video_velocity_hourly;" 2>/dev/null | sed 's/^/  /'

echo ""
case "$RESULT" in
  success) echo "✅ P1 全綠（dbt_test success）。注意：velocity_hourly 需 ≥2 個整點快照才 >0，首輪為 0 屬正常。";;
  *) echo "⚠️ 未全綠：dbt_test=$RESULT。查 spark/dbt task log。";;
esac
