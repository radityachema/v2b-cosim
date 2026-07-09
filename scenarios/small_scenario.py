"""Small quick-start scenario: real Chicago Taxi demand + real BDG2 building load/weather,
5 vehicles, 3 nodes. See chicago_scenario.py for a larger, synthetic-load variant."""
from pathlib import Path

from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from data.loaders.fleet import load_chicago_taxi_demands
from data.loaders.building import load_bdg2_load, load_bdg2_weather

# See data/README.md for where to get these files.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAXI_CSV = DATA_DIR / "chicago_taxi_trips.csv"
BDG2_ELEC = DATA_DIR / "bdg2" / "electricity_cleaned.csv"
BDG2_WEATHER = DATA_DIR / "bdg2" / "weather.csv"

TAXI_DATE = "2019-01-02"
BDG2_DATE = "2016-06-15"
T = 24
DT = 1.0

# Chicago Community Areas: 8 (depot, highest-volume), 32/28 (buildings).
NODE_MAP = {8: 0, 32: 1, 28: 2}
DEPOT = 0
BUILDING_NODES = [1, 2]
V = 5

# Fleet params (also used by the MILP model -- same source, no duplicate copy)
E_CAP = 60.0
P_BAR = 11.0
S_MIN = 0.2
S_MAX = 1.0
S_INIT = 0.8
N_CHARGERS = 5
Q_BLDG = N_CHARGERS * P_BAR

# MILP demand-service floor; lam=1.0 is infeasible at this fleet size, lam=0.3 is the
# largest value that solves in reasonable time.
LAM = 0.3

BUILDING_METER_ID = {1: 'Panther_office_Catherine', 2: 'Panther_office_Hannah'}


def build_scenario():
    # placeholder arcs (same {tau, e, d} for every pair) -- unlike chicago_scenario.py,
    # real travel times aren't modeled here
    network = NetworkClass(
        nodes=set(NODE_MAP.values()),
        arcs={
            (i, j): {'tau': 1, 'e': 0.05, 'd': 5.0}
            for i in NODE_MAP.values() for j in NODE_MAP.values() if i != j
        },
        building_nodes=set(BUILDING_NODES),
        depot=DEPOT,
    )

    demands = load_chicago_taxi_demands(str(TAXI_CSV), TAXI_DATE, NODE_MAP)
    ride_demand = RideDemandClass(demands=demands)

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=S_INIT, e_cap=E_CAP, p_max=P_BAR, s_min=S_MIN, s_max=S_MAX)
        for i in range(V)
    ])

    weather = load_bdg2_weather(str(BDG2_WEATHER), 'Panther', BDG2_DATE)
    load_profile = {
        b: load_bdg2_load(str(BDG2_ELEC), BUILDING_METER_ID[b], BDG2_DATE)
        for b in BUILDING_NODES
    }

    # Mode A: rc=None, no thermal decision for this scenario. weather is loaded anyway
    # so switching to Mode B later is a one-line change.
    buildings = BuildingClass([
        Building(b_id=b, load_profile=dict(load_profile[b]), n_chargers=N_CHARGERS,
                 rc=None, weather=weather)
        for b in BUILDING_NODES
    ])

    # MILP-compatible fields -- same scenario, so MILPScheduler can plug in too.
    demands_milp = {
        d['id']: (d['i_d'], d['j_d'], d['t_d'], network.get_arc(d['i_d'], d['j_d'])['d'])
        for d in demands
    }

    return {
        'network': network,
        'ride_demand': ride_demand,
        'fleet': fleet,
        'buildings': buildings,
        'dt': DT,
        'T': T,
        # MILP-specific fields -- ignored by Null/HeuristicScheduler, read by MILPScheduler
        'nodes': list(NODE_MAP.values()),
        'building_nodes': list(BUILDING_NODES),
        'depot': DEPOT,
        'vehicles_list': list(range(V)),
        'demands_milp': demands_milp,
        'load_profile': load_profile,
        'lam': LAM,
        'E_cap': E_CAP,
        'P_bar': P_BAR,
        'S_min': S_MIN,
        'S_max': S_MAX,
        'S_init': S_INIT,
        'Q_bldg': Q_BLDG,
    }
