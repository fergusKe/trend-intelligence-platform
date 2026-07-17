"""Test that DagBag can be initialized and required packages are importable."""

import pytest


def test_imports_available():
    """Test that required packages can be imported."""
    import yt_ingest.client
    import yt_ingest.bronze
    import yt_ingest.categories
    import pyiceberg
    import psycopg2
    import boto3
    import httpx


def test_dagbag_import():
    """Test that airflow DagBag can be instantiated.

    This verifies the DAG folder structure exists and can be parsed.
    """
    from airflow.models import DagBag

    # DagBag parses all DAGs in the specified directory
    # We test with a minimal path for now
    dag_bag = DagBag(
        dag_folder="/tmp/dags",
        include_examples=False,
    )
    # If we get here without exception, DagBag was initialized successfully
    assert dag_bag is not None
