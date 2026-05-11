#!/usr/bin/env python3
"""
Claude API を使った翻訳モジュール（キャッシュ付き）
- 事業説明（longBusinessSummary）を英語 → 日本語に翻訳
- インダストリー名は静的マッピング優先、未知は API で翻訳
- MD5 キャッシュにより再翻訳を防止
"""

import anthropic
import json
import hashlib
import os
import sys
import time

CACHE_FILE = "data/translation_cache.json"

# yfinance が返す主なインダストリー名の日本語マッピング
INDUSTRY_JP = {
    # Technology
    "Semiconductors":                          "半導体",
    "Semiconductor Equipment & Materials":     "半導体製造装置・材料",
    "Software - Application":                  "ソフトウェア（アプリ）",
    "Software - Infrastructure":               "ソフトウェア（インフラ）",
    "Information Technology Services":         "ITサービス",
    "Electronic Components":                   "電子部品",
    "Consumer Electronics":                    "民生用電子機器",
    "Computer Hardware":                       "コンピュータハードウェア",
    "Communication Equipment":                 "通信機器",
    "Electronics & Computer Distribution":     "電子機器・PC流通",
    "Data Storage":                            "データストレージ",
    "Scientific & Technical Instruments":      "科学・技術機器",
    "Solar":                                   "太陽光発電",
    "Electronic Gaming & Multimedia":          "電子ゲーム・マルチメディア",

    # Healthcare
    "Drug Manufacturers - General":            "製薬（大手）",
    "Drug Manufacturers - Specialty & Generic":"製薬（専門・ジェネリック）",
    "Biotechnology":                           "バイオテクノロジー",
    "Medical Devices":                         "医療機器",
    "Medical Care Facilities":                 "医療施設",
    "Diagnostics & Research":                  "診断・研究",
    "Health Information Services":             "医療情報サービス",
    "Medical Distribution":                    "医療品流通",
    "Pharmaceutical Retailers":                "調剤薬局",

    # Financials
    "Banks - Diversified":                     "総合銀行",
    "Banks - Regional":                        "地方銀行",
    "Insurance - Diversified":                 "総合保険",
    "Insurance - Life":                        "生命保険",
    "Insurance - Property & Casualty":         "損害保険",
    "Capital Markets":                         "資本市場",
    "Asset Management":                        "資産運用",
    "Financial Data & Stock Exchanges":        "金融データ・証券取引所",
    "Credit Services":                         "クレジットサービス",
    "Mortgage Finance":                        "住宅ローン金融",
    "Insurance Brokers":                       "保険ブローカー",

    # Consumer Discretionary / Cyclical
    "Auto Manufacturers":                      "自動車メーカー",
    "Auto Parts":                              "自動車部品",
    "Specialty Retail":                        "専門小売",
    "Internet Retail":                         "ネット通販",
    "Restaurants":                             "飲食業",
    "Home Improvement Retail":                 "ホームセンター",
    "Department Stores":                       "百貨店",
    "Apparel Retail":                          "アパレル小売",
    "Apparel Manufacturing":                   "アパレル製造",
    "Footwear & Accessories":                  "靴・アクセサリー",
    "Leisure":                                 "レジャー",
    "Gambling":                                "ギャンブル",
    "Travel Services":                         "旅行サービス",
    "Lodging":                                 "宿泊業",
    "Resorts & Casinos":                       "リゾート・カジノ",

    # Consumer Staples / Defensive
    "Beverages - Non-Alcoholic":               "飲料（非アルコール）",
    "Beverages - Alcoholic":                   "飲料（アルコール）",
    "Beverages - Brewers":                     "ビールメーカー",
    "Food Distribution":                       "食品流通",
    "Packaged Foods":                          "加工食品",
    "Personal Products":                       "パーソナルケア",
    "Household & Personal Products":           "家庭用・個人用品",
    "Grocery Stores":                          "スーパー",
    "Tobacco":                                 "たばこ",
    "Agricultural Inputs":                     "農業資材",

    # Industrials
    "Aerospace & Defense":                     "航空宇宙・防衛",
    "Industrial Machinery":                    "産業機械",
    "Specialty Industrial Machinery":          "特殊産業機械",
    "Farm & Heavy Construction Machinery":     "農業・重機",
    "Waste Management":                        "廃棄物処理",
    "Electrical Equipment & Parts":            "電気機器・部品",
    "Engineering & Construction":              "建設・エンジニアリング",
    "Rental & Leasing Services":               "レンタル・リース",
    "Trucking":                                "トラック輸送",
    "Airlines":                                "航空会社",
    "Integrated Freight & Logistics":          "総合物流",
    "Marine Shipping":                         "海運",
    "Railroads":                               "鉄道",
    "Staffing & Employment Services":          "人材・雇用サービス",
    "Business Services":                       "ビジネスサービス",
    "Security & Protection Services":          "警備・保護サービス",
    "Consulting Services":                     "コンサルティング",
    "Printing Services":                       "印刷サービス",

    # Energy
    "Oil & Gas Integrated":                    "石油・ガス（総合）",
    "Oil & Gas E&P":                           "石油・ガス（探査・生産）",
    "Oil & Gas Refining & Marketing":          "石油・ガス（精製・販売）",
    "Oil & Gas Equipment & Services":          "石油・ガス機器・サービス",
    "Oil & Gas Midstream":                     "石油・ガス（中流）",
    "Specialty Chemicals":                     "特殊化学品",
    "Coking Coal":                             "コークス用石炭",
    "Thermal Coal":                            "一般炭",
    "Uranium":                                 "ウラン",

    # Utilities
    "Utilities - Regulated Electric":          "規制電力会社",
    "Utilities - Regulated Gas":               "規制ガス会社",
    "Utilities - Regulated Water":             "規制水道",
    "Utilities - Renewable":                   "再生可能エネルギー",
    "Utilities - Diversified":                 "総合公益事業",
    "Utilities - Independent Power Producers": "独立系発電事業者",

    # Real Estate
    "REIT - Retail":                           "REIT（小売）",
    "REIT - Office":                           "REIT（オフィス）",
    "REIT - Residential":                      "REIT（住宅）",
    "REIT - Industrial":                       "REIT（産業）",
    "REIT - Diversified":                      "REIT（複合）",
    "REIT - Healthcare Facilities":            "REIT（医療）",
    "REIT - Hotel & Motel":                    "REIT（ホテル）",
    "REIT - Specialty":                        "REIT（特殊）",
    "Real Estate Services":                    "不動産サービス",
    "Real Estate - Development":               "不動産開発",

    # Communication Services
    "Telecom Services":                        "通信サービス",
    "Internet Content & Information":          "ネットコンテンツ・情報",
    "Entertainment":                           "エンターテイメント",
    "Broadcasting":                            "放送",
    "Publishing":                              "出版",
    "Advertising Agencies":                    "広告代理店",
    "Gaming":                                  "ゲーム",

    # Materials
    "Steel":                                   "鉄鋼",
    "Aluminum":                                "アルミニウム",
    "Copper":                                  "銅",
    "Gold":                                    "金",
    "Silver":                                  "銀",
    "Other Precious Metals & Mining":          "貴金属・鉱業",
    "Paper & Paper Products":                  "紙・紙製品",
    "Lumber & Wood Production":                "製材・木材",
    "Chemicals":                               "化学品",
}


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def cache_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def translate_industry(name: str) -> str:
    """インダストリー名を日本語に変換（静的マッピング優先）"""
    if not name:
        return name
    return INDUSTRY_JP.get(name, name)


def translate_descriptions(texts: list[str], cache: dict) -> tuple[dict, dict]:
    """
    英語説明文を一括翻訳（キャッシュ利用）。
    Returns: (results dict: orig_text → ja_text, updated cache)
    """
    if not texts:
        return {}, cache

    results: dict = {}
    to_translate: list[str] = []

    for text in texts:
        if not text:
            results[text] = ""
            continue
        key = cache_key(text)
        if key in cache:
            results[text] = cache[key]
        else:
            to_translate.append(text)

    if not to_translate:
        return results, cache

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  警告: ANTHROPIC_API_KEY 未設定 → 翻訳スキップ", file=sys.stderr)
        for t in to_translate:
            results[t] = t
        return results, cache

    client = anthropic.Anthropic(api_key=api_key)
    BATCH = 8  # 1リクエストで翻訳する件数

    for i in range(0, len(to_translate), BATCH):
        batch = to_translate[i : i + BATCH]
        items = [{"id": j, "text": t[:400]} for j, t in enumerate(batch)]

        prompt = (
            "以下のJSON配列にある英語の企業事業説明文をそれぞれ日本語に翻訳してください。\n"
            "翻訳は簡潔に200文字以内、専門用語は適切な日本語で表現してください。\n"
            "同じJSON構造（idとtextフィールド）で翻訳結果のみを返してください。\n\n"
            + json.dumps(items, ensure_ascii=False)
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            resp_text = response.content[0].text
            # JSON を抽出
            start = resp_text.find("[")
            end   = resp_text.rfind("]") + 1
            if start >= 0 and end > start:
                translated_items = json.loads(resp_text[start:end])
                for item in translated_items:
                    idx = item.get("id", -1)
                    if 0 <= idx < len(batch):
                        orig = batch[idx]
                        ja   = item.get("text", orig)
                        cache[cache_key(orig)] = ja
                        results[orig] = ja
            print(f"  翻訳完了: {i+1}〜{min(i+BATCH, len(to_translate))}/{len(to_translate)}件",
                  file=sys.stderr)
            time.sleep(0.3)

        except Exception as e:
            print(f"  翻訳エラー (batch {i//BATCH}): {e}", file=sys.stderr)
            for t in batch:
                results[t] = t  # フォールバック

    return results, cache


def enrich_with_translations(stocks: list[dict], cache: dict,
                              desc_key: str = "description") -> tuple[list[dict], dict]:
    """
    stocks リストの description を一括翻訳して description_ja に追加。
    industry も翻訳して industry_ja に追加。
    """
    texts = [s.get(desc_key, "") or "" for s in stocks]
    translations, cache = translate_descriptions(texts, cache)

    for s in stocks:
        orig = s.get(desc_key, "") or ""
        s["description_ja"] = translations.get(orig, orig)
        s["industry_ja"]    = translate_industry(s.get("industry", "") or "")

    return stocks, cache
