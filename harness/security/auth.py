"""Single admin login: env ADMIN_USER + argon2 ADMIN_PASSWORD_HASH; JWT in an httpOnly cookie.

No default credentials and no default secret: if ADMIN_PASSWORD_HASH or JWT_SECRET is unset, login
is disabled (503). Generate a hash with: python -m harness.security.auth 'your password'
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

COOKIE = "jmd_session"
TTL_SECONDS = 1800
_hasher = PasswordHasher()


class AuthDisabled(RuntimeError):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_login(user: str, password: str) -> bool:
    expect_user = os.environ.get("ADMIN_USER", "")
    pw_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if not pw_hash or not os.environ.get("JWT_SECRET"):
        raise AuthDisabled("ADMIN_PASSWORD_HASH and JWT_SECRET must be set")
    user_ok = bool(expect_user) and user == expect_user
    try:
        pw_ok = bool(_hasher.verify(pw_hash, password))
    except (VerificationError, InvalidHashError):
        pw_ok = False
    return user_ok and pw_ok


def issue_token(user: str, now: Callable[[], float] = time.time) -> str:
    t = int(now())
    return jwt.encode(
        {"sub": user, "iat": t, "exp": t + TTL_SECONDS}, os.environ["JWT_SECRET"], algorithm="HS256"
    )


def read_token(token: str) -> str | None:
    """Return the subject for a valid, unexpired token, else None."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return None
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) else None


if __name__ == "__main__":
    print(hash_password(sys.argv[1]))
