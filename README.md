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

**Scheduler** — the decision-maker. Pluggable: heuristic, LP, MPC, RL — anything that implements `decide_fleet()` and `decide_buildings()`.
- **Input**: geo info, fleet state, building load, building thermal state, and (for buildings) the realized P_v2b for this timestep
- **Output**: route assignment, power dispatch rate for vehicles, **temperature setpoint** for buildings

Both outputs are decisions a human operator could plausibly make — a dispatcher picks a route and a charge/discharge rate, a building manager picks a target temperature. Neither one is "run the compressor at 15kW" — that's a hardware response, not a decision, and it's handled inside the Simulator (see below).

**Interface**: each timestep is two round-trips between Simulator and Scheduler, not one — because P_v2b depends on the fleet's decision, and buildings need to see P_v2b before deciding a setpoint:

1. `Simulator.get_state() → dict` — snapshot of the world
2. `Scheduler.decide_fleet(state) → list` — route/power decision per vehicle
3. `Simulator.step_fleet(decisions) → p_v2b` — applies fleet movement, computes the realized P_v2b as a byproduct of the fleet's own dispatch (not something the Scheduler sets directly)
4. `Scheduler.decide_buildings(state, p_v2b) → dict` — temperature setpoint per building, now with real P_v2b to react to
5. `Simulator.step_buildings(t_sp_map, p_v2b)` — applies building physics, advances the clock

The direction of information is still one-way, fleet → building. Building's decision in step 4 cannot change what the fleet already did in step 3 — by the time buildings decide, the fleet's move for this timestep is already applied to the world. It's sequential causality within one timestep, not a feedback loop.

**Setpoint → power is fixed physics, not a decision.** `Building.step()` converts a setpoint into actual HVAC power itself, via a bang-bang relay (`if T_in > T_sp: run at hvac_max, else off`) — the same conversion regardless of which scheduler is plugged in, exactly like `Vehicle.step()` clamps any power value to `±p_max` regardless of who requested it. Neither the heuristic nor a future LP/RL scheduler can bypass this relay to set raw kW directly; every scheduler speaks in setpoints, and the Simulator owns the physical response to them.

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
```

## Quick start

```bash
python runner.py
```

Runs a synthetic 3-vehicle, 2-building scenario for 96 timesteps (15-min resolution, 1 day) with a `NullScheduler` — every vehicle stays idle, every building runs no HVAC. This just proves the Simulator/Scheduler loop wires together correctly.

## Plug in your own scheduler

Subclass `BaseScheduler`, implement `decide_fleet()` and `decide_buildings()`. Nothing else in the codebase needs to change.

```python
from scheduler.base import BaseScheduler

class MyScheduler(BaseScheduler):
    def decide_fleet(self, state: dict) -> list:
        return [{'arc': None, 'p': 0.0} for _ in state['fleet']]

    def decide_buildings(self, state: dict, p_v2b: dict) -> dict:
        return {b['b_id']: 24.0 for b in state['buildings']}  # setpoint in °C
```

## Status

Simulator scaffold complete — no heuristic scheduler yet. Next: `HeuristicScheduler` (SoC-floor dispatch rule), then data loaders for Chicago Taxi + BDG2, then evaluation metrics.
