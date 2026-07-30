#!/usr/bin/env python3
"""ジャパンネクスト公式CSVから夜間PTS値上がり率ランキングを作成する。"""

import csv
import datetime
import io
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save
from fetch_japan_stocks import enrich_yfinance, fetch_jpx_listed_stocks


CSV_URL = "https://www.japannext.co.jp/csv_download/dnd_market_movers/NGHT"
KABUTAN_LIVE_URL = "https://s.kabutan.jp/warnings/pts_night_price_increase/"
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


def active_night_session_date(now):
    """16:30〜翌06:00の進行中セッション日。時間外はNone。"""
    local = now.astimezone(JST)
    minutes = local.hour * 60 + local.minute
    if minutes >= 16 * 60 + 30:
        return local.date()
    if minutes < 6 * 60:
        return local.date() - datetime.timedelta(days=1)
    return None


def parse_kabutan_live(html):
    """株探モバイル版のPTS夜間上昇率ランキングを構造化する。"""
    soup = BeautifulSoup(html, "html.parser")
    as_of_match = re.search(
        r"株価：(\d{4})年(\d{2})月(\d{2})日\s+(\d{2}:\d{2})現在",
        soup.get_text(" ", strip=True),
    )
    if not as_of_match:
        raise ValueError("PTS当日ランキングのデータ日時を確認できません")
    session_date = (
        f"{as_of_match.group(1)}-{as_of_match.group(2)}-{as_of_match.group(3)}"
    )
    as_of = f"{session_date}T{as_of_match.group(4)}:00+09:00"

    table = next(
        (
            table for table in soup.find_all("table")
            if "PTS株価" in table.get_text(" ", strip=True)
            and "出来高" in table.get_text(" ", strip=True)
        ),
        None,
    )
    if table is None:
        raise ValueError("PTS当日ランキング表を確認できません")

    stocks = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["th", "td"])
        if len(cells) < 5:
            continue
        link = cells[0].find("a", href=re.compile(r"^/stocks/"))
        if not link:
            continue
        code_match = re.search(r"/stocks/([0-9A-Z]+)/", link.get("href", ""))
        if not code_match:
            continue
        code = code_match.group(1)
        abbr = link.find("abbr")
        name = (
            abbr.get("title")
            if abbr and abbr.get("title")
            else (link.find("p").get_text(" ", strip=True) if link.find("p") else code)
        )
        market_span = link.find("span")
        market_tse = market_span.get_text(" ", strip=True) if market_span else ""
        reference_price = as_number(cells[1].get_text(" ", strip=True))
        price = as_number(cells[2].get_text(" ", strip=True))
        change_parts = list(cells[3].stripped_strings)
        change = as_number(change_parts[0]) if change_parts else None
        pct = as_number(change_parts[1]) if len(change_parts) > 1 else None
        volume = as_number(cells[4].get_text(" ", strip=True).replace("株", ""))
        if price is None or pct is None or pct <= 0:
            continue
        stocks.append({
            "code": code,
            "name": name,
            "market": "夜間PTS",
            "market_tse": market_tse,
            "price": round(price, 2),
            "change_amount": round(change, 2) if change is not None else None,
            "change_pct": round(pct, 3),
            "volume": int(volume) if volume is not None else None,
            "turnover": (
                int(round(price * volume))
                if volume is not None else None
            ),
            "reference_price": (
                round(reference_price, 2)
                if reference_price is not None else None
            ),
            "sector": "不明",
            "chart": None,
            "session_date": session_date,
        })
    return session_date, as_of, stocks


def fetch_kabutan_live(expected_date):
    """進行中夜間セッションの上昇率上位30件を2ページから取得する。"""
    combined = {}
    newest_as_of = ""
    session_date = ""
    for page in (1, 2):
        response = requests.get(
            KABUTAN_LIVE_URL,
            params={"page": page},
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        page_date, as_of, stocks = parse_kabutan_live(response.text)
        session_date = page_date
        newest_as_of = max(newest_as_of, as_of)
        for stock in stocks:
            combined[stock["code"]] = stock

    if session_date != expected_date.isoformat():
        raise ValueError(
            f"PTS当日値が未更新です: expected={expected_date}, actual={session_date}"
        )
    stocks = sorted(
        combined.values(),
        key=lambda stock: stock["change_pct"],
        reverse=True,
    )[:30]
    if len(stocks) < 10:
        raise ValueError(f"PTS当日値上がり銘柄が少なすぎます: {len(stocks)}件")
    return session_date, newest_as_of, stocks


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
        active_date = active_night_session_date(now)
        if active_date:
            session_date, as_of, stocks = fetch_kabutan_live(active_date)
            source = "kabutan_pts_live"
            source_label = "株探 PTS夜間ランキング（ジャパンネクスト提供値）"
            source_url = KABUTAN_LIVE_URL
            scope = "PTS ナイトタイム・セッション（進行中）"
            ranking_definition = "通常取引終値比・値上がり率上位30銘柄"
        else:
            response = requests.get(CSV_URL, headers=HEADERS, timeout=45)
            response.raise_for_status()
            session_date, stocks = parse_csv(response.content.decode("utf-8-sig"))
            as_of = None
            source = "japannext"
            source_label = "ジャパンネクスト証券 公式夜間PTSランキング"
            source_url = SOURCE_PAGE
            scope = "ジャパンネクストPTS ナイトタイム・セッション"
            ranking_definition = "東証終値比・値上がり率上位30銘柄"
        if len(stocks) < 10:
            raise ValueError(f"PTS値上がり銘柄が少なすぎます: {len(stocks)}件")
        stocks = enrich_metadata(stocks)
        output = {
            "updated_at": now.isoformat(),
            "last_attempt_at": now.isoformat(),
            "session_date": session_date,
            "as_of": as_of,
            "source": source,
            "source_label": source_label,
            "source_url": source_url,
            "scope": scope,
            "ranking_definition": ranking_definition,
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
