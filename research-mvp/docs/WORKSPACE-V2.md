# Fullmark Research Studio · versão 0.2

Painel: https://fullmark-research-api.onrender.com

## Processo de trabalho

1. **Dashboard → Nova pesquisa.** Informe título, limite por estratégia, observações e base. Somente PubMed está habilitada. Google Scholar, BVS, Scopus e Web of Science estão identificadas como futuras integrações.
2. Envie a ficha em **PDF textual, DOCX ou TXT**, até 10 MB. Confira o texto extraído. Limite de 100 páginas PDF e 20.000 caracteres de contexto; sem OCR. O arquivo é lido no servidor, e o texto/hash ficam no protocolo; não prometemos conservar o binário original da ficha.
3. **Sugerir com IA** cria uma tarefa na nuvem. O Browser Use recebe o tema e a ficha para propor temas, pergunta, PICO, critérios, filtros, conceitos e estratégias. Os candidatos MeSH são conferidos na API NCBI. A proposta não substitui os campos sem a ação **Aplicar critérios e filtros sugeridos**. Revise e salve.
4. **Aprove o protocolo.** Rascunhos podem ser editados com auditoria; protocolo e título aprovados ficam congelados. Se marcou início automático, a primeira estratégia proposta é executada após sua aprovação. Sem proposta pronta, desmarque a opção ou aguarde o planejamento.
5. Em **Estratégias & descritores**, selecione uma string sugerida ou escreva a sua. O Query Box mostra a combinação com os filtros. A string final é gerada novamente no servidor. Cada estratégia é registrada de forma independente.
6. Acompanhe a fila, o total localizado no PubMed e os registros recebidos. A página consulta o estado a cada cinco segundos. O PubMed responde por lotes de até 25 registros; não simulamos contagens 1, 2, 3. Após importar, aparecem novos únicos e duplicatas de cada estratégia. Localizados na base e importados são contagens distintas.
7. Em **Artigos & seleção**, leia abstract, consulte PubMed/DOI, filtre recomendados, pendentes e duplicatas. As ocorrências duplicadas permanecem rastreáveis por estratégia. A ordenação destaca recomendações de inclusão, sem alegar avaliação formal de qualidade metodológica.
8. Selecione recomendações e clique **Aceitar selecionados**; confira e confirme a justificativa. Isso registra decisão humana de título/resumo e agenda PDFs legais. A avaliação do texto completo permanece separada e não é aprovada automaticamente.
9. Em **Matriz & entrega**, baixe Excel, PRISMA, histórico ou ZIP com PDFs disponíveis. Artigos sem cópia autorizada são listados com motivo e link de plataforma. Não há integração Sci-Hub. O ZIP limita PDFs a 50 MB e lista excedentes para download individual.
10. **Salvar na pasta do Drive** cria uma pasta por entrega em [Fullmark Research Studio](https://drive.google.com/drive/folders/1bj_TGeKYjDaPBj3HzGQWJApUTCZla0P4). Arquivos são enviados individualmente: matriz, PRISMA, CSV, histórico JSON, prompt de metodologia e PDFs dos artigos incluídos na triagem. Uma ação é processada a cada 30 segundos. O painel informa progresso e link da pasta.

## Filtros PubMed

Tipos de estudo, idiomas, intervalo de publicação, espécie, sexo, faixas etárias, disponibilidade de resumo/texto, MEDLINE, exclusão de preprints e ordenação. O campo avançado aceita filtros adicionais da sintaxe PubMed. Tipos de estudo são combinados com OR, idiomas com OR, e grupos com AND. Filtros de indexação podem omitir referências recentes; acesso gratuito não deve ser usado como substituto de elegibilidade científica.

Não implementamos todos os campos do Advanced Builder como controles separados. Campos de autor, periódico, afiliação, termos e filtros especializados podem ser inseridos na string ou no filtro avançado.

## Histórico: dois arquivos diferentes

O **CSV de histórico do sistema** contém a string completa, Query Translation do NCBI, filtros, ordenação, data UTC, total encontrado, importados e duplicatas. XML e resposta ESearch original são preservados no histórico JSON, além de WebEnv/querykey quando retornados. Não reproduzimos o CSV como se tivesse sido baixado do navegador.

O **CSV nativo de Advanced Search / History and Search Details do PubMed** pertence à sessão do navegador. O acesso atual do Browser Use retornou **403** em `/browsers/{session_id}/downloads`; a chave não dispõe da permissão necessária para ler esses downloads. Por isso, o download automatizado desse arquivo nativo não está habilitado. A API e o link para Advanced Search estão disponíveis. [Documentação oficial de History/Search Details](https://pubmed.ncbi.nlm.nih.gov/help/#history).

## ClickUp → pré-inicial automática

No workspace conectado, espaço **Operacional**, foi criada a etiqueta **fullmark-pesquisar**. Para iniciar:

- Use uma tarefa aberta cujo título seja o tema; coloque a ficha textual na descrição (20 a 20.000 caracteres) ou anexe PDF, DOCX ou TXT. Identifique o arquivo no nome como ficha de produção.
- Adicione a etiqueta `fullmark-pesquisar`.
- O n8n consulta apenas esse espaço e etiqueta a cada cinco minutos, cria uma pesquisa na conta redacao@fullmark.com.br e agenda planejamento.
- Após receber a entrada, a etiqueta é retirada da tarefa para consumir o comando. A tarefa não é excluída. Cada tarefa gera uma pesquisa; repetir o comando não duplica trabalhos ou custos de planejamento.
- Abra o painel, aplique/revise critérios e aprove o protocolo. A primeira estratégia e sugestões de triagem podem continuar automaticamente. Os artigos aguardam sua aprovação.
- Após as recomendações da busca automática, uma atualização é enviada à tarefa vinculada. Também há botão de atualização manual com ID explícito da tarefa.

Anexos PDF, DOCX e TXT podem alimentar a entrada: o sistema lê uma ficha identificada pelo nome ou o único documento elegível. Vários arquivos ambíguos exigem escolha pelo painel. O download só aceita HTTPS dos hosts de anexos ClickUp habilitados, sem redirecionamentos, até 10 MB. Outros hosts, arquivos sem texto ou inacessíveis exigem envio pelo painel. A seleção/leitura de anexos foi testada com respostas controladas; não baixamos um anexo real de cliente nesta validação. A leitura de comandos foi testada contra a API real com zero tarefas marcadas; não alteramos uma tarefa real de cliente para testar notificações.

## Pré-inicial e trabalho completo

A pré-inicial já serve de entrada ao planejamento. A aba Trabalho completo oferece encaminhamento à pesquisa e ao pacote de metodologia. O prompt exportado usa dados efetivamente registrados, não inventa metodologia. A geração editorial integral e o template específico da Fullmark aguardam suas próximas instruções. Nenhum serviço chamado “Beehive” foi conectado; o pedido foi atendido como integração n8n/ClickUp, sem presumir outro destino.

## Integrações n8n

Os quatro fluxos estão no projeto pessoal **Aptus Digital <aptusworkspace@gmail.com>**, mantido pela instância existente. Credenciais Fullmark foram vinculadas explicitamente; nenhum segredo foi copiado para parâmetros.

- Processar fila: `0SPEW7DFBBXjQRHe`, a cada minuto.
- Monitorar fila: `nbIthVaFfpyofVKt`, a cada cinco minutos.
- Entregar no Drive/ClickUp: `5I90nNhmfmpq4bOm`, a cada 30 segundos.
- Entrada ClickUp: `ztl2igpf27UGJWVl`, a cada cinco minutos.

A outbox congela um snapshot por entrega e grava cada ID externo confirmado. Uma resposta perdida não causa reenvio cego: após dez minutos sem confirmação, a entrega exige reconciliação operacional no n8n. O monitor sinaliza `needs_reconciliation`; não há botão que envie novamente sem conferir o provedor.

## Validação desta versão

- 45 testes automatizados; lint e sintaxe JavaScript aprovados. Um aviso de depreciação Starlette/httpx permanece.
- Rascunho editável e protocolo aprovado imutável testados no PostgreSQL hospedado em transação revertida.
- PubMed real: uma referência importada novamente resultou em `imported=1`, `new=0`, `duplicates=1`.
- Planejamento real Browser Use: run `484a82c1-01ae-4971-8052-1f7ded91ad97`, concluído, duas estratégias, quatro candidatos MeSH confirmados; custo reportado US$ 0,012621.
- Drive real: seis arquivos enviados, incluindo PDF legal de 18 páginas. [Pasta de QA, sem revisão científica real](https://drive.google.com/drive/folders/1CCIHANJLI4JjUTk07m5hw-5AQRkIknXd).
- ClickUp: leitura real autenticada das tarefas filtradas passou; estado vazio confirmado. Envio de comentário de cliente não foi disparado como teste.
- Layout desktop e largura móvel de 390 px inspecionados; sem transbordamento horizontal no dashboard. Capturas usam dados explicitamente identificados como QA.

O limite Browser Use continua em US$ 0,50 por run, sem compras ou recarga. A primeira versão não incluía planejamento por ficha; esta passa a usar créditos também ao solicitar propostas. O plano gratuito Render pode demorar a acordar. A segurança Supabase continua com aviso de proteção de senhas vazadas desativada, documentado em STATUS.
