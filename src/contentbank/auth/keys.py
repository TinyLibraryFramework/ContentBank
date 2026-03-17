"""
ECDH / ECDSA key utilities for ContentBank.

All agent and node identities are based on P-256 (secp256r1) key pairs.
- Private keys: PEM, stored locally only (never sent over the wire)
- Public keys: base64url-encoded DER (stored in cb_agents.public_key)

Key pairs serve two purposes:
  1. Authentication — agent signs a nonce to prove identity (ECDSA)
  2. Secure pairing / ECDH — key exchange for encrypted channels (future)

Both use the same P-256 key pair; ECDSA and ECDH share the curve.
"""

import base64
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1, generate_private_key, EllipticCurvePrivateKey,
    EllipticCurvePublicKey, ECDSA
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


def generate_key_pair() -> tuple[EllipticCurvePrivateKey, str]:
    """
    Generate a new P-256 key pair.

    Returns:
        (private_key, public_key_b64url)
        public_key_b64url is the base64url-encoded DER SubjectPublicKeyInfo,
        suitable for storage in cb_agents.public_key.
    """
    private_key = generate_private_key(SECP256R1(), default_backend())
    public_key_b64url = public_key_to_b64(private_key.public_key())
    return private_key, public_key_b64url


def public_key_to_b64(public_key: EllipticCurvePublicKey) -> str:
    """Serialize a public key to base64url DER."""
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.urlsafe_b64encode(der).rstrip(b"=").decode()


def public_key_from_b64(b64url: str) -> EllipticCurvePublicKey:
    """Deserialize a public key from base64url DER."""
    # Add padding if needed
    padding = 4 - len(b64url) % 4
    if padding != 4:
        b64url += "=" * padding
    der = base64.urlsafe_b64decode(b64url)
    return serialization.load_der_public_key(der, backend=default_backend())


def sign_nonce(private_key: EllipticCurvePrivateKey, nonce: str) -> str:
    """
    Sign a nonce with the private key (ECDSA P-256, SHA-256).
    Returns base64url-encoded DER signature.
    """
    sig = private_key.sign(nonce.encode(), ECDSA(hashes.SHA256()))
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def verify_nonce_signature(
    public_key_b64: str,
    nonce: str,
    signature_b64: str,
) -> bool:
    """
    Verify an ECDSA P-256 signature over a nonce.
    Returns True if valid, False otherwise.
    """
    try:
        public_key = public_key_from_b64(public_key_b64)
        # Add padding
        padding = 4 - len(signature_b64) % 4
        if padding != 4:
            signature_b64 += "=" * padding
        sig = base64.urlsafe_b64decode(signature_b64)
        public_key.verify(sig, nonce.encode(), ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, Exception):
        return False


def private_key_to_pem(private_key: EllipticCurvePrivateKey) -> str:
    """Serialize private key to PEM (for local storage only)."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def private_key_from_pem(pem: str) -> EllipticCurvePrivateKey:
    """Load private key from PEM string."""
    return serialization.load_pem_private_key(
        pem.encode(), password=None, backend=default_backend()
    )
