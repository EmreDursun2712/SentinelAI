"""User — an authenticated operator of the SentinelAI dashboard.

Authentication is stateless JWT: the password hash here is only consulted at
login time (``user_service.authenticate``). Per-request authorization reads the
role from the signed token, so this table is not hit on every API call.

Passwords are stored as bcrypt hashes (see ``app.core.security``); the plaintext
never touches the database or the logs.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    String,
    true,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import Role
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="user_role_enum", native_enum=False, length=20),
        nullable=False,
        default=Role.VIEWER,
        server_default=Role.VIEWER.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
