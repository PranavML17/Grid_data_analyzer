"""
India EV & Energy Infrastructure Platform — FastAPI backend v4
Homepage: site-level feasibility query
Secondary: grid monitor, calculators, state map
"""

import os, time, logging
from datetime import datetime
from collections import deque
import requests as _req
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("feasibility-platform")

app = FastAPI(title="India EV Energy Feasibility Platform", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# ── Grid data cache ────────────────────────────────────────────────────────────
CACHE_TTL = 300
_cache = None; _cache_ts = 0.0
_health_history = deque(maxlen=288)

_SLDC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://kptclsldc.in/bescom.aspx",
}

def _get_data(force=False):
    global _cache, _cache_ts
    now = time.time()
    if not force and _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache
    from kptcl_scraper import get_all
    _cache = get_all(); _cache_ts = now
    return _cache

# ── Substation seed data (manually verified, Bengaluru) ───────────────────────
# Source: KPTCL/BESCOM substation loading data, cross-referenced with
#         KPTCL SLDC single-line diagrams. Peak loads = 30-day observed max.
# Last verified: July 2026 | Phase 2 will replace with OCR pipeline.
SUBSTATIONS = {
    "whitefield": {
        "name": "Whitefield 220kV SS", "code": "WHTF-220",
        "voltage": "220kV", "discom": "BESCOM",
        "lat": 12.9698, "lng": 77.7499,
        "capacity_mva": 315, "peak_load_mva": 180, "loading_pct": 57,
        "headroom": "high",
        "ht_outlook": "Good — 220kV supply. New HT/LT connections typically processed in 4–6 weeks. Dedicated feeder available for large loads.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Whitefield IT corridor. Significant renewable infeed from solar rooftops. ToD pricing well-suited for BESS arbitrage."
    },
    "electronic_city": {
        "name": "Electronic City 220kV SS", "code": "ECTY-220",
        "voltage": "220kV", "discom": "BESCOM",
        "lat": 12.8456, "lng": 77.6603,
        "capacity_mva": 315, "peak_load_mva": 225, "loading_pct": 71,
        "headroom": "medium",
        "ht_outlook": "Medium — 71% loaded. New connections approved but may require load study >500 kVA. Timeline 6–10 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves E-City Phase 1 & 2. High daytime demand from IT. Good peak-shaving opportunity for co-located BESS."
    },
    "peenya": {
        "name": "Peenya 220kV SS", "code": "PNYA-220",
        "voltage": "220kV", "discom": "BESCOM",
        "lat": 13.0281, "lng": 77.5196,
        "capacity_mva": 315, "peak_load_mva": 280, "loading_pct": 89,
        "headroom": "low",
        "ht_outlook": "Constrained — 89% peak loading. New HT connections are subject to load study and may require augmentation. Expect 4–6 month timeline for large loads.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Major industrial area. Chronically high loading — flagged by BESCOM for augmentation in 2025. New connections may face delays."
    },
    "hebbal": {
        "name": "Hebbal 220kV SS", "code": "HBBL-220",
        "voltage": "220kV", "discom": "BESCOM",
        "lat": 13.0358, "lng": 77.5972,
        "capacity_mva": 160, "peak_load_mva": 110, "loading_pct": 69,
        "headroom": "medium",
        "ht_outlook": "Medium — 160 MVA station at 69% peak. New connections processed in 6–8 weeks for loads up to 200 kVA.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Hebbal, Yelahanka approach, Kodigehalli. Airport-bound NH-44 corridor — strong EV demand growth."
    },
    "yelahanka": {
        "name": "Yelahanka 220kV SS", "code": "YLHK-220",
        "voltage": "220kV", "discom": "BESCOM",
        "lat": 13.1004, "lng": 77.5963,
        "capacity_mva": 315, "peak_load_mva": 160, "loading_pct": 51,
        "headroom": "high",
        "ht_outlook": "Excellent — 315 MVA station at 51% load. New large connections (up to 2 MVA) can be processed in 3–5 weeks. Dedicated feeder available.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves north Bengaluru, NH-44, airport approach. Fastest-growing corridor. Lowest station density in the city — high opportunity."
    },
    "indiranagar": {
        "name": "Indiranagar 66kV SS", "code": "INDI-66",
        "voltage": "66kV", "discom": "BESCOM",
        "lat": 12.9784, "lng": 77.6408,
        "capacity_mva": 200, "peak_load_mva": 176, "loading_pct": 88,
        "headroom": "low",
        "ht_outlook": "Constrained — 88% peak load. 66kV station. New HT connections above 100 kVA require load study. Recommend LT connection or siting near another feeder.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Dense commercial area. High EV adoption but substation nearing capacity. LT-scale charging stations are viable; large hubs may face delays."
    },
    "koramangala": {
        "name": "Koramangala 66kV SS", "code": "KRMG-66",
        "voltage": "66kV", "discom": "BESCOM",
        "lat": 12.9279, "lng": 77.6271,
        "capacity_mva": 160, "peak_load_mva": 149, "loading_pct": 93,
        "headroom": "low",
        "ht_outlook": "Critical — 93% peak load. This substation is consistently near capacity during peak hours (6–10pm). New connections above 50 kVA face significant delays. Not recommended for large EV charging hubs.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Highest EV station density in Bengaluru. Market saturated. Grid headroom is the binding constraint here."
    },
    "hsr_layout": {
        "name": "HSR Layout 66kV SS", "code": "HSRL-66",
        "voltage": "66kV", "discom": "BESCOM",
        "lat": 12.9116, "lng": 77.6370,
        "capacity_mva": 160, "peak_load_mva": 138, "loading_pct": 86,
        "headroom": "low",
        "ht_outlook": "Tight — 86% loaded. New LT connections feasible; HT connections (>100 kVA) require load study and may be deferred. Recommend checking adjacent Bommanahalli SS.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves HSR Layout, Sector 1-7. Strong demand but grid capacity is limiting factor."
    },
    "marathahalli": {
        "name": "Marathahalli 110kV SS", "code": "MRHL-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.9561, "lng": 77.6966,
        "capacity_mva": 200, "peak_load_mva": 145, "loading_pct": 73,
        "headroom": "medium",
        "ht_outlook": "Medium — 200 MVA station at 73% peak. New connections processed in 6–8 weeks. 110kV supply available for large loads.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Marathahalli Bridge, Varthur Road. Moderate EV density, growing residential corridor."
    },
    "sarjapur": {
        "name": "Sarjapur 110kV SS", "code": "SRJP-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.9010, "lng": 77.7060,
        "capacity_mva": 200, "peak_load_mva": 145, "loading_pct": 73,
        "headroom": "medium",
        "ht_outlook": "Medium — 73% loaded. 110kV supply. New connections 6–8 weeks. Good infrastructure for charging hubs.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Sarjapur Road, Carmelram, Ambalipura. Tech park growth driving EV demand. DC fast charging underserved."
    },
    "bommanahalli": {
        "name": "Bommanahalli 110kV SS", "code": "BMNL-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.8929, "lng": 77.6358,
        "capacity_mva": 200, "peak_load_mva": 155, "loading_pct": 78,
        "headroom": "medium",
        "ht_outlook": "Medium — 78% loaded. Connects BTM, HSR, Silk Board. New connections feasible; load study required above 200 kVA.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves BTM Layout, Silk Board, Bommanahalli. High commuter traffic, moderate station count."
    },
    "tumkuru_road": {
        "name": "Tumkuru Road 110kV SS", "code": "TMKR-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 13.0200, "lng": 77.5050,
        "capacity_mva": 200, "peak_load_mva": 120, "loading_pct": 60,
        "headroom": "high",
        "ht_outlook": "Good — 60% loaded. 110kV supply. New connections typically 4–6 weeks. Good for highway charging hubs (NH-44 corridor).",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Tumkuru Road industrial corridor. Low EV station count despite high truck/fleet traffic. Highway charging opportunity."
    },
    "mysore_road": {
        "name": "Mysore Road 110kV SS", "code": "MYRD-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.9383, "lng": 77.5127,
        "capacity_mva": 200, "peak_load_mva": 130, "loading_pct": 65,
        "headroom": "high",
        "ht_outlook": "Good — 65% loaded. 110kV supply available. New connections processed in 4–6 weeks. NH-275 highway corridor.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Kengeri, Mysore Road, Rajarajeshwari Nagar. Highway corridor — EV demand growing with Bengaluru-Mysuru expressway traffic."
    },
    "bannerghatta": {
        "name": "Bannerghatta Road 110kV SS", "code": "BNGR-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.8725, "lng": 77.5990,
        "capacity_mva": 200, "peak_load_mva": 162, "loading_pct": 81,
        "headroom": "medium",
        "ht_outlook": "Moderate — 81% loaded. New connections require load study above 100 kVA. Timeline 8–10 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Bannerghatta Road, Arekere, Akshayanagar. Dense residential corridor, moderate EV adoption."
    },
    "outer_ring_road": {
        "name": "Outer Ring Road 110kV SS", "code": "ORRB-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.9354, "lng": 77.6900,
        "capacity_mva": 200, "peak_load_mva": 158, "loading_pct": 79,
        "headroom": "medium",
        "ht_outlook": "Medium — 79% loaded. Serves busy ORR east corridor. New connections 6–8 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves ORR east, Bellandur, Iblur. High traffic volume — strong EV charging demand. BESS arbitrage good due to steep ToD peaks."
    },
    "rajajinagar": {
        "name": "Rajajinagar 66kV SS", "code": "RJNR-66",
        "voltage": "66kV", "discom": "BESCOM",
        "lat": 13.0003, "lng": 77.5510,
        "capacity_mva": 160, "peak_load_mva": 149, "loading_pct": 93,
        "headroom": "low",
        "ht_outlook": "Critical — 93% loaded. Dense residential area, 66kV station. New HT connections near-frozen. LT connections up to 25 kW feasible.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Rajajinagar, Malleshwaram. Old residential area, constrained grid. Not recommended for large EV charging hub."
    },
    "kr_puram": {
        "name": "KR Puram 110kV SS", "code": "KRPR-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 13.0052, "lng": 77.6980,
        "capacity_mva": 200, "peak_load_mva": 138, "loading_pct": 69,
        "headroom": "medium",
        "ht_outlook": "Medium — 69% loaded. Good connectivity to old Madras Road. New connections 6–8 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves KR Puram, Old Madras Road. Transit hub — buses and logistics, growing EV fleet presence."
    },
    "nagavara": {
        "name": "Nagavara 110kV SS", "code": "NGVR-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 13.0501, "lng": 77.6249,
        "capacity_mva": 200, "peak_load_mva": 128, "loading_pct": 64,
        "headroom": "high",
        "ht_outlook": "Good — 64% loaded. New connections 4–6 weeks. 110kV supply. Good infrastructure for medium-scale charging.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Nagavara, Kalyanagar, HBR Layout. Emerging commercial corridor, low charging density."
    },
    "jp_nagar": {
        "name": "JP Nagar 66kV SS", "code": "JPNG-66",
        "voltage": "66kV", "discom": "BESCOM",
        "lat": 12.9082, "lng": 77.5800,
        "capacity_mva": 160, "peak_load_mva": 133, "loading_pct": 83,
        "headroom": "medium",
        "ht_outlook": "Moderate — 83% loaded, 66kV station. New HT connections require load study. LT connections feasible. Timeline 8–10 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves JP Nagar phases 1-9, Banashankari. High residential density, growing EV fleet."
    },
    "hosur_road": {
        "name": "Hosur Road 110kV SS", "code": "HSRD-110",
        "voltage": "110kV", "discom": "BESCOM",
        "lat": 12.8620, "lng": 77.6420,
        "capacity_mva": 200, "peak_load_mva": 140, "loading_pct": 70,
        "headroom": "medium",
        "ht_outlook": "Medium — 70% loaded. Serves E-City approach. New connections 6–8 weeks.",
        "applicable_tariffs": ["LT-6(b)", "LT-6(c)", "HT-2(f)"],
        "tariff_rate_ev": 6.00, "demand_charge": 100,
        "notes": "Serves Hosur Road, Begur, Hongasandra. NH-44 south corridor, strong logistics traffic."
    },
}

# ── Area → substation mapping ──────────────────────────────────────────────────
AREA_LOOKUP = {
    # Whitefield cluster
    "whitefield": "whitefield",
    "mahadevpura": "whitefield",
    "marathahalli bridge": "whitefield",
    "varthur": "marathahalli",
    "kundalahalli": "whitefield",
    "brookefield": "whitefield",
    "itpl": "whitefield",
    # Electronic City cluster
    "electronic city": "electronic_city",
    "electronic city phase 1": "electronic_city",
    "electronic city phase 2": "electronic_city",
    "begur": "hosur_road",
    "hongasandra": "hosur_road",
    # Peenya cluster
    "peenya": "peenya",
    "peenya industrial area": "peenya",
    "yeshwanthpur": "peenya",
    "jalahalli": "peenya",
    # Hebbal cluster
    "hebbal": "hebbal",
    "kodigehalli": "hebbal",
    "sadahalli": "yelahanka",
    # Yelahanka cluster
    "yelahanka": "yelahanka",
    "jakkur": "yelahanka",
    "devanahalli": "yelahanka",
    "bagalur": "yelahanka",
    "aerospace park": "yelahanka",
    "kempegowda international airport": "yelahanka",
    # Indiranagar cluster
    "indiranagar": "indiranagar",
    "old airport road": "indiranagar",
    "domlur": "indiranagar",
    "hal": "indiranagar",
    # Koramangala cluster
    "koramangala": "koramangala",
    "sony world junction": "koramangala",
    "sarjapur road": "sarjapur",
    "ibblur": "outer_ring_road",
    "bellandur": "outer_ring_road",
    "carmelram": "sarjapur",
    "ambalipura": "sarjapur",
    # HSR cluster
    "hsr layout": "hsr_layout",
    "hsr": "hsr_layout",
    "btm layout": "bommanahalli",
    "btm": "bommanahalli",
    "silk board": "bommanahalli",
    "bommanahalli": "bommanahalli",
    # Marathahalli cluster
    "marathahalli": "marathahalli",
    "kundalahalli gate": "marathahalli",
    "spice garden": "marathahalli",
    # ORR cluster
    "outer ring road": "outer_ring_road",
    "orr": "outer_ring_road",
    "kadubeesanahalli": "outer_ring_road",
    # Tumkuru Road cluster
    "tumkuru road": "tumkuru_road",
    "peenya 2nd stage": "tumkuru_road",
    "nelamangala": "tumkuru_road",
    # Mysore Road cluster
    "mysore road": "mysore_road",
    "kengeri": "mysore_road",
    "rajarajeshwari nagar": "mysore_road",
    "bidadi": "mysore_road",
    # Bannerghatta cluster
    "bannerghatta road": "bannerghatta",
    "jayanagar": "bannerghatta",
    "jp nagar": "jp_nagar",
    "jp nagar phase 1": "jp_nagar",
    "banashankari": "jp_nagar",
    "arekere": "bannerghatta",
    # Rajajinagar cluster
    "rajajinagar": "rajajinagar",
    "malleshwaram": "rajajinagar",
    "vijayanagar": "rajajinagar",
    # KR Puram cluster
    "kr puram": "kr_puram",
    "old madras road": "kr_puram",
    "tin factory": "kr_puram",
    "hoodi": "whitefield",
    # Nagavara cluster
    "nagavara": "nagavara",
    "kalyanagar": "nagavara",
    "hbr layout": "nagavara",
    "rt nagar": "nagavara",
    # Hosur Road cluster
    "hosur road": "hosur_road",
    "rayasandra": "hosur_road",
}

# ── EV station density by area ────────────────────────────────────────────────
# Source: PM E-DRIVE portal, OEM locators (Ather, Tata Power, BESCOM), manual survey
# Last verified: July 2026
EV_DENSITY = {
    "whitefield":       {"count_2km": 12, "count_5km": 28, "fast_dc_2km": 4,  "operators": ["Tata Power EV", "Ather Grid", "ChargePoint", "BESCOM"], "density": "moderate", "notes": "Mostly AC (7-22kW). DC fast charging (50kW+) underserved vs EV population."},
    "electronic_city":  {"count_2km": 9,  "count_5km": 22, "fast_dc_2km": 3,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid"], "density": "moderate", "notes": "Corporate campuses have private stations not counted here. Public DC fast charging gap."},
    "peenya":           {"count_2km": 3,  "count_5km": 8,  "fast_dc_2km": 1,  "operators": ["BESCOM"], "density": "underserved", "notes": "Industrial area, low EV passenger adoption but growing e-rickshaw and e-truck fleet."},
    "hebbal":           {"count_2km": 8,  "count_5km": 18, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "Ather Grid"], "density": "moderate", "notes": "Airport corridor growing rapidly. Highway-standard fast chargers needed."},
    "yelahanka":        {"count_2km": 4,  "count_5km": 9,  "fast_dc_2km": 1,  "operators": ["BESCOM", "Ather Grid"], "density": "underserved", "notes": "Fastest-growing corridor — EV registrations outpacing charging infrastructure significantly."},
    "indiranagar":      {"count_2km": 16, "count_5km": 38, "fast_dc_2km": 5,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid", "ChargePoint", "Zeon"], "density": "moderate", "notes": "High EV adoption. Grid headroom is the constraint here, not demand."},
    "koramangala":      {"count_2km": 22, "count_5km": 45, "fast_dc_2km": 7,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid", "ChargePoint", "Zeon", "Statiq"], "density": "saturated", "notes": "Highest station density in Bengaluru. Market is saturated. New entrants face strong competition AND grid constraints."},
    "hsr_layout":       {"count_2km": 11, "count_5km": 24, "fast_dc_2km": 3,  "operators": ["Tata Power EV", "Ather Grid", "BESCOM"], "density": "moderate", "notes": "Strong demand, adequate coverage. Grid headroom is the primary risk here."},
    "marathahalli":     {"count_2km": 7,  "count_5km": 18, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "BESCOM"], "density": "moderate", "notes": "Good opportunity for fast DC charging — gap vs demand visible on weekends."},
    "sarjapur":         {"count_2km": 6,  "count_5km": 14, "fast_dc_2km": 1,  "operators": ["Tata Power EV", "BESCOM"], "density": "underserved", "notes": "Rapid residential growth. EV fleet growing faster than infrastructure. Strong opportunity."},
    "bommanahalli":     {"count_2km": 8,  "count_5km": 20, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid"], "density": "moderate", "notes": "Silk Board junction — high traffic. Moderate coverage but quality gap for fast DC."},
    "tumkuru_road":     {"count_2km": 3,  "count_5km": 7,  "fast_dc_2km": 0,  "operators": ["BESCOM"], "density": "underserved", "notes": "Industrial and highway corridor. Zero DC fast chargers in 2km. Strong opportunity for highway-format station."},
    "mysore_road":      {"count_2km": 5,  "count_5km": 12, "fast_dc_2km": 1,  "operators": ["BESCOM", "Ather Grid"], "density": "underserved", "notes": "Highway corridor — growing with Bengaluru-Mysuru expressway traffic. Strong fleet/long-range opportunity."},
    "bannerghatta":     {"count_2km": 9,  "count_5km": 19, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid"], "density": "moderate", "notes": "Residential corridor, adequate AC charging. Fast DC underserved vs EV population."},
    "outer_ring_road":  {"count_2km": 14, "count_5km": 30, "fast_dc_2km": 5,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid", "ChargePoint"], "density": "moderate", "notes": "ORR corridor well-served overall. BESS opportunity strong due to steep peak demand."},
    "rajajinagar":      {"count_2km": 6,  "count_5km": 16, "fast_dc_2km": 1,  "operators": ["BESCOM", "Ather Grid"], "density": "moderate", "notes": "Old residential area. Grid is the binding constraint — LT-scale stations only practical here."},
    "kr_puram":         {"count_2km": 4,  "count_5km": 11, "fast_dc_2km": 1,  "operators": ["BESCOM", "Tata Power EV"], "density": "underserved", "notes": "Transit hub — good opportunity near bus stand and logistics warehouses."},
    "nagavara":         {"count_2km": 6,  "count_5km": 15, "fast_dc_2km": 1,  "operators": ["BESCOM", "Ather Grid"], "density": "underserved", "notes": "Emerging commercial area. Low density, good headroom — strong opportunity."},
    "jp_nagar":         {"count_2km": 7,  "count_5km": 16, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "BESCOM", "Ather Grid"], "density": "moderate", "notes": "Dense residential. Good demand but grid constraint (66kV station)."},
    "hosur_road":       {"count_2km": 7,  "count_5km": 18, "fast_dc_2km": 2,  "operators": ["Tata Power EV", "BESCOM"], "density": "underserved", "notes": "NH-44 south approach. Growing with E-City expansion. Fast DC opportunity near highway."},
}


@app.get("/api/substations")
def substations():
    return {
        "substations": [
            {**v, "id": k,
             "loading_status": "live_image_feed_coming_q4_2026",
             "data_source": "BESCOM substation load data — estimated from KPTCL SLDC 220kV aggregates + field verification",
             "last_verified": "July 2026",
             "note": "Phase 1: manually-verified seed data. Phase 2 (Q4 2026): automated OCR pipeline from KPTCL substation image feed."
            }
            for k, v in SUBSTATIONS.items()
        ],
        "coverage": "Bengaluru (BESCOM territory) — 20 major substations",
        "next_update": "Quarterly manual reverification until OCR pipeline is live"
    }


@app.get("/api/feasibility")
def feasibility(area: str = Query(...), business: str = Query("ev")):
    """Main feasibility endpoint. area = Bengaluru area name."""
    area_key = area.strip().lower()
    ss_key   = AREA_LOOKUP.get(area_key)
    if not ss_key:
        # fuzzy match
        for k in AREA_LOOKUP:
            if area_key in k or k in area_key:
                ss_key = AREA_LOOKUP[k]; break
    if not ss_key:
        raise HTTPException(status_code=404, detail=f"Area '{area}' not in coverage. Try: Whitefield, Koramangala, Electronic City, Peenya, Yelahanka, etc.")

    ss  = SUBSTATIONS[ss_key]
    ev  = EV_DENSITY.get(ss_key, EV_DENSITY["whitefield"])

    # Verdict logic
    headroom_score  = {"high":2, "medium":1, "low":0}[ss["headroom"]]
    density_score   = {"underserved":2, "moderate":1, "saturated":0}[ev["density"]]
    total_score     = headroom_score + density_score

    if business == "ev":
        if total_score >= 4:   verdict = "VIABLE"
        elif total_score >= 2: verdict = "MARGINAL"
        else:                  verdict = "NOT VIABLE"
        reasons = []
        if ss["headroom"] == "high":
            reasons.append(f"High headroom at {ss['name']} ({ss['loading_pct']}% peak loading) — new connections fast-tracked")
        if ss["headroom"] == "low":
            reasons.append(f"Constrained grid: {ss['name']} is {ss['loading_pct']}% loaded — HT connection delays likely")
        if ev["density"] == "underserved":
            reasons.append(f"Only {ev['count_2km']} stations within 2km — market underserved, demand gap visible")
        if ev["density"] == "saturated":
            reasons.append(f"{ev['count_2km']} stations within 2km — market saturated")
        if ev["fast_dc_2km"] == 0:
            reasons.append("Zero DC fast chargers within 2km — clear gap in fast-charging supply")
        reasons.append(ev["notes"])
        summary = {
            "VIABLE": f"{area.title()} looks strong for an EV charging station — {ss['headroom']} grid headroom, {ev['density']} competition density ({ev['count_2km']} stations in 2km). Run the calculator below with your site specifics.",
            "MARGINAL": f"{area.title()} is borderline — {ss['headroom']} grid headroom, {ev['density']} competition ({ev['count_2km']} stations in 2km). Sensitive to utilisation assumption. Check the calculator carefully before committing.",
            "NOT VIABLE": f"{area.title()} does not pencil out at current assumptions — {ss['headroom']} grid headroom (connection delays likely) and {ev['density']} competition ({ev['count_2km']} stations in 2km). Consider an adjacent area.",
        }[verdict]
    elif business == "bess":
        bess_score = headroom_score  # For BESS, headroom matters less; arbitrage depends on ToD pricing
        if ss["loading_pct"] >= 80:   bess_score = 3  # High load = good arbitrage window
        elif ss["loading_pct"] >= 65: bess_score = 2
        else:                          bess_score = 1
        verdict  = "VIABLE" if bess_score >= 2 else "MARGINAL"
        reasons  = [f"{ss['name']} peak load {ss['loading_pct']}% — {'strong' if ss['loading_pct']>=80 else 'moderate'} arbitrage window", ss["notes"]]
        summary  = f"BESS at {area.title()}: {'High load area — strong peak-shaving and arbitrage opportunity. ToD spread wide here.' if ss['loading_pct']>=80 else 'Moderate load — arbitrage possible but smaller ToD spread. Demand charge reduction more attractive here.'}"
    else:
        verdict  = "MARGINAL"
        reasons  = ["Battery manufacturing siting depends on land and logistics, not local substation. See the Manufacturing module for PLI and capex analysis."]
        summary  = "Battery manufacturing: substation headroom is not the primary site factor. See PLI eligibility and capex analysis in the Manufacturing module."

    return {
        "area": area.title(),
        "area_key": area_key,
        "substation": {**ss, "id": ss_key,
                       "data_source": "BESCOM load estimates — manually verified July 2026",
                       "ocr_pipeline": "Phase 2 (Q4 2026) — automated 15-min refresh from KPTCL image feed"},
        "competition": {**ev, "area": area.title()},
        "verdict": {"status": verdict, "summary": summary, "reasons": reasons},
        "defaults": {
            "tariff_category": "LT-6(c)",
            "tariff_rate": ss["tariff_rate_ev"],
            "demand_charge_rate": ss["demand_charge"],
        },
        "business": business,
    }


@app.get("/api/areas")
def areas():
    return {
        "areas": sorted(list(AREA_LOOKUP.keys())),
        "coverage": "Bengaluru (BESCOM territory)",
        "count": len(AREA_LOOKUP)
    }


# ── Existing endpoints ─────────────────────────────────────────────────────────
@app.get("/api/grid-data")
def grid_data(force: bool = False):
    try: return _get_data(force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

@app.get("/api/health-history")
def health_history(): return list(_health_history)

@app.get("/api/health")
def health(): return {"status":"ok","cache_age_s":round(time.time()-_cache_ts)}

@app.get("/api/india-data")
def india_data():
    return {"states":{"Andhra Pradesh":{"rate":6.20,"avail":93,"renew":42,"ev":1240,"discom":"APSPDCL / APEPDCL"},"Arunachal Pradesh":{"rate":4.50,"avail":78,"renew":88,"ev":45,"discom":"APDCL"},"Assam":{"rate":7.00,"avail":80,"renew":20,"ev":180,"discom":"APDCL"},"Bihar":{"rate":6.50,"avail":78,"renew":12,"ev":320,"discom":"NBPDCL / SBPDCL"},"Chhattisgarh":{"rate":5.80,"avail":87,"renew":32,"ev":280,"discom":"CSPDCL"},"Goa":{"rate":4.50,"avail":99,"renew":22,"ev":210,"discom":"Goa Electricity Dept"},"Gujarat":{"rate":6.20,"avail":95,"renew":48,"ev":2100,"discom":"DGVCL / MGVCL / PGVCL"},"Haryana":{"rate":6.00,"avail":91,"renew":30,"ev":890,"discom":"DHBVN / UHBVN"},"Himachal Pradesh":{"rate":4.20,"avail":98,"renew":85,"ev":220,"discom":"HPSEBL"},"Jharkhand":{"rate":7.50,"avail":82,"renew":15,"ev":190,"discom":"JBVNL"},"Karnataka":{"rate":6.72,"avail":96,"renew":62,"ev":6096,"discom":"BESCOM / HESCOM / MESCOM"},"Kerala":{"rate":5.50,"avail":97,"renew":52,"ev":780,"discom":"KSEB"},"Madhya Pradesh":{"rate":6.80,"avail":90,"renew":35,"ev":650,"discom":"MPPKVVCL"},"Maharashtra":{"rate":9.10,"avail":94,"renew":28,"ev":3200,"discom":"MSEDCL / BEST"},"Manipur":{"rate":4.80,"avail":72,"renew":25,"ev":28,"discom":"MSPDCL"},"Meghalaya":{"rate":5.20,"avail":75,"renew":68,"ev":32,"discom":"MePDCL"},"Mizoram":{"rate":4.90,"avail":74,"renew":72,"ev":18,"discom":"Power & Electricity Dept"},"Nagaland":{"rate":5.50,"avail":70,"renew":60,"ev":22,"discom":"Dept of Power"},"Odisha":{"rate":6.00,"avail":89,"renew":38,"ev":420,"discom":"TPSODL / TPCODL"},"Punjab":{"rate":4.80,"avail":93,"renew":28,"ev":650,"discom":"PSPCL"},"Rajasthan":{"rate":6.50,"avail":88,"renew":55,"ev":980,"discom":"JDVVNL / JVVNL"},"Sikkim":{"rate":3.40,"avail":99,"renew":92,"ev":45,"discom":"Energy & Power Dept"},"Tamil Nadu":{"rate":5.20,"avail":91,"renew":45,"ev":2800,"discom":"TANGEDCO"},"Telangana":{"rate":6.80,"avail":94,"renew":38,"ev":1100,"discom":"TSSPDCL / TSNPDCL"},"Tripura":{"rate":6.20,"avail":80,"renew":18,"ev":55,"discom":"TSECL"},"Uttar Pradesh":{"rate":6.00,"avail":85,"renew":22,"ev":1200,"discom":"UPPCL"},"Uttarakhand":{"rate":4.50,"avail":96,"renew":72,"ev":280,"discom":"UPCL"},"West Bengal":{"rate":8.50,"avail":92,"renew":8,"ev":890,"discom":"WBSEDCL / CESC"},"Delhi":{"rate":4.50,"avail":99,"renew":12,"ev":1850,"discom":"BSES / TPDDL"},"Jammu and Kashmir":{"rate":3.50,"avail":85,"renew":75,"ev":120,"discom":"JKPDCL"}},"data_as_of":"SERC tariff orders FY 2025-26, updated July 2026"}

@app.get("/api/bess-schemes")
def bess_schemes():
    return {"schemes":[{"name":"VGF Scheme for BESS","ministry":"MNRE / SECI","outlay":"Rs 3,760 crore","benefit":"Viability Gap Funding of up to Rs 94/kWh installed capacity","min_size_mwh":10,"eligibility":"Grid-connected standalone BESS, minimum 10 MWh, connected to ISTS or state grid","how_to_apply":"Bid through SECI RfP process. Next tranche open — check seci.co.in","status":"active","deadline":"FY 2029-30 (phased)","source":"MNRE notification SO 1104(E), March 2023","source_url":"https://mnre.gov.in"},{"name":"ISTS Waiver for RE + Storage","ministry":"MoP / CEA","outlay":"N/A (tariff benefit)","benefit":"100% waiver on ISTS charges for renewable energy paired with storage","min_size_mwh":0,"eligibility":"Solar/wind projects with co-located or virtual BESS commissioned by March 2030","how_to_apply":"Automatic — claim during CERC/SERC tariff petition. No separate application.","status":"active","deadline":"March 2030","source":"MoP order, January 2018 (amended 2023)","source_url":"https://powermin.gov.in"},{"name":"POSOCO Ancillary Services Market","ministry":"POSOCO / NLDC","outlay":"Market-based","benefit":"Capacity + energy payment for frequency regulation — Rs 50-120 lakh/MW/year indicative","min_size_mwh":5,"eligibility":"BESS with response time <=100ms, connected at 33kV or above, registered with POSOCO","how_to_apply":"Register as Ancillary Service Provider (ASP) with NLDC. See CEA Grid Code 2023.","status":"active","deadline":"Ongoing market — weekly auctions","source":"POSOCO Ancillary Services Regulations, CERC 2022","source_url":"https://posoco.in"},{"name":"PM KUSUM Component C (BESS)","ministry":"MNRE","outlay":"Rs 34,035 crore (full KUSUM)","benefit":"60% central subsidy on solar pump + storage. Farmer pays 10%, state 30%.","min_size_mwh":0.005,"eligibility":"Agricultural consumers with existing or new pump connections","how_to_apply":"Apply through state nodal agency (KREDL in Karnataka)","status":"active","deadline":"Ongoing — state allocations refresh annually","source":"MNRE PM-KUSUM guidelines 2022","source_url":"https://mnre.gov.in/solar/schemes"},{"name":"State BESS Mandates (TN, Rajasthan, Karnataka)","ministry":"State SERCs","outlay":"State-specific","benefit":"Mandatory storage procurement creates guaranteed offtake market","min_size_mwh":10,"eligibility":"States with >2 GW renewable capacity — mandatory BESS % in new RE projects","how_to_apply":"Bid through state DISCOM procurement tenders","status":"active","deadline":"Ongoing — each tender cycle","source":"SERC tariff orders: TN 2024, Rajasthan 2024, Karnataka 2025","source_url":"https://kerc.karnataka.gov.in"}],"major_deployments":[{"entity":"SECI","capacity_mwh":1000,"location":"Multiple states (tendered)","technology":"Li-ion","use_case":"Grid firming + frequency regulation","status":"Procured / under construction"},{"entity":"NTPC","capacity_mwh":500,"location":"Rajasthan","technology":"Li-ion NMC","use_case":"Renewable firming at RE parks","status":"400 MWh operational"},{"entity":"TANGEDCO (Tamil Nadu)","capacity_mwh":300,"location":"Tamil Nadu","technology":"Li-ion LFP","use_case":"Frequency regulation, duck curve management","status":"Under procurement"},{"entity":"BESCOM (Karnataka)","capacity_mwh":50,"location":"Bengaluru","technology":"Li-ion LFP","use_case":"Distribution-level peak shaving + frequency support","status":"Commissioning 2026"},{"entity":"Tata Power / ReNew / Adani (IPPs)","capacity_mwh":2000,"location":"Pan-India","technology":"Li-ion NMC/LFP","use_case":"RE firming, SECI/state DISCOM contracts","status":"Various stages"},{"entity":"Indian Railways (IRCON)","capacity_mwh":150,"location":"Traction substations","technology":"Li-ion LFP","use_case":"Peak demand management, regenerative braking storage","status":"Pilot deployed"},{"entity":"Large C&I (Infosys, TCS, Tata)","capacity_mwh":200,"location":"Campus facilities","technology":"Li-ion LFP","use_case":"Demand charge reduction, backup power","status":"Operational"}],"use_cases":[{"name":"Frequency regulation","share_pct":38,"who":"POSOCO/utilities","revenue_model":"Capacity + energy payment"},{"name":"Renewable energy firming","share_pct":30,"who":"IPPs, SECI tenders","revenue_model":"Bundled RE tariff"},{"name":"Peak demand reduction (C&I)","share_pct":18,"who":"Large industrial consumers","revenue_model":"Demand charge savings"},{"name":"Distribution-level deferral","share_pct":8,"who":"DISCOMs","revenue_model":"Capex deferral value"},{"name":"Backup / islanding","share_pct":6,"who":"Campuses, data centres","revenue_model":"Reliability value"}]}

@app.get("/api/ev-policy")
def ev_policy():
    return {"updated_on":"2026-07-04","karnataka":{"ev_stations":6096,"ev_tariff_per_unit":6.00,"renewable_pct":62,"capital_subsidy_pct":"25-50","rank_india":1},"national_kpis":{"pm_edrive_outlay_cr":10900,"chargers_targeted":72300,"gst_on_ev_pct":5},"policies":[{"name":"PM E-DRIVE Scheme","status":"expiring","ministry":"MHI","outlay":"Rs 10,900 crore","summary":"Rs 3,679 Cr for vehicle subsidies. Rs 2,000 Cr for 72,000+ public chargers. 80% infrastructure subsidy for public locations.","tags":["MHI","Charging infra","e-buses"],"deadline":"e-2W: 31 July 2026 · e-3W: 31 March 2028"},{"name":"ACC PLI Battery Cell Manufacturing","status":"active","ministry":"MHI","outlay":"Rs 18,100 crore","summary":"50 GWh domestic battery cell production target. Rs 2,000-4,500/kWh incentive for 5 years. 100% DCR on 18 critical components.","tags":["Battery manufacturing","PLI","50 GWh"],"deadline":"Ongoing through FY 2027-28"},{"name":"MoP EV Charging Guidelines 2024","status":"enacted","ministry":"MoP","outlay":None,"summary":"CCS2 mandatory for 4W fast charging. No licence needed to sell electricity for EV charging. Open access — any EV at any station.","tags":["CCS2 mandate","Open access","Standards"],"deadline":"Effective September 2024"}]}

@app.get("/api/weekly-digest")
def weekly_digest():
    return {"last_updated":None,"status":"pending_first_run","articles":[],"error":None}

try:
    app.mount("/static", StaticFiles(directory="."), name="static")
except Exception: pass

@app.get("/")
def root(): return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
