"""
Unit tests for auth: key generation, signing, verification, token flow.
"""

import pytest
from contentbank.auth.keys import (
    generate_key_pair, sign_nonce, verify_nonce_signature,
    private_key_to_pem, private_key_from_pem, public_key_to_b64,
)


def test_generate_key_pair():
    private_key, public_key_b64 = generate_key_pair()
    assert private_key is not None
    assert len(public_key_b64) > 0
    # base64url — no + or /
    assert "+" not in public_key_b64
    assert "/" not in public_key_b64


def test_sign_and_verify():
    private_key, public_key_b64 = generate_key_pair()
    nonce = "test-nonce-abc123"
    signature = sign_nonce(private_key, nonce)

    assert verify_nonce_signature(public_key_b64, nonce, signature)


def test_wrong_nonce_fails():
    private_key, public_key_b64 = generate_key_pair()
    signature = sign_nonce(private_key, "correct-nonce")

    assert not verify_nonce_signature(public_key_b64, "wrong-nonce", signature)


def test_wrong_key_fails():
    private_key1, _ = generate_key_pair()
    _, public_key_b64_2 = generate_key_pair()
    nonce = "test-nonce"
    signature = sign_nonce(private_key1, nonce)

    assert not verify_nonce_signature(public_key_b64_2, nonce, signature)


def test_pem_roundtrip():
    private_key, public_key_b64 = generate_key_pair()
    pem = private_key_to_pem(private_key)
    restored = private_key_from_pem(pem)

    # Restored key should produce same public key
    assert public_key_to_b64(restored.public_key()) == public_key_b64


def test_verify_nonce_invalid_signature():
    _, public_key_b64 = generate_key_pair()
    assert not verify_nonce_signature(public_key_b64, "nonce", "badsig")
