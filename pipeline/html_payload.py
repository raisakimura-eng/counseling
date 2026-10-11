"""Read / write the JSON payload embedded in the dashboard HTML (<script id="payload">)."""
import json
import re

OPEN = '<script type="application/json" id="payload">'
# claude.ai wraps a published page in this skeleton; a page saved from `Artifact read` still carries it
WRAP_HEAD = re.compile(r'^<!doctype html><html><head><meta charset=utf8>.*?</head><body>', re.S)
WRAP_TAIL = '</body></html>'


def read_html(path):
    t = open(path, encoding='utf-8').read()
    m = WRAP_HEAD.match(t)
    if m:
        t = t[m.end():]
        t = t[:t.rindex(WRAP_TAIL)] if WRAP_TAIL in t else t
    return t


def get_payload(html):
    a = html.index(OPEN) + len(OPEN)
    return json.loads(html[a:html.index('</script>', a)])


def set_payload(html, payload):
    a = html.index(OPEN) + len(OPEN)
    b = html.index('</script>', a)
    return html[:a] + json.dumps(payload, ensure_ascii=False).replace('</', '<\\/') + html[b:]
