"""Kleine HTTP-laag met retries. Alleen lezen: er bestaat in dit pakket geen order-endpoint."""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = "jplh/0.1 (JP-libau Holding research bot)"


class DataError(RuntimeError):
    pass


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def get(url: str, timeout: float = 15.0, retries: int = 3, backoff: float = 1.5) -> bytes:
    """GET met retries bij netwerkfouten, 429 en 5xx. Andere 4xx falen meteen."""
    last: Exception | None = None
    ctx = ssl_context()
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429 and exc.code < 500:
                raise DataError(f"HTTP {exc.code} voor {url}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(backoff * (2**attempt))
    raise DataError(f"{url} niet bereikbaar na {retries} pogingen: {last}")


def get_json(url: str, **kw) -> object:
    return json.loads(get(url, **kw))
