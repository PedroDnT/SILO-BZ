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

FUND_ASSET_TYPES = ("fundo", "fidc", "fii", "etf", "cota_listada")
TOP_ISSUERS = 8
TOP_FUNDS = 8


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


def figure(svg: str, caption: str, note: str = "") -> str:
    if not svg:
        return ""
    tail = f'<span class="nota"> {escape(note)}</span>' if note else ""
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
