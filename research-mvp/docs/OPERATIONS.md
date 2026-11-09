# Operação e limites científicos

## Protocolo e julgamento humano

O protocolo registra pergunta, PICO opcional, critérios e hash SHA256 antes da pesquisa. O dono da pesquisa aprova explicitamente. O protocolo não pode ser editado; mudanças requerem nova pesquisa, evitando aplicar novos critérios retroativamente sem registro.

A triagem registra etapas `title_abstract` e `full_text`, com ator validado, horário e motivo. Sugestões do Browser Use não contam como decisões. A inclusão no texto completo exige inclusão prévia de título/resumo e um PDF legal disponível. Não obtenção é uma decisão humana explícita, distinta de exclusão. Uma etapa de título/resumo não pode ser reaberta depois de existir decisão de texto completo; para reavaliar com outros critérios, crie nova pesquisa.

Este MVP usa um revisor por pesquisa. Não implementa triagem dupla independente, adjudicação, RoB 2/ROBINS-I, GRADE, metanálise, busca exaustiva em múltiplas bases, agrupamento de relatos em estudos ou revisão sistemática automaticamente publicável. Pode apoiar essas atividades, preservando dados e decisões. Nenhuma síntese clínica automatizada é apresentada como conclusão científica.

## Busca e rastreabilidade

PubMed é a fonte estruturada de importação. A string original, tradução, total encontrado, horário, XML e referências retornadas ficam preservados. A ordenação é data de publicação. O limite explícito é até 200 por busca; os resultados fora do limite não são tratados como importados, excluídos nem avaliados. Uma revisão completa pode exigir subdivisão planejada das buscas e expansão deste limite antes de uso editorial.

A busca é paginada em lotes de fetch de até 100 dos IDs selecionados. A API não mantém uma sessão ESearch histórica em servidor para milhões de registros. Identificação sem DOI usa PMID, sem fusões aproximadas por título.

Browser Use complementa a verificação web e as sugestões de título/resumo dos artigos importados. Não importa automaticamente novas referências encontradas fora do PubMed. Isso evita misturar achados não verificados às contagens da pesquisa. Cada resposta bruta, modelo, run ID e versão do prompt ficam em auditoria. Sites e artigos são dados não confiáveis; prompts não autorizam compras, login pessoal, mensagens ou execução de comandos.

## PDFs legais

A consulta core do Europe PMC deve confirmar PMID, PMCID, `isOpenAccess=Y` e licença explícita. A implementação permite automaticamente CC BY, CC BY-SA, CC0 e equivalentes públicos reconhecidos, incluindo versões de licença. Licenças não comerciais, personalizadas ou ausentes exigem revisão de permissão.

O PDF é obtido pelo serviço oficial **PMC Cloud**, no bucket público `pmc-oa-opendata`, sem login. A implementação lista somente metadados do PMCID exato, verifica correspondência do PMID, licença da versão, retratação e tipo de versão. Se existirem várias versões publicadas candidatas, não escolhe arbitrariamente: exige seleção humana. Manuscritos não são automaticamente preferidos a artigos publicados.

O antigo PMC OA Web Service e os pacotes FTP legados foram aposentados em agosto de 2026. Eles não são usados. O link de renderização Europe PMC respondeu 403 no teste deste ambiente; a versão final usa a rota oficial PMC Cloud, testada com sucesso.

Domínios de download são fixos, HTTPS obrigatório, redirects checados em cada etapa, limite de 20 MiB, assinatura PDF válida, máximo de 1.000 páginas, sem PDFs criptografados. O checksum MD5 publicado pelo PMC é conferido e também gravamos SHA256 local, URL, data, licença e metadados. O download não usa perfil autenticado nem contorna bloqueios. Arquivos são privados no Supabase.

A extração registra campo, valor, página e citação literal. A citação precisa aparecer no texto extraído da página. O sistema não conclui que um valor está cientificamente correto somente porque a citação existe: o revisor continua responsável pela interpretação. Tabelas difíceis e documentos digitalizados podem exigir extração manual/OCR fora do MVP.

## PRISMA e matriz

O JSON diferencia importados, duplicatas removidas, decisões de resumo, relatórios procurados, não obtidos, disponíveis, efetivamente avaliados, exclusões com motivos, pendências e relatórios incluídos. PDFs disponíveis não são contados como avaliados antes de uma decisão humana final.

`study_count=null` indica ausência de agrupamento de relatórios em estudos. O SVG é um fluxo operacional inspirado no PRISMA, com avisos de parcialidade e pendências; não é uma reprodução certificada do template oficial. Não omita buscas truncadas ou pendências ao preparar uma publicação.

A matriz Excel contém resumo PRISMA, matriz de referências, extração com campos/páginas/citações, auditoria e buscas. O arquivo JSON preserva dados completos, inclusive conteúdos longos que ultrapassem o limite das células Excel. O Excel é um snapshot exportado: editar suas células não modifica decisões no banco. Não há fórmulas de decisão; dados externos são gravados como texto.

## Falhas e recuperação

- **failed:** veja job ID, tipo e run ID, consulte logs do serviço/fornecedor; use “Tentar novamente” após corrigir a causa. Erros guardados no banco não contêm cabeçalhos ou corpos de requisição com segredos.
- **needs_reconciliation:** verifique Browser Use antes de criar outro run. Copie o ID da execução existente para o campo de reconciliação. A API verifica sua relação com os IDs de artigos solicitados e registra a intervenção.
- **PDF unavailable:** verifique a licença e origem; registre não obtenção se não houver uma cópia autorizada. Retentar não amplia automaticamente permissões ou domínios.
- **Auth indisponível:** acesso falha fechado; não se ignora autenticação para contornar a indisponibilidade.
- **Migração pendente:** `/health/ready` retorna 503. Aplique migrações antes de liberar o serviço.

O monitor n8n sinaliza tarefas falhas ou com envio ambíguo por execução com erro. Não há notificação externa configurada. Defina o destino explicitamente antes de adicionar email, Slack ou outro canal.

## Operação recomendada

- Um projeto Supabase dedicado, com cadastro público desabilitado; convide os revisores autorizados.
- Comece com um único consumidor de fila: n8n ou worker contínuo. O lock PubMed serializa os workers deste banco, mas outros programas usando o mesmo IP/API key também precisam respeitar as cotas NCBI.
- Mantenha a política de rede do Browser Use restrita e acompanhe gastos no fornecedor.
- Configure backups, monitoração, restauração e retenção do banco e Storage conforme o plano contratado. A aplicação não apaga dados automaticamente.
- Execute testes e smoke após cada mudança de API de fornecedor. Atualize dependências com revisão, preservando lockfiles.
- Preserve citações, atribuição ao NLM/PMC e licença. Os arquivos são snapshots datados e podem não refletir correções ou retratações posteriores; valide novamente antes da publicação. Não há endosso do NLM à aplicação.

Referências atuais: [PMC Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/textmining/), [PMC Cloud AWS](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/), [metadados e estrutura do dataset](https://pmc-oa-opendata.s3.amazonaws.com/README.txt).
