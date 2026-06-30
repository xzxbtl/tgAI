from datetime import datetime, timezone

from sqlalchemy.orm import Mapped, mapped_column, declarative_base
from sqlalchemy import (
    String,
    DateTime
)

Base = declarative_base()


class Mails(Base):
    __tablename__ = "allowed_mails"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    mail: Mapped[str] = mapped_column(String(255), index=True, nullable=False, unique=True)


class Logs(Base):
    __tablename__ = "mail_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    mail: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
