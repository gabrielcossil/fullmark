import pytest, respx, httpx
from app import db, browser, worker
from app.schemas import BrowserOutput
from app.job_control import InvalidProviderResult


def make_job(review, article, key="run-01"):
    with db.Session() as s:
        j = db.enqueue(s, review, "browser", key, {"article_ids": [article]})
        j.external_id = key
        s.commit()
        return j.id


def test_mixed_batch_keeps_valid_results(review, article, monkeypatch):
    with db.Session() as s:
        a = db.Article(review_id=review, identity="pmid:2", metadata_json={"title": "Second trial", "abstract": "Actual evidence."})
        s.add(a)
        s.flush()
        aid = a.id
        j = db.enqueue(s, review, "browser", "mixed", {"article_ids": [article, aid]})
        j.external_id = "mixed"
        jid = j.id
        s.commit()
    output = BrowserOutput(
        findings=[
            {"article_id": article, "recommendation": "include", "reason": "Trial matches", "quote": "Randomized trial of exercise."},
            {"article_id": aid, "recommendation": "include", "reason": "Looks good", "quote": "Invented evidence"},
        ]
    )
    monkeypatch.setattr(browser, "poll", lambda *a, **kw: (output, {"model": "test", "status": "completed"}))
    assert worker.tick()
    with db.Session() as s:
        assert s.get(db.Article, article).recommendation["evidence_status"] == "verified"
        bad = s.get(db.Article, aid).recommendation
        assert bad["recommendation"] == "uncertain" and bad["quote"] == ""
        j = s.get(db.Job, jid)
        assert j.status == "done_with_warnings" and j.attempts == 0
        assert j.payload["validation"]["verified"] == 1 and j.payload["validation"]["manual_review"] == 1


def test_new_invalid_output_does_not_erase_verified_evidence(review, article, monkeypatch):
    jid = make_job(review, article)
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.recommendation = {"recommendation": "include", "reason": "Already verified", "quote": "Randomized trial of exercise."}
        s.commit()
    out = BrowserOutput(
        findings=[{"article_id": article, "recommendation": "exclude", "reason": "Bad new quote", "quote": "Not in source"}]
    )
    monkeypatch.setattr(browser, "poll", lambda *a, **kw: (out, {}))
    worker.tick()
    with db.Session() as s:
        assert s.get(db.Article, article).recommendation["reason"] == "Already verified"
        assert s.get(db.Job, jid).payload["validation"]["retained_previous"] == 1


def test_cancel_queued_job_and_owner_isolation(client, auth, review, article):
    with db.Session() as s:
        j = db.enqueue(s, review, "browser", "not-sent", {})
        jid = j.id
        s.commit()
    assert client.post(f"/reviews/{review}/jobs/{jid}/cancel").status_code == 401
    assert client.post(f"/reviews/other/jobs/{jid}/cancel", headers=auth).status_code == 404
    assert client.post(f"/reviews/{review}/jobs/{jid}/cancel", headers=auth).json()["status"] == "cancelled"
    assert not worker.tick()
    with db.Session() as s:
        assert s.get(db.Article, article) is not None


def test_cancel_remote_and_live_logs(client, auth, review, article, monkeypatch):
    jid = make_job(review, article)
    calls = []
    monkeypatch.setattr(browser, "cancel", lambda run: calls.append(run) or {"status": "cancelled"})
    assert client.post(f"/reviews/{review}/jobs/{jid}/cancel", headers=auth).json()["status"] == "cancelled"
    assert calls == ["run-01"]
    monkeypatch.setattr(browser, "inspect", lambda run: {"status": "cancelled", "totalCostUsd": "0.02"})
    r = client.get(f"/reviews/{review}/jobs/{jid}/logs?refresh_provider=true", headers=auth)
    assert r.status_code == 200 and r.json()["remote"]["status"] == "cancelled"
    assert any(e["event"] == "cancelled" for e in r.json()["events"])
    assert client.get(f"/reviews/other/jobs/{jid}/logs", headers=auth).status_code == 404
    assert "headers" not in r.text.lower() and "apikey" not in r.text.lower()


def test_cancel_during_poll_prevents_late_results(review, article, monkeypatch):
    jid = make_job(review, article)
    out = BrowserOutput(
        findings=[{"article_id": article, "recommendation": "include", "reason": "Matches", "quote": "Randomized trial of exercise."}]
    )

    def poll(*a, **kw):
        with db.Session() as s:
            j = s.get(db.Job, jid)
            j.status = "cancel_requested"
            s.commit()
        return out, {"status": "completed"}

    monkeypatch.setattr(browser, "poll", poll)
    worker.tick()
    with db.Session() as s:
        assert not s.get(db.Article, article).recommendation
        assert s.get(db.Job, jid).status == "cancel_requested"
    monkeypatch.setattr(browser, "cancel", lambda run: {"status": "cancelled"})
    worker.tick()
    with db.Session() as s:
        assert s.get(db.Job, jid).status == "cancelled"


def test_deterministic_provider_error_does_not_repeat_three_times(review, article, monkeypatch):
    jid = make_job(review, article)

    def fail(*a, **kw):
        raise InvalidProviderResult("bad shape")

    monkeypatch.setattr(browser, "poll", fail)
    worker.tick()
    with db.Session() as s:
        j = s.get(db.Job, jid)
        assert j.status == "failed" and j.attempts == 1
    assert not worker.tick()


@respx.mock
def test_provider_item_validation_is_isolated(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "browser_use_api_key", "test-key")
    respx.get(browser.BASE + "/runs/r/status").mock(return_value=httpx.Response(200, json={"status": "completed"}))
    respx.get(browser.BASE + "/runs/r").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "completed",
                "output": {
                    "findings": [
                        {"article_id": "good", "recommendation": "include", "reason": "criterion", "quote": "source"},
                        {"article_id": "bad", "recommendation": "invented"},
                    ]
                },
            },
        )
    )
    output, raw = browser.poll("r")
    assert len(output.findings) == 1 and raw["_invalid_finding_ids"] == ["bad"]


def test_target_does_not_invent_candidates(client, auth, review, article):
    with db.Session() as s:
        a = s.get(db.Article, article)
        a.recommendation = {"recommendation": "include", "quote": "Randomized trial of exercise.", "priority": 80}
        s.commit()
    assert client.post(f"/reviews/{review}/selection-target", headers=auth, json={"target": 15}).status_code == 200
    summary = client.get("/reviews/" + review, headers=auth).json()["selection_summary"]
    assert summary["eligible"] == 1 and summary["shortfall"] == 14 and summary["suggested_ids"] == [article]
    snap = client.get("/reviews/" + review, headers=auth).json()
    assert snap["decisions"] == []


def test_cancel_failure_remains_retryable_then_marks_unknown(review, article, monkeypatch):
    jid = make_job(review, article)
    with db.Session() as s:
        j = s.get(db.Job, jid)
        j.status = "cancel_requested"
        s.commit()

    def unavailable(run):
        raise httpx.ConnectError("no private details")

    monkeypatch.setattr(browser, "cancel", unavailable)
    for attempt in range(3):
        assert worker.tick()
        with db.Session() as s:
            j = s.get(db.Job, jid)
            j.available_at = 0
            s.commit()
    with db.Session() as s:
        assert s.get(db.Job, jid).status == "cancel_unknown"


def test_missing_and_duplicate_findings_become_review_not_batch_failure(review, article, monkeypatch):
    jid = make_job(review, article)
    item = {"article_id": article, "recommendation": "include", "reason": "criterion", "quote": "Randomized trial of exercise."}
    monkeypatch.setattr(browser, "poll", lambda *a, **kw: (BrowserOutput(findings=[item, item]), {}))
    worker.tick()
    with db.Session() as s:
        assert s.get(db.Article, article).recommendation["validation_issue"] == "duplicate_id"
        assert s.get(db.Job, jid).status == "done_with_warnings"
