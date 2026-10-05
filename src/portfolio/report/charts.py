"""Static inline SVG charts for the PDF report, built from the report's view (engine 1.8).

Rule zero holds here too: every number a chart prints is ``values.format_value`` of a path in the view, the same text
the table beside it prints. A bar's length is geometry only, and no chart has an axis with ticks of its own, so no
figure on a chart is computed here. Each chart sits next to the table it draws and never replaces it.

A builder returns ``""`` when its data is missing, empty or all zero: no empty chart. The report's "O que não foi
possível avaliar" section says why (``adapt._chart_and_risk_gaps``).

Print-friendly and weasyprint-safe: literal hex colours on each element (no CSS variables, no patterns, no
JavaScript, no external fetch), one sans font, thin bars with a rounded data end, a value label at the tip of every
bar, a hairline baseline. The palette is the dataviz skill's reference instance (light surface), validated with its
``validate_palette.js``: blue for the data, orange outline for a third-party figure, gray for "sem classificação".
"""

from __future__ import annotations

from html import escape
from typing import Any

from src.portfolio.common import REASON_TEXT
from src.portfolio.report.values import format_value, is_number, resolve

FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
BASELINE = "#c3c2b7"
SURFACE = "#ffffff"
SERIES = "#2a78d6"          # categorical slot 1
THIRD_PARTY = "#eb6834"     # categorical slot 2: the ETF fee from a third-party site (outlined, never solid)
THIRD_PARTY_FILL = "#fbe1d6"
UNCLASSIFIED_FILL = "#c3c2b7"
NODE_FILL = "#eef4fc"
NODE_STROKE = "#2a78d6"
ROOT_FILL = "#2a78d6"

WIDTH = 640
FONT_SIZE = 8.5
CHAR_W = 0.6 * FONT_SIZE    # estimated glyph width, for truncating names (the table keeps the full name)
BAR_H = 12
ROW_H = 20
LABEL_W = 210
VALUE_W = 150
RADIUS = 4

FUND_ASSET_TYPES = ("fundo", "fidc", "fii", "fip", "etf", "cota_listada")
TOP_ISSUERS = 8
TOP_FUNDS = 8
TOP_MANAGERS = 8


def _num(view: dict, path: str) -> float | None:
    v = resolve(view, path)
    return float(v) if is_number(v) else None


def truncate(text: Any, max_px: float) -> str:
    s = "" if text is None else str(text)
    n = max(4, int(max_px / CHAR_W))
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _text(x: float, y: float, s: str, *, anchor: str = "start", fill: str = INK_2, weight: str = "normal",
          size: float = FONT_SIZE) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def _bar_path(x: float, y: float, w: float, h: float, r: float = RADIUS) -> str:
    """A horizontal bar, square at the baseline (left) and rounded at the data end (right)."""
    r = min(r, w, h / 2)
    if w <= 0:
        return ""
    return (f"M{x:.1f},{y:.1f} h{w - r:.1f} a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f} v{h - 2 * r:.1f} "
            f"a{r:.1f},{r:.1f} 0 0 1 {-r:.1f},{r:.1f} h{-(w - r):.1f} z")


def _col_path(x: float, base: float, w: float, h: float, r: float = RADIUS) -> str:
    """A vertical column, square at the baseline (bottom) and rounded at the data end (top)."""
    r = min(r, h, w / 2)
    if h <= 0:
        return ""
    return (f"M{x:.1f},{base:.1f} v{-(h - r):.1f} a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{-r:.1f} h{w - 2 * r:.1f} "
            f"a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f} v{h - r:.1f} z")


def _svg(height: float, body: str, label: str, width: int = WIDTH) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="grafico-svg" width="{width}" height="{height:.0f}" '
            f'viewBox="0 0 {width} {height:.0f}" role="img" aria-label="{escape(label)}">{body}</svg>')


def figure(svg: str, caption: str, note: str = "", note_below: bool = False) -> str:
    """The chart and its caption; ``note_below`` puts the note on a line of its own under the caption."""
    if not svg:
        return ""
    tail = ""
    if note:
        tail = f'{"<br>" if note_below else " "}<span class="nota">{escape(note)}</span>'
    return f'<figure class="grafico">{svg}<figcaption>{escape(caption)}{tail}</figcaption></figure>'


def hbars(view: dict, rows: list[dict], label: str, legend: list[tuple[str, str]] | None = None) -> str:
    """Horizontal bars. Each row: ``label``, ``value_path`` (geometry, a number in the view), ``text_paths`` (the
    printed value, formatted from the view) and ``style`` (``series``, ``unclassified`` or ``third_party``).

    Returns ``""`` when no row has a positive value."""
    vals = [_num(view, r["value_path"]) for r in rows]
    if not rows or not any(v and v > 0 for v in vals):
        return ""
    vmax = max(v for v in vals if v is not None and v > 0)
    plot_w = WIDTH - LABEL_W - VALUE_W
    top = 18 if legend else 4
    parts: list[str] = []
    if legend:
        x = LABEL_W
        for style, text in legend:
            fill, stroke = _style(style)
            parts.append(f'<rect x="{x}" y="4" width="10" height="10" rx="2" fill="{fill}"'
                         + (f' stroke="{stroke}" stroke-width="1.5"' if stroke else "") + "/>")
            parts.append(_text(x + 14, 12.5, text))
            x += 14 + len(text) * CHAR_W + 16
    for i, (r, v) in enumerate(zip(rows, vals)):
        y = top + i * ROW_H
        parts.append(_text(LABEL_W - 8, y + BAR_H - 2, truncate(r["label"], LABEL_W - 12), anchor="end", fill=INK))
        w = plot_w * (v / vmax) if v and v > 0 else 0
        fill, stroke = _style(r.get("style", "series"))
        if w > 0:
            parts.append(f'<path d="{_bar_path(LABEL_W, y, max(w, 1.5), BAR_H)}" fill="{fill}"'
                         + (f' stroke="{stroke}" stroke-width="1.5"' if stroke else "") + "/>")
        value_text = " · ".join(format_value(view, p) for p in r["text_paths"])
        if r.get("suffix"):
            value_text += f" {r['suffix']}"
        parts.append(_text(LABEL_W + w + 6, y + BAR_H - 2, value_text, fill=INK_2))
    height = top + len(rows) * ROW_H + 2
    parts.append(f'<line x1="{LABEL_W}" y1="{top - 3}" x2="{LABEL_W}" y2="{height - 4}" stroke="{BASELINE}" stroke-width="1"/>')
    return _svg(height, "".join(parts), label)


def _style(style: str) -> tuple[str, str | None]:
    if style == "unclassified":
        return UNCLASSIFIED_FILL, None
    if style == "third_party":
        return THIRD_PARTY_FILL, THIRD_PARTY
    return SERIES, None


# --- a. allocation -------------------------------------------------------------------------------------------------


def _bucket_rows(view: dict, base: str, label_key: str) -> list[dict]:
    rows = []
    for i, b in enumerate(resolve(view, f"{base}.buckets") or []):
        if not isinstance(b, dict):
            continue
        q = f"{base}.buckets[{i}]"
        rows.append({"label": b.get(label_key), "value_path": f"{q}.weight_pct", "text_paths": [f"{q}.weight_pct"],
                     "style": "unclassified" if b.get(label_key) == "sem classificação" else "series"})
    return rows


def allocation_chart(view: dict) -> str:
    """By asset class (engine ``allocation``), "sem classificação" its own gray bar."""
    if not isinstance(view.get("allocation"), dict):
        return ""
    svg = hbars(view, _bucket_rows(view, "allocation", "asset_class"), "Carteira por classe de ativo, % da carteira")
    return figure(svg, "Carteira por classe de ativo (% da carteira)", "Cinza: sem classificação.")


def indexer_chart(view: dict) -> str:
    """By indexer (engine ``indexer.classes``), "sem classificação" its own gray bar."""
    if not isinstance(view.get("indexer"), dict):
        return ""
    svg = hbars(view, _bucket_rows(view, "indexer", "indexer"), "Carteira por indexador, % da carteira")
    return figure(svg, "Carteira por indexador (% da carteira)", "Cinza: sem classificação.")


# --- b. maturity ladder ----------------------------------------------------------------------------------------------


def maturity_chart(view: dict) -> str:
    """Value maturing per calendar year (``concentration.maturity_ladder.by_year``), as columns; the label on each cap
    is the year's share of the portfolio."""
    base = "concentration.maturity_ladder.by_year"
    years = resolve(view, base)
    if not isinstance(years, list) or not years:
        return ""
    vals = [_num(view, f"{base}[{i}].value_brl") for i in range(len(years))]
    if not any(v and v > 0 for v in vals):
        return ""
    vmax = max(v for v in vals if v and v > 0)
    n = len(years)
    plot_h, top, left = 120, 16, 8
    slot = min(64, (WIDTH - 2 * left) / n)
    col_w = min(24, slot * 0.6)
    base_y = top + plot_h
    parts = []
    for i, v in enumerate(vals):
        cx = left + slot * i + slot / 2
        h = plot_h * (v / vmax) if v and v > 0 else 0
        if h > 0:
            parts.append(f'<path d="{_col_path(cx - col_w / 2, base_y, col_w, max(h, 1.5))}" fill="{SERIES}"/>')
        parts.append(_text(cx, base_y - h - 4, format_value(view, f"{base}[{i}].weight_pct"), anchor="middle"))
        parts.append(_text(cx, base_y + 12, format_value(view, f"{base}[{i}].year"), anchor="middle", fill=INK))
    parts.append(f'<line x1="{left}" y1="{base_y}" x2="{left + slot * n}" y2="{base_y}" stroke="{BASELINE}" stroke-width="1"/>')
    svg = _svg(base_y + 18, "".join(parts), "Vencimentos por ano, % da carteira", width=int(min(WIDTH, left * 2 + slot * n)))
    return figure(svg, "Valor que vence por ano (% da carteira; vencimento impresso no extrato)")


# --- c. concentration -------------------------------------------------------------------------------------------------


def issuer_chart(view: dict) -> str:
    """The largest direct-credit issuers as printed (``concentration.issuer.groups``)."""
    groups = resolve(view, "concentration.issuer.groups")
    if not isinstance(groups, list) or not groups:
        return ""
    rows = [{"label": g.get("issuer"), "value_path": f"concentration.issuer.groups[{i}].weight_pct",
             "text_paths": [f"concentration.issuer.groups[{i}].value_brl", f"concentration.issuer.groups[{i}].weight_pct"]}
            for i, g in enumerate(groups[:TOP_ISSUERS])]
    svg = hbars(view, rows, "Maiores emissores de crédito direto, como impressos no extrato")
    return figure(svg, "Maiores emissores de crédito direto (valor e % da carteira)",
                  "Emissor como impresso no extrato; grupo econômico não avaliado.")


def fund_positions(view: dict) -> list[int]:
    """Indexes into ``lines`` of the largest fund positions, largest first (a selection, no figure)."""
    idx = [i for i, ln in enumerate(view.get("lines") or [])
           if ln.get("asset_type") in FUND_ASSET_TYPES and is_number(ln.get("value_brl")) and ln["value_brl"] > 0]
    return sorted(idx, key=lambda i: -view["lines"][i]["value_brl"])[:TOP_FUNDS]


def fund_chart(view: dict) -> str:
    """The largest positions in funds (FI, FIDC, FII, ETF, listed quotas), from the statement lines."""
    rows = [{"label": view["lines"][i].get("fund_name") or view["lines"][i].get("instrument"),
             "value_path": f"lines[{i}].weight_pct", "text_paths": [f"lines[{i}].value_brl", f"lines[{i}].weight_pct"]}
            for i in fund_positions(view)]
    svg = hbars(view, rows, "Maiores posições em fundos")
    return figure(svg, "Maiores posições em fundos (valor e % da carteira)")


# --- d. look-through ---------------------------------------------------------------------------------------------------


def lookthrough_chart(view: dict) -> str:
    """Portfolio -> funds -> their largest underlying assets, left to right, with the weight at each level.

    Only paths the engine has (``lookthrough.tree``, built by ``adapt``); nothing when there is no look-through."""
    tree = resolve(view, "lookthrough.tree")
    if not isinstance(tree, list) or not tree:
        return ""
    node_h, gap, block_gap = 26, 4, 8
    x_root, w_root = 0, 120
    x_fund, w_fund = 160, 200
    x_leaf, w_leaf = 400, WIDTH - 400
    parts: list[str] = []
    y = 0.0
    fund_mids = []
    for i, f in enumerate(tree):
        kids = f.get("children") or []
        n = max(1, len(kids))
        block_h = n * node_h + (n - 1) * gap
        fy = y + (block_h - node_h) / 2
        q = f"lookthrough.tree[{i}]"
        parts.append(f'<rect x="{x_fund}" y="{fy:.1f}" width="{w_fund}" height="{node_h}" rx="4" fill="{NODE_FILL}" '
                     f'stroke="{NODE_STROKE}" stroke-width="1"/>')
        parts.append(_text(x_fund + 6, fy + 11, truncate(f.get("name"), w_fund - 12), fill=INK, weight="bold", size=7.5))
        parts.append(_text(x_fund + 6, fy + 21, f"{format_value(view, f'{q}.weight_pct')} da carteira", size=7.5))
        fund_mids.append(fy + node_h / 2)
        for j, _k in enumerate(kids):
            ky = y + j * (node_h + gap)
            kq = f"{q}.children[{j}]"
            parts.append(f'<path d="M{x_fund + w_fund},{fy + node_h / 2:.1f} C {x_fund + w_fund + 20},{fy + node_h / 2:.1f} '
                         f'{x_leaf - 20},{ky + node_h / 2:.1f} {x_leaf},{ky + node_h / 2:.1f}" fill="none" '
                         f'stroke="{BASELINE}" stroke-width="1"/>')
            parts.append(f'<rect x="{x_leaf}" y="{ky:.1f}" width="{w_leaf}" height="{node_h}" rx="4" fill="{SURFACE}" '
                         f'stroke="{BASELINE}" stroke-width="1"/>')
            parts.append(_text(x_leaf + 6, ky + 11, truncate(resolve(view, f"{kq}.name"), w_leaf - 12), fill=INK, size=7.5))
            parts.append(_text(x_leaf + 6, ky + 21, f"{format_value(view, f'{kq}.weight_pct')} da carteira", size=7.5))
        y += block_h + block_gap
    height = y - block_gap
    ry = (height - node_h) / 2
    for m in fund_mids:
        parts.append(f'<path d="M{x_root + w_root},{ry + node_h / 2:.1f} C {x_root + w_root + 20},{ry + node_h / 2:.1f} '
                     f'{x_fund - 20},{m:.1f} {x_fund},{m:.1f}" fill="none" stroke="{BASELINE}" stroke-width="1"/>')
    parts.append(f'<rect x="{x_root}" y="{ry:.1f}" width="{w_root}" height="{node_h}" rx="4" fill="{ROOT_FILL}"/>')
    parts.append(_text(x_root + 6, ry + 11, "Carteira", fill=SURFACE, weight="bold", size=7.5))
    parts.append(_text(x_root + 6, ry + 21, format_value(view, "portfolio.total_brl"), fill=SURFACE, size=7.5))
    svg = _svg(height + 2, "".join(parts), "Look-through: carteira, fundos e maiores ativos por baixo")
    return figure(svg, "Look-through: da carteira aos fundos e aos maiores ativos de cada um (% da carteira)",
                  "Só os caminhos que o motor abriu; o peso é o do ativo na carteira inteira.")


# --- d2. where the exposure to one asset comes from (owner's decision Q42 = A, 2026-10-05) ------------------------------

DIRECT_FILL = SERIES
VIA_FILLS = ("#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300")  # categorical slots 3 to 7 of the dataviz reference
ORIGIN_CAVEAT = ("A parte via fundo é a carteira do fundo no mês da CDA, não na data do extrato; fundos sem CDA no mês "
                 "não são abertos, então o total é um piso. Ações ON e PN da mesma companhia (como PETR3 e PETR4) são "
                 "ativos diferentes aqui. Peso no fundo: fração do fundo na CDA, não em %.")
ORIGIN_BAR_H = 14
ORIGIN_TEXT_X = 16
ORIGIN_DETAIL_SIZE = 8


def _seg_path(x: float, y: float, w: float, h: float, round_left: bool, round_right: bool, r: float = RADIUS) -> str:
    """A bar segment: rounded only at the ends of the whole bar, square where it touches its neighbour."""
    r = min(r, w / 2, h / 2)
    rl, rr = (r if round_left else 0.0), (r if round_right else 0.0)
    d = f"M{x + rl:.1f},{y:.1f} H{x + w - rr:.1f} "
    if rr:
        d += f"A{rr:.1f},{rr:.1f} 0 0 1 {x + w:.1f},{y + rr:.1f} "
    d += f"V{y + h - rr:.1f} "
    if rr:
        d += f"A{rr:.1f},{rr:.1f} 0 0 1 {x + w - rr:.1f},{y + h:.1f} "
    d += f"H{x + rl:.1f} "
    if rl:
        d += f"A{rl:.1f},{rl:.1f} 0 0 1 {x:.1f},{y + h - rl:.1f} "
    d += f"V{y + rl:.1f} "
    if rl:
        d += f"A{rl:.1f},{rl:.1f} 0 0 1 {x + rl:.1f},{y:.1f} "
    return d + "Z"


def _positive(v: Any) -> bool:
    return is_number(v) and v > 0


def _origin_detail(view: dict, q: str, seg: dict) -> str:
    """The second line of a via-fund segment: weight inside the fund and the CDA month with its age. Every figure is
    ``format_value`` of the segment's own path; a part the engine did not carry is left out."""
    parts = []
    if is_number(seg.get("weight_in_line")):
        parts.append(f"peso no fundo: {format_value(view, f'{q}.weight_in_line')}")
    elif is_number(seg.get("n_paths")):
        parts.append(f"{format_value(view, f'{q}.n_paths')} caminhos dentro do fundo (peso não somado)")
    if seg.get("cda_month"):
        text = f"CDA de {format_value(view, f'{q}.cda_month')}"
        age = seg.get("cda_age_months")
        if is_number(age):
            if age == 0:
                text += ", no mês do extrato"
            else:
                text += f", {format_value(view, f'{q}.cda_age_months')} {'mês' if age == 1 else 'meses'} antes do extrato"
        parts.append(text)
    return " · ".join(parts)


def exposure_origin_chart(view: dict) -> str:
    """Per asset held through more than one statement line, one stacked bar: the asset's total exposure
    (``total_brl``, ``total_pct``: the engine's) split into one segment per statement line, the direct holding and each
    fund the asset is reached through (``lookthrough.exposure_origin``, built by ``adapt``).

    Under each bar, one row per segment with the line and its R$; a via-fund row adds the asset's weight in that fund
    and the CDA month with its age against the statement. A segment with no positive R$ is never a bar: it is listed
    as text. Nothing when no asset has a positive total (the "Sobreposição" table still lists every group)."""
    groups = resolve(view, "lookthrough.exposure_origin")
    if not isinstance(groups, list) or not any(isinstance(g, dict) and _positive(g.get("total_brl")) for g in groups):
        return ""
    parts: list[str] = []
    summary: list[str] = []
    y = 0.0
    for gi, g in enumerate(groups):
        if not isinstance(g, dict):
            continue
        base = f"lookthrough.exposure_origin[{gi}]"
        segs = g.get("segments") or []
        total_txt = format_value(view, f"{base}.total_brl")
        if is_number(g.get("total_pct")):
            total_txt += f" · {format_value(view, f'{base}.total_pct')} da carteira"
        parts.append(_text(0, y + 9, truncate(g.get("asset"), WIDTH - 12 - len(total_txt) * CHAR_W), fill=INK, weight="bold"))
        parts.append(_text(WIDTH, y + 9, total_txt, anchor="end"))
        summary.append(f"{g.get('asset')}, {total_txt}")
        drawn = [(i, s) for i, s in enumerate(segs) if isinstance(s, dict) and _positive(s.get("value_brl"))]
        bar_y = y + 14
        vsum = sum(s["value_brl"] for _, s in drawn) if _positive(g.get("total_brl")) else 0
        x = 0.0
        via_n = 0
        fills: dict[int, str] = {}
        for k, (i, s) in enumerate(drawn):
            if s.get("direct"):
                fills[i] = DIRECT_FILL
            else:
                fills[i] = VIA_FILLS[via_n % len(VIA_FILLS)]
                via_n += 1
            w = max(WIDTH * s["value_brl"] / vsum, 1.5)
            q = f"{base}.segments[{i}]"
            title = (f"{'direta' if s.get('direct') else 'via'}: {s.get('name')}: {format_value(view, f'{q}.value_brl')}")
            parts.append(f'<path d="{_seg_path(x, bar_y, w, ORIGIN_BAR_H, k == 0, k == len(drawn) - 1)}" fill="{fills[i]}" '
                         f'stroke="{SURFACE}" stroke-width="1"><title>{escape(title)}</title></path>')
            x += w
        ry = bar_y + ORIGIN_BAR_H + 10 if drawn and vsum else y + 14
        if not (drawn and vsum):
            parts.append(_text(0, ry + 9, "Sem exposição positiva a desenhar; ver a tabela de sobreposição.", fill=INK_2))
            ry += 14
        for i, s in enumerate(segs):
            if not isinstance(s, dict):
                continue
            q = f"{base}.segments[{i}]"
            who = ("direta · " if s.get("direct") else "via · ") + truncate(s.get("name"), 380)
            value_txt = format_value(view, f"{q}.value_brl")
            if i in fills:
                parts.append(f'<rect x="0" y="{ry:.1f}" width="10" height="10" rx="2" fill="{fills[i]}"/>')
                parts.append(_text(ORIGIN_TEXT_X, ry + 8.5, who, fill=INK))
                parts.append(_text(WIDTH, ry + 8.5, value_txt, anchor="end", fill=INK))
            else:  # zero, negative or missing: never a bar
                parts.append(_text(ORIGIN_TEXT_X, ry + 8.5, f"{who} (não desenhada: exposição negativa, zero ou ausente)", fill=INK_2))
                parts.append(_text(WIDTH, ry + 8.5, value_txt, anchor="end", fill=INK_2))
            ry += 14
            detail = "" if s.get("direct") else _origin_detail(view, q, s)
            if detail:
                parts.append(_text(ORIGIN_TEXT_X, ry + 4, detail, fill=INK_2, size=ORIGIN_DETAIL_SIZE))
                ry += 12
        y = ry + 12
    height = y - 12
    note = ORIGIN_CAVEAT
    if resolve(view, "lookthrough.economic_group_assessed") is not True and resolve(view, "lookthrough.economic_group_note"):
        note += " " + format_value(view, "lookthrough.economic_group_note")
    if "sem_carteira_cda" in (resolve(view, "sections.lookthrough.reason_codes") or []):
        note += " Neste extrato: " + REASON_TEXT["sem_carteira_cda"] + "."
    svg = _svg(height, "".join(parts),
               "Origem da exposição aos maiores ativos que aparecem em mais de uma linha do extrato: " + "; ".join(summary))
    return figure(svg, "De onde vem a exposição ao mesmo ativo: direta e por cada fundo (valor e % da carteira)", note,
                  note_below=True)


# --- e. fee cost -------------------------------------------------------------------------------------------------------


def fee_chart(view: dict) -> str:
    """R$ a year per fund with a fixed disclosed fee; an ETF's fee from the third-party site is an outlined bar."""
    by_line = resolve(view, "fees.by_line")
    if not isinstance(by_line, list):
        return ""
    idx = [i for i, b in enumerate(by_line) if is_number(b.get("disclosed_brl_year")) and b["disclosed_brl_year"] > 0]
    idx.sort(key=lambda i: -by_line[i]["disclosed_brl_year"])
    rows = []
    kinds = set()
    for i in idx:
        b = by_line[i]
        q = f"fees.by_line[{i}]"
        third = bool(b.get("etf_site_label"))
        kinds.add("third_party" if third else "series")
        rows.append({"label": b.get("fund_name") or b.get("line_id"), "value_path": f"{q}.disclosed_brl_year",
                     "text_paths": [f"{q}.disclosed_brl_year", f"{q}.disclosed_pct_year"],
                     "suffix": "a.a. (site de terceiros)" if third else "a.a.",
                     "style": "third_party" if third else "series"})
    legend = []
    if "series" in kinds:
        legend.append(("series", "taxa divulgada em documento da CVM"))
    if "third_party" in kinds:
        legend.append(("third_party", "ETF: taxa do site etfsbrasil.com.br (terceiros)"))
    svg = hbars(view, rows, "Custo da taxa de administração por fundo, em R$ por ano", legend=legend)
    note = ("Barras cheias: os mesmos fundos e valores da soma divulgada; uma taxa a conferir aparece marcada na tabela. "
            "Faixas e estimativas do balancete não entram no gráfico.")
    if "third_party" in kinds:
        note += (" Barras contornadas: taxa de ETF do site etfsbrasil.com.br (terceiros), somada à parte e fora da soma "
                 "divulgada.")
    return figure(svg, "Taxa de administração por fundo, em R$ por ano (valor da posição x taxa)", note)


# --- f. manager and liquidity (engine 1.9) -----------------------------------------------------------------------------


def manager_chart(view: dict) -> str:
    """Fund value by manager (``concentration.manager.groups``: grouped by the filed ``gestor_id``), the name shown."""
    groups = resolve(view, "concentration.manager.groups")
    if not isinstance(groups, list) or not groups:
        return ""
    base = "concentration.manager.groups"
    rows = [{"label": g.get("gestor_name") or g.get("gestor_id"), "value_path": f"{base}[{i}].weight_pct",
             "text_paths": [f"{base}[{i}].value_brl", f"{base}[{i}].weight_pct"]}
            for i, g in enumerate(groups[:TOP_MANAGERS])]
    svg = hbars(view, rows, "Concentração por gestora, valor e % da carteira")
    return figure(svg, "Concentração por gestora (valor e % da carteira)",
                  "Agrupado pelo identificador da gestora arquivado na CVM, nunca pelo nome.")


def liquidity_chart(view: dict) -> str:
    """The liquidity ladder (``liquidity.buckets``) in the engine's order; "sem classificação" a gray bar of its own."""
    buckets = resolve(view, "liquidity.buckets")
    if not isinstance(buckets, list) or not buckets:
        return ""
    rows = []
    for i, b in enumerate(buckets):
        q = f"liquidity.buckets[{i}]"
        if not (is_number(b.get("value_brl")) and b["value_brl"] > 0):
            continue  # an empty bucket stays in the table only
        rows.append({"label": b.get("bucket"), "value_path": f"{q}.weight_pct", "text_paths": [f"{q}.value_brl", f"{q}.weight_pct"],
                     "style": "unclassified" if b.get("bucket_id") == "sem_classificacao" else "series"})
    svg = hbars(view, rows, "Escada de liquidez, valor e % da carteira")
    return figure(svg, "Escada de liquidez: prazo para resgatar ou vender (valor e % da carteira)",
                  "Prazos de resgate como arquivados; dias úteis e corridos não convertidos. Cinza: sem classificação.")
