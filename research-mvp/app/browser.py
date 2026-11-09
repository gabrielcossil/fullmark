import json
from pathlib import Path
import httpx
from .config import settings
from .schemas import BrowserOutput, PlanningOutput

BASE = "https://api.browser-use.com/api/v4"


def client():
    if not settings().browser_use_api_key:
        raise RuntimeError("BROWSER_USE_API_KEY not configured")
    return httpx.Client(base_url=BASE, headers={"X-Browser-Use-API-Key": settings().browser_use_api_key}, timeout=35)


def submit(protocol, articles, planning=False):
    s = settings()
    if not s.browser_network_policy_id:
        raise RuntimeError("Browser network allowlist policy is required")
    prompt = Path(__file__).with_name("prompts").joinpath("planning.txt" if planning else "research.txt").read_text()
    task = prompt + "\nUNTRUSTED_DATA_JSON:\n" + json.dumps({"protocol": protocol, "articles": articles}, ensure_ascii=False)
    with client() as c:
        r = c.post(
            "/runs",
            json={
                "task": task,
                "outputSchema": (PlanningOutput if planning else BrowserOutput).model_json_schema(),
                "model": s.browser_model,
                "maxCostUsd": s.browser_max_cost_usd,
                "agentmail": False,
                "browserSettings": {"networkPolicyId": s.browser_network_policy_id, "record": False},
            },
        )
        r.raise_for_status()
        return r.json()["id"]


def poll(run_id, planning=False):
    with client() as c:
        r = c.get(f"/runs/{run_id}/status")
        r.raise_for_status()
        status = r.json()["status"]
        if status not in ("completed", "failed", "cancelled"):
            return None
        r = c.get(f"/runs/{run_id}")
        r.raise_for_status()
        run = r.json()
        if status != "completed":
            raise ValueError("Browser run " + status)
        output = run.get("output")
        if output is None:
            output = json.loads(run.get("result") or "{}")
        if isinstance(output, str):
            output = json.loads(output)
        return (PlanningOutput if planning else BrowserOutput).model_validate(output), run
