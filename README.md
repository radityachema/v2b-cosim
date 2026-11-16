# v2b-cosim

A co-simulation framework for Vehicle-to-Building (V2B) fleet energy management research. It accompanies the ASim 2026 paper *Co-Simulation of Vehicle-to-Building (V2B) and Thermal Loads: A Scalable Testbed for Integrated Demand Response in Commercial Facilities*. The tag [`asim-2026`](https://github.com/radityachema/v2b-cosim/tree/asim-2026) is the exact code behind the paper's results.

The framework separates the physical world from the decision-maker. A **Simulator** holds the road network, ride demand, fleet, and buildings, and steps the physics forward one timestep at a time. A **Scheduler** reads the current state and returns decisions (route, power dispatch, HVAC setpoint). The Simulator does not know or care whether the Scheduler is a heuristic, an optimisation model, or a learned policy, so you can swap the Scheduler without touching the Simulator.

![Architecture](docs/Architecture.png)

## Quick start

```bash
pip install -r requirements.txt
```

Download the two real datasets (Chicago taxi trips and DOE/EnergyPlus building loads; see [data/README.md](data/README.md) for links and paths), then start the menu:

```bash
python menu.py
```

It is a small terminal menu (New run / Settings / Past runs / Quit). In Settings you pick:

- the scenario (`toy`, `small`, `chicago`, `scaled`). For `scaled` you also pick the number of nodes, buildings (1 to N-1) and vehicles.
- the scheduler (`null`, `heuristic`, `milp`). `milp` is only offered for `small` and small `scaled` cases.

Each run gets its own folder, `outputs/<date>_<time>_<scheduler>_<scenario>/`, holding `settings.yaml`, `summary.txt` and the plot.

`MILPScheduler` needs a working [Gurobi](https://www.gurobi.com/) install (free academic licences are available). `NullScheduler` and `HeuristicScheduler` don't need a solver.

`python runner.py` is the original non-menu entry point. It asks for the scenario, the scheduler (or `all`) and whether to plot.

You can also run the correctness checks, which need no data download or solver:

```bash
python -m tests.test_heuristic
python -m tests.test_adversarial
python -m tests.test_scaled_scenario
```

## Architecture

**Simulator** (`simulator/`): four classes, stepped together.

| Class | Holds |
|---|---|
| `NetworkClass` | Nodes, arcs, travel time, energy per arc, distance. Static. |
| `RideDemandClass` | Ride requests: origin, destination, pickup time. |
| `FleetClass` | `Vehicle` objects: SoC, current arc, power rate. |
| `BuildingClass` | `Building` objects: load profile, indoor temperature, charger capacity, RC thermal parameters. |

`Vehicle.step()` and `Building.step()` only apply physics. They clamp each decision to the hardware limits (power, SoC, setpoint range) and never decide anything themselves.

**Scheduler** (`scheduler/`): anything that implements `decide(state) -> {'fleet': [...], 'buildings': {...}}`. The Simulator makes one call per timestep, with no round trip between fleet and building decisions within a step.

**Interface contract** (what `state` contains):

- **Only the present.** The state holds the current timestep: SoC, positions, indoor temperatures, and the ride requests due now. There is no future load or demand in it. A day-ahead scheduler that needs the whole horizon receives it through its own constructor. That keeps the difference between online (reactive) and offline (day-ahead) schedulers explicit.
- **One piece of history: `p_v2b`, lagged one timestep.** The building's decision sees last step's V2B power, not this step's. The coupling is one-way (fleet → building). A scheduler that needs more memory keeps its own.

**Evaluation** (`evaluation/metrics.py`):

- peak reduction ΔP (kW)
- demand fulfilment ρ (%)
- V2B utilisation η_v2b (%)
- temporal alignment φ_i (correlation)
- total energy discharged (kWh)
- SoC conservation error (kWh)

`evaluation/plotting.py` renders per-run and multi-scheduler comparison plots.

Each scheduler's math is documented next to its code: [scheduler/heuristic/README.md](scheduler/heuristic/README.md) (Algorithm 1) and [scheduler/milp/README.md](scheduler/milp/README.md) (Model 1).

## Repo layout

```
simulator/            NetworkClass, RideDemandClass, FleetClass, BuildingClass, Simulator
scheduler/
  base/               BaseScheduler contract + NullScheduler
  heuristic/          HeuristicScheduler: SoC-floor dispatch + bang-bang setpoint
  milp/               MILPScheduler + _model.py (the Pyomo MILP)
scenarios/
  toy_scenario.py     hand-typed sanity check of the plumbing
  small_scenario.py   3 nodes, 13 vehicles; the MILP solves to a ~2% gap
  chicago_scenario.py 77 nodes, 250 vehicles; Heuristic/Null only
  scaled_scenario.py  choose N nodes; buildings min(ceil(2N/3), 16, N-1) by default
                      or any 1..N-1; ~3.25 vehicles per node by default
evaluation/           metrics.py, plotting.py
data/loaders/         DOE/EnergyPlus Chicago-O'Hare building load, taxi trips, weather
menu.py               terminal menu (start here)
runner.py             original non-menu entry point
tests/                correctness checks (plain asserts, no test framework)
docs/Architecture.png system diagram
```

## Plug in your own scheduler

Subclass `BaseScheduler` and implement `decide()`. Nothing else needs to change.

```python
from scheduler.base import BaseScheduler

class MyScheduler(BaseScheduler):
    def decide(self, state: dict) -> dict:
        return {
            'fleet':     [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: 24.0 for b in state['buildings']},  # setpoint in °C
        }
```

## Results (ASim 2026)

All runs use a summer day (2019-07-10) and a 100% demand-service floor (λ = 1.0). The building HVAC relay is cooling-only, so a winter date would leave it off (see `data/README.md`).

| Scenario | Scheduler | ρ | ΔP (kW) | Energy discharged | SoC conservation error |
|---|---|---|---|---|---|
| small | MILP | 100% | 38.90 / 2.54 | 558.5 kWh | −0.0 kWh |
| small | Heuristic | 97.55% | 0.00 / 0.85 | 1,072.5 kWh | −336.4 kWh |
| chicago | Heuristic | 35.90% | 0.00 / 0.00 | 26,115.0 kWh | −5,893.5 kWh |

- **ΔP:** one value per building.
- **ρ:** distance-weighted (see `evaluation/metrics.py`), not a raw count of requests served.
- **SoC conservation error:** negative means the fleet ends the day below its initial charge. The MILP's is about 0 by construction, because a soft term pulls the fleet back to at least its initial charge. The heuristic has no such term.

## Status and limitations

- **MILP scale.** The MILP runs on `small` and on small `scaled` cases. It does not scale to `chicago`, which runs with `null`/`heuristic`. `scaled` has been tested with `null`/`heuristic` at N = 3 and N = 11.
- **Fixed setpoint.** `HeuristicScheduler` and `MILPScheduler` currently return a fixed comfort setpoint (23 °C) rather than a per-timestep thermal decision. This is a placeholder (see the `TODO` in each scheduler).
- **Null scheduler.** `NullScheduler` sends no decisions. It is the no-V2B baseline.
