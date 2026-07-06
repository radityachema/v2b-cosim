"""
Plug-and-play demo: one Simulator, built from real Chicago Taxi + BDG2
data. Pick a Scheduler to run it with -- that's the whole demo. Add your
own BaseScheduler subclass to SCHEDULERS below; nothing else here needs
to change.

For the MILP-vs-heuristic comparison at a larger, MILP-specific scale,
see experiments/milp_comparison.py -- a separate, self-contained script.
MILPScheduler needs differently-shaped scenario data (demand distances,
service-level target, etc.) than the one scenario this demo uses, so it
isn't offered here; forcing it into this menu is what caused the
scenario/compatibility-matrix mess this file used to have.

For a fast, dependency-free correctness check instead of exploration,
see tests/test_heuristic.py.
"""
from simulator import Simulator
from scheduler.base import NullScheduler
from scheduler.heuristic import HeuristicScheduler
from scenarios.real_scenario import build_scenario
from evaluation import metrics
from evaluation.plotting import plot_run

SCHEDULERS = {
    'null': NullScheduler,
    'heuristic': HeuristicScheduler,
}


def run(scenario, scheduler, label, visualize):
    sim = Simulator(scenario['network'], scenario['ride_demand'],
                     scenario['fleet'], scenario['buildings'], dt=scenario['dt'])

    building_ids = [b.b_id for b in sim.buildings.buildings]
    p_load_hist = {b: [] for b in building_ids}
    p_grid_hist = {b: [] for b in building_ids}
    p_v2b_hist = {b: [] for b in building_ids}
    p_cons_hist = {b: [] for b in building_ids}
    soc_hist = {v.v_id: [] for v in sim.fleet.vehicles}
    served_ids = set()

    for _ in range(scenario['T']):
        state = sim.get_state()
        decisions = scheduler.decide(state)

        due_arcs = {(d['i_d'], d['j_d']): d['id'] for d in state['demands']}
        for dec in decisions['fleet']:
            if dec['arc'] in due_arcs:
                served_ids.add(due_arcs[dec['arc']])

        sim.step(decisions)

        t = state['t']
        for b in sim.buildings.buildings:
            p_load_hist[b.b_id].append(b.load_profile.get(t, 0.0))
            p_grid_hist[b.b_id].append(b.p_grid)
            p_cons_hist[b.b_id].append(b.p_cons)
        for b_id, v in sim.p_v2b.items():
            p_v2b_hist[b_id].append(v)
        for v in sim.fleet.vehicles:
            soc_hist[v.v_id].append(v.soc)

    all_demands = list(scenario['ride_demand'].demands)
    served = [d for d in all_demands if d['id'] in served_ids]
    rho = metrics.demand_fulfillment(served, all_demands, scenario['network']) if all_demands else 1.0

    print(f"\n--- {label} ---")
    for b_id in building_ids:
        dp = metrics.peak_reduction(p_load_hist[b_id], p_grid_hist[b_id])
        eta = metrics.v2b_utilization(p_v2b_hist[b_id], p_cons_hist[b_id])
        phi = metrics.temporal_alignment(p_v2b_hist[b_id], p_load_hist[b_id])
        print(f"  Building {b_id}: peak_reduction={dp:.2f} kW, "
              f"v2b_utilization={eta:.2%}, temporal_alignment={phi:.3f}")
    print(f"  Fleet: demand_fulfillment (rho) = {rho:.2%} ({len(served)}/{len(all_demands)})")

    if visualize:
        path = f"run_{label}"
        plot_run(p_load_hist, p_grid_hist, soc_hist, label, path, dt=scenario['dt'])
        print(f"  Saved plot to {path}.pdf / {path}.png")


def _prompt(options, question):
    print(question)
    for key in options:
        print(f"  {key}")
    while True:
        choice = input("> ").strip().lower()
        if choice in options:
            return choice
        print(f"'{choice}' isn't one of {list(options)}, try again.")


if __name__ == '__main__':
    options = list(SCHEDULERS) + ['all']
    name = _prompt(options, "Which scheduler?")
    visualize = input("Save a plot? (y/n) > ").strip().lower().startswith('y')

    names = list(SCHEDULERS) if name == 'all' else [name]
    for n in names:
        scenario = build_scenario()  # fresh objects per run -- Simulator mutates fleet/buildings
        scheduler = SCHEDULERS[n]()
        run(scenario, scheduler, n, visualize)
