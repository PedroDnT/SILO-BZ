export const SeriesQuery = ({ choices }) => {
  const [series, setSeries] = useState('CDI');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [token, setToken] = useState('');
  const [limit, setLimit] = useState('');
  const [result, setResult] = useState(null);
  const [raw, setRaw] = useState('');
  const [requestUrl, setRequestUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  const base = 'https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2/macro/series';
  const send = async (next) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true); setError(''); setResult(null); setRaw('');
    const timeout = setTimeout(() => abort.abort(), 30000);
    try {
      const url = new URL(base);
      url.searchParams.set('series', series);
      if (from) url.searchParams.set('from', from);
      if (to) url.searchParams.set('to', to);
      if (limit) url.searchParams.set('limit', limit);
      const target = next ? new URL(next) : url;
      if (target.origin !== url.origin || target.pathname !== url.pathname) throw new Error('Invalid next page URL.');
      const response = await fetch(target, {signal: abort.signal, redirect: 'error', headers: token ? {Authorization: `Bearer ${token}`} : {}});
      const text = await response.text();
      const payload = JSON.parse(text);
      if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status}).`);
      if (!Array.isArray(payload.data) || !payload.meta) throw new Error('Invalid API response.');
      setResult(payload); setRaw(text); setRequestUrl(target.toString());
    } catch (e) {
      setError(e.name === 'AbortError' ? 'Request timed out. Try again.' : e.message);
    } finally { clearTimeout(timeout); setBusy(false); }
  };
  const input = 'block w-full rounded-md border border-gray-300 dark:border-gray-700 bg-transparent p-2 mt-1';
  return <section aria-label="Query an economic series" className="rounded-xl border border-gray-200 dark:border-gray-800 p-5 my-5">
    <form onSubmit={e => {e.preventDefault(); send();}}>
      <label className="block" htmlFor="silo-series">Series
        <select id="silo-series" className={input} value={series} onChange={e => setSeries(e.target.value)}>
          {choices.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 my-4">
        <label>From <span className="text-gray-500">(optional)</span><input className={input} type="date" value={from} onChange={e => setFrom(e.target.value)}/></label>
        <label>To <span className="text-gray-500">(optional)</span><input className={input} type="date" value={to} onChange={e => setTo(e.target.value)}/></label>
      </div>
      <details className="my-4"><summary className="cursor-pointer">Advanced options</summary>
        <label className="block mt-3">Rows per page<input className={input} type="number" min="1" value={limit} onChange={e => setLimit(e.target.value)}/></label>
        <label className="block mt-3">Bearer token (optional)<input className={input} type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}/></label>
        <p className="text-sm text-gray-500">The token is sent only to SILO and is not saved.</p>
      </details>
      <button type="submit" disabled={busy} className="rounded-md bg-green-700 px-4 py-2 text-white disabled:opacity-50">{busy ? 'Loading…' : 'Get series'}</button>
    </form>
    {error && <p role="alert" className="mt-4 text-red-600">{error}</p>}
    {result && <div className="mt-4">
      <p role="status">{result.data.length} observations · {result.meta.tier}{result.meta.tier_cap_reached ? ' · Partial: tier limit reached' : result.next_page_url ? ' · More pages available' : ''}</p>
      <p className="break-all text-sm">{requestUrl}</p>
      <pre className="max-h-96 overflow-auto text-sm">{raw}</pre>
      {result.next_page_url && <button type="button" disabled={busy} onClick={() => send(result.next_page_url)} className="rounded-md border px-3 py-2">Next page</button>}
    </div>}
  </section>;
};
