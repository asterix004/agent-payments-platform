"""A database outage must surface as retryable 503s and failed readiness, never failed liveness."""
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError

from tests.conftest import auth, idem


def _db_down(*_a, **_kw):
    raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_db_outage_is_503_unready_but_live(client, funded, monkeypatch):
    alice, bob = funded
    engine = client.app.state.engine
    monkeypatch.setattr(engine, "connect", _db_down)
    monkeypatch.setattr(engine, "begin", _db_down)

    def payments_503():
        return REGISTRY.get_sample_value(
            "http_requests_total", {"route": "/v1/payments", "method": "POST", "code": "503"}) or 0

    before = payments_503()
    r = client.post("/v1/payments", headers={**auth("agent_alice"), **idem()}, json={
        "payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"})
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "2"
    assert payments_503() == before + 1  # counted against the availability SLO

    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200
