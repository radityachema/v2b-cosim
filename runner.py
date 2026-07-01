from simulator import Simulator
from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from scheduler.base import NullScheduler

if __name__ == '__main__':
    network = NetworkClass(
        nodes={'A', 'B', 'depot'},
        arcs={
            ('depot', 'A'): {'tau': 2, 'e': 0.05, 'd': 5},
            ('A', 'B'):     {'tau': 1, 'e': 0.03, 'd': 3},
        },
        building_nodes={'A', 'B'},
        depot='depot',
    )

    ride_demand = RideDemandClass(demands=[
        {'id': 0, 'i_d': 'A', 'j_d': 'B', 't_d': 10},
    ])

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=0.8, e_cap=60, p_max=11, s_min=0.2, s_max=1.0)
        for i in range(3)
    ])

    buildings = BuildingClass([
        Building(b_id='A', load_profile={t: 40.0 for t in range(96)}, n_chargers=5),
        Building(b_id='B', load_profile={t: 30.0 for t in range(96)}, n_chargers=3),
    ])

    sim = Simulator(network, ride_demand, fleet, buildings, dt=0.25)
    scheduler = NullScheduler()

    for _ in range(96):
        state = sim.get_state()
        decisions = scheduler.decide(state)
        sim.step(decisions)

    print(f"Scaffold OK — ran {sim.t} timesteps")
    print(f"Vehicle 0 final SoC: {sim.fleet.vehicles[0].soc:.3f}")
    print(f"Building A p_grid final: {sim.buildings.buildings[0].p_grid:.1f} kW")
