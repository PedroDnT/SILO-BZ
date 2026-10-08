"""Conditional crossed/block loss-test simulation; never an accepted power gate.

No collection, production access, test outcomes or hypothesis confirmation.
The hybrid resampling requires independent training/activity calibration.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
from statistics import NormalDist

import numpy as np

from research_examples.debenture_equity.development import nested_original_losses
from research_examples.debenture_equity.experiment import timestamp
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.snapshots import read_archive


def crossed_indices(n_dates, n_issuers, block, repetitions, rng):
    """Whole-issuer draws crossed with non-circular moving cash-calendar blocks."""
    if any(type(v) is not int or v < 1 for v in (n_dates, n_issuers, block, repetitions)) or block >= n_dates:
        raise ValueError('Resampling needs positive integers and block shorter than calendar')
    starts = rng.integers(0, n_dates-block+1, size=(repetitions, int(np.ceil(n_dates/block))))
    dates = (starts[:, :, None]+np.arange(block)).reshape(repetitions, -1)[:, :n_dates]
    issuers = rng.integers(0, n_issuers, size=(repetitions, n_issuers))
    return dates, issuers


def sampled_means(panel, dates, issuers):
    """Skip absent cells, retain multiplicity and return NaN for empty draws."""
    values = panel[dates[:, :, None], issuers[:, None, :]]
    valid = np.isfinite(values)
    counts = valid.sum(axis=(1, 2))
    totals = np.where(valid, values, 0.).sum(axis=(1, 2))
    return np.divide(totals, counts, out=np.full(len(counts), np.nan), where=counts > 0)


def _mc_row(gain, rejections, trials):
    if trials == 0:
        return {'relative_mse_gain': gain, 'rejections': rejections, 'trials': 0,
                'rejection_frequency': None, 'wilson_mc_interval_95': None}
    frequency = rejections/trials
    z = NormalDist().inv_cdf(.975)
    denominator = 1+z*z/trials
    center = (frequency+z*z/(2*trials))/denominator
    radius = z*np.sqrt(frequency*(1-frequency)/trials+z*z/(4*trials*trials))/denominator
    return {'relative_mse_gain': gain, 'rejections': rejections, 'trials': trials,
            'rejection_frequency': frequency,
            'wilson_mc_interval_95': [max(0., float(center-radius)), min(1., float(center+radius))]}


def conditional_sensitivity(losses, nested_report, protocol):
    """Double resampling of centered paired losses, with shared draws across gains.

    Outer draws simulate a centered null panel. Each gets an independent inner
    crossed/block bootstrap test, centered at that outer panel's observed mean.
    The same inner distribution tests each predeclared shift of baseline MSE.
    Null rejection and Wilson intervals describe Monte Carlo behavior conditional
    on these losses/mask, not a theorem or end-to-end learning calibration.
    """
    design, method = protocol['power_design'], protocol['method']
    if nested_report['protocol_sha256'] != fingerprint(protocol):
        raise ValueError('Conditional diagnostic differs from nested development protocol')
    positive = [design['outer_repetitions'], method['bootstrap_repetitions'], design['horizon_count'],
                design['minimum_development_oos_dates'], design['minimum_development_oos_issuers'],
                *design['block_sessions_grid']]
    if any(type(v) is not int or v < 1 for v in positive):
        raise ValueError('Monte Carlo counts, floors and blocks must be positive integers')
    alpha = design['family_alpha']/design['horizon_count']
    grid = design['relative_mse_gain_grid']
    if (not 0 < alpha < 1 or design['horizon_count'] != len(method['horizons'])
            or not grid or grid != sorted(set(grid)) or grid[0] != 0
            or not np.isfinite(grid).all() or any(v < 0 for v in grid)):
        raise ValueError('Invalid family alpha/horizon count or frozen gain grid')
    calendar = nested_report['oos_reference_sessions']
    if calendar != sorted(set(calendar)):
        raise ValueError('Conditional development calendar must be ordered and unique')
    for day in calendar:
        if date.fromisoformat(day).isoformat() != day or day >= nested_report['untouched_test_start']:
            raise ValueError('Conditional calendar must precede untouched test')
    result = {'protocol_sha256': fingerprint(protocol), 'nested_report_sha256': fingerprint(nested_report),
              'loss_table_sha256': fingerprint(losses.to_dict('records')),
              'horizon': nested_report['horizon'], 'entry_delay_sessions': nested_report['entry_delay_sessions'],
              'calendar_reference_sessions': len(calendar), 'observed_dates': 0, 'observed_issuers': 0,
              'missing_calendar_sessions': len(calendar), 'missing_cells': 0,
              'block_diagnostics': [], 'per_horizon_alpha': alpha,
              'power_status': 'not_estimable', 'minimum_detectable_gain': None,
              'test_activation_allowed': False, 'strict_pit_certified': False,
              'calibration_status': 'not_run',
              'reason': 'Insufficient development coverage',
              'limitations': ['Conditional loss-test sensitivity only, not end-to-end power of learning credit signals',
                             'Hybrid crossed-issuer/block inference requires independent finite-sample calibration',
                             'Training/selection uncertainty, source activity, sector/dominance and delayed-entry gates remain',
                             'Wilson intervals measure Monte Carlo error only; no MDE, test activation or PIT acceptance']}
    if losses.empty:
        return result
    if (not set(losses.signal_date).issubset(calendar)
            or (losses.exit_date >= nested_report['untouched_test_start']).any()
            or (losses.label_available_at.map(timestamp) > timestamp(nested_report['development_cutoff'])).any()
            or losses.duplicated(['cnpj', 'signal_date']).any()):
        raise ValueError('Conditional inputs must be available unique development-only losses')
    if not all(isinstance(c, str) and re.fullmatch(r'[0-9]{14}', c) for c in losses.cnpj):
        raise ValueError('Conditional resampling requires full CNPJ issuers')
    if (set(losses.horizon) != {nested_report['horizon']}
            or set(losses.entry_delay_sessions) != {nested_report['entry_delay_sessions']}
            or losses.original_registry_sha256.nunique(dropna=False) != 1
            or ('original_registry_sha256' in nested_report
                and set(losses.original_registry_sha256) != {nested_report['original_registry_sha256']})):
        raise ValueError('Conditional inputs mix horizon/delay or original scopes')
    baseline = losses.loss_equity_only.to_numpy(dtype=float)
    credit = losses.loss_equity_plus_credit.to_numpy(dtype=float)
    gain = losses.loss_gain.to_numpy(dtype=float)
    if (not np.isfinite(np.column_stack([baseline, credit, gain])).all()
            or (baseline < 0).any() or (credit < 0).any()
            or not np.allclose(gain, baseline-credit, rtol=1e-12, atol=1e-15)):
        raise ValueError('Conditional inputs need finite nonnegative reconciled paired losses')
    issuers = sorted(losses.cnpj.unique())
    n_dates = int(losses.signal_date.nunique())
    result.update(observed_dates=n_dates, observed_issuers=len(issuers),
                  missing_calendar_sessions=len(calendar)-n_dates,
                  missing_cells=len(calendar)*len(issuers)-len(losses),
                  baseline_mse=float(baseline.mean()), observed_mean_loss_gain=float(gain.mean()))
    if n_dates < design['minimum_development_oos_dates'] or len(issuers) < design['minimum_development_oos_issuers']:
        return result
    if baseline.mean() <= 0 or np.ptp(gain) == 0:
        result['reason'] = 'Degenerate baseline or loss-gain variation'
        return result
    if any(block >= len(calendar) for block in design['block_sessions_grid']):
        result['reason'] = 'Calendar too short for all predeclared non-circular block sensitivities'
        return result
    panel = np.full((len(calendar), len(issuers)), np.nan)
    di = {d: i for i, d in enumerate(calendar)}
    ii = {c: i for i, c in enumerate(issuers)}
    panel[[di[d] for d in losses.signal_date], [ii[c] for c in losses.cnpj]] = gain-gain.mean()
    outer, inner = design['outer_repetitions'], method['bootstrap_repetitions']
    if 1/(inner+1) > alpha:
        result['reason'] = 'Inner Monte Carlo resolution cannot reach the per-horizon alpha'
        return result
    for block in design['block_sessions_grid']:
        # Key by block so adding/reordering a sensitivity cannot perturb another.
        rng = np.random.default_rng(np.random.SeedSequence([design['seed'], nested_report['horizon'],
                                                           nested_report['entry_delay_sessions'], block]))
        ds, cs = crossed_indices(len(calendar), len(issuers), block, outer, rng)
        rejections, trials, empty_outer, empty_inner, incomplete_inner = np.zeros(len(grid), dtype=int), 0, 0, 0, 0
        for d, c in zip(ds, cs):
            sampled = panel[np.ix_(d, c)]
            if not np.isfinite(sampled).any():
                empty_outer += 1
                continue
            observed = float(np.nanmean(sampled))
            ids, ics = crossed_indices(len(calendar), len(issuers), block, inner, rng)
            inner_means = sampled_means(sampled, ids, ics)
            valid = np.isfinite(inner_means)
            empty_inner += int((~valid).sum())
            if not valid.all():
                # Never hide sparsity by redrawing or quietly conditioning tests
                # on a smaller inner Monte Carlo bank.
                incomplete_inner += 1
                continue
            null = inner_means-observed
            shifted = observed+np.asarray(grid)*baseline.mean()
            p = (1+np.count_nonzero(null[:, None] >= shifted, axis=0))/(inner+1)
            rejections += (p <= alpha) & (shifted > 0)
            trials += 1
        points = [_mc_row(g, int(r), trials) for g, r in zip(grid, rejections)]
        result['block_diagnostics'].append({'block_sessions': block,
                    'block_fraction_of_calendar': block/len(calendar),
                    'nonoverlapping_full_blocks': len(calendar)//block,
                    'moving_block_start_positions': len(calendar)-block+1,
                    'outer_requested': outer, 'outer_evaluated': trials, 'empty_outer': empty_outer,
                    'inner_requested_per_outer': inner, 'empty_inner': empty_inner,
                    'outer_with_incomplete_inner': incomplete_inner,
                    'null_rejection_mc': points[0], 'gain_grid': points})
    if any(b['outer_evaluated'] < outer for b in result['block_diagnostics']):
        result['calibration_status'] = 'incomplete_conditional_simulation'
        result['reason'] = 'Empty resampling draws; conditional frequencies exclude incomplete tests, no MDE or activation'
    else:
        result['calibration_status'] = 'conditional_null_simulation_only'
        result['reason'] = ('Conditional simulation completed; independent training/activity calibration and '
                            'sector/issuer robustness acceptance remain, so no MDE or test activation')
    return result


def diagnostic_originals(registry_path, boundary_input, development_inputs, *, registry_sha256,
                         horizon, delay, candidate=None):
    """Replay canonical development losses then simulate; no test label is read."""
    losses, report = nested_original_losses(registry_path, boundary_input, development_inputs,
                registry_sha256=registry_sha256, horizon=horizon, delay=delay, candidate=candidate)
    _, raw, retention = read_archive(boundary_input)
    if retention['manifest_sha256'] != report['boundary_input_manifest_sha256']:
        raise ValueError('Boundary changed during conditional diagnostic')
    protocol = json.loads(raw['frozen_model_and_feature_manifest'])['protocol']
    result = conditional_sensitivity(losses, report, protocol)
    return {**result, 'original_registry_sha256': registry_sha256,
            'boundary_input_manifest_sha256': report['boundary_input_manifest_sha256'],
            'archive_exclusions': report['archive_exclusions'],
            'omitted_development_inputs': report['omitted_development_inputs']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--registry-sha256', required=True)
    parser.add_argument('--boundary-input', required=True, type=Path)
    parser.add_argument('--development-input', action='append', type=Path, default=[])
    parser.add_argument('--horizon', required=True, type=int)
    parser.add_argument('--delay', required=True, type=int)
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    result = diagnostic_originals(args.registry, args.boundary_input, args.development_input,
              registry_sha256=args.registry_sha256, horizon=args.horizon, delay=args.delay,
              candidate=json.loads(args.protocol.read_text()) if args.protocol else None)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
