"""Declared client constraints; factual checks, never a suitability approval."""
from datetime import date
from decimal import Decimal, InvalidOperation

PROFILES = {'conservador', 'moderado', 'arrojado'}


def validate_input(raw, position_date):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {'profile', 'horizon_date', 'liquidity_date', 'liquidity_brl'}:
        raise ValueError('invalid client constraints')
    result = {}
    if raw.get('profile'):
        if raw['profile'] not in PROFILES:
            raise ValueError('invalid profile')
        result['profile'] = raw['profile']
    for key in ('horizon_date', 'liquidity_date'):
        if raw.get(key):
            d = date.fromisoformat(raw[key])
            if d < position_date:
                raise ValueError('date precedes statement')
            result[key] = d.isoformat()
    if raw.get('liquidity_brl') not in (None, ''):
        try:
            n = Decimal(str(raw['liquidity_brl']))
        except InvalidOperation:
            raise ValueError('invalid amount') from None
        if not n.is_finite() or n < 0 or n > Decimal('1e15'):
            raise ValueError('invalid amount')
        if not result.get('liquidity_date'):
            raise ValueError('liquidity date required')
        result['liquidity_brl'] = float(n)
    return result or None


def compute(doc, declared):
    """Cash is a conservative lower bound; maturities are not sale prices."""
    result = {'status': 'nao_avaliado', 'declared': declared or {},
              'profile_assessment': 'não avaliado: faltam objetivos, experiência e capacidade de suportar perdas; perfil declarado não aprova produtos',
              'note': 'Checagem factual de restrições declaradas; não é suitability nem recomendação.',
              'horizon': {'status': 'nao_avaliado'}, 'liquidity': {'status': 'nao_avaliado'}}
    if not declared:
        return result
    buckets = (doc.get('liquidity') or {}).get('buckets') or []
    if declared.get('horizon_date'):
        credit = next((b for b in buckets if b['bucket_id'] == 'credito_direto'), None)
        if credit is not None:
            lines = credit.get('lines') or []
            later = [r['line_no'] for r in lines if r.get('vencimento') and r['vencimento'] > declared['horizon_date']]
            missing = [r['line_no'] for r in lines if not r.get('vencimento')]
            result['horizon'] = {'status': 'a_conferir' if later else 'parcial', 'line_nos_after_horizon': later,
                                 'line_nos_without_maturity': missing,
                                 'note': 'Somente crédito direto: vencimentos do extrato após o horizonte; ausência de divergência não comprova adequação.'}
    if 'liquidity_brl' in declared:
        cash = next((b for b in buckets if b['bucket_id'] == 'caixa'), None)
        if cash is not None:
            available = Decimal(str(cash['value_brl']))
            required = Decimal(str(declared['liquidity_brl']))
            result['liquidity'] = {'status': 'coberto_em_caixa' if available >= required else 'nao_comprovado',
                                   'cash_brl': float(available), 'required_brl': float(required),
                                   'unproven_brl': float(max(required - available, Decimal(0))),
                                   'note': 'Somente caixa do extrato, na data de referência. Resgates e vendas não presumidos; saldo e necessidade devem ser reconfirmados.'}
    result['status'] = 'partial'
    return result
