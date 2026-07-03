"""
Bengaluru Grid Monitor — FastAPI backend
Local:   uvicorn server:app --reload --port 8000
Railway: PORT env var is set automatically
"""

import os
import time
import logging
from collections import deque
import requests as _req
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from kptcl_scraper import get_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grid-monitor")

_SLDC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://kptclsldc.in/bescom.aspx",   # ← required, SLDC checks this
    "Accept":     "image/jpeg,image/*,*/*",
}

app = FastAPI(title="Bengaluru Grid Monitor", version="2.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"]
)

# ── In-memory cache (5-min TTL) ────────────────────────────────
CACHE_TTL = 300
_cache: dict | None = None
_cache_ts: float = 0.0

# ── Health history — rolling 288 readings (24 h at 5-min intervals)
_health_history: deque = deque(maxlen=288)


# ── Health score ───────────────────────────────────────────────
def _compute_health(data: dict) -> dict:
    """
    Computes a 0–100 Bengaluru grid health score from two signals:
      - Frequency deviation from 50 Hz  (weight 60%)
      - BESCOM demand fulfillment        (weight 40%)
    Returns a dict with score, status, component scores, and timestamp.
    """
    gen    = data.get("generation", {})
    demand = data.get("demand",     {})
    bescom = demand.get("bescom")   or {}

    hz        = gen.get("frequency_hz") or demand.get("frequency_hz") or 50.0
    scheduled = bescom.get("schedule_mw") or 0
    actual    = bescom.get("actual_mw")   or 0

    # Frequency score
    dev = abs(hz - 50.0)
    if   dev <= 0.10: freq_score = 100
    elif dev <= 0.20: freq_score = 80
    elif dev <= 0.30: freq_score = 60
    elif dev <= 0.50: freq_score = 30
    else:             freq_score = 0

    # Demand fulfillment score
    if scheduled > 0:
        ratio = actual / scheduled
        if   0.95 <= ratio <= 1.05: demand_score = 100
        elif 0.90 <= ratio <= 1.10: demand_score = 80
        elif 0.85 <= ratio <= 1.15: demand_score = 60
        else:                        demand_score = 40
    else:
        demand_score = 50

    score  = round(freq_score * 0.6 + demand_score * 0.4)
    status = "healthy" if score >= 80 else "degraded" if score >= 50 else "stressed"

    return {
        "score":        score,
        "status":       status,
        "freq_score":   freq_score,
        "demand_score": demand_score,
        "hz":           hz,
        "bescom_actual":    actual,
        "bescom_scheduled": scheduled,
        "timestamp":    data.get("fetched_at", ""),
    }


def _get_data(force: bool = False) -> dict:
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    log.info("Fetching fresh data from KPTCL SLDC …")
    _cache    = get_all()
    _cache_ts = now
    # Log a health reading every time we fetch fresh data
    _health_history.append(_compute_health(_cache))
    return _cache


# ── Routes ─────────────────────────────────────────────────────

@app.get("/api/grid-data")
def grid_data(force: bool = False):
    try:
        return _get_data(force=force)
    except Exception as exc:
        log.exception("Scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/health-history")
def health_history():
    """
    Returns the rolling list of grid health readings (up to 288 = 24 h).
    Each entry: {score, status, freq_score, demand_score, hz, timestamp}
    """
    return list(_health_history)


@app.get("/api/generation")
def generation(): return _get_data()["generation"]

@app.get("/api/demand")
def demand(): return _get_data()["demand"]

@app.get("/api/ncep")
def ncep(): return _get_data()["ncep"]

@app.get("/api/health")
def health():
    h = _compute_health(_cache) if _cache else {}
    return {
        "status":             "ok",
        "cache_age_seconds":  round(time.time() - _cache_ts),
        "grid_health_score":  h.get("score"),
        "grid_health_status": h.get("status"),
    }


# ── BESCOM 220kV map proxy (with Referer so SLDC doesn't block it)
@app.get("/api/bescom-map")
def bescom_map():
    try:
        r = _req.get(
            "https://kptclsldc.in/data1/BESCOM.jpg",
            headers=_SLDC_HEADERS,
            timeout=12,
        )
        r.raise_for_status()
        return Response(
            content=r.content,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as exc:
        log.warning("BESCOM map fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="BESCOM map unavailable from SLDC")


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
