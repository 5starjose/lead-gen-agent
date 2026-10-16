import base64
from fastapi import Request, HTTPException
from .config import get_settings

def _check_credentials(request: Request):
    s = get_settings()
    if not s.admin_password:
        # No password configured: open only outside production (documented in README)
        if s.app_env == "production":
            raise HTTPException(503, "ADMIN_PASSWORD is not configured — refusing to serve in production")
        return True
    token = request.headers.get("x-api-token", "")
    if token and token == s.api_token:
        return True
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode()
            _, _, pw = decoded.partition(":")
            if pw == s.admin_password:
                return True
        except Exception:
            pass
    # session cookie set by /login
    if request.cookies.get("lg_session") == s.admin_password:
        return True
    raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Basic"})

def require_auth(request: Request):
    return _check_credentials(request)
