"""Static inline SVG charts for the PDF report, built from the report's view (engine 1.8).

Rule zero holds here too: every number a chart prints is ``values.format_value`` of a path in the view, the same text
the table beside it prints. A bar's length is geometry only, and no chart has an axis with ticks of its own, so no
figure on a chart is computed here. Each chart sits next to the table it draws and never replaces it.

A builder returns ``""`` when its data is missing, empty or all zero: no empty chart. The report's "O que não foi
possível avaliar" section says why (``sections.report_gaps``).

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


# --- d2. where the exposure to one asset comes from: an arrow flow diagram (Q42 = A, 2026-10-05; redrawn 2026-10-06) ---
#
# One diagram per asset, left to right: a box per statement line that holds the asset (the line's own name first, then
# "linha N", its type and its position), a ribbon from each box to the asset's box with an arrowhead at the right end,
# and the asset's box (code and ISIN, the engine's total in R$ and as a percent of the portfolio). A ribbon's thickness
# is its line's R$ exposure to the asset, geometry only; the text on it is ``format_value`` of the view paths of
# ``lookthrough.exposure_origin`` (built by ``adapt._exposure_origin``). The percent of the fund is the engine's
# ``weight_in_line`` times 100, taken in the adapter and printed through a ``_pct`` path. Plain SVG, no library: weasyprint
# has no JavaScript, and the engine image installs only ``deploy/cloudflare/engine/requirements.txt``.

DIRECT_FILL = SERIES
# categorical slots 3 to 7 of the dataviz reference, and a sixth (sienna) so six lines reached through funds (the cap)
# never share a colour
VIA_FILLS = ("#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300", "#a0522d")
ORIGIN_CAVEAT = ("A parte via fundo é a carteira do fundo no mês da CDA, não na data do extrato; fundos sem CDA no mês "
                 "não são abertos, então o total é um piso. Ações ON e PN da mesma companhia (como PETR3 e PETR4) são "
                 "ativos diferentes aqui. A espessura da seta é proporcional ao valor da linha (com um mínimo para as "
                 "pequenas); o % do fundo é o peso do ativo na carteira do fundo na CDA.")
ORIGIN_NAME_SIZE = FONT_SIZE      # box name, asset code
ORIGIN_SMALL_SIZE = 7.5           # the module's smallest size: box detail line, tag
ORIGIN_LABEL_SIZE = 8             # the text on an arrow
ORIGIN_LEFT_W = 205
ORIGIN_RIGHT_W = 124
ORIGIN_BOX_H = 36                 # two text lines and room
ORIGIN_ARROW_L = 9
ORIGIN_CURVE_W = 95               # horizontal run of the S-curve; the flat part before it carries the label
ORIGIN_T_MAX = 22                 # thickness of the largest ribbon
ORIGIN_T_MIN = 3                  # a tiny slice stays visible
ORIGIN_LINE_H = 10.5
ORIGIN_ROW_GAP = 10
ORIGIN_WRAP_CHAR_W = 0.55         # estimated glyph width (em) for wrapping the arrow label (measured 0.53 on the render)
ORIGIN_BOLD_CAPS_W = 0.7          # estimated glyph width (em) of a bold upper-case name, the widest a box name gets


def _positive(v: Any) -> bool:
    return is_number(v) and v > 0


def _tint(hex_colour: str, k: float = 0.6) -> str:
    """The colour mixed with white (``k`` of white), a literal hex: a ribbon is lighter than its box stripe."""
    c = [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(v * (1 - k) + 255 * k):02x}" for v in c)


def _fit(text: Any, max_px: float, size: float, char_em: float = 0.6) -> str:
    """``truncate`` for a text of another size than the module's base one (``char_em``: estimated glyph width in em)."""
    s = "" if text is None else str(text)
    n = max(4, int(max_px / (char_em * size)))
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _wrap(text: str, max_px: float, size: float) -> list[str]:
    """Greedy word wrap on an estimated glyph width; a single word longer than the line is kept whole."""
    per_line = max(8, int(max_px / (ORIGIN_WRAP_CHAR_W * size)))
    lines: list[str] = []
    cur = ""
    for word in text.replace("R$ ", "R$\0").split(" "):  # never break between "R$" and its number
        if cur and len(cur) + 1 + len(word) > per_line:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return [ln.replace("\0", " ") for ln in (lines + [cur] if cur else lines)]


def _cda_text(view: dict, q: str, seg: dict) -> str:
    """"CDA 05/2026 (4 meses antes do extrato)": the CDA month and its age against the statement; "" when the engine
    carried no month."""
    if not seg.get("cda_month"):
        return ""
    text = f"CDA {format_value(view, f'{q}.cda_month')}"
    age = seg.get("cda_age_months")
    if is_number(age):
        if age == 0:
            text += " (no mês do extrato)"
        else:
            text += f" ({format_value(view, f'{q}.cda_age_months')} {'mês' if age == 1 else 'meses'} antes do extrato)"
    return text


def _arrow_label(view: dict, q: str, seg: dict) -> list[str]:
    """The text on an arrow, as lines. Direct: "direta: R$ x". Via a fund: "via fundo: 16,59% do fundo = R$ x", then
    the CDA month and its age; a fund that holds the asset by several paths says so instead of a weight (weights are
    not summed)."""
    value = format_value(view, f"{q}.value_brl")
    if seg.get("direct"):
        return [f"direta: {value}"]
    if is_number(seg.get("weight_in_line_pct")):
        pct = seg["weight_in_line_pct"]
        # two decimals would print a real, tiny weight as "0,00%": say it is below the precision instead
        pct_txt = "menos de 0,01%" if 0 < pct < 0.005 else format_value(view, f"{q}.weight_in_line_pct")
        lines = [f"via fundo: {pct_txt} do fundo = {value}"]
    elif is_number(seg.get("n_paths")):
        lines = [f"via fundo: {value}",
                 f"{format_value(view, f'{q}.n_paths')} caminhos dentro do fundo (peso não somado)"]
    else:
        lines = [f"via fundo: {value}"]
    cda = _cda_text(view, q, seg)
    return lines + [cda] if cda else lines


def _box_name(seg: dict) -> str:
    name = seg.get("name")
    return str(name) if name else f"linha {seg.get('line_no')}"


def _box_detail(view: dict, q: str, seg: dict, max_px: float | None = None) -> str:
    """"linha 3 · fundo · posição R$ 264.615,00": the statement's own type and position value; a part the statement
    did not carry is left out. With ``max_px`` only the type is shortened (then dropped), never the number: a cut
    amount would read as another amount."""
    head = f"linha {format_value(view, f'{q}.line_no')}" if is_number(seg.get("line_no")) else "linha"
    tail = f"posição {format_value(view, f'{q}.position_brl')}" if is_number(seg.get("position_brl")) else ""
    tipo = str(seg["tipo"]) if seg.get("tipo") else ""

    def join(t: str) -> str:
        return " · ".join(x for x in (head, t, tail) if x)

    if max_px is None or len(join(tipo)) * 0.6 * ORIGIN_SMALL_SIZE <= max_px:
        return join(tipo)
    room = int(max_px / (0.6 * ORIGIN_SMALL_SIZE)) - len(join("")) - 3
    return join(tipo[: room - 1].rstrip() + "…" if tipo and room >= 4 else "")


def _asset_lines(label: Any) -> list[str]:
    """The group label ``<asset_key> (<isin>)`` on two lines; any other label on one."""
    text = "" if label is None else str(label)
    if text.endswith(")") and " (" in text:
        i = text.rindex(" (")
        return [text[:i], text[i + 1:]]
    return [text]


def _origin_diagram(view: dict, gi: int, g: dict) -> str:
    """One asset's diagram, or "" when it has no positive total or no line with a positive exposure to draw."""
    base = f"lookthrough.exposure_origin[{gi}]"
    segs = [(i, s) for i, s in enumerate(g.get("segments") or []) if isinstance(s, dict)]
    drawn = sorted(((i, s) for i, s in segs if _positive(s.get("value_brl")) and not s.get("hidden")),
                   key=lambda t: -t[1]["value_brl"])
    if not _positive(g.get("total_brl")) or not drawn:
        return ""
    unseen = [(i, s) for i, s in segs if not _positive(s.get("value_brl"))]
    overflow = g.get("overflow") if isinstance(g.get("overflow"), dict) else None
    vmax = drawn[0][1]["value_brl"]
    x0 = ORIGIN_LEFT_W
    xe = WIDTH - ORIGIN_RIGHT_W - ORIGIN_ARROW_L
    xa = xe - ORIGIN_CURVE_W
    xm = (xa + xe) / 2
    label_w = xa - x0 - 8

    # rows: the label above the flat part of the ribbon, the box centred on the ribbon
    rows = []
    top = 0.0
    via_n = 0
    for i, s in drawn:
        q = f"{base}.segments[{i}]"
        colour = DIRECT_FILL if s.get("direct") else VIA_FILLS[via_n % len(VIA_FILLS)]
        via_n += 0 if s.get("direct") else 1
        t = max(ORIGIN_T_MIN, ORIGIN_T_MAX * s["value_brl"] / vmax)
        label = [ln for raw in _arrow_label(view, q, s) for ln in _wrap(raw, label_w, ORIGIN_LABEL_SIZE)]
        band_top = top + max(len(label) * ORIGIN_LINE_H + 3, ORIGIN_BOX_H / 2 - t / 2)
        cy = band_top + t / 2
        bottom = max(band_top + t, cy + ORIGIN_BOX_H / 2) + ORIGIN_ROW_GAP
        rows.append({"i": i, "q": q, "s": s, "colour": colour, "t": t, "label": label, "band_top": band_top, "cy": cy})
        top = bottom
    left_h = top - ORIGIN_ROW_GAP

    # the asset's box: one arrival slot per ribbon, an arrowhead wider than the ribbon
    slots = [max(r["t"] + 6, 10) + 3 for r in rows]
    asset = _asset_lines(g.get("asset"))
    total_txt = format_value(view, f"{base}.total_brl")
    pct_txt = f"{format_value(view, f'{base}.total_pct')} da carteira" if is_number(g.get("total_pct")) else ""
    n_text = len(asset) + 1 + (1 if pct_txt else 0)
    right_h = max(sum(slots) + 6, n_text * ORIGIN_LINE_H + 14)
    h = max(left_h, right_h)
    left_off, right_off = (h - left_h) / 2, (h - right_h) / 2
    slot_y = right_off + (right_h - sum(slots)) / 2

    parts: list[str] = []
    for r, slot in zip(rows, slots):
        s, q, t, colour = r["s"], r["q"], r["t"], r["colour"]
        cy = r["cy"] + left_off
        ye = slot_y + slot / 2
        slot_y += slot
        yt, yb, yet, yeb = cy - t / 2, cy + t / 2, ye - t / 2, ye + t / 2
        title = f"{_box_name(s)}: " + " · ".join(r["label"])
        parts.append(f'<g><title>{escape(title)}</title>')
        parts.append(f'<path d="M{x0},{yt:.2f} H{xa:.1f} C{xm:.1f},{yt:.2f} {xm:.1f},{yet:.2f} {xe:.1f},{yet:.2f} '
                     f'V{yeb:.2f} C{xm:.1f},{yeb:.2f} {xm:.1f},{yb:.2f} {xa:.1f},{yb:.2f} H{x0} Z" '
                     f'fill="{_tint(colour)}" stroke="{colour}" stroke-width="0.6" class="ribbon"/>')
        hb = max(t + 6, 10)
        parts.append(f'<path d="M{xe:.1f},{ye - hb / 2:.1f} L{xe + ORIGIN_ARROW_L},{ye:.1f} L{xe:.1f},{ye + hb / 2:.1f} Z" '
                     f'fill="{colour}" class="arrowhead"/>')
        for k, line in enumerate(r["label"]):
            ly = r["band_top"] + left_off - 3 - (len(r["label"]) - 1 - k) * ORIGIN_LINE_H
            parts.append(_text(x0 + 8, ly, line, fill=INK, size=ORIGIN_LABEL_SIZE))
        # the statement line's box: name first, then line number, type and position; a tag says direct or via a fund
        by = cy - ORIGIN_BOX_H / 2
        tag = "direta" if s.get("direct") else "via fundo"
        tag_w = len(tag) * ORIGIN_SMALL_SIZE * 0.6 + 10
        parts.append(f'<rect x="0.5" y="{by:.1f}" width="{ORIGIN_LEFT_W - 1}" height="{ORIGIN_BOX_H}" rx="4" '
                     f'fill="{SURFACE}" stroke="{BASELINE}" stroke-width="1" class="line-box"/>')
        parts.append(f'<rect x="1.5" y="{by + 1:.1f}" width="4" height="{ORIGIN_BOX_H - 2}" rx="2" fill="{colour}"/>')
        parts.append(_text(12, by + 14, _fit(_box_name(s), ORIGIN_LEFT_W - 12 - tag_w - 12, ORIGIN_NAME_SIZE, ORIGIN_BOLD_CAPS_W), fill=INK,
                           weight="bold", size=ORIGIN_NAME_SIZE))
        parts.append(f'<rect x="{ORIGIN_LEFT_W - 6 - tag_w:.1f}" y="{by + 5:.1f}" width="{tag_w:.1f}" height="13" rx="6.5" '
                     f'fill="{_tint(colour, 0.8)}" stroke="{colour}" stroke-width="0.6"/>')
        parts.append(_text(ORIGIN_LEFT_W - 6 - tag_w / 2, by + 14.2, tag, anchor="middle", fill=INK, size=ORIGIN_SMALL_SIZE))
        parts.append(_text(12, by + 28, _box_detail(view, q, s, ORIGIN_LEFT_W - 12 - 8), size=ORIGIN_SMALL_SIZE))
        parts.append("</g>")
    bx = WIDTH - ORIGIN_RIGHT_W
    parts.append(f'<rect x="{bx}" y="{right_off:.1f}" width="{ORIGIN_RIGHT_W - 0.5}" height="{right_h:.1f}" rx="4" '
                 f'fill="{NODE_FILL}" stroke="{NODE_STROKE}" stroke-width="1" class="asset-box"/>')
    ty = right_off + (right_h - n_text * ORIGIN_LINE_H) / 2 + 8
    for k, line in enumerate(asset):
        parts.append(_text(bx + 8, ty, _fit(line, ORIGIN_RIGHT_W - 14, ORIGIN_NAME_SIZE, ORIGIN_BOLD_CAPS_W if k == 0 else 0.6), fill=INK,
                           weight="bold" if k == 0 else "normal",
                           size=ORIGIN_NAME_SIZE))
        ty += ORIGIN_LINE_H
    parts.append(_text(bx + 8, ty, total_txt, fill=INK, weight="bold", size=ORIGIN_NAME_SIZE))
    ty += ORIGIN_LINE_H
    if pct_txt:
        parts.append(_text(bx + 8, ty, pct_txt, size=ORIGIN_LABEL_SIZE))

    # lines that are not drawn: no positive R$ (zero, negative or missing), and the smaller ones past the cap
    texts_below: list[str] = []
    for i, s in unseen:
        q = f"{base}.segments[{i}]"
        tail = f", {_box_detail(view, q, s).split(' · ')[0]}: {format_value(view, f'{q}.value_brl')}"
        head = "Não desenhada (exposição zero, negativa ou ausente): "
        name_px = WIDTH - (len(head) + len(tail)) * 0.6 * ORIGIN_LABEL_SIZE
        texts_below.append(head + _fit(_box_name(s), name_px, ORIGIN_LABEL_SIZE) + tail)
    if overflow and is_number(overflow.get("n_lines")):
        texts_below.append(f"+{format_value(view, f'{base}.overflow.n_lines')} linhas menores: "
                           f"{format_value(view, f'{base}.overflow.value_brl')} (não desenhadas)")
    for k, text in enumerate(texts_below):
        parts.append(_text(0, h + 14 + k * (ORIGIN_LINE_H + 2), text, size=ORIGIN_LABEL_SIZE))
    height = h + 2 if not texts_below else h + 14 + (len(texts_below) - 1) * (ORIGIN_LINE_H + 2) + 4
    shown = [f"{_box_name(s)}, {'direta' if s.get('direct') else 'via fundo'}, "
             f"{format_value(view, f'{base}.segments[{i}].value_brl')}" for i, s in drawn]
    label = (f"Origem da exposição a {g.get('asset')}: total {total_txt}"
             + (f", {pct_txt}" if pct_txt else "") + ". Linhas: " + "; ".join(shown))
    body = f"<title>{escape(label)}</title>" + "".join(parts)
    return _svg(height, body, label)


def exposure_origin_chart(view: dict) -> str:
    """Per asset held through more than one statement line, an arrow flow diagram of where its exposure comes from:
    a box per statement line (name, line number, type, position), a ribbon to the asset's box whose thickness is the
    line's R$ exposure, and the asset's box with the engine's total and portfolio percent
    (``lookthrough.exposure_origin``, built by ``adapt``). One figure per asset, each with the same fixed caveat under it.

    A line with no positive R$ is never a ribbon: it is listed as text under the diagram, and so is the rest of a
    group past the cap of lines. Nothing when no asset has a positive total (the "Sobreposição" table still lists every
    group)."""
    groups = resolve(view, "lookthrough.exposure_origin")
    if not isinstance(groups, list):
        return ""
    note = ORIGIN_CAVEAT
    if resolve(view, "lookthrough.economic_group_assessed") is not True and resolve(view, "lookthrough.economic_group_note"):
        note += " " + format_value(view, "lookthrough.economic_group_note")
    if "sem_carteira_cda" in (resolve(view, "sections.lookthrough.reason_codes") or []):
        note += " Neste extrato: " + REASON_TEXT["sem_carteira_cda"] + "."
    figures = []
    for gi, g in enumerate(groups):
        svg = _origin_diagram(view, gi, g) if isinstance(g, dict) else ""
        if svg:
            figures.append(figure(svg, f"De onde vem a exposição a {g.get('asset')}: uma seta por linha do extrato "
                                       "(valor da linha e % da carteira do ativo)", note, note_below=True))
    return "".join(figures)


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
