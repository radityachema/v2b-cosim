"""
Building data loader -- DOE Commercial Reference Building (EnergyPlus-simulated),
ASHRAE 90.1-2004 prototype models, Chicago-O'Hare TMY3 weather file.

Source: https://openei.org/datasets/files/961/pub/COMMERCIAL_LOAD_DATA_E_PLUS_OUTPUT/
        USA_IL_Chicago-OHare.Intl.AP.725300_TMY3/
Citation: M. Deru et al., "U.S. Department of Energy Commercial Reference Building
Models of the National Building Stock," NREL/TP-5500-46861, 2011.

Native resolution is hourly -- linearly interpolated to 15-min for this scenario,
so values between real hourly points are interpolated, not measured. The last
3 of each day's 96 slots hold at the final hour's value (no next-day point is
loaded for a single-day cut).
"""
import numpy as np
import pandas as pd

_LOAD_COL = 'Electricity:Facility [kW](Hourly)'


def load_doe_chicago_load(path, month, day):
    """Load one day of DOE Chicago-O'Hare EnergyPlus electricity output,
    interpolated from native hourly to 15-min, as {timestep index (0-95): kW}.

    EnergyPlus timestamps label the END of each hourly interval -- hour label
    24 is that same date's 23:00-24:00 interval, not the next day."""
    df = pd.read_csv(path)
    parts = df['Date/Time'].str.strip().str.split(r'\s+', expand=True)
    m, d = parts[0].str.split('/', expand=True).astype(int).to_numpy().T
    hour_idx = parts[1].str.split(':', expand=True)[0].astype(int).to_numpy() - 1

    mask = (m == month) & (d == day)
    hourly = np.zeros(24)
    hourly[hour_idx[mask]] = df.loc[mask, _LOAD_COL].to_numpy()

    quarter_t = np.arange(96) / 4.0
    interp = np.interp(quarter_t, np.arange(24), hourly)
    return {t: float(interp[t]) for t in range(96)}
