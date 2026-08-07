from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from starlette.responses import HTMLResponse

from app.core.database import init_db

from app.i18n.middleware import LocaleMiddleware

from fastapi.responses import RedirectResponse

from app.core.deps import get_current_user, oauth2_scheme
from app.models.user import User

from app.routers import auth, projects, input, teaching, practice, integration, pages, integration_promote

app = FastAPI(title="R6AX:/Learn", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
