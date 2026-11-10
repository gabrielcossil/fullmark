# Controle de análises · versão 0.3

## Processamento

A API hospeda um dispatcher residente em produção. Ele atende a fila continuamente, com até dois workers locais. As esperas/polls do Browser Use retornam à fila com próxima consulta em cinco segundos; o ciclo ocioso também usa backoff de cinco segundos. Não há mais um agendamento de um minuto como limite principal. O n8n permanece ativo como fallback e para as integrações Drive/ClickUp.

As submissões remotas têm limite global independente de duas execuções potencialmente ativas. O marcador durável de submissão, os IDs existentes e as respostas concluídas são reaproveitados. A fila usa lock de claim no PostgreSQL, limites globais, lease token e verificação antes do commit. Novas submissões sobre a mesma pesquisa são serializadas. Chamadas ao NCBI passam por um limitador compartilhado de pelo menos 360 ms entre requisições nesta instância.

O serviço continua no plano gratuito Render: interrupções da hospedagem podem atrasar o processamento; jobs são persistidos e retomados. Não foi contratado plano pago nem habilitada recarga. O n8n continua chamando a API a cada minuto para suporte operacional.

## Validação por artigo

Uma citação não literal, item ausente, ID duplicado ou item inválido não elimina o lote inteiro. Recomendações com evidência literal válida são mantidas. O artigo problemático recebe `uncertain`, sem citação fabricada, e aviso de revisão humana. A resposta original continua na auditoria. Se uma resposta posterior trouxer evidência inválida para um artigo já validado, a evidência anterior é preservada.

IDs desconhecidos são ignorados e contabilizados no alerta; não escrevem em artigos externos. O worker consulta a pertença de cada artigo à pesquisa. Falhas determinísticas de formato não são repetidas três vezes sobre a mesma resposta. Falhas transitórias continuam com retentativas limitadas. Lotes novos são limitados a 50 artigos por run; próximos lotes usam os artigos ainda sem análise, sem refazer o que já foi concluído.

`done_with_warnings` significa processamento finalizado com itens para revisão, não aprovação científica. Decisões humanas de título/resumo e texto completo permanecem independentes.

## Novos controles no painel

**Atividade e controle das análises** mostra tarefas concluídas e em andamento, horários, último estado conhecido do provedor e resultado da validação.

- **Ver atividade:** abre eventos registrados, ID remoto, tentativas, última atividade e próxima consulta. O histórico pode ser baixado como JSON.
- **Verificar no provedor agora:** consulta diretamente o Browser Use, sem iniciar uma nova execução. O horário dessa consulta é exibido.
- **Cancelar:** exige confirmação. Buscas, artigos e decisões anteriores são preservados. Quando há um run conhecido, a API pede cancelamento remoto e registra a confirmação. Custos já consumidos permanecem. Resultados que chegam depois de uma solicitação de cancelamento não são aplicados.
- Se a resposta de cancelamento se perder ou o ID de uma submissão ambígua não tiver sido recuperado, o painel indica ausência de confirmação remota; não afirma que a cobrança foi interrompida. A confirmação é repetida com limites, e o operador pode consultar o provedor.
- **Reprocessar resposta existente:** usa o mesmo run ID; não cria uma nova chamada paga. Jobs concluídos não podem ser cancelados retroativamente.

Logs são restritos ao proprietário da pesquisa e não devolvem headers, chaves, senhas ou respostas brutas do provedor. A auditoria científica original continua append-only.

## Meta de pré-seleção

A aba Artigos & seleção permite salvar uma meta de 1 a 200 e selecionar sugestões elegíveis até esse limite. É uma preferência auditada e não altera o protocolo aprovado. A seleção ainda precisa ser confirmada pelo revisor. A prioridade da IA representa aderência relativa aos critérios, não avaliação de qualidade metodológica nem probabilidade calibrada; respostas antigas sem prioridade explícita usam valor neutro.

Se faltarem artigos elegíveis, o painel mostra a diferença e não inclui artigos para completar a quantidade. Citações não validadas não entram na seleção automática de sugestões. O limite de importação por estratégia é outro campo.

## Validação

55 testes automatizados passaram, incluindo lote misto com citação inválida, preservação de evidência anterior, cancelamento em corrida com resposta tardia, isolamento por proprietário, consulta ao provedor, falha de cancelamento e meta maior que as sugestões elegíveis. Lint e sintaxe JavaScript também foram verificados. Controle de cancelamento e visualização de eventos testados pela interface em fixture local identificado como QA.

A recuperação hospedada reaproveitou duas respostas remotas já concluídas, preservou as 40 referências únicas e terminou em `done_with_warnings`, sem retentativas ou novas submissões pagas. Os dois claims ocorreram com menos de um segundo de diferença e ambos concluíram em cerca de dois segundos, validando o processamento paralelo. A tarefa repetida ainda não submetida foi cancelada. A fila ficou sem tarefas pendentes ou com falha após a recuperação.

A permissão real de cancelamento foi conferida no endpoint idempotente usando um run técnico já concluído: HTTP 200, estado completed preservado, sem iniciar execução nova. O cancelamento de run ainda em andamento foi coberto pelos testes controlados; não foi criado um run pago apenas para testar essa função. O limite de concorrência remota também foi conferido no PostgreSQL hospedado com fixtures técnicos não confirmados e rollback.
