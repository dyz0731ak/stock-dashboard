#!/usr/bin/env python3
"""
プリレンダリング（SSG）: data/*.json の中身を index.html に「焼き込む」。

投資の砦は app.js がデータを後から描画する SPA のため、Googlebot が最初に受け取る
HTML が空に近く、検索インデックスされない。そこでビルド時（cron のデータ取得後）に
本スクリプトを実行し、各セクションの中身入り HTML を index.html のマーカー間へ差し込む。
これにより「最初のHTMLに見出し・銘柄名・数値・テーブルが入った」状態でデプロイされ、
検索エンジンにクロール・インデックスされる。app.js は従来どおりライブ更新を担う。

冪等: <!--PRERENDER:KEY--> 〜 <!--/PRERENDER:KEY--> の間だけを置換するので、
何度実行しても二重挿入されない。
"""

import json
import os
import re
import html
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
INDEX = os.path.join(ROOT, "index.html")
SITEMAP = os.path.join(ROOT, "sitemap.xml")
BASE_URL = "https://dashboard.stock-overflow24.com"
ADSENSE_CLIENT = "ca-pub-8504127793204920"
GA_ID = os.environ.get("GA4_ID", "")

FIXED_PAGES = [
    ("stop-high", "今日のストップ高銘柄", "ストップ高銘柄"),
    ("top-gainers", "今日の急騰銘柄ランキング", "急騰銘柄ランキング"),
    ("volume-surge", "出来高急増銘柄", "出来高急増"),
    ("earnings", "本日の決算速報", "決算速報"),
]


def adsense_head():
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
            f'?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>')


def ga_head():
    if not GA_ID:
        return ""
    return f"""<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{GA_ID}');</script>"""


def load(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def esc(s):
    return html.escape(str(s if s is not None else ""))


def flash_reference_links(item):
    code = re.sub(r"[^0-9A-Z]", "", str(item.get("code") or ""), flags=re.I)
    original = str(item.get("url") or "")
    document_url = str(item.get("document_url") or "")
    if not document_url:
        match = re.search(r"/(1401\d{14,})\.pdf(?:\?.*)?$", original, re.I)
        if match:
            document_url = (
                "https://www.release.tdnet.info/inbs/"
                f"{match.group(1)}.pdf"
            )
        elif re.match(r"^https?://.+\.pdf(?:\?.*)?$", original, re.I):
            document_url = original
    article_url = str(item.get("article_url") or "")
    if not article_url and original and not document_url:
        article_url = original
    candidates = [
        (document_url, "決算短信・適時開示PDF", True),
        (article_url, "決算速報・解説を読む", False),
        (
            str(item.get("ir_url") or "")
            or (f"https://irbank.net/{code}/ir" if code else ""),
            "過去の決算資料",
            False,
        ),
        (
            str(item.get("news_url") or "")
            or (
                f"https://s.kabutan.jp/stocks/{code}/news/"
                "?news_category_id=3"
                if code else ""
            ),
            "関連する決算記事",
            False,
        ),
    ]
    links = []
    seen = set()
    for url, label, primary in candidates:
        if not re.match(r"^https?://", url, re.I) or url in seen:
            continue
        seen.add(url)
        links.append((url, label, primary))
    return links


def fmt(n, dec=0):
    if n is None:
        return "—"
    try:
        return f"{float(n):,.{dec}f}"
    except Exception:
        return esc(n)


def pcttxt(v):
    try:
        v = float(v)
        return ("+" if v > 0 else "") + f"{v:.2f}%"
    except Exception:
        return esc(v)


def sign_cls(v):
    try:
        v = float(v)
        return "up" if v > 0 else "down" if v < 0 else "flat"
    except Exception:
        return "flat"


def pct_badge_style(pct):
    try:
        p = float(pct)
    except Exception:
        p = 0
    if p > 0:
        return "background:var(--up-soft);color:var(--up)"
    if p < 0:
        return "background:var(--down-soft);color:var(--down)"
    return "background:#eef1f5;color:var(--ink-3)"


def is_fresh(data, max_hours):
    if not data or data.get("fetch_status") == "stale":
        return False
    try:
        updated = datetime.datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=JST)
        return (datetime.datetime.now(datetime.timezone.utc) - updated.astimezone(
            datetime.timezone.utc
        )).total_seconds() <= max_hours * 3600
    except Exception:
        return False


# ─────────────────────────────────────────────
# 各セクションの HTML 生成
# ─────────────────────────────────────────────
def build_idx(futures):
    if not futures or not futures.get("items"):
        return ""
    out = []
    for it in futures["items"]:
        pct = it.get("pct", 0)
        cls = sign_cls(pct)
        ch = it.get("change", 0)
        arrow = "▲" if (ch or 0) > 0 else "▼" if (ch or 0) < 0 else ""
        out.append(
            f'<div class="idx-card"><div class="head">'
            f'<span class="label">{esc(it.get("label"))}</span>'
            f'<span class="pct-badge" style="{pct_badge_style(pct)}">{pcttxt(pct)}</span></div>'
            f'<div class="price num {cls}">{fmt(it.get("price"), it.get("decimals", 0))}</div>'
            f'<div class="change num {sign_cls(ch)}">{arrow} {fmt(abs(ch or 0), it.get("decimals", 0))}</div></div>'
        )
    return "\n".join(out)


def build_rank(japan):
    if not is_fresh(japan, 36) or not japan.get("all_stocks"):
        return ""
    rows = sorted([s for s in japan["all_stocks"] if s.get("change_pct") is not None],
                  key=lambda s: -float(s["change_pct"]))[:30]
    body = []
    st_tag = '<span class="st-tag">S高</span>'
    for s in rows:
        pct = float(s["change_pct"])
        st = st_tag if s.get("is_stop_high") else ""
        body.append(
            f'<tr><td class="t-code">{esc(s.get("code"))}</td>'
            f'<td><div class="t-name">{esc(s.get("name"))}</div>'
            f'<div class="t-sec">{esc(s.get("sector",""))}</div></td>'
            f'<td><span class="pill-mkt">{esc(s.get("market",""))}</span></td>'
            f'<td class="r num">{fmt(s.get("price"))}円</td>'
            f'<td class="r num {sign_cls(pct)}">{esc(s.get("change_amount",""))}</td>'
            f'<td class="r num {sign_cls(pct)}"><b>{pcttxt(pct)}</b></td>'
            f'<td class="r">{st}</td></tr>'
        )
    return ('<table class="rank"><thead><tr><th>コード</th><th>銘柄</th><th>市場</th>'
            '<th class="r">株価</th><th class="r">前日比</th><th class="r">騰落率</th>'
            '<th class="r">状態</th></tr></thead><tbody>' + "".join(body) + "</tbody></table>")


def build_themes(themes):
    if not themes or not themes.get("themes"):
        return ""
    ts = sorted(themes["themes"], key=lambda x: -x.get("week_pct", 0))[:12]
    body = []
    for i, th in enumerate(ts):
        chips = "".join(
            f'<span class="theme-chip"><b>{esc(m.get("name"))}</b> '
            f'<span class="{sign_cls(m.get("week_pct"))}">{pcttxt(m.get("week_pct"))}</span></span>'
            for m in (th.get("top") or [])[:3]
        )
        topcls = " top" if i < 3 else ""
        badge = '<span class="hot-badge">注目度急上昇中</span><br>' if th.get("hot") else ""
        body.append(
            f'<tr><td><span class="rank-no{topcls}">{i+1}</span></td>'
            f'<td><div class="t-name">{badge}{esc(th.get("name"))}</div></td>'
            f'<td></td>'
            f'<td class="r num {sign_cls(th.get("week_pct"))}"><b>{pcttxt(th.get("week_pct"))}</b></td>'
            f'<td class="r num {sign_cls(th.get("month_pct"))}">{pcttxt(th.get("month_pct"))}</td>'
            f'<td class="r num {sign_cls(th.get("day_pct"))}">{pcttxt(th.get("day_pct"))}</td>'
            f'<td class="r num">{fmt(th.get("win_rate"),0)}%</td>'
            f'<td class="r num">{th.get("count","")}社</td>'
            f'<td><div class="theme-chips">{chips}</div></td></tr>'
        )
    return ('<table class="rank"><thead><tr><th style="width:40px">#</th><th>テーマ</th>'
            '<th style="width:70px">推移</th><th class="r">1週間</th><th class="r">1ヶ月</th>'
            '<th class="r">前日比</th><th class="r">勝率</th><th class="r">銘柄</th>'
            '<th>注目銘柄</th></tr></thead><tbody>' + "".join(body) + "</tbody></table>")


def build_events(events):
    if not events or not events.get("economic"):
        return ""
    wd = ["月", "火", "水", "木", "金", "土", "日"]  # weekday(): 月=0 … 日=6

    def evdate(d):
        try:
            y, m, da = (int(x) for x in d.split("-"))
            return f"{m}/{da}({wd[datetime.date(y, m, da).weekday()]})"
        except Exception:
            return esc(d)

    rows = []
    for e in sorted(events["economic"], key=lambda x: x.get("datetime_jst") or "")[:24]:
        parts = []
        if e.get("actual"):
            parts.append(f'結果 <b class="{sign_cls(0)}">{esc(e["actual"])}</b>')
        if e.get("forecast"):
            parts.append(f'予想 <span class="num">{esc(e["forecast"])}</span>')
        if e.get("prior"):
            parts.append(f'前回 <span class="num">{esc(e["prior"])}</span>')
        metrics = ('<div class="ev-metrics">' + "・".join(parts) + "</div>") if parts else ""
        status = ('<span class="ev-status done">発表済み</span>' if e.get("status") == "released"
                  else '<span class="ev-status soon">発表前</span>')
        stars = "★" * int(e.get("stars") or 0)
        rows.append(
            f'<div class="row-item ev-row"><span class="r-datetime">'
            f'<span class="r-d">{evdate(e.get("date",""))}</span>'
            f'<span class="r-t num">{esc(e.get("time_jst",""))}</span></span>'
            f'<span class="r-tag" style="min-width:40px;text-align:center">{esc((e.get("country_label") or "")[:3])}</span>'
            f'<div class="ev-body"><div class="r-name">{esc(e.get("event_ja") or e.get("event"))}</div>{metrics}</div>'
            f'{status}<span class="ev-stars">{stars}</span></div>'
        )
    return "".join(rows)


def build_market_news(news):
    if not news or not news.get("items"):
        return ""
    cards = []
    for index, item in enumerate(news["items"][:10]):
        sectors = "".join(
            f"<span>{esc(sector)}</span>" for sector in (item.get("watch_sectors") or [])[:4]
        )
        cards.append(
            f'<a class="market-news-card{" lead" if index == 0 else ""}" '
            f'href="{esc(item.get("url") or "#")}" target="_blank" rel="noopener">'
            f'<div class="market-news-meta"><span class="market-topic">{esc(item.get("topic") or "市場全体")}</span>'
            f'<span>{esc(item.get("source_label") or "主要メディア")}</span>'
            f'<time>{esc(item.get("date") or "")}</time></div>'
            f'<h3>{esc(item.get("title") or "")}</h3>'
            f'<div class="market-impact"><b>日本株への見方</b>'
            f'<p>{esc(item.get("impact_summary") or "")}</p></div>'
            f'<div class="market-news-foot"><div class="market-sectors">{sectors}</div>'
            f'<span class="market-read">記事を読む</span></div></a>'
        )
    return "".join(cards)


def build_flash(flash):
    if not flash:
        return ""
    items = flash.get("highlights") or [
        item for group in (flash.get("groups") or []) for item in (group.get("items") or [])
    ]
    if not items:
        return '<div class="skeleton">重要決算を確認中です</div>'
    out = ['<div class="flash-list">']
    for it in items[:12]:
        reference_buttons = []
        for url, label, primary in flash_reference_links(it):
            cls = " primary" if primary else ""
            reference_buttons.append(
                f'<a class="flash-detail-link{cls}" href="{esc(url)}" '
                f'target="_blank" rel="noopener"><span>{esc(label)}</span>'
                f'<span aria-hidden="true">↗</span></a>'
            )
        chips = []
        for chip in it.get("chips") or []:
            cls = "pos" if chip.get("direction") == "up" else "neg" if chip.get("direction") == "down" else ""
            chips.append(
                f'<span class="chip {cls}">{esc(chip.get("label"))} {esc(chip.get("value"))}</span>'
            )
        out.append(
            f'<article class="flash-item {esc(it.get("impact_zone") or "decision")}" '
            f'tabindex="0" role="button" aria-expanded="false">'
            f'<div class="flash-top"><span class="nm">{esc(it.get("name"))}</span>'
            f'<span class="code">{esc(it.get("code"))}</span>'
            f'<span class="flash-published">{esc(it.get("published_label") or "")}</span>'
            f'<span class="impact-label">{esc(it.get("impact_label") or "注目決算")}</span></div>'
            f'<div class="nar">{esc(it.get("narrative"))}</div>'
            f'<div class="chips">{"".join(chips)}</div>'
            f'<div class="impact-summary">{esc(it.get("impact_summary") or "通期計画への進捗と今後の見通しを確認したい決算です。")}</div>'
            f'<div class="flash-chart-toggle">詳細・根拠を見る</div>'
            f'<div class="flash-detail-panel" hidden><div class="flash-reference">'
            f'<div class="flash-detail-title">根拠資料・関連記事</div>'
            f'<div class="flash-detail-note">表示内容は決算短信・適時開示をもとに整理しています。'
            f'数値や会社予想は原資料でもご確認ください。</div>'
            f'<div class="flash-detail-links">{"".join(reference_buttons)}</div>'
            f'</div><div class="flash-chart-panel"><div class="flash-chart-head">'
            f'<span class="flash-chart-title">3か月日足（約65営業日）</span>'
            f'</div><div class="mini-nochart">チャートを読み込み中</div></div></div>'
            f'</article>'
        )
    out.append("</div>")
    return "".join(out)


def build_news(news):
    if not is_fresh(news, 12) or not news.get("items"):
        return ""
    rows = []
    for it in news["items"]:
        d = (it.get("date") or "").split(" ")[0]
        rows.append(
            f'<a class="row-item" href="{esc(it.get("url","#"))}" target="_blank" rel="noopener">'
            f'<span class="r-date">{esc(d)}</span>'
            f'<span class="r-name">{esc(it.get("title"))}</span>'
            f'<span class="r-tag">{esc(it.get("source_label") or it.get("source",""))}</span></a>'
        )
    return "".join(rows)


def build_earn(events):
    if not events:
        return '<div class="skeleton">本日の日本株決算予定はありません</div>'
    lst = events.get("jp_earnings") or []
    rows = []
    for it in lst[:12]:
        ident = it.get("code")
        tag = it.get("time_jst_label") or it.get("quarter") or ""
        tagspan = f'<span class="r-tag">{esc(tag)}</span>' if tag else ""
        rows.append(
            f'<div class="row-item"><span class="r-code">{esc(ident)}</span>'
            f'<span class="r-name">{esc(it.get("name"))}</span>'
            f'{tagspan}</div>'
        )
    return "".join(rows) or '<div class="skeleton">本日の日本株決算予定はありません</div>'


def build_themelinks(themes):
    """フッターのテーマ株リンク（クロール導線）。週間騰落率順。"""
    links = '<span class="ft-label">毎日見るページ</span>'
    links += "".join(f'<a href="/{slug}/">{esc(label)}</a>' for slug, _title, label in FIXED_PAGES)
    if not themes or not themes.get("themes"):
        return links
    import prerender_themes as pt
    ts = sorted([t for t in themes["themes"] if pt.SLUGS.get(t["name"])],
                key=lambda x: -(x.get("week_pct") or 0))
    links += '<span class="ft-label">テーマ株から探す</span>'
    links += "".join(f'<a href="/themes/{pt.SLUGS[t["name"]]}/">{esc(t["name"])}関連株</a>' for t in ts)
    links += '<a href="/themes/"><b>テーマ株一覧 ›</b></a>'
    return links


def build_heat(nikkei):
    if not nikkei or not nikkei.get("items"):
        return ""
    items = sorted([s for s in nikkei["items"] if s.get("market_cap")],
                   key=lambda s: -s["market_cap"])[:60]
    spans = "".join(
        f'<span><b>{esc(s.get("name"))}</b>'
        f'<span class="p {sign_cls(s.get("change_pct"))}">{pcttxt(s.get("change_pct"))}</span></span>'
        for s in items
    )
    return f'<div class="hm-fallback">{spans}</div>'


def as_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default


def stock_label(s):
    code = s.get("code") or s.get("symbol") or s.get("ticker") or ""
    name = s.get("name") or s.get("company") or s.get("company_name") or ""
    return code, name


def market_page_nav(current):
    links = []
    for slug, _title, label in FIXED_PAGES:
        attr = ' aria-current="page"' if slug == current else ""
        links.append(f'<a href="/{slug}/"{attr}>{esc(label)}</a>')
    return '<div class="rel">' + "".join(links) + '</div>'


def fixed_table(headers, rows, empty):
    if not rows:
        return f'<div class="lead">{esc(empty)}</div>'
    head = "".join(f'<th class="{cls}">{esc(label)}</th>' for label, cls in headers)
    body = "".join(rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def jp_stock_table(stocks, empty):
    rows = []
    for i, s in enumerate(stocks[:30]):
        code, name = stock_label(s)
        pct = as_float(s.get("change_pct"), 0)
        status = '<span class="up">S高</span>' if s.get("is_stop_high") else ""
        rows.append(
            f'<tr><td class="r">{i+1}</td><td><b>{esc(name)}</b><br><span style="color:var(--ink-3);font-size:12px">{esc(s.get("sector",""))}</span></td>'
            f'<td class="r">{esc(code)}</td><td class="r">{fmt(s.get("price"))}円</td>'
            f'<td class="r {sign_cls(pct)}"><b>{pcttxt(pct)}</b></td><td class="r">{status}</td></tr>'
        )
    return fixed_table(
        [("#", "r"), ("銘柄", ""), ("コード", "r"), ("株価", "r"), ("騰落率", "r"), ("状態", "r")],
        rows,
        empty,
    )


def us_stock_table(stocks, empty):
    rows = []
    for i, s in enumerate(stocks[:30]):
        code, name = stock_label(s)
        pct = as_float(s.get("change_pct") or s.get("changesPercentage"), 0)
        price = s.get("price") or s.get("last_price") or s.get("regularMarketPrice")
        rows.append(
            f'<tr><td class="r">{i+1}</td><td><b>{esc(name or code)}</b></td>'
            f'<td class="r">{esc(code)}</td><td class="r">{fmt(price, 2)}</td>'
            f'<td class="r {sign_cls(pct)}"><b>{pcttxt(pct)}</b></td></tr>'
        )
    return fixed_table(
        [("#", "r"), ("銘柄", ""), ("ティッカー", "r"), ("株価", "r"), ("騰落率", "r")],
        rows,
        empty,
    )


def volume_table(volume):
    jp = (volume or {}).get("jp_stocks") or []
    stocks = [(s, "日本株") for s in jp]
    if not stocks:
        stocks = [(s, "日本株") for s in ((volume or {}).get("items") or [])]
    rows = []
    for i, (s, market) in enumerate(stocks[:30]):
        code, name = stock_label(s)
        pct = as_float(s.get("change_pct"), 0)
        vol = s.get("volume_today") or s.get("volume") or s.get("出来高") or ""
        ratio = s.get("volume_ratio") or s.get("ratio") or s.get("volume_change_pct") or ""
        price_unit = "円" if market == "日本株" else "ドル"
        rows.append(
            f'<tr><td class="r">{i+1}</td><td>{market}</td><td><b>{esc(name)}</b></td><td class="r">{esc(code)}</td>'
            f'<td class="r">{fmt(s.get("price"), 0 if market == "日本株" else 2)}{price_unit}</td><td class="r {sign_cls(pct)}"><b>{pcttxt(pct)}</b></td>'
            f'<td class="r">{esc(vol)}</td><td class="r">{esc(ratio)}</td></tr>'
        )
    return fixed_table(
        [("#", "r"), ("市場", ""), ("銘柄", ""), ("コード", "r"), ("株価", "r"), ("騰落率", "r"), ("出来高", "r"), ("急増度", "r")],
        rows,
        "出来高急増データは次回の自動更新後に表示されます。トップページのリアルタイム欄もあわせて確認してください。",
    )


def earnings_table(events, flash):
    rows = []
    for g in (flash or {}).get("groups") or []:
        label = g.get("display") or g.get("label") or "決算速報"
        for it in (g.get("items") or [])[:12]:
            code = it.get("code") or it.get("symbol") or ""
            name = it.get("name") or ""
            chips = " / ".join(f'{c.get("label","")} {c.get("value","")}' for c in (it.get("chips") or []))
            rows.append(
                f'<tr><td>{esc(label)}</td><td class="r">{esc(it.get("time",""))}</td>'
                f'<td><b>{esc(name)}</b></td><td class="r">{esc(code)}</td>'
                f'<td>{esc(it.get("narrative") or chips)}</td></tr>'
            )
    if not rows:
        for it in ((events or {}).get("jp_earnings") or [])[:30]:
            code = it.get("code") or ""
            rows.append(
                f'<tr><td>{esc(it.get("market","決算予定"))}</td><td class="r">{esc(it.get("time_jst_label") or it.get("quarter") or "")}</td>'
                f'<td><b>{esc(it.get("name"))}</b></td><td class="r">{esc(code)}</td><td>{esc(it.get("memo",""))}</td></tr>'
            )
    return fixed_table(
        [("区分", ""), ("時刻", "r"), ("銘柄", ""), ("コード", "r"), ("内容", "")],
        rows,
        "決算速報データは次回の自動更新後に表示されます。",
    )


def fixed_page_html(slug, title, desc, lead, updated, content):
    import prerender_themes as pt
    url = f"{BASE_URL}/{slug}/"
    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "url": url,
        "description": desc,
        "inLanguage": "ja",
        "isPartOf": {"@type": "WebSite", "name": "投資の砦", "url": BASE_URL + "/"},
    }
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{esc(title)}｜投資の砦</title>
<meta name="description" content="{esc(desc)}"/>
<meta name="robots" content="index, follow"/>
<link rel="canonical" href="{url}"/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{url}"/>
<meta property="og:title" content="{esc(title)}｜投資の砦"/>
<meta property="og:description" content="{esc(desc)}"/>
<meta property="og:image" content="{BASE_URL}/ogp.png"/>
<meta property="og:site_name" content="投資の砦"/>
<meta property="og:locale" content="ja_JP"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{esc(title)}｜投資の砦"/>
<meta name="twitter:description" content="{esc(desc)}"/>
<meta name="twitter:image" content="{BASE_URL}/ogp.png"/>
{adsense_head()}
{ga_head()}
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<style>{pt.CSS}</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<a href="{BASE_URL}/" class="brand"><span class="brand-word">投資の<span>砦</span></span></a>
</div></header>
<div class="wrap">
<nav class="crumb"><a href="{BASE_URL}/">ホーム</a> › {esc(title)}</nav>
<h1>{esc(title)}</h1>
<p class="sub">更新日 {esc(updated)}（定期更新・各ページの参照データ時刻）</p>
<div class="lead">{esc(lead)}</div>
{content}
<h2>ほかの日本株データを見る</h2>
{market_page_nav(slug)}
</div>
<footer><div class="foot-inner">© 投資の砦 ｜ 情報提供のみを目的とし、投資判断はご自身の責任で。</div></footer>
</body>
</html>
"""


def write_fixed_pages(japan, volume, events, flash):
    today = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    def data_date(data):
        return ((data or {}).get("updated_at") or today)[:10]

    all_jp = (japan or {}).get("all_stocks") or []
    top_jp = sorted([s for s in all_jp if as_float(s.get("change_pct")) is not None],
                    key=lambda s: as_float(s.get("change_pct"), -999), reverse=True)
    stop_high = [s for s in top_jp if s.get("is_stop_high")]
    jp_fallback = bool((japan or {}).get("is_fallback"))
    jp_scope = (japan or {}).get("scope") or "国内株・全市場"
    jp_source = (japan or {}).get("source_label") or "ランキング取得元"
    if jp_fallback:
        stop_lead = "全市場のストップ高データは現在取得確認中です。代替ランキングをストップ高として扱っていません。"
        stop_content = jp_stock_table([], "本日のストップ高は取得確認中です。古いデータや代替データは表示していません。")
    else:
        stop_lead = f"本日のストップ高は{(japan or {}).get('stop_high_count', len(stop_high))}銘柄。値幅制限に到達した銘柄を急騰率順にまとめています。出典: {jp_source}"
        stop_content = jp_stock_table(stop_high, "本日のストップ高該当銘柄はありません。")
    volume_warning = (volume or {}).get("fetch_warning")
    if not volume_warning and (volume or {}).get("jp_count", 0) == 0:
        volume_warning = "日本株の出来高ランキングは取得確認中です"
    payloads = {
        "stop-high": (
            "今日のストップ高銘柄",
            "本日のストップ高銘柄を一覧で確認できます。株価・騰落率・業種を自動更新し、短期資金が集まる銘柄を素早く把握できます。",
            stop_lead,
            stop_content,
        ),
        "top-gainers": (
            "今日の急騰銘柄ランキング",
            "日本株の急騰銘柄を騰落率順にランキング表示。株価・業種・ストップ高到達有無を自動更新します。",
            f"{jp_scope}の値上がり率上位を一覧化しています。出典: {jp_source}。"
            + (" 全市場データ取得停止中のため、対象を限定した代替表示です。" if jp_fallback else ""),
            jp_stock_table(top_jp, "急騰銘柄データは次回の自動更新後に表示されます。"),
        ),
        "volume-surge": (
            "出来高急増銘柄",
            "出来高が急増した日本株を一覧化。値動きだけでなく売買代金や市場参加者の注目度を確認できます。",
            f"日本株の出来高急増データを定期更新しています。現在の取得件数は{(volume or {}).get('jp_count', 0)}件です。"
            + (f" 注意: {volume_warning}。" if volume_warning else ""),
            volume_table(volume),
        ),
        "earnings": (
            "本日の決算速報",
            "日本株の決算速報を一覧化。サプライズ決算や市場への影響が大きい発表を確認できます。",
            f"日本株の重要決算速報を自動更新しています。現在の速報件数は{(flash or {}).get('total', 0)}件です。",
            earnings_table({}, flash),
        ),
    }
    updates = {
        "stop-high": data_date(japan),
        "top-gainers": data_date(japan),
        "volume-surge": data_date(volume),
        "earnings": data_date(flash),
    }
    written = []
    for slug, _title, _label in FIXED_PAGES:
        title, desc, lead, content = payloads[slug]
        d = os.path.join(ROOT, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(fixed_page_html(slug, title, desc, lead, updates[slug], content))
        written.append(slug)
    print(f"  ✓ [固定SEOページ] {len(written)} ページを生成")
    return written


def write_sitemap(theme_slugs=None, fixed_slugs=None):
    """sitemap.xml を生成。トップは毎日データ更新されるので lastmod=当日(JST)・changefreq=daily。
    /about/ は内容がほぼ不変なのでファイルの更新日を lastmod にする（毎日変わったと誤認させない）。
    theme_slugs を渡すと /themes/ ハブ + 各テーマページも収録する。"""
    today = datetime.datetime.now(JST).strftime("%Y-%m-%d")
    try:
        mtime = os.path.getmtime(os.path.join(ROOT, "about", "index.html"))
        about_lastmod = datetime.datetime.fromtimestamp(mtime, JST).strftime("%Y-%m-%d")
    except Exception:
        about_lastmod = today
    urls = [
        (f"{BASE_URL}/", today, "daily", "1.0"),
        (f"{BASE_URL}/about/", about_lastmod, "monthly", "0.7"),
    ]
    if fixed_slugs:
        for slug in fixed_slugs:
            urls.append((f"{BASE_URL}/{slug}/", today, "daily", "0.85"))
    if theme_slugs:
        urls.append((f"{BASE_URL}/themes/", today, "daily", "0.8"))
        for slug in theme_slugs:
            urls.append((f"{BASE_URL}/themes/{slug}/", today, "daily", "0.7"))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod, freq, pr in urls:
        out.append(f'  <url>\n    <loc>{loc}</loc>\n    <lastmod>{lastmod}</lastmod>'
                   f'\n    <changefreq>{freq}</changefreq>\n    <priority>{pr}</priority>\n  </url>')
    out.append('</urlset>')
    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"  ✓ [サイトマップ] sitemap.xml を更新（トップ lastmod={today}）")


def replace_marker(html_text, key, content):
    pat = re.compile(rf"(<!--PRERENDER:{key}-->).*?(<!--/PRERENDER:{key}-->)", re.S)
    if not pat.search(html_text):
        print(f"  ⚠ マーカー PRERENDER:{key} が見つからない")
        return html_text
    return pat.sub(lambda m: m.group(1) + "\n" + content + "\n" + m.group(2), html_text)


def move_section_after(html_text, section_id, target_id):
    """指定セクションを対象セクションの直後へ移し、表示順を固定する。"""
    section_pat = re.compile(
        rf"\n\s*<!-- ===== [^>]* ===== -->\s*"
        rf"<section\b[^>]*\bid=[\"']{re.escape(section_id)}[\"'][^>]*>.*?</section>",
        re.S,
    )
    section_match = section_pat.search(html_text)
    if not section_match:
        print(f"  ⚠ セクション #{section_id} が見つからない")
        return html_text

    section_html = section_match.group(0)
    without_section = html_text[:section_match.start()] + html_text[section_match.end():]
    target_pat = re.compile(
        rf"<section\b[^>]*\bid=[\"']{re.escape(target_id)}[\"'][^>]*>.*?</section>",
        re.S,
    )
    target_match = target_pat.search(without_section)
    if not target_match:
        print(f"  ⚠ 移動先セクション #{target_id} が見つからない")
        return html_text

    insert_at = target_match.end()
    return without_section[:insert_at] + "\n" + section_html + without_section[insert_at:]


def remove_section(html_text, section_id):
    """指定セクションと直前の説明コメントをHTMLから取り除く。"""
    pat = re.compile(
        rf"\n\s*(?:<!-- ===== [^>]* ===== -->\s*)?"
        rf"<section\b[^>]*\bid=[\"']{re.escape(section_id)}[\"'][^>]*>.*?</section>",
        re.S,
    )
    return pat.sub("", html_text)


def main():
    futures = load("futures.json")
    japan = load("japan_stocks.json")
    themes = load("themes.json")
    volume = load("volume_stocks.json")
    events = {}
    market_news = load("market_news.json")
    flash = load("earnings_flash.json")
    nikkei = load("nikkei225.json")

    with open(INDEX, encoding="utf-8") as f:
        doc = f.read()

    sections = {
        "idx": build_idx(futures),
        "flash": build_flash(flash),
        "rank": build_rank(japan),
        "themes": build_themes(themes),
        "marketnews": build_market_news(market_news),
        "heat": build_heat(nikkei),
        "themelinks": build_themelinks(themes),
    }
    filled = 0
    for key, content in sections.items():
        if content:
            doc = replace_marker(doc, key, content)
            filled += 1

    doc = move_section_after(doc, "rank", "idx")
    doc = move_section_after(doc, "themes", "rank")
    doc = remove_section(doc, "earn")
    doc = remove_section(doc, "news")
    doc = remove_section(doc, "stats")
    doc = re.sub(
        r"\n\s*<!-- ===== 本日の決算 \+ 市場ニュース ===== -->\s*"
        r"<div class=\"cols\">\s*</div>",
        "",
        doc,
        flags=re.S,
    )

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"  ✓ [プリレンダリング] index.html に {filled} セクションを焼き込み")

    # テーマ個別ページ（SSG）を生成し、その URL をサイトマップに収録
    try:
        import prerender_themes
        theme_slugs = prerender_themes.main()
    except Exception as e:
        print(f"  ⚠ テーマページ生成に失敗: {e}")
        theme_slugs = None

    fixed_slugs = write_fixed_pages(japan, volume, events, flash)
    write_sitemap(theme_slugs, fixed_slugs)


if __name__ == "__main__":
    main()
