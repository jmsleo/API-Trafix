#!/usr/bin/env python3
"""Mock LPR Camera — simulates the ECV86 entry/exit LPR camera.

Returns plate data when the API polls /checklpr, and accepts
image uploads from the camera's push mode.

Usage:
    python mock_lpr_camera.py                  # default plate B 1234 XYZ
    PLATE_NUMBER="B 9999 ABC" python mock_lpr_camera.py
"""

import json
import os
from aiohttp import web

PLATE_NUMBER = os.environ.get("PLATE_NUMBER", "B 1234 XYZ")
PORT = int(os.environ.get("PORT", "8090"))


async def handle_checklpr(request: web.Request) -> web.Response:
    """Return the current plate read — mimics the real camera's /checklpr."""
    return web.json_response({
        "plate_num": PLATE_NUMBER,
        "confidence": 0.95,
        "url_gambar": f"http://mock-lpr:{PORT}/image/{PLATE_NUMBER.replace(' ', '')}.jpg",
    })


async def handle_upload(request: web.Request) -> web.Response:
    """Accept image uploads from the camera's push mode."""
    reader = await request.multipart()
    field = await reader.next()
    if field is None:
        return web.json_response({"error": "no file"}, status=400)

    filename = field.filename or "unknown"
    size = 0
    while True:
        chunk = await field.read_chunk()
        if not chunk:
            break
        size += len(chunk)

    print(f"[LPR] Received upload: {filename} ({size} bytes)")
    return web.json_response({"status": "ok", "filename": filename, "bytes": size})


async def handle_image(request: web.Request) -> web.Response:
    """Serve a placeholder image."""
    return web.Response(
        text=b'\x89PNG\r\n\x1a\n' + b'\x00' * 100,
        content_type="image/png",
    )


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "healthy", "plate": PLATE_NUMBER})


def main() -> None:
    app = web.Application()
    app.router.add_get("/checklpr", handle_checklpr)
    app.router.add_post("/", handle_upload)
    app.router.add_get("/image/{filename}", handle_image)
    app.router.add_get("/health", handle_health)

    print(f"[LPR] Mock camera listening on port {PORT}")
    print(f"[LPR] Plate: {PLATE_NUMBER}")
    print(f"[LPR] Endpoints:")
    print(f"  GET  /checklpr      — return plate read")
    print(f"  POST /              — accept image upload")
    print(f"  GET  /image/{{file}}  — placeholder image")

    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
