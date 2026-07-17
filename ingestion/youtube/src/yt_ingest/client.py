"""YouTube Data API v3 client（httpx，顯式 timeout，錯誤分類）。

錯誤語意（design §3）：
- 403 且 reason ∈ {quotaExceeded, dailyLimitExceeded} → QuotaExceededError（DAG 層 map 成
  AirflowFailException fail-fast，不重試——重試燒 quota 又必然再失敗）
- 其他非 2xx → YouTubeAPIError（交給 Airflow retry：3 次 exponential backoff）
本模組不得 import airflow（套件獨立可測、可攜）。
"""
from __future__ import annotations

import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


class YouTubeAPIError(Exception):
    """非 quota 的 API/網路錯誤（可重試）。"""


class QuotaExceededError(Exception):
    """每日 quota 用罄（不可重試，fail-fast）。"""


class YouTubeClient:
    def __init__(self, api_key: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport)

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._client.get(path, params={**params, "key": self._api_key})
        except httpx.HTTPError as exc:
            raise YouTubeAPIError(f"HTTP error calling {path}: {exc}") from exc
        if resp.status_code == 403:
            reasons = {
                e.get("reason")
                for e in resp.json().get("error", {}).get("errors", [])
            }
            if reasons & QUOTA_REASONS:
                raise QuotaExceededError(f"quota exhausted: reasons={sorted(reasons)}")
            raise YouTubeAPIError(f"403 non-quota: reasons={sorted(reasons)}")
        if resp.status_code != 200:
            raise YouTubeAPIError(f"{path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def fetch_trending(self, region: str, max_results: int = 50) -> dict:
        return self._get("/videos", {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region,
            "maxResults": str(max_results),
        })

    def fetch_categories(self, region: str) -> dict:
        return self._get("/videoCategories", {"part": "snippet", "regionCode": region})
