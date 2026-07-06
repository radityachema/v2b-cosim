from simulator import Simulator
from simulator.network import NetworkClass
from simulator.ride_demand import RideDemandClass
from simulator.fleet import FleetClass, Vehicle
from simulator.building import BuildingClass, Building
from scheduler.heuristic import HeuristicScheduler

if __name__ == '__main__':
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
        Building(b_id='A', load_profile={t: 45.0 for t in range(96)}, n_chargers=5,
                 rc={'a': 0.1, 'b': 0.05, 'hvac_max': 15.0, 't_init': 28.0}),
        Building(b_id='B', load_profile={t: 30.0 for t in range(96)}, n_chargers=3),
    ])

    sim = Simulator(network, ride_demand, fleet, buildings, dt=0.25)
    scheduler = HeuristicScheduler()

    b_a_t_init = buildings.buildings[0].t_in
    demand_arc_count_at_t10 = 0

    for _ in range(96):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        if state['t'] == 10:
            for dec in decisions['fleet']:
                if dec['arc'] == ('A', 'B'):
                    demand_arc_count_at_t10 += 1

        sim.step(decisions)

    print(f"Scaffold OK — ran {sim.t} timesteps")

    for v in sim.fleet.vehicles:
        assert 0.1 <= v.soc <= 0.9, f"vehicle {v.v_id} soc {v.soc} out of bounds"
    print("PASS: all vehicles within [s_min, s_max]")

    assert demand_arc_count_at_t10 == 1, f"expected exactly 1 vehicle serving demand at t=10, got {demand_arc_count_at_t10}"
    print("PASS: seeded demand served exactly once at t=10 (dedup confirmed)")

    b_a_final = sim.buildings.buildings[0].t_in
    assert b_a_final != b_a_t_init, f"Mode B building t_in did not move from t_init={b_a_t_init}"
    print(f"PASS: Mode B building t_in moved from {b_a_t_init} to {b_a_final:.3f}")

    b_b = sim.buildings.buildings[1]
    assert b_b.t_in is None, "Mode A building should have no t_in"
    print("PASS: Mode A building has no thermal state")

    print("\nAll verification checks passed.")
