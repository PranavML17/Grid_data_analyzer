"""
Bengaluru Grid Monitor — FastAPI backend
Local:   uvicorn server:app --reload --port 8000
Railway: PORT env var is set automatically
"""

import os
import time
import logging
import requests as _req
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from kptcl_scraper import get_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grid-monitor")

_SLDC_HEADERS = {"User-Agent": "BengaluruGridMonitor/1.0 (public data)"}

app = FastAPI(title="Bengaluru Grid Monitor", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── In-memory cache (5-min TTL) ────────────────────────────────
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


# ── Data routes ────────────────────────────────────────────────

@app.get("/api/grid-data")
def grid_data(force: bool = False):
    try:
        return _get_data(force=force)
    except Exception as exc:
        log.exception("Scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream scrape failed: {exc}")


@app.get("/api/generation")
def generation():
    return _get_data()["generation"]


@app.get("/api/demand")
def demand():
    return _get_data()["demand"]


@app.get("/api/ncep")
def ncep():
    return _get_data()["ncep"]


@app.get("/api/health")
def health():
    return {"status": "ok", "cache_age_seconds": round(time.time() - _cache_ts)}


# ── BESCOM 220kV network map (proxy from SLDC) ─────────────────
# The SLDC publishes a live JPG of BESCOM's 220kV substation
# network. We proxy it here so the browser doesn't hit kptclsldc.in
# directly (avoids CORS/hotlinking issues).

@app.get("/api/bescom-map")
def bescom_map():
    try:
        r = _req.get(
            "https://kptclsldc.in/data1/BESCOM.jpg",
            headers=_SLDC_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return Response(
            content=r.content,
            media_type="image/jpeg",
            headers={"Cache-Control": "max-age=900"},  # 15 min browser cache
        )
    except Exception as exc:
        log.warning("BESCOM map fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Could not fetch BESCOM map from SLDC")


# ── Serve frontend ─────────────────────────────────────────────
try:
    app.mount("/static", StaticFiles(directory="."), name="static")
except Exception:
    pass


@app.get("/")
def root():
    return FileResponse("index.html")


# ── Run directly ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
