# Prévias iniciais e editor · versão 0.5

## Organização

A aba Prévia inicial é uma biblioteca de trabalhos. **Nova prévia inicial** vincula uma pesquisa aprovada e cria um documento independente; é possível criar várias prévias sobre a mesma pesquisa. A prévia anterior permanece como registro legado e conserva conteúdo, comentários, versões e propostas. Cada cartão informa cliente, pesquisa, fontes e etapa.

A ficha contém identificação (cliente/autor, cidade, instituição, curso, redator, orientador, banca e ano), tema, ficha de produção, orientações, meta de páginas, fonte, tamanho, entrelinhas e margens em centímetros. A meta de páginas orienta a IA; a contagem real deve ser conferida no arquivo Word.

## Editor separado

**Editor de texto** na barra lateral e **Abrir editor de texto** na ficha abrem a área de edição. Recursos: títulos, negrito, itálico, sublinhado, riscado, grifo, fontes, tamanho, cor, alinhamento, listas, sobrescrito/subscrito, tabelas, linhas e colunas, desfazer/refazer, localizar e substituir uma ocorrência, comentários/elogios por trecho e exportação DOCX. Não é uma reprodução integral do Microsoft Word; não inclui edição simultânea, controle nativo de alterações, paginação exata nem todos os recursos de layout do Word.

Comentários mantêm a citação do trecho e permitem localizá-la. Se o trecho for reescrito e não puder ser localizado, o comentário original permanece com aviso. No Word, comentários abertos são exportados em uma seção de revisão, e não como comentários nativos nas margens.

Citações PMID no texto são clicáveis e abrem um pop-up com título, resumo, indicação de avaliação, link PubMed e PDF privado quando disponível. Também há uma lista das fontes por trecho. O vínculo identifica a fonte declarada; não certifica que cada afirmação foi verificada integralmente. As referências devem ser revisadas por uma pessoa.

## Modelo pré-textual

Envie DOCX de até 4 MB. O modelo é preservado como base do Word exportado. Use marcadores `{{nome}}`, `{{titulo}}`, `{{cidade}}`, `{{redator}}`, `{{banca}}`, `{{instituicao}}`, `{{curso}}`, `{{ano}}` e `{{orientador}}`. Marcadores divididos entre runs podem exigir reconstrução do parágrafo, perdendo a formatação específica daquele parágrafo. Texto em caixas, campos complexos e marcadores em cabeçalhos/rodapés não são substituídos nesta versão. O corpo da prévia é acrescentado após uma quebra de página. As margens e a fonte principal seguem a configuração da ficha. Macros, objetos incorporados e vínculos externos são recusados.

Sem modelo, o Word gera uma identificação pré-textual simples com os campos preenchidos. O documento final sempre requer conferência editorial.

## Revisão e notificações

Geração concluída cria proposta pronta para revisão e notificação persistente. O sino atualiza a cada 15 segundos enquanto o sistema está aberto e mostra notificações não lidas ao retornar; não são notificações push ou emails. A IA continua funcionando na nuvem.

Fluxo: preparação → geração → revisão humana → ajustes solicitados → correção com IA → revisão → aprovação. Propostas só substituem o texto após **Aplicar proposta no editor**. A aprovação exige texto salvo, ausência de comentários abertos e ausência de análises em andamento. Prévia aprovada fica bloqueada; use **Solicitar ajustes / reabrir** com justificativa para voltar a editar. **Iniciar versão final** exige aprovação e registra a versão aprovada no histórico. A biblioteca Trabalho completo lista essas iniciações; a geração e edição completa do trabalho final ainda não estão implementadas.

## Implementação e proteção

Documentos independentes usam identificadores de eventos de criação e revisões append-only na auditoria existente. Todas as rotas verificam o proprietário e a vinculação do documento à pesquisa. Sem novas permissões, tabelas ou migrações. Modelos são armazenados uma única vez como evento privado; revisões referenciam esse evento. O binário é omitido dos snapshots de acompanhamento e do contexto da IA. O editor Tiptap 3.33.1 é servido localmente, com fonte e lockfile versionados. O JSON rico é validado e o Word é gerado a partir da estrutura, sem executar HTML fornecido pelo usuário.

## Validação

62 testes passaram, incluindo independência entre prévias, autorização por proprietário, conflitos de versão, comentários, bloqueio após aprovação, reabertura com justificativa, início da versão final, notificações persistentes e Word com modelo, identificação, margens e destaque. Editor, negrito/grifo, salvamento e pop-up de artigo foram conferidos na interface local. Word com modelo pré-textual foi renderizado e as duas páginas inspecionadas. Não foram criadas novas execuções pagas para repetir a geração já validada na versão anterior.

Build do editor: `cd editor && npm ci && npm run build`. O deploy Docker usa uma etapa Node para compilar o editor e uma imagem Python para executar a API. Dependências e lockfile ficam versionados; os recursos são servidos pelo próprio aplicativo.
