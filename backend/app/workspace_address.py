"""Company workspace subdomains, separate from the internal tenant/login slug."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit


RESERVED = {
    "www", "api", "admin", "login", "account", "billing", "pos", "static",
    "assets", "platform", "support", "mail", "help", "docs", "status", "cdn",
}
CYRILLIC = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def root_domain(public_app_url: str = "") -> str:
    parsed = urlsplit(public_app_url.strip()) if public_app_url.strip() else None
    host = (parsed.hostname if parsed and parsed.hostname else "oimopos.com").lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return "oimopos.com"
    return host.removeprefix("www.")


def workspace_url(subdomain: str, public_app_url: str = "") -> str:
    return f"https://{subdomain}.{root_domain(public_app_url)}"


def request_subdomain(host: str | None, domain: str) -> str | None:
    """Return the label for a workspace host; root and www are not workspaces."""
    host = (host or "").lower().split(":", 1)[0].rstrip(".")
    if host in {domain, f"www.{domain}"} or not host.endswith("." + domain):
        return None
    label = host[: -(len(domain) + 1)]
    if label == "www":
        return None
    return label


def validate_subdomain(value: str) -> str:
    value = value.strip().lower()
    if len(value) < 3 or len(value) > 48 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("Используйте 3–48 латинских букв, цифр или дефисов; дефис не может быть в начале или конце")
    if value in RESERVED:
        raise ValueError("Это имя зарезервировано системой. Выберите другое")
    return value


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.strip().lower().translate(CYRILLIC))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    result = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    result = result[:48].rstrip("-")
    if len(result) < 3 or result in RESERVED:
        return "oimo-" + (result or "cafe")
    return result


def allocate(connection, name: str, requested: str | None = None, *, exclude_tenant_id: str | None = None) -> str:
    """Reserve a unique address while the caller holds the shared advisory lock."""
    base = validate_subdomain(requested) if requested else slugify(name)
    candidate = base
    suffix = 2
    while connection.execute(
        "SELECT 1 FROM tenants WHERE lower(workspace_subdomain) = lower(%s) AND id IS DISTINCT FROM %s LIMIT 1",
        (candidate, exclude_tenant_id),
    ).fetchone():
        if requested:
            raise ValueError("Этот адрес уже занят. Выберите другой")
        tail = f"-{suffix}"
        candidate = base[:48 - len(tail)].rstrip("-") + tail
        suffix += 1
    return candidate
