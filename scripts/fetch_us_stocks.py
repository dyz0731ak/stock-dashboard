#!/usr/bin/env python3
"""
Yahoo Finance から米国株の上昇率上位銘柄を取得して JSON に保存するスクリプト
"""

import requests
import json
import datetime
import sys
import time

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

# セクター名マッピング（英語→日本語）
SECTOR_JP = {
    "Technology": "テクノロジー",
    "Healthcare": "ヘルスケア",
    "Financials": "金融",
    "Consumer Discretionary": "一般消費財",
    "Consumer Staples": "生活必需品",
    "Industrials": "資本財・サービス",
    "Energy": "エネルギー",
    "Materials": "素材",
    "Real Estate": "不動産",
    "Communication Services": "通信サービス",
    "Utilities": "公共事業",
    "Financial Services": "金融サービス",
    "Basic Materials": "基礎素材",
    "N/A": "不明",
    "": "不明",
}

# 主要銘柄のセクター情報（Yahoo Finance APIが失敗した場合のフォールバック）
KNOWN_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "GOOG": "Technology", "AMZN": "Consumer Discretionary", "META": "Technology",
    "NVDA": "Technology", "TSLA": "Consumer Discretionary", "NFLX": "Technology",
    "AMD": "Technology", "INTC": "Technology", "CRM": "Technology",
    "ORCL": "Technology", "ADBE": "Technology", "QCOM": "Technology",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
    "MS": "Financials", "V": "Financials", "MA": "Financials",
    "JNJ": "Healthcare", "PFE": "Healthcare", "MRNA": "Healthcare",
    "UNH": "Healthcare", "ABBV": "Healthcare", "LLY": "Healthcare",
    "XOM": "Energy", "CVX": "Energy", "OXY": "Energy",
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PG": "Consumer Staples",
    "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "DIS": "Communication Services", "CMCSA": "Communication Services",
    "T": "Communication Services", "VZ": "Communication Services",
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "HON": "Industrials", "MMM": "Industrials",
    "BRK-B": "Financials", "BRK.B": "Financials",
}


def fetch_yahoo_finance_gainers():
    """Yahoo Finance Screener API から上昇率上位銘柄を取得"""
    stocks = []

    # Yahoo Finance の day_gainers スクリーナー
    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        "?formatted=false&scrIds=day_gainers&count=50&region=US&lang=en-US"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        data = resp.json()

        quotes = (
            data.get("finance", {})
            .get("result", [{}])[0]
            .get("quotes", [])
        )

        for q in quotes:
            symbol = q.get("symbol", "")
            name = q.get("shortName") or q.get("longName") or symbol
            price = q.get("regularMarketPrice", 0)
            change = q.get("regularMarketChange", 0)
            change_pct = q.get("regularMarketChangePercent", 0)
            volume = q.get("regularMarketVolume", 0)
            market_cap = q.get("marketCap", 0)
            sector_en = q.get("sector") or KNOWN_SECTORS.get(symbol, "")
            sector = SECTOR_JP.get(sector_en, sector_en or "不明")

            stocks.append({
                "symbol": symbol,
                "name": name,
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "market_cap": market_cap,
                "sector": sector,
                "sector_en": sector_en,
            })

        print(f"Yahoo Finance Screener: {len(stocks)} 銘柄取得", file=sys.stderr)

    except Exception as e:
        print(f"[警告] Yahoo Finance Screener 失敗: {e}", file=sys.stderr)
        stocks = fetch_yahoo_finance_v2_gainers()

    return stocks


def fetch_yahoo_finance_v2_gainers():
    """Yahoo Finance v2 API (代替) から上昇率上位銘柄を取得"""
    stocks = []

    url = (
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved"
        "?formatted=false&scrIds=day_gainers&count=50&region=US&lang=en-US"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        data = resp.json()
        quotes = (
            data.get("finance", {})
            .get("result", [{}])[0]
            .get("quotes", [])
        )

        for q in quotes:
            symbol = q.get("symbol", "")
            name = q.get("shortName") or q.get("longName") or symbol
            price = q.get("regularMarketPrice", 0)
            change = q.get("regularMarketChange", 0)
            change_pct = q.get("regularMarketChangePercent", 0)
            volume = q.get("regularMarketVolume", 0)
            market_cap = q.get("marketCap", 0)
            sector_en = q.get("sector") or KNOWN_SECTORS.get(symbol, "")
            sector = SECTOR_JP.get(sector_en, sector_en or "不明")

            stocks.append({
                "symbol": symbol,
                "name": name,
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "market_cap": market_cap,
                "sector": sector,
                "sector_en": sector_en,
            })

        print(f"Yahoo Finance v2: {len(stocks)} 銘柄取得", file=sys.stderr)

    except Exception as e:
        print(f"[警告] Yahoo Finance v2 失敗: {e}", file=sys.stderr)

    return stocks


def fetch_sector_info_batch(symbols):
    """Yahoo Finance から銘柄のセクター情報をバッチ取得"""
    sector_map = {}
    # 10件ずつ取得
    chunk_size = 10
    for i in range(0, min(len(symbols), 50), chunk_size):
        chunk = symbols[i : i + chunk_size]
        symbols_str = ",".join(chunk)
        url = (
            f"https://query1.finance.yahoo.com/v1/finance/quoteType/"
            f"?symbols={symbols_str}&lang=en-US&region=US"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            data = resp.json()
            results = data.get("quoteType", {}).get("result", [])
            for r in results:
                sym = r.get("symbol", "")
                sector_en = r.get("sector") or KNOWN_SECTORS.get(sym, "")
                sector_map[sym] = SECTOR_JP.get(sector_en, sector_en or "不明")
            time.sleep(0.3)
        except Exception:
            pass
    return sector_map


def aggregate_by_sector(stocks):
    """セクター別に集計"""
    sector_data = {}
    for s in stocks:
        sector = s.get("sector", "不明") or "不明"
        if sector not in sector_data:
            sector_data[sector] = {
                "count": 0,
                "symbols": [],
                "avg_change_pct": 0,
                "total_change_pct": 0,
            }
        sector_data[sector]["count"] += 1
        sector_data[sector]["symbols"].append(s["symbol"])
        sector_data[sector]["total_change_pct"] += s.get("change_pct", 0)

    # 平均騰落率を計算
    for sector in sector_data:
        count = sector_data[sector]["count"]
        if count > 0:
            sector_data[sector]["avg_change_pct"] = round(
                sector_data[sector]["total_change_pct"] / count, 2
            )

    # 件数降順ソート
    return dict(
        sorted(sector_data.items(), key=lambda x: x[1]["count"], reverse=True)
    )


def main():
    print("米国株データ取得中...", file=sys.stderr)

    gainers = fetch_yahoo_finance_gainers()

    # セクター情報が不足している銘柄を補完
    missing_sector = [s["symbol"] for s in gainers if s["sector"] == "不明"]
    if missing_sector:
        print(f"セクター不明: {len(missing_sector)} 銘柄 → 補完取得中...", file=sys.stderr)
        sector_map = fetch_sector_info_batch(missing_sector)
        for s in gainers:
            if s["symbol"] in sector_map:
                s["sector"] = sector_map[s["symbol"]]

    # セクター別集計
    sector_analysis = aggregate_by_sector(gainers)

    # 上昇率でソート
    gainers.sort(key=lambda x: x.get("change_pct", 0), reverse=True)

    output = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gainers": gainers,
        "sector_analysis": sector_analysis,
        "total_gainers": len(gainers),
    }

    out_path = "data/us_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"保存完了: {out_path}", file=sys.stderr)
    print(json.dumps({"status": "ok", "gainers": len(gainers)}))


if __name__ == "__main__":
    main()
