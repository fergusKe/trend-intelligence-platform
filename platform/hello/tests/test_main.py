from fastapi.testclient import TestClient

from hello.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_exposes_http_requests():
    client.get("/healthz")  # 先打一次讓 counter 有值
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_request" in resp.text
