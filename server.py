"""
Karnataka Grid Monitor — FastAPI backend
Local:   uvicorn server:app --reload --port 8000
Railway: PORT env var is set automatically
"""

import os
import time
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from kptcl_scraper import get_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grid-monitor")

app = FastAPI(title="Karnataka Grid Monitor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten this in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Simple in-memory cache (5-minute TTL) ──────────────────────
CACHE_TTL_SECONDS = 300
_cache: dict | None = None
_cache_ts: float = 0.0


def _get_data(force: bool = False) -> dict:
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache and (now - _cache_ts) < CACHE_TTL_SECONDS:
        log.info("Cache hit (age %.0fs)", now - _cache_ts)
        return _cache
    log.info("Fetching fresh data from KPTCL SLDC …")
    _cache = get_all()
    _cache_ts = now
    return _cache


# ── Routes ─────────────────────────────────────────────────────

@app.get("/api/grid-data")
def grid_data(force: bool = False):
    """
    Returns combined generation + demand + NCEP snapshot.
    Add ?force=true to bypass the 5-minute cache.
    """
    try:
        return _get_data(force=force)
    except Exception as exc:
        log.exception("Scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream scrape failed: {exc}")


@app.get("/api/generation")
def generation():
    """Plant-level generation + frequency + source breakdown."""
    return _get_data()["generation"]


@app.get("/api/demand")
def demand():
    """ESCOM schedule vs actual demand (BESCOM + all ESCOMs)."""
    return _get_data()["demand"]


@app.get("/api/ncep")
def ncep():
    """Renewable breakdown (solar/wind/bio) per ESCOM."""
    return _get_data()["ncep"]


@app.get("/api/health")
def health():
    return {"status": "ok", "cache_age_seconds": round(time.time() - _cache_ts)}


# ── Serve the frontend ─────────────────────────────────────────
# Put index.html in the same directory and it will be served at /
try:
    app.mount("/static", StaticFiles(directory="."), name="static")
except Exception:
    pass  # static dir optional in dev


@app.get("/")
def root():
    return FileResponse("index.html")


# ── Run directly ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))   # Railway sets $PORT automatically
    uvicorn.run("server:app", host="0.0.0.0", port=port)
