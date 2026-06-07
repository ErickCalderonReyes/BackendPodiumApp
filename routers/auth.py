from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.auth import UserRegister, UserLogin, TokenResponse, UserOut
from services.auth import register_user, authenticate_user, create_access_token
from core.dependencies import get_db, get_current_user
from db_models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
    user = await register_user(body.email, body.password, body.full_name, db)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(body.email, body.password, db)
    token = create_access_token({"sub": user.email, "role": user.role})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user