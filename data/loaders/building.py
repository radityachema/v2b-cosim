"""
Building data loader -- Building Data Genome Project 2 (BDG2).

Source: https://github.com/buds-lab/building-data-genome-project-2
"""
import pandas as pd


def load_bdg2_load(path, building_id, date):
    """Load one day of BDG2 electricity data for one building as {hour: kW}."""
    df = pd.read_csv(path, usecols=['timestamp', building_id], parse_dates=['timestamp'])
    day = df[df['timestamp'].dt.date == pd.Timestamp(date).date()]
    return {
        row['timestamp'].hour: row[building_id]
        for _, row in day.iterrows() if pd.notna(row[building_id])
    }


def load_bdg2_weather(path, site_id, date):
    """Load one day of BDG2 outdoor temperature for one site as {hour: Celsius}."""
    df = pd.read_csv(path, usecols=['timestamp', 'site_id', 'airTemperature'],
                      parse_dates=['timestamp'])
    site = df[df['site_id'] == site_id]
    day = site[site['timestamp'].dt.date == pd.Timestamp(date).date()]
    return {
        row['timestamp'].hour: row['airTemperature']
        for _, row in day.iterrows() if pd.notna(row['airTemperature'])
    }
