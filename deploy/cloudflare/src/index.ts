// The portfolio-diagnosis demo on Cloudflare (map #510, slice E step 2).
//
// GET  /          the upload page (Portuguese, token field, downloads the PDF)
// GET  /health    answered by the Worker itself, public, no container
// POST /diagnose  needs the shared token; starts a fresh engine Container for
//                 this upload alone, forwards the statement with
//                 `Authorization: Bearer`, returns the PDF, then stops it
// GET  /traces    the owner's trace page (static shell, no data): asks for the token, lists runs, shows where an
//                 asset's exposure comes from and downloads a run's PDF
// GET  /api/traces, /api/traces/exposure, /api/traces/pdf
//                 need the same token; read the private R2 bucket through the binding (see below)
// Anything else   404
//
// Clients send the token as `x-demo-token` (the scheme of the first deploy) or
// as `Authorization: Bearer`. It is compared as a SHA-256 digest with
// timingSafeEqual. Nothing is logged: no console call, invocation logs off in
// wrangler.jsonc, and the Container's onError is silenced.
//
// Storage (ADR 0003): the uploaded statement is never stored; its bytes are only
// forwarded. After answering, each run's trace is written to the private R2
// bucket bound as TRACES (only this Worker writes it, through the binding):
// traces/YYYY/MM/DD/<trace_id>.json (OTLP/JSON, the date is UTC), the masked
// engine JSON as artifacts/<sha256>.json and the PDF as artifacts/<sha256>.pdf, and (engine 1.12) the
// public documents the investigator read as docs/<source>/<id>/<sha256>.txt.
// Holder, CPF and account are masked by the engine's readers before any of it
// exists. No KV, D1 or DO storage of our own.
import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";
import { type EngineDoc, exposureText, topGroups, traceRootAttribute } from "./exposure";

// The outbound allow-list runs through ContainerProxy, which must be exported.
export { ContainerProxy };

interface Env {
	ENGINE: DurableObjectNamespace<HealthContainer>;
	// Private R2 bucket silo-diagnosis-traces (wrangler.jsonc).
	TRACES: R2Bucket;
	DEMO_ACCESS_TOKEN?: string;
	OPENAI_API_KEY?: string;
	// Engine 1.12 (#605): the investigator of official documents and its web fallback (Exa).
	EXA_API_KEY?: string;
	SILO_INVESTIGATOR?: string;
	SILO_LLM_PROVIDER?: string;
	SILO_LLM_MODEL?: string;
	SILO_LLM_EFFORT?: string;
	// "allowlist" (default): only the hosts below. "open": internet on.
	EGRESS?: string;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const TOKEN_HEADER = "x-demo-token";
// The engine names each run's trace here; never passed to the client (not in PASS_HEADERS).
const TRACE_HEADER = "x-silo-trace-id";
const TRACE_ID = /^[0-9a-f]{32}$/;
const SHA256_KEY = /^artifacts\/[0-9a-f]{64}\.json$/;
// The owner's trace page reads only keys of these two shapes: no other path reaches the bucket.
const TRACE_KEY = /^traces\/\d{4}\/\d{2}\/\d{2}\/[0-9a-f]{32}\.json$/;
const SHA256 = /^[0-9a-f]{64}$/;
const TICKER = /^[A-Za-z0-9]{1,12}$/;
// Engine 1.12 (#605, Q35): public documents the investigator read, keyed by source, id and the text's SHA-256.
const DOC_KEY = /^docs\/(fnet|rad|web)\/[A-Za-z0-9_.-]{1,128}\/([0-9a-f]{64})\.txt$/;
// silo-mcp (and PostgREST) on Supabase, the LLM provider, and (engine 1.12, #605) the investigator's
// public sources: B3 Fundos.NET, CVM RAD and Exa. Nothing else.
const EGRESS_ALLOWED = [
	"zcjbtpxuhdekpwcxmepn.supabase.co",
	"api.openai.com",
	"fnet.bmfbovespa.com.br",
	"www.rad.cvm.gov.br",
	"api.exa.ai",
];
// Response headers of the engine passed back to the client: status, sizes,
// timings and cost only, never content.
const PASS_HEADERS = [
	"content-type",
	"content-disposition",
	"x-silo-narrative",
	"x-silo-provider",
	"x-silo-cost-usd",
	"x-silo-seconds",
	"x-silo-stage",
	"x-silo-error",
	"x-silo-error-status",
	"x-silo-error-code",
	"x-silo-engine-rev",
	"x-silo-narrative-reason",
	"x-silo-llm-calls",
	// engine 1.7: a 503 when SILO did not answer says when to try again
	"retry-after",
];

// The class keeps the name of the first deploy (#519) so the Durable Object
// namespace and the Container application carry over; it now runs the engine
// image (deploy/cloudflare/engine/Dockerfile).
export class HealthContainer extends Container<Env> {
	defaultPort = 8080;
	// Billed while up. Each upload gets its own instance and the Worker stops it
	// after the answer; this only covers a client that went away mid-report.
	// An open request keeps the instance alive past it.
	sleepAfter = "60s";

	constructor(ctx: DurableObjectState, env: Env) {
		super(ctx, env);
		const open = (env.EGRESS ?? "allowlist") === "open";
		this.enableInternet = open;
		if (!open) {
			this.allowedHosts = EGRESS_ALLOWED;
			// Without it HTTPS is not filtered; the image trusts the platform CA.
			this.interceptHttps = true;
		}
		const vars: Record<string, string> = {
			DEMO_ACCESS_TOKEN: env.DEMO_ACCESS_TOKEN ?? "",
			SILO_LLM_PROVIDER: env.SILO_LLM_PROVIDER ?? "openai",
			SILO_TRUST_CF_CA: open ? "0" : "1",
		};
		if (env.OPENAI_API_KEY) vars.OPENAI_API_KEY = env.OPENAI_API_KEY;
		if (env.EXA_API_KEY) vars.EXA_API_KEY = env.EXA_API_KEY;
		if (env.SILO_INVESTIGATOR) vars.SILO_INVESTIGATOR = env.SILO_INVESTIGATOR;
		if (env.SILO_LLM_MODEL) vars.SILO_LLM_MODEL = env.SILO_LLM_MODEL;
		if (env.SILO_LLM_EFFORT) vars.SILO_LLM_EFFORT = env.SILO_LLM_EFFORT;
		this.envVars = vars;
	}

	// The default hooks log; this one logs nothing and lets the Worker answer 503.
	override onError(error: unknown): never {
		throw error;
	}
}

function reply(status: number, body: string, type = "text/plain; charset=utf-8", extra: Record<string, string> = {}): Response {
	return new Response(body, {
		status,
		headers: { "content-type": type, "cache-control": "no-store", "x-silo-origin": "worker", ...extra },
	});
}

function erro(status: number, message: string): Response {
	return reply(status, JSON.stringify({ erro: message }), "application/json; charset=utf-8");
}

async function digest(value: string): Promise<ArrayBuffer> {
	return crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
}

async function tokenMatches(given: string | null, expected: string): Promise<boolean> {
	if (!given) return false;
	const [a, b] = await Promise.all([digest(given), digest(expected)]);
	return crypto.subtle.timingSafeEqual(a, b);
}

function givenToken(request: Request): string | null {
	const header = request.headers.get(TOKEN_HEADER);
	if (header) return header.trim();
	const auth = request.headers.get("authorization") ?? "";
	const [scheme, ...rest] = auth.split(" ");
	return scheme.toLowerCase() === "bearer" && rest.length ? rest.join(" ").trim() : null;
}

// Reads the body up to the limit; null when it is larger. Never buffers more
// than the limit plus one chunk, whatever the client claims.
async function readCapped(body: ReadableStream<Uint8Array> | null): Promise<Uint8Array | null> {
	if (!body) return new Uint8Array(0);
	const reader = body.getReader();
	const chunks: Uint8Array[] = [];
	let size = 0;
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		size += value.byteLength;
		if (size > MAX_UPLOAD_BYTES) {
			await reader.cancel();
			return null;
		}
		chunks.push(value);
	}
	const out = new Uint8Array(size);
	let at = 0;
	for (const c of chunks) {
		out.set(c, at);
		at += c.byteLength;
	}
	return out;
}

async function diagnose(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
	// Fail closed: without the secret nothing is started.
	if (!env.DEMO_ACCESS_TOKEN) return erro(503, "Serviço não configurado.");
	if (!(await tokenMatches(givenToken(request), env.DEMO_ACCESS_TOKEN))) {
		return erro(401, "Acesso não autorizado.");
	}
	const declared = Number(request.headers.get("content-length") ?? "0");
	if (declared > MAX_UPLOAD_BYTES) return erro(413, "Arquivo grande demais: o limite é 10 MB.");
	const body = await readCapped(request.body);
	if (body === null) return erro(413, "Arquivo grande demais: o limite é 10 MB.");
	if (body.byteLength === 0) {
		return erro(400, "Envie o extrato no campo 'file' (multipart) ou no corpo da requisição.");
	}

	const forward = new Headers({
		authorization: `Bearer ${env.DEMO_ACCESS_TOKEN}`,
		"content-type": request.headers.get("content-type") ?? "application/octet-stream",
	});
	// One Durable Object, so one Container and one disk, per upload.
	const container = getContainer(env.ENGINE, crypto.randomUUID());
	let res: Response;
	try {
		res = await container.fetch(new Request("http://container/diagnose", { method: "POST", headers: forward, body }));
	} catch {
		ctx.waitUntil(container.destroy().catch(() => undefined));
		return erro(503, "Serviço ocupado ou iniciando. Tente de novo em alguns minutos.");
	}
	const out = await res.arrayBuffer();
	// The answer is in hand. After it goes out: read the run's trace from this
	// same instance (it keeps it in memory for one read), write it to R2, then
	// stop the instance, which frees the slot and discards its disk. The open
	// /trace request keeps the instance up; sleepAfter is only the backstop.
	const traceId = res.headers.get(TRACE_HEADER) ?? "";
	const isPdf = res.status === 200 && (res.headers.get("content-type") ?? "").startsWith("application/pdf");
	ctx.waitUntil(
		(async () => {
			try {
				if (env.TRACES && TRACE_ID.test(traceId)) {
					await storeTrace(env.TRACES, container, env.DEMO_ACCESS_TOKEN as string, traceId, isPdf ? out : null);
				}
			} catch {
				// A lost trace never fails the answer; nothing is logged.
			} finally {
				await container.stop().catch(() => undefined);
			}
		})(),
	);
	const headers = new Headers({ "cache-control": "no-store", "x-silo-origin": "engine" });
	for (const name of PASS_HEADERS) {
		const v = res.headers.get(name);
		if (v) headers.set(name, v);
	}
	return new Response(out, { status: res.status, headers });
}

async function sha256Hex(data: ArrayBuffer | Uint8Array): Promise<string> {
	const d = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
	return Array.from(d, (b) => b.toString(16).padStart(2, "0")).join("");
}

function fromBase64(b64: string): Uint8Array {
	const bin = atob(b64);
	const out = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
	return out;
}

interface TraceBundle {
	trace_id: string;
	trace: { resourceSpans: { scopeSpans: { spans: { attributes: { key: string; value: Record<string, unknown> }[] }[] }[] }[] };
	artifacts: Record<string, string>;
	documents?: Record<string, string>;
}

function rootAttribute(bundle: TraceBundle, key: string): string | null {
	const span = bundle.trace?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans?.[0];
	const kv = span?.attributes?.find((a) => a.key === key);
	const v = kv?.value?.stringValue;
	return typeof v === "string" ? v : null;
}

// One run's objects in R2 (ADR 0003). Each artifact is written under its own
// SHA-256, computed here: a body that does not hash to its key is skipped.
async function storeTrace(bucket: R2Bucket, container: { fetch: (r: Request) => Promise<Response> }, token: string, traceId: string, pdf: ArrayBuffer | null): Promise<void> {
	const res = await container.fetch(
		new Request(`http://container/trace/${traceId}`, { headers: { authorization: `Bearer ${token}` } }),
	);
	if (res.status !== 200) return;
	const raw = await res.arrayBuffer();
	const bundle = JSON.parse(new TextDecoder().decode(raw)) as TraceBundle;
	if (bundle.trace_id !== traceId) return;
	const day = new Date().toISOString().slice(0, 10).replaceAll("-", "/"); // UTC
	const puts: Promise<unknown>[] = [];
	for (const [key, b64] of Object.entries(bundle.artifacts ?? {})) {
		if (!SHA256_KEY.test(key)) continue;
		const body = fromBase64(b64);
		if (`artifacts/${await sha256Hex(body)}.json` !== key) continue;
		puts.push(bucket.put(key, body, { httpMetadata: { contentType: "application/json" } }));
	}
	for (const [key, b64] of Object.entries(bundle.documents ?? {})) {
		const m = DOC_KEY.exec(key);
		if (!m) continue;
		const body = fromBase64(b64);
		// A body that does not hash to its key is skipped, as for the artifacts.
		if ((await sha256Hex(body)) !== m[2]) continue;
		puts.push(bucket.put(key, body, { httpMetadata: { contentType: "text/plain; charset=utf-8" } }));
	}
	if (pdf) {
		const sha = await sha256Hex(pdf);
		// Only the PDF the engine traced: a different hash means a different body.
		if (rootAttribute(bundle, "app.pdf.sha256") === sha) {
			puts.push(bucket.put(`artifacts/${sha}.pdf`, pdf, { httpMetadata: { contentType: "application/pdf" } }));
		}
	}
	await Promise.all(puts);
	// The trace last, so a trace in R2 means its artifacts are there too.
	await bucket.put(`traces/${day}/${traceId}.json`, JSON.stringify(bundle.trace), {
		httpMetadata: { contentType: "application/json" },
	});
}

// Owner-only reads of the private bucket (ADR 0003), behind the same token as /diagnose. Nothing here
// logs, caches or stores: the answers carry portfolio data (holder, CPF and account already masked by the
// engine's readers), so they go out `no-store` to the page that asked and nowhere else.
async function ownerOnly(request: Request, env: Env): Promise<Response | null> {
	if (!env.DEMO_ACCESS_TOKEN) return erro(503, "Serviço não configurado.");
	if (!(await tokenMatches(givenToken(request), env.DEMO_ACCESS_TOKEN))) return erro(401, "Acesso não autorizado.");
	return null;
}

function json(status: number, body: unknown): Response {
	return reply(status, JSON.stringify(body), "application/json; charset=utf-8");
}

// The last `days` UTC days of traces, newest first (at most 50).
async function listTraces(url: URL, env: Env): Promise<Response> {
	const days = Math.min(Math.max(Number(url.searchParams.get("days") ?? "3") || 3, 1), 14);
	const found: { key: string; size: number; enviado: string }[] = [];
	for (let d = 0; d < days; d++) {
		const day = new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10).replaceAll("-", "/");
		const page = await env.TRACES.list({ prefix: `traces/${day}/`, limit: 100 });
		for (const o of page.objects) {
			if (TRACE_KEY.test(o.key)) found.push({ key: o.key, size: o.size, enviado: o.uploaded.toISOString() });
		}
	}
	found.sort((a, b) => b.enviado.localeCompare(a.enviado));
	return json(200, { traces: found.slice(0, 50) });
}

async function readTrace(env: Env, key: string | null): Promise<{ trace: unknown } | Response> {
	if (!key || !TRACE_KEY.test(key)) return erro(400, "Chave de trace inválida.");
	const obj = await env.TRACES.get(key);
	if (!obj) return erro(404, "Trace não encontrado.");
	return { trace: JSON.parse(await obj.text()) };
}

// With a ticker: the text of where that asset's exposure comes from. Without: the assets held through
// several statement lines, largest first.
async function traceExposure(url: URL, env: Env): Promise<Response> {
	const read = await readTrace(env, url.searchParams.get("key"));
	if (read instanceof Response) return read;
	const sha = traceRootAttribute(read.trace, "app.engine_json.sha256");
	if (!sha || !SHA256.test(sha)) return erro(422, "Este trace não tem o JSON do motor (a execução falhou antes de terminar).");
	const art = await env.TRACES.get(`artifacts/${sha}.json`);
	if (!art) return erro(404, "O JSON do motor deste trace não está no bucket.");
	const doc = JSON.parse(await art.text()) as EngineDoc;
	const ticker = (url.searchParams.get("ticker") ?? "").trim();
	if (!ticker) return json(200, { grupos: topGroups(doc, 10), cda: doc.look_through?.cda_month ?? null });
	if (!TICKER.test(ticker)) return erro(400, "Ticker inválido.");
	const texto = exposureText(doc, ticker);
	return json(200, { texto: texto ?? `${ticker.toUpperCase()}: nenhum ativo mantido por mais de uma linha do extrato corresponde a esse código.` });
}

// The PDF the run returned, as the Worker stored it (holder, CPF and account masked).
async function tracePdf(url: URL, env: Env): Promise<Response> {
	const read = await readTrace(env, url.searchParams.get("key"));
	if (read instanceof Response) return read;
	const sha = traceRootAttribute(read.trace, "app.pdf.sha256");
	if (!sha || !SHA256.test(sha)) return erro(422, "Este trace não tem PDF (a execução não gerou o relatório).");
	const pdf = await env.TRACES.get(`artifacts/${sha}.pdf`);
	if (!pdf) return erro(404, "O PDF deste trace não está no bucket.");
	return new Response(pdf.body, {
		status: 200,
		headers: {
			"content-type": "application/pdf",
			"content-disposition": 'attachment; filename="diagnostico.pdf"',
			"cache-control": "no-store",
			"x-silo-origin": "worker",
		},
	});
}

const PAGE_HEADERS = {
	"content-security-policy":
		"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
	"referrer-policy": "no-referrer",
	"x-robots-tag": "noindex",
};

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		const { pathname } = new URL(request.url);

		if (pathname === "/health" && (request.method === "GET" || request.method === "HEAD")) {
			return reply(200, "ok\n");
		}
		if (pathname === "/" && (request.method === "GET" || request.method === "HEAD")) {
			return reply(200, PAGE, "text/html; charset=utf-8", {
				"content-security-policy":
					"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
				"referrer-policy": "no-referrer",
			});
		}
		if (pathname === "/diagnose" && request.method === "POST") {
			return diagnose(request, env, ctx);
		}
		if (pathname === "/traces" && (request.method === "GET" || request.method === "HEAD")) {
			return reply(200, TRACES_PAGE, "text/html; charset=utf-8", PAGE_HEADERS);
		}
		if (pathname.startsWith("/api/traces") && request.method === "GET") {
			const denied = await ownerOnly(request, env);
			if (denied) return denied;
			const url = new URL(request.url);
			try {
				if (pathname === "/api/traces") return await listTraces(url, env);
				if (pathname === "/api/traces/exposure") return await traceExposure(url, env);
				if (pathname === "/api/traces/pdf") return await tracePdf(url, env);
			} catch {
				// Nothing is logged: a trace that does not read as JSON, or an R2 hiccup, is one plain error.
				return erro(500, "Não foi possível ler este trace.");
			}
		}
		return reply(404, "not found\n");
	},
} satisfies ExportedHandler<Env>;

const PAGE = `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Diagnóstico de carteira</title>
<style>
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fafaf7; --muted: #5f6368; --line: #d8d8d2; --accent: #1f5f8b; }
@media (prefers-color-scheme: dark) { :root { --fg: #ececea; --bg: #17181a; --muted: #a0a4a8; --line: #34363a; --accent: #7fb6dd; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 34rem; margin: 3rem auto; padding: 0 16px; }
h1 { font-size: 1.5rem; margin: 0 0 .5rem; }
p { color: var(--muted); margin: 0 0 1.5rem; }
label { display: block; font-weight: 600; margin: 1rem 0 .25rem; }
input { width: 100%; padding: .6rem; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: inherit; font: inherit; }
button { margin-top: 1.5rem; padding: .7rem 1.2rem; border: 0; border-radius: 6px; background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
button[disabled] { opacity: .6; cursor: wait; }
#status { margin-top: 1rem; min-height: 1.5rem; }
</style>
</head>
<body>
<main>
<h1>Diagnóstico de carteira</h1>
<p>Envie o extrato: o PDF do BTG ("Extrato da Conta Investimento" ou relatório de performance) ou a planilha modelo .xlsx. Com mais de uma conta, selecione um arquivo por conta: eles são somados num diagnóstico só. Até 10 MB no total. O arquivo enviado não é guardado. Guardamos, de forma privada, o relatório e a análise com nome, CPF e conta mascarados, para melhorar o serviço. O relatório leva alguns minutos.</p>
<form id="f">
<label for="token">Código de acesso</label>
<input id="token" type="password" autocomplete="off" required>
<label for="file">Extratos (um por conta)</label>
<input id="file" type="file" accept=".xlsx,.pdf" multiple required>
<button id="go" type="submit">Gerar diagnóstico</button>
</form>
<div id="status" role="status" aria-live="polite"></div>
</main>
<script>
const f = document.getElementById("f"), go = document.getElementById("go"), st = document.getElementById("status");
f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const files = Array.from(document.getElementById("file").files);
  const token = document.getElementById("token").value;
  if (!files.length) return;
  const total = files.reduce((n, f) => n + f.size, 0);
  if (total > 10 * 1024 * 1024) { st.textContent = "Arquivos grandes demais: o limite é 10 MB no total."; return; }
  const body = new FormData();
  for (const f of files) body.append("file", f);
  go.disabled = true;
  st.textContent = "Gerando o diagnóstico. Isso leva alguns minutos; mantenha esta página aberta.";
  try {
    // multipart: the browser sets the content-type with its boundary, and the Worker forwards it.
    const r = await fetch("/diagnose", { method: "POST", headers: { "x-demo-token": token }, body });
    if (r.ok) {
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "diagnostico.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 60000);
      st.textContent = "Pronto: o PDF foi baixado.";
    } else {
      let msg = "Erro " + r.status + ".";
      try { const j = await r.json(); if (j && j.erro) msg = j.erro; } catch (_) {}
      st.textContent = msg;
    }
  } catch (_) {
    st.textContent = "A conexão caiu antes do fim. Tente de novo.";
  } finally {
    go.disabled = false;
  }
});
</script>
</body>
</html>
`;

const TRACES_PAGE = `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Traces do diagnóstico</title>
<style>
:root { color-scheme: light dark; --fg: #1d1d1f; --bg: #fafaf7; --muted: #5f6368; --line: #d8d8d2; --accent: #1f5f8b; }
@media (prefers-color-scheme: dark) { :root { --fg: #ececea; --bg: #17181a; --muted: #a0a4a8; --line: #34363a; --accent: #7fb6dd; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 40rem; margin: 2rem auto; padding: 0 16px; }
h1 { font-size: 1.4rem; margin: 0 0 .5rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .5rem; }
p { color: var(--muted); margin: 0 0 1rem; }
input { width: 100%; padding: .6rem; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: inherit; font: inherit; }
button { padding: .6rem 1rem; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
button.main { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.row { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .5rem; }
ul { list-style: none; padding: 0; margin: 0; }
li { margin: 0 0 .5rem; }
li button { width: 100%; text-align: left; }
pre { white-space: pre-wrap; word-break: break-word; border: 1px solid var(--line); border-radius: 6px; padding: .75rem; font: 14px/1.5 ui-monospace, monospace; }
#status { min-height: 1.5rem; color: var(--muted); }
</style>
</head>
<body>
<main>
<h1>Traces do diagnóstico</h1>
<p>Só para o dono. Mostra as execuções guardadas de forma privada (nome, CPF e conta já mascarados) e de onde vem a exposição a um ativo. O código não fica guardado nesta página.</p>
<label for="token">Código de acesso</label>
<input id="token" type="password" autocomplete="off">
<div class="row"><button class="main" id="list">Listar execuções</button></div>
<div id="status" role="status" aria-live="polite"></div>
<ul id="traces"></ul>
<div id="detail" hidden>
<h2 id="detail-title"></h2>
<div class="row"><button id="pdf">Baixar o PDF</button></div>
<h2>Exposição a um ativo</h2>
<ul id="groups"></ul>
<label for="ticker">Ou um código (ex.: PETR4)</label>
<input id="ticker" autocomplete="off" autocapitalize="characters">
<div class="row"><button id="go">Ver origem</button></div>
<pre id="out" hidden></pre>
</div>
</main>
<script>
const $ = (id) => document.getElementById(id);
let key = null;
const tok = () => $("token").value.trim();
const say = (t) => { $("status").textContent = t; };
const when = (iso) => new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) + " (UTC-3)";
async function api(path) {
  const r = await fetch(path, { headers: { "x-demo-token": tok() } });
  if (!r.ok) {
    let msg = "Erro " + r.status + ".";
    try { const j = await r.json(); if (j && j.erro) msg = j.erro; } catch (_) {}
    throw new Error(msg);
  }
  return r;
}
function item(list, text, onclick) {
  const li = document.createElement("li");
  const b = document.createElement("button");
  b.textContent = text;
  b.addEventListener("click", onclick);
  li.appendChild(b);
  list.appendChild(li);
}
async function showExposure(ticker) {
  $("out").hidden = false;
  $("out").textContent = "Lendo...";
  try {
    const j = await (await api("/api/traces/exposure?key=" + encodeURIComponent(key) + "&ticker=" + encodeURIComponent(ticker))).json();
    $("out").textContent = j.texto;
  } catch (e) { $("out").textContent = e.message; }
}
async function openTrace(t) {
  key = t.key;
  $("detail").hidden = false;
  $("detail-title").textContent = "Execução de " + when(t.enviado);
  $("groups").replaceChildren();
  $("out").hidden = true;
  say("Lendo os ativos repetidos entre linhas...");
  try {
    const j = await (await api("/api/traces/exposure?key=" + encodeURIComponent(key))).json();
    say(j.grupos.length ? "" : "Nenhum ativo aparece em mais de uma linha desta execução.");
    for (const g of j.grupos) {
      const code = g.label.split(" ")[0];
      item($("groups"), g.label + ": " + g.total_brl.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) + " (" + g.portfolio_pct.toFixed(2).replace(".", ",") + "% da carteira, " + g.n_lines + " linhas)", () => showExposure(code));
    }
  } catch (e) { say(e.message); }
}
$("list").addEventListener("click", async () => {
  $("traces").replaceChildren();
  $("detail").hidden = true;
  say("Listando...");
  try {
    const j = await (await api("/api/traces?days=7")).json();
    say(j.traces.length ? "" : "Nenhuma execução nos últimos 7 dias.");
    for (const t of j.traces) item($("traces"), when(t.enviado) + " · " + Math.round(t.size / 1024) + " KB", () => openTrace(t));
  } catch (e) { say(e.message); }
});
$("go").addEventListener("click", () => { const t = $("ticker").value.trim(); if (t && key) showExposure(t); });
$("pdf").addEventListener("click", async () => {
  if (!key) return;
  say("Baixando o PDF...");
  try {
    const blob = await (await api("/api/traces/pdf?key=" + encodeURIComponent(key))).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "diagnostico.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    say("Pronto: o PDF foi baixado.");
  } catch (e) { say(e.message); }
});
</script>
</body>
</html>
`;
