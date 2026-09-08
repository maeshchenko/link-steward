#!/usr/bin/env python3
"""Check the exact public payload and links under the historic Pages prefix."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin
import hashlib
import json
import re

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
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        assert tag not in ('script', 'iframe', 'form'), f'Unexpected element: {tag}'
        self.h1 += tag == 'h1'
        self.title += tag == 'title'
        if 'id' in a:
            assert a['id'] not in self.ids, f'Duplicate ID: {a["id"]}'
            self.ids.add(a['id'])
        if tag == 'link' and a.get('rel') == 'canonical': self.canonical = a['href']
        for key in ('href', 'src'):
            if a.get(key): self.links.append(a[key])
        if 'srcset' in a:
            self.links.extend(part.strip().split()[0] for part in a['srcset'].split(','))

pages = {}
for path in PUBLIC.glob('*.html'):
    page = Page()
    page.feed(path.read_text())
    assert page.h1 == page.title == 1, f'Invalid h1/title: {path.name}'
    if path.name != '404.html':
        suffix = '' if path.name == 'index.html' else path.name
        assert page.canonical == 'https://misheno.com/link-steward/' + suffix
    pages[path] = page

count = 0
def check(base, value):
    global count
    url = urlsplit(urljoin(ORIGIN + str(base.relative_to(PUBLIC)), value))
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
for name, digest in baseline['published_sha256'].items():
    assert hashlib.sha256((PUBLIC / name).read_bytes()).hexdigest() == digest, f'Content drift: {name}'
print(f'PASS: {len(pages)} pages, {count} local links/assets, exact {len(actual)}-file public payload; Misheno canonicals preserved.')
