"""
Adversarial stress test: a scheduler that returns intentionally extreme,
malformed, or contradictory decisions every timestep -- huge/negative/NaN/
inf power requests, arcs that don't originate at the vehicle's current
node, NaN/inf/out-of-range building setpoints -- to confirm Vehicle.step()/
Building.step() clamp to physically valid values no matter what a scheduler
sends, not just under well-behaved heuristics. Plain asserts, no test
framework, matching tests/test_heuristic.py's style.
"""
import random

from simulator import Simulator
from scheduler.base import BaseScheduler
from scenarios.toy_scenario import build_scenario

EXTREME = [float('inf'), float('-inf'), float('nan'), 1e12, -1e12]


class AdversarialScheduler(BaseScheduler):
    """Not a published scheduler -- a fuzzer. Ignores every soft convention
    a well-behaved scheduler would respect (arc/current-node adjacency, sane
    power magnitude, sane setpoints), to confirm the physics layer clamps
    regardless of what it's handed."""

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def decide(self, state):
        arcs = list(state['network']['arcs'].keys())
        fleet = []
        for _ in state['fleet']:
            if self.rng.random() < 0.3:
                fleet.append({'arc': self.rng.choice(arcs), 'p': self.rng.choice(EXTREME)})
            else:
                fleet.append({'arc': None, 'p': self.rng.choice(EXTREME)})
        buildings = {b['b_id']: self.rng.choice(EXTREME + [None]) for b in state['buildings']}
        return {'fleet': fleet, 'buildings': buildings}


def _fresh_sim():
    # Rebuild from scratch each time -- Simulator.__init__ only resets
    # vehicle .node, not .arc/.arc_remaining/.soc, so reusing one
    # build_scenario() dict's Vehicle objects across multiple Simulators
    # leaks mid-transit state between them.
    scenario = build_scenario()
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    return sim, scenario


if __name__ == '__main__':
    sim, scenario = _fresh_sim()
    scheduler = AdversarialScheduler(seed=42)

    for _ in range(scenario['T']):
        state = sim.get_state()
        sim.step(scheduler.decide(state))

        for v in sim.fleet.vehicles:
            assert v.s_min <= v.soc <= v.s_max, \
                f"t={state['t']}: vehicle {v.v_id} soc {v.soc} out of [{v.s_min},{v.s_max}]"
            assert -v.p_max <= v.p <= v.p_max, \
                f"t={state['t']}: vehicle {v.v_id} p {v.p} out of [-{v.p_max},{v.p_max}]"

        for b in sim.buildings.buildings:
            assert b.p_hvac >= 0.0, f"t={state['t']}: building {b.b_id} p_hvac {b.p_hvac} negative"
            if b.rc is not None:
                assert b.p_hvac <= b.rc.get('hvac_max', 10.0), \
                    f"t={state['t']}: building {b.b_id} p_hvac {b.p_hvac} exceeds hvac_max"
                assert b.t_in == b.t_in and abs(b.t_in) != float('inf'), \
                    f"t={state['t']}: building {b.b_id} t_in {b.t_in} is NaN/inf"
            assert b.p_grid == b.p_grid and b.p_cons == b.p_cons, \
                f"t={state['t']}: building {b.b_id} produced NaN power"

    print(f"PASS: {scenario['T']} timesteps of adversarial decisions (extreme/NaN/inf power, "
          f"NaN/inf/out-of-range setpoints, arc teleports) -- SoC, power, and HVAC stayed in bounds throughout")

    # Contradictory decision: both 'arc' and a huge 'p' in the same dict --
    # confirm the arc branch wins outright and p is reset to 0, not summed
    # or applied alongside the arc move.
    sim2, _ = _fresh_sim()
    arcs = list(sim2.network.arcs.keys())
    sim2.step({
        'fleet': [{'arc': arcs[0], 'p': 1e9}] + [{'arc': None, 'p': 0.0} for _ in sim2.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim2.buildings.buildings},
    })
    assert sim2.fleet.vehicles[0].p == 0.0, \
        f"expected p reset to 0 when arc decision taken, got {sim2.fleet.vehicles[0].p}"
    print("PASS: contradictory decision (arc + huge p) -- arc wins, p silently ignored, not summed")

    # Documented non-invariant, not a bug: arc/current-node adjacency isn't
    # validated by Vehicle.step() -- routing correctness is the Scheduler's
    # responsibility, the Simulator just applies whatever arc it's
    # given. A vehicle at the depot handed arc ('A','B') -- which it was
    # never physically on -- teleports straight to 'B' and pays that arc's
    # energy cost, no adjacency check anywhere in the physics layer.
    sim3, scenario3 = _fresh_sim()
    assert sim3.fleet.vehicles[0].node == scenario3['network'].depot
    sim3.step({
        'fleet': [{'arc': ('A', 'B'), 'p': 0.0}] + [{'arc': None, 'p': 0.0} for _ in sim3.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim3.buildings.buildings},
    })
    assert sim3.fleet.vehicles[0].node == 'B' and sim3.fleet.vehicles[0].arc is None, \
        "expected an unvalidated ('A','B') arc from the depot to teleport the vehicle straight to 'B'"
    print("PASS: confirmed (documented, not a bug) -- arc/current-node adjacency is not validated by the physics layer")

    print("\nAll adversarial checks passed.")
