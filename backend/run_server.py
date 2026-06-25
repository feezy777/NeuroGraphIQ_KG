"""Start uvicorn with Windows-compatible event loop (psycopg async)."""
import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8002
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    # On Windows, reload parent can survive port-kill and respawn stale workers (missing new routes).
    # Set WORKBENCH_RELOAD=1 to enable hot reload; default off on win32.
    use_reload = os.environ.get("WORKBENCH_RELOAD", "0" if sys.platform == "win32" else "1") == "1"
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=use_reload,
        reload_dirs=["app"] if use_reload else None,
        loop="asyncio",
    )
