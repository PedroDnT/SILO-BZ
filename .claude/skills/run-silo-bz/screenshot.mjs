// Screenshot a running Evidence dashboard page with the pre-installed
// Chromium. No npm install needed: playwright is global under /opt/node22
// but ESM ignores NODE_PATH, so import it by absolute path.
//
//   node .claude/skills/run-silo-bz/screenshot.mjs [url] [out.png]
//
// Prints the page <title> and first <h1> so an agent can assert on them
// without opening the image.
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';

const url = process.argv[2] || 'http://127.0.0.1:3000/';
const out = process.argv[3] || '/tmp/dash.png';

const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium',
  args: ['--disable-gpu'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(3000); // Evidence hydrates charts after load
console.log('TITLE:', await page.title());
console.log('H1:', await page.locator('h1').first().textContent().catch(() => 'none'));
await page.screenshot({ path: out, fullPage: false });
console.log('saved', out);
await browser.close();
