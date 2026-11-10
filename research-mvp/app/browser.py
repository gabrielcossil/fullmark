import json
from pathlib import Path
import httpx
from .config import settings
from .schemas import BrowserOutput, PlanningOutput, Finding

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


def poll(run_id, planning=False, observer=None):
    with client() as c:
        r = c.get(f"/runs/{run_id}/status")
        r.raise_for_status()
        status = r.json()["status"]
        if status not in ("completed", "failed", "cancelled"):
            if observer:
                observer({"status": status})
            return None
        r = c.get(f"/runs/{run_id}")
        r.raise_for_status()
        run = r.json()
        if observer:
            observer(run)
        if status != "completed":
            raise ValueError("Browser run " + status)
        output = run.get("output")
        if output is None:
            output = json.loads(run.get("result") or "{}")
        if isinstance(output, str):
            output = json.loads(output)
        if planning:
            return PlanningOutput.model_validate(output), run
        from .job_control import InvalidProviderResult
        from pydantic import ValidationError

        if not isinstance(output, dict) or not isinstance(output.get("findings"), list):
            raise InvalidProviderResult("Formato de resposta inválido")
        valid = []
        invalid = []
        for item in output["findings"][:2000]:
            try:
                valid.append(Finding.model_validate(item))
            except ValidationError:
                invalid.append(item.get("article_id") if isinstance(item, dict) else None)
        run["_invalid_finding_ids"] = invalid
        sources = output.get("sources", [])
        return BrowserOutput(
            findings=valid[:2000], sources=[x for x in sources if isinstance(x, str)][:40] if isinstance(sources, list) else []
        ), run


def cancel(run_id):
    with client() as c:
        r = c.post(f"/runs/{run_id}/cancel")
        r.raise_for_status()
        return r.json()


def inspect(run_id):
    with client() as c:
        r = c.get(f"/runs/{run_id}")
        r.raise_for_status()
        run = r.json()
    return {k: run.get(k) for k in ("status", "createdAt", "updatedAt", "totalCostUsd")}
