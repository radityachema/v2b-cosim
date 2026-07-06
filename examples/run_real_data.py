"""
End-to-end run of HeuristicScheduler against real data: Chicago Taxi trips
for fleet demand, BDG2 electricity + weather for building load/thermal.

Note: no BDG2 site is actually in Chicago (checked -- closest US_Central
sites are Austin and Minneapolis). This pairs a real Chicago fleet demand
day with a real BDG2 building's load/weather from a different city. That's
fine for what this script demonstrates -- the loaders, HeuristicScheduler,
and metrics pipeline working end-to-end on real (not synthetic) data --
but it is not a claim about a geographically coherent deployment.
"""
from simulator import Simulator
from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from scheduler.heuristic import HeuristicScheduler
from data.loaders.fleet import load_chicago_taxi_demands
from data.loaders.building import load_bdg2_load, load_bdg2_weather
from evaluation import metrics

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

# Chicago Community Areas: 8 (depot, highest-volume), 32/28 (buildings) --
# same node choice already verified against the loader in isolation.
NODE_MAP = {8: 0, 32: 1, 28: 2}
DEPOT = 0
BUILDING_NODES = [1, 2]

if __name__ == '__main__':
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
    print(f"Loaded {len(demands)} real ride demands from {TAXI_DATE}")

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=0.8, e_cap=60, p_max=11, s_min=0.2, s_max=1.0)
        for i in range(5)
    ])

    load_1 = load_bdg2_load(BDG2_ELEC, 'Panther_office_Hannah', BDG2_DATE)
    load_2 = load_bdg2_load(BDG2_ELEC, 'Panther_office_Catherine', BDG2_DATE)
    weather = load_bdg2_weather(BDG2_WEATHER, 'Panther', BDG2_DATE)
    print(f"Loaded real BDG2 load ({len(load_1)}h) and weather ({len(weather)}h) for {BDG2_DATE}")

    buildings = BuildingClass([
        Building(b_id=1, load_profile=load_1, n_chargers=5,
                 rc={'a': 0.05, 'b': 0.02, 'hvac_max': 80.0, 't_init': 24.0},
                 weather=weather),
        Building(b_id=2, load_profile=load_2, n_chargers=5),
    ])

    sim = Simulator(network, ride_demand, fleet, buildings, dt=DT)
    scheduler = HeuristicScheduler()

    p_load_hist = {b.b_id: [] for b in buildings.buildings}
    p_grid_hist = {b.b_id: [] for b in buildings.buildings}
    p_v2b_hist = {b.b_id: [] for b in buildings.buildings}
    p_cons_hist = {b.b_id: [] for b in buildings.buildings}
    served_demand_ids = set()

    for _ in range(T):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        due_arcs = {(d['i_d'], d['j_d']): d['id'] for d in state['demands']}
        for dec in decisions['fleet']:
            if dec['arc'] in due_arcs:
                served_demand_ids.add(due_arcs[dec['arc']])

        sim.step(decisions)

        t = state['t']
        for b in sim.buildings.buildings:
            p_load_hist[b.b_id].append(b.load_profile.get(t, 0.0))
            p_grid_hist[b.b_id].append(b.p_grid)
            p_cons_hist[b.b_id].append(b.p_cons)
        for b_id, v in sim.p_v2b.items():
            p_v2b_hist[b_id].append(v)

    served_demands = [d for d in demands if d['id'] in served_demand_ids]

    print(f"\nRan {sim.t} timesteps on real data. Results:")
    for b_id in (1, 2):
        dp = metrics.peak_reduction(p_load_hist[b_id], p_grid_hist[b_id])
        eta = metrics.v2b_utilization(p_v2b_hist[b_id], p_cons_hist[b_id])
        phi = metrics.temporal_alignment(p_v2b_hist[b_id], p_load_hist[b_id])
        print(f"  Building {b_id}: peak_reduction={dp:.2f} kW, "
              f"v2b_utilization={eta:.2%}, temporal_alignment={phi:.3f}")

    rho = metrics.demand_fulfillment(served_demands, demands, network)
    print(f"  Fleet: demand_fulfillment (rho) = {rho:.2%} "
          f"({len(served_demands)}/{len(demands)} demands served)")
