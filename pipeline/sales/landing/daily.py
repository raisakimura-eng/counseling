"""Daily update of the 着地予想ダッシュボード (meant to run at 0:00 JST).

    python3 -I pipeline/sales/landing/daily.py [--today YYYY-MM-DD] [--html CURRENT.html]
    python3 -I pipeline/sales/landing/daily.py --intraday     # 12/14/16/18/20時: today's results only

1. downloads the live page from Netlify (site `naaclinic`), unless --html is given
2. fetches KOS statistics into $WORK (default /tmp/sales-work/landing; patient data, outside the repo)
3. build.py: closes yesterday, makes today's forecast, rolls the month over on the 1st
4. verify.py: compares the published days with the API (report only)
5. check_render.js: opens every tab/day in Chromium (fails on errors, NaN, undefined)

It does not deploy. The new page is $WORK/new.html; publishing is a separate, deliberate step.
Exit codes: 0 ready, 3 the month's sales target is missing (ask for it: pipeline/sales/targets.json),
4 a closed month needs its 「◯月まとめ」 sentences: write the "text" of $WORK/summary_todo.json
  (guidelines: README.md 「月まとめの文章」) and run again with --summary $WORK/summary_todo.json,
1 anything else (build, sanity or render check failed).
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
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import config  # noqa: E402
import page  # noqa: E402

from data import JST  # noqa: E402

WORK = os.environ.get('WORK', '/tmp/sales-work/landing')
TARGETS = os.path.join(os.path.dirname(HERE), 'targets.json')


def py(script, *args):
    print('$', script, ' '.join(str(a).replace(WORK, '$WORK') for a in args), flush=True)
    return subprocess.run([sys.executable, '-I', os.path.join(HERE, script), *map(str, args)]).returncode


def intraday(a):
    """12・14・16・18・20時: download the live page, fetch today's reservations only, refresh the results."""
    os.makedirs(WORK, exist_ok=True)
    os.chmod(WORK, 0o700)
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    w = os.path.join(WORK, 'intraday')
    cur, new = os.path.join(w, 'current.html'), os.path.join(WORK, 'new.html')
    os.makedirs(w, exist_ok=True)
    if a.html:
        shutil.copy(a.html, cur)
    else:
        sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
        import netlify
        netlify.download(config.SITE, cur)
    if page.get_consts(open(cur, encoding='utf-8').read())['TODAY']['date'] != f'{today.month}/{today.day}':
        sys.exit(f'STOP: the live page has no forecast for {today} yet (the 0:30 run did not publish); nothing to refresh')
    if py('fetch.py', '--from', today, '--to', today, '--kinds', 'schedule', '--exact', '--work', w):
        sys.exit('STOP: fetching KOS data failed; nothing built')
    if py('build.py', '--intraday', '--html', cur, '--work', w, '--out', new, '--today', today):
        sys.exit(1)
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    if subprocess.run(['node', os.path.join(HERE, 'check_render.js'), new], env=dict(os.environ, NODE_PATH=npm_root)).returncode:
        sys.exit('STOP: the page does not render cleanly; not ready to publish')
    print('READY (intraday): $WORK/new.html')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--today', help='JST date of the new day (default: today in JST)')
    ap.add_argument('--html', help='use this page instead of downloading it from Netlify')
    ap.add_argument('--summary', help='$WORK/summary_todo.json after its "text" was written: makes the 月まとめ tab')
    ap.add_argument('--intraday', action='store_true', help='日中の更新: refresh only today\'s results (no forecast change)')
    a = ap.parse_args()
    os.umask(0o077)
    if a.intraday:
        return intraday(a)
    os.makedirs(WORK, exist_ok=True)
    os.chmod(WORK, 0o700)
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(JST).date()
    yday = today - dt.timedelta(days=1)
    ym = today.strftime('%Y-%m')
    targets = config.load_targets(TARGETS)
    if not targets.get(ym):
        print(f'【要対応】{today.month}月の売上目標が未設定です。金額を教えてください（pipeline/sales/targets.json に "{ym}": 金額 を追加）。')
        sys.exit(3)
    cur = os.path.join(WORK, 'current.html')
    if a.html:
        open(cur, 'w', encoding='utf-8').write(open(a.html, encoding='utf-8').read())
    else:
        sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
        import netlify
        netlify.download(config.SITE, cur)
    consts = page.get_consts(open(cur, encoding='utf-8').read())
    new = os.path.join(WORK, 'new.html')
    if consts['TODAY']['date'] == f'{today.month}/{today.day}':
        print(f'NOTHING TO DO: the page already shows the forecast for {today}.')
        shutil.copy(cur, new)  # so that publishing new.html is harmless
        return
    # which month will be the reference month after this run, and does it still need its 月まとめ?
    mon = consts.get('MON')
    if mon:
        cur_ym = f"{mon['y']}-{mon['c']:02d}"
        base_ym = cur_ym if today.strftime('%Y-%m') != cur_ym else f"{mon['by']}-{mon['b']:02d}"
    else:
        base_ym = config.LEGACY_SUMMARY
    need_summary = base_ym != config.LEGACY_SUMMARY and base_ym not in {x['key'] for x in consts.get('SUMMARIES', [])}
    # published days not yet restated to the current 着地結果 definition need their month's data too
    restate_base = any('Cex' not in r for r in consts.get('DAYS_BASE', []))
    if need_summary:
        # the まとめ compares with the two months before: fetch them too (closed months are cached in $WORK)
        y, m = map(int, base_ym.split('-'))
        k = y * 12 + m - 1 - 2
        first = dt.date(k // 12, k % 12 + 1, 1)
    elif restate_base or today.day == 1:
        first = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)  # the previous month
    else:
        first = today.replace(day=1)
    month_end = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    vis_from = base_ym if need_summary else first.strftime('%Y-%m')
    rc = py('fetch.py', '--from', first, '--to', today, '--future-to', month_end, '--work', WORK, '--visitors', vis_from)
    if rc:
        sys.exit(f'STOP: fetching KOS data failed (exit {rc}); nothing built')
    todo = os.path.join(WORK, 'summary_todo.json')
    stale = os.path.join(WORK, 'daily_analysis.json')
    if os.path.exists(stale):
        os.remove(stale)  # only a file made by this run may be posted
    rc = py('build.py', '--html', cur, '--work', WORK, '--out', new, '--today', today,
            *(['--summary', a.summary] if a.summary else ['--summary-todo', todo]))
    if rc == 4:
        print(f'SUMMARY NEEDED: {base_ym[5:].lstrip("0")}月まとめの文章を {todo} の "text" に書き（指針: pipeline/sales/landing/README.md「月まとめの文章」）、'
              f'daily.py --summary {todo} で作り直してください。公開できる状態ではありません。')
        sys.exit(4)
    if rc:
        sys.exit(rc)
    c = page.get_consts(open(new, encoding='utf-8').read())
    problems = []
    if c['TODAY']['date'] != f'{today.month}/{today.day}':
        problems.append('TODAY is not today')
    if today.day != 1 and (not c['DAYS_CUR'] or c['DAYS_CUR'][-1]['date'] != f'{yday.month}/{yday.day}'):
        problems.append('yesterday is missing from the month')
    last = (c['DAYS_CUR'] or c['DAYS_BASE'])[-1]
    for r in c['DAYS_BASE'] + c['DAYS_CUR']:
        if r['visN'] and not r['C']:
            problems.append(f"{r['date']}: visits but 着地結果 0 (KOS data missing in $WORK?)")
    if last['bookN'] and not last['visN']:
        problems.append(f"{last['date']}: reservations but no completed visit (KOS statuses not updated yet?)")
    if last['visN'] and not last.get('payC'):
        problems.append(f"{last['date']}: visits but no payments (KOS data incomplete?)")
    if problems:
        sys.exit('STOP: ' + '; '.join(problems))
    py('verify.py', '--html', new, '--work', WORK, '--json', os.path.join(WORK, 'verify.json'))
    npm_root = subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()
    rc = subprocess.run(['node', os.path.join(HERE, 'check_render.js'), new], env=dict(os.environ, NODE_PATH=npm_root)).returncode
    if rc:
        sys.exit('STOP: the page does not render cleanly; not ready to publish')
    T, G = c['TODAY'], c['TARGET']
    act = sum(r[2] for r in G['rows'] if r[3] == 'actual')
    y = last
    print(f"READY: $WORK/new.html — {y['date']} 着地結果 {y.get('payC', y['C']):,}円（朝の予想 {y['Amorning']:,}円）, "
          f"{T['date']}の着地予想 {T['cur']:,}円（予約{T['active']}件）, {G['month']}累計 {act:,}円 / 目標 {G['target']:,}円")
    # 「この日の分析」 of the closed day, for the Slack post (not on the page). A failure here does not stop publishing.
    out = os.path.join(WORK, 'daily_analysis.json')
    if py('analysis.py', '--html', new, '--work', WORK, '--day', yday, '--out', out):
        print('WARNING: daily_analysis.json could not be made; the page is still ready to publish')


if __name__ == '__main__':
    main()
