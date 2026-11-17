"""Put the 受付 受電率 report (TOBILA call history, a static snapshot) into the reception VOC page as a 受電率 tab.

Usage:
    python3 -I pipeline/rc_calls.py REPORT_HTML            # build + browser check only
    python3 -I pipeline/rc_calls.py REPORT_HTML --publish  # ... then publish to naaclinic-rc

REPORT_HTML is the standalone 受電率 report (<title>受付 受電率レポート 11/1〜11/16</title>, body in <main>).
The live page is downloaded, any earlier 受電率 tab (between the calls:start / calls:end markers) is replaced,
and nothing else changes: the survey payload and scripts stay as they are, so daily.py, which only swaps the
payload, keeps the tab. TOBILA has no API, so the numbers stay at the report's period until the next report.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netlify  # noqa: E402

SITE = 'naaclinic-rc'
WORK = os.environ.get('CALLS_WORK', '/tmp/rc-calls-work')
HERE = os.path.dirname(os.path.abspath(__file__))
MARK = {'css': ('/* calls:start */', '/* calls:end */'), 'html': ('<!-- calls:start -->', '<!-- calls:end -->')}

CSS = '''/* calls:start */
/* ---- 受電率 view (static snapshot from TOBILA call history) ---- */
#calls{display:none; --olive:var(--accent-2); --deep:var(--accent); --sage:#cdcabc; --tint:var(--accent-soft);
  --line:var(--rule); --bg:var(--surface); --miss:var(--crit);
  flex-direction:column; gap:32px; padding-top:28px}
body.calls-view #calls{display:flex}
body.calls-view .wrap > :not(#calls), body.calls-view #periodbar, body.calls-view .mast-meta{display:none !important}
#calls .calls-head{display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 14px; border-bottom:2px solid var(--olive); padding-bottom:10px}
#calls .calls-head h2{font-size:1.5rem; font-weight:600; color:var(--deep); margin:0; border:0; padding:0}
#calls .calls-badge{font-size:12px; color:var(--muted); background:var(--tint); border:1px solid var(--line); border-radius:999px; padding:2px 10px}
#calls .lede{margin:0; max-width:70ch; font-size:15px; line-height:1.8} #calls .lede b{color:var(--deep); font-variant-numeric:tabular-nums}
#calls .meta{margin:-20px 0 0; color:var(--muted); font-size:12px}
#calls .tiles{display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px}
@media (max-width:640px){ #calls .tiles{grid-template-columns:repeat(2,minmax(0,1fr))} }
#calls .tile{background:var(--tint); border:1px solid var(--line); border-radius:8px; padding:16px; display:flex; flex-direction:column; gap:4px}
#calls .tile .l{font-size:12px; color:var(--deep); font-weight:600} #calls .tile .v{font-size:2.1rem; font-weight:600; line-height:1.1; font-variant-numeric:tabular-nums}
#calls .tile .s{font-size:12px; color:var(--muted)} #calls .tile.alert{background:var(--bg); border-color:var(--miss)} #calls .tile.alert .v{color:var(--miss)}
#calls h2{margin:0 0 10px; font-size:1.1rem; color:var(--deep); border-left:4px solid var(--olive); padding-left:10px}
#calls .finds{display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px}
#calls .find{background:var(--tint); border-left:3px solid var(--olive); border-radius:0 8px 8px 0; padding:10px 14px; line-height:1.7} #calls .find b{color:var(--deep)}
#calls .legend{display:flex; flex-wrap:wrap; gap:14px; font-size:12px; color:var(--muted); margin:0 0 6px}
#calls .legend i{display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px}
#calls .legend i.ln{width:16px; height:0; border-top:2px solid var(--ink); border-radius:0}
#calls svg{width:100%; height:auto; display:block}
@media (max-width:640px){ #calls .tw svg{min-width:680px} }  /* keep chart labels legible; the chart scrolls sideways in its box */
#calls svg .grid{stroke:var(--line)} #calls svg .ax{fill:var(--muted); font-size:12px} #calls svg .ok{fill:var(--olive)} #calls svg .ng{fill:var(--miss)} #calls svg .sage{fill:var(--sage)}
#calls svg .rl{fill:var(--ink); font-size:12px; font-weight:600; paint-order:stroke; stroke:var(--paper); stroke-width:4px; stroke-linejoin:round} #calls svg .rl.low{fill:var(--miss)}
#calls svg .ma{stroke:var(--ink); stroke-width:2; opacity:.85} #calls svg .mad{fill:var(--ink); stroke:var(--paper); stroke-width:1.5}
#calls .note{color:var(--muted); font-size:12px; margin:6px 0 0}
#calls .tw{overflow-x:auto} #calls table{border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; background:var(--surface)}
#calls th, #calls td{padding:8px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap} #calls th:first-child, #calls td:first-child{text-align:left}
#calls th{background:var(--tint); color:var(--deep); font-size:12px}
#calls details summary{cursor:pointer; color:var(--deep); font-weight:600} #calls details ul{color:var(--muted); line-height:1.8; max-width:75ch}
/* calls:end */
'''

SCRIPT = '''<!-- calls:start -->
<script>
/* 受電率 view tab. The VOC script removes #viewbar when there is no audit view; then this adds its own tab bar. */
(function(){
  var calls = document.getElementById('calls'); if (!calls) return;
  if (document.getElementById('viewbar')) { calls.style.display = 'flex'; return; }
  var bar = document.createElement('div');
  bar.className = 'viewbar'; bar.id = 'callsbar';
  bar.innerHTML = '<div class="inner"><div class="vtabs" role="tablist" aria-label="表示するデータ">' +
    '<button class="vtab" role="tab" data-v="survey" aria-selected="true">満足度アンケート</button>' +
    '<button class="vtab" role="tab" data-v="calls" aria-selected="false">受電率（__PERIOD__）</button>' +
    '</div><span class="vnote">アンケートの星評価と自由記述</span></div>';
  var pb = document.getElementById('periodbar');
  pb.parentNode.insertBefore(bar, pb);
  var note = bar.querySelector('.vnote');
  bar.querySelector('.vtabs').addEventListener('click', function(e){
    var b = e.target.closest('.vtab'); if (!b) return;
    var v = b.dataset.v;
    Array.prototype.forEach.call(bar.querySelectorAll('.vtab'), function(x){ x.setAttribute('aria-selected', String(x === b)); });
    document.body.classList.toggle('calls-view', v === 'calls');
    note.textContent = v === 'calls' ? 'TOBILA の通話履歴から作成（__PERIOD__ の固定データ）' : 'アンケートの星評価と自由記述';
    window.scrollTo({top: 0, behavior: 'smooth'});
  });
})();
</script>
<!-- calls:end -->
'''


def strip(html):
    """Remove an earlier 受電率 tab (every block between the markers)."""
    for a, b in MARK.values():
        html = re.sub(re.escape(a) + r'.*?' + re.escape(b) + r'\n?', '', html, flags=re.S)
    if 'id="calls"' in html:
        raise SystemExit('STOP: the page has a 受電率 tab without calls:start / calls:end markers; not touching it.')
    return html


def merge(rc, rep):
    title = re.search(r'<title>([^<]*)</title>', rep).group(1)
    period = title.split()[-1]  # 受付 受電率レポート 11/1〜11/16 -> 11/1〜11/16
    body = re.search(r'<main>(.*)</main>', rep, re.S).group(1)
    if re.search(r'0\d{1,4}-\d{1,4}-\d{3,4}', re.sub(r'<p class="meta">.*?</p>', '', body, flags=re.S)):
        raise SystemExit('STOP: the report seems to contain phone numbers outside the source line; check it first.')
    head = re.search(r'<header>(.*?)</header>', body, re.S)
    lede = re.search(r'<p class="lede">.*?</p>', head.group(1), re.S).group(0)
    meta = re.search(r'<p class="meta">.*?</p>', head.group(1), re.S).group(0)
    section = (f'{MARK["html"][0]}\n  <section id="calls" aria-label="受電率">\n    <div class="calls-head">\n'
               f'      <h2 class="mincho">受付 受電率レポート（{period}）</h2>\n'
               '      <span class="calls-badge">固定スナップショット・毎日の自動更新の対象外</span>\n    </div>\n'
               f'    {lede}\n    {meta}\n{body[head.end():]}\n  </section>\n{MARK["html"][1]}\n')
    rc = strip(rc)
    i = rc.index('</style>')
    rc = rc[:i] + CSS + rc[i:]
    p = rc.index('<script type="application/json" id="payload">')
    w = rc.rindex('</div>', 0, p)  # end of .wrap
    rc = rc[:w] + section + rc[w:]
    b = rc.rindex('</body>')
    return rc[:b] + SCRIPT.replace('__PERIOD__', period) + rc[b:], period


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('report')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    os.umask(0o077)
    cur, out = os.path.join(WORK, 'current.html'), os.path.join(WORK, 'rc.html')
    netlify.download(SITE, cur)
    html, period = merge(open(cur, encoding='utf-8').read(), open(a.report, encoding='utf-8').read())
    open(out, 'w', encoding='utf-8').write(html)
    env = dict(os.environ, NODE_PATH=subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip())
    for js in ('check_render.js', 'check_calls.js'):
        subprocess.run(['node', os.path.join(HERE, js), out], check=True, env=env)
    print(f'built {out} (受電率 {period})')
    if a.publish:
        print('published', SITE, netlify.deploy(SITE, out, f'受電率 tab {period}'))


if __name__ == '__main__':
    main()
