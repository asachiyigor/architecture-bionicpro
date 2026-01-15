"""
BionicPRO Auth Service

This service handles:
- PKCE OAuth 2.0 flow with Keycloak
- Session management with Redis
- Secure token storage (tokens never exposed to frontend)
- Session rotation to prevent session fixation attacks
"""

import secrets
import hashlib
import base64
import json
import time
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Response, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
import httpx
import redis
from cryptography.fernet import Fernet

from config import get_settings, Settings

app = FastAPI(title="BionicPRO Auth Service", version="1.0.0")

# CORS configuration
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis client
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    decode_responses=True
)

# Encryption for tokens
def get_fernet():
    key = base64.urlsafe_b64encode(settings.token_encryption_key[:32].encode().ljust(32, b'0'))
    return Fernet(key)


def generate_session_id() -> str:
    """Generate a cryptographically secure session ID."""
    return secrets.token_urlsafe(32)


def generate_pkce_verifier() -> str:
    """Generate PKCE code verifier (43-128 chars, RFC 7636)."""
    return secrets.token_urlsafe(64)[:128]


def generate_pkce_challenge(verifier: str) -> str:
    """Generate PKCE code challenge from verifier using S256."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def encrypt_token(token: str) -> str:
    """Encrypt token for secure storage."""
    fernet = get_fernet()
    return fernet.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt token from storage."""
    fernet = get_fernet()
    return fernet.decrypt(encrypted_token.encode()).decode()


def store_session(session_id: str, data: dict, ttl: int = None):
    """Store session data in Redis."""
    if ttl is None:
        ttl = settings.session_ttl
    redis_client.setex(
        f"session:{session_id}",
        ttl,
        json.dumps(data)
    )


def get_session(session_id: str) -> Optional[dict]:
    """Retrieve session data from Redis."""
    data = redis_client.get(f"session:{session_id}")
    if data:
        return json.loads(data)
    return None


def delete_session(session_id: str):
    """Delete session from Redis."""
    redis_client.delete(f"session:{session_id}")


def set_session_cookie(response: Response, session_id: str):
    """Set secure HTTP-only session cookie."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,
        secure=True,  # Enable in production with HTTPS
        samesite="lax",
        max_age=settings.session_ttl
    )


def get_session_id_from_request(request: Request) -> Optional[str]:
    """Extract session ID from request cookies."""
    return request.cookies.get(settings.session_cookie_name)


async def get_keycloak_token(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens using PKCE."""
    token_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": settings.keycloak_client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier
    }

    if settings.keycloak_client_secret:
        data["client_secret"] = settings.keycloak_client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Token exchange failed")
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh access token using refresh token."""
    token_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"

    data = {
        "grant_type": "refresh_token",
        "client_id": settings.keycloak_client_id,
        "refresh_token": refresh_token
    }

    if settings.keycloak_client_secret:
        data["client_secret"] = settings.keycloak_client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Token refresh failed")
        return response.json()


async def introspect_token(token: str) -> dict:
    """Introspect token to validate it."""
    introspect_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token/introspect"

    data = {
        "token": token,
        "client_id": settings.keycloak_client_id
    }

    if settings.keycloak_client_secret:
        data["client_secret"] = settings.keycloak_client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(introspect_url, data=data)
        return response.json()


@app.get("/auth/login")
async def login(request: Request):
    """
    Initiate PKCE OAuth 2.0 flow.
    Generates code verifier and challenge, stores verifier, and redirects to Keycloak.
    """
    # Generate PKCE parameters
    code_verifier = generate_pkce_verifier()
    code_challenge = generate_pkce_challenge(code_verifier)
    state = secrets.token_urlsafe(32)

    # Store code verifier with state as key (temporary, expires in 5 min)
    redis_client.setex(f"pkce:{state}", 300, code_verifier)

    # Construct authorization URL (use public URL for browser redirect)
    redirect_uri = f"http://localhost:8001/auth/callback"
    auth_url = (
        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/auth"
        f"?client_id={settings.keycloak_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=openid profile email"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def callback(request: Request, code: str, state: str):
    """
    Handle OAuth callback from Keycloak.
    Exchanges code for tokens, creates session, and sets secure cookie.
    """
    # Retrieve and validate code verifier
    code_verifier = redis_client.get(f"pkce:{state}")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Clean up PKCE state
    redis_client.delete(f"pkce:{state}")

    # Exchange code for tokens (use same redirect_uri as in login)
    redirect_uri = f"http://localhost:8001/auth/callback"
    tokens = await get_keycloak_token(code, code_verifier, redirect_uri)

    # Create session
    session_id = generate_session_id()
    session_data = {
        "access_token": encrypt_token(tokens["access_token"]),
        "refresh_token": encrypt_token(tokens["refresh_token"]),
        "access_token_expires_at": time.time() + tokens.get("expires_in", settings.access_token_ttl),
        "created_at": time.time(),
        "user_info": None  # Will be populated on first request
    }

    store_session(session_id, session_data)

    # Create response with redirect to frontend
    response = RedirectResponse(url=settings.frontend_url)
    set_session_cookie(response, session_id)

    return response


@app.get("/auth/logout")
async def logout(request: Request):
    """
    Logout user by invalidating session and clearing cookie.
    """
    session_id = get_session_id_from_request(request)

    if session_id:
        session = get_session(session_id)
        if session:
            # Optionally logout from Keycloak
            try:
                refresh_token = decrypt_token(session["refresh_token"])
                logout_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/logout"
                async with httpx.AsyncClient() as client:
                    await client.post(logout_url, data={
                        "client_id": settings.keycloak_client_id,
                        "refresh_token": refresh_token
                    })
            except Exception:
                pass  # Continue even if Keycloak logout fails

        delete_session(session_id)

    response = RedirectResponse(url=settings.frontend_url)
    response.delete_cookie(settings.session_cookie_name)
    return response


@app.get("/auth/session")
async def get_session_info(request: Request):
    """
    Get current session info without exposing tokens.
    Implements session rotation for security.
    """
    session_id = get_session_id_from_request(request)

    if not session_id:
        raise HTTPException(status_code=401, detail="No session")

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Check if access token needs refresh
    current_time = time.time()
    if current_time >= session["access_token_expires_at"]:
        try:
            refresh_token = decrypt_token(session["refresh_token"])
            new_tokens = await refresh_access_token(refresh_token)

            session["access_token"] = encrypt_token(new_tokens["access_token"])
            session["refresh_token"] = encrypt_token(new_tokens["refresh_token"])
            session["access_token_expires_at"] = current_time + new_tokens.get("expires_in", settings.access_token_ttl)
        except Exception:
            delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired")

    # Session rotation: create new session ID
    new_session_id = generate_session_id()
    delete_session(session_id)
    store_session(new_session_id, session)

    response = JSONResponse(content={
        "authenticated": True,
        "session_valid_until": datetime.fromtimestamp(
            session["created_at"] + settings.session_ttl
        ).isoformat()
    })
    set_session_cookie(response, new_session_id)

    return response


@app.get("/auth/validate")
async def validate_session(request: Request):
    """
    Validate current session and return access token for internal service use.
    This endpoint is for backend services only.
    """
    session_id = get_session_id_from_request(request)

    if not session_id:
        raise HTTPException(status_code=401, detail="No session")

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Check if access token needs refresh
    current_time = time.time()
    if current_time >= session["access_token_expires_at"]:
        try:
            refresh_token = decrypt_token(session["refresh_token"])
            new_tokens = await refresh_access_token(refresh_token)

            session["access_token"] = encrypt_token(new_tokens["access_token"])
            session["refresh_token"] = encrypt_token(new_tokens["refresh_token"])
            session["access_token_expires_at"] = current_time + new_tokens.get("expires_in", settings.access_token_ttl)
            store_session(session_id, session)
        except Exception:
            delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired")

    # Return decrypted access token for internal service use
    access_token = decrypt_token(session["access_token"])

    return {"access_token": access_token}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
