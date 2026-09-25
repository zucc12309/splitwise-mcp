"""Opt-in static-bearer Streamable HTTP. This is NOT OAuth."""

import hashlib
import hmac
from contextlib import asynccontextmanager

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import Settings
from .errors import AppError
from .server import principal


class Guard:
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        values = dict(headers)
        if len([k for k, _ in headers if k in (b"authorization", b"host")]) != 2:
            return await JSONResponse({"error": "unauthorized"}, 401)(scope, receive, send)
        if values.get(b"host", b"").decode() != self.settings.host or b"origin" in values:
            return await JSONResponse({"error": "forbidden_host_or_origin"}, 403)(
                scope, receive, send
            )
        if any(k in values for k in (b"x-user-id", b"x-owner-id", b"x-forwarded-user")):
            return await JSONResponse({"error": "identity_header_rejected"}, 403)(
                scope, receive, send
            )
        authorization = values.get(b"authorization", b"")
        token = authorization[7:] if authorization.startswith(b"Bearer ") else b""
        if not token or not hmac.compare_digest(
            hashlib.sha256(token).hexdigest(), self.settings.caller_token_hash
        ):
            return await JSONResponse(
                {"error": "unauthorized"}, 401, headers={"WWW-Authenticate": "Bearer"}
            )(scope, receive, send)
        context_token = principal.set(self.settings.owner)
        try:
            await self.app(scope, receive, send)
        finally:
            principal.reset(context_token)


def build_remote(server, settings: Settings, upstream):
    settings.validate()
    if not settings.remote:
        raise AppError("configuration", "Set SW_REMOTE=true explicitly.")
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        max_request_body_size=32_768,
        security_settings=TransportSecuritySettings(
            allowed_hosts=[settings.host], allowed_origins=[]
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            try:
                yield
            finally:
                await upstream.close()

    async def health(request):
        return JSONResponse({"status": "ok"})

    # Guard wraps every MCP method including GET/DELETE/initialization/discovery.
    app = Starlette(
        routes=[
            Route("/health", health),
            Route(
                "/mcp",
                Guard(manager.handle_request, settings),
                methods=["GET", "POST", "DELETE", "OPTIONS"],
            ),
        ],
        lifespan=lifespan,
    )
    return app
