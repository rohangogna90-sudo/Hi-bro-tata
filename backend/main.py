import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("personal-ai-assistant")

app = FastAPI(title="Personal AI Assistant API", version="0.1.0")

# Native mobile apps do not rely on browser CORS, but this also supports local web previews.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

SYSTEM_PROMPT = (
    "You are a helpful personal AI assistant. Be clear, practical, and honest. "
    "Do not claim to have performed actions that you have not actually performed. "
    "If a request needs live information or an external action and no tool is available, "
    "explain that limitation and ask for the information or tool access needed."
)

OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    provider: Optional[Literal["gemini", "openai", "anthropic"]] = None


def issue_token() -> str:
    if len(JWT_SECRET) < 32:
        raise HTTPException(
            status_code=503,
            detail="Server authentication is not configured. Set JWT_SECRET (32+ characters).",
        )
    payload = {
        "sub": "owner",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_owner(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Please sign in.")
    if len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Server authentication is not configured.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Your session expired. Please sign in again.")
    if payload.get("sub") != "owner":
        raise HTTPException(status_code=403, detail="This assistant is private.")
    return "owner"


@app.middleware("http")
async def request_logging(request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, elapsed_ms)
        return response
    except Exception:
        logger.exception("Unhandled request error on %s", request.url.path)
        raise


@app.get("/health")
async def health():
    return {"ok": True, "service": "personal-ai-assistant-api"}


@app.post("/auth/login")
async def login(body: LoginRequest):
    if not OWNER_PASSWORD:
        raise HTTPException(status_code=503, detail="Set OWNER_PASSWORD in the backend environment.")
    # Constant-time comparison avoids leaking password-match information.
    import hmac
    if not hmac.compare_digest(body.password, OWNER_PASSWORD):
        raise HTTPException(status_code=401, detail="Incorrect owner password.")
    return {"access_token": issue_token(), "token_type": "bearer"}


@app.get("/providers")
async def providers(_: str = Depends(require_owner)):
    configured = {
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
    }
    return {
        "default": os.getenv("AI_PROVIDER", "gemini").lower(),
        "configured": configured,
    }


async def ask_gemini(messages: list[ChatMessage]) -> str:
    api_key = os.getenv("AQ.Ab8RN6LQv73y7WPML_CG8s_xf70LL0BIebvQmMuawI4ayHmycg")
    if not api_key:
        raise HTTPException(status_code=503, detail="Gemini is not configured on the server.")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    contents = []
    for message in messages:
        contents.append({
            "role": "model" if message.role == "assistant" else "user",
            "parts": [{"text": message.content}],
        })
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
    if response.is_error:
        logger.error("Gemini provider returned HTTP %s", response.status_code)
        raise HTTPException(status_code=502, detail="Gemini could not complete the request. Check the provider key, model and quota.")
    data = response.json()
    try:
        return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError):
        logger.error("Unexpected Gemini response structure")
        raise HTTPException(status_code=502, detail="Gemini returned an empty or unexpected response.")


async def ask_openai(messages: list[ChatMessage]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenAI is not configured on the server.")
    model = os.getenv("OPENAI_MODEL", "gpt-6-astra")
    input_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    input_messages.extend({"role": m.role, "content": m.content} for m in messages)
    payload = {"model": model, "input": input_messages, "max_output_tokens": 2048}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.is_error:
        logger.error("OpenAI provider returned HTTP %s", response.status_code)
        raise HTTPException(status_code=502, detail="OpenAI could not complete the request. Check the provider key, model and quota.")
    data = response.json()
    # The Responses API returns text in output message content blocks.
    pieces = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    pieces.append(block.get("text", ""))
    answer = "".join(pieces).strip()
    if not answer:
        logger.error("OpenAI response contained no output text")
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response.")
    return answer


async def ask_anthropic(messages: list[ChatMessage]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Claude is not configured on the server.")
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
    if response.is_error:
        logger.error("Anthropic provider returned HTTP %s", response.status_code)
        raise HTTPException(status_code=502, detail="Claude could not complete the request. Check the provider key, model and quota.")
    data = response.json()
    answer = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()
    if not answer:
        logger.error("Anthropic response contained no text")
        raise HTTPException(status_code=502, detail="Claude returned an empty response.")
    return answer


@app.post("/chat")
async def chat(body: ChatRequest, _: str = Depends(require_owner)):
    provider = (body.provider or os.getenv("AI_PROVIDER", "gemini")).lower()
    if provider not in {"gemini", "openai", "anthropic"}:
        raise HTTPException(status_code=400, detail="Unsupported AI provider.")
    # Require the latest message to be from the user to prevent malformed chat turns.
    if body.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="The last chat message must be from the user.")
    if provider == "gemini":
        reply = await ask_gemini(body.messages)
    elif provider == "openai":
        reply = await ask_openai(body.messages)
    else:
        reply = await ask_anthropic(body.messages)
    return {"reply": reply, "provider": provider}
