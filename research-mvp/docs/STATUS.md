# Atualização · Fumark Studio 0.5

Biblioteca de prévias independentes, editor rico separado, identificação e formatação estruturadas, modelo DOCX pré-textual, vínculos clicáveis a artigos, notificações persistentes e aprovação antes de iniciar a versão final. [Detalhes e limites](STUDIO-V5.md).

# Atualização · Fumark Studio 0.4

Login e dashboard simplificados, atividades concentradas no Histórico, próximos passos explícitos, editor de prévia com versões, comentários, assistência IA e Word. [Detalhes e limites](STUDIO-V4.md).

# Atualização · Controle de análises 0.3

Fila contínua com até dois workers e duas execuções remotas; validação isolada por artigo; cancelamento com confirmação; histórico consultável e meta de pré-seleção. [Detalhes e limites](JOBS-V3.md). 55 testes passaram. Abaixo seguem evidências históricas das versões anteriores.

# Atualização · Research Studio 0.2

Novo layout, fichas, filtros, descritores, progresso, revisão e entrega ao Drive estão publicados. Quatro workflows n8n ativos. [Guia, evidências e limites atuais](WORKSPACE-V2.md). Validação atual: 45 testes. O relato abaixo preserva as evidências da implantação inicial.

# Estado verificado · 09/11/2026

O MVP está publicado em https://fullmark-research-api.onrender.com e `/health/ready` retorna 200. O serviço funciona na nuvem sem o computador do usuário ligado.

## Implementado

- FastAPI e painel em português, autenticação Supabase e acesso limitado a emails explicitamente autorizados e confirmados. Convite enviado para redacao@fullmark.com.br; o usuário define sua própria senha. O primeiro login pelo usuário ainda não foi observado.
- Supabase Fullmark (`blgzcajmjuivaxyblgdi`): três migrações, RLS por proprietário, auditoria e decisões imutáveis, protocolo aprovado imutável, bucket privado de 20 MiB. Papel de backend restrito, sem superusuário ou BYPASSRLS. O projeto Aptus Clin não foi alterado.
- Fila PostgreSQL persistente com leases e retentativas. No PostgreSQL, o claim usa bloqueio de linha; comparação de timestamps float foi removida para evitar perda de precisão pelo pooler.
- PubMed real com XML, tradução da string, total encontrado e deduplicação por identificadores.
- Browser Use Cloud V4 com chave restrita a runs e network policies, política de rede bloqueando por padrão e permitindo fontes científicas selecionadas. Limite configurado de US$ 0,50 por execução. Sugestões validadas por identificador e citação literal, sem decidir pela pessoa.
- PDF legal pelo PMC Cloud oficial, conferência de identidade, licença, tamanho e checksum; extração por página. Armazenamento e leitura privados por ponte autenticada. Chave administrativa do Supabase permanece no próprio Supabase.
- Triagem humana de título/resumo e texto completo, motivos auditáveis, matriz Excel com cinco abas, snapshot JSON e fluxo SVG inspirado no PRISMA.

## Recursos e evidências

Código: https://github.com/gabrielcossil/fullmark/tree/fullmark-research-mvp/research-mvp. Branch main e README original preservados. Render gratuito, auto-deploy desligado; versão funcional `f24a5f52a9b9ad64a78847560c8e1960d90f41c5`, deploy `dep-dbp35mrbc2fs7390bveg` live.

Os dois workflows estão ativos no projeto pessoal **Aptus Digital <aptusworkspace@gmail.com>** do n8n, pois a instância não oferece projetos de equipe:

- [Processar fila, a cada minuto](https://n8n-n8n.og3bg4.easypanel.host/workflow/0SPEW7DFBBXjQRHe)
- [Monitorar fila, a cada cinco minutos](https://n8n-n8n.og3bg4.easypanel.host/workflow/nbIthVaFfpyofVKt)

Credencial Fullmark Internal configurada e restrita ao domínio da API. Chamadas autenticadas reais passaram: execuções 13840 e 13841. A execução 13865 processou o teste de PDF na nuvem. O convite foi enviado na execução 13861 e sua presença em Enviados foi confirmada por consulta somente leitura na execução 13862; workflow temporário arquivado e função de convite desativada (HTTP 410).

Teste real na nuvem, identificado como QA técnico: review `216ed73f-c35c-4af2-9521-baa48bd4f2c1`, PMID 42987252. Jobs PubMed, Browser Use e PDF concluídos. Run Browser Use `7f5661c8-db1e-492f-ba51-aa83e638aefb` concluído; recomendação validada e persistida. O fixture usa proprietário técnico separado, não aparece nas pesquisas da conta convidada e não representa aprovação científica humana.

33 testes automatizados passaram; um aviso de depreciação Starlette/httpx permanece sem falha funcional. Também passaram 13 verificações PostgreSQL/PGlite e testes transacionais de isolamento/RLS no Supabase. Teste local completo com PDF real, citações, decisões sintéticas e exportações. Planilha aberta e renderizada para conferência. Evidências adicionais nos JSON desta pasta.

## Limites e operação

O plano gratuito Render pode exigir espera na primeira abertura; não há SLA de produção. O monitor sinaliza falhas no histórico do n8n; não envia alertas externos. Pesquisa usa um revisor, até 200 referências por busca e não implementa OCR, triagem dupla, GRADE, metanálise ou agrupamento de relatos em estudos. O fluxo PRISMA é operacional e sinaliza pendências; não é um template oficial certificado.

A chave rápida Browser Use criada inicialmente não foi usada nem removida; a integração utiliza a chave restrita Fullmark Research MVP. Nenhuma compra ou recarga automática foi configurada. Segredos e links de convite não integram o código ou esta documentação.

Última consulta de segurança: RLS sem falhas apontadas; aviso Auth `auth_leaked_password_protection` permanece porque a verificação de senhas vazadas está desativada. [Referência](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection). A aplicação exige senha inicial de pelo menos 12 caracteres.
