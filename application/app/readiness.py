"""Readiness checks database connectivity; /health stays database-independent."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.config import settings

router = APIRouter()

# A separate engine keeps probe timeouts out of normal application transactions.
# NullPool closes each probe connection rather than keeping another idle pool.
readiness_engine = create_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    connect_args={
        "connect_timeout": 2,
        "options": "-c statement_timeout=1000",
    },
    hide_parameters=True,
)


@router.get("/ready", include_in_schema=False)
def ready() -> JSONResponse:
    # Synchronous psycopg2 I/O belongs in a normal def endpoint, not async def.
    try:
        with readiness_engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
        if result != 1:
            raise SQLAlchemyError("Unexpected readiness query result")
    except SQLAlchemyError:
        # Never expose a DSN, password, query parameters, or driver error text.
        return JSONResponse(
            status_code=503,
            content={"status": "not ready"},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready"},
        headers={"Cache-Control": "no-store"},
    )
