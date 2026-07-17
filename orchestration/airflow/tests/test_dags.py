"""DagBag import + 依賴鏈 + 守門 + config 一致性（design §11）。"""
import re
from pathlib import Path

import yaml
from airflow.models import DagBag

REPO_ROOT = Path(__file__).resolve().parents[3]
DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


def _bag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


def test_dagbag_imports_clean():
    bag = _bag()
    assert bag.import_errors == {}, bag.import_errors
    assert {"yt_trending_hourly", "yt_categories_daily", "yt_reprocess_range"} <= set(bag.dags)


def test_hourly_guards():
    dag = _bag().dags["yt_trending_hourly"]
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout.total_seconds() == 45 * 60
    assert dag.default_args["retries"] == 3
    assert dag.default_args["retry_exponential_backoff"] is True


def test_hourly_dependency_chain():
    dag = _bag().dags["yt_trending_hourly"]
    ids = set(dag.task_ids)
    assert {"ingest_trending", "delete_stale_sparkapp", "spark_bronze_to_silver",
            "load_silver_to_postgres", "dbt_run", "dbt_test"} <= ids
    get = dag.get_task
    assert "delete_stale_sparkapp" in [t.task_id for t in get("ingest_trending").downstream_list]
    assert "spark_bronze_to_silver" in [t.task_id for t in get("delete_stale_sparkapp").downstream_list]
    assert "load_silver_to_postgres" in [t.task_id for t in get("spark_bronze_to_silver").downstream_list]
    assert "dbt_run" in [t.task_id for t in get("load_silver_to_postgres").downstream_list]
    assert "dbt_test" in [t.task_id for t in get("dbt_run").downstream_list]
    # 部分 region 失敗不擋批：mapped ingest 之後第一個匯聚 task 是 all_done
    # （注意：此 TriggerRule enum 在本 Airflow SDK 版本 str() 回 "TriggerRule.ALL_DONE"，
    #  不是其 value；enum 是 str 子類，用 == 比較走 str.__eq__ 直接比 value 較穩健）
    assert get("delete_stale_sparkapp").trigger_rule == "all_done"


def test_categories_and_reprocess_guards():
    bag = _bag()
    daily = bag.dags["yt_categories_daily"]
    assert daily.catchup is False
    rp = bag.dags["yt_reprocess_range"]
    assert rp.schedule is None or str(rp.schedule) == "None"
    assert {"start_hour", "end_hour"} <= set(rp.params)


def test_regions_single_source_of_truth_vs_dbt():
    pipeline = yaml.safe_load((DAGS_DIR / "config" / "pipeline.yaml").read_text())
    regions = pipeline["regions"]
    assert regions == ["TW", "JP", "KR", "HK", "US", "GB", "SG", "AU"]
    schema = yaml.safe_load(
        (REPO_ROOT / "lakehouse" / "dbt" / "models" / "staging" / "_staging_schema.yml").read_text()
    )
    stg = next(m for m in schema["models"] if m["name"] == "stg_video_snapshots")
    region_col = next(c for c in stg["columns"] if c["name"] == "region")
    accepted = next(t for t in region_col["data_tests"] if isinstance(t, dict) and "accepted_values" in t)
    assert accepted["accepted_values"]["values"] == regions, "pipeline.yaml regions 與 dbt accepted_values 漂移"
