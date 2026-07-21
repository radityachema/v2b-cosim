"""One-off script: pull one full day of Chicago Taxi Trips via the Socrata
API and save it as data/chicago_taxi_trips.csv, matching the column names
and format of the portal's own CSV export (so scenario builders don't care
which path the data came from).

Faster than the portal's web UI for a full day's data (no auth needed for
this public dataset). Only one day is ever read by the scenario builders
(TARGET_DATE filters it down), so there's no reason to pull more than that.

Usage: python -m data.loaders.pull_taxi_trips 2019-07-10
"""
import sys
from pathlib import Path

import pandas as pd
import requests

DATASET_URL = 'https://data.cityofchicago.org/resource/wrvz-psew.json'
OUT_PATH = Path(__file__).resolve().parent.parent / 'chicago_taxi_trips.csv'


def pull_day(date_str):
    where = f"trip_start_timestamp between '{date_str}T00:00:00' and '{date_str}T23:59:59'"
    rows, offset, limit = [], 0, 50000
    while True:
        r = requests.get(DATASET_URL, params={'$where': where, '$limit': limit, '$offset': offset}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        offset += limit
        print(f'fetched {len(rows)} rows so far...')
        if len(batch) < limit:
            break
    return pd.DataFrame(rows)


def to_original_schema(df):
    fmt_ts = lambda s: pd.to_datetime(s).dt.strftime('%m/%d/%Y %I:%M:%S %p')
    return pd.DataFrame({
        'Trip ID': df['trip_id'],
        'Taxi ID': df['taxi_id'],
        'Trip Start Timestamp': fmt_ts(df['trip_start_timestamp']),
        'Trip End Timestamp': fmt_ts(df['trip_end_timestamp']),
        'Trip Seconds': df['trip_seconds'],
        'Trip Miles': df['trip_miles'],
        'Pickup Community Area': df.get('pickup_community_area'),
        'Dropoff Community Area': df.get('dropoff_community_area'),
        'Fare': df.get('fare'),
        'Trip Total': df.get('trip_total'),
        'Pickup Centroid Location': '',
        'Dropoff Centroid  Location': '',
        'Pickup Census Tract': df.get('pickup_census_tract'),
        'Dropoff Census Tract': df.get('dropoff_census_tract'),
        'Tips': df.get('tips'),
        'Tolls': df.get('tolls'),
        'Extras': df.get('extras'),
        'Payment Type': df.get('payment_type'),
        'Company': df.get('company'),
        'Pickup Centroid Latitude': df.get('pickup_centroid_latitude'),
        'Pickup Centroid Longitude': df.get('pickup_centroid_longitude'),
        'Dropoff Centroid Latitude': df.get('dropoff_centroid_latitude'),
        'Dropoff Centroid Longitude': df.get('dropoff_centroid_longitude'),
    })


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python -m data.loaders.pull_taxi_trips YYYY-MM-DD')
    date_str = sys.argv[1]
    raw = pull_day(date_str)
    print('TOTAL rows:', len(raw))
    to_original_schema(raw).to_csv(OUT_PATH, index=False)
    print(f'wrote {OUT_PATH}')
