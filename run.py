import os
import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.config import settings
from app.database.connection import init_db, ACTIVE_DB_DIALECT
from app.plc.collector import plc_collector
from app.api.websocket import start_ws_broadcast
from app.api import api_router, chat_router, ws_router, plc_router, data_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup:
    logger.info("=" * 65)
    logger.info(f" Starting {settings.APP_NAME}")
    logger.info(f" Database Engine: {ACTIVE_DB_DIALECT}")
    logger.info(f" PLC Mode: {'Physical S7-1200 (' + settings.PLC_IP + ')' if settings.PLC_ENABLED else 'Digital Twin Simulator'}")
    logger.info(f" Local Chatbot Model: {settings.OLLAMA_MODEL} ({settings.OLLAMA_BASE_URL})")
    logger.info(f" Web Dashboard: http://localhost:{settings.PORT}")
    logger.info("=" * 65)

    # 1. Initialize DB tables & seed historical data
    init_db()

    # 2. Start PLC collection loop
    await plc_collector.start()

    # 3. Start real-time WebSocket telemetry broadcaster
    await start_ws_broadcast()

    yield

    # Shutdown:
    logger.info("Stopping background tasks...")
    plc_collector.stop()
    logger.info("Air Compressor Management shutdown complete.")

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None
)

# Static files & Templates
static_path = os.path.join(BASE_DIR, "app", "static")
templates_path = os.path.join(BASE_DIR, "app", "templates")

app.mount("/static", StaticFiles(directory=static_path), name="static")
templates = Jinja2Templates(directory=templates_path)

# Register API Routers
app.include_router(api_router)
app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(plc_router)
app.include_router(data_router)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serves the primary SCADA monitoring dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.APP_NAME,
            "compressor_tag": settings.COMPRESSOR_TAG,
            "compressor_name": settings.COMPRESSOR_NAME,
            "active_db": ACTIVE_DB_DIALECT,
            "current_page": "dashboard"
        }
    )

@app.get("/plc", response_class=HTMLResponse)
async def serve_plc_page(request: Request):
    """Serves the Siemens S7-1200 PLC Communication & Diagnostics page."""
    return templates.TemplateResponse(
        request=request,
        name="plc.html",
        context={
            "app_name": settings.APP_NAME,
            "compressor_tag": settings.COMPRESSOR_TAG,
            "compressor_name": settings.COMPRESSOR_NAME,
            "active_db": ACTIVE_DB_DIALECT,
            "plc_ip": settings.PLC_IP,
            "plc_db": settings.PLC_DB_NUMBER,
            "current_page": "plc"
        }
    )

@app.get("/data", response_class=HTMLResponse)
async def serve_data_viewer(request: Request):
    """Serves the SQL Database Log Viewer & Historian page."""
    return templates.TemplateResponse(
        request=request,
        name="data_viewer.html",
        context={
            "app_name": settings.APP_NAME,
            "compressor_tag": settings.COMPRESSOR_TAG,
            "compressor_name": settings.COMPRESSOR_NAME,
            "active_db": ACTIVE_DB_DIALECT,
            "current_page": "data"
        }
    )

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info"
    )
