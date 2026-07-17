from yt_ingest.categories import CATEGORIES_DDL, CATEGORIES_UPSERT, rows_from_response, upsert_categories


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def executemany(self, sql, rows):
        self.executed.append((sql, rows))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


RESP = {"items": [
    {"id": "10", "snippet": {"title": "Music"}},
    {"id": "20", "snippet": {"title": "Gaming"}},
]}


def test_rows_from_response():
    rows = rows_from_response(RESP, region="TW", updated_at="2026-07-08T00:00:00+00:00")
    assert rows == [
        ("10", "TW", "Music", "2026-07-08T00:00:00+00:00"),
        ("20", "TW", "Gaming", "2026-07-08T00:00:00+00:00"),
    ]


def test_upsert_executes_ddl_then_upsert_and_commits():
    conn = FakeConn()
    n = upsert_categories(conn, RESP, region="TW", updated_at="2026-07-08T00:00:00+00:00")
    assert n == 2
    sqls = [e[0] for e in conn.cur.executed]
    assert sqls[0] == CATEGORIES_DDL
    assert sqls[1] == CATEGORIES_UPSERT
    assert conn.committed


def test_ddl_and_upsert_shapes():
    assert "silver.youtube_categories" in CATEGORIES_DDL
    assert "PRIMARY KEY (category_id, region)" in CATEGORIES_DDL
    assert "ON CONFLICT (category_id, region) DO UPDATE" in CATEGORIES_UPSERT
