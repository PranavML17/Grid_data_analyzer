"""
Bengaluru Grid Monitor — FastAPI backend
Local:   uvicorn server:app --reload --port 8000
Railway: PORT env var is set automatically
"""

import os
from datetime import datetime
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



# ── Daily-cached data endpoints ────────────────────────────────
# These serve the India tariff map and EV policy data.
# TTL is 24 hours — data is static (tariffs update annually,
# policies update occasionally) but served via API so the
# frontend refreshes daily and the data can be updated server-side
# without touching the HTML.

DAILY_TTL = 86400  # 24 hours in seconds
_india_cache_ts: float = 0.0
_policy_cache_ts: float = 0.0

INDIA_STATE_DATA = {
  "Andhra Pradesh":    {"rate":6.20,"avail":93,"renew":42,"ev":1240,"discom":"APSPDCL / APEPDCL"},
  "Arunachal Pradesh": {"rate":4.50,"avail":78,"renew":88,"ev":45,  "discom":"APDCL"},
  "Assam":             {"rate":7.00,"avail":80,"renew":20,"ev":180, "discom":"APDCL"},
  "Bihar":             {"rate":6.50,"avail":78,"renew":12,"ev":320, "discom":"NBPDCL / SBPDCL"},
  "Chhattisgarh":      {"rate":5.80,"avail":87,"renew":32,"ev":280, "discom":"CSPDCL"},
  "Goa":               {"rate":4.50,"avail":99,"renew":22,"ev":210, "discom":"Goa Electricity Dept"},
  "Gujarat":           {"rate":6.20,"avail":95,"renew":48,"ev":2100,"discom":"DGVCL / MGVCL / PGVCL"},
  "Haryana":           {"rate":6.00,"avail":91,"renew":30,"ev":890, "discom":"DHBVN / UHBVN"},
  "Himachal Pradesh":  {"rate":4.20,"avail":98,"renew":85,"ev":220, "discom":"HPSEBL"},
  "Jharkhand":         {"rate":7.50,"avail":82,"renew":15,"ev":190, "discom":"JBVNL"},
  "Karnataka":         {"rate":6.82,"avail":96,"renew":62,"ev":6096,"discom":"BESCOM / HESCOM / MESCOM"},
  "Kerala":            {"rate":5.50,"avail":97,"renew":52,"ev":780, "discom":"KSEB"},
  "Madhya Pradesh":    {"rate":6.80,"avail":90,"renew":35,"ev":650, "discom":"MPPKVVCL / others"},
  "Maharashtra":       {"rate":9.10,"avail":94,"renew":28,"ev":3200,"discom":"MSEDCL / BEST"},
  "Manipur":           {"rate":4.80,"avail":72,"renew":25,"ev":28,  "discom":"MSPDCL"},
  "Meghalaya":         {"rate":5.20,"avail":75,"renew":68,"ev":32,  "discom":"MePDCL"},
  "Mizoram":           {"rate":4.90,"avail":74,"renew":72,"ev":18,  "discom":"Power & Electricity Dept"},
  "Nagaland":          {"rate":5.50,"avail":70,"renew":60,"ev":22,  "discom":"Dept of Power"},
  "Odisha":            {"rate":6.00,"avail":89,"renew":38,"ev":420, "discom":"TPSODL / TPCODL"},
  "Punjab":            {"rate":4.80,"avail":93,"renew":28,"ev":650, "discom":"PSPCL"},
  "Rajasthan":         {"rate":6.50,"avail":88,"renew":55,"ev":980, "discom":"JDVVNL / JVVNL"},
  "Sikkim":            {"rate":3.40,"avail":99,"renew":92,"ev":45,  "discom":"Energy & Power Dept"},
  "Tamil Nadu":        {"rate":5.20,"avail":91,"renew":45,"ev":2800,"discom":"TANGEDCO"},
  "Telangana":         {"rate":6.80,"avail":94,"renew":38,"ev":1100,"discom":"TSSPDCL / TSNPDCL"},
  "Tripura":           {"rate":6.20,"avail":80,"renew":18,"ev":55,  "discom":"TSECL"},
  "Uttar Pradesh":     {"rate":6.00,"avail":85,"renew":22,"ev":1200,"discom":"UPPCL"},
  "Uttarakhand":       {"rate":4.50,"avail":96,"renew":72,"ev":280, "discom":"UPCL"},
  "West Bengal":       {"rate":8.50,"avail":92,"renew":8, "ev":890, "discom":"WBSEDCL / CESC"},
  "Delhi":             {"rate":4.50,"avail":99,"renew":12,"ev":1850,"discom":"BSES / TPDDL"},
  "Jammu and Kashmir": {"rate":3.50,"avail":85,"renew":75,"ev":120, "discom":"JKPDCL"},
}

EV_POLICY_DATA = {
  "updated_on": "2026-07-03",
  "source": "MHI, MoP, NITI Aayog, KERC",
  "karnataka": {
    "ev_stations": 6096,
    "ev_tariff_per_unit": 6.00,
    "renewable_pct": 62,
    "capital_subsidy_pct": "25-50",
    "rank_india": 1
  },
  "national_kpis": {
    "pm_edrive_outlay_cr": 10900,
    "chargers_targeted": 72300,
    "gst_on_ev_pct": 5,
    "public_stations_dec25": 29151
  },
  "policies": [
    {
      "name": "PM E-DRIVE Scheme",
      "status": "expiring",
      "ministry": "MHI",
      "outlay": "Rs 10,900 crore",
      "summary": "India flagship EV incentive. Rs 3,679 crore for vehicle demand subsidies (e-2W, e-3W, e-buses, trucks, ambulances). Rs 2,000 crore for 72,000+ public chargers across cities, highways, airports and ports. 100% subsidy on infrastructure for government premises with free public charger access. BHEL appointed as nodal agency for charger deployment.",
      "tags": ["MHI","Charging infra","2W / 3W","e-buses","Trucks"],
      "deadline": "e-2W: 31 July 2026 · e-3W (rickshaws): 31 March 2028 · Chargers: March 2026"
    },
    {
      "name": "ACC PLI Scheme — Battery Cell Manufacturing",
      "status": "active",
      "ministry": "MHI",
      "outlay": "Rs 18,100 crore",
      "summary": "Rs 18,100 crore PLI for advanced chemistry cell (ACC) battery manufacturing. Target: 50 GWh domestic battery cell production. Beneficiaries include Reliance, Ola Electric, Rajesh Exports. Re-tender opened following Hyundai exit. Directly reduces EV battery costs for Indian consumers.",
      "tags": ["MHI","Battery manufacturing","PLI","50 GWh target"],
      "deadline": "Ongoing through FY 2027-28"
    },
    {
      "name": "Auto & Components PLI",
      "status": "active",
      "ministry": "MHI",
      "outlay": "Rs 25,938 crore",
      "summary": "Rs 25,938 crore for advanced automotive technology including EV drivetrains, motors, power electronics and BMS. Incentivises domestic manufacturing of components India currently imports — critical for cutting EV costs long-term.",
      "tags": ["MHI","EV components","Motors","BMS"],
      "deadline": "Ongoing — Rs 7,485 crore automotive budget in FY2025-26"
    },
    {
      "name": "MoP EV Charging Guidelines 2024",
      "status": "enacted",
      "ministry": "MoP",
      "outlay": None,
      "summary": "Ministry of Power mandatory standards for all public charging stations. CCS2 connector required for 4W fast charging (50-500 kW). Type 2 AC for AC charging. 120 kW minimum fast-charging guns for heavy vehicles. Open-access provisions: any EV must be able to charge at any station regardless of OEM. Simplified licensing — no separate licence needed to set up a charging station.",
      "tags": ["MoP","CCS2 mandate","Open access","Standards"],
      "deadline": "Effective September 2024 · Revised Jan 2025 for battery swapping"
    },
    {
      "name": "Battery Swapping & BCS Guidelines",
      "status": "enacted",
      "ministry": "MoP",
      "outlay": None,
      "summary": "MoP released guidelines (Jan 2025) for Battery Swapping Stations (BSS) and Battery Charging Stations (BCS). Promotes Battery-as-a-Service model — separating battery from vehicle reduces upfront EV cost. Vehicle-to-Grid (V2G) applications permitted to aid grid stability. Liquid-cooled swappable batteries encouraged for buses and trucks.",
      "tags": ["MoP","Battery swapping","V2G","BaaS"],
      "deadline": "Effective January 2025"
    },
    {
      "name": "FAME III — Diesel Bus Replacement",
      "status": "upcoming",
      "ministry": "MHI",
      "outlay": "TBD",
      "summary": "Under deliberation as successor to FAME II and PM E-DRIVE. Scope shifts entirely to commercial and public transport — target of replacing 800,000 diesel buses with electric alternatives over 7 years. Private car and 2W subsidies will NOT be included. Timing tied to state fleet procurement pipelines.",
      "tags": ["MHI","Electric buses","800k buses","7-year plan"],
      "deadline": "Expected announcement: FY 2026-27"
    },
    {
      "name": "Union Budget 2026-27 — EV Manufacturing",
      "status": "upcoming",
      "ministry": "Finance Ministry",
      "outlay": None,
      "summary": "Budget removes Basic Customs Duty on Li-ion battery cell machinery and critical minerals processing equipment — reduces capex for domestic gigafactories. Significant for BESCOM EV tariff cost since cheaper domestic batteries = lower EV cost = higher LT-6 adoption.",
      "tags": ["Finance Ministry","BCD removal","Li-ion machinery","Critical minerals"],
      "deadline": "Effective FY 2026-27"
    },
    {
      "name": "PM Surya Ghar — Rooftop Solar for EV Charging",
      "status": "active",
      "ministry": "MNRE",
      "outlay": "Up to Rs 78,000 subsidy",
      "summary": "Up to Rs 78,000 subsidy for rooftop solar installations in Karnataka. Directly relevant to EV charging — rooftop solar + home charger = near-zero cost per km. BESCOM offers net metering: surplus solar exported to grid. Combined with BESCOM Rs 6.00/unit EV tariff, solar-charged EVs are the cheapest transport in Bengaluru.",
      "tags": ["MNRE","Rooftop solar","Net metering","Home charging"],
      "deadline": "Ongoing — pmsuryaghar.gov.in"
    },
    {
      "name": "India Electric Mobility Index (NITI Aayog)",
      "status": "active",
      "ministry": "NITI Aayog",
      "outlay": None,
      "summary": "Launched August 2025 — measures state performance across vehicle electrification, charging readiness, and R&D. Delhi, Maharashtra, and Chandigarh are current leaders. Karnataka ranks high on charging infrastructure. Index drives competitive state policy-making.",
      "tags": ["NITI Aayog","State ranking","Policy tracker"],
      "deadline": "Annual update — next edition: August 2026"
    },
    {
      "name": "100% Domestic Content Requirement — PM E-DRIVE",
      "status": "enacted",
      "ministry": "MHI",
      "outlay": None,
      "summary": "MHI mandated 100% DCR for 18 critical EV components — motors, controllers, BMS, charger modules — for 2W, 3W and e-buses under PM E-DRIVE to qualify for subsidies. Forces OEMs to localise supply chains. Eliminates Chinese component dependency for subsidy-eligible vehicles.",
      "tags": ["MHI","DCR","Localisation","18 components"],
      "deadline": "Effective 2025 for all PM E-DRIVE eligible vehicles"
    }
  ]
}


@app.get("/api/india-data")
def india_data():
    """State-wise tariff, availability, renewables, EV station data.
    Data is static (SERC tariffs update annually) but served via API
    so the frontend refreshes daily and updates are server-side only."""
    return {
        "states": INDIA_STATE_DATA,
        "national_avg_rate": 7.2,
        "data_as_of": "SERC tariff orders FY 2025-26, updated June 2026",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/ev-policy")
def ev_policy():
    """EV and power policy tracker data.
    Policies are updated when new orders/notifications are issued — the server
    is the single source of truth; push a new server.py to Railway to update."""
    return {
        **EV_POLICY_DATA,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
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
