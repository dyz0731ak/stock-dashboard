#!/usr/bin/env python3
"""
yfinance で S&P500 構成銘柄から当日上昇率上位20銘柄を取得
チャートデータ（6ヶ月日足）と会社情報も一緒に保存
"""

import yfinance as yf
import pandas as pd
import json
import datetime
import sys
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

SECTOR_JP = {
    "Technology":             "テクノロジー",
    "Health Care":            "ヘルスケア",
    "Healthcare":             "ヘルスケア",
    "Financials":             "金融",
    "Financial Services":     "金融サービス",
    "Consumer Discretionary": "一般消費財",
    "Consumer Cyclical":      "一般消費財",
    "Consumer Staples":       "生活必需品",
    "Consumer Defensive":     "生活必需品",
    "Industrials":            "資本財・サービス",
    "Energy":                 "エネルギー",
    "Materials":              "素材",
    "Basic Materials":        "基礎素材",
    "Real Estate":            "不動産",
    "Communication Services": "通信サービス",
    "Utilities":              "公共事業",
}


def get_sp500_tickers():
    """Wikipedia から S&P500 構成銘柄リストを取得"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    print("  S&P500 銘柄リスト取得中...", file=sys.stderr)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="constituents")
        if not table:
            raise ValueError("constituents テーブル未発見")
        tickers = [
            row.find_all("td")[0].get_text(strip=True).replace(".", "-")
            for row in table.find_all("tr")[1:]
            if row.find_all("td")
        ]
        print(f"  S&P500: {len(tickers)}銘柄", file=sys.stderr)
        return tickers
    except Exception as e:
        print(f"  S&P500 取得失敗（フォールバック）: {e}", file=sys.stderr)
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
            "V","UNH","XOM","ORCL","MA","COST","HD","PG","JNJ","WMT",
            "ABBV","NFLX","BAC","AMD","CRM","CVX","KO","MRK","PEP","TMO",
            "ACN","LIN","MCD","CSCO","ABT","NKE","DHR","TXN","QCOM","GE",
            "NEE","INTU","IBM","RTX","AMGN","AMAT","PM","SPGI","HON","ISRG",
            "GS","T","BKNG","VRTX","CAT","LOW","NOW","SYK","PLD","DE",
        ]


def fetch_price_data(tickers):
    """yfinance で 2 日分の価格データを一括取得"""
    print(f"  価格データ取得中（{len(tickers)}銘柄）...", file=sys.stderr)
    try:
        data = yf.download(
            tickers, period="2d", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        return data
    except Exception as e:
        print(f"  価格データ取得エラー: {e}", file=sys.stderr)
        return None


def calculate_top_gainers(data, top_n=20):
    """前日比騰落率を計算してトップ N を返す"""
    if data is None or data.empty:
        return []
    try:
        close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]
        if len(close) >= 2:
            prev_close = close.iloc[-2]
            curr_close = close.iloc[-1]
        else:
            curr_close = prev_close = close.iloc[-1]

        pct_change    = ((curr_close - prev_close) / prev_close * 100).dropna()
        change_amount = (curr_close - prev_close).dropna()
        top_gainers   = pct_change.nlargest(top_n)

        results = []
        for ticker in top_gainers.index:
            pct   = float(pct_change.get(ticker, 0))
            chg   = float(change_amount.get(ticker, 0))
            price = float(curr_close.get(ticker, 0))
            prev  = float(prev_close.get(ticker, 0))
            if price <= 0:
                continue
            results.append({
                "symbol": ticker, "price": round(price, 2),
                "prev_close": round(prev, 2), "change": round(chg, 2),
                "change_pct": round(pct, 2),
                "name": "", "sector": "", "sector_en": "",
                "volume": 0, "market_cap": 0,
                "description": None, "industry": None, "website": None,
                "chart": None,
            })
        return results
    except Exception as e:
        print(f"  騰落率計算エラー: {e}", file=sys.stderr)
        return []


def fetch_ticker_full(symbol):
    """
    yfinance Ticker から会社情報 + 6ヶ月チャートを取得
    Returns: (symbol, info_dict, chart_dict)
    """
    try:
        t    = yf.Ticker(symbol)
        info = t.info or {}

        # ── 会社情報 ──
        sec_en   = info.get("sector") or ""
        sec_jp   = SECTOR_JP.get(sec_en, sec_en) if sec_en else "不明"
        name     = info.get("shortName") or info.get("longName") or symbol
        desc     = (info.get("longBusinessSummary") or "")[:500]
        industry = info.get("industry") or ""
        website  = info.get("website") or ""
        mktcap   = info.get("marketCap") or 0
        volume   = info.get("volume") or info.get("regularMarketVolume") or 0

        info_out = {
            "name": name, "sector": sec_jp, "sector_en": sec_en,
            "industry": industry, "description": desc,
            "website": website, "market_cap": mktcap, "volume": volume,
        }

        # ── 6ヶ月日足チャート ──
        hist  = t.history(period="6mo", interval="1d", auto_adjust=True)
        chart = None
        if not hist.empty:
            chart = {
                "dates":   [d.strftime("%Y-%m-%d") for d in hist.index],
                "closes":  [round(float(v), 2) if v == v else None for v in hist["Close"]],
                "volumes": [int(v) if v == v else None for v in hist["Volume"]],
            }

        return symbol, info_out, chart

    except Exception as e:
        print(f"    {symbol} 詳細取得失敗: {e}", file=sys.stderr)
        return symbol, {}, None


def enrich_gainers(gainers, max_workers=6):
    """並列で会社情報 + チャートを補完"""
    if not gainers:
        return gainers
    print(f"  詳細情報・チャート取得中（{len(gainers)}件, {max_workers}並列）...",
          file=sys.stderr)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_ticker_full, s["symbol"]): s["symbol"] for s in gainers}
        done = 0
        for fut in as_completed(futures):
            symbol, info, chart = fut.result()
            results[symbol] = (info, chart)
            done += 1
            name = info.get("name", symbol)
            sec  = info.get("sector", "")
            print(f"    [{done}/{len(gainers)}] {symbol}: {name} / {sec}", file=sys.stderr)

    for s in gainers:
        info, chart = results.get(s["symbol"], ({}, None))
        for k, v in info.items():
            if v:
                s[k] = v
        if chart:
            s["chart"] = chart

    return gainers


def aggregate_by_sector(gainers):
    sector_data = {}
    for s in gainers:
        sec = s.get("sector") or "不明"
        if sec not in sector_data:
            sector_data[sec] = {"count": 0, "symbols": [], "total_pct": 0.0, "avg_change_pct": 0.0}
        sector_data[sec]["count"] += 1
        sector_data[sec]["symbols"].append(s["symbol"])
        sector_data[sec]["total_pct"] += s.get("change_pct", 0.0)
    for sec in sector_data:
        n = sector_data[sec]["count"]
        sector_data[sec]["avg_change_pct"] = round(sector_data[sec]["total_pct"] / n, 2) if n else 0
        del sector_data[sec]["total_pct"]
    return dict(sorted(sector_data.items(), key=lambda x: -x[1]["count"]))


def main():
    print("[米国株] 取得開始...", file=sys.stderr)

    tickers = get_sp500_tickers()
    data    = fetch_price_data(tickers)
    gainers = calculate_top_gainers(data, top_n=20)
    print(f"[米国株] 上昇率上位 {len(gainers)}件 抽出", file=sys.stderr)

    if gainers:
        gainers = enrich_gainers(gainers)

    sector_analysis = aggregate_by_sector(gainers)

    output = {
        "updated_at":    datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_gainers": len(gainers),
        "gainers":       gainers,
        "sector_analysis": sector_analysis,
    }

    out_path = "data/us_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[米国株] 保存: {out_path}", file=sys.stderr)
    print(json.dumps({"status": "ok", "gainers": len(gainers)}))


if __name__ == "__main__":
    main()
