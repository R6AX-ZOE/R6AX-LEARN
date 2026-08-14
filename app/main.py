import hmac
import secrets
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.core.database import init_db

from app.i18n.middleware import LocaleMiddleware

from fastapi.responses import RedirectResponse

from app.core.deps import get_current_user, oauth2_scheme
from app.models.user import User

from app.routers import auth, projects, input, teaching, practice, integration, pages, integration_promote

app = FastAPI(title="R6AX:/Learn", version="0.1.0-beta.2")

CSRF_COOKIE = "csrf_token"
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in UNSAFE_METHODS and not request.headers.get("Authorization"):
        cookie_token = request.cookies.get(CSRF_COOKIE)
        if cookie_token:
            supplied = request.headers.get("X-CSRF-Token")
            if not supplied:
                content_type = request.headers.get("content-type", "")
                if content_type.startswith("application/x-www-form-urlencoded"):
                    body = await request.body()
                    params = parse_qs(body.decode("utf-8", errors="replace"))
                    supplied = (params.get("csrf_token") or [None])[0]
            if not supplied or not hmac.compare_digest(cookie_token, supplied):
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

    response = await call_next(request)

    if CSRF_COOKIE not in request.cookies:
        existing = response.headers.get("set-cookie", "")
        if f"{CSRF_COOKIE}=" not in existing:
            response.set_cookie(
                key=CSRF_COOKIE,
                value=secrets.token_urlsafe(32),
                httponly=False,
                samesite="lax",
                secure=not settings.DEBUG,
                path="/",
            )
    return response

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=bool(cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LocaleMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages.router, prefix="", tags=["pages"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(input.router, prefix="/api/input", tags=["input"])
app.include_router(teaching.router, prefix="/api/teaching", tags=["teaching"])
app.include_router(practice.router, prefix="/api/practice", tags=["practice"])
app.include_router(integration.router, prefix="/api/integration", tags=["integration"])
app.include_router(integration_promote.router, prefix="/api/integration", tags=["integration-promote"])

@app.on_event("startup")
async def on_startup():
    await init_db()

@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/auth/login")
