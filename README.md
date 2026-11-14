# v2b-cosim

A co-simulation framework for Vehicle-to-Building (V2B) fleet energy management research.

The framework separates the physical world from the decision-maker. A **Simulator** holds the road network, ride demand, fleet, and buildings, and steps the physics forward one timestep at a time. A **Scheduler** reads the current state and returns decisions — route, power dispatch, HVAC setpoint — without knowing or caring whether it's a heuristic, an LP, or a learned policy. Swap the Scheduler without touching the Simulator.

Each scheduler's math lives next to its implementation: [scheduler/heuristic/README.md](scheduler/heuristic/README.md) (Algorithm 1), [scheduler/milp/README.md](scheduler/milp/README.md) (Model 1).

![Architecture](docs/Architecture.png)

## Architecture

| Class | Holds |
|---|---|
| `NetworkClass` | Nodes, arcs, travel time, energy per arc, distance. Static. |
| `RideDemandClass` | Ride requests: origin, destination, pickup time. |
| `FleetClass` | `Vehicle` objects — SoC, current arc, power rate. |
| `BuildingClass` | `Building` objects — load profile, indoor temperature, charger capacity, RC thermal params. |

**Scheduler** — pluggable decision-maker: anything implementing `decide(state) -> {'fleet': [...], 'buildings': {...}}`. One call in, one call out, per timestep — no round-trip between fleet and building decisions within a step.

**Evaluation** (`evaluation/metrics.py`): peak reduction ΔP (kW), demand fulfillment ρ (%), V2B utilization η_v2b (%), temporal alignment φ_i (correlation), total energy discharged (kWh), SoC conservation error (kWh — net fleet depletion vs. initial charge by end of horizon). `evaluation/plotting.py` renders per-run and multi-scheduler comparison plots.

## Repo layout

```
simulator/           NetworkClass, RideDemandClass, FleetClass, BuildingClass, Simulator
scheduler/
  base/               BaseScheduler contract + NullScheduler
  heuristic/          HeuristicScheduler -- SoC-floor dispatch + bang-bang setpoint
  milp/               MILPScheduler + _model.py (the Pyomo MILP)
runner.py            plug-and-play demo -- pick a scenario, a scheduler (or "all"), optionally plot
tests/                non-interactive correctness checks (asserts, no test framework)
data/loaders/
  doe_chicago.py      real DOE/EnergyPlus Chicago-O'Hare building load
evaluation/           metrics.py, plotting.py
scenarios/
  small_scenario.py    3 nodes, 13 vehicles -- MILP lands at a small (~2%) optimality
                        gap in a practical time budget, not proven-optimal; this paper
                        makes no claim about MILP solve time or scalability
  chicago_scenario.py  full city scale, 77 nodes, 250 vehicles -- Heuristic/Null only
  scaled_scenario.py   you choose the node count N: buildings = min(ceil(2N/3), 16, N-1),
                        DOE types assigned by descending annual peak, vehicles ~3.25 per
                        node (override with n_vehicles) -- Heuristic/Null at larger N
docs/Architecture.png  system diagram
```

## Quick start

```bash
pip install -r requirements.txt
```

`MILPScheduler` needs a working [Gurobi](https://www.gurobi.com/) install (free academic licenses available). `NullScheduler` and `HeuristicScheduler` don't need a solver.

Download the two real datasets (see [data/README.md](data/README.md) for links/paths), then:

```bash
python runner.py
```

Pick a scenario (`small`, `chicago`, or `scaled` -- which then asks for the node count N and prints the resulting building and vehicle counts), a scheduler (`null`, `heuristic`, `milp`, or `all`), and whether to save a plot. Prints ΔP, η_v2b, φ_i, ρ, and total energy discharged.

For a fast, dependency-free correctness check instead:

```bash
python -m tests.test_heuristic
python -m tests.test_adversarial
python -m tests.test_scaled_scenario
```

## Plug in your own scheduler

Subclass `BaseScheduler`, implement `decide()`. Nothing else needs to change.

```python
from scheduler.base import BaseScheduler

class MyScheduler(BaseScheduler):
    def decide(self, state: dict) -> dict:
        return {
            'fleet':     [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: 24.0 for b in state['buildings']},  # setpoint in °C
        }
```

## Status

`NullScheduler`, `HeuristicScheduler`, `MILPScheduler` all run against `small`. `chicago` runs `Null`/`HeuristicScheduler` only — MILP doesn't scale there. `scaled` (any N, buildings = ⌈2N/3⌉ capped at the 16 DOE types) was tested with `Null`/`HeuristicScheduler` at N=3 and N=11; `MILPScheduler` has not been tried on it. All three scenarios use λ=1.0 (100% demand-service floor) and a summer date (2019-07-10) — Mode B's bang-bang HVAC relay is cooling-only, so a winter date leaves it permanently off (see `data/README.md`). `HeuristicScheduler` and `MILPScheduler` currently each return a fixed comfort setpoint (`T_SP_FIXED = 23.0`) instead of a real per-timestep thermal decision -- a placeholder pending an actual rule, not a design choice (see the `TODO` in each scheduler). `NullScheduler` still returns `None`.

| Scenario | Scheduler | ρ | ΔP (kW) | Energy discharged | SoC conservation error |
|---|---|---|---|---|---|
| small | MILP | 100% | 38.90 / 2.54 | 558.5 kWh | −0.0 kWh |
| small | Heuristic | 97.55% | 0.00 / 0.85 | 1,072.5 kWh | −336.4 kWh |
| chicago | Heuristic | 35.90% | 0.00 / 0.00 | 26,115.0 kWh | −5,893.5 kWh |

SoC conservation error: negative = fleet ends the day below its initial charge, positive = ends above. MILP's is ~0 by construction (a soft term pulls the fleet back to at least its initial charge); Heuristic has no such guarantee, and depletes meaningfully more on both scenarios. ρ is distance-weighted (see `evaluation/metrics.py`), not a raw count of demands served.
