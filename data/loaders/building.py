"""
Building data loader -- Building Data Genome Project 2 (BDG2).

Source: https://github.com/buds-lab/building-data-genome-project-2
"""
import pandas as pd


def load_bdg2_load(path, building_id, date):
    """Load one day of BDG2 electricity meter data for one building.

    Parameters
    ----------
    path : str
        Path to BDG2's electricity_cleaned.csv (one column per building).
    building_id : str
        Column name of the building to extract.
    date : str
        Date to filter to, e.g. "2016-01-02".

    Returns
    -------
    dict
        {t: kW}, t = hour of day (0-23) -- native hourly resolution.
    """
    df = pd.read_csv(path, usecols=['timestamp', building_id], parse_dates=['timestamp'])
    day = df[df['timestamp'].dt.date == pd.Timestamp(date).date()]
    return {
        row['timestamp'].hour: row[building_id]
        for _, row in day.iterrows() if pd.notna(row[building_id])
    }


def load_bdg2_weather(path, site_id, date):
    """Load one day of BDG2 outdoor temperature for one site.

    Parameters
    ----------
    path : str
        Path to BDG2's weather.csv.
    site_id : str
        Site id to filter to (e.g. "Panther").
    date : str
        Date to filter to, e.g. "2016-01-02".

    Returns
    -------
    dict
        {t: T_out in Celsius}, t = hour of day (0-23).
    """
    df = pd.read_csv(path, usecols=['timestamp', 'site_id', 'airTemperature'],
                      parse_dates=['timestamp'])
    site = df[df['site_id'] == site_id]
    day = site[site['timestamp'].dt.date == pd.Timestamp(date).date()]
    return {
        row['timestamp'].hour: row['airTemperature']
        for _, row in day.iterrows() if pd.notna(row['airTemperature'])
    }
