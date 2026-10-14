"""Weather tool: parsing Open-Meteo's daily arrays and staying inside the forecast window. No network."""
import datetime as dt

from schemas import Location
from tools import weather as w

TODAY = dt.date(2026, 10, 12)
JODHPUR = Location(name="Jodhpur", lat=26.29, lon=73.02)
DAILY = {"daily": {"time": ["2026-10-24", "2026-10-25"], "weather_code": [0, 63],
                   "temperature_2m_max": [34.1, 30.0], "temperature_2m_min": [22.0, 21.5],
                   "precipitation_probability_max": [5, None]}}


def test_daily_values_become_day_weather():
    days = w.parse_daily(DAILY)
    assert [(d.date.day, d.summary, d.rain_probability) for d in days] == [(24, "Clear sky", 5), (25, "Rain", 0)]


def test_request_is_clipped_to_the_forecast_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(w, "get_json", lambda tool, url, params: (seen.update(params) or DAILY, 1))
    w.forecast(JODHPUR, dt.date(2026, 10, 24), dt.date(2026, 10, 30), TODAY)
    assert seen["end_date"] == "2026-10-27"  # today + 15 days


def test_trip_beyond_the_window_makes_no_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no call expected")
    monkeypatch.setattr(w, "get_json", boom)
    assert w.forecast(JODHPUR, dt.date(2026, 12, 20), dt.date(2026, 12, 24), TODAY) == ([], 0)
