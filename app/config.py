import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Windows 控制台默认使用 cp1252，print 中文会抛 UnicodeEncodeError，
# 导致 SSE 流中断。这里全局重配置 stdout/stderr 为 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/r6ax.db"
    JWT_SECRET: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    APP_NAME: str = "R6AX-Learn"
    DEBUG: bool = False
    PORT: int = 8000
    CORS_ORIGINS: str = ""

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_must_be_strong(cls, v: str) -> str:
        v = v.strip()
        weak_markers = ("change", "changeme", "replace", "example", "your-secret", "test-jwt-secret")
        if len(v) < 32 or any(m in v.lower() for m in weak_markers):
            raise ValueError(
                "JWT_SECRET is required and must be a random string of at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return v

settings = Settings()
