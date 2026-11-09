"""Post-deploy PostgreSQL checks, all fixtures rolled back. Never prints credentials."""

from uuid import uuid4
from sqlalchemy import text
from app.db import engine


def main():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Requires PostgreSQL after migration")
    owner, other, r1, r2, aid, audit_id = [str(uuid4()) for _ in range(6)]
    passed = []
    with engine.connect() as c:
        transaction = c.begin()
        try:
            c.execute(
                text(
                    "insert into fm_reviews (id,owner_id,title,protocol,protocol_hash,created_at) values (:r1,:owner,'RLS fixture','{}','test',0),(:r2,:other,'RLS fixture','{}','test',0)"
                ),
                dict(r1=r1, r2=r2, owner=owner, other=other),
            )
            c.execute(
                text(
                    "insert into fm_articles (id,review_id,identity,metadata_json,recommendation,pdf,extraction) values (:id,:rid,'test','{}','{}','{}','{}')"
                ),
                dict(id=aid, rid=r1),
            )
            c.execute(
                text("insert into fm_audit (id,review_id,actor,action,payload,created_at) values (:id,:rid,'fixture','test','{}',0)"),
                dict(id=audit_id, rid=r1),
            )

            def check(name, condition):
                if not condition:
                    raise AssertionError(name)
                passed.append(name)

            c.exec_driver_sql("set local role authenticated")
            c.execute(text("select set_config('request.jwt.claim.sub',:owner,true)"), {"owner": owner})
            check("owner can read own review", c.execute(text("select count(*) from fm_reviews where id=:id"), {"id": r1}).scalar() == 1)
            check(
                "owner cannot read other review", c.execute(text("select count(*) from fm_reviews where id=:id"), {"id": r2}).scalar() == 0
            )
            c.execute(text("select set_config('request.jwt.claim.sub',:owner,true)"), {"owner": other})
            check("other cannot read article", c.execute(text("select count(*) from fm_articles where id=:id"), {"id": aid}).scalar() == 0)
            check("other cannot read audit", c.execute(text("select count(*) from fm_audit where id=:id"), {"id": audit_id}).scalar() == 0)
            c.exec_driver_sql("reset role")
            for role in ("anon", "authenticated"):
                check(
                    role + " cannot write",
                    not c.execute(
                        text("select has_table_privilege(:role,'public.fm_reviews','INSERT,UPDATE,DELETE')"), {"role": role}
                    ).scalar(),
                )
            check(
                "all fm tables have RLS",
                c.exec_driver_sql(
                    "select count(*) from pg_tables where schemaname='public' and tablename like 'fm_%' and not rowsecurity"
                ).scalar()
                == 0,
            )
            check(
                "private storage bucket",
                c.exec_driver_sql("select public=false from storage.buckets where id='fullmark-private'").scalar() is True,
            )
            for name, statement in [
                ("audit append only", "update fm_audit set actor='changed' where id=:id"),
                ("protocol immutable", "update fm_reviews set protocol='{\"changed\":true}' where id=:id"),
            ]:
                blocked = False
                savepoint = c.begin_nested()
                try:
                    c.execute(text(statement), {"id": audit_id if "audit" in name else r1})
                except Exception:
                    blocked = True
                finally:
                    savepoint.rollback()
                check(name, blocked)
        finally:
            transaction.rollback()
    print("Passed PostgreSQL checks:", len(passed))
    for name in passed:
        print("-", name)


if __name__ == "__main__":
    main()
