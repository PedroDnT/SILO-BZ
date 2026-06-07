/**
 * Apify Web Scraper pageFunction for etfsbrasil.com.br/comparador/<ticker>.
 *
 * Used by src/fetchers/apify_etf_fetcher.py, which reads this file and passes it
 * as the `pageFunction` of the apify/web-scraper actor, together with one
 * startUrl per ETF ticker and a RESIDENTIAL proxy configuration (rotating
 * proxies — etfsbrasil rate-limits direct scraping).
 *
 * The page is a single-page app: the classification + returns tables are in the
 * rendered DOM, and NAV (Evolução do PL) and Número de Cotistas are rendered as
 * charts/sections after JS runs — so this MUST run in a browser (web-scraper does),
 * not via plain HTTP. We wait for the content, then read label→value pairs by their
 * Portuguese labels. The Python side parses Brazilian number/date formats and maps
 * to etf_market_snapshot columns; here we just emit the raw scraped strings keyed
 * by stable label keys, plus the ticker from the URL.
 *
 * Output: one dataset item per ticker:
 *   { ticker, source_url, fund_name, categoria, regiao, indice, provedor_indice,
 *     taxa_adm, ret_ytd, ret_12m, ret_36m, vol_12m, sharpe_12m, max_drawdown,
 *     launch, nav, cotistas, fields: {<label>: <value>, ...} }
 *
 * NOTE: the chart-backed NAV/cotistas selectors below are best-effort against the
 * current layout and MUST be verified on a real run (see docs) — every field is
 * also dumped into `fields` so nothing scraped is silently lost.
 */
async function pageFunction(context) {
    const { request, page, log } = context;

    // Ticker is the last path segment of /comparador/<ticker>.
    const ticker = decodeURIComponent(request.url.split('/').filter(Boolean).pop() || '')
        .toUpperCase();

    // Give the SPA time to render the comparador tables and charts.
    try {
        await page.waitForSelector('table', { timeout: 30000 });
    } catch (e) {
        log.warning(`No table rendered for ${ticker}: ${e.message}`);
    }
    await page.waitForTimeout(2500);

    // Pull every label→value pair from the rendered tables, keyed by the label
    // text (trimmed). Two-cell rows are label/value; we keep the last value cell.
    const fields = await page.evaluate(() => {
        const out = {};
        for (const row of document.querySelectorAll('tr')) {
            const cells = Array.from(row.querySelectorAll('th,td'))
                .map((c) => c.innerText.trim())
                .filter((t) => t.length > 0);
            if (cells.length >= 2) {
                const label = cells[0];
                const value = cells[cells.length - 1];
                if (label && value && label !== value) out[label] = value;
            }
        }
        // Best-effort: NAV (Patrimônio) and Cotistas often appear as labelled
        // figures outside the table — capture any element whose text pairs a known
        // label with a number nearby.
        const bodyText = document.body.innerText;
        const grab = (re) => {
            const m = bodyText.match(re);
            return m ? m[1].trim() : null;
        };
        out['__patrimonio'] = grab(/Patrim[oô]nio[^\n]*?\n?\s*([R$\s\d.,]+)/i);
        out['__cotistas']   = grab(/Cotistas[^\n]*?\n?\s*([\d.,]+)/i);
        return out;
    });

    const pick = (...labels) => {
        for (const l of labels) {
            for (const key of Object.keys(fields)) {
                if (key.toLowerCase() === l.toLowerCase()) return fields[key];
            }
        }
        return null;
    };

    return {
        ticker,
        source_url: request.url,
        scraped_at: new Date().toISOString(),
        fund_name:       pick('Nome do fundo'),
        categoria:       pick('Categoria'),
        regiao:          pick('Região'),
        indice:          pick('Índice'),
        provedor_indice: pick('Provedor do índice'),
        taxa_adm:        pick('Taxa de adm. total', 'Taxa de adm.'),
        ret_ytd:         pick('No ano'),
        ret_12m:         pick('12 meses'),
        ret_36m:         pick('Últimos 3 anos'),
        vol_12m:         null, // disambiguated Python-side from the Desvio Padrão block
        sharpe_12m:      null,
        max_drawdown:    pick('Max. Drawdown', 'Máx. Drawdown'),
        launch:          pick('Lançamento'),
        nav:             fields['__patrimonio'] || null,
        cotistas:        fields['__cotistas'] || null,
        fields,          // full label→value map for audit + Python-side remapping
    };
}
