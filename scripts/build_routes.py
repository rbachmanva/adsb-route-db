import gzip
import os
import sqlite3
import struct
import sys
import tempfile
import urllib.request

SOURCE_URL = "http://www.virtualradarserver.co.uk/Files/StandingData.sqb.gz"
OUTPUT_BIN = "routes_na.bin"
TARGET_MAX_RECORDS = 25000  # Stays under 400 KB for ESP32 LittleFS

# North American mainline, regionals, cargo, and major international hub visitors
TARGET_PREFIXES = {
    # US Mainline & Low Cost
    "UAL", "DAL", "AAL", "SWA", "JBU", "ASA", "FFT", "NKS", "AAY", "MXY", "HAL", "SCX", "APF",
    # Regional Feeders (SkyWest, Republic, Envoy, Endeavor, PSA, Piedmont, Mesa, GoJet)
    "SKW", "RPA", "ENY", "EDV", "JIA", "PDT", "ASH", "GJS", "CPZ", "SIL", "POE", "CPA", "JZA", "WEN",
    # Cargo Carriers
    "FDX", "UPS", "GTI", "ABX", "ATN", "PAC", "CLX", "CKS", "AJT", "WGN", "BOX",
    # Canada & Mexico / Central America
    "ACA", "WJA", "TSC", "ROU", "AMX", "VOI", "VIV", "CMP", "AVA",
    # Frequent Transatlantic & Transpacific Hub Visitors
    "BAW", "AFR", "DLH", "VIR", "KLM", "EIN", "IBE", "TAP", "SWR", "AUA", "SAS", "ICE", "LOT",
    "THY", "QTR", "UAE", "ETD", "ETH", "ANA", "JAL", "KAL",
    # Business Jet & VIP
    "EJA", "XOJ", "VJT", "SAM", "EXEC"
}

def clean_airport_code(iata: str, icao: str) -> str:
    """Normalizes airport to 3-letter IATA or stripped 3-letter ICAO."""
    if iata and iata != "NULL" and len(iata) == 3:
        return iata.strip().upper()
    if icao and icao != "NULL":
        code = icao.strip().upper()
        if len(code) == 4 and code.startswith("K"):
            return code[1:4]
        return code[:3]
    return ""

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

        print("Querying database tables...")
        conn = sqlite3.connect(temp_sqb.name)
        cursor = conn.cursor()

        # 1. Discover Tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0].lower(): row[0] for row in cursor.fetchall()}
        print(f"Tables found: {list(tables.values())}")

        airport_tbl = tables.get("airport") or tables.get("airports")
        route_tbl = tables.get("route") or tables.get("flightroute")

        if not airport_tbl or not route_tbl:
            print(f"Error: Missing required tables. Found: {list(tables.values())}")
            sys.exit(1)

        # 2. Map Airport IDs to 3-Letter Airport Codes
        cursor.execute(f"PRAGMA table_info({airport_tbl});")
        ap_cols = {c[1].lower(): c[1] for c in cursor.fetchall()}
        id_col = ap_cols.get("airportid") or ap_cols.get("id")
        iata_col = ap_cols.get("iata") or ap_cols.get("iatacode")
        icao_col = ap_cols.get("icao") or ap_cols.get("icaocode")

        print(f"Mapping airports using {airport_tbl} ({id_col}, {iata_col}, {icao_col})...")
        cursor.execute(f"SELECT {id_col}, {iata_col}, {icao_col} FROM {airport_tbl}")
        
        airport_map = {}
        for row in cursor.fetchall():
            ap_id = row[0]
            iata = str(row[1]).strip() if row[1] else ""
            icao = str(row[2]).strip() if row[2] else ""
            code = clean_airport_code(iata, icao)
            if code:
                airport_map[ap_id] = code

        print(f"Loaded {len(airport_map)} airports.")

        # 3. Query Routes and Resolve Foreign Keys
        cursor.execute(f"SELECT callsign, fromairportid, toairportid FROM {route_tbl} WHERE callsign IS NOT NULL ORDER BY routeid ASC")
        
        routes = {}
        for row in cursor.fetchall():
            raw_cs = str(row[0]).strip().upper()
            from_id = row[1]
            to_id = row[2]

            if len(raw_cs) < 4:
                continue

            prefix = raw_cs[:3]
            if prefix in TARGET_PREFIXES:
                orig = airport_map.get(from_id)
                dest = airport_map.get(to_id)
                if orig and dest and orig != dest:
                    routes[raw_cs] = (orig, dest)

        conn.close()
        print(f"Resolved {len(routes)} target commercial routes.")

        # 4. Sort alphabetically for O(log N) bsearch on ESP32
        sorted_callsigns = sorted(routes.keys())
        if len(sorted_callsigns) > TARGET_MAX_RECORDS:
            sorted_callsigns = sorted_callsigns[:TARGET_MAX_RECORDS]

        # 5. Pack into 16-byte records: <8s4s4s
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
        print(f"Success: Generated {OUTPUT_BIN} ({len(sorted_callsigns)} entries, {size_kb:.2f} KB)")

    finally:
        if os.path.exists(temp_gz.name):
            os.remove(temp_gz.name)
        if os.path.exists(temp_sqb.name):
            os.remove(temp_sqb.name)

if __name__ == "__main__":
    fetch_and_pack()
