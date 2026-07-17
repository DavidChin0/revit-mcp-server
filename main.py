# -*- coding: utf-8 -*-
import gc
import os
import sys
import httpx
import anyio
from mcp.server.fastmcp import FastMCP, Image, Context
import base64
from typing import Optional, Dict, Any, Union

# Create a generic MCP server for interacting with Revit
# Use stateless_http=True and json_response=True for better compatibility
mcp = FastMCP(
    "Revit MCP Server",
    host="127.0.0.1",
    port=8000,
    stateless_http=True,
    json_response=True
)

# Configuration
REVIT_HOST = os.environ.get("REVIT_HOST", "localhost")
REVIT_PORT = 48884  # Default pyRevit Routes port
BASE_URL = f"http://{REVIT_HOST}:{REVIT_PORT}/revit_mcp"

# Dump the HTTP connection pool every N tool calls to reclaim response buffers
# and fragmented heap. Sync'd via a simple module counter (stdio = single process,
# no concurrency risk between tool calls).
CACHE_DUMP_INTERVAL = int(os.environ.get("REVIT_MCP_DUMP_INTERVAL", "3"))

# Shared HTTP client with keep-alive connection pooling. Reusing a single
# AsyncClient across all tool calls avoids the per-request TCP/handshake cost
# of creating a new client each time — meaningful when a session fires dozens
# of calls at the local Routes server.
_http_client: Optional[httpx.AsyncClient] = None
_call_count: int = 0


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=BASE_URL,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _http_client


async def _flush_client() -> Dict[str, Any]:
    """Close the HTTP client pool and run GC. Client recreates on next call."""
    global _http_client, _call_count
    client = _http_client
    _http_client = None
    if client is not None and not client.is_closed:
        await client.aclose()
    collected = gc.collect()
    return {"flushed": True, "call_count": _call_count, "gc_collected": collected}


async def _maybe_flush() -> None:
    """Auto-dump every CACHE_DUMP_INTERVAL calls (0 = disabled)."""
    global _call_count
    if CACHE_DUMP_INTERVAL <= 0:
        return
    _call_count += 1
    if _call_count % CACHE_DUMP_INTERVAL == 0:
        await _flush_client()


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    """GET request that returns an Image object"""
    try:
        client = _get_client()
        response = await client.get(endpoint, timeout=60.0)

        if response.status_code == 200:
            data = response.json()
            image_bytes = base64.b64decode(data["image_data"])
            return Image(data=image_bytes, format="png")
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error: {e}"


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = 30.0, params: Dict = None) -> Union[Dict, str]:
    """Internal function handling all HTTP calls"""
    await _maybe_flush()
    try:
        client = _get_client()

        if method == "GET":
            response = await client.get(endpoint, params=params, timeout=timeout)
        else:  # POST
            response = await client.post(
                endpoint,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )

        return response.json() if response.status_code == 200 else f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def dump_cache(ctx: Context = None) -> Dict[str, Any]:
    """Force-flush the HTTP connection pool and run GC immediately."""
    result = await _flush_client()
    result["dump_interval"] = CACHE_DUMP_INTERVAL
    return result


# Register all tools BEFORE the main block
from tools import register_tools
register_tools(mcp, revit_get, revit_post, revit_image)


async def run_combined_async():
    """Run server with both SSE and streamable-http endpoints.

    This allows clients to connect via either:
    - SSE: GET /sse, POST /messages/
    - Streamable-HTTP: POST/GET /mcp
    """
    import uvicorn

    # Get the streamable-http app first - it has the proper lifespan
    # that initializes the session manager's task group
    http_app = mcp.streamable_http_app()

    # Get SSE routes (SSE doesn't need special lifespan - it creates
    # task groups per-request in connect_sse())
    sse_app = mcp.sse_app()

    # Add SSE routes to the http app (preserving its lifespan)
    for route in sse_app.routes:
        http_app.routes.append(route)

    config = uvicorn.Config(
        http_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    transport = "stdio"

    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv or "--streamable-http" in sys.argv:
        transport = "streamable-http"
    elif "--combined" in sys.argv:
        # Run both SSE and streamable-http transports simultaneously
        print("Starting combined server with SSE (/sse, /messages/) and streamable-http (/mcp) endpoints...")
        anyio.run(run_combined_async)
        sys.exit(0)

    mcp.run(transport=transport)