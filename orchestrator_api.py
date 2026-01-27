import asyncio
from aiohttp import web
import json
from system_orchestrator import SystemOrchestrator

system = SystemOrchestrator()
app = web.Application()

async def status_handler(request):
    data = {
        "mode": system.macro_mode.value.upper() if system.macro_mode else "OFFLINE",
        "active_orders": 0,
        "timestamp": asyncio.get_event_loop().time()
    }
    return web.json_response(data)

app.router.add_get('/status', status_handler)

if __name__ == '__main__':
    web.run_app(app, port=8000)
