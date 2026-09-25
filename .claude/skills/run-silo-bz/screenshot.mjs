// Screenshot a running Evidence dashboard page and print what an agent can
// assert on without opening the image: <title> and first <h1>.
//
//   node .claude/skills/run-silo-bz/screenshot.mjs [url] [out.png]
//
// playwright is not a repo dependency. ESM ignores NODE_PATH, so the package
// is located by absolute path, first hit wins:
//   $SILO_PLAYWRIGHT                       (dir containing playwright/)
//   ~/.cache/silo-pw/node_modules          (macOS / laptop install, see SKILL.md)
//   /opt/node22/lib/node_modules           (the Linux agent container)
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const roots = [
  process.env.SILO_PLAYWRIGHT,
  join(homedir(), '.cache/silo-pw/node_modules'),
  '/opt/node22/lib/node_modules',
].filter(Boolean);
const root = roots.find((r) => existsSync(join(r, 'playwright/index.mjs')));
if (!root) {
  console.error('playwright not found in: ' + roots.join(', ') + ' (see SKILL.md Prerequisites)');
  process.exit(2);
}
const { chromium } = await import(pathToFileURL(join(root, 'playwright/index.mjs')).href);

const url = process.argv[2] || 'http://127.0.0.1:3000/';
const out = process.argv[3] || '/tmp/dash.png';
// Optional: --click "Link text" clicks that sidebar/page link after load and
// screenshots where it lands (a real navigation, not a direct URL load).
const ci = process.argv.indexOf('--click');
const clickText = ci > 0 ? process.argv[ci + 1] : null;

// The Linux container pre-installs Chromium outside Playwright's cache.
const linuxChromium = '/opt/pw-browsers/chromium';
const browser = await chromium.launch({
  ...(existsSync(linuxChromium) ? { executablePath: linuxChromium } : {}),
  args: ['--disable-gpu'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(3000); // Evidence hydrates charts after load
if (clickText) {
  await page.getByRole('link', { name: clickText, exact: true }).first().click();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);
  console.log('CLICKED:', clickText, '->', new URL(page.url()).pathname);
}
console.log('TITLE:', await page.title());
console.log('H1:', await page.locator('h1').first().textContent().catch(() => 'none'));
await page.screenshot({ path: out, fullPage: false });
console.log('saved', out);
await browser.close();
