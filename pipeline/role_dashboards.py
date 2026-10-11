"""Update the four single-role dashboards (受付／看護師／医師／カウンセラーとクリニック総評) from the 4職種横断 dashboard.

Usage:
    python3 -I pipeline/role_dashboards.py NEW_4ROLE_HTML OUT_DIR ROLE_HTML [ROLE_HTML ...]

Each single-role dashboard embeds `{"periods", "periodList", "default"}` where
`periods[per]` is exactly `roles[<role>].periods[per]` of the 4職種横断 payload
(checked on 2026-10-11 for every role and period). So after build.py has
produced the new 4職種横断 HTML, the role pages are refreshed by copying those
blocks over; their HTML/CSS/JS is left untouched. Output files contain patient
data: keep OUT_DIR outside the repository.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from html_payload import get_payload, read_html, set_payload  # noqa: E402

ROLE_OF = {'Reception': '受付', 'Nurse': '看護師', 'Doctor': '医師', 'Counselor': 'カウンセラー'}
KOS_NOTE = re.compile(r'\d+月分（[^）]*提出）はKOS OpenAPIから直接取得した回答で集計しています（[^）]*更新）。')


def main():
    four, out_dir, *role_files = sys.argv[1:]
    four_html = read_html(four)
    p4 = get_payload(four_html)
    note = KOS_NOTE.search(four_html)
    os.makedirs(out_dir, exist_ok=True)
    os.umask(0o077)
    for f in role_files:
        html = read_html(f)
        role = ROLE_OF[re.search(r'NaA Clinic · (\w+)', html).group(1)]
        p = get_payload(html)
        p['periods'] = {k: p4['roles'][role]['periods'][k] for k in p['periods']}
        p['periodList'] = p4['periodList']
        html = set_payload(html, p)
        if note:
            html = KOS_NOTE.sub(note.group(0), html) if KOS_NOTE.search(html) else html.replace('含みません。', '含みません。' + note.group(0), 1)
        out = os.path.join(out_dir, f'{role}とクリニック総評.html')
        open(out, 'w', encoding='utf-8').write(html)
        oct_meta = p['periods']['oct']['meta'] if 'oct' in p['periods'] else {}
        print(f'{role}: {out}  (10月 {oct_meta.get("subFrom")}〜{oct_meta.get("subTo")}, {oct_meta.get("nResp")}名)')


if __name__ == '__main__':
    main()
