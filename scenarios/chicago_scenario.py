"""
One-off scenario replica of the N=6/V=30/D=317 Chicago stress-test run
recorded in a separate prior research notebook
(Toytrial/notebooks/v5_diagnostics.ipynb, Section 3c), reproduced here
against this repo's actual NetworkClass/FleetClass/BuildingClass so a
MILPScheduler can be built and compared against HeuristicScheduler on
identical objects.

Not a general-purpose loader -- data/loaders/ is for that. This is a
fully-specified, one-time scenario construction tied to this exact
comparison.
"""
import math

import pandas as pd

from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building

TAXI_CSV_PATH = (
    r"C:\Users\Lenovo\Documents\PhD Folder\99_Extras\Code\Toytrial"
    r"\data\Taxi_Trips_(2013-2023)_20260121.csv"
)
TARGET_DATE = "2019-01-02"

N_ACTIVE = 6            # top-6 Chicago community areas by trip volume
DEPOT = 0                # node 0 = highest-volume area = depot
BUILDING_NODES = [1, 2]  # nodes 1, 2 = 2nd/3rd highest-volume areas
T = 24                   # hourly resolution, matches source notebook
DT = 1.0

# V=30 came from a feasibility search in the source notebook (incrementing
# fleet size until the MILP became feasible at N=6) -- not re-derived here,
# just reused as the recorded outcome (stress_frontier.jsonl).
V = 30

E_CAP = 41.3
EPS = 0.15
P_BAR = 10.0
S_MIN = 0.1
S_MAX = 0.9
S_INIT = 0.8
Q_BLDG = 200.0
N_BAY = 5
LAM = 1.0

# RC params: only existing occurrence in this repo (_staging/examples/run_demo.py).
# No evidence these are fitted to real Chicago-zone thermal behavior -- placeholders.
RC_A = 0.05
RC_B = 0.02
HVAC_MAX = 80.0
T_INIT = 24.0
T_MIN = 20.0   # flat comfort band -- occupancy isn't wired into this repo
T_MAX = 26.0

# Synthetic building load, reused verbatim from the source notebook's Section 3c
# (placeholder -- swapping in real BDG2 data is future work, no loader exists yet).
def _synthetic_load(t):
    return 200.0 * math.sin(math.pi * t / 12) ** 2 + 50.0


def _haversine_miles_and_tau(lon1, lat1, lon2, lat2):
    R = 6371
    ph1, ph2 = math.radians(lat1), math.radians(lat2)
    dph = math.radians(lat2 - lat1)
    dlm = math.radians(lon2 - lon1)
    a = math.sin(dph / 2) ** 2 + math.cos(ph1) * math.cos(ph2) * math.sin(dlm / 2) ** 2
    km = 2 * R * math.asin(math.sqrt(a))
    # Preserved deliberately: despite the name, this is MILES (km * 0.621371),
    # matching the source notebook exactly -- eps was calibrated against this
    # value, don't "fix" the mislabeling.
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
    # Trip Seconds loads as object dtype (mixed/garbage values) -- coerce to
    # numeric so `.notna()` actually means "a real numeric value", matching
    # the source notebook's preprocessing exactly.
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

    # Dedup by (origin, dest, hour), first occurrence in row order -- deterministic,
    # no RNG involved (a seed claim from an earlier task brief for this pool was
    # checked and found not to apply here).
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
    load_profile = {b: dict(shared_load) for b in BUILDING_NODES}  # per-building, same formula for both here
    n_chargers = int(Q_BLDG / P_BAR)
    rc_params = {
        b: {'a': RC_A, 'b': RC_B, 'hvac_max': HVAC_MAX, 't_init': T_INIT}
        for b in BUILDING_NODES
    }
    buildings = BuildingClass([
        Building(
            b_id=b, load_profile=dict(load_profile[b]), n_chargers=n_chargers,
            rc=dict(rc_params[b]),
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
        'rc_params': rc_params,
        't_min': T_MIN,
        't_max': T_MAX,
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
