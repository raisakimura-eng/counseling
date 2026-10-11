// カウンセラー販売実績ダッシュボードを Chromium で開き、全期間タブ × 流入チャネル × 指標 × VOC の
// カウンセラー選択を切り替えて、JS エラーや「NaN」「undefined」「Infinity」の表示がないか確認する。
//
// Usage: NODE_PATH=$(npm root -g) node pipeline/sales/counselor/check_render.js FILE.html [FILE.html ...]
const { chromium } = require('playwright');

const BAD = /\bNaN\b|\bundefined\b|\bInfinity\b|\bnull\b/;

async function scan(page, where, errs) {
  const r = await page.evaluate((src) => {
    const re = new RegExp(src);
    const t = document.querySelector('main').innerText + '\n' + document.querySelector('header').innerText;
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

(async () => {
  const files = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  let failed = 0;
  for (const f of files) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errs = [];
    page.on('pageerror', e => errs.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error' && !/fonts\.g/.test(m.text())) errs.push('console: ' + m.text()); });
    page.on('requestfailed', () => {});  // fonts may be blocked offline; not an error of the page
    await page.goto('file://' + require('path').resolve(f));
    const nTabs = await page.$$eval('#tabs .tab', b => b.length);
    const nCh = await page.$$eval('#chPills .pill', b => b.length);
    const nMet = await page.$$eval('#metricPills .pill', b => b.length);
    let views = 0;
    for (let t = 0; t < nTabs; t++) {
      await page.click(`#tabs .tab:nth-child(${t + 1})`);
      const tabName = await page.$eval(`#tabs .tab:nth-child(${t + 1})`, b => b.textContent);
      for (let c = 0; c < nCh; c++) {
        const sel = `#chPills .pill:nth-child(${c + 1})`;
        if (await page.$eval(sel, b => b.disabled)) continue;
        await page.click(sel);
        const chName = await page.$eval(sel, b => b.textContent);
        // 指標は全チャネルで全部、他のチャネルでは先頭と VOC だけ（時間短縮）
        const mets = c === 0 ? [...Array(nMet).keys()] : [0, nMet - 2];
        for (const k of mets) {
          await page.click(`#metricPills .pill:nth-child(${k + 1})`);
          await scan(page, `${tabName}/${chName}/metric${k}`, errs);
          views++;
        }
        // VOC: カウンセラーを全員選び、★3以下フィルタも押す
        const opts = await page.$$eval('#vocSel option', o => o.map(x => x.value));
        for (const v of opts) {
          if (v === '—') continue;
          await page.selectOption('#vocSel', v);
          await scan(page, `${tabName}/${chName}/voc:${v}`, errs);
          const low = await page.$('#cmtPills .pill[data-f="low"]');
          if (low) { await low.click(); await scan(page, `${tabName}/${chName}/voc:${v}/low`, errs); }
          views++;
        }
      }
      // 凡例クリック（表示切替）も1回
      const n = await page.$eval('#legend span[data-n]', e => e.dataset.n).catch(() => null);
      if (n) {
        await page.click(`#legend span[data-n="${n}"]`);
        await page.click(`#legend span[data-n="${n}"]`);
      }
    }
    const uniq = [...new Set(errs)];
    console.log(`${uniq.length ? 'NG' : 'OK'} ${f} (${views} views)` + (uniq.length ? '\n  ' + uniq.slice(0, 12).join('\n  ') : ''));
    failed += uniq.length ? 1 : 0;
    await page.close();
  }
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
