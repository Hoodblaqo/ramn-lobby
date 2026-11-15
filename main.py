import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

class ConnectRequest(BaseModel):
    token: str = Field(min_length=8, max_length=4096)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
