# Data

Raw data is not committed (see `.gitignore`). Download and place files at
the paths below before running `runner.py` — it reads from these fixed
locations, for either the `small` or `chicago` scenario.

Both `scenarios/small_scenario.py` and `scenarios/chicago_scenario.py` do
their own inline pandas processing of the raw taxi CSV rather than going
through a shared loader (each needs its own top-N-areas-by-volume /
centroid / haversine logic, which isn't reusable across a fixed node count).
`data/loaders/fleet.py` and `data/loaders/building.py` (the BDG2 loader) are
therefore currently unused by both scenarios -- left in place, not deleted,
in case a future scenario wants a simpler non-bespoke loader again.

## Fleet data — Chicago Taxi Trips

Source: [Chicago Data Portal](https://data.cityofchicago.org/Transportation/Taxi-Trips/wrvz-psew)

Download the CSV export and save it as `data/chicago_taxi_trips.csv`.

## Building data — DOE Commercial Reference Buildings (used by both scenarios)

Source: [OpenEI, dataset 961](https://openei.org/datasets/files/961/pub/COMMERCIAL_LOAD_DATA_E_PLUS_OUTPUT/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3/)
— EnergyPlus-simulated (not measured), ASHRAE 90.1-2004 DOE Commercial
Reference Building prototypes, Chicago-O'Hare TMY3 weather file. Citation:
M. Deru et al., "U.S. Department of Energy Commercial Reference Building
Models of the National Building Stock," NREL/TP-5500-46861, 2011. Native
resolution is hourly, one year (8760 rows) per building type. This is a
genuinely Chicago-located dataset — unlike BDG2 above, no city mismatch.

Illinois has 17 TMY3 stations; only two are within Chicago city limits
(O'Hare 725300, Midway 725340) — the rest (DuPage, Waukegan, etc.) are
suburban. We use O'Hare. Each station has the same 16 DOE reference building
types (offices, hotels, retail, school, hospital, etc.) — see the directory
link above for the full list.

Download `RefBldgMediumOfficeNew2004_v1.3_7.1_5A_USA_IL_CHICAGO-OHARE.csv`
and `RefBldgSmallHotelNew2004_v1.3_7.1_5A_USA_IL_CHICAGO-OHARE.csv`, save as
`data/doe_chicago/MediumOffice.csv` and `data/doe_chicago/SmallHotel.csv`.

Loader: `data/loaders/doe_chicago.py → load_doe_chicago_load(path, month, day)`.
Returns `{15-min timestep index (0-95): kW}`, linearly interpolated from the
native hourly data (see the loader's docstring for the EnergyPlus hour-24
timestamp convention). MediumOffice (node 1) and SmallHotel (node 2) are used
by both scenarios; the "commensurate with fleet power capacity" pick was
calibrated against `small_scenario.py`'s V=13 (`V * P_bar` = 130 kW):
MediumOffice peaks ~319 kW, SmallHotel ~136 kW. At `chicago_scenario.py`'s
V=250, the same two buildings are comparatively small relative to total fleet
capacity (2,500 kW) — the binding constraint there is `Q_bldg` (fixed
charger count, 200 kW / 20 chargers, unchanged from small_scenario.py, since
a real building's charger count doesn't scale with the city's total fleet
size), not building-vs-fleet power matching. (LargeOffice peaks ~1658 kW,
SmallOffice ~20 kW — both were tried and rejected as poor fits at V=13.)

## Shared clock

Both scenarios now run at `T=96`, `dt=0.25` (15-min) — the DOE building load
is native hourly but interpolated to this resolution in both, and the
ride-demand pickup times are genuinely 15-min (derived from the taxi trips'
real timestamps) in both. They differ only in scale: `small_scenario.py` is
4 nodes / 13 vehicles (the largest scale that still solves the MILP to
proven optimality, 39s); `chicago_scenario.py` is the full 77 real active
Chicago community areas / 250 vehicles (Heuristic/Null only — MILP does not
solve at this scale, see `scenarios/chicago_scenario.py`'s docstring for the
stress-test evidence).

## No thermal (Mode B) decision in the published scenarios

Both `scenarios/small_scenario.py` and `scenarios/chicago_scenario.py`
construct every `Building` with `rc=None` (Mode A) -- AC setpoint is a
constant for this paper's published checkpoint, not something any of the
three schedulers decide. `Building.step()` (`simulator/building.py`)
still supports Mode B (thermal-aware, RC dynamics + bang-bang relay) if
a future scheduler wants to reintroduce a real thermal decision; that
capability wasn't removed, only its use by the current scenarios/
schedulers. If you do populate `rc=...` again, note that a poorly-scaled
`hvac_max` relative to a building's real load can produce misleading
results (e.g. a "worse" peak after adding HVAC control) -- check
parameter scale against the building's actual load range.
