# v2b-cosim

A co-simulation framework for Vehicle-to-Building (V2B) fleet energy management research.

The framework separates the physical world from the decision-maker. A **Simulator** holds the road network, ride demand, fleet, and buildings, and steps the physics forward one timestep at a time. A **Scheduler** reads the current state and returns decisions — route, power dispatch, HVAC — without knowing or caring whether it's a heuristic, an LP, or a learned policy. Swap the Scheduler without touching the Simulator.

![Architecture](docs/Architecture.png)

## Architecture

**Simulator** — the physics engine. Holds world state, steps +1 each timestep.

| Class | Holds |
|---|---|
| `NetworkClass` | Nodes 𝒩, arcs (i,j), travel time τ_ij, energy per arc e_ij, distance d_ij. Static — loaded once. |
| `RideDemandClass` | All ride requests: origin, destination, pickup time. Provides 𝒟_t each timestep. |
| `FleetClass` | Collection of `Vehicle` objects (×\|𝒱\|). Each holds SoC, current arc, power rate. |
| `BuildingClass` | Collection of `Building` objects (×\|ℬ\|). Each holds load profile, indoor temperature, charger capacity, RC thermal parameters. |

**Scheduler** — the decision-maker. Pluggable: heuristic, LP, MPC, RL — anything that implements `decide()`.
- **Input** (from `Simulator.get_state()`): geo info, fleet state, building load, building thermal state
- **Output**: route assignment, power dispatch rate, HVAC power

**Interface**: `Simulator.get_state() → dict`, `Scheduler.decide(state) → dict`. The Simulator pulls decisions from the Scheduler every step; it never pushes anything to the Scheduler on its own. `P_v2b` — the power the fleet makes available to buildings — is computed *inside* the Simulator each step, as a byproduct of the fleet's own dispatch decisions, not something the Scheduler sets directly.

**Evaluation**: peak reduction (kW), demand fulfillment (%), V2B utilization (%), temporal alignment φ_i (correlation between fleet availability and building load).

## Repo layout

```
simulator/
  network.py       NetworkClass — static road graph
  ride_demand.py   RideDemandClass — ride requests
  fleet.py         Vehicle + FleetClass
  building.py      Building + BuildingClass
  simulator.py     Simulator — steps all classes, computes P_v2b
scheduler/
  base.py          BaseScheduler (abstract contract) + NullScheduler
runner.py           minimal end-to-end loop (synthetic data)
data/loaders/        Chicago taxi + BDG2 loaders (WIP)
evaluation/          metrics: ΔP, η_v2b, φ_i, ρ (WIP)
docs/Architecture.png  system diagram
_staging/            earlier ICE-framed prototype, kept for reference only
```

## Quick start

```bash
python runner.py
```

Runs a synthetic 3-vehicle, 2-building scenario for 96 timesteps (15-min resolution, 1 day) with a `NullScheduler` — every vehicle stays idle, every building runs no HVAC. This just proves the Simulator/Scheduler loop wires together correctly.

## Plug in your own scheduler

Subclass `BaseScheduler`, implement `decide()`. Nothing else in the codebase needs to change.

```python
from scheduler.base import BaseScheduler

class MyScheduler(BaseScheduler):
    def decide(self, state: dict) -> dict:
        return {
            'fleet':     [{'arc': None, 'p': 0.0} for _ in state['fleet']],
            'buildings': {b['b_id']: {'p_hvac': 0.0} for b in state['buildings']},
        }
```

## Status

Simulator scaffold complete — no heuristic scheduler yet. Next: `HeuristicScheduler` (SoC-floor dispatch rule), then data loaders for Chicago Taxi + BDG2, then evaluation metrics.
