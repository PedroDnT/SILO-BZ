"""Render a bounded SELECT or report its JSON result. No network or credentials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
from datetime import datetime


def query(capture_id: str) -> str:
    return Path(__file__).with_name('audit.sql').read_text().replace('__CAPTURE_ID__', str(UUID(capture_id)))


def summarize(data: dict) -> dict:
    capture = data.get('capture')
    if not capture:
        raise ValueError('Capture not found; no readiness result can be inferred')
    if not capture['hash_valid']:
        raise ValueError('Capture payload hash mismatch')
    expected = set(capture['expected_dates'])
    delivered = set(capture['delivered_dates'])
    cash = set(data['cash_sessions'])
    sessions = data['sessions']
    bonds = data['bonds']
    if len({b['instrument_code'] for b in bonds}) != len(bonds):
        raise ValueError('Duplicate bond identity in audit input')
    for bond in bonds:
        if bond['candidate_count'] != len(bond['candidates']):
            raise ValueError('Candidate census does not reconcile')
        if len({c['cnpj_cia'] for c in bond['candidates']}) != bond['candidate_count']:
            raise ValueError('Duplicate candidate CNPJ')
    metrics = {m['metric']: m for m in data['metrics']}
    if len(metrics) != len(data['metrics']):
        raise ValueError('Duplicate metric identity')
    complete = (capture['status'] == 'complete' and bool(expected)
                and not capture['missing_dates'] and not capture['dropped_rows']
                and expected <= delivered and cash <= delivered
                and {s['trade_date'] for s in sessions} <= delivered
                and sum(s['groups'] for s in sessions) == capture['debenture_rows']
                and all(not s['wrong_source_facts'] and not s['groups_with_bad_metrics']
                        for s in sessions))
    if sum(m['facts'] for m in metrics.values()) != sum(s['facts'] for s in sessions):
        raise ValueError('Metric and session fact counts do not reconcile')
    unique = [b for b in bonds if b['candidate_count'] == 1]
    priced = [b for b in unique if any(t['priced_sessions'] > 0 for t in b['candidates'][0]['equities'])]
    # These are retrieval vintages. No original-date PIT claim follows from trade_date.
    observed = datetime.fromisoformat(capture['observed_at'].replace('Z', '+00:00'))
    if observed.tzinfo is None:
        raise ValueError('observed_at must include timezone')
    return {
        'capture_id': capture['capture_id'], 'capture_complete': complete,
        'observed_at_utc_minus_3': observed.astimezone(ZoneInfo('America/Sao_Paulo')).isoformat(),
        'sessions': len(sessions), 'bonds': len(bonds),
        'unique_cnpj_candidates': len(unique),
        'ambiguous_bonds': [b for b in bonds if b['candidate_count'] > 1],
        'unmatched_bonds': sum(b['candidate_count'] == 0 for b in bonds),
        'candidates_with_registered_equity': sum(bool(b['candidates'][0]['equities']) for b in unique),
        'candidates_with_priced_equity': len(priced),
        'candidate_issuers_with_priced_equity': len({b['candidates'][0]['cnpj_cia'] for b in priced}),
        'metrics': metrics, 'raw_bytes': capture['raw_bytes'],
        'verdict': 'PARTIALLY READY' if complete and bonds else 'NOT READY',
        'blockers': ['No reviewed dated bond-to-CNPJ links',
                     'Retrieval timestamps do not certify original historical PIT availability',
                     'Equity adjusted returns, benchmark and sufficient estimation/test history not validated'],
    }


def report(data: dict) -> str:
    s = summarize(data)
    c = data['capture']
    span = f"{c['requested_from']} to {c['requested_to']} ({s['sessions']} observed sessions)"
    def present(names):
        return any(s['metrics'].get(n, {}).get('populated', 0) for n in names)
    rows = [
        ('Debenture PU', 'Yes' if present(['avg_price', 'last_price']) else 'No', 'fact_credit_market: min/avg/max/last/reference_price', span, 'Bond × date × settlement × classification', 'Reference may be modeled; last/reference repeat across groups; no bond total return'),
        ('Yield/spread/traded rate', 'Yes' if present(['yield', 'spread', 'traded_rate']) else 'No', 'Captured metric census', span, 'Long metric', 'Never infer yield from PU without contractual cash flows; REUNE not ingested here'),
        ('Liquidity', 'Yes' if present(['volume_brl', 'quantity', 'trade_count']) else 'No', 'fact_credit_market: volume_brl/quantity/trade_count', span, 'Source group', 'Sum disjoint groups once; absence of a bond is not proven zero trades'),
        ('Issue → issuer', 'Candidate only', 'DEB code/ISIN/issuer_name + CIA legal/commercial names + B3 names', span, 'Bond → candidate CNPJ', f"{s['unique_cnpj_candidates']} unique; {len(s['ambiguous_bonds'])} ambiguous; {s['unmatched_bonds']} unmatched; no definitive link"),
        ('Dates and PIT', 'Partial', 'b3_credit_capture.observed_at/status/hash/session census', span, 'Retrieval vintage', f"Complete={s['capture_complete']}; retrieved {s['observed_at_utc_minus_3']}; trade date is not knowledge time"),
        ('Outstanding/notional', 'No' if not present(['outstanding', 'notional']) else 'Yes', 'Captured metric census', span, 'Not present in current B3 contract', 'Traded volume is not outstanding; no turnover denominator'),
        ('Equity future/residual return', 'Partial', 'cia_ticker + b3_cotahist cash positive closes', span, 'Ticker × session', f"{s['candidates_with_priced_equity']} candidate bonds / {s['candidate_issuers_with_priced_equity']} candidate issuers with prints; adjusted returns/benchmark not certified"),
        ('Bond → issuer → ticker', 'Candidate only', 'Audit candidates and exact cia_ticker CNPJ → codneg', span, 'Bond → CNPJ → equity/unit', 'No parent/guarantor inference; no equity required for every issuer; all aliases are retrospective'),
    ]
    lines = ['# Debenture/equity readiness audit', '',
             '| Required data | Exists? | Source/table/file | Available history | Grain | Limitations |',
             '| --- | --- | --- | --- | --- | --- |']
    lines.extend('| ' + ' | '.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in row) + ' |' for row in rows)
    lines += ['', 'Verdict: **' + s['verdict'] + '**.', '',
              'This bounded capture audit does not inventory all warehouse history or test predictability.',
              'No new production write, source collection, schema apply or daily enablement is performed.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture-id', help='Print the read-only SQL; execute with Supabase MCP')
    group.add_argument('--input', type=Path, help='JSON audit object returned by that SQL')
    args = parser.parse_args()
    if args.capture_id:
        print(query(args.capture_id))
    else:
        print(report(json.loads(args.input.read_text())), end='')


if __name__ == '__main__':
    main()
