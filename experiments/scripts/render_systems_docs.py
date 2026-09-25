#!/usr/bin/env python3
"""Build offline UTF-8 HTML documents linked from the systems gallery.

Markdown and JSON remain the source of truth. No runtime fetch, CDN or web
server is needed when the generated pages are opened from the filesystem.
"""
import hashlib
import html
import json
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1] / 'network-and-load'
PAGES = {
    'README.md': ('README.html', 'ko', 'KPQC TLS 실험 보고서'),
    'README.en.md': ('README.en.html', 'en', 'KPQC TLS experiment report'),
    'METHODS.md': ('METHODS.html', 'ko', '실험 방법'),
    'METHODS.en.md': ('METHODS.en.html', 'en', 'Experimental methods'),
    'audit.json': ('audit.html', 'ko', '검증 요약 / Audit'),
}
CSS = '''
*{box-sizing:border-box}body{margin:0;background:#f6f8fa;color:#182b3a;
font:16px/1.75 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:1120px;margin:32px auto;padding:32px;background:#fff}
nav{display:flex;flex-wrap:wrap;gap:8px 20px;border-bottom:1px solid #dce3e8;padding-bottom:16px}
a{color:#006da8;overflow-wrap:anywhere}h1{line-height:1.35}h2{margin-top:2em}
img{max-width:100%;height:auto}table{border-collapse:collapse;display:block;overflow-x:auto;margin:20px 0}
th,td{border:1px solid #dce3e8;padding:9px 12px}th{background:#edf3f7}
pre{padding:16px;background:#f1f4f7;overflow:auto;line-height:1.5}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
footer{border-top:1px solid #dce3e8;margin-top:32px;padding-top:16px}
@media(max-width:640px){main{margin:0;padding:20px}h1{font-size:26px}}
'''


def rewrite_links(body):
    for source, (target, _, _) in PAGES.items():
        body = body.replace(f'href="{source}"', f'href="{target}"')
    return body


def build():
    for source, (target, lang, title) in PAGES.items():
        text = (ROOT / source).read_text(encoding='utf-8')
        if source.endswith('.json'):
            body = '<h1>검증 요약 / Audit</h1><pre>' + html.escape(
                json.dumps(json.loads(text), ensure_ascii=False, indent=2)) + '</pre>'
        else:
            body = markdown.markdown(text, extensions=['tables', 'fenced_code'])
        body = rewrite_links(body)
        page = f'''<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body><main>
<nav aria-label="Documents"><a href="gallery.html">그림 모음 / Gallery</a>
<a href="README.html">보고서</a><a href="README.en.html">Report</a>
<a href="METHODS.html">실험 방법</a><a href="METHODS.en.html">Methods</a>
<a href="audit.html">Audit</a></nav>
{body}
<footer><a href="{source}" download>원본 다운로드 / Download source</a></footer>
</main></body></html>
'''
        (ROOT / target).write_text(page, encoding='utf-8')
    gallery = ROOT / 'gallery.html'
    gallery.write_text(rewrite_links(gallery.read_text(encoding='utf-8')), encoding='utf-8')
    # Catch missing document/image links before handing out an offline gallery.
    for filename in ['gallery.html'] + [v[0] for v in PAGES.values()]:
        page = (ROOT / filename).read_text(encoding='utf-8')
        assert '<meta charset="utf-8">' in page[:1024]
        assert '\ufffd' not in page, filename
        for link in re.findall(r'(?:href|src)="([^"]+)"', page):
            if not link.startswith(('http:', 'https:', '#')):
                assert (ROOT / link.split('#')[0]).exists(), (filename, link)
    files = sorted(p for p in ROOT.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (ROOT / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(ROOT)) + '\n'
        for p in files), encoding='utf-8')
    print('Rendered and checked five UTF-8 document pages and gallery links.')


if __name__ == '__main__':
    build()
