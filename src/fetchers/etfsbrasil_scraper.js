/**
 * Apify Web Scraper pageFunction for etfsbrasil.com.br/etfs/<ticker>.
 *
 * Used by src/fetchers/apify_etf_fetcher.py, which reads this file and passes it
 * as the `pageFunction` of the Apify headless-browser actor (default
 * apify/playwright-scraper; apify/web-scraper still works), with one startUrl
 * per ETF ticker and a RESIDENTIAL proxy configuration (etfsbrasil rate-limits
 * scraping). The body uses only page.evaluate + Node timers so Puppeteer and
 * Playwright pageFunction APIs both work (waitForFunction option placement differs).
 *
 * The /etfs/<ticker> page is a Next.js SPA whose per-ETF page exposes — once
 * rendered — NAV (Patrimônio líquido, R$ MM), Número de cotistas, price/cotação,
 * taxa de administração, fund name, índice, provedor, região, lançamento, CNPJ and
 * ISIN. NAV/cotistas are JS-rendered, so this MUST run in a browser, not via
 * plain HTTP.
 *
 * Robustness: rather than betting on brittle per-field selectors, we return the
 * full rendered `text` (innerText) AND the embedded Next.js `__NEXT_DATA__` JSON
 * (the page props, which carry the structured ETF object). The Python side
 * (ingest_etf_market.py) parses fields from `text` by their Portuguese labels and
 * keeps both in `raw`, so a moved label never silently drops data and the exact
 * JSON mapping can be tightened after a verified run.
 */
async function pageFunction(context) {
    const { request, page, log } = context;

    const ticker = decodeURIComponent(request.url.split('/').filter(Boolean).pop() || '')
        .toUpperCase();

    // Wait for the SPA to render the figures (Patrimônio líquido / cotistas).
    // Poll via page.evaluate rather than page.waitForFunction: Puppeteer takes
    // (fn, options) while Playwright takes (fn, arg, options), so a shared
    // options-in-second-slot call is wrong on one of the two actors.
    const deadline = Date.now() + 30000;
    let found = false;
    try {
        while (Date.now() < deadline) {
            found = await page.evaluate(
                () => /Patrim[oô]nio l[ií]quido/i.test(document.body.innerText),
            );
            if (found) break;
            await new Promise((resolve) => setTimeout(resolve, 500));
        }
        if (!found) {
            log.warning(`${ticker}: Patrimônio líquido not detected within timeout`);
        }
    } catch (e) {
        log.warning(`${ticker}: Patrimônio líquido wait failed: ${e.message}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));

    const data = await page.evaluate(() => {
        let nextData = null;
        const el = document.getElementById('__NEXT_DATA__');
        if (el && el.textContent) {
            try { nextData = JSON.parse(el.textContent); } catch (e) { /* keep text fallback */ }
        }
        return { nextData, text: document.body ? document.body.innerText : '' };
    });

    return {
        ticker,
        source_url: request.url,
        scraped_at: new Date().toISOString(),
        text: data.text,          // full rendered text — parsed server-side by labels
        next_data: data.nextData, // Next.js page props (structured; mapped later)
    };
}
