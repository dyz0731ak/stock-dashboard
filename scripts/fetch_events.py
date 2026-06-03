#!/usr/bin/env python3
"""
本日の市場イベントカレンダー取得スクリプト（APIキー不要・完全無料）

データソース:
  - 日本株決算予定: kabutan.jp /warning/?mode=5_1（翌営業日）
  - 米国株決算予定: Yahoo Finance /calendar/earnings
  - 経済指標スケジュール: ForexFactory 週次フィード（nfs.faireconomy.media）
  - 全て JST（UTC+9）で出力

出力: data/events.json
"""

from __future__ import annotations

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


TARGET_COUNTRIES = {"US", "United States", "JP", "Japan"}

# ─────────────────────────────────────────────────
# 重要経済指標ホワイトリスト（投資判断に効くものだけを厳選）
#
#   match     : Yahoo の英語イベント名に対する小文字部分一致キーワード
#   country   : "US" / "JP"（その国のイベントのみに適用）
#   ja        : 表示用の日本語名
#   stars     : 重要度 1〜5（★の数）
#   good_when : "high"   … 予想より高い＝市場にポジティブ（株高要因）
#               "low"    … 予想より低い＝市場にポジティブ（株高要因）
#               "neutral"… 数値の上下では強弱を判定しない（金融政策・発言など）
#   memo      : 市場への影響メモ（静的・AI不使用）
#
# 先に列挙したものが優先マッチ。長い・具体的なキーワードを上に置くこと。
# ─────────────────────────────────────────────────
IMPORTANT_INDICATORS: list[dict] = [
    # ── 米国：金融政策 ──
    {"match": ["fomc minutes", "fomc meeting minutes", "meeting minutes"], "country": "US", "ja": "FOMC議事要旨", "stars": 4, "good_when": "neutral",
     "memo": "FRBの政策スタンスを読む手がかり。利上げ/利下げ観測の変化で金利・株が動く。"},
    {"match": ["fed interest rate decision", "fomc statement", "fomc rate", "federal funds rate",
               "interest rate decision", "fomc press", "fomc economic projections"],
     "country": "US", "ja": "FOMC 政策金利", "stars": 5, "good_when": "neutral",
     "memo": "政策金利の決定。全資産に影響する最重要イベント。声明・会見の文言が焦点。"},
    {"match": ["powell", "fed chair", "fed speech", "fed governor", "fomc member"],
     "country": "US", "ja": "FRB要人発言", "stars": 3, "good_when": "neutral",
     "memo": "発言トーン（タカ派/ハト派）で金利・ドル円・株が短期的に振れやすい。"},
    # ── 米国：物価 ──
    {"match": ["core pce price index", "core personal consumption"], "country": "US", "ja": "コアPCE物価指数", "stars": 5, "good_when": "low",
     "memo": "FRBが最重視するインフレ指標。上振れは利上げ観測→金利上昇・ハイテク株安要因。"},
    {"match": ["pce price index", "personal consumption expenditures"], "country": "US", "ja": "PCEデフレーター", "stars": 5, "good_when": "low",
     "memo": "FRBが重視するインフレ指標。上振れは株安・ドル高要因になりやすい。"},
    {"match": ["core cpi", "cpi ex food", "core consumer price"], "country": "US", "ja": "コアCPI", "stars": 5, "good_when": "low",
     "memo": "変動の大きい食品・エネルギーを除くインフレの基調。上振れは株安要因。"},
    {"match": ["consumer price index", "cpi"], "country": "US", "ja": "CPI（消費者物価指数）", "stars": 5, "good_when": "low",
     "memo": "米金利・ドル円・ハイテク株に影響大。上振れ＝インフレ加速で株安要因。"},
    # ── 米国：雇用 ──
    # ADP は NFP より前に置く（"ADP Non-Farm Employment Change" を ADP として拾うため）
    {"match": ["adp"], "country": "US", "ja": "ADP雇用統計", "stars": 3, "good_when": "high",
     "memo": "雇用統計の先行指標として注目される民間雇用データ。"},
    {"match": ["nonfarm payroll", "non-farm payroll", "nfp", "non-farm employment", "nonfarm employment"],
     "country": "US", "ja": "雇用統計（非農業部門雇用者数）", "stars": 5, "good_when": "high",
     "memo": "米金利・ドル円・NASDAQに影響しやすい最重要の雇用指標。"},
    {"match": ["unemployment rate"], "country": "US", "ja": "失業率", "stars": 4, "good_when": "low",
     "memo": "雇用統計と同時発表。上振れ（悪化）は景気減速懸念。"},
    {"match": ["average hourly earnings"], "country": "US", "ja": "平均時給（前月比）", "stars": 3, "good_when": "high",
     "memo": "雇用統計と同時発表。賃金インフレの指標として注目。"},
    {"match": ["initial jobless claims", "continuing jobless claims", "jobless claims", "unemployment claims"],
     "country": "US", "ja": "失業保険申請件数", "stars": 3, "good_when": "low",
     "memo": "週次の雇用動向。トレンドの変化（増加基調）に注目。"},
    # ── 米国：景況・消費・成長 ──
    {"match": ["ism manufacturing pmi", "ism manufacturing"], "country": "US", "ja": "ISM製造業景況指数", "stars": 4, "good_when": "high",
     "memo": "景気敏感株・半導体株に影響しやすい。50が拡大/縮小の分かれ目。"},
    {"match": ["ism services pmi", "ism services", "ism non-manufacturing"], "country": "US", "ja": "ISM非製造業景況指数", "stars": 4, "good_when": "high",
     "memo": "サービス業の景況感。米景気の約7割を占める消費・サービスの強さを映す。"},
    {"match": ["retail sales"], "country": "US", "ja": "小売売上高", "stars": 4, "good_when": "high",
     "memo": "個人消費の強さ。景気敏感株・消費関連株に影響。"},
    {"match": ["gross domestic product", "gdp"], "country": "US", "ja": "GDP（国内総生産）", "stars": 4, "good_when": "high",
     "memo": "米景気全体の成長率。市場予想との乖離で金利・株が動く。"},
    {"match": ["michigan", "consumer sentiment"], "country": "US", "ja": "ミシガン大学消費者信頼感指数", "stars": 3, "good_when": "high",
     "memo": "消費者マインド。同時発表のインフレ期待値も注目される。"},

    # ── 日本：金融政策 ──
    {"match": ["boj governor", "boj gov", "boj press", "ueda", "boj outlook"], "country": "JP", "ja": "日銀総裁会見・展望レポート", "stars": 4, "good_when": "neutral",
     "memo": "今後の政策の方向性を示唆。ドル円・銀行株・日本株全体に影響。"},
    {"match": ["bank of japan", "boj rate", "boj interest rate", "boj policy", "boj monetary", "monetary policy statement"],
     "country": "JP", "ja": "日銀 金融政策決定会合", "stars": 5, "good_when": "neutral",
     "memo": "金利・ドル円・銀行株に影響大。政策変更やその示唆が焦点。"},
    # ── 日本：物価 ──
    {"match": ["tokyo core cpi", "tokyo cpi", "tokyo"], "country": "JP", "ja": "東京都区部CPI", "stars": 3, "good_when": "low",
     "memo": "全国CPIの先行指標。日銀の政策判断材料として注目。"},
    {"match": ["national core cpi", "national cpi", "japan cpi"], "country": "JP", "ja": "全国CPI", "stars": 4, "good_when": "low",
     "memo": "日銀の物価目標に直結。上振れは追加利上げ観測→円高・銀行株高要因。"},
    # ── 日本：成長・生産・消費 ──
    {"match": ["gdp", "gross domestic product"], "country": "JP", "ja": "GDP（国内総生産）", "stars": 4, "good_when": "high",
     "memo": "日本景気全体の成長率。予想との乖離で日本株・円が動く。"},
    {"match": ["industrial production"], "country": "JP", "ja": "鉱工業生産", "stars": 3, "good_when": "high",
     "memo": "製造業の生産動向。景気敏感株・輸出関連株の手がかり。"},
    {"match": ["retail sales"], "country": "JP", "ja": "小売売上高", "stars": 3, "good_when": "high",
     "memo": "国内消費の強さ。内需・小売関連株に影響。"},
    {"match": ["economy watchers", "eco watchers"], "country": "JP", "ja": "景気ウォッチャー調査", "stars": 3, "good_when": "high",
     "memo": "街角の景況感。内需・景気循環株のセンチメント材料。"},
    # ── 日本：日銀短観・景況感 ──
    {"match": ["tankan"], "country": "JP", "ja": "日銀短観", "stars": 5, "good_when": "high",
     "memo": "四半期ごとの企業景況感。日本株全体の方向性を左右する重要指標。"},
    {"match": ["manufacturing pmi"], "country": "JP", "ja": "製造業PMI", "stars": 3, "good_when": "high",
     "memo": "製造業の景況感。輸出関連・景気敏感株の手がかり。"},
    {"match": ["services pmi", "non-manufacturing pmi"], "country": "JP", "ja": "サービス業PMI", "stars": 3, "good_when": "high",
     "memo": "非製造業の景況感。内需・サービス株の手がかり。"},
    {"match": ["consumer confidence", "consumer sentiment"], "country": "JP", "ja": "消費者態度指数", "stars": 2, "good_when": "high",
     "memo": "家計の景況感。内需・小売株のセンチメント材料。"},
    # ── 日本：雇用・賃金 ──
    {"match": ["unemployment rate", "jobless rate"], "country": "JP", "ja": "失業率", "stars": 3, "good_when": "low",
     "memo": "労働市場の強さ。賃金・消費の先行きを映す。"},
    {"match": ["jobs/applicants", "jobs to applicants", "job-to-applicant"], "country": "JP", "ja": "有効求人倍率", "stars": 2, "good_when": "high",
     "memo": "求人の逼迫度。雇用の強さと賃金上昇圧力の目安。"},
    {"match": ["average cash earnings", "cash earnings", "labor cash earnings"], "country": "JP", "ja": "現金給与総額", "stars": 3, "good_when": "high",
     "memo": "賃金の伸び。日銀の利上げ判断材料で、上振れは円高・銀行株高要因。"},
    # ── 日本：消費・生産・受注 ──
    {"match": ["household spending"], "country": "JP", "ja": "家計調査（消費支出）", "stars": 2, "good_when": "high",
     "memo": "家計の実支出。内需・小売関連株の手がかり。"},
    {"match": ["core machinery orders", "machinery orders"], "country": "JP", "ja": "機械受注（コア）", "stars": 3, "good_when": "high",
     "memo": "設備投資の先行指標。資本財・機械関連株に影響。"},
    {"match": ["machine tool orders"], "country": "JP", "ja": "工作機械受注", "stars": 2, "good_when": "high",
     "memo": "設備投資需要の先行指標。工作機械・FA関連株の手がかり。"},
    {"match": ["capital spending", "capex"], "country": "JP", "ja": "設備投資（法人企業統計）", "stars": 2, "good_when": "high",
     "memo": "企業の設備投資。GDP改定値にも反映され景気の強さを映す。"},
    {"match": ["tertiary industry"], "country": "JP", "ja": "第三次産業活動指数", "stars": 2, "good_when": "high",
     "memo": "サービス業全体の活動量。内需の強さの目安。"},
    {"match": ["leading indicators", "leading index"], "country": "JP", "ja": "景気先行指数（CI）", "stars": 2, "good_when": "high",
     "memo": "景気の先行きを示す合成指数。景気循環株のセンチメント材料。"},
    # ── 日本：物価・貿易・金融 ──
    {"match": ["producer price", "corporate goods price", "ppi"], "country": "JP", "ja": "企業物価指数（CGPI）", "stars": 3, "good_when": "low",
     "memo": "企業間取引の物価。消費者物価への波及で日銀政策に影響。"},
    {"match": ["trade balance"], "country": "JP", "ja": "貿易収支", "stars": 3, "good_when": "high",
     "memo": "輸出入の差。円相場・輸出関連株に影響。"},
    {"match": ["current account"], "country": "JP", "ja": "経常収支", "stars": 3, "good_when": "high",
     "memo": "対外収支の総合。中長期の円需給を映す。"},
    {"match": ["monetary base"], "country": "JP", "ja": "マネタリーベース", "stars": 2, "good_when": "neutral",
     "memo": "日銀の資金供給量。金融緩和スタンスの目安。"},
]


def _country_key(country: str) -> str:
    c = (country or "").strip()
    if c in ("US", "United States", "USD"):
        return "US"
    if c in ("JP", "Japan", "JPY"):
        return "JP"
    return c


def match_indicator(event_name: str, country: str) -> dict | None:
    """重要指標ホワイトリストに一致すれば enrich 用の dict を返す。なければ None。"""
    name_lower = (event_name or "").lower()
    ckey = _country_key(country)
    for ind in IMPORTANT_INDICATORS:
        if ind.get("country") and ind["country"] != ckey:
            continue
        if any(kw in name_lower for kw in ind["match"]):
            return ind
    return None


def stars_to_importance(stars: int) -> str:
    """★の数を既存の importance ラベルへ（後方互換・並び替え用）。"""
    if stars >= 5:
        return "high"
    if stars >= 3:
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
# 経済指標カレンダー（ForexFactory 週次フィード）
#
# データソース: https://nfs.faireconomy.media/ff_calendar_thisweek.json
#   - APIキー不要・完全無料・JSON
#   - 今週(月〜日)の全世界の経済指標。country=通貨コード(USD/JPY/…)
#   - フィールド: title, country, date(ISO+TZ), impact, forecast, previous
#     ※ 発表後は actual が付与される場合がある → e.get("actual") で拾う
#   - 高頻度アクセスは 429 になるため、呼び出し側でキャッシュ／フォールバックする
# ─────────────────────────────────────────────────

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

COUNTRY_LABEL = {"US": "🇺🇸 米国", "JP": "🇯🇵 日本"}


def _clean_val(v):
    """ForexFactory の値を正規化。空・記号は None に。"""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "—"):
        return None
    return s


def fetch_economic_calendar() -> list[dict]:
    """
    ForexFactory 週次フィードから US・JP の重要経済指標のみを取得。
    JST に変換し、ホワイトリストで enrich。取得失敗時は例外を投げる
    （呼び出し側で既存データへフォールバックさせるため）。
    """
    print("  [経済指標] ForexFactory 週次フィード取得中...", file=sys.stderr)

    resp = requests.get(
        FF_CALENDAR_URL,
        headers={**HEADERS, "Accept": "application/json,text/plain,*/*"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ForexFactory HTTP {resp.status_code}")
    data = resp.json()  # JSON でなければここで例外

    now_jst = datetime.datetime.now(JST)
    results: list[dict] = []

    for e in data:
        ckey = _country_key(e.get("country", ""))
        if ckey not in COUNTRY_LABEL:
            continue

        title = e.get("title", "")
        tl = title.lower()
        # ISM の派生指数（価格指数・雇用指数など）はヘッドラインPMIと誤マッチするため除外
        if "ism" in tl and ("price" in tl or "employment" in tl):
            continue
        ind = match_indicator(title, ckey)
        if not ind:
            continue

        # 日時を JST に変換（ISO 8601 + オフセット）
        raw_dt = e.get("date", "")
        try:
            dt = datetime.datetime.fromisoformat(raw_dt)
            dt_jst = dt.astimezone(JST)
            date_str = dt_jst.strftime("%Y-%m-%d")
            time_jst = dt_jst.strftime("%H:%M")
            iso_jst = dt_jst.isoformat()
            is_released = dt_jst < now_jst
        except Exception:
            # 時刻パース不能（終日・未定など）。日付だけ拾えれば拾う。
            date_str = (raw_dt[:10] if raw_dt else "")
            time_jst = ""
            iso_jst = ""
            is_released = False

        stars = ind["stars"]
        results.append({
            "event":         title,
            "event_ja":      ind.get("ja") or translate_event_name(title),
            "country":       ckey,
            "country_label": COUNTRY_LABEL[ckey],
            "time_jst":      time_jst,
            "datetime_jst":  iso_jst,
            "date":          date_str,
            "actual":        _clean_val(e.get("actual")),
            "forecast":      _clean_val(e.get("forecast")),
            "prior":         _clean_val(e.get("previous")),
            "importance":    stars_to_importance(stars),
            "stars":         stars,
            "good_when":     ind["good_when"],
            "memo":          ind["memo"],
            "status":        "released" if is_released else "scheduled",
            "ff_impact":     e.get("impact", ""),
        })

    # 同一指標・同時刻の重複を除去（FF は m/m と y/y を別行で出すことがある→残す）
    seen = set()
    deduped = []
    for r in results:
        key = (r["event_ja"], r["datetime_jst"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    deduped.sort(key=lambda x: (x.get("date", ""), -x.get("stars", 0), x.get("time_jst") or "99:99"))
    _merge_bls_actuals(deduped)
    print(f"  [経済指標] US/JP 重要指標 {len(deduped)}件取得", file=sys.stderr)
    return deduped


def _ref_month(date_str: str) -> str:
    """発表日(YYYY-MM-DD)から参照月（=前月）の 'YYYY-MM' を返す。"""
    try:
        y, m, _ = (int(x) for x in date_str.split("-"))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        return f"{y:04d}-{m:02d}"
    except Exception:
        return ""


def _merge_bls_actuals(events: list[dict]) -> None:
    """data/bls_actuals.json の結果値を、発表済み・参照月一致の米国指標に埋める。"""
    path = os.path.join(os.path.dirname(__file__), "..", "data", "bls_actuals.json")
    try:
        actuals = json.load(open(path, encoding="utf-8")).get("actuals", {})
    except Exception:
        return
    filled = 0
    for ev in events:
        if ev.get("country") != "US" or ev.get("status") != "released" or ev.get("actual"):
            continue
        a = actuals.get(ev.get("event_ja"))
        if a and a.get("period") == _ref_month(ev.get("date", "")):
            ev["actual"] = a["value"]
            filled += 1
    if filled:
        print(f"  [経済指標] BLS結果値を {filled}件 反映", file=sys.stderr)


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


# 経済指標フィードの再取得間隔（分）。FF は高頻度アクセスで 429 になるため、
# 5分毎の cron でも実際の再取得はこの間隔に絞る。
FF_CACHE_MINUTES = 25

# ─────────────────────────────────────────────────
# gaikaex（外為どっとコム）経済指標カレンダー
#   FFと違い「結果(actual)」を発表直後に掲載し、日本語・JST・全通貨対応。
#   主ソースとして使い、失敗時のみ FF にフォールバックする。
# ─────────────────────────────────────────────────
GAIKAEX_URL = "https://www.gaikaex.com/gaikaex/mark/calendar/{date}"

GX_CUR2COUNTRY = {
    "usd": "US", "jpy": "JP", "eur": "EU", "gbp": "GB", "aud": "AU", "nzd": "NZ",
    "cad": "CA", "chf": "CH", "cny": "CN", "zar": "ZA", "dem": "DE", "frf": "FR",
    "mxn": "MX", "try": "TR",
}
GX_COUNTRY_LABEL = {
    "US": "🇺🇸 米国", "JP": "🇯🇵 日本", "EU": "🇪🇺 ユーロ", "GB": "🇬🇧 英国",
    "DE": "🇩🇪 ドイツ", "FR": "🇫🇷 フランス", "AU": "🇦🇺 豪州", "NZ": "🇳🇿 NZ",
    "CA": "🇨🇦 カナダ", "CH": "🇨🇭 スイス", "CN": "🇨🇳 中国", "ZA": "🇿🇦 南ア",
    "MX": "🇲🇽 メキシコ", "TR": "🇹🇷 トルコ",
}

# 指標名（日本語）→ good_when（結果が予想を上回った時に市場プラスか）
#   high: 上振れ＝株高材料 / low: 下振れ＝株高材料(物価・失業など) / neutral: 方向感なし
GX_GOOD_WHEN = [
    ("low",     ["失業率", "失業保険", "新規失業", "消費者物価", "ＣＰＩ", "CPI", "生産者物価", "卸売物価",
                 "PPI", "物価", "インフレ"]),
    ("neutral", ["発言", "会見", "議事", "総裁", "理事", "委員", "声明", "政策金利", "金利決定", "FOMC",
                 "日銀", "ＦＲＢ", "要人"]),
    ("high",    ["雇用", "非農業", "就業", "給与", "賃金", "GDP", "国内総生産", "小売", "消費", "PMI",
                 "購買担当者", "景況", "景気", "鉱工業", "生産", "受注", "貿易収支", "経常収支",
                 "設備投資", "住宅", "販売", "信頼感", "態度指数"]),
]


def _gx_good_when(name: str) -> str:
    for gw, kws in GX_GOOD_WHEN:
        if any(k in name for k in kws):
            return gw
    return "neutral"


def _gx_clean(v: str):
    """gaikaex のセル値を正規化。'*'・空・'-' は None。前回の修正値 '(...)' は除く。"""
    if not v:
        return None
    v = v.split("(")[0].strip()
    if v in ("", "*", "**", "-", "—", "―"):
        return None
    return v


def fetch_gaikaex_economic() -> list[dict]:
    """gaikaex から経済指標（結果・予想・前回・重要度付き）を取得。★2以上のみ採用。"""
    now_jst = datetime.datetime.now(JST)
    start = (now_jst.date() - datetime.timedelta(days=3)).strftime("%Y%m%d")
    print("  [経済指標] gaikaex カレンダー取得中...", file=sys.stderr)
    resp = requests.get(GAIKAEX_URL.format(date=start),
                        headers={"User-Agent": HEADERS.get("User-Agent", "Mozilla/5.0")}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"gaikaex HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    tbl = soup.select_one(".tableA01.pcOnly table")
    if not tbl:
        raise RuntimeError("gaikaex: テーブルが見つからない")

    year = now_jst.year
    cur_date = None
    results: list[dict] = []
    for tr in tbl.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        if tds[0].get("class") == ["date"]:
            m = re.search(r"(\d+)/(\d+)", tds[0].get_text())
            if m:
                mo, da = int(m.group(1)), int(m.group(2))
                yr = year
                # 年跨ぎ（12月→1月）の簡易補正
                if cur_date and mo == 1 and cur_date.startswith(f"{year}-12"):
                    yr = year + 1
                cur_date = f"{yr:04d}-{mo:02d}-{da:02d}"
            rest = tds[1:]
        else:
            rest = tds
        if len(rest) < 7:
            continue

        time_txt = rest[0].get_text(strip=True)
        fimg = rest[1].find("img")
        cur = ""
        if fimg:
            mm = re.search(r"/([a-z]{3})_", fimg.get("src", ""))
            cur = mm.group(1) if mm else ""
        country = GX_CUR2COUNTRY.get(cur)
        if country not in ("US", "JP"):   # 日本・米国のみ採用
            continue
        name = rest[2].get_text(" ", strip=True)
        stars = rest[3].get_text(strip=True).count("★")
        if stars < 2:                      # 重要度の低い指標は除外
            continue
        actual   = _gx_clean(rest[5].get_text(strip=True))
        forecast = _gx_clean(rest[4].get_text(strip=True))
        prior    = _gx_clean(rest[6].get_text(strip=True))

        # 日時（JST）
        tm = re.match(r"(\d{1,2}):(\d{2})", time_txt or "")
        if cur_date and tm:
            try:
                dt = datetime.datetime(int(cur_date[:4]), int(cur_date[5:7]), int(cur_date[8:10]),
                                       int(tm.group(1)), int(tm.group(2)), tzinfo=JST)
                iso_jst, hhmm = dt.isoformat(), dt.strftime("%H:%M")
                is_released = (actual is not None) or (dt < now_jst)
            except Exception:
                iso_jst, hhmm, is_released = "", time_txt, actual is not None
        else:
            iso_jst, hhmm, is_released = "", time_txt, actual is not None

        results.append({
            "event":         name,
            "event_ja":      name,
            "country":       country,
            "country_label": GX_COUNTRY_LABEL.get(country, country),
            "time_jst":      hhmm,
            "datetime_jst":  iso_jst,
            "date":          cur_date or "",
            "actual":        actual,
            "forecast":      forecast,
            "prior":         prior,
            "importance":    stars_to_importance(stars),
            "stars":         stars,
            "good_when":     _gx_good_when(name),
            "memo":          "",
            "status":        "released" if is_released else "scheduled",
            "source":        "gaikaex",
        })

    # 重複除去
    seen, deduped = set(), []
    for r in results:
        key = (r["event_ja"], r["datetime_jst"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    deduped.sort(key=lambda x: (x.get("date", ""), x.get("time_jst") or "99:99", -x.get("stars", 0)))
    print(f"  [経済指標] gaikaex {len(deduped)}件取得（★2以上）", file=sys.stderr)
    return deduped


EVENTS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "events.json")


def load_existing_events() -> dict:
    """既存 events.json を読み込む。無ければ空 dict。"""
    try:
        with open(EVENTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_economic_data(prior: dict, now_jst: datetime.datetime) -> tuple[list[dict], str]:
    """
    経済指標データを返す (economic, fetched_at)。
    キャッシュが新しければ再利用し、古ければ ForexFactory から再取得。
    取得失敗時は既存データを温存する。
    """
    prior_eco = prior.get("economic", []) or []
    prior_at  = prior.get("economic_fetched_at", "")

    # キャッシュが十分新しければ再取得しない
    if prior_eco and prior_at:
        try:
            age_min = (now_jst - datetime.datetime.fromisoformat(prior_at)).total_seconds() / 60
            if 0 <= age_min < FF_CACHE_MINUTES:
                print(f"  [経済指標] キャッシュ利用（{age_min:.0f}分前 / {len(prior_eco)}件）", file=sys.stderr)
                return prior_eco, prior_at
        except Exception:
            pass

    # 再取得：gaikaex（結果値あり）を主とし、失敗時は ForexFactory にフォールバック
    economic = []
    try:
        economic = fetch_gaikaex_economic()
    except Exception as ex:
        print(f"  [経済指標] gaikaex失敗（{ex}）→ ForexFactoryにフォールバック", file=sys.stderr)
        try:
            economic = fetch_economic_calendar()
        except Exception as ex2:
            print(f"  [経済指標] FFも失敗（{ex2}）→ 既存データを温存", file=sys.stderr)
            return prior_eco, prior_at or now_jst.isoformat()

    if not economic and prior_eco:
        print("  [経済指標] 0件のため既存データを温存", file=sys.stderr)
        return prior_eco, prior_at or now_jst.isoformat()
    return economic, now_jst.isoformat()


def main():
    print("[イベント] 取得開始...", file=sys.stderr)
    now_jst = datetime.datetime.now(JST)
    biz = next_business_days(2)        # 今日 + 翌営業日（決算予定用）
    today     = biz[0]
    tomorrow  = biz[1] if len(biz) > 1 else today

    print(f"  対象日: {today} (今日), {tomorrow} (翌営業日)", file=sys.stderr)

    prior = load_existing_events()

    # ── 各データ取得 ──
    jp_earnings  = fetch_jp_earnings(max_pages=3)    # 翌日 ~45件
    us_earnings  = fetch_us_earnings([today, tomorrow])
    economic, eco_fetched_at = get_economic_data(prior, now_jst)

    output = {
        "updated_at":   now_jst.isoformat(),
        "target_today":    today.isoformat(),
        "target_tomorrow": tomorrow.isoformat(),
        "economic_fetched_at": eco_fetched_at,
        "jp_earnings":  jp_earnings,
        "us_earnings":  us_earnings,
        "economic":     economic,
        "summary": {
            "jp_earnings_count": len(jp_earnings),
            "us_earnings_count": len(us_earnings),
            "economic_count":    len(economic),
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
        "economic":    len(economic),
    }))


if __name__ == "__main__":
    main()
