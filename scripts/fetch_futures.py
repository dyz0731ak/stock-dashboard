#!/usr/bin/env python3
"""
先物・為替データ取得スクリプト（yfinance）

対象:
  - 日経225先物（NIY=F）
  - NYダウ先物（YM=F）
  - ナスダック先物（NQ=F）
  - USD/JPY（JPY=X）

出力: data/futures.json
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
]


def fetch_one(item):
    """1銘柄分: 現在値・前日終値・直近1日(5分足)の価格列を取得"""
    ticker = item["ticker"]
    try:
        t = yf.Ticker(ticker)
        # 2日分の1日足で前日終値を取る
        d_hist = t.history(period="5d", interval="1d", auto_adjust=False)
        if d_hist.empty or len(d_hist) < 2:
            print(f"  [{ticker}] 日足データ不足", file=sys.stderr)
            return None

        prev_close = float(d_hist["Close"].iloc[-2])
        last_close = float(d_hist["Close"].iloc[-1])

        # 1日分5分足（直近の値動き）
        intra = t.history(period="1d", interval="5m", auto_adjust=False)
        if intra.empty:
            # フォールバック: 30分足
            intra = t.history(period="2d", interval="30m", auto_adjust=False)

        chart_points = []
        if not intra.empty:
            for ts, row in intra.iterrows():
                price = row.get("Close")
                if price is None or price != price:  # NaN check
                    continue
                # ISOフォーマット（UTC）
                ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                chart_points.append({
                    "t": ts_iso,
                    "v": round(float(price), 4),
                })

        # 現在値は intra の最終値が最新
        if chart_points:
            current = chart_points[-1]["v"]
        else:
            current = last_close

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
            "chart":      chart_points,
        }
    except Exception as e:
        print(f"  [{ticker}] error: {e}", file=sys.stderr)
        return None


def main():
    print("[先物・為替] 取得開始...", file=sys.stderr)

    results = []
    for item in SYMBOLS:
        r = fetch_one(item)
        if r:
            print(f"  [{item['ticker']}] price={r['price']} change={r['change']} ({r['pct']:+.2f}%) chart={len(r['chart'])}点", file=sys.stderr)
            results.append(r)

    out = {
        "items":      results,
        "updated_at": datetime.datetime.now(JST).isoformat(),
    }

    # 取得失敗（0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        "data/futures.json",
        out,
        lambda d: len(d.get("items", [])),
        label="先物・為替",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "count": len(results),
    }))


if __name__ == "__main__":
    main()
