import sys

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
    JWT_SECRET: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    APP_NAME: str = "R6AX-Learn"
    DEBUG: bool = False
    PORT: int = 8000
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
