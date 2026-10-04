// First safe Cloudflare deploy for map #510 (issue #519).
//
// GET /health            answered by the Worker itself, public, no container.
// GET /container/health  needs the shared token; starts (or reuses) the one
//                        Container and returns what its own /health answers.
// Anything else          404.
//
// No engine, no upload, no LLM key, nothing logged. The token is compared as a
// SHA-256 digest with timingSafeEqual, and the container never sees it: the
// Worker sends it a fresh request with no headers from the caller.
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
	HEALTH_CONTAINER: DurableObjectNamespace<HealthContainer>;
	DEMO_ACCESS_TOKEN?: string;
}

export class HealthContainer extends Container<Env> {
	defaultPort = 8080;
	// Short idle window: memory and disk are billed while the instance is up.
	sleepAfter = "60s";
	// The health image needs no network of its own.
	enableInternet = false;
	pingEndpoint = "localhost/health";

	// The default hooks log; this one logs nothing and lets the Worker answer 503.
	override onError(error: unknown): never {
		throw error;
	}
}

const TOKEN_HEADER = "x-demo-token";

function text(status: number, body: string): Response {
	return new Response(body, {
		status,
		headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
	});
}

async function digest(value: string): Promise<ArrayBuffer> {
	return crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
}

async function tokenMatches(given: string | null, expected: string): Promise<boolean> {
	if (!given) return false;
	const [a, b] = await Promise.all([digest(given), digest(expected)]);
	return crypto.subtle.timingSafeEqual(a, b);
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const { pathname } = new URL(request.url);
		if (request.method !== "GET" && request.method !== "HEAD") {
			return text(404, "not found\n");
		}

		if (pathname === "/health") {
			return text(200, "ok\n");
		}

		if (pathname === "/container/health") {
			// Fail closed: without the secret nothing is started.
			if (!env.DEMO_ACCESS_TOKEN) return text(503, "not configured\n");
			if (!(await tokenMatches(request.headers.get(TOKEN_HEADER), env.DEMO_ACCESS_TOKEN))) {
				return text(401, "unauthorized\n");
			}
			try {
				const container = getContainer(env.HEALTH_CONTAINER, "health");
				const res = await container.fetch(new Request("http://container/health"));
				await res.body?.cancel();
				return text(res.ok ? 200 : 502, res.ok ? "container ok\n" : "container unhealthy\n");
			} catch {
				return text(503, "container unavailable\n");
			}
		}

		return text(404, "not found\n");
	},
} satisfies ExportedHandler<Env>;
