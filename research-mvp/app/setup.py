from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(
        """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fullmark · Configuração</title><body style="margin:0;background:#f5f3eb;color:#153f35;font-family:Georgia,serif"><main style="max-width:760px;margin:15vh auto;padding:32px"><p style="font:700 22px sans-serif">fullmark / pesquisa</p><h1 style="font-size:54px;font-weight:400">Seu espaço de pesquisa<br>está sendo preparado.</h1><p style="font:18px/1.8 sans-serif">A publicação foi iniciada. O administrador precisa concluir a configuração segura dos serviços antes de liberar o acesso às pesquisas.</p></main></body></html>""",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/health/live")
def live():
    return {"status": "setup_pending", "ready": False}


@app.get("/health/ready")
def ready():
    return JSONResponse({"status": "setup_pending", "ready": False}, status_code=503)
