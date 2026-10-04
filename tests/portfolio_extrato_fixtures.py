"""Synthetic page texts that mimic the BTG "Extrato da Conta Investimento" layout (no real data).

Everything here is invented: the holder, the account, the CPF, the address, the plan certificates,
the issuers, the codes and the amounts. The pages follow the layout facts the reader is built on
(docs/reference/portfolio/statement-pdf.md, "Extrato da Conta Investimento"), in the shape
``pdftotext -layout`` prints: fixed columns, one output line per baseline.

``extrato_pages(align)`` draws every table the same way, as one renderer would:

* ``"top"``: a cell that wraps keeps its first line on the row's baseline and continues below;
* ``"bottom"``: it ends on the baseline and starts above;
* ``"center"``: it is centred on the row, so a two-line cell prints one line above the numbers and one
  below (the baseline holds neither), and a three-line cell prints its middle line on the baseline.
"""

from __future__ import annotations

from decimal import Decimal

D = Decimal

HOLDER_NAME = "JOANA FICTICIA DE SOUZA"
HOLDER_ACCOUNT = "987654321"
HOLDER_CPF = "111.444.777-35"
ADDRESS = "RUA DAS PALMEIRAS SINTETICAS, 100, AP 12, JARDIM IMAGINARIO, CIDADE MODELO - SP, CEP 04567-890"
ADDRESS_PARTS = ("RUA DAS PALMEIRAS SINTETICAS", "04567-890", "04567890")
CERTS = ("8877665544", "8877665545")
ORIGINALS = (HOLDER_NAME, "JOANA FICTICIA", HOLDER_ACCOUNT, HOLDER_CPF, "11144477735") + ADDRESS_PARTS + CERTS

PERIOD = "Período de 01/09/26 a 30/09/26"
FOOTER = "SAC: 0800-772-2827 / Ouvidoria: 0800-047-4335"


def money(v: Decimal | str) -> str:
    q = D(str(v)).quantize(D("0.01"))
    s = f"{q:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def br(v: Decimal | str, places: int) -> str:
    q = D(str(v)).quantize(D(1).scaleb(-places)) if places else D(str(v)).quantize(D(1))
    s = f"{q:,.{places}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def place(cells: list[tuple[int, str]]) -> str:
    """Text at fixed columns, with at least two spaces between cells (as -layout keeps them)."""
    out = ""
    for x, text in cells:
        if not text:
            continue
        if out and len(out) + 2 > x:
            out += "  "
        else:
            out = out.ljust(x)
        out += text
    return out.rstrip()


def render_row(cells: list[tuple[int, list[str]]], align: str) -> list[str]:
    """One table row whose cells may wrap: each cell is (column, its lines). Returns the printed lines."""
    h = max(len(lines) for _, lines in cells)
    by_y: dict[int, list[tuple[int, str]]] = {}
    for x, lines in cells:
        n = len(lines)
        for j, text in enumerate(lines):
            if align == "top":
                y = 2 * j
            elif align == "bottom":
                y = 2 * (h - n) + 2 * j
            else:
                y = (h - n) + 2 * j
            by_y.setdefault(y, []).append((x, text))
    return [place(sorted(by_y[y])) for y in sorted(by_y)]


# ---------------------------------------------------------------------------
# The portfolio (all invented).
# ---------------------------------------------------------------------------

# Funds: (title lines, cnpj, subclass, ref date, qty, quota, bruto, ir)
FUNDS = [
    (["FUNDO ALFA CREDITO PRIVADO FIC FIRF CP RL"], "11.222.333/0001-81", None, "30/09/26", "10263.80716338", "4.74340124", D("48685.36"), D("2259.05")),
    (["FUNDO BETA ESTRUTURADO MULTIESTRATEGIA", "FICFIDC RESP LIMITADA"], "22.333.444/0001-92", "D50RZ1778084725", "30/09/26", "50000.00000000", "2.10000000", D("105000.00"), D("0")),
    (["FUNDO GAMA RENDA IMOBILIARIA FII"], "33.444.555/0001-03", None, "29/09/26", "1200.00000000", "95.50000000", D("114600.00"), D("0")),
]

# Renda fixa tables: kind -> rows (emissor lines, ativo lines, emissão, vencimento, taxa lines, qty, preço, bruto, ir)
RF = {
    "CRA": [
        (["BOA SAFRA"], ["CRA-CRA02500001"], "15/01/25", "15/01/30", ["15,41% a.a."], "30", "1006.275754", D("30188.27"), D("0")),
        (["BTG PACTUAL COMMODITIES", "SERTRADING S.A."], ["CRA-", "CRA0250005M"], "10/03/25", "10/03/31", ["IPCA + 8,74%"], "50", "1012.500000", D("50625.00"), D("0")),
        (["ARTESANA", "L"], ["CRA-CRA0250009X"], "20/05/25", "20/05/29", ["CDI + 1,80%"], "20", "998.100000", D("19962.00"), D("0")),
    ],
    "CDB": [
        (["OMNI S/A CREDITO", "FINANCIAMENTO E", "INVESTIMENTO"], ["CDB-", "CDB421A6V2", "0"], "02/02/25", "02/02/28", ["112,00% do", "CDI"], "40", "1100.000000", D("44000.00"), D("1200.00")),
    ],
    "NTNB-P": [
        (["BACEN-BANCO CENTRAL DO", "BRASIL - RJ"], ["NTNB-P"], "10/01/24", "15/05/35", ["IPCA + 6,20%"], "12", "2050.123456789", D("24601.48"), D("0")),
    ],
    "LFT": [
        (["BACEN-BANCO CENTRAL DO", "BRASIL - RJ"], ["LFT"], "05/06/23", "01/03/29", ["CDI"], "3", "16500.500000", D("49501.50"), D("0")),
    ],
    "Debênture": [
        (["EMPRESA DELTA ENERGIA S.A."], ["DEB-DLTA11"], "11/11/24", "11/11/31", ["CDI + 1,80%"], "100", "1005.000000", D("100500.00"), D("0")),
    ],
    "CDCA": [
        (["COOPERATIVA EPSILON"], ["CDCA-25E0001"], "01/04/25", "01/04/27", ["105,00% do CDI"], "25", "1010.000000", D("25250.00"), D("300.00")),
    ],
}

# Previdência plans: (cert, wrapper, rows (fund name lines, cnpj, qty, quota, bruto))
PREV = [
    (CERTS[0], "PGBL", [
        (["BTG ALOCACAO GLOBAL CRED PREV FI MULT"], "52.000.111/0001-03", "170068.4674864", "1.326029", D("225515.72")),
        (["BTG PREV RENDA FIXA LONGO PRAZO FIE", "RESP LIMITADA"], "52.000.222/0001-14", "50000.0000000", "2.000000", D("100000.00")),
    ]),
    (CERTS[1], "VGBL", [
        (["BTG PREV EQUILIBRIO FIE"], "52.000.333/0001-25", "1000.0000000", "15.500000", D("15500.00")),
    ]),
]

# Renda variável: kind -> rows (ticker, name lines, qty, close, avg, bruto)
RV = {
    "ETF": [
        ("DEBB11", ["BTG DEB DI FI11"], "1725", "17.20", "14.59", D("29670.00")),
        ("BOVZ11", ["ETF SINTETICO IBOV", "FUNDO DE INDICE"], "100", "120.00", "110.00", D("12000.00")),
    ],
    "Ações": [
        ("ABCD3", ["EMPRESA ALFA ON NM"], "200", "38.50", "30.00", D("7700.00")),
    ],
}
CAIXA = D("776.73")


def fund_total() -> Decimal:
    return sum((f[6] for f in FUNDS), D("0"))


def rf_total() -> Decimal:
    return sum((r[7] for rows in RF.values() for r in rows), D("0"))


def prev_total() -> Decimal:
    return sum((r[4] for _, _, rows in PREV for r in rows), D("0"))


def rv_total() -> Decimal:
    return sum((r[5] for rows in RV.values() for r in rows), D("0"))


def grand_total() -> Decimal:
    return fund_total() + rf_total() + prev_total() + rv_total() + CAIXA


def n_positions() -> int:
    return len(FUNDS) + sum(len(r) for r in RF.values()) + sum(len(r) for _, _, r in PREV) + sum(len(r) for r in RV.values()) + 1


# ---------------------------------------------------------------------------
# Pages.
# ---------------------------------------------------------------------------


def page(body: list[str], with_holder_header: bool = True) -> str:
    head = ["One Investimentos | BTG Pactual" + " " * 60 + "Extrato da Conta Investimento", PERIOD]
    if with_holder_header:
        head.append(f"{HOLDER_NAME}   Conta investimento {HOLDER_ACCOUNT}")
    return "\n".join(head + [""] + body + ["", FOOTER, ""])


def cover() -> str:
    return "\n".join(
        [
            "One Investimentos | BTG Pactual",
            "",
            "Extrato da Conta Investimento",
            "Informações detalhadas sobre investimentos",
            HOLDER_NAME,
            f"Conta investimento {HOLDER_ACCOUNT}",
            f"CPF {HOLDER_CPF}",
            ADDRESS,
            PERIOD,
            "Emitido em 02/10/26 21:19",
        ]
    )


def indice() -> list[str]:
    return ["Índice", "Sumário", "Fundo de Investimento", "Renda fixa", "Previdência Individual", "Renda variável", "Conta corrente"]


def distribuicao() -> list[str]:
    return ["Distribuição da Carteira", "Renda Fixa  38,58%", "Previdência  31,20%", "Fundos de Investimento  22,10%", "Renda Variável  6,00%"]


def sumario() -> list[str]:
    x = [0, 30, 52, 74, 96]
    rows = [
        ("Previdência", prev_total()),
        ("Renda Fixa", rf_total()),
        ("Fundos de Investimento", fund_total()),
        ("Renda Variável", rv_total()),
        ("Conta Corrente", CAIXA),
    ]
    out = [
        "Sumário - Distribuição em 30/09/26",
        place([(0, "Mercados"), (30, "Saldo Bruto R$"), (52, "Saldo Líquido R$"), (74, "Saldo Bruto R$"), (96, "Saldo Líquido R$")]),
        place([(30, "31/08/26"), (52, "31/08/26"), (74, "30/09/26"), (96, "30/09/26")]),
    ]
    for label, v in rows:
        prev = v - D("1000") if label != "Conta Corrente" else D("0")
        out.append(place([(x[0], label), (x[1], money(prev) if prev else "-"), (x[2], money(prev) if prev else "-"), (x[3], money(v)), (x[4], money(v - D("100")))]))
    out.append(place([(x[0], "Total"), (x[1], money(grand_total() - D("4000"))), (x[2], money(grand_total() - D("4000"))), (x[3], money(grand_total())), (x[4], money(grand_total() - D("500")))]))
    return out


FX = [0, 14, 34, 52, 66, 82, 96, 108, 124, 138]


def funds_section() -> list[str]:
    out = [
        "Distribuição - Fundos de Investimento",
        "FUNDO ALFA CREDITO PRIVADO  20,00%",
        "Fundo de Investimento - Posição - Portfólio de fundos",
        place([(0, "Data Referência"), (14, "Saldo Líquido R$"), (34, "Quantidade de Cotas"), (52, "Cotação Atual R$"), (66, "Saldo Bruto R$"), (82, "Provisão de IR R$"), (96, "Provisão de IOF R$"), (114, "Saldo Líquido R$"), (132, "Variação Nominal R$")]),
        place([(14, "31/08/26")]),
    ]
    for title, cnpj, sub, ref, qty, quota, bruto, ir in FUNDS:
        lines = list(title)
        lines[-1] = lines[-1] + f" - Classe CNPJ: {cnpj}" + (f" - Cód. Subclasse: {sub}" if sub else "")
        out += lines
        liq = bruto - ir
        out.append(place(list(zip(FX, [ref, money(bruto - D("2000")) if sub is None else "–", br(qty, 8), br(quota, 8), money(bruto), money(ir) if ir else "–", "–", money(liq), "-" + money(D("12.50")) if sub else money(D("533.83"))]))))
    tb = fund_total()
    ir_t = sum((f[7] for f in FUNDS), D("0"))
    out.append(place([(0, "Total em fundos"), (66, money(tb)), (82, money(ir_t)), (96, "–"), (114, money(tb - ir_t)), (132, money(D("1055.16")))]))
    return out


def fund_ignored_sections() -> list[str]:
    return [
        f"Fundo de Investimento - Detalhamento - FUNDO ALFA CREDITO PRIVADO FIC FIRF CP RL - Classe CNPJ: {FUNDS[0][1]}",
        place([(0, "Data de Aplicação"), (20, "Quantidade de Cotas"), (40, "Valor Aplicado R$"), (60, "Saldo Bruto R$")]),
        place([(0, "10/01/25"), (20, "5.000,00000000"), (40, "20.000,00"), (60, "24.000,00")]),
        place([(0, "10/02/25"), (20, "5.263,80716338"), (40, "21.000,00"), (60, "24.685,36")]),
        "Fundo de Investimento - Movimentação - FUNDO ALFA CREDITO PRIVADO FIC FIRF CP RL",
        place([(0, "15/09/26"), (12, "Aplicação"), (40, "1.000,00")]),
        "Fundo de Investimento - Rentabilidade",
        place([(0, "FUNDO ALFA CREDITO PRIVADO"), (40, "1,05%"), (50, "CDI"), (60, "0,98%")]),
    ]


RX = {"em": 0, "at": 28, "emi": 46, "ven": 56, "liq": 66, "car": 72, "din": 78, "tax": 90, "qtd": 106, "pre": 114, "bru": 132, "ir": 146, "iof": 156, "lq": 162}


def rf_header() -> list[str]:
    return [
        place([(RX["em"], "Emissor"), (RX["at"], "Ativo"), (RX["emi"], "Emissão"), (RX["ven"], "Vencimento"), (RX["liq"], "Liquidez"), (RX["car"], "Dias de"), (RX["din"], "Data inicial"), (RX["tax"], "Taxa Média"), (RX["qtd"], "Quantidade"), (RX["pre"], "Preço R$"), (RX["bru"], "Saldo Bruto R$"), (RX["ir"], "IR R$"), (RX["iof"], "IOF R$"), (RX["lq"], "Saldo Líquido R$")]),
        place([(RX["car"], "carência para"), (RX["din"] + 8, "de liquidez"), (RX["tax"], "Ponderada")]),
        place([(RX["car"], "liquidez")]),
    ]


def rf_table(kind: str, align: str, split_after: int | None = None) -> tuple[list[str], list[str]]:
    """The table, split across two pages after ``split_after`` rows when given (heading and header repeat)."""
    first = [f"Renda fixa - Posição - {kind}"] + rf_header()
    second: list[str] = []
    rows = RF[kind]
    for i, (em, at, emi, ven, taxa, qty, preco, bruto, ir) in enumerate(rows):
        target = first if split_after is None or i < split_after else second
        if split_after is not None and i == split_after:
            second += [f"Renda fixa - Posição - {kind}"] + rf_header()
        cells = [
            (RX["em"], em),
            (RX["at"], at),
            (RX["emi"], [emi]),
            (RX["ven"], [ven]),
            (RX["liq"], ["Não"]),
            (RX["car"], ["-"]),
            (RX["din"], ["-"]),
            (RX["tax"], taxa),
            (RX["qtd"], [br(qty, 1)]),
            (RX["pre"], [br(preco, len(preco.split(".")[1]))]),
            (RX["bru"], [money(bruto)]),
            (RX["ir"], [money(ir) if ir else "-"]),
            (RX["iof"], ["-"]),
            (RX["lq"], [money(bruto - ir)]),
        ]
        target += render_row(cells, align)
    sub = sum((r[7] for r in rows), D("0"))
    ir_t = sum((r[8] for r in rows), D("0"))
    (second or first).append(place([(RX["bru"], money(sub)), (RX["ir"], money(ir_t) if ir_t else "-"), (RX["iof"], "-"), (RX["lq"], money(sub - ir_t))]))
    return first, second


def rf_ignored_sections() -> list[str]:
    return [
        "Renda fixa - Detalhamento - CRA | BTG PACTUAL COMMODITIES SERTRADING S.A.",
        place([(0, "Data Aplicação"), (20, "Quantidade"), (34, "Taxa"), (50, "Valor Aplicado R$")]),
        place([(0, "10/03/25"), (20, "50,0"), (34, "IPCA + 8,74%"), (50, "50.000,00")]),
        "Renda fixa - Movimentação - CRA",
        place([(0, "15/07/26"), (12, "Pagamento de juros"), (40, "BOA SAFRA"), (60, "1.234,56")]),
    ]


def rf_emissor_section() -> list[str]:
    out = ["Renda fixa - Posição Consolidada Por Emissor", place([(0, "Emissor"), (40, "Saldo Bruto R$")])]
    by: dict[str, Decimal] = {}
    for rows in RF.values():
        for em, *_rest in rows:
            name = " ".join(em)
            by[name] = by.get(name, D("0")) + _rest[6]
    for name, v in by.items():
        if len(name) > 30:
            out.append(name[:22])
            out.append(place([(0, name[22:].strip()), (40, money(v))]))
        else:
            out.append(place([(0, name), (40, money(v))]))
    return out


PX = [0, 44, 66, 78, 98, 112]


def prev_sections(align: str) -> list[str]:
    out: list[str] = []
    for cert, wrapper, rows in PREV:
        out += [
            f"Previdência Individual - Plano - {cert}/{wrapper}",
            place([(0, "Certificado"), (20, cert), (40, "Produto"), (60, "BTG PREV SINTETICO"), (90, "SUSEP"), (100, "15414.900000/2020-11")]),
            place([(0, "Início"), (20, "01/02/2020"), (40, "Tipo"), (60, wrapper), (90, "Regime"), (100, "Regressivo")]),
            f"Previdência Individual - Posição - {cert}/{wrapper}",
            place(list(zip(PX, ["Fundo", "CNPJ", "Data Referência", "Quantidade de Cotas", "Cotação Atual R$", "Saldo Bruto R$"]))),
        ]
        for name, cnpj, qty, quota, bruto in rows:
            out += render_row(
                [(PX[0], name), (PX[1], [cnpj]), (PX[2], ["30/09/26"]), (PX[3], [br(qty, 7)]), (PX[4], [br(quota, 6)]), (PX[5], [money(bruto)])],
                align,
            )
        out.append(place([(0, "Total"), (PX[5], money(sum((r[4] for r in rows), D("0"))))]))
    out += [
        "Previdência Individual - Rentabilidade",
        place([(0, f"{CERTS[0]}/PGBL"), (30, "1,10%"), (40, "12,30%")]),
        "Posições abertas por alíquota",
        place([(0, "35%"), (10, "01/02/2020"), (30, "10.000,00")]),
    ]
    return out


VX = [0, 10, 40, 52, 70, 86]


def rv_sections(align: str) -> list[str]:
    out: list[str] = []
    for kind, rows in RV.items():
        out += [f"Renda variável - Posição - {kind}", place(list(zip(VX, ["Código", "Ativo", "Qtde.", "Preço Fechamento R$", "Preço Médio R$", "Saldo Bruto R$"])))]
        for tick, name, qty, close, avg, bruto in rows:
            out += render_row(
                [(VX[0], [tick]), (VX[1], name), (VX[2], [br(qty, 0)]), (VX[3], [br(close, 2)]), (VX[4], [br(avg, 2)]), (VX[5], [money(bruto)])],
                align,
            )
        label = "Total em ETF's R$" if kind == "ETF" else f"Total em {kind} R$"
        out.append(place([(0, label), (VX[5], money(sum((r[5] for r in rows), D("0"))))]))
    return out


def cc_sections() -> list[str]:
    return [
        "Conta corrente - Posição",
        place([(0, "Data"), (20, "Valor financeiro R$")]),
        place([(0, "30/09/26"), (20, money(CAIXA))]),
        "Conta corrente - Movimentação",
        place([(0, "Data"), (12, "Descrição"), (60, "Valor R$")]),
        place([(0, "05/09/26"), (12, f"TED RECEBIDA {HOLDER_NAME}"), (60, "1.000,00")]),
        place([(0, "06/09/26"), (12, "COMPRA CRA BOA SAFRA"), (60, "-30.000,00")]),
    ]


def trailer() -> list[str]:
    return ["Perfil de Risco", "Moderado", "Disclaimers", "Este extrato é informativo. Rentabilidade passada - não garante futura.", "Fale Conosco", "Central 0800 000 0000"]


def extrato_pages(align: str = "top") -> list[str]:
    cra_1, cra_2 = rf_table("CRA", align, split_after=2)
    rf_rest: list[str] = []
    for kind in RF:
        if kind == "CRA":
            continue
        a, b = rf_table(kind, align)
        rf_rest += a + b
    return [
        cover(),
        page(indice()),
        page(distribuicao() + [""] + sumario()),
        page(funds_section() + [""] + fund_ignored_sections()),
        page(cra_1),
        page(cra_2 + [""] + rf_rest),
        page(rf_ignored_sections() + [""] + rf_emissor_section()),
        page(prev_sections(align)),
        page(rv_sections(align) + [""] + cc_sections()),
        page(trailer(), with_holder_header=False),
    ]


def expected_rf() -> list[tuple[str, str | None, Decimal, str]]:
    """(tipo, codigo, valor, taxa) per renda fixa row, in order."""
    return [
        ("CRA", "CRA02500001", D("30188.27"), "15,41% a.a."),
        ("CRA", "CRA0250005M", D("50625.00"), "IPCA + 8,74%"),
        ("CRA", "CRA0250009X", D("19962.00"), "CDI + 1,80%"),
        ("CDB", "CDB421A6V20", D("44000.00"), "112,00% do CDI"),
        ("tesouro", "NTN-B Principal 2035-05-15", D("24601.48"), "IPCA + 6,20%"),
        ("tesouro", "LFT 2029-03-01", D("49501.50"), "CDI"),
        ("debênture", "DLTA11", D("100500.00"), "CDI + 1,80%"),
        ("outro", "25E0001", D("25250.00"), "105,00% do CDI"),
    ]


EXPECTED_EMISSORES = [
    "BOA SAFRA",
    "BTG PACTUAL COMMODITIES SERTRADING S.A.",
    "ARTESANA L",
    "OMNI S/A CREDITO FINANCIAMENTO E INVESTIMENTO",
    "BACEN-BANCO CENTRAL DO BRASIL - RJ",
    "BACEN-BANCO CENTRAL DO BRASIL - RJ",
    "EMPRESA DELTA ENERGIA S.A.",
    "COOPERATIVA EPSILON",
]
