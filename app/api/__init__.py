from app.api.routes import router as api_router
from app.api.chat_routes import router as chat_router
from app.api.websocket import router as ws_router
from app.api.plc_routes import router as plc_router
from app.api.data_routes import router as data_router

__all__ = ["api_router", "chat_router", "ws_router", "plc_router", "data_router"]

