"""
Adversarial stress test: several deliberately extreme/malformed/contradictory
scheduler designs (not just one random fuzzer), each run against every
available scenario, to confirm Vehicle.step()/Building.step() clamp to
physically valid values no matter what a scheduler sends -- not just under
well-behaved heuristics, one lucky seed, or one scenario's topology. Plain
asserts, no test framework, matching tests/test_heuristic.py's style.

Also confirms Vehicle.step() rejects an arc that doesn't start from the
vehicle's actual current node (a real gap found in review: nothing enforced
this before -- a parked vehicle handed an unrelated arc would silently
teleport and pay that arc's energy cost). Fixed in simulator/fleet.py;
covered here so it can't regress silently.
"""
import copy
import random
from pathlib import Path

from simulator import Simulator
from scheduler.base import BaseScheduler
from scenarios.toy_scenario import build_scenario as _toy

EXTREME = [float('inf'), float('-inf'), float('nan'), 1e12, -1e12]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HAS_REAL_DATA = (DATA_DIR / "chicago_taxi_trips.csv").exists() and \
                (DATA_DIR / "bdg2" / "electricity_cleaned.csv").exists()


# ---- Adversarial scheduler designs -------------------------------------

class RandomFuzzScheduler(BaseScheduler):
    """Every decision independently randomized: extreme/NaN/inf power,
    NaN/inf/out-of-range setpoints, arcs picked without regard to a
    vehicle's current node (30% of the time)."""

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


class AlwaysMaxChargeScheduler(BaseScheduler):
    """Every idle vehicle always requests the largest possible charge, every
    building always requests the highest possible setpoint. Confirms SoC/
    t_in settle at their ceiling under sustained pressure and stay there --
    no overshoot, no runaway."""

    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': 1e9} for _ in state['fleet']],
            'buildings': {b['b_id']: 1e9 for b in state['buildings']},
        }


class AlwaysMaxDischargeScheduler(BaseScheduler):
    """Every idle vehicle always requests the largest possible discharge --
    including once SoC is already at s_min. Every building always requests
    the lowest possible setpoint (HVAC relay runs flat out). Confirms SoC/
    t_in floor out and stay there."""

    def decide(self, state):
        return {
            'fleet': [{'arc': None, 'p': -1e9} for _ in state['fleet']],
            'buildings': {b['b_id']: -1e9 for b in state['buildings']},
        }


class OscillatingScheduler(BaseScheduler):
    """Sawtooth: full charge one timestep, full discharge the next, every
    vehicle in lockstep -- the 'contradictory choices' case as a sustained,
    deterministic pattern rather than a single random spike, to catch any
    accumulation/drift bug that only shows up under repeated reversal."""

    def decide(self, state):
        sign = 1.0 if state['t'] % 2 == 0 else -1.0
        return {
            'fleet': [{'arc': None, 'p': sign * 1e9} for _ in state['fleet']],
            'buildings': {b['b_id']: (30.0 if sign > 0 else -30.0) for b in state['buildings']},
        }


class AlwaysTeleportScheduler(BaseScheduler):
    """Every idle vehicle, every timestep, is routed onto an arc chosen
    without any regard for its current node -- always, not the 30% hit rate
    RandomFuzzScheduler gets by chance. Stress-tests arc/current-node
    adjacency rejection under sustained abuse (see Vehicle.step())."""

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def decide(self, state):
        arcs = list(state['network']['arcs'].keys())
        return {
            'fleet': [{'arc': self.rng.choice(arcs), 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: None for b in state['buildings']},
        }


# ---- Invariant checks ----------------------------------------------------

def _check_invariants(sim, t, label):
    for v in sim.fleet.vehicles:
        assert v.s_min <= v.soc <= v.s_max, \
            f"[{label}] t={t}: vehicle {v.v_id} soc {v.soc} out of [{v.s_min},{v.s_max}]"
        assert -v.p_max <= v.p <= v.p_max, \
            f"[{label}] t={t}: vehicle {v.v_id} p {v.p} out of [-{v.p_max},{v.p_max}]"
    for b in sim.buildings.buildings:
        assert b.p_hvac >= 0.0, f"[{label}] t={t}: building {b.b_id} p_hvac {b.p_hvac} negative"
        if b.rc is not None:
            assert b.p_hvac <= b.rc.get('hvac_max', 10.0), \
                f"[{label}] t={t}: building {b.b_id} p_hvac {b.p_hvac} exceeds hvac_max"
            assert b.t_in == b.t_in and abs(b.t_in) != float('inf'), \
                f"[{label}] t={t}: building {b.b_id} t_in {b.t_in} is NaN/inf"
        assert b.p_grid == b.p_grid and b.p_cons == b.p_cons, \
            f"[{label}] t={t}: building {b.b_id} produced NaN power"


def run_experiment(label, scenario_template, scheduler):
    # deepcopy, not scenario_builder() again -- small/chicago scenarios load
    # real CSVs (multi-second cost) and get built once up front; a fresh
    # Simulator still needs fresh, un-mutated Vehicle/Building objects, since
    # Simulator.__init__ only resets vehicle .node, not .arc/.soc/.p (see the
    # earlier bug this caused when three experiments shared one built scenario).
    scenario = copy.deepcopy(scenario_template)
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    for _ in range(scenario['T']):
        state = sim.get_state()
        sim.step(scheduler.decide(state))
        _check_invariants(sim, state['t'], label)
    print(f"PASS: {label} ({scenario['T']} steps, {len(sim.fleet.vehicles)} vehicles)")


SCHEDULER_DESIGNS = [
    ('random-fuzz-seed0', lambda: RandomFuzzScheduler(0)),
    ('random-fuzz-seed7', lambda: RandomFuzzScheduler(7)),
    ('random-fuzz-seed99', lambda: RandomFuzzScheduler(99)),
    ('always-max-charge', AlwaysMaxChargeScheduler),
    ('always-max-discharge', AlwaysMaxDischargeScheduler),
    ('oscillating', OscillatingScheduler),
    ('always-teleport-seed0', lambda: AlwaysTeleportScheduler(0)),
]


if __name__ == '__main__':
    scenarios = [('toy', _toy())]
    if HAS_REAL_DATA:
        from scenarios.small_scenario import build_scenario as _small
        from scenarios.chicago_scenario import build_scenario as _chicago
        scenarios += [('small', _small()), ('chicago', _chicago())]
    else:
        print("SKIP: small/chicago scenarios -- real data files not found (see data/README.md)")

    for scen_name, scen_template in scenarios:
        for sched_name, sched_factory in SCHEDULER_DESIGNS:
            run_experiment(f"{scen_name}/{sched_name}", scen_template, sched_factory())

    print(f"\n{len(scenarios) * len(SCHEDULER_DESIGNS)} experiment(s) passed "
          f"({len(scenarios)} scenario(s) x {len(SCHEDULER_DESIGNS)} scheduler design(s))\n")

    # Two targeted structural checks, on toy_scenario specifically -- its
    # exact arc topology is known ahead of time, so exact outcomes are assertable.

    # Contradictory decision: both 'arc' and a huge 'p' in the same dict --
    # confirm the arc branch wins outright and p is reset to 0, not summed
    # or applied alongside the arc move.
    scenario = _toy()
    sim2 = Simulator(scenario['network'], scenario['ride_demand'],
                      scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    arcs = list(sim2.network.arcs.keys())
    sim2.step({
        'fleet': [{'arc': arcs[0], 'p': 1e9}] + [{'arc': None, 'p': 0.0} for _ in sim2.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim2.buildings.buildings},
    })
    assert sim2.fleet.vehicles[0].p == 0.0, \
        f"expected p reset to 0 when arc decision taken, got {sim2.fleet.vehicles[0].p}"
    print("PASS: contradictory decision (arc + huge p) -- arc wins, p silently ignored, not summed")

    # Arc/current-node adjacency IS validated by Vehicle.step() (fixed in
    # review -- previously it wasn't). A vehicle at the depot handed arc
    # ('A','B') -- which it was never physically on -- must NOT teleport to
    # 'B'; the arc gets clamped to "no decision" (same as any other
    # physically-impossible value) and the vehicle stays exactly where it is.
    scenario = _toy()
    sim3 = Simulator(scenario['network'], scenario['ride_demand'],
                      scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    assert sim3.fleet.vehicles[0].node == scenario['network'].depot
    sim3.step({
        'fleet': [{'arc': ('A', 'B'), 'p': 0.0}] + [{'arc': None, 'p': 0.0} for _ in sim3.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim3.buildings.buildings},
    })
    assert sim3.fleet.vehicles[0].node == scenario['network'].depot and sim3.fleet.vehicles[0].arc is None, \
        "expected an ('A','B') arc from the depot (a node the vehicle was never on) to be rejected, not teleport it"
    print("PASS: arc from a node the vehicle isn't on is rejected, vehicle stays put")

    # Same check, but the vehicle IS mid-transit -- confirm a mismatched arc
    # sent while already traveling doesn't get picked up either (it's ignored
    # entirely while self.arc is not None, this just confirms that stays true).
    # Needs tau >= 3: departure consumes one step (arc_remaining tau -> tau-1),
    # so tau=2 would already arrive on the very next step, leaving no
    # still-mid-transit step to test the mismatched-arc-is-ignored behavior.
    scenario = _toy()
    sim4 = Simulator(scenario['network'], scenario['ride_demand'],
                      scenario['fleet'], scenario['buildings'], dt=scenario['dt'])
    arcs4 = list(sim4.network.arcs.keys())
    valid_arc = next(a for a in arcs4
                      if a[0] == sim4.fleet.vehicles[0].node and sim4.network.get_arc(*a)['tau'] >= 3)
    sim4.step({
        'fleet': [{'arc': valid_arc, 'p': 0.0}] + [{'arc': None, 'p': 0.0} for _ in sim4.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim4.buildings.buildings},
    })
    assert sim4.fleet.vehicles[0].arc == valid_arc, "expected the valid arc to be accepted and still in progress"
    unrelated_arc = next(a for a in arcs4 if a != valid_arc)
    sim4.step({
        'fleet': [{'arc': unrelated_arc, 'p': 0.0}] + [{'arc': None, 'p': 0.0} for _ in sim4.fleet.vehicles[1:]],
        'buildings': {b.b_id: None for b in sim4.buildings.buildings},
    })
    assert sim4.fleet.vehicles[0].arc == valid_arc, \
        "expected an arc sent mid-transit to be ignored -- vehicle should still be on its original arc"
    print("PASS: an arc sent while a vehicle is mid-transit is ignored, original arc continues")

    print("\nAll adversarial checks passed.")
