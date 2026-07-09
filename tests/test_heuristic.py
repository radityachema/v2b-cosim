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

    # HeuristicScheduler makes no thermal decision -- AC setpoint is a
    # constant (None) for this paper's published checkpoint, not something
    # any scheduler decides. Confirm that directly rather than just via its
    # downstream effect.
    assert all(t_sp is None for t_sp in decisions['buildings'].values()), \
        f"expected every building decision to be None (no thermal decision), got {decisions['buildings']}"
    print("PASS: HeuristicScheduler makes no building thermal decision")

    # Mode B building's t_in still moves -- but now via passive RC physics
    # (drift toward outdoor temp) only, since p_hvac stays 0 with no
    # setpoint decision. Confirms Building.step()'s RC dynamics still run
    # on their own, independent of any scheduler decision.
    b_a_final = sim.buildings.buildings[0].t_in
    assert b_a_final != b_a_t_init, f"Mode B building t_in did not passively drift from t_init={b_a_t_init}"
    print(f"PASS: Mode B building t_in passively drifted from {b_a_t_init} to {b_a_final:.3f} (no active HVAC)")

    b_b = sim.buildings.buildings[1]
    assert b_b.t_in is None, "Mode A building should have no t_in"
    print("PASS: Mode A building has no thermal state")

    print("\nAll verification checks passed.")
