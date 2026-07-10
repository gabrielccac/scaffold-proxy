from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class ProxyRow(Base):
    __tablename__ = "proxies"
    __table_args__ = (UniqueConstraint("host", "port", "protocol", name="uq_proxy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="freeproxy.world")
    country: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    anonymity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    listed_speed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    egress_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    egress_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    checks: Mapped[list[CheckRow]] = relationship(
        "CheckRow",
        back_populates="proxy",
        cascade="all, delete-orphan",
        order_by="CheckRow.checked_at.desc()",
    )


class CheckRow(Base):
    __tablename__ = "proxy_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proxy_id: Mapped[int] = mapped_column(
        ForeignKey("proxies.id", ondelete="CASCADE"), index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    egress_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    egress_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    proxy: Mapped[ProxyRow] = relationship("ProxyRow", back_populates="checks")


def make_engine(database_url: str):
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, future=True, connect_args=connect_args)


def make_session_factory(database_url: str):
    engine = make_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True), engine


def init_db(database_url: str) -> None:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)
