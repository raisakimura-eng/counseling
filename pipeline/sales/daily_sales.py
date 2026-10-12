"""Daily update of the sales dashboards on Netlify (run by the routine at 0:30 JST).

    python3 -I pipeline/sales/daily_sales.py [--only counselor|landing] [--no-deploy]

counselor (naa-counselor): download the live page -> fetch every month from KOS -> build up to
yesterday (JST) -> verify --strict -> Chromium render check -> deploy.
landing (naaclinic): pipeline/sales/landing/daily.py (download, fetch, build, verify, render) -> deploy.
Exit code 3 from landing means the month's sales target is missing in pipeline/sales/targets.json.
Exit code 4 from landing (1st of a month): the closed month's 「◯月まとめ」 needs its sentences. Write the
"text" of $SALES_WORK/landing/summary_todo.json (README in landing/), then run
    python3 -I pipeline/sales/daily_sales.py --only landing --summary $SALES_WORK/landing/summary_todo.json

Both sites are public by the owner's decision (2026-10-12), so they deploy with require_password=False.
Work folders under $SALES_WORK (default /tmp/sales-work) hold patient data and stay outside the repo.
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import netlify  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
BASE = os.environ.get('SALES_WORK', '/tmp/sales-work')
ENABLED = ['counselor']  # landing is added after the owner approves publishing it


def run(*args, env=None):
    print('$', ' '.join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], env=env).returncode


def counselor(deploy):
    w = os.path.join(BASE, 'counselor')
    os.makedirs(os.path.join(w, 'out'), exist_ok=True)
    os.chmod(w, 0o700)
    until = (dt.datetime.now(JST).date() - dt.timedelta(days=1)).isoformat()
    cur, new = os.path.join(w, 'current.html'), os.path.join(w, 'out', 'new.html')
    netlify.download('naa-counselor', cur)
    d = os.path.join(HERE, 'counselor')
    if run(sys.executable, '-I', os.path.join(d, 'build.py'), '--html', cur, '--work', w, '--out', new,
           '--until', until, '--fetch-all'):
        sys.exit('STOP counselor: build failed; nothing deployed')
    if run(sys.executable, '-I', os.path.join(d, 'verify.py'), new, w, '--strict'):
        sys.exit('STOP counselor: verify --strict found differences; nothing deployed')
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if run('node', os.path.join(d, 'check_render.js'), new, env=dict(os.environ, NODE_PATH=npm_root)):
        sys.exit('STOP counselor: render check failed; nothing deployed')
    if deploy:
        netlify.deploy('naa-counselor', new, f'{until}分まで反映（自動更新）', require_password=False)
        print(f'DONE counselor: {until}分まで反映 https://naa-counselor.netlify.app')
    else:
        print('built and checked (not deployed):', new)


def landing(deploy, summary=None, today=None):
    w = os.path.join(BASE, 'landing')
    code = run(sys.executable, '-I', os.path.join(HERE, 'landing', 'daily.py'), *(['--summary', summary] if summary else []), *(['--today', today] if today else []),
               env=dict(os.environ, WORK=w))
    if code == 4:
        todo = os.path.join(w, 'summary_todo.json')
        print(f'STOP landing (exit 4): 締めた月の「◯月まとめ」の文章が必要です。{todo} の "text" を書き'
              f'（指針: pipeline/sales/landing/README.md「月まとめの文章」）、'
              f'python3 -I pipeline/sales/daily_sales.py --only landing --summary {todo} で再実行してください。nothing deployed')
        sys.exit(4)
    if code == 3:
        sys.exit('STOP landing: 今月の売上目標が pipeline/sales/targets.json にありません（【要対応】目標金額をユーザーに確認）')
    if code:
        sys.exit('STOP landing: build / verify / render check failed; nothing deployed')
    if deploy:
        netlify.deploy('naaclinic', os.path.join(w, 'new.html'), '自動更新', require_password=False)
        print('DONE landing: https://naaclinic.netlify.app')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=['counselor', 'landing'])
    ap.add_argument('--no-deploy', action='store_true')
    ap.add_argument('--today', help='landing, for tests: JST date to treat as today (the 0:30 run makes the forecast for it)')
    ap.add_argument('--summary', help='landing: summary_todo.json with the 月まとめ sentences written (after exit 4)')
    a = ap.parse_args()
    os.umask(0o077)
    for name in ([a.only] if a.only else ENABLED):
        if name == 'landing':
            landing(not a.no_deploy, a.summary, a.today)
        else:
            counselor(not a.no_deploy)


if __name__ == '__main__':
    main()
