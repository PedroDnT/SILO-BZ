// The portfolio-diagnosis demo on Cloudflare (map #510, slice E step 2).
//
// GET  /          the upload page (Portuguese, token field, downloads the PDF)
// GET  /health    answered by the Worker itself, public, no container
// POST /diagnose  needs the shared token; starts a fresh engine Container for
//                 this upload alone, forwards the statement with
//                 `Authorization: Bearer`, returns the PDF, then stops it; answers the run's R2 trace key
//                 as `x-silo-trace-key` (the page links to /traces#<key>)
// GET  /traces    the owner's trace page (static shell, no data): asks for the token, lists runs, shows where an
//                 asset's exposure comes from and downloads a run's PDF; /traces#<trace key> opens one run
// GET  /api/traces, /api/traces/exposure, /api/traces/pdf, /api/traces/report, /api/traces/agents, /api/traces/investigation
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
import { agentTimeline, type InvestigationDoc, investigationView } from "./agents";
import { type EngineDoc, exposureFlows, exposureText, topGroups, traceRootAttribute } from "./exposure";

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
	SILO_LLM_EFFORT_REDATOR?: string;
	SILO_LLM_EFFORT_REVISOR?: string;
	// "allowlist" (default): only the hosts below. "open": internet on.
	EGRESS?: string;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const TOKEN_HEADER = "x-demo-token";
// The engine names each run's trace here; not passed through (not in PASS_HEADERS).
const TRACE_HEADER = "x-silo-trace-id";
// The Worker's own answer header: the R2 key it writes the run's trace to, for a link to /traces#<key>.
// Reading that key still needs the token, which the caller of /diagnose already holds.
const TRACE_KEY_HEADER = "x-silo-trace-key";
const TRACE_ID = /^[0-9a-f]{32}$/;
const SHA256_KEY = /^artifacts\/[0-9a-f]{64}\.(json|html)$/;
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
		if (env.SILO_LLM_EFFORT_REDATOR) vars.SILO_LLM_EFFORT_REDATOR = env.SILO_LLM_EFFORT_REDATOR;
		if (env.SILO_LLM_EFFORT_REVISOR) vars.SILO_LLM_EFFORT_REVISOR = env.SILO_LLM_EFFORT_REVISOR;
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
	const willStore = Boolean(env.TRACES) && TRACE_ID.test(traceId);
	// The UTC day is fixed now, so the key sent to the client is the key written.
	const day = new Date().toISOString().slice(0, 10).replaceAll("-", "/");
	const isPdf = res.status === 200 && (res.headers.get("content-type") ?? "").startsWith("application/pdf");
	ctx.waitUntil(
		(async () => {
			try {
				if (willStore) {
					await storeTrace(env.TRACES, container, env.DEMO_ACCESS_TOKEN as string, traceId, day, isPdf ? out : null);
				}
			} catch {
				// A lost trace never fails the answer; nothing is logged.
			} finally {
				await container.stop().catch(() => undefined);
			}
		})(),
	);
	const headers = new Headers({ "cache-control": "no-store", "x-silo-origin": "engine" });
	if ((res.headers.get("content-type") ?? "").startsWith("text/html")) {
		headers.set("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'");
	}
	for (const name of PASS_HEADERS) {
		const v = res.headers.get(name);
		if (v) headers.set(name, v);
	}
	if (willStore) headers.set(TRACE_KEY_HEADER, `traces/${day}/${traceId}.json`);
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
async function storeTrace(bucket: R2Bucket, container: { fetch: (r: Request) => Promise<Response> }, token: string, traceId: string, day: string, pdf: ArrayBuffer | null): Promise<void> {
	const res = await container.fetch(
		new Request(`http://container/trace/${traceId}`, { headers: { authorization: `Bearer ${token}` } }),
	);
	if (res.status !== 200) return;
	const raw = await res.arrayBuffer();
	const bundle = JSON.parse(new TextDecoder().decode(raw)) as TraceBundle;
	if (bundle.trace_id !== traceId) return;
	const puts: Promise<unknown>[] = [];
	for (const [key, b64] of Object.entries(bundle.artifacts ?? {})) {
		if (!SHA256_KEY.test(key)) continue;
		const body = fromBase64(b64);
		const ext = key.endsWith(".html") ? "html" : "json";
		if (`artifacts/${await sha256Hex(body)}.${ext}` !== key) continue;
		puts.push(bucket.put(key, body, { httpMetadata: { contentType: ext === "html" ? "text/html; charset=utf-8" : "application/json" } }));
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

// The last `days` UTC days of traces (at most 30), newest first (at most 100).
const MAX_LIST_DAYS = 30;
const MAX_LIST_TRACES = 100;
async function listTraces(url: URL, env: Env): Promise<Response> {
	const days = Math.min(Math.max(Number(url.searchParams.get("days") ?? "3") || 3, 1), MAX_LIST_DAYS);
	const found: { key: string; size: number; enviado: string }[] = [];
	for (let d = 0; d < days; d++) {
		const day = new Date(Date.now() - d * 86_400_000).toISOString().slice(0, 10).replaceAll("-", "/");
		const page = await env.TRACES.list({ prefix: `traces/${day}/`, limit: 100 });
		for (const o of page.objects) {
			if (TRACE_KEY.test(o.key)) found.push({ key: o.key, size: o.size, enviado: o.uploaded.toISOString() });
		}
	}
	found.sort((a, b) => b.enviado.localeCompare(a.enviado));
	return json(200, { traces: found.slice(0, MAX_LIST_TRACES) });
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
	return json(200, {
		texto: texto ?? `${ticker.toUpperCase()}: nenhum ativo mantido por mais de uma linha do extrato corresponde a esse código.`,
		fluxos: exposureFlows(doc, ticker),
	});
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

// The report's HTML as the engine built it and the Worker stored it (holder, CPF and account masked), sent as
// text for the page to show in a sandboxed frame. Its own policy lets it carry no script and no request.
async function traceReport(url: URL, env: Env): Promise<Response> {
	const read = await readTrace(env, url.searchParams.get("key"));
	if (read instanceof Response) return read;
	const sha = traceRootAttribute(read.trace, "app.html.sha256");
	if (!sha || !SHA256.test(sha)) return erro(422, "Este trace não guardou o relatório em HTML (execuções anteriores a esta função, ou que falharam antes do relatório).");
	const html = await env.TRACES.get(`artifacts/${sha}.html`);
	if (!html) return erro(404, "O HTML deste trace não está no bucket.");
	return new Response(html.body, {
		status: 200,
		headers: {
			"content-type": "text/html; charset=utf-8",
			"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; sandbox",
			"cache-control": "no-store",
			"x-silo-origin": "worker",
		},
	});
}

// The run as the agents lived it: each span with its start, duration, model, tokens and cost.
async function traceAgents(url: URL, env: Env): Promise<Response> {
	const read = await readTrace(env, url.searchParams.get("key"));
	if (read instanceof Response) return read;
	const timeline = agentTimeline(read.trace);
	if (!timeline) return erro(422, "Este trace não tem spans.");
	return json(200, timeline);
}

// What the investigator did and found, from the engine JSON of the run.
async function traceInvestigation(url: URL, env: Env): Promise<Response> {
	const read = await readTrace(env, url.searchParams.get("key"));
	if (read instanceof Response) return read;
	const sha = traceRootAttribute(read.trace, "app.engine_json.sha256");
	if (!sha || !SHA256.test(sha)) return erro(422, "Este trace não tem o JSON do motor (a execução falhou antes de terminar).");
	const art = await env.TRACES.get(`artifacts/${sha}.json`);
	if (!art) return erro(404, "O JSON do motor deste trace não está no bucket.");
	const view = investigationView(JSON.parse(await art.text()) as InvestigationDoc);
	if (!view) return erro(422, "Este JSON do motor não tem a seção do investigador.");
	return json(200, view);
}

const PAGE_HEADERS = {
	"content-security-policy":
		"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
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
					"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'",
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
				if (pathname === "/api/traces/report") return await traceReport(url, env);
				if (pathname === "/api/traces/agents") return await traceAgents(url, env);
				if (pathname === "/api/traces/investigation") return await traceInvestigation(url, env);
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
label.check { display: inline-flex; align-items: center; gap: .4rem; font-weight: 400; margin: .5rem 1rem 0 0; }
label.check input { width: auto; }
button.plain { margin-top: .5rem; padding: .3rem .8rem; background: transparent; color: inherit; border: 1px solid var(--line); font-weight: 400; cursor: pointer; }
a { color: var(--accent); }
</style>
</head>
<body>
<main>
<h1>Diagnóstico de carteira</h1>
<p>Envie o extrato: o PDF do BTG ("Extrato da Conta Investimento" ou relatório de performance) ou a planilha modelo .xlsx. Com mais de uma conta, selecione um arquivo por conta: eles são somados num diagnóstico só. Até 10 MB no total. O arquivo enviado não é guardado. Guardamos, de forma privada, o relatório e a análise com nome, CPF e conta mascarados, para melhorar o serviço. O relatório leva alguns minutos. O código de acesso só fica guardado neste navegador se você marcar "Lembrar neste aparelho"; "Esquecer" o apaga.</p>
<form id="f">
<label for="token">Código de acesso</label>
<input id="token" type="password" autocomplete="off" required>
<label class="check"><input id="remember" type="checkbox"> Lembrar neste aparelho</label><button id="forget" class="plain" type="button">Esquecer</button>
<label for="file">Extratos (um por conta)</label>
<input id="file" type="file" accept=".xlsx,.pdf" multiple required>
<fieldset><legend>Restrições do cliente (opcional)</legend>
<label for="profile">Perfil declarado</label><select id="profile"><option value="">Não informado</option><option value="conservador">Conservador</option><option value="moderado">Moderado</option><option value="arrojado">Arrojado</option></select>
<label for="horizon">Data do horizonte de investimento</label><input id="horizon" type="date">
<label for="needDate">Data da necessidade de liquidez</label><input id="needDate" type="date">
<label for="need">Valor necessário (R$)</label><input id="need" type="number" min="0" step="0.01">
<p>Checagem factual; não aprova produtos nem substitui suitability. Não informe nome ou documentos.</p></fieldset>
<button id="go" type="submit">Gerar diagnóstico</button>
</form>
<div id="status" role="status" aria-live="polite"></div><p><a id="tracelink" href="/traces" hidden>Ver esta execução nos traces</a></p><button id="print" type="button" hidden>Imprimir / salvar PDF</button><iframe id="report" title="Diagnóstico de carteira" sandbox="allow-same-origin allow-modals" style="width:100%;height:80vh;border:0" hidden></iframe>
</main>
<script>
// The access code is kept only when the box is ticked, only in this browser, and every storage call may throw
// (blocked storage, private mode): then nothing is kept and the page works the same.
const MEMO = "silo-demo-token";
const recall = () => { try { return localStorage.getItem(MEMO) || ""; } catch (_) { return ""; } };
const keep = (v) => { try { localStorage.setItem(MEMO, v); } catch (_) {} };
const forget = () => { try { localStorage.removeItem(MEMO); } catch (_) {} };
{
  const saved = recall();
  if (saved) { document.getElementById("token").value = saved; document.getElementById("remember").checked = true; }
}
document.getElementById("remember").addEventListener("change", (e) => { if (!e.target.checked) forget(); });
document.getElementById("forget").addEventListener("click", () => {
  forget();
  document.getElementById("remember").checked = false;
  document.getElementById("token").value = "";
  document.getElementById("status").textContent = "Código esquecido neste aparelho.";
});
document.getElementById("print").addEventListener("click", () => {
  const frame = document.getElementById("report");
  frame.contentDocument.querySelectorAll("details").forEach(d => d.open = true);
  frame.contentWindow.print();
});
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
  body.append("output_format", "html");
  const constraints = {};
  for (const [id, key] of [["profile", "profile"], ["horizon", "horizon_date"], ["needDate", "liquidity_date"], ["need", "liquidity_brl"]]) {
    const value = document.getElementById(id).value;
    if (value !== "") constraints[key] = value;
  }
  if (constraints.liquidity_brl && !constraints.liquidity_date) { st.textContent = "Informe a data da necessidade de liquidez."; return; }
  if (Object.keys(constraints).length) body.append("client_constraints", JSON.stringify(constraints));
  document.getElementById("report").hidden = true;
  document.getElementById("print").hidden = true;
  document.getElementById("tracelink").hidden = true;
  go.disabled = true;
  st.textContent = "Gerando o diagnóstico. Isso leva alguns minutos; mantenha esta página aberta.";
  try {
    // multipart: the browser sets the content-type with its boundary, and the Worker forwards it.
    const r = await fetch("/diagnose", { method: "POST", headers: { "x-demo-token": token }, body });
    if (r.ok) {
      if (document.getElementById("remember").checked) keep(token);
      const traceKey = r.headers.get("x-silo-trace-key");
      const tl = document.getElementById("tracelink");
      tl.href = "/traces" + (traceKey ? "#" + traceKey : "");
      tl.hidden = false;
      const frame = document.getElementById("report");
      frame.srcdoc = await r.text();
      frame.hidden = false;
      document.getElementById("print").hidden = false;
      st.textContent = "Pronto: brief e análise disponíveis abaixo. O PDF é salvo somente quando solicitado.";
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
:root { --direct: #1f5f8b; --fund: #b8741a; --box: #ffffff; }
@media (prefers-color-scheme: dark) { :root { --direct: #7fb6dd; --fund: #e0a458; --box: #1f2124; } }
#flow h3 { font-size: .95rem; margin: 1rem 0 .25rem; }
#flow svg { display: block; width: 100%; height: auto; margin-bottom: .25rem; }
.node { fill: var(--box); stroke: var(--line); stroke-width: 1; }
.node-asset { fill: var(--box); stroke: var(--fg); stroke-width: 1.5; }
.rib-direct { fill: var(--direct); fill-opacity: .55; }
.rib-fund { fill: var(--fund); fill-opacity: .55; }
.arrow-direct { fill: var(--direct); }
.arrow-fund { fill: var(--fund); }
.t { fill: var(--fg); font: 11px system-ui, sans-serif; }
.t-b { font-weight: 700; font-size: 12px; }
.t-m { fill: var(--muted); }
.t-tag-direct { fill: var(--direct); font-weight: 700; }
.t-tag-fund { fill: var(--fund); font-weight: 700; }
.card { border: 1px solid var(--line); border-radius: 6px; padding: .6rem .75rem; margin: 0 0 .5rem; }
.card strong { display: block; margin-bottom: .15rem; }
.card div { color: var(--muted); font-size: .9rem; word-break: break-word; }
.card a { color: var(--accent); }
.bar { height: 8px; background: var(--line); border-radius: 4px; margin: .35rem 0; }
.bar span { display: block; height: 8px; background: var(--accent); border-radius: 4px; min-width: 2px; }
.sum { color: var(--fg); font-size: .95rem; margin: 0 0 .75rem; }
.t-halo { paint-order: stroke; stroke: var(--bg); stroke-width: 3px; stroke-linejoin: round; font-weight: 700; }
label.check { display: inline-flex; align-items: center; gap: .4rem; }
label.check input { width: auto; }
select { padding: .55rem; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: inherit; font: inherit; }
a { color: var(--accent); }
</style>
</head>
<body>
<main>
<h1>Traces do diagnóstico</h1>
<p>Só para o dono. Mostra as execuções guardadas de forma privada (nome, CPF e conta já mascarados) e de onde vem a exposição a um ativo. O código só fica guardado neste navegador se você marcar "Lembrar neste aparelho"; "Esquecer" o apaga. Cada execução tem um link próprio (/traces#chave), que só abre com o código.</p>
<label for="token">Código de acesso</label>
<input id="token" type="password" autocomplete="off">
<div class="row"><label class="check"><input id="remember" type="checkbox"> Lembrar neste aparelho</label><button id="forget" type="button">Esquecer</button></div>
<div class="row"><label for="days">Período</label><select id="days"><option value="3">3 dias</option><option value="7" selected>7 dias</option><option value="14">14 dias</option><option value="30">30 dias</option></select><button class="main" id="list">Listar execuções</button></div>
<div id="status" role="status" aria-live="polite"></div>
<ul id="traces"></ul>
<div id="detail" hidden>
<h2 id="detail-title"></h2>
<p><a id="permalink" href="#">Link desta execução</a></p>
<div class="row"><button class="main" id="html">Ver o relatório em HTML</button><button id="pdf">Baixar o PDF</button></div>
<div class="row"><button id="print" type="button" hidden>Imprimir / salvar PDF</button></div>
<iframe id="report" title="Relatório da execução" sandbox="allow-same-origin allow-modals" style="width:100%;height:80vh;border:0;margin-top:.5rem" hidden></iframe>
<h2>Agentes desta execução</h2>
<div class="row"><button id="agents">Ver a linha do tempo dos agentes</button></div>
<div id="agents-out"></div>
<h2>O que o investigador achou</h2>
<div class="row"><button id="inv">Ver o investigador</button></div>
<div id="inv-out"></div>
<h2>Exposição a um ativo</h2>
<ul id="groups"></ul>
<label for="ticker">Ou um código (ex.: PETR4)</label>
<input id="ticker" autocomplete="off" autocapitalize="characters">
<div class="row"><button id="go">Ver origem</button></div>
<div id="flow"></div>
<pre id="out" hidden></pre>
</div>
</main>
<script>
const $ = (id) => document.getElementById(id);
let key = null;
let runs = [];
// The access code is kept only when the box is ticked, only in this browser, and every storage call may throw
// (blocked storage, private mode): then nothing is kept and the page works the same.
const MEMO = "silo-demo-token";
const recall = () => { try { return localStorage.getItem(MEMO) || ""; } catch (_) { return ""; } };
const keep = (v) => { try { localStorage.setItem(MEMO, v); } catch (_) {} };
const forget = () => { try { localStorage.removeItem(MEMO); } catch (_) {} };
const tok = () => $("token").value.trim();
const say = (t) => { $("status").textContent = t; };
const when = (iso) => new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) + " (UTC-3)";
async function api(path) {
  const r = await fetch(path, { headers: { "x-demo-token": tok() } });
  if (r.ok && $("remember").checked) keep(tok());
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
const NS = "http://www.w3.org/2000/svg";
function svgEl(name, attrs, text) {
  const e = document.createElementNS(NS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
const money = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const pct = (v) => v.toFixed(2).replace(".", ",") + "%";
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const mmyyyy = (ym) => ym.slice(5, 7) + "/" + ym.slice(0, 4);
// One asset as arrows: a box per statement line that holds it (its name first, then its line number),
// a ribbon per line as thick as the R$ it puts in, and the asset on the right. Text only via textContent.
function drawFlow(host, f) {
  const src = f.fontes.filter((s) => s.exposicao_brl > 0);
  const rest = f.fontes.filter((s) => !(s.exposicao_brl > 0));
  const title = document.createElement("h3");
  title.textContent = f.ativo.label;
  host.appendChild(title);
  const W = 360, LW = 168, RW = 112, RX = W - RW, BH = 94, GAP = 12, XE = RX - 8, SLOT = 14;
  const n = src.length;
  const maxV = Math.max.apply(null, src.map((s) => s.exposicao_brl));
  const thick = src.map((s) => Math.max(5, (30 * s.exposicao_brl) / maxV));
  const total = thick.reduce((a, b) => a + b, 0) + SLOT * Math.max(n - 1, 0);
  const leftH = n * BH + (n - 1) * GAP;
  const RH = Math.max(96, total + 24);
  const H = Math.max(leftH, RH) + 24;
  const ry = (H - RH) / 2;
  const svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Origem da exposição a " + f.ativo.label });
  const cx = LW + (XE - LW) / 2;
  let slot = ry + (RH - total) / 2;
  const leftTop = (H - leftH) / 2;
  src.forEach((s, i) => {
    const y = leftTop + i * (BH + GAP), yc = y + BH / 2, t = thick[i], sy = slot + t / 2;
    slot += t + SLOT;
    const kind = s.direto ? "direct" : "fund";
    svg.appendChild(svgEl("path", { class: "rib-" + kind, d: "M" + LW + "," + (yc - t / 2) + " C" + cx + "," + (yc - t / 2) + " " + cx + "," + (sy - t / 2) + " " + XE + "," + (sy - t / 2) + " L" + XE + "," + (sy + t / 2) + " C" + cx + "," + (sy + t / 2) + " " + cx + "," + (yc + t / 2) + " " + LW + "," + (yc + t / 2) + " Z" }));
    svg.appendChild(svgEl("path", { class: "arrow-" + kind, d: "M" + XE + "," + (sy - t / 2 - 4) + " L" + RX + "," + sy + " L" + XE + "," + (sy + t / 2 + 4) + " Z" }));
    svg.appendChild(svgEl("rect", { class: "node", x: 0, y: y, width: LW, height: BH, rx: 6 }));
    const longName = s.nome.length > 21;
    const nameEl = svgEl("text", { class: "t t-b", x: 8, y: y + 16 }, short(s.nome, 25));
    if (longName) nameEl.setAttribute("style", "font-size:11px");
    const full = svgEl("title", {}, s.nome);
    nameEl.appendChild(full);
    svg.appendChild(nameEl);
    svg.appendChild(svgEl("text", { class: "t t-m", x: 8, y: y + 31 }, "linha " + s.line_no + (s.tipo ? " · " + s.tipo : "")));
    svg.appendChild(svgEl("text", { class: "t t-tag-" + kind, x: 8, y: y + 45 }, s.direto ? "direta" : "via fundo"));
    svg.appendChild(svgEl("text", { class: "t t-tag-" + kind, x: 8, y: y + 59 }, "→ " + money(s.exposicao_brl)));
    if (s.posicao_brl !== null) svg.appendChild(svgEl("text", { class: "t t-m", x: 8, y: y + 73 }, "posição " + money(s.posicao_brl)));
    if (!s.direto && s.peso_no_fundo_pct !== null) svg.appendChild(svgEl("text", { class: "t", x: 8, y: y + 87 }, pct(s.peso_no_fundo_pct) + " do fundo" + (s.cda ? " · CDA " + mmyyyy(s.cda) : "")));
    else if (!s.direto && s.cda) svg.appendChild(svgEl("text", { class: "t", x: 8, y: y + 87 }, "CDA " + mmyyyy(s.cda)));
  });
  svg.appendChild(svgEl("rect", { class: "node-asset", x: RX, y: ry, width: RW, height: RH, rx: 6 }));
  const code = f.ativo.label.split(" ")[0];
  const codeEl = svgEl("text", { class: "t t-b", x: RX + 8, y: ry + 20 }, short(code, 14));
  if (code.length > 9) codeEl.setAttribute("style", "font-size:10.5px");
  svg.appendChild(codeEl);
  svg.appendChild(svgEl("text", { class: "t t-m", x: RX + 8, y: ry + 36 }, "total"));
  svg.appendChild(svgEl("text", { class: "t", x: RX + 8, y: ry + 51 }, money(f.ativo.total_brl)));
  svg.appendChild(svgEl("text", { class: "t t-b", x: RX + 8, y: ry + 70 }, pct(f.ativo.portfolio_pct)));
  svg.appendChild(svgEl("text", { class: "t t-m", x: RX + 8, y: ry + 84 }, "da carteira"));
  host.appendChild(svg);
  rest.forEach((s) => {
    const p = document.createElement("p");
    p.textContent = "Sem seta (valor zero ou negativo): " + s.nome + " (linha " + s.line_no + "): " + money(s.exposicao_brl);
    host.appendChild(p);
  });
}
const fmtn = (v, d) => v.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const usd = (v) => "US$ " + fmtn(v, 4);
const dur = (s) => (s >= 60 ? Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" : fmtn(s, 1) + " s");
function card(host, title, lines, bar) {
  const d = document.createElement("div");
  d.className = "card";
  const h = document.createElement("strong");
  h.textContent = title;
  d.appendChild(h);
  if (bar) {
    const b = document.createElement("div");
    b.className = "bar";
    const sp = document.createElement("span");
    sp.style.marginLeft = bar.from + "%";
    sp.style.width = bar.width + "%";
    b.appendChild(sp);
    d.appendChild(b);
  }
  for (const l of lines) {
    if (!l) continue;
    const p = document.createElement("div");
    p.textContent = l;
    d.appendChild(p);
  }
  host.appendChild(d);
  return d;
}
function link(card, url) {
  if (!url) return;
  const p = document.createElement("div");
  if (url.indexOf("https://") === 0) {
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = url;
    p.appendChild(a);
  } else {
    p.textContent = url;
  }
  card.appendChild(p);
}
function summary(host, text) {
  const p = document.createElement("p");
  p.className = "sum";
  p.textContent = text;
  host.appendChild(p);
}
function showAgents(t) {
  const host = $("agents-out");
  host.replaceChildren();
  const head = ["HTTP " + (t.http === null ? "?" : t.http), "total " + dur(t.total_s)];
  if (t.custo_usd !== null) head.push("custo " + usd(t.custo_usd));
  if (t.revisao_do_motor) head.push("motor " + t.revisao_do_motor);
  if (t.esquema) head.push("esquema " + t.esquema);
  summary(host, head.join(" · "));
  if (t.etapa_que_falhou) summary(host, "Falhou na etapa " + t.etapa_que_falhou + (t.tipo_do_erro ? " (" + t.tipo_do_erro + ")" : "") + ".");
  const total = t.total_s > 0 ? t.total_s : 1;
  for (const r of t.linhas) {
    const lines = ["começa em +" + dur(r.inicio_s) + ", dura " + dur(r.duracao_s) + (r.estado === "ok" || r.estado === "erro" ? " · " + r.estado : "")];
    if (r.modelo) lines.push("modelo " + r.modelo + (r.chamadas !== null ? " · " + r.chamadas + " chamada(s)" : ""));
    if (r.tokens_entrada !== null || r.tokens_saida !== null) {
      lines.push("tokens: entrada " + (r.tokens_entrada === null ? "?" : r.tokens_entrada) + ", saída " + (r.tokens_saida === null ? "?" : r.tokens_saida) + (r.tokens_raciocinio ? " (raciocínio " + r.tokens_raciocinio + ")" : ""));
    }
    if (r.buscas_exa !== null) lines.push(r.buscas_exa + " busca(s) no Exa");
    if (r.custo_usd !== null) lines.push("custo " + usd(r.custo_usd));
    for (const n of r.notas) lines.push(n);
    for (const x of r.removidos) lines.push("o revisor removeu: " + (x.secao || "?") + " (" + (x.regra || "?") + ")" + (x.inteiro ? ", o achado inteiro" : ""));
    card(host, r.nome, lines, { from: Math.min(100 * r.inicio_s / total, 99), width: Math.max(100 * r.duracao_s / total, 1) });
  }
}
function showInvestigation(v) {
  const host = $("inv-out");
  host.replaceChildren();
  if (!v.ligado) {
    summary(host, "O investigador estava desligado nesta execução." + (v.motivo ? " " + v.motivo : ""));
    return;
  }
  const head = ["estado " + (v.estado || "?"), "buscas " + v.buscas.usadas + (v.buscas.limite ? " de " + v.buscas.limite : "")];
  if (v.custo.total_usd !== null) head.push("custo " + usd(v.custo.total_usd) + (v.custo.exa_usd !== null ? " (Exa " + usd(v.custo.exa_usd) + ")" : ""));
  summary(host, head.join(" · "));
  const c = v.contagens;
  summary(host, "fatos " + (c.facts || 0) + " (nível A " + (c.tier_a || 0) + ", nível B " + (c.tier_b || 0) + ") · divergências " + (c.divergences || 0) + " · documentos lidos " + (c.documents_read || 0) + ", não lidos " + (c.documents_not_read || 0) + (v.descartados ? " · " + v.descartados : ""));
  if (v.busca_na_web.disponivel === false) summary(host, v.busca_na_web.nota || "Busca na web indisponível.");
  if (v.modelos.extrator) summary(host, "modelo de extração " + v.modelos.extrator + (v.modelos.juiz ? " · juiz " + v.modelos.juiz : " · sem juiz"));
  const h1 = document.createElement("h2");
  h1.textContent = "Itens investigados";
  host.appendChild(h1);
  if (!v.gatilhos.length) summary(host, "Nenhuma linha ativou o investigador.");
  for (const g of v.gatilhos) card(host, "Linha " + (g.linha === null ? "?" : g.linha) + (g.nome_da_linha ? " · " + g.nome_da_linha : "") + " · " + (g.tipo || ""), [g.identificadores, g.mensagem, g.buscas !== null ? g.buscas + " busca(s) · " + g.fontes_tentadas + " fonte(s) tentada(s)" : null]);
  const h2 = document.createElement("h2");
  h2.textContent = "Fatos encontrados";
  host.appendChild(h2);
  if (!v.fatos.length) summary(host, "Nenhum fato com citação passou pela verificação.");
  for (const f of v.fatos) {
    const d = card(host, (f.campo || "fato") + (f.assunto ? " · " + f.assunto : "") + " · linha " + (f.linha === null ? "?" : f.linha), [
      f.valor, f.citacao ? "citação: " + f.citacao : null, "nível " + (f.nivel || "?") + ": " + (f.nivel_rotulo || ""),
      f.documento ? "documento: " + f.documento + (f.data_do_documento ? " (" + f.data_do_documento + ")" : "") : null,
      f.fonte ? "fonte: " + f.fonte : null, f.confere,
    ]);
    link(d, f.url);
  }
  const h3 = document.createElement("h2");
  h3.textContent = "Documentos consultados";
  host.appendChild(h3);
  if (!v.documentos.length) summary(host, "Nenhum documento foi consultado.");
  for (const x of v.documentos) {
    const d = card(host, x.titulo || "(sem título)", [(x.fonte || "") + " · " + (x.estado || "") + (x.cache ? " · cache " + x.cache : "")]);
    link(d, x.url);
  }
}
async function showExposure(ticker) {
  $("out").hidden = false;
  $("out").textContent = "Lendo...";
  $("flow").replaceChildren();
  try {
    const j = await (await api("/api/traces/exposure?key=" + encodeURIComponent(key) + "&ticker=" + encodeURIComponent(ticker))).json();
    for (const f of j.fluxos || []) drawFlow($("flow"), f);
    $("out").textContent = j.texto;
  } catch (e) { $("out").textContent = e.message; }
}
// The run named in the address (/traces#traces/YYYY/MM/DD/<id>.json); the server checks its shape.
const hashKey = () => { try { return decodeURIComponent(location.hash.slice(1)); } catch (_) { return ""; } };
async function openTrace(t) {
  key = t.key;
  if (hashKey() !== key) history.replaceState(null, "", "#" + key);
  $("permalink").href = "#" + key;
  $("detail").hidden = false;
  $("detail-title").textContent = "Execução de " + (t.enviado ? when(t.enviado) : t.key.slice(7, 17).split("/").reverse().join("/") + " (dia UTC)");
  $("groups").replaceChildren();
  $("flow").replaceChildren();
  $("out").hidden = true;
  $("report").hidden = true;
  $("report").srcdoc = "";
  $("print").hidden = true;
  $("agents-out").replaceChildren();
  $("inv-out").replaceChildren();
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
async function listRuns() {
  $("traces").replaceChildren();
  $("detail").hidden = true;
  const days = $("days").value;
  say("Listando...");
  try {
    const j = await (await api("/api/traces?days=" + encodeURIComponent(days))).json();
    runs = j.traces;
    say(runs.length ? (runs.length >= 100 ? "Mostrando as 100 execuções mais recentes." : "") : "Nenhuma execução nos últimos " + days + " dias.");
    for (const t of runs) item($("traces"), when(t.enviado) + " · " + Math.round(t.size / 1024) + " KB", () => openTrace(t));
    return true;
  } catch (e) { say(e.message); return false; }
}
// Opens the run in the address, from the list when it is there (with its time), else by its key alone.
function openFromHash() {
  const h = hashKey();
  if (!h || h === key || h.indexOf("traces/") !== 0) return;
  openTrace(runs.find((t) => t.key === h) || { key: h, enviado: null });
}
$("list").addEventListener("click", async () => { key = null; if (await listRuns()) openFromHash(); });
$("days").addEventListener("change", () => { if (tok()) $("list").click(); });
$("remember").addEventListener("change", (e) => { if (e.target.checked) { if (tok()) keep(tok()); } else forget(); });
$("forget").addEventListener("click", () => {
  forget();
  $("remember").checked = false;
  $("token").value = "";
  say("Código esquecido neste aparelho.");
});
window.addEventListener("hashchange", () => { if (tok()) openFromHash(); });
{
  const saved = recall();
  if (saved) {
    $("token").value = saved;
    $("remember").checked = true;
    $("list").click();
  } else if (hashKey()) {
    say("Informe o código e liste as execuções para abrir a do link.");
  }
}
$("go").addEventListener("click", () => { const t = $("ticker").value.trim(); if (t && key) showExposure(t); });
$("html").addEventListener("click", async () => {
  if (!key) return;
  say("Lendo o relatório...");
  try {
    $("report").srcdoc = await (await api("/api/traces/report?key=" + encodeURIComponent(key))).text();
    $("report").hidden = false;
    $("print").hidden = false;
    say("");
    $("report").scrollIntoView();
  } catch (e) { say(e.message); }
});
$("print").addEventListener("click", () => {
  const frame = $("report");
  frame.contentDocument.querySelectorAll("details").forEach((d) => { d.open = true; });
  frame.contentWindow.print();
});
$("agents").addEventListener("click", async () => {
  if (!key) return;
  say("Lendo os agentes...");
  try {
    showAgents(await (await api("/api/traces/agents?key=" + encodeURIComponent(key))).json());
    say("");
  } catch (e) { say(e.message); }
});
$("inv").addEventListener("click", async () => {
  if (!key) return;
  say("Lendo o investigador...");
  try {
    showInvestigation(await (await api("/api/traces/investigation?key=" + encodeURIComponent(key))).json());
    say("");
  } catch (e) { say(e.message); }
});
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
