"""Shared index data for SSG and future event/ranking filters; never infers from names."""
import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'data' / 'index_memberships.json'
LABELS = {'topix': 'TOPIX', 'topix_new': 'TOPIX新規', 'transition': '移行措置', 'nikkei225': '日経225'}


def normalize_code(value):
    code = re.sub(r'\.T$', '', str(value or '').strip().upper())
    return code if re.fullmatch(r'[0-9][0-9A-Z]{3}', code) else ''


def validate(data):
    if data.get('schema_version') != 1 or not data.get('version') or not data.get('basis_note'):
        raise ValueError('Invalid index metadata')
    counts = dict.fromkeys(LABELS, 0)
    for code, tags in data['securities'].items():
        if normalize_code(code) != code or not isinstance(tags, list) or not tags or len(tags) != len(set(tags)):
            raise ValueError('Invalid index membership: ' + code)
        for key in tags:
            if key not in LABELS:
                raise ValueError('Unknown index: ' + key)
            counts[key] += 1
    for key, count in counts.items():
        if not count or data['groups'][key]['count'] != count:
            raise ValueError('Index count mismatch: ' + key)
    return data


def load_memberships(path=PATH):
    return validate(json.loads(path.read_text(encoding='utf-8')))


def memberships(data, code):
    tags = data['securities'].get(normalize_code(code), [])
    return [key for key in LABELS if key in tags]


def filter_rows(rows, condition, data, code_key='code'):
    return [row for row in rows if condition == 'all' or condition in memberships(data, row.get(code_key))]


def parse_topix_selection(text, expected_counts):
    """Import pdftotext -layout output. Reject missing/duplicate/out-of-order rows."""
    sections = re.split(r'（[１２３]）[^\n]+', text)[1:]
    if len(sections) != 3:
        raise ValueError('Expected JPX new/transition/constituents sections')
    groups = {}
    for key, section in zip(['topix_new', 'transition', 'topix'], sections):
        rows = re.findall(r'^\s*(\d+)\s+([0-9A-Z]{4})\s+.+?\s+(?:プライム|スタンダード|グロース)\s*$', section, re.M)
        count = expected_counts[key]
        codes = [row[1] for row in rows]
        if len(codes) != count or len(set(codes)) != count or [int(row[0]) for row in rows] != list(range(1, count + 1)):
            raise ValueError('JPX section count/sequence mismatch: ' + key)
        groups[key] = codes
    if not set(groups['topix_new']).isdisjoint(groups['transition']):
        raise ValueError('New and transition memberships overlap')
    if not (set(groups['topix_new']) | set(groups['transition'])) <= set(groups['topix']):
        raise ValueError('Selection missing from constituent list')
    return groups
