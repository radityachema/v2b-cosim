# v2b-cosim

A co-simulation framework for Vehicle-to-Building (V2B) fleet energy management research.

The framework separates the physical world from the decision-maker. A **Simulator** holds the road network, ride demand, fleet, and buildings, and steps the physics forward one timestep at a time. A **Scheduler** reads the current state and returns decisions — route, power dispatch, HVAC — without knowing or caring whether it's a heuristic, an LP, or a learned policy. Swap the Scheduler without touching the Simulator.

Each scheduler's full mathematical formulation lives next to its implementation: [scheduler/heuristic/README.md](scheduler/heuristic/README.md) (Algorithm 1), [scheduler/milp/README.md](scheduler/milp/README.md) (Model 1, mapped constraint-by-constraint against the original notation).

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
- `buildings`: per building — `b_id, t_in, n_chargers, p_grid, p_cons` plus static thermal/hardware config `rc` (`a, b, hvac_max, t_init, t_sp_min, t_sp_max`, or `None` for Mode A). Mode A = thermal-agnostic (full measured load, no `T_in` state); Mode B = thermal-aware (HVAC portion of load stripped out, reintroduced by the Scheduler's setpoint).
- `p_v2b`: the one piece of real history — lagged one timestep, as above
- `network`: static

Deliberately *not* included: any deeper history, or any future beyond the current timestep. A scheduler that wants more memory keeps it itself (a list it appends to every `decide()` call) — the Simulator doesn't guess how much history any given scheduler wants. And future building load / ride demand are withheld from the per-step interface on purpose: exposing them would erase the distinction between an online scheduler (reacts to what's already happened) and a day-ahead scheduler (sees the whole known horizon up front) — a distinction that matters for comparing methods under uncertainty. A scheduler that legitimately needs full-horizon foresight gets it via its own constructor, not through `get_state()`.

**Setpoint → power is fixed physics, not a decision.** `Building.step()` converts a setpoint into actual HVAC power itself, via a bang-bang relay (`if T_in > T_sp: run at hvac_max, else off`) — the same conversion regardless of which scheduler is plugged in, exactly like `Vehicle.step()` clamps any power value to `±p_max` regardless of who requested it. No scheduler can bypass this relay to set raw kW directly; every scheduler speaks in setpoints, and the Simulator owns the physical response to them.

**None of the three schedulers this repo publishes (`NullScheduler`, `HeuristicScheduler`, `MILPScheduler`) actually make a thermal decision.** Every building setpoint they return is `None`, not a float -- `Building.step()` treats `t_sp=None` as "no decision," skipping the relay entirely (`p_hvac` stays 0; `T_in` still evolves passively toward outdoor temperature, since that's physics, not a decision). This paper's published checkpoint is V2B-only: AC setpoint is a constant, not a decision variable, for every scheduler and every scenario. The capability itself is still real -- `Building.step()`'s Mode B relay is unchanged, and a future scheduler can return an actual float to exercise it -- but reintroducing it is out of scope for what's published here.

**Evaluation** (`evaluation/metrics.py`): peak reduction ΔP (kW), demand fulfillment ρ (%), V2B utilization η_v2b (%), temporal alignment φ_i (correlation between fleet availability and building load). `evaluation/plotting.py` renders either a single-run triple panel (building load vs. grid draw, a per-vehicle Gantt schedule, and SoC over time -- the Gantt/SoC panels draw only the top-5 most V2B-active vehicles so the figure stays readable at any fleet size; `summarize_fleet()` prints a one-line-per-vehicle text summary covering everyone else) or, for `all`-scheduler runs, one comparison plot with every scheduler's grid draw overlaid on the same building load curve. Always saved as PDF + PNG.

## Repo layout

```
simulator/
  network.py       NetworkClass — static road graph
  ride_demand.py   RideDemandClass — ride requests
  fleet.py         Vehicle + FleetClass
  building.py      Building + BuildingClass
  simulator.py     Simulator — steps all classes, computes P_v2b
scheduler/
  base/            BaseScheduler (abstract contract) + NullScheduler
  heuristic/       HeuristicScheduler — SoC-floor dispatch + bang-bang setpoint
                     README.md: full formalization (notation, Algorithm 1, complexity)
  milp/            MILPScheduler (pre-solved day-ahead comparison) + _model.py (the Pyomo MILP itself)
                     README.md: full formalization (notation, Model 1, all 16 constraints)
runner.py           plug-and-play demo -- pick a scenario ("small" or "chicago"), a scheduler (or "all"), optionally plot
tests/test_heuristic.py  non-interactive correctness check (asserts, no test framework)
data/loaders/
  fleet.py         load_chicago_taxi_demands() -- real ride demands for RideDemandClass
  building.py      load_bdg2_load(), load_bdg2_weather() -- real building load + outdoor temp
evaluation/
  metrics.py       ΔP, η_v2b, φ_i, ρ -- plain Python, no pandas dependency
  plotting.py      single-run triple panel, multi-scheduler-overlay plot, fleet text summary
scenarios/
  toy_scenario.py      3 vehicles, 2 buildings, no external files -- used by tests/ only
  small_scenario.py    Real Chicago Taxi ride demand + real BDG2 building load/weather -- the road
                       network between nodes is a placeholder, not real travel data (see comment in
                       the file). runner.py's "small" scenario (5 vehicles, 3 nodes). Carries every
                       field any scheduler needs (Null, Heuristic, or MILP), so all three run
                       against genuinely identical data -- no separate scenario per scheduler.
  chicago_scenario.py  4 real Chicago community areas, 13 vehicles, 121 real demands -- runner.py's
                       "chicago" scenario (synthetic building load; see Quick Start for why this
                       size was chosen).
docs/Architecture.png  system diagram
```

## Quick start

Dependencies: `pip install -r requirements.txt` (pandas, numpy, matplotlib, pyomo). `MILPScheduler` additionally requires a working [Gurobi](https://www.gurobi.com/) install with a license — free academic licenses are available. `NullScheduler` and `HeuristicScheduler` don't need Gurobi at all.

`runner.py` needs two real datasets that aren't checked into this repo (see [data/README.md](data/README.md) for exact download links and paths) — put them in place before running.

```bash
python runner.py
```

Prompts for a scenario (`small`: 5 vehicles, 3 nodes, seconds to solve; `chicago`: 13 vehicles, 4 real Chicago community areas, 121 real demands, harder but still solves in ~5s), then a scheduler (`null`, `heuristic`, `milp`, or `all`), then whether to save a plot, then prints ΔP, η_v2b, φ_i, ρ for each. Pick `all` to run every scheduler against the identical scenario and get one comparison plot — the same building load curve with each scheduler's grid draw overlaid on it, so it's a genuine apples-to-apples comparison, not separate experiments.

`MILPScheduler` solves in seconds against either scenario — it's a real, satisfied instance of the `BaseScheduler` contract, not a special case requiring different data. `chicago` keeps `lambda=1.0` (100% demand-service floor) fixed; `small` uses `lambda=0.3`, the largest value that solves there (see Status below). `chicago_scenario.py` was originally 6 areas / 30 vehicles / 317 demands; checked directly that this does **not** solve within Gurobi's default time limit even at `lambda=0.0` (no demand constraint at all) -- the bottleneck is the routing formulation's combinatorial size, not the demand floor. The scenario now used is a smaller real network (4 areas / 13 vehicles / 121 real demands) found by testing V=10..20 directly: V≤14 solves in under 20s, V≥15 doesn't solve within 90s. `Null`/`HeuristicScheduler` run against either scenario the same way, no solver involved.

For a fast, dependency-free correctness check instead of exploration (no data files or Gurobi needed):

```bash
python -m tests.test_heuristic
python -m tests.test_adversarial  # 7 adversarial scheduler designs x every available scenario -- clamping holds regardless
```

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

`runner.py` is the plug-and-play demo: `NullScheduler`, `HeuristicScheduler`, and `MILPScheduler` all run against either scenario, verified end-to-end, all three computing peak reduction, V2B utilization, and temporal alignment. Against `small`, MILP uses `λ=0.3` (see below). Against `chicago`, MILP keeps a hard `λ=1.0` (100% demand service) and gets it: 100% demand fulfillment, positive peak reduction on both buildings, strong temporal alignment (checked directly: 0.735 / 0.685) — solved in ~5s.

Two structural asymmetries are worth remembering when reading a Heuristic-vs-MILP comparison: the MILP has full-day foresight the heuristic doesn't have, and (for `small`) a demand-service floor the heuristic has no equivalent of (checked directly: `λ=1.0`, i.e. serve every demand, is infeasible for the 5-vehicle `small` scenario — `λ=0.3` is the largest value that solves there; `chicago`'s smaller real network solves at the full `λ=1.0`). So report peak reduction *and* demand fulfillment together, never peak reduction alone.
