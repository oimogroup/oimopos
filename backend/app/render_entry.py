"""Same-origin cloud entry point; local Compose continues using app.main."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles


def configure_environment():
    for key, minimum in (("DATABASE_URL", 1), ("EMPLOYEE_PIN_KEY", 32), ("PLATFORM_INITIAL_PASSWORD", 16)):
        value = os.environ.get(key, "")
        if len(value) < minimum or value == "ChangeMe-Platform-2026":
            raise RuntimeError(f"Set a valid {key} in the service environment")
    if os.environ.get("SESSION_COOKIE_SECURE", "").lower() != "true":
        raise RuntimeError("SESSION_COOKIE_SECURE must be true")
    origins = [v.strip().rstrip("/") for v in os.environ.get("CORS_ORIGINS", "").split(",") if v.strip()]
    external = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if external:
        origins.append(external)
    if not origins or any(urlsplit(v).scheme != "https" or not urlsplit(v).netloc or urlsplit(v).path for v in origins):
        raise RuntimeError("Configure HTTPS origins using RENDER_EXTERNAL_URL or CORS_ORIGINS")
    os.environ["CORS_ORIGINS"] = ",".join(dict.fromkeys(origins))


configure_environment()
from .main import app  # noqa: E402


@app.middleware("http")
async def cloud_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api/", "/health")) or request.url.path.endswith(".html") or request.url.path in {"/pos", "/admin", "/login", "/platform"} else "no-cache"
    return response


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(PUBLIC / "landing.html", headers={"Cache-Control": "no-cache"})


PUBLIC = Path(__file__).resolve().parents[1] / "public"
PAGES = {"pos": "index.html", "admin": "admin.html", "login": "login.html", "platform": "platform.html"}


def page_response(filename):
    async def endpoint():
        return FileResponse(PUBLIC / filename, headers={"Cache-Control": "no-store"})
    return endpoint


def legacy_redirect(path):
    async def endpoint(request: Request):
        query = request.url.query
        return RedirectResponse(path + ("?" + query if query else ""), status_code=301)
    return endpoint


app.add_api_route("/landing.html", legacy_redirect("/"), methods=["GET"], include_in_schema=False)


for page, filename in PAGES.items():
    app.add_api_route("/" + page, page_response(filename), methods=["GET"], include_in_schema=False)
    app.add_api_route("/" + filename, legacy_redirect("/" + page), methods=["GET"], include_in_schema=False)


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "public", html=True), name="frontend")
