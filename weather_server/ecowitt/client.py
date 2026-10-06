"""HTTP-Client fuer GW1200 /get_livedata_info."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch_livedata(
    base_url: str,
    *,
    path: str = "/get_livedata_info",
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """GET livedata JSON vom Gateway. Wirft bei Netz-/HTTP-Fehlern."""
    url = f"{base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
    request = Request(url, headers={"User-Agent": "Astro-weather_server/0.1"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Gateway HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gateway unreachable: {url} ({exc.reason})") from exc

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Gateway returned invalid JSON from {url}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Gateway JSON root is not an object: {url}")
    return data
