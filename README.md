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
- **Input**: whatever `Simulator.get_state()` exposes — geo info, fleet state, building load, building thermal state, and the V2B power realized at each building as of the previous timestep
- **Output**: route assignment, power dispatch rate for vehicles, **temperature setpoint** for buildings

Both outputs are decisions a human operator could plausibly make — a dispatcher picks a route and a charge/discharge rate, a building manager picks a target temperature. Neither one is "run the compressor at 15kW" — that's a hardware response, not a decision, and it's handled inside the Simulator (see below).

**Interface**: one call in, one call out, per timestep:

1. `Simulator.get_state() → dict` — snapshot of the world, including `p_v2b`: the V2B power realized at each building at the end of the *previous* timestep
2. `Scheduler.decide(state) → dict` — route/power per vehicle, temperature setpoint per building
3. `Simulator.step(decisions)` — applies both, advances the clock

Fleet and building decisions are made simultaneously off the same snapshot — neither one waits on the other within a timestep. Building's setpoint decision, if it uses `p_v2b` at all, is reacting to what the fleet did *last* timestep, not this one; the fleet's decision this timestep has no way to reach the building until the next `get_state()` call. This is a standard co-simulation pattern (Jacobi-type coupling) for avoiding an internal round-trip between two decision layers that can't be solved simultaneously.

**`p_v2b` is exposed as a plain ingredient in the state, not a prescribed coupling mechanism.** The Simulator's job is to make available information visible — what a scheduler does with it (react to it, shift a threshold with it, ignore it entirely) is a decision made by whoever writes that scheduler, not something the framework dictates.

**Setpoint → power is fixed physics, not a decision.** `Building.step()` converts a setpoint into actual HVAC power itself, via a bang-bang relay (`if T_in > T_sp: run at hvac_max, else off`) — the same conversion regardless of which scheduler is plugged in, exactly like `Vehicle.step()` clamps any power value to `±p_max` regardless of who requested it. No scheduler can bypass this relay to set raw kW directly; every scheduler speaks in setpoints, and the Simulator owns the physical response to them.

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

Subclass `BaseScheduler`, implement `decide()`. Nothing else in the codebase needs to change.

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

Simulator scaffold complete — no heuristic scheduler yet. Next: `HeuristicScheduler` (SoC-floor dispatch rule), then data loaders for Chicago Taxi + BDG2, then evaluation metrics.
