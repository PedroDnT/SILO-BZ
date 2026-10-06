// What the agents did in one run, read off the stored trace (OTLP/JSON) and the engine JSON: the owner's
// view of the Redator, the Revisor and the investigator.
//
// Pure functions: no Worker types, no I/O. Every figure is copied from the trace or the engine output; the
// only derived values are durations (two span times) and sums of costs the trace already holds. A trace
// carries no prompt, document or fact text (src/portfolio/trace.py); the investigator's facts come from the
// engine JSON, where they already carry their quote, their source and their tier.

type Attr = { key: string; value: Record<string, unknown> };
interface Span {
	name: string;
	startTimeUnixNano: string;
	endTimeUnixNano: string;
	attributes?: Attr[];
	events?: { name: string; attributes?: Attr[] }[];
	status?: { code?: number };
}
export type TraceDoc = { resourceSpans?: { scopeSpans?: { spans?: Span[] }[] }[] };

function val(a: Attr | undefined): string | number | boolean | null {
	const v = a?.value;
	if (!v) return null;
	if (typeof v.stringValue === "string") return v.stringValue;
	if (typeof v.intValue === "string" || typeof v.intValue === "number") return Number(v.intValue);
	if (typeof v.doubleValue === "number") return v.doubleValue;
	if (typeof v.boolValue === "boolean") return v.boolValue;
	return null;
}

function get(attrs: Attr[] | undefined, key: string): string | number | boolean | null {
	return val(attrs?.find((a) => a.key === key));
}

function num(attrs: Attr[] | undefined, key: string): number | null {
	const v = get(attrs, key);
	return typeof v === "number" ? v : null;
}

function str(attrs: Attr[] | undefined, key: string): string | null {
	const v = get(attrs, key);
	return v === null ? null : String(v);
}

function secondsBetween(from: string, to: string): number {
	try {
		return Number(BigInt(to) - BigInt(from)) / 1e9;
	} catch {
		return 0;
	}
}

export interface AgentRow {
	nome: string;
	inicio_s: number;
	duracao_s: number;
	estado: string;
	modelo: string | null;
	chamadas: number | null;
	tokens_entrada: number | null;
	tokens_saida: number | null;
	tokens_raciocinio: number | null;
	buscas_exa: number | null;
	custo_usd: number | null;
	removidos: { secao: string | null; regra: string | null; inteiro: boolean }[];
	notas: string[];
}

export interface Timeline {
	total_s: number;
	http: number | null;
	etapa_que_falhou: string | null;
	tipo_do_erro: string | null;
	custo_usd: number | null;
	revisao_do_motor: string | null;
	esquema: string | null;
	linhas: AgentRow[];
}

// The spans of a trace as rows, in start order: the run, the engine, the investigator and the report's agents.
export function agentTimeline(trace: unknown): Timeline | null {
	const spans = (trace as TraceDoc)?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans;
	if (!spans?.length) return null;
	const root = spans[0];
	const t0 = root.startTimeUnixNano;
	const rows: AgentRow[] = spans.map((s) => {
		const a = s.attributes;
		const notas: string[] = [];
		if (s.name === "engine.run") {
			// How many sections ended in each status: the names stay in the engine JSON.
			const counts: Record<string, number> = {};
			for (const kv of a ?? []) {
				if (/^app\.section\..+\.status$/.test(kv.key)) {
					const st = String(val(kv));
					counts[st] = (counts[st] ?? 0) + 1;
				}
			}
			const parts = Object.entries(counts).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${v} ${k}`);
			if (parts.length) notas.push(`seções: ${parts.join(", ")}`);
			const lines = num(a, "app.statement.n_lines");
			if (lines !== null) notas.push(`${lines} linhas no extrato`);
		}
		if (s.name === "invoke_agent redator") {
			const n = str(a, "app.narrative.status");
			if (n) notas.push(`narrativa: ${n}${str(a, "app.narrative.reason_code") ? ` (${str(a, "app.narrative.reason_code")})` : ""}`);
			const kept = num(a, "app.findings.kept");
			if (kept !== null) notas.push(`${kept} achados mantidos`);
		}
		const removidos = (s.events ?? [])
			.filter((e) => e.name === "app.revisor.removed")
			.map((e) => ({
				secao: str(e.attributes, "app.finding.section"),
				regra: str(e.attributes, "app.revisor.rule"),
				inteiro: get(e.attributes, "app.finding.whole") === true,
			}));
		const code = s.status?.code;
		return {
			nome: s.name,
			inicio_s: secondsBetween(t0, s.startTimeUnixNano),
			duracao_s: secondsBetween(s.startTimeUnixNano, s.endTimeUnixNano),
			estado: code === 1 ? "ok" : code === 2 ? "erro" : "sem estado",
			modelo: str(a, "gen_ai.response.model") ?? str(a, "gen_ai.request.model"),
			chamadas: num(a, "app.llm.calls"),
			tokens_entrada: num(a, "gen_ai.usage.input_tokens"),
			tokens_saida: num(a, "gen_ai.usage.output_tokens"),
			tokens_raciocinio: num(a, "app.llm.reasoning_tokens"),
			buscas_exa: num(a, "app.exa.calls"),
			custo_usd: num(a, "app.cost_usd"),
			removidos,
			notas,
		};
	});
	const ra = root.attributes;
	return {
		total_s: secondsBetween(root.startTimeUnixNano, root.endTimeUnixNano),
		http: num(ra, "app.http.status"),
		etapa_que_falhou: str(ra, "app.failed_stage"),
		tipo_do_erro: str(ra, "error.type"),
		custo_usd: num(ra, "app.cost_usd"),
		revisao_do_motor: str(ra, "app.engine.rev"),
		esquema: str(ra, "app.engine.schema_version"),
		linhas: rows.sort((x, y) => x.inicio_s - y.inicio_s),
	};
}

// --- the investigator, from the engine JSON (`investigation`, engine 1.12) ---------------------------------

interface Fact {
	fact_id?: string;
	trigger_id?: string;
	line_no?: number;
	field_label?: string;
	subject?: string | null;
	value?: string;
	quote?: string;
	url?: string;
	document_title?: string | null;
	document_date?: string | null;
	read_date?: string | null;
	source_type_label?: string;
	tier?: string;
	tier_label?: string;
	cross_check?: { agrees?: boolean | null; note?: string | null; silo_value?: string | null } | null;
}

interface Trigger {
	trigger_id?: string;
	line_no?: number;
	kind_label?: string;
	identifiers?: Record<string, unknown>;
	sources_tried?: unknown[];
	searches_used?: number;
	message?: string;
}

interface Doc {
	title?: string | null;
	url?: string | null;
	source_type?: string;
	status?: string;
	cache?: string;
	n_chars?: number | null;
}

export interface InvestigationDoc {
	investigation?: {
		status?: string;
		reason?: string | null;
		enabled?: boolean;
		searches_used?: number;
		limits?: { searches_per_report?: number };
		costs?: { usd?: number; llm_usd?: number; exa_usd?: number; share_cap_usd?: number };
		counts?: Record<string, number>;
		web_search?: { available?: boolean; note?: string | null };
		models?: { extractor?: string | null; judge?: string | null };
		messages?: string[];
		triggers?: Trigger[];
		facts?: Fact[];
		documents_consulted?: Doc[];
		discarded?: { count?: number; text?: string };
		note?: string | null;
	};
	statement?: { positions?: { line_no: number; linha_extrato?: string }[] };
}

export interface InvestigationView {
	ligado: boolean;
	estado: string | null;
	motivo: string | null;
	buscas: { usadas: number; limite: number | null };
	custo: { total_usd: number | null; llm_usd: number | null; exa_usd: number | null; teto_do_investigador_usd: number | null };
	busca_na_web: { disponivel: boolean | null; nota: string | null };
	modelos: { extrator: string | null; juiz: string | null };
	contagens: Record<string, number>;
	descartados: string | null;
	gatilhos: { linha: number | null; nome_da_linha: string | null; tipo: string | null; identificadores: string; fontes_tentadas: number; buscas: number | null; mensagem: string | null }[];
	fatos: {
		linha: number | null;
		campo: string | null;
		assunto: string | null;
		valor: string | null;
		citacao: string | null;
		nivel: string | null;
		nivel_rotulo: string | null;
		documento: string | null;
		data_do_documento: string | null;
		url: string | null;
		fonte: string | null;
		confere: string | null;
	}[];
	documentos: { titulo: string | null; url: string | null; fonte: string | null; estado: string | null; cache: string | null }[];
	nota: string | null;
}

function idsText(ids: Record<string, unknown> | undefined): string {
	return Object.entries(ids ?? {})
		.filter(([, v]) => typeof v === "string" || typeof v === "number")
		.map(([k, v]) => `${k}: ${v}`)
		.join("; ");
}

// What the investigator did and found, or null when the engine JSON has no investigation section.
export function investigationView(doc: InvestigationDoc): InvestigationView | null {
	const inv = doc.investigation;
	if (!inv) return null;
	const names = new Map((doc.statement?.positions ?? []).map((p) => [p.line_no, p.linha_extrato ?? null]));
	const confere = (f: Fact): string | null => {
		const c = f.cross_check;
		if (!c) return null;
		if (c.agrees === true) return "confere com o registro do SILO";
		if (c.agrees === false) return `diverge do registro do SILO${c.silo_value ? ` (${c.silo_value})` : ""}`;
		return c.note ?? "sem comparação possível";
	};
	return {
		ligado: inv.enabled === true,
		estado: inv.status ?? null,
		motivo: inv.reason ?? null,
		buscas: { usadas: inv.searches_used ?? 0, limite: inv.limits?.searches_per_report ?? null },
		custo: {
			total_usd: inv.costs?.usd ?? null,
			llm_usd: inv.costs?.llm_usd ?? null,
			exa_usd: inv.costs?.exa_usd ?? null,
			teto_do_investigador_usd: inv.costs?.share_cap_usd ?? null,
		},
		busca_na_web: { disponivel: inv.web_search?.available ?? null, nota: inv.web_search?.note ?? null },
		modelos: { extrator: inv.models?.extractor ?? null, juiz: inv.models?.judge ?? null },
		contagens: inv.counts ?? {},
		descartados: inv.discarded?.count ? (inv.discarded.text ?? `${inv.discarded.count} fatos descartados`) : null,
		gatilhos: (inv.triggers ?? []).map((t) => ({
			linha: t.line_no ?? null,
			nome_da_linha: t.line_no !== undefined ? (names.get(t.line_no) ?? null) : null,
			tipo: t.kind_label ?? null,
			identificadores: idsText(t.identifiers),
			fontes_tentadas: (t.sources_tried ?? []).length,
			buscas: t.searches_used ?? null,
			mensagem: t.message ?? null,
		})),
		fatos: (inv.facts ?? []).map((f) => ({
			linha: f.line_no ?? null,
			campo: f.field_label ?? null,
			assunto: f.subject ?? null,
			valor: f.value ?? null,
			citacao: f.quote ?? null,
			nivel: f.tier ?? null,
			nivel_rotulo: f.tier_label ?? null,
			documento: f.document_title ?? null,
			data_do_documento: f.document_date ?? null,
			url: f.url ?? null,
			fonte: f.source_type_label ?? null,
			confere: confere(f),
		})),
		documentos: (inv.documents_consulted ?? []).map((d) => ({
			titulo: d.title ?? null,
			url: d.url ?? null,
			fonte: d.source_type ?? null,
			estado: d.status ?? null,
			cache: d.cache ?? null,
		})),
		nota: inv.note ?? null,
	};
}
