# FIDC credit analysis

FIDC (Fundo de Investimento em Direitos Creditórios) are Brazilian securitization vehicles. SILO ingests the full CVM monthly informe, covering tranche structure, receivables aging, top creditors and debtors, sector exposure, and the restatement register.

## Fund discovery

Start by finding the fund:

```bash
POST /rpc/search_funds
{
  "p_q": "fundo",
  "p_type": "fidc",
  "p_limit": 20
}
```

Or look up by CNPJ:

```bash
POST /rpc/fund_profile
{
  "p_cnpj": "12345678000190"
}
```

## Tranche structure

`fidc_tranches()` returns the tranche-level data for one fund and period: quotas outstanding, PL, subordination ratio, delinquency.

```bash
POST /rpc/fidc_tranches
{
  "p_cnpj": "12345678000190",
  "p_from": "2024-01-01",
  "p_to": "2024-12-31"
}
```

Data starts in 2025-01 (first month CVM published the new Resolução CVM 175 format for FIDC). There is no backfill archive for pre-175 tranches.

## Receivables aging

`fidc_aging()` returns the aging buckets for each fund's receivable portfolio.

```bash
POST /rpc/fidc_aging
{
  "p_cnpj": "12345678000190",
  "p_from": "2024-01-01",
  "p_to": "2024-12-31"
}
```

Buckets follow CVM's filing format: current, 1–30 days, 31–60 days, 61–90 days, 91–180 days, 181–360 days, over 360 days.

## Concentration: creditors, debtors, and sectors

`fidc_portfolio()` returns the top creditors (tab VIII), top 25 debtors (tab II), and sector exposure (tab X) for a fund.

```bash
POST /rpc/fidc_portfolio
{
  "p_cnpj": "12345678000190",
  "p_tab": "cedentes",
  "p_from": "2024-01-01",
  "p_to": "2024-12-31"
}
```

`p_tab` options: `cedentes` (creditors, with CNPJ), `sacados` (debtors, anonymized), `setor` (sector breakdown).

**Creditors carry CNPJs.** You can join `fidc_cedentes` to `cia_company` to get the originator's sector and financial statement history.

**Debtors are anonymized.** CVM anonymizes the top-25 debtor rows. The concentration metrics are in the data but individual identities are not.

## Guarantee coverage

`fidc_garantia()` returns the filed guarantee values for each fund's credit rights.

The denominator of the guarantee percentage is not documented by CVM. Do not call it "coverage ratio" — it is filed guarantee value as a percentage of something CVM does not specify.

## Restatement register

FIDC funds restate their monthly informes through B3's Fundos.NET system. SILO tracks every restatement.

```bash
POST /rpc/fund_restatements
{
  "p_cnpj": "12345678000190"
}
```

Each row is a restatement pair: the original document and its replacement, the number of fields changed, and the status of the diff.

```bash
POST /rpc/fund_restatement_diff
{
  "p_cnpj": "12345678000190",
  "p_fnet_id": 123456
}
```

Returns the field-level diff between the original and the restated document. Only `compared` pairs have a diff; `status` on each pair explains why a diff may be missing.

## Things to watch

**FNET documents carry no CNPJ.** A document's fund is identified by the CNPJ SILO used to query for it — not by anything in the document itself. `fund_documents` shows `cnpj = NULL` for any document delivered before that fund's last nightly sweep.

**Restatements do not overwrite the original.** Each version of a filing is a distinct `fnet_id`. The CVM CSV files carry no version information — FNET is the only public record of FIDC restatements.

**`versao` is part of the key.** `cvm_fidc_*` tables store every version as a separate row. Query through the `vw_fidc_*_latest` views to get the current version without managing versioning yourself.
