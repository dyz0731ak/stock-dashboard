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


def load(name):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def esc(s):
    return html.escape(str(s if s is not None else ""))


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


# ─────────────────────────────────────────────
# 各セクションの HTML 生成
# ─────────────────────────────────────────────
def build_hero(japan, themes, futures):
    today = datetime.datetime.now(JST).strftime("%-m/%-d")
    bits = []
    if japan and japan.get("all_stocks"):
        top = max(japan["all_stocks"], key=lambda s: float(s.get("change_pct") or 0))
        bits.append(f'本日のストップ高は{japan.get("stop_high_count", 0)}銘柄、'
                    f'急騰トップは{esc(top["name"])}（{esc(top["code"])}・{pcttxt(top["change_pct"])}）')
    if themes and themes.get("themes"):
        t = max(themes["themes"], key=lambda x: x.get("week_pct", 0))
        bits.append(f'注目テーマは{esc(t["name"])}（週{pcttxt(t["week_pct"])}）')
    lead2 = "、".join(bits)
    h = ['<h1 class="hero-h1">日本株・米国株 リアルタイム株式ダッシュボード｜投資の砦</h1>']
    h.append('<p class="hero-lead">ストップ高・急騰銘柄・米国株トップゲイナー・決算速報・テーマ株ランキング・'
             '経済指標カレンダー・日経225/S&amp;P500ヒートマップを一画面でリアルタイム自動更新。'
             + (f'<br>{today}時点 — {lead2}。' if lead2 else "") + '</p>')
    return "\n".join(h)


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
    if not japan or not japan.get("all_stocks"):
        return ""
    rows = sorted([s for s in japan["all_stocks"] if s.get("change_pct") is not None],
                  key=lambda s: -float(s["change_pct"]))[:15]
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


def build_flash(flash):
    if not flash or not flash.get("groups"):
        return ""
    out = []
    for g in flash["groups"]:
        items = g.get("items") or []
        if not items:
            continue
        out.append(f'<div class="flash-zone zone-{esc(g.get("zone","neutral"))}">'
                   f'<div class="zone-label"><span class="zone-tag">{esc(g.get("display"))}</span></div>')
        for it in items[:6]:
            chips = "".join(f'<span class="chip">{esc(c.get("label"))} {esc(c.get("value"))}</span>'
                            for c in (it.get("chips") or []))
            out.append(
                f'<div class="flash-item"><span class="time">{esc(it.get("time",""))}</span>'
                f'<span class="code">{esc(it.get("code"))}</span>'
                f'<div class="body"><div class="nm">{esc(it.get("name"))}</div>'
                f'<div class="nar">{esc(it.get("narrative",""))}</div>'
                f'<div class="chips">{chips}</div></div></div>'
            )
        out.append("</div>")
    return "".join(out)


def build_news(news):
    if not news or not news.get("items"):
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
        return ""
    lst = events.get("us_earnings") or events.get("jp_earnings") or []
    rows = []
    for it in lst[:12]:
        ident = it.get("symbol") or it.get("code")
        tag = it.get("time_jst_label") or it.get("quarter") or ""
        tagspan = f'<span class="r-tag">{esc(tag)}</span>' if tag else ""
        rows.append(
            f'<div class="row-item"><span class="r-code">{esc(ident)}</span>'
            f'<span class="r-name">{esc(it.get("name"))}</span>'
            f'{tagspan}</div>'
        )
    return "".join(rows)


def build_stats(japan, events, flash):
    if not japan:
        return ""
    cards = [
        ("ストップ高", japan.get("stop_high_count", 0), "銘柄", "本日の値幅制限到達", ""),
        ("ストップ高接近", japan.get("near_stop_count", 0), "銘柄", "5%以内に接近", ""),
    ]
    if japan.get("all_stocks"):
        top = max(japan["all_stocks"], key=lambda s: float(s.get("change_pct") or 0))
        cards.append(("最高騰落率", pcttxt(top["change_pct"]).rstrip("%"), "%", esc(top["name"]), "up"))
    cards.append(("決算発表(速報)", (flash or {}).get("total", 0), "件", "日本株・前営業日分", ""))
    cards.append(("本日の経済指標", len((events or {}).get("economic", [])), "件", "★重要度付き", ""))
    out = []
    for k, v, u, meta, cls in cards:
        out.append(f'<div class="stat"><div class="k">{esc(k)}</div>'
                   f'<div class="v {cls}">{esc(v)}<small>{esc(u)}</small></div>'
                   f'<div class="meta">{meta}</div></div>')
    return "".join(out)


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


def write_sitemap():
    """sitemap.xml を生成。トップは毎日データ更新されるので lastmod=当日(JST)・changefreq=daily。
    /about/ は内容がほぼ不変なのでファイルの更新日を lastmod にする（毎日変わったと誤認させない）。"""
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


def main():
    futures = load("futures.json")
    japan = load("japan_stocks.json")
    themes = load("themes.json")
    events = load("events.json")
    flash = load("earnings_flash.json")
    news = load("market_news.json")
    nikkei = load("nikkei225.json")

    with open(INDEX, encoding="utf-8") as f:
        doc = f.read()

    sections = {
        "hero": build_hero(japan, themes, futures),
        "idx": build_idx(futures),
        "flash": build_flash(flash),
        "earn": build_earn(events),
        "news": build_news(news),
        "stats": build_stats(japan, events, flash),
        "rank": build_rank(japan),
        "themes": build_themes(themes),
        "events": build_events(events),
        "heat": build_heat(nikkei),
    }
    filled = 0
    for key, content in sections.items():
        if content:
            doc = replace_marker(doc, key, content)
            filled += 1

    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"  ✓ [プリレンダリング] index.html に {filled} セクションを焼き込み")

    write_sitemap()


if __name__ == "__main__":
    main()
