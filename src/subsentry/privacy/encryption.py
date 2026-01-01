from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_TIME_COST = 3
KDF_MEMORY_COST = 64 * 1024  # 64MB
KDF_PARALLELISM = 2
KEY_LEN = 32

@dataclass(frozen=True)
class KeyMaterial:
    salt_b64: str
    key: bytes

def derive_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise ValueError("Passphrase cannot be empty")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=KDF_TIME_COST,
        memory_cost=KDF_MEMORY_COST,
        parallelism=KDF_PARALLELISM,
        hash_len=KEY_LEN,
        type=Type.ID,
    )

def init_key(passphrase: str) -> KeyMaterial:
    salt = os.urandom(16)
    key = derive_key(passphrase, salt)
    return KeyMaterial(salt_b64=base64.b64encode(salt).decode("ascii"), key=key)

def load_key(passphrase: str, salt_b64: str) -> KeyMaterial:
    salt = base64.b64decode(salt_b64.encode("ascii"))
    key = derive_key(passphrase, salt)
    return KeyMaterial(salt_b64=salt_b64, key=key)

def encrypt_str(key: bytes, plaintext: str) -> str:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    blob = nonce + ct
    return "enc:" + base64.b64encode(blob).decode("ascii")

def decrypt_str(key: bytes, ciphertext: str) -> str:
    if not ciphertext.startswith("enc:"):
        return ciphertext
    blob = base64.b64decode(ciphertext[4:].encode("ascii"))
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(key)
    pt = aes.decrypt(nonce, ct, None)
    return pt.decode("utf-8")

def maybe_encrypt(key: Optional[bytes], s: str) -> str:
    return s if key is None else encrypt_str(key, s)

def maybe_decrypt(key: Optional[bytes], s: str) -> str:
    if not s.startswith("enc:"):
        return s
    return "<encrypted>" if key is None else decrypt_str(key, s)
