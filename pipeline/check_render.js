// Open each dashboard HTML in Chromium, click through every role tab and period tab,
// and fail if the page throws or shows "NaN" / "undefined".
//
// Usage: NODE_PATH=$(npm root -g) node pipeline/check_render.js FILE.html [FILE.html ...]
const { chromium } = require('playwright');

(async () => {
  const files = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  let failed = 0;
  for (const f of files) {
    const page = await browser.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await page.goto('file://' + require('path').resolve(f));
    const roles = await page.$$eval('.rtab', b => b.map(x => x.dataset.r));
    const pers = await page.$$eval('.ptab', b => b.map(x => x.dataset.p));
    let views = 0;
    for (const r of (roles.length ? roles : [null])) {
      if (r !== null) await page.click(`.rtab[data-r="${r}"]`);
      for (const p of pers) {
        await page.click(`.ptab[data-p="${p}"]`);
        await page.waitForTimeout(60);
        const bad = await page.evaluate(() => {
          const t = document.querySelector('.wrap').innerText;
          return /\bNaN\b|\bundefined\b/.test(t) ? t.match(/.{0,40}(NaN|undefined).{0,40}/)[0] : '';
        });
        if (bad) errs.push(`${r || ''}/${p}: shows "${bad}"`);
        views++;
      }
    }
    console.log(`${errs.length ? 'NG' : 'OK'} ${f} (${views} views)` + (errs.length ? '\n  ' + [...new Set(errs)].slice(0, 8).join('\n  ') : ''));
    failed += errs.length ? 1 : 0;
    await page.close();
  }
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
