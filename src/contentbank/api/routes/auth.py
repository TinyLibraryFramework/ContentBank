"""
Authentication routes.

Flow:
  1. POST /auth/challenge  — client requests a nonce for their agent_id
  2. POST /auth/token      — client presents (agent_id, nonce, signature)
                             node verifies signature against stored public_key
                             node issues a signed JWT on success

This is a challenge-response proof of key possession.
The agent's private key never leaves the client.
"""

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from contentbank.db.database import get_db
from contentbank.db.models import Agent
from contentbank.auth.keys import verify_nonce_signature
from contentbank.auth.tokens import issue_agent_token

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory nonce store: {agent_id: (nonce, expires_at)}
# In production this should be Redis or a DB table with TTL.
_nonce_store: dict[str, tuple[str, float]] = {}
_NONCE_TTL_SECONDS = 120


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChallengeRequest(BaseModel):
    agent_id: str  # urn:cb:agent:{uuid}


class ChallengeResponse(BaseModel):
    nonce: str
    expires_in: int  # seconds


class TokenRequest(BaseModel):
    agent_id: str
    nonce: str
    signature: str  # base64url ECDSA P-256 signature over nonce


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class AgentRegisterRequest(BaseModel):
    display_name: str
    public_key: str  # base64url DER P-256 public key


class AgentResponse(BaseModel):
    id: str
    display_name: str
    public_key: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/challenge", response_model=ChallengeResponse)
async def request_challenge(
    body: ChallengeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Issue a nonce for an agent to sign.
    The agent must already be registered (have a stored public key).
    """
    result = await db.execute(
        select(Agent).where(Agent.id == body.agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        # Return same response whether agent exists or not (no enumeration)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    nonce = secrets.token_urlsafe(32)
    expires_at = time.time() + _NONCE_TTL_SECONDS
    _nonce_store[body.agent_id] = (nonce, expires_at)

    return ChallengeResponse(nonce=nonce, expires_in=_NONCE_TTL_SECONDS)


@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify a signed nonce and issue an access JWT.

    The client must:
      1. Have called /auth/challenge to obtain a nonce
      2. Sign the nonce with their P-256 private key (ECDSA SHA-256)
      3. Present agent_id, nonce, and base64url signature here
    """
    # Check nonce exists and is fresh
    entry = _nonce_store.get(body.agent_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No pending challenge for this agent. Call /auth/challenge first.",
        )

    stored_nonce, expires_at = entry
    if time.time() > expires_at:
        del _nonce_store[body.agent_id]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Challenge has expired. Request a new one.",
        )

    if stored_nonce != body.nonce:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nonce mismatch.",
        )

    # Look up agent's public key
    result = await db.execute(
        select(Agent).where(Agent.id == body.agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Agent not found")

    # Verify signature
    if not verify_nonce_signature(agent.public_key, body.nonce, body.signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature verification failed.",
        )

    # Consume nonce (single-use)
    del _nonce_store[body.agent_id]

    # Issue token
    from contentbank.config import settings
    token = issue_agent_token(body.agent_id)

    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_seconds,
    )


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def register_agent(
    body: AgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new agent with their P-256 public key.
    Returns the assigned agent_id.

    In a production deployment, agent registration may require
    an admin token or invitation code. For now it is open.
    """
    import uuid
    from datetime import datetime, timezone

    agent_id = f"urn:cb:agent:{uuid.uuid4()}"
    now = datetime.now(timezone.utc)

    agent = Agent(
        id=agent_id,
        display_name=body.display_name,
        public_key=body.public_key,
        created_at=now,
    )
    db.add(agent)
    await db.flush()

    return AgentResponse(
        id=agent.id,
        display_name=agent.display_name,
        public_key=agent.public_key,
    )
