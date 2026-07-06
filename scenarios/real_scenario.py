"""
Real-data scenario: Chicago Taxi trips for fleet demand, BDG2 electricity +
weather for building load/thermal.

No BDG2 site is actually in Chicago (checked directly -- closest US_Central
sites are Austin, TX and Minneapolis, MN). This pairs a real Chicago fleet
demand day with a real BDG2 building's load/weather from a different city.
That's fine for demonstrating the loaders + scheduler + metrics pipeline
works end-to-end on real (not synthetic) data -- it is not a claim about a
geographically coherent deployment.
"""
from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from data.loaders.fleet import load_chicago_taxi_demands
from data.loaders.building import load_bdg2_load, load_bdg2_weather

TAXI_CSV = (
    r"C:\Users\Lenovo\Documents\PhD Folder\99_Extras\Code\Toytrial"
    r"\data\Taxi_Trips_(2013-2023)_20260121.csv"
)
BDG2_ELEC = (
    r"C:\Users\Lenovo\Documents\PhD Folder\99_Extras\Code\Toytrial"
    r"\building-data-genome-project-2\data\meters\cleaned\electricity_cleaned.csv"
)
BDG2_WEATHER = (
    r"C:\Users\Lenovo\Documents\PhD Folder\99_Extras\Code\Toytrial"
    r"\building-data-genome-project-2\data\weather\weather.csv"
)

TAXI_DATE = "2019-01-02"
BDG2_DATE = "2016-06-15"
T = 24
DT = 1.0

# Chicago Community Areas: 8 (depot, highest-volume), 32/28 (buildings).
NODE_MAP = {8: 0, 32: 1, 28: 2}
DEPOT = 0
BUILDING_NODES = [1, 2]


def build_scenario():
    network = NetworkClass(
        nodes=set(NODE_MAP.values()),
        arcs={
            (i, j): {'tau': 1, 'e': 0.05, 'd': 5.0}
            for i in NODE_MAP.values() for j in NODE_MAP.values() if i != j
        },
        building_nodes=set(BUILDING_NODES),
        depot=DEPOT,
    )

    demands = load_chicago_taxi_demands(TAXI_CSV, TAXI_DATE, NODE_MAP)
    ride_demand = RideDemandClass(demands=demands)

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=0.8, e_cap=60, p_max=11, s_min=0.2, s_max=1.0)
        for i in range(5)
    ])

    load_1 = load_bdg2_load(BDG2_ELEC, 'Panther_office_Hannah', BDG2_DATE)
    load_2 = load_bdg2_load(BDG2_ELEC, 'Panther_office_Catherine', BDG2_DATE)
    weather = load_bdg2_weather(BDG2_WEATHER, 'Panther', BDG2_DATE)

    buildings = BuildingClass([
        Building(b_id=1, load_profile=load_1, n_chargers=5,
                 rc={'a': 0.05, 'b': 0.02, 'hvac_max': 80.0, 't_init': 24.0},
                 weather=weather),
        Building(b_id=2, load_profile=load_2, n_chargers=5),
    ])

    return {
        'network': network,
        'ride_demand': ride_demand,
        'fleet': fleet,
        'buildings': buildings,
        'dt': DT,
        'T': T,
    }
