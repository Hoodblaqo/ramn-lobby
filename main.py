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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            response = await client.get("https://api.fnlb.net/v1/bots", headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="FNLB took too long to respond. Try again.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach FNLB. Try again in a moment.")
    if response.status_code in (400, 401, 403, 429):
        try:
            err = response.json()
            errors = err.get("errors", []) if isinstance(err, dict) else []
            detail = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        except ValueError:
            detail = None
        if not detail:
            detail = {400: "FNLB rejected the request.", 401: "FNLB rejected this API token.", 403: "This token does not have permission to list bots.", 429: "FNLB rate limit reached. Wait a moment and try again."}[response.status_code]
        raise HTTPException(status_code=response.status_code, detail=detail)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"FNLB returned HTTP {response.status_code}.")
    try:
        data: Any = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="FNLB returned an unexpected response.")
    if isinstance(data, dict) and isinstance(data.get("bots"), list):
        data = data["bots"]
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="FNLB returned an unexpected bot-list format.")
    bots = []
    for item in data:
        if isinstance(item, dict):
            bots.append({"id": str(item.get("id", "")), "nickname": str(item.get("nickname") or "Unnamed bot")})
    return {"bots": bots}

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
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as client:
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
