#!/usr/bin/env bash
set -euo pipefail

YOUTUBE_API_KEY="${1:?用法：pipeline-secrets.sh <YOUTUBE_API_KEY>}"

# 冪等：secret 已存在則沿用其值（避免密碼輪替導致 Postgres 已初始化的角色失聯），不存在才生成
get_or_gen() {  # $1=ns $2=secret $3=key
  local v
  v=$(kubectl -n "$1" get secret "$2" -o "jsonpath={.data['$3']}" 2>/dev/null | base64 -d 2>/dev/null || true)
  if [ -z "${v}" ]; then v=$(openssl rand -hex 20); fi
  printf '%s' "${v}"
}

for ns in data airflow; do
  kubectl create namespace "${ns}" --dry-run=client -o yaml | kubectl apply -f -
done

MINIO_USER=$(get_or_gen data minio-root AWS_ACCESS_KEY_ID)
MINIO_PW=$(get_or_gen data minio-root AWS_SECRET_ACCESS_KEY)
PG_SUPER_PW=$(get_or_gen data lakehouse-postgres postgres-password)
AIRFLOW_PW=$(get_or_gen data lakehouse-postgres airflow-password)
PIPELINE_PW=$(get_or_gen data lakehouse-postgres pipeline-password)
DBT_PW=$(get_or_gen data lakehouse-postgres dbt-password)
GRAFANA_PW=$(get_or_gen data lakehouse-postgres grafana-reader-password)
WEBSERVER_KEY=$(get_or_gen airflow airflow-webserver-secret webserver-secret-key)

for ns in data airflow; do
  kubectl -n "${ns}" create secret generic minio-root \
    --from-literal=AWS_ACCESS_KEY_ID="${MINIO_USER}" \
    --from-literal=AWS_SECRET_ACCESS_KEY="${MINIO_PW}" \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n "${ns}" create secret generic lakehouse-postgres \
    --from-literal=postgres-password="${PG_SUPER_PW}" \
    --from-literal=airflow-password="${AIRFLOW_PW}" \
    --from-literal=pipeline-password="${PIPELINE_PW}" \
    --from-literal=dbt-password="${DBT_PW}" \
    --from-literal=grafana-reader-password="${GRAFANA_PW}" \
    --from-literal=connection="postgresql://airflow:${AIRFLOW_PW}@lakehouse-postgres.data.svc:5432/airflow" \
    --from-literal=pipeline-dsn="postgresql://pipeline_writer:${PIPELINE_PW}@lakehouse-postgres.data.svc:5432/lakehouse" \
    --dry-run=client -o yaml | kubectl apply -f -
done

kubectl -n airflow create secret generic youtube-api \
  --from-literal=YOUTUBE_API_KEY="${YOUTUBE_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n airflow create secret generic airflow-webserver-secret \
  --from-literal=webserver-secret-key="${WEBSERVER_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n monitoring create secret generic grafana-lakehouse-reader \
  --from-literal=password="${GRAFANA_PW}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✅ pipeline secrets 就緒（youtube-api / minio-root ×2 / lakehouse-postgres ×2 / airflow-webserver-secret / grafana-lakehouse-reader）"
