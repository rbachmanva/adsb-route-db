import os
import io
import csv
import json
import time
import struct
import urllib.request
from FlightRadar24 import FlightRadar24API

MASTER_JSON      = "routes_master.json"
OUTPUT_BIN       = "routes.bin"
DMV_AIRPORTS     = ["IAD", "DCA", "BWI"]
AIRPORTS_URL     = "https://davidmegginson.github.io/ourairports-data/airports.csv"
BASE_ROUTES_URL  = "https://vrs-standing-data.adsb.lol/routes.csv"

PRUNE_DAYS       = 45
PRUNE_SECS       = PRUNE_DAYS * 86400
US_COUNTRIES     = {"US", "PR", "VI", "GU", "MP", "AS"}

def format_city_tag(city, code):
    city_clean = city.split("/")[0].split(",")[0].strip() if city else code
    tag = f"({code})"
    max_len = 15 - len(tag)
    if len(city_clean) > max_len:
        city_clean = city_clean[:max_len].strip()
    return f"{city_clean}{tag}"[:15]

def load_airports_db():
    print("Downloading OurAirports database...")
    req = urllib.request.Request(AIRPORTS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        reader = csv.reader(io.StringIO(resp.read().decode("utf-8", errors="replace")))
    next(reader, None)

    airports = {}
    for row in reader:
        if len(row) < 14: continue
        ident, lat_s, lon_s, country, city, iata = row[1].strip().upper(), row[4].strip(), row[5].strip(), row[8].strip().upper(), row[10].strip(), row[13].strip().upper()
        if not ident: continue
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            continue

        code = iata if (len(iata) == 3 and iata.isalpha()) else (ident[1:] if len(ident) == 4 and ident.startswith("K") else ident[:4])
        display = format_city_tag(city, code)
        is_us = (country in US_COUNTRIES) or (len(ident) == 4 and ident.startswith("K"))
        info = (display, lat, lon, is_us)

        airports[ident] = info
        if len(iata) == 3 and iata.isalpha():
            airports[iata] = info

    print(f"Loaded {len(airports)} airports into lookup dictionary.")
    return airports

def load_base_catalog(airports):
    """Pulls open routes to catch cruising high-altitude overflights."""
    print("Downloading baseline routes.csv from adsb.lol...")
    req = urllib.request.Request(BASE_ROUTES_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            reader = csv.reader(io.StringIO(resp.read().decode("utf-8", errors="replace")))
    except Exception as e:
        print(f"Warning: Could not fetch base routes ({e}). Continuing with local overlay only.")
        return {}

    next(reader, None)
    base_routes = {}

    for row in reader:
        if len(row) < 5: continue
        callsign, ap_codes = row[0].strip().upper(), row[4].strip().upper()
        if len(callsign) < 3 or len(callsign) > 8 or "-" not in ap_codes: continue

        parts = [p.strip() for p in ap_codes.split("-") if p.strip()]
        if len(parts) < 2: continue

        orig_info, dest_info = airports.get(parts[0]), airports.get(parts[-1])
        if not orig_info or not dest_info: continue

        # Keep if touches US (captures all Northeast Corridor overflights)
        if not (orig_info[3] or dest_info[3]): continue

        base_routes[callsign] = {
            "orig": orig_info[0],
            "dest": dest_info[0],
            "olat": orig_info[1],
            "olon": orig_info[2],
            "dlat": dest_info[1],
            "dlon": dest_info[2],
            "source": "base"
        }

    print(f"Loaded {len(base_routes)} US & overflight baseline routes.")
    return base_routes

def scrape_local_fr24(airports):
    """Pulls live arrival/departure boards for IAD, DCA, and BWI for free."""
    print("Scraping live schedules for IAD, DCA, and BWI...")
    fr_api = FlightRadar24API()
    scraped = {}
    now = int(time.time())

    for ap_code in DMV_AIRPORTS:
        try:
            details = fr_api.get_airport_details(ap_code)
            plugin_data = details.get("pluginData", {}).get("schedule", {})
        except Exception as e:
            print(f"Failed to fetch {ap_code}: {e}")
            continue

        for mode in ["arrivals", "departures"]:
            data_list = plugin_data.get(mode, {}).get("data", [])
            for item in data_list:
                flt = item.get("flight", {})
                ident = flt.get("identification", {})
                callsign = ident.get("callsign") or ident.get("number", {}).get("default")
                if not callsign or len(callsign) < 3 or len(callsign) > 8: continue
                callsign = callsign.strip().upper()

                o_code = flt.get("airport", {}).get("origin", {}).get("code", {}).get("iata") or \
                         flt.get("airport", {}).get("origin", {}).get("code", {}).get("icao")
                d_code = flt.get("airport", {}).get("destination", {}).get("code", {}).get("iata") or \
                         flt.get("airport", {}).get("destination", {}).get("code", {}).get("icao")
                if not o_code or not d_code: continue

                orig_info = airports.get(o_code.upper())
                dest_info = airports.get(d_code.upper())
                if not orig_info or not dest_info: continue

                scraped[callsign] = {
                    "orig": orig_info[0],
                    "dest": dest_info[0],
                    "olat": orig_info[1],
                    "olon": orig_info[2],
                    "dlat": dest_info[1],
                    "dlon": dest_info[2],
                    "last_seen": now,
                    "source": "local_free"
                }

        time.sleep(2)  # Avoid rapid requests

    print(f"Scraped {len(scraped)} local DMV flights.")
    return scraped

def main():
    now = int(time.time())
    airports = load_airports_db()

    # 1. Load persistent historical cache from Git
    master = {}
    if os.path.exists(MASTER_JSON):
        try:
            with open(MASTER_JSON, "r", encoding="utf-8") as f:
                master = json.load(f)
        except Exception:
            master = {}
    print(f"Existing persistent local cache: {len(master)} routes.")

    # 2. Scrape live local boards & update master
    fresh_local = scrape_local_fr24(airports)
    for cs, data in fresh_local.items():
        master[cs] = data

    # 3. Prune entries not seen in the last 45 days
    pruned = [cs for cs, d in master.items() if (now - d.get("last_seen", now)) > PRUNE_SECS]
    for cs in pruned:
        del master[cs]

    with open(MASTER_JSON, "w", encoding="utf-8") as f:
        json.dump(master, f, indent=2, sort_keys=True)
    print(f"Updated {MASTER_JSON} ({len(master)} active routes, {len(pruned)} pruned).")

    # 4. Load base overflight catalog
    base_routes = load_base_catalog(airports)

    # 5. Merge: Base overflights first, local free overlay takes priority!
    merged = {}
    for cs, d in base_routes.items():
        merged[cs] = d
    for cs, d in master.items():
        merged[cs] = d

    print(f"Final combined database: {len(merged)} total routes.")

    # 6. Sort alphabetically & pack into 48-byte binary format
    sorted_callsigns = sorted(merged.keys())
    packed = bytearray()
    record_fmt = "<8s16s16s4h"

    for cs in sorted_callsigns:
        d = merged[cs]
        packed.extend(struct.pack(
            record_fmt,
            cs.encode("ascii", "ignore"),
            d["orig"].encode("ascii", "ignore"),
            d["dest"].encode("ascii", "ignore"),
            int(round(d["olat"] * 100)),
            int(round(d["olon"] * 100)),
            int(round(d["dlat"] * 100)),
            int(round(d["dlon"] * 100))
        ))

    with open(OUTPUT_BIN, "wb") as f:
        f.write(packed)

    print(f"Compiled '{OUTPUT_BIN}' ({len(packed):,} bytes / {len(packed)/1024:.1f} KB).")

if __name__ == "__main__":
    main()
