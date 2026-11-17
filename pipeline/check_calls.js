// Open the reception VOC page, switch to the 受電率 tab and back, on a desktop and a phone viewport.
// Fails if the page throws, the tab does not show / hide the right parts, or the page scrolls sideways.
//
// Usage: NODE_PATH=$(npm root -g) node pipeline/check_calls.js FILE.html
const { chromium } = require('playwright');

(async () => {
  const f = 'file://' + require('path').resolve(process.argv[2]);
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' }).catch(() => chromium.launch());
  const errs = [];
  for (const [name, vp] of [['desktop', { width: 1280, height: 900 }], ['phone', { width: 390, height: 800 }]]) {
    const page = await browser.newPage({ viewport: vp });
    page.on('pageerror', e => errs.push(`${name}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error') errs.push(`${name}: ${m.text()}`); });
    await page.goto(f);
    await page.click('.vtab[data-v="calls"]');
    await page.waitForTimeout(300);
    const on = await page.evaluate(() => ({
      calls: getComputedStyle(document.getElementById('calls')).display,
      survey: getComputedStyle(document.getElementById('pair')).display,
      side: document.documentElement.scrollWidth > window.innerWidth,
      bad: /\bNaN\b|\bundefined\b/.test(document.getElementById('calls').innerText) }));
    if (on.calls !== 'flex' || on.survey !== 'none') errs.push(`${name}: 受電率 tab shows calls=${on.calls} survey=${on.survey}`);
    if (on.side) errs.push(`${name}: page scrolls sideways on the 受電率 tab`);
    if (on.bad) errs.push(`${name}: 受電率 tab shows NaN / undefined`);
    await page.click('.vtab[data-v="survey"]');
    await page.waitForTimeout(200);
    const off = await page.evaluate(() => getComputedStyle(document.getElementById('calls')).display);
    if (off !== 'none') errs.push(`${name}: 受電率 stays visible on the survey tab`);
    await page.close();
  }
  await browser.close();
  console.log(errs.length ? 'NG 受電率 tab\n  ' + errs.join('\n  ') : 'OK 受電率 tab (desktop, phone)');
  process.exit(errs.length ? 1 : 0);
})();
