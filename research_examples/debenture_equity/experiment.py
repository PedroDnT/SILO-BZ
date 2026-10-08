"""Offline credit→equity experiment. Current revisions support retrospective research only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, time
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from research_examples.debenture_equity.prepare import fingerprint, load_protocol

SAO_PAULO = ZoneInfo('America/Sao_Paulo')
METRICS = {'quantity', 'trade_count', 'volume_brl', 'min_price', 'avg_price',
           'max_price', 'last_price', 'reference_price', 'oscillation_pct'}
ROW_KEY = ['capture_id', 'instrument_code', 'trade_date', 'settlement_date', 'trade_classification']
FCA_INTERVAL_FIELDS = {'dt_inicio_neg', 'dt_fim_neg', 'dt_inicio_list', 'dt_fim_list'}


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Knowledge timestamps must include timezone')
    return result


def day_cutoff(value):
    return datetime.combine(datetime.fromisoformat(value).date(), time.max, SAO_PAULO)


def validate_links(links):
    """A reviewed original-issuer link is distinct from a guarantor/parent inference."""
    for link in links:
        if (link['status'] != 'reviewed_original_issuer' or link['relationship'] != 'issuer'
                or len(link['cnpj']) != 14 or not link['cnpj'].isdigit()
                or not link['evidence'] or not link['instrument_code'] or not link['isin']):
            raise ValueError('Only cited, reviewed original-issuer links are eligible')
        timestamp(link['known_at'])
        if link['valid_from'] > link['reviewed_through']:
            raise ValueError('Link validity must be bounded by documentary review')
        if any(not e['url'].startswith('https://') or not e['locator'] for e in link['evidence']):
            raise ValueError('Evidence needs a source URL and document locator')
    by_bond = {}
    for link in links:
        by_bond.setdefault((link['instrument_code'], link['isin']), []).append(link)
    for versions in by_bond.values():
        for a, b in zip(sorted(versions, key=lambda x: x['valid_from']),
                        sorted(versions, key=lambda x: x['valid_from'])[1:]):
            if a['reviewed_through'] >= b['valid_from']:
                raise ValueError('Overlapping identity intervals need resolution before testing')


def validate_bundle(bundle, protocol):
    if bundle['protocol_sha256'] != fingerprint(protocol):
        raise ValueError('Bundle was exported under a different protocol')
    if any(not FCA_INTERVAL_FIELDS <= record.keys() for record in bundle['fca']):
        raise ValueError('FCA interval fields missing; re-export the existing-data bundle')
    if len({c['capture_id'] for c in bundle['captures']}) != len(bundle['captures']):
        raise ValueError('Duplicate capture identity')
    census = {c['capture_id']: c for c in bundle['credit_census']}
    if len(census) != len(bundle['credit_census']) or set(census) != {c['capture_id'] for c in bundle['captures']}:
        raise ValueError('Capture census must cover every exported snapshot exactly once')
    exported_counts = Counter(f['capture_id'] for f in bundle['credit'])
    if not set(exported_counts) <= set(census):
        raise ValueError('Credit facts lack capture provenance')
    for c in bundle['captures']:
        counts = census[c['capture_id']]
        complete = (c['status'] == 'complete' and c.get('hash_valid', False)
                    and not c['dropped_rows'] and not c['missing_dates']
                    and bool(c['expected_dates'])
                    and set(c['expected_dates']) <= set(c['delivered_dates']))
        if counts['selected_fact_count'] != exported_counts[c['capture_id']]:
            raise ValueError('Credit fact census disagrees with selected export')
        if complete and (counts['debenture_rows'] != c['debenture_rows']
                or counts['group_count'] != c['debenture_rows']
                or counts['fact_count'] != 9*c['debenture_rows']):
            raise ValueError('Credit fact census disagrees with stored capture or selected export')
    return validate_return_series(bundle)


def validate_return_series(bundle):
    """Coherent endpoint series; independent of credit or future label availability."""
    if bundle['return_basis'] != 'total_return' or bundle['benchmark_code'] != 'IBOV':
        raise ValueError('Equity and benchmark must both represent total returns')
    timestamp(bundle['exported_at'])
    eq = pd.DataFrame(bundle['equities'])
    bench = pd.DataFrame(bundle['benchmark'])
    if eq.empty or bench.empty:
        raise ValueError('Existing equity and benchmark series are required')
    if eq.duplicated(['ticker', 'trade_date']).any() or bench.duplicated('trade_date').any():
        raise ValueError('Ambiguous equity or benchmark session')
    if (bench['index_code'] != 'IBOV').any():
        raise ValueError('An ETF or settlement ticker cannot substitute for IBOV')
    for _, series in eq.groupby('ticker'):
        if series['data_revision'].isna().any() or series['data_revision'].nunique() != 1:
            raise ValueError('Equity revisions changed within the exported series')
        if series['isin'].nunique(dropna=False) != 1:
            raise ValueError('This experiment does not splice equity ISIN changes')
    if not set(eq['trade_date']) <= set(bench['trade_date']):
        raise ValueError('Benchmark is missing an observed equity session')
    if not set(bundle['cash_sessions']) <= set(bench['trade_date']):
        raise ValueError('Benchmark calendar does not cover the known cash sessions')
    return eq, bench.sort_values('trade_date')


def credit_snapshot(bundle, cutoff):
    """Choose whole complete captures per source/date BEFORE joining a bond's rows."""
    chosen = {}
    for c in bundle['captures']:
        if (c['status'] != 'complete' or c['dropped_rows'] or c['missing_dates']
                or not c['expected_dates'] or not c.get('hash_valid', False)
                or not set(c['expected_dates']) <= set(c['delivered_dates'])
                or timestamp(c['observed_at']) > cutoff):
            continue
        for d in c['delivered_dates']:
            k = c['source'], d
            rank = timestamp(c['observed_at']), c['capture_id']
            if (k in chosen and rank[0] == chosen[k][0][0]
                    and rank[1] != chosen[k][1]):
                raise ValueError('Equal-time captures require an explicit revision ordering')
            if k not in chosen or rank > chosen[k][0]:
                chosen[k] = rank, c['capture_id']
    facts = [f for f in bundle['credit'] if (f['source'], f['trade_date']) in chosen
             and chosen[f['source'], f['trade_date']][1] == f['capture_id']]
    if not facts:
        return [], {d for _, d in chosen}
    frame = pd.DataFrame(facts)
    if frame.duplicated(ROW_KEY + ['metric']).any():
        raise ValueError('Duplicate long credit observation')
    rows = []
    for key, group in frame.groupby(ROW_KEY, dropna=False):
        if set(group['metric']) != METRICS or len(group) != len(METRICS):
            raise ValueError('Selected credit grouping lacks the nine source metrics')
        if group['isin'].nunique(dropna=False) != 1 or group['row_sha256'].nunique() != 1:
            raise ValueError('Conflicting provenance within credit grouping')
        row = dict(zip(ROW_KEY, key))
        row.update(dict(zip(group['metric'], group['value'])))
        row.update(isin=group['isin'].iloc[0], source=group['source'].iloc[0])
        rows.append(row)
    return rows, {d for _, d in chosen}


def active_fca_records(records, signal_date):
    """Retrospective reference-date selection; this does not certify publication PIT."""
    latest = {}
    for record in records:
        if record['data_refer'] > signal_date:
            continue
        key = record['cnpj'], record['ticker']
        rank = record['data_refer'], int(record.get('version') or 0)
        if key not in latest or rank > latest[key][0]:
            latest[key] = rank, [record]
        elif rank == latest[key][0]:
            latest[key][1].append(record)
    active = []
    for _, filing_records in latest.values():
        # A segment change can close one listing and open another in one filing.
        for record in filing_records:
            if all((not record.get(start) or record[start] <= signal_date)
                   and (not record.get(end) or signal_date <= record[end])
                   for start, end in [('dt_inicio_neg', 'dt_fim_neg'),
                                      ('dt_inicio_list', 'dt_fim_list')]):
                active.append(record)
    return active


def return_series(eq, bench):
    """Published levels and adjacent returns without filling gaps or splicing revisions."""
    calendar = list(bench['trade_date'])
    market = bench.set_index('trade_date')['level'].astype(float).reindex(calendar)
    if not np.isfinite(market).all() or (market <= 0).any():
        raise ValueError('Invalid published benchmark level')
    market_return = np.log(market).diff()
    market_return.loc[bench.set_index('trade_date')['divisor_step'].astype(bool)] = np.nan
    prices = {}
    for ticker, group in eq.groupby('ticker'):
        series = group.set_index('trade_date')['close_total_return'].astype(float).reindex(calendar)
        if 'close_total_return_null_reason' in group:
            reasons = group.set_index('trade_date')['close_total_return_null_reason'].reindex(calendar)
            series = series.where(reasons.isna())
        prices[ticker] = series.where(np.isfinite(series) & (series > 0))
    return calendar, prices, market, market_return


def build_features(bundle, links, protocol, mode='retrospective'):
    """Past-only issuer/date features computed without requiring future outcomes."""
    if mode not in ('retrospective', 'strict_pit'):
        raise ValueError('Unknown availability mode')
    validate_links(links)
    eq, bench = validate_bundle(bundle, protocol)
    p = protocol
    calendar, prices, _, market_return = return_series(eq, bench)
    position = {d: i for i, d in enumerate(calendar)}
    volumes = {}
    for ticker, group in eq.groupby('ticker'):
        vol = group.set_index('trade_date')['volume'].astype(float).reindex(calendar)
        volumes[ticker] = vol.where(np.isfinite(vol) & (vol >= 0))
    rows, exclusions = [], Counter()
    exported = timestamp(bundle['exported_at'])
    retrospective_snapshot = credit_snapshot(bundle, exported) if mode == 'retrospective' else None
    for d in calendar:
        if not p['signal_from'] <= d <= p['signal_to']:
            continue
        i = position[d]
        cutoff = min(exported, day_cutoff(d)) if mode == 'strict_pit' else exported
        groups, delivered = (retrospective_snapshot if retrospective_snapshot is not None
                             else credit_snapshot(bundle, cutoff))
        if d not in delivered:
            exclusions['credit_session_unavailable'] += 1
            continue
        if mode == 'strict_pit':
            # Current-revision API has no historic equity/index vintage archive.
            # Credit PIT alone cannot certify an end-to-end strict PIT backtest.
            exclusions['equity_index_historical_vintages_unavailable'] += 1
            continue
        identity = [l for l in links if l['valid_from'] <= d <= l['reviewed_through']
                    and (mode != 'strict_pit' or timestamp(l['known_at']) <= cutoff)]
        mapped = []
        for g in groups:
            if (g['trade_date'] != d or str(g['trade_classification']).strip().upper()
                    != p['primary_credit_classification'].strip().upper()):
                continue
            match = [l for l in identity if (l['instrument_code'], l['isin']) ==
                     (g['instrument_code'], g['isin'])]
            if len(match) != 1:
                exclusions['unreviewed_or_ambiguous_bond'] += 1
                continue
            values = [g['volume_brl'], g['trade_count'], g['quantity']]
            if any(v is None or not np.isfinite(float(v)) or float(v) < 0 for v in values):
                exclusions['unpublished_liquidity_metric'] += 1
                continue
            if g['trade_count'] != int(g['trade_count']):
                raise ValueError('Trade count must be integral')
            mapped.append({**g, 'cnpj': match[0]['cnpj']})
        if not mapped:
            exclusions['no_eligible_credit_observation'] += 1
            continue
        active_fca = active_fca_records(bundle['fca'], d)
        for cnpj, bonds in pd.DataFrame(mapped).groupby('cnpj'):
            fca = [f for f in active_fca if f['cnpj'] == cnpj]
            eligible = []
            for ticker in sorted({f['ticker'] for f in fca} & prices.keys()):
                # A reused ticker claimed by multiple CNPJs is never guessed.
                owners = {f['cnpj'] for f in active_fca if f['ticker'] == ticker}
                prior_vol = volumes[ticker].iloc[max(0, i-p['liquidity_window']):i]
                if owners == {cnpj} and prior_vol.count() >= p['min_liquidity_observations']:
                    eligible.append((float(prior_vol.mean()), ticker))
            if not eligible:
                exclusions['no_past_liquid_equity'] += 1
                continue
            _, ticker = max(eligible, key=lambda v: (v[0], v[1]))
            price = prices[ticker]
            r = np.log(price).diff()
            hist = pd.DataFrame({'market': market_return, 'equity': r}).iloc[max(1, i-p['beta_window']):i].dropna()
            if len(hist) < p['min_beta_observations'] or hist['market'].var() <= 1e-16:
                exclusions['insufficient_trailing_beta'] += 1
                continue
            x = np.column_stack([np.ones(len(hist)), hist['market']])
            alpha, beta = np.linalg.lstsq(x, hist['equity'], rcond=None)[0]
            # Adjacent observations only: gaps never become multi-day daily returns.
            if i < 20 or price.iloc[i-5:i+1].isna().any() or r.iloc[i-19:i+1].isna().any():
                exclusions['equity_feature_gap'] += 1
                continue
            if volumes[ticker].iloc[i-20:i].count() < p['min_liquidity_observations']:
                exclusions['equity_liquidity_feature_gap'] += 1
                continue
            base = {'cnpj': cnpj, 'signal_date': d, 'ticker': ticker,
                    'alpha': float(alpha), 'beta': float(beta),
                    'equity_momentum_5': float(np.log(price.iloc[i]/price.iloc[i-5])),
                    'equity_volatility_20': float(r.iloc[i-19:i+1].std()),
                    'equity_log_volume_20': float(np.log1p(volumes[ticker].iloc[i-20:i].mean())),
                    'credit_volume_brl': float(bonds['volume_brl'].astype(float).sum()),
                    'credit_log_volume': float(np.log1p(bonds['volume_brl'].astype(float).sum())),
                    'credit_log_trades': float(np.log1p(bonds['trade_count'].astype(float).sum())),
                    'credit_active_bonds': int(bonds['instrument_code'].nunique()),
                    'credit_capture_ids': sorted(set(bonds['capture_id'])),
                    'equity_revision': eq.loc[eq['ticker'] == ticker, 'data_revision'].iloc[0],
                    'equity_isin': eq.loc[eq['ticker'] == ticker, 'isin'].iloc[0]}
            rows.append(base)
    features = pd.DataFrame(rows)
    if not features.empty and features.duplicated(['cnpj', 'signal_date']).any():
        raise ValueError('Issuer/date pseudo-replication detected')
    return features, dict(exclusions)


def attach_outcomes(features, bundle, protocol, delay=None):
    """Use one realized vintage, retaining the frozen class, features, alpha and beta.

    This arithmetic seam is not archive/PIT or label-availability certification.
    """
    p = protocol
    delay = p['entry_delay_sessions'] if delay is None else delay
    if delay < 1:
        raise ValueError('Cannot enter before next session after the signal')
    if features.empty:
        return pd.DataFrame(), {}
    if features.duplicated(['cnpj', 'signal_date']).any():
        raise ValueError('Issuer/date pseudo-replication detected')
    if {'horizon', 'residual_return', 'entry_date', 'exit_date'} & set(features.columns):
        raise ValueError('Frozen features cannot contain future outcomes')
    if not np.isfinite(features[['alpha', 'beta']].to_numpy(dtype=float)).all():
        raise ValueError('Frozen alpha/beta must be finite')
    eq, bench = validate_return_series(bundle)
    calendar, prices, market, market_return = return_series(eq, bench)
    position = {d: i for i, d in enumerate(calendar)}
    identities = {t: g['isin'].iloc[0] for t, g in eq.groupby('ticker')}
    revisions = {t: g['data_revision'].iloc[0] for t, g in eq.groupby('ticker')}
    rows, exclusions = [], Counter()
    for base in features.to_dict('records'):
        d, ticker = base['signal_date'], base['ticker']
        if d not in position or ticker not in prices:
            exclusions['label_series_unavailable'] += 1
            continue
        if not base['equity_isin'] or identities[ticker] != base['equity_isin']:
            exclusions['label_equity_identity_changed'] += 1
            continue
        i, price = position[d], prices[ticker]
        entry = i + delay
        for h in p['horizons']:
            exit_ = entry + h
            if exit_ >= len(calendar) or calendar[exit_] > p['outcome_to']:
                exclusions[f'future_outcome_unavailable_{h}'] += 1
                continue
            if price.iloc[entry:exit_+1].isna().any() or market_return.iloc[entry+1:exit_+1].isna().any():
                exclusions[f'future_outcome_gap_{h}'] += 1
                continue
            er = np.log(price.iloc[exit_]/price.iloc[entry])
            mr = np.log(market.iloc[exit_]/market.iloc[entry])
            rows.append({**base, 'horizon': h, 'entry_date': calendar[entry],
                         'exit_date': calendar[exit_],
                         'label_equity_revision': revisions[ticker],
                         'residual_return': float(er-h*base['alpha']-base['beta']*mr)})
    panel = pd.DataFrame(rows)
    if not panel.empty and panel.duplicated(['cnpj', 'signal_date', 'horizon']).any():
        raise ValueError('Issuer/date pseudo-replication detected')
    return panel, dict(exclusions)


def build_panel(bundle, links, protocol, mode='retrospective', delay=None):
    """Retrospective composition; strict mode still refuses missing historical vintages."""
    features, feature_exclusions = build_features(bundle, links, protocol, mode)
    panel, label_exclusions = attach_outcomes(features, bundle, protocol, delay)
    return panel, dict(Counter(feature_exclusions)+Counter(label_exclusions))


def fit_ridge(train, features, alpha):
    values = train[features].to_numpy(dtype=float)
    center, scale = values.mean(axis=0), values.std(axis=0)
    scale[scale < 1e-12] = 1
    x = np.column_stack([np.ones(len(values)), (values-center)/scale])
    penalty = np.diag([0.] + [alpha]*len(features))
    coef = np.linalg.solve(x.T@x+penalty, x.T@train['residual_return'].to_numpy())
    return center, scale, coef


def predict(model, frame, features):
    center, scale, coef = model
    x = np.column_stack([np.ones(len(frame)), (frame[features].to_numpy(dtype=float)-center)/scale])
    return x@coef


def model_pair(panel, protocol):
    """Tune on validation only; purge labels overlapping the next chronological split."""
    p = protocol
    train_raw = panel[panel['signal_date'] <= p['train_end']]
    valid = panel[(panel['signal_date'] > p['train_end']) & (panel['signal_date'] <= p['validation_end'])]
    test = panel[panel['signal_date'] > p['validation_end']].copy()
    if valid.empty or test.empty:
        return None, 'Empty validation or untouched test interval'
    if (test['signal_date'].nunique() < p['min_test_dates']
            or test['cnpj'].nunique() < p['min_test_issuers']):
        return None, 'Insufficient independent date/issuer coverage for inference'
    train = train_raw[train_raw['exit_date'] < valid['signal_date'].min()]
    if train['signal_date'].nunique() < p['min_train_dates'] or valid['signal_date'].nunique() < p['min_validation_dates']:
        return None, 'Insufficient training/validation dates after label purge'
    # Validation labels are used for tuning only when known before the first test signal.
    valid = valid[valid['exit_date'] < test['signal_date'].min()]
    if valid['signal_date'].nunique() < p['min_validation_dates']:
        return None, 'Insufficient validation dates after untouched-test purge'
    fit_all = panel[(panel['signal_date'] <= p['validation_end']) &
                    (panel['exit_date'] < test['signal_date'].min())]
    penalties, predictions = {}, {}
    for name, features in (('equity_only', p['equity_features']),
                           ('equity_plus_credit', p['equity_features'] + p['credit_features'])):
        losses = []
        for a in p['ridge_grid']:
            yhat = predict(fit_ridge(train, features, a), valid, features)
            losses.append((float(np.mean((valid['residual_return'].to_numpy()-yhat)**2)), a))
        _, chosen = min(losses)
        penalties[name] = chosen
        predictions[name] = predict(fit_ridge(fit_all, features, chosen), test, features)
    for name, values in predictions.items():
        test['prediction_'+name] = values
    y = test['residual_return'].to_numpy()
    test['loss_gain'] = (y-predictions['equity_only'])**2-(y-predictions['equity_plus_credit'])**2
    return {'test': test, 'ridge_penalties': penalties,
            'train_dates': int(train['signal_date'].nunique()),
            'validation_dates': int(valid['signal_date'].nunique()),
            'mse_equity_only': float(np.mean((y-predictions['equity_only'])**2)),
            'mse_equity_plus_credit': float(np.mean((y-predictions['equity_plus_credit'])**2))}, None


def clustered_interval(test, protocol, rng):
    """Crossed issuer resampling and moving calendar blocks preserve both dependence axes."""
    dates = sorted(test['signal_date'].unique())
    issuers = sorted(test['cnpj'].unique())
    di = pd.Categorical(test['signal_date'], categories=dates).codes
    ii = pd.Categorical(test['cnpj'], categories=issuers).codes
    gains = test['loss_gain'].to_numpy()
    block = protocol['bootstrap_block_sessions']
    draws = []
    for _ in range(protocol['bootstrap_repetitions']):
        # Non-circular blocks; no fabricated last→first temporal adjacency.
        starts = rng.integers(0, max(1, len(dates)-block+1), size=int(np.ceil(len(dates)/block)))
        sampled_dates = np.concatenate([np.arange(s, min(s+block, len(dates))) for s in starts])[:len(dates)]
        dw = np.bincount(sampled_dates, minlength=len(dates))
        iw = np.bincount(rng.integers(0, len(issuers), len(issuers)), minlength=len(issuers))
        weights = dw[di]*iw[ii]
        if weights.sum():
            draws.append(float(np.average(gains, weights=weights)))
    if not draws:
        raise ValueError('No nonempty clustered bootstrap draw')
    observed = float(gains.mean())
    draws = np.asarray(draws)
    alpha = protocol['family_alpha']/len(protocol['horizons'])
    lo, hi = np.quantile(draws, [alpha/2, 1-alpha/2])
    centered = draws-observed
    p_null = float((1+np.count_nonzero(centered >= observed))/(1+len(draws)))
    return {'mean_mse_gain': observed, 'familywise_interval': [float(lo), float(hi)],
            'one_sided_centered_bootstrap_p': p_null,
            'bonferroni_p': min(1., p_null*len(protocol['horizons'])),
            'draws': len(draws), 'block_sessions': block}


def attach_sectors(panel, bundle):
    """Exact dated B3 classification, observed by signal-day end; never backfill."""
    labels = {}
    exported = timestamp(bundle['exported_at'])
    for row in bundle.get('sectors', []):
        label = row['sector']
        if (not label or not label.strip()
                or timestamp(row['fetched_at']) > min(exported, day_cutoff(row['reference_date']))):
            continue
        key = row['ticker'], row['reference_date']
        if key in labels and labels[key] != label:
            raise ValueError('Conflicting dated sector labels require source review')
        labels[key] = label
    selected = panel.copy()
    if not selected.empty:
        selected['sector'] = [labels.get((r.ticker, r.signal_date))
                              for r in selected.itertuples()]
        selected = selected[selected['sector'].notna()].copy()
    return selected, {'input_rows': len(panel), 'retained_rows': len(selected),
                      'missing_sector_rows': len(panel)-len(selected)}


def sector_features(frame, protocol):
    """Freeze category encoding on purged training rows; exclude unseen sectors."""
    valid = frame[(frame['signal_date'] > protocol['train_end']) &
                  (frame['signal_date'] <= protocol['validation_end'])]
    train = frame[frame['signal_date'] <= protocol['train_end']]
    if not valid.empty:
        train = train[train['exit_date'] < valid['signal_date'].min()]
    categories = sorted(train['sector'].dropna().unique())
    encoded = frame[frame['sector'].isin(categories)].copy()
    features = []
    # Intercept carries the first category; no redundant full dummy set.
    for i, label in enumerate(categories[1:], start=1):
        feature = f'sector_control_{i}'
        encoded[feature] = (encoded['sector'] == label).astype(float)
        features.append(feature)
    adjusted = {**protocol, 'equity_features': protocol['equity_features']+features}
    return encoded, adjusted, {'training_sectors': categories,
                               'unseen_sector_rows': len(frame)-len(encoded)}


def evaluate_panel(panel, protocol, sector_controls=False):
    results = {}
    for h in protocol['horizons']:
        subset = panel[panel['horizon'] == h] if not panel.empty else panel
        if subset.empty:
            results[str(h)] = {'status': 'inconclusive', 'reason': 'No eligible issuer/date outcomes'}
            continue
        active_protocol = protocol
        sector_coverage = {}
        if sector_controls:
            subset, active_protocol, sector_coverage = sector_features(subset, protocol)
            if len(sector_coverage['training_sectors']) < 2:
                results[str(h)] = {'status': 'inconclusive',
                                  'reason': 'Fewer than two sectors in purged training sample',
                                  'sector_coverage': sector_coverage}
                continue
        pair, reason = model_pair(subset, active_protocol)
        if pair is None:
            results[str(h)] = {'status': 'inconclusive', 'reason': reason, 'rows': len(subset),
                              **({'sector_coverage': sector_coverage} if sector_controls else {})}
            continue
        test = pair.pop('test')
        result = {**pair, 'test_dates': int(test['signal_date'].nunique()),
                  'test_issuers': int(test['cnpj'].nunique()), 'test_rows': len(test)}
        if sector_controls:
            result['sector_coverage'] = sector_coverage
        if result['test_dates'] < protocol['min_test_dates'] or result['test_issuers'] < protocol['min_test_issuers']:
            results[str(h)] = {**result, 'status': 'inconclusive',
                               'reason': 'Insufficient independent date/issuer coverage for inference'}
            continue
        rng = np.random.default_rng(protocol['seed']+h)
        result.update(clustered_interval(test, protocol, rng))
        placebo_gains = []
        for _ in range(protocol['placebo_repetitions']):
            shuffled = subset.copy()
            # Shuffle the entire credit vector within each date, never targets or future dates.
            cols = protocol['credit_features']
            shuffle_keys = ['signal_date', 'sector'] if sector_controls else ['signal_date']
            for _, group in shuffled.groupby(shuffle_keys):
                shuffled.loc[group.index, cols] = group[cols].to_numpy()[rng.permutation(len(group))]
            placebo, _ = model_pair(shuffled, active_protocol)
            if placebo is not None:
                placebo_gains.append(float(placebo['test']['loss_gain'].mean()))
        result['issuer_shuffle_p'] = float((1+sum(g >= result['mean_mse_gain'] for g in placebo_gains))/(1+len(placebo_gains)))
        # Refit after removing dominant exposures across all chronological splits.
        dominant_issuers = list(test.groupby('cnpj')['credit_volume_brl'].sum().nlargest(3).index)
        dominant_dates = list(test.groupby('signal_date')['credit_volume_brl'].sum().nlargest(3).index)
        sensitivities = {}
        for issuer in dominant_issuers:
            reduced, _ = model_pair(subset[subset['cnpj'] != issuer], active_protocol)
            sensitivities['without_issuer_'+issuer] = (float(reduced['test']['loss_gain'].mean())
                                                        if reduced is not None else None)
        reduced, _ = model_pair(subset[~subset['signal_date'].isin(dominant_dates)], active_protocol)
        sensitivities['without_top_three_activity_dates'] = (float(reduced['test']['loss_gain'].mean())
                                                             if reduced is not None else None)
        result['dominance_sensitivities'] = sensitivities
        if any(v is None for v in sensitivities.values()):
            results[str(h)] = {**result, 'status': 'inconclusive',
                               'reason': 'Dominance exclusions leave insufficient evaluation coverage'}
            continue
        supported = (result['familywise_interval'][0] > 0 and result['bonferroni_p'] < protocol['family_alpha']
                     and result['issuer_shuffle_p'] < protocol['family_alpha']
                     and all(v is not None and np.isfinite(v) and v > 0 for v in sensitivities.values()))
        result['status'] = 'incremental_evidence' if supported else 'hypothesis_not_supported'
        results[str(h)] = result
    return results


def run(bundle, links, protocol, mode='retrospective'):
    panel, exclusions = build_panel(bundle, links, protocol, mode)
    delayed, delayed_exclusions = build_panel(bundle, links, protocol, mode,
                                              protocol['robustness_delay_sessions'])
    evaluated = evaluate_panel(panel, protocol)
    delayed_evaluation = evaluate_panel(delayed, protocol)
    sector_panel, sector_coverage = attach_sectors(panel, bundle)
    sector_delayed, sector_delayed_coverage = attach_sectors(delayed, bundle)
    sector_evaluation = evaluate_panel(sector_panel, protocol, sector_controls=True)
    sector_delayed_evaluation = evaluate_panel(sector_delayed, protocol, sector_controls=True)
    statuses = [evaluation[str(protocol['primary_horizon'])]['status']
                for evaluation in (evaluated, delayed_evaluation,
                                   sector_evaluation, sector_delayed_evaluation)]
    decision = ('inconclusive' if 'inconclusive' in statuses else
                'incremental_evidence' if all(s == 'incremental_evidence' for s in statuses)
                else 'hypothesis_not_supported')
    return {'decision': decision, 'mode': mode, 'protocol_sha256': fingerprint(protocol),
            'bundle_sha256': fingerprint(bundle), 'links_sha256': fingerprint(links),
            'panel_rows': len(panel), 'exclusions': exclusions, 'horizons': evaluated,
            'delay_robustness': {'sessions': protocol['robustness_delay_sessions'],
                                 'exclusions': delayed_exclusions, 'horizons': delayed_evaluation},
            'sector_robustness': {'coverage': sector_coverage, 'horizons': sector_evaluation,
                                  'delayed_coverage': sector_delayed_coverage,
                                  'delayed_horizons': sector_delayed_evaluation},
            'limitations': ['Retrospective data revisions and identity review are not original-date knowledge vintages',
                           'Liquidity-only first experiment; PU/cash-flow, REUNE rate and outstanding gaps remain',
                           'Operational sample floors do not establish statistical power',
                           'No trading strategy, net performance, execution-cost or capacity claim'],
            'strict_pit_certified': False, 'tradability_certified': False}, panel


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--bundle', type=Path, required=True)
    a.add_argument('--links', type=Path, required=True)
    a.add_argument('--protocol', type=Path, default=Path(__file__).with_name('protocol.json'))
    a.add_argument('--mode', choices=['retrospective', 'strict_pit'], default='strict_pit')
    a.add_argument('--out-dir', type=Path, required=True)
    args = a.parse_args()
    result, panel = run(json.loads(args.bundle.read_text()), json.loads(args.links.read_text()),
                        load_protocol(args.protocol), args.mode)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir/'result.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    panel.to_csv(args.out_dir/'issuer_panel.csv', index=False)
    print(json.dumps({k: result[k] for k in ('decision', 'mode', 'panel_rows', 'exclusions')}, indent=2))


if __name__ == '__main__':
    main()
