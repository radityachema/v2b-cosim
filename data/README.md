# Data

Raw data is not committed (see `.gitignore`). Download and place files at
the paths below before running `runner.py` or `experiments/milp_comparison.py`
— both read from these fixed locations.

## Fleet data — Chicago Taxi Trips

Source: [Chicago Data Portal](https://data.cityofchicago.org/Transportation/Taxi-Trips/wrvz-psew)

Download the CSV export and save it as `data/chicago_taxi_trips.csv`.

Loader: `data/loaders/fleet.py → load_chicago_taxi_demands(path, date, node_map)`

Returns a list of ride demand dicts (`{'id', 'i_d', 'j_d', 't_d'}`) ready for
`RideDemandClass`, at native hourly resolution. `node_map` (Chicago Community
Area → network node id) is supplied by the caller — this loader doesn't decide
which areas belong in a given network, so it stays reusable across setups.

## Building data — Building Data Genome Project 2 (BDG2)

Source: [https://github.com/buds-lab/building-data-genome-project-2](https://github.com/buds-lab/building-data-genome-project-2)

Download `electricity_cleaned.csv` (meter readings) and `weather.csv`, save
both under `data/bdg2/`.

Loader: `data/loaders/building.py → load_bdg2_load(path, building_id, date)`,
`load_bdg2_weather(path, site_id, date)`

Both return plain dicts (`{t: value}`, `t` = hour of day 0–23) — `load_bdg2_load`
in kW for one building column, `load_bdg2_weather` in °C outdoor temperature for
one site.

**No BDG2 site is actually located in Chicago** (checked directly — closest
`US_Central` timezone sites are Austin, TX and Minneapolis, MN). Pairing
Chicago fleet demand with a BDG2 building means a real-but-different-city
building, not a geographically coherent deployment — fine for testing the
pipeline end-to-end, not for claiming a coherent scenario without saying so.
`scenarios/real_scenario.py` uses the "Panther" site (Orlando, FL) for this
reason among others — it's simply a real building whose meter data was
available, not a claim about Chicago building stock.

## Shared clock

Both loaders operate at native hourly resolution (`t` = hour of day) — that's
the real granularity of both source datasets, not resampled to 15-min. Build
the `Simulator` for real-data runs with `dt=1.0`, not the synthetic toy
scenario's default `dt=0.25`.

## RC/HVAC parameters are not fitted to real buildings

`Building(rc=...)` parameters (`a`, `b`, `hvac_max`) used in
`scenarios/real_scenario.py` are hand-picked to be roughly proportionate to
each building's own real load range and to keep the MILP feasible against
real weather — they are not fitted to any specific building's actual
measured thermal behavior. A poorly-scaled `hvac_max` relative to a
building's real load can produce misleading results (e.g. a "worse" peak
after adding HVAC control) — check parameter scale against the building's
actual load range before trusting a Mode B result on different data.
