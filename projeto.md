# projeto.md - CONTEXTO COMPLETO DO PROJETO: Bot de Orçamento Pessoal (Telegram)

Atualizado em 20/11/2026.

Como usar: cole este arquivo inteiro numa IA nova e, em seguida, cole o main.py. Tudo aqui descreve o main.py atual (arquivo único). O bot e todas as mensagens são em português do Brasil. Itens marcados "(informado pelo dono, fora do main.py)" não estão no código.

## 1. STACK

- Linguagem: Python 3 (usa `zoneinfo`, então precisa de Python 3.9 ou mais novo).
- Telegram: `python-telegram-bot[webhooks]==21.6`. Tudo é assíncrono (`async def`). Usa ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, TypeHandler, ApplicationHandlerStop, `filters`.
- Servidor web (modo webhook): `starlette` + `uvicorn` (sem versão fixada no requirements). O bot NÃO usa mais o `app.run_webhook` do python-telegram-bot; ele sobe um servidor próprio (função `rodar_webhook`) para poder responder a um health check. Os imports de uvicorn/starlette ficam DENTRO de `rodar_webhook` (só são necessários em modo webhook).
- Banco: Supabase, cliente `supabase` (supabase-py). No requirements.txt do dono: `supabase==2.7.1`.
- `httpx==0.27.2` (fixado por compatibilidade com o supabase-py e o python-telegram-bot).
- `python-dotenv==1.0.1` está no requirements, mas NÃO é usado no main.py.
- `tzdata` (garante o fuso America/Sao_Paulo no Render).
- `matplotlib` (gráficos). Só é importado dentro de `_plt()`, com backend "Agg".
- requirements.txt do dono (informado pelo dono, fora do main.py): python-telegram-bot[webhooks]==21.6, supabase==2.7.1, httpx==0.27.2, python-dotenv==1.0.1, tzdata, matplotlib, starlette, uvicorn (uma por linha).
- Deploy: GitHub -> Render -> Supabase. O Render faz deploy automático a cada commit na branch main.
- Modo de execução (função `main()`): se a variável RENDER_EXTERNAL_URL existir e não for vazia, roda `asyncio.run(rodar_webhook(montar_app(com_updater=False)))` (webhook, com health check). Senão, roda `montar_app().run_polling()` (polling).
- Timezone: `TZ = ZoneInfo("America/Sao_Paulo")`. "Hoje" é sempre `hoje_sp()`. Datas de gastos são convertidas para esse fuso na leitura.
- Mensagens de erro e logs usam `print(...)` (aparecem nos Logs do Render).

## 2. ENV VARS

- `BOT_TOKEN`: token do BotFather. Obrigatória (`os.environ["BOT_TOKEN"]`, dá KeyError se faltar).
- `SUPABASE_URL`: URL do projeto Supabase. Obrigatória.
- `SUPABASE_KEY`: chave do Supabase. Obrigatória. (informado pelo dono, fora do main.py) Todas as tabelas estão com RLS ativado e sem policies, então precisa ser a chave com acesso total (service_role / secret). Se for a anon/publishable, as consultas voltam vazias ou dão erro.
- `PORT`: porta do servidor. Opcional, padrão 10000 (o Render define sozinho).
- `RENDER_EXTERNAL_URL`: URL pública do serviço (o Render define sozinho). Opcional, padrão "". Presente = webhook. Ausente = polling.
- `ALLOWED_USER_IDS`: IDs numéricos do Telegram permitidos, separados por vírgula ou ponto e vírgula (ex.: `123456789,987654321`). Pedaços que não são só dígitos são ignorados. Segurança "fechada": se a lista ficar vazia ou inválida, o bot ignora TODO MUNDO e imprime "ATENÇÃO: ALLOWED_USER_IDS vazio ou inválido. O bot vai ignorar todo mundo!".
- (Render, informado pelo dono, fora do main.py) `PYTHON_VERSION` é configuração do Render, não é lida pelo código.

## 3. INFRA

(informado pelo dono, fora do main.py, exceto onde indicado)

- GitHub: repositório com `main.py` e `requirements.txt`.
- Render: Web Service no plano gratuito. Build Command `pip install -r requirements.txt`. Start Command `python main.py`.
- Supabase: plano gratuito (projetos gratuitos são pausados após 7 dias sem atividade; os dados ficam guardados e dá pra restaurar pelo painel).
- Rotas HTTP do servidor (no main.py, função `rodar_webhook`):
  - `POST /<BOT_TOKEN>`: entrada do Telegram (o webhook é registrado com `set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)` toda vez que o bot inicia). Qualquer erro ao ler o update é impresso no log e a resposta é 200 mesmo assim.
  - `GET` e `HEAD` em `/` e em `/health`: health check, respondem 200 com o texto `ok`.
- cron-job.org, dois cron jobs:
  1. Pinga o Supabase 1 vez por dia (evita a pausa do projeto). Faz GET na API REST do Supabase numa tabela auxiliar `ping` (id int, com RLS e uma policy de SELECT pública), usando a chave publishable no header `apikey`. O bot NÃO usa a tabela `ping`.
  2. "Manter Render acordado - Bot Telegram": GET na URL raiz pública do serviço do Render, a cada 10 minutos, timeout de 30 segundos. Evita que o Web Service gratuito hiberne após 15 min sem tráfego. Como a raiz responde 200 (health check), o job conta como sucesso. Importante: o cron-job.org desativa o job sozinho depois de 25 falhas seguidas. Se o serviço estiver dormindo na hora do ping, a primeira resposta pode ser 503 (o Render está acordando).
- Todas as tabelas (`gastos`, `despesas`, `saldo_config`, `categoria_palavras`, `transacoes`, `usuarios`) estão com RLS ativado. `transacoes` e `usuarios` são antigas e o main.py não usa.
- Os dados são compartilhados entre todos os IDs de ALLOWED_USER_IDS (não existe coluna de usuário nas tabelas).
- Limite do Supabase: cada consulta devolve no máximo 1000 linhas. O código lê tudo com `todos_gastos()` (paginado com `.range`).
- Limite do Telegram: 4096 caracteres por mensagem. O código divide com `enviar_longo` (limite 3800).
- Estado das conversas: fica em `context.user_data` (memória do processo). Reiniciar/redeploy no Render apaga confirmações pendentes.

## 4. TABELAS SUPABASE

### gastos
Colunas: `id`, `descricao`, `valor`, `tipo`, `created_at`, `data`, `categoria`.
- `id`: chave (o código usa `.eq("id", ...)`, `.order("id")`, `.in_("id", [...])`).
- `descricao`: texto. `valor`: numérico.
- `tipo`: um destes textos: `dinheiro`, `cartao`, `sodexo`, `entrada`. Saídas são dinheiro/cartao/sodexo. Entradas (dinheiro recebido) também ficam nesta tabela, com `tipo = "entrada"` e sem categoria.
- `categoria`: texto ou NULL. Um dos nomes de CATEGORIAS. NULL aparece como "Sem categoria" nos resumos e gráficos.
- COLUNA DE DATA: a tabela pode ter `data` e/ou `created_at` (o dono listou as duas; o código funciona com qualquer uma ou com as duas). Quando o lançamento não informa data, o código não envia coluna de data e o banco usa o valor padrão (agora). O código descobre e trata assim:
  - `colunas_data()`: lê 1 linha de gastos (`select("*").limit(1)`). Devolve a lista das colunas de data existentes, na ordem de preferência `["data", "created_at"]` (só as que existem). Guarda em `_COLS_DATA`. Também define `_DATA_E_DATE = True` se o valor de `data` dessa linha tem 10 caracteres (AAAA-MM-DD, coluna do tipo date). Se a tabela estiver vazia ou der erro, devolve o palpite `["created_at"]` sem guardar.
  - `tentar_com_data(dados, dt, executar)`: usado em todo insert/update que precisa gravar data. Se `dt` é None, só executa. Se tem data, tenta nesta ordem: `colunas_data()`, `["data"]`, `["created_at"]`, `["data", "created_at"]`. Em cada tentativa chama `executar({**dados, **valores})`. Em caso de erro, imprime e tenta a próxima. Ao dar certo, guarda o conjunto em `_COLS_DATA`. Se todas falharem, relança o último erro. Valor gravado: coluna `data` recebe só "AAAA-MM-DD" se `_DATA_E_DATE` for True; caso contrário recebe o timestamp completo de `iso_data(dt)`. `created_at` sempre recebe `iso_data(dt)`.
  - Leitura de data: `mes_de(g)`, `quando_de(g)` e `data_curta(g)` e o CSV usam `g.get("data") or g.get("created_at")`. Valor com 10 caracteres é tratado como só data, sem conversão de fuso. Valor com hora é convertido de UTC para São Paulo.
  - Filtro por período (`gastos_entre`): usa `.gte(colunas_data()[0], ...)` e `.lt(colunas_data()[0], ...)` com 1 dia de folga em cada ponta, e depois confere o mês exato no Python com `mes_de`. Se a consulta falhar, o plano B busca a tabela inteira em UMA consulta (sem paginar, limite de 1000 linhas do Supabase). Limitação conhecida.

### despesas
Colunas: `id`, `descricao`, `valor`, `status`.
- `status`: `pendente` ou `pago`.
- Sem coluna de data e sem categoria. Despesas são contas do mês (aluguel, luz, cartão...) lançadas manualmente.

### saldo_config
Colunas: `id`, `valor`.
- Linha `id = 1`: saldo atual em dinheiro. `get_saldo()` lê (se não existir, cria com 0). `set_saldo(v)` faz upsert.
- Linha `id = 3`: último mês visto, guardado como inteiro AAAAMM (ex.: 202611). Usada por `checar_virada()`. `get_ultimo_mes_visto()` converte para "AAAA-MM".
- Qualquer outro `id` não é usado pelo main.py.

### categoria_palavras
Colunas: `palavra` (chave, texto), `categoria` (texto).
- Aprendizado: `palavra` é a descrição normalizada (minúscula, sem acento) de um gasto, `categoria` é o nome escolhido pelo usuário nos botões. Escrita com upsert por `aprender()`. Lida e guardada em cache global `_APRENDIDAS` por `aprendidas()` (se a leitura falhar, devolve `{}` e não guarda o cache).

## 5. TODAS AS FUNÇÕES

### 5.1 Handlers registrados em montar_app() (nesta ordem)
`montar_app(com_updater=True)` cria o Application (com `com_updater=False` usa `.updater(None)`, que é o modo webhook com servidor próprio) e registra:
1. `TypeHandler(Update, so_permitidos)` com `group=-1` (roda antes de todos; bloqueia IDs não permitidos, inclusive cliques em botões, lançando ApplicationHandlerStop).
2. Comandos: `/start`, `/despesa`, `/exportar`, `/zerar_mes`, `/resumo`, `/comparar`, `/buscar`, `/editar`, `/apagar_tudo`.
3. `CallbackQueryHandler(on_button)`.
4. `MessageHandler(filters.TEXT & ~filters.COMMAND, on_text)`.
5. `add_error_handler(erro_geral)`: imprime "Erro: ..." no log e responde "⚠️ Deu um erro aqui. Tenta de novo.".
- NÃO existem os comandos /saldo, /add, /relatorio (existiram em versões antigas). O saldo é lançado pelo botão "💰 Saldo".

`rodar_webhook(app)` (modo webhook): monta um app Starlette com as rotas da seção 3, cria `uvicorn.Server` (host 0.0.0.0, porta PORT, `log_level="warning"`) e roda `async with app:` -> `set_webhook` -> `app.start()` -> `servidor.serve()` -> `app.stop()`. O POST do Telegram vira `Update.de_json(...)` e é colocado em `app.update_queue`.

### 5.2 Menu e botões (callback_data)
`/start` limpa `context.user_data`. Se o mês virou, faz a pergunta de fechar o mês (ver 5.6). Senão mostra "Bot de orçamento / Bem-vindo!" com o menu (`menu()`):
- "💰 Saldo" = `saldo` | "💸 Dinheiro" = `gasto_dinheiro`
- "💳 Cartão" = `gasto_cartao` | "🍽️ SODEXO" = `gasto_sodexo`
- "📋 Gastos" = `listar_gastos` | "🧾 Despesas" = `listar_despesas`
- "✅ Pagar" = `pagar_despesa` | "🗑️ Apagar último" = `apagar_ultimo`
- "📈 Resumos e gráficos" = `menu_resumo` | "🔄 Zerar mês" = `zerar_mes`

Comportamento de `on_button(update, context)` (sempre faz `q.answer()` primeiro):
- `cat:{gid}:{idx}`: grava `categoria = CAT_LISTA[idx]` no gasto `gid`, chama `aprender(descricao, nome)` e edita a mensagem para "✅ descrição → emoji nome". Se o gasto não existe mais, edita para "Esse gasto não existe mais.". Erro: responde que não conseguiu salvar e pede para conferir a coluna `categoria`. Retorna.
- `menu_resumo`: envia "Resumo de MM/AAAA - quer como?" com `teclado_resumo(mês atual)`. Retorna.
- `resumo_simples:{fm}`, `resumo_detalhado:{fm}`, `resumo_categorias:{fm}`: chamam `resumo(...)` do mês `fm` (formato AAAA-MM). `resumo_comparar:{fm}` chama `comparativo(fim_mes=fm)`. `resumo_hoje:{fm}` e `resumo_semana:{fm}` chamam `resumo_periodo(update, "hoje"|"semana")` (o `fm` vem no callback mas é ignorado). Retornam.
- `saldo`: `esperando = "saldo"`, pede "Envie o saldo. Ex: 3500".
- `gasto_dinheiro` / `gasto_cartao` / `gasto_sodexo`: `esperando = <o próprio callback>`, pede uma linha por item (explica vírgula opcional, data "ontem"/"15/11" e `#categoria`).
- `listar_gastos`: gastos do mês atual (`gastos_do_mes`), uma linha por item: `ID. descricao - R$ valor - tipo - categoria` (a categoria só se existir; NÃO mostra data), mais dicas de editar/categoria/apagar. Usa `enviar_longo`.
- `listar_despesas`: todas as despesas (`ID. descricao - R$ valor - status`) mais dicas.
- `pagar_despesa`: lista as pendentes e define `esperando = "pagar"`. Se não há pendentes, responde "Nenhuma pendente.".
- `apagar_ultimo`: apaga o gasto de maior `id` (de qualquer mês, inclusive entrada) via `apagar_gasto_por_id` (que ajusta o saldo).
- `zerar_mes`: `esperando = "confirmar_zerar:AAAA-MM"` (mês atual) e pede SIM/NÃO. Retorna.
- IMPORTANTE: depois de `saldo`, `gasto_*`, `listar_*`, `pagar_despesa` e `apagar_ultimo`, o `on_button` cai no final e envia também `await resumo(update, context)` (resumo do mês atual). Só os ramos que dão `return` (cat:, menu_resumo, resumo_*, zerar_mes) não enviam esse resumo.

### 5.3 Texto: `on_text` -> `tratar_texto(update, context, o)`
`on_text` só chama `tratar_texto` com o texto sem espaços nas pontas. `tratar_texto` recebe o texto como parâmetro (não altera o objeto Message; ele também se chama recursivamente para reprocessar texto pendente). `tx = o.lower()`, `esp = context.user_data.get("esperando")`.

ORDEM EXATA das verificações (a ordem importa; um comando novo precisa entrar antes do que poderia capturá-lo e antes do "texto solto"):
1. `esp` começa com `confirmar_zerar` ou `confirmar_fechar`: resposta "sim" ou "s" confirma; "nao"/"não"/"n"/"cancelar" cancela; qualquer outro texto também cancela e depois é reprocessado como mensagem normal. Detalhes em 5.6.
2. `esp` começa com `confirmar_apagar_tudo`: só confirma se o texto, em maiúsculas, for exatamente `APAGAR TUDO`.
3. Virada de mês: `checar_virada` detecta mês novo (ver 5.6).
4. `esp == "saldo"`: lê um número com `pega_num` e SOMA ao saldo atual (não substitui). Responde "Saldo: R$ v" e envia o resumo. Se não achar número: "Envie só o número, ex: 3500".
5. `esp` começa com `gasto_`: fluxo dos botões Dinheiro/Cartão/SODEXO. O tipo vem do botão (`dinheiro`, `cartao`, `sodexo`). Os itens são separados por `linhas_de(o)` (quebra de linha ou `;`). Cada item usa `parse_linha_data(linha)` (sem `limpar_pagamento`). Salva com `salvar_gasto(d, v, tipo, dt, fc)`. Se `tipo == "dinheiro"`, desconta do saldo. Linhas inválidas entram em "⚠️ Não registrei:" com o motivo (`explica_falha`). Responde "Registrado: N item(ns) - R$ total" mais as linhas de recibo, depois envia o resumo e depois `perguntar_sem_categoria`. Limpa `user_data`.
6. `esp == "pagar"`: extrai todos os números do texto (`\d+`), sem repetir e mantendo a ordem. Para cada ID: se não existe vai para "Não encontrei"; se já está `pago` vai para "Já estavam pagas"; senão marca `status = "pago"`. Ao final desconta do saldo a soma das pagas. Responde "✅ Pagas: ... Total: R$ ..." e envia o resumo. Se nenhuma foi paga, avisa e mantém o estado `pagar` para tentar de novo.
7. `tx` começa com `editar`: `editar_item` (5.9).
8. `tx` começa com `categoria`: `categoria ID` mostra os botões de categoria para o gasto ID. Sem número: "Use: categoria 12 (veja o ID no botão Gastos)". ID inexistente: "Não achei esse gasto.".
9. `tx` começa com `comparar`: `comparar` ou `comparar 3` (número = quantidade de meses, padrão 6) -> `comparativo`.
10. `tx` começa com `buscar`: `buscar(update, context, resto)` (5.8).
11. `tx` começa com `apagar tudo` ou é `apagar_tudo`: define `esperando = "confirmar_apagar_tudo"` e pede para digitar exatamente `APAGAR TUDO`.
12. `tx` começa com `zerar`: `zerar` / `zerar setembro` / `zerar 09/2026`. Mês via `parse_mes` (padrão: mês atual). Define `esperando = "confirmar_zerar:AAAA-MM"`.
13. `tx` começa com `apagar entrada`: `apagar entrada 3000`. Procura a entrada MAIS RECENTE (maior id) com `tipo = "entrada"` e `valor` exatamente igual; apaga e faz saldo -= valor. Se não achar: "Não achei uma entrada de R$ x".
14. `tx` começa com `apagar`: com a palavra `despesa` na frase: `apagar despesa 3` apaga a despesa (se estava `pago`, devolve o valor ao saldo). Sem `despesa`: `apagar ultimo` (ou `apagar` sem número, ou com "ultimo"/"último") apaga o gasto de maior id; `apagar 12` apaga o gasto de ID 12 (`apagar_gasto_por_id`). Depois envia o resumo.
15. `tx` começa com `resumo`: se o texto tem `hoje` -> `resumo_periodo(update, "hoje")`; se tem `semana` -> `resumo_periodo(update, "semana")` (essas duas checagens vêm ANTES de `parse_mes`). Senão: `resumo`, `resumo setembro`, `resumo 10/2026`, `resumo 2026-10` mostram "Resumo de MM/AAAA - quer como?" com `teclado_resumo(fm)`.
16. `tx` começa com `despesa`: `processar_despesas(o)`. Responde "✅ N despesa(s) adicionada(s)!" ou a ajuda "Use: despesa aluguel, 1500".
17. `tx` começa com `entrada`, `recebi`, `salario` ou `salário`: lançamento de entrada (5.4).
18. `tx` começa com `saida`, `saída`, `gasto`, `gastei` ou `paguei`: `lancar_saidas(update, linhas_de(o))` (5.4).
19. Várias linhas sem prefixo: se `linhas_de(o)` tem mais de 1 item e pelo menos um deles tem valor (`parse_linha_data(limpar_pagamento(l))` não é None), chama `lancar_saidas` com todos os itens.
20. Texto solto (uma linha só): qualquer texto que tenha um número vira saída (5.4).
21. Se nada serviu: `explica_falha(o)`. Se o motivo não for "faltou o valor", responde "⚠️ Não registrei: motivo.". Senão responde o texto de ajuda que começa com "Tenta:" e lista exemplos (inclui `resumo hoje` e `resumo semana`).

### 5.4 Lançar saídas e entradas
Separador de lançamentos: `linhas_de(texto)` separa por quebra de linha OU por `;` e descarta itens vazios. A vírgula NÃO separa lançamentos (ela também é decimal: `35,50`). Mandar vários itens na mesma linha só separados por vírgula ou espaço é lido como UM lançamento (último número = valor).

Saída (`saida mercado 50`, `gasto ...`, `gastei ...`, `paguei ...`) e várias linhas sem prefixo (`mercado 50` / `almoço 35 cartão`): ambos passam por `lancar_saidas(update, linhas)`.
- Em cada item: `detectar_tipo(item)` define o tipo; `limpar_pagamento(item)` tira as palavras de pagamento; `parse_linha_data(ll, r"^\s*(saida|saída|gastos?|gastei|paguei)\b")` extrai descrição, valor, data e categoria forçada. O prefixo (`saida`, `gasto`...) é opcional em cada item.
- `salvar_gasto(d, v, tipo, dt, fc)` grava e devolve `(id, categoria)`. Dinheiro desconta do saldo; cartão e SODEXO não mexem no saldo.
- Resposta: "✅ N saída(s) lançada(s) - R$ total" mais uma linha por item (`linha_recibo`: `emoji descrição - R$ valor (tipo) → categoria 📅 DD/MM`, a data só aparece se foi informada), "⚠️ Não registrei:" para as inválidas, depois o resumo e depois os botões de categoria para quem ficou sem categoria (até 8). Se nenhum item for válido: só o "⚠️ Não registrei:" (ou "Ex: saida mercado 50").
- `lancar_saidas` chama `resumo(update, context=None)` (o `resumo` não usa o context).
- Pagamento misto (parte dinheiro, parte cartão) hoje se faz com dois itens: `mercado 30` e `mercado 20 cartão`.

Texto solto de uma linha só (ex.: `mercado 50`, `almoço 35 #viagem ontem`, `pix farmácia 40`): igual a uma saída de uma linha. Resposta "✅ Saída: ..." + resumo + `perguntar_categoria` se ficou sem categoria.

Entrada (`entrada salario 3000`, `recebi 3000`, `salario 3000`): vários itens aceitos (`linhas_de`); usa `limpar_pagamento` e `parse_linha_data(ll, r"^\s*(entrada|recebi)\b")`. Grava em `gastos` com `tipo = "entrada"` via `tentar_com_data` (sem categoria; a #categoria é lida e ignorada). Só soma ao saldo depois de gravar com sucesso. Resposta: "✅ N entrada(s) lançada(s) - R$ total" e o resumo.

Despesa (`despesa aluguel, 1500` ou `/despesa aluguel, 1500` e linhas seguintes `luz, 200`; várias separadas por quebra de linha ou `;`): `processar_despesas` remove o prefixo `/despesa`, tira qualquer data digitada (despesa não tem data) e usa `parse_linha` (2 valores, sem tratamento de #categoria). Descrição "Item" vira "Despesa". Insere `status = "pendente"`. Não mexe no saldo.

### 5.5 Pagar despesas
Botão "✅ Pagar" -> manda IDs (um ou vários: `1 2 5`). Cada despesa pendente vira `pago` e o total é descontado do saldo (uma vez, no fim). Despesa já paga não é cobrada de novo.

### 5.6 Virada de mês, fechar mês, zerar mês, apagar tudo
- `checar_virada(update)`: compara `saldo_config id=3` com o mês atual. Se não existe registro: grava o mês atual e devolve False. Se é igual: False. Se diferente: grava o mês atual e devolve o mês anterior registrado (ex.: "2026-10"). É chamada em `/start` e em toda mensagem de texto (cliques em botões NÃO chamam).
- Quando a virada é detectada num texto: guarda `user_data["pendente"] = texto`, `user_data["esperando_depois"] = fluxo que estava em andamento` e `user_data["esperando"] = "confirmar_fechar:AAAA-MM"`; pergunta "Quer fechar MM/AAAA e começar do zero?" (SIM ou NÃO). No `/start` a pergunta é parecida, sem `pendente`.
- Resposta SIM em `confirmar_fechar`: manda backup CSV, chama `fechar_mes()` (apaga TODAS as despesas e zera o saldo; os GASTOS FICAM guardados no histórico) e avisa. Resposta NÃO: mantém tudo. Em seguida restaura `esperando_depois` (se houver) e reprocessa o `pendente` (se houver) com `tratar_texto`. Se a resposta não foi nem SIM nem NÃO, ela também é reprocessada como mensagem normal.
- `zerar_mes(filtro_mes)` (botão, `zerar [mês]` ou `/zerar_mes [mês]`, depois de SIM): manda backup e apaga os gastos DAQUELE mês (`gastos_do_mes`). Só se o mês for o ATUAL também apaga TODAS as despesas e zera o saldo. Para mês passado apaga só os gastos (despesas e saldo não mudam).
- `apagar_tudo()` (só com `APAGAR TUDO`): manda backup; apaga todos os gastos (`todos_gastos`) e todas as despesas e zera o saldo. NÃO apaga `categoria_palavras` nem `saldo_config id=3`.
- `apagar_ids(tabela, ids)` apaga em lotes de 100 com `.in_("id", ...)`.
- Backup: `enviar_backup(update, legenda)` manda `backup.csv` por `reply_document`. É enviado antes de fechar mês, zerar e apagar tudo.

### 5.7 Resumos e gráficos
`resumo(update, context, filtro_mes=None, detalhado=False, categorias=False)`. Mês padrão = atual (`AAAA-MM`). Envia por `enviar_longo(..., parse_mode="Markdown")`.
- Resumido: título "📊 *Resumo* de MM/AAAA"; "💰 Saldo atual" (só no mês atual); Dinheiro, Cartão, SODEXO, Total gasto (soma dinheiro+cartão+sodexo); "Entradas" se houver; "Pagas" (soma das despesas com status pago; só no mês atual); "Nenhum gasto nesse mês." se não há registros.
- Detalhado: título "📊 *Resumo Detalhado*"; lista "🧾 *Detalhes:*" com cada gasto não-entrada em ordem de data crescente (desempate por id), formato `N. DD/MM - Descrição - R$ valor`. Só dia e mês, sem horário. A descrição usa `.strip().title()` e `escape_md`.
- Categorias + gráfico (`categorias=True`): acrescenta "🗂️ *Por categoria:*" com `emoji nome - R$ valor (xx%)` em ordem decrescente e envia uma imagem PNG de pizza/rosca (`grafico_pizza`, título "Gastos por categoria - MM/AAAA", total no centro, legenda com valor e %). Se o gráfico falhar: "Não consegui gerar o gráfico agora.".
- `resumo_periodo(update, periodo)` (`periodo` = `"hoje"` ou `"semana"`): resumo curto de um período recente. Usa `_msg(update)` (funciona por botão, texto e comando).
  - `hoje`: só o dia de hoje (`hoje_sp()`). `semana`: os ÚLTIMOS 7 DIAS, contando hoje (hoje e os 6 dias anteriores), NÃO a semana de segunda a domingo.
  - Busca com `gastos_entre(mês inicial, mês final)` e filtra no Python por `quando_de(x).date()` dentro do intervalo. Lançamentos com data retroativa entram no dia informado.
  - Texto: título ("📅 *Resumo de hoje* (DD/MM)" ou "🗓️ *Resumo da semana* (DD/MM a DD/MM)"), Dinheiro, Cartão, SODEXO, Total gasto, "Entradas" se houver. Depois "🧾 *Gastos:*" com os gastos (sem entradas) em ordem de data: em `hoje` `emoji Descrição - R$ valor`; em `semana` com `DD/MM - ` na frente. Só em `semana` acrescenta "🗂️ *Por categoria:*" com valor e %. Descrições passam por `escape_md`; envia por `enviar_longo(..., parse_mode="Markdown")`.
  - Sem lançamentos no período: "Nenhum lançamento nesse período." (sem Markdown). Não mostra saldo nem "Pagas".
- `teclado_resumo(fm)`: 6 botões em 3 linhas: "📋 Resumido" `resumo_simples:fm` e "🧾 Detalhado" `resumo_detalhado:fm`; "🗂️ Categorias + gráfico" `resumo_categorias:fm` e "📈 Comparar meses" `resumo_comparar:fm`; "📅 Hoje" `resumo_hoje:fm` e "🗓️ Semana" `resumo_semana:fm`.
- `comparativo(update, context, fim_mes=None, n=6)`: `n` limitado entre 2 e 12. Pega os últimos `n` meses terminando em `fim_mes` (padrão: mês atual). Para cada mês soma os gastos (sem entradas) e mostra "MM/AAAA: R$ x" com variação % em relação ao mês anterior (só quando o anterior é maior que 0). Se o fim é o mês atual, acrescenta "_(o mês atual vai só até hoje)_". Mostra as 3 maiores mudanças por categoria entre os dois últimos meses (⬆️/⬇️). Envia gráfico de barras (`grafico_barras`, último mês em amarelo). Sem gastos: "Ainda não há gastos nesse período para comparar.".
- Os gráficos NÃO usam emoji nos textos (a fonte do matplotlib não renderiza emoji).

### 5.8 Buscar
`buscar termo [período]`, `/buscar termo [período]`. `extrai_escopo(texto)` separa o período do termo (primeiro que combinar, nesta ordem): `tudo|todos|todas|geral|sempre` = todos os meses; `mês passado|mês anterior`; `AAAA-MM`; `MM/AAAA`; nome do mês em português (opcionalmente `de 20xx`; sem ano: se o número do mês for maior que o mês atual usa o ano anterior, senão o ano atual); sem período = mês atual.
- Se o termo ficar vazio, mostra a ajuda de uso.
- Busca: `normalizar` (minúsculas, sem acento) em `descricao + categoria + tipo`. TODAS as palavras do termo precisam aparecer (aceita plural com "s" em palavras com mais de 3 letras).
- Fonte: `todos_gastos()` (paginado) para "tudo"; senão `gastos_do_mes(mes)`.
- Resultado: "🔎 "termo" em MM/AAAA (ou todos os meses)", quantidade, "Gastos: R$ x" (sem entradas) e "Entradas: R$ y" se houver. Em "tudo", mostra "Por mês:" (até 12 meses mais recentes, com total e quantidade) quando há mais de um mês. Lista até 50 itens, do mais recente ao mais antigo: `ID. data - descricao - R$ valor - tipo - emoji categoria`. A data tem ano (DD/MM/AA) só em "tudo". Mais de 50: "... e mais N.". Nada achado: mensagem com dica de usar `tudo`.

### 5.9 Editar
`editar ID ...`, `/editar ID ...`, `editar despesa ID ...` (`editar_item`). Ordem da leitura do texto depois do ID:
1. Data (`extrai_data`): `ontem`, `anteontem`, `hoje`, `DD/MM`, `DD/MM/AAAA`. Data inválida: "Data inválida. ...". Em despesa: "Despesas não têm data. ...".
2. `#categoria` (`extrai_categoria`). Categoria desconhecida: "Categoria desconhecida. ...". Em despesa: "Despesas não têm categoria.".
3. Valor: se o texto restante começa com número, esse é o valor e o resto é a nova descrição; senão, se termina com número, esse é o valor e o início é a descrição; senão tudo é a nova descrição. A descrição nova usa `.title()`.
- Precisa ter pelo menos um de: valor, descrição, data ou categoria. Exemplos: `editar 12 45,90`, `editar 12 45,90 Mercado`, `editar 12 Mercado`, `editar 12 ontem`, `editar 12 15/11`, `editar 12 #viagem`, `editar 12 ontem 45,90`, `editar despesa 3 187,40`.
- Grava com `tentar_com_data(upd, dt, executar)`. A categoria só muda se vier `#tag` (e NÃO é aprendida).
- Ajuste do saldo na edição: despesa paga: saldo += valor_antigo - valor_novo. Gasto em dinheiro: saldo += valor_antigo - valor_novo. Entrada: saldo += valor_novo - valor_antigo. Gasto no cartão/SODEXO e despesa pendente: não mexe no saldo. A resposta mostra "Saldo ajustado em R$ ±x" quando muda.
- Resposta: "✏️ Gasto|Despesa ID atualizado: descrição - R$ valor 📅 DD/MM categoria" e depois o resumo.

### 5.10 Exportar / backup
`/exportar` -> `gerar_csv_bytes()` e `reply_document` com `backup.csv` (codificação utf-8-sig) e legenda "Saldo: R$ x". Colunas: `tipo`, `descricao`, `valor`, `data/status`, `categoria`. Linhas `gasto` (data crua de `data` ou `created_at`, categoria) e linhas `despesa` (status, categoria vazia). Usa `todos_gastos()`.

### 5.11 Segurança
`so_permitidos` (TypeHandler, group -1): se `update.effective_user.id` não está em `ALLOWED_IDS`, lança `ApplicationHandlerStop` (o bot não responde nada). A rota de health check (`/` e `/health`) é pública e só devolve "ok" (não expõe dados).

### 5.12 Estados em context.user_data
Chaves: `esperando`, `pendente`, `esperando_depois`.
- `esperando` pode ser: `saldo`, `gasto_dinheiro`, `gasto_cartao`, `gasto_sodexo`, `pagar`, `confirmar_zerar:AAAA-MM`, `confirmar_fechar:AAAA-MM`, `confirmar_apagar_tudo`.
- `pendente` e `esperando_depois` só existem durante a confirmação da virada do mês.
- Os fluxos terminam com `context.user_data.clear()`.
- Se o bot parece "travado" tratando mensagens como outra coisa, `/start` limpa o estado.

### 5.13 Índice de TODAS as funções do main.py (ordem do arquivo)
- `so_permitidos`: bloqueia IDs não permitidos.
- `escape_md`: escapa `_ * ` [` para o Markdown simples do Telegram.
- `hoje_sp`: data de hoje em São Paulo.
- `mes_atual_str`, `mes_anterior_str`: "AAAA-MM" do mês atual / anterior.
- `mes_de`: "AAAA-MM" de um gasto (usa `data` ou `created_at`).
- `quando_de`: datetime em São Paulo de um gasto (ou None).
- `data_curta(g, ano=False)`: "DD/MM" (ou "DD/MM/AA" com `ano=True`), sem horário.
- `parse_mes`: texto -> "AAAA-MM" (aceita AAAA-MM, MM/AAAA, nome do mês + ano opcional, ou número solto = mês do ano atual).
- `get_saldo`, `set_saldo`: saldo (saldo_config id 1).
- `get_ultimo_mes_visto`, `set_ultimo_mes_visto`: último mês visto (saldo_config id 3, AAAAMM).
- `checar_virada`: detecta o mês novo.
- `parse_valor`: converte número no formato brasileiro.
- `pega_num`: pega o valor (último número do texto).
- `pega_desc`: monta a descrição.
- `parse_linha`: devolve `(descricao, valor)` ou None.
- `limpar_pagamento`: remove palavras de forma de pagamento.
- `detectar_tipo`: dinheiro / cartao / sodexo.
- `extrai_data`: lê ontem/anteontem/hoje/DD/MM/DD/MM/AAAA.
- `colunas_data`, `tentar_com_data`, `iso_data`: gravação e leitura de data (seção 4).
- `extrai_categoria`: lê `#categoria`.
- `explica_falha`: motivo de uma linha não ter sido registrada.
- `parse_linha_data`: devolve `(descricao, valor, data, categoria_forcada)` ou None.
- `processar_despesas`: lança despesas (várias linhas).
- `gastos_entre`, `gastos_do_mes`: gastos por período (filtro no Supabase + conferência no Python).
- `lista_meses(fim, n)`: lista dos últimos n meses em ordem crescente.
- `normalizar`: minúsculas e sem acento.
- `aprendidas`, `aprender`: categorias aprendidas (tabela categoria_palavras, cache `_APRENDIDAS`).
- `detectar_categoria`: categoria automática.
- `salvar_gasto(desc, valor, tipo, data=None, forcada=None)`: grava um gasto e devolve `(id, categoria)`.
- `linha_recibo`: texto de confirmação de um gasto.
- `teclado_categorias(gid)`: botões das categorias (2 por linha, `cat:{gid}:{idx}`).
- `perguntar_categoria(msg, gid, desc)`: "Qual a categoria de X?" com botões.
- `perguntar_sem_categoria(msg, lista, maximo=8)`: pergunta até 8 de uma vez; se passar, avisa para usar `categoria ID`.
- `totais_por_categoria`, `ordenar_categorias`: somas por categoria (sem entradas; NULL = "Sem categoria") e ordenação decrescente.
- `_msg(update)`: mensagem onde responder (de botão ou de texto).
- `enviar_longo(msg, texto, limite=3800, parse_mode=None)`: divide mensagens longas por linhas.
- `teclado_resumo`: 6 botões de resumo (4 antigos + Hoje e Semana).
- `_plt`: importa matplotlib com backend Agg.
- `grafico_pizza`, `grafico_barras`: geram PNG em memória (devolvem None se falhar).
- `comparativo`, `comparar_cmd`: comparação de meses (comando `/comparar [n]`).
- `todos_gastos`: lê toda a tabela gastos paginando de 1000 em 1000.
- `_sem_trecho`, `extrai_escopo`: apoio do buscar (período).
- `buscar`, `buscar_cmd`: busca de gastos (comando `/buscar`).
- `gerar_csv_bytes`, `enviar_backup`: backup CSV.
- `resumo`: resumos do mês (resumido/detalhado/categorias).
- `resumo_periodo(update, periodo)`: resumo de hoje ou dos últimos 7 dias.
- `menu`: teclado do menu principal.
- `aviso_zerar(fm)`, `aviso_fechar(ant)`: textos de aviso (zerar mês atual x mês passado; fechar mês).
- `start`: comando /start.
- `apagar_ids(tabela, ids)`: apaga em lotes de 100.
- `apagar_gasto_por_id`: apaga um gasto e ajusta o saldo.
- `fechar_mes`: apaga despesas e zera o saldo (gastos ficam).
- `zerar_mes`: apaga gastos do mês (e despesas + saldo se o mês for o atual).
- `apagar_tudo`: apaga todos os gastos e despesas e zera o saldo.
- `on_button`: tratador de botões.
- `linhas_de(texto)`: separa lançamentos por quebra de linha ou `;`.
- `lancar_saidas(update, linhas)`: lança várias saídas e responde (recibo, falhas, resumo, perguntas de categoria).
- `on_text`, `tratar_texto`: tratadores de texto.
- `editar_item`, `editar_cmd`: editar gasto/despesa.
- `despesa_cmd`: comando `/despesa`.
- `exportar_cmd`: comando `/exportar`.
- `zerar_mes_cmd`: comando `/zerar_mes [mês]` (pede confirmação).
- `resumo_cmd`: comando `/resumo [mês | hoje | semana]` (hoje/semana respondem direto; senão mostra o teclado de resumos).
- `apagar_tudo_cmd`: comando `/apagar_tudo` (pede `APAGAR TUDO`).
- `erro_geral`: tratador global de erros.
- `montar_app(com_updater=True)`: cria o Application e registra os handlers.
- `rodar_webhook(app)`: servidor Starlette/uvicorn com o webhook do Telegram e o health check.
- `main`: avisa se ALLOWED_IDS está vazio e inicia (webhook ou polling).

### 5.14 Constantes e variáveis globais
`TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `PORT`, `BASE_URL`, `WEBHOOK_URL` (= BASE_URL + "/" + TOKEN), `supabase` (cliente), `TZ`, `MESES` (nome do mês em português -> "01".."12", com "marco" e "março"), `PAG_RE`, `NUM_RE`, `DATA_RE`, `PAL_DATA_RE`, `TAG_RE`, `CATEGORIAS`, `CAT_LISTA`, `CORES`, `PALAVRAS_CATEGORIA`, `_IDX`, `_APRENDIDAS`, `ALLOWED_IDS`, `_COLS_DATA`, `_DATA_E_DATE`.

### 5.15 Cuidados para não quebrar o código
- Para gravar data de gasto, SEMPRE use `tentar_com_data`. Nunca escreva `created_at` ou `data` direto.
- Para ler a data de um gasto, use `mes_de`, `quando_de` ou `data_curta` (aceitam `data` e `created_at`).
- `parse_linha_data` devolve 4 valores `(descricao, valor, data, categoria_forcada)` ou None; `parse_linha` devolve 2 `(descricao, valor)` ou None. `processar_despesas` usa `parse_linha`; os lançamentos de gastos/entradas usam `parse_linha_data`.
- A ordem dos `if` em `tratar_texto` importa (seção 5.3). O "texto solto" vira saída para qualquer texto com número, então novos comandos de texto entram ANTES do bloco "várias linhas sem prefixo" e do "texto solto", e antes de qualquer `startswith` que os capture.
- Para separar lançamentos de uma mensagem, use `linhas_de` (não `split("\n")`). Para lançar várias saídas, reuse `lancar_saidas`.
- NÃO volte a usar `app.run_webhook`: o servidor próprio (`rodar_webhook`) é o que atende o health check. Novas rotas HTTP entram na lista de rotas do Starlette dentro de `rodar_webhook`. Handlers novos entram em `montar_app`. A rota do Telegram continua em `POST /<TOKEN>`.
- Se o health check parar de responder 200, o cron-job.org marca falha e desativa o job depois de 25 falhas seguidas.
- `callback_data` do Telegram aceita no máximo 64 bytes. O callback `cat:{gid}:{idx}` usa o índice da posição em `CAT_LISTA`: mudar a ordem das categorias muda o significado (manter "Outros" por último).
- `resumo`, `resumo_periodo` e `comparativo` enviam com `parse_mode="Markdown"` (Markdown simples): textos do usuário passam por `escape_md`. Mensagens sem `parse_mode` não devem usar `escape_md` (a barra apareceria).
- Mensagens longas: use `enviar_longo`.
- Para ler a tabela `gastos` inteira, use `todos_gastos()` (paginado).
- Erros de banco quase sempre são capturados com try/except e `print`. `erro_geral` cobre o resto com uma mensagem genérica.
- O cache `_APRENDIDAS` e o estado `_COLS_DATA`/`_DATA_E_DATE` só são recarregados quando o processo reinicia.
- O saldo é um número único (saldo_config id 1) e só reflete os lançamentos em dinheiro e as entradas (regras na seção 8).

## 6. CATEGORIAS

As 12 categorias atuais (ordem de `CATEGORIAS`/`CAT_LISTA`, emoji entre parênteses): Mercado (🛒), Alimentação (🍽️), Combustível (⛽), Manutenção (🔧), Transporte (🚌), Saúde (💊), Lazer (🎉), Compras (👕), Casa (🏠), Educação (📚), Viagem (✈️), Outros (📦). Gastos sem categoria aparecem como "Sem categoria" (emoji ❔ no texto; cor cinza nos gráficos). Cores dos gráficos em `CORES`.

Palavras que classificam sozinhas (`PALAVRAS_CATEGORIA`, sem acento e em minúsculas):
- Mercado: mercado, supermercado, feira, acougue, hortifruti, atacadao, sacolao
- Alimentação: almoco, jantar, comida, cafe, lanche, padaria, restaurante, pizza, ifood, marmita, sorvete, acai, pastel, pasteis, hamburguer, salgado, refeicao, pao, paes
- Combustível: combustivel, gasolina, gnv, etanol, alcool, diesel, posto, abastecimento
- Manutenção: manutencao, oficina, mecanico, oleo, pneu, revisao, peca, alinhamento, balanceamento, bateria, freio, conserto
- Transporte: uber, 99, onibus, passagem, pedagio, estacionamento, metro, taxi, bilhete
- Saúde: farmacia, remedio, consulta, exame, dentista, medico, hospital
- Lazer: cinema, bar, passeio, show, festa, jogo, netflix, spotify, ingresso, balada
- Compras: roupa, sapato, tenis, shopping, camisa, calca, bermuda, bolsa, loja
- Casa: gas, botijao, reforma, limpeza, movel, moveis, lampada, ferramenta, tinta
- Educação: curso, escola, faculdade, livro, matricula, apostila
- Viagem: viagem, hotel, hospedagem, pousada, airbnb, hostel, excursao, pacote
- Outros: sem palavras (só por escolha manual).

Detecção automática (`detectar_categoria(desc)`):
1. `normalizar(desc)` (minúsculas, sem acento).
2. Se a descrição inteira normalizada existe em `categoria_palavras` (aprendizado) e a categoria ainda existe em CATEGORIAS, usa ela.
3. Senão, quebra em palavras (`\w+`). Se alguma palavra existe em `categoria_palavras`, usa a primeira que achar.
4. Senão, procura cada palavra, na ordem em que aparece no texto, em `_IDX` (índice das palavras fixas; aceita também o plural com "s" ou "es"; se duas categorias tiverem a mesma palavra, vale a primeira definida).
5. Se nada servir, devolve None (fica sem categoria e o bot pergunta).

Aprendizado: quando o usuário escolhe uma categoria nos botões (`cat:`), `aprender(descricao, nome)` grava em `categoria_palavras` a chave `normalizar(descricao)` (descrição inteira). Descrições de uma palavra só (ex.: "farmácia") passam a valer também dentro de frases, pelo passo 3. `#categoria` e `editar #categoria` NÃO ensinam nada.

Quando não reconhece: o gasto é salvo sem categoria e o bot envia "Qual a categoria de X?" com os botões (um por categoria, 2 por linha). Em lançamento com várias linhas, pergunta até 8 itens (`perguntar_sem_categoria`), e avisa para usar `categoria ID` nos demais. Se a coluna `categoria` não existir no Supabase, `salvar_gasto` salva sem categoria (tenta de novo sem o campo).

Escolher a categoria na hora com `#`: `almoço 35 #viagem`. `extrai_categoria` usa a primeira `#tag`, normaliza, aceita o nome inteiro (ex.: `#alimentacao`) ou uma abreviação com pelo menos 3 letras que combine com UMA só categoria (ex.: `#alim`). Tag que não existe: a linha NÃO é salva e o bot avisa "categoria desconhecida, use por exemplo #mercado ou #viagem".

Mudar depois: `categoria ID` (botões) ou `editar ID #categoria`.

Para criar uma categoria nova: acrescentar em `CATEGORIAS` (emoji), `CORES` e `PALAVRAS_CATEGORIA`, mantendo "Outros" por último.

## 7. REGRAS DE PARSING

- `PAG_RE = r"\b(cartao|cartão|credito|crédito|sodexo|vale|pix|dinheiro|debito|débito)\b"`: palavras de forma de pagamento. `limpar_pagamento` apaga essas palavras da linha (sem diferenciar maiúsculas) antes de ler a descrição. `detectar_tipo` olha o texto original: `cartao|cartão|credito|crédito` = `cartao`; `sodexo|vale` = `sodexo`; qualquer outra coisa (inclusive pix, dinheiro, débito) = `dinheiro`. No fluxo dos botões (Dinheiro/Cartão/SODEXO) o tipo vem do botão e `limpar_pagamento` NÃO é aplicado.
- `NUM_RE = r"(?:R\$\s*)?(\d[\d.,]*)"`: número com `R$` opcional; o grupo 1 é só o número.
- `parse_valor(s)`: tira "R$"; se tem vírgula, os pontos são milhar e a vírgula é decimal (`1.500,50` = 1500.50, `35,5` = 35.5); se não tem vírgula e bate com `[1-9]\d{0,2}(\.\d{3})+`, o ponto é milhar (`1.500` = 1500); caso contrário é decimal normal (`1.5` = 1.5, `0.500` = 0.5).
- `pega_num(s)`: acha todos os números com NUM_RE e usa o ÚLTIMO (tira "." e "," do fim). Sem número = None. Cuidado: números na descrição contam, e o último vence.
- `pega_desc(s, rem="")`: se `rem` (regex) foi passado, remove da linha (sem diferenciar maiúsculas); remove o ÚLTIMO número encontrado (com o `R$`); junta espaços; corta espaços, vírgulas e hífens das pontas; aplica `.title()`; vazio vira "Item". Os `rem` usados: saída `r"^\s*(saida|saída|gastos?|gastei|paguei)\b"`, entrada `r"^\s*(entrada|recebi)\b"`.
- `parse_linha(linha, rem="")`: `(pega_desc, pega_num)` ou None se não há número.
- `linhas_de(texto)`: `re.split(r"[\n;]", texto)`, tira espaços e descarta itens vazios. É o separador de lançamentos de saída, entrada e dos botões de gasto. (`processar_despesas` tem o seu próprio split com o mesmo critério.)
- `extrai_data(txt)` devolve `(texto sem a data, data)`:
  - `anteontem` = hoje menos 2 dias; `ontem` = hoje menos 1 dia; `hoje` = apaga a palavra e devolve data None (usa o horário real). Palavras são procuradas primeiro.
  - Senão procura `DD/MM`, `DD/MM/AA` ou `DD/MM/AAAA` (`DATA_RE`, que não pega números colados em outros dígitos, barras, pontos ou vírgulas). Ano de 2 dígitos soma 2000. Sem ano: usa o ano atual e, se a data ficar no futuro, usa o ano anterior. Com ano explícito no futuro: aceita.
  - Sem data: `(texto, None)`. Data impossível (ex.: 31/11): `(texto sem a data, False)`; a linha é rejeitada e `explica_falha` responde "data inválida".
  - Só a primeira data/palavra é lida.
- `iso_data(d)`: meio-dia (12:00) de São Paulo, convertido para UTC no formato `AAAA-MM-DDTHH:MM:SSZ` (meio-dia evita o dia "escorregar" por causa do fuso).
- `extrai_categoria(txt)` devolve `(texto sem a tag, categoria)`: `TAG_RE = (?<!\w)#(\w+)`; sem tag = None; tag que não existe = False; tag normalizada que bate com o nome de uma categoria (sem acento/maiúscula) ou abreviação com 3+ letras que combine com uma só categoria.
- `parse_linha_data(linha, rem="")`: ordem fixa: 1) `extrai_data`; se False, devolve None. 2) `extrai_categoria`; se False, devolve None. 3) `parse_linha(texto_restante, rem)`; sem número, None. Devolve `(descricao, valor, data|None, categoria_forcada|None)`.
- `explica_falha(linha)`: devolve "data inválida" (data False), ou "categoria desconhecida, use por exemplo #mercado ou #viagem" (categoria False), ou "faltou o valor".
- `extrai_escopo` (buscar) e `parse_mes` (resumo/zerar): ver seções 5.7 e 5.8. `parse_mes`: procura `AAAA-M`, depois `M/AAAA`, depois nome do mês em português (ano = `20xx` do texto ou o ano atual), por último qualquer número de 1-2 dígitos (= esse mês do ano atual). Sem nada, devolve None (os chamadores usam o mês atual). `resumo hoje` e `resumo semana` são tratados antes de chamar `parse_mes`.
- Ordem de leitura de uma linha de saída: `detectar_tipo` -> `limpar_pagamento` -> `extrai_data` -> `extrai_categoria` -> `pega_num`/`pega_desc`.
- Exemplos: `almoço 35 #viagem ontem`, `mercado 1.500,50 15/11`, `pizza 2x 80` (valor 80, descrição "Pizza 2X"), `saida mercado 50 cartao anteontem`, `mercado 50; almoço 35 cartão` (dois gastos), duas linhas `mercado 50` e `almoço 35` na mesma mensagem (dois gastos).

## 8. REGRAS DE SALDO

O saldo é um único número (saldo_config id 1), só do dinheiro em mãos:
- Botão "💰 Saldo": o valor digitado é SOMADO ao saldo atual (não substitui).
- Saída em dinheiro: saldo -= valor. Saída no cartão ou SODEXO: não mexe no saldo.
- Entrada: saldo += valor (só depois de gravar com sucesso).
- Despesa nova (pendente): não mexe no saldo.
- Pagar despesa: saldo -= valor de cada despesa paga agora (descontado uma vez com a soma). Despesa já paga não desconta de novo.
- Editar: despesa paga e gasto em dinheiro: saldo += valor_antigo - valor_novo. Entrada: saldo += valor_novo - valor_antigo. Cartão/SODEXO e despesa pendente: sem mudança.
- Apagar gasto (por ID ou último): dinheiro devolve o valor (saldo += valor); entrada tira o valor (saldo -= valor); cartão/SODEXO não mexe.
- Apagar despesa: se estava `pago`, devolve o valor (saldo += valor); se pendente, não mexe.
- `apagar entrada VALOR`: saldo -= VALOR.
- Fechar mês, zerar mês atual e apagar tudo: saldo = 0. Zerar um mês passado: não mexe no saldo.
- Data retroativa (`ontem`, `15/11`): o saldo é ajustado na hora do lançamento, qualquer que seja a data informada.
- "Pagas" no resumo do mês (mês atual): soma das despesas com status `pago`.
- O resumo do mês mostra "Saldo atual" só para o mês atual. Meses passados mostram só os totais de gastos e entradas. `resumo hoje` e `resumo semana` não mostram saldo.

## 9. REGRAS DE SAÍDA (como a IA deve responder)

- Quando eu pedir uma mudança, devolver SEMPRE o main.py COMPLETO, não só o trecho alterado, e me falar o que mudou.
- Se a mudança exigir biblioteca nova, avisar para acrescentar no requirements.txt.
- Não inventar tabelas, colunas ou funções que não estão neste documento sem avisar antes.
- Decisões do dono que não devem ser desfeitas sem eu pedir (informado pelo dono, fora do main.py): despesas lançadas manualmente todo mês (sem despesas recorrentes automáticas); limite mensal com alerta e campo "quem lançou" ficaram de fora por enquanto; `/apagar_tudo` só com a frase `APAGAR TUDO`; histórico dos gastos é mantido na virada do mês (fechar mês não apaga gastos); resumo detalhado mostra só DD/MM (sem horário) e a lista do botão "📋 Gastos" não mostra data; "semana" no `resumo semana` = últimos 7 dias (não segunda a domingo); pensa em um app Android no futuro, usando o mesmo Supabase.
- Ideias sugeridas e AINDA NÃO implementadas (só fazer se eu pedir): backup automático agendado enviado no Telegram; pagamento misto numa linha só (`mercado dinheiro 30 cartão 20`); botão "Desfazer" depois de cada lançamento; alertas de saldo baixo ou limite por categoria; guardar o estado das conversas (`user_data`) no Supabase para sobreviver a reinício do Render.

O main.py completo está no GitHub.
