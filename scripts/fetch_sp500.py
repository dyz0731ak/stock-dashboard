#!/usr/bin/env python3
"""
S&P 500 主要銘柄のヒートマップ用データを取得する。

GICS 11セクター分類で銘柄をグルーピング。各銘柄について:
  - 現在値 / 前日終値 / 日次変化率 (%)
  - 時価総額（タイル面積の重み）

出力: data/sp500.json
  {
    "updated_at": "...",
    "items": [
      {"symbol": "AAPL", "name": "Apple", "sector": "情報技術",
       "price": 230.5, "prev_close": 228.1, "change_pct": 1.05,
       "market_cap": 3500000000000},
      ...
    ]
  }
"""

import yfinance as yf
import json
import datetime
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
from safe_save import safe_save

JST = datetime.timezone(datetime.timedelta(hours=9))

# ─────────────────────────────────────────────────────────────
# S&P 500 主要銘柄 (シンボル, 企業名, GICS 11セクター)
# 約300銘柄。指数の時価総額ベースで概ね90%以上をカバー。
# ─────────────────────────────────────────────────────────────
SP500 = [
    # 情報技術 (Information Technology)
    ("AAPL",  "Apple",                       "情報技術"),
    ("MSFT",  "Microsoft",                   "情報技術"),
    ("NVDA",  "NVIDIA",                      "情報技術"),
    ("AVGO",  "Broadcom",                    "情報技術"),
    ("ORCL",  "Oracle",                      "情報技術"),
    ("CRM",   "Salesforce",                  "情報技術"),
    ("CSCO",  "Cisco Systems",               "情報技術"),
    ("ACN",   "Accenture",                   "情報技術"),
    ("ADBE",  "Adobe",                       "情報技術"),
    ("AMD",   "AMD",                         "情報技術"),
    ("IBM",   "IBM",                         "情報技術"),
    ("INTC",  "Intel",                       "情報技術"),
    ("QCOM",  "Qualcomm",                    "情報技術"),
    ("TXN",   "Texas Instruments",           "情報技術"),
    ("INTU",  "Intuit",                      "情報技術"),
    ("AMAT",  "Applied Materials",           "情報技術"),
    ("ADI",   "Analog Devices",              "情報技術"),
    ("LRCX",  "Lam Research",                "情報技術"),
    ("KLAC",  "KLA",                         "情報技術"),
    ("MU",    "Micron Technology",           "情報技術"),
    ("NOW",   "ServiceNow",                  "情報技術"),
    ("PANW",  "Palo Alto Networks",          "情報技術"),
    ("ANET",  "Arista Networks",             "情報技術"),
    ("CDNS",  "Cadence Design",              "情報技術"),
    ("SNPS",  "Synopsys",                    "情報技術"),
    ("MRVL",  "Marvell Technology",          "情報技術"),
    ("ADSK",  "Autodesk",                    "情報技術"),
    ("FTNT",  "Fortinet",                    "情報技術"),
    ("MSI",   "Motorola Solutions",          "情報技術"),
    ("ROP",   "Roper Technologies",          "情報技術"),
    ("CRWD",  "CrowdStrike",                 "情報技術"),
    ("WDAY",  "Workday",                     "情報技術"),
    ("PAYX",  "Paychex",                     "情報技術"),
    ("HPQ",   "HP",                          "情報技術"),
    ("HPE",   "Hewlett Packard Enterprise",  "情報技術"),
    ("DELL",  "Dell Technologies",           "情報技術"),
    ("NXPI",  "NXP Semiconductors",          "情報技術"),
    ("MCHP",  "Microchip Technology",        "情報技術"),
    ("ON",    "ON Semiconductor",            "情報技術"),
    ("STX",   "Seagate Technology",          "情報技術"),
    ("ZS",    "Zscaler",                     "情報技術"),
    ("FICO",  "Fair Isaac",                  "情報技術"),
    ("KEYS",  "Keysight Technologies",       "情報技術"),
    ("GLW",   "Corning",                     "情報技術"),
    ("WDC",   "Western Digital",             "情報技術"),
    ("ENPH",  "Enphase Energy",              "情報技術"),

    # 通信サービス (Communication Services)
    ("META",  "Meta Platforms",              "通信サービス"),
    ("GOOGL", "Alphabet (A)",                "通信サービス"),
    ("GOOG",  "Alphabet (C)",                "通信サービス"),
    ("NFLX",  "Netflix",                     "通信サービス"),
    ("TMUS",  "T-Mobile US",                 "通信サービス"),
    ("DIS",   "Walt Disney",                 "通信サービス"),
    ("CMCSA", "Comcast",                     "通信サービス"),
    ("VZ",    "Verizon",                     "通信サービス"),
    ("T",     "AT&T",                        "通信サービス"),
    ("CHTR",  "Charter Communications",      "通信サービス"),
    ("WBD",   "Warner Bros. Discovery",      "通信サービス"),
    ("EA",    "Electronic Arts",             "通信サービス"),
    ("TTWO",  "Take-Two Interactive",        "通信サービス"),
    ("ROKU",  "Roku",                        "通信サービス"),
    ("PARA",  "Paramount Global",            "通信サービス"),
    ("OMC",   "Omnicom Group",               "通信サービス"),
    ("LYV",   "Live Nation",                 "通信サービス"),
    ("FOXA",  "Fox (A)",                     "通信サービス"),
    ("FOX",   "Fox (B)",                     "通信サービス"),
    ("MTCH",  "Match Group",                 "通信サービス"),

    # 一般消費財 (Consumer Discretionary)
    ("AMZN",  "Amazon",                      "一般消費財"),
    ("TSLA",  "Tesla",                       "一般消費財"),
    ("HD",    "Home Depot",                  "一般消費財"),
    ("MCD",   "McDonald's",                  "一般消費財"),
    ("NKE",   "Nike",                        "一般消費財"),
    ("LOW",   "Lowe's",                      "一般消費財"),
    ("TJX",   "TJX Companies",               "一般消費財"),
    ("BKNG",  "Booking Holdings",            "一般消費財"),
    ("SBUX",  "Starbucks",                   "一般消費財"),
    ("CMG",   "Chipotle Mexican Grill",      "一般消費財"),
    ("ABNB",  "Airbnb",                      "一般消費財"),
    ("MAR",   "Marriott International",      "一般消費財"),
    ("HLT",   "Hilton Worldwide",            "一般消費財"),
    ("GM",    "General Motors",              "一般消費財"),
    ("F",     "Ford Motor",                  "一般消費財"),
    ("ORLY",  "O'Reilly Automotive",         "一般消費財"),
    ("AZO",   "AutoZone",                    "一般消費財"),
    ("ROST",  "Ross Stores",                 "一般消費財"),
    ("YUM",   "Yum! Brands",                 "一般消費財"),
    ("EBAY",  "eBay",                        "一般消費財"),
    ("DHI",   "D.R. Horton",                 "一般消費財"),
    ("LEN",   "Lennar",                      "一般消費財"),
    ("NVR",   "NVR",                         "一般消費財"),
    ("PHM",   "PulteGroup",                  "一般消費財"),
    ("BBY",   "Best Buy",                    "一般消費財"),
    ("LULU",  "Lululemon Athletica",         "一般消費財"),
    ("DECK",  "Deckers Outdoor",             "一般消費財"),
    ("RCL",   "Royal Caribbean Cruises",     "一般消費財"),
    ("CCL",   "Carnival",                    "一般消費財"),
    ("ULTA",  "Ulta Beauty",                 "一般消費財"),
    ("APTV",  "Aptiv",                       "一般消費財"),
    ("MGM",   "MGM Resorts",                 "一般消費財"),
    ("LVS",   "Las Vegas Sands",             "一般消費財"),
    ("DRI",   "Darden Restaurants",          "一般消費財"),
    ("EXPE",  "Expedia Group",               "一般消費財"),
    ("DPZ",   "Domino's Pizza",              "一般消費財"),
    ("TPR",   "Tapestry",                    "一般消費財"),

    # 生活必需品 (Consumer Staples)
    ("WMT",   "Walmart",                     "生活必需品"),
    ("PG",    "Procter & Gamble",            "生活必需品"),
    ("KO",    "Coca-Cola",                   "生活必需品"),
    ("PEP",   "PepsiCo",                     "生活必需品"),
    ("COST",  "Costco Wholesale",            "生活必需品"),
    ("PM",    "Philip Morris International", "生活必需品"),
    ("MO",    "Altria Group",                "生活必需品"),
    ("MDLZ",  "Mondelez International",      "生活必需品"),
    ("CL",    "Colgate-Palmolive",           "生活必需品"),
    ("TGT",   "Target",                      "生活必需品"),
    ("KMB",   "Kimberly-Clark",              "生活必需品"),
    ("GIS",   "General Mills",               "生活必需品"),
    ("KHC",   "Kraft Heinz",                 "生活必需品"),
    ("SYY",   "Sysco",                       "生活必需品"),
    ("KR",    "Kroger",                      "生活必需品"),
    ("STZ",   "Constellation Brands",        "生活必需品"),
    ("HSY",   "Hershey",                     "生活必需品"),
    ("KDP",   "Keurig Dr Pepper",            "生活必需品"),
    ("MNST",  "Monster Beverage",            "生活必需品"),
    ("ADM",   "Archer-Daniels-Midland",      "生活必需品"),
    ("EL",    "Estee Lauder",                "生活必需品"),
    ("CLX",   "Clorox",                      "生活必需品"),
    ("CHD",   "Church & Dwight",             "生活必需品"),
    ("MKC",   "McCormick",                   "生活必需品"),
    ("CAG",   "Conagra Brands",              "生活必需品"),
    ("TSN",   "Tyson Foods",                 "生活必需品"),
    ("DLTR",  "Dollar Tree",                 "生活必需品"),
    ("DG",    "Dollar General",              "生活必需品"),

    # ヘルスケア (Health Care)
    ("LLY",   "Eli Lilly",                   "ヘルスケア"),
    ("UNH",   "UnitedHealth Group",          "ヘルスケア"),
    ("JNJ",   "Johnson & Johnson",           "ヘルスケア"),
    ("ABBV",  "AbbVie",                      "ヘルスケア"),
    ("MRK",   "Merck",                       "ヘルスケア"),
    ("TMO",   "Thermo Fisher Scientific",    "ヘルスケア"),
    ("ABT",   "Abbott Laboratories",         "ヘルスケア"),
    ("DHR",   "Danaher",                     "ヘルスケア"),
    ("AMGN",  "Amgen",                       "ヘルスケア"),
    ("PFE",   "Pfizer",                      "ヘルスケア"),
    ("ISRG",  "Intuitive Surgical",          "ヘルスケア"),
    ("SYK",   "Stryker",                     "ヘルスケア"),
    ("BMY",   "Bristol-Myers Squibb",        "ヘルスケア"),
    ("MDT",   "Medtronic",                   "ヘルスケア"),
    ("VRTX",  "Vertex Pharmaceuticals",      "ヘルスケア"),
    ("REGN",  "Regeneron Pharmaceuticals",   "ヘルスケア"),
    ("BSX",   "Boston Scientific",           "ヘルスケア"),
    ("GILD",  "Gilead Sciences",             "ヘルスケア"),
    ("CI",    "Cigna",                       "ヘルスケア"),
    ("ELV",   "Elevance Health",             "ヘルスケア"),
    ("HUM",   "Humana",                      "ヘルスケア"),
    ("CVS",   "CVS Health",                  "ヘルスケア"),
    ("ZTS",   "Zoetis",                      "ヘルスケア"),
    ("MCK",   "McKesson",                    "ヘルスケア"),
    ("BDX",   "Becton Dickinson",            "ヘルスケア"),
    ("EW",    "Edwards Lifesciences",        "ヘルスケア"),
    ("HCA",   "HCA Healthcare",              "ヘルスケア"),
    ("DXCM",  "DexCom",                      "ヘルスケア"),
    ("IDXX",  "IDEXX Laboratories",          "ヘルスケア"),
    ("BIIB",  "Biogen",                      "ヘルスケア"),
    ("MRNA",  "Moderna",                     "ヘルスケア"),
    ("A",     "Agilent Technologies",        "ヘルスケア"),
    ("IQV",   "IQVIA Holdings",              "ヘルスケア"),
    ("CNC",   "Centene",                     "ヘルスケア"),
    ("RMD",   "ResMed",                      "ヘルスケア"),
    ("ALGN",  "Align Technology",            "ヘルスケア"),
    ("WST",   "West Pharmaceutical Services","ヘルスケア"),
    ("MTD",   "Mettler-Toledo",              "ヘルスケア"),
    ("ILMN",  "Illumina",                    "ヘルスケア"),

    # 金融 (Financials)
    ("BRK-B", "Berkshire Hathaway",          "金融"),
    ("JPM",   "JPMorgan Chase",              "金融"),
    ("V",     "Visa",                        "金融"),
    ("MA",    "Mastercard",                  "金融"),
    ("BAC",   "Bank of America",             "金融"),
    ("WFC",   "Wells Fargo",                 "金融"),
    ("GS",    "Goldman Sachs",               "金融"),
    ("MS",    "Morgan Stanley",              "金融"),
    ("C",     "Citigroup",                   "金融"),
    ("AXP",   "American Express",            "金融"),
    ("BLK",   "BlackRock",                   "金融"),
    ("SPGI",  "S&P Global",                  "金融"),
    ("PGR",   "Progressive",                 "金融"),
    ("CB",    "Chubb",                       "金融"),
    ("MCO",   "Moody's",                     "金融"),
    ("ICE",   "Intercontinental Exchange",   "金融"),
    ("CME",   "CME Group",                   "金融"),
    ("AON",   "Aon",                         "金融"),
    ("USB",   "U.S. Bancorp",                "金融"),
    ("PNC",   "PNC Financial Services",      "金融"),
    ("SCHW",  "Charles Schwab",              "金融"),
    ("TFC",   "Truist Financial",            "金融"),
    ("COF",   "Capital One",                 "金融"),
    ("BK",    "Bank of New York Mellon",     "金融"),
    ("AIG",   "American International Group","金融"),
    ("MET",   "MetLife",                     "金融"),
    ("PRU",   "Prudential Financial",        "金融"),
    ("AFL",   "Aflac",                       "金融"),
    ("ALL",   "Allstate",                    "金融"),
    ("TRV",   "Travelers",                   "金融"),
    ("HIG",   "Hartford Financial Services", "金融"),
    ("SYF",   "Synchrony Financial",         "金融"),
    ("MTB",   "M&T Bank",                    "金融"),
    ("FITB",  "Fifth Third Bancorp",         "金融"),
    ("STT",   "State Street",                "金融"),
    ("NTRS",  "Northern Trust",              "金融"),
    ("WTW",   "Willis Towers Watson",        "金融"),
    ("BX",    "Blackstone",                  "金融"),
    ("KKR",   "KKR",                         "金融"),

    # 資本財・サービス (Industrials)
    ("GE",    "GE Aerospace",                "資本財"),
    ("CAT",   "Caterpillar",                 "資本財"),
    ("RTX",   "RTX",                         "資本財"),
    ("UNP",   "Union Pacific",               "資本財"),
    ("HON",   "Honeywell International",     "資本財"),
    ("LMT",   "Lockheed Martin",             "資本財"),
    ("BA",    "Boeing",                      "資本財"),
    ("DE",    "Deere",                       "資本財"),
    ("ADP",   "Automatic Data Processing",   "資本財"),
    ("ETN",   "Eaton",                       "資本財"),
    ("UPS",   "United Parcel Service",       "資本財"),
    ("CSX",   "CSX",                         "資本財"),
    ("NSC",   "Norfolk Southern",            "資本財"),
    ("WM",    "Waste Management",            "資本財"),
    ("ITW",   "Illinois Tool Works",         "資本財"),
    ("MMM",   "3M",                          "資本財"),
    ("EMR",   "Emerson Electric",            "資本財"),
    ("PH",    "Parker-Hannifin",             "資本財"),
    ("GD",    "General Dynamics",            "資本財"),
    ("NOC",   "Northrop Grumman",            "資本財"),
    ("FDX",   "FedEx",                       "資本財"),
    ("CARR",  "Carrier Global",              "資本財"),
    ("OTIS",  "Otis Worldwide",              "資本財"),
    ("PCAR",  "PACCAR",                      "資本財"),
    ("ROK",   "Rockwell Automation",         "資本財"),
    ("CTAS",  "Cintas",                      "資本財"),
    ("RSG",   "Republic Services",           "資本財"),
    ("PWR",   "Quanta Services",             "資本財"),
    ("URI",   "United Rentals",              "資本財"),
    ("FAST",  "Fastenal",                    "資本財"),
    ("ODFL",  "Old Dominion Freight Line",   "資本財"),
    ("CMI",   "Cummins",                     "資本財"),
    ("PAYC",  "Paycom Software",             "資本財"),
    ("VRSK",  "Verisk Analytics",            "資本財"),
    ("AME",   "AMETEK",                      "資本財"),
    ("EFX",   "Equifax",                     "資本財"),
    ("LHX",   "L3Harris Technologies",       "資本財"),
    ("DAL",   "Delta Air Lines",             "資本財"),
    ("UAL",   "United Airlines",             "資本財"),
    ("LUV",   "Southwest Airlines",          "資本財"),
    ("AAL",   "American Airlines",           "資本財"),
    ("XYL",   "Xylem",                       "資本財"),
    ("IR",    "Ingersoll Rand",              "資本財"),
    ("DOV",   "Dover",                       "資本財"),
    ("SWK",   "Stanley Black & Decker",      "資本財"),
    ("HUBB",  "Hubbell",                     "資本財"),
    ("AXON",  "Axon Enterprise",             "資本財"),
    ("J",     "Jacobs Solutions",            "資本財"),

    # エネルギー (Energy)
    ("XOM",   "Exxon Mobil",                 "エネルギー"),
    ("CVX",   "Chevron",                     "エネルギー"),
    ("COP",   "ConocoPhillips",              "エネルギー"),
    ("EOG",   "EOG Resources",               "エネルギー"),
    ("MPC",   "Marathon Petroleum",          "エネルギー"),
    ("PSX",   "Phillips 66",                 "エネルギー"),
    ("SLB",   "Schlumberger",                "エネルギー"),
    ("VLO",   "Valero Energy",               "エネルギー"),
    ("OXY",   "Occidental Petroleum",        "エネルギー"),
    ("WMB",   "Williams Companies",          "エネルギー"),
    ("KMI",   "Kinder Morgan",               "エネルギー"),
    ("FANG",  "Diamondback Energy",          "エネルギー"),
    ("DVN",   "Devon Energy",                "エネルギー"),
    ("HAL",   "Halliburton",                 "エネルギー"),
    ("BKR",   "Baker Hughes",                "エネルギー"),
    ("OKE",   "ONEOK",                       "エネルギー"),

    # 素材 (Materials)
    ("LIN",   "Linde",                       "素材"),
    ("SHW",   "Sherwin-Williams",            "素材"),
    ("APD",   "Air Products and Chemicals",  "素材"),
    ("ECL",   "Ecolab",                      "素材"),
    ("FCX",   "Freeport-McMoRan",            "素材"),
    ("NEM",   "Newmont",                     "素材"),
    ("DOW",   "Dow",                         "素材"),
    ("DD",    "DuPont de Nemours",           "素材"),
    ("PPG",   "PPG Industries",              "素材"),
    ("CTVA",  "Corteva",                     "素材"),
    ("NUE",   "Nucor",                       "素材"),
    ("VMC",   "Vulcan Materials",            "素材"),
    ("MLM",   "Martin Marietta Materials",   "素材"),
    ("PKG",   "Packaging Corp of America",   "素材"),
    ("IP",    "International Paper",         "素材"),
    ("ALB",   "Albemarle",                   "素材"),
    ("STLD",  "Steel Dynamics",              "素材"),
    ("EMN",   "Eastman Chemical",            "素材"),
    ("CF",    "CF Industries",               "素材"),
    ("MOS",   "Mosaic",                      "素材"),

    # 公益事業 (Utilities)
    ("NEE",   "NextEra Energy",              "公益事業"),
    ("SO",    "Southern Company",            "公益事業"),
    ("DUK",   "Duke Energy",                 "公益事業"),
    ("CEG",   "Constellation Energy",        "公益事業"),
    ("SRE",   "Sempra",                      "公益事業"),
    ("AEP",   "American Electric Power",     "公益事業"),
    ("D",     "Dominion Energy",             "公益事業"),
    ("PCG",   "PG&E",                        "公益事業"),
    ("EXC",   "Exelon",                      "公益事業"),
    ("XEL",   "Xcel Energy",                 "公益事業"),
    ("PEG",   "Public Service Enterprise",   "公益事業"),
    ("ED",    "Consolidated Edison",         "公益事業"),
    ("WEC",   "WEC Energy Group",            "公益事業"),
    ("ETR",   "Entergy",                     "公益事業"),
    ("EIX",   "Edison International",        "公益事業"),
    ("AWK",   "American Water Works",        "公益事業"),
    ("AEE",   "Ameren",                      "公益事業"),
    ("DTE",   "DTE Energy",                  "公益事業"),
    ("VST",   "Vistra",                      "公益事業"),
    ("FE",    "FirstEnergy",                 "公益事業"),

    # 不動産 (Real Estate)
    ("PLD",   "Prologis",                    "不動産"),
    ("AMT",   "American Tower",              "不動産"),
    ("EQIX",  "Equinix",                     "不動産"),
    ("WELL",  "Welltower",                   "不動産"),
    ("SPG",   "Simon Property Group",        "不動産"),
    ("PSA",   "Public Storage",              "不動産"),
    ("O",     "Realty Income",               "不動産"),
    ("CCI",   "Crown Castle",                "不動産"),
    ("DLR",   "Digital Realty Trust",        "不動産"),
    ("CSGP",  "CoStar Group",                "不動産"),
    ("VICI",  "VICI Properties",             "不動産"),
    ("AVB",   "AvalonBay Communities",       "不動産"),
    ("EXR",   "Extra Space Storage",         "不動産"),
    ("EQR",   "Equity Residential",          "不動産"),
    ("SBAC",  "SBA Communications",          "不動産"),
    ("WY",    "Weyerhaeuser",                "不動産"),
    ("INVH",  "Invitation Homes",            "不動産"),
    ("ARE",   "Alexandria Real Estate",      "不動産"),
    ("MAA",   "Mid-America Apartment",       "不動産"),
    ("ESS",   "Essex Property Trust",        "不動産"),
]

# 重複除去
_seen = set()
SP500_DEDUP = []
for sym, name, sector in SP500:
    if sym in _seen:
        continue
    _seen.add(sym)
    SP500_DEDUP.append((sym, name, sector))


def fetch_one(symbol, name, sector):
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d", interval="1d", auto_adjust=False)
        if hist.empty or len(hist) < 2:
            return None
        prev_close = float(hist["Close"].iloc[-2])
        price      = float(hist["Close"].iloc[-1])
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

        market_cap = None
        try:
            mc = t.fast_info.get("market_cap") if hasattr(t, "fast_info") else None
            if mc:
                market_cap = float(mc)
        except Exception:
            pass
        if not market_cap:
            try:
                shares = t.fast_info.get("shares") if hasattr(t, "fast_info") else None
                if shares:
                    market_cap = float(shares) * price
            except Exception:
                pass

        return {
            "symbol":     symbol,
            "name":       name,
            "sector":     sector,
            "price":      round(price, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(change_pct, 3),
            "market_cap": int(market_cap) if market_cap else None,
        }
    except Exception as e:
        print(f"  [{symbol}] error: {e}", file=sys.stderr)
        return None


def main():
    print(f"[S&P500ヒートマップ] {len(SP500_DEDUP)}銘柄 取得開始...", file=sys.stderr)

    results = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fetch_one, s, n, c): (s, n, c) for s, n, c in SP500_DEDUP}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: -(x.get("market_cap") or 0))

    out = {
        "items": results,
        "updated_at": datetime.datetime.now(JST).isoformat(),
    }

    saved = safe_save(
        "data/sp500.json",
        out,
        lambda d: len(d.get("items", [])),
        label="S&P500ヒートマップ",
    )

    print(json.dumps({
        "status": "ok" if saved else "kept_existing",
        "count": len(results),
    }))


if __name__ == "__main__":
    main()
