import csv
import gzip
import io
import struct
import sys
import urllib.request

SOURCE_URL = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/routes.csv.gz"
OUTPUT_BIN = "routes_na.bin"
TARGET_MAX_RECORDS = 22500  # Stays under 360 KB

NA_PREFIXES = {
    "AAL", "DAL", "UAL", "SWA", "ASA", "JBU", "FFT", "NKS", "HAL", "FDX", "UPS",
    "ACA", "WJA", "TSC", "ROU", "AMX", "VOI", "VIV",
    "SKW", "RPA", "ENY", "EDV", "JIA", "ASH", "PDT", "GJS", "QXE", "CPZ",
    "SCX", "MXY", "GTI", "EJA"
}

def fetch_and_pack():
    print(f"Fetching routes from {SOURCE_URL}...")
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "ESP32-Route-Builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        gz_data = resp.read()

    print("Extracting and parsing CSV...")
    with gzip.GzipFile(fileobj=io.BytesIO(gz_data)) as gz:
        reader = csv.reader(io.TextIOWrapper(gz, encoding="utf-8", errors="ignore"))
        routes = {}
        for row in reader:
            if len(row) < 3:
                continue
            callsign, orig, dest = row[0].strip().upper(), row[1].strip().upper(), row[2].strip().upper()
            if not callsign or not orig or not dest:
                continue
            if callsign[:3] in NA_PREFIXES:
                clean_orig = orig[1:] if len(orig) == 4 and orig.startswith("K") else orig
                clean_dest = dest[1:] if len(dest) == 4 and dest.startswith("K") else dest
                routes[callsign] = (clean_orig[:3], clean_dest[:3])

    sorted_callsigns = sorted(routes.keys())
    if len(sorted_callsigns) > TARGET_MAX_RECORDS:
        sorted_callsigns = sorted_callsigns[:TARGET_MAX_RECORDS]

    packed_data = bytearray()
    for cs in sorted_callsigns:
        orig, dest = routes[cs]
        packed_data.extend(struct.pack("<8s4s4s", cs.encode("ascii", "ignore"), orig.encode("ascii", "ignore"), dest.encode("ascii", "ignore")))

    with open(OUTPUT_BIN, "wb") as f:
        f.write(packed_data)
    print(f"Packed {len(sorted_callsigns)} routes ({len(packed_data)/1024:.2f} KB) into {OUTPUT_BIN}")

if __name__ == "__main__":
    fetch_and_pack()
