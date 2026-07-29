#!/usr/bin/env python3
"""ジャパンネクスト公式CSVから夜間PTS値上がり率ランキングを作成する。"""

import csv
import datetime
import io
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save
from fetch_japan_stocks import enrich_yfinance, fetch_jpx_listed_stocks


CSV_URL = "https://www.japannext.co.jp/csv_download/dnd_market_movers/NGHT"
SOURCE_PAGE = (
    "https://www.japannext.co.jp/ja/statistics/market-movers/"
    "turnover-and-market-share"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
JST = datetime.timezone(datetime.timedelta(hours=9))


def as_number(value):
    text = str(value or "").strip().replace(",", "")
    return float(text) if text else None


def parse_csv(text):
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if len(rows) < 5 or rows[0][:2] != ["Market", "Date"]:
        raise ValueError("PTS公式CSVの形式を確認できません")

    session_date = rows[1][1].strip()
    header_index = next(
        i for i, row in enumerate(rows)
        if row and row[0].strip() == "Symbol"
    )
    headers = [column.strip() for column in rows[header_index]]
    stocks = []
    for raw in rows[header_index + 1:]:
        if not raw or len(raw) < len(headers):
            continue
        item = dict(zip(headers, raw))
        pct = as_number(item.get("% Change"))
        if pct is None or pct <= 0:
            continue
        price = as_number(item.get("Price"))
        change = as_number(item.get("Change"))
        volume = as_number(item.get("Volume"))
        code = str(item.get("Symbol") or "").strip()
        if not code or price is None:
            continue
        stocks.append({
            "code": code,
            "name": str(item.get("Security Name") or code).strip(),
            "market": "夜間PTS",
            "price": round(price, 2),
            "change_amount": round(change, 2) if change is not None else None,
            "change_pct": round(pct, 3),
            "volume": int(volume) if volume is not None else None,
            "turnover": (
                int(round(price * volume))
                if volume is not None else None
            ),
            "reference_price": (
                round(price - change, 2)
                if change is not None else None
            ),
            "sector": "不明",
            "chart": None,
            "session_date": session_date,
        })
    stocks.sort(key=lambda stock: stock["change_pct"], reverse=True)
    return session_date, stocks[:30]


def enrich_metadata(stocks):
    master = fetch_jpx_listed_stocks()
    by_code = {stock["code"]: stock for stock in master}
    for stock in stocks:
        metadata = by_code.get(stock["code"])
        if not metadata:
            continue
        stock["name"] = metadata.get("name") or stock["name"]
        stock["market_tse"] = metadata.get("market")
        stock["sector"] = metadata.get("sector") or "不明"
    return enrich_yfinance(stocks, max_workers=8, label="PTS ")


def main():
    now = datetime.datetime.now(JST)
    try:
        response = requests.get(CSV_URL, headers=HEADERS, timeout=45)
        response.raise_for_status()
        session_date, stocks = parse_csv(response.content.decode("utf-8-sig"))
        if len(stocks) < 10:
            raise ValueError(f"PTS値上がり銘柄が少なすぎます: {len(stocks)}件")
        stocks = enrich_metadata(stocks)
        output = {
            "updated_at": now.isoformat(),
            "last_attempt_at": now.isoformat(),
            "session_date": session_date,
            "source": "japannext",
            "source_label": "ジャパンネクスト証券 公式夜間PTSランキング",
            "source_url": SOURCE_PAGE,
            "scope": "ジャパンネクストPTS ナイトタイム・セッション",
            "ranking_definition": "東証終値比・値上がり率上位30銘柄",
            "ranking_count": len(stocks),
            "fetch_status": "ok",
            "all_stocks": stocks,
        }
    except Exception as exc:
        print(f"[夜間PTS] 取得失敗: {exc}", file=sys.stderr)
        output = {
            "updated_at": now.isoformat(),
            "last_attempt_at": now.isoformat(),
            "fetch_status": "stale",
            "fetch_error": str(exc),
            "all_stocks": [],
        }

    saved = safe_save(
        "data/pts_ranking.json",
        output,
        lambda data: (
            len(data.get("all_stocks", []))
            if len(data.get("all_stocks", [])) >= 10 else 0
        ),
        label="夜間PTS",
        failure_reason=output.get("fetch_error"),
    )
    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "session_date": output.get("session_date"),
        "stocks": len(output.get("all_stocks", [])),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
