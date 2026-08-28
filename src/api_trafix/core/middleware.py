from starlette.responses import JSONResponse

from api_trafix.config.settings import get_settings

_HEADER_NAMES = frozenset(
    {
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
        "strict-transport-security",
        "cache-control",
    }
)

_UPLOAD_EXEMPT_PREFIXES = frozenset({"/backups/upload", "/signages/contents/upload"})


def _set_header(headers: list[tuple[bytes, bytes]], name: str, value: str) -> list[tuple[bytes, bytes]]:
    return [(k, v) for k, v in headers if k.lower() != name] + [(name.encode(), value.encode())]


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        settings = get_settings()
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers = [h for h in headers if h[0].decode("latin-1").lower() not in _HEADER_NAMES]
                headers = _set_header(headers, "X-Content-Type-Options", "nosniff")
                headers = _set_header(headers, "X-Frame-Options", "DENY")
                headers = _set_header(headers, "Referrer-Policy", "no-referrer")
                headers = _set_header(
                    headers,
                    "Permissions-Policy",
                    "geolocation=(), microphone=(), camera=()",
                )
                if settings.app_env != "development":
                    headers = _set_header(headers, "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
                if path.startswith("/auth"):
                    headers = _set_header(headers, "Cache-Control", "no-store")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in _UPLOAD_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        limit = get_settings().max_request_size_mb * 1024 * 1024

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    response = JSONResponse(status_code=413, content={"detail": "Ukuran body permintaan terlalu besar"})
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(status_code=400, content={"detail": "Content-length tidak valid"})
                await response(scope, receive, send)
                return

        if scope.get("method") in ("POST", "PUT", "PATCH"):
            chunks = []
            while True:
                message = await receive()
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            if len(body) > limit:
                response = JSONResponse(status_code=413, content={"detail": "Ukuran body permintaan terlalu besar"})
                await response(scope, receive, send)
                return

            delivered = False

            async def receive_wrapper():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            await self.app(scope, receive_wrapper, send)
            return

        await self.app(scope, receive, send)
