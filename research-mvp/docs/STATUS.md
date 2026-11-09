# Estado verificado · 09/11/2026

## Implementado e validado

- FastAPI, painel em português, autenticação Supabase, autorização por proprietário, fila persistente e workers.
- PubMed real: importação com preservação de XML, tradução da string e total encontrado.
- Browser Use V4: adaptador, prompt, schemas, polling e proteção contra reenvio de submissões ambíguas. Contrato testado com respostas simuladas; nenhuma execução paga real realizada nesta sessão.
- PDF real de 18 páginas, licença CC BY, obtido pelo PMC Cloud com identidade e checksum conferidos; texto extraído por página.
- Decisões humanas em duas etapas, histórico append-only, extração com citação e página, matriz XLSX com cinco abas, snapshot JSON e fluxo SVG com pendências.
- 31 testes automatizados passaram. Há um aviso de depreciação do cliente de testes Starlette/httpx, sem falha funcional.
- 13 verificações em PostgreSQL/PGlite, além de teste transacional de RLS executado no Supabase real; os fixtures de nuvem foram revertidos.
- Teste local de ponta a ponta com fontes reais, PDF, extração, seleção e exportação. As decisões do teste são sintéticas e não representam aprovação científica real.
- Interface validada visualmente no navegador; exportações XLSX abertas e renderizadas para conferência.

## Recursos conectados e alterações reais

**Supabase:** projeto `Fullmark` (`blgzcajmjuivaxyblgdi`), organização Fullmark, região `us-east-1`, saudável. Migração aplicada após confirmar schema público vazio. Criadas sete tabelas de aplicação, histórico de migrações, RLS por proprietário, triggers de imutabilidade e bucket privado `fullmark-private` de 20 MiB. O projeto Aptus Clin não foi alterado. O usuário criou o destino; não foi necessário criar projeto duplicado.

**n8n:** dois workflows criados no projeto pessoal **Aptus Digital <aptusworkspace@gmail.com>**, porque esta instância não dispõe de projetos de equipe. São rascunhos e não foram publicados: falta vincular a credencial interna da API. Os URLs HTTP já estão configurados para o serviço Render. Testes com respostas HTTP simuladas: fila sucesso (execução 13823); monitor sem falhas sucesso (13824); monitor com falha erro esperado (13825). Não houve chamada de produção autenticada entre n8n e API.

- [Fullmark · Processar fila](https://n8n-n8n.og3bg4.easypanel.host/workflow/0SPEW7DFBBXjQRHe)
- [Fullmark · Monitorar fila](https://n8n-n8n.og3bg4.easypanel.host/workflow/nbIthVaFfpyofVKt)

**GitHub:** código publicado em [gabrielcossil/fullmark](https://github.com/gabrielcossil/fullmark/tree/fullmark-research-mvp/research-mvp), pasta `research-mvp`, branch `fullmark-research-mvp`. README original e branch main preservados. Nenhum segredo foi incluído.

**Render:** serviço gratuito criado e build concluído, deploy `dep-dbp2a2rl550s73c4c4g0` com estado `live`. URL: https://fullmark-research-api.onrender.com. A aplicação está em **modo de configuração fechado**, com `/health/live` indicando `setup_pending` e `/health/ready` retornando 503. Isso é uma publicação do código, não uma API de pesquisa já liberada. [Configurar ambiente](https://dashboard.render.com/web/srv-dbp2a23l550s73c4c340/env). Auto-deploy está desligado para mudanças controladas.

## Pendências essenciais

- Banco e arquivos já configurados automaticamente: papel dedicado `fullmark_runtime`, pooler SSL validado e ponte autenticada `fullmark-storage`. Render não precisa da chave administrativa do Supabase. A nova versão precisa ser implantada para usar a ponte.
- Configurar chave do Browser Use e política restrita de domínios diretamente na hospedagem.
- Vincular credencial Header Auth `Fullmark Internal` nos dois workflows n8n; nome de header `X-Internal-Token`, valor do segredo `INTERNAL_TOKEN` da hospedagem.
- Desabilitar signup público no Supabase Auth, convidar revisores e testar login/Storage hospedados.
- Publicar workflows somente após API configurada, teste autenticado de produção e verificação de readiness.

Não foram enviadas senhas, tokens ou secret keys a arquivos de código ou documentação. A chave publicável fornecida pelo usuário não é reproduzida nesta entrega.

## Validação Supabase hospedado

O teste transacional confirmou leitura própria, bloqueio entre proprietários, negação de escrita cliente, negação de leitura anônima e imutabilidade de auditoria/protocolo. Todas as oito tabelas `fm_*` têm RLS; há zero grants INSERT/UPDATE/DELETE para clientes. Bucket privado de 20 MiB. Após política explícita de negação para metadados de migração, os advisories de segurança retornaram lista vazia. Os 12 avisos de índices ainda não usados são informativos em banco recém-criado e foram mantidos. [Referência do aviso](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).

## Configuração automática adicional

Foi aplicado um papel de backend dedicado, sem superusuário e sem BYPASSRLS, com acesso somente às tabelas do aplicativo. Sua senha foi gerada e configurada diretamente no ambiente Render, sem incluí-la em migrações, código ou documentação. A conexão SSL via session pooler foi testada com sucesso.

A Edge Function `fullmark-storage` mantém o service role interno ao Supabase. Ela exige um token exclusivo de servidor (diferente do token n8n), armazena apenas seu hash no código e permite GET/POST somente no bucket privado e em caminhos estritos do aplicativo. Teste real: requisição sem token 401; upload autorizado 200; leitura idêntica validada. Um pequeno JSON identificado como QA foi conservado no bucket, conforme runtime-validation.json.
