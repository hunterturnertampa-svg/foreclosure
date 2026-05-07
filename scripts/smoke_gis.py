"""Look up a parcel by tax map number against the live ArcGIS service."""
import asyncio
import sys
from foreclosure_bot.config import Settings
from foreclosure_bot.gis_lookup import GisClient, GisFieldMap


async def main(pin: str):
    s = Settings()
    c = GisClient(
        query_url=s.arcgis_parcel_query_url,
        fields=GisFieldMap(
            pin=s.arcgis_parcel_pin_field, owner=s.arcgis_parcel_owner_field,
            address=s.arcgis_parcel_address_field, city=s.arcgis_parcel_city_field,
            zip=s.arcgis_parcel_zip_field,
        ),
    )
    parcel = await c.query(pin)
    print(parcel)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
