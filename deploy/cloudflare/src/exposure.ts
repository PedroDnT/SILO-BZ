// Where one asset's exposure comes from, read off the engine JSON (the owner's PETR4 question).
//
// Pure functions: no Worker types, no I/O. `scripts/trace_view.py exposure` prints the same text
// from the same engine output; tests/test_worker_exposure.py checks that the two agree on the
// synthetic demo. Every number is copied from the engine; nothing is computed here but the
// percentage of a fraction.

interface Line {
	line_no: number;
	linha_extrato: string;
	exposure_brl: number;
	direct?: boolean;
}

interface Group {
	kind?: string;
	label: string;
	total_exposure_brl: number;
	total_exposure_portfolio_pct: number;
	lines?: Line[];
}

interface Exposure {
	asset_key?: string;
	weight_in_line?: number | null;
	period?: string | null;
	depth?: number | null;
}

// The engine document: only the paths this module reads.
export interface EngineDoc {
	statement?: { position_date?: string | null; positions?: { line_no: number; linha_extrato?: string; tipo?: string | null; valor_brl?: number | null }[] };
	look_through?: {
		status?: string | null;
		cda_month?: string | null;
		lines?: { line_no: number; exposures?: Exposure[] }[];
		shared_exposure?: { groups?: Group[]; note?: string | null };
	};
}

export function brl(v: number): string {
	const [int, dec] = Math.abs(v).toFixed(2).split(".");
	const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
	return `R$ ${v < 0 ? "-" : ""}${grouped},${dec}`;
}

export function pct(v: number): string {
	return `${v.toFixed(2).replace(".", ",")}%`;
}

function sharedGroups(doc: EngineDoc): Group[] {
	return (doc.look_through?.shared_exposure?.groups ?? []).filter((g) => g.kind === "mesmo_ativo");
}

// The asset held through more than one statement line, largest first: what the owner picks from.
export function topGroups(doc: EngineDoc, n = 10): { label: string; total_brl: number; portfolio_pct: number; n_lines: number }[] {
	return sharedGroups(doc)
		.sort((a, b) => b.total_exposure_brl - a.total_exposure_brl)
		.slice(0, n)
		.map((g) => ({
			label: g.label,
			total_brl: g.total_exposure_brl,
			portfolio_pct: g.total_exposure_portfolio_pct,
			n_lines: (g.lines ?? []).length,
		}));
}

// The text of one asset, or null when no asset held through several lines matches it.
export function exposureText(doc: EngineDoc, ticker: string): string | null {
	const want = ticker.toUpperCase();
	const lt = doc.look_through ?? {};
	const groups = sharedGroups(doc).filter((g) => g.label.toUpperCase().includes(want));
	if (!groups.length) return null;
	const byLine = new Map((lt.lines ?? []).map((l) => [l.line_no, l]));
	const out: string[] = [];
	for (const g of groups) {
		out.push(`${g.label}: ${brl(g.total_exposure_brl)} = ${pct(g.total_exposure_portfolio_pct)} da carteira`);
		for (const ln of g.lines ?? []) {
			if (ln.direct) {
				out.push(`  direta       ${ln.linha_extrato} (linha ${ln.line_no}): ${brl(ln.exposure_brl)}`);
				continue;
			}
			const ex = (byLine.get(ln.line_no)?.exposures ?? []).find((e) => String(e.asset_key ?? "").toUpperCase() === want);
			const bits: string[] = [];
			if (ex) {
				if (ex.weight_in_line !== null && ex.weight_in_line !== undefined) bits.push(`${pct(ex.weight_in_line * 100)} do valor do fundo`);
				if (ex.period) bits.push(`CDA de ${String(ex.period).slice(0, 7)}`);
				if (ex.depth) bits.push(`nível ${ex.depth}`);
			}
			const detail = bits.length ? `; ${bits.join("; ")}` : "";
			out.push(`  via fundo    ${ln.linha_extrato} (linha ${ln.line_no}): ${brl(ln.exposure_brl)}${detail}`);
		}
	}
	out.push(
		"",
		`Extrato de ${doc.statement?.position_date ?? "?"}; CDA do look-through: ${lt.cda_month ?? "None"}. A parte via fundo é a carteira do fundo naquele mês, não na data do extrato; fundo sem CDA do mês não é aberto (o total é um piso).`,
		lt.shared_exposure?.note ?? "",
	);
	return out.join("\n");
}

// One asset as a flow: each statement line that holds it, with what it puts in. Everything is copied from the
// engine output; the one figure derived here is the CDA's age in whole calendar months (two engine dates).
export interface FlowSource {
	line_no: number;
	nome: string;
	tipo: string | null;
	direto: boolean;
	posicao_brl: number | null;
	exposicao_brl: number;
	peso_no_fundo_pct: number | null;
	cda: string | null;
	cda_idade_meses: number | null;
}

export interface Flow {
	ativo: { label: string; total_brl: number; portfolio_pct: number };
	fontes: FlowSource[];
	cda_mes: string | null;
	extrato_em: string | null;
	nota: string | null;
}

function monthsBetween(position: string | null | undefined, period: string | null | undefined): number | null {
	const a = /^(\d{4})-(\d{2})/.exec(position ?? "");
	const b = /^(\d{4})-(\d{2})/.exec(period ?? "");
	if (!a || !b) return null;
	return (Number(a[1]) - Number(b[1])) * 12 + (Number(a[2]) - Number(b[2]));
}

export function exposureFlows(doc: EngineDoc, ticker: string): Flow[] {
	const want = ticker.toUpperCase();
	const lt = doc.look_through ?? {};
	const positions = new Map((doc.statement?.positions ?? []).map((p) => [p.line_no, p]));
	const byLine = new Map((lt.lines ?? []).map((l) => [l.line_no, l]));
	return sharedGroups(doc)
		.filter((g) => g.label.toUpperCase().includes(want))
		.map((g) => ({
			ativo: { label: g.label, total_brl: g.total_exposure_brl, portfolio_pct: g.total_exposure_portfolio_pct },
			fontes: (g.lines ?? []).map((ln) => {
				const pos = positions.get(ln.line_no);
				const direct = Boolean(ln.direct);
				const ex = direct ? undefined : (byLine.get(ln.line_no)?.exposures ?? []).find((e) => String(e.asset_key ?? "").toUpperCase() === want);
				const w = ex?.weight_in_line;
				return {
					line_no: ln.line_no,
					nome: ln.linha_extrato,
					tipo: pos?.tipo ?? null,
					direto: direct,
					posicao_brl: pos?.valor_brl ?? null,
					exposicao_brl: ln.exposure_brl,
					peso_no_fundo_pct: w === null || w === undefined ? null : w * 100,
					cda: ex?.period ? String(ex.period).slice(0, 7) : null,
					cda_idade_meses: ex?.period ? monthsBetween(doc.statement?.position_date, ex.period) : null,
				};
			}),
			cda_mes: lt.cda_month ?? null,
			extrato_em: doc.statement?.position_date ?? null,
			nota: lt.shared_exposure?.note ?? null,
		}));
}

// The root span's attribute of a trace (OTLP/JSON), as a string.
export function traceRootAttribute(trace: unknown, key: string): string | null {
	const t = trace as { resourceSpans?: { scopeSpans?: { spans?: { attributes?: { key: string; value: Record<string, unknown> }[] }[] }[] }[] };
	const kv = t?.resourceSpans?.[0]?.scopeSpans?.[0]?.spans?.[0]?.attributes?.find((a) => a.key === key);
	const v = kv?.value?.stringValue;
	return typeof v === "string" ? v : null;
}
