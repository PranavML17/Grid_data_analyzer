"""
India EV & Energy Infrastructure Platform — FastAPI backend
Local:   uvicorn server:app --reload --port 8000
Railway: PORT env var is set automatically
"""

import os
import time
import logging
from datetime import datetime
from collections import deque
import requests as _req
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from kptcl_scraper import get_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grid-platform")

app = FastAPI(title="India EV & Energy Platform", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_SLDC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://kptclsldc.in/bescom.aspx",
    "Accept":     "image/jpeg,image/*,*/*",
}

# ── Grid data cache (5-min TTL) ────────────────────────────────────────────────
CACHE_TTL = 300
_cache: dict | None = None
_cache_ts: float = 0.0
_health_history: deque = deque(maxlen=288)


def _compute_health(data: dict) -> dict:
    gen    = data.get("generation", {})
    demand = data.get("demand",     {})
    bescom = demand.get("bescom")   or {}
    hz     = gen.get("frequency_hz") or demand.get("frequency_hz") or 50.0
    sched  = bescom.get("schedule_mw") or 0
    actual = bescom.get("actual_mw")   or 0
    dev    = abs(hz - 50.0)
    fs = 100 if dev<=.10 else 80 if dev<=.20 else 60 if dev<=.30 else 30 if dev<=.50 else 0
    ds = 50
    if sched > 0:
        r = actual / sched
        ds = 100 if .95<=r<=1.05 else 80 if .90<=r<=1.10 else 60 if .85<=r<=1.15 else 40
    score  = round(fs * .6 + ds * .4)
    status = "healthy" if score >= 80 else "degraded" if score >= 50 else "stressed"
    return {"score": score, "status": status, "freq_score": fs, "demand_score": ds,
            "hz": hz, "timestamp": data.get("fetched_at", "")}


def _get_data(force: bool = False) -> dict:
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    log.info("Fetching fresh data from KPTCL SLDC …")
    _cache    = get_all()
    _cache_ts = now
    _health_history.append(_compute_health(_cache))
    return _cache


# ── BESS government schemes data ──────────────────────────────────────────────
BESS_SCHEMES_DATA = {
    "updated_on": "2026-07-04",
    "sources": ["MNRE", "SECI", "POSOCO", "MoP", "PIB"],
    "schemes": [
        {
            "name": "VGF Scheme for BESS",
            "short": "Viability Gap Funding — Standalone BESS",
            "ministry": "MNRE / SECI",
            "outlay": "₹3,760 crore",
            "capacity_target": "4,000 MWh (first tranche)",
            "benefit": "Viability Gap Funding of up to ₹94/kWh installed capacity",
            "min_size_mwh": 10,
            "eligibility": "Grid-connected standalone BESS, minimum 10 MWh capacity, must be connected to ISTS or state grid",
            "how_to_apply": "Bid through SECI RfP process. Next tranche open — check SECI tender portal (seci.co.in)",
            "status": "active",
            "deadline": "FY 2029-30 (phased deployment)",
            "source": "MNRE notification SO 1104(E), March 2023",
            "source_url": "https://mnre.gov.in",
            "tags": ["Grid-scale", "Utility", "SECI tender"]
        },
        {
            "name": "ISTS Waiver — Renewable + Storage",
            "short": "Inter-State Transmission Waiver for RE+BESS",
            "ministry": "MoP / CEA",
            "outlay": "N/A (tariff benefit)",
            "capacity_target": "All commissioned by March 2026",
            "benefit": "100% waiver on ISTS charges and losses for renewable energy paired with storage",
            "min_size_mwh": 0,
            "eligibility": "Solar or wind projects with co-located or virtual BESS commissioned by March 2026. Extended to 2030 for hybrid projects.",
            "how_to_apply": "Automatic — claim during CERC or SERC tariff petition. No separate application.",
            "status": "active",
            "deadline": "Projects commissioned by March 2030 (hybrid RE+storage)",
            "source": "MoP order, January 2018 (amended 2023)",
            "source_url": "https://powermin.gov.in",
            "tags": ["RE+Storage", "Tariff waiver", "ISTS"]
        },
        {
            "name": "POSOCO Ancillary Services Market",
            "short": "Frequency Regulation via BESS",
            "ministry": "POSOCO / NLDC",
            "outlay": "Market-based (no fixed subsidy)",
            "capacity_target": "300 MW reserves procured weekly",
            "benefit": "Capacity payment + energy payment for frequency regulation. Indicative: ₹50–120 lakh/MW/year for primary frequency response",
            "min_size_mwh": 5,
            "eligibility": "BESS with response time ≤100ms, connected at 33kV or above, registered as resource with POSOCO",
            "how_to_apply": "Register as an Ancillary Service Provider (ASP) with NLDC. Technical specs: CEA Grid Code 2023",
            "status": "active",
            "deadline": "Ongoing market — weekly auctions",
            "source": "POSOCO Ancillary Services Regulations, CERC 2022",
            "source_url": "https://posoco.in",
            "tags": ["Frequency regulation", "Ancillary services", "Market-based"]
        },
        {
            "name": "PM KUSUM Component C — BESS for Agriculture",
            "short": "Solar Pump + Storage for Farmers",
            "ministry": "MNRE",
            "outlay": "₹34,035 crore (full KUSUM, Component C portion ~₹4,000 Cr)",
            "capacity_target": "25 lakh solar pumps with storage option",
            "benefit": "60% central subsidy on solar pump + storage. Farmer pays only 10%, state pays 30%.",
            "min_size_mwh": 0.005,
            "eligibility": "Agricultural consumers with existing or new pump connections. Works through state DISCOM/nodal agency.",
            "how_to_apply": "Apply through state nodal agency (e.g., KREDL in Karnataka). Farmer → DISCOM → nodal agency pipeline.",
            "status": "active",
            "deadline": "Ongoing — state allocations refresh annually",
            "source": "MNRE PM-KUSUM guidelines 2022",
            "source_url": "https://mnre.gov.in/solar/schemes",
            "tags": ["Agriculture", "C&I adjacent", "Subsidy 60%"]
        },
        {
            "name": "State-Level BESS Mandates",
            "short": "Tamil Nadu, Rajasthan, Karnataka BESS requirements",
            "ministry": "State SERCs",
            "outlay": "State-specific",
            "capacity_target": "Varies by state",
            "benefit": "Mandatory storage procurement creates guaranteed offtake market",
            "min_size_mwh": 10,
            "eligibility": "States with >2 GW renewable capacity have mandatory BESS % in new RE projects",
            "how_to_apply": "Bid through state DISCOM procurement tenders (TANGEDCO, RUVNL, BESCOM for storage-linked RE)",
            "status": "active",
            "deadline": "Ongoing — each tender cycle",
            "source": "SERC tariff orders: TN 2024, Rajasthan 2024, Karnataka 2025",
            "source_url": "https://kerc.karnataka.gov.in",
            "tags": ["Tamil Nadu", "Rajasthan", "Karnataka", "Mandatory"]
        }
    ],
    "major_deployments": [
        {"entity": "SECI", "capacity_mwh": 1000, "location": "Multiple states (tendered)", "technology": "Li-ion", "use_case": "Grid firming + frequency regulation", "status": "Procured / under construction"},
        {"entity": "NTPC", "capacity_mwh": 500,  "location": "Rajasthan", "technology": "Li-ion NMC", "use_case": "Renewable firming at RE parks", "status": "400 MWh operational"},
        {"entity": "TANGEDCO (Tamil Nadu)", "capacity_mwh": 300, "location": "Tamil Nadu", "technology": "Li-ion LFP", "use_case": "Frequency regulation, duck curve management", "status": "Under procurement"},
        {"entity": "BESCOM (Karnataka)", "capacity_mwh": 50, "location": "Bengaluru", "technology": "Li-ion LFP", "use_case": "Distribution-level peak shaving + frequency support", "status": "Commissioning 2026"},
        {"entity": "Tata Power / ReNew / Adani (IPPs)", "capacity_mwh": 2000, "location": "Pan-India", "technology": "Li-ion NMC/LFP", "use_case": "RE firming, SECI/state DISCOM contracts", "status": "Various stages"},
        {"entity": "Indian Railways (IRCON)", "capacity_mwh": 150, "location": "Traction substations", "technology": "Li-ion LFP", "use_case": "Peak demand management, regenerative braking storage", "status": "Pilot deployed"},
        {"entity": "Large C&I (Infosys, TCS, Tata)", "capacity_mwh": 200, "location": "Campus facilities", "technology": "Li-ion LFP", "use_case": "Demand charge reduction, backup power", "status": "Operational"},
    ],
    "use_cases": [
        {"name": "Frequency regulation",        "share_pct": 38, "who": "POSOCO/utilities", "revenue_model": "Capacity + energy payment"},
        {"name": "Renewable energy firming",     "share_pct": 30, "who": "IPPs, SECI tenders", "revenue_model": "Bundled RE tariff"},
        {"name": "Peak demand reduction (C&I)",  "share_pct": 18, "who": "Large industrial consumers", "revenue_model": "Demand charge savings"},
        {"name": "Distribution-level deferral",  "share_pct": 8,  "who": "DISCOMs", "revenue_model": "Capex deferral value"},
        {"name": "Backup / islanding",           "share_pct": 6,  "who": "Campuses, data centres", "revenue_model": "Reliability value"},
    ]
}


# ── EV zones data by state ─────────────────────────────────────────────────────
EV_ZONES_DATA = {
    "Karnataka": {
        "discom": "BESCOM (Bengaluru) / HESCOM (Hubli) / MESCOM (Mangaluru) / CESC (Mysuru) / GESCOM (Gulbarga)",
        "ev_stations_total": 6096,
        "grid_avail_pct": 96,
        "power_context": "BESCOM territory has dedicated 220kV infrastructure feeding Bengaluru metro. NH highway corridors typically fed by 11kV/33kV feeders — transformer upgrades often needed for chargers above 60kW. 220kV available at Electronic City, Whitefield, KIADB industrial areas.",
        "corridors": [
            {"name": "NH-44 Bengaluru → Hyderabad", "distance_km": 570, "stations_existing": 14, "stations_per_100km": 2.5, "opportunity": "High", "gap_towns": ["Kolar", "Chittoor border"]},
            {"name": "NH-48 Bengaluru → Mumbai", "distance_km": 995, "stations_existing": 9, "stations_per_100km": 0.9, "opportunity": "Very High", "gap_towns": ["Chitradurga", "Davangere", "Dharwad"]},
            {"name": "NH-75 Bengaluru → Mangaluru", "distance_km": 352, "stations_existing": 6, "stations_per_100km": 1.7, "opportunity": "High", "gap_towns": ["Hassan", "Sakleshpur ghat"]},
            {"name": "NH-66 Mangaluru → Goa", "distance_km": 350, "stations_existing": 4, "stations_per_100km": 1.1, "opportunity": "High", "gap_towns": ["Udupi", "Kumta", "Karwar"]},
            {"name": "ORR / Peripheral Ring Road, Bengaluru", "distance_km": 65, "stations_existing": 48, "stations_per_100km": 73.8, "opportunity": "Low (saturating)", "gap_towns": []},
        ],
        "zones": [
            {"zone": "Whitefield", "city": "Bengaluru", "discom": "BESCOM", "opportunity_score": 9, "ev_demand": "Very High", "power_reliability": "High", "supply_voltage": "220kV nearby", "reason": "1.2M daily footfall (tech parks), low charger density relative to EV registrations, dedicated BESCOM feeder"},
            {"zone": "Electronic City", "city": "Bengaluru", "discom": "BESCOM", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "Very High", "supply_voltage": "220kV", "reason": "150k+ IT employees, planned KIADB expansion, multiple large campuses"},
            {"zone": "Tumkuru (NH-48)", "city": "Tumkuru", "discom": "BESCOM", "opportunity_score": 9, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "Industrial corridor + NH-48 gateway, zero public DC fast chargers in 80km stretch"},
            {"zone": "Mysuru City", "city": "Mysuru", "discom": "CESC", "opportunity_score": 7, "ev_demand": "Medium-High", "power_reliability": "High", "supply_voltage": "66kV", "reason": "Tourism capital, growing EV fleet, limited charging infrastructure"},
            {"zone": "Hubli-Dharwad", "city": "Hubli", "discom": "HESCOM", "opportunity_score": 7, "ev_demand": "Medium", "power_reliability": "Medium", "supply_voltage": "33kV main areas", "reason": "NH-48 node, commercial hub for North Karnataka, sparse highway coverage"},
        ]
    },
    "Maharashtra": {
        "discom": "MSEDCL (majority) / BEST (Mumbai) / TPC (Mumbai)",
        "ev_stations_total": 3200,
        "grid_avail_pct": 94,
        "power_context": "Mumbai grid is highly reliable (multiple 220kV rings). Pune and Nashik have 110kV infrastructure. Rural MSEDCL areas have load-shedding schedules — verify substation capacity before committing to highway stations.",
        "corridors": [
            {"name": "Mumbai → Pune (Expressway)", "distance_km": 165, "stations_existing": 22, "stations_per_100km": 13.3, "opportunity": "Low (densifying)", "gap_towns": []},
            {"name": "NH-48 Pune → Bengaluru", "distance_km": 840, "stations_existing": 11, "stations_per_100km": 1.3, "opportunity": "High", "gap_towns": ["Satara", "Kolhapur", "Belgaum"]},
            {"name": "NH-44 Nagpur → Hyderabad", "distance_km": 500, "stations_existing": 6, "stations_per_100km": 1.2, "opportunity": "High", "gap_towns": ["Yavatmal", "Nanded"]},
        ],
        "zones": [
            {"zone": "Hinjewadi", "city": "Pune", "discom": "MSEDCL", "opportunity_score": 9, "ev_demand": "Very High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "IT corridor, 400k+ daily commuters, growing EV fleet faster than infrastructure"},
            {"zone": "Bandra-Kurla Complex", "city": "Mumbai", "discom": "BEST/TPC", "opportunity_score": 7, "ev_demand": "Very High", "power_reliability": "Very High", "supply_voltage": "220kV", "reason": "Financial hub, premium EV users, high ₹/charge willingness-to-pay"},
            {"zone": "Nashik Industrial Area", "city": "Nashik", "discom": "MSEDCL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "Auto manufacturing cluster, fleet EV adoption, Pune highway node"},
        ]
    },
    "Tamil Nadu": {
        "discom": "TANGEDCO",
        "ev_stations_total": 2800,
        "grid_avail_pct": 91,
        "power_context": "TANGEDCO has been expanding 110kV infrastructure for EV charging. Chennai metro area has 220kV available. ToD tariff: off-peak (10pm-6am) rates significantly lower — a strong signal for overnight fleet charging.",
        "corridors": [
            {"name": "NH-44 Chennai → Bengaluru", "distance_km": 345, "stations_existing": 18, "stations_per_100km": 5.2, "opportunity": "Medium (growing)", "gap_towns": ["Vellore", "Krishnagiri"]},
            {"name": "NH-66 Chennai → Kochi (ECR/NH)", "distance_km": 700, "stations_existing": 8, "stations_per_100km": 1.1, "opportunity": "High", "gap_towns": ["Cuddalore", "Pondicherry", "Nagapattinam"]},
            {"name": "Coimbatore → Salem (NH-544)", "distance_km": 160, "stations_existing": 5, "stations_per_100km": 3.1, "opportunity": "Medium", "gap_towns": ["Erode"]},
        ],
        "zones": [
            {"zone": "OMR Tech Corridor", "city": "Chennai", "discom": "TANGEDCO", "opportunity_score": 9, "ev_demand": "Very High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "50km tech corridor, 400k IT employees, 2x EV growth YoY"},
            {"zone": "Coimbatore Industrial", "city": "Coimbatore", "discom": "TANGEDCO", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "66kV", "reason": "Textile + engineering hub, fleet EV early adopters, gateway to Kerala"},
        ]
    },
    "Delhi": {
        "discom": "BSES Rajdhani / BSES Yamuna / TPDDL",
        "ev_stations_total": 1850,
        "grid_avail_pct": 99,
        "power_context": "Delhi has India's most reliable urban grid (99% availability). BSES and TPDDL have 220kV ring throughout NCR. Delhi EV policy is aggressive — free registration, road tax waiver, 5% GST refund through state scheme.",
        "corridors": [
            {"name": "NH-44 Delhi → Chandigarh", "distance_km": 275, "stations_existing": 14, "stations_per_100km": 5.1, "opportunity": "Medium", "gap_towns": []},
            {"name": "NH-48 Delhi → Jaipur", "distance_km": 280, "stations_existing": 9, "stations_per_100km": 3.2, "opportunity": "Medium-High", "gap_towns": ["Dharuhera", "Rewari"]},
            {"name": "NH-19 Delhi → Agra (Yamuna Exp)", "distance_km": 210, "stations_existing": 8, "stations_per_100km": 3.8, "opportunity": "Medium", "gap_towns": []},
        ],
        "zones": [
            {"zone": "Cyber City / DLF", "city": "Gurugram (NCR)", "discom": "DHBVN/TPDDL", "opportunity_score": 9, "ev_demand": "Very High", "power_reliability": "Very High", "supply_voltage": "220kV", "reason": "Highest per-capita EV density in India, premium willingness-to-pay"},
            {"zone": "Noida Expressway Corridor", "city": "Noida (NCR)", "discom": "PVVNL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "IT/ITES hub, 300k+ daily commuters, adjacent to Greater Noida industrial"},
        ]
    },
    "Gujarat": {
        "discom": "DGVCL / MGVCL / PGVCL / UGVCL",
        "ev_stations_total": 2100,
        "grid_avail_pct": 95,
        "power_context": "Gujarat has India's best industrial power quality. DGVCL and PGVCL have extensive 66kV and 110kV grids. Strong solar + wind generation means off-peak ToD prices are low — attractive for fleet depot charging.",
        "corridors": [
            {"name": "NH-48 Ahmedabad → Mumbai", "distance_km": 530, "stations_existing": 16, "stations_per_100km": 3.0, "opportunity": "High", "gap_towns": ["Vadodara south", "Bharuch", "Vapi"]},
            {"name": "Ahmedabad → Surat (Expressway)", "distance_km": 265, "stations_existing": 12, "stations_per_100km": 4.5, "opportunity": "Medium-High", "gap_towns": []},
        ],
        "zones": [
            {"zone": "GIFT City", "city": "Gandhinagar", "discom": "DGVCL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "Very High", "supply_voltage": "220kV dedicated", "reason": "Smart city infrastructure, premium commercial, rapid EV adoption"},
            {"zone": "Surat Diamond Bourse / Textile", "city": "Surat", "discom": "MGVCL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "Highest per-capita income city, fleet operators, good power quality"},
        ]
    },
    "Telangana": {
        "discom": "TSSPDCL (south) / TSNPDCL (north)",
        "ev_stations_total": 1100,
        "grid_avail_pct": 94,
        "power_context": "Hyderabad metro has 220kV and 400kV infrastructure. TSSPDCL has been actively supporting EV charging through dedicated feeders in HITEC City and Gachibowli. ToD pricing available.",
        "corridors": [
            {"name": "NH-44 Hyderabad → Bengaluru", "distance_km": 570, "stations_existing": 14, "stations_per_100km": 2.5, "opportunity": "High", "gap_towns": ["Kurnool", "Anantapur"]},
            {"name": "NH-65 Hyderabad → Pune", "distance_km": 560, "stations_existing": 7, "stations_per_100km": 1.3, "opportunity": "High", "gap_towns": ["Solapur", "Nanded"]},
        ],
        "zones": [
            {"zone": "HITEC City / Gachibowli", "city": "Hyderabad", "discom": "TSSPDCL", "opportunity_score": 9, "ev_demand": "Very High", "power_reliability": "Very High", "supply_voltage": "220kV", "reason": "India's 2nd largest IT hub, EV adoption growing 80% YoY, grid well-upgraded"},
            {"zone": "Outer Ring Road Corridor", "city": "Hyderabad", "discom": "TSSPDCL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV nodes", "reason": "158km ring with multiple industrial nodes, sparse DC fast charging"},
        ]
    },
    "Rajasthan": {
        "discom": "JDVVNL (Jodhpur) / JVVNL (Jaipur)",
        "ev_stations_total": 980,
        "grid_avail_pct": 88,
        "power_context": "Rajasthan has abundant solar, but grid reliability in rural areas is lower (88%). Jaipur and Udaipur urban areas are reliable. RUVNL is actively procuring BESS to firm up solar — good long-term backdrop for combined charging+storage.",
        "corridors": [
            {"name": "NH-48 Jaipur → Delhi", "distance_km": 280, "stations_existing": 9, "stations_per_100km": 3.2, "opportunity": "High", "gap_towns": ["Rewari", "Kotputli"]},
            {"name": "NH-58 Jaipur → Agra", "distance_km": 235, "stations_existing": 5, "stations_per_100km": 2.1, "opportunity": "High", "gap_towns": ["Bharatpur"]},
        ],
        "zones": [
            {"zone": "Jaipur Pink City + Commercial", "city": "Jaipur", "discom": "JVVNL", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "Tourism + growing IT hub, state EV policy is aggressive, Delhi corridor"},
        ]
    },
    "Kerala": {
        "discom": "KSEB",
        "ev_stations_total": 780,
        "grid_avail_pct": 97,
        "power_context": "Kerala has India's second-highest grid availability (97%). KSEB infrastructure is well-maintained. High EV adoption rate due to high literacy and environmental awareness. NH-66 coastal highway is the primary EV corridor.",
        "corridors": [
            {"name": "NH-66 Thiruvananthapuram → Kochi → Kozhikode", "distance_km": 450, "stations_existing": 24, "stations_per_100km": 5.3, "opportunity": "Medium (growing)", "gap_towns": ["Thrissur-Kozhikode gap"]},
            {"name": "NH-544 Kochi → Coimbatore (Palakkad)", "distance_km": 185, "stations_existing": 6, "stations_per_100km": 3.2, "opportunity": "Medium-High", "gap_towns": ["Palakkad ghat section"]},
        ],
        "zones": [
            {"zone": "Infopark / SmartCity Kochi", "city": "Kochi", "discom": "KSEB", "opportunity_score": 8, "ev_demand": "High", "power_reliability": "Very High", "supply_voltage": "110kV", "reason": "Rapidly growing IT hub, high-income workforce, EV-friendly state policy"},
        ]
    },
    "Andhra Pradesh": {
        "discom": "APSPDCL (south) / APEPDCL (north)",
        "ev_stations_total": 1240,
        "grid_avail_pct": 93,
        "power_context": "AP has significant renewable capacity (solar, wind). Grid reliability is good in Visakhapatnam and Amaravati capital region. NH-16 coastal highway is the primary corridor connecting Chennai to Kolkata.",
        "corridors": [
            {"name": "NH-16 Chennai → Vijayawada → Vizag", "distance_km": 800, "stations_existing": 18, "stations_per_100km": 2.3, "opportunity": "High", "gap_towns": ["Ongole", "Rajahmundry", "Srikakulam"]},
        ],
        "zones": [
            {"zone": "Visakhapatnam Port / IT", "city": "Visakhapatnam", "discom": "APEPDCL", "opportunity_score": 8, "ev_demand": "Medium-High", "power_reliability": "High", "supply_voltage": "110kV", "reason": "Steel + IT hub, Navy presence, growing middle class, NH-16 node"},
        ]
    }
}


# ── Weekly policy digest ───────────────────────────────────────────────────────
WEEKLY_DIGEST = {
    "last_updated": None,
    "status": "pending_first_run",
    "articles": [],
    "error": None
}

EV_KEYWORDS  = ['electric vehicle', 'ev charging', 'fame', 'e-drive', 'battery', 'evcs', 'electric mobility', 'pm e-drive', 'charger']
BESS_KEYWORDS = ['battery storage', 'bess', 'energy storage', 'grid storage', 'battery energy', 'lithium', 'acc pli', 'acc cell']

PIB_FEEDS = {
    "MHI":  "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "MNRE": "https://pib.gov.in/RssMain.aspx?ModId=17&Lang=1&Regid=3",
    "MoP":  "https://pib.gov.in/RssMain.aspx?ModId=21&Lang=1&Regid=3",
}


def weekly_policy_update():
    global WEEKLY_DIGEST
    log.info("Running weekly policy digest update …")
    articles = []
    errors   = []

    try:
        import feedparser
        for ministry, url in PIB_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in (feed.entries or [])[:30]:
                    title   = entry.get('title',   '').lower()
                    summary = entry.get('summary', '').lower()
                    text    = title + ' ' + summary
                    is_ev   = any(kw in text for kw in EV_KEYWORDS)
                    is_bess = any(kw in text for kw in BESS_KEYWORDS)
                    if is_ev or is_bess:
                        articles.append({
                            "title":    entry.get('title', 'Untitled'),
                            "link":     entry.get('link',  ''),
                            "date":     entry.get('published', ''),
                            "category": 'bess' if is_bess else 'ev',
                            "ministry": ministry,
                        })
            except Exception as e:
                errors.append(f"{ministry}: {e}")
                log.warning("PIB feed failed for %s: %s", ministry, e)
    except ImportError:
        errors.append("feedparser not installed")

    WEEKLY_DIGEST = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "status":       "ok" if articles else ("no_matches" if not errors else "error"),
        "articles":     articles[:12],
        "error":        "; ".join(errors) if errors else None,
    }
    log.info("Weekly digest: %d articles, %d errors", len(articles), len(errors))


# Run immediately on startup + schedule every Sunday 06:00 UTC
weekly_policy_update()

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(weekly_policy_update, 'cron', day_of_week='sun', hour=6, minute=0)
    _scheduler.start()
    log.info("Weekly scheduler started — runs every Sunday 06:00 UTC")
except Exception as e:
    log.warning("APScheduler not available: %s", e)


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/grid-data")
def grid_data(force: bool = False):
    try: return _get_data(force=force)
    except Exception as exc:
        log.exception("Scrape failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

@app.get("/api/health-history")
def health_history(): return list(_health_history)

@app.get("/api/generation")
def generation(): return _get_data()["generation"]

@app.get("/api/demand")
def demand(): return _get_data()["demand"]

@app.get("/api/ncep")
def ncep(): return _get_data()["ncep"]

@app.get("/api/health")
def health_check():
    return {"status": "ok", "cache_age_seconds": round(time.time() - _cache_ts),
            "weekly_digest_status": WEEKLY_DIGEST.get("status"),
            "weekly_digest_updated": WEEKLY_DIGEST.get("last_updated")}

@app.get("/api/bess-schemes")
def bess_schemes(): return BESS_SCHEMES_DATA

@app.get("/api/ev-zones")
def ev_zones(): return {"states": list(EV_ZONES_DATA.keys())}

@app.get("/api/ev-zones/{state}")
def ev_zones_state(state: str):
    d = EV_ZONES_DATA.get(state)
    if not d: raise HTTPException(status_code=404, detail=f"No zone data for state: {state}")
    return {"state": state, **d}

@app.get("/api/weekly-digest")
def weekly_digest(): return WEEKLY_DIGEST

@app.get("/api/india-data")
def india_data():
    return {
        "states": {
            "Andhra Pradesh":    {"rate":6.20,"avail":93,"renew":42,"ev":1240, "discom":"APSPDCL / APEPDCL"},
            "Arunachal Pradesh": {"rate":4.50,"avail":78,"renew":88,"ev":45,   "discom":"APDCL"},
            "Assam":             {"rate":7.00,"avail":80,"renew":20,"ev":180,  "discom":"APDCL"},
            "Bihar":             {"rate":6.50,"avail":78,"renew":12,"ev":320,  "discom":"NBPDCL / SBPDCL"},
            "Chhattisgarh":      {"rate":5.80,"avail":87,"renew":32,"ev":280,  "discom":"CSPDCL"},
            "Goa":               {"rate":4.50,"avail":99,"renew":22,"ev":210,  "discom":"Goa Electricity Dept"},
            "Gujarat":           {"rate":6.20,"avail":95,"renew":48,"ev":2100, "discom":"DGVCL / MGVCL / PGVCL"},
            "Haryana":           {"rate":6.00,"avail":91,"renew":30,"ev":890,  "discom":"DHBVN / UHBVN"},
            "Himachal Pradesh":  {"rate":4.20,"avail":98,"renew":85,"ev":220,  "discom":"HPSEBL"},
            "Jharkhand":         {"rate":7.50,"avail":82,"renew":15,"ev":190,  "discom":"JBVNL"},
            "Karnataka":         {"rate":6.72,"avail":96,"renew":62,"ev":6096, "discom":"BESCOM / HESCOM / MESCOM"},
            "Kerala":            {"rate":5.50,"avail":97,"renew":52,"ev":780,  "discom":"KSEB"},
            "Madhya Pradesh":    {"rate":6.80,"avail":90,"renew":35,"ev":650,  "discom":"MPPKVVCL"},
            "Maharashtra":       {"rate":9.10,"avail":94,"renew":28,"ev":3200, "discom":"MSEDCL / BEST"},
            "Manipur":           {"rate":4.80,"avail":72,"renew":25,"ev":28,   "discom":"MSPDCL"},
            "Meghalaya":         {"rate":5.20,"avail":75,"renew":68,"ev":32,   "discom":"MePDCL"},
            "Mizoram":           {"rate":4.90,"avail":74,"renew":72,"ev":18,   "discom":"Power & Electricity Dept"},
            "Nagaland":          {"rate":5.50,"avail":70,"renew":60,"ev":22,   "discom":"Dept of Power"},
            "Odisha":            {"rate":6.00,"avail":89,"renew":38,"ev":420,  "discom":"TPSODL / TPCODL"},
            "Punjab":            {"rate":4.80,"avail":93,"renew":28,"ev":650,  "discom":"PSPCL"},
            "Rajasthan":         {"rate":6.50,"avail":88,"renew":55,"ev":980,  "discom":"JDVVNL / JVVNL"},
            "Sikkim":            {"rate":3.40,"avail":99,"renew":92,"ev":45,   "discom":"Energy & Power Dept"},
            "Tamil Nadu":        {"rate":5.20,"avail":91,"renew":45,"ev":2800, "discom":"TANGEDCO"},
            "Telangana":         {"rate":6.80,"avail":94,"renew":38,"ev":1100, "discom":"TSSPDCL / TSNPDCL"},
            "Tripura":           {"rate":6.20,"avail":80,"renew":18,"ev":55,   "discom":"TSECL"},
            "Uttar Pradesh":     {"rate":6.00,"avail":85,"renew":22,"ev":1200, "discom":"UPPCL"},
            "Uttarakhand":       {"rate":4.50,"avail":96,"renew":72,"ev":280,  "discom":"UPCL"},
            "West Bengal":       {"rate":8.50,"avail":92,"renew":8, "ev":890,  "discom":"WBSEDCL / CESC"},
            "Delhi":             {"rate":4.50,"avail":99,"renew":12,"ev":1850, "discom":"BSES / TPDDL"},
            "Jammu and Kashmir": {"rate":3.50,"avail":85,"renew":75,"ev":120,  "discom":"JKPDCL"},
        },
        "data_as_of": "SERC tariff orders FY 2025-26, updated July 2026"
    }

@app.get("/api/india-energy-stats")
def india_energy_stats():
    return {
        "as_of": "March 2026", "sources": ["MNRE", "CEA", "PIB"],
        "total_installed_gw": 530.5, "non_fossil_gw": 283.46, "non_fossil_pct": 53.4,
        "capacity_by_source": [
            {"source":"Coal","gw":219.61,"color":"#F87171"},
            {"source":"Gas/Lignite","gw":26.74,"color":"#FB923C"},
            {"source":"Solar","gw":150.26,"color":"#FBBF24"},
            {"source":"Wind","gw":56.09,"color":"#34D399"},
            {"source":"Large Hydro","gw":51.41,"color":"#60A5FA"},
            {"source":"Bio Energy","gw":11.75,"color":"#A78BFA"},
            {"source":"Small Hydro","gw":5.17,"color":"#93C5FD"},
            {"source":"Nuclear","gw":8.78,"color":"#F472B6"},
        ],
        "milestones": [
            {"label":"50% non-fossil capacity achieved","date":"June 2025","note":"5 years ahead of 2030 NDC target"},
            {"label":"Highest-ever RE share in generation","value":"51.5%","date":"July 29 2025"},
            {"label":"Solar crossed 100 GW","date":"January 2025"},
            {"label":"Wind crossed 50 GW","date":"March 2025"},
        ],
        "targets_2030": {"non_fossil_gw":500,"achieved_gw":283.46,"pct_complete":56.7},
        "growth_series": [
            {"year":"2014","solar":2.82,"wind":21.04,"total_re":35.0},
            {"year":"2016","solar":6.76,"wind":28.70,"total_re":46.9},
            {"year":"2018","solar":22.81,"wind":35.29,"total_re":70.0},
            {"year":"2020","solar":37.63,"wind":38.43,"total_re":88.4},
            {"year":"2022","solar":61.97,"wind":42.63,"total_re":121.8},
            {"year":"2024","solar":94.17,"wind":47.96,"total_re":203.2},
            {"year":"2026","solar":150.26,"wind":56.09,"total_re":274.7},
        ],
        "fetched_at": datetime.utcnow().isoformat() + "Z"
    }

@app.get("/api/ev-policy")
def ev_policy():
    return {
        "updated_on": "2026-07-04",
        "karnataka": {"ev_stations":6096,"ev_tariff_per_unit":6.00,"renewable_pct":62,"capital_subsidy_pct":"25–50","rank_india":1},
        "national_kpis": {"pm_edrive_outlay_cr":10900,"chargers_targeted":72300,"gst_on_ev_pct":5},
        "policies": [
            {"name":"PM E-DRIVE Scheme","status":"expiring","ministry":"MHI","outlay":"₹10,900 crore","summary":"₹3,679 Cr for vehicle subsidies (e-2W, e-3W, e-buses). ₹2,000 Cr for 72,000+ public chargers. 80% infrastructure subsidy for public locations, 100% for government premises.","tags":["MHI","Charging infra","e-buses"],"deadline":"e-2W: 31 July 2026 · e-3W: 31 March 2028"},
            {"name":"ACC PLI — Battery Cell Manufacturing","status":"active","ministry":"MHI","outlay":"₹18,100 crore","summary":"50 GWh domestic battery cell production target. ₹2,000–4,500/kWh incentive for 5 years. 100% DCR on 18 critical components.","tags":["Battery manufacturing","PLI","50 GWh"],"deadline":"Ongoing through FY 2027-28"},
            {"name":"MoP EV Charging Guidelines 2024","status":"enacted","ministry":"MoP","outlay":None,"summary":"CCS2 mandatory for 4W fast charging (50–500 kW). No licence needed to sell electricity for EV charging. Open access: any EV at any station.","tags":["CCS2 mandate","Open access","Standards"],"deadline":"Effective September 2024"},
            {"name":"PM Surya Ghar — Solar + EV","status":"active","ministry":"MNRE","outlay":"Up to ₹78,000 subsidy","summary":"Rooftop solar subsidy. Combined with net metering: near-zero cost per km for home EV charging.","tags":["Rooftop solar","Net metering","Home charging"],"deadline":"Ongoing"},
            {"name":"FAME III (proposed)","status":"upcoming","ministry":"MHI","outlay":"TBD","summary":"Successor to FAME II / PM E-DRIVE. Focus on replacing 800,000 diesel buses with electric. Private EV subsidies not included.","tags":["Electric buses","800k buses"],"deadline":"Expected FY 2026-27"},
        ],
        "fetched_at": datetime.utcnow().isoformat() + "Z"
    }


# ── BESCOM map proxy ───────────────────────────────────────────────────────────
@app.get("/api/bescom-map")
def bescom_map():
    try:
        r = _req.get("https://kptclsldc.in/data1/BESCOM.jpg", headers=_SLDC_HEADERS, timeout=12)
        r.raise_for_status()
        return Response(content=r.content, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
    except Exception as exc:
        log.warning("BESCOM map fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="BESCOM map unavailable")


# ── Frontend ───────────────────────────────────────────────────────────────────
try:
    app.mount("/static", StaticFiles(directory="."), name="static")
except Exception:
    pass

@app.get("/")
def root(): return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
