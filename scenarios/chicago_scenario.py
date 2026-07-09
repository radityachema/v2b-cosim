"""
A larger, real-data scenario: real Chicago Community Areas (by trip
volume), real ride demands derived directly from the Chicago Taxi Trips
CSV, plus a synthetic building load (no real building data is used here
-- see scenarios/small_scenario.py for that, which uses real BDG2 data
instead). Not "more real" than small_scenario.py -- both use real Chicago
taxi data; this one is bigger and its building load is synthetic instead
of real BDG2.

A bigger, slower-to-solve companion to small_scenario.py -- selectable in
runner.py as the "chicago" scenario. At this scale routing/scheduling is
genuinely hard, not just a proof that the pipeline works -- see the scale
constants below (N_ACTIVE, V) and the comment on LAM for what's been
checked to actually solve within a reasonable time at lambda=1.0 (a hard
100% demand-service floor, kept fixed rather than relaxed). Null/
HeuristicScheduler are unaffected by any of this -- they run against this
scenario exactly like any other, no solver involved.

Not a general-purpose loader -- data/loaders/ is for that. This is a
fully-specified, one-time scenario construction tied to this exact
comparison.
"""
import math
from pathlib import Path

import pandas as pd

from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building

# See data/README.md for where to get this file.
TAXI_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "chicago_taxi_trips.csv"
TARGET_DATE = "2019-01-02"

N_ACTIVE = 4            # top-4 Chicago community areas by trip volume
DEPOT = 0                # node 0 = highest-volume area = depot
BUILDING_NODES = [1, 2]  # nodes 1, 2 = 2nd/3rd highest-volume areas
T = 24                   # hourly resolution
DT = 1.0

# lam=1.0 (serve every real demand) is kept fixed -- not relaxed, per an
# explicit requirement that the demand-service floor stay a hard 100%, not
# tuned down the way small_scenario.py's LAM=0.3 was. N_ACTIVE=6/V=30
# (this scenario's original scale) checked directly: at lam=1.0, Gurobi
# finds ZERO feasible solutions within 300s -- not just slow, genuinely
# doesn't solve at that scale. Also checked: lowering lam alone doesn't
# fix it either (lam=0.0, i.e. no demand constraint at all, still finds no
# solution in 60s at N_ACTIVE=6/V=30) -- the bottleneck is the routing
# formulation's combinatorial size (x[v,i,j,t] is V*N*N*T binaries), not
# the demand floor.
#
# N_ACTIVE=4/V=13 is the scale actually used: checked directly across
# V=10..20 at N_ACTIVE=4 -- V<=14 solves in under 20s (V=13: ~5s), V>=15
# does not solve within 90s. V=13 keeps a full vehicle of margin below
# that cliff. Still real Chicago Taxi Trips data (121 real demands from
# 4 real community areas), still lam=1.0, just a smaller real network
# than the original 6-area/30-vehicle version -- not a relaxed problem,
# a smaller real one.
V = 13

E_CAP = 41.3
EPS = 0.15
P_BAR = 10.0
S_MIN = 0.1
S_MAX = 0.9
S_INIT = 0.8
Q_BLDG = 200.0
N_BAY = 5
LAM = 1.0


def _synthetic_load(t):
    """
    Synthetic daily load curve (placeholder, not real building data) --
    the building's total electrical demand. Buildings are Mode A (see
    build_scenario() below): no thermal decision, so there's no separate
    HVAC component to net out of this figure.
    """
    return 200.0 * math.sin(math.pi * t / 12) ** 2 + 50.0


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
    tau = max(1, min(math.ceil(km / 40), T - 2))
    return dist_miles, tau


def build_scenario():
    """
    Returns a dict bundle: the real v2b-cosim objects (network, ride_demand,
    fleet, buildings) plus everything scheduler/milp.py needs to build and
    solve the extended MILP against this exact same network/fleet/demand
    data -- single source of truth, no independently-recomputed copies.
    """
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
    trips['th'] = trips['Trip Start Timestamp'].dt.hour

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

    shared_load = {t: _synthetic_load(t) for t in range(T)}
    load_profile = {b: dict(shared_load) for b in BUILDING_NODES}  # same formula for both buildings here
    n_chargers = int(Q_BLDG / P_BAR)
    # Mode A (rc=None): AC setpoint is a constant for this paper's published
    # checkpoint, not a decision any scheduler makes -- see
    # scheduler/heuristic/__init__.py and scheduler/milp/__init__.py.
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
        'N_bay': N_BAY,
        'T': T,
        'dt': DT,
    }
