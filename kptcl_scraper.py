"""
KPTCL SLDC Scraper
Scrapes 3 public pages from kptclsldc.in (no auth required):
  - StateGen.aspx   → plant-level generation, frequency, source breakdown
  - Snapshot.aspx   → ESCOM schedule vs actual demand (BESCOM + all ESCOMs)
  - StateNCEP.aspx  → renewable breakdown (solar/wind/bio) per ESCOM

Usage:
    from kptcl_scraper import get_all
    data = get_all()   # returns combined dict
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://kptclsldc.in"
HEADERS = {
    "User-Agent": (
        "KarnatakaGridMonitor/1.0 (public data research; "
        "contact your@email.com)"
    )
}
TIMEOUT = 15  # seconds


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _get(path: str) -> BeautifulSoup:
    """Fetch a SLDC page and return a parsed BeautifulSoup object."""
    resp = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _float(s: str) -> float | None:
    """Safe string → float, ignoring non-numeric chars except . and -"""
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except (ValueError, TypeError):
        return None


def _int(s: str) -> int | None:
    val = _float(s)
    return int(val) if val is not None else None


def _extract_bold_value(soup: BeautifulSoup, label: str) -> str | None:
    """
    Finds <b>LABEL</b> : VALUE or <strong>LABEL</strong> : VALUE
    in the page and returns VALUE as stripped string.
    """
    for tag in soup.find_all(["b", "strong"]):
        if label.lower() in tag.get_text(strip=True).lower():
            # value might be in the next sibling text
            nxt = tag.next_sibling
            if nxt:
                val = str(nxt).strip().lstrip(":").strip()
                if val:
                    return val
            # or in the parent text after the tag
            parent_text = tag.parent.get_text(" ", strip=True)
            m = re.search(re.escape(label) + r"[\s:]+([0-9.]+)", parent_text, re.I)
            if m:
                return m.group(1)
    return None


def _parse_tables(soup: BeautifulSoup):
    """Return all <table> rows as list-of-lists of stripped strings."""
    tables = []
    for tbl in soup.find_all("table"):
        rows = []
        for tr in tbl.find_all("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cols):
                rows.append(cols)
        if rows:
            tables.append(rows)
    return tables


# ─────────────────────────────────────────────────────────────────
# Page 1: StateGen.aspx  – Generation & Frequency
# ─────────────────────────────────────────────────────────────────

PLANT_TYPE_MAP = {
    # Thermal
    "RTPS": "thermal", "BTPS": "thermal", "YTPS": "thermal", "YCCP": "thermal",
    # Major hydro
    "SHARAVATHI": "hydro_major", "NAGJHARI": "hydro_major", "VARAHI": "hydro_major",
    "KODSALLI": "hydro_major", "KADRA": "hydro_major", "GERUSOPPA": "hydro_major",
    # Other hydro
    "JOG": "hydro_other", "LPH": "hydro_other", "SUPA": "hydro_other",
    "SHIMSHA": "hydro_other", "SHIVASAMUDRA": "hydro_other",
    "MANIDAM": "hydro_other", "MUNRABAD": "hydro_other", "BHADRA": "hydro_other",
    "GHATAPRABHA": "hydro_other", "ALMATTI": "hydro_other",
    # IPPs
    "JINDAL": "ipp_thermal", "UPCL": "ipp_thermal",
}


def scrape_generation() -> dict:
    """
    Returns:
        frequency_hz        : float
        total_generation_mw : int  (all sources incl CGS + NCEP)
        own_gen_mw          : int  (Karnataka own plants only)
        ncep_mw             : int  (non-conventional energy)
        cgs_mw              : int  (central generating stations)
        source_breakdown    : dict  {thermal, hydro_major, hydro_other, ipp_thermal}
        plants              : list[dict]  per-plant detail
        timestamp           : str
        page_url            : str
    """
    soup = _get("StateGen.aspx")
    full_text = soup.get_text(" ")

    # ── Frequency ──────────────────────────────────────────────
    freq_match = re.search(r"FREQUENCY\s*[:\-]?\s*([\d.]+)\s*Hz", full_text, re.I)
    frequency = float(freq_match.group(1)) if freq_match else None

    # ── Totals from bold markers ────────────────────────────────
    total_match = re.search(r"TOTAL\s+GENERATION\s*[:\-]?\s*([\d,]+)\s*MW", full_text, re.I)
    total_gen = _int(total_match.group(1).replace(",", "")) if total_match else None

    ncep_match = re.search(r"\bNCEP\b\s*[:\-]?\s*([\d,]+)\s*MW", full_text, re.I)
    ncep = _int(ncep_match.group(1).replace(",", "")) if ncep_match else None

    cgs_match = re.search(r"\bCGS\b\s*[:\-]?\s*([\d,]+)\s*MW", full_text, re.I)
    cgs = _int(cgs_match.group(1).replace(",", "")) if cgs_match else None

    # ── Timestamp ───────────────────────────────────────────────
    ts_match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", full_text)
    timestamp = ts_match.group(1) if ts_match else None

    # ── Plant table + source breakdown ──────────────────────────
    plants = []
    source_breakdown = {
        "thermal": 0, "hydro_major": 0,
        "hydro_other": 0, "ipp_thermal": 0,
    }

    tables = _parse_tables(soup)
    own_gen = 0
    for tbl in tables:
        for row in tbl:
            if not row or len(row) < 3:
                continue
            name = row[0].upper().strip()
            if name in PLANT_TYPE_MAP and name != "TOTAL":
                cap = _int(row[1]) if len(row) > 1 else None
                gen = _int(row[2]) if len(row) > 2 else None
                plant_type = PLANT_TYPE_MAP[name]
                plants.append({
                    "name": name,
                    "type": plant_type,
                    "capacity_mw": cap,
                    "generation_mw": gen if gen is not None else 0,
                })
                if gen:
                    source_breakdown[plant_type] = (
                        source_breakdown.get(plant_type, 0) + gen
                    )
                    own_gen += gen

    return {
        "frequency_hz": frequency,
        "total_generation_mw": total_gen,
        "own_gen_mw": own_gen or None,
        "ncep_mw": ncep,
        "cgs_mw": cgs,
        "source_breakdown": source_breakdown,
        "plants": plants,
        "timestamp": timestamp,
        "page_url": f"{BASE}/StateGen.aspx",
    }


# ─────────────────────────────────────────────────────────────────
# Page 2: Snapshot.aspx  – ESCOM Demand (Schedule vs Actual)
# ─────────────────────────────────────────────────────────────────

def scrape_demand() -> dict:
    """
    Returns:
        frequency_hz    : float
        state_gen_mw    : int
        cgs_actual_mw   : int
        ncep_mw         : int
        escom_loads     : list[dict]  {escom, schedule, actual, ui}
        bescom          : dict        shortcut for BESCOM row
        timestamp       : str
        page_url        : str
    """
    soup = _get("Snapshot.aspx")
    full_text = soup.get_text(" ")

    freq_match = re.search(r"([\d.]+)\s*\n?\s*FREQUENCY", full_text, re.I)
    if not freq_match:
        freq_match = re.search(r"FREQUENCY\s*[\(Hz\)]*\s*[:\-]?\s*([\d.]+)", full_text, re.I)
    frequency = float(freq_match.group(1)) if freq_match else None

    ts_match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", full_text)
    timestamp = ts_match.group(1) if ts_match else None

    escom_loads = []
    tables = _parse_tables(soup)

    ESCOM_NAMES = {"BESCOM", "MESCOM", "CESC", "GESCOM", "HESCOM"}
    state_row = {}

    for tbl in tables:
        for row in tbl:
            if not row:
                continue
            name = row[0].upper().strip()

            # State-level demand row: STATE GEN | CGS | NCEPs | TOTAL
            if "STATE" in name and "GEN" in name and len(row) >= 3:
                state_row = {
                    "state_gen_mw": _int(row[1]) if len(row) > 1 else None,
                    "cgs_actual_mw": _int(row[2]) if len(row) > 2 else None,
                    "ncep_mw": _int(row[3]) if len(row) > 3 else None,
                }

            if name in ESCOM_NAMES and len(row) >= 4:
                escom_loads.append({
                    "escom": name,
                    "schedule_mw": _int(row[1]),
                    "actual_mw": _int(row[2]),
                    "ui_mw": _int(row[3]),  # Unscheduled Interchange: +ve = drew more
                })

    bescom = next((e for e in escom_loads if e["escom"] == "BESCOM"), None)

    return {
        "frequency_hz": frequency,
        **state_row,
        "escom_loads": escom_loads,
        "bescom": bescom,
        "timestamp": timestamp,
        "page_url": f"{BASE}/Snapshot.aspx",
    }


# ─────────────────────────────────────────────────────────────────
# Page 3: StateNCEP.aspx  – Renewable breakdown per ESCOM
# ─────────────────────────────────────────────────────────────────

def scrape_ncep() -> dict:
    """
    Returns:
        escom_ncep  : list[dict]  {escom, biomass, cogen, mini_hydro, wind, solar, total}
        totals      : dict        sum row
        frequency_hz: float
        timestamp   : str
        page_url    : str
    """
    soup = _get("StateNCEP.aspx")
    full_text = soup.get_text(" ")

    freq_match = re.search(r"([\d.]+)\s*\n?\s*FREQUENCY", full_text, re.I)
    if not freq_match:
        freq_match = re.search(r"FREQUENCY\s*[:\-]?\s*([\d.]+)", full_text, re.I)
    frequency = float(freq_match.group(1)) if freq_match else None

    ts_match = re.search(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", full_text)
    timestamp = ts_match.group(1) if ts_match else None

    ESCOM_NAMES = {"BESCOM", "MESCOM", "CESC", "GESCOM", "HESCOM"}
    escom_ncep = []
    totals = {}

    tables = _parse_tables(soup)
    for tbl in tables:
        for row in tbl:
            if not row:
                continue
            name = row[0].upper().strip()
            if name in ESCOM_NAMES and len(row) >= 6:
                escom_ncep.append({
                    "escom": name,
                    "biomass_mw": _int(row[1]),
                    "cogen_mw": _int(row[2]),
                    "mini_hydro_mw": _int(row[3]),
                    "wind_mw": _int(row[4]),
                    "solar_mw": _int(row[5]),
                    "total_mw": _int(row[6]) if len(row) > 6 else None,
                })
            elif "TOTAL" in name and len(row) >= 6:
                totals = {
                    "biomass_mw": _int(row[1]),
                    "cogen_mw": _int(row[2]),
                    "mini_hydro_mw": _int(row[3]),
                    "wind_mw": _int(row[4]),
                    "solar_mw": _int(row[5]),
                    "total_mw": _int(row[6]) if len(row) > 6 else None,
                }

    return {
        "escom_ncep": escom_ncep,
        "totals": totals,
        "frequency_hz": frequency,
        "timestamp": timestamp,
        "page_url": f"{BASE}/StateNCEP.aspx",
    }


# ─────────────────────────────────────────────────────────────────
# Combined
# ─────────────────────────────────────────────────────────────────

def get_all() -> dict:
    """
    Scrape all three pages and return a unified dict.
    Raises requests.RequestException on network failure.
    """
    gen = scrape_generation()
    demand = scrape_demand()
    ncep = scrape_ncep()
    return {
        "generation": gen,
        "demand": demand,
        "ncep": ncep,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────────────────────────────────────────────────
# CLI test
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    data = get_all()
    print(json.dumps(data, indent=2))
