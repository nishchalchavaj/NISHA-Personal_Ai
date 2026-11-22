import sqlite3

import httpx

from nisha.errors import ModelUnavailable


def health(core, generate=False):
    checks = {"storage": "ok"}
    try:
        core.store.memories()
    except sqlite3.Error:
        checks["storage"] = "unavailable"
    with httpx.Client(timeout=5, trust_env=False) as client:
        try:
            response = client.get(core.settings.ollama_url + "/api/tags")
            response.raise_for_status()
            installed = {item["name"] for item in response.json()["models"]}
            missing = []
            for profile in core.settings.models.values():
                if profile.local:
                    name = profile.model.split("/", 1)[1]
                    if name not in installed and name + ":latest" not in installed:
                        missing.append(name)
            checks["ollama"] = "ok" if not missing else "missing models: " + ", ".join(missing)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            checks["ollama"] = "unavailable; start Ollama"
        try:
            response = client.get(
                core.settings.gateway_url + "/v1/models", headers=core.gateway.headers()
            )
            response.raise_for_status()
            aliases = {item["id"] for item in response.json()["data"]}
            checks["gateway"] = (
                "ok" if set(core.settings.models) <= aliases else "model aliases missing"
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            checks["gateway"] = "unavailable; run python -m nisha gateway"
    if generate:
        try:
            reply = core.gateway.complete(
                "local_fast",
                [
                    {"role": "user", "content": "Reply with the word ready."},
                ],
            )
            checks["local_generation"] = "ok" if reply else "empty response"
        except ModelUnavailable:
            checks["local_generation"] = "failed; check gateway logs"
    return checks
