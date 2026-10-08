"""Optimistic development OOS date ceilings; not a calibrated power assessment.

No loss data, untouched outcomes, production access or activation is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_examples.debenture_equity.prepare import fingerprint


def development_date_ceiling(protocol):
    """Necessary date condition for nested train/validation/OOS chronological purges.

    Ordinals start at zero. For g=entry_delay+horizon, 30 training signal dates
    need their last exit strictly before validation, 10 validation signal dates
    need their last exit strictly before OOS, and the OOS exit must precede the
    untouched-test start. Perfect daily coverage is assumed; availability and
    issuer/sector attrition can only reduce these counts.
    """
    calendar, method, power = protocol['calendar'], protocol['method'], protocol['power_design']
    values = [calendar['training_reference_sessions'], calendar['validation_reference_sessions'],
              method['min_train_dates'], method['min_validation_dates'],
              power['minimum_development_oos_dates'], method['entry_delay_sessions'],
              method['robustness_delay_sessions'], *method['horizons']]
    if any(type(v) is not int or v < 1 for v in values):
        raise ValueError('Reference lengths, floors, horizons and delays must be positive integers')
    n = calendar['training_reference_sessions']+calendar['validation_reference_sessions']
    train, valid, floor = method['min_train_dates'], method['min_validation_dates'], power['minimum_development_oos_dates']
    scenarios = []
    for delay in sorted({method['entry_delay_sessions'], method['robustness_delay_sessions']}):
        for horizon in method['horizons']:
            g = delay+horizon
            first, last = train+valid+2*g, n-g-1
            ceiling = max(0, last-first+1)
            scenarios.append({'horizon': horizon, 'entry_delay_sessions': delay,
                              'first_possible_oos_ordinal': first, 'last_possible_oos_ordinal': last,
                              'best_case_oos_dates': ceiling, 'required_oos_dates': floor,
                              'required_development_reference_sessions': train+valid+3*g+floor,
                              'meets_date_floor_in_best_case': ceiling >= floor})
    required = max(s['required_development_reference_sessions'] for s in scenarios)
    fails = any(not s['meets_date_floor_in_best_case'] for s in scenarios)
    return {'protocol_sha256': fingerprint(protocol), 'protocol_version': protocol['version'],
            'development_reference_sessions': n, 'scenarios': scenarios,
            'minimum_development_reference_sessions_all_scenarios': required,
            'additional_reference_sessions_needed_in_best_case': max(0, required-n),
            'structural_date_gate': 'fails' if fails else 'passes_best_case_only',
            'power_status': 'not_estimable', 'minimum_detectable_gain': None, 'test_activation_allowed': False,
            'reason': ('Even perfect coverage cannot supply the predeclared development OOS date floor'
                       if fails else 'Date ceiling alone supplies no nested loss series, calibration or power estimate'),
            'assumptions': ['Expanding nested training and validation with one OOS signal per cash session',
                            'No credit training signals before the first accepted development signal',
                            'Strict exit-before-next-split purges; all OOS exits precede untouched-test start',
                            'Complete daily data and timely labels; no missing issuers or sectors',
                            'No training uncertainty, loss variance or source activity inferred from date counts'],
            'limitations': ['Necessary condition only; not sufficient for estimability, precision or activation',
                            'Nested OOS losses, issuer/sector floors, null calibration, block sensitivities and MC uncertainty remain required']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=Path(__file__).with_name('prospective_protocol.json'))
    args = parser.parse_args()
    print(json.dumps(development_date_ceiling(json.loads(args.protocol.read_text())), indent=2))


if __name__ == '__main__':
    main()
