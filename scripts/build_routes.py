import csv
import io
import struct
import urllib.request

ROUTES_URL   = "https://vrs-standing-data.adsb.lol/routes.csv"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUTPUT_BIN   = "routes_na.bin"
MAX_RECORDS  = 250000

# Major North American & International Commercial Carriers flying in NA airspace
TARGET_CARRIERS = {
    "AAL", "AAY", "ABX", "ACA", "AFR", "AJT", "AMX", "ANA", "ASA", "ASH",
    "ATN", "AUA", "AVA", "AZU", "BAW", "BEL", "BOX", "BWA", "CCA", "CKS",
    "CLX", "CMP", "CPA", "DAL", "DLH", "EDV", "EIN", "EJA", "ENY", "ETD",
    "ETH", "EVA", "FDX", "FFT", "GJS", "GLO", "GTI", "HAL", "IBE", "ICE",
    "JAL", "JBU", "JIA", "JZA", "KAC", "KAL", "KLM", "LAN", "LXJ", "MSR",
    "MXY", "NCR", "NKS", "PAC", "PDT", "POE", "QFA", "QTR", "QXE", "RAM",
    "RJA", "ROU", "RPA", "SAS", "SCX", "SKW", "SVA", "SWA", "SWR", "TAM",
    "TAP", "THY", "TSC", "UAE", "UAL", "UCA", "UPS", "VIR", "VIV", "VJT",
    "VOI", "WJA", "XOJ"
}

def download_text(url):
    print(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "ESP32P4-RouteUpdater/2.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")

def build_database():
    # 1. Parse OurAirports CSV (ident, iata_code -> municipality, lat, lon)
    airports_raw = download_text(AIRPORTS_URL)
    airports = {}
    reader = csv.reader(io.StringIO(airports_raw))
    header = next(reader, None)

    for row in reader:
        if len(row) < 14:
            continue
        ident = row[1].strip().upper()
        lat_s = row[4].strip()
        lon_s = row[5].strip()
        city  = row[10].strip()
        iata  = row[13].strip().upper()

        if not ident or not city:
            continue
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            continue

        # Clean up long city names (e.g. "Washington, D.C." -> "Washington")
        city_clean = city.split("/")[0].split(",")[0].strip()
        if not city_clean:
            city_clean = iata if iata else ident

        info = (city_clean[:15], lat, lon)
        airports[ident] = info
        if len(iata) == 3:
            airports[iata] = info

    print(f"Loaded {len(airports)} airport lookup keys from OurAirports.")

    # 2. Parse adsb.lol routes.csv
    # Columns: 0:Callsign, 1:Code, 2:Number, 3:AirlineCode, 4:AirportCodes
    routes_raw = download_text(ROUTES_URL)
    reader = csv.reader(io.StringIO(routes_raw))
    next(reader, None)  # Skip header

    routes = {}
    for row in reader:
        if len(row) < 5:
            continue
        callsign = row[0].strip().upper()
        airline  = row[3].strip().upper()
        ap_codes = row[4].strip().upper()

        if len(callsign) < 4 or len(callsign) > 7 or "-" not in ap_codes:
            continue

        prefix = airline if len(airline) == 3 else callsign[:3]
        if prefix not in TARGET_CARRIERS:
            continue

        parts = [p.strip() for p in ap_codes.split("-") if p.strip()]
        if len(parts) < 2:
            continue

        orig_code = parts[0]
        dest_code = parts[-1]
        if orig_code == dest_code:
            continue

        orig_info = airports.get(orig_code)
        dest_info = airports.get(dest_code)
        if not orig_info or not dest_info:
            continue

        routes[callsign] = (orig_info, dest_info)

    sorted_keys = sorted(routes.keys())
    if len(sorted_keys) > MAX_RECORDS:
        sorted_keys = sorted_keys[:MAX_RECORDS]

    # Pack 48-byte binary struct:
    # <8s (callsign) 16s (orig_city) 16s (dest_city) 4h (orig_lat*100, orig_lon*100, dest_lat*100, dest_lon*100)
    packed = bytearray()
    for cs in sorted_keys:
        (o_city, o_lat, o_lon), (d_city, d_lat, d_lon) = routes[cs]
        packed.extend(struct.pack(
            "<8s16s16s4h",
            cs.encode("ascii", "ignore"),
            o_city.encode("ascii", "ignore"),
            d_city.encode("ascii", "ignore"),
            int(round(o_lat * 100)),
            int(round(o_lon * 100)),
            int(round(d_lat * 100)),
            int(round(d_lon * 100))
        ))

    with open(OUTPUT_BIN, "wb") as f:
        f.write(packed)

    print(f"Success: Packed {len(sorted_keys)} routes ({len(packed)/1024:.1f} KB) into {OUTPUT_BIN}")

if __name__ == "__main__":
    build_database()import csv
import io
import struct
import urllib.request

ROUTES_URL   = "https://vrs-standing-data.adsb.lol/routes.csv"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUTPUT_BIN   = "routes_na.bin"
MAX_RECORDS  = 25000

# Major North American & International Commercial Carriers flying in NA airspace
TARGET_CARRIERS = {
    "AAL", "AAY", "ABX", "ACA", "AFR", "AJT", "AMX", "ANA", "ASA", "ASH",
    "ATN", "AUA", "AVA", "AZU", "BAW", "BEL", "BOX", "BWA", "CCA", "CKS",
    "CLX", "CMP", "CPA", "DAL", "DLH", "EDV", "EIN", "EJA", "ENY", "ETD",
    "ETH", "EVA", "FDX", "FFT", "GJS", "GLO", "GTI", "HAL", "IBE", "ICE",
    "JAL", "JBU", "JIA", "JZA", "KAC", "KAL", "KLM", "LAN", "LXJ", "MSR",
    "MXY", "NCR", "NKS", "PAC", "PDT", "POE", "QFA", "QTR", "QXE", "RAM",
    "RJA", "ROU", "RPA", "SAS", "SCX", "SKW", "SVA", "SWA", "SWR", "TAM",
    "TAP", "THY", "TSC", "UAE", "UAL", "UCA", "UPS", "VIR", "VIV", "VJT",
    "VOI", "WJA", "XOJ"
}

def download_text(url):
    print(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "ESP32P4-RouteUpdater/2.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")

def build_database():
    # 1. Parse OurAirports CSV (ident, iata_code -> municipality, lat, lon)
    airports_raw = download_text(AIRPORTS_URL)
    airports = {}
    reader = csv.reader(io.StringIO(airports_raw))
    header = next(reader, None)

    for row in reader:
        if len(row) < 14:
            continue
        ident = row[1].strip().upper()
        lat_s = row[4].strip()
        lon_s = row[5].strip()
        city  = row[10].strip()
        iata  = row[13].strip().upper()

        if not ident or not city:
            continue
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            continue

        # Clean up long city names (e.g. "Washington, D.C." -> "Washington")
        city_clean = city.split("/")[0].split(",")[0].strip()
        if not city_clean:
            city_clean = iata if iata else ident

        info = (city_clean[:15], lat, lon)
        airports[ident] = info
        if len(iata) == 3:
            airports[iata] = info

    print(f"Loaded {len(airports)} airport lookup keys from OurAirports.")

    # 2. Parse adsb.lol routes.csv
    # Columns: 0:Callsign, 1:Code, 2:Number, 3:AirlineCode, 4:AirportCodes
    routes_raw = download_text(ROUTES_URL)
    reader = csv.reader(io.StringIO(routes_raw))
    next(reader, None)  # Skip header

    routes = {}
    for row in reader:
        if len(row) < 5:
            continue
        callsign = row[0].strip().upper()
        airline  = row[3].strip().upper()
        ap_codes = row[4].strip().upper()

        if len(callsign) < 4 or len(callsign) > 7 or "-" not in ap_codes:
            continue

        prefix = airline if len(airline) == 3 else callsign[:3]
        if prefix not in TARGET_CARRIERS:
            continue

        parts = [p.strip() for p in ap_codes.split("-") if p.strip()]
        if len(parts) < 2:
            continue

        orig_code = parts[0]
        dest_code = parts[-1]
        if orig_code == dest_code:
            continue

        orig_info = airports.get(orig_code)
        dest_info = airports.get(dest_code)
        if not orig_info or not dest_info:
            continue

        routes[callsign] = (orig_info, dest_info)

    sorted_keys = sorted(routes.keys())
    if len(sorted_keys) > MAX_RECORDS:
        sorted_keys = sorted_keys[:MAX_RECORDS]

    # Pack 48-byte binary struct:
    # <8s (callsign) 16s (orig_city) 16s (dest_city) 4h (orig_lat*100, orig_lon*100, dest_lat*100, dest_lon*100)
    packed = bytearray()
    for cs in sorted_keys:
        (o_city, o_lat, o_lon), (d_city, d_lat, d_lon) = routes[cs]
        packed.extend(struct.pack(
            "<8s16s16s4h",
            cs.encode("ascii", "ignore"),
            o_city.encode("ascii", "ignore"),
            d_city.encode("ascii", "ignore"),
            int(round(o_lat * 100)),
            int(round(o_lon * 100)),
            int(round(d_lat * 100)),
            int(round(d_lon * 100))
        ))

    with open(OUTPUT_BIN, "wb") as f:
        f.write(packed)

    print(f"Success: Packed {len(sorted_keys)} routes ({len(packed)/1024:.1f} KB) into {OUTPUT_BIN}")

if __name__ == "__main__":
    build_database()
