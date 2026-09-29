"""SECURIT keeps every row CVM files, with its securitizer — issues #349, #350.

upsert_rows dedupes rows that share a conflict key, last write wins, with no
error. The SECURIT keys were coarser than the files: cvm_securit_dfin kept one
filing per year of each type, and mensal and serie dropped rows that shared a
month and an issue value, or a series number. CNPJ_Emissora, the CRA/CRI
securitizer column, was never a candidate, so cnpj_securit was NULL on every
CRA/CRI row. The fixtures carry CVM's real headers (2026 files) and real rows.
"""

import random
import re
from pathlib import Path

import pytest

from src.parsers.field_maps import securit_dfin as _dfin
from src.parsers.field_maps import securit_mensal as _mensal
from src.parsers.field_maps import securit_serie as _serie
from src.parsers.mapping import FieldMapMismatch

ROOT = Path(__file__).resolve().parents[1]

CRA_MENSAL_HEADER = (
    "CNPJ_Emissora;Codigo_Identificacao_Certificado;Data_Referencia;Versao;Ativo;"
    "Direitos_Creditorios;Creditos_A_Vencer_Sem_Parcelas_Atraso;"
    "Creditos_A_Vencer_Com_Parcelas_Atraso;Creditos_Vencidos;Reducao_Valor_Recuperacao;"
    "Caixa_Equivalentes;Caixa_Titulos_Publicos_Federais;Caixa_Cotas_Fundos;"
    "Caixa_Operacoes_Compromissadas;Caixa_Outros;Ativo_Derivativos;Ativo_Contratos_Termo;"
    "Ativo_Futuros;Ativo_Opcoes;Ativo_Swap;Outros_Ativos;Passivo;Passivo_Derivativos;"
    "Passivo_Contratos_Termo;Passivo_Futuros;Passivo_Opcoes;Passivo_Swap;"
    "Valor_Atualizado_Emissao;Reducao_Valor_Emissao;Outros_Passivos;"
    "Companhia_Securitizadora_Emissora"
)
# OTS names the securitizer CNPJ_Securitizadora and has no trailing name column.
OTS_MENSAL_HEADER = CRA_MENSAL_HEADER.replace(
    "CNPJ_Emissora", "CNPJ_Securitizadora"
).replace(";Companhia_Securitizadora_Emissora", "")
CRI_CLASSE_HEADER = (
    "CNPJ_Emissora;Codigo_Identificacao_Certificado;Data_Referencia;Versao;Classe;"
    "Numero_Serie;Tipo_Oferta;Codigo_CETIP;Codigo_ISIN;Quantidade;Valor;Data_Vencimento;"
    "Taxas_Indexadores;Situacao;Total_Integralizado;Taxa_Juros;Pagamento_Periodicidade;"
    "Pagamento_Mes_Base;Quantidade_Certificados;Valor_Certificados;Rendimentos;"
    "Amortizacoes;Rentabilidade;Classificacao_Risco_Atual;Nivel_Subordinacao;"
    "Periodicidade_Amortizacao;Indice_Subordinacao_Minimo;Indice_Subordinacao_Data_Base"
)
DFIN_HEADER = (
    "CNPJ_Emissora;Nome_Emissora;Data_Referencia;Versao;Data_Entrega;Nome_Certificado;"
    "Codigo_Identificacao_Certificado;Link_Download;Parecer_Auditor"
)


def _row(header, **values):
    """One CSV row as CVMFetcher yields it: every header column, as text."""
    row = {col: "0.00" for col in header.split(";")}
    row.update(values)
    return row


# Real, inf_mensal_cra_ativo_passivo_2026.csv: two certificates of one
# securitizer, same month, same updated issue value. The old key (no
# certificate, NULL CNPJ, month, vl_emissao) stored one of them.
CRA_TWINS = [
    _row(CRA_MENSAL_HEADER, CNPJ_Emissora="02.773.542/0001-22",
         Codigo_Identificacao_Certificado=cert, Data_Referencia="2026-01-01", Versao="1",
         Ativo="229828263.63", Valor_Atualizado_Emissao="229577657.62",
         Companhia_Securitizadora_Emissora="OPEA SECURITIZADORA S.A.")
    for cert in ("BRAPCSCRA0M6", "BRAPCSCRA0N4")
]

# Real, inf_mensal_ots_ativo_passivo_2026.csv: ONE certificate-month filed
# twice with different values. No column tells them apart.
OTS_PAIR = [
    _row(OTS_MENSAL_HEADER, CNPJ_Securitizadora="38.042.694/0001-00",
         Codigo_Identificacao_Certificado="BRPCHSDBS131", Data_Referencia="2026-03-31",
         Versao="1", Ativo=ativo, Valor_Atualizado_Emissao=emissao)
    for ativo, emissao in (("1310149686.28", "1307676002.16"),
                           ("1626124050.89", "1630849431.59"))
]


def _classe(classe, valor, isin="BRPVSCCRI487", cetip="", serie="1", **extra):
    return _row(CRI_CLASSE_HEADER, CNPJ_Emissora="04.200.649/0001-07",
                Codigo_Identificacao_Certificado="BRPVSCCRI487", Data_Referencia="2026-01-01",
                Versao="1", Classe=classe, Numero_Serie=serie, Codigo_ISIN=isin,
                Codigo_CETIP=cetip, Valor_Certificados=valor, Situacao="Adimplente",
                Data_Vencimento="2027-05-31", **extra)


# Real, inf_mensal_cri_classe_2026.csv: series 1 carries a senior AND a
# subordinated class. The old key had no Classe and kept one of them.
CRI_CLASSES = [_classe("Sênior", "16510677.04"), _classe("Subordinada", "4966934.15")]

# Shaped on BRAPCSCRIK26 2026-03 (series 1, Sênior, three different rows):
# nothing in the row separates them, so each gets its own occurrence.
CRI_SAME_SERIES = [
    _classe("Sênior", "0.00"),
    _classe("Sênior", "25506706.26", Quantidade_Certificados="25000.00"),
    _classe("Sênior", "0.00", cetip="23I1698252", Total_Integralizado="25000000.00"),
]

DFIN_FILINGS = [
    _row(DFIN_HEADER, CNPJ_Emissora="02.773.542/0001-22", Nome_Emissora="OPEA SECURITIZADORA S.A.",
         Data_Referencia="2026-03-31", Versao="1", Data_Entrega="2026-07-08",
         Codigo_Identificacao_Certificado=cert, Nome_Certificado=f"OPEA CRI {cert}",
         Link_Download="https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=1",
         Parecer_Auditor="Sem ressalva e com ênfase")
    for cert in ("BRAPCSCRIEZ9", "BRAPCSCRIEO3", "BRAPCSCRIES4")
]


def _ingest(monkeypatch, kind, rows, doc_type, year=2026):
    from src.pipeline import ingest_securit as ing

    seen = {}

    def fake_upsert(conn, table, recs, **kw):
        seen["table"], seen["rows"], seen["conflict"] = table, recs, kw["conflict_columns"]
        return len(recs)

    monkeypatch.setattr(ing, "upsert_rows", fake_upsert)
    fn = {"mensal": ing.ingest_securit_mensal, "serie": ing.ingest_securit_serie,
          "dfin": ing.ingest_securit_dfin}[kind]
    fn(object(), rows, doc_type, year)
    return seen


def _keys(seen):
    cols = seen["conflict"].split(",")
    return [tuple(r[c] for c in cols) for r in seen["rows"]]


@pytest.mark.parametrize("kind,rows,doc_type", [
    ("mensal", CRA_TWINS, "cra_mensal"),
    ("mensal", OTS_PAIR, "ots_mensal"),
    ("serie", CRI_CLASSES, "cri_classe"),
    ("serie", CRI_SAME_SERIES, "cri_classe"),
    ("dfin", DFIN_FILINGS, "dfin_cri"),
])
def test_every_distinct_source_row_keeps_its_own_key(monkeypatch, kind, rows, doc_type):
    seen = _ingest(monkeypatch, kind, rows, doc_type)
    keys = _keys(seen)
    assert len(keys) == len(rows)
    assert len(set(keys)) == len(rows), (
        "rows share a conflict key, so upsert_rows would keep only the last"
    )


def test_cra_and_cri_rows_carry_their_securitizer(monkeypatch):
    """#350: CNPJ_Emissora was never a candidate, so this was NULL."""
    for kind, rows, doc in (("mensal", CRA_TWINS, "cra_mensal"),
                            ("serie", CRI_CLASSES, "cri_classe"),
                            ("dfin", DFIN_FILINGS, "dfin_cri")):
        seen = _ingest(monkeypatch, kind, rows, doc)
        assert {r["cnpj_securit"] for r in seen["rows"]} <= {"02773542000122", "04200649000107"}
        assert all(r["cnpj_securit"] for r in seen["rows"])
    seen = _ingest(monkeypatch, "mensal", OTS_PAIR, "ots_mensal")
    assert {r["cnpj_securit"] for r in seen["rows"]} == {"38042694000100"}


def test_the_report_is_typed_not_left_in_raw(monkeypatch):
    seen = _ingest(monkeypatch, "mensal", CRA_TWINS[:1], "cra_mensal")
    r = seen["rows"][0]
    assert r["codigo_identificacao"] == "BRAPCSCRA0M6"
    assert r["versao"] == 1
    assert r["dt_emissao"].isoformat() == "2026-01-01"
    assert r["occurrence"] == 1
    # The monthly report has no maturity column in any layout.
    assert r["dt_vencto"] is None

    seen = _ingest(monkeypatch, "dfin", DFIN_FILINGS[:1], "dfin_cri")
    r = seen["rows"][0]
    assert (r["codigo_identificacao"], r["data_referencia"].isoformat(), r["versao"]) == (
        "BRAPCSCRIEZ9", "2026-03-31", 1)
    assert r["raw"]["Link_Download"].startswith("https://fnet.bmfbovespa.com.br/")


def test_rows_no_column_separates_are_numbered_by_content(monkeypatch):
    """The same file must land on the same keys however its rows are ordered,
    or every re-ingest would rewrite the group."""
    def mapping(rows):
        seen = _ingest(monkeypatch, "serie", rows, "cri_classe")
        return {r["occurrence"]: r["valor_certificados"] for r in seen["rows"]}

    first = mapping(CRI_SAME_SERIES)
    assert sorted(first) == [1, 2, 3]
    shuffled = CRI_SAME_SERIES[:]
    for seed in range(5):
        random.Random(seed).shuffle(shuffled)
        assert mapping(shuffled) == first


def test_a_byte_identical_repeat_is_kept_once(monkeypatch):
    """CRI 2026 files the same ISIN two to four times, byte for byte."""
    seen = _ingest(monkeypatch, "serie", CRI_CLASSES + [dict(CRI_CLASSES[0])], "cri_classe")
    assert len(seen["rows"]) == 2


def test_a_refiled_report_overwrites_its_first_version(monkeypatch):
    """Versao is stored, not keyed: 12-19% of monthly reports are re-filed,
    and a v2 landing beside its v1 would double every sum."""
    v1 = _ingest(monkeypatch, "mensal", CRA_TWINS[:1], "cra_mensal")
    v2_row = dict(CRA_TWINS[0], Versao="2", Ativo="229900000.00")
    v2 = _ingest(monkeypatch, "mensal", [v2_row], "cra_mensal")
    assert _keys(v1) == _keys(v2)
    assert v2["rows"][0]["versao"] == 2


@pytest.mark.parametrize("kind,rows,doc_type,header_col", [
    ("mensal", CRA_TWINS, "cra_mensal", "Codigo_Identificacao_Certificado"),
    ("dfin", DFIN_FILINGS, "dfin_cri", "Codigo_Identificacao_Certificado"),
    ("dfin", DFIN_FILINGS, "dfin_cri", "Data_Referencia"),
])
def test_a_renamed_key_column_fails_loudly(monkeypatch, kind, rows, doc_type, header_col):
    renamed = [{("X_" + k if k == header_col else k): v for k, v in r.items()} for r in rows]
    with pytest.raises(FieldMapMismatch):
        _ingest(monkeypatch, kind, renamed, doc_type)


# --------------------------------------------------------------------------
# Schema, migration and consumers agree
# --------------------------------------------------------------------------

def _constraint_cols(sql, name):
    m = re.search(rf"CONSTRAINT {name}\s+UNIQUE NULLS NOT DISTINCT\s*\(([^)]*)\)", sql)
    assert m, f"{name} not declared UNIQUE NULLS NOT DISTINCT"
    return tuple(c.strip() for c in m.group(1).split(","))


@pytest.mark.parametrize("fmap,name", [
    (_mensal, "uq_securit_mensal"), (_serie, "uq_securit_serie"), (_dfin, "uq_securit_dfin"),
])
def test_field_map_schema_and_migration_agree_on_the_key(fmap, name):
    """ON CONFLICT resolves only against a unique index on exactly these columns."""
    schema = (ROOT / "src/store/schema.sql").read_text()
    migration = (ROOT / "src/store/migrations/52_securit_keys.sql").read_text()
    assert _constraint_cols(schema, name) == fmap.CONFLICT
    migration_cols = re.search(
        rf"ADD CONSTRAINT {name}\s+UNIQUE NULLS NOT DISTINCT \(([^)]*)\)", migration
    ).group(1)
    assert tuple(c.strip() for c in migration_cols.split(",")) == fmap.CONFLICT
    assert fmap.CONFLICT == fmap.GROUP + ("occurrence",)
    injected = {"instrument_type", "occurrence"}
    assert set(fmap.CONFLICT) - injected <= set(fmap.FIELD_MAP)


@pytest.mark.parametrize("fmap", [_mensal, _serie, _dfin])
def test_the_securitizer_is_not_part_of_any_key(fmap):
    """Existing CRA/CRI rows have a NULL CNPJ that raw cannot restore
    (_strip_raw_duplicates dropped CNPJ_Emissora), so a key naming it would make
    the re-ingest insert every row beside its NULL twin (migration 52)."""
    assert "cnpj_securit" not in fmap.CONFLICT
    candidates, _ = fmap.FIELD_MAP["cnpj_securit"]
    assert candidates[:2] == ["CNPJ_Emissora", "CNPJ_Securitizadora"]


def test_the_migration_backfills_every_mensal_year():
    """A year left out keeps a NULL certificate, and the re-ingest of that year
    would then insert beside the existing row instead of merging."""
    migration = (ROOT / "src/store/migrations/52_securit_keys.sql").read_text()
    years = {int(y) for y in re.findall(r"WHERE period_year = (\d{4})", migration)}
    assert years == set(range(2016, 2028))
    assert "(period_year < 2016 OR period_year > 2027)" in migration


SERIES_READERS = [
    "dashboard/sources/supabase/securit_overview.sql",
    "dashboard/sources/supabase/securit_ratings.sql",
    "dashboard/sources/supabase/securit_subordination.sql",
    "dashboard/sources/supabase/securit_maturity_wall.sql",
    "src/store/analytical/15_fraud_screens.sql",
]


@pytest.mark.parametrize("path", SERIES_READERS)
def test_a_series_is_not_split_by_securitizer(path):
    """Certificates move between securitizers (318 CRI codes, 2019-2026). A
    per-series snapshot keyed on cnpj_securit would count a moved series twice,
    once with the old securitizer's stale last filing."""
    sql = (ROOT / path).read_text()
    heads = re.findall(r"distinct on\s*\(([^)]*)\)", sql, re.I)
    series = [h for h in heads if "numero_serie" in h]
    assert series, f"{path}: no per-series DISTINCT ON found"
    for h in series:
        assert "cnpj_securit" not in h, f"{path}: {h.strip()}"
