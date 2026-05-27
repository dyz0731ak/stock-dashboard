#!/usr/bin/env python3
"""
先物・為替・指数データ取得スクリプト（yfinance）

対象:
  - 日経225先物（NIY=F）
  - NYダウ先物（YM=F）
  - ナスダック先物（NQ=F）
  - USD/JPY（JPY=X）
  - SOX指数（^SOX）
  - 金先物（GC=F）

出力: data/futures.json
  各 item は最新値 + 直近6ヶ月の日足OHLC配列を持つ。
"""

import yfinance as yf
import json
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

JST = datetime.timezone(datetime.timedelta(hours=9))

SYMBOLS = [
    {"id": "nk225",  "ticker": "NIY=F", "label": "日経225先物",   "decimals": 0, "sep": True},
    {"id": "ym",     "ticker": "YM=F",  "label": "NYダウ先物",    "decimals": 0, "sep": True},
    {"id": "nq",     "ticker": "NQ=F",  "label": "ナスダック先物", "decimals": 2, "sep": True},
    {"id": "usdjpy", "ticker": "JPY=X", "label": "USD/JPY",       "decimals": 3, "sep": False},
    {"id": "sox",    "ticker": "^SOX",  "label": "SOX指数",        "decimals": 2, "sep": True},
    {"id": "gold",   "ticker": "GC=F",  "label": "金先物",         "decimals": 1, "sep": True},
]


def fetch_one(item):
    """1銘柄分: 直近6ヶ月の日足OHLCを取得し、最新値・前日終値・日次変化率を計算"""
    ticker = item["ticker"]
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="6mo", interval="1d", auto_adjust=False)
        if hist.empty or len(hist) < 2:
            print(f"  [{ticker}] 日足データ不足", file=sys.stderr)
            return None

        candles = []
        for ts, row in hist.iterrows():
            o = row.get("Open")
            h = row.get("High")
            l = row.get("Low")
            c = row.get("Close")
            # NaN チェック（pandas/numpy NaN は self != self）
            if any(v is None or v != v for v in (o, h, l, c)):
                continue
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            candles.append({
                "t": ts_iso,
                "o": round(float(o), 4),
                "h": round(float(h), 4),
                "l": round(float(l), 4),
                "c": round(float(c), 4),
            })

        if len(candles) < 2:
            print(f"  [{ticker}] 有効なローソク不足", file=sys.stderr)
            return None

        last = candles[-1]
        prev = candles[-2]
        current = last["c"]
        prev_close = prev["c"]
        change = current - prev_close
        pct = (change / prev_close * 100) if prev_close else 0.0

        return {
            "id":         item["id"],
            "ticker":     ticker,
            "label":      item["label"],
            "price":      round(current, 4),
            "prev_close": round(prev_close, 4),
            "change":     round(change, 4),
            "pct":        round(pct, 3),
            "decimals":   item["decimals"],
            "sep":        item["sep"],
            "chart":      candles,
        }
    except Exception as e:
        print(f"  [{ticker}] error: {e}", file=sys.stderr)
        return None


def main():
    print("[先物・為替・指数] 取得開始...", file=sys.stderr)

    results = []
    for item in SYMBOLS:
        r = fetch_one(item)
        if r:
            print(f"  [{item['ticker']}] price={r['price']} change={r['change']} ({r['pct']:+.2f}%) candles={len(r['chart'])}", file=sys.stderr)
            results.append(r)

    out = {
        "items":      results,
        "updated_at": datetime.datetime.now(JST).isoformat(),
    }

    saved = safe_save(
        "data/futures.json",
        out,
        lambda d: len(d.get("items", [])),
        label="先物・為替・指数",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "count": len(results),
    }))


if __name__ == "__main__":
    main()
