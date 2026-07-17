"""Test that DagBag can be initialized and required packages are importable."""

from pathlib import Path

import pytest

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


def test_imports_available():
    """Test that required packages can be imported."""
    import yt_ingest.client
    import yt_ingest.bronze
    import yt_ingest.categories
    import pyiceberg
    import psycopg2
    import boto3
    import httpx


def test_dags_dir_exists():
    """Test that DAG directory exists."""
    assert DAGS_DIR.is_dir(), f"DAG 目錄不存在：{DAGS_DIR}"


def test_dagbag_import_errors():
    """Test that DagBag can parse DAGs with no import errors.

    This verifies the DAG folder structure exists, can be parsed,
    and has no import errors. When real DAGs are added, this test
    provides signal on whether they parse correctly.
    """
    from airflow.models import DagBag

    dagbag = DagBag(dag_folder=str(DAGS_DIR), include_examples=False)
    assert dagbag.import_errors == {}, f"DAG import 失敗：{dagbag.import_errors}"
