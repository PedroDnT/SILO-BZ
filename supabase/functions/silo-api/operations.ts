// Public operation names map to the existing resource contract, never to SQL.
import definitions from "./operations.json" with { type: "json" };
import { ApiError } from "./errors.ts";
import type { Envelope } from "./envelope.ts";

export const OPERATIONS = definitions;
export const OPERATIONS_BY_PATH = new Map(OPERATIONS.map((o) => [o.path, o]));
export type Operation = typeof OPERATIONS[number];

export function operationQuery(operation: Operation, input: URLSearchParams): URLSearchParams {
  const query = new URLSearchParams();
  for (const [key, value] of input) {
    if (input.getAll(key).length !== 1) throw new ApiError(400, "bad_request", `Send ${key} only once.`, key);
    if (key === "details") {
      if (value !== "true" && value !== "false") throw new ApiError(400, "bad_request", "details must be true or false.", key);
      continue;
    }
    const parameter = operation.parameters.find((p) => p.name === key);
    if (!parameter) throw new ApiError(400, "unknown_parameter", `Unknown parameter ${key} for ${operation.path}.`, key);
    query.set(parameter.target, value);
  }
  // panel has no kind parameter in the legacy contract.
  if (operation.resource !== "panel") query.set("kind", operation.kind);
  return query;
}

export function operationBody(operation: Operation, text: string): string {
  let body: unknown;
  try { body = JSON.parse(text); } catch { throw new ApiError(400, "bad_request", "Send a JSON object.", "body"); }
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new ApiError(400, "bad_request", "Send a JSON object.", "body");
  const mapped: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(body)) {
    const parameter = operation.body.find((p) => p.name === key);
    if (!parameter) throw new ApiError(400, "unknown_parameter", `Unknown body field ${key}.`, key);
    mapped[parameter.target] = value;
  }
  // Stable serialization keeps POST cursor digests independent of JSON formatting.
  return JSON.stringify(Object.fromEntries(Object.entries(mapped).sort(([a], [b]) => a.localeCompare(b))));
}

export function operationResponse(body: Envelope, details: boolean): Envelope {
  if (details) return body;
  const meta = { ...body.meta };
  // Keep interpretation, provenance, warnings and tier limits. Only routing/debug
  // fields are omitted; new safety metadata remains visible by default.
  for (const key of ["resource", "kind", "request", "endpoint", "id_known"]) delete meta[key];
  return { ...body, meta } as Envelope;
}
