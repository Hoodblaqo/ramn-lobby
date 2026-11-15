import logging
import os
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["https://hoodblaqo.github.io"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])

class ConnectRequest(BaseModel):
    token: str = Field(min_length=8, max_length=4096)

class CommandRequest(BaseModel):
    token: str = Field(min_length=8, max_length=4096)
    bot_id: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=255)
    args: str | None = Field(default=None, max_length=1000)

class SocialRequest(BaseModel):
    token: str = Field(min_length=8, max_length=4096)
    bot_id: str = Field(min_length=1, max_length=128)

@app.post("/api/social")
async def get_social_lists(payload: SocialRequest):
    token = payload.token.strip()
    bot_id = payload.bot_id.strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = f"https://api.fnlb.net/v1/bots/{quote(bot_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            friends_response, pending_response = await __import__("asyncio").gather(
                client.get(base + "/friends", headers=headers),
                client.get(base + "/pending", headers=headers),
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="FNLB took too long to load friends.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach FNLB social endpoints.")
    def unpack(response, label):
        if response.status_code >= 400:
            try:
                body = response.json(); errs = body.get("errors", []) if isinstance(body, dict) else []
                detail = errs[0].get("message") if errs and isinstance(errs[0], dict) else None
            except ValueError:
                detail = None
            raise HTTPException(status_code=response.status_code, detail=detail or f"FNLB could not load {label} (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise HTTPException(status_code=502, detail=f"FNLB returned invalid {label} data.")
    return {"friends": unpack(friends_response, "friends"), "pending": unpack(pending_response, "pending")}

@app.get("/")
async def home():
    return FileResponse("index.html")

@app.post("/api/bots")
async def list_bots(payload: ConnectRequest):
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Enter your FNLB API token.")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            bots_response, user_response = await __import__("asyncio").gather(
                client.get("https://api.fnlb.net/v1/bots", headers=headers),
                client.get("https://api.fnlb.net/v1/user", headers=headers),
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="FNLB took too long to respond. Try again.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach FNLB. Try again in a moment.")

    def read_json(response, label):
        try:
            return response.json()
        except ValueError:
            raise HTTPException(status_code=502, detail=f"FNLB returned an unreadable {label} response.")

    data = read_json(bots_response, "bot list")
    if bots_response.status_code >= 400:
        errors = data.get("errors", []) if isinstance(data, dict) else []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        detail = first.get("message") or f"FNLB bot-list request failed (HTTP {bots_response.status_code})."
        code = first.get("errorCode")
        if code:
            detail += f" ({code})"
        raise HTTPException(status_code=bots_response.status_code, detail=detail)

    account = {}
    if user_response.status_code < 400:
        user_data = read_json(user_response, "account")
        if isinstance(user_data, dict) and isinstance(user_data.get("user"), dict):
            user_data = user_data["user"]
        if isinstance(user_data, dict):
            account = {"id": str(user_data.get("id") or user_data.get("userId") or ""),
                       "username": str(user_data.get("username") or user_data.get("name") or "")}

    # FNLB documents a JSON array; also accept common API envelope variants safely.
    for _ in range(3):
        if isinstance(data, list):
            break
        if not isinstance(data, dict):
            break
        next_data = None
        for key in ("bots", "data", "items", "results"):
            value = data.get(key)
            if isinstance(value, (list, dict)):
                next_data = value
                break
        if next_data is None or next_data is data:
            break
        data = next_data
    if isinstance(data, dict):
        for key in ("bots", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        shape = ", ".join(list(data.keys())[:8]) if isinstance(data, dict) else type(data).__name__
        raise HTTPException(status_code=502, detail=f"FNLB returned an unsupported bot-list format ({shape}).")

    bots = []
    for item in data:
        if not isinstance(item, dict):
            continue
        bot_id = item.get("id") or item.get("botId") or item.get("bot_id")
        if not bot_id:
            continue
        bots.append({"id": str(bot_id), "nickname": str(item.get("nickname") or item.get("name") or "Unnamed bot")})
    return {"bots": bots, "account": account}

@app.post("/api/command")
async def run_bot_command(payload: CommandRequest):
    token = payload.token.strip()
    bot_id = payload.bot_id.strip()
    command = payload.command.strip()
    if not token or not bot_id or not command:
        raise HTTPException(status_code=400, detail="Missing token, bot, or command.")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    body = {"command": command, "locale": "en"}
    if payload.args and payload.args.strip():
        body["args"] = payload.args.strip()
    url = f"https://api.fnlb.net/v1/bots/{quote(bot_id, safe='')}/commands/run"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="FNLB took too long to run that command.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach FNLB. Try again.")
    try:
        data: Any = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        detail = data.get("message") if isinstance(data, dict) else None
        if not detail and isinstance(data, dict):
            errors = data.get("errors", [])
            detail = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        raise HTTPException(status_code=response.status_code, detail=detail or f"FNLB rejected the command (HTTP {response.status_code}).")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="FNLB returned an unexpected command response.")
    return {"content": str(data.get("content") or "Command sent."), "format": int(data.get("format", 0)), "botName": str(data.get("botName") or "")}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
