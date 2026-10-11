"""Daily update of the survey dashboards on Netlify (4職種横断 + the four single-role pages).

Run by the scheduled routine every day at 0:00 JST; adds the responses submitted
up to the previous day. Two steps, with comment classification in between:

    python3 -I pipeline/daily.py prepare [--date YYYY-MM-DD]
    #  -> fill in t / p / shine in every $WORK/todo_*.json (rules: pipeline/README.md)
    python3 -I pipeline/daily.py finish [--no-deploy]

--date is the last submission date (JST) to include; default = yesterday (JST).
$WORK (default /tmp/survey-work) holds patient data; it is outside the repository.

prepare: downloads the live pages from Netlify, fetches every month from KOS,
re-checks that the closed months still reproduce exactly, and lists the new
responses per month to classify. If the dashboard already covers --date it says
so and there is nothing to do.
finish: rebuilds (catching up a month that was left unfinished, opening a new
month's tab when needed), updates the four role pages, opens every page in
Chromium, checks the numbers only grew, deploys the five sites and checks that
each one is live with password protection on.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netlify  # noqa: E402
from html_payload import get_payload, read_html  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
ALL_SITE = 'naaclinic-all-voc'
ROLE_SITES = {'受付': 'naaclinic-rc', 'カウンセラー': 'naaclinic-cs', '医師': 'naaclinic-dr', '看護師': 'naaclinic-ns'}
FIRST_DAY = dt.date(2026, 8, 11)  # first submission date on the dashboards (8/6-10 are not included)
KEYS = {'2026-08': 'aug', '2026-09': 'sep', '2026-10': 'oct'}  # tabs created by hand; later months get 'mYYYYMM'
WORK = os.environ.get('WORK', '/tmp/survey-work')


def key_of(ym):
    return KEYS.get(ym, 'm' + ym.replace('-', ''))


def label_of(ym):
    return f'{int(ym[5:])}月'


def utc(day):
    """JST midnight at the start of DAY, as an API timestamp."""
    return (dt.datetime.combine(day, dt.time(), JST) - dt.timedelta(hours=9)).strftime('%Y-%m-%dT%H:%M:%SZ')


def month_start(d):
    return d.replace(day=1)


def next_month(d):
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def run(*args):
    print('$', ' '.join(a.replace(WORK, '$WORK') for a in args), flush=True)
    subprocess.run(args, check=True, cwd=os.path.dirname(HERE))


def py(script, *args):
    run(sys.executable, '-I', os.path.join(HERE, script), *args)


def summary_line(payload):
    s = payload['summary']['all']
    return f"全期間 {s['from']}〜{s['to']} 回答 {s['nResp']}名 / 自由記述 {s['comTotal']} / 改善要望 {s['reqTotal']}"


def prepare(a):
    os.makedirs(WORK, exist_ok=True)
    os.chmod(WORK, 0o700)
    until = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(JST).date() - dt.timedelta(days=1)
    cur = os.path.join(WORK, 'current.html')
    os.makedirs(os.path.join(WORK, 'role_src'), exist_ok=True)
    get = netlify.download if not a.local else (lambda site, out: shutil.copy(os.path.join(a.local, site + '.html'), out))
    get(ALL_SITE, cur)
    for role, site in ROLE_SITES.items():
        get(site, os.path.join(WORK, 'role_src', site + '.html'))
    p = get_payload(read_html(cur))
    done_to = dt.date.fromisoformat(p['summary']['all']['to'])
    print('live:', summary_line(p))
    if until <= done_to:
        json.dump(dict(until=str(until), steps=[]), open(os.path.join(WORK, 'plan.json'), 'w'))
        print(f'NOTHING TO DO: the dashboards already include submissions up to {done_to} (target {until}).')
        return

    # raw API data, one file per month (the API allows at most 3 months per call; whole months at limit 1000 have failed)
    raw, m = {}, month_start(FIRST_DAY)
    while m <= until:
        ym = m.strftime('%Y-%m')
        start, end = max(m, FIRST_DAY), min(next_month(m), until + dt.timedelta(days=1))
        raw[ym] = os.path.join(WORK, f'raw_{ym}.json')
        py('kos_client.py', utc(start), utc(end), raw[ym])
        m = next_month(m)

    # the months already closed on the dashboard must still reproduce exactly (guards against API / rule drift)
    on_dash = {x['key'] for x in p['periodList']}
    for ym, f in raw.items():
        last_day = next_month(dt.date.fromisoformat(ym + '-01')) - dt.timedelta(days=1)
        if key_of(ym) in on_dash and last_day <= done_to:
            py('verify.py', cur, key_of(ym), label_of(ym), f)

    # months to (re)build: from the month of the first missing day up to the target month
    steps, m = [], month_start(done_to + dt.timedelta(days=1))
    while m <= until:
        ym = m.strftime('%Y-%m')
        sub_to = min(next_month(m) - dt.timedelta(days=1), until)
        todo = os.path.join(WORK, f'todo_{ym}.json')
        py('prepare_labels.py', cur, key_of(ym), todo, raw[ym])
        steps.append(dict(ym=ym, key=key_of(ym), label=label_of(ym), sub_to=str(sub_to), todo=todo,
                          month=raw[ym], all=[raw[k] for k in sorted(raw) if k <= ym]))
        m = next_month(m)
    json.dump(dict(until=str(until), steps=steps), open(os.path.join(WORK, 'plan.json'), 'w'), ensure_ascii=False, indent=1)
    n = sum(len(t['comments']) for s in steps for t in json.load(open(s['todo'])))
    print(f'READY: classify {n} comments in ' + ', '.join(s['todo'].replace(WORK, '$WORK') for s in steps) + ', then run: daily.py finish')


def finish(a):
    plan = json.load(open(os.path.join(WORK, 'plan.json')))
    if not plan['steps']:
        print('NOTHING TO DO (see prepare).')
        return
    html = os.path.join(WORK, 'current.html')
    before = get_payload(read_html(html))
    for i, s in enumerate(plan['steps']):
        out = os.path.join(WORK, f'step{i}.html')
        py('build.py', '--html', html, '--period', s['key'], '--label', s['label'], '--month', s['month'],
           '--all', *s['all'], '--labels', s['todo'], '--sub-to', s['sub_to'], '--out', out)
        html = out
    after = get_payload(read_html(html))
    b, n = before['summary']['all'], after['summary']['all']
    if n['nResp'] < b['nResp'] or n['comTotal'] < b['comTotal'] or n['to'] != plan['until']:
        sys.exit(f'STOP: unexpected result ({summary_line(before)} -> {summary_line(after)}); nothing deployed')
    roles_dir = os.path.join(WORK, 'roles')
    py('role_dashboards.py', html, roles_dir, *[os.path.join(WORK, 'role_src', s + '.html') for s in ROLE_SITES.values()])
    pages = {ALL_SITE: html}
    pages.update({site: os.path.join(roles_dir, f'{role}とクリニック総評.html') for role, site in ROLE_SITES.items()})
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    subprocess.run(['node', os.path.join(HERE, 'check_render.js'), *pages.values()], check=True,
                   env=dict(os.environ, NODE_PATH=npm_root))
    if a.no_deploy:
        print('built and checked (not deployed):', summary_line(after))
        return
    title = f"{plan['until']}提出分まで反映（自動更新）"
    for site, f in pages.items():
        netlify.deploy(site, f, title)
        print(f'deployed https://{site}.netlify.app')
    print('DONE:', summary_line(after), f"(+{n['nResp'] - b['nResp']}名, +{n['comTotal'] - b['comTotal']}件)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p1 = sub.add_parser('prepare')
    p1.add_argument('--date', help='last submission date to include (JST), default yesterday')
    p1.add_argument('--local', help='testing: read <site>.html from this folder instead of downloading from Netlify')
    p2 = sub.add_parser('finish')
    p2.add_argument('--no-deploy', action='store_true')
    a = ap.parse_args()
    os.umask(0o077)
    {'prepare': prepare, 'finish': finish}[a.cmd](a)


if __name__ == '__main__':
    main()
