"""Circuit breaker around database calls.

When the database is down, every request would otherwise wait out the connect timeout
before failing, so requests pile up faster than they fail and clients time out instead of
getting a retryable 503. After `failure_threshold` consecutive database failures the breaker
opens and requests fail immediately for `reset_after` seconds. Then one trial request is let
through (half-open): success closes the breaker, failure opens it again.

Readiness probes bypass the open check and report their result. While they keep failing they
keep the breaker open (so live payments are not used as trials), and the first passing probe
closes it.
"""
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import exc as sa_exc

from .metrics import DB_CIRCUIT_STATE

log = logging.getLogger("payments")

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
DB_UNAVAILABLE = (sa_exc.OperationalError, sa_exc.TimeoutError)


class CircuitOpen(Exception):
    def __init__(self, retry_after: float):
        super().__init__("database circuit open")
        self.retry_after = retry_after


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_after: float = 5.0,
                 clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.reset_after = reset_after
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False
        self._set_state(CLOSED)

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        if getattr(self, "_state", None) not in (None, state):
            log.warning("database circuit %s -> %s", self._state, state)
        self._state = state
        for s in (CLOSED, OPEN, HALF_OPEN):
            DB_CIRCUIT_STATE.labels(s).set(1 if s == state else 0)

    def _before_call(self) -> None:
        with self._lock:
            if self._state == CLOSED:
                return
            remaining = self._opened_at + self.reset_after - self._clock()
            if self._state == OPEN and remaining <= 0:
                self._set_state(HALF_OPEN)
            if self._state == HALF_OPEN and not self._trial_in_flight:
                self._trial_in_flight = True
                return
            raise CircuitOpen(max(remaining, 1.0))

    def _on_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._trial_in_flight = False
            if self._state != CLOSED:
                self._set_state(CLOSED)

    def _on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._trial_in_flight = False
            if self._state == HALF_OPEN or self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
                self._set_state(OPEN)

    @contextmanager
    def guard(self, probe: bool = False) -> Iterator[None]:
        """Wrap one unit of database work. `probe=True` (readiness) always runs and only reports."""
        if not probe:
            self._before_call()
        try:
            yield
        except DB_UNAVAILABLE:
            self._on_failure()
            raise
        except BaseException:
            # The database answered (e.g. insufficient funds, constraint error): it is up.
            self._on_success()
            raise
        else:
            self._on_success()
