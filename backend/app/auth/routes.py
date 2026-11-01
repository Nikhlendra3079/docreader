from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import User, UserIdentity
from app.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.security import (
    hash_password,
    verify_password,
    create_access_token,
)
from app.auth.dependencies import get_current_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    email = request.email.lower()

    # Check whether an account already exists for this email.
    result = await db.execute(
        select(User).where(User.email == email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Create the user.
    user = User(
        email=email,
        is_active=True,
    )

    db.add(user)

    try:
        await db.flush()

        # Create a password identity for this user.
        identity = UserIdentity(
            user_id=user.id,
            provider="password",
            provider_subject=email,
            password_hash=hash_password(request.password),
        )

        db.add(identity)

        await db.commit()
        await db.refresh(user)

    except IntegrityError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    return UserResponse(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    email = request.email.lower()

    # Find the password identity associated with this email.
    result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.provider == "password",
            UserIdentity.provider_subject == email,
        )
    )

    identity = result.scalar_one_or_none()

    # Use the same error for unknown email and incorrect password.
    if (
        identity is None
        or identity.password_hash is None
        or not verify_password(
            request.password,
            identity.password_hash,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load the user associated with the identity.
    result = await db.execute(
        select(User).where(
            User.id == identity.user_id,
            User.is_active.is_(True),
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user.id)

    return TokenResponse(
        access_token=access_token,
    )


@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        is_active=current_user.is_active,
    )