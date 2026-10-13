// djen-relay — fetches DJEN (CNJ's Diário de Justiça Eletrônico Nacional) from
// São Paulo for the RJ collector (#846, epic #841).
//
// DJEN answers HTTP 403 to any egress outside Brazil (#843), GitHub runners
// included. Invoked with the header `x-region: sa-east-1`, this function runs
// in Supabase's São Paulo region, where DJEN answers 200. It is not an open
// relay:
//   - it needs the shared token DJEN_RELAY_TOKEN (header x-relay-token); with
//     no token configured it refuses everything;
//   - it forwards GET to one endpoint, /api/v1/comunicacao, with an allowlist
//     of query parameters;
//   - it returns DJEN's status, content type and body unchanged, so the caller
//     sees exactly what DJEN said, a non-200 included.
// The caller (src/fetchers/rj/djen.py) keeps the rate at 1 request a second.
//
//   supabase functions deploy djen-relay --project-ref zcjbtpxuhdekpwcxmepn --no-verify-jwt

const UPSTREAM = "https://comunicaapi.pje.jus.br/api/v1/comunicacao";
const USER_AGENT = "SILO-BZ RJ collector (+https://github.com/PedroDnT/SILO-BZ)";
const ALLOWED = new Set([
  "siglaTribunal", "dataDisponibilizacaoInicio", "dataDisponibilizacaoFim",
  "texto", "pagina", "itensPorPagina", "numeroProcesso",
]);

function refuse(status: number, message: string): Response {
  return new Response(JSON.stringify({ error: message }), {
    status, headers: { "content-type": "application/json" },
  });
}

function sameToken(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function handle(req: Request, token = (Deno.env.get("DJEN_RELAY_TOKEN") ?? "").trim()): Promise<Response> {
  if (!token) return refuse(503, "relay not configured: DJEN_RELAY_TOKEN is unset");
  // Trimmed on both sides: a secret pasted with a trailing newline is the same secret.
  const given = (req.headers.get("x-relay-token") ?? "").trim();
  if (!sameToken(given, token)) {
    console.warn(`token mismatch: received ${given.length} chars, expected ${token.length}`); // lengths only
    return refuse(401, "bad or missing x-relay-token");
  }
  if (req.method !== "GET") return refuse(405, "GET only");
  const out = new URLSearchParams();
  for (const [k, v] of new URL(req.url).searchParams) {
    if (!ALLOWED.has(k)) return refuse(400, `parameter not allowed: ${k}`);
    out.append(k, v);
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${UPSTREAM}?${out}`, {
      headers: { "user-agent": USER_AGENT, accept: "application/json" },
    });
  } catch (e) {
    return refuse(502, `DJEN unreachable from the relay: ${e}`);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "x-relay-region": Deno.env.get("SB_REGION") ?? "unknown",
    },
  });
}

if (import.meta.main) Deno.serve((req) => handle(req));
