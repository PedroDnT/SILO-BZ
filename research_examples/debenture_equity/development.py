"""Development-only nested chronological losses; no power or activation decision.

The pure tabular seam expects independently replayed frozen inputs and canonical
original labels. It does not authenticate archives, completeness or PIT by itself.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import json

import numpy as np
import pandas as pd

from research_examples.debenture_equity.experiment import timestamp
from research_examples.debenture_equity.fitting import fit_available_pair
from research_examples.debenture_equity.originals import _scope, _slot, load_original
from research_examples.debenture_equity.power import development_date_ceiling
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.prospective import _replay_input
from research_examples.debenture_equity.snapshots import read_archive


def nested_losses(features, labels, calendar, protocol, *, development_start, horizon, delay):
    """Expanding fits with a fixed minimum-length rolling validation reference window.

    Each OOS signal s uses validation start s-(horizon+delay)-V; training exits
    precede that start and validation exits precede s. Availability purges can
    shrink either segment below its floor; that fold is skipped, never extended
    using later labels. OOS labels are attached only after each fit. The untouched
    test starts after the protocol's fixed development reference count.
    """
    development_date_ceiling(protocol)  # Validate integer lengths, floors and delays.
    method = protocol['method']
    if (type(horizon) is not int or type(delay) is not int
            or horizon not in method['horizons']
            or delay not in {method['entry_delay_sessions'], method['robustness_delay_sessions']}):
        raise ValueError('Nested horizon/delay differs from frozen design')
    if calendar != sorted(set(calendar)):
        raise ValueError('Nested calendar must be ordered and unique')
    for day in calendar:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Nested calendar must use ISO dates')
    start = calendar.index(development_start)
    n = protocol['calendar']['training_reference_sessions']+protocol['calendar']['validation_reference_sessions']
    boundary = start+n
    if boundary+1 >= len(calendar):
        raise ValueError('Nested calendar must establish the first test cutoff')
    cutoff = calendar[boundary+1]+'T10:00:00-03:00'
    keys = ['cnpj', 'signal_date']
    fields = method['equity_features']+method['credit_features']
    bound = fields+['input_manifest_sha256', 'original_registry_sha256']
    if {'residual_return', 'entry_date', 'exit_date', 'horizon'} & set(features.columns):
        raise ValueError('Nested prediction features cannot contain future outcomes')
    development_days = set(calendar[start:boundary])
    for frame in (features, labels):
        if not frame.empty and (not set(frame.signal_date).issubset(development_days)
                                or frame.duplicated(keys).any()):
            raise ValueError('Nested inputs must be unique issuer/dates inside the development interval')
        if not frame.empty and (frame['original_registry_sha256'].nunique(dropna=False) != 1
                                or frame.groupby('signal_date')['input_manifest_sha256'].nunique(dropna=False).max() != 1):
            raise ValueError('Nested inputs mix frozen registry/input scopes')
    if not labels.empty:
        if any(set(labels[c]) != {v} for c, v in [('horizon', horizon), ('entry_delay_sessions', delay)]):
            raise ValueError('Nested labels mix horizons/delays')
        if features.empty:
            raise ValueError('Nested labels require their frozen features')
        matched = labels.merge(features[keys+bound], on=keys, how='left', suffixes=('', '_frozen'), validate='one_to_one')
        if any(not matched[c].equals(matched[c+'_frozen'].rename(c)) for c in bound):
            raise ValueError('Nested label differs from its frozen feature or input scope')
        for row in labels.to_dict('records'):
            i = calendar.index(row['signal_date'])
            if i+delay+horizon+1 >= len(calendar) or (row['entry_date'], row['exit_date']) != (calendar[i+delay], calendar[i+delay+horizon]):
                raise ValueError('Nested label entry/exit differs from verified calendar')
            if timestamp(row['label_available_at']) < timestamp(calendar[i+delay+horizon+1]+'T00:00:00-03:00'):
                raise ValueError('Nested label was available before realization')
    known = labels[labels.label_available_at.map(timestamp) <= timestamp(cutoff)].copy() if not labels.empty else labels.copy()
    folds, losses = [], []
    g, valid_length = horizon+delay, method['min_validation_dates']
    first = start+method['min_train_dates']+valid_length+2*g
    for i in range(first, boundary-g):
        day = calendar[i]
        prediction_features = features[features.signal_date == day].copy() if not features.empty else features.copy()
        fit_cutoff = calendar[i+1]+'T10:00:00-03:00'
        validation_start = calendar[i-g-valid_length]
        validation_cutoff = calendar[i-g-valid_length+1]+'T10:00:00-03:00'
        prior = known[known.signal_date < day].copy() if not known.empty else known.copy()
        result, reason = fit_available_pair(prediction_features, prior, method,
                                            fit_cutoff=fit_cutoff, validation_start=validation_start,
                                            validation_cutoff=validation_cutoff, test_start=day)
        fold = {'signal_date': day, 'fit_cutoff': fit_cutoff, 'validation_start': validation_start,
                'validation_cutoff': validation_cutoff, 'reason': reason, 'prediction_rows': 0,
                'scored_rows': 0, 'missing_oos_labels': 0}
        if result is not None:
            fold.update({k: result[k] for k in ('models', 'training_lineage', 'validation_lineage', 'final_fit_lineage',
                                               'train_dates', 'validation_dates', 'fit_dates')})
            predicted = result['predictions']
            realized = known[known.signal_date == day]
            paired = predicted.merge(realized[keys+['residual_return', 'label_manifest_sha256', 'label_available_at',
                                                    'entry_date', 'exit_date']], on=keys, how='inner', validate='one_to_one')
            fold.update(prediction_rows=len(predicted), scored_rows=len(paired), missing_oos_labels=len(predicted)-len(paired))
            if not paired.empty:
                if not np.isfinite(paired['residual_return'].to_numpy(dtype=float)).all():
                    raise ValueError('Nonfinite available OOS target')
                for name in ('equity_only', 'equity_plus_credit'):
                    paired['loss_'+name] = (paired.residual_return-paired['prediction_'+name])**2
                paired['loss_gain'] = paired.loss_equity_only-paired.loss_equity_plus_credit
                paired['horizon'], paired['entry_delay_sessions'] = horizon, delay
                losses.append(paired)
        folds.append(fold)
    frame = pd.concat(losses, ignore_index=True) if losses else pd.DataFrame()
    return frame, {'protocol_sha256': fingerprint(protocol), 'development_start': development_start,
                   'untouched_test_start': calendar[boundary], 'development_cutoff': cutoff,
                   'horizon': horizon, 'entry_delay_sessions': delay,
                   'validation_rule': 'rolling_minimum_reference_window_before_oos_exit_purge',
                   'folds': folds, 'oos_dates': int(frame.signal_date.nunique()) if not frame.empty else 0,
                   'oos_issuers': int(frame.cnpj.nunique()) if not frame.empty else 0,
                   'unavailable_at_development_cutoff': len(labels)-len(known),
                   'missing_oos_labels': sum(f['missing_oos_labels'] for f in folds),
                   'power_status': 'not_estimable', 'minimum_detectable_gain': None,
                   'test_activation_allowed': False, 'strict_pit_certified': False,
                   'limitations': ['Pure tabular preparation; independently verified canonical archive integration is required',
                                   'Fold rule requires acceptance before outcomes; no timely prediction-publication claim',
                                   'Sector/issuer coverage, block/null calibration and MC assessment remain; no learning-power claim']}


def nested_original_losses(registry_path, boundary_input, development_inputs, *, registry_sha256,
                           horizon, delay, candidate=None):
    """Read canonical originals only, bound to the pinned first-test input cutoff.

    No test label is loaded. This replays causal development predictions after
    development for a diagnostic; it does not publish tradable predictions.
    """
    boundary, boundary_report = _scope(registry_path, boundary_input, registry_sha256, candidate)
    boundary, raw, retention = read_archive(boundary_input)
    if retention['manifest_sha256'] != boundary_report['manifest_sha256']:
        raise ValueError('Boundary input changed during nested replay')
    protocol = json.loads(raw['frozen_model_and_feature_manifest'])['protocol']
    calendar = json.loads(raw['verified_cash_calendar'])['sessions']
    root, root_raw, root_report = read_archive(registry_path)
    if root_report['manifest_sha256'] != registry_sha256:
        raise ValueError('Registry changed during nested replay')
    root_calendar = json.loads(root_raw['verified_cash_calendar'])['sessions']
    if [d for d in calendar if d <= root_calendar[-1]] != root_calendar:
        raise ValueError('Nested boundary changes frozen registry calendar')
    start = calendar.index(root['signal_date'])
    n = protocol['calendar']['training_reference_sessions']+protocol['calendar']['validation_reference_sessions']
    if start+n+1 >= len(calendar) or boundary['signal_date'] != calendar[start+n]:
        raise ValueError('Nested replay requires the fixed first test boundary')
    scope = set(calendar[start:start+n])
    seen, feature_rows, label_rows, exclusions = set(), [], [], Counter()
    for path in development_inputs:
        item, report = _scope(registry_path, path, registry_sha256, candidate)
        day = item['signal_date']
        if day in seen or day not in scope:
            raise ValueError('Nested inventory must be unique inside the development interval')
        seen.add(day)
        item, item_raw, item_retention = read_archive(path)
        if item_retention['manifest_sha256'] != report['manifest_sha256']:
            raise ValueError('Development input changed during nested replay')
        item_calendar = json.loads(item_raw['verified_cash_calendar'])['sessions']
        if [d for d in calendar if d <= item_calendar[-1]] != item_calendar:
            raise ValueError('Nested development input changes boundary calendar')
        frozen_features, _ = _replay_input(item, item_raw, item_retention, candidate)
        if not frozen_features.empty:
            frozen_features = frozen_features.assign(input_manifest_sha256=report['manifest_sha256'],
                                                     original_registry_sha256=registry_sha256)
            feature_rows.append(frozen_features)
        slot = _slot(registry_path, day, horizon, delay)
        if not slot.exists():
            exclusions['missing_original_slot'] += 1
            continue
        _, _, label_retention = read_archive(slot)
        if timestamp(label_retention['archived_at']) > timestamp(boundary['cutoff_at']):
            exclusions['label_unavailable_at_development_cutoff'] += 1
            continue
        labels, outcome_report = load_original(registry_path, path, horizon, delay,
                                               registry_sha256=registry_sha256,
                                               as_of=boundary['cutoff_at'], candidate=candidate)
        exclusions.update(outcome_report['exclusions'])
        if not labels.empty:
            label_rows.append(labels)
    features = pd.concat(feature_rows, ignore_index=True) if feature_rows else pd.DataFrame()
    labels = pd.concat(label_rows, ignore_index=True) if label_rows else pd.DataFrame()
    losses, report = nested_losses(features, labels, calendar, protocol,
                                   development_start=root['signal_date'], horizon=horizon, delay=delay)
    report.update(original_registry_sha256=registry_sha256,
                  boundary_input_manifest_sha256=boundary_report['manifest_sha256'],
                  supplied_development_inputs=len(seen), omitted_development_inputs=n-len(seen),
                  archive_exclusions=dict(exclusions))
    report['limitations'][0] = 'Canonical archive replay; root/inventory completeness and PIT require independent acceptance'
    return losses, report
