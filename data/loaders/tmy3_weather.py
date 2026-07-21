"""
Outdoor dry-bulb temperature loader -- NREL TMY3 EnergyPlus weather file (.epw),
Chicago-O'Hare Intl. AP, station 725300. Same station already used for the
DOE Commercial Reference Building load data (see doe_chicago.py) -- this is
the companion weather file that was missing (Building.step()'s RC model was
falling back to a hardcoded 30 degC constant with no real weather wired in).

Source: https://climate.onebuilding.org (WMO_Region_4_North_and_Central_America
        / USA_United_States_of_America / IL_Illinois)
Citation: NREL, "Users Manual for TMY3 Data Sets," NREL/TP-581-43156, 2008.

EPW format: 8 header lines, then one row per hour, 8760 rows/year (no leap
day). Columns are positional (no header row on the data section): Year=0,
Month=1, Day=2, Hour=3 (1-24, hour 24 = that date's 23:00-24:00 interval --
same "label ends the interval" convention as doe_chicago.py), Minute=4,
Data Source/Uncertainty flags=5, Dry Bulb Temperature [C]=6.

Native resolution is hourly -- linearly interpolated to 15-min to match
doe_chicago.py's load data, so both series line up on the same timestep grid.
"""
import numpy as np
import pandas as pd

_N_HEADER_LINES = 8
_MONTH_COL, _DAY_COL, _HOUR_COL, _DRYBULB_COL = 1, 2, 3, 6


def load_tmy3_outdoor_temp(path, month, day):
    """Load one day of TMY3 outdoor dry-bulb temperature, interpolated from
    native hourly to 15-min, as {timestep index (0-95): degC}."""
    df = pd.read_csv(path, skiprows=_N_HEADER_LINES, header=None)

    mask = (df[_MONTH_COL] == month) & (df[_DAY_COL] == day)
    hour_idx = df.loc[mask, _HOUR_COL].to_numpy() - 1
    hourly = np.zeros(24)
    hourly[hour_idx] = df.loc[mask, _DRYBULB_COL].to_numpy()

    quarter_t = np.arange(96) / 4.0
    interp = np.interp(quarter_t, np.arange(24), hourly)
    return {t: float(interp[t]) for t in range(96)}
