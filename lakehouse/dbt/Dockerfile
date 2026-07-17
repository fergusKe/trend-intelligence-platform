FROM python:3.12-slim
RUN pip install --no-cache-dir dbt-postgres==1.10.2
WORKDIR /app
COPY dbt_project.yml profiles.yml ./
COPY macros/ macros/
COPY models/ models/
COPY tests/ tests/
RUN useradd -u 1000 -m dbt && chown -R dbt /app
USER 1000
# KPO 以 dbt run/test --profiles-dir /app --project-dir /app 呼叫（Task 9）
