#!/usr/bin/env python3
"""
本日の決算速報（サプライズ決算）取得スクリプト

データソース:
  kabutan.jp の「★本日の【サプライズ決算】速報」記事を毎日スクレイプし、
  業績修正・大幅増益・上方修正などサプライズ性のある決算を抽出する。

  記事は通常 大引け後（17時前後）に公開される。
  公開前のタイミングで実行された場合は、直近の公開済み記事をフォールバック使用する。

出力: data/earnings_flash.json
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time

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

KABUTAN_BASE = "https://kabutan.jp"
LISTING_URL = f"{KABUTAN_BASE}/news/?market=0&category=4"

# 各サプライズ種別のタグ表示順とラベル
# 数値が小さいほど優先表示
CATEGORY_PRIORITY: dict[str, int] = {
    "一転最高益": 10,
    "上振れ最高益": 12,
    "連続最高益": 14,
    "一転増益": 20,
    "大幅上方修正": 22,
    "上振れ着地": 24,
    "上方修正": 30,
    "大幅増益": 32,
    "増収増益": 40,
    "増配": 50,
    "配当増額": 52,
    "復配": 54,
    "黒字浮上": 60,
    "一転黒字": 62,
    "業績修正": 80,
}

# 章のヘッダ（◆ で始まる）からカテゴリを推定するキーワード
def category_tag(header: str) -> str:
    """`◆【一転増益】に上方修正した銘柄（サプライズ順）` → `一転増益` を返す"""
    m = re.search(r"【([^】]+)】", header)
    if m:
        return m.group(1).strip()
    # フォールバック: ◆ 以後の最初の語句
    cleaned = header.replace("◆", "").strip()
    return cleaned[:20]


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def find_latest_surprise_article() -> tuple[str, str] | None:
    """
    決算ニュース一覧から最新の「サプライズ決算速報」記事を1件探す。
    return: (article_url, title) または None
    """
    print("  [決算速報] 一覧ページ取得中...", file=sys.stderr)
    html = fetch(LISTING_URL)
    soup = BeautifulSoup(html, "html.parser")

    candidates: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if "サプライズ決算" not in title:
            continue
        if "/news/marketnews/?b=" not in href:
            continue
        candidates.append((href, title))

    if not candidates:
        print("  [決算速報] サプライズ記事が見つかりませんでした", file=sys.stderr)
        return None

    # 一覧の上から順 = 新しい順なので先頭を採用
    href, title = candidates[0]
    if href.startswith("/"):
        href = KABUTAN_BASE + href
    print(f"  [決算速報] 発見: {title}", file=sys.stderr)
    return href, title


def parse_article(url: str) -> dict:
    """
    記事本文をパースし、サプライズ決算銘柄をカテゴリ毎に分類して返す。
    """
    print(f"  [決算速報] 記事取得: {url}", file=sys.stderr)
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    article = soup.find("article")
    if not article:
        raise RuntimeError("article要素が見つかりません")

    # 記事タイトル
    h1 = article.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    # 記事公開日時
    time_tag = article.find("time", class_="s_news_date")
    published_at = ""
    if time_tag:
        ts = time_tag.get_text(strip=True)
        # 例: "2026年05月28日17時07分"
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分", ts)
        if m:
            y, mo, d, hh, mm = (int(x) for x in m.groups())
            published_at = datetime.datetime(
                y, mo, d, hh, mm, tzinfo=JST
            ).isoformat()

    # 記事日付（タイトル "(05月28日)" から抽出）。なければ公開日時から
    article_date = ""
    md = re.search(r"\((\d{1,2})月(\d{1,2})日\)", title)
    if md and time_tag:
        m = re.match(r"(\d{4})年", time_tag.get_text(strip=True))
        if m:
            article_date = f"{m.group(1)}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"
    if not article_date and published_at:
        article_date = published_at[:10]

    # 本文 .mono
    mono = article.find("div", class_="mono")
    if not mono:
        raise RuntimeError("本文(.mono)が見つかりません")

    body_text = mono.get_text("\n", strip=True)

    # セクション 1)発表済 だけを切り出す。2)以降は明日の予定なので不要
    # 区切りは「２）」or「2）」
    section_match = re.search(r"(?ms)１）(.*?)(?:^|\n)\s*[２2]）", body_text)
    if section_match:
        section1 = section_match.group(1)
    else:
        # 区切りが無い場合は全体を対象
        section1 = body_text

    # `◆【...】...` で始まる小見出しごとに切り分ける
    # 小見出しの前にある文字列は無視
    lines = section1.splitlines()
    groups: dict[str, list[dict]] = {}
    current_header: str | None = None
    buffer: list[str] = []

    def flush(header: str | None, lines_buf: list[str]) -> None:
        if not header or not lines_buf:
            return
        # buffer は数行が1銘柄を構成する。コード行(数字のみ)を起点にまとめる
        # 期待される並び（line by line, 空白trim済）:
        #   名前
        #   <
        #   コード
        #   > [市場]
        #   修正内容説明（1〜複数行）
        # 連結して "<code> 名前 [市場] 説明" 形式の文字列にしてから正規表現で抽出する。
        joined = " ".join(s.strip() for s in lines_buf if s.strip())
        # `<` と `>` の間のコード周辺の空白を畳む
        joined = re.sub(r"<\s*", "<", joined)
        joined = re.sub(r"\s*>", ">", joined)

        # 銘柄エントリのパターン:
        #   会社名 <CODE> [市場]  説明...
        # 説明は次のエントリ手前まで貪欲一致を避けて非貪欲で取る。
        # 名前は <CODE> の直前の連続した非空白＋全角文字列。
        # tokenize アプローチ: <数字> [市場] の位置をすべて取り、間を切る
        positions = list(re.finditer(r"<(\d{3,5}[A-Z]?)>\s*\[([^\]]+)\]", joined))
        if not positions:
            return
        category = category_tag(header)
        for i, m in enumerate(positions):
            code = m.group(1)
            market = m.group(2)
            # 名前は直前 m.start() より前の最後の空白以後〜直前まで
            before = joined[: m.start()].rstrip()
            # 前のエントリ末尾の説明文を除く: 前のエントリの市場 `]` 以降を切り捨て
            prev_end_idx = positions[i - 1].end() if i > 0 else 0
            before_segment = joined[prev_end_idx : m.start()].rstrip()
            # 会社名は before_segment の末尾トークン
            name_match = re.search(r"([\w぀-ヿ㐀-鿿・ー’＆\&\(\)（）]+)\s*$", before_segment)
            name = name_match.group(1) if name_match else ""

            # 説明は当該マッチの直後〜次のマッチ手前まで
            next_start = positions[i + 1].start() if i + 1 < len(positions) else len(joined)
            # 次のエントリ手前にある会社名トークンは説明から除く
            desc_seg = joined[m.end() : next_start]
            if i + 1 < len(positions):
                # 次のエントリの名前トークンを取り除く
                next_name_match = re.search(
                    r"([\w぀-ヿ㐀-鿿・ー’＆\&\(\)（）]+)\s*$",
                    joined[m.end() : next_start].rstrip(),
                )
                if next_name_match:
                    desc_seg = desc_seg[: desc_seg.rstrip().rfind(next_name_match.group(1))]
            description = re.sub(r"\s+", " ", desc_seg).strip()

            groups.setdefault(category, []).append(
                {
                    "code": code,
                    "name": name,
                    "market": market,
                    "category": category,
                    "category_label": header.replace("◆", "").strip(),
                    "description": description,
                }
            )

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("◆"):
            # 直前グループをflush
            flush(current_header, buffer)
            current_header = line
            buffer = []
            continue
        if current_header is not None:
            buffer.append(line)

    flush(current_header, buffer)

    # カテゴリ順序（優先度）でソートしたグループリストを生成
    grouped_list = []
    for cat, items in groups.items():
        prio = CATEGORY_PRIORITY.get(cat, 999)
        grouped_list.append({"category": cat, "priority": prio, "items": items})
    grouped_list.sort(key=lambda g: (g["priority"], g["category"]))

    total = sum(len(g["items"]) for g in grouped_list)
    print(f"  [決算速報] パース完了: {total}件 / {len(grouped_list)}カテゴリ", file=sys.stderr)

    return {
        "title": title,
        "source_url": url,
        "published_at": published_at,
        "article_date": article_date,
        "groups": grouped_list,
        "total": total,
    }


def main() -> int:
    now = datetime.datetime.now(JST)
    print(f"[決算速報] {now.isoformat()} 実行開始", file=sys.stderr)

    try:
        found = find_latest_surprise_article()
        if not found:
            # 取得失敗扱い: 既存データを温存
            data = {
                "updated_at": now.isoformat(),
                "groups": [],
                "total": 0,
                "note": "サプライズ決算速報の記事が見つかりませんでした",
            }
        else:
            url, _title = found
            parsed = parse_article(url)
            time.sleep(0.3)
            data = {
                "updated_at": now.isoformat(),
                **parsed,
            }
    except Exception as e:
        print(f"  [決算速報] 取得エラー: {e}", file=sys.stderr)
        data = {
            "updated_at": now.isoformat(),
            "groups": [],
            "total": 0,
            "error": str(e),
        }

    out_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "earnings_flash.json"
    )
    out_path = os.path.normpath(out_path)

    safe_save(
        out_path,
        data,
        lambda d: d.get("total", 0),
        label="決算速報",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
