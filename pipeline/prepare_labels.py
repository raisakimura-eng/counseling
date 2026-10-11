"""List the responses that are not in the dashboard yet, for comment classification.

Usage:
    python3 -I pipeline/prepare_labels.py CURRENT_HTML PERIOD_KEY OUT_TODO_JSON RAW_JSON [RAW_JSON ...]

A response counts as new when it was submitted after the period's current end
date (meta.subTo), or when it has non-empty comments none of which appear in
the dashboard yet (late submissions). OUT_TODO_JSON holds comment text, so
keep it outside the repository. Fill in "t", "p" and "shine" for every entry
(rules in pipeline/README.md), then pass the file to build.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aggregate import ROLES, extract_comments, load  # noqa: E402
from html_payload import get_payload, read_html  # noqa: E402


def find_new(payload, per, recs, raw):
    sub_to = payload['roles'][ROLES[0]]['periods'][per]['meta']['subTo']
    known = {(c['d'], c['k'], c['x'].strip()) for r in ROLES for c in payload['roles'][r]['periods'][per]['comments']}
    new = []
    for rec in sorted(recs, key=lambda r: r['sub']):
        cm, shine = extract_comments(raw[rec['id']])
        cm = [c for c in cm if not c['empty']]
        if rec['date'] > sub_to or (cm and not any((rec['date'], rec['chart'], c['x']) in known for c in cm)):
            new.append((rec, cm, shine))
    return new


def main():
    html, per, out, *files = sys.argv[1:]
    payload = get_payload(read_html(html))
    recs, raw = load(*files)
    todo = []
    for rec, cm, shine in find_new(payload, per, recs, raw):
        todo.append(dict(id=rec['id'], date=rec['date'], time=rec['sub'].strftime('%H:%M'), clinic=rec['clinic'],
                         comments=[dict(r=c['r'], tg=c['tg'], s=c['s'], x=c['x'], t=[], p='') for c in cm],
                         shine_text=shine if shine and shine.strip() else None, shine=[]))
    os.umask(0o077)
    json.dump(todo, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'{len(todo)} new responses, {sum(len(t["comments"]) for t in todo)} comments, '
          f'{sum(1 for t in todo if t["shine_text"])} shine answers -> {out}')


if __name__ == '__main__':
    main()
