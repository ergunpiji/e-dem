"""
E-dem — JWT tabanlı kimlik doğrulama
HttpOnly cookie ile token saklama
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from models import User

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------

_env_key = os.environ.get("SECRET_KEY", "")
SECRET_KEY = _env_key or "edem-dev-fallback-key--set-SECRET_KEY-env-var-in-production"
if not _env_key:
    print("[AUTH] SECRET_KEY env variable ayarlı değil — development fallback kullanılıyor!", flush=True)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 saat

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
COOKIE_NAME = "access_token"


# ---------------------------------------------------------------------------
# Şifre yardımcıları
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# ---------------------------------------------------------------------------
# JWT yardımcıları
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Kullanıcı sorgulama
# ---------------------------------------------------------------------------

def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = db.query(User).filter(
        User.email == email.lower().strip(),
        User.active == True,  # noqa: E712
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id, User.active == True).first()  # noqa: E712


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Oturum bulunamadı. Lütfen giriş yapın.")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Geçersiz veya süresi dolmuş oturum.")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Geçersiz token.")
    user = get_user_by_id(db, int(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Kullanıcı bulunamadı veya hesap devre dışı.")
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu işlem için Admin yetkisi gereklidir.")
    return current_user


def require_gm(current_user: User = Depends(get_current_user)) -> User:
    """Genel Müdür veya Admin yetkisi gerektirir."""
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu sayfa için Genel Müdür yetkisi gereklidir.")
    return current_user
