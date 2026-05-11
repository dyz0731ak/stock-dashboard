#!/usr/bin/env python3
"""
本日の市場イベントカレンダー取得スクリプト（APIキー不要・完全無料）

データソース:
  - 日本株決算予定: kabutan.jp /warning/?mode=5_1（翌営業日）
  - 米国株決算予定: Yahoo Finance /calendar/earnings
  - 経済指標スケジュール: Yahoo Finance /calendar/economic
  - 全て JST（UTC+9）で出力

出力: data/events.json
"""

import requests
import json
import datetime
import re
import sys
import time
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

JST = datetime.timezone(datetime.timedelta(hours=9))
UTC = datetime.timezone.utc


# ─────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────

def utc_str_to_jst(time_str: str, base_date: datetime.date) -> str:
    """
    "5:00 AM UTC" → "14:00 JST" に変換。
    パース失敗時は元の文字列を返す。
    """
    if not time_str or time_str.strip() in ("-", ""):
        return ""
    s = time_str.strip().upper().replace(" UTC", "").replace("UTC", "")
    try:
        t = datetime.datetime.strptime(s, "%I:%M %p")
        dt_utc = datetime.datetime(
            base_date.year, base_date.month, base_date.day,
            t.hour, t.minute, tzinfo=UTC
        )
        dt_jst = dt_utc.astimezone(JST)
        return dt_jst.strftime("%H:%M")
    except Exception:
        return time_str.strip()


def earnings_time_to_jst_label(code: str) -> str:
    """
    AMC=After Market Close / BMO=Before Market Open / TAS=Time As Scheduled
    → JST での目安ラベルに変換
    """
    mapping = {
        "AMC": "引け後 (翌朝)",   # ~5:00 AM UTC → 14:00 JST
        "BMO": "寄り前",          # ~11:30 AM UTC → 20:30 JST (前日夜)
        "TAS": "時刻調整中",
        "TNS": "発表なし",
    }
    return mapping.get(code.upper(), code)


# 経済指標の重要度判定キーワード
HIGH_KEYWORDS = [
    "federal funds rate", "fomc", "interest rate decision",
    "nonfarm payroll", "non-farm payroll", "nfp",
    "consumer price index", " cpi ",
    "gross domestic product", " gdp",
    "unemployment rate",
    "bank of japan", " boj", "boj rate",
    "monetary policy",
    "retail sales",        # US retail sales は high
    "federal reserve",
    "jobs report",
]
MED_KEYWORDS = [
    "producer price index", " ppi",
    "industrial production",
    "durable goods",
    "ism manufacturing", "ism services",
    "housing starts", "existing home sales",
    "trade balance",
    "current account",
    "consumer confidence",
    "inflation",
    "employment change",
]

TARGET_COUNTRIES = {"US", "United States", "JP", "Japan"}

def classify_importance(event_name: str, country: str) -> str:
    name_lower = event_name.lower()
    for kw in HIGH_KEYWORDS:
        if kw in name_lower:
            return "high"
    for kw in MED_KEYWORDS:
        if kw in name_lower:
            return "medium"
    return "low"


# ─────────────────────────────────────────────────
# 日本株 決算予定（kabutan）
# ─────────────────────────────────────────────────

def fetch_jp_earnings(max_pages: int = 3) -> list[dict]:
    """
    kabutan mode=5_1: 翌営業日の決算発表予定銘柄を取得。
    max_pages ページ分取得（15件/ページ）。
    """
    print("  [JP決算] kabutan mode=5_1 取得中...", file=sys.stderr)
    results = []

    for page in range(1, max_pages + 1):
        url = (f"https://kabutan.jp/warning/?mode=5_1"
               f"&market=0&capitalization=-1&dispmode=normal&page={page}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")

            # 日付をヘッダーから取得
            if page == 1:
                h1 = soup.find("h1")
                date_str = ""
                if h1:
                    m = re.search(r"(\d{2})月(\d{2})日", h1.get_text())
                    if m:
                        now = datetime.datetime.now(JST)
                        date_str = f"{now.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

            table = soup.find("table", class_="stock_table")
            if not table:
                break
            rows = table.find_all("tr")[1:]
            if not rows:
                break

            for row in rows:
                tds = row.find_all("td")
                th  = row.find("th")
                if len(tds) < 7 or not th:
                    continue
                a_tag = tds[0].find("a")
                if not a_tag:
                    continue

                code    = a_tag.get_text(strip=True)
                name    = th.get_text(strip=True)
                market  = tds[1].get_text(strip=True)
                price_s = tds[4].get_text(strip=True).replace(",", "")
                quarter = tds[6].get_text(strip=True) if len(tds) > 6 else ""

                try:
                    price = float(price_s) if price_s else None
                except ValueError:
                    price = None

                results.append({
                    "code": code, "name": name, "market": market,
                    "price": price, "quarter": quarter,
                    "date": date_str,
                    "time_jst": "",   # kabutan はリリース時刻を掲載しない
                    "country": "JP",
                })

            time.sleep(0.2)

        except Exception as e:
            print(f"  [JP決算] page {page} エラー: {e}", file=sys.stderr)
            break

    print(f"  [JP決算] {len(results)}件取得", file=sys.stderr)
    return results


# ─────────────────────────────────────────────────
# 米国株 決算予定（Yahoo Finance）
# ─────────────────────────────────────────────────

def fetch_us_earnings(dates: list[datetime.date]) -> list[dict]:
    """
    Yahoo Finance /calendar/earnings から指定日の米国株決算予定を取得。
    """
    print(f"  [US決算] Yahoo Finance 取得中（{len(dates)}日分）...", file=sys.stderr)
    results = []

    for day in dates:
        day_str = day.strftime("%Y-%m-%d")
        url = f"https://finance.yahoo.com/calendar/earnings?day={day_str}"
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                continue

            rows = table.find_all("tr")[1:]  # skip header
            for row in rows:
                cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                if len(cols) < 4:
                    continue

                symbol       = cols[0]
                company      = cols[1]
                call_time    = cols[3] if len(cols) > 3 else ""
                eps_estimate = cols[4] if len(cols) > 4 else ""
                reported_eps = cols[5] if len(cols) > 5 else ""

                time_label = earnings_time_to_jst_label(call_time)

                results.append({
                    "symbol": symbol, "name": company,
                    "date": day_str,
                    "call_time": call_time,
                    "time_jst_label": time_label,
                    "eps_estimate": eps_estimate,
                    "reported_eps": reported_eps if reported_eps not in ("-", "") else None,
                    "country": "US",
                })

            time.sleep(0.3)
            print(f"    {day_str}: {len(rows)}件", file=sys.stderr)

        except Exception as e:
            print(f"  [US決算] {day_str} エラー: {e}", file=sys.stderr)

    print(f"  [US決算] 合計 {len(results)}件取得", file=sys.stderr)
    return results


# ─────────────────────────────────────────────────
# 経済指標カレンダー（Yahoo Finance）
# ─────────────────────────────────────────────────

def fetch_economic_calendar(dates: list[datetime.date]) -> list[dict]:
    """
    Yahoo Finance /calendar/economic から経済指標スケジュールを取得。
    US・JP のみフィルタリングし、JST 時刻に変換。
    """
    print(f"  [経済指標] Yahoo Finance 取得中（{len(dates)}日分）...", file=sys.stderr)
    results = []

    COUNTRY_MAP = {
        "US": "🇺🇸 米国", "United States": "🇺🇸 米国",
        "JP": "🇯🇵 日本", "Japan": "🇯🇵 日本",
    }

    for day in dates:
        day_str = day.strftime("%Y-%m-%d")
        url = f"https://finance.yahoo.com/calendar/economic?day={day_str}"
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table")
            if not table:
                continue

            rows = table.find_all("tr")[1:]
            day_results = []
            for row in rows:
                cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                if len(cols) < 3:
                    continue

                event_name   = cols[0]
                country_code = cols[1] if len(cols) > 1 else ""
                time_utc     = cols[2] if len(cols) > 2 else ""
                for_period   = cols[3] if len(cols) > 3 else ""
                actual       = cols[4] if len(cols) > 4 else ""
                forecast     = cols[5] if len(cols) > 5 else ""
                prior        = cols[6] if len(cols) > 6 else ""

                # US・JP のみ
                if country_code not in COUNTRY_MAP:
                    continue

                time_jst = utc_str_to_jst(time_utc, day)
                importance = classify_importance(event_name, country_code)
                country_label = COUNTRY_MAP.get(country_code, country_code)

                day_results.append({
                    "event": event_name,
                    "country": country_code,
                    "country_label": country_label,
                    "time_utc": time_utc,
                    "time_jst": time_jst,
                    "date": day_str,
                    "for_period": for_period,
                    "actual": actual if actual not in ("-", "") else None,
                    "forecast": forecast if forecast not in ("-", "") else None,
                    "prior": prior if prior not in ("-", "") else None,
                    "importance": importance,
                })

            # 重要度順にソート
            order = {"high": 0, "medium": 1, "low": 2}
            day_results.sort(key=lambda x: (order.get(x["importance"], 9), x["time_jst"] or "99:99"))
            results.extend(day_results)

            print(f"    {day_str}: US/JP {len(day_results)}件", file=sys.stderr)
            time.sleep(0.3)

        except Exception as e:
            print(f"  [経済指標] {day_str} エラー: {e}", file=sys.stderr)

    print(f"  [経済指標] 合計 {len(results)}件取得", file=sys.stderr)
    return results


# ─────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────

def next_business_days(n: int) -> list[datetime.date]:
    """今日を含む直近 n 営業日（土日を除く）を返す"""
    result = []
    d = datetime.date.today()
    while len(result) < n:
        if d.weekday() < 5:   # 0=Mon … 4=Fri
            result.append(d)
        d += datetime.timedelta(days=1)
    return result


def main():
    print("[イベント] 取得開始...", file=sys.stderr)
    now_jst = datetime.datetime.now(JST)
    days = next_business_days(2)   # 今日 + 翌営業日
    today     = days[0]
    tomorrow  = days[1] if len(days) > 1 else today

    print(f"  対象日: {today} (今日), {tomorrow} (翌営業日)", file=sys.stderr)

    # ── 各データ取得 ──
    jp_earnings  = fetch_jp_earnings(max_pages=3)    # 翌日 ~45件
    us_earnings  = fetch_us_earnings([today, tomorrow])
    economic     = fetch_economic_calendar([today, tomorrow])

    # ── 経済指標の高重要度イベントのみ抽出（low は除外してファイルサイズ削減）
    eco_filtered = [e for e in economic if e["importance"] in ("high", "medium")]
    # low も念のため保持するが最大20件
    eco_low = [e for e in economic if e["importance"] == "low"][:20]

    output = {
        "updated_at":   now_jst.isoformat(),
        "target_today":    today.isoformat(),
        "target_tomorrow": tomorrow.isoformat(),
        "jp_earnings":  jp_earnings,
        "us_earnings":  us_earnings,
        "economic":     eco_filtered + eco_low,
        "summary": {
            "jp_earnings_count": len(jp_earnings),
            "us_earnings_count": len(us_earnings),
            "economic_count":    len(eco_filtered),
        },
    }

    out_path = "data/events.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[イベント] 保存: {out_path}", file=sys.stderr)
    print(json.dumps({
        "status": "ok",
        "jp_earnings": len(jp_earnings),
        "us_earnings": len(us_earnings),
        "economic":    len(eco_filtered),
    }))


if __name__ == "__main__":
    main()
