"""Hash de contraseñas (scrypt, solo librería estándar)."""
import hashlib
import hmac
import os

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2)
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False
