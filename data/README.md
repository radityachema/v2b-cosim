# Data

Raw data is not committed. Download and place files here before running experiments.

## Fleet data — Chicago Taxi Trips

Source: [Chicago Data Portal](https://data.cityofchicago.org/Transportation/Taxi-Trips/wrvz-psew)

Download the CSV export and save as `data/chicago_taxi_trips.csv`.

Loader: `data/loaders/fleet.py → load_chicago_taxi()`

## Building data — Building Data Genome Project 2 (BDG2)

Source: [https://github.com/buds-lab/building-data-genome-project-2](https://github.com/buds-lab/building-data-genome-project-2)

Download `train.csv` (meter readings) and `weather.csv` and save under `data/bdg2/`.

Loader: `data/loaders/building.py → load_bdg2_meter(), load_bdg2_weather()`

## Shared clock

Both datasets must be resampled to the same `freq` (default: `"15min"`) before
passing to the simulators. The loaders handle this. Do not mix frequencies.
