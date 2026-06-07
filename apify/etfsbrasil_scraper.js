/**
 * Apify Web Scraper pageFunction for etfsbrasil.com.br/etfs/<ticker>.
 *
 * Used by src/fetchers/apify_etf_fetcher.py, which reads this file and passes it
 * as the `pageFunction` of the apify/web-scraper actor, with one startUrl per ETF
 * ticker and a RESIDENTIAL proxy configuration (etfsbrasil rate-limits scraping).
 *
 * The /etfs/<ticker> page is a Next.js SPA whose per-ETF page exposes — once
 * rendered — NAV (Patrimônio líquido, R$ MM), Número de cotistas, price/cotação,
 * taxa de administração, fund name, índice, provedor, região, lançamento, CNPJ and
 * ISIN. NAV/cotistas are JS-rendered, so this MUST run in a browser (web-scraper
 * does), not via plain HTTP.
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
    try {
        await page.waitForFunction(
            () => /Patrim[oô]nio l[ií]quido/i.test(document.body.innerText),
            { timeout: 30000 },
        );
    } catch (e) {
        log.warning(`${ticker}: Patrimônio líquido not detected within timeout: ${e.message}`);
    }
    await page.waitForTimeout(1500);

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
