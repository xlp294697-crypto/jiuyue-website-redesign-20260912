/* Run against the local static preview. No production bookings are submitted.
   PLAYWRIGHT_MODULE can point to an installed Playwright package. */
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.GLASS_BASE_URL || 'http://127.0.0.1:8846';

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
    await page.goto(base + '/classroom/index.html?course=cheer');
    const initial = await page.locator('.chips').evaluate(group => {
      const selected = group.querySelector('[aria-pressed="true"]');
      const highlight = group.querySelector('.glass-filter-indicator');
      if (!highlight) return { present: false };
      const a = selected.getBoundingClientRect(), b = highlight.getBoundingClientRect();
      return { present: true, selected: selected.dataset.filter, dx: Math.abs(a.x - b.x), dy: Math.abs(a.y - b.y), dw: Math.abs(a.width - b.width) };
    });
    assert.equal(initial.present, true, 'The selected classroom filter needs a movable glass highlight');
    assert.equal(initial.selected, 'cheer');
    assert.ok(initial.dx < 2 && initial.dy < 2 && initial.dw < 2, 'Initial highlight must match the deep-linked filter');

    await page.locator('[data-analytics-reject]').click();
    await page.locator('[data-filter="athletics"]').click();
    await page.waitForFunction(() => {
      const a = document.querySelector('[data-filter="athletics"]').getBoundingClientRect();
      const b = document.querySelector('.glass-filter-indicator').getBoundingClientRect();
      return Math.abs(a.x - b.x) < 2 && Math.abs(a.y - b.y) < 2 && Math.abs(a.width - b.width) < 2;
    });
    assert.equal(await page.locator('[data-category]:visible').count(), 1, 'Filtering still hides unrelated classroom videos');
    assert.equal(await page.locator('[data-category]:visible').first().getAttribute('data-category'), 'athletics');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForFunction(() => {
      const a = document.querySelector('[data-filter="athletics"]').getBoundingClientRect();
      const b = document.querySelector('.glass-filter-indicator').getBoundingClientRect();
      return Math.abs(a.x - b.x) < 2 && Math.abs(a.y - b.y) < 2;
    });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const duration = await page.locator('.glass-filter-indicator').evaluate(el => getComputedStyle(el).transitionDuration);
    assert.ok(duration.split(',').every(value => parseFloat(value) <= .01), 'Reduced motion must disable the travelling highlight');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.menu-toggle').click();
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'true');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.menu-toggle').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('.menu-toggle').evaluate(el => document.activeElement === el), true);
    assert.equal(await page.locator('.mobile-dock a[href^="tel:"]').count(), 1, 'The bottom bar keeps its phone entry');
    assert.equal(await page.locator('.mobile-dock a[href^="https://v.douyin.com/"]').count(), 1, 'The bottom bar keeps its Douyin purchase entry');
    await page.locator('.header a[href*="booking"]').click();
    await page.locator('#booking-form').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#booking-form').count(), 1, 'Floating consultation entry still reaches the real booking form');
    assert.equal(await page.locator('.wechat-image-link img').count(), 1, 'WeChat consultation stays available');
    assert.equal(errors.length, 0, errors.join('\n'));
    console.log('PASS: selected filter highlight, query selection, filter results, responsive realignment, reduced motion, mobile menu keyboard dismissal, booking and WeChat entry');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
