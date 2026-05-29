#!/usr/bin/env python3
"""
本日の決算速報 / マルチソース取得スクリプト

データソース:
  1) irbank.net/news          — 数値データ完備の決算速報（売上・利益・増減率）
  2) kabutan.jp/news/?category=4 — 株探の決算速報ニュース（修正/決算の見出し付き）
  3) ke.kabupro.jp/hist/today.htm — 当日の決算関連適時開示の全件

3ソースを統合し、当日（JST）の決算関連情報のみを対象に
銘柄コードで重複排除しつつ、サプライズ性の高い順にグルーピングして出力する。

出力: data/earnings_flash.json
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
from typing import Any

import requests
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


# ─────────────────────────────────────────────────
# カテゴリ定義
# ─────────────────────────────────────────────────

# 表示優先度（小さいほど上位に表示）
CATEGORY_PRIORITY: dict[str, int] = {
    "一転最高益": 10,
    "上振れ最高益": 12,
    "連続最高益": 14,
    "一転増益": 20,
    "大幅上方修正": 22,
    "上方修正": 30,
    "増配・配当修正": 40,
    "黒字浮上": 45,
    "本決算・四半期決算": 60,
    "下方修正": 80,
    "減配": 85,
    "赤字・減益": 90,
    "その他開示": 99,
}

CATEGORY_DISPLAY: dict[str, str] = {
    "一転最高益": "一転最高益",
    "上振れ最高益": "上振れ最高益",
    "連続最高益": "連続最高益",
    "一転増益": "一転増益",
    "大幅上方修正": "大幅上方修正",
    "上方修正": "上方修正",
    "増配・配当修正": "増配・配当修正",
    "黒字浮上": "黒字浮上",
    "本決算・四半期決算": "決算発表",
    "下方修正": "下方修正",
    "減配": "減配",
    "赤字・減益": "赤字・減益",
    "その他開示": "その他開示",
}


def classify_by_title(title: str) -> str:
    """ニュース見出しから決算カテゴリを推定する"""
    t = title

    # 上位カテゴリから順に判定
    if "一転最高益" in t:
        return "一転最高益"
    if "上振れ" in t and "最高益" in t:
        return "上振れ最高益"
    if "最高益" in t and ("連続" in t or "更新" in t):
        return "連続最高益"
    if "一転" in t and "増益" in t:
        return "一転増益"
    if ("大幅" in t and "上方修正" in t) or ("上方修正" in t and re.search(r"[2-9]\d％|\d{3}％", t)):
        return "大幅上方修正"
    if "上方修正" in t or ("一転" in t and "上方" in t):
        return "上方修正"
    if "黒字浮上" in t or "黒字転換" in t or ("一転" in t and "黒字" in t):
        return "黒字浮上"
    if "下方修正" in t:
        return "下方修正"
    # 減配の明確なシグナル
    if (
        "減配" in t
        or "無配" in t
        or ("配当" in t and "見送" in t)
        or ("配当" in t and "未定" in t)
    ):
        return "減配"
    # 増配の明確なシグナル（「配当予想の修正」だけでは方向不明なので増額キーワード必須）
    if "増配" in t or ("配当" in t and ("増額" in t or "上方" in t)):
        return "増配・配当修正"
    if "赤字" in t or "減益" in t:
        return "赤字・減益"
    if (
        "決算短信" in t
        or "決算説明" in t
        or "決算補足" in t
        or "決算・" in t       # 例: "決算・経営方針説明"
        or "四半期" in t
        or "本決算" in t
        or re.search(r"第\d+期.*決算", t)  # "（第44期）決算説…" のように説明が切れていてもマッチ
        or re.search(r"\d-\d月期", t)  # 株探タイトル例: "2-4月期(1Q)経常..."
    ):
        return "本決算・四半期決算"
    return "その他開示"


# 鮮度の高い決算情報として表示対象外にするタイトル（訂正・組織変更など）
NOISE_PATTERNS = [
    r"^\s*[（(]訂正",
    r"^\s*[（(]再送",
    r"会社分割",
    r"株主優待",
    r"株式分割",
    r"自己株式",
    r"株式の.*取得",
    r"資本.+業務提携",
    r"組織再編",
    r"定款の一部変更",
    r"代表取締役",
    r"事業計画",
    r"成長可能性",
    r"特別利益.*計上",
    r"特別損失.*計上",
    r"剰余金の配当",  # 通常の配当決定はノイズ（増配/減配は別途分類済み）
    r"連結子会社",
    r"株式報酬",
    r"ストックオプション",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS))


def is_noise(title: str) -> bool:
    return bool(NOISE_RE.search(title))


# ─────────────────────────────────────────────────
# ソース1: irbank.net/news
# ─────────────────────────────────────────────────

def fetch_irbank() -> tuple[list[dict], str]:
    """
    irbank.net/news の決算速報テーブルから最新営業日分を取得。
    return: (items, latest_date_str)
    """
    print("  [irbank] /news 取得中...", file=sys.stderr)
    url = "https://irbank.net/news"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [irbank] 取得エラー: {e}", file=sys.stderr)
        return [], ""

    soup = BeautifulSoup(resp.text, "html.parser")
    tbl = soup.find("table", class_="cs")
    if not tbl:
        print("  [irbank] 表が見つかりません", file=sys.stderr)
        return [], ""

    items: list[dict] = []
    in_target = False
    seen_first_day = False
    latest_date = ""
    current_code = None
    current_name = None
    current_time = None

    for tr in tbl.find_all("tr"):
        tds = tr.find_all("td")
        # 日付見出し行（1セルのみ）
        if len(tds) <= 1:
            text = tr.get_text(" ", strip=True)
            m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
            if m:
                if not seen_first_day:
                    # 最新営業日の見出しを採用
                    seen_first_day = True
                    in_target = True
                    latest_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                else:
                    # 翌の日付に到達したら終了
                    if in_target:
                        break
            continue

        if not in_target:
            continue

        # 通常エントリ行 (9 cells: 時刻+コード+会社+年度+区分+売上+営業+経常+純利益)
        # 継続行（6 cells: 年度+区分+売上+営業+経常+純利益）は前の銘柄の別期間
        cells_text = [c.get_text(" ", strip=True) for c in tds]

        if len(tds) == 9:
            current_time = cells_text[0]
            current_code = cells_text[1]
            current_name = cells_text[2]
            period = cells_text[3]
            kind = cells_text[4]  # 修正/実績/予想
            sales, op, ord_, net = cells_text[5], cells_text[6], cells_text[7], cells_text[8]
            href = ""
            for a in tds[2].find_all("a", href=True):
                href = a["href"]
                break
            url_full = (
                f"https://irbank.net{href}" if href.startswith("/") else href
            )

            # カテゴリ判定: 金額の +/- と区分から判定
            cat = _classify_irbank(kind, sales, op, ord_, net)
            # description: 主要数値を短く
            desc = _irbank_description(period, kind, sales, op, ord_, net)

            items.append(
                {
                    "code": current_code,
                    "name": current_name,
                    "time": current_time,
                    "source": "irbank",
                    "category": cat,
                    "description": desc,
                    "metrics": {
                        "period": period,
                        "type": kind,
                        "sales": sales,
                        "op": op,
                        "ord": ord_,
                        "net": net,
                    },
                    "url": url_full or "https://irbank.net/news",
                }
            )
        elif len(tds) == 6 and current_code:
            # 同じ銘柄の別期間（予想など）。重要度低いので主項目のみ保持
            # ここでは追加しない（メイン項目のみ表示で十分）
            continue

    print(f"  [irbank] {len(items)}件取得（最新日={latest_date}）", file=sys.stderr)
    return items, latest_date


def _classify_irbank(kind: str, sales: str, op: str, ord_: str, net: str) -> str:
    """irbankの行から決算カテゴリを推定"""
    text = f"{sales} {op} {ord_} {net}"

    if kind == "実績":
        return "本決算・四半期決算"

    # 修正・予想系: 増減率の +/- を見る（％は半角/全角どちらも許容）
    positives = re.findall(r"\+(\d+(?:\.\d+)?)[％%]", text)
    negatives = re.findall(r"-(\d+(?:\.\d+)?)[％%]", text)
    pos_vals = [float(x) for x in positives]
    neg_vals = [float(x) for x in negatives]

    # 利益系の +/- 多数派で判断
    if pos_vals and not neg_vals:
        # 大きな増益→大幅上方修正
        if any(v >= 20 for v in pos_vals):
            return "大幅上方修正"
        return "上方修正"
    if neg_vals and not pos_vals:
        return "下方修正"
    # 混在 → 多い方
    if len(pos_vals) > len(neg_vals):
        return "上方修正"
    if len(neg_vals) > len(pos_vals):
        return "下方修正"

    # 値なし: kindが"予想"なら本決算系
    if kind == "予想":
        return "本決算・四半期決算"
    return "その他開示"


def _irbank_description(period: str, kind: str, sales: str, op: str, ord_: str, net: str) -> str:
    """irbank行から短い説明文を組み立て"""
    # period 例: "2026/04 12ヶ月"
    parts = [f"{period}・{kind}"]
    # 経常と純利益を優先表示
    if ord_ and ord_ != "-":
        parts.append(f"経常 {ord_}")
    if net and net != "-":
        parts.append(f"純益 {net}")
    return " / ".join(parts)


# ─────────────────────────────────────────────────
# ソース2: kabutan.jp/news/?category=4 の決算ニュース一覧
# ─────────────────────────────────────────────────

def fetch_kabutan() -> tuple[list[dict], str]:
    """
    kabutan.jp/news/?category=4 の決算ニュースリスト（s_news_list）から
    最新日付分を取得。return: (items, "MM/DD")
    """
    print("  [kabutan] /news/ 取得中...", file=sys.stderr)
    url = "https://kabutan.jp/news/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [kabutan] 取得エラー: {e}", file=sys.stderr)
        return [], ""

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []

    # 一覧の先頭にある日付プレフィックス（MM/DD）を最新営業日として採用
    latest_md = ""
    for tbl in soup.find_all("table", class_="s_news_list"):
        for tr in tbl.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            date_time = tds[0].get_text(" ", strip=True)
            m_md = re.match(r"(\d{2}/\d{2})", date_time)
            if m_md:
                latest_md = m_md.group(1)
                break
        if latest_md:
            break

    if not latest_md:
        return [], ""

    for tbl in soup.find_all("table", class_="s_news_list"):
        for tr in tbl.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            date_time = tds[0].get_text(" ", strip=True)
            if not date_time.startswith(latest_md):
                continue

            # 時刻部分
            m = re.search(r"(\d{1,2}:\d{2})", date_time)
            time_str = m.group(1) if m else ""

            kind = tds[1].get_text(strip=True)  # 修正/決算
            code = tds[2].get("data-code", "") if tds[2].has_attr("data-code") else ""
            title_td = tds[3]
            a = title_td.find("a", href=True)
            title = (a.get_text(strip=True) if a else title_td.get_text(strip=True))
            href = a["href"] if a else ""
            url_full = (
                f"https://kabutan.jp{href}" if href.startswith("/") else href
            )

            # 会社名はタイトル冒頭の "XXX、〜" 形式から推定
            name = title.split("、")[0] if "、" in title else ""

            if is_noise(title):
                continue

            cat = classify_by_title(title)
            # 区分が「決算」なら本決算系を優先
            if kind == "決算" and cat == "その他開示":
                cat = "本決算・四半期決算"

            items.append(
                {
                    "code": code,
                    "name": name,
                    "time": time_str,
                    "source": "kabutan",
                    "category": cat,
                    "description": title,
                    "metrics": None,
                    "url": url_full or "https://kabutan.jp/news/?category=4",
                    "kabutan_kind": kind,
                }
            )

    print(f"  [kabutan] {len(items)}件取得（最新日={latest_md}）", file=sys.stderr)
    return items, latest_md


# ─────────────────────────────────────────────────
# ソース3: ke.kabupro.jp/hist/today.htm
# ─────────────────────────────────────────────────

def fetch_kabupro() -> tuple[list[dict], str]:
    """
    決算プロの決算関連適時開示一覧（TDnet公開順）。
    today.htm がまだ空（深夜帯）なら、直近営業日の YYYYMMDD.htm を試す。
    return: (items, page_date_str)
    """
    candidates = ["http://ke.kabupro.jp/hist/today.htm"]
    # 念のため直近5営業日分のフォールバック
    base = datetime.datetime.now(JST).date()
    for back in range(1, 6):
        d = base - datetime.timedelta(days=back)
        candidates.append(f"http://ke.kabupro.jp/hist/{d.strftime('%Y%m%d')}.htm")

    for url in candidates:
        items, page_date = _fetch_kabupro_one(url)
        if items:
            return items, page_date
    return [], ""


def _fetch_kabupro_one(url: str) -> tuple[list[dict], str]:
    print(f"  [kabupro] {url} 取得中...", file=sys.stderr)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return [], ""
    except Exception as e:
        print(f"  [kabupro] 取得エラー: {e}", file=sys.stderr)
        return [], ""

    # Shift_JIS
    try:
        text = resp.content.decode("shift_jis")
    except UnicodeDecodeError:
        text = resp.text

    soup = BeautifulSoup(text, "html.parser")

    # 該当ページの日付（タイトルやH1から）
    page_date = ""
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", h1.get_text())
        if m:
            page_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 決算関連のテーブルを見つける（H1直下の最初の大きなテーブル）
    target_tbl = None
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if 20 < len(rows) < 250:
            first = rows[0].get_text(" ", strip=True)
            if "決算" in first and "業績" in first:
                target_tbl = tbl
                break
    if not target_tbl:
        return [], page_date

    items: list[dict] = []
    for tr in target_tbl.find_all("tr"):
        # 1セル目はTH（コード）、以降はTD。両方拾う
        cells = tr.find_all(["th", "td"])
        if len(cells) < 4:
            continue
        code_text = cells[0].get_text(strip=True)
        if not re.match(r"^\d{4}[A-Z]?$", code_text):
            continue  # 説明行は除外

        name = cells[1].get_text(strip=True)
        title_td = cells[2]
        a = title_td.find("a", href=True)
        title = a.get_text(strip=True) if a else title_td.get_text(strip=True)
        pdf_url = a["href"] if a else ""
        time_str = cells[3].get_text(strip=True)

        if is_noise(title):
            continue

        cat = classify_by_title(title)

        items.append(
            {
                "code": code_text,
                "name": name,
                "time": time_str,
                "source": "kabupro",
                "category": cat,
                "description": title,
                "metrics": None,
                "url": pdf_url or "http://ke.kabupro.jp/hist/today.htm",
            }
        )

    print(f"  [kabupro] {len(items)}件取得（page={page_date}）", file=sys.stderr)
    return items, page_date


# ─────────────────────────────────────────────────
# 統合・重複排除
# ─────────────────────────────────────────────────

SOURCE_PRIORITY = {"irbank": 1, "kabutan": 2, "kabupro": 3}

# チップ表示用ラベル
METRIC_LABELS = {"sales": "売上", "op": "営業益", "ord": "経常", "net": "純益"}


def extract_chips(metrics: dict | None) -> list[dict]:
    """irbankの数値dictから ±% チップ用の構造化データを抽出"""
    if not metrics:
        return []
    chips: list[dict] = []
    for key in ("sales", "op", "ord", "net"):
        v = metrics.get(key, "") or ""
        m = re.search(r"([+\-])(\d+(?:\.\d+)?)[％%]", v)
        if not m:
            continue
        sign = m.group(1)
        pct = float(m.group(2))
        direction = "up" if sign == "+" else "down"
        # 強度: ±30%以上をstrong, それ以外をnormal
        strength = "strong" if pct >= 30 else "normal"
        chips.append(
            {
                "label": METRIC_LABELS[key],
                "value": f"{sign}{m.group(2)}%",
                "direction": direction,
                "strength": strength,
                "pct": pct,
            }
        )
    return chips


def clean_narrative(text: str, company_name: str = "") -> str:
    """株探タイトルの冒頭「会社名、」プレフィックスを除去"""
    if not text:
        return ""
    # "オリコン、今期配当を見送り" -> "今期配当を見送り"
    if "、" in text[:24]:
        head, rest = text.split("、", 1)
        # 名前のような短いプレフィックスのときだけ削る
        if len(head) <= 16:
            return rest.strip()
    return text


def auto_summary_from_metrics(category: str, metrics: dict | None, chips: list[dict]) -> str:
    """ナラティブが無いときに、数値テンプレートから1行サマリーを生成"""
    if not metrics and not chips:
        return ""
    # 例: 大幅上方修正 → "経常+140.7% / 純益+139.5% の大幅増益修正"
    body = " / ".join(f"{c['label']}{c['value']}" for c in chips[:2]) if chips else ""
    period = metrics.get("period", "") if metrics else ""
    kind = metrics.get("type", "") if metrics else ""
    suffix = {
        "大幅上方修正": "の大幅増益修正",
        "上方修正": "の上方修正",
        "一転増益": "に一転増益",
        "一転最高益": "で最高益更新",
        "下方修正": "に下方修正",
        "本決算・四半期決算": "の業績着地",
    }.get(category, "")
    if body and suffix:
        return f"{body} {suffix}"
    if body:
        return body
    if period and kind:
        return f"{period} {kind}"
    return ""


def merge_items(*lists: list[dict]) -> list[dict]:
    """
    銘柄コード単位で全ソースをマージし、リッチエントリを生成。
    - カテゴリ: 全ソース中で最も優先度の高い（priority最小）ものを採用
    - ナラティブ: 株探（短く要約済み） > IRバンク > 決算プロの順
    - メトリクス: IRバンクのものを採用
    - チップ: メトリクスから抽出した ±% リスト
    - sources: 言及した全ソースのリスト
    """
    by_code: dict[str, list[dict]] = {}
    for lst in lists:
        for it in lst:
            by_code.setdefault(it["code"], []).append(it)

    final: list[dict] = []
    for code, items in by_code.items():
        # 採用カテゴリ
        best = min(items, key=lambda x: CATEGORY_PRIORITY.get(x["category"], 999))
        category = best["category"]

        # メトリクス（IRバンク由来）とチップ
        metrics = None
        for it in items:
            if it.get("metrics"):
                metrics = it["metrics"]
                break
        chips = extract_chips(metrics)

        # ナラティブ: 株探(短い要約) > 決算プロ(タイトル) > IRのテンプレ生成
        # IRはそのまま使うと冗長（数値の重複）なのでテンプレに任せる
        narrative_src = None
        narrative = ""
        for pref in ("kabutan", "kabupro"):
            for it in items:
                if it["source"] == pref and it.get("description"):
                    narrative = clean_narrative(it["description"], best.get("name", ""))
                    narrative_src = pref
                    break
            if narrative:
                break
        if not narrative:
            # IRしか無い場合は数値テンプレからサマリーを生成
            narrative = auto_summary_from_metrics(category, metrics, chips)
            narrative_src = "template"

        # ソース一覧
        sources = []
        for it in items:
            if it["source"] not in sources:
                sources.append(it["source"])

        # 代表URLは IR > 株探 > 決算プロの順
        url = ""
        for pref in ("irbank", "kabutan", "kabupro"):
            for it in items:
                if it["source"] == pref and it.get("url"):
                    url = it["url"]
                    break
            if url:
                break

        final.append(
            {
                "code": code,
                "name": best["name"],
                "time": best.get("time", ""),
                "category": category,
                "narrative": narrative,
                "narrative_source": narrative_src,
                "metrics": metrics,
                "chips": chips,
                "sources": sources,
                "primary_source": best["source"],
                "url": url,
            }
        )

    return final


# UIゾーン分類: positive / decision / negative / other
CATEGORY_ZONE: dict[str, str] = {
    "一転最高益": "positive",
    "上振れ最高益": "positive",
    "連続最高益": "positive",
    "一転増益": "positive",
    "大幅上方修正": "positive",
    "上方修正": "positive",
    "増配・配当修正": "positive",
    "黒字浮上": "positive",
    "本決算・四半期決算": "decision",
    "下方修正": "negative",
    "減配": "negative",
    "赤字・減益": "negative",
    "その他開示": "other",
}


def group_items(items: list[dict]) -> list[dict]:
    """カテゴリごとにグループ化。優先度順でソート＋ゾーン情報を付与"""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it["category"], []).append(it)
    # 各グループ内は時刻降順（新しいものを上に）
    for k, lst in groups.items():
        lst.sort(key=lambda x: x.get("time", ""), reverse=True)

    out = []
    for cat, lst in groups.items():
        prio = CATEGORY_PRIORITY.get(cat, 999)
        out.append(
            {
                "category": cat,
                "display": CATEGORY_DISPLAY.get(cat, cat),
                "priority": prio,
                "zone": CATEGORY_ZONE.get(cat, "other"),
                "items": lst,
            }
        )
    out.sort(key=lambda g: (g["priority"], g["category"]))
    return out


# ─────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────

def main() -> int:
    now = datetime.datetime.now(JST)
    print(f"[決算速報] {now.isoformat()} 実行開始", file=sys.stderr)

    ir_items, ir_date = fetch_irbank()
    time.sleep(0.4)
    ku_items, ku_md = fetch_kabutan()
    time.sleep(0.4)
    kp_items, kp_date = fetch_kabupro()

    merged = merge_items(ir_items, ku_items, kp_items)
    groups = group_items(merged)
    total = sum(len(g["items"]) for g in groups)

    # 表示用の article_date: irbankの最新日を優先（最も信頼できる日付）
    article_date = ir_date or kp_date
    if not article_date and ku_md:
        # kabutanのMM/DDをそのまま使う（年は今年）
        article_date = f"{now.year}-{ku_md.replace('/', '-')}"

    data: dict[str, Any] = {
        "updated_at": now.isoformat(),
        "article_date": article_date,
        "sources": ["irbank", "kabutan", "kabupro"],
        "source_counts": {
            "irbank": len(ir_items),
            "kabutan": len(ku_items),
            "kabupro": len(kp_items),
        },
        "source_dates": {
            "irbank": ir_date,
            "kabutan": ku_md,
            "kabupro": kp_date,
        },
        "groups": groups,
        "total": total,
    }

    out_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "earnings_flash.json")
    )

    print(
        f"[決算速報] 統合結果 total={total} groups={len(groups)} "
        f"(ir={len(ir_items)}, kabutan={len(ku_items)}, kabupro={len(kp_items)})",
        file=sys.stderr,
    )

    safe_save(
        out_path,
        data,
        lambda d: d.get("total", 0),
        label="決算速報",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
