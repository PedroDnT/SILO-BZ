"""Development-only fitting from canonical originals at the first test cutoff.

No test outcomes, production action, prediction publication or PIT certification.
"""
from __future__ import annotations

from collections import Counter
import json

import numpy as np
import pandas as pd

from research_examples.debenture_equity.experiment import fit_ridge, predict, timestamp
from research_examples.debenture_equity.originals import _scope, _slot, load_original
from research_examples.debenture_equity.prospective import _replay_input
from research_examples.debenture_equity.snapshots import read_archive


def fit_available_pair(features, labels, method, *, fit_cutoff, validation_start,
                       validation_cutoff, test_start, sector_controls=False):
    """Fit/tune with explicit calendar and actual-availability purges, never test labels."""
    if features.empty:
        return None, 'No eligible prediction features'
    if labels.empty:
        return None, 'No available development labels'
    if set(features['signal_date']) != {test_start}:
        raise ValueError('Prediction features must use the supplied next-split signal')
    if {'residual_return', 'entry_date', 'exit_date', 'horizon'} & set(features.columns):
        raise ValueError('Prediction features cannot contain future outcomes')
    if any(labels[c].nunique() != 1 for c in ('horizon', 'entry_delay_sessions', 'original_registry_sha256')):
        raise ValueError('Fitting cannot mix horizons, delays or registry scopes')
    if (labels['signal_date'] >= test_start).any():
        raise ValueError('Test outcomes cannot enter development fitting')
    if labels.duplicated(['cnpj', 'signal_date']).any() or features.duplicated(['cnpj', 'signal_date']).any():
        raise ValueError('Duplicate issuer/date in fitting inputs')
    known = labels[labels['label_available_at'].map(timestamp) <= timestamp(fit_cutoff)].copy()
    matured = known[known['exit_date'] < test_start]
    train = matured[(matured['signal_date'] < validation_start)
                    & (matured['exit_date'] < validation_start)
                    & (matured['label_available_at'].map(timestamp) <= timestamp(validation_cutoff))]
    valid = matured[matured['signal_date'] >= validation_start]
    equity_fields = list(method['equity_features'])
    sector_coverage = {}
    if sector_controls:
        if 'sector' not in features or 'sector' not in labels:
            return None, 'Missing frozen dated sector inputs'
        present = lambda values: values.map(lambda v: isinstance(v, str) and bool(v.strip()))
        categories = sorted(train.loc[present(train['sector']), 'sector'].unique())
        if len(categories) < 2:
            return None, 'Fewer than two sectors in available purged training sample'
        sector_coverage['training_sectors'] = categories
        retained = {}
        for name, frame in [('training', train), ('validation', valid),
                            ('final_fit', matured), ('prediction', features)]:
            available = present(frame['sector'])
            seen = frame['sector'].isin(categories)
            selected = frame[available & seen].copy()
            sector_coverage[name] = {'input_rows': len(frame), 'retained_rows': len(selected),
                    'missing_sector_rows': int((~available).sum()),
                    'unseen_sector_rows': int((available & ~seen).sum())}
            # The intercept carries the first category. Encoding never learns
            # a category from validation, refit-only gap labels or OOS features.
            for i, label in enumerate(categories[1:], start=1):
                selected[f'sector_control_{i}'] = (selected['sector'] == label).astype(float)
            retained[name] = selected
        train, valid, matured, features = (retained[k] for k in ('training', 'validation', 'final_fit', 'prediction'))
        equity_fields += [f'sector_control_{i}' for i in range(1, len(categories))]
        if features.empty:
            return None, 'No prediction rows in available training sectors: '+json.dumps(sector_coverage['prediction'])
    if (train['signal_date'].nunique() < method['min_train_dates']
            or valid['signal_date'].nunique() < method['min_validation_dates']):
        return None, ('Insufficient available sector-covered dates after calendar/availability purges' if sector_controls
                      else 'Insufficient available development dates after calendar/availability purges')
    columns = equity_fields+method['credit_features']
    if not np.isfinite(matured[columns+['residual_return']].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite eligible model inputs')
    if not np.isfinite(features[columns].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite prediction features')
    models, predictions = {}, features.copy()
    for name, fields in [('equity_only', equity_fields),
                          ('equity_plus_credit', columns)]:
        losses = []
        for penalty in method['ridge_grid']:
            estimate = predict(fit_ridge(train, fields, penalty), valid, fields)
            losses.append((float(np.mean((valid['residual_return'].to_numpy()-estimate)**2)), penalty))
        _, penalty = min(losses)
        model = fit_ridge(matured, fields, penalty)
        models[name] = {'features': fields, 'ridge_penalty': penalty,
                        'center': model[0].tolist(), 'scale': model[1].tolist(), 'coefficients': model[2].tolist()}
        predictions['prediction_'+name] = predict(model, features, fields)
    lineage_columns = ['cnpj', 'signal_date', 'input_manifest_sha256', 'label_manifest_sha256',
                       'label_available_at', 'original_registry_sha256']
    return {'models': models, 'predictions': predictions,
            'train_dates': int(train['signal_date'].nunique()),
            'validation_dates': int(valid['signal_date'].nunique()),
            'fit_dates': int(matured['signal_date'].nunique()),
            'training_lineage': train[lineage_columns].to_dict('records'),
            'validation_lineage': valid[lineage_columns].to_dict('records'),
            'final_fit_lineage': matured[lineage_columns].to_dict('records'),
            **({'sector_coverage': sector_coverage} if sector_controls else {})}, None


def fit_originals(registry_path, prediction_input, development_inputs, *, registry_sha256,
                  horizon, delay, candidate=None):
    """Prepare a model candidate; publication before entry and activation remain separate gates."""
    manifest, prediction_report = _scope(registry_path, prediction_input, registry_sha256, candidate)
    manifest, raw, retention = read_archive(prediction_input)
    if retention['manifest_sha256'] != prediction_report['manifest_sha256']:
        raise ValueError('Prediction input changed during fitting preparation')
    features, _ = _replay_input(manifest, raw, retention, candidate)
    protocol = json.loads(raw['frozen_model_and_feature_manifest'])['protocol']
    method = protocol['method']
    if horizon not in method['horizons'] or delay not in {method['entry_delay_sessions'], method['robustness_delay_sessions']}:
        raise ValueError('Fitting horizon/delay differs from frozen design')
    root, root_raw, root_report = read_archive(registry_path)
    if root_report['manifest_sha256'] != registry_sha256:
        raise ValueError('Registry changed during fitting preparation')
    calendar = json.loads(raw['verified_cash_calendar'])['sessions']
    root_calendar = json.loads(root_raw['verified_cash_calendar'])['sessions']
    if [d for d in calendar if d <= root_calendar[-1]] != root_calendar:
        raise ValueError('Prediction calendar changes the frozen registry calendar')
    start = calendar.index(root['signal_date'])
    ntrain = protocol['calendar']['training_reference_sessions']
    nvalid = protocol['calendar']['validation_reference_sessions']
    test_index = start+ntrain+nvalid
    if test_index+1 >= len(calendar) or manifest['signal_date'] != calendar[test_index]:
        raise ValueError('Fitting initialization requires the fixed first test signal')
    validation_start = calendar[start+ntrain]
    validation_cutoff = calendar[start+ntrain+1]+'T10:00:00-03:00'
    fit_cutoff = manifest['cutoff_at']
    if len(development_inputs) > ntrain+nvalid:
        raise ValueError('Development input inventory exceeds the fixed design')
    rows, excluded, seen = [], Counter(), set()
    for path in development_inputs:
        item, report = _scope(registry_path, path, registry_sha256, candidate)
        day = item['signal_date']
        if day in seen or day not in calendar[start:test_index]:
            raise ValueError('Duplicate or non-development input in fitting inventory')
        seen.add(day)
        slot = _slot(registry_path, day, horizon, delay)
        if not slot.exists():
            excluded['missing_original_slot'] += 1
            continue
        _, _, label_report = read_archive(slot)
        if timestamp(label_report['archived_at']) > timestamp(fit_cutoff):
            excluded['label_unavailable_at_fit'] += 1
            continue
        panel, outcome_report = load_original(registry_path, path, horizon, delay,
                                               registry_sha256=registry_sha256, as_of=fit_cutoff, candidate=candidate)
        excluded.update(outcome_report['exclusions'])
        if not panel.empty:
            rows.append(panel)
    labels = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    result, reason = fit_available_pair(features, labels, method, fit_cutoff=fit_cutoff,
                                        validation_start=validation_start, validation_cutoff=validation_cutoff,
                                        test_start=manifest['signal_date'])
    report = {'original_registry_sha256': registry_sha256,
              'prediction_input_manifest_sha256': prediction_report['manifest_sha256'],
              'fit_cutoff': fit_cutoff, 'horizon': horizon, 'entry_delay_sessions': delay,
              'supplied_development_inputs': len(seen), 'omitted_development_inputs': ntrain+nvalid-len(seen),
              'exclusions': dict(excluded), 'reason': reason, 'strict_pit_certified': False,
              'limitations': ['Offline preparation only; model/predictions are not published or accepted',
                              'Development inventory completeness and pre-outcome root acceptance require evidence',
                              'Power, sector robustness, frozen prediction reuse and independent financial/PIT acceptance remain']}
    return result, report
