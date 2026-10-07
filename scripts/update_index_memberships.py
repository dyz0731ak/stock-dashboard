"""Explicit, atomic JPX snapshot update; never called by the quote collection cron."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from index_memberships import PATH, load_memberships, parse_topix_selection, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--published', required=True)
    parser.add_argument('--effective', required=True)
    parser.add_argument('--reevaluation', required=True)
    parser.add_argument('--announcement-url', required=True)
    parser.add_argument('--document-url', required=True)
    parser.add_argument('--new-count', type=int, required=True)
    parser.add_argument('--transition-count', type=int, required=True)
    parser.add_argument('--topix-count', type=int, required=True)
    args = parser.parse_args()
    counts = dict(topix_new=args.new_count, transition=args.transition_count, topix=args.topix_count)
    text = subprocess.check_output(['pdftotext', '-layout', str(args.pdf), '-'], text=True)
    groups = parse_topix_selection(text, counts)
    data = load_memberships()
    securities = {code: [key for key in tags if key not in groups] for code, tags in data['securities'].items()}
    for key, codes in groups.items():
        data['groups'][key]['count'] = len(codes)
        for code in codes:
            securities.setdefault(code, []).append(key)
    data['securities'] = {code: tags for code, tags in sorted(securities.items()) if tags}
    data.update(version=args.published, published_at=args.published, effective_at=args.effective, reevaluation_at=args.reevaluation)
    data['sources']['jpx'] = dict(url=args.announcement_url, document_url=args.document_url,
                                sha256=hashlib.sha256(args.pdf.read_bytes()).hexdigest())
    nikkei_date = data['sources']['nikkei']['as_of']
    data['basis_note'] = f'TOPIX区分：{args.published}公表・{args.effective}構成予定（移行措置を含む）。日経225：{nikkei_date}時点。'
    validate(data)
    temporary = PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(PATH)
    print('Updated verified JPX snapshot:', counts)


if __name__ == '__main__':
    main()
