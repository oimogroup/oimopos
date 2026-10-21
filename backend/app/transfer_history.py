"""Read-only, employee-scoped history of cooked-food transfers."""
from datetime import datetime, timezone
from math import isfinite


_FIELDS = (
    'id', 'number', 'servingDocumentId', 'batchNumber', 'name', 'weight',
    'status', 'createdAt', 'acceptedAt', 'actualWeight', 'rejectedAt',
    'rejectReason', 'canceledAt', 'cancelReason', 'reviewStatus',
    'reviewedAt', 'reviewNote',
)
_PEOPLE = ('actor', 'acceptedBy', 'rejectedBy', 'canceledBy', 'reviewedBy')


def _date(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if value.tzinfo is not None:
            return value
    except (ValueError, TypeError):
        pass
    return None


def _timestamp(row):
    value = _date(row.get('createdAt'))
    if value is not None:
        return value
    return datetime.min.replace(tzinfo=timezone.utc)


def _snapshot(value, fields=('id', 'name')):
    return {key: value[key] for key in fields if key in value} if isinstance(value, dict) else {}


def _same_actor(snapshot, actor_id):
    return (actor_id is not None and actor_id != '' and isinstance(snapshot, dict)
            and snapshot.get('id') is not None and str(snapshot['id']) == str(actor_id))


def _fallback(row, field, *values):
    if row.get(field) is None:
        for value in values:
            if value is not None:
                row[field] = value
                break


def shift_snapshots(shifts, branch_id, kind):
    """Copy only display fields; counts, cash totals and replay data stay private."""
    rows = [shift for shift in shifts if str(shift.get('branchId')) == str(branch_id)]
    rows.sort(key=lambda shift: (_timestamp({'createdAt': shift.get('openedAt')}), str(shift.get('id'))))
    result = []
    for number, shift in enumerate(rows, 1):
        if shift.get('id') is None:
            continue
        opened, closed = _date(shift.get('openedAt')), _date(shift.get('closedAt'))
        result.append({
            'id': shift['id'], 'kind': kind, 'branchId': str(branch_id),
            'number': shift.get('number') or (number if kind == 'production' else shift['id']),
            'employeeId': shift.get('employeeId'), 'employeeName': shift.get('employeeName') or '',
            'openedAt': opened.isoformat() if opened is not None else None,
            'closedAt': closed.isoformat() if closed is not None else None,
            'status': 'closed' if shift.get('closedAt') or shift.get('status') == 'closed' else 'open',
            **({key: shift.get(key) for key in ('registerId', 'registerName')} if kind == 'cash' else {}),
        })
    return list(reversed(result))


def _current_shift_id(shifts, user, kind):
    matches = [shift for shift in shifts if shift['status'] == 'open' and
               (str(shift.get('employeeId')) == str(user.get('id')) if kind == 'production' else
                user.get('register_id') is not None and str(shift.get('registerId')) == str(user['register_id']))]
    return matches[0]['id'] if len(matches) == 1 else None


def build_cash_shift_history(cash_shifts, branch_id, user):
    shifts = shift_snapshots(cash_shifts, branch_id, 'cash')
    if user.get('role') != 'owner' and str(user.get('branch_id')) != str(branch_id):
        shifts = []
    return {'shifts': shifts, 'currentShiftId': _current_shift_id(shifts, user, 'cash')}


def _event_shift(shifts, explicit_id, actor, timestamp, register_id=None):
    if explicit_id is not None:
        # An explicit event link is authoritative, including a cashier acting in
        # a shift opened by another employee. A broken link is not guessed anew.
        matches = [shift for shift in shifts if str(shift['id']) == str(explicit_id)]
    else:
        at = _date(timestamp)
        actor_id = actor.get('id') if isinstance(actor, dict) else None
        if at is None or actor_id is None:
            return None
        matches = []
        for shift in shifts:
            opened, closed = _date(shift['openedAt']), _date(shift['closedAt'])
            if opened is None or str(shift.get('employeeId')) != str(actor_id):
                continue
            if register_id is not None and str(shift.get('registerId')) != str(register_id):
                continue
            if shift['status'] == 'closed' and closed is None:
                continue
            # Inclusive boundaries deliberately leave overlapping legacy shifts
            # (including an exact close/open boundary) unassigned.
            if opened <= at and (closed is None or at <= closed):
                matches.append(shift)
    return dict(matches[0]) if len(matches) == 1 else None


def build_transfer_history(state, branch_id, user, cash_shifts=None):
    """Return transfer snapshots and their receipt outcomes without cost or requests."""
    actor_id = user.get('id')
    kind = 'production' if user.get('staff_role') == 'production' else 'cash'
    result = {'documents': [], 'actorId': actor_id, 'shifts': [], 'currentShiftId': None, 'currentShiftKind': kind}
    branch_id = str(branch_id)
    if user.get('role') != 'owner' and str(user.get('branch_id')) != branch_id:
        return result
    documents = [row for row in state.get('logisticsState', {}).get('custodyDocuments', [])
                 if str(row.get('branchId')) == branch_id]
    children = {}
    for row in sorted(documents, key=_timestamp):
        if row.get('sourceId') and row.get('kind') in {'acceptance', 'rejection', 'cancel', 'review'}:
            children.setdefault(str(row['sourceId']), {})[row['kind']] = row
    recipes = {str(row['id']): row.get('name') for row in state.get('recipes', [])}
    batches = {str(row['id']): row for row in state.get('logisticsState', {}).get('batches', [])
               if str(row.get('branchId')) == branch_id}
    see_all = user.get('role') == 'owner' or user.get('staff_role') == 'branch_manager'
    receiving = user.get('staff_role') in {'cashier', 'hall_admin'}
    production = shift_snapshots(state.get('logisticsState', {}).get('productionShifts', []), branch_id, 'production')
    cash = shift_snapshots(cash_shifts or [], branch_id, 'cash')
    role_shifts = production if kind == 'production' else cash
    result['currentShiftId'] = _current_shift_id(role_shifts, user, kind)

    for source in sorted(documents, key=_timestamp, reverse=True):
        if source.get('kind') != 'transfer':
            continue
        row = {key: source[key] for key in _FIELDS if key in source}
        for key in _PEOPLE:
            if isinstance(source.get(key), dict):
                row[key] = _snapshot(source[key])
        row['recipient'] = _snapshot(source.get('recipient'), ('id', 'kind', 'name', 'branchId'))
        linked = children.get(str(source.get('id')), {})
        acceptance = linked.get('acceptance', {})
        rejection = linked.get('rejection', {})
        cancellation = linked.get('cancel', {})
        batch = batches.get(str(source.get('batchId')), {})
        _fallback(row, 'name', recipes.get(str(source.get('recipeId', batch.get('recipeId')))), 'Блюдо')
        _fallback(row, 'batchNumber', batch.get('number'))
        _fallback(row, 'weight', acceptance.get('expectedWeight'))
        if not row.get('status'):
            outcomes = [(event, status) for event, status in
                        ((acceptance, 'accepted'), (rejection, 'rejected'), (cancellation, 'canceled')) if event]
            row['status'] = max(outcomes, key=lambda pair: _timestamp(pair[0]))[1] if outcomes else 'pending'
        for event, prefix in ((acceptance, 'accepted'), (rejection, 'rejected'), (cancellation, 'canceled')):
            if event:
                _fallback(row, prefix + 'At', event.get(prefix + 'At'), event.get('createdAt'))
                _fallback(row, prefix + 'By', _snapshot(event.get(prefix + 'By') or event.get('actor')))
        _fallback(row, 'actualWeight', acceptance.get('actualWeight'))
        _fallback(row, 'rejectReason', rejection.get('reason'))
        _fallback(row, 'cancelReason', cancellation.get('reason'))

        own_sent = _same_actor(row.get('actor'), actor_id)
        own_pending = row['status'] == 'pending' and (
            row['recipient'].get('kind') == 'branch_cashiers' or _same_actor(row['recipient'], actor_id))
        own_outcome = any(_same_actor(row.get(key), actor_id) for key in ('acceptedBy', 'rejectedBy'))
        if not (see_all or own_sent or (receiving and (own_pending or own_outcome))):
            continue

        row['productionShift'] = _event_shift(production, source.get('productionShiftId'), row.get('actor'), row.get('createdAt'))
        row['receivingShift'] = None
        if row['status'] in {'accepted', 'rejected'}:
            prefix, event = ('accepted', acceptance) if row['status'] == 'accepted' else ('rejected', rejection)
            explicit_id = source.get('receivingShiftId', source.get(prefix + 'ShiftId'))
            if explicit_id is None:
                explicit_id = event.get('shiftId')
            row['receivingShift'] = _event_shift(cash, explicit_id, row.get(prefix + 'By'), row.get(prefix + 'At'),
                source.get('receivingRegisterId', event.get('registerId')))

        for key in ('variance', 'reason'):
            _fallback(row, key, source.get(key), acceptance.get(key))
        if row.get('variance') is None and row.get('actualWeight') is not None and row.get('weight') is not None:
            try:
                difference = float(row['actualWeight']) - float(row['weight'])
                if isfinite(difference):
                    row['variance'] = round(difference, 6)
            except (ValueError, TypeError):
                pass
        if acceptance:
            review = children.get(str(acceptance.get('id')), {}).get('review', {})
            _fallback(row, 'reviewStatus', acceptance.get('status'),
                      {'approve': 'approved', 'reject': 'rejected'}.get(review.get('decision')))
            _fallback(row, 'reviewedAt', acceptance.get('reviewedAt'), review.get('reviewedAt'), review.get('createdAt'))
            reviewer = acceptance.get('reviewedBy') or review.get('reviewedBy') or review.get('actor')
            if isinstance(reviewer, dict):
                _fallback(row, 'reviewedBy', _snapshot(reviewer))
            _fallback(row, 'reviewNote', acceptance.get('reviewNote'), review.get('reviewNote'), review.get('reason'))
        result['documents'].append(row)
    referenced = {str(row[key]['id']) for row in result['documents']
                  for key in ('productionShift' if kind == 'production' else 'receivingShift',) if row.get(key)}
    result['shifts'] = [shift for shift in role_shifts if see_all or
                        str(shift.get('employeeId')) == str(actor_id) or str(shift['id']) in referenced or
                        str(shift['id']) == str(result['currentShiftId'])]
    return result
