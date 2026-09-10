"""Validate generated HTML/JSON and existing internal links without a browser."""
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]

def main():
    sitemap=BeautifulSoup((ROOT/'sitemap.xml').read_text(),'xml')
    pages=[ROOT/urlparse(loc.get_text()).path.lstrip('/')/'index.html' for loc in sitemap.find_all('loc')]
    for path in pages:
        if '.git' in path.parts:continue
        soup=BeautifulSoup(path.read_text(),'html.parser')
        assert soup.title and soup.select_one('link[rel="canonical"]'), f'SEO metadata missing: {path}'
        ids=[x['id'] for x in soup.select('[id]')]
        assert len(ids)==len(set(ids)), f'duplicate IDs: {path}'
        for script in soup.select('script[type="application/ld+json"]'):json.loads(script.string)
        for a in soup.select('a[href]'):
            href=a['href'];parsed=urlparse(href)
            if parsed.scheme and parsed.netloc != 'dashboard.stock-overflow24.com':continue
            if not parsed.path:continue
            target=ROOT/unquote(parsed.path).lstrip('/') if parsed.path.startswith('/') else path.parent/unquote(parsed.path)
            if not target.suffix:target=target/'index.html'
            assert target.exists(), f'broken internal link: {path}: {href}'
    for path in (ROOT/'data').glob('*.json'):
        json.loads(path.read_text(),parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'{path}: {x}')))
    print(f'HTML/SEO/internal-link checks passed: {len(pages)} pages; all data JSON valid')
if __name__=='__main__':main()
