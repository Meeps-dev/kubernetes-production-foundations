"""Build-specific release identity. Keep existing API response contracts unchanged."""
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
VERSION = "week14-v2"


@router.get("/version", tags=["operations"])
def version() -> JSONResponse:
    return JSONResponse(
        content={"version": VERSION, "pod": os.getenv("HOSTNAME", "unknown")},
        headers={"Cache-Control": "no-store"},
    )
