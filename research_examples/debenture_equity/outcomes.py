"""Replay one immutable, on-time outcome archive against its frozen feature archive.

No fetch, fitting, prediction, production write or financial/PIT certification.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path

from research_examples.debenture_equity.experiment import SAO_PAULO, attach_outcomes, timestamp
from research_examples.debenture_equity.prospective import _available, _replay_input
from research_examples.debenture_equity.snapshots import read_archive


def replay_outcome(input_path, outcome_path, *, as_of, candidate=None):
    """Return labels only when their original publication preceded the requested fit cutoff.

    An on-time archive is required here. Late/missing and revised outcomes must be
    recorded separately; this function never silently substitutes either.
    """
    input_manifest, input_raw, input_retention = read_archive(input_path)
    features, input_report = _replay_input(input_manifest, input_raw, input_retention, candidate)
    manifest, raw, retention = read_archive(outcome_path)
    if manifest.get('kind') != 'outcome':
        raise ValueError('Expected an outcome archive')
    context = manifest['outcome']
    # Bind the exact verified input bytes as well as their replayed calculations.
    if (context['input_manifest_sha256'] != input_report['manifest_sha256']
            or manifest['protocol_sha256'] != input_manifest['protocol_sha256']
            or manifest['links_sha256'] != input_manifest['links_sha256']
            or manifest['signal_date'] != input_manifest['signal_date']):
        raise ValueError('Outcome archive does not reference the frozen input archive')
    if timestamp(retention['archived_at']) > timestamp(as_of):
        raise ValueError('Outcome was not archived by the requested fit cutoff')
    payloads = {name: json.loads(data) for name, data in raw.items()}
    reference = payloads['frozen_feature_reference']
    if reference != {'input_manifest_sha256': input_report['manifest_sha256']}:
        raise ValueError('Outcome feature reference differs from frozen archive')
    frozen = json.loads(input_raw['frozen_model_and_feature_manifest'])
    method = frozen['protocol']['method']
    horizon, delay = context['horizon'], context['entry_delay_sessions']
    if horizon not in method['horizons'] or delay not in {method['entry_delay_sessions'], method['robustness_delay_sessions']}:
        raise ValueError('Outcome horizon/delay is not in the externally pinned design')
    limits = {name: min(timestamp(c['source_observed_at']), timestamp(c['read_finished_at']))
              for name, c in manifest['components'].items()}
    calendar = payloads['verified_cash_calendar']
    sessions = calendar['sessions']
    if sessions != sorted(set(sessions)) or not calendar['source_url'].startswith('https://'):
        raise ValueError('Outcome cash calendar needs ordered unique sessions and provenance')
    for session in sessions:
        date.fromisoformat(session)
    _available(calendar['observed_at'], limits['verified_cash_calendar'])
    original_calendar = json.loads(input_raw['verified_cash_calendar'])['sessions']
    if [s for s in sessions if s <= original_calendar[-1]] != original_calendar:
        raise ValueError('Outcome calendar changes the frozen feature calendar')
    signal = manifest['signal_date']
    if signal not in sessions or sessions.index(signal)+delay+horizon+1 >= len(sessions):
        raise ValueError('Outcome calendar does not establish exit and next cash session')
    i = sessions.index(signal)
    entry, exit_, next_session = sessions[i+delay], sessions[i+delay+horizon], sessions[i+delay+horizon+1]
    cutoff = timestamp(manifest['cutoff_at']).astimezone(SAO_PAULO)
    if cutoff.date().isoformat() != next_session or cutoff.strftime('%H:%M:%S.%f') != '10:00:00.000000':
        raise ValueError('Outcome cutoff must be 10:00 Brasilia on first cash session after exit')
    response = payloads['realized_return_response']
    limit = limits['realized_return_response']
    _available(response['exported_at'], limit)
    # Without an independently verified exchange-close time, require collection
    # and publication on the first post-exit session, never merely before its
    # future deadline. Future-dated payload rows alone cannot prove realization.
    earliest = datetime.combine(date.fromisoformat(next_session), time.min, SAO_PAULO)
    if min(timestamp(response['exported_at']), timestamp(retention['archived_at'])) < earliest:
        raise ValueError('Realized response/publication precedes first cash session after exit')
    if timestamp(response['exported_at']) <= timestamp(input_manifest['cutoff_at']):
        raise ValueError('Realized response must follow the feature cutoff')
    expected = {s for s in sessions if signal <= s <= exit_}
    if {r['trade_date'] for r in response['benchmark']} != expected:
        raise ValueError('Outcome benchmark must cover exactly signal through exit cash sessions')
    for row in response['equities']:
        _available(row['data_revision'], limit)
        if row['trade_date'] not in expected:
            raise ValueError('Outcome equity includes dates outside the realized window')
    bundle = {**response, 'cash_sessions': sorted(expected)}
    panel, exclusions = attach_outcomes(features, bundle, {**method, 'horizons': [horizon], 'outcome_to': exit_}, delay)
    if not panel.empty:
        if set(panel['entry_date']) != {entry} or set(panel['exit_date']) != {exit_}:
            raise ValueError('Computed outcome dates disagree with verified calendar')
        panel['label_available_at'] = retention['archived_at']
        panel['label_manifest_sha256'] = retention['manifest_sha256']
        panel['input_manifest_sha256'] = input_report['manifest_sha256']
        panel['label_return_response_sha256'] = hashlib.sha256(raw['realized_return_response']).hexdigest()
        panel['entry_delay_sessions'] = delay
    return panel, {**retention, 'input_manifest_sha256': input_report['manifest_sha256'],
                   'label_rows': len(panel), 'exclusions': exclusions, 'fit_as_of': as_of,
                   'strict_pit_certified': False, 'limitations': retention['limitations']+[
                       'On-time original outcome arithmetic only; no late/revision substitution or prediction acceptance',
                       'Calendar completeness, coherent benchmark source vintage and financial conventions require independent acceptance']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-archive', required=True, type=Path)
    parser.add_argument('--outcome-archive', required=True, type=Path)
    parser.add_argument('--as-of', required=True, help='Fit information cutoff including timezone')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    candidate = json.loads(args.protocol.read_text()) if args.protocol else None
    _, report = replay_outcome(args.input_archive, args.outcome_archive, as_of=args.as_of, candidate=candidate)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
