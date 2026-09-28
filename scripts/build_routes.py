import gzip
import os
import sqlite3
import struct
import sys
import tempfile
import urllib.request

# Official Virtual Radar Server Standing Data (Callsigns & Routes)
SOURCE_URL = "http://www.virtualradarserver.co.uk/Files/StandingData.sqb.gz"
OUTPUT_BIN = "routes_na.bin"
TARGET_MAX_RECORDS = 22500  # Stays under 360 KB for ESP32 LittleFS

# North American mainline, regional feeder, and cargo callsign prefixes
NA_PREFIXES = {
    # Major US Mainline
    "AAL", "DAL", "UAL", "SWA", "ASA", "JBU", "FFT", "NKS", "HAL",
    # Cargo Giants
    "FDX", "UPS", "GTI", "ATN", "ABX",
    # Canadian & Mexican Mainline
    "ACA", "WJA", "TSC", "ROU", "AMX", "VOI", "VIV",
    # Regional Feeders (SkyWest, Republic, Envoy, Endeavor, PSA, Piedmont, Mesa, GoJet)
    "SKW", "RPA", "ENY", "EDV", "JIA", "PDT", "ASH", "GJS", "QXE", "CPZ",
    # Charter / Commuter / Leisure
    "SCX", "MXY", "EJA"
}

def clean_code(code: str) -> str:
    """Normalizes 4-letter US ICAO (KLGA) to 3-letter (LGA) or preserves 3-letter IATA."""
    if not code:
        return "---"
    code = code.strip().upper()
    if len(code) == 4 and code.startswith("K"):
        return code[1:4]
    return code[:3]

def fetch_and_pack():
    temp_gz = tempfile.NamedTemporaryFile(delete=False, suffix=".gz")
    temp_sqb = tempfile.NamedTemporaryFile(delete=False, suffix=".sqb")
    temp_gz.close()
    temp_sqb.close()

    try:
        print(f"Downloading standing data from {SOURCE_URL}...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        req = urllib.request.Request(SOURCE_URL, headers=headers)
        
        with urllib.request.urlopen(req, timeout=60) as resp, open(temp_gz.name, "wb") as f_out:
            while chunk := resp.read(65536):
                f_out.write(chunk)

        print("Decompressing SQLite database...")
        with gzip.open(temp_gz.name, "rb") as f_in, open(temp_sqb.name, "wb") as f_out:
            while chunk := f_in.read(65536):
                f_out.write(chunk)

        print("Querying route tables...")
        conn = sqlite3.connect(temp_sqb.name)
        cursor = conn.cursor()

        # Discover schema table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        routes = {}

        # VRS schemas store callsign pairings in FlightRoute or Route
        target_table = None
        for t in ["FlightRoute", "Route", "CallsignRoute"]:
            if t in tables:
                target_table = t
                break

        if not target_table:
            print(f"Error: Could not identify route table. Available tables: {tables}")
            sys.exit(1)

        # Inspect table columns
        cursor.execute(f"PRAGMA table_info({target_table});")
        cols = [c[1].lower() for c in cursor.fetchall()]

        cs_col = next((c for c in cols if "callsign" in c), None)
        from_col = next((c for c in cols if c in ["from", "fromairport", "orig", "origin"]), None)
        to_col = next((c for c in cols if c in ["to", "toairport", "dest", "destination"]), None)

        if not (cs_col and from_col and to_col):
            print(f"Error: Missing route columns in {target_table}. Columns found: {cols}")
            sys.exit(1)

        query = f"SELECT {cs_col}, {from_col}, {to_col} FROM {target_table} WHERE {cs_col} IS NOT NULL"
        cursor.execute(query)

        for row in cursor.fetchall():
            raw_cs = str(row[0]).strip().upper()
            raw_from = str(row[1]).strip().upper() if row[1] else ""
            raw_to = str(row[2]).strip().upper() if row[2] else ""

            if len(raw_cs) < 4 or not raw_from or not raw_to:
                continue

            prefix = raw_cs[:3]
            if prefix in NA_PREFIXES:
                orig = clean_code(raw_from)
                dest = clean_code(raw_to)
                if orig != "---" and dest != "---":
                    routes[raw_cs] = (orig, dest)

        conn.close()
        print(f"Extracted {len(routes)} valid North American commercial routes.")

        # Sort alphabetically by callsign for ESP32 bsearch()
        sorted_callsigns = sorted(routes.keys())
        if len(sorted_callsigns) > TARGET_MAX_RECORDS:
            sorted_callsigns = sorted_callsigns[:TARGET_MAX_RECORDS]

        print(f"Packing {len(sorted_callsigns)} routes into {OUTPUT_BIN}...")
        packed_data = bytearray()
        record_format = "<8s4s4s"

        for cs in sorted_callsigns:
            orig, dest = routes[cs]
            packed_data.extend(
                struct.pack(
                    record_format,
                    cs.encode("ascii", "ignore"),
                    orig.encode("ascii", "ignore"),
                    dest.encode("ascii", "ignore")
                )
            )

        with open(OUTPUT_BIN, "wb") as f_bin:
            f_bin.write(packed_data)

        size_kb = len(packed_data) / 1024.0
        print(f"Success: {OUTPUT_BIN} generated ({len(sorted_callsigns)} entries, {size_kb:.2f} KB)")

    finally:
        if os.path.exists(temp_gz.name):
            os.remove(temp_gz.name)
        if os.path.exists(temp_sqb.name):
            os.remove(temp_sqb.name)

if __name__ == "__main__":
    fetch_and_pack()
