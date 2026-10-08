"""Private local, deadline-bound first-model publication and unchanged-model reuse.

No source collection, test-label fitting, production action or PIT certification.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from research_examples.debenture_equity import snapshots
from research_examples.debenture_equity.experiment import predict, timestamp
from research_examples.debenture_equity.fitting import fit_originals
from research_examples.debenture_equity.originals import _scope
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.prospective import _replay_input


def _prediction_slot(root, signal, horizon, delay):
    return Path(root)/('prediction-'+fingerprint({'signal_date': signal, 'horizon': horizon,
                                                 'entry_delay_sessions': delay}))


def _input(root, path, pin, candidate):
    _, scope_report = _scope(root, path, pin, candidate)
    manifest, raw, report = snapshots.read_archive(path)
    if report['manifest_sha256'] != scope_report['manifest_sha256']:
        raise ValueError('Prediction input changed during publication/replay')
    features, _ = _replay_input(manifest, raw, report, candidate)
    return manifest, raw, report, features


def _fitted_payload(result, report):
    return {'models': result['models'], 'predictions': result['predictions'].to_dict('records'),
            'training_lineage': result['training_lineage'], 'validation_lineage': result['validation_lineage'],
            'final_fit_lineage': result['final_fit_lineage'], 'fit_report': report}


def _seal(root, manifest, input_report, payload, context, started, max_bytes):
    prepared = snapshots._now()
    if not timestamp(input_report['archived_at']) <= started <= prepared <= timestamp(manifest['cutoff_at']):
        raise ValueError('Prediction preparation is early, late or clock-inconsistent')
    slot = _prediction_slot(root, manifest['signal_date'], context['horizon'], context['entry_delay_sessions'])
    # Stage computed bytes in a private, exclusive sibling. It is diagnostic
    # evidence only; the existing archive helper alone publishes readiness.
    staging = slot.with_name(slot.name+'-staging')
    staging.mkdir(mode=0o700, parents=False, exist_ok=False)
    values = {'frozen_feature_reference': {'input_manifest_sha256': input_report['manifest_sha256']},
              'frozen_model_prediction': payload}
    request = {k: manifest[k] for k in ('signal_date', 'cutoff_at', 'protocol_sha256', 'links_sha256')}
    request.update(kind='prediction', prediction=context, components={})
    for name, value in values.items():
        data = snapshots._json_bytes(value)
        if len(data) > max_bytes:
            raise ValueError('Prediction staging byte budget exceeded; evidence retained')
        path = staging/(name+'.json')
        snapshots._write_new(path, data)
        request['components'][name] = {'path': str(path), 'sha256': snapshots._digest(data),
            'source_observed_at': prepared.isoformat(), 'read_started_at': started.isoformat(),
            'read_finished_at': prepared.isoformat()}
    return slot, snapshots.archive(request, slot, max_bytes)


def publish_first(root, input_path, development_inputs, *, registry_sha256, horizon, delay,
                  candidate=None, max_bytes=snapshots.DEFAULT_MAX_BYTES):
    """Compute and seal the first-test model/predictions before the input cutoff."""
    started = snapshots._now()
    manifest, _, input_report, _ = _input(root, input_path, registry_sha256, candidate)
    result, report = fit_originals(root, input_path, development_inputs, registry_sha256=registry_sha256,
                                   horizon=horizon, delay=delay, candidate=candidate)
    if result is None:
        raise ValueError('Cannot publish model: '+str(report['reason']))
    if report['prediction_input_manifest_sha256'] != input_report['manifest_sha256']:
        raise ValueError('First prediction input changed during fitting')
    context = {'horizon': horizon, 'entry_delay_sessions': delay,
               'input_manifest_sha256': input_report['manifest_sha256'],
               'original_registry_sha256': registry_sha256, 'model_manifest_sha256': None}
    slot, retained = _seal(root, manifest, input_report, _fitted_payload(result, report), context, started, max_bytes)
    return {**retained, 'prediction_slot': slot.name, 'model_manifest_sha256': retained['manifest_sha256'],
            'prediction_rows': len(result['predictions']), 'strict_pit_certified': False}


def verify_first(root, input_path, development_inputs, *, registry_sha256, horizon, delay,
                 as_of, candidate=None):
    """Reproduce the initial fit using only its original, fixed development inputs."""
    manifest, _, input_report, _ = _input(root, input_path, registry_sha256, candidate)
    slot = _prediction_slot(root, manifest['signal_date'], horizon, delay)
    sealed, raw, report = snapshots.read_archive(slot)
    expected = {'horizon': horizon, 'entry_delay_sessions': delay,
                'input_manifest_sha256': input_report['manifest_sha256'],
                'original_registry_sha256': registry_sha256, 'model_manifest_sha256': None}
    _check_receipt(manifest, input_report, sealed, raw, report, expected, as_of)
    result, fit_report = fit_originals(root, input_path, development_inputs, registry_sha256=registry_sha256,
                                       horizon=horizon, delay=delay, candidate=candidate)
    if result is None or fingerprint(json.loads(raw['frozen_model_prediction'])) != fingerprint(_fitted_payload(result, fit_report)):
        raise ValueError('Published model/predictions differ from original development replay')
    return json.loads(raw['frozen_model_prediction']), report


def _check_receipt(input_manifest, input_report, sealed, raw, report, context, as_of):
    if (sealed.get('kind') != 'prediction' or sealed['prediction'] != context
            or any(sealed[k] != input_manifest[k] for k in ('signal_date', 'cutoff_at', 'protocol_sha256', 'links_sha256'))
            or json.loads(raw['frozen_feature_reference']) != {'input_manifest_sha256': input_report['manifest_sha256']}):
        raise ValueError('Prediction receipt differs from its frozen input/model scope')
    if timestamp(report['archived_at']) > timestamp(as_of):
        raise ValueError('Prediction was unavailable at the requested cutoff')
    if timestamp(sealed['started_at']) < timestamp(input_report['archived_at']):
        raise ValueError('Prediction publication precedes its frozen input')


def _reuse_payload(root, input_path, initial_input, development_inputs, registry_sha256, horizon, delay, candidate):
    manifest, raw, input_report, features = _input(root, input_path, registry_sha256, candidate)
    original, model_report = verify_first(root, initial_input, development_inputs,
        registry_sha256=registry_sha256, horizon=horizon, delay=delay, as_of=manifest['cutoff_at'], candidate=candidate)
    first_manifest, first_raw, first_report = snapshots.read_archive(initial_input)
    if first_report['manifest_sha256'] != original['fit_report']['prediction_input_manifest_sha256']:
        raise ValueError('Initial model input changed during reuse')
    calendar = json.loads(raw['verified_cash_calendar'])['sessions']
    first_calendar = json.loads(first_raw['verified_cash_calendar'])['sessions']
    if [d for d in calendar if d <= first_calendar[-1]] != first_calendar:
        raise ValueError('Reuse calendar changes the first prediction calendar')
    first = calendar.index(first_manifest['signal_date'])
    current = calendar.index(manifest['signal_date'])
    protocol = json.loads(raw['frozen_model_and_feature_manifest'])['protocol']
    if not first < current < first+protocol['calendar']['untouched_test_reference_sessions']:
        raise ValueError('Reuse signal is outside the fixed subsequent test interval')
    predictions = features.copy()
    for name, model in original['models'].items():
        values = tuple(np.asarray(model[k], dtype=float) for k in ('center', 'scale', 'coefficients'))
        predictions['prediction_'+name] = predict(values, features, model['features'])
    context = {'horizon': horizon, 'entry_delay_sessions': delay,
               'input_manifest_sha256': input_report['manifest_sha256'], 'original_registry_sha256': registry_sha256,
               'model_manifest_sha256': model_report['manifest_sha256']}
    payload = {'models': original['models'], 'predictions': predictions.to_dict('records')}
    return manifest, input_report, payload, context, model_report


def publish_reuse(root, input_path, initial_input, development_inputs, *, registry_sha256,
                  horizon, delay, candidate=None, max_bytes=snapshots.DEFAULT_MAX_BYTES):
    """Audit the fixed first model, then predict without fitting on any test outcomes."""
    started = snapshots._now()
    manifest, input_report, payload, context, model_report = _reuse_payload(
        root, input_path, initial_input, development_inputs, registry_sha256, horizon, delay, candidate)
    if timestamp(model_report['archived_at']) > started:
        raise ValueError('Initial model was unavailable when reuse began')
    slot, retained = _seal(root, manifest, input_report, payload, context, started, max_bytes)
    return {**retained, 'prediction_slot': slot.name, 'model_manifest_sha256': model_report['manifest_sha256'],
            'prediction_rows': len(payload['predictions']), 'strict_pit_certified': False}


def verify_reuse(root, input_path, initial_input, development_inputs, *, registry_sha256,
                 horizon, delay, as_of, candidate=None):
    """Verify unchanged model parameters and exact predictions from the frozen later input."""
    manifest, input_report, payload, context, model_report = _reuse_payload(
        root, input_path, initial_input, development_inputs, registry_sha256, horizon, delay, candidate)
    slot = _prediction_slot(root, manifest['signal_date'], horizon, delay)
    sealed, raw, report = snapshots.read_archive(slot)
    _check_receipt(manifest, input_report, sealed, raw, report, context, as_of)
    if timestamp(model_report['archived_at']) > timestamp(sealed['started_at']):
        raise ValueError('Initial model was unavailable when reuse began')
    if fingerprint(json.loads(raw['frozen_model_prediction'])) != fingerprint(payload):
        raise ValueError('Published reuse predictions/model differ from frozen replay')
    return payload, report
