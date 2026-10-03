# The portfolio report: Redator, Revisor and PDF

What turns the engine's JSON (`engine-output.md`) into the Portuguese PDF report. Code: `src/portfolio/report/`; this page is the contract between the engine and the report. One rule decides everything: **a number in the report comes from the engine, never from a model.**

```
python -m src.portfolio.report.build engine.json --out report.pdf [--html report.html] \
    [--provider fake|anthropic|openai] [--signature TEXT] [--no-llm-review]
```

`--provider fake` writes the findings with a deterministic template writer (no network, no key). `anthropic` and `openai` use the Redator and the Revisor over the provider's API. Without `--provider`, `SILO_LLM_PROVIDER` decides, and an unset variable means `anthropic`. A sample report is `docs/reference/portfolio/sample-report.pdf` (synthetic fixture).

## Roles

| Role | Does | May not |
| --- | --- | --- |
| Engine (`src/portfolio/`, SQL in schema `api`) | Every figure, with source tool, arguments and data date | Write prose |
| Redator (`redator.py`) | Writes the findings in Portuguese from the masked engine JSON, with `{{path}}` placeholders | Type a digit, date, CNPJ or amount |
| Revisor (`revisor.py`) | Removes what the engine does not support: deterministic code first, then an optional LLM pass | Add a placeholder or a claim; the LLM pass may only delete or reword, and a reword is re-checked by the same code |
| Renderer (`render.py`, `values.py`) | The one place a figure becomes text, in Brazilian format | Format by anything but the path's last key |

The Redator sees the masked JSON only: `assert_masked` refuses the call when anything that looks like the client (name, CPF, account, a forbidden key) is in it. The engine already guarantees none is: holder `[TITULAR]`, accounts `C1..Cn`.

## The placeholder rule

A placeholder is `{{path}}`: dot-separated keys with `[i]` list indexes into the engine JSON, for example `{{fees.by_line[3].estimated_pct_year}}`. A sentence with a literal digit outside a placeholder is removed. A placeholder pointing at a missing key or a null is removed with its sentence. The renderer prints the value by the last key of its path (the table lives in `values.py`):

| Key | Unit in the engine JSON | Printed as |
| --- | --- | --- |
| contains `_brl` | reais | `R$ 1.234,56`, `R$ 187,3 milhões` |
| contains `_pct` | percent (1.65 = 1,65%) | `1,65%` |
| contains `cnpj` | 14 digits | `00.000.000/0000-00` |
| `month`, `competencia` | ISO date, first of month | `08/2026` |
| other ISO date | `YYYY-MM-DD` | `31/08/2026` |
| ISO timestamp | UTC | `03/10/2026 13:00 (UTC-3) (16:00 UTC)` |
| `old_num`, `new_num`, `change_brl` of a `VL_*` leaf | reais | as `_brl` |

A fraction (`weight_in_line`, `similarity`, `explained_weight`) is never printed as a percent: the engine names a percent `_pct` and a fraction never.

## Revisor rules

Deterministic, sentence by sentence:

1. every placeholder resolves to an existing path with a non-null scalar;
2. a sentence with a literal digit outside a placeholder is removed;
3. every citation is an `id` of the engine's `provenance`, and a source named in the text (CVM, BCB, B3, FNET, ANBIMA, IBGE) is one the provenance carries;
4. an extreme value stays only when the engine carries a second path confirming it, else the sentence is removed with a note. Thresholds (`revisor.py`): a fee above 5% a.a., an exposure above 50% of the portfolio, a delinquency change above R$ 100 milhões;
5. unusual movement (`movement`, engine schema 1.3): the text may cite the "forte" level and the count of funds not evaluated; a sentence that cites the table or puts "atenção" in a sentence about movement is removed, because "atenção" is a table-only level. Movement paths are exempt from the exposure rule.

A finding whose title fails, whose citations are invalid or empty, or that has no sentence left is removed whole. The report states no forecast and no recommendation. What the engine does not assess is written as such: a restatement is "reapresentado, não avaliado"; a fee not found is "taxa divulgada não encontrada"; an estimate is "estimativa, não divulgada"; a fund without a movement verdict is "não avaliado" with its reason. The Redator may not turn an estimate into the fee or a performance-fee text into a rate. When the Extrato files 0 or above 5% a.a., the other document's fee is shown beside the headline (engine 1.4: `lamina_beside_*`, "lâmina informa X; a conferir", or, when the newer lâmina is the headline, `extrato_beside_*`, "Extrato de <data> informa X"); neither is summed or compared, and `scale_flag_label` ("possível erro de escala no Extrato") is a flag, never a correction. Fees by level follow Res. CVM 175 Art. 98 (`docs/reference/research/cvm175-structure-and-fees.md`): a fund-of-funds' disclosed administration and management fee already includes its investees' unless the investee is listed or run by an unrelated manager, so the report never adds a master's fee to a feeder's in that case.

## Structured output and validation

The Redator's and the Revisor's replies are Pydantic v2 models (`FindingsOutput`, `VerdictsOutput`). The same models define the schema each provider is asked for and validate every reply, whatever provider produced it. A reply that fails validation raises `LLMValidationError`: in the Redator the narrative is marked unknown, like a refusal, and the engine tables still print; in the Revisor the deterministic result stands. A finding with an unknown section fails the whole reply.

## Providers and the cost cap

`llm.py` is one `complete(system, user, schema)` interface with three providers, chosen by `SILO_LLM_PROVIDER`:

| Provider | Model | Key | Notes |
| --- | --- | --- | --- |
| `openai` (current, owner's choice 2026-10-03) | `SILO_LLM_MODEL`, default `gpt-6-luna` | `OPENAI_API_KEY` | Responses API with structured output; reasoning effort `SILO_LLM_EFFORT`, default `medium` (`off` sends none); `store=False`; no hosted tools (web or file search are reserved for the later Investigator) |
| `anthropic` | `SILO_LLM_MODEL`, default `claude-opus-5-5` | `ANTHROPIC_API_KEY` | Messages API with structured output; `SILO_LLM_EFFORT`, `SILO_LLM_FALLBACKS` |
| `fake` | none | none | Deterministic, for tests and offline runs |

`SILO_LLM_MODEL` is shared by the providers: unset it, or set an OpenAI ID, before switching to `openai` from a Claude ID. The key is read from the environment only, passed explicitly and never logged.

Cap: US$ 1,00 per report, counted from the reply's token usage with a worst-case check before each call. Prices are the table in `llm.py`, read from each provider's official pricing page and dated there (for example `gpt-6-luna` at US$ 0,10 input, 0,01 cached input, 0,50 output per million tokens, read 2026-10-03). An unpriced model is booked at the most expensive row, so the cap errs high. A refusal, a truncated or filtered reply, a validation failure or the cap marks the narrative unknown, and the engine tables still print. Not handled yet: an HTTP error from either SDK (a 429 for an account without credits, a 404 for a wrong model ID) still stops the run.

Swapping vendor means writing one provider class: the engine, the placeholders, the Pydantic models and the Revisor do not change.

## PDF

WeasyPrint (CSS paged media), chosen over a headless browser for one native dependency (pango and cairo) and print CSS kept as plain text in `templates/report.css`. Report-only dependencies (`anthropic`, `openai`, `pydantic`, `weasyprint`, `pypdf`, `reportlab`) are in `requirements-report.txt`, not `requirements.txt`: the daily ingest installs the latter and must not need pango. The signature defaults to the owner's ("Pedro Todescan, pesquisador independente"), overridable with `SILO_REPORT_SIGNATURE` or `--signature`.

## Hosting

The report is meant to run in the Cloudflare Container behind the upload page (slice E of map #510). The first safe deploy (`deploy/cloudflare/`, `.github/workflows/deploy_cloudflare.yml`) serves a health-only container with no engine and no LLM key. Running the report there will need `api.openai.com` in the egress list and `OPENAI_API_KEY` handed to the container; `docs/reference/research/cloudflare-container.md` was written for `api.anthropic.com`.

## Not verified

No live model call has been made with either provider; the sample report comes from a synthetic fixture. The engine schema the report reads is `engine-output.md`.
