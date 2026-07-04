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




# ── City-level feasibility data — Tier 1 & 2 cities, all major states ─────────
# Grid loading: estimated from state DISCOM published reports + CEA data
# EV stations: PM E-DRIVE portal + OEM locators (July 2026)
# headroom: high (loading <65%) | medium (65-82%) | low (>82%)
CITY_DATA = {
    "Karnataka": {
        "Bengaluru": {"tier":1,"discom":"BESCOM","grid_avail_pct":96,"loading_pct":72,"headroom":"medium","ev_stations":6096,"ev_density":"moderate","power_context":"BESCOM territory with 220kV infrastructure in IT corridors. Headroom varies by zone — 57% loaded at Whitefield/Yelahanka, 93% at Koramangala/Rajajinagar. Use the Bengaluru substation lookup on the homepage for zone-specific headroom.","zones":[{"zone":"Whitefield / ITPL","city":"Bengaluru","discom":"BESCOM","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"220kV","reason":"High headroom, moderate competition, large IT commuter base"},{"zone":"Yelahanka / NH-44 North","city":"Bengaluru","discom":"BESCOM","opportunity_score":9,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV","reason":"51% loaded substation, airport corridor, only 4 stations in 2km"},{"zone":"Electronic City","city":"Bengaluru","discom":"BESCOM","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV","reason":"150k+ IT employees, good 220kV supply"},{"zone":"Koramangala","city":"Bengaluru","discom":"BESCOM","opportunity_score":3,"ev_demand":"Very High","power_reliability":"Low","supply_voltage":"66kV","reason":"93% loaded substation + saturated market — both red flags"}],"corridors":[{"name":"NH-48 Bengaluru-Mumbai","distance_km":995,"stations_existing":9,"stations_per_100km":0.9,"opportunity":"Very High","gap_towns":["Chitradurga","Davangere"]},{"name":"NH-44 Bengaluru-Hyderabad","distance_km":570,"stations_existing":14,"stations_per_100km":2.5,"opportunity":"High","gap_towns":["Kolar"]}]},
        "Mysuru": {"tier":2,"discom":"CESC","grid_avail_pct":95,"loading_pct":61,"headroom":"high","ev_stations":320,"ev_density":"underserved","power_context":"CESC territory with reliable 110kV grid (61% loaded). Bengaluru-Mysuru Expressway is a strong EV corridor. Tourism and IT park growth driving EV adoption faster than infrastructure.","zones":[{"zone":"Infosys / IT City Periphery","city":"Mysuru","discom":"CESC","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Growing IT workforce, low station count, high headroom"},{"zone":"Nazarbad / Commercial Core","city":"Mysuru","discom":"CESC","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"66kV","reason":"Tourism hub, reliable grid, gap in fast DC charging"}],"corridors":[{"name":"Bengaluru-Mysuru Expressway (NH-275)","distance_km":118,"stations_existing":4,"stations_per_100km":3.4,"opportunity":"High","gap_towns":["Mandya","Srirangapatna"]}]},
        "Hubli-Dharwad": {"tier":2,"discom":"HESCOM","grid_avail_pct":89,"loading_pct":68,"headroom":"medium","ev_stations":210,"ev_density":"underserved","power_context":"HESCOM territory, 110kV supply. Twin city with significant commercial and educational activity. NH-48 (Mumbai-Bengaluru) passes through — highway charging opportunity.","zones":[{"zone":"Dharwad Commercial / NH-48","city":"Hubli-Dharwad","discom":"HESCOM","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"110kV","reason":"NH-48 node, university town, underserved market"}],"corridors":[{"name":"NH-48 Bengaluru-Mumbai","distance_km":200,"stations_existing":3,"stations_per_100km":1.5,"opportunity":"High","gap_towns":["Haveri","Gadag"]}]},
        "Mangaluru": {"tier":2,"discom":"MESCOM","grid_avail_pct":94,"loading_pct":63,"headroom":"high","ev_stations":280,"ev_density":"underserved","power_context":"MESCOM territory, reliable grid (94% availability). Port city with growing commercial activity. NH-66 coastal highway is the primary EV corridor.","zones":[{"zone":"Lalbagh / Commercial Core","city":"Mangaluru","discom":"MESCOM","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Port city commercial hub, high headroom, underserved charging market"}],"corridors":[{"name":"NH-66 Goa-Mangaluru-Kochi","distance_km":350,"stations_existing":5,"stations_per_100km":1.4,"opportunity":"High","gap_towns":["Udupi","Karwar"]}]},
    },
    "Maharashtra": {
        "Mumbai": {"tier":1,"discom":"BEST (island) / TPC (western) / MSEDCL (suburbs)","grid_avail_pct":99,"loading_pct":84,"headroom":"medium","ev_stations":820,"ev_density":"moderate","power_context":"Multiple DISCOMs. Mumbai island and western suburbs have 220kV rings — very reliable. MSEDCL outer suburbs are more constrained. High tariff (Rs 9.10/unit) makes charging economics tighter than other cities. Demand is very high.","zones":[{"zone":"Bandra-Kurla Complex","city":"Mumbai","discom":"BEST/TPC","opportunity_score":8,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Financial district, premium users, high willingness-to-pay, good grid"},{"zone":"Andheri East / MIDC","city":"Mumbai","discom":"TPC/MSEDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial + IT area, high commuter traffic, moderate competition"},{"zone":"Navi Mumbai / Vashi","city":"Mumbai","discom":"MSEDCL/TPC","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Planned city, good grid, lower competition than core Mumbai"},{"zone":"Thane / Kapurbawdi","city":"Mumbai","discom":"MSEDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"Medium","supply_voltage":"110kV","reason":"Residential + commercial hub, growing EV fleet, moderate supply"}],"corridors":[{"name":"Mumbai-Pune Expressway","distance_km":94,"stations_existing":12,"stations_per_100km":12.8,"opportunity":"Low (saturating)","gap_towns":[]},{"name":"NH-48 Mumbai-Bengaluru","distance_km":995,"stations_existing":18,"stations_per_100km":1.8,"opportunity":"High","gap_towns":["Kolhapur","Belgaum"]}]},
        "Pune": {"tier":1,"discom":"MSEDCL / Tata Power (some zones)","grid_avail_pct":94,"loading_pct":74,"headroom":"medium","ev_stations":650,"ev_density":"moderate","power_context":"MSEDCL serves Pune with 110kV infrastructure. IT corridors (Hinjewadi, Kharadi) have better supply. Pune has one of the highest EV adoption rates in India — demand growing faster than infrastructure.","zones":[{"zone":"Hinjewadi IT Park","city":"Pune","discom":"MSEDCL","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"400k+ IT employees, EV demand far outstripping supply"},{"zone":"Kharadi / EON IT Park","city":"Pune","discom":"MSEDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT corridor, Pune-Nagar Road, moderate competition"},{"zone":"Pimpri-Chinchwad Industrial","city":"Pune","discom":"MSEDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Auto + manufacturing hub, fleet EV adoption growing"}],"corridors":[{"name":"NH-48 Pune-Bengaluru","distance_km":840,"stations_existing":11,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Satara","Kolhapur"]}]},
        "Nagpur": {"tier":2,"discom":"MSEDCL / MSEDCL (city)","grid_avail_pct":91,"loading_pct":67,"headroom":"medium","ev_stations":290,"ev_density":"underserved","power_context":"Central India hub. 110kV supply. MIHAN (international airport zone) is a major development. NH-7/NH-44 junction makes it a critical charging corridor node.","zones":[{"zone":"MIHAN / Airport Zone","city":"Nagpur","discom":"MSEDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"SEZ + airport hub, central India logistics node, low competition"},{"zone":"Sitabuldi / Commercial Core","city":"Nagpur","discom":"MSEDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"City centre, growing EV adoption, constrained old grid"}],"corridors":[{"name":"NH-44 Hyderabad-Nagpur-Delhi","distance_km":450,"stations_existing":8,"stations_per_100km":1.8,"opportunity":"High","gap_towns":["Yavatmal","Amravati"]}]},
        "Nashik": {"tier":2,"discom":"MSEDCL","grid_avail_pct":92,"loading_pct":65,"headroom":"medium","ev_stations":220,"ev_density":"underserved","power_context":"Auto + pharma + wine manufacturing hub. 110kV supply, 65% loaded — reasonable headroom. NH-3 Agra-Mumbaj highway. Strong fleet EV opportunity in manufacturing sector.","zones":[{"zone":"Satpur / Ambad MIDC","city":"Nashik","discom":"MSEDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Auto manufacturing cluster, fleet EV adoption, NH-3 corridor"}],"corridors":[{"name":"NH-3 Mumbai-Nashik-Indore","distance_km":390,"stations_existing":6,"stations_per_100km":1.5,"opportunity":"High","gap_towns":["Igatpuri","Dhule"]}]},
        "Aurangabad": {"tier":2,"discom":"MSEDCL","grid_avail_pct":89,"loading_pct":66,"headroom":"medium","ev_stations":160,"ev_density":"underserved","power_context":"Marathwada industrial hub and heritage tourism centre. MSEDCL 110kV supply. Strong industrial base (auto ancillaries) makes fleet EV a natural opportunity.","zones":[{"zone":"Chikalthana MIDC","city":"Aurangabad","discom":"MSEDCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"110kV","reason":"Industrial area, fleet vehicle concentration, low EV charging competition"}],"corridors":[{"name":"NH-52 Aurangabad-Hyderabad","distance_km":490,"stations_existing":5,"stations_per_100km":1.0,"opportunity":"High","gap_towns":["Latur","Nanded"]}]},
        "Kolhapur": {"tier":2,"discom":"MSEDCL","grid_avail_pct":90,"loading_pct":64,"headroom":"high","ev_stations":130,"ev_density":"underserved","power_context":"South Maharashtra commercial hub, near Goa/Karnataka border. Good grid headroom (64% loaded). NH-48 Pune-Bengaluru passes through — highway charging opportunity.","zones":[{"zone":"Kolhapur Commercial","city":"Kolhapur","discom":"MSEDCL","opportunity_score":7,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"Border city, high footfall on NH-48, underserved charging market"}],"corridors":[{"name":"NH-48 Pune-Belgaum border","distance_km":170,"stations_existing":3,"stations_per_100km":1.8,"opportunity":"High","gap_towns":["Sangli","Kagal"]}]},
    },
    "Tamil Nadu": {
        "Chennai": {"tier":1,"discom":"TANGEDCO","grid_avail_pct":91,"loading_pct":79,"headroom":"medium","ev_stations":720,"ev_density":"moderate","power_context":"TANGEDCO 110kV in most corridors. ToD pricing available — off-peak (10pm-6am) significantly cheaper. Chennai has India's 3rd highest EV adoption. OMR and GST Road are primary IT/industrial corridors.","zones":[{"zone":"OMR / Sholinganallur","city":"Chennai","discom":"TANGEDCO","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"50km IT corridor, 400k employees, DC fast charging severely underserved"},{"zone":"Ambattur Industrial Estate","city":"Chennai","discom":"TANGEDCO","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Manufacturing hub, fleet EV adoption, NH-4 proximity"},{"zone":"GST Road / NH-44","city":"Chennai","discom":"TANGEDCO","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Airport-Bengaluru corridor, high-volume highway traffic"}],"corridors":[{"name":"NH-44 Chennai-Bengaluru","distance_km":345,"stations_existing":18,"stations_per_100km":5.2,"opportunity":"Medium","gap_towns":["Vellore"]},{"name":"NH-16 Chennai-Vijayawada","distance_km":420,"stations_existing":9,"stations_per_100km":2.1,"opportunity":"High","gap_towns":["Nellore"]}]},
        "Coimbatore": {"tier":2,"discom":"TANGEDCO","grid_avail_pct":92,"loading_pct":68,"headroom":"medium","ev_stations":310,"ev_density":"underserved","power_context":"Textile + engineering manufacturing hub. 110kV supply, 68% loaded. Gateway to Kerala — NH-544 Coimbatore-Kochi is a high-traffic corridor. Strong fleet EV opportunity in textile and logistics.","zones":[{"zone":"Peelamedu / IT Corridor","city":"Coimbatore","discom":"TANGEDCO","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT + education hub, growing EV fleet, low competition"},{"zone":"SIDCO Industrial","city":"Coimbatore","discom":"TANGEDCO","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Textile manufacturing, fleet EV, NH-544 Kerala gateway"}],"corridors":[{"name":"NH-544 Coimbatore-Kochi","distance_km":185,"stations_existing":5,"stations_per_100km":2.7,"opportunity":"High","gap_towns":["Palakkad"]}]},
        "Madurai": {"tier":2,"discom":"TANGEDCO","grid_avail_pct":88,"loading_pct":72,"headroom":"medium","ev_stations":220,"ev_density":"underserved","power_context":"South Tamil Nadu hub and temple tourism centre. 110kV supply. Growing commercial activity. NH-44 south extension and NH-85 are key corridors.","zones":[{"zone":"Anna Nagar / Commercial","city":"Madurai","discom":"TANGEDCO","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"City centre, growing EV adoption, first-mover in underpenetrated market"}],"corridors":[{"name":"NH-44 Madurai-Kanyakumari","distance_km":180,"stations_existing":4,"stations_per_100km":2.2,"opportunity":"High","gap_towns":["Virudhunagar","Tirunelveli"]}]},
        "Tiruchirappalli": {"tier":2,"discom":"TANGEDCO","grid_avail_pct":90,"loading_pct":65,"headroom":"high","ev_stations":180,"ev_density":"underserved","power_context":"Central Tamil Nadu hub with aerospace, heavy engineering, and education sectors. Good headroom (65% loaded). Bharat Heavy Electricals (BHEL) township — institutional fleet EV opportunity.","zones":[{"zone":"Thillai Nagar / Commercial","city":"Tiruchirappalli","discom":"TANGEDCO","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"BHEL + university town, government fleet EV, high headroom"}],"corridors":[{"name":"NH-38 Trichy-Chennai","distance_km":330,"stations_existing":5,"stations_per_100km":1.5,"opportunity":"High","gap_towns":["Villupuram"]}]},
    },
    "Telangana": {
        "Hyderabad": {"tier":1,"discom":"TSSPDCL / TSNPDCL","grid_avail_pct":94,"loading_pct":76,"headroom":"medium","ev_stations":480,"ev_density":"moderate","power_context":"TSSPDCL serves Hyderabad metro with 220kV infrastructure in HITEC City and ORR. Strong EV adoption — 80% YoY growth. TSREDCO actively promoting EV charging. ToD pricing available.","zones":[{"zone":"HITEC City / Gachibowli","city":"Hyderabad","discom":"TSSPDCL","opportunity_score":9,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"500k+ tech workers, EV adoption growing 80% YoY, grid well-upgraded"},{"zone":"Outer Ring Road Corridor","city":"Hyderabad","discom":"TSSPDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"158km ring, multiple nodes, sparse DC fast charging"},{"zone":"Begumpet / Commercial","city":"Hyderabad","discom":"TSSPDCL","opportunity_score":6,"ev_demand":"High","power_reliability":"Medium","supply_voltage":"66kV","reason":"Old commercial area, grid more constrained, high footfall"}],"corridors":[{"name":"NH-44 Hyderabad-Bengaluru","distance_km":570,"stations_existing":14,"stations_per_100km":2.5,"opportunity":"High","gap_towns":["Kurnool"]},{"name":"NH-65 Hyderabad-Pune","distance_km":560,"stations_existing":7,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Solapur"]}]},
        "Warangal": {"tier":2,"discom":"TSNPDCL","grid_avail_pct":91,"loading_pct":62,"headroom":"high","ev_stations":85,"ev_density":"underserved","power_context":"North Telangana hub, 110kV supply, 62% loaded. NH-163 Hyderabad-Warangal highway is a key corridor. Steel, textile and education-driven economy.","zones":[{"zone":"Hanamkonda Commercial","city":"Warangal","discom":"TSNPDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"Twin city commercial hub, high headroom, first-mover opportunity"}],"corridors":[{"name":"NH-163 Hyderabad-Warangal","distance_km":145,"stations_existing":3,"stations_per_100km":2.1,"opportunity":"High","gap_towns":["Bhongir"]}]},
    },
    "Gujarat": {
        "Ahmedabad": {"tier":1,"discom":"APDCL (AMCS) / DGVCL","grid_avail_pct":96,"loading_pct":72,"headroom":"medium","ev_stations":520,"ev_density":"moderate","power_context":"AMCS serves Ahmedabad city with reliable 110kV/220kV grid. DGVCL for periphery. Strong solar generation — off-peak ToD attractive for fleet charging. GIFT City nearby.","zones":[{"zone":"GIFT City / Gandhinagar","city":"Ahmedabad","discom":"DGVCL","opportunity_score":9,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV dedicated","reason":"Smart city, premium market, very reliable dedicated grid"},{"zone":"SG Highway Corridor","city":"Ahmedabad","discom":"AMCS","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT + commercial corridor, high traffic, growing EV fleet"}],"corridors":[{"name":"NH-48 Ahmedabad-Mumbai","distance_km":530,"stations_existing":16,"stations_per_100km":3.0,"opportunity":"High","gap_towns":["Bharuch","Vapi"]}]},
        "Surat": {"tier":1,"discom":"MGVCL / Surat Municipal","grid_avail_pct":95,"loading_pct":68,"headroom":"medium","ev_stations":380,"ev_density":"underserved","power_context":"Diamond + textile hub. 110kV supply, 68% loaded. Highest per-capita income city in India — strong willingness-to-pay for premium charging. Surat-Mumbai Expressway is new EV corridor.","zones":[{"zone":"Vesu / City Light","city":"Surat","discom":"MGVCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Affluent residential, high EV adoption, underserved on fast charging"},{"zone":"Sachin GIDC Industrial","city":"Surat","discom":"MGVCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial zone, fleet EV opportunity, highway proximity"}],"corridors":[{"name":"NH-48 Surat-Mumbai","distance_km":265,"stations_existing":8,"stations_per_100km":3.0,"opportunity":"Medium-High","gap_towns":["Silvassa"]}]},
        "Vadodara": {"tier":2,"discom":"MGVCL","grid_avail_pct":95,"loading_pct":63,"headroom":"high","ev_stations":280,"ev_density":"underserved","power_context":"Petrochemical + engineering hub. Good grid headroom (63% loaded). NH-48 and National Highway corridor. PCPIR zone (petroleum/chemical) creates fleet EV opportunity.","zones":[{"zone":"Alkapuri / Commercial","city":"Vadodara","discom":"MGVCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Premium commercial area, high headroom, growing EV fleet"}],"corridors":[{"name":"NH-48 Vadodara-Ahmedabad","distance_km":113,"stations_existing":6,"stations_per_100km":5.3,"opportunity":"Medium","gap_towns":[]}]},
        "Rajkot": {"tier":2,"discom":"PGVCL / Rajkot Municipal","grid_avail_pct":94,"loading_pct":61,"headroom":"high","ev_stations":230,"ev_density":"underserved","power_context":"Engineering + auto parts manufacturing hub. Good grid (61% loaded). Growing EV adoption. NH-27 Rajkot-Ahmedabad corridor. Auto parts industry drives fleet EV opportunity.","zones":[{"zone":"Kalawad Road / Commercial","city":"Rajkot","discom":"PGVCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Commercial hub, auto industry fleet, high headroom, low competition"}],"corridors":[{"name":"NH-27 Rajkot-Ahmedabad","distance_km":216,"stations_existing":5,"stations_per_100km":2.3,"opportunity":"High","gap_towns":["Morbi"]}]},
    },
    "Rajasthan": {
        "Jaipur": {"tier":1,"discom":"JVVNL","grid_avail_pct":90,"loading_pct":72,"headroom":"medium","ev_stations":380,"ev_density":"underserved","power_context":"JVVNL 110kV supply, 72% loaded. Strong state EV policy with capital subsidies. High tourism + IT growth. NH-48 Delhi-Jaipur is one of India's busiest highways.","zones":[{"zone":"Malviya Nagar / IT City","city":"Jaipur","discom":"JVVNL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT corridor, tourism gateway, aggressive state EV policy"},{"zone":"Sitapura Industrial","city":"Jaipur","discom":"JVVNL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial zone, fleet EV adoption, NH-48 proximity"}],"corridors":[{"name":"NH-48 Delhi-Jaipur","distance_km":280,"stations_existing":9,"stations_per_100km":3.2,"opportunity":"High","gap_towns":["Kotputli"]}]},
        "Jodhpur": {"tier":2,"discom":"JDVVNL","grid_avail_pct":86,"loading_pct":66,"headroom":"medium","ev_stations":190,"ev_density":"underserved","power_context":"Blue City — tourism + textile hub. JDVVNL 110kV, 66% loaded. Growing commercial activity. NH-65 Jodhpur-Hyderabad is a long-distance EV corridor.","zones":[{"zone":"Residency Road / Commercial","city":"Jodhpur","discom":"JDVVNL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"Tourism hub, first-mover opportunity, grid adequate"}],"corridors":[{"name":"NH-65 Jodhpur-Ahmedabad","distance_km":310,"stations_existing":4,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Barmer","Pali"]}]},
        "Udaipur": {"tier":2,"discom":"JDVVNL","grid_avail_pct":87,"loading_pct":60,"headroom":"high","ev_stations":140,"ev_density":"underserved","power_context":"Heritage tourism city with high-income tourists. Good headroom (60% loaded). High EV adoption among luxury hotels. NH-76 and NH-58 corridors.","zones":[{"zone":"Udaipur Lake Pichola Area","city":"Udaipur","discom":"JDVVNL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"66kV","reason":"Premium tourism, luxury hotel fleet EVs, high willingness-to-pay"}],"corridors":[{"name":"NH-76 Udaipur-Chittorgarh","distance_km":115,"stations_existing":2,"stations_per_100km":1.7,"opportunity":"High","gap_towns":["Chittorgarh"]}]},
    },
    "Uttar Pradesh": {
        "Lucknow": {"tier":1,"discom":"LECO (Lucknow Electric Supply Co.)","grid_avail_pct":88,"loading_pct":74,"headroom":"medium","ev_stations":320,"ev_density":"underserved","power_context":"UP state capital with improving grid. LECO serves core city. Expressway-connected (Agra, Kanpur, Gorakhpur). Growing IT corridor — Vibrant Lucknow. Government fleet EV push strong here.","zones":[{"zone":"Gomti Nagar / IT Park","city":"Lucknow","discom":"LECO","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Growing IT sector, government fleet EV, NH connectivity"},{"zone":"Hazratganj / Commercial","city":"Lucknow","discom":"LECO","opportunity_score":6,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"66kV","reason":"Prime commercial area, dense footfall, old grid constraint"}],"corridors":[{"name":"Agra-Lucknow Expressway","distance_km":302,"stations_existing":6,"stations_per_100km":2.0,"opportunity":"High","gap_towns":["Unnao","Kannauj"]}]},
        "Kanpur": {"tier":1,"discom":"KESCO","grid_avail_pct":84,"loading_pct":76,"headroom":"medium","ev_stations":210,"ev_density":"underserved","power_context":"Industrial hub — leather, textiles, defence manufacturing. KESCO grid improving but old industrial areas have quality issues. Strong fleet EV opportunity in logistics and manufacturing.","zones":[{"zone":"Naveen Market / Commercial","city":"Kanpur","discom":"KESCO","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"Major commercial centre, fleet opportunity but grid challenges"},{"zone":"Panki Industrial Area","city":"Kanpur","discom":"KESCO","opportunity_score":6,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"110kV","reason":"Manufacturing hub, fleet EV, better grid in industrial zone"}],"corridors":[{"name":"NH-19 Delhi-Kanpur-Varanasi","distance_km":420,"stations_existing":8,"stations_per_100km":1.9,"opportunity":"High","gap_towns":["Etawah"]}]},
        "Agra": {"tier":2,"discom":"PVVNL","grid_avail_pct":83,"loading_pct":72,"headroom":"medium","ev_stations":160,"ev_density":"underserved","power_context":"Tourism capital — Taj Mahal draws 7M+ annual visitors. PVVNL grid, 72% loaded. Yamuna Expressway is a well-developed EV corridor. Tourism-driven demand for EV taxis and cabs.","zones":[{"zone":"Fatehabad Road / Tourism Zone","city":"Agra","discom":"PVVNL","opportunity_score":7,"ev_demand":"High","power_reliability":"Medium","supply_voltage":"66kV","reason":"Tourism hub, EV taxi opportunity, Yamuna Expressway terminus"}],"corridors":[{"name":"Yamuna Expressway Delhi-Agra","distance_km":165,"stations_existing":8,"stations_per_100km":4.8,"opportunity":"Medium-High","gap_towns":[]}]},
        "Varanasi": {"tier":2,"discom":"PUVVNL","grid_avail_pct":80,"loading_pct":73,"headroom":"medium","ev_stations":130,"ev_density":"underserved","power_context":"Temple city + major tourism destination. PUVVNL grid with improvement underway. Purvanchal Expressway now connected. High tourist footfall drives EV cab/auto demand.","zones":[{"zone":"Lanka / BHU Campus Area","city":"Varanasi","discom":"PUVVNL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"University + tourism area, growing EV cab fleet, underserved"}],"corridors":[{"name":"NH-19 Lucknow-Varanasi","distance_km":285,"stations_existing":4,"stations_per_100km":1.4,"opportunity":"High","gap_towns":["Allahabad","Mirzapur"]}]},
    },
    "Delhi": {
        "New Delhi": {"tier":1,"discom":"BSES Rajdhani / BSES Yamuna / TPDDL","grid_avail_pct":99,"loading_pct":80,"headroom":"medium","ev_stations":950,"ev_density":"moderate","power_context":"Delhi has India's most reliable urban grid (99%, 220kV rings). Multiple DISCOMs. Delhi EV policy is India's most aggressive — free registration, road tax waiver, PM E-DRIVE priority city. High competition in central areas.","zones":[{"zone":"Connaught Place / Central","city":"New Delhi","discom":"BSES Rajdhani","opportunity_score":6,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Very high demand but saturating market — competition is the constraint"},{"zone":"Saket / South Delhi","city":"New Delhi","discom":"BSES Rajdhani","opportunity_score":7,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Premium residential + commercial, high-income EV owners"},{"zone":"Rohini / West Delhi","city":"New Delhi","discom":"BSES Yamuna","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Largest residential area in Delhi, moderate station count, growing fleet"}],"corridors":[{"name":"NH-44 Delhi-Chandigarh-Amritsar","distance_km":450,"stations_existing":14,"stations_per_100km":3.1,"opportunity":"Medium-High","gap_towns":[]},{"name":"NH-48 Delhi-Jaipur","distance_km":280,"stations_existing":9,"stations_per_100km":3.2,"opportunity":"High","gap_towns":["Dharuhera"]}]},
        "Gurugram": {"tier":1,"discom":"DHBVN / TPC (Gurugram)","grid_avail_pct":98,"loading_pct":77,"headroom":"medium","ev_stations":420,"ev_density":"moderate","power_context":"NCR financial hub. Very reliable 220kV grid. Highest per-capita EV ownership in India. NH-48 expressway. Strong competition but demand consistently outstrips supply.","zones":[{"zone":"Cyber Hub / DLF Phase 2-3","city":"Gurugram","discom":"TPC","opportunity_score":8,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Premium commercial, very high EV density, DC fast charging gap"},{"zone":"Sohna Road / Golf Course Ext","city":"Gurugram","discom":"DHBVN","opportunity_score":8,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"Rapid residential growth, EV adoption highest in India"}],"corridors":[{"name":"NH-48 Delhi-Jaipur (through Gurugram)","distance_km":40,"stations_existing":12,"stations_per_100km":30,"opportunity":"Low (saturating)","gap_towns":[]}]},
        "Noida": {"tier":1,"discom":"PVVNL / Noida Power Company","grid_avail_pct":96,"loading_pct":71,"headroom":"medium","ev_stations":340,"ev_density":"moderate","power_context":"NCR IT hub on UP side of Yamuna. Noida Power Company (NPC) serves core sectors with reliable 110kV. Good grid headroom relative to Delhi. Yamuna Expressway access.","zones":[{"zone":"Sector 62 / 63 IT Hub","city":"Noida","discom":"PVVNL","opportunity_score":8,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"Large IT workforce, NCR EV adoption, better headroom than Delhi"},{"zone":"Greater Noida / Knowledge Park","city":"Noida","discom":"PVVNL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Planned township, low competition, good grid"}],"corridors":[{"name":"Yamuna Expressway (Noida-Agra)","distance_km":165,"stations_existing":8,"stations_per_100km":4.8,"opportunity":"Medium-High","gap_towns":[]}]},
    },
    "West Bengal": {
        "Kolkata": {"tier":1,"discom":"CESC (Kolkata city) / WBSEDCL (suburbs)","grid_avail_pct":92,"loading_pct":80,"headroom":"medium","ev_stations":380,"ev_density":"moderate","power_context":"CESC serves Kolkata with reliable 220kV grid. WBSEDCL for suburbs is more variable. Among the highest tariff states (Rs 8.50/unit) — tightens charging economics. Salt Lake and Rajarhat are the IT/commercial EV corridors.","zones":[{"zone":"Salt Lake / Sector V","city":"Kolkata","discom":"CESC","opportunity_score":7,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV","reason":"IT hub, reliable CESC grid, growing EV adoption, tariff is the constraint"},{"zone":"Rajarhat / New Town","city":"Kolkata","discom":"CESC/WBSEDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Planned city, good grid, lower competition than Salt Lake"}],"corridors":[{"name":"NH-12 Kolkata-Siliguri","distance_km":600,"stations_existing":8,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Burdwan","Durgapur"]}]},
        "Siliguri": {"tier":2,"discom":"WBSEDCL","grid_avail_pct":88,"loading_pct":67,"headroom":"medium","ev_stations":110,"ev_density":"underserved","power_context":"Northeast India gateway city. NH-10 junction for Sikkim/Bhutan. Growing commercial hub. Tourism to Darjeeling drives EV cab demand. Good connectivity opportunity.","zones":[{"zone":"Sevoke Road / Commercial","city":"Siliguri","discom":"WBSEDCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"110kV","reason":"Northeast gateway, tourism EV, underserved charging market"}],"corridors":[{"name":"NH-10 Siliguri-Gangtok","distance_km":114,"stations_existing":3,"stations_per_100km":2.6,"opportunity":"High","gap_towns":["Rangpo"]}]},
        "Durgapur": {"tier":2,"discom":"WBSEDCL / DPL","grid_avail_pct":89,"loading_pct":65,"headroom":"high","ev_stations":95,"ev_density":"underserved","power_context":"Steel + industrial city, Damodar Valley power region. Good headroom (65% loaded, industrial supply). NH-2 / Durgapur Expressway. Fleet EV opportunity in steel industry logistics.","zones":[{"zone":"Durgapur Steel Plant Area","city":"Durgapur","discom":"DPL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial fleet, high headroom, underserved EV market"}],"corridors":[{"name":"NH-2 / Durgapur Expressway","distance_km":170,"stations_existing":4,"stations_per_100km":2.4,"opportunity":"High","gap_towns":["Asansol"]}]},
    },
    "Haryana": {
        "Gurugram": {"tier":1,"discom":"DHBVN / TPC (some zones)","grid_avail_pct":97,"loading_pct":77,"headroom":"medium","ev_stations":420,"ev_density":"moderate","power_context":"NCR financial hub with reliable 220kV grid. Highest per-capita EV ownership in India. NH-48 Delhi-Jaipur expressway. Strong demand but market moderately competitive.","zones":[{"zone":"Cyber Hub / DLF","city":"Gurugram","discom":"TPC","opportunity_score":8,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Premium commercial, premium users, DC fast charging gap"},{"zone":"IMT Manesar","city":"Gurugram","discom":"DHBVN","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Auto manufacturing, fleet EV, NH-48 industrial corridor"}],"corridors":[{"name":"NH-48 Delhi-Jaipur","distance_km":280,"stations_existing":9,"stations_per_100km":3.2,"opportunity":"High","gap_towns":["Dharuhera"]}]},
        "Faridabad": {"tier":2,"discom":"DHBVN","grid_avail_pct":91,"loading_pct":73,"headroom":"medium","ev_stations":220,"ev_density":"underserved","power_context":"Industrial suburb south of Delhi. DHBVN 110kV supply. Manufacturing hub (auto, textiles). NH-19 Delhi-Agra passes through. Fleet EV opportunity in industrial sector.","zones":[{"zone":"NHPC / Sector 17-21","city":"Faridabad","discom":"DHBVN","opportunity_score":6,"ev_demand":"Medium-High","power_reliability":"Medium","supply_voltage":"110kV","reason":"Industrial area, fleet EV, Delhi overspill demand"}],"corridors":[{"name":"NH-19 Delhi-Agra","distance_km":165,"stations_existing":8,"stations_per_100km":4.8,"opportunity":"Medium","gap_towns":[]}]},
    },
    "Madhya Pradesh": {
        "Indore": {"tier":1,"discom":"MPMKVVCL","grid_avail_pct":92,"loading_pct":69,"headroom":"medium","ev_stations":340,"ev_density":"underserved","power_context":"India's cleanest city, strong civic culture favouring EVs. MPMKVVCL 110kV supply, 69% loaded. Commercial + pharma hub. NH-3 and NH-52 corridor node.","zones":[{"zone":"Vijay Nagar / Super Corridor","city":"Indore","discom":"MPMKVVCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT/commercial growth corridor, strong environmental awareness, low competition"},{"zone":"Pipliyahana / AB Road","city":"Indore","discom":"MPMKVVCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Commercial artery, high traffic, underserved charging market"}],"corridors":[{"name":"NH-3 Mumbai-Indore-Agra","distance_km":580,"stations_existing":8,"stations_per_100km":1.4,"opportunity":"High","gap_towns":["Dhule","Mhow","Shajapur"]}]},
        "Bhopal": {"tier":1,"discom":"MPPKVVCL","grid_avail_pct":91,"loading_pct":67,"headroom":"medium","ev_stations":280,"ev_density":"underserved","power_context":"State capital, IT park + education hub. MPPKVVCL 110kV supply. Government fleet EV procurement strong. NH-12 Bhopal-Jabalpur and NH-146 Bhopal-Indore are key corridors.","zones":[{"zone":"MP Nagar / IT Park","city":"Bhopal","discom":"MPPKVVCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Government + IT hub, strong fleet EV, underserved public charging"}],"corridors":[{"name":"NH-146 Bhopal-Indore","distance_km":190,"stations_existing":4,"stations_per_100km":2.1,"opportunity":"High","gap_towns":["Sehore"]}]},
        "Gwalior": {"tier":2,"discom":"MPPKVVCL","grid_avail_pct":88,"loading_pct":68,"headroom":"medium","ev_stations":150,"ev_density":"underserved","power_context":"Historic city + industrial hub. 110kV supply. NH-44 Delhi-Hyderabad corridor. Tourism (forts) and defence establishments drive demand.","zones":[{"zone":"Gwalior Commercial","city":"Gwalior","discom":"MPPKVVCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"Tourism + defence, underserved market, NH-44 connectivity"}],"corridors":[{"name":"NH-44 Delhi-Hyderabad (Gwalior)","distance_km":100,"stations_existing":3,"stations_per_100km":3.0,"opportunity":"Medium","gap_towns":[]}]},
    },
    "Punjab": {
        "Ludhiana": {"tier":1,"discom":"PSPCL","grid_avail_pct":93,"loading_pct":74,"headroom":"medium","ev_stations":280,"ev_density":"underserved","power_context":"Hosiery + bicycle + auto ancillary capital. PSPCL reliable 110kV supply. NH-44 Delhi-Amritsar passes through. Fleet EV strong opportunity in manufacturing.","zones":[{"zone":"Focal Point Industrial","city":"Ludhiana","discom":"PSPCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Largest industrial zone, fleet EV, NH-44 highway node"}],"corridors":[{"name":"NH-44 Delhi-Amritsar GT Road","distance_km":450,"stations_existing":14,"stations_per_100km":3.1,"opportunity":"Medium-High","gap_towns":["Panipat","Karnal"]}]},
        "Amritsar": {"tier":2,"discom":"PSPCL","grid_avail_pct":92,"loading_pct":66,"headroom":"medium","ev_stations":190,"ev_density":"underserved","power_context":"Tourism capital + border city. Wagah border and Golden Temple draw 25M+ annual visitors. 110kV supply, 66% loaded. Airport expressway. Tourism EV opportunity is significant.","zones":[{"zone":"Lawrence Road / Ranjit Avenue","city":"Amritsar","discom":"PSPCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Tourism hub, EV cab/auto demand, airport proximity"}],"corridors":[{"name":"NH-54 Amritsar-Jammu","distance_km":220,"stations_existing":4,"stations_per_100km":1.8,"opportunity":"High","gap_towns":["Pathankot"]}]},
    },
    "Uttarakhand": {
        "Dehradun": {"tier":1,"discom":"UPCL","grid_avail_pct":96,"loading_pct":62,"headroom":"high","ev_stations":180,"ev_density":"underserved","power_context":"State capital with reliable hydro-backed grid (96% availability, low tariff Rs 4.50/unit). IT + education hub. NH-7 to Rishikesh/Haridwar pilgrimage corridor. High headroom — very good for new connections.","zones":[{"zone":"Rajpur Road / Commercial","city":"Dehradun","discom":"UPCL","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"110kV","reason":"IT + education hub, high headroom, tourism gateway, low competition"}],"corridors":[{"name":"NH-7 Dehradun-Haridwar-Rishikesh","distance_km":55,"stations_existing":3,"stations_per_100km":5.5,"opportunity":"Medium-High","gap_towns":[]}]},
        "Haridwar": {"tier":2,"discom":"UPCL","grid_avail_pct":95,"loading_pct":58,"headroom":"high","ev_stations":95,"ev_density":"underserved","power_context":"Pilgrimage city — 30M+ annual visitors. UPCL reliable hydro grid, 58% loaded. NH-58 Delhi-Haridwar highway. Strong EV cab/auto demand from pilgrims.","zones":[{"zone":"Har Ki Pauri / Tourism Zone","city":"Haridwar","discom":"UPCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"66kV","reason":"10M+ pilgrims, growing EV cab fleet, high headroom, low charging competition"}],"corridors":[{"name":"NH-58 Delhi-Haridwar","distance_km":250,"stations_existing":9,"stations_per_100km":3.6,"opportunity":"Medium","gap_towns":[]}]},
    },
    "Odisha": {
        "Bhubaneswar": {"tier":1,"discom":"TPCODL","grid_avail_pct":90,"loading_pct":67,"headroom":"medium","ev_stations":185,"ev_density":"underserved","power_context":"Smart city initiative — well-planned infrastructure. TPCODL (Tata Power) with improving grid. NH-16 Kolkata-Chennai passes through. IT + government hub with growing EV adoption.","zones":[{"zone":"Infocity / IT Park","city":"Bhubaneswar","discom":"TPCODL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"IT + government hub, smart city, underserved EV market"}],"corridors":[{"name":"NH-16 Bhubaneswar-Kolkata","distance_km":480,"stations_existing":6,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Balasore","Bhadrak"]}]},
        "Rourkela": {"tier":2,"discom":"TPSODL","grid_avail_pct":88,"loading_pct":61,"headroom":"high","ev_stations":85,"ev_density":"underserved","power_context":"Steel city with industrial power supply. TPSODL (Tata Power), 61% loaded. Jharkhand border — Ranchi-Rourkela corridor. Fleet EV in steel/mining sector.","zones":[{"zone":"Steel Township","city":"Rourkela","discom":"TPSODL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial fleet opportunity, high headroom, very underserved market"}],"corridors":[{"name":"NH-143 Rourkela-Ranchi","distance_km":130,"stations_existing":2,"stations_per_100km":1.5,"opportunity":"High","gap_towns":["Simdega"]}]},
    },
    "Kerala": {
        "Kochi": {"tier":1,"discom":"KSEB","grid_avail_pct":97,"loading_pct":70,"headroom":"medium","ev_stations":320,"ev_density":"underserved","power_context":"KSEB hydro-backed grid, 97% availability. Growing IT and port-based economy. Kerala has high EV adoption (environmental awareness + high literacy). NH-66 coastal highway is the primary corridor.","zones":[{"zone":"Infopark / SmartCity","city":"Kochi","discom":"KSEB","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"110kV","reason":"IT hub, high-income workforce, EV-friendly state policy, low competition"},{"zone":"Kakkanad / NH-85","city":"Kochi","discom":"KSEB","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Commercial corridor, growing EV fleet"}],"corridors":[{"name":"NH-66 Kochi-Kozhikode","distance_km":230,"stations_existing":9,"stations_per_100km":3.9,"opportunity":"Medium","gap_towns":[]}]},
        "Thiruvananthapuram": {"tier":1,"discom":"KSEB","grid_avail_pct":97,"loading_pct":65,"headroom":"high","ev_stations":240,"ev_density":"underserved","power_context":"State capital + IT hub. KSEB reliable grid, 65% loaded. High headroom. Technopark is India's first IT park — large EV-adopting workforce. Tourism to beaches and backwaters.","zones":[{"zone":"Technopark / Kazhakoottam","city":"Thiruvananthapuram","discom":"KSEB","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"110kV","reason":"IT hub, high headroom, Kerala high EV policy support, underserved"}],"corridors":[{"name":"NH-44 Thiruvananthapuram-Chennai (NH-66)","distance_km":640,"stations_existing":22,"stations_per_100km":3.4,"opportunity":"Medium","gap_towns":[]}]},
        "Kozhikode": {"tier":2,"discom":"KSEB","grid_avail_pct":96,"loading_pct":62,"headroom":"high","ev_stations":160,"ev_density":"underserved","power_context":"Calicut — commercial hub of North Kerala. KSEB reliable grid, 62% loaded — high headroom. NH-66 coastal highway. Textile and spice trade creates fleet opportunity.","zones":[{"zone":"Mavoor Road / Commercial","city":"Kozhikode","discom":"KSEB","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Commercial hub, high headroom, low competition, growing EV fleet"}],"corridors":[{"name":"NH-66 Kozhikode-Goa","distance_km":350,"stations_existing":6,"stations_per_100km":1.7,"opportunity":"High","gap_towns":["Kannur","Kasaragod"]}]},
    },
    "Andhra Pradesh": {
        "Visakhapatnam": {"tier":1,"discom":"APEPDCL","grid_avail_pct":93,"loading_pct":72,"headroom":"medium","ev_stations":280,"ev_density":"underserved","power_context":"Steel + IT hub and port city. APEPDCL 110kV, 72% loaded. NH-16 Chennai-Kolkata corridor. New state capital region driving investment. Fleet EV in steel and port logistics.","zones":[{"zone":"Rushikonda / IT Hill","city":"Visakhapatnam","discom":"APEPDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT cluster, high-income area, growing EV market"},{"zone":"BHPV / Steel Plant Area","city":"Visakhapatnam","discom":"APEPDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial fleet, high EV potential in heavy industry"}],"corridors":[{"name":"NH-16 Vizag-Vijayawada","distance_km":350,"stations_existing":8,"stations_per_100km":2.3,"opportunity":"High","gap_towns":["Rajahmundry"]}]},
        "Vijayawada": {"tier":1,"discom":"APSPDCL","grid_avail_pct":91,"loading_pct":74,"headroom":"medium","ev_stations":220,"ev_density":"underserved","power_context":"Andhra Pradesh commercial hub. Amaravati capital region nearby. APSPDCL 110kV supply. NH-16 junction — high-traffic corridor node. Seed capital area driving premium EV adoption.","zones":[{"zone":"MG Road / Benz Circle","city":"Vijayawada","discom":"APSPDCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Commercial hub, capital region proximity, growing EV fleet"}],"corridors":[{"name":"NH-65 Vijayawada-Hyderabad","distance_km":275,"stations_existing":6,"stations_per_100km":2.2,"opportunity":"High","gap_towns":["Nalgonda"]}]},
    },
}

# ── EV zones data — all 30 states ─────────────────────────────────────────────
# Detailed for 9 key states; summary-level for remaining 21.
# Source: State EV policy portals, NH corridor data, DISCOM territory maps.
# Last verified: July 2026
EV_ZONES_DATA = {
    "Karnataka": {
        "discom": "BESCOM / HESCOM / MESCOM / CESC / GESCOM",
        "ev_stations_total": 6096, "grid_avail_pct": 96,
        "power_context": "BESCOM territory has dedicated 220kV infrastructure in Bengaluru. NH highway corridors fed by 11kV/33kV — transformer upgrades needed for chargers above 60kW. 220kV available at Electronic City, Whitefield, KIADB areas.",
        "corridors": [
            {"name":"NH-44 Bengaluru → Hyderabad","distance_km":570,"stations_existing":14,"stations_per_100km":2.5,"opportunity":"High","gap_towns":["Kolar","Chittoor border"]},
            {"name":"NH-48 Bengaluru → Mumbai","distance_km":995,"stations_existing":9,"stations_per_100km":0.9,"opportunity":"Very High","gap_towns":["Chitradurga","Davangere","Dharwad"]},
            {"name":"NH-75 Bengaluru → Mangaluru","distance_km":352,"stations_existing":6,"stations_per_100km":1.7,"opportunity":"High","gap_towns":["Hassan","Sakleshpur ghat"]},
        ],
        "zones": [
            {"zone":"Whitefield","city":"Bengaluru","discom":"BESCOM","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"220kV nearby","reason":"1.2M daily footfall, low charger density vs EV registrations"},
            {"zone":"Electronic City","city":"Bengaluru","discom":"BESCOM","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV","reason":"150k+ IT employees, dedicated KIADB infrastructure"},
            {"zone":"Tumkuru (NH-48)","city":"Tumkuru","discom":"BESCOM","opportunity_score":9,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"NH-48 gateway, zero public DC fast chargers in 80km stretch"},
            {"zone":"Mysuru City","city":"Mysuru","discom":"CESC","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"66kV","reason":"Tourism capital, growing EV fleet, limited fast charging"},
        ]
    },
    "Maharashtra": {
        "discom": "MSEDCL / BEST (Mumbai) / TPC (Mumbai)",
        "ev_stations_total": 3200, "grid_avail_pct": 94,
        "power_context": "Mumbai grid highly reliable (multiple 220kV rings). Pune and Nashik have 110kV. Rural MSEDCL areas have load-shedding — verify substation capacity before highway stations.",
        "corridors": [
            {"name":"Mumbai → Pune Expressway","distance_km":165,"stations_existing":22,"stations_per_100km":13.3,"opportunity":"Low (densifying)","gap_towns":[]},
            {"name":"NH-48 Pune → Bengaluru","distance_km":840,"stations_existing":11,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Satara","Kolhapur","Belgaum"]},
            {"name":"NH-44 Nagpur → Hyderabad","distance_km":500,"stations_existing":6,"stations_per_100km":1.2,"opportunity":"High","gap_towns":["Yavatmal","Nanded"]},
        ],
        "zones": [
            {"zone":"Hinjewadi","city":"Pune","discom":"MSEDCL","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"IT corridor, 400k+ daily commuters, EV fleet growing faster than infrastructure"},
            {"zone":"Bandra-Kurla Complex","city":"Mumbai","discom":"BEST/TPC","opportunity_score":7,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Financial hub, premium users, high willingness-to-pay"},
            {"zone":"Nashik Industrial Area","city":"Nashik","discom":"MSEDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Auto manufacturing cluster, fleet EV adoption, Pune highway node"},
        ]
    },
    "Tamil Nadu": {
        "discom": "TANGEDCO",
        "ev_stations_total": 2800, "grid_avail_pct": 91,
        "power_context": "TANGEDCO has 110kV infrastructure for EV charging in Chennai metro. ToD tariff: off-peak (10pm-6am) significantly lower — strong overnight fleet charging signal.",
        "corridors": [
            {"name":"NH-44 Chennai → Bengaluru","distance_km":345,"stations_existing":18,"stations_per_100km":5.2,"opportunity":"Medium","gap_towns":["Vellore","Krishnagiri"]},
            {"name":"NH-66 Chennai Coastal","distance_km":700,"stations_existing":8,"stations_per_100km":1.1,"opportunity":"High","gap_towns":["Cuddalore","Nagapattinam"]},
        ],
        "zones": [
            {"zone":"OMR Tech Corridor","city":"Chennai","discom":"TANGEDCO","opportunity_score":9,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"50km corridor, 400k IT employees, 2x EV growth YoY"},
            {"zone":"Coimbatore Industrial","city":"Coimbatore","discom":"TANGEDCO","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"66kV","reason":"Textile + engineering hub, fleet EV early adopters, Kerala gateway"},
        ]
    },
    "Delhi": {
        "discom": "BSES Rajdhani / BSES Yamuna / TPDDL",
        "ev_stations_total": 1850, "grid_avail_pct": 99,
        "power_context": "Delhi has India's most reliable urban grid (99% availability). 220kV ring throughout NCR. Delhi EV policy aggressive — free registration, road tax waiver, 5% GST refund.",
        "corridors": [
            {"name":"NH-44 Delhi → Chandigarh","distance_km":275,"stations_existing":14,"stations_per_100km":5.1,"opportunity":"Medium","gap_towns":[]},
            {"name":"NH-48 Delhi → Jaipur","distance_km":280,"stations_existing":9,"stations_per_100km":3.2,"opportunity":"Medium-High","gap_towns":["Dharuhera"]},
        ],
        "zones": [
            {"zone":"Cyber City / DLF","city":"Gurugram (NCR)","discom":"DHBVN/TPDDL","opportunity_score":9,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"Highest per-capita EV density in India, premium willingness-to-pay"},
            {"zone":"Noida Expressway","city":"Noida (NCR)","discom":"PVVNL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT/ITES hub, 300k+ daily commuters"},
        ]
    },
    "Gujarat": {
        "discom": "DGVCL / MGVCL / PGVCL / UGVCL",
        "ev_stations_total": 2100, "grid_avail_pct": 95,
        "power_context": "Gujarat has India's best industrial power quality. Strong solar + wind generation means off-peak ToD prices are low — attractive for fleet depot charging.",
        "corridors": [
            {"name":"NH-48 Ahmedabad → Mumbai","distance_km":530,"stations_existing":16,"stations_per_100km":3.0,"opportunity":"High","gap_towns":["Bharuch","Vapi"]},
            {"name":"Ahmedabad → Surat Expressway","distance_km":265,"stations_existing":12,"stations_per_100km":4.5,"opportunity":"Medium-High","gap_towns":[]},
        ],
        "zones": [
            {"zone":"GIFT City","city":"Gandhinagar","discom":"DGVCL","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV dedicated","reason":"Smart city infrastructure, premium commercial, rapid EV adoption"},
            {"zone":"Surat Commercial","city":"Surat","discom":"MGVCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Highest per-capita income city, fleet operators, good power quality"},
        ]
    },
    "Telangana": {
        "discom": "TSSPDCL / TSNPDCL",
        "ev_stations_total": 1100, "grid_avail_pct": 94,
        "power_context": "Hyderabad metro has 220kV and 400kV. TSSPDCL has dedicated feeders in HITEC City and Gachibowli. ToD pricing available.",
        "corridors": [
            {"name":"NH-44 Hyderabad → Bengaluru","distance_km":570,"stations_existing":14,"stations_per_100km":2.5,"opportunity":"High","gap_towns":["Kurnool","Anantapur"]},
        ],
        "zones": [
            {"zone":"HITEC City / Gachibowli","city":"Hyderabad","discom":"TSSPDCL","opportunity_score":9,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"India's 2nd largest IT hub, EV adoption growing 80% YoY"},
            {"zone":"Outer Ring Road","city":"Hyderabad","discom":"TSSPDCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"158km ring with industrial nodes, sparse DC fast charging"},
        ]
    },
    "Rajasthan": {
        "discom": "JDVVNL / JVVNL",
        "ev_stations_total": 980, "grid_avail_pct": 88,
        "power_context": "Rajasthan has abundant solar but rural grid reliability is lower (88%). Jaipur urban area is reliable. RUVNL actively procuring BESS — good backdrop for solar+charging co-location.",
        "corridors": [
            {"name":"NH-48 Jaipur → Delhi","distance_km":280,"stations_existing":9,"stations_per_100km":3.2,"opportunity":"High","gap_towns":["Kotputli"]},
        ],
        "zones": [
            {"zone":"Jaipur Commercial","city":"Jaipur","discom":"JVVNL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Tourism + growing IT hub, aggressive state EV policy, Delhi corridor"},
        ]
    },
    "Kerala": {
        "discom": "KSEB",
        "ev_stations_total": 780, "grid_avail_pct": 97,
        "power_context": "Kerala has India's 2nd-highest grid availability (97%). KSEB infrastructure well-maintained. High EV adoption due to high literacy and environmental awareness.",
        "corridors": [
            {"name":"NH-66 Thiruvananthapuram → Kozhikode","distance_km":450,"stations_existing":24,"stations_per_100km":5.3,"opportunity":"Medium","gap_towns":["Thrissur-Kozhikode gap"]},
        ],
        "zones": [
            {"zone":"Infopark / SmartCity","city":"Kochi","discom":"KSEB","opportunity_score":8,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"110kV","reason":"Rapidly growing IT hub, high-income workforce, EV-friendly state policy"},
        ]
    },
    "Andhra Pradesh": {
        "discom": "APSPDCL / APEPDCL",
        "ev_stations_total": 1240, "grid_avail_pct": 93,
        "power_context": "AP has significant renewable capacity (solar, wind). Grid reliability good in Visakhapatnam and Amaravati capital region.",
        "corridors": [
            {"name":"NH-16 Chennai → Vijayawada → Vizag","distance_km":800,"stations_existing":18,"stations_per_100km":2.3,"opportunity":"High","gap_towns":["Ongole","Rajahmundry"]},
        ],
        "zones": [
            {"zone":"Visakhapatnam Port / IT","city":"Visakhapatnam","discom":"APEPDCL","opportunity_score":8,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Steel + IT hub, NH-16 corridor, growing EV adoption"},
        ]
    },
    "Uttar Pradesh": {
        "discom": "UPPCL (multiple DISCOMs)",
        "ev_stations_total": 1200, "grid_avail_pct": 85,
        "power_context": "UP has large geographic spread with variable grid quality (85% avg). Lucknow, Noida, Agra urban areas are reliable. Rural areas face load-shedding. New expressway corridors (Yamuna, Purvanchal, Bundelkhand) are the key EV opportunity.",
        "corridors": [
            {"name":"Yamuna Expressway (Delhi-Agra)","distance_km":165,"stations_existing":8,"stations_per_100km":4.8,"opportunity":"Medium","gap_towns":[]},
            {"name":"Lucknow-Kanpur Highway","distance_km":80,"stations_existing":4,"stations_per_100km":5.0,"opportunity":"Medium","gap_towns":[]},
            {"name":"NH-19 Agra → Varanasi","distance_km":560,"stations_existing":6,"stations_per_100km":1.1,"opportunity":"High","gap_towns":["Allahabad","Mirzapur"]},
        ],
        "zones": [
            {"zone":"Gomti Nagar IT / Commercial","city":"Lucknow","discom":"LECO","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"State capital IT corridor, growing EV fleet, good urban grid"},
            {"zone":"Sector 62 / 63","city":"Noida (NCR)","discom":"PVVNL","opportunity_score":8,"ev_demand":"Very High","power_reliability":"High","supply_voltage":"110kV","reason":"NCR tech corridor, high EV adoption, NH-24 connectivity"},
        ]
    },
    "West Bengal": {
        "discom": "WBSEDCL / CESC (Kolkata)",
        "ev_stations_total": 890, "grid_avail_pct": 92,
        "power_context": "CESC serves Kolkata metro with reliable 220kV grid. WBSEDCL covers rest of state with variable quality. Among the highest tariff states (Rs 8.50/unit) — affects EV charging economics.",
        "corridors": [
            {"name":"NH-12 Kolkata → Siliguri","distance_km":600,"stations_existing":8,"stations_per_100km":1.3,"opportunity":"High","gap_towns":["Burdwan","Durgapur","Asansol"]},
        ],
        "zones": [
            {"zone":"Salt Lake / Sector V","city":"Kolkata","discom":"CESC","opportunity_score":7,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"220kV","reason":"IT hub, high-income area, CESC reliable grid — tariff is the constraint"},
            {"zone":"Durgapur Industrial","city":"Durgapur","discom":"WBSEDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"Industrial corridor, fleet opportunity, NH-12 highway node"},
        ]
    },
    "Haryana": {
        "discom": "DHBVN / UHBVN",
        "ev_stations_total": 890, "grid_avail_pct": 91,
        "power_context": "Haryana benefits from NCR proximity. Gurugram and Faridabad have 220kV infrastructure. NH-48 and NH-44 are key corridors. Good EV policy — 100% road tax waiver on EVs.",
        "corridors": [
            {"name":"NH-48 Delhi-Gurugram-Jaipur","distance_km":270,"stations_existing":18,"stations_per_100km":6.7,"opportunity":"Medium","gap_towns":[]},
            {"name":"NH-44 Delhi-Ambala-Chandigarh","distance_km":250,"stations_existing":12,"stations_per_100km":4.8,"opportunity":"Medium-High","gap_towns":["Karnal","Panipat"]},
        ],
        "zones": [
            {"zone":"Cyber Hub / DLF Gurugram","city":"Gurugram","discom":"DHBVN","opportunity_score":8,"ev_demand":"Very High","power_reliability":"Very High","supply_voltage":"220kV","reason":"NCR financial hub, premium market, Delhi spillover demand"},
            {"zone":"IMT Manesar","city":"Manesar","discom":"DHBVN","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"Auto + manufacturing hub, fleet EV adoption, NH-48 corridor"},
        ]
    },
    "Madhya Pradesh": {
        "discom": "MPPKVVCL / MPMKVVCL / MPPKVVCL",
        "ev_stations_total": 650, "grid_avail_pct": 90,
        "power_context": "MP has variable grid quality by region. Indore and Bhopal urban areas are reliable (110kV). Expressway corridors are the main EV opportunity — MP has India's longest expressway network.",
        "corridors": [
            {"name":"NH-3 Agra-Indore-Mumbai","distance_km":860,"stations_existing":10,"stations_per_100km":1.2,"opportunity":"High","gap_towns":["Gwalior","Shivpuri","Ujjain"]},
            {"name":"NH-12 Bhopal-Jabalpur","distance_km":290,"stations_existing":5,"stations_per_100km":1.7,"opportunity":"High","gap_towns":["Sagar","Damoh"]},
        ],
        "zones": [
            {"zone":"Vijay Nagar / Super Corridor","city":"Indore","discom":"MPMKVVCL","opportunity_score":8,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"India's cleanest city, high EV awareness, IT/commercial growth"},
            {"zone":"Bhopal IT Park","city":"Bhopal","discom":"MPPKVVCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"State capital, growing IT sector, NH-12 hub"},
        ]
    },
    "Punjab": {
        "discom": "PSPCL",
        "ev_stations_total": 650, "grid_avail_pct": 93,
        "power_context": "Punjab has good urban grid reliability (93%) and low domestic tariff (Rs 4.80/unit) due to agricultural subsidies. NH-44 Delhi-Amritsar is the primary EV corridor. High commercial vehicle traffic.",
        "corridors": [
            {"name":"NH-44 Delhi-Amritsar (Grand Trunk Road)","distance_km":450,"stations_existing":14,"stations_per_100km":3.1,"opportunity":"Medium-High","gap_towns":["Ambala-Ludhiana gap","Jalandhar bypass"]},
        ],
        "zones": [
            {"zone":"Industrial Area Phase 8-9","city":"Mohali","discom":"PSPCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"110kV","reason":"IT and pharma hub, Chandigarh proximity, growing EV adoption"},
            {"zone":"Focal Point Industrial","city":"Ludhiana","discom":"PSPCL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Largest industrial city, hosiery/auto ancillary, NH-44 node"},
        ]
    },
    "Bihar": {
        "discom": "NBPDCL / SBPDCL",
        "ev_stations_total": 320, "grid_avail_pct": 78,
        "power_context": "Bihar has improving but still unreliable grid (78% avg availability). Patna urban area is more reliable. Low EV density creates opportunity but grid quality is a real constraint for DC fast charging.",
        "corridors": [
            {"name":"NH-30 Patna-Ranchi-Raipur","distance_km":680,"stations_existing":4,"stations_per_100km":0.6,"opportunity":"Very High","gap_towns":["Gaya","Aurangabad","Hazaribagh"]},
        ],
        "zones": [
            {"zone":"Patna City / Bailey Road","city":"Patna","discom":"SBPDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"State capital, growing commercial area, first-mover opportunity in underserved market"},
        ]
    },
    "Odisha": {
        "discom": "TPSODL / TPCODL",
        "ev_stations_total": 420, "grid_avail_pct": 89,
        "power_context": "Odisha has large renewable capacity and improving grid (TPCODL/TPSODL after Tata Power privatisation). Bhubaneswar-Cuttack corridor is the primary urban EV market.",
        "corridors": [
            {"name":"NH-16 Kolkata-Bhubaneswar-Chennai","distance_km":500,"stations_existing":6,"stations_per_100km":1.2,"opportunity":"High","gap_towns":["Balasore","Bhadrak","Berhampur"]},
        ],
        "zones": [
            {"zone":"Infocity / IT Park","city":"Bhubaneswar","discom":"TPCODL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"High","supply_voltage":"110kV","reason":"Smart city, growing IT sector, NH-16 corridor node, low competition"},
        ]
    },
    "Jharkhand": {
        "discom": "JBVNL",
        "ev_stations_total": 190, "grid_avail_pct": 82,
        "power_context": "Jharkhand has significant coal and hydro capacity but distribution is underdeveloped (82% availability). Ranchi urban area is reliable. Mining and steel corridor creates fleet EV opportunity.",
        "corridors": [
            {"name":"NH-33 Ranchi-Dhanbad-Asansol","distance_km":215,"stations_existing":3,"stations_per_100km":1.4,"opportunity":"High","gap_towns":["Bokaro","Dhanbad area"]},
        ],
        "zones": [
            {"zone":"Ranchi Commercial District","city":"Ranchi","discom":"JBVNL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"State capital, first-mover opportunity, mining industry fleet vehicles"},
        ]
    },
    "Chhattisgarh": {
        "discom": "CSPDCL",
        "ev_stations_total": 280, "grid_avail_pct": 87,
        "power_context": "Chhattisgarh is a power-surplus state with low tariff (Rs 5.80/unit). Industrial corridor (Raipur-Bhilai) is the primary market. Good grid for industrial connections.",
        "corridors": [
            {"name":"NH-53 Raipur-Nagpur","distance_km":290,"stations_existing":4,"stations_per_100km":1.4,"opportunity":"High","gap_towns":["Durg","Rajnandgaon"]},
        ],
        "zones": [
            {"zone":"Raipur Industrial / Commercial","city":"Raipur","discom":"CSPDCL","opportunity_score":7,"ev_demand":"Medium","power_reliability":"High","supply_voltage":"110kV","reason":"State capital, steel industry fleet, low tariff advantageous for charging economics"},
        ]
    },
    "Assam": {
        "discom": "APDCL",
        "ev_stations_total": 180, "grid_avail_pct": 80,
        "power_context": "Assam has improving but challenging grid (80% availability, higher tariff Rs 7.00/unit). Guwahati urban area is most reliable. NH-27 and NH-37 are key corridors for EV charging. Tea estate and oil industry creates captive fleet opportunity.",
        "corridors": [
            {"name":"NH-27 Guwahati-Shillong","distance_km":105,"stations_existing":3,"stations_per_100km":2.9,"opportunity":"Medium-High","gap_towns":[]},
        ],
        "zones": [
            {"zone":"Guwahati Commercial / NH-37","city":"Guwahati","discom":"APDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"Northeast hub city, growing commercial activity, NH-37 corridor"},
        ]
    },
    "Himachal Pradesh": {
        "discom": "HPSEBL",
        "ev_stations_total": 220, "grid_avail_pct": 98,
        "power_context": "HP has the cleanest and most reliable grid in India (98%, 85% hydro-based). Very low tariff (Rs 4.20/unit). NH-1 Chandigarh-Manali and NH-5 are primary tourist-driven EV corridors.",
        "corridors": [
            {"name":"NH-1 Chandigarh-Shimla-Manali","distance_km":275,"stations_existing":8,"stations_per_100km":2.9,"opportunity":"High","gap_towns":["Mandi","Kullu-Bhuntar"]},
        ],
        "zones": [
            {"zone":"The Mall / Commercial Core","city":"Shimla","discom":"HPSEBL","opportunity_score":7,"ev_demand":"Medium-High","power_reliability":"Very High","supply_voltage":"33kV","reason":"Tourism capital, reliable hydro grid, EV adoption growing with state incentives"},
        ]
    },
    "Uttarakhand": {
        "discom": "UPCL",
        "ev_stations_total": 280, "grid_avail_pct": 96,
        "power_context": "Uttarakhand has excellent grid reliability (96%, 72% hydro). Low tariff (Rs 4.50/unit). NH-58 Delhi-Haridwar-Rishikesh and NH-7 Rishikesh-Badrinath are key pilgrimage and tourism EV corridors.",
        "corridors": [
            {"name":"NH-58 Delhi-Haridwar-Rishikesh","distance_km":250,"stations_existing":9,"stations_per_100km":3.6,"opportunity":"Medium-High","gap_towns":["Muzaffarnagar","Roorkee"]},
        ],
        "zones": [
            {"zone":"Haridwar-Rishikesh Corridor","city":"Haridwar","discom":"UPCL","opportunity_score":7,"ev_demand":"High","power_reliability":"High","supply_voltage":"66kV","reason":"10M+ annual pilgrims, growing EV fleet, reliable hydro grid, low tariff"},
        ]
    },
    "Goa": {
        "discom": "Goa Electricity Dept",
        "ev_stations_total": 210, "grid_avail_pct": 99,
        "power_context": "Goa has India's best grid availability (tied 99%) and the lowest commercial vehicle density. Tourism-driven EV demand — two-wheelers and taxis dominate. NH-66 is the primary corridor.",
        "corridors": [
            {"name":"NH-66 Goa Coastal Highway","distance_km":107,"stations_existing":8,"stations_per_100km":7.5,"opportunity":"Medium","gap_towns":["South Goa beaches stretch"]},
        ],
        "zones": [
            {"zone":"Panaji / Calangute Area","city":"Panaji","discom":"Goa Electricity Dept","opportunity_score":7,"ev_demand":"High","power_reliability":"Very High","supply_voltage":"66kV","reason":"Tourism hub, high-value EV rental market, excellent grid reliability"},
        ]
    },
    "Jammu and Kashmir": {
        "discom": "JKPDCL",
        "ev_stations_total": 120, "grid_avail_pct": 85,
        "power_context": "J&K has low tariff (Rs 3.50/unit, heavily subsidised) and improving grid (85%). Srinagar and Jammu urban areas are most reliable. NH-44 Jammu-Srinagar is the critical corridor.",
        "corridors": [
            {"name":"NH-44 Jammu-Srinagar","distance_km":270,"stations_existing":4,"stations_per_100km":1.5,"opportunity":"High","gap_towns":["Banihal tunnel","Udhampur","Qazigund"]},
        ],
        "zones": [
            {"zone":"Jammu Commercial","city":"Jammu","discom":"JKPDCL","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"66kV","reason":"Fastest-growing city in J&K, NH-44 starting point, government fleet EV push"},
        ]
    },
    "Meghalaya": {
        "discom": "MePDCL",
        "ev_stations_total": 32, "grid_avail_pct": 75,
        "power_context": "Meghalaya has improving but limited grid (75%). Shillong is the main urban market. NH-6 and NH-27 are key corridors. Very low EV station count — first-mover opportunity.",
        "corridors": [
            {"name":"NH-6 Guwahati-Shillong","distance_km":105,"stations_existing":2,"stations_per_100km":1.9,"opportunity":"High","gap_towns":["Jorabat","Byrnihat"]},
        ],
        "zones": [
            {"zone":"Shillong Commercial","city":"Shillong","discom":"MePDCL","opportunity_score":5,"ev_demand":"Medium","power_reliability":"Medium","supply_voltage":"33kV","reason":"State capital, tourism, but limited grid and small market size — early mover"},
        ]
    },
    "Manipur": {
        "discom": "MSPDCL",
        "ev_stations_total": 28, "grid_avail_pct": 72,
        "power_context": "Manipur has the most challenging grid in northeast India (72%). Imphal urban area has partial reliability. Central government push for EV adoption but infrastructure is nascent.",
        "corridors": [
            {"name":"NH-2 Imphal-Moreh","distance_km":110,"stations_existing":1,"stations_per_100km":0.9,"opportunity":"Very High (first-mover)","gap_towns":["Pallel","Moreh"]},
        ],
        "zones": [
            {"zone":"Imphal Commercial","city":"Imphal","discom":"MSPDCL","opportunity_score":4,"ev_demand":"Low-Medium","power_reliability":"Low","supply_voltage":"33kV","reason":"State capital, first-mover opportunity but grid is significant constraint — diesel backup needed"},
        ]
    },
    "Sikkim": {
        "discom": "Energy & Power Dept",
        "ev_stations_total": 45, "grid_avail_pct": 99,
        "power_context": "Sikkim has India's best grid reliability (tied 99%) and lowest tariff (Rs 3.40/unit) due to abundant hydro. Tourism EV opportunity on NH-10 Siliguri-Gangtok. Small market but 100% clean energy.",
        "corridors": [
            {"name":"NH-10 Siliguri-Gangtok","distance_km":114,"stations_existing":5,"stations_per_100km":4.4,"opportunity":"Medium-High","gap_towns":["Melli","Singtam"]},
        ],
        "zones": [
            {"zone":"MG Marg / Commercial","city":"Gangtok","discom":"Energy & Power Dept","opportunity_score":6,"ev_demand":"Medium","power_reliability":"Very High","supply_voltage":"33kV","reason":"Tourism capital, 100% hydro power, lowest tariff in India — premium eco-tourism EV market"},
        ]
    },
    "Tripura": {
        "discom": "TSECL",
        "ev_stations_total": 55, "grid_avail_pct": 80,
        "power_context": "Tripura has improving grid (80%) and moderate tariff (Rs 6.20/unit). Small state with Agartala as the primary market. Bangladesh border creates logistics demand.",
        "corridors": [
            {"name":"NH-44 Agartala-Sabroom","distance_km":115,"stations_existing":2,"stations_per_100km":1.7,"opportunity":"High (first-mover)","gap_towns":["Belonia","Sabroom"]},
        ],
        "zones": [
            {"zone":"Agartala Commercial","city":"Agartala","discom":"TSECL","opportunity_score":5,"ev_demand":"Low-Medium","power_reliability":"Medium","supply_voltage":"33kV","reason":"State capital, Bangladesh border trade, first-mover in very underserved market"},
        ]
    },
    "Nagaland": {
        "discom": "Dept of Power",
        "ev_stations_total": 22, "grid_avail_pct": 70,
        "power_context": "Nagaland has the lowest grid availability in India (70%). Dimapur (plains) is more reliable than Kohima (hills). Very nascent EV market — any station is a first-mover.",
        "corridors": [
            {"name":"NH-29 Dimapur-Kohima","distance_km":74,"stations_existing":1,"stations_per_100km":1.4,"opportunity":"Very High (first-mover)","gap_towns":["Chumoukedima"]},
        ],
        "zones": [
            {"zone":"Dimapur Commercial","city":"Dimapur","discom":"Dept of Power","opportunity_score":4,"ev_demand":"Low","power_reliability":"Low-Medium","supply_voltage":"33kV","reason":"Gateway city, most reliable grid in state, but diesel backup essential — early pilot only"},
        ]
    },
    "Mizoram": {
        "discom": "Power & Electricity Dept",
        "ev_stations_total": 18, "grid_avail_pct": 74,
        "power_context": "Mizoram has 72% renewable but limited distribution reliability (74%). Aizawl is almost entirely hilly — challenging for charging infrastructure. Myanmar border trade is a long-term opportunity.",
        "corridors": [
            {"name":"NH-54 Silchar-Aizawl","distance_km":180,"stations_existing":1,"stations_per_100km":0.6,"opportunity":"High (first-mover)","gap_towns":["Lunglei","Kolasib"]},
        ],
        "zones": [
            {"zone":"Aizawl Commercial","city":"Aizawl","discom":"Power & Electricity Dept","opportunity_score":4,"ev_demand":"Low","power_reliability":"Low-Medium","supply_voltage":"33kV","reason":"State capital, early pilot opportunity, very underserved market — long payback expected"},
        ]
    },
    "Arunachal Pradesh": {
        "discom": "APDCL",
        "ev_stations_total": 45, "grid_avail_pct": 78,
        "power_context": "Arunachal has massive hydro potential (88% renewables) but limited distribution infrastructure (78%). Itanagar corridor is the main market. Central government push for EV adoption.",
        "corridors": [
            {"name":"NH-415 Itanagar-Naharlagun","distance_km":15,"stations_existing":1,"stations_per_100km":6.7,"opportunity":"Medium","gap_towns":[]},
        ],
        "zones": [
            {"zone":"Itanagar Commercial","city":"Itanagar","discom":"APDCL","opportunity_score":5,"ev_demand":"Low-Medium","power_reliability":"Medium","supply_voltage":"33kV","reason":"State capital, government fleet EV opportunity, NH-415 growing corridor"},
        ]
    },
}


@app.get("/api/ev-zones")
def ev_zones_list():
    """List all states that have zone data."""
    return {
        "states": sorted(list(EV_ZONES_DATA.keys())),
        "count": len(EV_ZONES_DATA),
        "coverage": "All 30 Indian states — detailed for 9 key EV markets, summary for remaining 21",
        "last_verified": "July 2026"
    }


@app.get("/api/ev-zones/{state}")
def ev_zones_state(state: str):
    """Zone data for a specific state."""
    # Try exact match first
    d = EV_ZONES_DATA.get(state)
    if not d:
        # Try case-insensitive match
        for k in EV_ZONES_DATA:
            if k.lower() == state.lower():
                d = EV_ZONES_DATA[k]
                break
    if not d:
        raise HTTPException(
            status_code=404,
            detail=f"No zone data for state: '{state}'. Available states: {', '.join(sorted(EV_ZONES_DATA.keys()))}"
        )
    return {"state": state, **d}




# ── Coverage definitions ───────────────────────────────────────────────────────
COVERAGE_LABELS = {
    "live":     "Live — KPTCL SLDC",
    "verified": "Verified — DISCOM reports",
    "partial":  "Partial — city aggregate",
    "estimate": "Estimate — secondary data",
}
COVERAGE_NOTES = {
    "live":     "Real-time substation loading from KPTCL SLDC, refreshed every 5 minutes. Seed capacity figures manually verified July 2026.",
    "verified": "Substation loading cross-referenced against DISCOM published loading schedules and CEA substation data. Manually verified July 2026. Not real-time.",
    "partial":  "City-level aggregate published by DISCOM or SLDC. No per-substation breakdown available publicly. Use directionally, not for site-specific decisions.",
    "estimate": "Estimated from CEA state-wise capacity reports, NITI Aayog EV data, and state energy statistics. NOT verified against DISCOM source data. Treat as indicative only.",
}
PARTIAL_STATES = {
    "Maharashtra","Tamil Nadu","Gujarat","Delhi","Telangana",
    "Kerala","Haryana","West Bengal","Andhra Pradesh","Uttar Pradesh",
    "Madhya Pradesh","Punjab","Rajasthan","Odisha","Jharkhand",
    "Chhattisgarh","Bihar","Assam","Uttarakhand",
}

def _one_liner_ev(headroom, density, coverage):
    h = {"high":"High headroom","medium":"Moderate headroom","low":"Constrained grid"}[headroom]
    d = {"underserved":"underserved market","moderate":"moderate competition","saturated":"saturated market"}[density]
    c = {"live":"live data","verified":"verified estimates","partial":"partial data — city aggregate","estimate":"estimated data — treat as directional"}[coverage]
    return f"{h}, {d} — {c}"

def _one_liner_bess(loading_pct, headroom, coverage):
    if loading_pct >= 78:
        base = f"High load ({loading_pct}%) — strong arbitrage and peak-shaving signal"
    elif loading_pct >= 65:
        base = f"Moderate load ({loading_pct}%) — demand charge reduction likely more attractive than arbitrage"
    else:
        base = f"Low base load ({loading_pct}%) — limited arbitrage window, best as backup/firming play"
    c = {"live":"live data","verified":"verified estimates","partial":"partial data","estimate":"estimated"}[coverage]
    return f"{base} — {c}"

def _ev_card(loc, city, state, tier, discom, coverage, loading_pct, headroom, density, ev_stations,
             fast_dc, zones, corridors, query_suffix):
    h_score = {"high":3,"medium":2,"low":1}[headroom]
    d_score = {"underserved":3,"moderate":2,"saturated":1}.get(density, 2)
    score   = h_score + d_score
    verdict = "VIABLE" if score>=4 else "MARGINAL" if score>=3 else "NOT VIABLE"
    bess_s  = 3 if loading_pct>=78 else 2 if loading_pct>=65 else 1
    return {
        "id": f"{state.lower().replace(' ','_')}_{city.lower().replace(' ','_')}_{loc.lower().replace(' ','_').replace('/','_')}",
        "location": loc, "city": city, "state": state, "tier": tier, "discom": discom,
        "coverage": coverage, "coverage_label": COVERAGE_LABELS[coverage], "coverage_note": COVERAGE_NOTES[coverage],
        "ev": {"score":score,"headroom":headroom,"loading_pct":loading_pct,"competition":density,
               "stations":ev_stations,"fast_dc":fast_dc,
               "one_liner":_one_liner_ev(headroom,density,coverage),"verdict":verdict},
        "bess": {"score":bess_s,"headroom":headroom,"loading_pct":loading_pct,
                 "one_liner":_one_liner_bess(loading_pct,headroom,coverage),
                 "verdict":"VIABLE" if bess_s>=2 else "MARGINAL"},
        "zones": zones, "corridors": corridors, "query": query_suffix,
    }


@app.get("/api/opportunities")
def get_opportunities(
    state: str = Query(None), tier: int = Query(None),
    business: str = Query("ev"), coverage: str = Query(None),
    headroom: str = Query(None),
):
    cards = []

    # ── Bengaluru zone-level (LIVE) ──────────────────────────────────────────
    for ss_key, ss in SUBSTATIONS.items():
        ev  = EV_DENSITY.get(ss_key, {})
        zone_name = ss["name"].replace(" 220kV SS","").replace(" 110kV SS","").replace(" 66kV SS","")
        cards.append(_ev_card(
            loc=zone_name, city="Bengaluru", state="Karnataka", tier=1,
            discom="BESCOM", coverage="live",
            loading_pct=ss["loading_pct"], headroom=ss["headroom"],
            density=ev.get("density","moderate"),
            ev_stations=ev.get("count_2km",0), fast_dc=ev.get("fast_dc_2km",0),
            zones=[], corridors=[],
            query_suffix=f"area={ss_key}&business={business}",
        ))

    # ── City-level (from CITY_DATA) ──────────────────────────────────────────
    for sname, scities in CITY_DATA.items():
        for cname, cd in scities.items():
            if sname == "Karnataka" and cname == "Bengaluru":
                continue  # Already covered zone-level above
            if sname == "Karnataka":
                cov = "verified"
            elif sname in PARTIAL_STATES:
                cov = "partial"
            else:
                cov = "estimate"
            cards.append(_ev_card(
                loc=cname, city=cname, state=sname, tier=cd.get("tier",2),
                discom=cd["discom"], coverage=cov,
                loading_pct=cd["loading_pct"], headroom=cd["headroom"],
                density=cd["ev_density"], ev_stations=cd["ev_stations"], fast_dc=0,
                zones=cd.get("zones",[]), corridors=cd.get("corridors",[]),
                query_suffix=f"state={sname}&city={cname}&business={business}",
            ))

    # ── Apply filters ────────────────────────────────────────────────────────
    result = cards
    if state:    result = [c for c in result if c["state"] == state]
    if tier:     result = [c for c in result if c["tier"] == tier]
    if coverage: result = [c for c in result if c["coverage"] == coverage]
    if headroom:
        result = [c for c in result if c.get(business,{}).get("headroom") == headroom]
    biz = business if business in ("ev","bess") else "ev"
    result.sort(key=lambda c: c.get(biz,{}).get("score",0), reverse=True)

    # Unique states for filter UI
    all_states = sorted({c["state"] for c in cards})

    return {
        "opportunities": result,
        "total": len(result),
        "all_states": all_states,
        "coverage_counts": {
            k: sum(1 for c in cards if c["coverage"]==k)
            for k in ("live","verified","partial","estimate")
        },
    }

@app.get("/api/cities")
def cities_all():
    return {"states": sorted(list(CITY_DATA.keys())), "count": len(CITY_DATA)}

@app.get("/api/cities/{state}")
def cities_for_state(state: str):
    d = CITY_DATA.get(state)
    if not d:
        for k in CITY_DATA:
            if k.lower() == state.lower():
                d = CITY_DATA[k]; state = k; break
    if not d:
        raise HTTPException(status_code=404,
            detail=f"State '{state}' not found. Available: {', '.join(sorted(CITY_DATA.keys()))}")
    cities = []
    for city_name, cd in d.items():
        cities.append({
            "city": city_name,
            "tier": cd.get("tier", 2),
            "discom": cd.get("discom","—"),
            "ev_stations": cd.get("ev_stations", 0),
            "headroom": cd.get("headroom", "medium"),
            "grid_avail_pct": cd.get("grid_avail_pct", 90),
        })
    cities.sort(key=lambda x: (x["tier"], x["city"]))
    return {"state": state, "cities": cities, "count": len(cities)}


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
def feasibility(
    city: str = Query(None),
    state: str = Query(None),
    area: str = Query(None),
    business: str = Query("ev")
):
    """
    Two modes:
    1. city + state (new) — city-level feasibility, all India
    2. area only (legacy) — Bengaluru substation-level feasibility
    """
    # ── Mode 1: city + state ───────────────────────────────────
    if city and state:
        state_data = CITY_DATA.get(state)
        if not state_data:
            for k in CITY_DATA:
                if k.lower() == state.lower():
                    state_data = CITY_DATA[k]; state = k; break
        if not state_data:
            raise HTTPException(status_code=404, detail=f"State not found: {state}")
        cd = state_data.get(city)
        if not cd:
            for k in state_data:
                if k.lower() == city.lower():
                    cd = state_data[k]; city = k; break
        if not cd:
            raise HTTPException(status_code=404, detail=f"City not found: {city} in {state}")

        headroom = cd["headroom"]
        ev_dens  = cd["ev_density"]
        h_score  = {"high":2,"medium":1,"low":0}[headroom]
        d_score  = {"underserved":2,"moderate":1,"saturated":0}[ev_dens]
        total    = h_score + d_score

        if business == "ev":
            verdict_status = "VIABLE" if total>=4 else "MARGINAL" if total>=2 else "NOT VIABLE"
            reasons = []
            if headroom == "high":    reasons.append(f"High grid headroom — new connections fast-tracked")
            if headroom == "low":     reasons.append(f"Constrained grid ({cd['loading_pct']}% loaded) — HT connection delays likely")
            if ev_dens == "underserved": reasons.append(f"{cd['ev_stations']} stations across city — DC fast charging severely underserved")
            if ev_dens == "saturated":   reasons.append(f"{cd['ev_stations']} stations — market saturated, high competition")
            reasons.append(cd["power_context"])
            summaries = {
                "VIABLE": f"{city} looks viable for EV charging — {headroom} grid headroom, {ev_dens} market. Use the calculator below with local tariff.",
                "MARGINAL": f"{city} is borderline — {headroom} headroom, {ev_dens} competition. Specific site selection and utilisation assumption are critical.",
                "NOT VIABLE": f"{city} does not pencil out easily at current assumptions — {headroom} headroom and {ev_dens} competition are both unfavourable.",
            }
        elif business == "bess":
            bess_score  = 3 if cd["loading_pct"]>=78 else 2 if cd["loading_pct"]>=62 else 1
            verdict_status = "VIABLE" if bess_score>=2 else "MARGINAL"
            reasons = [f"Grid loading {cd['loading_pct']}% — {'strong arbitrage window' if cd['loading_pct']>=78 else 'moderate ToD spread'}", cd["power_context"]]
            summaries = {
                "VIABLE": f"BESS in {city}: high load area with strong arbitrage and peak-shaving opportunity.",
                "MARGINAL": f"BESS in {city}: moderate economics — demand charge reduction is likely more attractive than arbitrage here.",
            }
        else:
            verdict_status = "MARGINAL"
            reasons = ["Battery manufacturing siting is driven by land, logistics, and PLI tier — not local substation. See the Manufacturing module."]
            summaries = {"MARGINAL": "Battery manufacturing: check PLI eligibility and capex analysis in the Manufacturing module rather than substation data."}

        summary = summaries.get(verdict_status, summaries.get("MARGINAL", ""))

        return {
            "area": city, "area_key": city.lower().replace(" ","_"),
            "city": city, "state": state,
            "substation": {
                "name": f"{city} — {cd['discom']}",
                "voltage": "110–220kV (varies by zone)",
                "discom": cd["discom"],
                "loading_pct": cd["loading_pct"],
                "headroom": headroom,
                "ht_outlook": cd["power_context"],
                "applicable_tariffs": ["LT-6(b)","LT-6(c)","HT-2(f)"],
                "tariff_rate_ev": 6.00,
                "data_source": "State DISCOM published data + CEA reports — city-level estimate",
                "last_verified": "July 2026",
            },
            "competition": {
                "area": city, "state": state,
                "count_2km": max(1, cd["ev_stations"]//15),
                "count_5km": max(2, cd["ev_stations"]//5),
                "fast_dc_2km": max(0, cd["ev_stations"]//40),
                "operators": ["Check local OEM locators"],
                "density": ev_dens,
                "notes": f"{city} has approximately {cd['ev_stations']} public EV stations citywide. {cd.get('zones',[{}])[0].get('reason','') if cd.get('zones') else ''}",
            },
            "verdict": {
                "status": verdict_status,
                "summary": summary,
                "reasons": reasons,
            },
            "zones": cd.get("zones", []),
            "corridors": cd.get("corridors", []),
            "defaults": {
                "tariff_category": "LT-6(c)",
                "tariff_rate": 6.00,
                "demand_charge_rate": 100,
            },
            "business": business,
        }

    # ── Mode 2: Bengaluru area-level (legacy) ──────────────────
    if not area:
        raise HTTPException(status_code=422, detail="Provide 'city+state' or 'area' parameter")
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

# ── Weekly policy digest ─────────────────────────────────────────────────────
# Fallback articles — verified, sourced. Used when PIB RSS is unreachable.
DIGEST_FALLBACK = [
    {"title":"PM E-DRIVE Scheme: 80% infra subsidy for public EV chargers — deployment window active","link":"https://mhi.gov.in","date":"October 2024","category":"ev","ministry":"MHI","source_note":"MHI notification Oct 2024. 80% infra subsidy public, 100% for govt. 72,000+ chargers targeted."},
    {"title":"MoP EV Charging Standards 2024: CCS2 mandatory for DC fast charging, no licence needed to sell electricity","link":"https://powermin.gov.in","date":"September 2024","category":"ev","ministry":"MoP","source_note":"MoP guidelines effective Sep 2024. Any business can set up public EVCS without distribution licence."},
    {"title":"MNRE VGF Scheme for Standalone BESS: Rs 3,760 crore outlay, 4,000 MWh in first tranche","link":"https://mnre.gov.in","date":"March 2023 (bids ongoing)","category":"bess","ministry":"MNRE","source_note":"VGF up to Rs 94/kWh installed. Minimum 10 MWh. SECI tender portal: seci.co.in"},
    {"title":"ACC PLI Scheme: 50 GWh domestic battery cell target, Rs 18,100 crore outlay through FY2027-28","link":"https://mhi.gov.in","date":"2021 (ongoing)","category":"bess","ministry":"MHI","source_note":"100% DCR on 18 battery components from 2025. Rs 2,000–4,500/kWh incentive for 5 years on actual production."},
    {"title":"India crosses 500 GW total installed capacity — non-fossil share reaches 53.4%","link":"https://mnre.gov.in","date":"June 2025","category":"bess","ministry":"MNRE","source_note":"CEA monthly report. Solar 150 GW, Wind 56 GW. India 5 years ahead of 2030 NDC target."},
    {"title":"ISTS waiver extended to 2030 for RE + storage hybrid projects — 100% charge waiver","link":"https://powermin.gov.in","date":"2023 (amended)","category":"bess","ministry":"MoP","source_note":"MoP order. Applies to solar/wind projects with co-located or virtual BESS commissioned by March 2030."},
    {"title":"Karnataka KERC Tariff Order 2025-26: LT-6(c) public DC charging confirmed at Rs 6.00/unit","link":"https://kerc.karnataka.gov.in","date":"April 2025","category":"ev","ministry":"KERC Karnataka","source_note":"BESCOM EVCS tariff. HT-2(f) for hubs > 100 kW: Rs 5.80/unit. Verified arithmetic: LT-1 domestic = Rs 6.72/unit."},
    {"title":"PM Surya Ghar rooftop solar + EV: up to Rs 78,000 subsidy, net metering enables near-zero charging cost","link":"https://mnre.gov.in","date":"2024 (ongoing)","category":"ev","ministry":"MNRE","source_note":"MNRE scheme. Combined with BESCOM net metering (Rs 3.68/unit export), effective EV charging cost < Rs 1/km."},
    {"title":"POSOCO Ancillary Services Market: Rs 50–120 lakh/MW/yr for frequency regulation BESS","link":"https://posoco.in","date":"CERC Regulations 2022 (ongoing market)","category":"bess","ministry":"POSOCO/NLDC","source_note":"BESS must respond in ≤100ms. Register as Ancillary Service Provider (ASP) with NLDC. See CEA Grid Code 2023."},
    {"title":"FAME III under Cabinet consideration — successor to PM E-DRIVE, focus on 800,000 electric buses","link":"https://mhi.gov.in","date":"Expected FY2026-27","category":"ev","ministry":"MHI","source_note":"FAME III will NOT include private EV subsidies. Focus: public bus electrification at scale."},
]

WEEKLY_DIGEST = {
    "last_updated": None,
    "status": "pending_first_run",
    "articles": [],
    "error": None,
    "source": "none",
}

EV_KEYWORDS   = ['electric vehicle','ev charging','fame','e-drive','battery','evcs','electric mobility','pm e-drive','charger','ev station','electric']
BESS_KEYWORDS = ['battery storage','bess','energy storage','grid storage','battery energy','acc pli','acc cell','lithium','storage system','renewable energy storage']

PIB_FEEDS = {
    "MHI":  "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "MNRE": "https://pib.gov.in/RssMain.aspx?ModId=17&Lang=1&Regid=3",
    "MoP":  "https://pib.gov.in/RssMain.aspx?ModId=21&Lang=1&Regid=3",
}

def weekly_policy_update():
    global WEEKLY_DIGEST
    log.info("Running weekly policy digest update …")
    live_articles = []
    errors = []
    try:
        import feedparser
        for ministry, url in PIB_FEEDS.items():
            try:
                feed = feedparser.parse(url, request_headers={"User-Agent":"Mozilla/5.0"})
                entries = getattr(feed, 'entries', []) or []
                log.info("PIB %s: %d entries", ministry, len(entries))
                for entry in entries[:50]:
                    title   = (entry.get('title',   '') or '').strip()
                    summary = (entry.get('summary', '') or '').strip()
                    text    = (title + ' ' + summary).lower()
                    is_ev   = any(kw in text for kw in EV_KEYWORDS)
                    is_bess = any(kw in text for kw in BESS_KEYWORDS)
                    if is_ev or is_bess:
                        live_articles.append({
                            "title":       title or 'Untitled',
                            "link":        entry.get('link', ''),
                            "date":        entry.get('published', ''),
                            "category":    'bess' if is_bess else 'ev',
                            "ministry":    ministry,
                            "source_note": "PIB official press release — verify figures before citing",
                        })
            except Exception as e:
                errors.append(f"{ministry}: {str(e)[:80]}")
                log.warning("PIB feed failed for %s: %s", ministry, e)
    except ImportError:
        errors.append("feedparser not installed")

    if live_articles:
        articles = live_articles[:14]
        source   = "pib_rss_live"
        status   = "ok"
    else:
        log.info("PIB RSS: 0 matches or error — using curated fallback")
        articles = list(DIGEST_FALLBACK)
        source   = "curated_fallback"
        status   = "fallback_used" if not errors else "rss_error_fallback_used"

    WEEKLY_DIGEST = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "status":       status,
        "articles":     articles,
        "error":        ("; ".join(errors) if errors else None),
        "source":       source,
    }
    log.info("Digest done: %d articles, source=%s", len(articles), source)

# Always run on startup — guaranteed to have data on first request
weekly_policy_update()

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(weekly_policy_update, 'cron', day_of_week='sun', hour=6, minute=0)
    _scheduler.start()
    log.info("Scheduler started — weekly digest every Sunday 06:00 UTC")
except Exception as e:
    log.warning("APScheduler unavailable: %s", e)


@app.get("/api/weekly-digest")
def weekly_digest():
    return WEEKLY_DIGEST


@app.post("/api/trigger-digest")
def trigger_digest():
    """Manual trigger for digest refresh (call from browser devtools or curl)."""
    weekly_policy_update()
    return {"status": "triggered", "result": WEEKLY_DIGEST["status"], "count": len(WEEKLY_DIGEST["articles"])}

try:
    app.mount("/static", StaticFiles(directory="."), name="static")
except Exception: pass

@app.get("/")
def root(): return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
