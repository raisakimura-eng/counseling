// Open the 着地予想ダッシュボード in Chromium, show every tab (当日 / 今月 / 前月 / まとめ) and every day
// of both months, and fail on a page error, a console error, or "NaN" / "undefined" / "Infinity" on screen.
//
// Usage: NODE_PATH=$(npm root -g) node pipeline/sales/landing/check_render.js PAGE.html [--dump OUT.json]
// --dump writes the visible text of every view/day, to compare two versions of the page.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const args = process.argv.slice(2);
  const di = args.indexOf('--dump');
  const dump = di >= 0 ? args.splice(di, 2)[1] : null;
  const file = args[0];
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [], texts = {};
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto('file://' + path.resolve(file));
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  const grab = async key => {
    const t = await page.evaluate(() => document.body.innerText);
    const m = t.match(/.{0,40}\b(NaN|undefined|Infinity)\b.{0,40}/);
    if (m) errs.push(`${key}: shows "${m[0]}"`);
    texts[key] = t;
  };
  let views = 0;
  for (const v of ['today', 'oct', 'past', 'sum']) {
    await page.click(`#vt-${v}`);
    await page.waitForTimeout(50);
    if (v === 'oct' || v === 'past') {
      const n = await page.$$eval('#dSel option', o => o.length);
      for (let i = 0; i < n; i++) {
        await page.selectOption('#dSel', String(i));
        await page.waitForTimeout(20);
        await grab(`${v}/${i}`);
        views++;
      }
    } else { await grab(v); views++; }
  }
  if (dump) fs.writeFileSync(dump, JSON.stringify(texts));
  console.log(`${errs.length ? 'NG' : 'OK'} ${file} (${views} views)` + (errs.length ? '\n  ' + [...new Set(errs)].slice(0, 10).join('\n  ') : ''));
  await browser.close();
  process.exit(errs.length ? 1 : 0);
})();
