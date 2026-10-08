"""Local current-vintage FCA evidence from retained source ZIPs; no warehouse writes.

Zero equities means zero published equity rows in the selected retained export,
not independently certified source completeness or historical PIT.
"""
from __future__ import annotations

import base64
import argparse
import csv
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

from research_examples.debenture_equity.experiment import SAO_PAULO, timestamp, validate_links
from research_examples.debenture_equity.prepare import fingerprint
from src.parsers.field_maps.cia_fca_valor_mobiliario import FIELD_MAP
from src.parsers.mapping import coerce
from src.parsers.validation import DataValidator

EQUITIES = {'Ações Ordinárias', 'Ações Preferenciais', 'Units'}
MAX_ZIP_BYTES = 10_000_000
MAX_EXPANDED_BYTES = 50_000_000


def source_url(year):
    return f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip'


def retain_zip(raw, receipt, year):
    """Embed already fetched bytes and their actual receipt; never invent timestamps."""
    if len(raw) > MAX_ZIP_BYTES or hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('FCA ZIP hash/byte budget mismatch')
    if receipt['source_url'] != source_url(year):
        raise ValueError('FCA source URL/year mismatch')
    start, end, seen = (timestamp(receipt[k]) for k in
                        ('read_started_at', 'read_finished_at', 'source_observed_at'))
    if not start <= seen <= end:
        raise ValueError('FCA receipt timing is inconsistent')
    return {**{k: receipt[k] for k in ('source_url', 'sha256', 'read_started_at',
        'read_finished_at', 'source_observed_at')}, 'year': year,
        'zip_base64': base64.b64encode(raw).decode()}


def _key(row, columns):
    cnpj, reference, version, document = (row[k] for k in columns)
    cnpj = coerce(cnpj, 'cnpj')
    errors, _ = DataValidator().validate_record({'cnpj': cnpj}, ['cnpj'], {'cnpj': 'cnpj'})
    if errors:
        raise ValueError('Malformed FCA full CNPJ')
    date.fromisoformat(reference)
    if not version.isdigit() or int(version) < 1 or not document.strip():
        raise ValueError('Malformed FCA filing key')
    return cnpj, reference, int(version), document.strip()


def _rows(z, name, required):
    text = z.read(name).decode('latin1')
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    if (not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames)
            or not set(required) <= set(reader.fieldnames)):
        raise ValueError('FCA member missing/duplicate column labels')
    rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('Malformed FCA source row')
    return rows


def derive_identity(archives, links, signal_date):
    """Select indexed latest filings before joining current published content."""
    date.fromisoformat(signal_date)
    validate_links(links)
    scope = {link['cnpj'] for link in links}
    if not archives or len({a['year'] for a in archives}) != len(archives):
        raise ValueError('Explicit FCA years with one retained vintage each are required')
    index, general, securities, receipts = {}, {}, {}, {}
    summary_keys = ('CNPJ_CIA', 'DT_REFER', 'VERSAO', 'ID_DOC')
    content_keys = ('CNPJ_Companhia', 'Data_Referencia', 'Versao', 'ID_Documento')
    for a in archives:
        if type(a['year']) is not int or not 2010 <= a['year'] <= 2100:
            raise ValueError('Invalid FCA archive year')
        raw = base64.b64decode(a['zip_base64'], validate=True)
        if retain_zip(raw, a, a['year']) != a:
            raise ValueError('FCA archive differs from canonical raw evidence')
        seen = timestamp(a['source_observed_at'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            if (len(set(names)) != len(names)
                    or sum(i.file_size for i in z.infolist()) > MAX_EXPANDED_BYTES):
                raise ValueError('FCA ZIP has duplicate members or exceeds expansion budget')
            year = a['year']
            summary = _rows(z, f'fca_cia_aberta_{year}.csv', summary_keys+('CATEG_DOC', 'DT_RECEB'))
            contents = _rows(z, f'fca_cia_aberta_geral_{year}.csv', content_keys)
            stocks = _rows(z, f'fca_cia_aberta_valor_mobiliario_{year}.csv',
                           [aliases[0] for aliases, _ in FIELD_MAP.values()])
        if not summary or not contents:
            raise ValueError('FCA source index/general member is empty')
        for row in summary:
            key = _key(row, summary_keys)
            received = date.fromisoformat(row['DT_RECEB'])
            if row['CATEG_DOC'] != 'FCA' or received > seen.astimezone(SAO_PAULO).date():
                raise ValueError('FCA index category/receipt date is invalid')
            if key in index:
                raise ValueError('Duplicate FCA source index filing')
            index[key], receipts[key] = row, a
        for row in contents:
            key = _key(row, content_keys)
            if key not in index or key in general:
                raise ValueError('FCA general member has duplicate/unindexed filing')
            general[key] = row
        for row in stocks:
            key = _key(row, content_keys)
            if key not in general:
                raise ValueError('FCA securities member lacks indexed general filing')
            securities.setdefault(key, []).append(row)
    latest = {}
    for key in index:
        company, reference, version, _ = key
        if company not in scope or reference > signal_date:
            continue
        rank = reference, version
        if company in latest and rank == latest[company][:2]:
            raise ValueError('Conflicting equal-rank FCA document identities')
        if company not in latest or rank > latest[company][:2]:
            latest[company] = reference, version, key
    if set(latest) != scope:
        raise ValueError('Scoped issuer absent from retained FCA year inventory')
    projected, census, selected = [], [], []
    rename = {'cnpj_cia': 'cnpj', 'versao': 'version', 'id_documento': 'document_id',
              'valor_mobiliario': 'security_type', 'codneg': 'ticker',
              'sigla_classe': 'share_class', 'mercado': 'market', 'segmento': 'segment'}
    for company in sorted(latest):
        key = latest[company][2]
        if key not in general:
            raise ValueError('Content missing for latest indexed filing; no older fallback')
        a = receipts[key]
        members = []
        for raw_row in securities.get(key, []):
            if raw_row['Valor_Mobiliario'] not in EQUITIES:
                continue
            row = {}
            for field, (aliases, kind) in FIELD_MAP.items():
                value = raw_row[aliases[0]]
                typed = coerce(value, kind)
                if value.strip() and typed is None:
                    raise ValueError('Malformed FCA security field; do not drop/coerce a row')
                row[rename.get(field, field)] = typed.isoformat() if isinstance(typed, date) else typed
            row['fetched_at'] = a['source_observed_at']
            if row in members:
                raise ValueError('Duplicate FCA equity row in selected filing')
            members.append(row)
        projected.extend(members)
        census.append({'cnpj': company, 'data_refer': key[1], 'version': key[2],
            'document_id': key[3], 'complete': True, 'equity_rows': len(members),
            'equity_rows_sha256': fingerprint(members), 'fetched_at': a['source_observed_at'],
            'received_date': index[key]['DT_RECEB'], 'source_archive_sha256': a['sha256'],
            'published_security_rows': len(securities.get(key, []))})
        selected.append({'index': index[key], 'general': general[key],
                         'source_archive_sha256': a['sha256']})
    return {'links': links, 'fca': projected, 'filing_census': census,
            'selected_source_filings': selected, 'source_archives': archives,
            'source_completeness': 'Published ZIP attestation, not independently certified',
            'strict_pit_certified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--year', required=True, type=int)
    parser.add_argument('--links', required=True, type=Path)
    parser.add_argument('--signal-date', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    links = json.loads(args.links.read_text())
    if isinstance(links, dict):
        links = links['links']
    if args.zip.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError('FCA ZIP byte budget exceeded')
    retained = retain_zip(args.zip.read_bytes(), receipt, args.year)
    identity = derive_identity([retained], links, args.signal_date)
    with args.output.open('x') as stream:
        os.chmod(args.output, 0o600)
        json.dump(identity, stream, ensure_ascii=False, allow_nan=False)
    print(json.dumps({'filings': len(identity['filing_census']),
                      'equity_rows': len(identity['fca']), 'strict_pit_certified': False}))


if __name__ == '__main__':
    main()
