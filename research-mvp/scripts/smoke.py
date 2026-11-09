"""Non-destructive deployment readiness check. No secrets printed."""

import os, httpx

base = os.environ["FULLMARK_API_URL"].rstrip("/")
with httpx.Client(timeout=70) as c:
    for path in ("/health/live", "/health/ready"):
        r = c.get(base + path)
        print(path, r.status_code)
        r.raise_for_status()
    r = c.get(base + "/reviews")
    assert r.status_code == 401, "Reviews must require authentication"
    r = c.post(base + "/internal/tick")
    assert r.status_code == 401, "Worker must require internal credential"
print("Public readiness checks passed")
