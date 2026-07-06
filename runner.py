"""
Plug-and-play demo: one Simulator, built from real Chicago Taxi + BDG2
data. Pick a Scheduler to run it with -- that's the whole demo. Add your
own BaseScheduler subclass to SCHEDULERS below; nothing else here needs
to change.

Pick "all" to run every scheduler against the identical scenario and get
one comparison plot -- same building load, one grid-draw line per
scheduler, on the same axes.

For a fast, dependency-free correctness check instead of exploration,
see tests/test_heuristic.py.
"""
from simulator import Simulator
from scheduler.base import NullScheduler
from scheduler.heuristic import HeuristicScheduler
from scheduler.milp import MILPScheduler
from scenarios.real_scenario import build_scenario
from evaluation import metrics
from evaluation.plotting import plot_run, plot_comparison

SCHEDULERS = {
    'null': lambda scenario: NullScheduler(),
    'heuristic': lambda scenario: HeuristicScheduler(),
    'milp': lambda scenario: MILPScheduler(scenario),
}


def run(scenario, scheduler, label):
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

    return p_load_hist, p_grid_hist, soc_hist


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

    results = {}
    load_for_plot = None
    dt = None
    for n in names:
        scenario = build_scenario()  # fresh objects per run -- Simulator mutates fleet/buildings
        if n == 'milp':
            print("Solving MILP (usually a few seconds against this scenario)...")
        scheduler = SCHEDULERS[n](scenario)
        p_load_hist, p_grid_hist, soc_hist = run(scenario, scheduler, n)
        results[n] = (p_load_hist, p_grid_hist, soc_hist)
        load_for_plot = p_load_hist
        dt = scenario['dt']

    if visualize:
        if len(names) > 1:
            grid_hists = {n: results[n][1] for n in names}
            path = "run_comparison"
            plot_comparison(load_for_plot, grid_hists, "Scheduler comparison", path, dt=dt)
            print(f"\nSaved comparison plot to {path}.pdf / {path}.png")
        else:
            n = names[0]
            p_load_hist, p_grid_hist, soc_hist = results[n]
            path = f"run_{n}"
            plot_run(p_load_hist, p_grid_hist, soc_hist, n, path, dt=dt)
            print(f"  Saved plot to {path}.pdf / {path}.png")
