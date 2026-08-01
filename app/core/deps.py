from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.requests import Request

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db = Depends(get_db)
) -> Optional[User]:
    if not token:
        token = request.cookies.get("access_token")
    
    if not token:
        return None
    
    payload = decode_access_token(token)
    if payload is None:
        return None
    
    username: str = payload.get("sub")
    if username is None:
        return None
    
    user = await db.get(User, username)
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
