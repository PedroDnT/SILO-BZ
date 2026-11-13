export const OperationQuery = ({ operation }) => {
  const initial = Object.fromEntries(operation.parameters.filter(p => p.example !== undefined && !p.advanced).map(p => [p.name, String(p.example)]));
  const [values, setValues] = useState(initial);
  const [body, setBody] = useState(JSON.stringify(Object.fromEntries(operation.body.map(p => [p.name, []])), null, 2));
  const [token, setToken] = useState('');
  const [result, setResult] = useState(null);
  const [raw, setRaw] = useState('');
  const [requestUrl, setRequestUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  const base = 'https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2' + operation.path;
  const inputClass = 'block w-full rounded-md border border-gray-300 dark:border-gray-700 bg-transparent p-2 mt-1';
  const label = name => ({cnpj:'CNPJ',cnpjs:'CNPJs',q:'Search',identifier:'Company',identifiers:'Identifiers',from:'From',to:'To'}[name] || name.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()));
  const field = p => <label key={p.name} htmlFor={'silo-' + p.name} className="block">
    {label(p.name)}{!p.required && <span className="text-gray-500 text-sm"> (optional)</span>}
    {p.choices || p.schema.enum ? <select id={'silo-' + p.name} className={inputClass} value={values[p.name] || ''} required={p.required} onChange={e => setValues({...values, [p.name]: e.target.value})}>
      <option value="">{p.required ? 'Choose…' : p.schema.default !== undefined ? `Default: ${p.schema.default}` : 'Default'}</option>
      {(p.choices || p.schema.enum.map(value => ({value, label:String(value)}))).map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
    </select> : <input id={'silo-' + p.name} className={inputClass} type={p.schema.format === 'date' ? 'date' : ['integer','number'].includes(p.schema.type) ? 'number' : 'text'} step={p.schema.type === 'number' ? 'any' : undefined} min={p.schema.minimum} required={p.required} value={values[p.name] || ''} placeholder={p.schema.default !== undefined ? String(p.schema.default) : ''} onChange={e => setValues({...values,[p.name]:e.target.value})}/>}
    {!p.choices && !["from","to","ticker","q"].includes(p.name) && <span className="text-sm text-gray-500">{p.description}</span>}
  </label>;
  const send = async next => {
    controller.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError(''); setResult(null); setRaw('');
    const timeout = setTimeout(() => abort.abort(), 30000);
    try {
      const url = new URL(base);
      Object.entries(values).forEach(([key, value]) => {if (value !== '') url.searchParams.set(key,value);});
      const target = next ? new URL(next.url) : url;
      if (target.origin !== url.origin || target.pathname !== url.pathname) throw new Error('Invalid next page URL.');
      const payloadBody = operation.method === 'POST' ? (next ? next.body : JSON.stringify(JSON.parse(body))) : undefined;
      const response = await fetch(target, {method:operation.method, signal:abort.signal, redirect:'error', headers:{...(token ? {Authorization:`Bearer ${token}`} : {}), ...(payloadBody ? {'Content-Type':'application/json'} : {})}, body:payloadBody});
      const text = await response.text();
      const payload = JSON.parse(text);
      if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status}).`);
      if (!Array.isArray(payload.data) || !payload.meta) throw new Error('Invalid API response.');
      setResult({...payload, requestBody:payloadBody}); setRaw(text); setRequestUrl(target.toString());
    } catch(e) {setError(e.name === 'AbortError' ? 'Request timed out. Try again.' : e.message);}
    finally {clearTimeout(timeout); setBusy(false);}
  };
  return <section aria-label={'Query '+operation.title} className="rounded-xl border border-gray-200 dark:border-gray-800 p-5 my-5">
    <div className="font-mono text-sm mb-4">{operation.method} {operation.path}</div>
    {["portfolio","screens"].includes(operation.resource) && <p className="text-sm mb-4">Sign-in required. Add your Bearer token in Advanced options.</p>}
    <form onSubmit={e => {e.preventDefault(); send();}}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">{operation.parameters.filter(p => !p.advanced).map(field)}</div>
      {operation.body.length > 0 && <label className="block my-4">Request body
        <textarea aria-label="Request body" className={inputClass + ' font-mono min-h-40'} value={body} onChange={e => setBody(e.target.value)}/>
        {operation.body.map(p => <span key={p.name} className="block text-sm text-gray-500">{p.name}: {p.description}</span>)}
      </label>}
      <details className="my-4"><summary className="cursor-pointer">Advanced options</summary>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">{operation.parameters.filter(p => p.advanced).map(field)}</div>
        <label className="block mt-4"><input type="checkbox" checked={values.details === 'true'} onChange={e => setValues({...values,details:e.target.checked ? 'true' : ''})}/> Include request diagnostics</label>
        <label className="block mt-4">Bearer token (optional)<input className={inputClass} type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}/></label>
        <p className="text-sm text-gray-500">The token is sent only to SILO and is not saved.</p>
      </details>
      <button type="submit" disabled={busy} className="rounded-md bg-green-700 px-4 py-2 text-white disabled:opacity-50">{busy ? 'Loading…' : 'Get data'}</button>
    </form>
    {error && <p role="alert" className="mt-4 text-red-600">{error}</p>}
    {result && <div className="mt-4">
      <p role="status">{result.data.length} rows · {result.meta.tier}{result.meta.tier_cap_reached ? ' · Partial: tier limit reached' : result.next_page_url ? ' · More pages available' : ''}</p>
      <p className="break-all text-sm">{requestUrl}</p>
      <pre className="max-h-96 overflow-auto text-sm whitespace-pre-wrap break-words">{raw}</pre>
      {result.next_page_url && <button type="button" disabled={busy} onClick={() => send({url:result.next_page_url,body:result.requestBody})} className="rounded-md border px-3 py-2">Next page</button>}
    </div>}
  </section>;
};
