"""Canonical original-outcome slots inside one externally pinned local input archive.

Only already fetched files are archived. No collection, fitting or PIT certification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_examples.debenture_equity import snapshots
from research_examples.debenture_equity.experiment import timestamp
from research_examples.debenture_equity.outcomes import replay_outcome
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.prospective import _replay_input


def _scope(registry_path, input_path, registry_sha256, candidate):
    root, root_raw, root_report = snapshots.read_archive(registry_path)
    _replay_input(root, root_raw, root_report, candidate)
    snapshots._validate_digest(registry_sha256)
    if root_report['manifest_sha256'] != registry_sha256:
        raise ValueError('Registry differs from the externally pinned first input manifest')
    manifest, raw, report = snapshots.read_archive(input_path)
    _replay_input(manifest, raw, report, candidate)
    if (manifest['protocol_sha256'] != root['protocol_sha256']
            or manifest['links_sha256'] != root['links_sha256']
            or manifest['signal_date'] < root['signal_date']
            or timestamp(report['archived_at']) < timestamp(root_report['archived_at'])
            or (manifest['signal_date'] == root['signal_date']
                and report['manifest_sha256'] != registry_sha256)):
        raise ValueError('Input does not belong to the frozen registry scope')
    return manifest, report


def _slot(registry_path, signal_date, horizon, delay):
    if type(horizon) is not int or horizon < 1 or type(delay) is not int or delay < 1:
        raise ValueError('Original slot horizon/delay must be positive integers')
    key = {'signal_date': signal_date, 'horizon': horizon, 'entry_delay_sessions': delay}
    return Path(registry_path)/('original-'+fingerprint(key))


def archive_original(registry_path, input_path, request, *, registry_sha256, candidate=None,
                     max_bytes=snapshots.DEFAULT_MAX_BYTES):
    """Exclusive archival reserves a canonical slot; never overwrite or retry that slot.

    The externally pinned registry is the first accepted feature archive. Its
    original files are unchanged; one new private child is created per outcome.
    Once created, even a failed slot remains evidence and cannot be replaced.
    Preflight failures before directory creation do not reserve a slot.
    """
    manifest, report = _scope(registry_path, input_path, registry_sha256, candidate)
    context = request.get('outcome', {})
    if (request.get('kind') != 'outcome'
            or context.get('input_manifest_sha256') != report['manifest_sha256']
            or any(request.get(k) != manifest[k] for k in ('signal_date', 'protocol_sha256', 'links_sha256'))):
        raise ValueError('Original request differs from the frozen input scope')
    destination = _slot(registry_path, manifest['signal_date'], context['horizon'], context['entry_delay_sessions'])
    snapshots.archive(request, destination, max_bytes)
    # Retention alone does not make a scientifically valid original. Replay must
    # also pass; any partial/invalid attempt is kept and never replaced.
    return load_original(registry_path, input_path, context['horizon'], context['entry_delay_sessions'],
                         registry_sha256=registry_sha256, as_of=snapshots._now().isoformat(), candidate=candidate)


def load_original(registry_path, input_path, horizon, delay, *, registry_sha256, as_of, candidate=None):
    """Load only the canonical original slot; no alternative revision path is accepted."""
    manifest, report = _scope(registry_path, input_path, registry_sha256, candidate)
    destination = _slot(registry_path, manifest['signal_date'], horizon, delay)
    panel, outcome_report = replay_outcome(input_path, destination, as_of=as_of, candidate=candidate)
    # A slot cannot masquerade as another horizon/delay, even if its file names
    # were moved by hand. Compare the verified context, including empty panels.
    if outcome_report['outcome_context'] != {'input_manifest_sha256': report['manifest_sha256'],
                             'horizon': horizon, 'entry_delay_sessions': delay}:
        raise ValueError('Original slot context differs from its canonical key')
    if outcome_report['input_manifest_sha256'] != report['manifest_sha256']:
        raise ValueError('Original input changed during replay')
    if not panel.empty:
        panel['original_registry_sha256'] = registry_sha256
    return panel, {**outcome_report, 'original_registry_sha256': registry_sha256,
                   'original_slot': destination.name, 'original_selection': 'exclusive_slot_in_pinned_scope',
                   'limitations': outcome_report['limitations']+[
                       'Pinned scope must be accepted before outcomes; no proof of earlier archives outside this scope',
                       'Missing/failed slots cannot be repaired by substituting a later revision; late/revision sensitivity remains separate']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True, type=Path, help='First accepted frozen input archive')
    parser.add_argument('--registry-sha256', required=True, help='Externally pinned first input manifest hash')
    parser.add_argument('--input-archive', required=True, type=Path)
    parser.add_argument('--protocol', type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    write = commands.add_parser('archive', help='Archive already fetched original files in an exclusive slot')
    write.add_argument('--request', required=True, type=Path)
    write.add_argument('--max-bytes', type=int, default=snapshots.DEFAULT_MAX_BYTES)
    read = commands.add_parser('verify', help='Verify canonical original availability at a fit cutoff')
    read.add_argument('--horizon', required=True, type=int)
    read.add_argument('--delay', required=True, type=int)
    read.add_argument('--as-of', required=True)
    args = parser.parse_args()
    common = {'registry_sha256': args.registry_sha256,
              'candidate': json.loads(args.protocol.read_text()) if args.protocol else None}
    if args.command == 'archive':
        _, report = archive_original(args.registry, args.input_archive, json.loads(args.request.read_text()),
                                     max_bytes=args.max_bytes, **common)
    else:
        _, report = load_original(args.registry, args.input_archive, args.horizon, args.delay,
                                  as_of=args.as_of, **common)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
