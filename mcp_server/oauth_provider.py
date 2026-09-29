"""Database-backed, single-tenant OAuth provider for the remote MCP server."""
import asyncio
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

from pydantic import AnyHttpUrl

from db import get_db
from mcp_server import auth as mcp_auth
from mcp.server.auth.provider import AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken, TokenError, construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

try:
    from config import PUBLIC_BASE_URL
except ImportError:
    PUBLIC_BASE_URL = "https://rezeptify.battlogg.at"


ACCESS_TOKEN_SECONDS = 3600
REFRESH_TOKEN_SECONDS = 60 * 60 * 24 * 30
AUTH_CODE_SECONDS = 300


def _epoch(value: datetime) -> int:
    """DB DATETIMEs hold naive UTC values."""
    return int(value.replace(tzinfo=timezone.utc).timestamp())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RezeptifyOAuthProvider:
    """OAuth 2.1 authorization server using the existing family password at login."""

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        def query():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT metadata FROM mcp_oauth_clients WHERE client_id=%s", (client_id,))
                    return cur.fetchone()
        row = await self._run(query)
        return OAuthClientInformationFull.model_validate(json.loads(row["metadata"])) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Public PKCE clients need no stored client secret. This also avoids persisting
        # another reusable credential in this deliberately small single-tenant server.
        stored = client_info.model_copy(update={"token_endpoint_auth_method": "none", "client_secret": None})
        metadata = stored.model_dump(mode="json")

        def insert():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO mcp_oauth_clients
                        (client_id,client_name,redirect_uris,grant_types,response_types,
                         token_endpoint_auth_method,scope,metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE metadata=VALUES(metadata)""", (
                        stored.client_id, stored.client_name,
                        json.dumps(metadata.get("redirect_uris") or []),
                        json.dumps(stored.grant_types), json.dumps(stored.response_types),
                        "none", stored.scope, json.dumps(metadata),
                    ))
        await self._run(insert)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        pending_id = secrets.token_urlsafe(32)

        def insert():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO mcp_oauth_pending
                        (pending_id,client_id,redirect_uri,redirect_uri_explicit,code_challenge,
                         scope,resource,state_value,expires_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
                        pending_id, client.client_id, str(params.redirect_uri),
                        params.redirect_uri_provided_explicitly, params.code_challenge,
                        " ".join(params.scopes or []), params.resource, params.state,
                        datetime.utcnow() + timedelta(seconds=AUTH_CODE_SECONDS),
                    ))
        await self._run(insert)
        return f"{PUBLIC_BASE_URL.rstrip('/')}/mcp/login?pending={pending_id}"

    async def get_pending(self, pending_id: str) -> dict | None:
        def query():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM mcp_oauth_pending WHERE pending_id=%s AND expires_at > UTC_TIMESTAMP()", (pending_id,))
                    return cur.fetchone()
        return await self._run(query)

    async def complete_login(self, pending_id: str) -> str | None:
        pending = await self.get_pending(pending_id)
        if not pending:
            return None
        code = secrets.token_urlsafe(32)

        def consume():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM mcp_oauth_pending WHERE pending_id=%s AND expires_at > UTC_TIMESTAMP()", (pending_id,))
                    if cur.rowcount != 1:
                        return False
                    cur.execute("""INSERT INTO mcp_oauth_auth_codes
                        (code_hash,client_id,redirect_uri,redirect_uri_explicit,code_challenge,
                         scope,resource,subject,expires_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
                        _hash(code), pending["client_id"], pending["redirect_uri"],
                        pending["redirect_uri_explicit"], pending["code_challenge"],
                        pending["scope"], pending["resource"], "familie",
                        datetime.utcnow() + timedelta(seconds=AUTH_CODE_SECONDS),
                    ))
                    return True
        if not await self._run(consume):
            return None
        return construct_redirect_uri(pending["redirect_uri"], code=code, state=pending["state_value"], iss=PUBLIC_BASE_URL)

    async def load_authorization_code(self, client, authorization_code: str) -> AuthorizationCode | None:
        def query():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM mcp_oauth_auth_codes WHERE code_hash=%s", (_hash(authorization_code),))
                    return cur.fetchone()
        row = await self._run(query)
        if not row:
            return None
        return AuthorizationCode(code=authorization_code, client_id=row["client_id"],
            redirect_uri=AnyHttpUrl(row["redirect_uri"]), redirect_uri_provided_explicitly=bool(row["redirect_uri_explicit"]),
            code_challenge=row["code_challenge"], scopes=(row["scope"] or "").split(),
            resource=row["resource"], subject=row["subject"], expires_at=_epoch(row["expires_at"]))

    async def _issue_tokens(self, client_id: str, scopes: list[str], resource: str | None, subject: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        access_hash, refresh_hash = _hash(access), _hash(refresh)

        def insert():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""INSERT INTO mcp_oauth_tokens
                        (token_hash,token_type,client_id,scope,resource,subject,expires_at,linked_token_hash)
                        VALUES (%s,'access',%s,%s,%s,%s,%s,%s),(%s,'refresh',%s,%s,%s,%s,%s,%s)""", (
                        access_hash, client_id, " ".join(scopes), resource, subject,
                        datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_SECONDS), refresh_hash,
                        refresh_hash, client_id, " ".join(scopes), resource, subject,
                        datetime.utcnow() + timedelta(seconds=REFRESH_TOKEN_SECONDS), access_hash,
                    ))
        await self._run(insert)
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=ACCESS_TOKEN_SECONDS, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        def consume():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM mcp_oauth_auth_codes WHERE code_hash=%s AND expires_at > UTC_TIMESTAMP()", (_hash(authorization_code.code),))
                    return cur.rowcount == 1
        if not await self._run(consume):
            raise TokenError("invalid_grant", "authorization code is no longer valid")
        return await self._issue_tokens(client.client_id, authorization_code.scopes, authorization_code.resource, authorization_code.subject)

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        def query():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT * FROM mcp_oauth_tokens WHERE token_hash=%s AND token_type='refresh'
                        AND revoked=0 AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP())""", (_hash(refresh_token),))
                    return cur.fetchone()
        row = await self._run(query)
        if not row:
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=(row["scope"] or "").split(),
                            resource=row["resource"], subject=row["subject"], expires_at=_epoch(row["expires_at"]) if row["expires_at"] else None)

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        def revoke():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE mcp_oauth_tokens SET revoked=1 WHERE token_hash=%s AND revoked=0", (_hash(refresh_token.token),))
                    return cur.rowcount == 1
        if not await self._run(revoke):
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        return await self._issue_tokens(client.client_id, scopes, refresh_token.resource, refresh_token.subject)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if (mcp_auth.MCP_API_TOKEN
                and secrets.compare_digest(token.encode(), mcp_auth.MCP_API_TOKEN.encode())):
            return AccessToken(token=token, client_id="rezeptify-mcp-static", scopes=[],
                               resource=f"{PUBLIC_BASE_URL.rstrip('/')}/mcp")
        def query():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT * FROM mcp_oauth_tokens WHERE token_hash=%s AND token_type='access'
                        AND revoked=0 AND (expires_at IS NULL OR expires_at > UTC_TIMESTAMP())""", (_hash(token),))
                    return cur.fetchone()
        row = await self._run(query)
        if not row:
            return None
        return AccessToken(token=token, client_id=row["client_id"], scopes=(row["scope"] or "").split(),
                           resource=row["resource"], subject=row["subject"],
                           expires_at=_epoch(row["expires_at"]) if row["expires_at"] else None)

    async def revoke_token(self, token) -> None:
        token_hash = _hash(token.token)
        def revoke():
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT linked_token_hash FROM mcp_oauth_tokens WHERE token_hash=%s", (token_hash,))
                    row = cur.fetchone()
                    cur.execute("UPDATE mcp_oauth_tokens SET revoked=1 WHERE token_hash=%s", (token_hash,))
                    if row and row["linked_token_hash"]:
                        cur.execute("UPDATE mcp_oauth_tokens SET revoked=1 WHERE token_hash=%s", (row["linked_token_hash"],))
        await self._run(revoke)
