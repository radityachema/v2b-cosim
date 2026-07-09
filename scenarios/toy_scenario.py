"""Minimal hand-typed scenario for sanity-checking Simulator/Scheduler plumbing."""
from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building

T = 96
DT = 0.25


def build_scenario():
    network = NetworkClass(
        nodes={'depot', 'A', 'B'},
        arcs={
            ('depot', 'A'): {'tau': 2, 'e': 0.05, 'd': 5},
            ('depot', 'B'): {'tau': 3, 'e': 0.07, 'd': 8},
            ('A', 'B'):     {'tau': 1, 'e': 0.03, 'd': 3},
            ('B', 'A'):     {'tau': 1, 'e': 0.03, 'd': 3},
        },
        building_nodes={'A', 'B'},
        depot='depot',
    )

    ride_demand = RideDemandClass(demands=[
        {'id': 0, 'i_d': 'A', 'j_d': 'B', 't_d': 10},
    ])

    fleet = FleetClass([
        Vehicle(v_id=i, soc_init=0.8, e_cap=60, p_max=11, s_min=0.1, s_max=0.9)
        for i in range(3)
    ])

    buildings = BuildingClass([
        Building(b_id='A', load_profile={t: 45.0 for t in range(T)}, n_chargers=5,
                 rc={'a': 0.1, 'b': 0.05, 'hvac_max': 15.0, 't_init': 28.0}),
        Building(b_id='B', load_profile={t: 30.0 for t in range(T)}, n_chargers=3),
    ])

    return {
        'network': network,
        'ride_demand': ride_demand,
        'fleet': fleet,
        'buildings': buildings,
        'dt': DT,
        'T': T,
    }
