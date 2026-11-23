#!/usr/bin/env python3
"""Serve the dashboard and an on-demand chart feed for loopback previews."""
import argparse
import datetime as dt
from functools import lru_cache, partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TOKYO = ZoneInfo("Asia/Tokyo")
HISTORY_PATH = re.compile(r"/data/stock_history/([0-9][0-9A-Z]{3})/(5m|1h|1d|1w|1mo)\.json")
PROVIDER = {"5m": ("5m", "1mo"), "1h": ("60m", "2y"), "1d": ("1d", "10y")}


def calendar_bars(bars, interval):
    groups = {}
    for bar in bars:
        day = dt.datetime.fromtimestamp(bar["time"], TOKYO).date()
        period = day - dt.timedelta(days=day.weekday()) if interval == "1w" else day.replace(day=1)
        if period not in groups:
            time_at_open = dt.datetime.combine(period, dt.time(9), TOKYO)
            groups[period] = {**bar, "time": int(time_at_open.timestamp())}
            continue
        grouped = groups[period]
        grouped["high"] = max(grouped["high"], bar["high"])
        grouped["low"] = min(grouped["low"], bar["low"])
        grouped["close"] = bar["close"]
        if bar["volume"] is not None:
            grouped["volume"] = (grouped["volume"] or 0) + bar["volume"]
    return list(groups.values())


@lru_cache(maxsize=64)
def fetch_bars(code, interval, cache_window, summary=False):
    query_interval, query_range = PROVIDER[interval]
    query = urlencode({"interval": query_interval, "range": "5d" if summary else query_range, "includePrePost": "false"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=8) as response:
        result = json.load(response)["chart"]["result"][0]
    step = result["meta"]["dataGranularity"]
    if step != query_interval and (interval, step) != ("1h", "1h"):
        raise ValueError("Unexpected provider interval")
    quote = result["indicators"]["quote"][0]
    bars = {}
    for index, timestamp in enumerate(result.get("timestamp", [])):
        o, h, l, c = (quote[key][index] for key in ("open", "high", "low", "close"))
        if None in (o, h, l, c) or not (0 < l <= min(o, c) and max(o, c) <= h):
            continue
        volumes = quote.get("volume", [])
        volume = volumes[index] if index < len(volumes) else None
        # The intraday endpoint can append a standalone last quote marker.
        if interval in ("5m", "1h") and timestamp == result["meta"].get("regularMarketTime"):
            local_time = dt.datetime.fromtimestamp(timestamp, TOKYO).time()
            if local_time == dt.time(15, 30):
                # The closing-auction quote can come separately with no auction volume.
                minutes = 30 if interval == "1h" else 5
                bar_start = timestamp - minutes * 60
                previous = bars.get(bar_start)
                if previous is None:
                    bars[bar_start] = {"time": bar_start, "open": o, "high": h, "low": l, "close": c, "volume": volume or None}
                else:
                    previous.update(high=max(previous["high"], h), low=min(previous["low"], l), close=c,
                                    volume=previous["volume"] + volume if previous["volume"] is not None and volume else None)
                continue
            if local_time.second or local_time.minute % (5 if interval == "5m" else 60) or not volume:
                continue
        bars[timestamp] = {"time": timestamp, "open": o, "high": h, "low": l, "close": c, "volume": volume}
    return [bars[timestamp] for timestamp in sorted(bars)]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        match = HISTORY_PATH.fullmatch(parsed.path)
        if not match:
            return super().do_GET()
        code, interval = match.groups()
        source_interval = interval if interval in PROVIDER else "1d"
        try:
            summary = interval == "1d" and parse_qs(parsed.query).get("summary") == ["1"]
            bars = fetch_bars(code, source_interval, int(time.time()) // (300 if summary else 60), summary)
            if summary:
                bars = bars[-2:]
            if interval != source_interval:
                bars = calendar_bars(bars, interval)
        except HTTPError as error:
            if error.code != 404:
                return self.send_error(502, "Price data unavailable")
            bars = []
        except (URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
            return self.send_error(502, "Price data unavailable")
        body = json.dumps({"code": code, "interval": interval, "source": "Yahoo Finance（東証20分遅延・プレビュー）", "bars": bars}, ensure_ascii=False).encode()
        etag = '"' + sha256(body).hexdigest() + '"'
        unchanged = self.headers.get("If-None-Match") == etag
        self.send_response(304 if unchanged else 200)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        if not unchanged:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not unchanged:
            self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8878)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=ROOT)) as server:
        print(f"Local: http://127.0.0.1:{server.server_port}/chart/", flush=True)
        server.serve_forever()
