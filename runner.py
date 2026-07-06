"""
Interactive entry point: pick a scenario, pick a scheduler (or run every
scheduler compatible with that scenario), optionally save a plot.

For a non-interactive correctness check instead of exploration, see
tests/test_heuristic.py.
"""
from simulator import Simulator
from scheduler.base import NullScheduler
from scheduler.heuristic import HeuristicScheduler
from scheduler.milp import MILPScheduler
from evaluation import metrics
from evaluation.plotting import plot_run

SCENARIOS = {
    '1': ('toy', 'Toy synthetic (3 vehicles, 2 buildings, no external files)'),
    '2': ('real', 'Real data (Chicago Taxi + BDG2)'),
    '3': ('chicago', 'Chicago MILP scenario (6 zones, 30 vehicles, 317 real demands)'),
}

SCHEDULERS = {
    'null':      'NullScheduler (do-nothing baseline)',
    'heuristic': 'HeuristicScheduler',
    'milp':      'MILPScheduler (pre-solved MILP, Chicago scenario only)',
}

COMPATIBLE = {
    'toy': ['null', 'heuristic'],
    'real': ['null', 'heuristic'],
    'chicago': ['null', 'heuristic', 'milp'],
}


def build_scenario(name):
    if name == 'toy':
        from scenarios.toy_scenario import build_scenario as build
    elif name == 'real':
        from scenarios.real_scenario import build_scenario as build
    elif name == 'chicago':
        from scenarios.chicago_scenario import build_scenario as build
    else:
        raise ValueError(name)
    return build()


def build_scheduler(name, scenario):
    if name == 'null':
        return NullScheduler()
    if name == 'heuristic':
        return HeuristicScheduler()
    if name == 'milp':
        print("Solving MILP (this can take a few minutes)...")
        return MILPScheduler(scenario)
    raise ValueError(name)


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
        safe_label = label.replace('/', '_').replace(' ', '_')
        path = f"run_{safe_label}.png"
        plot_run(p_load_hist, p_grid_hist, soc_hist, label, path)
        print(f"  Saved plot to {path}")


def _prompt(options, question):
    print(question)
    for key, desc in options.items():
        print(f"  {key}) {desc}")
    while True:
        choice = input("> ").strip().lower()
        if choice in options:
            return choice
        print(f"'{choice}' isn't one of {list(options.keys())}, try again.")


def main():
    scenario_options = {k: v[1] for k, v in SCENARIOS.items()}
    scenario_key = _prompt(scenario_options, "Which scenario?")
    scenario_name = SCENARIOS[scenario_key][0]

    compatible = COMPATIBLE[scenario_name]
    scheduler_options = {k: v for k, v in SCHEDULERS.items() if k in compatible}
    scheduler_options['all'] = f"Run all compatible schedulers ({', '.join(compatible)})"
    scheduler_choice = _prompt(scheduler_options, f"Which scheduler? (compatible with '{scenario_name}')")

    visualize = input("Save a plot of the results? (y/n) > ").strip().lower().startswith('y')

    names = compatible if scheduler_choice == 'all' else [scheduler_choice]

    for name in names:
        scenario = build_scenario(scenario_name)  # fresh objects per run -- Simulator mutates fleet/buildings
        scheduler = build_scheduler(name, scenario)
        run(scenario, scheduler, f"{scenario_name}-{name}", visualize)


if __name__ == '__main__':
    main()
