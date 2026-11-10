# Fumark Studio · 0.4

Ferramenta interna. Login simplificado, sem logotipo ou textos comerciais. Tipografia nativa do sistema, controles maiores e visual claro em azul e branco. Referência: Apple Human Interface Guidelines (Typography e Accessibility).

## Da seleção à prévia

1. Em Artigos & seleção, revise e aceite os artigos.
2. Use **Preparar pacote e continuar**. PDFs autorizados são procurados automaticamente; Matriz & entrega lista disponíveis e pendentes, com links PubMed/DOI. É possível enviar um PDF obtido com acesso autorizado, confirmando a correspondência ao artigo.
3. Baixe ZIP, matriz e PRISMA ou solicite a pasta no Drive. O pacote pode ser gerado com pendências declaradas. Isso não registra uma leitura de texto completo.
4. Clique **Iniciar prévia inicial**. Os artigos aceitos são vinculados à redação, com indicação de fontes preliminares e avaliações de texto completo.
5. Confira título, cliente, tema, orientações e ficha; PDF/DOCX/TXT é convertido em texto. Salve uma versão.
6. Use **Gerar prévia com IA**. O assistente propõe introdução, problema, justificativa, objetivos e metodologia. Confira as cautelas; **Aplicar proposta no editor** cria uma nova versão.
7. Edite o texto, selecione trechos para comentários e solicite correções no botão **IA**. Exporte em **Word**. Comentários abertos aparecem em uma seção de revisão no Word, não como comentários nativos do Word.

## Atividades

A lista completa com consulta remota, logs, cancelamento e retentativas fica em **Histórico**. Outras abas mostram apenas o resumo das atividades atuais. A prévia mantém um atalho para o Histórico.

## Persistência e segurança

As versões, comentários e propostas usam a auditoria imutável já existente, vinculada à pesquisa e protegida pelo controle de proprietário/RLS existente. Não há migração nova nem permissões ampliadas. O salvamento usa bloqueio da pesquisa e versão esperada: conflitos retornam 409 e preservam o texto no editor. O editor requer salvar as alterações e avisa ao fechar a página com texto pendente.

A IA usa a credencial Browser Use já configurada, com o mesmo limite de custo e concorrência. Recebe a ficha, protocolo, buscas realmente executadas, resumos e extrações estruturadas dos artigos aceitos. Não lê automaticamente os PDFs completos nesta etapa. PMIDs citados são conferidos contra as fontes fornecidas. Propostas nunca mudam o documento automaticamente; decisões científicas permanecem humanas. Submissão, consulta, cancelamento e recuperação seguem os mesmos controles das análises.

## Limites atuais

Editor textual com títulos # e ##, sem importação de formatação Word ou comentários nativos do Word. A prévia é uma versão editorial revisável; não certifica revisão sistemática concluída. PDFs indisponíveis não impedem iniciar a redação, mas limitam as afirmações científicas. Não há integração Sci-Hub. O arquivo DOCX é baixado pelo painel; a entrega automática atual ao Drive continua cobrindo o pacote de pesquisa, não o DOCX da prévia.

## Verificação

59 testes automatizados: regressões do pipeline, autoria, conflitos entre versões, comentários, Word, envio de PDF e proposta de IA sem substituir texto humano. Resposta real do assistente conferida em fixture técnico: concluída, custo US$ 0,001624. Word renderizado e inspecionado; editor e comentários testados pela interface local.
