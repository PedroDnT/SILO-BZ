"""Private local snapshot retention; no fetch, database access or PIT certification."""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from research_examples.debenture_equity.experiment import SAO_PAULO, timestamp

COMPONENTS = (
    'verified_cash_calendar', 'credit_full_capture_and_audit_census',
    'equity_quote_responses_and_adjustment_revision', 'ibov_response_and_conventions',
    'complete_relevant_fca_vintages_and_identity_evidence', 'dated_sector_input',
    'frozen_model_and_feature_manifest',
)
OUTCOME_COMPONENTS = ('verified_cash_calendar', 'realized_return_response', 'frozen_feature_reference')
DEFAULT_MAX_BYTES = 100_000_000


def _now():
    return datetime.now(timezone.utc)


def _publication_time(path):
    # Hard-link publication updates inode ctime; a crash needs no later LATE marker.
    # This is original-filesystem/local-clock evidence, not an external timestamp.
    return datetime.fromtimestamp(path.stat().st_ctime, timezone.utc)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _validate_digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid SHA256 hash')


def _timing(component, latest):
    observed = timestamp(component['source_observed_at'])
    start = timestamp(component['read_started_at'])
    end = timestamp(component['read_finished_at'])
    if not start <= end <= latest or observed > end:
        raise ValueError('Component timing is late or inconsistent')


def _cutoff(request):
    cutoff = timestamp(request['cutoff_at'])
    local = cutoff.astimezone(SAO_PAULO)
    if local.time() != time(10) or local.date() <= date.fromisoformat(request['signal_date']):
        raise ValueError('Cutoff must be 10:00 Brasilia after the signal date')
    for key in ('protocol_sha256', 'links_sha256'):
        _validate_digest(request[key])
    if set(request['components']) != set(_components(request)):
        raise ValueError('Exactly the required snapshot components must be supplied')
    return cutoff


def _components(request):
    kind = request.get('kind', 'input')
    if kind == 'input':
        return COMPONENTS
    if kind == 'outcome':
        context = request['outcome']
        if set(context) != {'horizon', 'entry_delay_sessions', 'input_manifest_sha256'}:
            raise ValueError('Invalid outcome archive context')
        if (type(context['horizon']) is not int or context['horizon'] < 1
                or type(context['entry_delay_sessions']) is not int or context['entry_delay_sessions'] < 1):
            raise ValueError('Outcome horizon and entry delay must be positive integers')
        _validate_digest(context['input_manifest_sha256'])
        return OUTCOME_COMPONENTS
    raise ValueError('Unsupported snapshot kind')


def _write_new(path, data):
    # Exclusive creation and fsync: partial evidence remains, never silently overwritten.
    with path.open('xb') as f:
        os.chmod(path, 0o600)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def archive(request, destination, max_bytes=DEFAULT_MAX_BYTES):
    """Seal already fetched files now. Caller receipts are attestations, not source proofs."""
    started = _now()
    cutoff = _cutoff(request)
    if started > cutoff:
        raise ValueError('Cannot archive after cutoff or backdate the current clock')
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError('Local byte budget must be positive')
    contents, total = {}, 0
    for name in _components(request):
        component = request['components'][name]
        _timing(component, started)
        _validate_digest(component['sha256'])
        source = Path(component['path'])
        # Check size before reading, then again on actual bytes in case it changed.
        if source.stat().st_size + total > max_bytes:
            raise ValueError('Local snapshot byte budget exceeded')
        data = source.read_bytes()
        total += len(data)
        if total > max_bytes:
            raise ValueError('Local snapshot byte budget exceeded')
        if _digest(data) != component['sha256']:
            raise ValueError('Source file hash differs from supplied receipt')
        contents[name] = data
    dest = Path(destination)
    dest.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, data in contents.items():
        _write_new(dest / (name+'.bin'), data)
    sealed = _now()
    if not started <= sealed <= cutoff:
        raise ValueError('Clock moved backwards or archive crossed cutoff; partial evidence retained')
    manifest = {
        'schema_version': 2 if request.get('kind') == 'outcome' else 1,
        'signal_date': request['signal_date'],
        'cutoff_at': request['cutoff_at'], 'started_at': started.isoformat(),
        'sealed_at': sealed.isoformat(), 'protocol_sha256': request['protocol_sha256'],
        'links_sha256': request['links_sha256'], 'max_bytes': max_bytes,
        'components': {name: {k: v for k, v in request['components'][name].items() if k != 'path'}
                       | {'file': name+'.bin', 'bytes': len(contents[name])} for name in _components(request)},
        'limitation': 'Local clock and caller receipts; source semantics, next cash session, '
                      'protocol acceptance and historical knowledge are not independently certified',
    }
    if request.get('kind') == 'outcome':
        manifest.update(kind='outcome', outcome=request['outcome'])
    data = _json_bytes(manifest)
    _write_new(dest/'manifest.json', data)
    committed = _now()
    if not sealed <= committed <= cutoff:
        raise ValueError('Manifest crossed cutoff or clock moved backwards; archive is not ready')
    pending = dest/'.READY.pending'
    _write_new(pending, _json_bytes({'manifest_sha256': _digest(data),
                                    'committed_at': committed.isoformat()}))
    staged = _now()
    if not committed <= staged <= cutoff:
        raise ValueError('Readiness staging crossed cutoff or clock moved backwards; archive is not ready')
    # Atomic, exclusive publication of the fully synced readiness receipt. Keep
    # the staging link as diagnostic evidence; never delete or replace a file.
    os.link(pending, dest/'READY.json')
    finished = _now()
    if not staged <= finished <= cutoff:
        _write_new(dest/'LATE.json', _json_bytes({'finished_at': finished.isoformat()}))
        raise ValueError('Publication crossed cutoff or clock moved backwards; archive is not ready')
    return verify(dest)


def _read_file(path, cap):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise ValueError('Archive file is missing, linked or exceeds byte budget')
    data = path.read_bytes()
    if len(data) > cap:
        raise ValueError('Archive file exceeds byte budget')
    return data


def read_archive(destination):
    """Return the exact verified bytes and receipts; never reread unverified payloads."""
    dest = Path(destination)
    if dest.is_symlink() or not (dest/'READY.json').is_file() or (dest/'LATE.json').exists():
        raise ValueError('Archive is not ready')
    ready = json.loads(_read_file(dest/'READY.json', 4096))
    raw = _read_file(dest/'manifest.json', 1_000_000)
    if _digest(raw) != ready['manifest_sha256']:
        raise ValueError('Archive manifest hash mismatch')
    manifest = json.loads(raw)
    if (manifest['schema_version'], manifest.get('kind', 'input')) not in {(1, 'input'), (2, 'outcome')}:
        raise ValueError('Unsupported snapshot manifest')
    cutoff = _cutoff(manifest)
    started, sealed, committed = map(timestamp, (manifest['started_at'], manifest['sealed_at'], ready['committed_at']))
    published = _publication_time(dest/'READY.json')
    if not started <= sealed <= committed <= published <= cutoff:
        raise ValueError('Archive timing exceeds cutoff or is inconsistent')
    budget = manifest['max_bytes']
    if not isinstance(budget, int) or budget < 1:
        raise ValueError('Invalid stored byte budget')
    total, contents = 0, {}
    for name in _components(manifest):
        component = manifest['components'][name]
        _timing(component, started)
        if component['file'] != name+'.bin':
            raise ValueError('Unexpected archive component path')
        data = _read_file(dest/component['file'], budget-total)
        if _digest(data) != component['sha256'] or len(data) != component['bytes']:
            raise ValueError('Archive component hash or size mismatch')
        total += len(data)
        contents[name] = data
    report = {'retention_verified': True, 'strict_pit_certified': False,
            'manifest_sha256': ready['manifest_sha256'], 'component_bytes': total,
            'signal_date': manifest['signal_date'], 'cutoff_at': manifest['cutoff_at'],
            'archived_at': published.isoformat(),
            'limitations': [manifest['limitation'], 'Local files are not durable production storage']}
    return manifest, contents, report


def verify(destination):
    """Check stored bytes/receipts; this does not evaluate source correctness or returns."""
    return read_archive(destination)[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, help='Verify an existing local archive')
    parser.add_argument('--request', type=Path, help='Local JSON receipt request; never fetches')
    parser.add_argument('--out-dir', type=Path, help='New private local directory; parent must exist')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.verify and not (args.request or args.out_dir):
        result = verify(args.verify)
    elif args.request and args.out_dir and not args.verify:
        result = archive(json.loads(args.request.read_text()), args.out_dir, args.max_bytes)
    else:
        parser.error('Use --verify alone, or --request with --out-dir')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
