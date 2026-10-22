"""Original-photo persistence, scoped access and atomic supplier-receipt linking."""
import base64
import io
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import psycopg
from fastapi import HTTPException
from PIL import Image
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from starlette.requests import Request

from app import invoice_photo, main, supply_photos
from app.schemas import WorkspaceActionInput
from app.workspace import default_state


TERMINAL = {"id": 90, "role": "branch", "staff_role": "pos_terminal", "tenant_id": "tenant-a", "branch_id": "b1"}
OPERATOR = {"id": 91, "role": "branch", "staff_role": "cashier", "login": "cashier", "display_name": "Кассир",
            "access_permissions": {"posAccess": True, "posSupply": True}}
ACTOR = {**TERMINAL, **OPERATOR, "register_id": TERMINAL["id"], "shift_id": 17}
SETTINGS = SimpleNamespace(openai_api_key="fake-unit-test-key", invoice_photo_model="test-model")
REQUEST = Request({"type": "http", "method": "POST", "headers": [(b"x-ashkana-client", b"pos")]})


def original_png():
    stream = io.BytesIO()
    Image.new("RGB", (12, 16), "white").save(stream, format="PNG")
    return stream.getvalue()


class MemoryConnection:
    """SQL boundary double: rows are copied and transactions roll back on failure."""
    def __init__(self):
        self.photos = {}
        self.documents = {}
        self.queries = []

    @contextmanager
    def transaction(self):
        before = deepcopy((self.photos, self.documents))
        try:
            yield self
        except Exception:
            self.photos, self.documents = before
            raise

    def execute(self, query, params=()):
        query = " ".join(query.split())
        self.queries.append((query, params))
        result = None
        now = datetime.now(timezone.utc)
        if query.startswith("SELECT pg_advisory"):
            pass
        elif query.startswith("DELETE FROM supply_photos"):
            self.photos = {key: row for key, row in self.photos.items()
                           if row["tenant_id"] != params[0] or row["expires_at"] >= now
                           or any(key == photo_id for photo_id, _ in self.documents)}
        elif query.startswith("SELECT count(*)"):
            result = {"count": sum(row["tenant_id"] == params[0] and row["created_by"] == params[1]
                                   and row["created_at"] > now - timedelta(hours=1) for row in self.photos.values())}
        elif query.startswith("SELECT coalesce(sum(recognition_attempts)"):
            result = {"count": sum(row.get("recognition_attempts", 0) for row in self.photos.values()
                                   if row["tenant_id"] == params[0] and row["created_by"] == params[1]
                                   and (row.get("recognition_attempted_at") or now - timedelta(days=1)) > now - timedelta(hours=1))}
        elif query.startswith("SELECT id, file_name"):
            for row in self.photos.values():
                if (row["tenant_id"], row["branch_id"], row["created_by"], row["register_id"], row["sha256"]) == params:
                    result = self._photo(row)
                    if result["linked"] or row["expires_at"] > now:
                        break
                    result = None
        elif query.startswith("INSERT INTO supply_photos"):
            keys = ("id", "tenant_id", "branch_id", "created_by", "register_id", "file_name", "content_type", "content", "sha256")
            row = dict(zip(keys, params))
            row.update(created_at=now, expires_at=now + timedelta(hours=24), recognition_result=None,
                       recognition_attempts=0, recognition_attempted_at=None, recognition_error=None)
            self.photos[row["id"]] = row
        elif query.startswith("SELECT photo."):
            row = self.photos.get(params[1])
            result = self._photo(row) if row and row["tenant_id"] == params[0] else None
        elif query.startswith("UPDATE supply_photos SET recognition_attempts"):
            row = self.photos[params[1]]
            row["recognition_attempts"] += 1
            row["recognition_attempted_at"] = now
        elif query.startswith("UPDATE supply_photos SET recognition_error"):
            row = self.photos[params[-1]]
            row.update(recognition_error=params[0], recognition_error_status=params[1])
        elif query.startswith("UPDATE supply_photos SET recognition_result"):
            self.photos[params[-1]].update(recognition_result=deepcopy(params[0].obj), recognition_error=None)
        elif query.startswith("SELECT supply_id FROM supply_photo_documents"):
            supply_id = self.documents.get((params[1], params[2]))
            result = {"supply_id": supply_id} if supply_id else None
        elif query.startswith("INSERT INTO supply_photo_documents"):
            assert (params[1], params[2]) not in self.documents
            self.documents[(params[1], params[2])] = params[3]
        elif query.startswith("UPDATE operational_state") or query.startswith("INSERT INTO operational_events"):
            pass
        else:
            raise AssertionError(f"Unexpected SQL: {query}")
        return SimpleNamespace(fetchone=lambda: deepcopy(result))

    def _photo(self, row):
        indexes = sorted(index for photo_id, index in self.documents if photo_id == row["id"])
        return {**row, "linked": bool(indexes), "used_indexes": indexes}


@pytest.fixture
def stored():
    connection = MemoryConnection()
    raw = original_png()
    uploaded = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "накладная.png")
    return connection, uploaded, raw


def test_original_bytes_and_mime_survive_ai_normalization_and_upload_retry(stored):
    connection, uploaded, raw = stored
    photo = connection.photos[uploaded["id"]]
    assert photo["content"] == raw
    assert photo["content_type"] == "image/png"
    assert base64.b64decode(invoice_photo.prepare_photo(raw, "накладная.png")["content"]) != raw
    assert "content" not in uploaded and "file" not in uploaded
    retry = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "duplicate.png")
    assert retry["id"] == uploaded["id"] and len(connection.photos) == 1


def test_pending_photo_tenant_scope_expiry_and_cleanup(stored):
    connection, uploaded, raw = stored
    with pytest.raises(supply_photos.PhotoStorageError) as denied:
        supply_photos.get_photo(connection, "another-tenant", uploaded["id"])
    assert denied.value.status_code == 404
    connection.photos[uploaded["id"]]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(supply_photos.PhotoStorageError):
        supply_photos.get_photo(connection, TERMINAL["tenant_id"], uploaded["id"])
    replacement = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "new.png")
    assert replacement["id"] != uploaded["id"] and uploaded["id"] not in connection.photos


@pytest.mark.parametrize("user,operator", [
    ({**TERMINAL, "branch_id": "b2"}, OPERATOR),
    ({**TERMINAL, "id": 100}, OPERATOR),
    (TERMINAL, {**OPERATOR, "id": 100}),
])
def test_pending_photo_is_bound_to_branch_register_and_operator(stored, user, operator):
    connection, uploaded, _ = stored
    with pytest.raises(supply_photos.PhotoStorageError) as denied:
        supply_photos.require_uploader(connection.photos[uploaded["id"]], user, operator)
    assert denied.value.status_code == 403


def test_bind_distinct_documents_once_and_reupload_returns_used_indexes(stored):
    connection, uploaded, raw = stored
    identity = uploaded["id"]
    connection.photos[identity]["recognition_result"] = {"documents": [{}, {}]}
    state = {"logisticsState": {"supplies": [{"id": f"s{i}", "branchId": "b1"} for i in range(3)]}}
    for index in (0, 1):
        supply_photos.bind_supply(connection, state, ACTOR, {"photoId": identity, "photoDocumentIndex": index}, f"s{index}")
    assert len(connection.documents) == 2
    assert state["logisticsState"]["supplies"][1]["photo"]["documentIndex"] == 1
    with pytest.raises(supply_photos.PhotoStorageError) as duplicate:
        supply_photos.bind_supply(connection, state, ACTOR, {"photoId": identity, "photoDocumentIndex": 1}, "s2")
    assert duplicate.value.status_code == 409
    connection.photos[identity]["expires_at"] = datetime.now(timezone.utc) - timedelta(days=1)
    assert supply_photos.get_photo(connection, TERMINAL["tenant_id"], identity)["linked"]
    retry = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "new.png")
    assert retry["id"] == identity and retry["usedDocumentIndexes"] == [0, 1]


@pytest.mark.parametrize("index", [-1, 1, 20, "0", True])
def test_manual_photo_accepts_only_document_zero(stored, index):
    connection, uploaded, _ = stored
    state = {"logisticsState": {"supplies": [{"id": "s1", "branchId": "b1"}]}}
    with pytest.raises(supply_photos.PhotoStorageError):
        supply_photos.bind_supply(connection, state, ACTOR, {"photoId": uploaded["id"], "photoDocumentIndex": index}, "s1")
    assert not connection.documents and "photo" not in state["logisticsState"]["supplies"][0]


def test_catalog_matching_rejects_ambiguity_and_suppliers_from_another_branch():
    state = {"ingredients": [{"id": "a", "name": "Молоко"}, {"id": "b", "name": "МОЛОКО"}, {"id": "c", "name": " Рис "}],
             "suppliers": [{"id": "wrong", "name": "Фермер", "status": "active", "locations": ["b2"]},
                           {"id": "right", "name": "Склад", "status": "active", "locations": ["b1"]}]}
    result = {"documents": [{"supplierName": "Фермер", "supplierId": "forged", "rows": [{"name": "молоко", "itemId": "forged"}]},
                            {"supplierName": "  СКЛАД ", "rows": [{"name": "РИС"}, {"name": "Рисовая мука"}]}]}
    matched = supply_photos._matches(result, state, "b1")
    assert matched["documents"][0]["supplierId"] is None
    assert matched["documents"][0]["rows"][0]["itemId"] is None
    assert matched["documents"][1]["supplierId"] == "right"
    assert [row["itemId"] for row in matched["documents"][1]["rows"]] == ["c", None]
    assert result["documents"][0]["supplierId"] == "forged"


def test_successful_recognition_is_cached_and_matches_refreshed_catalog(stored, monkeypatch):
    connection, uploaded, _ = stored
    calls = []
    def provider(*args):
        calls.append(args)
        return {"documents": [{"supplierName": "", "rows": [{"name": "Рис", "quantity": 2, "price": 100}]}]}
    monkeypatch.setattr(invoice_photo, "recognize_invoice", provider)
    result, status = supply_photos.recognize(connection, TERMINAL, OPERATOR, uploaded["id"], {}, SETTINGS)
    assert status == 200 and result["documents"][0]["rows"][0]["itemId"] is None
    refreshed = {"ingredients": [{"id": "rice", "name": "Рис"}]}
    again, _ = supply_photos.recognize(connection, TERMINAL, OPERATOR, uploaded["id"], refreshed, SETTINGS)
    assert again["documents"][0]["rows"][0]["itemId"] == "rice"
    assert len(calls) == 1 and connection.photos[uploaded["id"]]["recognition_attempts"] == 1


def test_missing_key_does_not_prevent_photo_upload_or_consume_attempt(stored):
    connection, uploaded, _ = stored
    with pytest.raises(supply_photos.PhotoStorageError) as disabled:
        supply_photos.recognize(connection, TERMINAL, OPERATOR, uploaded["id"], {}, SimpleNamespace())
    assert disabled.value.status_code == 503
    assert connection.photos[uploaded["id"]]["recognition_attempts"] == 0


def test_provider_failure_is_sanitized_and_retry_cooldown_avoids_another_charge(stored, monkeypatch):
    connection, uploaded, _ = stored
    calls = []
    def provider(*args):
        calls.append(1)
        raise RuntimeError("secret=do-not-return-this")
    monkeypatch.setattr(invoice_photo, "recognize_invoice", provider)
    for _ in range(2):
        result, status = supply_photos.recognize(connection, TERMINAL, OPERATOR, uploaded["id"], {}, SETTINGS)
        assert status == 502 and "secret" not in result["detail"]
    assert len(calls) == 1 and connection.photos[uploaded["id"]]["recognition_attempts"] == 1


def test_recognition_rate_limit(stored):
    connection, uploaded, _ = stored
    connection.photos[uploaded["id"]].update(recognition_attempts=10, recognition_attempted_at=datetime.now(timezone.utc))
    with pytest.raises(supply_photos.PhotoStorageError) as limited:
        supply_photos.recognize(connection, TERMINAL, OPERATOR, uploaded["id"], {}, SETTINGS)
    assert limited.value.status_code == 429


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setattr(main, "_check_origin", lambda request: None)
    monkeypatch.setattr(main, "_current_pos_operator", lambda *args: OPERATOR)
    monkeypatch.setattr(main, "_current_pos_shift", lambda *args: {"id": 17})


def test_download_returns_exact_original_and_cannot_cross_branches(stored, authorized, monkeypatch):
    connection, uploaded, raw = stored
    response = main.get_supply_photo(uploaded["id"], True, "pin", TERMINAL, connection)
    assert response.body == raw and response.media_type == "image/png"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    with pytest.raises(HTTPException) as denied:
        main.get_supply_photo(uploaded["id"], False, "pin", {**TERMINAL, "branch_id": "b2"}, connection)
    assert denied.value.status_code == 404
    monkeypatch.setattr(main, "_current_pos_operator", lambda *args: {**OPERATOR, "access_permissions": {"posAccess": True}})
    with pytest.raises(HTTPException) as denied:
        main.get_supply_photo(uploaded["id"], False, "pin", TERMINAL, connection)
    assert denied.value.status_code == 403


def test_linked_original_is_visible_to_owner_and_branch_history_but_not_unrelated_staff(stored, authorized, monkeypatch):
    connection, uploaded, raw = stored
    state = {"logisticsState": {"supplies": [{"id": "s1", "branchId": "b1"}]}}
    supply_photos.bind_supply(connection, state, ACTOR, {"photoId": uploaded["id"]}, "s1")
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: {"payload": state})
    owner = {"id": 1, "role": "owner", "tenant_id": TERMINAL["tenant_id"]}
    assert main.get_supply_photo(uploaded["id"], True, None, owner, connection).body == raw
    manager = {**ACTOR, "staff_role": "branch_manager", "access_permissions": {"inventory": True}}
    assert main.get_supply_photo(uploaded["id"], True, None, manager, connection).body == raw
    with pytest.raises(HTTPException):
        main.get_supply_photo(uploaded["id"], True, None, {**ACTOR, "access_permissions": {"posAccess": True}}, connection)


def test_receipt_transaction_binds_photo_without_copying_bytes_to_state_or_audit(stored, authorized, monkeypatch):
    connection, uploaded, raw = stored
    state = default_state()
    row = {"payload": state, "version": 4}
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: row)
    command = WorkspaceActionInput(action="supply.create", payload={
        "supplierId": "supplier-frunze", "items": [{"itemId": "rice", "quantity": 1, "price": 50}],
        "photoId": uploaded["id"], "photoDocumentIndex": 0, "requestId": "save-photo-receipt",
    })
    response = main.workspace_action(command, REQUEST, TERMINAL, "pin", connection)
    supply = state["logisticsState"]["supplies"][0]
    assert supply["id"] == response["entity"]["id"]
    assert supply["photo"]["id"] == uploaded["id"]
    assert connection.documents[(uploaded["id"], 0)] == supply["id"]
    assert supply["requestPayload"] == command.payload
    assert base64.b64encode(raw).decode() not in str(state)
    writes = [(query, params) for query, params in connection.queries if "operational_" in query]
    assert len(writes) == 2 and all(base64.b64encode(raw).decode() not in str(params) for _, params in writes)
    replay = main.workspace_action(command, REQUEST, TERMINAL, "pin", connection)
    assert replay["entity"] == response["entity"] and len(connection.documents) == 1


def test_rejected_photo_binding_never_persists_stock_or_audit(stored, authorized, monkeypatch):
    connection, uploaded, _ = stored
    connection.photos[uploaded["id"]]["created_by"] = 777
    state = default_state()
    monkeypatch.setattr(main, "_workspace_row", lambda *args, **kwargs: {"payload": deepcopy(state), "version": 4})
    command = WorkspaceActionInput(action="supply.create", payload={
        "supplierId": "supplier-frunze", "items": [{"itemId": "rice", "quantity": 1, "price": 50}],
        "photoId": uploaded["id"], "requestId": "rejected-photo-receipt",
    })
    with pytest.raises(HTTPException) as denied:
        main.workspace_action(command, REQUEST, TERMINAL, "pin", connection)
    assert denied.value.status_code == 403
    assert not connection.documents
    assert not any("UPDATE operational_state" in query or "INSERT INTO operational_events" in query for query, _ in connection.queries)


def test_photo_browser_requests_choose_terminal_cookie_without_admin_fallback(monkeypatch):
    from app.security import token_hash

    request = Request({"type": "http", "path": "/api/v1/pos/supplies/photos/photo-test", "headers": []})
    accounts = {
        token_hash("admin-cookie"): {"id": 1, "role": "owner", "tenant_id": "admin-tenant", "session_id": 1},
        token_hash("terminal-cookie"): {**TERMINAL, "session_id": 2},
    }
    class Connection:
        def execute(self, query, params):
            if "FROM auth_sessions" in query:
                return SimpleNamespace(fetchone=lambda: accounts.get(params[0]))
            return SimpleNamespace()
    connection = Connection()
    monkeypatch.setattr(main, "_validate_tenant_access", lambda user, **kw: None)
    monkeypatch.setattr(main, "_workspace_row", lambda *args: {"payload": {"branches": [{"id": "b1", "status": "active"}]}})
    assert main._supply_photo_user(request, "pos", "admin-cookie", "terminal-cookie", connection)["tenant_id"] == "tenant-a"
    assert main._supply_photo_user(request, "", "admin-cookie", "terminal-cookie", connection)["tenant_id"] == "admin-tenant"
    with pytest.raises(HTTPException) as missing:
        main._supply_photo_user(request, "pos", "admin-cookie", None, connection)
    assert missing.value.status_code == 401
    assert "x-ashkana-client" not in request.headers


def test_locked_terminal_cannot_view_even_its_own_photo(stored, monkeypatch):
    connection, uploaded, _ = stored
    def locked(*args):
        raise HTTPException(423, "Введите личный PIN")
    monkeypatch.setattr(main, "_current_pos_operator", locked)
    before = len(connection.queries)
    with pytest.raises(HTTPException) as denied:
        main.get_supply_photo(uploaded["id"], False, None, TERMINAL, connection)
    assert denied.value.status_code == 423 and len(connection.queries) == before


@pytest.fixture
def photo_database():
    dsn = os.environ.get("SUPPLY_PHOTO_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Opt-in PostgreSQL tests use temporary tables and always roll back")
    connection = psycopg.connect(dsn, row_factory=dict_row)
    try:
        connection.execute("CREATE TEMP TABLE tenants (id TEXT PRIMARY KEY) ON COMMIT DROP")
        for table in ("supply_photos", "supply_photo_documents"):
            connection.execute(f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP")
        connection.execute("ALTER TABLE supply_photos ADD FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE")
        connection.execute("ALTER TABLE supply_photo_documents ADD FOREIGN KEY (tenant_id, photo_id) REFERENCES supply_photos(tenant_id, id) ON DELETE CASCADE")
        connection.execute("CREATE TEMP TABLE operational_state (tenant_id TEXT PRIMARY KEY, version BIGINT, payload JSONB, updated_at TIMESTAMPTZ) ON COMMIT DROP")
        connection.execute("""CREATE TEMP TABLE operational_events (
            tenant_id TEXT, state_version BIGINT, actor_user_id BIGINT, actor_login TEXT, actor_role TEXT,
            branch_id TEXT, action TEXT, entity_type TEXT, entity_id TEXT, payload JSONB) ON COMMIT DROP""")
        connection.execute("INSERT INTO tenants (id) VALUES ('tenant-a'), ('tenant-b')")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_postgres_preserves_originals_links_uniquely_and_cascades_only_tenant_data(photo_database):
    connection = photo_database
    raw = original_png()
    uploaded = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "original.png")
    state = {"logisticsState": {"supplies": [{"id": "s1", "branchId": "b1"}]}}
    supply_photos.bind_supply(connection, state, ACTOR, {"photoId": uploaded["id"]}, "s1")
    assert bytes(supply_photos.get_photo(connection, "tenant-a", uploaded["id"], for_update=True)["content"]) == raw
    retry = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(raw).decode(), "retry.png")
    assert retry["usedDocumentIndexes"] == [0] and retry["id"] == uploaded["id"]
    with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
        connection.execute("INSERT INTO supply_photo_documents (tenant_id, photo_id, document_index, supply_id) VALUES (%s, %s, 0, 's2')", ("tenant-a", uploaded["id"]))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
        connection.execute("INSERT INTO supply_photo_documents (tenant_id, photo_id, document_index, supply_id) VALUES (%s, %s, 1, 's2')", ("tenant-b", uploaded["id"]))
    connection.execute("DELETE FROM tenants WHERE id = 'tenant-b'")
    assert connection.execute("SELECT count(*) AS count FROM supply_photos").fetchone()["count"] == 1
    connection.execute("DELETE FROM tenants WHERE id = 'tenant-a'")
    assert connection.execute("SELECT count(*) AS count FROM supply_photos").fetchone()["count"] == 0
    assert connection.execute("SELECT count(*) AS count FROM supply_photo_documents").fetchone()["count"] == 0


def test_postgres_audit_failure_rolls_back_link_and_inventory_as_one_transaction(photo_database, authorized):
    connection = photo_database
    uploaded = supply_photos.upload(connection, TERMINAL, OPERATOR, base64.b64encode(original_png()).decode(), "original.png")
    state = default_state()
    connection.execute("INSERT INTO operational_state (tenant_id, version, payload) VALUES ('tenant-a', 4, %s)", (Jsonb(state),))
    connection.execute("ALTER TABLE operational_events ADD CHECK (action <> 'supply.create')")
    command = WorkspaceActionInput(action="supply.create", payload={
        "supplierId": "supplier-frunze", "items": [{"itemId": "rice", "quantity": 1, "price": 50}],
        "photoId": uploaded["id"], "requestId": "rollback-photo-receipt",
    })
    with pytest.raises(psycopg.errors.CheckViolation):
        main.workspace_action(command, REQUEST, TERMINAL, "pin", connection)
    saved = main._workspace_row(connection, "tenant-a")
    assert saved["version"] == 4 and saved["payload"] == state
    assert connection.execute("SELECT count(*) AS count FROM supply_photo_documents").fetchone()["count"] == 0
    assert connection.execute("SELECT count(*) AS count FROM operational_events").fetchone()["count"] == 0
    assert supply_photos.get_photo(connection, "tenant-a", uploaded["id"])["linked"] is False
