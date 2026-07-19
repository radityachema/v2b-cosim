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
  small_scenario.py    4 nodes, 13 vehicles -- solves the MILP to proven optimality
  chicago_scenario.py  full city scale, 77 nodes, 250 vehicles -- Heuristic/Null only
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

Pick a scenario (`small` or `chicago`), a scheduler (`null`, `heuristic`, `milp`, or `all`), and whether to save a plot. Prints ΔP, η_v2b, φ_i, ρ, and total energy discharged.

For a fast, dependency-free correctness check instead:

```bash
python -m tests.test_heuristic
python -m tests.test_adversarial
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

`NullScheduler`, `HeuristicScheduler`, `MILPScheduler` all run against `small`. `chicago` runs `Null`/`HeuristicScheduler` only — MILP doesn't scale there. Both use λ=1.0 (100% demand-service floor).

| Scenario | Scheduler | ρ | ΔP (kW) | Energy discharged | SoC conservation error |
|---|---|---|---|---|---|
| small | MILP | 100% | 25.43 / 2.26 | 193.2 kWh | +14.3 kWh |
| small | Heuristic | 74.94% | 0.00 / 0.00 | 1,127.5 kWh | −317.0 kWh |
| chicago | Heuristic | 38.50% | 10.00 / 0.00 | 29,987.5 kWh | −5,761.6 kWh |

SoC conservation error: negative = fleet ends the day below its initial charge, positive = ends above. MILP's is ~0 by construction (a hard constraint enforces ending at or above the initial charge); Heuristic has no such guarantee. ~28% of Heuristic's headline energy-discharged figure on `small` is unrecovered net depletion, not sustainable day-over-day cycling — same story proportionally at city scale.
