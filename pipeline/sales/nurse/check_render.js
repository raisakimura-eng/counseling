// 看護師ダッシュボードを Chromium で開き、全期間・各日 × VOC（施術と同期間／全回答）を切り替え、
// 表の並べ替え・行の選択・Excel 読み込み欄の開閉もして、JS エラーや「NaN」「undefined」「Infinity」「null」の表示がないか確認する。
// --expect EXPECT.json（verify.py --expect の出力）を付けると、各表示のサマリー・スコアボードの各行・VOC コメント数が
// Python の再現（page.Calc）と同じかも確かめる（ページの JS と verify.py の集計がずれていないことの確認）。
//
// Usage: NODE_PATH=$(npm root -g) node pipeline/sales/nurse/check_render.js FILE.html [--expect EXPECT.json]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BAD = /\bNaN\b|\bundefined\b|\bInfinity\b|\bnull\b/;

async function scan(page, where, errs) {
  const r = await page.evaluate((src) => {
    const re = new RegExp(src);
    const tip = document.getElementById('tip');
    const t = document.querySelector('.wrap').innerText + '\n' + (tip && !tip.hidden ? tip.innerText : '');
    const m = t.match(re);
    if (m) return 'text: ' + t.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ');
    for (const el of document.querySelectorAll('svg *')) {
      for (const a of el.getAttributeNames()) {
        if (/NaN|undefined|Infinity/.test(el.getAttribute(a))) return `svg ${el.tagName}[${a}]=${el.getAttribute(a).slice(0, 60)}`;
      }
    }
    return '';
  }, BAD.source);
  if (r) errs.push(`${where}: ${r}`);
}

async function screen(page) {
  return page.evaluate(() => ({
    tiles: [...document.querySelectorAll('#tiles .tile .v')].map(e => e.textContent.trim()),
    board: Object.fromEntries([...document.querySelectorAll('#board tbody tr')].map(tr =>
      [tr.dataset.n, [...tr.querySelectorAll('td')].slice(1).map((td, i) =>
        i === 3 ? (td.querySelector('.num') || td).textContent.trim() : td.innerText.replace(/\s+/g, ' ').trim())])),
    comments: +(document.getElementById('vocSub').textContent.match(/^(\d+)件/) || [0, -1])[1],
  }));
}

function diff(where, got, exp, errs) {
  if (JSON.stringify(got.tiles) !== JSON.stringify(exp.tiles)) errs.push(`${where}: tiles ${JSON.stringify(got.tiles)} != expected ${JSON.stringify(exp.tiles)}`);
  const names = new Set([...Object.keys(got.board), ...Object.keys(exp.board)]);
  for (const n of names) {
    const a = got.board[n], b = exp.board[n];
    if (JSON.stringify(a) !== JSON.stringify(b)) errs.push(`${where}: ${n} ${JSON.stringify(a)} != expected ${JSON.stringify(b)}`);
  }
  if (got.comments !== exp.comments) errs.push(`${where}: VOC comments ${got.comments} != expected ${exp.comments}`);
}

(async () => {
  const args = process.argv.slice(2);
  const ei = args.indexOf('--expect');
  const expect = ei >= 0 ? JSON.parse(fs.readFileSync(args[ei + 1], 'utf8')) : null;
  const files = args.filter((a, i) => ei < 0 || (i !== ei && i !== ei + 1));
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  if (!files.length) { console.log('usage: check_render.js FILE.html [--expect EXPECT.json]'); process.exit(2); }
  let failed = 0;
  for (const f of files) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errs = [];
    page.on('pageerror', e => errs.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error' && !/fonts\.g|xlsx|cdnjs|ERR_/.test(m.text())) errs.push('console: ' + m.text()); });
    await page.goto('file://' + path.resolve(f));
    await page.waitForSelector('#board tbody tr', { timeout: 15000 }).catch(() => errs.push('scoreboard has no rows'));
    const days = await page.$$eval('#dayBar button', b => b.map(x => x.dataset.d));
    let views = 0, compared = 0;
    for (const d of days) {
      await page.click(`#dayBar button[data-d="${d}"]`);
      for (const mode of ['same', 'all']) {
        await page.click(mode === 'same' ? '#vocSame' : '#vocAll');
        const where = `${d || 'ALL'}|${mode}`;
        await scan(page, where, errs);
        views++;
        if (expect) {
          if (!expect[where]) errs.push(`${where}: not in --expect`);
          else { diff(where, await screen(page), expect[where], errs); compared++; }
        }
      }
    }
    // 全期間で: 列ごとの並べ替え（2回押して昇順・降順）、行の選択と解除、散布図の点、Excel 欄の開閉
    await page.click('#dayBar button[data-d=""]');
    await page.click('#vocSame');
    const nCols = await page.$$eval('#board thead th', t => t.length);
    for (let i = 0; i < nCols; i++) {
      for (let k = 0; k < 2; k++) {
        await page.click(`#board thead th:nth-child(${i + 1})`);
        await scan(page, `sort col ${i}`, errs);
      }
    }
    const rows = await page.$$eval('#board tbody tr', r => r.map(x => x.dataset.n));
    for (const n of rows) {
      await page.click(`#board tbody tr[data-n="${n}"]`);
      await scan(page, `select ${n}`, errs);
      await page.click(`#board tbody tr[data-n="${n}"]`);
    }
    // 散布図: 点は重なることがある（データが増えれば普通）ので、座標クリックではなく各点の要素に click を送る。
    // 全部の点で 選択→表示確認→解除。ホバー（ツールチップ）も同じく要素に mousemove を送って確認する。
    const pts = await page.$$eval('#scatter .pt', e => e.map(x => x.dataset.n));
    for (const n of pts) {
      for (let k = 0; k < 2; k++) {
        const ok = await page.evaluate((name) => {
          const el = [...document.querySelectorAll('#scatter .pt')].find(x => x.dataset.n === name);
          if (!el) return false;
          el.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 100, clientY: 100 }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
          return true;
        }, n);
        if (!ok) errs.push(`scatter point ${n} disappeared after re-render`);
        await scan(page, `scatter ${n}`, errs);
      }
    }
    if (pts.length && !(await page.$$eval('#board tbody tr.sel', r => r.length === 0))) errs.push('scatter click left a row selected');
    await page.click('#loadBtn');
    if (await page.$eval('#drop', e => e.hidden)) errs.push('Excel drop area did not open');
    await page.click('#loadBtn');
    const uniq = [...new Set(errs)];
    console.log(`${uniq.length ? 'NG' : 'OK'} ${f} (${views} views${expect ? `, ${compared} compared with --expect` : ''}, ${rows.length} rows selected, ${pts.length} scatter points)` +
      (uniq.length ? '\n  ' + uniq.slice(0, 15).join('\n  ') : ''));
    failed += uniq.length ? 1 : 0;
    await page.close();
  }
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log('NG check_render: ' + (e && e.stack || e)); process.exit(2); });
