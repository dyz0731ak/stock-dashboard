#!/usr/bin/env python3
"""
テーマ株の個別ページ（SSG）を生成する。

themes.json の各テーマ（固定20テーマ）について
  /themes/<slug>/index.html
を中身入りで書き出す。各ページは「○○関連株 一覧・値動き」というロングテール
検索意図を満たす独立ページで、トップ（SPA）とは別URL・既存のトップには手を付けない。

冪等: 毎回まるごと書き直すだけ。data 更新後に cron から呼ぶことで数値も最新化される。
評価対象の本文（テーマ解説）は THEME_INTRO に静的キュレーション（薄いページにしない）。
"""

import json
import os
import html
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))
ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "themes")
BASE_URL = "https://dashboard.stock-overflow24.com"

# テーマ名 → URL スラッグ（ascii・固定）
SLUGS = {
    "電子部品": "denshi-buhin",
    "半導体製造装置": "handotai-seizo-souchi",
    "量子コンピュータ": "quantum-computer",
    "半導体": "handotai",
    "蓄電池": "chikudenchi",
    "銀行": "ginko",
    "海運": "kaiun",
    "インバウンド": "inbound",
    "空運": "kuuun",
    "高配当": "kohaito",
    "ゲーム": "game",
    "ロボット": "robot",
    "人工知能（AI）": "ai",
    "不動産": "fudosan",
    "鉄鋼": "tekko",
    "自動車": "jidosha",
    "総合商社": "sogo-shosha",
    "防衛": "boei",
    "医薬・バイオ": "iyaku-bio",
    "再生可能エネルギー": "saisei-energy",
}

# テーマ解説（evergreen 本文・E-E-A-T／薄いページ回避）
THEME_INTRO = {
    "電子部品": "コンデンサ・抵抗器・コネクタなど電子機器の基幹部品を手がける銘柄群です。スマートフォン・自動車・データセンター向けの需要に業績が連動し、村田製作所・京セラ・太陽誘電など世界シェア上位の日本企業が多いのが特徴です。",
    "半導体製造装置": "半導体を作るための製造装置（露光・成膜・エッチング・検査）を手がける銘柄群です。東京エレクトロン・アドバンテスト・ディスコなど世界的シェアを持つ日本企業が中心で、半導体メーカーの設備投資サイクルに業績が左右されます。",
    "量子コンピュータ": "従来型コンピュータを超える計算能力を狙う量子技術の関連銘柄です。研究開発段階のテーマ性が強く、政府の戦略投資や大型受注のニュースで急騰しやすい一方、値動きが荒くなりやすい点に注意が必要です。",
    "半導体": "半導体の設計・製造・材料・装置に関わる銘柄群です。AI・データセンター・EVなどあらゆる成長分野の中核であり、市況（メモリ価格・受注動向）と為替に業績が大きく連動する代表的な景気敏感セクターです。",
    "蓄電池": "リチウムイオン電池・全固体電池など蓄電技術の関連銘柄です。EVや再生可能エネルギー普及の中核技術として注目され、素材・セル・製造装置メーカーまで裾野が広いのが特徴です。",
    "銀行": "都市銀行・地方銀行など金融セクターの中核となる銘柄群です。金利上昇局面では利ざや改善が業績を押し上げやすく、日銀の金融政策や長期金利の動向に株価が敏感に反応します。",
    "海運": "コンテナ船・ばら積み船などを運航する海運会社の銘柄群です。世界の貿易量と運賃市況（バルチック海運指数など）に業績が連動し、高配当銘柄が多いことでも知られます。",
    "インバウンド": "訪日外国人観光客の増加で恩恵を受ける銘柄群です。百貨店・ホテル・鉄道・化粧品・空運など幅広く、為替（円安）や訪日客数の統計が株価材料になりやすいテーマです。",
    "空運": "航空会社・空港関連の銘柄群です。旅客・貨物の需要や燃油価格、インバウンドの動向に業績が左右され、景気回復局面で見直されやすいセクターです。",
    "高配当": "配当利回りの高い銘柄群です。安定した株主還元を重視する投資家に人気で、インカム狙いの長期保有や、下落局面での下値の堅さが特徴とされます。",
    "ゲーム": "家庭用・スマホ・PC向けゲームを手がける銘柄群です。ヒットタイトルの有無で業績が大きく変動し、新作発表や海外展開、eスポーツなどがテーマになりやすい分野です。",
    "ロボット": "産業用ロボット・FA（ファクトリーオートメーション）・協働ロボットの関連銘柄です。人手不足・省人化ニーズと、中国をはじめ世界の設備投資動向に業績が連動します。",
    "人工知能（AI）": "生成AI・機械学習などAI技術の開発・活用に関わる銘柄群です。データセンターや半導体需要の拡大とともに最も注目されるテーマで、関連ニュースで物色が広がりやすいのが特徴です。",
    "不動産": "不動産の開発・賃貸・REITに関わる銘柄群です。金利動向と地価・オフィス賃料に業績が左右され、再開発やインバウンドが追い風材料になりやすいセクターです。",
    "鉄鋼": "高炉・電炉など鉄鋼メーカーの銘柄群です。自動車・建設・インフラ需要と鋼材市況、原料価格に業績が連動する代表的な景気敏感セクターです。",
    "自動車": "完成車メーカー・部品サプライヤーの銘柄群です。EVシフト・為替（円安メリット）・世界販売台数が業績の鍵を握る、日本を代表する基幹産業です。",
    "総合商社": "資源・エネルギーから食料・インフラまで幅広く手がける総合商社の銘柄群です。資源市況と為替に業績が連動し、高い株主還元と著名投資家の保有でも注目されています。",
    "防衛": "防衛装備・関連機器を手がける銘柄群です。防衛予算の増額や安全保障環境の変化がテーマとなり、政策ニュースで物色されやすい分野です。",
    "医薬・バイオ": "新薬・バイオ医薬品・創薬ベンチャーの銘柄群です。治験の進捗・承認・提携のニュースで急騰・急落しやすく、長期の成長テーマと短期の材料株の両面を持ちます。",
    "再生可能エネルギー": "太陽光・風力・水素などクリーンエネルギー関連の銘柄群です。脱炭素政策と電力価格、補助金の動向が追い風・逆風となり、蓄電池やインフラ企業まで広がります。",
}

CSS = """
:root{--bg:#f4f6f9;--surface:#fff;--surface-2:#f8fafc;--border:#e3e8ef;--border-strong:#cdd5df;
--ink:#1c2531;--ink-2:#48566a;--ink-3:#7b8794;--brand:#0b7a4b;--brand-ink:#0a6a42;--brand-soft:#e6f4ed;
--up:#d92d20;--up-soft:#fdeceb;--down:#0e8a5f;--down-soft:#e7f5ef;--radius:10px;--radius-sm:7px;
--shadow:0 1px 2px rgba(16,24,40,.04),0 1px 3px rgba(16,24,40,.06);--maxw:980px;
--sans:"Noto Sans JP","Inter",system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.7}
a{color:var(--brand-ink);text-decoration:none}a:hover{text-decoration:underline}
.topbar{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:9}
.topbar-inner{max-width:var(--maxw);margin:0 auto;padding:12px 18px;display:flex;align-items:center}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-weight:700;text-decoration:none}
.brand .logo{width:30px;height:30px;border-radius:8px;background:var(--brand);color:#fff;display:flex;
align-items:center;justify-content:center;font-weight:800}
.brand small{display:block;font-size:11px;color:var(--ink-3);font-weight:500}
.wrap{max-width:var(--maxw);margin:0 auto;padding:22px 18px 60px}
.crumb{font-size:12.5px;color:var(--ink-3);margin:4px 0 14px}
.crumb a{color:var(--ink-3)}
h1{font-size:25px;line-height:1.35;margin:0 0 6px}
.sub{color:var(--ink-3);font-size:13px;margin:0 0 18px}
.lead{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
padding:16px 18px;box-shadow:var(--shadow);margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 22px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px;box-shadow:var(--shadow)}
.stat .k{font-size:12px;color:var(--ink-3)}
.stat .v{font-size:21px;font-weight:800;margin-top:2px}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--ink-3)}
h2{font-size:17px;margin:26px 0 12px;padding-left:10px;border-left:4px solid var(--brand)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);
border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--border);font-size:14px}
th{background:var(--surface-2);color:var(--ink-2);font-size:12.5px;font-weight:600}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
.spark{display:block;margin:6px 0 4px}
.cta{display:inline-block;background:var(--brand);color:#fff;font-weight:700;padding:11px 20px;
border-radius:var(--radius-sm);margin:6px 0 8px}.cta:hover{background:var(--brand-ink);text-decoration:none}
.rel{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.rel a{background:var(--brand-soft);color:var(--brand-ink);border-radius:999px;padding:6px 14px;font-size:13px}
.rel a:hover{text-decoration:none;background:#d8ecdf}
footer{border-top:1px solid var(--border);background:var(--surface);margin-top:40px}
.foot-inner{max-width:var(--maxw);margin:0 auto;padding:18px;font-size:12px;color:var(--ink-3);text-align:center}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}h1{font-size:21px}}
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


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


def sparkline(vals, w=120, h=34):
    pts = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    n = len(pts)
    coords = []
    for i, v in enumerate(pts):
        x = i / (n - 1) * w
        y = h - (v - lo) / rng * h
        coords.append(f"{x:.1f},{y:.1f}")
    color = "#d92d20" if pts[-1] >= pts[0] else "#0e8a5f"
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{" ".join(coords)}"/></svg>')


def build_page(theme, all_themes, updated):
    name = theme["name"]
    slug = SLUGS.get(name)
    if not slug:
        return None
    intro = THEME_INTRO.get(name, f"{name}に関連する銘柄群の値動きをまとめたページです。")
    title = f"{name}関連株 一覧・値動きランキング｜投資の砦"
    desc = (f"{name}関連株の主要銘柄一覧と週間・月間の騰落率、勝率をリアルタイムで確認できます。"
            f"{intro[:60]}…")[:120]
    url = f"{BASE_URL}/themes/{slug}/"

    # 構成銘柄テーブル
    rows = ""
    stocks_ld = []
    for i, s in enumerate(theme.get("top") or []):
        wp = s.get("week_pct")
        rows += (f'<tr><td class="r">{i+1}</td><td><b>{esc(s.get("name"))}</b></td>'
                 f'<td class="r">{esc(s.get("code"))}</td>'
                 f'<td class="r {sign_cls(wp)}"><b>{pcttxt(wp)}</b></td></tr>')
        stocks_ld.append({"@type": "ListItem", "position": i + 1,
                          "name": f'{s.get("name")}（{s.get("code")}）'})
    table = (f'<table><thead><tr><th class="r" style="width:44px">#</th><th>銘柄名</th>'
             f'<th class="r">コード</th><th class="r">週間騰落率</th></tr></thead>'
             f'<tbody>{rows}</tbody></table>') if rows else ""

    # 関連テーマ（自分以外を週間騰落率順に上位8）
    others = sorted([t for t in all_themes if t["name"] != name and SLUGS.get(t["name"])],
                    key=lambda x: -(x.get("week_pct") or 0))[:8]
    rel = "".join(f'<a href="{BASE_URL}/themes/{SLUGS[t["name"]]}/">{esc(t["name"])}関連株</a>'
                  for t in others)

    spark = sparkline(theme.get("spark"))

    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "投資の砦", "item": BASE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "テーマ株", "item": BASE_URL + "/themes/"},
                {"@type": "ListItem", "position": 3, "name": f"{name}関連株", "item": url},
            ]},
            {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": title,
             "description": desc, "inLanguage": "ja",
             "isPartOf": {"@type": "WebSite", "name": "投資の砦", "url": BASE_URL + "/"}},
            {"@type": "ItemList", "name": f"{name}関連の主要銘柄", "itemListElement": stocks_ld},
        ],
    }

    return slug, f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}"/>
<meta name="keywords" content="{esc(name)}関連株,{esc(name)}関連銘柄,{esc(name)},テーマ株,株価,ランキング,投資の砦"/>
<meta name="robots" content="index, follow"/>
<link rel="canonical" href="{url}"/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{url}"/>
<meta property="og:title" content="{esc(title)}"/>
<meta property="og:description" content="{esc(desc)}"/>
<meta property="og:image" content="{BASE_URL}/ogp.png"/>
<meta property="og:site_name" content="投資の砦"/>
<meta property="og:locale" content="ja_JP"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{esc(title)}"/>
<meta name="twitter:description" content="{esc(desc)}"/>
<meta name="twitter:image" content="{BASE_URL}/ogp.png"/>
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<style>{CSS}</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<a href="{BASE_URL}/" class="brand"><span class="logo">砦</span>
<span>投資の砦<small>日本株・米国株マーケット</small></span></a>
</div></header>
<div class="wrap">
<nav class="crumb"><a href="{BASE_URL}/">ホーム</a> › <a href="{BASE_URL}/themes/">テーマ株</a> › {esc(name)}関連株</nav>
<h1>{esc(name)}関連株【主要銘柄・週間/月間騰落率ランキング】</h1>
<p class="sub">構成銘柄 {esc(theme.get("count", ""))} 社 ／ 更新日 {esc(updated)}（自動更新）</p>
<div class="lead">{esc(intro)}{spark}</div>
<div class="stats">
<div class="stat"><div class="k">前日比</div><div class="v {sign_cls(theme.get("day_pct"))}">{pcttxt(theme.get("day_pct"))}</div></div>
<div class="stat"><div class="k">週間</div><div class="v {sign_cls(theme.get("week_pct"))}">{pcttxt(theme.get("week_pct"))}</div></div>
<div class="stat"><div class="k">月間</div><div class="v {sign_cls(theme.get("month_pct"))}">{pcttxt(theme.get("month_pct"))}</div></div>
<div class="stat"><div class="k">勝率</div><div class="v">{esc(round(theme.get("win_rate") or 0))}%</div></div>
</div>
<h2>{esc(name)}関連の主要銘柄</h2>
{table}
<p style="margin:18px 0"><a class="cta" href="{BASE_URL}/#themes">▶ 全テーマのランキングをリアルタイムで見る</a></p>
<h2>他のテーマ株を見る</h2>
<div class="rel">{rel}</div>
</div>
<footer><div class="foot-inner">© 投資の砦 ｜ 情報提供のみを目的とし、投資判断はご自身の責任で。</div></footer>
</body>
</html>
"""


def build_hub(themes, updated):
    """テーマ一覧ハブ /themes/ 。各テーマページへの導線（パンくず／フッターの着地先）。"""
    url = f"{BASE_URL}/themes/"
    title = "テーマ株ランキング一覧｜関連株の値動きを一覧で｜投資の砦"
    desc = ("半導体・AI・防衛・海運・高配当など主要テーマ株の週間・月間騰落率ランキングを一覧で確認。"
            "各テーマの関連銘柄と値動きをリアルタイムで自動更新する個人投資家向けダッシュボード「投資の砦」。")[:120]
    ts = sorted([t for t in themes if SLUGS.get(t["name"])], key=lambda x: -(x.get("week_pct") or 0))
    rows = ""
    ld_items = []
    for i, t in enumerate(ts):
        slug = SLUGS[t["name"]]
        wp, mp = t.get("week_pct"), t.get("month_pct")
        rows += (f'<tr><td class="r">{i+1}</td>'
                 f'<td><a href="{BASE_URL}/themes/{slug}/"><b>{esc(t["name"])}関連株</b></a></td>'
                 f'<td class="r">{esc(t.get("count",""))}社</td>'
                 f'<td class="r {sign_cls(wp)}"><b>{pcttxt(wp)}</b></td>'
                 f'<td class="r {sign_cls(mp)}">{pcttxt(mp)}</td></tr>')
        ld_items.append({"@type": "ListItem", "position": i + 1, "name": f'{t["name"]}関連株',
                         "url": f"{BASE_URL}/themes/{slug}/"})
    jsonld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "投資の砦", "item": BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "テーマ株", "item": url}]},
        {"@type": "CollectionPage", "url": url, "name": title, "description": desc, "inLanguage": "ja"},
        {"@type": "ItemList", "name": "テーマ株一覧", "itemListElement": ld_items}]}
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}"/>
<meta name="keywords" content="テーマ株,テーマ株ランキング,関連株,関連銘柄,半導体,AI,防衛,高配当,投資の砦"/>
<meta name="robots" content="index, follow"/>
<link rel="canonical" href="{url}"/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{url}"/>
<meta property="og:title" content="{esc(title)}"/>
<meta property="og:description" content="{esc(desc)}"/>
<meta property="og:image" content="{BASE_URL}/ogp.png"/>
<meta property="og:site_name" content="投資の砦"/>
<meta property="og:locale" content="ja_JP"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{esc(title)}"/>
<meta name="twitter:description" content="{esc(desc)}"/>
<meta name="twitter:image" content="{BASE_URL}/ogp.png"/>
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<style>{CSS}</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<a href="{BASE_URL}/" class="brand"><span class="logo">砦</span>
<span>投資の砦<small>日本株・米国株マーケット</small></span></a>
</div></header>
<div class="wrap">
<nav class="crumb"><a href="{BASE_URL}/">ホーム</a> › テーマ株</nav>
<h1>テーマ株ランキング一覧</h1>
<p class="sub">主要テーマ {len(ts)} 件 ／ 更新日 {esc(updated)}（自動更新）</p>
<div class="lead">半導体・AI・防衛・海運・高配当など、注目テーマごとの関連株の値動き（週間・月間騰落率）を一覧でまとめています。
気になるテーマをクリックすると、構成銘柄とテーマの解説をご覧いただけます。</div>
<h2>週間騰落率ランキング</h2>
<table><thead><tr><th class="r" style="width:44px">#</th><th>テーマ</th>
<th class="r">銘柄数</th><th class="r">週間</th><th class="r">月間</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="margin:18px 0"><a class="cta" href="{BASE_URL}/#themes">▶ ダッシュボードでリアルタイムに見る</a></p>
</div>
<footer><div class="foot-inner">© 投資の砦 ｜ 情報提供のみを目的とし、投資判断はご自身の責任で。</div></footer>
</body>
</html>
"""
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


def main():
    with open(os.path.join(DATA, "themes.json"), encoding="utf-8") as f:
        data = json.load(f)
    themes = data.get("themes", [])
    updated = (data.get("updated_at") or "")[:10] or datetime.datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for th in themes:
        res = build_page(th, themes, updated)
        if not res:
            continue
        slug, page = res
        d = os.path.join(OUT_DIR, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        n += 1
    build_hub(themes, updated)
    print(f"  ✓ [テーマページ] ハブ + {n} ページを生成（themes/）")
    return [SLUGS[t["name"]] for t in themes if SLUGS.get(t["name"])]


if __name__ == "__main__":
    main()
