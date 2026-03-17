"""
JWT issuance and verification for ContentBank.

Token types:
  - agent_access: issued to an agent after successful nonce challenge.
    Claims: sub (agent_id), node (issuing node_id), type=agent_access
  - node_sync: issued by a node for replication sync requests.
    Claims: sub (node_id), type=node_sync
  - grant_access: issued to a sharing grant recipient.
    Claims: sub (grant_key), grant_id, type=grant_access

All tokens are signed with the issuing node's ECDSA P-256 private key.
Verification uses the corresponding public key.

For agent_access tokens, the node signs on behalf of the agent after
verifying the agent's nonce signature. The token sub is the agent_id.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid

from jose import jwt, JWTError, ExpiredSignatureError
from jose.exceptions import JWTClaimsError

from contentbank.config import settings
from contentbank.auth.keys import private_key_from_pem, public_key_from_b64


# ---------------------------------------------------------------------------
# Token issuance
# ---------------------------------------------------------------------------

def _node_private_key():
    """Load the node private key from settings."""
    if not settings.node_private_key:
        raise RuntimeError(
            "CB_NODE_PRIVATE_KEY is not set. "
            "Run 'contentbank keygen' to generate a node key pair."
        )
    return private_key_from_pem(settings.node_private_key)


def issue_agent_token(agent_id: str, expiry_seconds: int | None = None) -> str:
    """
    Issue a JWT for an authenticated agent.

    The token is signed by this node's private key.
    Agents present this token as: Authorization: Bearer <token>
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=expiry_seconds or settings.jwt_expiry_seconds)

    claims = {
        "iss": settings.node_id,
        "sub": agent_id,
        "iat": now,
        "exp": exp,
        "jti": str(uuid.uuid4()),
        "type": "agent_access",
        "node": settings.node_id,
    }

    return jwt.encode(
        claims,
        _node_private_key(),
        algorithm=settings.jwt_algorithm,
    )


def issue_node_token(expiry_seconds: int = 300) -> str:
    """Issue a JWT for node-to-node replication auth."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=expiry_seconds)

    claims = {
        "iss": settings.node_id,
        "sub": settings.node_id,
        "iat": now,
        "exp": exp,
        "jti": str(uuid.uuid4()),
        "type": "node_sync",
    }

    return jwt.encode(
        claims,
        _node_private_key(),
        algorithm=settings.jwt_algorithm,
    )


def issue_grant_token(grant_id: str, grant_key_b64: str,
                      expiry_seconds: int = 3600) -> str:
    """Issue a JWT for a sharing grant recipient."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=expiry_seconds)

    claims = {
        "iss": settings.node_id,
        "sub": grant_key_b64,
        "grant_id": grant_id,
        "iat": now,
        "exp": exp,
        "jti": str(uuid.uuid4()),
        "type": "grant_access",
    }

    return jwt.encode(
        claims,
        _node_private_key(),
        algorithm=settings.jwt_algorithm,
    )


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

class TokenError(Exception):
    """Raised when a token is invalid, expired, or has wrong type."""
    pass


def _verify_token(token: str, expected_type: str) -> dict:
    """
    Verify a JWT signed by this node's private key.
    Returns decoded claims or raises TokenError.
    """
    if not settings.node_public_key:
        raise RuntimeError("CB_NODE_PUBLIC_KEY is not set.")

    public_key = public_key_from_b64(settings.node_public_key)

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except ExpiredSignatureError:
        raise TokenError("Token has expired")
    except (JWTError, JWTClaimsError) as e:
        raise TokenError(f"Invalid token: {e}")

    if claims.get("type") != expected_type:
        raise TokenError(
            f"Wrong token type: expected {expected_type}, "
            f"got {claims.get('type')}"
        )

    return claims


def verify_agent_token(token: str) -> str:
    """
    Verify an agent_access JWT.
    Returns agent_id (sub claim) on success.
    Raises TokenError on failure.
    """
    claims = _verify_token(token, "agent_access")
    return claims["sub"]


def verify_node_token(token: str) -> str:
    """
    Verify a node_sync JWT.
    Returns node_id (sub claim) on success.
    """
    claims = _verify_token(token, "node_sync")
    return claims["sub"]


def verify_grant_token(token: str) -> tuple[str, str]:
    """
    Verify a grant_access JWT.
    Returns (grant_id, grant_key_b64) on success.
    """
    claims = _verify_token(token, "grant_access")
    return claims["grant_id"], claims["sub"]
