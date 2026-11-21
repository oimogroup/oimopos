"""Catalog edit revisions, durable operation identity and small database writes."""
from hashlib import sha256
from copy import deepcopy
import json

from fastapi import HTTPException
from psycopg.types.json import Jsonb

ACTIONS = {'recipe.upsert', 'recipe.group.upsert', 'preparation.upsert', 'ingredient.upsert', 'product.upsert', 'product.group.upsert', 'supplier.upsert', 'category.upsert'}
COLLECTIONS = {'recipe.upsert':'recipes', 'recipe.group.upsert':'recipes', 'preparation.upsert':'preparations', 'ingredient.upsert':'ingredients', 'product.upsert':'products', 'product.group.upsert':'products', 'supplier.upsert':'suppliers'}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def category_rows(state, kind):
    if kind != 'ingredient':
        from .workspace import _menu_category_registry
        clone = {key: deepcopy(state.get(key, [])) for key in ('recipes', 'products', 'menuCategories', 'recipeCategories', 'productCategories')}
        return _menu_category_registry(clone)
    result, seen = [], set()
    covers = {key.strip().casefold(): value for key, value in (state.get('ingredientCategoryCovers') or {}).items()}
    sources = [*(state.get('ingredientCategories') or []), *[row.get('category') or 'Без категории' for row in state.get('ingredients', [])]]
    for raw in sources:
        name = str(raw.get('name', '') if isinstance(raw, dict) else raw).strip()
        if name and name.casefold() not in seen:
            result.append({'name':name, **covers.get(name.casefold(), {})})
            seen.add(name.casefold())
    return result


def fingerprint(state, rows):
    groups = {str(key) for row in rows for key in row.get('modifierSetIds', [])}
    return digest([rows, [group for group in state.get('modifierSets', []) if str(group['id']) in groups]])


def revision(state, action, identity, *, kind=None):
    if action == 'category.upsert':
        row = next((row for row in category_rows(state, kind) if row['name'].casefold() == str(identity).strip().casefold()), None)
        return digest(row) if row else 'new'
    collection = COLLECTIONS[action]
    row = next((r for r in state.get(collection, []) if str(r['id']) == str(identity)), None)
    if row is None:
        return 'new'
    rows = [row]
    if collection in {'recipes', 'products'}:
        root = row.get('parentId') or row['id']
        rows = [r for r in state.get(collection, []) if str(r['id']) == str(root) or str(r.get('parentId')) == str(root)]
    return fingerprint(state, rows)


def decorate(state, output):
    for collection in ('recipes', 'products', 'preparations', 'ingredients', 'suppliers'):
        families = {}
        grouped = collection in {'recipes', 'products'}
        for row in state.get(collection, []):
            families.setdefault(str((row.get('parentId') if grouped else None) or row['id']), []).append(row)
        revisions = {key: fingerprint(state, rows) for key, rows in families.items()}
        for row in output.get(collection, []):
            row['editRevision'] = revisions[str((row.get('parentId') if grouped else None) or row['id'])]
    output['categoryRevisions'] = {kind: {row['name']: digest(row) for row in category_rows(state, kind)} for kind in ('menu', 'ingredient')}


def operation(connection, tenant, actor, request_id):
    return connection.execute(
        """SELECT action, entity_type, entity_id, payload FROM operational_events
           WHERE tenant_id = %s AND actor_user_id = %s
             AND action = ANY(%s)
             AND payload ? '_catalogSave'
             AND payload->'_catalogSave'->>'requestId' = %s
           ORDER BY state_version DESC LIMIT 1""", (tenant, actor, sorted(ACTIONS), request_id),
    ).fetchone()


def check_revision(state, command):
    identity = command.payload.get('id')
    if command.action == 'category.upsert':
        identity = command.payload.get('originalName') or command.payload.get('name')
    if command.expected_revision is not None and revision(state, command.action, identity, kind=command.payload.get('kind')) != command.expected_revision:
        raise HTTPException(409, 'Эта карточка уже изменена в другой вкладке. Скопируйте свои изменения и заново откройте карточку. Ваши данные не перезаписаны.')


def changes(before, after, path=()):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = [(path + (key,), None, True) for key in before.keys() - after.keys()]
        for key, value in after.items():
            result.extend(changes(before[key], value, path + (key,)) if key in before else [(path + (key,), value, False)])
        return result
    if isinstance(before, list) and isinstance(after, list) and len(after) >= len(before):
        # Keep indexes stable; append new rows without re-sending existing photos.
        if all(isinstance(a, dict) and isinstance(b, dict) and a.get('id') == b.get('id') for a, b in zip(before, after)):
            result = []
            for index, value in enumerate(after):
                result.extend(changes(before[index], value, path + (str(index),)) if index < len(before) else [(path + (str(index),), value, False)])
            return result
    return [(path, after, False)]


def update(connection, tenant, version, before, after):
    delta = changes(before, after)
    if len(delta) > 100:
        connection.execute('UPDATE operational_state SET version = %s, payload = %s, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s', (version, Jsonb(after), tenant))
        return
    expression, params = 'payload', []
    for path, value, remove in delta:
        if remove:
            expression = f'({expression} #- %s::text[])'
            params.append(list(path))
        else:
            expression = f'jsonb_set({expression}, %s::text[], %s::jsonb, true)'
            params.extend([list(path), Jsonb(value)])
    connection.execute(f'UPDATE operational_state SET version = %s, payload = {expression}, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s', [version, *params, tenant])


def audit_payload(payload):
    # Photos already live in the catalog. Do not copy them into every audit event.
    def clean(value):
        if isinstance(value, dict):
            return {key: ('[фото в каталоге]' if key == 'image' and item else clean(item)) for key, item in value.items() if key not in {'password', 'rawComponents', 'editRevision', '_catalogSave'}}
        return [clean(item) for item in value] if isinstance(value, list) else value
    return clean(payload)
