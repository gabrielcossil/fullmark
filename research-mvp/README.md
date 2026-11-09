# Fullmark Research · MVP 0.1

Aplicação executável para pesquisa bibliográfica: FastAPI, fila persistente PostgreSQL, Supabase Auth/Storage, Browser Use Cloud **V4**, PubMed e workflows n8n. Interface em português incluída no mesmo serviço.

**Estado desta entrega:** MVP publicado e conectado a Supabase, Browser Use V4 e n8n; workflows ativos e teste real na nuvem concluído. Acesso: https://fullmark-research-api.onrender.com. Veja [STATUS.md](docs/STATUS.md) para evidências e limites.

## Executar localmente

Requisitos: Python 3.12+ e [uv](https://docs.astral.sh/uv/). As dependências estão fixadas em `uv.lock` e `requirements.lock`.

```sh
cp .env.example .env
uv sync --frozen
# Somente para demonstração local: DEMO_MODE=true no .env.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Em outro terminal, na mesma pasta:

```sh
uv run python -m app.worker
```

Abra http://127.0.0.1:8000. O botão de demonstração só aparece com `DEMO_MODE=true`; não use esse modo em hospedagem pública. SQLite permite experimentar a aplicação. PostgreSQL é obrigatório em produção. Não rode um worker SQLite e a API em contêineres diferentes com bancos locais independentes.

Fluxo funcional:

1. Crie a pergunta e os critérios; leia e aprove o protocolo imutável.
2. Envie uma string PubMed e o limite de importação, de 1 a 200 por busca.
3. Atualize o andamento; a fila busca os metadados e preserva XML, tradução da string e total encontrado.
4. Opcionalmente solicite Browser Use: ele consulta as fontes e propõe triagem, com evidência literal validada. É necessário configurar chave e política de domínios antes.
5. Registre decisões humanas de título/resumo. Cada inclusão agenda obtenção legal de PDF.
6. Leia o texto completo e registre inclusão, exclusão, incerteza ou não obtenção, com motivo. O sistema não inclui um texto sem PDF disponível.
7. Registre campos da matriz, página e citação literal. A API confere a citação no texto extraído da página. PDFs digitalizados precisam de OCR externo; não há OCR neste MVP.
8. Baixe matriz Excel, fluxo SVG e o histórico JSON completo.

## Organização do projeto

- `app/main.py`: autenticação, autorização, interface e endpoints.
- `app/worker.py`: claims atômicos, recuperação de leases, retentativas e tarefas de fornecedores.
- `app/db.py`: tabelas e modelos; `supabase/migrations/`: SQL revisável com RLS e bucket privado.
- `app/pubmed.py`: ESearch/EFetch, XML e normalização de identificadores.
- `app/browser.py` e `app/prompts/`: contrato V4 e prompt versionado.
- `app/files.py`: OA, download restrito e Storage privado.
- `app/service.py`: decisões, auditoria, contagens e snapshot.
- `app/exports.py`: XLSX OOXML portátil, SVG e segurança de células.
- `n8n/`: dois workflows importáveis, desativados por padrão.
- `scripts/migrate.py`: migrações transacionais com checksum e lock.
- `scripts/smoke.py`: verificações públicas após deploy.
- `tests/`: testes de comportamento e contratos HTTP simulados.

## Documentação

- [Configurar e implantar](docs/DEPLOY.md)
- [Arquitetura, API e decisões técnicas](docs/ARCHITECTURE.md)
- [Operação, dados e critérios científicos](docs/OPERATIONS.md)
- [Status e bloqueios verificados](docs/STATUS.md)
- [Resultado da validação PostgreSQL](docs/postgres-validation.json)

## Testes

```sh
uv run pytest -q
uv run ruff check app tests scripts
node --check app/static/app.js
```

Os testes não exigem credenciais reais. Integrações simuladas são identificadas como tal. A validação real do PubMed não substitui teste pago do Browser Use, de Auth/Storage hospedados ou do n8n de produção.
