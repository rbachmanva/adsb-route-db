import csv
import io
import struct
import urllib.request

ROUTES_URL   = "https://vrs-standing-data.adsb.lol/routes.csv"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUTPUT_BIN   = "routes_na.bin"
MAX_RECORDS  = 300000

# US & territories ISO country codes in OurAirports
US_COUNTRIES = {"US", "PR", "VI", "GU", "MP", "AS"}

def download_text(url):
    print(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "ESP32P4-RouteUpdater/2.1"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")

def build_database():
    # 1. Parse OurAirports CSV
    # Columns: 1:ident(ICAO), 4:lat, 5:lon, 8:iso_country, 10:municipality(City), 13:iata_code
    airports_raw = download_text(AIRPORTS_URL)
    airports = {}
    reader = csv.reader(io.StringIO(airports_raw))
    next(reader, None)  # Skip header

    for row in reader:
        if len(row) < 14:
            continue
        ident   = row[1].strip().upper()
        lat_s   = row[4].strip()
        lon_s   = row[5].strip()
        country = row[8].strip().upper()
        city    = row[10].strip()
        iata    = row[13].strip().upper()

        if not ident or not city:
            continue
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            continue

        # Clean city name (e.g., "Washington, D.C." -> "Washington", "Dallas-Fort Worth" -> "Dallas")
        city_clean = city.split("/")[0].split(",")[0].strip()
        if not city_clean:
            city_clean = iata if iata else ident

        is_us = (country in US_COUNTRIES) or (len(ident) == 4 and ident.startswith("K"))
        info = (city_clean[:15], lat, lon, is_us)

        airports[ident] = info
        if len(iata) == 3 and iata.isalpha():
            airports[iata] = info

    print(f"Loaded {len(airports)} airport lookup keys from OurAirports.")

    # 2. Parse adsb.lol routes.csv
    # Columns: 0:Callsign, 1:Code, 2:Number, 3:AirlineCode, 4:AirportCodes
    routes_raw = download_text(ROUTES_URL)
    reader = csv.reader(io.StringIO(routes_raw))
    next(reader, None)  # Skip header

    routes = {}
    skipped_non_us = 0

    for row in reader:
        if len(row) < 5:
            continue
        callsign = row[0].strip().upper()
        ap_codes = row[4].strip().upper()

        if len(callsign) < 4 or len(callsign) > 7 or "-" not in ap_codes:
            continue

        parts = [p.strip() for p in ap_codes.split("-") if p.strip()]
        if len(parts) < 2:
            continue

        # Take first airport as Origin and last airport as Destination
        orig_code = parts[0]
        dest_code = parts[-1]
        if orig_code == dest_code:
            continue

        orig_info = airports.get(orig_code)
        dest_info = airports.get(dest_code)
        if not orig_info or not dest_info:
            continue

        # FILTER: Keep ONLY if Origin is in the US OR Destination is in the US
        orig_is_us = orig_info[3]
        dest_is_us = dest_info[3]
        if not (orig_is_us or dest_is_us):
            skipped_non_us += 1
            continue

        routes[callsign] = (orig_info, dest_info)

    print(f"Retained {len(routes)} US-origin/destination routes (filtered out {skipped_non_us} foreign-only routes).")

    sorted_keys = sorted(routes.keys())
    if len(sorted_keys) > MAX_RECORDS:
        sorted_keys = sorted_keys[:MAX_RECORDS]

    # 3. Pack 48-byte binary struct:
    # <8s (callsign) 16s (orig_city) 16s (dest_city) 4h (orig_lat*100, orig_lon*100, dest_lat*100, dest_lon*100)
    packed = bytearray()
    for cs in sorted_keys:
        (o_city, o_lat, o_lon, _), (d_city, d_lat, d_lon, _) = routes[cs]
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

    print(f"Success: Packed {len(sorted_keys)} US routes ({len(packed)/1024:.1f} KB) into {OUTPUT_BIN}")

if __name__ == "__main__":
    build_database()
