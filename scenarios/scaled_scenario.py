"""Scaled Chicago scenario: a configurable number of community areas N, with
the number of buildings scaled to the system size, as in the joint routing +
V2B MILP paper (P2).

    build_scenario(n_nodes=11, n_vehicles=None, n_buildings=None)

- Nodes: the N highest-trip-volume Chicago community areas on TARGET_DATE
  (node 0 = highest volume = depot).
- Buildings: nodes 1 .. n_B, with n_B = min(ceil(2N/3), 16, N-1). The cap of 16
  is the number of DOE reference-building types available; N-1 keeps at least
  the depot free of a charger. N=3 gives 2 buildings, N=11 gives 8, N>=24 gives 16.
- n_buildings (optional): any number from 1 to N-1 (depot excluded). With
  n_buildings=None the rule above applies (the default, unchanged). A count
  above 16 reuses the 16 DOE types by cycling.
- Building types: the k-th highest-volume building node (k = 1, 2, ...) gets
  BUILDING_TYPES_BY_PEAK[(k-1) % 16], the k-th highest-annual-peak DOE type,
  the same rule as the MILP paper. Beyond 16 buildings the sequence simply
  wraps: node 17 gets LargeOffice again, node 18 Hospital, and so on, so
  each type is reused on the next-highest-volume nodes.
- hvac_max (placeholder physics, like small/chicago): HVAC_FRACTION x the
  type's annual peak load. The other RC parameters are the same placeholders
  used in small_scenario.py.
- Vehicles: n_vehicles, default round(250 * N / 77), i.e. the city-scale ratio.
- Everything else (EV battery, charger, SoC bounds, day, time step) is imported
  from chicago_scenario.py so the scenarios cannot drift apart.

small_scenario.py and chicago_scenario.py are left untouched: the ASIM 2026
results come from small_scenario.py. Heuristic/Null only beyond small N; the
MILP does not solve at city scale (see chicago_scenario.py's docstring)."""
import math
from functools import lru_cache

import pandas as pd

from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from data.loaders.doe_chicago import load_doe_chicago_load
from data.loaders.tmy3_weather import load_tmy3_outdoor_temp
from scenarios.chicago_scenario import (
    TAXI_CSV_PATH, TARGET_DATE, DOE_CHICAGO_DIR, TMY3_WEATHER_PATH, DOE_MONTH, DOE_DAY,
    DEPOT, T, DT, E_CAP, EPS, P_BAR, S_MIN, S_MAX, S_INIT, Q_BLDG, LAM,
    _haversine_miles_and_tau,
)

# DOE Commercial Reference Building types in descending annual-peak order
# (Chicago/O'Hare: LargeOffice 1657.7 kW ... SmallOffice 19.6 kW).
BUILDING_TYPES_BY_PEAK = [
    'LargeOffice', 'Hospital', 'SecondarySchool', 'LargeHotel', 'SuperMarket',
    'PrimarySchool', 'MediumOffice', 'OutPatient', 'SmallHotel', 'StandaloneRetail',
    'StripMall', 'Warehouse', 'FullServiceRestaurant', 'MidriseApartment',
    'QuickServiceRestaurant', 'SmallOffice',
]
MAX_BUILDINGS = len(BUILDING_TYPES_BY_PEAK)
HVAC_FRACTION = 0.16  # hvac_max = this x annual peak (small_scenario: 50/319 and 25/136 kW)
_LOAD_COL = 'Electricity:Facility [kW](Hourly)'
V_PER_NODE = 250 / 77  # city-scale fleet ratio


def n_buildings_for(n_nodes):
    """Buildings for N nodes: ceil(2N/3), capped at the 16 DOE types and at N-1."""
    return max(1, min(math.ceil(2 * n_nodes / 3), MAX_BUILDINGS, n_nodes - 1))


def default_vehicles(n_nodes):
    return max(1, round(V_PER_NODE * n_nodes))


@lru_cache(maxsize=None)
def _annual_peak_kw(path):
    return float(pd.read_csv(path, usecols=[_LOAD_COL])[_LOAD_COL].max())


def build_scenario(n_nodes=11, n_vehicles=None, n_buildings=None):
    if n_nodes < 2:
        raise ValueError("n_nodes must be >= 2 (a depot plus at least one building)")
    V = default_vehicles(n_nodes) if n_vehicles is None else int(n_vehicles)
    if n_buildings is None:
        n_b = n_buildings_for(n_nodes)
    else:
        n_b = int(n_buildings)
        if not 1 <= n_b <= n_nodes - 1:
            raise ValueError(f"n_buildings must be between 1 and N-1 = {n_nodes - 1}, got {n_b}")
    building_nodes = list(range(1, 1 + n_b))
    building_type = {b: BUILDING_TYPES_BY_PEAK[(b - 1) % MAX_BUILDINGS] for b in building_nodes}

    df = pd.read_csv(TAXI_CSV_PATH, low_memory=False)
    df['Trip Start Timestamp'] = pd.to_datetime(df['Trip Start Timestamp'])
    day = df[df['Trip Start Timestamp'].dt.date == pd.Timestamp(TARGET_DATE).date()].copy()
    day['Trip Seconds'] = pd.to_numeric(day['Trip Seconds'], errors='coerce')
    day['Trip Miles'] = pd.to_numeric(day['Trip Miles'], errors='coerce')

    pu_cnt = day['Pickup Community Area'].value_counts()
    do_cnt = day['Dropoff Community Area'].value_counts()
    vol = pu_cnt.add(do_cnt, fill_value=0).dropna()
    vol.index = vol.index.astype(int)
    top_areas = list(vol.sort_values(ascending=False).head(n_nodes).index)
    if len(top_areas) < n_nodes:
        raise ValueError(f"only {len(top_areas)} community areas have trips on {TARGET_DATE}")
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

    dist, tau = {}, {}
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i == j:
                dist[i, j] = 0.0
                tau[i, j] = 1
                continue
            lon1, lat1 = centroids[i]
            lon2, lat2 = centroids[j]
            dist[i, j], tau[i, j] = _haversine_miles_and_tau(lon1, lat1, lon2, lat2)

    day['on'] = day['Pickup Community Area'].map(node_map)
    day['dn'] = day['Dropoff Community Area'].map(node_map)
    valid = (day['on'].notna() & day['dn'].notna() & (day['on'] != day['dn']) &
             (day['Trip Miles'] > 0) & day['Trip Seconds'].notna())
    trips = day[valid].copy()
    trips['on'] = trips['on'].astype(int)
    trips['dn'] = trips['dn'].astype(int)
    trips['th'] = (trips['Trip Start Timestamp'].dt.hour * 4
                   + trips['Trip Start Timestamp'].dt.minute // 15)

    # Dedup by (origin, dest, slot), first occurrence in row order -- deterministic.
    pool, seen = {}, set()
    for _, row in trips.iterrows():
        o, d, td = int(row['on']), int(row['dn']), int(row['th'])
        if td < 1 or td >= T - 1:
            continue
        if (o, d, td) in seen:
            continue
        seen.add((o, d, td))
        pool[len(pool)] = (o, d, td)

    demands_milp = {}
    for o, d, td in pool.values():
        tau_to = tau[DEPOT, o] if o != DEPOT else 0
        if o != DEPOT and td < tau_to + 2:
            continue
        tau_back = tau[d, DEPOT] if d != DEPOT else 0
        if td + tau[o, d] + tau_back >= T:
            continue
        demands_milp[len(demands_milp)] = (o, d, td, dist[o, d])

    arcs = {}
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i != j:
                arcs[(i, j)] = {'tau': tau[i, j], 'e': dist[i, j] * EPS / E_CAP, 'd': dist[i, j]}

    network = NetworkClass(nodes=set(range(n_nodes)), arcs=arcs,
                           building_nodes=set(building_nodes), depot=DEPOT)
    ride_demand = RideDemandClass(demands=[
        {'id': did, 'i_d': o, 'j_d': d, 't_d': td}
        for did, (o, d, td, _dk) in demands_milp.items()
    ])
    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=S_INIT, e_cap=E_CAP, p_max=P_BAR, s_min=S_MIN, s_max=S_MAX)
        for i in range(V)
    ])

    load_profile, rc_by_node = {}, {}
    for b in building_nodes:
        path = DOE_CHICAGO_DIR / f"{building_type[b]}.csv"
        load_profile[b] = load_doe_chicago_load(path, DOE_MONTH, DOE_DAY)
        rc_by_node[b] = {'a': 0.0417, 'b': 0.006,
                         'hvac_max': round(HVAC_FRACTION * _annual_peak_kw(path), 1),
                         't_init': 26.0, 't_sp_min': 20.0, 't_sp_max': 26.0}
    n_chargers = int(Q_BLDG / P_BAR)
    weather = load_tmy3_outdoor_temp(TMY3_WEATHER_PATH, DOE_MONTH, DOE_DAY)
    buildings = BuildingClass([
        Building(b_id=b, load_profile=dict(load_profile[b]), n_chargers=n_chargers,
                 rc=rc_by_node[b], weather=dict(weather))
        for b in building_nodes
    ])

    return {
        'network': network, 'ride_demand': ride_demand, 'fleet': fleet, 'buildings': buildings,
        'demands_milp': demands_milp, 'nodes': list(range(n_nodes)),
        'building_nodes': list(building_nodes), 'building_types': dict(building_type),
        'depot': DEPOT, 'vehicles_list': list(range(V)), 'load_profile': load_profile,
        'lam': LAM, 'E_cap': E_CAP, 'eps': EPS, 'P_bar': P_BAR, 'S_min': S_MIN,
        'S_max': S_MAX, 'S_init': S_INIT, 'Q_bldg': Q_BLDG, 'T': T, 'dt': DT,
    }
