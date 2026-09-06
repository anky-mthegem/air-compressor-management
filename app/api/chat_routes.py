import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.chatbot.agent import chatbot_agent

logger = logging.getLogger("app.api.chat")
router = APIRouter(prefix="/api/chat", tags=["Local AI Chatbot"])

class ChatRequest(BaseModel):
    message: str

@router.post("")
async def chat_stream_endpoint(req: ChatRequest):
    """
    Streams AI diagnostic response token-by-token.
    Works with local Ollama or built-in industrial expert diagnostic rules.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    async def token_generator():
        try:
            async for token in chatbot_agent.answer(req.message):
                yield token
        except Exception as e:
            logger.error(f"Error streaming chat: {e}", exc_info=True)
            yield f"\n\n[Diagnostic Error: {str(e)}]"

    return StreamingResponse(token_generator(), media_type="text/plain; charset=utf-8")

@router.get("/suggestions")
def get_suggested_prompts():
    """Returns preset diagnostic questions for factory personnel."""
    return [
        {"icon": "📊", "label": "Analyze Today's OEE", "prompt": "Evaluate today's OEE performance, availability, and idle running losses."},
        {"icon": "🌡️", "label": "Check Thermal Health", "prompt": "Is the compressor airend discharge temperature running within normal limits?"},
        {"icon": "🛡️", "label": "Inspect Filters & Separator", "prompt": "Check the air-oil separator differential pressure and consumable filter condition."},
        {"icon": "⚡", "label": "Energy & SEC Analysis", "prompt": "What is our current Specific Energy Consumption (kWh/m³) and power loading?"},
        {"icon": "⚠️", "label": "Review Recent Alarms", "prompt": "Show me any recent alarm warnings or trip conditions from the event log."}
    ]
