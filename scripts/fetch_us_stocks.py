#!/usr/bin/env python3
"""
yfinance を使って S&P500 構成銘柄から当日上昇率上位20銘柄を取得

手順:
  1. Wikipedia から S&P500 構成銘柄リストを取得
  2. yfinance で一括ダウンロード（1d OHLCV）
  3. 変化率を計算して上位20件を抽出
  4. セクター情報は yfinance Ticker オブジェクトから取得
"""

import yfinance as yf
import pandas as pd
import json
import datetime
import sys
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# セクター名 英語→日本語
SECTOR_JP = {
    "Technology":               "テクノロジー",
    "Health Care":              "ヘルスケア",
    "Healthcare":               "ヘルスケア",
    "Financials":               "金融",
    "Financial Services":       "金融サービス",
    "Consumer Discretionary":   "一般消費財",
    "Consumer Staples":         "生活必需品",
    "Consumer Defensive":       "生活必需品",
    "Consumer Cyclical":        "一般消費財",
    "Industrials":              "資本財・サービス",
    "Energy":                   "エネルギー",
    "Materials":                "素材",
    "Basic Materials":          "基礎素材",
    "Real Estate":              "不動産",
    "Communication Services":   "通信サービス",
    "Utilities":                "公共事業",
}


def get_sp500_tickers():
    """Wikipedia から S&P500 構成銘柄リストを取得"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    print("  S&P500 銘柄リストを Wikipedia から取得中...", file=sys.stderr)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="constituents")
        if not table:
            raise ValueError("constituents テーブルが見つかりません")

        rows = table.find_all("tr")[1:]
        tickers = []
        for row in rows:
            cols = row.find_all("td")
            if cols:
                ticker = cols[0].get_text(strip=True).replace(".", "-")
                tickers.append(ticker)

        print(f"  S&P500 銘柄数: {len(tickers)}", file=sys.stderr)
        return tickers
    except Exception as e:
        print(f"  S&P500 リスト取得失敗: {e}", file=sys.stderr)
        # フォールバック: 主要銘柄リスト
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
            "LLY","V","UNH","XOM","ORCL","MA","COST","HD","PG","JNJ",
            "WMT","ABBV","NFLX","BAC","AMD","CRM","CVX","KO","MRK","PEP",
            "TMO","ACN","LIN","MCD","CSCO","ABT","NKE","DHR","TXN","QCOM",
            "GE","NEE","INTU","IBM","RTX","AMGN","AMAT","PM","SPGI","MDT",
            "HON","ISRG","GS","T","BKNG","VRTX","CAT","LOW","NOW","SYK",
            "PLD","DE","GILD","AXP","ELV","C","ADI","ETN","MU","ZTS",
            "SCHW","BSX","BX","REGN","MDLZ","CB","MMC","CI","BDX","SO",
            "DUK","AON","SLB","ITW","TJX","WM","CME","PH","USB","APH",
        ]


def fetch_price_data(tickers, period="2d"):
    """
    yfinance で価格データを一括取得
    period='2d' で前日と当日の終値を取得
    """
    print(f"  yfinance で価格データ取得中（{len(tickers)} 銘柄）...", file=sys.stderr)

    try:
        # yfinance bulk download
        data = yf.download(
            tickers,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        return data
    except Exception as e:
        print(f"  価格データ取得エラー: {e}", file=sys.stderr)
        return None


def calculate_gainers(data, tickers, top_n=20):
    """
    終値の前日比を計算して上昇率上位 top_n 件を返す
    """
    if data is None or data.empty:
        return []

    try:
        # Close 列を取得
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"]
        else:
            close = data[["Close"]]

        # 2日分あれば前日比計算、1日のみなら intraday
        if len(close) >= 2:
            prev_close = close.iloc[-2]
            curr_close = close.iloc[-1]
        else:
            curr_close = close.iloc[-1]
            prev_close = curr_close

        pct_change = ((curr_close - prev_close) / prev_close * 100).dropna()
        change_amount = (curr_close - prev_close).dropna()

        # 上昇率 TOP N を抽出
        top_gainers = pct_change.nlargest(top_n)

        results = []
        for ticker in top_gainers.index:
            pct = float(pct_change.get(ticker, 0))
            chg = float(change_amount.get(ticker, 0))
            price = float(curr_close.get(ticker, 0))
            prev  = float(prev_close.get(ticker, 0))

            if price <= 0:
                continue

            results.append({
                "symbol": ticker,
                "price": round(price, 2),
                "prev_close": round(prev, 2),
                "change": round(chg, 2),
                "change_pct": round(pct, 2),
                "name": "",       # 後で補完
                "sector": "",     # 後で補完
                "sector_en": "",
                "volume": 0,
                "market_cap": 0,
            })

        return results

    except Exception as e:
        print(f"  上昇率計算エラー: {e}", file=sys.stderr)
        return []


def enrich_ticker_info(stocks):
    """
    yfinance Ticker オブジェクトから銘柄名・セクター・時価総額・出来高を取得
    """
    print(f"  銘柄詳細情報を取得中（{len(stocks)} 件）...", file=sys.stderr)
    enriched = []

    for i, s in enumerate(stocks):
        ticker = s["symbol"]
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            name     = info.get("shortName") or info.get("longName") or ticker
            sec_en   = info.get("sector") or ""
            sector   = SECTOR_JP.get(sec_en, sec_en) if sec_en else "不明"
            mktcap   = info.get("marketCap") or 0
            volume   = info.get("volume") or info.get("regularMarketVolume") or 0

            s["name"]       = name
            s["sector"]     = sector
            s["sector_en"]  = sec_en
            s["market_cap"] = mktcap
            s["volume"]     = volume

            print(f"    [{i+1}/{len(stocks)}] {ticker}: {name} / {sector}", file=sys.stderr)
        except Exception as e:
            print(f"    [{i+1}/{len(stocks)}] {ticker} 詳細取得失敗: {e}", file=sys.stderr)
            s["name"]   = s["name"] or ticker
            s["sector"] = s["sector"] or "不明"

        enriched.append(s)
        time.sleep(0.1)   # API レート制限回避

    return enriched


def aggregate_by_sector(stocks):
    """セクター別集計"""
    sector_data = {}
    for s in stocks:
        sector = s.get("sector") or "不明"
        if sector not in sector_data:
            sector_data[sector] = {
                "count": 0,
                "symbols": [],
                "total_pct": 0.0,
                "avg_change_pct": 0.0,
            }
        sector_data[sector]["count"] += 1
        sector_data[sector]["symbols"].append(s["symbol"])
        sector_data[sector]["total_pct"] += s.get("change_pct", 0.0)

    for sec in sector_data:
        n = sector_data[sec]["count"]
        if n > 0:
            sector_data[sec]["avg_change_pct"] = round(
                sector_data[sec]["total_pct"] / n, 2
            )
        del sector_data[sec]["total_pct"]

    return dict(
        sorted(sector_data.items(), key=lambda x: x[1]["count"], reverse=True)
    )


def main():
    print("[米国株] 取得開始...", file=sys.stderr)

    # 1. S&P500 銘柄リスト取得
    tickers = get_sp500_tickers()

    # 2. 価格データ一括取得
    data = fetch_price_data(tickers, period="2d")

    # 3. 上昇率上位20件を抽出
    gainers = calculate_gainers(data, tickers, top_n=20)
    print(f"[米国株] 上昇率上位 {len(gainers)} 件を抽出", file=sys.stderr)

    if not gainers:
        print("[米国株] 警告: データが0件です（市場休場の可能性）", file=sys.stderr)

    # 4. 銘柄名・セクター情報を補完
    if gainers:
        gainers = enrich_ticker_info(gainers)

    # 5. セクター集計
    sector_analysis = aggregate_by_sector(gainers)

    output = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_gainers": len(gainers),
        "gainers": gainers,
        "sector_analysis": sector_analysis,
    }

    out_path = "data/us_stocks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[米国株] 保存完了: {out_path}", file=sys.stderr)
    print(json.dumps({"status": "ok", "gainers": len(gainers)}))


if __name__ == "__main__":
    main()
