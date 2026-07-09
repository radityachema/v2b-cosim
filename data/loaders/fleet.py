"""
Fleet data loader -- Chicago Taxi Trips dataset.

Source: Chicago Data Portal -- Taxi Trips
https://data.cityofchicago.org/Transportation/Taxi-Trips/wrvz-psew
"""
import pandas as pd


def load_chicago_taxi_demands(path, date, node_map):
    """Load one day of Chicago taxi trips as ride demands. node_map filters to known
    network nodes; t_d is pickup hour (0-23). One demand per (origin, dest, hour),
    first occurrence kept. Returns [{'id', 'i_d', 'j_d', 't_d'}, ...]."""
    df = pd.read_csv(path, low_memory=False)
    df['Trip Start Timestamp'] = pd.to_datetime(df['Trip Start Timestamp'])
    day = df[df['Trip Start Timestamp'].dt.date == pd.Timestamp(date).date()].copy()

    # Trip Seconds loads as object dtype (mixed/garbage values) in this dataset --
    # coerce to numeric so `.notna()` means "a real numeric value".
    day['Trip Seconds'] = pd.to_numeric(day['Trip Seconds'], errors='coerce')
    day['Trip Miles'] = pd.to_numeric(day['Trip Miles'], errors='coerce')

    # Look up node_map values inside the loop below (not via a mapped column) --
    # a mapped column with any NaN present gets upcast to float64 by pandas,
    # silently turning int node ids like 1 into 1.0.
    pickup_in_map = day['Pickup Community Area'].isin(node_map)
    dropoff_in_map = day['Dropoff Community Area'].isin(node_map)
    valid = (
        pickup_in_map & dropoff_in_map &
        (day['Pickup Community Area'] != day['Dropoff Community Area']) &
        (day['Trip Miles'] > 0) &
        day['Trip Seconds'].notna()
    )
    trips = day[valid].copy()
    trips['t_d'] = trips['Trip Start Timestamp'].dt.hour

    demands = []
    seen = set()
    for _, row in trips.iterrows():
        i_d = node_map[row['Pickup Community Area']]
        j_d = node_map[row['Dropoff Community Area']]
        t_d = int(row['t_d'])
        key = (i_d, j_d, t_d)
        if key in seen:
            continue
        seen.add(key)
        demands.append({'id': len(demands), 'i_d': i_d, 'j_d': j_d, 't_d': t_d})
    return demands
