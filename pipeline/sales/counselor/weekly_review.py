"""毎週月曜、カウンセラー販売実績ダッシュボード（naa-counselor、パスワード保護）の「週次の課題」セクションを更新する。

    python3 -I pipeline/sales/counselor/weekly_review.py prepare [--week-end YYYY-MM-DD]
    #  -> $WORK/issues.json を書く（README「週次の課題ページ」の書き方）
    python3 -I pipeline/sales/counselor/weekly_review.py finish [--no-deploy]

prepare: 前週（月〜日）と直前4週の数字を KOS から作り（weekly.py --fetch）、$WORK/numbers.json と
         書き込み用の $WORK/issues.json（ひな形）を置く。
finish:  公開中の naa-counselor を取り、issues.json の文章と数字で「週次の課題」セクションを差し替え、
         Chromium で表示を確かめて、パスワード保護を確認してから公開する（ダッシュボードの数字は変えない）。
$WORK（既定 /tmp/sales-work/review）は患者のコメント本文を含むので、リポジトリの外に置く。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # pipeline/ (netlify)
import netlify  # noqa: E402

SITE = 'naa-counselor'  # 2026-10-24: 別サイト naa-counselor-review から合併（オーナーの決定）
BASE = os.environ.get('SALES_WORK', '/tmp/sales-work')
WORK = os.path.join(BASE, 'review')
RAW = os.path.join(BASE, 'counselor')  # 販売実績ダッシュボードと同じ生データの置き場（raw/）


def run(*args):
    print('$', ' '.join(args), flush=True)
    return subprocess.run(args).returncode


def prepare(a):
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    os.chmod(WORK, 0o700)
    numbers = os.path.join(WORK, 'numbers.json')
    if run(sys.executable, '-I', os.path.join(HERE, 'weekly.py'), '--work', RAW, '--fetch', '--out', numbers,
           *(['--week-end', a.week_end] if a.week_end else [])):
        sys.exit('STOP: could not make the numbers; nothing to write')
    n = json.load(open(numbers))
    todo = dict(week=n['week'], updated='', overview='', team=[],
                people={p: dict(headline='', good=[], issues=[], actions=[]) for p in n['people'] if p != 'クリニック全体'})
    json.dump(todo, open(os.path.join(WORK, 'issues.json'), 'w'), ensure_ascii=False, indent=1)
    print(f"READY: write {WORK}/issues.json for {n['week'][0]}〜{n['week'][1]} "
          f"(guide: pipeline/sales/counselor/README.md 「週次の課題ページ」), then run: weekly_review.py finish")


def finish(a):
    cur, page = os.path.join(WORK, 'current.html'), os.path.join(WORK, 'page.html')
    netlify.download(SITE, cur)
    if run(sys.executable, '-I', os.path.join(HERE, 'review_page.py'), '--numbers', os.path.join(WORK, 'numbers.json'),
           '--issues', os.path.join(WORK, 'issues.json'), '--into', cur, '--out', page):
        sys.exit('STOP: the page could not be made; nothing deployed')
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if subprocess.run(['node', os.path.join(HERE, 'check_render.js'), page], env=dict(os.environ, NODE_PATH=npm_root)).returncode:
        sys.exit('STOP: render check failed; nothing deployed')
    if a.no_deploy:
        print('built and checked (not deployed):', page)
        return
    week = json.load(open(os.path.join(WORK, 'numbers.json')))['week']
    netlify.deploy(SITE, page, f'週次の課題 {week[0]}〜{week[1]}')  # require_password: the section names staff and their issues
    print(f'DONE: https://{SITE}.netlify.app#weekly（{week[0]}〜{week[1]}）')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p1 = sub.add_parser('prepare')
    p1.add_argument('--week-end', help='Sunday of the week (JST); default: the last finished week')
    p2 = sub.add_parser('finish')
    p2.add_argument('--no-deploy', action='store_true')
    a = ap.parse_args()
    os.umask(0o077)
    {'prepare': prepare, 'finish': finish}[a.cmd](a)


if __name__ == '__main__':
    main()
