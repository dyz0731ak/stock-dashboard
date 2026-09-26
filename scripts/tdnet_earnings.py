"""Important Japanese disclosures, from TDnet's dated list and original XBRL/PDF.

No market-cap filter. Comparisons are company forecasts or published actuals,
never assumed analyst consensus. Successfully checked empty days are not errors.
"""
import datetime as dt
import io
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin
import zipfile
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
import pdfplumber

from market_clock import JST
from market_http import get
from safe_save import _load_existing, _write_json_atomic, safe_save, mark_failed
from data_status import is_fresh
from fetch_company_profiles import collect_one, needs_refresh
from earnings_amounts import format_yen, normalize_earnings

BASE = 'https://www.release.tdnet.info/inbs/'
DATA = Path(__file__).resolve().parents[1] / 'data'
CACHE_VERSION = 2
TAGS = {
    'NetSales': '売上高', 'RevenueIFRS': '売上収益', 'Revenue': '売上収益',
    'OrdinaryRevenuesBK': '経常収益', 'OperatingIncome': '営業利益',
    'OperatingProfitIFRS': '営業利益', 'OrdinaryIncome': '経常利益',
    'ProfitAttributableToOwnersOfParent': '純利益', 'NetIncome': '純利益',
    'ProfitAttributableToOwnersOfParentIFRS': '純利益', 'ProfitLossIFRS': '純利益',
    'DividendPerShare': '1株配当',
}


def normal(text):
    return unicodedata.normalize('NFKC', text).replace('△', '-').replace('▲', '-')


def relevant(title):
    title = normal(title)
    if re.search(r'訂正|数値データ訂正|取得状況|取得結果|取得終了|取得完了|払込|処分|報酬|非上場|説明資料|補足資料|決算説明|英文|\[Delayed\]', title, re.I):
        return False
    return bool(re.search(r'決算短信|業績予想.*修正|予想.*実績.*差異|配当.*(修正|増配|減配)|自己株式.*(取得.*決定|取得枠|取得に係る事項)', title))


def parse_list(html, day):
    soup = BeautifulSoup(html, 'html.parser')
    date_node = soup.select_one('#kaiji-date-1')
    if not date_node or re.sub(r'\D', '', date_node.text) != day.replace('-', ''):
        raise ValueError('TDnet list date mismatch')
    rows = []
    for cell in soup.select('td.kjTime'):
        tr = cell.parent
        code = tr.select_one('.kjCode').get_text(strip=True)
        if not re.fullmatch(r'[0-9][0-9A-Z]{3}0', code):
            continue
        link = tr.select_one('.kjTitle a[href]')
        if not link or not relevant(link.get_text(' ', strip=True)):
            continue
        xbrl = tr.select_one('.kjXbrl a[href]')
        title = normal(link.get_text(' ', strip=True))
        rows.append(dict(code=code[:4], name=re.sub(r'^[GSP]-', '', normal(tr.select_one('.kjName').get_text(strip=True))),
                         title=title, time=cell.get_text(strip=True), published_date=day,
                         document_url=urljoin(BASE, link['href']),
                         xbrl_url=urljoin(BASE, xbrl['href']) if xbrl else ''))
    pages = sorted(set(re.findall(r'I_list_\d{3}_'+day.replace('-', '')+r'\.html', html)))
    return rows, pages


def fetch_list(day):
    first = f'I_list_001_{day.replace("-", "")}.html'
    pending, visited, rows = [first], set(), []
    while pending:
        page = pending.pop(0)
        if page in visited:
            continue
        if len(visited) >= 20:
            raise ValueError('TDnet pagination exceeded safe limit')
        response = get(BASE+page)
        html = response.content.decode('utf-8')
        found, pages = parse_list(html, day)
        rows.extend(found)
        visited.add(page)
        pending.extend(p for p in pages if p not in visited and p not in pending)
    return list({r['document_url']: r for r in rows}.values())


def parse_xbrl(content):
    """Use summary facts only; match identical dimensions across comparisons."""
    z = zipfile.ZipFile(io.BytesIO(content))
    facts, notes = {}, []
    for member in z.infolist():
        if not member.filename.endswith('-ixbrl.htm') or '/Attachment/' in member.filename:
            continue
        if member.file_size > 8_000_000:
            raise ValueError('XBRL summary too large')
        soup = BeautifulSoup(z.read(member), 'xml')
        for node in soup.find_all():
            name = node.get('name', '').split(':')[-1]
            ctx = node.get('contextRef', '')
            if node.name == 'nonNumeric' and name in ('ReasonForForecastCorrection', 'ReasonForDividendForecastCorrection'):
                notes.append(normal(node.get_text(' ', strip=True)))
            if node.name != 'nonFraction' or name not in TAGS:
                continue
            raw = normal(node.get_text(strip=True)).replace(',', '')
            try:
                value = float(raw) * 10**int(node.get('scale', '0'))
                if node.get('sign') == '-':
                    value = -value
                if not math.isfinite(value):
                    continue
            except (ValueError, TypeError):
                continue
            facts[(name, ctx)] = value
    comparisons = []
    for (name, ctx), value in facts.items():
        tokens = ctx.split('_')
        if 'CurrentMember' in tokens and 'ForecastMember' in tokens:
            old_ctx, basis = ctx.replace('_CurrentMember_', '_PreviousMember_'), '前回会社予想比'
        elif ctx.startswith('Current') and 'ResultMember' in tokens and name != 'DividendPerShare':
            old_ctx, basis = ctx.replace('Current', 'Prior', 1), '前年同期比'
        else:
            continue
        old = facts.get((name, old_ctx))
        if old is None:
            continue
        period = '通期'
        match = re.search(r'AccumulatedQ([1-4])', ctx)
        if match:
            period = f'第{match[1]}四半期累計'
        elif 'SecondQuarterMember' in tokens:
            period = '中間'
        elif 'YearEndMember' in tokens:
            period = '期末'
        pct = (value-old)/abs(old)*100 if old else None
        comparisons.append(dict(label=TAGS[name], current=value, previous=old, pct=round(pct, 2) if pct is not None else None,
                                basis=basis, period=period, consolidated='ConsolidatedMember' in tokens,
                                context=ctx, fact=name, unit='円' if name=='DividendPerShare' else '百万円'))
    # Prefer consolidated accounts, and annual dividends over a component of the same year.
    selected = {}
    for row in sorted(comparisons, key=lambda r: (r['consolidated'], r['period']=='通期', r['current']!=r['previous'], abs(r.get('pct') or 0)), reverse=True):
        key = (row['label'], row['basis'])
        selected.setdefault(key, row)
    return list(selected.values()), notes


def parse_buyback(text):
    text = re.sub(r'\s+', '', normal(text))
    number = r'([\d,]+(?:\.\d+)?)'
    rows = []
    for label, pattern, unit in (
        ('取得上限額', r'(?:取得価額の総額|取得価額の総額の上限|取得総額).*?'+number+r'(億円|百万円|千円|万円|円)', '円'),
        ('取得上限株数', r'(?:取得する株式の総数|取得し得る株式の総数|取得株式数).*?'+number+r'(万株|株)', '株'),
        ('発行済株式比', r'(?:発行済株式総数.{0,45}?割合|発行済株式総数.{0,45}?対する割合)'+number+r'%', '%'),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        value = float(match[1].replace(',', ''))
        multiplier = {'億円':1e8, '百万円':1e6, '千円':1e3, '万円':1e4, '万株':1e4}
        if match.lastindex > 1:
            value *= multiplier.get(match[2], 1)
        rows.append(dict(label=label, current=value, unit=unit, basis='取得枠の決定'))
    return rows


def parse_pdf_comparisons(text, title):
    text = normal(text)
    if 'IFRS' in title or '米国' in title:
        return []  # Unknown layouts must not silently shift the profit columns.
    labels = ['経常収益','経常利益','純利益'] if '経常収益' in text and '売上高' not in text else ['売上高','営業利益','経常利益','純利益']
    old, new, basis = None, None, '前回会社予想比'
    for line in text.splitlines():
        match = re.search(r'(前回発表予想|今回修正予想|今回発表予想)\s*(?:[\(（]?[AB][\)）]?)?\s*(.*)', line)
        if match:
            values = re.findall(r'(?<![\d.])-?[\d,]+(?:\.\d+)?',match[2])
            if len(values)==len(labels)+1:  # Financial amounts plus EPS; reject different layouts.
                parsed = [float(v.replace(',',''))*1e6 for v in values[:len(labels)]]
                if match[1]=='前回発表予想': old=parsed
                else:new=parsed
    if old is None or new is None:
        return []
    return [dict(label=label,current=b,previous=a,pct=round((b-a)/abs(a)*100,2) if a else None,
                 basis=basis,period='会社予想',unit='百万円',source_format='PDF')
            for label,a,b in zip(labels,old,new)]


def describe_number(row, value):
    if row['unit'] == '百万円' or (row['unit']=='円' and row['label']=='取得上限額'):
        return format_yen(value)
    return f'{value:,.2f}'.rstrip('0').rstrip('.')+row['unit']


def select_impact(row, comparisons, buyback):
    reasons, scores, directions, numbers, chips = [], [], [], [], []
    for c in comparisons:
        new, old, pct = c['current'], c['previous'], c.get('pct')
        numbers.append(dict(label=c['period']+' '+c['label'], value=describe_number(c,new),
                            comparison=f'{describe_number(c,old)} → {describe_number(c,new)}（{c["basis"]}）'))
        change = None
        if old < 0 < new:
            change, score = '黒字転換', 95
        elif old > 0 > new:
            change, score = '赤字転落', 95
        elif c['label']=='1株配当' and new != old:
            change, score = ('増配' if new>old else '減配'), 70 + min(abs(pct or 0), 20)
        elif c['basis']=='前回会社予想比' and pct is not None and abs(pct)>=5 and '利益' in c['label']:
            change, score = ('上方修正' if new>old else '下方修正'), 65+min(abs(pct),30)
        elif c['basis']=='前年同期比' and pct is not None and abs(pct)>=30 and '利益' in c['label']:
            change, score = ('大幅増益' if new>old else '大幅減益'), 65+min(abs(pct)/2,30)
        if change:
            delta = f' {pct:+.1f}%' if pct is not None and old>0 and new>=0 else ''
            reasons.append(f'{c["period"]}{c["label"]}が{change}{delta}（{c["basis"]}）')
            scores.append(score); directions.append('positive' if new>old else 'negative')
            chips.append(dict(label=c['label'], value=change+delta, direction='up' if new>old else 'down'))
    if buyback:
        numbers.extend(dict(label=c['label'],value=describe_number(c,c['current']),comparison='取得枠の上限・発行済株式比') for c in buyback)
        proportion = next((c['current'] for c in buyback if c['unit']=='%'),0)
        reasons.append('新たな自社株買いを決定'+(f'（発行済株式の{proportion:g}%が上限）' if proportion else ''))
        scores.append(70+min(proportion*3,25)); directions.append('positive')
        chips.append(dict(label='資本政策',value='自社株買い',direction='up'))
    if not reasons:
        return None
    lead = max(range(len(scores)), key=lambda i:scores[i])
    return dict(row, narrative=row['title'], key_numbers=numbers[:6], comparisons=comparisons,
                chips=chips[:5], impact_score=round(max(scores)), impact_zone=directions[lead],
                impact_label=chips[lead]['value'] if lead<len(chips) else '自社株買い',
                impact_summary='。'.join(reasons)+'。', category='重要開示',
                url=row['document_url'], sources=['TDnet'], primary_source='TDnet',
                published_label=f'{row["published_date"][5:].replace("-", "/")} {row["time"]}発表',
                published_time=row['time'], consensus_status='市場予想データなし（会社予想・前年実績との比較）')


def enrich(row):
    comparisons, notes, buyback, errors = [], [], [], []
    if row['xbrl_url']:
        try:
            comparisons, notes = parse_xbrl(get(row['xbrl_url']).content)
        except Exception as exc:
            errors.append('XBRL: '+str(exc))
    if not comparisons or '自己株式' in row['title']:
        try:
            response = get(row['document_url'])
            with pdfplumber.open(io.BytesIO(response.content)) as pdf:
                text = '\n'.join(page.extract_text() or '' for page in pdf.pages[:3])
            if '自己株式' in row['title']:
                buyback = parse_buyback(text)
            if not comparisons and not buyback:
                comparisons = parse_pdf_comparisons(text,row['title'])
        except Exception as exc:
            errors.append('PDF: '+str(exc))
    if not comparisons and not buyback and not errors:
        errors.append('未対応の原資料形式：数値・比較を確認できず選定から除外')
    item = select_impact(row, comparisons, buyback)
    if item and notes:
        # Keep the company's explanation available as evidence, not an invented consensus claim.
        item['company_explanation'] = notes[0][:800]
    return dict(version=CACHE_VERSION, row=row, item=item, errors=errors,
                checked_at=dt.datetime.now(JST).isoformat())


def main():
    now = dt.datetime.now(JST)
    today = now.date().isoformat()
    outpath = str(DATA/'earnings_flash.json')
    cachepath = str(DATA/'tdnet_cache.json')
    cache = _load_existing(cachepath) or {}
    try:
        rows = fetch_list(today)
    except Exception as exc:
        previous = _load_existing(outpath) or {}
        if is_fresh(previous,36,now) and previous.get('highlights'):
            previous.update(fetch_status='fallback',cache_status='previous',last_attempt_at=now.isoformat(),
                            fetch_warning='TDnetの更新確認に失敗したため、前回取得済みの開示を掲載しています。発表日時をご確認ください。',
                            fetch_error=str(exc))
            _write_json_atomic(outpath,normalize_earnings(previous))
            return 0
        mark_failed(outpath,f'TDnet一覧取得失敗: {exc}')
        return 1
    # Today was checked successfully. Before new releases arrive, include the latest
    # prior release day (up to seven calendar days) and show its real publication date.
    article_date = today
    if not rows:
        for back in range(1,8):
            day = (now.date()-dt.timedelta(days=back)).isoformat()
            try:
                prior = fetch_list(day)
            except Exception:
                continue
            if prior:
                rows, article_date = prior, day
                break
    def reusable(row):
        entry = cache.get(row['document_url'],{})
        if entry.get('version')!=CACHE_VERSION:
            return False
        if not entry.get('errors'):
            return True
        try:
            return now-dt.datetime.fromisoformat(entry['checked_at'])<dt.timedelta(hours=6)
        except (KeyError,ValueError):
            return False
    pending = [row for row in rows if not reusable(row)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(enrich, pending):
            cache[result['row']['document_url']] = result
    cutoff = (now.date()-dt.timedelta(days=8)).isoformat()
    cache = {url:entry for url,entry in cache.items() if entry.get('row',{}).get('published_date','')>=cutoff}
    _write_json_atomic(cachepath, cache)
    selected, failures = {}, []
    for row in rows:
        result = cache[row['document_url']]
        if result.get('errors'):
            failures.append(dict(code=row['code'], url=row['document_url'], errors=result['errors']))
        item = normalize_earnings(result.get('item'))
        if not item:
            continue
        # Keep separate announcements auditable; show the strongest per company.
        old = selected.get(item['code'])
        if not old:
            selected[item['code']] = dict(item, documents=[dict(url=item['document_url'], title=item['title'], time=item['time'])])
        else:
            lead, other = (item, old) if item['impact_score']>old['impact_score'] else (old, item)
            merged = dict(lead)
            merged['key_numbers'] = list({n['label']:n for n in other['key_numbers']+lead['key_numbers']}.values())[:8]
            merged['chips'] = list({n['label']+n['value']:n for n in lead['chips']+other['chips']}.values())[:6]
            merged['impact_summary'] = '。'.join(dict.fromkeys((lead['impact_summary']+other['impact_summary']).split('。'))).rstrip('。')+'。'
            merged['narrative'] = lead['narrative']+' / '+other['narrative']
            merged['documents'] = old.get('documents',[])+[dict(url=item['document_url'],title=item['title'],time=item['time'])]
            selected[item['code']] = merged
    highlights = sorted(selected.values(), key=lambda it:(it['impact_score'],it['time']),reverse=True)[:12]
    profilespath = str(DATA/'company_profiles.json')
    profiledata = _load_existing(profilespath) or {}
    profiles = profiledata.get('companies',{})
    for item in highlights:
        code = item['code']
        if needs_refresh(profiles.get(code,{}),now):
            profiles[code] = collect_one(code,item,profiles.get(code,{}),now)
        item['name'] = profiles.get(code,{}).get('name') or item['name']
        profile = profiles.get(code,{})
        summary = profile.get('summary','')
        if len(summary)<10 or summary.endswith(('系','傘下')):
            summary = '。'.join(profile.get('description','').split('。')[:2]).strip('。')[:64]
        item['company_summary'] = summary
        item['company_summary_source'] = profiles.get(code,{}).get('source_url','')
    profiledata.update(companies=profiles,checked_at=now.isoformat())
    _write_json_atomic(profilespath,profiledata)
    if failures and not highlights:
        mark_failed(outpath,'重要開示の原資料を取得できませんでした',details={'failures':failures})
        return 1
    data = dict(updated_at=now.isoformat(),article_date=article_date,checked_date=today,
                sources=['TDnet'],source='TDnet 適時開示（XBRL / PDF）',
                source_counts={'tdnet_candidates':len(rows),'selected':len(selected),'document_failures':len(failures)},
                source_failures=failures,highlights=highlights,total=len(selected),
                groups=[dict(category='重要開示',display='重要開示',zone='decision',items=highlights)],
                fetch_status='partial' if failures else 'ok',
                selection_note='時価総額を問わず、利益の大幅増減・黒字赤字転換・業績修正・増減配・自社株買いを重要度順に掲載。比較は前年実績または前回会社予想。市場予想は未取得。',
                empty_message='対象日の重要開示はありません（TDnet確認済み）。')
    # A successful list with no significant releases is a valid result, not a fetch failure.
    safe_save(outpath,normalize_earnings(data),lambda d:1,label='決算速報・TDnet')
    print(json.dumps(dict(event='tdnet_finished',checked_date=today,article_date=article_date,
                          candidates=len(rows),selected=len(highlights),failures=failures),ensure_ascii=False))
    return 0
