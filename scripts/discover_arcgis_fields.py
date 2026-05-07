"""Hit the ArcGIS rest directory and print parcel-layer URLs + field names."""
import sys

import httpx

ROOT = "https://gis.berkeleycountysc.gov/arcgis/rest/services?f=json"


def main():
    services = httpx.get(ROOT).json().get("services", [])
    for svc in services:
        name = svc["name"]
        if "parcel" in name.lower() or "tax" in name.lower():
            url = f"https://gis.berkeleycountysc.gov/arcgis/rest/services/{name}/MapServer?f=json"
            meta = httpx.get(url).json()
            for layer in meta.get("layers", []):
                lid = layer["id"]
                lname = layer["name"]
                furl = f"https://gis.berkeleycountysc.gov/arcgis/rest/services/{name}/MapServer/{lid}?f=json"
                fmeta = httpx.get(furl).json()
                fields = [f["name"] for f in fmeta.get("fields", [])]
                print(f"\nLayer: {lname}\nQuery URL: {furl[:-7]}/query")
                print(f"Fields: {fields}")


if __name__ == "__main__":
    sys.exit(main())
