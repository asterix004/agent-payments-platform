"""Agent payments API: accounts, sandbox deposits and idempotent payments for AI agents."""
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from . import ledger
from .auth import Agent, current_agent
from .config import get_settings
from .db import init_db, make_engine
from .metrics import HTTP_LATENCY, HTTP_REQUESTS, PAYMENT_AMOUNT, PAYMENTS
from .schemas import Account, AccountCreate, DepositCreate, Payment, PaymentCreate

log = logging.getLogger("payments")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format='{"level":"%(levelname)s","msg":"%(message)s"}')


def _setup_tracing(app: FastAPI, engine) -> None:
    """Enable OpenTelemetry only when an OTLP endpoint is configured."""
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": get_settings().service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
    SQLAlchemyInstrumentor().instrument(engine=engine)


def create_app(database_url: str | None = None) -> FastAPI:
    settings = get_settings()
    engine = make_engine(database_url or settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Agent Payments API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    _setup_tracing(app, engine)

    @app.middleware("http")
    async def http_metrics(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        if template not in ("/metrics", "/healthz", "/readyz"):
            HTTP_REQUESTS.labels(template, request.method, str(response.status_code)).inc()
            HTTP_LATENCY.labels(template, request.method).observe(time.perf_counter() - start)
        return response

    @app.exception_handler(ledger.LedgerError)
    async def ledger_error(_: Request, exc: ledger.LedgerError):
        return JSONResponse(status_code=exc.status_code, content={"error": type(exc).__name__, "detail": str(exc)})

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - any DB failure means not ready
            log.warning("readiness check failed: %s", exc)
            raise HTTPException(503, "database unavailable") from exc
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/accounts", response_model=Account, status_code=201)
    def create_account(body: AccountCreate, agent: Agent = Depends(current_agent)):
        agent.require("accounts:write")
        with engine.begin() as conn:
            return ledger.create_account(conn, agent.agent_id, body.currency)

    @app.get("/v1/accounts/{account_id}", response_model=Account)
    def get_account(account_id: str, agent: Agent = Depends(current_agent)):
        with engine.connect() as conn:
            acct = ledger.get_account(conn, account_id)
            if acct.owner_agent_id != agent.agent_id:
                raise ledger.Forbidden("not your account")
            return {
                "id": acct.id, "owner_agent_id": acct.owner_agent_id,
                "currency": acct.currency, "balance_minor": ledger.balance(conn, acct.id),
            }

    @app.post("/v1/deposits", status_code=201)
    def create_deposit(body: DepositCreate, agent: Agent = Depends(current_agent)):
        agent.require("treasury:deposit")
        with engine.begin() as conn:
            return ledger.deposit(conn, agent_id=agent.agent_id, account_id=body.account_id, amount=body.amount_minor)

    @app.post("/v1/payments", response_model=Payment, status_code=201)
    def create_payment(
        body: PaymentCreate,
        response: Response,
        agent: Agent = Depends(current_agent),
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        agent.require("payments:write")
        payload = body.model_dump()
        for attempt in range(2):
            try:
                with engine.begin() as conn:
                    status, result, replayed = ledger.pay(
                        conn, agent_id=agent.agent_id, agent_max_txn=agent.max_txn_minor,
                        hard_max=settings.max_payment_minor, idem_key=idempotency_key, body=payload,
                    )
                break
            except ledger.ConcurrentRetry:
                if attempt == 1:
                    raise HTTPException(409, "concurrent request with the same Idempotency-Key") from None
            except ledger.LedgerError as exc:
                PAYMENTS.labels(exc.outcome).inc()
                raise
        if replayed:
            PAYMENTS.labels("replayed").inc()
            response.headers["Idempotent-Replayed"] = "true"
        else:
            PAYMENTS.labels("succeeded").inc()
            PAYMENT_AMOUNT.labels(result["currency"]).inc(result["amount_minor"])
        response.status_code = status
        return result

    return app


app = create_app()
