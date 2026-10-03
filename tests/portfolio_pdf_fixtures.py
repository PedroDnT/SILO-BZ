"""Synthetic page texts that mimic the BTG performance report layout (no real data).

Everything here is invented: the holder, the account, the issuers and the amounts. The two
variants follow the layout facts the reader is built on (docs/reference/portfolio/statement-pdf.md):

* ``variant_a_pages``: portrait, one month. Page 2 summary with 'Patrimônio bruto' and the
  'Distribuição por classe de ativos' table (with a 'Conta corrente' line), then the two-column
  'Posição consolidada dos investimentos' (left 'Renda Fixa', right 'Fundo de Investimento' then
  'Renda Variável'), then 'Detalhamento dos Ativos' and the sections that follow.
* ``variant_b_pages``: landscape, long period. Page 2 is an 'Evolução do saldo' roll-forward
  (no 'Patrimônio bruto', no distribution table) and the consolidated position starts at the
  bottom of a page and continues on the next.

The text layer's stray spaces next to the letter 't' ('At ivo', 'Tot al', 'Fundo de Invest iment o')
are reproduced in headings and labels, and the footer 'Página N de M' is wrong on purpose.
"""

from __future__ import annotations

from decimal import Decimal

HOLDER_NAME = "MARIA SINTETICA DA SILVA"
HOLDER_ACCOUNT = "0012345"
HOLDER_CPF = "321.654.987-91"
ORIGINALS = (HOLDER_NAME, "MARIA", "SINTETICA", HOLDER_ACCOUNT, HOLDER_CPF, "32165498791")

D = Decimal
LEFT_W = 86  # the right column starts here


def money(v: Decimal | float | str) -> str:
    q = D(str(v)).quantize(D("0.01"))
    s = f"{q:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: Decimal | float | str) -> str:
    return f"{D(str(v)):.2f}".replace(".", ",") + "%"


def heading(label: str, valor: Decimal | None = None, p: str | None = None, w: int = 80) -> str:
    if valor is None:
        return label
    return label.ljust(w - 26) + money(valor).rjust(16) + (p or "").rjust(10)


def row(label: str, valor: Decimal, p: str, w: int = 80) -> str:
    return label.ljust(w - 26) + money(valor).rjust(16) + p.rjust(10)


def two_col(left: list[str], right: list[str]) -> list[str]:
    n = max(len(left), len(right))
    left = left + [""] * (n - len(left))
    right = right + [""] * (n - len(right))
    return [(a.ljust(LEFT_W) + b).rstrip() for a, b in zip(left, right)]


# ---------------------------------------------------------------------------
# The portfolio (all invented). Position names exactly as the layout would print them.
# ---------------------------------------------------------------------------
# (class, strategy, name lines (the last carries the numbers), valor)
POSITIONS = [
    ("Renda Fixa", "Pós-fixado", ["BANCO EXEMPLO S.A. - CDB-CDB421A6V20"], D("250000.00")),
    ("Renda Fixa", "Pós-fixado", ["BACEN-BANCO CENTRAL DO BRASIL - RJ - LFT"], D("350000.00")),
    ("Renda Fixa", "Inflação", ["BACEN-BANCO CENTRAL DO BRASIL - RJ - NTNB"], D("500000.00")),
    ("Renda Fixa", "Inflação", ["EMPRESA ZETA AGRO S.A. - CRA-", "CRA0250001*"], D("400000.00")),  # prefix wrap
    ("Renda Fixa", "Pré-fixado", ["DEB-CUTI11*"], D("100000.00")),
    ("Renda Fixa", "Pré-fixado", ["CRI-24I1980390*"], D("200000.00")),
    ("Fundo de Investimento", "Pós-fixado", ["FUNDO ALFA RF CRED PRIV FIC FIRF"], D("350000.00")),
    ("Fundo de Investimento", "Pós-fixado", ["FUNDO BETA CASH FIC", "RESP LIMITADA*"], D("250000.00")),  # tail wrap
    ("Renda Variável", "Renda Variável", ["PETR4"], D("300000.00")),
    ("Renda Variável", "Renda Variável", ["HGLG11*"], D("150000.00")),
]
CAIXA = D("150000.00")
# detail table: name -> (data inicial, quantidade, vencimento, taxa, preco)
DETAIL = {
    "BANCO EXEMPLO S.A. - CDB-CDB421A6V20": ("10/01/2024", "250,00", "15/03/2027", "105,00% do CDI"),
    "BACEN-BANCO CENTRAL DO BRASIL - RJ - LFT": ("02/02/2023", "30,00", "01/03/2029", "SELIC + 0,0500%"),
    "BACEN-BANCO CENTRAL DO BRASIL - RJ - NTNB": ("05/05/2022", "120,50", "15/05/2035", "IPCA + 6,20%"),
    "EMPRESA ZETA AGRO S.A. - CRA-CRA0250001*": ("20/06/2023", "400,00", "20/06/2030", "IPCA + 7,00%"),
    "DEB-CUTI11*": ("11/11/2024", "100,00", "11/11/2031", "11,87% a.a."),
    "CRI-24I1980390*": ("03/03/2024", "200,00", "03/03/2033", "CDI + 1,80%"),
    "FUNDO ALFA RF CRED PRIV FIC FIRF": ("01/08/2021", "175.000,000000", "-", "-"),
    "FUNDO BETA CASH FIC RESP LIMITADA*": ("01/09/2022", "200.000,000000", "-", "-"),
}
RV_DETAIL = {"PETR4": ("6.000,00", "50,00", "45,00"), "HGLG11*": ("1.000,00", "150,00", "140,00")}

TOTAL_LEAVES = sum((p[3] for p in POSITIONS), D("0"))
BRUTO = TOTAL_LEAVES + CAIXA
PF = D("1200000.00")  # both 'Pós-fixado' strategies


def _sub(cls: str, strat: str | None = None) -> Decimal:
    return sum((p[3] for p in POSITIONS if p[0] == cls and (strat is None or p[1] == strat)), D("0"))


def _pct(v: Decimal) -> str:
    return pct(v / BRUTO * 100)


def _full(names: list[str]) -> str:
    out = names[0]
    for n in names[1:]:
        out += ("" if out.endswith("-") else " ") + n
    return out


def _consolidated_lines_a() -> list[str]:
    left = [heading("Renda Fixa", _sub("Renda Fixa"), _pct(_sub("Renda Fixa"))), "Posição bruta                  % total"]
    for strat in ("Pós-fixado", "Inflação", "Pré-fixado"):
        left.append(heading(strat, _sub("Renda Fixa", strat), _pct(_sub("Renda Fixa", strat))))
        for c, s, names, v in POSITIONS:
            if c == "Renda Fixa" and s == strat:
                left.extend(names[:-1])
                left.append(row(names[-1], v, _pct(v)))
    right = [heading("Fundo de Invest iment o", _sub("Fundo de Investimento"), _pct(_sub("Fundo de Investimento"))), "Posição bruta                  % total"]
    right.append(heading("Pós-fixado", _sub("Fundo de Investimento", "Pós-fixado"), _pct(_sub("Fundo de Investimento", "Pós-fixado"))))
    right.append(row("FUNDO ALFA RF CRED PRIV FIC FIRF", D("350000.00"), _pct(D("350000.00"))))
    right.append(row("FUNDO BETA CASH FIC", D("250000.00"), _pct(D("250000.00"))))
    right.append("RESP LIMITADA*")  # tail of the name, below the numbers
    right.append(heading("Renda Variável", _sub("Renda Variável"), _pct(_sub("Renda Variável"))))
    right.append(heading("Renda Variável", _sub("Renda Variável", "Renda Variável"), _pct(_sub("Renda Variável", "Renda Variável"))))
    right.append(row("PETR4", D("300000.00"), _pct(D("300000.00"))))
    right.append(row("HGLG11*", D("150000.00"), _pct(D("150000.00"))))
    lines = two_col(left, right)
    lines.append(heading("Tot al", TOTAL_LEAVES))
    return lines


def _detail_lines() -> list[str]:
    hdr = ["At ivo", "Data Inicial", "Quant idade", "Resgate", "Vencimento", "Taxa", "Saldo bruto", "Preço médio", "Saldo líquido", "Valor aplicado", "Defasagem", "Projeção"]
    lines = ["Detalhamento dos Ativos"]

    def cells(*vals: str) -> str:
        return "  ".join(vals)

    for strat, classes in (("Pós-fixado", None), ("Inflação", None), ("Pré-fixado", None)):
        group = [p for p in POSITIONS if p[0] == "Renda Fixa" and p[1] == strat]
        if not group:
            continue
        lines += [strat, cells(*hdr)]
        for c, s, names, v in group:
            full = _full(names)
            d = DETAIL[full]
            lines.extend(names[:-1])
            lines.append(cells(names[-1], d[0], d[1], "-", d[2], d[3], money(v), "1.000,00", money(v - D("1000")), money(v - D("5000")), "-", "-"))
    lines += ["Fundo de Investimento", "Pós-fixado", cells(*hdr)]
    for c, s, names, v in POSITIONS:
        if c == "Fundo de Investimento":
            full = _full(names)
            d = DETAIL[full]
            lines.append(cells(full if len(names) == 1 else names[0], d[0], d[1], "-", d[2], d[3], money(v), "1,50", money(v - D("500")), money(v - D("9000")), "-", "-"))
    lines += ["Renda Variável", cells("At ivo", "Quant idade", "Saldo bruto", "Preço", "Preço médio", "Valor aplicado")]
    for c, s, names, v in POSITIONS:
        if c == "Renda Variável":
            q, pr, pm = RV_DETAIL[names[0]]
            lines.append(cells(names[0], q, money(v), pr, pm, money(v - D("10000"))))
    return lines


def variant_a_pages() -> list[str]:
    cover = [
        "BTG Pactual                         Relatório de Performance",
        "",
        f"Nome                    {HOLDER_NAME}",
        f"Conta Investimento      {HOLDER_ACCOUNT}",
        "Assessor                 Assessoria Exemplo",
        "Emitido em 16/01/2026",
    ]
    p2 = [
        "Relatório de Performance",
        "Período de 01/12/2025 a 31/12/2025",
        "",
        "Resumo",
        f"Patrimônio bruto            R$ {money(BRUTO)}",
        f"Patrimônio líquido          R$ {money(BRUTO - D('50000'))}",
        "",
        "Distribuição por classe de ativos",
        "Estratégia                  %             Valor financeiro",
        f"Pós-fixado               {_pct(PF)}    {money(PF)}",
        f"Inflação                 {_pct(_sub('Renda Fixa', 'Inflação'))}    {money(_sub('Renda Fixa', 'Inflação'))}",
        f"Pré-fixado               {_pct(_sub('Renda Fixa', 'Pré-fixado'))}    {money(_sub('Renda Fixa', 'Pré-fixado'))}",
        f"Renda Variável           {_pct(_sub('Renda Variável'))}    {money(_sub('Renda Variável'))}",
        f"Conta corrente           {_pct(CAIXA)}    {money(CAIXA)}",
        f"Tot al                   100,00%    {money(BRUTO)}",
        "",
        "Página 2 de 7",
    ]
    p3 = (
        ["Relatório de Performance", "", "Posição consolidada dos investimentos", ""]
        + _consolidated_lines_a()
        + ["", "Página 3 de 7"]
    )
    p4 = ["Relatório de Performance", ""] + _detail_lines() + ["", "Página 4 de 7"]
    p5 = [
        "Relatório de Performance",
        "A rentabilidade completa",
        "NOME DE FUNDO QUALQUER | IPCA + 7,00% | 2045     1,22%   10,10%   12,00%   30,00%",
        "Movimentações da conta",
        "Data        Descrição         Valor",
        "05/12/2025  Crédito           1.000,00",
        "Página 5 de 7",
    ]
    return ["\n".join(p) for p in (cover, p2, p3, p4, p5)]


def variant_b_pages() -> list[str]:
    cover = [
        "BTG Pactual                    Relatório de Performance",
        f"Nome   {HOLDER_NAME}",
        f"Conta Investimento   {HOLDER_ACCOUNT}",
    ]
    p2 = [
        "Relatório de Performance",
        "Período de 01/03/2019 a 31/12/2025",
        "Evolução do saldo",
        f"Saldo Bruto Anterior          {money(BRUTO - D('300000'))}",
        "Rendimento                    50.000,00",
        "Entrada                      300.000,00",
        "Saída                        -50.000,00",
        "Impostos                      -5.000,00",
        f"Saldo Bruto                   {money(BRUTO)}",
        "Impostos Provisionados         10.000,00",
        f"Valor Líquido                 {money(BRUTO - D('10000'))}",
        "",
        "Resumo do saldo",
        f"Conta corrente                {money(CAIXA)}",
        "Página 2 de 3",
    ]
    p3 = ["Rentabilidade mensal", "Jan/2025  1,02%   Fev/2025  0,90%"]
    lines = _consolidated_lines_a()
    # split the consolidated position across two pages: the first strategy block on page 4, the rest on page 5
    cut = 6
    p4 = ["Relatório de Performance", "Informações gerais", "", "Posição consolidada dos investimentos", ""] + lines[:cut]
    p5 = ["Relatório de Performance"] + lines[cut:] + ["Página 5 de 3"]
    p6 = ["Relatório de Performance"] + _detail_lines()
    return ["\n".join(p) for p in (cover, p2, p3, p4, p5, p6)]


def expected_leaves() -> list[tuple[str, str, str, Decimal]]:
    return [(c, s, _full(n), v) for c, s, n, v in POSITIONS]
