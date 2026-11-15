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


GITHUB_API = "https://api.github.com"
BOT_REPO = "Hoodblaqo/ramn-lobby"
BOT_WORKFLOW = "bot-session.yml"
BOT_BRANCH = "dev"

def github_headers():
    token = os.environ.get("GITHUB_ACTIONS_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Bot controls are not configured yet. The site is okay; the server is missing its private GitHub Actions token.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

async def latest_bot_run(client):
    url = f"{GITHUB_API}/repos/{BOT_REPO}/actions/workflows/{BOT_WORKFLOW}/runs"
    response = await client.get(url, headers=github_headers(), params={"branch": BOT_BRANCH, "per_page": 5})
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GitHub status check failed (HTTP {response.status_code}). Check the server token permissions.")
    data = response.json()
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    return runs[0] if runs else None

@app.get("/api/session/status")
async def bot_session_status():
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            run = await latest_bot_run(client)
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach GitHub to check the bot session.")
    if not run:
        return {"state": "idle", "active": False, "message": "Bot is stopped."}
    status = str(run.get("status") or "unknown")
    conclusion = run.get("conclusion")
    active = status in {"queued", "in_progress", "waiting", "requested", "pending"}
    state = status if active else (str(conclusion or status))
    return {"state": state, "active": active, "run_id": run.get("id"), "url": run.get("html_url"), "message": ("Bot session " + state.replace("_", " ") + ".") if active else ("Last session: " + state.replace("_", " ") + ".")}

@app.post("/api/session/start")
async def start_bot_session():
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            existing = await latest_bot_run(client)
            if existing and str(existing.get("status")) in {"queued", "in_progress", "waiting", "requested", "pending"}:
                return {"ok": True, "active": True, "message": "A bot session is already starting or running."}
            url = f"{GITHUB_API}/repos/{BOT_REPO}/actions/workflows/{BOT_WORKFLOW}/dispatches"
            response = await client.post(url, headers=github_headers(), json={"ref": BOT_BRANCH})
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach GitHub to start the bot.")
    if response.status_code != 204:
        raise HTTPException(status_code=502, detail=f"GitHub did not accept the start request (HTTP {response.status_code}).")
    return {"ok": True, "active": True, "message": "Start request accepted. Waiting for the bot session to launch."}

@app.post("/api/session/stop")
async def stop_bot_session():
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            run = await latest_bot_run(client)
            if not run or str(run.get("status")) not in {"queued", "in_progress", "waiting", "requested", "pending"}:
                return {"ok": True, "active": False, "message": "There is no active bot session to stop."}
            run_id = run.get("id")
            response = await client.post(f"{GITHUB_API}/repos/{BOT_REPO}/actions/runs/{run_id}/cancel", headers=github_headers())
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach GitHub to stop the bot.")
    if response.status_code not in (202, 409):
        raise HTTPException(status_code=502, detail=f"GitHub did not accept the stop request (HTTP {response.status_code}).")
    return {"ok": True, "active": response.status_code == 202, "message": "Stop request sent." if response.status_code == 202 else "The bot session is already stopping."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
