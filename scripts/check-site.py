#!/usr/bin/env python3
"""Check the exact public payload and links under the historic Pages prefix."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin
import hashlib
import json
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'public'
ORIGIN = 'https://maeshchenko.github.io/link-steward/'
EXPECTED = {
    'index.html', 'guide.html', 'support.html', 'privacy.html', 'terms.html',
    'security.html', 'dpa.html', '404.html', '.nojekyll', 'favicon.svg',
    'assets/app.css', 'assets/inter-LICENSE.txt', 'assets/inter-variable.woff2',
    'assets/link-repair-hero.webp', 'assets/review-with-confidence.webp', 'assets/social-card.png',
}
assert not any(p.is_symlink() for p in PUBLIC.rglob('*')), 'Symlink in public payload'
actual = {str(p.relative_to(PUBLIC)) for p in PUBLIC.rglob('*') if p.is_file()}
assert actual == EXPECTED, f'Unexpected or missing public files: {actual ^ EXPECTED}'
assert not (ROOT / 'forge-app').exists(), 'Application source does not belong in this public repository'

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.canonical = [], set(), None
        self.h1 = self.title = 0
        self.meta, self.structured = {}, []
        self.title_text, self.in_title, self.json_text = '', False, None
        self.lang = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        assert tag not in ('iframe', 'form'), f'Unexpected element: {tag}'
        assert not any(key.startswith('on') for key in a), 'Unexpected event handler'
        if tag == 'script':
            assert a == {'type': 'application/ld+json'}, 'Only inline JSON-LD is permitted'
            self.json_text = ''
        if tag == 'title': self.in_title = True
        if tag == 'html': self.lang = a.get('lang')
        if tag == 'meta' and ('name' in a or 'property' in a):
            key = a.get('name', a.get('property'))
            assert key not in self.meta, f'Duplicate metadata: {key}'
            self.meta[key] = a.get('content', '')
        if tag == 'img':
            assert 'alt' in a and a.get('width') and a.get('height'), 'Image needs alt and dimensions'
        self.h1 += tag == 'h1'
        self.title += tag == 'title'
        if 'id' in a:
            assert a['id'] not in self.ids, f'Duplicate ID: {a["id"]}'
            self.ids.add(a['id'])
        if tag == 'link' and a.get('rel') == 'canonical':
            assert self.canonical is None, 'Duplicate canonical'
            self.canonical = a['href']
        for key in ('href', 'src'):
            if a.get(key): self.links.append(a[key])
        if 'srcset' in a:
            self.links.extend(part.strip().split()[0] for part in a['srcset'].split(','))
    def handle_data(self, data):
        if self.in_title: self.title_text += data
        if self.json_text is not None: self.json_text += data
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
        if tag == 'script' and self.json_text is not None:
            self.structured.append(json.loads(self.json_text))
            self.json_text = None

pages = {}
for path in PUBLIC.glob('*.html'):
    page = Page()
    page.feed(path.read_text())
    assert page.h1 == page.title == 1, f'Invalid h1/title: {path.name}'
    assert page.lang == 'en', f'Missing page language: {path.name}'
    if path.name != '404.html':
        suffix = '' if path.name == 'index.html' else path.name
        assert page.canonical == 'https://misheno.com/link-steward/' + suffix
        assert page.meta.get('og:url') == page.canonical, f'OG URL mismatch: {path.name}'
        assert page.title_text == page.meta.get('og:title') == page.meta.get('twitter:title'), f'Title mismatch: {path.name}'
        description = page.meta.get('description')
        assert description and description == page.meta.get('og:description') == page.meta.get('twitter:description'), f'Description mismatch: {path.name}'
        assert 'noindex' not in page.meta.get('robots', ''), f'Content page excluded: {path.name}'
        assert page.meta.get('twitter:card') == 'summary_large_image'
        image_url = page.meta.get('og:image')
        assert image_url == page.meta.get('twitter:image') == 'https://misheno.com/link-steward/assets/social-card.png'
        assert page.meta.get('og:image:type') == 'image/png'
        assert (page.meta.get('og:image:width'), page.meta.get('og:image:height')) == ('1200', '630')
        assert page.meta.get('og:image:alt') and page.meta.get('twitter:image:alt')
        assert len(page.structured) == 1, f'Missing or duplicate JSON-LD: {path.name}'
        schema = page.structured[0]
        assert schema.get('@context') == 'https://schema.org'
        graph = schema['@graph']
        webpage = graph[0]
        assert webpage['@type'] == 'WebPage' and webpage['url'] == page.canonical
        assert webpage['name'] == page.title_text and webpage['description'] == description
        assert webpage['primaryImageOfPage']['url'] == image_url
        if path.name != 'index.html':
            assert len(graph) == 2 and graph[1]['@type'] == 'BreadcrumbList'
            items = graph[1]['itemListElement']
            assert [item['position'] for item in items] == [1, 2]
            assert items[0]['item'] == 'https://misheno.com/link-steward/'
            assert items[1]['item'] == page.canonical
    else:
        assert 'noindex' in page.meta.get('robots', ''), '404 must be excluded from search'
    pages[path] = page

indexable = [page for path, page in pages.items() if path.name != '404.html']
assert len({page.title_text for page in indexable}) == len(indexable), 'Duplicate page titles'
assert len({page.meta['description'] for page in indexable}) == len(indexable), 'Duplicate page descriptions'
social = (PUBLIC / 'assets/social-card.png').read_bytes()
assert social[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', social[16:24]) == (1200, 630)

count = 0
def check(base, value):
    global count
    url = urlsplit(urljoin(ORIGIN + str(base.relative_to(PUBLIC)), value))
    assert url.scheme not in ('javascript', 'data'), f'Unexpected executable link: {value}'
    if url.scheme not in ('http', 'https') or url.netloc != 'maeshchenko.github.io': return
    assert url.path.startswith('/link-steward/'), f'Link leaves project prefix: {value}'
    target = (PUBLIC / unquote(url.path.removeprefix('/link-steward/'))).resolve()
    assert target.is_relative_to(PUBLIC), f'Link escapes website: {value}'
    if target.is_dir(): target /= 'index.html'
    assert target.is_file(), f'Missing target: {base.name}: {value}'
    if url.fragment and target in pages:
        assert unquote(url.fragment) in pages[target].ids, f'Missing fragment: {value}'
    count += 1

for path, page in pages.items():
    for value in page.links: check(path, value)
for css in PUBLIC.rglob('*.css'):
    for value in re.findall(r'url\([\s\'\"]*([^\)\'\"\s]+)', css.read_text()): check(css, value)

baseline = json.loads((ROOT / 'site-source.json').read_text())
assert set(baseline['published_sha256']) == EXPECTED, 'Manifest must cover the exact public payload'
for name, digest in baseline['published_sha256'].items():
    assert hashlib.sha256((PUBLIC / name).read_bytes()).hexdigest() == digest, f'Content drift: {name}'
print(f'PASS: {len(pages)} pages, {count} local links/assets, exact {len(actual)}-file public payload; unique metadata, JSON-LD, social card and Misheno canonicals verified.')
