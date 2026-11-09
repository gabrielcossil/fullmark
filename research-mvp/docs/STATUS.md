# Estado verificado · 09/11/2026

## Implementado e validado

- FastAPI, painel em português, autenticação Supabase, autorização por proprietário, fila persistente e workers.
- PubMed real: importação com preservação de XML, tradução da string e total encontrado.
- Browser Use V4: adaptador, prompt, schemas, polling e proteção contra reenvio de submissões ambíguas. Contrato testado com respostas simuladas; nenhuma execução paga real realizada nesta sessão.
- PDF real de 18 páginas, licença CC BY, obtido pelo PMC Cloud com identidade e checksum conferidos; texto extraído por página.
- Decisões humanas em duas etapas, histórico append-only, extração com citação e página, matriz XLSX com cinco abas, snapshot JSON e fluxo SVG com pendências.
- 29 testes automatizados passaram. Há um aviso de depreciação do cliente de testes Starlette/httpx, sem falha funcional.
- 13 verificações em PostgreSQL/PGlite, além de teste transacional de RLS executado no Supabase real; os fixtures de nuvem foram revertidos.
- Teste local de ponta a ponta com fontes reais, PDF, extração, seleção e exportação. As decisões do teste são sintéticas e não representam aprovação científica real.
- Interface validada visualmente no navegador; exportações XLSX abertas e renderizadas para conferência.

## Recursos conectados e alterações reais

**Supabase:** projeto `Fullmark` (`blgzcajmjuivaxyblgdi`), organização Fullmark, região `us-east-1`, saudável. Migração aplicada após confirmar schema público vazio. Criadas sete tabelas de aplicação, histórico de migrações, RLS por proprietário, triggers de imutabilidade e bucket privado `fullmark-private` de 20 MiB. O projeto Aptus Clin não foi alterado. O usuário criou o destino; não foi necessário criar projeto duplicado.

**n8n:** dois workflows criados no projeto pessoal **Aptus Digital <aptusworkspace@gmail.com>**, porque esta instância não dispõe de projetos de equipe. São rascunhos e não foram publicados: falta vincular a credencial interna da API.

- [Fullmark · Processar fila](https://n8n-n8n.og3bg4.easypanel.host/workflow/0SPEW7DFBBXjQRHe)
- [Fullmark · Monitorar fila](https://n8n-n8n.og3bg4.easypanel.host/workflow/nbIthVaFfpyofVKt)

**GitHub:** conexão confirmada, repositório `gabrielcossil/fullmark` disponível; código será preservado em pasta/branch própria, mantendo o README existente.

**Render:** conexão confirmada no workspace Fullmark. Publicação depende da fonte Git e dos segredos de execução, configurados diretamente no painel seguro. O serviço não deve ser declarado pronto enquanto `/health/ready` não retornar 200.

## Pendências essenciais

- Configurar a conexão Postgres e a chave secret de Supabase diretamente na hospedagem. O conector administrativo e uma chave publicável não fornecem essas credenciais ao processo Python.
- Configurar chave do Browser Use e política restrita de domínios diretamente na hospedagem.
- Vincular credencial Header Auth `Fullmark Internal` nos dois workflows n8n; nome de header `X-Internal-Token`, valor do segredo `INTERNAL_TOKEN` da hospedagem.
- Desabilitar signup público no Supabase Auth, convidar revisores e testar login/Storage hospedados.
- Publicar workflows somente após API configurada, teste autenticado de produção e verificação de readiness.

Não foram enviadas senhas, tokens ou secret keys a arquivos de código ou documentação. A chave publicável fornecida pelo usuário não é reproduzida nesta entrega.
