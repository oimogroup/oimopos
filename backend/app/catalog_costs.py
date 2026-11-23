"""Current catalogue costing; historical batches and receipts keep their snapshots."""
from math import isfinite


def unit_cost(state, identity, branch_id=None):
    identity = str(identity)
    def number(value):
        try:
            result = float(value or 0)
            return result if isfinite(result) else 0
        except (ValueError, TypeError):
            return 0
    source = next((row for row in [*state.get('ingredients', []), *state.get('products', [])] if str(row['id']) == identity), {})
    fallback = number(source.get('averageCost'))
    logistics = state.get('logisticsState', {})
    costs, stocks = logistics.get('branchCosts', {}), logistics.get('branchStocks', {})
    if branch_id is not None:
        return number(costs.get(str(branch_id), {}).get(identity, fallback))
    quantity, value, known = 0, 0, []
    for branch in state.get('branches', []):
        if branch.get('status') not in {None, 'active'}:
            continue
        bid = str(branch['id'])
        amount = max(0, number(stocks.get(bid, {}).get(identity)))
        cost = number(costs.get(bid, {}).get(identity, fallback))
        quantity += amount
        value += amount * cost
        if cost > 0:
            known.append(cost)
    return value / quantity if quantity > 0 else sum(known) / len(known) if known else fallback
