"""Check that the pipeline reproduces a period already on the dashboard.

Usage:
    python3 -I pipeline/verify.py CURRENT_HTML PERIOD_KEY PERIOD_LABEL RAW_JSON [RAW_JSON ...]

Recomputes the numeric blocks of PERIOD_KEY from the raw API files and compares
them with the HTML; then regenerates the summary and the narrative copy from the
HTML's own data and compares those too. Run it on a closed month (e.g. aug, sep)
before trusting a rebuild: everything should print OK.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copytext  # noqa: E402
from aggregate import ROLES, load, role_numeric  # noqa: E402
from html_payload import get_payload, read_html  # noqa: E402


def diff(a, b, path, errs):
    if isinstance(a, dict):
        for k in a:
            if k in b:
                diff(a[k], b[k], f'{path}.{k}', errs)
            else:
                errs.append(f'{path}.{k} missing')
    elif isinstance(a, list):
        if len(a) != len(b):
            errs.append(f'{path}: {len(a)} items vs {len(b)}')
            return
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f'{path}[{i}]', errs)
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or abs(a - b) > 1e-6:
            errs.append(f'{path}: {a} vs {b}')
    elif a != b:
        errs.append(f'{path}: {a!r} vs {b!r}')


def main():
    html, per, label, *files = sys.argv[1:]
    p = get_payload(read_html(html))
    recs, _ = load(*files)
    ok = True
    for R in ROLES:
        E = p['roles'][R]['periods'][per]
        M = role_numeric(recs, R, E['meta']['minN'])
        errs = []
        for k in ('role', 'clinic', 'drivers', 'hours', 'dows'):
            diff(E[k], M[k], k, errs)
        for k in E['segs']:
            diff(sorted(E['segs'][k], key=lambda s: s['v']), sorted(M['segs'][k], key=lambda s: s['v']), f'segs.{k}', errs)
        diff(sorted(E['staff'], key=lambda s: s['name']), sorted(M['staff'], key=lambda s: s['name']), 'staff', errs)
        print(per, R, 'numbers OK' if not errs else f'numbers DIFF ({len(errs)}): {errs[:5]}')
        ok &= not errs
    P = {R: p['roles'][R]['periods'][per] for R in ROLES}
    S = copytext.summary(P, per)
    bad = [k for k in p['summary'][per] if json.dumps(p['summary'][per][k], sort_keys=True) != json.dumps(S.get(k), sort_keys=True)]
    print(per, 'summary', 'OK' if not bad else f'DIFF {bad}')
    ok &= not bad
    for R in ROLES:
        C = copytext.copy(P, R, label)
        bad = [k for k in P[R]['copy'] if P[R]['copy'][k] != C.get(k)]
        print(per, R, 'copy', 'OK' if not bad else f'DIFF {bad}')
        ok &= not bad
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
