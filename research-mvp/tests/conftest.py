import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DEMO_MODE"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["INTERNAL_TOKEN"] = "test-internal-secret-at-least-32-characters"
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app import db, main

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
db.Session.configure(bind=engine)
main.engine = engine


@pytest.fixture(autouse=True)
def reset_db():
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def auth():
    return {"Authorization": "Bearer local-demo"}


@pytest.fixture
def review(client, auth):
    body = {
        "title": "Exercício e quedas",
        "protocol": {
            "question": "Exercício reduz quedas em idosos?",
            "inclusion": ["Ensaios randomizados em idosos"],
            "exclusion": ["Estudos em animais"],
        },
    }
    rid = client.post("/reviews", headers=auth, json=body).json()["id"]
    client.post(f"/reviews/{rid}/approve", headers=auth)
    return rid


@pytest.fixture
def article(review):
    with db.Session() as s:
        a = db.Article(
            review_id=review,
            identity="pmid:1",
            metadata_json={
                "pmid": "1",
                "title": "Trial in older people",
                "abstract": "Randomized trial of exercise.",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
            },
        )
        s.add(a)
        s.flush()
        aid = a.id
        search = db.Search(review_id=review, request_key="seed-search", query="exercise", max_records=1)
        s.add(search)
        s.flush()
        s.add(db.Record(review_id=review, search_id=search.id, article_id=aid, source_id="1", raw=a.metadata_json))
        s.commit()
    return aid
