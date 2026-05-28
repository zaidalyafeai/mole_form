from __future__ import annotations

import os
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from github_push import GithubPushError, PushResult, push_metadata_to_github, unwrap_metadata

load_dotenv()

app = FastAPI(
    title="Masader Form API",
    description="Push dataset metadata to the Masader GitHub catalogue.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PushMetadataRequest(BaseModel):
    github_username: str = Field(..., min_length=1, description="GitHub username for PR attribution")
    metadata: dict = Field(..., description="Dataset metadata JSON (must include Name)")


class PushMetadataResponse(BaseModel):
    status: str
    branch: str
    pull_request_url: Optional[str] = None
    message: Optional[str] = None


def validate_github(username: str) -> bool:
    response = requests.get(f"https://api.github.com/users/{username}", timeout=10)
    return response.status_code == 200


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = (os.getenv("API_KEY") or "").strip()
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def to_response(result: PushResult) -> PushMetadataResponse:
    return PushMetadataResponse(
        status=result.status,
        branch=result.branch,
        pull_request_url=result.pull_request_url,
        message=result.message,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/push-metadata",
    response_model=PushMetadataResponse,
    dependencies=[Depends(require_api_key)],
)
def push_metadata(body: PushMetadataRequest) -> PushMetadataResponse:
    github_username = body.github_username.strip()
    if not validate_github(github_username):
        raise HTTPException(status_code=400, detail="Invalid GitHub username.")

    metadata = unwrap_metadata(body.metadata)
    if not (metadata.get("Name") or "").strip():
        raise HTTPException(status_code=400, detail="metadata must include a non-empty 'Name' field.")

    try:
        result = push_metadata_to_github(metadata, github_username)
    except GithubPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return to_response(result)
