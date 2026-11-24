"""Live, sourced weather for explicit user requests; never invent conditions."""

import re

import httpx


def weather_request(text):
    value = text.casefold().strip(" .!?")
    if not re.search(r"\bweather\b", value):
        return None
    if re.search(r"\bdefine weather\b|\bwhat does weather mean\b", value):
        return None
    if not re.search(r"\b(?:weather|temperature|forecast)\b", value):
        return None
    place = re.search(r"\b(?:in|for|at)\s+([a-z][a-z .'-]{1,65})$", value)
    location = place[1].strip() if place else "Nargund"
    if location in {"nargonda", "naragund", "nargunda"}:
        location = "Nargund"
    return location


class LiveWeather:
    def __init__(self, client=None):
        self.client = client

    def current(self, location):
        client = self.client or httpx.Client(timeout=8, trust_env=False)
        try:
            params = {"name": location, "count": 3, "language": "en"}
            if location == "Nargund":
                params["countryCode"] = "IN"
            response = client.get("https://geocoding-api.open-meteo.com/v1/search", params=params)
            response.raise_for_status()
            places = response.json().get("results", [])
            if not places:
                return f"I couldn't locate {location} for a live weather check. Please give a town and state."
            if len(places) > 1 and location != "Nargund":
                names = ", ".join(
                    f"{p['name']}, {p.get('admin1') or p.get('country', '')}" for p in places[:3]
                )
                return f"Several places match {location}: {names}. Which one?"
            place = places[0]
            response = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"], "longitude": place["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                    "timezone": "auto", "forecast_days": 1,
                },
            )
            response.raise_for_status()
            current = response.json()["current"]
            temperature = float(current["temperature_2m"])
            humidity = int(current["relative_humidity_2m"])
            wind = float(current["wind_speed_10m"])
            condition = describe_code(int(current["weather_code"]))
            place_name = ", ".join(
                part for part in (place["name"], place.get("admin1"), place.get("country")) if part
            )
            return (
                f"Current model estimate for {place_name} at {current['time']}: "
                f"{temperature:g}°C, {condition}; humidity {humidity}%, wind {wind:g} km/h. "
                "Source: Open-Meteo (https://open-meteo.com/)."
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return "I couldn't retrieve live weather right now, so I won't guess the conditions."
        finally:
            if self.client is None:
                client.close()


def describe_code(code):
    if code == 0:
        return "clear sky"
    if code in {1, 2, 3}:
        return "partly to fully cloudy"
    if code in {45, 48}:
        return "foggy"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorms"
    return "conditions unavailable"
