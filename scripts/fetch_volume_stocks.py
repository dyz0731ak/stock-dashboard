#!/usr/bin/env python3
"""
出来高急増ランキング取得スクリプト
- 日本株: kabutan.jp /warning/volume_ranking をスクレイピング後 yfinance で前日比算出
- 米国株: yfinance で S&P500 2日分の出来高を比較
- 事業説明は Claude API で日本語翻訳（キャッシュ利用）
"""

import yfinance as yf
import pandas as pd
import requests
import json
import datetime
import sys
import time
import re
import os
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# translate モジュールは同じ scripts/ ディレクトリにある
sys.path.insert(0, os.path.dirname(__file__))
from translate import load_cache, save_cache, enrich_with_translations, translate_industry
from safe_save import safe_save

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


# ──────────────────────────────────────────────
#  日本株 出来高急増
# ──────────────────────────────────────────────

def scrape_jp_volume_ranking(top_n: int = 60) -> list[dict]:
    """
    kabutan volume_ranking から上位 top_n 銘柄を取得。
    戻り値: [{ code, name, market, price, change_amount, change_pct, volume_today }, ...]
    """
    print("  kabutan 出来高ランキング取得中...", file=sys.stderr)
    results = []
    page = 1
    MAX_PAGES = 5

    while len(results) < top_n and page <= MAX_PAGES:
        url = f"https://kabutan.jp/warning/volume_ranking?page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", class_="stock_table")
            if not table:
                break
            rows = table.find_all("tr")[1:]
            if not rows:
                break

            for row in rows:
                tds = row.find_all("td")
                th  = row.find("th")
                if len(tds) < 9 or not th:
                    continue
                a_tag = tds[0].find("a")
                if not a_tag:
                    continue

                code    = a_tag.get_text(strip=True)
                name    = th.get_text(strip=True)
                market  = tds[1].get_text(strip=True).replace("東", "東").replace("名", "名")
                price_s = tds[4].get_text(strip=True).replace(",", "")
                chg_sp  = tds[6].find("span")
                chg_s   = chg_sp.get_text(strip=True).replace(",", "") if chg_sp else "0"
                pct_sp  = tds[7].find("span")
                pct_s   = pct_sp.get_text(strip=True) if pct_sp else "0"
                vol_s   = tds[8].get_text(strip=True).replace(",", "")

                try:
                    price     = float(price_s) if price_s else 0.0
                    change_a  = float(chg_s) if chg_s else 0.0
                    change_p  = float(pct_s) if pct_s else 0.0
                    vol_today = int(vol_s) if vol_s.isdigit() else 0
                except ValueError:
                    continue

                results.append({
                    "code": code, "name": name, "market": market,
                    "price": price, "change_amount": round(change_a, 2),
                    "change_pct": round(change_p, 2),
                    "volume_today": vol_today, "volume_yesterday": 0,
                    "volume_ratio": 0.0,
                    "sector": "", "industry": "", "industry_ja": "",
                    "description": None, "description_ja": None,
                    "website": None, "chart": None,
                })
                if len(results) >= top_n:
                    break

            page += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"  page {page} 取得エラー: {e}", file=sys.stderr)
            break

    print(f"  kabutan 出来高ランキング: {len(results)}件", file=sys.stderr)
    return results


def fetch_jp_yfinance_volume(stocks: list[dict]) -> list[dict]:
    """
    yfinance で各銘柄の前日出来高を取得し volume_ratio を計算。
    チャート・会社情報も取得。
    """
    if not stocks:
        return stocks

    codes = [s["code"] for s in stocks]
    tickers_yf = [f"{c}.T" for c in codes]

    print(f"  yfinance 出来高・チャート取得中（{len(codes)}件）...", file=sys.stderr)

    def fetch_one(symbol: str):
        try:
            t    = yf.Ticker(symbol)
            info = t.info or {}

            # 業種情報
            sec_en   = info.get("sector", "")
            sec_jp   = SECTOR_JP.get(sec_en, sec_en) if sec_en else "不明"
            industry = info.get("industry", "")
            desc     = (info.get("longBusinessSummary", "") or "")[:400]
            website  = info.get("website", "")

            # 5日分のデータから前日出来高を取得
            hist = t.history(period="5d", interval="1d", auto_adjust=True)
            vol_yesterday = 0
            chart = None
            if not hist.empty and len(hist) >= 2:
                vol_yesterday = int(hist["Volume"].iloc[-2])

            # 6ヶ月チャート
            hist6 = t.history(period="6mo", interval="1d", auto_adjust=True)
            if not hist6.empty:
                chart = {
                    "dates":   [d.strftime("%Y-%m-%d") for d in hist6.index],
                    "closes":  [round(float(v), 2) if v == v else None for v in hist6["Close"]],
                    "volumes": [int(v) if v == v else None for v in hist6["Volume"]],
                }

            return symbol, {
                "sector": sec_jp, "industry": industry, "description": desc,
                "website": website, "vol_yesterday": vol_yesterday, "chart": chart,
            }

        except Exception as e:
            print(f"    {symbol} 取得失敗: {e}", file=sys.stderr)
            return symbol, {}

    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_one, sym): sym for sym in tickers_yf}
        done = 0
        for fut in as_completed(futs):
            sym, data = fut.result()
            results[sym] = data
            done += 1
            if done % 10 == 0:
                print(f"    進捗 {done}/{len(tickers_yf)}", file=sys.stderr)

    for s in stocks:
        data = results.get(f"{s['code']}.T", {})
        if data.get("sector"):   s["sector"]   = data["sector"]
        if data.get("industry"): s["industry"] = data["industry"]
        if data.get("description"): s["description"] = data["description"]
        if data.get("website"):  s["website"]  = data["website"]
        if data.get("chart"):    s["chart"]    = data["chart"]
        vy = data.get("vol_yesterday", 0) or 0
        s["volume_yesterday"] = vy
        if vy > 0 and s["volume_today"] > 0:
            s["volume_ratio"] = round((s["volume_today"] / vy - 1) * 100, 1)
        else:
            s["volume_ratio"] = 0.0

    return stocks


def get_jp_volume_stocks(top_n: int = 20) -> list[dict]:
    """日本株 出来高急増 Top N を返す（volume_ratio 降順）"""
    print("[日本株] 出来高急増ランキング取得...", file=sys.stderr)
    stocks = scrape_jp_volume_ranking(top_n=60)
    stocks = fetch_jp_yfinance_volume(stocks)
    # volume_ratio で降順ソートして上位 top_n を返す
    stocks.sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)
    return stocks[:top_n]


# ──────────────────────────────────────────────
#  米国株 出来高急増
# ──────────────────────────────────────────────

def get_sp500_tickers_simple() -> list[str]:
    """Wikipedia から S&P500 構成銘柄を取得"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="constituents")
        if not table:
            raise ValueError("table not found")
        return [
            row.find_all("td")[0].get_text(strip=True).replace(".", "-")
            for row in table.find_all("tr")[1:]
            if row.find_all("td")
        ]
    except Exception as e:
        print(f"  S&P500 フォールバック: {e}", file=sys.stderr)
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
            "V","UNH","XOM","ORCL","MA","COST","HD","PG","JNJ","WMT",
            "ABBV","NFLX","BAC","AMD","CRM","CVX","KO","MRK","PEP","TMO",
        ]


def fetch_us_ticker_full(symbol: str):
    """yfinance で会社情報 + 6ヶ月チャートを取得"""
    try:
        t    = yf.Ticker(symbol)
        info = t.info or {}
        sec_en   = info.get("sector", "")
        sec_jp   = SECTOR_JP.get(sec_en, sec_en) if sec_en else "不明"
        name     = info.get("shortName") or info.get("longName") or symbol
        desc     = (info.get("longBusinessSummary", "") or "")[:400]
        industry = info.get("industry", "")
        website  = info.get("website", "")
        volume   = info.get("volume") or info.get("regularMarketVolume") or 0

        hist = t.history(period="6mo", interval="1d", auto_adjust=True)
        chart = None
        if not hist.empty:
            chart = {
                "dates":   [d.strftime("%Y-%m-%d") for d in hist.index],
                "closes":  [round(float(v), 2) if v == v else None for v in hist["Close"]],
                "volumes": [int(v) if v == v else None for v in hist["Volume"]],
            }

        return symbol, {
            "name": name, "sector": sec_jp, "sector_en": sec_en,
            "industry": industry, "description": desc,
            "website": website, "volume": volume, "chart": chart,
        }

    except Exception as e:
        print(f"    {symbol} 取得失敗: {e}", file=sys.stderr)
        return symbol, {}


def get_us_volume_stocks(top_n: int = 20) -> list[dict]:
    """米国株 出来高急増 Top N（前日比出来高増加率順）"""
    print("[米国株] 出来高急増ランキング取得...", file=sys.stderr)

    tickers = get_sp500_tickers_simple()
    print(f"  S&P500: {len(tickers)}銘柄 / 5日分ダウンロード中...", file=sys.stderr)

    try:
        data = yf.download(
            tickers, period="5d", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
    except Exception as e:
        print(f"  ダウンロードエラー: {e}", file=sys.stderr)
        return []

    if data is None or data.empty:
        return []

    try:
        vol = data["Volume"] if isinstance(data.columns, pd.MultiIndex) else data[["Volume"]]
        if len(vol) < 2:
            return []

        # 前日・当日の出来高を抽出（最後の2行）
        vol_yesterday = vol.iloc[-2].dropna()
        vol_today     = vol.iloc[-1].dropna()

        # 共通銘柄で比率計算
        common = vol_today.index.intersection(vol_yesterday.index)
        vt = vol_today[common]
        vy = vol_yesterday[common]

        # ゼロ除算を防ぐ
        mask = (vy > 1000) & (vt > 1000)
        ratio = ((vt[mask] / vy[mask]) - 1) * 100
        top_tickers = ratio.nlargest(top_n * 3).index.tolist()  # 余裕を持って取得

    except Exception as e:
        print(f"  出来高比率計算エラー: {e}", file=sys.stderr)
        return []

    # 価格データも取得
    close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]]
    prev_close = close.iloc[-2]
    curr_close = close.iloc[-1]

    # 初期リスト（price/change を含む）
    candidates = []
    for ticker in top_tickers:
        price = float(curr_close.get(ticker, 0) or 0)
        prev  = float(prev_close.get(ticker, 0) or 0)
        if price <= 0:
            continue
        vt_val = float(vol_today.get(ticker, 0) or 0)
        vy_val = float(vol_yesterday.get(ticker, 0) or 0)
        vol_r  = float(ratio.get(ticker, 0))
        candidates.append({
            "symbol": ticker,
            "price": round(price, 2),
            "prev_close": round(prev, 2),
            "change": round(price - prev, 2),
            "change_pct": round((price - prev) / prev * 100, 2) if prev else 0,
            "volume_today": int(vt_val),
            "volume_yesterday": int(vy_val),
            "volume_ratio": round(vol_r, 1),
            "name": "", "sector": "", "sector_en": "", "industry": "", "industry_ja": "",
            "description": None, "description_ja": None, "website": None, "chart": None,
        })

    # 詳細情報取得（top_n × 1.5 件まで）
    enrich_count = min(len(candidates), top_n + 5)
    to_enrich = candidates[:enrich_count]
    print(f"  詳細情報取得中（{len(to_enrich)}件）...", file=sys.stderr)

    details = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_us_ticker_full, s["symbol"]): s["symbol"] for s in to_enrich}
        done = 0
        for fut in as_completed(futs):
            sym, info = fut.result()
            details[sym] = info
            done += 1
            print(f"    [{done}/{len(to_enrich)}] {sym}: {info.get('name','')} / {info.get('sector','')}",
                  file=sys.stderr)

    for s in to_enrich:
        d = details.get(s["symbol"], {})
        for k in ["name","sector","sector_en","industry","description","website","chart"]:
            if d.get(k):
                s[k] = d[k]

    # volume_ratio 降順で最終 top_n
    to_enrich.sort(key=lambda x: x["volume_ratio"], reverse=True)
    return to_enrich[:top_n]


# ──────────────────────────────────────────────
#  main
# ──────────────────────────────────────────────

def main():
    print("[出来高急増] 取得開始...", file=sys.stderr)

    jp_stocks = get_jp_volume_stocks(top_n=20)
    us_stocks = get_us_volume_stocks(top_n=20)

    # ── 翻訳 ──
    print("[翻訳] 事業説明を日本語化中...", file=sys.stderr)
    cache = load_cache()

    all_stocks = jp_stocks + us_stocks
    all_stocks, cache = enrich_with_translations(all_stocks, cache)

    save_cache(cache)
    print(f"  翻訳キャッシュ保存: {len(cache)}件", file=sys.stderr)

    output = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "jp_count":   len(jp_stocks),
        "us_count":   len(us_stocks),
        "jp_stocks":  jp_stocks,
        "us_stocks":  us_stocks,
    }

    # 取得失敗（0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        "data/volume_stocks.json",
        output,
        lambda d: len(d.get("jp_stocks", [])) + len(d.get("us_stocks", [])),
        label="出来高急増",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "jp": len(jp_stocks),
        "us": len(us_stocks),
    }))


if __name__ == "__main__":
    main()
