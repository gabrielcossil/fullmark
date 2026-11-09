import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Integer, JSON, ForeignKey, UniqueConstraint, Float, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def now():
    return datetime.now(timezone.utc).timestamp()


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Review(Base):
    __tablename__ = "fm_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(Text)
    protocol: Mapped[dict] = mapped_column(JSON)
    protocol_hash: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Search(Base):
    __tablename__ = "fm_searches"
    __table_args__ = (UniqueConstraint("review_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(Text)
    max_records: Mapped[int] = mapped_column(Integer)
    total_found: Mapped[int] = mapped_column(Integer, default=0)
    translated_query: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Article(Base):
    __tablename__ = "fm_articles"
    __table_args__ = (UniqueConstraint("review_id", "identity"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    identity: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    recommendation: Mapped[dict] = mapped_column(JSON, default=dict)
    pdf: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)


class Record(Base):
    __tablename__ = "fm_records"
    __table_args__ = (UniqueConstraint("search_id", "source_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("fm_searches.id"), index=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("fm_articles.id"), index=True)
    source_id: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSON)


class Decision(Base):
    __tablename__ = "fm_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("fm_articles.id"), index=True)
    actor: Mapped[str] = mapped_column(String(36))
    stage: Mapped[str] = mapped_column(String(30))
    verdict: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Audit(Base):
    __tablename__ = "fm_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Job(Base):
    __tablename__ = "fm_jobs"
    __table_args__ = (UniqueConstraint("review_id", "kind", "request_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("fm_reviews.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    request_key: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=now, index=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=now)


engine = create_engine(
    settings().database_url,
    pool_pre_ping=True,
    **(
        {"pool_size": 2, "max_overflow": 2, "pool_timeout": 15, "connect_args": {"connect_timeout": 10}}
        if settings().database_url.startswith("postgresql")
        else {}
    ),
)
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def sqlite_fk(dbapi, _):
        dbapi.execute("PRAGMA foreign_keys=ON")


Session = sessionmaker(engine, expire_on_commit=False)


def audit(db, review_id, actor, action, payload):
    db.add(Audit(review_id=review_id, actor=actor, action=action, payload=payload))


def enqueue(db, review_id, kind, key, payload):
    from sqlalchemy import select

    j = db.scalar(select(Job).where(Job.review_id == review_id, Job.kind == kind, Job.request_key == key))
    if j:
        return j
    j = Job(review_id=review_id, kind=kind, request_key=key, payload=payload)
    db.add(j)
    db.flush()
    return j
