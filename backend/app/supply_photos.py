"""Private original invoice photos, separate from operational JSON and its audit log."""
from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from .supply_import import normalize


class PhotoStorageError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def metadata(photo: dict) -> dict:
    url = f"/api/v1/pos/supplies/photos/{photo['id']}"
    return {"id": photo["id"], "fileName": photo["file_name"], "url": url,
            "downloadUrl": f"{url}?download=true", "usedDocumentIndexes": photo.get("used_indexes") or []}


def _actor_lock(connection, tenant_id, operator_id):
    # Serialize this operator's upload/recognition limits, including concurrent tabs.
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       (f"supply-photo:{tenant_id}:{operator_id}",))


def upload(connection, user: dict, operator: dict, encoded, file_name) -> dict:
    from .invoice_photo import prepare_photo

    prepared = prepare_photo(encoded, file_name)
    raw = encoded if isinstance(encoded, bytes) else base64.b64decode(encoded, validate=True)
    tenant_id, operator_id = str(user["tenant_id"]), operator["id"]
    _actor_lock(connection, tenant_id, operator_id)
    # Bound originals never expire. Abandoned previews disappear on subsequent uploads.
    connection.execute(
        """DELETE FROM supply_photos WHERE id IN (
           SELECT photo.id FROM supply_photos photo WHERE tenant_id = %s
           AND expires_at < CURRENT_TIMESTAMP
           AND NOT EXISTS (SELECT 1 FROM supply_photo_documents doc WHERE doc.photo_id = photo.id)
           FOR UPDATE SKIP LOCKED)""",
        (tenant_id,),
    )
    digest = hashlib.sha256(raw).hexdigest()
    # A retry or re-upload reuses the original, including already imported documents.
    existing = connection.execute(
        """SELECT id, file_name,
             (SELECT array_agg(document_index ORDER BY document_index) FROM supply_photo_documents doc WHERE doc.photo_id = photo.id) AS used_indexes
           FROM supply_photos photo
           WHERE tenant_id = %s AND branch_id = %s AND created_by = %s AND register_id = %s
             AND sha256 = %s AND (expires_at > CURRENT_TIMESTAMP
               OR EXISTS (SELECT 1 FROM supply_photo_documents doc WHERE doc.photo_id = photo.id))
           ORDER BY created_at DESC LIMIT 1""",
        (tenant_id, str(user["branch_id"]), operator_id, user["id"], digest),
    ).fetchone()
    if existing:
        return metadata(existing)
    recent = connection.execute(
        """SELECT count(*) AS count FROM supply_photos
           WHERE tenant_id = %s AND created_by = %s AND created_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'""",
        (tenant_id, operator_id),
    ).fetchone()
    if recent["count"] >= 30:
        raise PhotoStorageError("Загружено слишком много фотографий. Повторите позже", 429)
    photo = {"id": f"photo-{uuid4()}", "file_name": prepared["fileName"]}
    connection.execute(
        """INSERT INTO supply_photos
           (id, tenant_id, branch_id, created_by, register_id, file_name, content_type, content, sha256)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (photo["id"], tenant_id, str(user["branch_id"]), operator_id, user["id"],
         photo["file_name"], prepared["originalMimeType"], raw, digest),
    )
    return metadata(photo)


def get_photo(connection, tenant_id, photo_id, *, for_update=False, content=True):
    if not isinstance(photo_id, str) or not photo_id.startswith("photo-") or len(photo_id) > 80:
        raise PhotoStorageError("Фотография не найдена", 404)
    columns = "photo.*" if content else "photo.id, photo.tenant_id, photo.branch_id, photo.created_by, photo.register_id, photo.file_name, photo.expires_at, photo.recognition_result"
    photo = connection.execute(
        f"""SELECT {columns}, EXISTS (SELECT 1 FROM supply_photo_documents doc WHERE doc.photo_id = photo.id) AS linked,
              (SELECT array_agg(document_index ORDER BY document_index) FROM supply_photo_documents doc WHERE doc.photo_id = photo.id) AS used_indexes
            FROM supply_photos photo WHERE tenant_id = %s AND id = %s{' FOR UPDATE' if for_update else ''}""",
        (str(tenant_id), photo_id),
    ).fetchone()
    if not photo or (not photo["linked"] and photo["expires_at"] <= datetime.now(timezone.utc)):
        raise PhotoStorageError("Фотография не найдена или срок хранения черновика истёк", 404)
    return photo


def require_uploader(photo, user, operator):
    if (str(photo["branch_id"]) != str(user.get("branch_id"))
            or str(photo["created_by"]) != str(operator.get("id"))
            or str(photo["register_id"]) != str(user.get("register_id", user.get("id")))):
        raise PhotoStorageError("Фотография принадлежит другому сотруднику, кассе или заведению", 403)


def _matches(result: dict, state: dict, branch_id: str, used_indexes=None) -> dict:
    """Only unique exact normalized names are mapped; model IDs are never trusted."""
    result = deepcopy(result)
    result["usedDocumentIndexes"] = used_indexes or []
    items = {}
    for item in [*state.get("ingredients", []), *state.get("products", [])]:
        items.setdefault(normalize(item.get("name", "")), []).append(item)
    suppliers = {}
    for supplier in state.get("suppliers", []):
        if supplier.get("status") == "active" and branch_id in supplier.get("locations", []):
            suppliers.setdefault(normalize(supplier.get("name", "")), []).append(supplier)
    for index, document in enumerate(result.get("documents", [])):
        document["documentIndex"] = index
        document["supplierId"] = None
        matches = suppliers.get(normalize(document.get("supplierName", "")), [])
        if len(matches) == 1:
            document["supplierId"] = matches[0]["id"]
        for row in document.get("rows", []):
            row["itemId"] = None
            matches = items.get(normalize(row.get("name", "")), [])
            if len(matches) == 1:
                row["itemId"] = str(matches[0]["id"])
    return result


def recognize(connection, user, operator, photo_id, state, settings):
    from .invoice_photo import PhotoInvoiceError, prepare_photo, recognize_invoice

    _actor_lock(connection, str(user["tenant_id"]), operator["id"])
    photo = get_photo(connection, user["tenant_id"], photo_id, for_update=True)
    require_uploader(photo, user, operator)
    if photo.get("recognition_result") is not None:
        return _matches(photo["recognition_result"], state, str(user["branch_id"]), photo.get("used_indexes")), 200
    if not getattr(settings, "openai_api_key", "") or not getattr(settings, "invoice_photo_model", ""):
        raise PhotoStorageError("Распознавание фото не настроено. Добавьте OPENAI_API_KEY и INVOICE_PHOTO_MODEL на сервере. Фото можно сохранить с поставкой вручную", 503)
    attempted = photo.get("recognition_attempted_at")
    if attempted and attempted > datetime.now(timezone.utc) - timedelta(seconds=60) and photo.get("recognition_error"):
        return {"detail": photo["recognition_error"]}, photo.get("recognition_error_status") or 502
    recent = connection.execute(
        """SELECT coalesce(sum(recognition_attempts), 0) AS count FROM supply_photos
           WHERE tenant_id = %s AND created_by = %s AND recognition_attempted_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'""",
        (str(user["tenant_id"]), operator["id"]),
    ).fetchone()
    if recent["count"] >= 10:
        raise PhotoStorageError("Лимит распознавания фотографий исчерпан. Повторите через час", 429)
    connection.execute(
        """UPDATE supply_photos SET recognition_attempts = recognition_attempts + 1,
           recognition_attempted_at = CURRENT_TIMESTAMP WHERE tenant_id = %s AND id = %s""",
        (str(user["tenant_id"]), photo_id),
    )
    try:
        prepared = prepare_photo(bytes(photo["content"]), photo["file_name"])
        result = recognize_invoice(prepared, settings.openai_api_key, settings.invoice_photo_model)
    except Exception as error:
        # Never expose provider responses, credentials, or traceback text.
        detail = str(error) if isinstance(error, PhotoInvoiceError) else "Не удалось распознать фотографию. Попробуйте позже"
        status_code = getattr(error, "status_code", 502) if isinstance(error, PhotoInvoiceError) else 502
        connection.execute(
            "UPDATE supply_photos SET recognition_error = %s, recognition_error_status = %s WHERE tenant_id = %s AND id = %s",
            (detail, status_code, str(user["tenant_id"]), photo_id),
        )
        # Returning an HTTP error body lets the request commit this attempt and its cooldown.
        return {"detail": detail}, status_code
    connection.execute(
        """UPDATE supply_photos SET recognition_result = %s, recognition_error = NULL,
           recognition_error_status = NULL WHERE tenant_id = %s AND id = %s""",
        (Jsonb(result), str(user["tenant_id"]), photo_id),
    )
    return _matches(result, state, str(user["branch_id"]), photo.get("used_indexes")), 200


def bind_supply(connection, state, user, payload, supply_id):
    """Called inside the existing stock/event transaction after supply.create."""
    photo_id = payload.get("photoId")
    if not photo_id:
        return
    photo = get_photo(connection, user["tenant_id"], photo_id, for_update=True, content=False)
    require_uploader(photo, user, user)
    index = payload.get("photoDocumentIndex", 0)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 20:
        raise PhotoStorageError("Выберите накладную на фотографии")
    documents = (photo.get("recognition_result") or {}).get("documents", [])
    if index >= (len(documents) if documents else 1):
        raise PhotoStorageError("Выбранной накладной нет на фотографии")
    existing = connection.execute(
        "SELECT supply_id FROM supply_photo_documents WHERE tenant_id = %s AND photo_id = %s AND document_index = %s",
        (str(user["tenant_id"]), photo_id, index),
    ).fetchone()
    if existing and existing["supply_id"] != supply_id:
        raise PhotoStorageError("Эта накладная с фотографии уже сохранена в поставках", 409)
    supply = next((entry for entry in state["logisticsState"]["supplies"] if entry.get("id") == supply_id), None)
    if not supply or str(supply["branchId"]) != str(photo["branch_id"]):
        raise PhotoStorageError("Фотография относится к другому заведению", 403)
    if not existing:
        connection.execute(
            "INSERT INTO supply_photo_documents (tenant_id, photo_id, document_index, supply_id) VALUES (%s, %s, %s, %s)",
            (str(user["tenant_id"]), photo_id, index, supply_id),
        )
    supply["photo"] = {key: value for key, value in metadata(photo).items() if key != "usedDocumentIndexes"}
    supply["photo"]["documentIndex"] = index
