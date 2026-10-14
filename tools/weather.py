"""Weather tool: daily forecast for the trip dates (Open-Meteo forecast API, free, no API key)."""
import datetime as dt

import config
from schemas import DayWeather, Location
from tools.http import get_json

URL = "https://api.open-meteo.com/v1/forecast"
# WMO weather codes used by Open-Meteo
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy rain showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def last_forecast_day(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=config.FORECAST_MAX_DAYS - 1)


def parse_daily(data: dict) -> list[DayWeather]:
    d = data.get("daily") or {}
    days = []
    for i, day in enumerate(d.get("time") or []):
        tmax, tmin = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        if tmax is None or tmin is None:
            continue  # the model has no value for that day
        rain = d.get("precipitation_probability_max", [None] * (i + 1))[i]
        code = d.get("weather_code", [None] * (i + 1))[i]
        days.append(DayWeather(date=dt.date.fromisoformat(day), temp_max_c=tmax, temp_min_c=tmin,
                               rain_probability=int(rain or 0), summary=WEATHER_CODES.get(code, "Unknown")))
    return days


def forecast(location: Location, start: dt.date, end: dt.date, today: dt.date) -> tuple[list[DayWeather], int]:
    """Forecast for the trip days inside the forecast window. Returns (days, attempts); ([], 0) if none fall
    inside it. Raises ToolError if the API fails."""
    last = min(end, last_forecast_day(today))
    if start > last:
        return [], 0
    params = {"latitude": location.lat, "longitude": location.lon, "timezone": "Asia/Kolkata",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
              "start_date": start.isoformat(), "end_date": last.isoformat()}
    data, attempts = get_json("weather", URL, params)
    return parse_daily(data if isinstance(data, dict) else {}), attempts
