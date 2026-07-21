"""
Assertion-based correctness check for HeuristicScheduler, decoupled from
the interactive runner.py (that's for exploration, this is for verifying
nothing broke). Plain asserts, no test framework dependency, matching the
rest of this repo's verification style.
"""
from simulator import Simulator
from scheduler.heuristic import HeuristicScheduler
from scenarios.toy_scenario import build_scenario

if __name__ == '__main__':
    scenario = build_scenario()
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    scheduler = HeuristicScheduler()

    b_a_t_init = sim.buildings.buildings[0].t_in
    demand_arc_count_at_t10 = 0

    for _ in range(scenario['T']):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        if state['t'] == 10:
            for dec in decisions['fleet']:
                if dec['arc'] == ('A', 'B'):
                    demand_arc_count_at_t10 += 1

        sim.step(decisions)

    for v in sim.fleet.vehicles:
        assert v.s_min <= v.soc <= v.s_max, f"vehicle {v.v_id} soc {v.soc} out of bounds"
    print("PASS: all vehicles within [s_min, s_max]")

    assert demand_arc_count_at_t10 == 1, \
        f"expected exactly 1 vehicle serving demand at t=10, got {demand_arc_count_at_t10}"
    print("PASS: seeded demand served exactly once at t=10 (dedup confirmed)")

    # HeuristicScheduler returns a fixed comfort setpoint (T_SP_FIXED) for
    # every building -- constant, not decided per-timestep, but no longer
    # None: Mode B buildings' bang-bang relay is meant to actually engage.
    assert all(t_sp == HeuristicScheduler.T_SP_FIXED for t_sp in decisions['buildings'].values()), \
        f"expected every building decision to equal T_SP_FIXED, got {decisions['buildings']}"
    print("PASS: HeuristicScheduler returns the fixed comfort setpoint for every building")

    # Mode B building's t_in should now trend down from its warm t_init
    # toward T_SP_FIXED under active bang-bang HVAC, not just passively
    # drift toward outdoor temp.
    b_a_final = sim.buildings.buildings[0].t_in
    assert b_a_final < b_a_t_init, \
        f"Mode B building t_in should cool from t_init={b_a_t_init} under active HVAC, got {b_a_final}"
    print(f"PASS: Mode B building t_in cooled from {b_a_t_init} to {b_a_final:.3f} under active HVAC")

    b_b = sim.buildings.buildings[1]
    assert b_b.t_in is None, "Mode A building should have no t_in"
    print("PASS: Mode A building has no thermal state")

    print("\nAll verification checks passed.")
