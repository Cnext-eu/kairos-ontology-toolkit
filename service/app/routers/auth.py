"""GitHub OAuth authentication router.

Implements the standard GitHub OAuth web application flow so each user
gets their own token with the ``copilot`` scope.  Tokens are stored
server-side in an in-memory session store, keyed by a signed cookie.

Flow:
  1. User clicks "Login with GitHub" → GET /api/auth/login
  2. Browser redirects to GitHub authorize URL
  3. GitHub redirects back with ?code=… → GET /api/auth/callback
  4. Server exchanges code for token, stores it, sets session cookie
  5. Subsequent requests include the cookie → server looks up token
"""

import secrets
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import settings

router = APIRouter()

# In-memory session store: session_id → {token, user, scopes, expires_at}
_sessions: dict[str, dict] = {}

_GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
_GITHUB_USER = "https://api.github.com/user"
_SESSION_COOKIE = "kairos_session"
_SESSION_MAX_AGE = 8 * 3600  # 8 hours


def _oauth_enabled() -> bool:
    return bool(settings.oauth_client_id and settings.oauth_client_secret)


@router.get("/login")
async def login(request: Request):
    """Redirect the user to GitHub's OAuth authorize page."""
    if not _oauth_enabled():
        return JSONResponse(
            status_code=501,
            content={"detail": "OAuth not configured. Set KAIROS_OAUTH_CLIENT_ID "
                     "and KAIROS_OAUTH_CLIENT_SECRET in .env"},
        )

    # Build callback URL from the current request
    callback_url = str(request.url_for("oauth_callback"))
    state = secrets.token_urlsafe(32)

    # Store state for CSRF verification (simple in-memory, keyed by state)
    _sessions[f"oauth_state:{state}"] = {"created": time.time()}

    params = {
        "client_id": settings.oauth_client_id,
        "redirect_uri": callback_url,
        "scope": "read:user copilot",
        "state": state,
    }
    url = f"{_GITHUB_AUTHORIZE}?" + "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url)


@router.get("/callback")
async def oauth_callback(code: str, state: str, response: Response):
    """Exchange the OAuth code for a token and create a session."""
    if not _oauth_enabled():
        return JSONResponse(status_code=501, content={"detail": "OAuth not configured"})

    # Verify state
    state_key = f"oauth_state:{state}"
    if state_key not in _sessions:
        return JSONResponse(status_code=400, content={"detail": "Invalid OAuth state"})
    del _sessions[state_key]

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GITHUB_TOKEN,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "code": code,
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        error = token_data.get("error_description", token_data.get("error", "Unknown"))
        return JSONResponse(status_code=400, content={"detail": f"OAuth error: {error}"})

    # Fetch user info
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _GITHUB_USER,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        user_data = resp.json()

    # Create session
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "token": access_token,
        "scopes": token_data.get("scope", ""),
        "user": user_data.get("login", ""),
        "name": user_data.get("name", ""),
        "avatar": user_data.get("avatar_url", ""),
        "expires_at": time.time() + _SESSION_MAX_AGE,
    }

    # Redirect back to the app with a session cookie
    redirect = RedirectResponse(url="/", status_code=302)
    redirect.set_cookie(
        key=_SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    return redirect


@router.get("/status")
async def auth_status(kairos_session: Optional[str] = Cookie(None)):
    """Return current authentication status."""
    result = {"authenticated": False, "oauth_enabled": _oauth_enabled()}

    if not kairos_session:
        return result

    session = _sessions.get(kairos_session)
    if not session or time.time() > session.get("expires_at", 0):
        if session:
            del _sessions[kairos_session]
        return result

    return {
        "authenticated": True,
        "oauth_enabled": True,
        "user": session["user"],
        "name": session["name"],
        "avatar": session["avatar"],
    }


@router.post("/logout")
async def logout(response: Response, kairos_session: Optional[str] = Cookie(None)):
    """Clear the session."""
    if kairos_session and kairos_session in _sessions:
        del _sessions[kairos_session]

    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(_SESSION_COOKIE, path="/")
    return response


def get_user_token(kairos_session: Optional[str]) -> Optional[str]:
    """Look up the OAuth token for a session cookie value.

    Returns None if the session is missing or expired.
    """
    if not kairos_session:
        return None
    session = _sessions.get(kairos_session)
    if not session:
        return None
    if time.time() > session.get("expires_at", 0):
        del _sessions[kairos_session]
        return None
    return session["token"]
