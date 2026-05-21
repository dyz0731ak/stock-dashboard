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
import os
import time
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

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
        "AMC": "引け後",
        "BMO": "寄り前",
        "TAS": "時刻未定",
        "TNS": "発表なし",
    }
    return mapping.get(code.upper(), code)


# ─────────────────────────────────────────────────
# 経済指標名の日本語マッピング
# ─────────────────────────────────────────────────

EVENT_NAME_JP: dict[str, str] = {
    # 米国 - 住宅
    "Existing Home Sales":              "中古住宅販売件数",
    "Exist. Home Sales % Chg":          "中古住宅販売 前月比",
    "New Home Sales":                   "新築住宅販売件数",
    "New Home Sales MoM":               "新築住宅販売 前月比",
    "Housing Starts":                   "住宅着工件数",
    "Building Permits":                 "建設許可件数",
    "Pending Home Sales":               "住宅販売保留件数",
    "Pending Home Sales MoM":           "住宅販売保留 前月比",
    "Case-Shiller Home Price Index":    "ケース・シラー住宅価格指数",
    "FHFA House Price Index":           "FHFA住宅価格指数",
    "FHFA House Price Index MoM":       "FHFA住宅価格 前月比",
    "FHFA House Price Index YoY":       "FHFA住宅価格 前年比",
    "MBA Mortgage Applications":        "MBA住宅ローン申請件数",
    "MBA Mortgage Market Index":        "MBA住宅ローン市場指数",
    "Mortgage Market Index":            "住宅ローン市場指数",

    # 米国 - 雇用
    "Nonfarm Payrolls":                 "非農業部門雇用者数",
    "Non-Farm Payrolls":                "非農業部門雇用者数",
    "NFP":                              "非農業部門雇用者数",
    "Unemployment Rate":                "失業率",
    "Initial Jobless Claims":           "新規失業保険申請件数",
    "Continuing Jobless Claims":        "継続失業保険申請件数",
    "Jobless Claims 4-Wk Avg":         "失業保険申請 4週平均",
    "Average Hourly Earnings MoM":      "平均時給 前月比",
    "Average Hourly Earnings YoY":      "平均時給 前年比",
    "Average Weekly Hours":             "平均週労働時間",
    "Labor Force Participation Rate":   "労働参加率",
    "Employment Trends":                "雇用トレンド指数",
    "Employment Trends*":               "雇用トレンド指数",
    "ADP Employment Change":            "ADP雇用者数変化",
    "ADP Nonfarm Employment Change":    "ADP非農業部門雇用変化",
    "JOLTS Job Openings":               "JOLTS求人件数",
    "JOLTS Quits Rate":                 "JOLTS離職率",
    "Challenger Job Cuts":              "チャレンジャー人員削減数",
    "Employment Cost Index":            "雇用コスト指数",

    # 米国 - 物価・インフレ
    "Consumer Price Index":             "消費者物価指数（CPI）",
    "CPI":                              "消費者物価指数（CPI）",
    "CPI MoM":                          "CPI 前月比",
    "CPI YoY":                          "CPI 前年比",
    "Core CPI MoM":                     "コアCPI 前月比",
    "Core CPI YoY":                     "コアCPI 前年比",
    "CPI ex Food & Energy MoM":         "コアCPI 前月比",
    "CPI ex Food & Energy YoY":         "コアCPI 前年比",
    "Producer Price Index":             "生産者物価指数（PPI）",
    "PPI":                              "生産者物価指数（PPI）",
    "PPI MoM":                          "PPI 前月比",
    "PPI YoY":                          "PPI 前年比",
    "Core PPI MoM":                     "コアPPI 前月比",
    "Core PPI YoY":                     "コアPPI 前年比",
    "PCE Price Index":                  "PCE物価指数",
    "PCE Price Index MoM":              "PCE物価指数 前月比",
    "PCE Price Index YoY":              "PCE物価指数 前年比",
    "Core PCE Price Index":             "コアPCE物価指数",
    "Core PCE Price Index MoM":         "コアPCE物価指数 前月比",
    "Core PCE Price Index YoY":         "コアPCE物価指数 前年比",
    "Import Price Index":               "輸入物価指数",
    "Export Price Index":               "輸出物価指数",
    "Wholesale Inventories":            "卸売在庫",

    # 米国 - GDP・成長
    "GDP":                              "GDP（国内総生産）",
    "Gross Domestic Product":           "GDP（国内総生産）",
    "GDP QoQ":                          "GDP 前期比",
    "GDP Growth Rate":                  "GDP成長率",
    "GDP Price Index":                  "GDPデフレーター",
    "Real GDP":                         "実質GDP",
    "Personal Spending":                "個人消費支出",
    "Personal Income":                  "個人所得",
    "Personal Consumption Expenditures":"個人消費支出",

    # 米国 - 金融政策
    "FOMC Meeting":                     "FOMC会合",
    "FOMC Statement":                   "FOMC声明",
    "FOMC Minutes":                     "FOMC議事録",
    "Fed Funds Rate":                   "FF金利",
    "Federal Funds Rate":               "FF金利（政策金利）",
    "Interest Rate Decision":           "政策金利決定",
    "Fed Interest Rate Decision":       "FRB政策金利決定",
    "Fed Balance Sheet":                "FRBバランスシート",
    "Fed Chair Powell Speech":          "パウエルFRB議長 講演",
    "Treasury Budget":                  "財務省財政収支",

    # 米国 - 消費・小売
    "Retail Sales MoM":                 "小売売上高 前月比",
    "Retail Sales YoY":                 "小売売上高 前年比",
    "Core Retail Sales MoM":            "コア小売売上高 前月比",
    "Retail Sales Ex Autos":            "小売売上高（自動車除く）",
    "Consumer Confidence":              "消費者信頼感指数（CB）",
    "Consumer Confidence Index":        "消費者信頼感指数",
    "Michigan Consumer Sentiment":      "ミシガン大消費者信頼感",
    "Michigan Inflation Expectations":  "ミシガン大インフレ期待",
    "Consumer Sentiment":               "消費者信頼感",

    # 米国 - 製造業・生産
    "Industrial Production MoM":        "鉱工業生産 前月比",
    "Industrial Production YoY":        "鉱工業生産 前年比",
    "Capacity Utilization":             "設備稼働率",
    "Durable Goods Orders":             "耐久財受注",
    "Durable Goods Orders MoM":         "耐久財受注 前月比",
    "Core Durable Goods Orders MoM":    "コア耐久財受注 前月比",
    "Factory Orders":                   "製造業受注",
    "ISM Manufacturing PMI":            "ISM製造業景況指数",
    "ISM Manufacturing":                "ISM製造業景況指数",
    "ISM Services PMI":                 "ISMサービス業景況指数",
    "ISM Non-Manufacturing PMI":        "ISM非製造業景況指数",
    "S&P Global Manufacturing PMI":     "S&Pグローバル製造業PMI",
    "S&P Global Services PMI":          "S&Pグローバルサービス業PMI",
    "S&P Global Composite PMI":         "S&Pグローバル総合PMI",
    "Philadelphia Fed Manufacturing":   "フィラデルフィア連銀製造業指数",
    "Empire State Manufacturing":       "NY連銀製造業指数",
    "Richmond Fed Manufacturing":       "リッチモンド連銀製造業指数",
    "Chicago PMI":                      "シカゴ購買担当者景気指数",
    "Dallas Fed Manufacturing":         "ダラス連銀製造業活動指数",

    # 米国 - 国際収支・貿易
    "Trade Balance":                    "貿易収支",
    "Current Account":                  "経常収支",
    "Current Account Balance":          "経常収支",
    "Goods Trade Balance":              "財貿易収支",

    # 米国 - その他指標
    "Business Inventories":             "企業在庫",
    "Construction Spending":            "建設支出",
    "Crude Oil Inventories":            "原油在庫",
    "EIA Crude Oil Stocks Change":      "EIA原油在庫変化",
    "Natural Gas Storage":              "天然ガス在庫",
    "Baker Hughes Oil Rig Count":       "採掘リグ稼働数",
    "Leading Economic Indicators":      "景気先行指数",
    "Leading Indicators":               "景気先行指数",
    "Beige Book":                       "地区連銀経済報告（ベージュブック）",
    "Quarterly Services Survey":        "四半期サービス業調査",

    # 日本 - 金融政策
    "Bank of Japan Rate Decision":      "日銀政策金利決定",
    "BOJ Rate Decision":                "日銀政策金利決定",
    "BOJ Interest Rate Decision":       "日銀政策金利決定",
    "BOJ Monetary Policy Statement":    "日銀金融政策声明",
    "BOJ Policy Rate":                  "日銀政策金利",
    "BOJ Meeting Minutes":              "日銀会合議事録",
    "BOJ Outlook Report":               "日銀展望レポート",
    "BOJ Governor Speech":              "日銀総裁 発言",

    # 日本 - 物価・消費
    "Japan CPI":                        "日本 消費者物価指数",
    "Japan CPI YoY":                    "日本 CPI 前年比",
    "Japan CPI MoM":                    "日本 CPI 前月比",
    "Japan Core CPI YoY":               "日本 コアCPI 前年比",
    "Tokyo CPI":                        "東京都 消費者物価指数",
    "Tokyo CPI YoY":                    "東京都 CPI 前年比",
    "All Household Spending MM":        "家計支出（月次）",
    "All Household Spending YY":        "家計支出（年次）",
    "Household Spending MoM":           "家計支出 前月比",
    "Household Spending YoY":           "家計支出 前年比",
    "Retail Sales MoM":                 "小売売上高 前月比",
    "Retail Sales YoY":                 "小売売上高 前年比",

    # 日本 - GDP・生産
    "Japan GDP":                        "日本 GDP",
    "Japan GDP QoQ":                    "日本 GDP 前期比",
    "Japan GDP YoY":                    "日本 GDP 前年比",
    "Industrial Production MoM":        "鉱工業生産 前月比",
    "Industrial Production YoY":        "鉱工業生産 前年比",
    "Manufacturing PMI":                "製造業PMI",
    "Services PMI":                     "サービス業PMI",
    "Composite PMI":                    "総合PMI",
    "Jibun Bank Manufacturing PMI":     "じぶん銀行製造業PMI",
    "Jibun Bank Services PMI":          "じぶん銀行サービス業PMI",
    "Jibun Bank Composite PMI":         "じぶん銀行総合PMI",

    # 日本 - 雇用・貿易
    "Japan Unemployment Rate":          "日本 失業率",
    "Jobs/Applicants Ratio":            "有効求人倍率",
    "Foreign Reserves":                 "外貨準備高",
    "Japan Trade Balance":              "日本 貿易収支",
    "Trade Balance":                    "貿易収支",
    "Current Account":                  "経常収支",
    "Tankan Large Manufacturers Index": "日銀短観 大企業製造業",
    "Tankan Survey":                    "日銀短観",
    "Machinery Orders":                 "機械受注",
    "Machine Tool Orders":              "工作機械受注",
    "Housing Starts":                   "新設住宅着工件数",
    "Consumer Confidence":              "消費者信頼感指数",
    "Leading Index":                    "景気先行指数（CI）",
    "Coincident Index":                 "景気一致指数",
}


def translate_event_name(name: str) -> str:
    """経済指標名を日本語に変換。マッピングにない場合は元の名前を返す。"""
    cleaned = name.rstrip("*").strip()
    return EVENT_NAME_JP.get(cleaned, EVENT_NAME_JP.get(name.strip(), name))


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
                event_name_ja = translate_event_name(event_name)

                day_results.append({
                    "event": event_name,
                    "event_ja": event_name_ja,
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

    # 3ソース全滅（合計0件）で既存の良いデータを破壊しないようガード
    saved = safe_save(
        "data/events.json",
        output,
        lambda d: (len(d.get("jp_earnings", []))
                   + len(d.get("us_earnings", []))
                   + len(d.get("economic", []))),
        label="イベント",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "jp_earnings": len(jp_earnings),
        "us_earnings": len(us_earnings),
        "economic":    len(eco_filtered),
    }))


if __name__ == "__main__":
    main()
