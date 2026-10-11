"""Database circuit breaker: fail fast while the database is down, recover on its own."""
import pytest
from sqlalchemy.exc import OperationalError

from app.breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpen
from tests.conftest import auth, idem


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def db_error():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def fail(breaker, probe=False):
    with pytest.raises(OperationalError), breaker.guard(probe=probe):
        raise db_error()


def test_opens_after_threshold_then_rejects_without_calling():
    b = CircuitBreaker(failure_threshold=3, reset_after=5, clock=Clock())
    for _ in range(2):
        fail(b)
    assert b.state == CLOSED
    fail(b)
    assert b.state == OPEN
    with pytest.raises(CircuitOpen) as exc, b.guard():
        pytest.fail("must not reach the database while open")
    assert exc.value.retry_after == 5


def test_success_resets_consecutive_count():
    b = CircuitBreaker(failure_threshold=2, clock=Clock())
    fail(b)
    with b.guard():
        pass
    fail(b)
    assert b.state == CLOSED


def test_business_errors_count_as_database_up():
    b = CircuitBreaker(failure_threshold=1, clock=Clock())
    with pytest.raises(ValueError), b.guard():
        raise ValueError("insufficient funds")
    assert b.state == CLOSED


def test_half_open_allows_one_trial():
    clock = Clock()
    b = CircuitBreaker(failure_threshold=1, reset_after=5, clock=clock)
    fail(b)
    clock.now += 5
    with b.guard():
        assert b.state == HALF_OPEN
        with pytest.raises(CircuitOpen), b.guard():  # a concurrent request during the trial
            pass
    assert b.state == CLOSED


def test_failed_trial_reopens():
    clock = Clock()
    b = CircuitBreaker(failure_threshold=1, reset_after=5, clock=clock)
    fail(b)
    clock.now += 5
    fail(b)
    assert b.state == OPEN
    with pytest.raises(CircuitOpen), b.guard():
        pass


def test_probe_bypasses_open_and_closes_on_success():
    b = CircuitBreaker(failure_threshold=1, reset_after=60, clock=Clock())
    fail(b)
    with b.guard(probe=True):
        pass
    assert b.state == CLOSED


def test_api_fails_fast_while_open_and_readiness_recovers(client, funded, monkeypatch):
    alice, bob = funded
    engine, breaker = client.app.state.engine, client.app.state.breaker
    calls = {"n": 0}
    real_begin, real_connect = engine.begin, engine.connect

    def down(*_a, **_kw):
        calls["n"] += 1
        raise db_error()

    monkeypatch.setattr(engine, "begin", down)
    monkeypatch.setattr(engine, "connect", down)

    def pay():
        return client.post("/v1/payments", headers={**auth("agent_alice"), **idem()}, json={
            "payer_account_id": alice["id"], "payee_account_id": bob["id"], "amount_minor": 100, "currency": "USD"})

    for _ in range(breaker.failure_threshold):
        assert pay().status_code == 503
    assert breaker.state == OPEN
    before = calls["n"]
    r = pay()
    assert r.status_code == 503 and int(r.headers["Retry-After"]) >= 1
    assert calls["n"] == before  # rejected without touching the database

    monkeypatch.setattr(engine, "begin", real_begin)
    monkeypatch.setattr(engine, "connect", real_connect)
    assert client.get("/readyz").status_code == 200  # the kubelet's probe closes the breaker
    assert breaker.state == CLOSED
    assert pay().status_code == 201
