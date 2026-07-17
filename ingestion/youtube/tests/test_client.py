import httpx
import pytest

from yt_ingest.client import QuotaExceededError, YouTubeAPIError, YouTubeClient


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return YouTubeClient(api_key="test-key", transport=transport)


def test_fetch_trending_returns_raw_response():
    def handler(request):
        assert request.url.params["chart"] == "mostPopular"
        assert request.url.params["regionCode"] == "TW"
        assert request.url.params["maxResults"] == "50"
        assert request.url.params["part"] == "snippet,statistics,contentDetails"
        assert request.url.params["key"] == "test-key"
        return httpx.Response(200, json={"items": [{"id": "vid1"}]})

    resp = make_client(handler).fetch_trending(region="TW", max_results=50)
    assert resp == {"items": [{"id": "vid1"}]}


def test_quota_exceeded_raises_dedicated_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "quotaExceeded"}], "code": 403}
        })

    with pytest.raises(QuotaExceededError):
        make_client(handler).fetch_trending(region="TW")


def test_daily_limit_exceeded_raises_dedicated_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "dailyLimitExceeded"}], "code": 403}
        })

    with pytest.raises(QuotaExceededError):
        make_client(handler).fetch_trending(region="TW")


def test_server_error_raises_retryable_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(YouTubeAPIError):  # 讓 Airflow retry 機制接手
        make_client(handler).fetch_trending(region="TW")


def test_forbidden_non_quota_is_retryable_error():
    def handler(request):
        return httpx.Response(403, json={
            "error": {"errors": [{"reason": "forbidden"}], "code": 403}
        })

    with pytest.raises(YouTubeAPIError):
        make_client(handler).fetch_trending(region="TW")


def test_fetch_categories():
    def handler(request):
        assert request.url.path.endswith("/videoCategories")
        assert request.url.params["regionCode"] == "JP"
        return httpx.Response(200, json={"items": [{"id": "10", "snippet": {"title": "Music"}}]})

    resp = make_client(handler).fetch_categories(region="JP")
    assert resp["items"][0]["id"] == "10"
