"""Bounded retries for public market feeds; no retries for permanent 4xx errors."""
import json
import time
import sys
import requests


def get(url, attempts=2, timeout=(4, 10)):
    last = None
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            response = requests.get(url, timeout=timeout, headers={'User-Agent':'Mozilla/5.0', 'Cache-Control':'no-cache'})
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            print(json.dumps(dict(event='http_retry', url=url, attempt=attempt+1, status=status,
                                  elapsed=round(time.monotonic()-started, 2), error=str(exc))), file=sys.stderr)
            if status and status not in (408, 429, 500, 502, 503, 504):
                break
            if attempt+1 < attempts:
                delay = .7 * 2**attempt
                try:
                    retry_after = float(exc.response.headers.get('Retry-After', 0))
                    if retry_after>3:
                        break  # Do not retry earlier than the server's requested cooldown.
                    delay = max(delay, retry_after)
                except (ValueError, AttributeError):
                    pass
                time.sleep(min(delay, 3))
    raise last
