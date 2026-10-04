// The portfolio-diagnosis demo on Cloudflare (map #510, slice E step 2).
//
// GET  /          the upload page (Portuguese, token field, downloads the PDF)
// GET  /health    answered by the Worker itself, public, no container
// POST /diagnose  needs the shared token; starts a fresh engine Container for
//                 this upload alone, forwards the statement with
//                 `Authorization: Bearer`, returns the PDF, then stops it
// Anything else   404
//
// Clients send the token as `x-demo-token` (the scheme of the first deploy) or
// as `Authorization: Bearer`. It is compared as a SHA-256 digest with
// timingSafeEqual. Nothing is logged: no console call, invocation logs off in
// wrangler.jsonc, and the Container's onError is silenced. Bodies are never
// read except to forward them, and never stored (no KV, R2, D1, no DO storage
// of our own).
import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";

// The outbound allow-list runs through ContainerProxy, which must be exported.
export { ContainerProxy };

interface Env {
	ENGINE: DurableObjectNamespace<HealthContainer>;
	DEMO_ACCESS_TOKEN?: string;
	OPENAI_API_KEY?: string;
	SILO_LLM_PROVIDER?: string;
	SILO_LLM_MODEL?: string;
	SILO_LLM_EFFORT?: string;
	// "allowlist" (default): only the hosts below. "open": internet on.
	EGRESS?: string;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const TOKEN_HEADER = "x-demo-token";
// silo-mcp (and PostgREST) on Supabase, and the LLM provider. Nothing else.
const EGRESS_ALLOWED = ["zcjbtpxuhdekpwcxmepn.supabase.co", "api.openai.com"];
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
	"x-silo-engine-rev",
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
	// The answer is in hand: stop the instance now, which frees the slot and
	// discards its disk.
	ctx.waitUntil(container.stop().catch(() => undefined));
	const headers = new Headers({ "cache-control": "no-store", "x-silo-origin": "engine" });
	for (const name of PASS_HEADERS) {
		const v = res.headers.get(name);
		if (v) headers.set(name, v);
	}
	return new Response(out, { status: res.status, headers });
}

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
<p>Envie o extrato (planilha modelo .xlsx ou relatório de performance do BTG em PDF, até 10 MB). O arquivo é processado em memória e não é guardado. O relatório leva alguns minutos.</p>
<form id="f">
<label for="token">Código de acesso</label>
<input id="token" type="password" autocomplete="off" required>
<label for="file">Extrato</label>
<input id="file" type="file" accept=".xlsx,.pdf" required>
<button id="go" type="submit">Gerar diagnóstico</button>
</form>
<div id="status" role="status" aria-live="polite"></div>
</main>
<script>
const f = document.getElementById("f"), go = document.getElementById("go"), st = document.getElementById("status");
f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = document.getElementById("file").files[0];
  const token = document.getElementById("token").value;
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { st.textContent = "Arquivo grande demais: o limite é 10 MB."; return; }
  go.disabled = true;
  st.textContent = "Gerando o diagnóstico. Isso leva alguns minutos; mantenha esta página aberta.";
  try {
    const r = await fetch("/diagnose", { method: "POST", headers: { "x-demo-token": token, "content-type": "application/octet-stream" }, body: file });
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
