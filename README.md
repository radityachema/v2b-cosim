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

**What's in `state`, exactly:**
- `t`, `demands` (only pickups due this exact timestep — no future visibility)
- `fleet`: per vehicle — `v_id, soc, node, arc, p` plus static hardware bounds `p_max, s_min, s_max, e_cap`
- `buildings`: per building — `b_id, t_in, n_chargers, p_grid, p_cons` plus static thermal/hardware config `rc` (`a, b, hvac_max, t_init, t_sp_min, t_sp_max`, or `None` for Mode A)
- `p_v2b`: the one piece of real history — lagged one timestep, as above
- `network`: static

Deliberately *not* included: any deeper history, or any future beyond the current timestep. A scheduler that wants more memory keeps it itself (a list it appends to every `decide()` call) — the Simulator doesn't guess how much history any given scheduler wants. And future building load / ride demand are withheld from the per-step interface on purpose: exposing them would erase the distinction between an online scheduler (reacts to what's already happened) and a day-ahead scheduler (sees the whole known horizon up front) — a distinction that matters for comparing methods under uncertainty. A scheduler that legitimately needs full-horizon foresight gets it via its own constructor, not through `get_state()`.

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
  heuristic.py     HeuristicScheduler — SoC-floor dispatch + bang-bang setpoint
  milp.py          MILPScheduler — pre-solved day-ahead comparison
  _milp_model.py   Pyomo MILP model (routing + V2B + thermal)
runner.py           minimal end-to-end loop (synthetic data)
examples/
  run_heuristic.py       HeuristicScheduler verification run (synthetic data)
  run_real_data.py       HeuristicScheduler on real Chicago Taxi + BDG2 data
  run_milp_comparison.py Heuristic vs MILP on identical scenario data (Task 3)
data/loaders/
  fleet.py         load_chicago_taxi_demands() -- real ride demands for RideDemandClass
  building.py      load_bdg2_load(), load_bdg2_weather() -- real building load + outdoor temp
evaluation/metrics.py  ΔP, η_v2b, φ_i, ρ -- plain Python, no pandas dependency
scenarios/chicago_scenario.py  one-off N=6/V=30/D=317 scenario replica for the MILP comparison
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

`HeuristicScheduler` complete and verified (`examples/run_heuristic.py`) — SoC-floor fleet dispatch, bang-bang building setpoint with a P_v2b-aware shift. Data loaders (`data/loaders/`) and evaluation metrics (`evaluation/metrics.py`) are complete and verified end-to-end against real Chicago Taxi + BDG2 data (`examples/run_real_data.py`).

`MILPScheduler` complete and compared against `HeuristicScheduler` on identical scenario data (`examples/run_milp_comparison.py`) — the extended Pyomo model (`scheduler/_milp_model.py`) solves against a real 6-zone/30-vehicle/317-demand Chicago scenario (`scenarios/chicago_scenario.py`). Not the paper's main method — a baseline comparison. Two structural asymmetries are worth remembering when reading results: the MILP has full-day foresight and a hard 100%-demand-service constraint the heuristic doesn't have, so report peak reduction *and* demand fulfillment together, never peak reduction alone.
