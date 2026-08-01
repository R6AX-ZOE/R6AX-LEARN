from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.i18n.i18n import set_locale

class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        locale = request.headers.get("Accept-Language", "zh_CN").split(",")[0].replace("-", "_")
        if locale not in ["zh_CN", "en_US"]:
            locale = "zh_CN"
        
        set_locale(locale)
        request.state.locale = locale
        
        response = await call_next(request)
        response.headers["Content-Language"] = locale
        return response
