from datetime import datetime

from d94_mcp.token_sync import MAX_TTL, PREFIX, sync


class FakeRedis:
    def __init__(self, keys):
        self.data = {k: ("old", None) for k in keys}

    def scan_iter(self, match, count):
        return [k for k in self.data if k.startswith(match.rstrip("*"))]

    def pipeline(self, transaction):
        return self

    def set(self, k, v, ex):
        self.data[k] = (v, ex)

    def delete(self, k):
        self.data.pop(k)

    def execute(self):
        pass


def test_sync_sets_active_caps_ttl_and_removes_revoked():
    exp = datetime(2027, 1, 1)
    r = FakeRedis([PREFIX + "keep", PREFIX + "revoked", "other:key"])
    assert sync([("keep", "cira", exp, 999999), ("new", "docs", exp, 30)], r) == (2, 1)
    assert r.data[PREFIX + "keep"] == ('{"service": "cira", "expiresAt": "2027-01-01T00:00:00"}', MAX_TTL)
    assert r.data[PREFIX + "new"][1] == 30
    assert PREFIX + "revoked" not in r.data and "other:key" in r.data
