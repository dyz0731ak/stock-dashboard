"""One presentation rule for earnings totals, including cached comparisons."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def format_yen(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        return '—'
    divisor, unit = (Decimal(100000000),'億円') if abs(amount)>=100000000 else (Decimal(10000),'万円')
    number = format(amount/divisor, ',f')
    if '.' in number: number=number.rstrip('0').rstrip('.')
    return ('0' if number in ('-0','+0') else number)+unit


AMOUNT = re.compile(r'([+\-−△▲]?\d[\d,，]*(?:[.．]\d+)?)\s*(千万円|百万円|億円|万円|千円|円)')
SCALE = {'千万円':10000000,'百万円':1000000,'億円':100000000,'万円':10000,'千円':1000,'円':1}


def normalize_text(text):
    def replace(match):
        # Per-share amounts retain yen, including explanatory prose.
        prefix = text[max(0,match.start()-28):match.start()]
        if match[2]=='円' and re.search(r'(?:1株|一株|１株|EPS)[^。、;；\n]{0,24}$',prefix,re.I):
            return match[0]
        raw = unicodedata.normalize('NFKC',match[1]).replace(',','').replace('−','-').replace('△','-').replace('▲','-')
        try:
            return format_yen(Decimal(raw)*SCALE[match[2]])
        except InvalidOperation:
            return match[0]
    return AMOUNT.sub(replace,text)


def normalize_earnings(value, per_share=False):
    """Normalize display strings, without changing raw numeric facts or URLs."""
    if isinstance(value,list):
        return [normalize_earnings(item,per_share) for item in value]
    if not isinstance(value,dict):
        return value
    per_share = per_share or bool(re.search(r'1株|一株|１株|EPS',str(value.get('label','')),re.I))
    display_keys = {'title','narrative','company_explanation','company_summary','impact_summary','value','comparison','fetch_warning'}
    return {key:(normalize_text(item) if isinstance(item,str) and key in display_keys and not per_share
                 else normalize_earnings(item,per_share)) for key,item in value.items()}
