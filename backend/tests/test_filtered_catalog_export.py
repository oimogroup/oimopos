import pytest
from fastapi.testclient import TestClient

from app import main, technical_card_report
from app.workspace import default_state


@pytest.mark.parametrize(('params', 'recipe_ids', 'preparation_ids'), [
    ({}, [201, 203, 205], ['pf-1', 'pf-2']),
    ([('kind', 'recipes'), ('item_id', '203')], [203], []),
    ([('kind', 'preparations'), ('item_id', 'pf-2')], [], ['pf-2']),
    ([('kind', 'recipes'), ('item_id', 'other-tenant-id')], [], []),
])
def test_export_uses_requested_kind_and_visible_ids(monkeypatch, params, recipe_ids, preparation_ids):
    state = default_state()
    state['recipes'] = [{'id': value} for value in [201, 203, 205]]
    state['preparations'] = [{'id': value} for value in ['pf-1', 'pf-2']]
    captured = {}
    def workbook(recipes, preparations, ingredients):
        captured['recipes'] = [row['id'] for row in recipes]
        captured['preparations'] = [row['id'] for row in preparations]
        return 'xlsx'
    monkeypatch.setattr(technical_card_report, 'workbook', workbook)
    monkeypatch.setattr(main, '_workspace_row', lambda connection, tenant: {'payload': state})
    overrides = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[main.current_user] = lambda: {'role': 'owner', 'tenant_id': 'tenant-a'}
    main.app.dependency_overrides[main.get_connection] = lambda: object()
    try:
        response = TestClient(main.app).get('/api/v1/technical-cards/export', params=params)
        assert response.status_code == 200
        assert captured == {'recipes': recipe_ids, 'preparations': preparation_ids}
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(overrides)
