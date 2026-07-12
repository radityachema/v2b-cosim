"""Small quick-start scenario: real Chicago Taxi demand + real DOE/EnergyPlus
Chicago-O'Hare building load (two building types as two buildings), 13
vehicles, 4 nodes -- the largest scale that still solves the MILP to proven
optimality (39s). See chicago_scenario.py for the full ~77-node city-scale
version -- MILP doesn't scale there (see chicago_scenario.py docstring),
Heuristic/Null do."""
import math
from pathlib import Path

import pandas as pd

from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from data.loaders.doe_chicago import load_doe_chicago_load

# See data/README.md for where to get these files.
TAXI_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "chicago_taxi_trips.csv"
TARGET_DATE = "2019-01-02"
DOE_CHICAGO_DIR = Path(__file__).resolve().parent.parent / "data" / "doe_chicago"
DOE_MONTH, DOE_DAY = 1, 2  # TMY3 is a synthetic typical year, not tied to a real
                           # calendar year -- day-of-year chosen to match TARGET_DATE

N_ACTIVE = 4            # top-4 Chicago community areas by trip volume
DEPOT = 0                # node 0 = highest-volume area = depot
BUILDING_NODES = [1, 2]  # nodes 1, 2 = 2nd/3rd highest-volume areas; 1=MediumOffice, 2=SmallHotel
T = 96                   # 15-min resolution (hourly DOE data linearly interpolated -- see
                         # data/loaders/doe_chicago.py)
DT = 0.25

# lam=1.0 (100% demand-service) kept fixed -- not relaxed. V=13, N_ACTIVE=4 is
# the confirmed frontier for PROVEN MILP optimality: solves in 39s. N=5,V=20
# plateaus at a flat 5.53% gap even after 12h (identical bound at 6h and 12h --
# a genuine wall, not a patience problem). See chicago_scenario.py for the
# city-scale version this doesn't attempt to match.
V = 13

E_CAP = 41.3
EPS = 0.15
P_BAR = 10.0
S_MIN = 0.1
S_MAX = 0.9
S_INIT = 0.8
Q_BLDG = 200.0
LAM = 1.0


def _haversine_miles_and_tau(lon1, lat1, lon2, lat2):
    R = 6371
    ph1, ph2 = math.radians(lat1), math.radians(lat2)
    dph = math.radians(lat2 - lat1)
    dlm = math.radians(lon2 - lon1)
    a = math.sin(dph / 2) ** 2 + math.cos(ph1) * math.cos(ph2) * math.sin(dlm / 2) ** 2
    km = 2 * R * math.asin(math.sqrt(a))
    # Despite the variable name below, this stores MILES (km * 0.621371) --
    # `EPS` (energy per mile) is calibrated against that unit, so converting
    # this to actual km later would silently break the SoC-consumption math.
    dist_miles = round(km * 0.621371, 2)
    # km/40 is hours at an assumed 40 km/h; divide by DT to convert hours ->
    # timesteps (only equivalent to the raw hour count when DT=1.0).
    tau = max(1, min(math.ceil((km / 40) / DT), T - 2))
    return dist_miles, tau


def build_scenario():
    """Builds the scenario dict, including MILP-specific fields sharing this same
    network/fleet/demand data."""
    df = pd.read_csv(TAXI_CSV_PATH, low_memory=False)
    df['Trip Start Timestamp'] = pd.to_datetime(df['Trip Start Timestamp'])
    day = df[df['Trip Start Timestamp'].dt.date == pd.Timestamp(TARGET_DATE).date()].copy()
    # Trip Seconds loads as object dtype (mixed/garbage values in this
    # dataset) -- coerce to numeric so `.notna()` means "a real number".
    day['Trip Seconds'] = pd.to_numeric(day['Trip Seconds'], errors='coerce')
    day['Trip Miles'] = pd.to_numeric(day['Trip Miles'], errors='coerce')

    pu_cnt = day['Pickup Community Area'].value_counts()
    do_cnt = day['Dropoff Community Area'].value_counts()
    vol = pu_cnt.add(do_cnt, fill_value=0).dropna()
    vol.index = vol.index.astype(int)
    top_areas = list(vol.sort_values(ascending=False).head(N_ACTIVE).index)
    node_map = {area: idx for idx, area in enumerate(top_areas)}

    centroids = {}
    for area, node in node_map.items():
        pu_pts = day[day['Pickup Community Area'] == area][
            ['Pickup Centroid Longitude', 'Pickup Centroid Latitude']].dropna()
        do_pts = day[day['Dropoff Community Area'] == area][
            ['Dropoff Centroid Longitude', 'Dropoff Centroid Latitude']].dropna()
        do_pts.columns = ['Pickup Centroid Longitude', 'Pickup Centroid Latitude']
        pts = pd.concat([pu_pts, do_pts])
        centroids[node] = (pts['Pickup Centroid Longitude'].mean(),
                            pts['Pickup Centroid Latitude'].mean())

    dist = {}
    tau = {}
    for i in range(N_ACTIVE):
        for j in range(N_ACTIVE):
            if i == j:
                dist[i, j] = 0.0
                tau[i, j] = 1
                continue
            lon1, lat1 = centroids[i]
            lon2, lat2 = centroids[j]
            dist[i, j], tau[i, j] = _haversine_miles_and_tau(lon1, lat1, lon2, lat2)

    day['on'] = day['Pickup Community Area'].map(node_map)
    day['dn'] = day['Dropoff Community Area'].map(node_map)
    valid = (
        day['on'].notna() & day['dn'].notna() &
        (day['on'] != day['dn']) &
        (day['Trip Miles'] > 0) &
        day['Trip Seconds'].notna()
    )
    trips = day[valid].copy()
    trips['on'] = trips['on'].astype(int)
    trips['dn'] = trips['dn'].astype(int)
    # 15-min-slot index (0-95), not just the hour -- T is now 96, so an
    # hour-only index would cram every demand into the first 24 slots.
    trips['th'] = (trips['Trip Start Timestamp'].dt.hour * 4
                    + trips['Trip Start Timestamp'].dt.minute // 15)

    # Dedup by (origin, dest, hour), first occurrence in row order --
    # fully deterministic, no randomness involved.
    pool = {}
    seen = set()
    for _, row in trips.iterrows():
        o, d, td = int(row['on']), int(row['dn']), int(row['th'])
        if td < 1 or td >= T - 1:
            continue
        key = (o, d, td)
        if key in seen:
            continue
        seen.add(key)
        pool[len(pool)] = (o, d, td)

    demands_milp = {}
    for o, d, td in pool.values():
        tau_to = tau[DEPOT, o] if o != DEPOT else 0
        if o != DEPOT and td < tau_to + 2:
            continue
        tau_od = tau[o, d]
        tau_back = tau[d, DEPOT] if d != DEPOT else 0
        if td + tau_od + tau_back >= T:
            continue
        demands_milp[len(demands_milp)] = (o, d, td, dist[o, d])

    # Single source of truth for network numbers -- the MILP model must derive
    # its own e/e_hat from this same NetworkClass instance, not recompute them.
    arcs = {}
    for i in range(N_ACTIVE):
        for j in range(N_ACTIVE):
            if i == j:
                continue
            e = dist[i, j] * EPS / E_CAP
            arcs[(i, j)] = {'tau': tau[i, j], 'e': e, 'd': dist[i, j]}

    network = NetworkClass(
        nodes=set(range(N_ACTIVE)), arcs=arcs,
        building_nodes=set(BUILDING_NODES), depot=DEPOT,
    )

    ride_demand = RideDemandClass(demands=[
        {'id': did, 'i_d': o, 'j_d': d, 't_d': td}
        for did, (o, d, td, _dk) in demands_milp.items()
    ])

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=S_INIT, e_cap=E_CAP, p_max=P_BAR, s_min=S_MIN, s_max=S_MAX)
        for i in range(V)
    ])

    # node 1 = MediumOffice, node 2 = SmallHotel -- two distinct DOE reference
    # building types, both from the Chicago-O'Hare TMY3 station, picked so
    # their peak load is commensurate with this fleet's total power capacity
    # (V * P_bar = 130 kW): MediumOffice peaks ~319 kW, SmallHotel ~136 kW.
    doe_file_by_node = {1: 'MediumOffice.csv', 2: 'SmallHotel.csv'}
    load_profile = {
        b: load_doe_chicago_load(DOE_CHICAGO_DIR / doe_file_by_node[b], DOE_MONTH, DOE_DAY)
        for b in BUILDING_NODES
    }
    n_chargers = int(Q_BLDG / P_BAR)
    buildings = BuildingClass([
        Building(
            b_id=b, load_profile=dict(load_profile[b]), n_chargers=n_chargers,
            rc=None,
        )
        for b in BUILDING_NODES
    ])

    return {
        'network': network,
        'ride_demand': ride_demand,
        'fleet': fleet,
        'buildings': buildings,
        'demands_milp': demands_milp,
        'nodes': list(range(N_ACTIVE)),
        'building_nodes': list(BUILDING_NODES),
        'depot': DEPOT,
        'vehicles_list': list(range(V)),
        'load_profile': load_profile,
        'lam': LAM,
        'E_cap': E_CAP,
        'eps': EPS,
        'P_bar': P_BAR,
        'S_min': S_MIN,
        'S_max': S_MAX,
        'S_init': S_INIT,
        'Q_bldg': Q_BLDG,
        'T': T,
        'dt': DT,
    }
