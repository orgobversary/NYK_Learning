/* Verify that the synthetic, bipartite passing Sankey renders rather than failing on cycles. */
const assert = require('node:assert/strict');

const playwrightPath = process.env.PLAYWRIGHT_MODULE;
if (!playwrightPath) throw new Error('Set PLAYWRIGHT_MODULE to the installed playwright package');
const { chromium } = require(playwrightPath);
const baseUrl = process.env.NYK_PASSING_URL || 'http://127.0.0.1:4174/';

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    assert.match(await page.locator('.badge').innerText(), /SYNTHETIC METHODS LAB/);
    const chart = page.frame({ url: /player-passing-sankey\.html/ });
    assert.ok(chart, 'passing chart iframe did not load');
    assert.ok(await chart.locator('svg').count(), 'passing chart did not create an SVG');
    assert.ok(await chart.locator('path').count(), 'passing chart did not create any paths');
    assert.deepEqual(errors, [], `browser errors: ${errors.join('; ')}`);
    console.log(JSON.stringify({ ok: true, baseUrl }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
