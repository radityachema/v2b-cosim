"""
Plain-assert check for scenarios/scaled_scenario.py: building count rule
(ceil(2N/3), capped at 16 DOE types and N-1), type assignment by peak, and one
full Null + Heuristic day at two sizes. Run from the repo root:
    python -m tests.test_scaled_scenario
"""
from simulator import Simulator
from scheduler.base import NullScheduler
from scheduler.heuristic import HeuristicScheduler
from scenarios.scaled_scenario import (
    build_scenario, n_buildings_for, default_vehicles, BUILDING_TYPES_BY_PEAK, MAX_BUILDINGS,
)


def _run(scenario, scheduler):
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                    scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    for _ in range(scenario['T']):
        sim.step(scheduler.decide(sim.get_state()))
    for v in sim.fleet.vehicles:
        assert v.s_min - 1e-9 <= v.soc <= v.s_max + 1e-9, f"vehicle {v.v_id} soc {v.soc} out of bounds"


if __name__ == '__main__':
    # --- building-count rule (pure, no data needed)
    expected = {2: 1, 3: 2, 6: 4, 11: 8, 15: 10, 24: 16, 25: 16, 77: 16}
    for n, nb in expected.items():
        assert n_buildings_for(n) == nb, (n, n_buildings_for(n), nb)
    assert MAX_BUILDINGS == 16 and len(set(BUILDING_TYPES_BY_PEAK)) == 16
    print("PASS: building counts", expected)

    # --- builds + one simulated day
    for n in (3, 11):
        sc = build_scenario(n_nodes=n)
        nb = n_buildings_for(n)
        assert len(sc['nodes']) == n
        assert sc['building_nodes'] == list(range(1, 1 + nb)) and sc['depot'] == 0
        assert len(sc['buildings'].buildings) == nb
        assert [sc['building_types'][b] for b in sc['building_nodes']] == BUILDING_TYPES_BY_PEAK[:nb]
        assert len(sc['vehicles_list']) == default_vehicles(n)
        for name, sched in (('null', NullScheduler()), ('heuristic', HeuristicScheduler())):
            _run(build_scenario(n_nodes=n), sched)  # fresh objects: Simulator mutates them
            print(f"PASS: N={n} ({nb} buildings, {default_vehicles(n)} vehicles) {name} day ran, SoC in bounds")
    # explicit vehicle override
    assert len(build_scenario(n_nodes=3, n_vehicles=13)['vehicles_list']) == 13
    print("PASS: n_vehicles override")

    # --- n_buildings option: any count 1..N-1, types cycle in BUILDING_TYPES_BY_PEAK order
    sc = build_scenario(n_nodes=20, n_buildings=19)
    assert sc['building_nodes'] == list(range(1, 20)) and sc['depot'] == 0
    assert len(sc['buildings'].buildings) == 19
    types = [sc['building_types'][b] for b in sc['building_nodes']]
    assert types == (BUILDING_TYPES_BY_PEAK * 2)[:19], types  # node 17 reuses LargeOffice
    assert build_scenario(n_nodes=6, n_buildings=1)['building_nodes'] == [1]
    for bad in (0, 6):  # N-1 = 5 is the max; depot never gets a building
        try:
            build_scenario(n_nodes=6, n_buildings=bad)
            raise AssertionError(f"n_buildings={bad} should have been rejected")
        except ValueError:
            pass
    # default (None) is unchanged
    d = build_scenario(n_nodes=11)
    assert d['building_nodes'] == list(range(1, 1 + n_buildings_for(11)))
    _run(build_scenario(n_nodes=8, n_buildings=7), HeuristicScheduler())
    print("PASS: n_buildings option (cycling, bounds, default unchanged)")
