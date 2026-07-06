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

**Evaluation** (`evaluation/metrics.py`): peak reduction ΔP (kW), demand fulfillment ρ (%), V2B utilization η_v2b (%), temporal alignment φ_i (correlation between fleet availability and building load). `evaluation/plotting.py` renders load-vs-grid-draw (single run, or all schedulers overlaid on one axis for direct comparison) and vehicle SoC over time, saved as PDF + PNG.

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
runner.py           plug-and-play demo -- one real-data scenario, pick a scheduler (or "all"), optionally plot
experiments/milp_comparison.py  Heuristic vs MILP at a much larger, real Chicago-taxi-scale (30 vehicles, 317 demands)
tests/test_heuristic.py  non-interactive correctness check (asserts, no test framework)
data/loaders/
  fleet.py         load_chicago_taxi_demands() -- real ride demands for RideDemandClass
  building.py      load_bdg2_load(), load_bdg2_weather() -- real building load + outdoor temp
evaluation/
  metrics.py       ΔP, η_v2b, φ_i, ρ -- plain Python, no pandas dependency
  plotting.py      single-run and multi-scheduler-overlay plots, matplotlib, always saves PDF+PNG
scenarios/
  toy_scenario.py      3 vehicles, 2 buildings, no external files -- used by tests/ only
  real_scenario.py     Chicago Taxi + BDG2, real data -- the ONE canonical scenario, used by runner.py.
                       Carries every field any scheduler needs (Null, Heuristic, or MILP), so all three
                       run against genuinely identical data -- no separate scenario per scheduler.
  chicago_scenario.py  N=6/V=30/D=317 Chicago-scale replica -- used by experiments/milp_comparison.py only,
                       for the much bigger comparison, not the main demo
docs/Architecture.png  system diagram
```

## Quick start

```bash
python runner.py
```

Prompts for a scheduler (`NullScheduler`, `HeuristicScheduler`, `MILPScheduler`, or `all`), then whether to save a plot, then runs it against one fixed real-data scenario (Chicago Taxi + BDG2). Prints ΔP, η_v2b, φ_i, ρ for each. Pick `all` to run every scheduler against the identical scenario and get one comparison plot — the same building load curve with each scheduler's grid draw overlaid on it, so it's a genuine apples-to-apples comparison, not three separate experiments.

`MILPScheduler` solves in seconds against this scenario's small scale (5 vehicles, 3 nodes) — it's a real, satisfied instance of the `BaseScheduler` contract here, not a special case requiring different data. `experiments/milp_comparison.py` exists separately only because it runs the comparison at a much larger, more demanding scale (30 vehicles, 317 real demands) that takes minutes to solve — that's a scale choice, not an architectural one.

For a fast, dependency-free correctness check instead of exploration, run `tests/test_heuristic.py`.

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

`runner.py` is the plug-and-play demo: `NullScheduler`, `HeuristicScheduler`, and `MILPScheduler` all run against the same real-data scenario (`scenarios/real_scenario.py`), verified end-to-end, including a real solved MILP result (peak reduction, V2B utilization, temporal alignment all computed identically for all three). `experiments/milp_comparison.py` runs the same comparison at a much larger scale (30 vehicles, 317 real demands) — same idea, bigger and slower to solve.

Two structural asymmetries are worth remembering when reading either comparison: the MILP has full-day foresight and a demand-service floor the heuristic doesn't have (checked directly: `λ=1.0`, i.e. serve every demand, is infeasible for the 5-vehicle real scenario — `λ=0.3` is the largest value that solves), so report peak reduction *and* demand fulfillment together, never peak reduction alone.

`MILPScheduler` isn't the paper's main method — a comparison baseline.
