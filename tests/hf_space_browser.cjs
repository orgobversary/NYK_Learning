/* Repeatable browser smoke test for a generated NYK World static Space. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const playwrightPath = process.env.PLAYWRIGHT_MODULE;
if (!playwrightPath) throw new Error('Set PLAYWRIGHT_MODULE to the installed playwright package');
const { chromium } = require(playwrightPath);

const baseUrl = process.env.NYK_SPACE_URL || 'http://127.0.0.1:4173/';
const output = process.env.NYK_BROWSER_OUTPUT || 'build/browser-qa';
const expectedSeason = process.env.NYK_EXPECTED_SEASON || '2025-26';
const expectedGames = process.env.NYK_EXPECTED_GAMES || '82';
const expectedSynthetic = (process.env.NYK_EXPECTED_SYNTHETIC || 'true') === 'true';
fs.mkdirSync(output, { recursive: true });

async function inspectPage(page, label) {
  const consoleErrors = [];
  const pageErrors = [];
  const externalRequests = [];
  const expectedOrigin = new URL(baseUrl).origin;
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (new URL(request.url()).origin !== expectedOrigin) externalRequests.push(request.url());
  });
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('h1').waitFor();
  assert.match(await page.locator('h1').innerText(), /signal beneath the season/i);
  assert.match(await page.locator('.season-lockup').innerText(), new RegExp(expectedSeason));
  const tabs = page.locator('[role="tab"]');
  assert.equal(await tabs.count(), 8);
  assert.match(await page.locator('.metrics').innerText(), new RegExp(expectedGames));
  assert.equal(await page.locator('.story-rail a').count(), 7);
  await page.getByRole('heading', { name: /(?:Sixteen wins|No historical playoff claims)/ }).waitFor();
  await page.getByRole('heading', { name: /The ball reveals the network/ }).waitFor();
  await page.getByRole('heading', { name: /Prediction, with the lights on/ }).waitFor();

  const story = await page.evaluate(async () => (await fetch('story-manifest.json')).json());
  assert.equal(story.chapters.length, 7);
  assert.equal(story.synthetic, expectedSynthetic);

  const frame = page.locator('#chart-frame');
  await frame.waitFor();
  await page.waitForTimeout(700);
  assert.match(await frame.getAttribute('src'), /season-pulse\.html/);
  assert.ok((await frame.contentFrame().locator('body').innerText()).length > 0);

  for (let index = 1; index < await tabs.count(); index += 1) {
    const tab = tabs.nth(index);
    await tab.click();
    await page.waitForTimeout(500);
    const slug = await tab.getAttribute('data-chart');
    assert.match(await frame.getAttribute('src'), new RegExp(`${slug}\\.html`));
    assert.ok((await frame.contentFrame().locator('body').innerText()).length > 0);
    assert.equal(await tab.getAttribute('tabindex'), '0');
  }

  const selected = page.getByRole('tab', { name: 'Opponent share' });
  await selected.focus();
  await selected.press('ArrowRight');
  assert.equal(await page.getByRole('tab', { name: 'Matchup grid' }).getAttribute('aria-selected'), 'true');
  assert.match(await frame.getAttribute('src'), /matchup-grid\.html/);
  const provenance = page.getByRole('link', { name: /(?:Build manifest|Synthetic dataset and provenance)/ });
  assert.ok(await provenance.getAttribute('href'));
  for (const source of ['playoff-journey.html', 'passing-lanes.html', 'model-signal.html']) {
    const feature = page.locator(`.feature-frame iframe[src$="${source}"]`);
    await feature.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    assert.ok((await feature.contentFrame().locator('body').innerText()).length > 0);
  }

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  assert.equal(overflow, false, `${label} viewport has horizontal overflow`);
  await page.screenshot({ path: path.join(output, `${label}.png`), fullPage: true });
  assert.deepEqual(pageErrors, [], `page errors: ${pageErrors.join('; ')}`);
  assert.deepEqual(consoleErrors, [], `console errors: ${consoleErrors.join('; ')}`);
  assert.deepEqual(externalRequests, [], `unexpected external requests: ${externalRequests.join('; ')}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    await inspectPage(desktop, 'desktop');
    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    await inspectPage(mobile, 'mobile');
    const zoom = await browser.newPage({ viewport: { width: 720, height: 900 }, deviceScaleFactor: 2, reducedMotion: 'reduce' });
    await inspectPage(zoom, 'zoom-200');
    console.log(JSON.stringify({ ok: true, baseUrl, screenshots: output }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
