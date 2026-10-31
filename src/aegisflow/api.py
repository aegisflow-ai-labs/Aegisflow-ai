"""Synthetic-only HTTP boundary. Static development credentials are not OIDC."""

import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi import Request as HTTPRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime

from .contracts import AuditEvent, Case, Contract, Evidence, Identifier, Request, Scenario, Scope
from .postgres import PostgresStore
from .store import IdempotencyConflict, NotFound, PolicyDenied, Store


class CreateCase(Contract):
    order_id: Identifier
    as_of: AwareDatetime


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(
    store: Store | PostgresStore, credentials: dict[str, Scope], sources: tuple[Scenario, ...]
) -> FastAPI:
    """Only server configuration may assign scopes and source snapshots."""
    if not credentials or any(
        len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in credentials
    ):
        raise ValueError("Sunucu için SHA-256 kimlik kayıtları gerekli")
    if isinstance(store, PostgresStore):
        store.verify_runtime_role()
    principals = dict(credentials)
    snapshots = {(s.order.tenant_id, s.order.order_id): s.model_copy(deep=True) for s in sources}
    if len(snapshots) != len(sources):
        raise ValueError("Yinelenen kaynak kaydı")
    app = FastAPI(title="AegisFlow synthetic baseline", version="0.2.0")

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> Scope:
        if authorization is not None and authorization.startswith("Bearer "):
            hashed = token_digest(authorization[7:])
            for expected, scope in principals.items():
                if secrets.compare_digest(expected, hashed):
                    return scope
        raise HTTPException(401, detail="UNAUTHENTICATED", headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_: HTTPRequest, __: RequestValidationError) -> JSONResponse:
        # Never echo input bodies, tokens, or framework validation details.
        return JSONResponse(status_code=422, content={"detail": "INVALID_SCHEMA"})

    @app.exception_handler(ValueError)
    async def invalid_domain(_: HTTPRequest, __: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "INVALID_SCHEMA"})

    @app.exception_handler(PolicyDenied)
    async def denied(_: HTTPRequest, __: PolicyDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "POLICY_DENIED"})

    @app.exception_handler(NotFound)
    async def missing(_: HTTPRequest, __: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "NOT_FOUND"})

    @app.exception_handler(IdempotencyConflict)
    async def conflict(_: HTTPRequest, __: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "IDEMPOTENCY_CONFLICT"})

    @app.exception_handler(psycopg.Error)
    @app.exception_handler(sqlite3.Error)
    async def unavailable(_: HTTPRequest, __: sqlite3.Error) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "DEPENDENCY_UNAVAILABLE"})

    @app.post("/v1/cases", response_model=Case, status_code=201)
    def create(
        body: CreateCase,
        scope: Annotated[Scope, Depends(authenticate)],
        idempotency_key: Annotated[Identifier, Header()],
    ) -> Case:
        Store.authorize(scope, scope.tenant_id, "investigate")
        source = snapshots.get((scope.tenant_id, body.order_id))
        if source is None:
            raise NotFound()
        request = Request(
            tenant_id=scope.tenant_id,
            order_id=body.order_id,
            idempotency_key=idempotency_key,
            as_of=body.as_of,
        )
        return store.run(scope, request, source)

    @app.get("/v1/cases/{case_id}", response_model=Case)
    def read(case_id: str, scope: Annotated[Scope, Depends(authenticate)]) -> Case:
        return store.read(scope, case_id)

    @app.get("/v1/cases/{case_id}/events", response_model=tuple[AuditEvent, ...])
    def events(
        case_id: str, scope: Annotated[Scope, Depends(authenticate)]
    ) -> tuple[AuditEvent, ...]:
        return store.events(scope, case_id)

    @app.get("/v1/cases/{case_id}/evidence/{evidence_id}", response_model=Evidence)
    def evidence(
        case_id: str, evidence_id: str, scope: Annotated[Scope, Depends(authenticate)]
    ) -> Evidence:
        case = store.read(scope, case_id)
        for item in case.evidence:
            if item.evidence_id == evidence_id:
                return item
        raise NotFound()

    return app


def from_environment() -> FastAPI:
    """Fail closed: no default identity, token, or source. Configuration stays server-side."""
    config = json.loads(Path(os.environ["AEGISFLOW_AUTH_FILE"]).read_text())
    credentials = {key: Scope.model_validate(value) for key, value in config.items()}
    source_path = Path(os.environ["AEGISFLOW_SCENARIO_FILE"])
    if source_path.stat().st_size > 1_000_000:
        raise ValueError("Kaynak boyutu sınırı aşıldı")
    source = Scenario.model_validate_json(source_path.read_text())
    if "AEGISFLOW_DATABASE_URL" in os.environ:
        store: Store | PostgresStore = PostgresStore(os.environ["AEGISFLOW_DATABASE_URL"])
    else:
        store = Store(Path(os.environ["AEGISFLOW_DB"]))
    return create_app(store, credentials, (source,))
