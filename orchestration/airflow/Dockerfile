FROM apache/airflow:3.2.2

# build context = repo root（CI 的 context: "."）；yt_ingest 套件整包安裝
COPY ingestion/youtube /opt/yt_ingest

RUN pip install --no-cache-dir /opt/yt_ingest \
    "pyiceberg[s3fs,sql-postgres]==0.11.1" \
    "psycopg2-binary==2.9.10" \
    "httpx==0.28.1" \
    "boto3==1.40.0"

# DAG 不烤進 image（git-sync 送達）；cncf-kubernetes provider base image 已內建
