# Configurar os serviços na nuvem

## 1. Supabase Fullmark

Destino informado: `https://blgzcajmjuivaxyblgdi.supabase.co`. A conexão Fullmark já está autorizada, e as duas migrações desta entrega foram aplicadas e verificadas nesse projeto. A chave publicável não concede acesso administrativo. Não aplique os arquivos no projeto Aptus Clin.

O procedimento usado nesta sessão foi: inspecionar tabelas, aplicar migração, verificar RLS/storage e consultar advisories. Não enviar senhas, connection strings, secret keys ou tokens pelo chat.

Se configurar diretamente:

1. Use um projeto Supabase dedicado à Fullmark, preferencialmente São Paulo. Use o projeto já criado se estiver correto; não crie outro por duplicidade.
2. No painel **Connect**, obtenha a conexão Postgres. Para um serviço sem IPv6, use o session pooler. Configure no gerenciador de segredos da hospedagem `DATABASE_URL=postgresql+psycopg://...?...sslmode=require` com a sintaxe de query correta (se já houver `?`, acrescente `&sslmode=require`). Escape caracteres especiais da senha no URL. Não salve a senha em Git.
3. Configure `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` e a chave **secret** do servidor (`SUPABASE_SECRET_KEY`) no painel da hospedagem. A publicável serve para Auth; a secret é usada somente no backend para Storage.
4. Com `DATABASE_URL` definido no ambiente seguro, execute `python -m scripts.migrate` a partir da raiz. O executor mantém histórico próprio `fm_schema_migrations`, checksums e lock. Não combine com `supabase db push` sem baselining do histórico: escolha um único executor.
5. Confirme sete tabelas de aplicação `fm_*`, mais `fm_schema_migrations`,, RLS ativo, políticas SELECT por proprietário, ausência de grants de escrita para `anon`/`authenticated`, bucket `fullmark-private` com `public=false`.
6. Em **Authentication > Users**, crie/convide revisores, que entrarão com email/senha Supabase no painel. Desabilite cadastro público nas configurações do Supabase Auth; a interface não oferece signup, mas isso sozinho não desabilita a API de signup. Configure SMTP e confirmação de email conforme a política da Fullmark.
7. Configure backups e retenção adequados ao plano. Teste restauração antes de uso institucional. Não há exclusão de pesquisas pela aplicação neste MVP.

A migração adiciona apenas recursos prefixados `fm_` e um bucket dedicado; não altera tabelas de outros produtos. Requer banco Supabase com schemas `auth` e `storage`. Uma segunda execução pelo executor não reaplica a migração já registrada.

## 2. Browser Use Cloud V4

Crie/acesse o projeto em https://cloud.browser-use.com. Configure o segredo `BROWSER_USE_API_KEY` diretamente na hospedagem. Não é necessária uma chave separada de LLM: o agente hospedado é o provedor de sugestões deste MVP.

Crie uma política de rede com allowlist para `pubmed.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov`, `www.ncbi.nlm.nih.gov`, `europepmc.org` e `www.ebi.ac.uk`. Bloqueie outros destinos. Copie o ID para `BROWSER_NETWORK_POLICY_ID`. A aplicação se recusa a criar runs sem essa política. Se o fornecedor exigir algum domínio operacional adicional, revise-o antes de ampliar a lista.

O adaptador usa `POST https://api.browser-use.com/api/v4/runs`, `X-Browser-Use-API-Key`, `outputSchema`, polling em `GET /runs/{id}/status` e leitura final de `GET /runs/{id}`. Modelo configurável; padrão atual `gpt-6-luna`. Sem email, compras, credenciais de navegação ou perfil pessoal. `agentmail=false`.

O teto configurado de US$25 por sessão cobre as categorias descritas pelo fornecedor, não representa um limite global garantido de toda cobrança (navegador/rede e serviços podem ter cobrança própria). Reduza `BROWSER_MAX_COST_USD` se desejar, e limite também o saldo e as permissões no fornecedor. As execuções só são solicitadas pelo revisor.

## 3. Fonte Git e Render

O Render conectado contém o workspace **Fullmark**. Seu conector publica a partir de um repositório Git. O repositório autorizado é `gabrielcossil/fullmark`, e o aplicativo fica na pasta `research-mvp` em branch própria. Não existe implantação real sem essa fonte e os segredos de execução.

1. Publique o conteúdo desta pasta em um repositório privado autorizado. Não inclua `.env`, bancos locais, PDFs, `data/` nem diretórios temporários.
2. Crie o serviço Web a partir do `Dockerfile` ou importe `render.yaml` como Blueprint, no workspace Fullmark.
3. Configure os segredos listados no `.env.example`. Use `ENVIRONMENT=production`, `DEMO_MODE=false` e `INTERNAL_TOKEN` aleatório com pelo menos 32 caracteres. Guarde o mesmo token em uma credencial Header Auth no n8n.
4. Execute as migrações em um terminal seguro com acesso ao banco, **antes** de considerar a aplicação pronta. A aplicação em produção não executa DDL automaticamente.
5. Deploy e healthcheck `/health/ready`. Confirme `FULLMARK_API_URL=https://...` e execute `python scripts/smoke.py`.
6. O plano web gratuito pode dormir. Para o MVP econômico, use o n8n para `/internal/tick`, com timeout de 210 s. Não depende de seu computador. O painel pode levar tempo para acordar.
7. Para processamento contínuo, use serviço web e worker sempre ligados. O worker executa `python -m app.worker` com os mesmos segredos; desative o workflow de processamento quando escolher esse modo. Contrate plano pago apenas após aprovar seu custo.

O `render.yaml` não cria banco Render: Supabase continua sendo o banco de aplicação. Não há tráfego de produção permitido para SQLite. Os artefatos persistem no Supabase Storage; o disco efêmero do Render não é o armazenamento de produção.

## 4. n8n existente

Endereço informado: `https://n8n-n8n.og3bg4.easypanel.host/mcp-server/http`. A conexão autenticada n8n está disponível e permitiu criar os dois rascunhos. Ele é um endereço MCP, não a API REST de administração de workflows.

Nesta instância, o MCP oferece SDK, criação, atualização, validação e testes. Os workflows já foram criados por essa conexão. Não os importe de novo: abra os links em STATUS.md e configure as credenciais pendentes. As orientações de importação abaixo servem para restaurar em outra instância.

Importação manual quando necessário:

1. Abra o editor da instância em `https://n8n-n8n.og3bg4.easypanel.host` com sua conta.
2. Importe `n8n/01-process-queue.json` e `n8n/02-monitor-queue.json`.
3. Em ambos, no nó HTTP, configure a URL real do serviço seguida de `/internal/tick` ou `/internal/queue`.
4. Crie credencial **Header Auth** com Name `X-Internal-Token` e Value igual ao segredo `INTERNAL_TOKEN` da API. Selecione-a nos nós HTTP. O workflow não contém segredo exportado.
5. Execute manualmente e confirme resposta `processed: false` quando não há tarefas, ou `true` quando uma foi processada. Uma resposta `true` significa tentativa processada; consulte o estado final da tarefa no painel.
6. Ative o workflow de fila (a cada minuto). Ative o monitor (a cada cinco minutos). Falhas/reconciliações fazem o monitor falhar visivelmente no n8n.
7. Configure notificações de falha no n8n para o canal escolhido. Esta entrega não enviou mensagens nem configurou um destinatário sem autorização específica.
8. Defina fuso `America/Bahia`. Os agendamentos por intervalo não dependem do horário local; registros científicos usam UTC.

Sucesso de uma chamada HTTP não é evidência de importação no n8n. Verifique os workflows e suas execuções na instância antes de declarar o deploy concluído.

## Fontes oficiais consultadas em 09/11/2026

- [Browser Use quickstart V4](https://docs.browser-use.com/cloud/agent/quickstart)
- [Contrato OpenAPI V4](https://docs.browser-use.com/openapi/v4.json)
- [Supabase changelog](https://supabase.com/changelog)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
- [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [PMC Cloud AWS: distribuição atual](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/)
- [n8n deployment configuration](https://docs.n8n.io/hosting/configuration/environment-variables/deployment/)
