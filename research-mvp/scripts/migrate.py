"""Apply immutable SQL migrations transactionally. Reads DATABASE_URL from secret environment."""

from pathlib import Path
import hashlib
from sqlalchemy import text
from app.db import engine


def main():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Use PostgreSQL for migrations")
    with engine.begin() as conn:
        conn.execute(text("select pg_advisory_xact_lock(73941024)"))
        conn.exec_driver_sql(
            "create table if not exists public.fm_schema_migrations (name text primary key, sha256 text not null, applied_at timestamptz not null default now())"
        )
        conn.exec_driver_sql("alter table public.fm_schema_migrations enable row level security")
        conn.exec_driver_sql("revoke all on public.fm_schema_migrations from anon, authenticated")
        for path in sorted(Path("supabase/migrations").glob("*.sql")):
            sql = path.read_text()
            digest = hashlib.sha256(sql.encode()).hexdigest()
            previous = conn.execute(text("select sha256 from public.fm_schema_migrations where name=:name"), {"name": path.name}).scalar()
            if previous:
                if previous != digest:
                    raise RuntimeError("Applied migration checksum mismatch")
                continue
            conn.exec_driver_sql(sql)
            conn.execute(
                text("insert into public.fm_schema_migrations(name,sha256) values (:name,:hash)"), {"name": path.name, "hash": digest}
            )
            print("Applied", path.name)


if __name__ == "__main__":
    main()
