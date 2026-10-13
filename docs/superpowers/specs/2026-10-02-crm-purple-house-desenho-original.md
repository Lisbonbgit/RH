# Purple House CRM — Documento de desenho (v1)

> **Nota (2026-10-09):** este é o desenho original do CRM como app autónoma (PHP + MariaDB na Hostinger), aprovado pelo Bruce a 2026-10-02 e construído no repositório `purple-house-crm` (ramo `etapa-1`, etiqueta `referencia-standalone`). As **regras de negócio** (§4, §6, §7, §8, §9) continuam válidas. A **arquitetura** (§10–§13, §16–§17) foi substituída por [2026-10-09-crm-purple-house-no-portal-design.md](2026-10-09-crm-purple-house-no-portal-design.md): o CRM passa a ser um módulo do portal Gestão Lisbonb.


- **Data:** 2026-10-02
- **Autor:** Bruce Silva (com Claude Code)
- **Estado:** aprovado em conversa; revisto por 4 revisores independentes; por rever por escrito pelo Bruce

---

## 1. Objetivo

Um CRM para a fábrica de sorbet de açaí **Purple House** cujo ecrã principal é um **mapa**. Cada loja (revendedor atual ou potencial) aparece como um pino colorido pela sua fase comercial, com o nome sempre visível. O CRM serve também para **planear o dia da carrinha**: juntar as entregas marcadas com visitas a lojas próximas ou no caminho (amostras, acompanhamento, angariação) e calcular a melhor ordem, respeitando os horários de cada loja.

**Sucesso na v1 =**
1. Todas as lojas registadas no mapa, com fase, contacto e histórico completo (incluindo tentativas falhadas).
2. O escritório planeia a rota de um dia em menos de 10 minutos.
3. O motorista faz a rota no telemóvel e regista cada paragem com um toque; fases, encomendas e histórico atualizam-se sozinhos, mesmo com falhas de rede.

## 2. Contexto e restrições

| Tema | Decisão |
|---|---|
| Utilizadores | Escritório (planeia no computador) + rua (segue a rota no telemóvel). Poucos utilizadores. |
| Operação | 1 carrinha, várias regiões de Portugal, 1 rota por dia. Entregas em parte fixas (rotina), em parte por encomenda. |
| Dados iniciais | Não existem — começa do zero. Registar uma loja tem de ser muito rápido. |
| Alojamento | Hostinger (plano Business/"Ilimitado", já pago), mesmo plano da assistente Cleide, num site separado. |
| Código | Repositório privado no GitHub; o Bruce e o sócio fazem alterações através do Claude Code (não são programadores). |
| Língua | Interface e documentação em português de Portugal. |

## 3. Âmbito

**Dentro da v1:** lojas e funil; histórico de interações; encomendas simples (produto, quantidade, data) com repetição; produtos; regiões; mapa; planeamento de rotas com janelas horárias e sugestões; rota do dia no telemóvel (app instalável, tolerante a falhas de rede); utilizadores com dois perfis; cópias de segurança; site de teste + publicação controlada a partir do GitHub.

**Fora da v1 (pode vir depois):** faturação, preços e tabelas por cliente, stock, relatórios/estatísticas, ligação à Cleide, encomendas fixas totalmente automáticas (na v1 usa-se "Repetir", §6.4), prospeção automática em massa, várias carrinhas/rotas no mesmo dia, feriados/férias das lojas como datas (na v1 ficam nas notas), seguimento GPS contínuo (nunca — ver §11).

## 4. Conceitos e regras de negócio

### 4.1 Fases da loja (funil)

| Fase | Nome no ecrã | Pino | Significado |
|---|---|---|---|
| `potencial` | Potencial | ⚪ cinza claro | Identificada, ainda sem contacto |
| `contactada` | A aguardar amostra | 🟡 amarelo | Já houve contacto; a loja espera a amostra |
| `amostra` | Amostra recebida | 🟠 laranja | Amostra entregue, a experimentar |
| `cliente` | Cliente | 🟣 roxo | Compra regularmente |
| `perdida` | Perdida | ⚫ preto | Não interessada — visível no mapa (para se saber que não vale a pena visitar); pode ser escondida pelo filtro |

O nome interno da fase (a coluna "Fase") é o que a API aceita, o que fica no histórico (`contactada→amostra`) e o que dá a cor ao pino; nunca muda. O nome no ecrã é o único texto que o utilizador vê (filtros, formulário, cartão, ficha, título do pino). Em 2026-10-13 o Bruce renomeou "Contactada" para "A aguardar amostra" e "Amostra" para "Amostra recebida"; as chaves, as cores e as regras automáticas ficaram iguais.

**Ordem para regras automáticas:** `perdida` < `potencial` < `contactada` < `amostra` < `cliente`. As mudanças automáticas **só sobem** nesta ordem, com uma exceção: o resultado "Não interessado" passa a loja a `perdida`, exceto se for `cliente`. A fase pode sempre ser mudada à mão (um toque na ficha). Cada mudança de fase cria uma interação `mudanca_fase` no histórico.

**Efeitos automáticos de um resultado** (iguais quer venham de uma paragem da rota, §8.3, quer de uma visita/chamada registada na ficha, §6.3):

| Resultado | Nova fase (se for "subida") |
|---|---|
| Interessado / Voltar depois | `contactada` |
| Amostra deixada | `amostra` |
| Entregue (encomenda) | `cliente` |
| Não interessado | `perdida` (exceto `cliente`) |

### 4.2 Alertas no mapa e temporizadores

- 📦 **Entrega pendente:** a loja tem pelo menos uma encomenda `pendente`.
- 🔁 **Visita pendente:** uma paragem que não era de entrega (amostra/acompanhamento/angariação) ficou por fazer, ou terminou com "Voltar depois" (§8.3) — fica marcada até uma visita/amostra com sucesso ou até ser anulada à mão.
- ⏰ **Seguimento em atraso:**
  - fase `amostra` e `ultima_interacao_em` há mais de **7 dias**, ou
  - fase `cliente` e `ultima_visita_ou_entrega_em` há mais de **30 dias** (ambos configuráveis).

Regras dos temporizadores:
- Só interações `visita`, `chamada`, `amostra`, `entrega` atualizam `ultima_interacao_em` (notas e mudanças de fase não "silenciam" o alerta).
- Só visitas/amostras/entregas **com sucesso** atualizam `ultima_visita_ou_entrega_em`.
- Atualização sempre com `GREATEST(valor atual, ocorrida_em)` (registos atrasados vindos do telemóvel nunca andam para trás).
- Se o valor for nulo (loja acabada de criar), conta a partir de `fase_desde` (data em que entrou na fase atual).

### 4.3 Motivo de uma paragem

`entrega` · `amostra` · `acompanhamento` · `angariacao`. Pré-escolha ao adicionar à rota: `entrega` se a loja tiver encomenda `pendente` com data **até ao dia da rota (inclusive)**; senão `angariacao` (potencial/perdida), `amostra` (contactada), `acompanhamento` (amostra/cliente). Se a loja tiver visita pendente 🔁, usa o motivo dessa visita. Pode ser alterado.

## 5. Modelo de dados (MariaDB)

**Tempo:** cada ligação à BD corre `SET time_zone = '+00:00'`. Instantes (`*_em`) em `DATETIME` UTC. Datas de calendário (data de entrega, data da rota) em `DATE` e horas de janela em `TIME`, ambas em hora local de Lisboa. "Hoje" é sempre calculado em `Europe/Lisbon`.

**`utilizadores`** — id, nome, email (único), password_hash, perfil (`admin`|`utilizador`), ativo, criado_em.

**`sessoes`** — id, utilizador_id, token_hash, dispositivo (texto), criado_em, ultimo_uso_em, expira_em (login persistente por dispositivo, §11).

**`regioes`** — id, nome, ordem. Uma região só pode ser apagada se não tiver lojas (senão renomeia-se).

**`lojas`**
- id, nome, fase, fase_desde, regiao_id (**opcional** — "Sem região" nos filtros)
- morada, codigo_postal, localidade
- lat, lng (`DECIMAL(9,6)`), origem_coords (`pin_manual`|`gps`|`geocoder`), precisao_m (opcional)
- telefone, pessoa_contacto, notas (incluem férias/feriados na v1)
- instagram, site (opcionais; acrescentados no portal em 2026-10-13, a pedido do dono: o Instagram guarda-se como o endereço do perfil, `https://www.instagram.com/<nome>/`, e o site como URL `http(s)`, até 255 caracteres; não existiam no CRM autónomo)
- janela1_inicio, janela1_fim, janela2_inicio, janela2_fim (opcionais; ex.: 10:00–13:00 e 15:00–19:00; sem janelas = qualquer hora do dia de trabalho)
- dias_fechada (conjunto de dias da semana)
- visita_pendente_motivo, visita_pendente_desde (🔁, §4.2)
- ultima_interacao_em, ultima_visita_ou_entrega_em
- criado_por, criado_em, atualizado_em
- Apagar: só se não tiver interações, encomendas nem paragens (enganos); caso contrário usa-se `perdida`.

**`interacoes`** (linha do tempo) — id, loja_id, tipo (`visita`|`chamada`|`amostra`|`entrega`|`nota`|`mudanca_fase`), resultado (ex.: `interessado`, `nao_entregue_fechada`, `nao_visitada`), notas, paragem_id (opcional), utilizador_id, ocorrida_em, client_uuid (único, opcional).

**`produtos`** — id, nome, formato (ex.: "balde 5 L"), ativo, ordem.

**`encomendas`** — id, loja_id, data_entrega (`DATE`), estado (`pendente`|`entregue`|`cancelada`), paragem_id (opcional — a paragem que a vai entregar), notas, recusada_em (opcional), criado_por, criado_em, entregue_em.

**`encomenda_linhas`** — id, encomenda_id, produto_id, quantidade.

**`rotas`** — id, data (`DATE`, **única**), estado (`rascunho`|`planeada`|`em_curso`|`concluida`), versao (inteiro, controlo de edições simultâneas), hora_saida, hora_regresso_limite, inicio_lat/inicio_lng e fim_lat/fim_lng (por defeito a fábrica), evitar_portagens, distancia_m, duracao_s, regresso_previsto, geometria (polyline), calculada_em, criado_por.

**`paragens`** — id, rota_id, loja_id (**único por rota**), ordem, motivo, tempo_servico_min, chegada_prevista (`TIME`, nulo se não cabe), aviso (`nenhum`|`fora_de_horario`|`nao_cabe`|`fechada_neste_dia`), estado (`pendente`|`feita`|`nao_feita`), resultado, notas_escritorio (instruções; só leitura no telemóvel), concluida_em, removida_em (remoção "suave" — nunca se apagam paragens de rotas planeadas/em curso).

**`definicoes`** (chave/valor) — morada e coordenadas da fábrica; hora de saída e regresso por defeito (08:00 / 19:00); raio de sugestões (5 km); distância ao percurso para sugestões "no caminho" (3 km); dias sem repetir sugestão após contacto (7); dias de alerta amostra (7) e cliente (30); tempos de serviço por motivo (entrega 10, amostra 10, acompanhamento 15, angariação 15 min); bloco de paragens no Google Maps (9); estado da última cópia de segurança e do último email.

**Técnicas:** `schema_migrations` (nome completo do ficheiro aplicado + data), `tentativas_login`.

## 6. Ecrãs

Interface responsiva única; planeamento otimizado para computador, rota do dia para telemóvel.

### 6.1 🗺️ Mapa (principal)
- Todas as lojas como pinos coloridos por fase, **com o nome sempre visível ao lado do pino, em qualquer zoom, sem agrupamento** (decisão explícita: aceita-se sobreposição de nomes com o mapa muito afastado).
- Ícones 📦 🔁 ⏰ junto ao pino (§4.2).
- Filtros: fase (por defeito todas), região, "só com pendentes".
- Tocar num pino → cartão: nome, fase, contacto em texto («Contacto: pessoa · telefone», só as partes que existem; nada sem ambas), última ação, botões **Ver ficha**, **Adicionar à rota** (escolhe o dia). O botão **Ligar** (`tel:`) do desenho original saiu em 2026-10-13, a pedido do Bruce: o contacto lê-se no próprio cartão.
- Atribuição sempre visível no canto do mapa (§9).

### 6.2 ➕ Adicionar loja
- Pesquisa de morada (autocompletar limitado a Portugal, com "Powered by Geoapify" por baixo) → coloca o pino; o utilizador **arrasta o pino para o sítio exato e confirma**.
- Alternativa: tocar diretamente no mapa.
- No telemóvel: **"Estou nesta loja"** → GPS (só nesse momento) → pino arrastável com círculo de precisão e botão **Confirmar**; se a precisão for pior que 50 m: "Localização imprecisa — ajuste o pino". Morada sugerida por geocodificação inversa.
- Nome e telefone escritos pelo utilizador (não copiados de serviços de terceiros, §9).
- Obrigatórios: nome, pino, fase. Região pré-escolhida = última usada (opcional).
- **Aviso de duplicado:** se já existir uma loja a menos de 50 m → "Já existe *X* aqui — é a mesma?".
- **Falha da pesquisa de morada:** mensagem "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'"; o resto funciona.
- No telemóvel, adicionar loja exige rede (botão desativado com "sem rede").

### 6.3 📋 Ficha da loja
- Dados, fase (mudar com um toque), horário de receção, dias fechada, notas. Desde 2026-10-13 também o Instagram e o site (só aqui, não no registo rápido do §6.2).
- "Estou nesta loja" também aqui, para corrigir a localização (mesmo fluxo de confirmação).
- Linha do tempo com botão para registar chamada/visita/nota; uma chamada ou visita com resultado aplica os efeitos de §4.1.
- Visita pendente 🔁: mostra o motivo e permite anulá-la.
- Encomendas da loja + **Nova encomenda**.

### 6.4 📦 Encomendas
- Lista de pendentes por data de entrega (filtro por região); recusadas mostram "⚠️ recusada em *data*".
- Nova/editar: loja, linhas (produto + quantidade), data de entrega, notas. Aviso se a data cair num dia em que a loja está fechada.
- **Repetir:** copiar para uma nova data, ou "semanalmente até *data*" (cria várias encomendas de uma vez) — é assim que a rotina fixa é tratada na v1.
- **Marcar como entregue** (fora de rota — ex.: levantou na fábrica): mesmos efeitos de "Entregue" (§4.1).
- Cancelar ou mudar a data de uma encomenda que está numa rota: §7.5.
- Se a encomenda for criada/alterada para um dia que já tem rota planeada → aviso "Há uma rota para esse dia — [Adicionar à rota]".
- No telemóvel, criar encomenda exige rede.

### 6.5 🚐 Planear rota (computador) — §7
### 6.6 📱 Rota do dia (telemóvel) — §8

### 6.7 ⚙️ Definições (admin)
Utilizadores (criar, desativar, repor palavra-passe — não é possível desativar/despromover o último admin), produtos, regiões, valores de `definicoes`, **estado da última cópia de segurança e do último email semanal** (com data, para se ver se falhou).

### 6.8 Termos e privacidade
Uso do GPS (só ao tocar, nunca seguimento), dados guardados, atribuições: OpenStreetMap, OpenMapTiles, Geoapify, openrouteservice/VROOM.

## 7. Planeamento de rota

### 7.1 Fluxo
1. **Escolher o dia** (hoje ou futuro; não se criam rotas no passado). Se já existir rota, abre-a.
2. **Entregas entram automaticamente — só quando a rota é criada:** encomendas `pendente` com `data_entrega ≤ dia`, que não estejam "presas" (§7.5). (Visitas pendentes 🔁 não entram sozinhas — aparecem no topo das sugestões, passo 4.) Depois da criação nada entra sozinho: ao abrir a rota, um aviso mostra "N entregas pendentes para este dia não estão na rota — [Adicionar]". Encomendas já noutra rota futura aparecem como "Já na rota de *data* — [Mover para aqui]".
3. **Dias fechados:** uma paragem cuja loja está fechada nesse dia da semana fica com ⚠️ **"Fechada neste dia"** e **não entra no cálculo** até o escritório decidir: retirar, mudar a data da encomenda, ou "manter" (passa a entrar no cálculo — ex.: a loja abre excecionalmente).
4. **Sugestões "aproveitar a viagem"** — lista lateral, ordenada por grupo e depois por distância:
   0. 🔁 visita pendente
   1. 🟠 amostra com seguimento em atraso
   2. 🟣 cliente com seguimento em atraso (> 30 dias)
   3. 🟡 contactada
   4. ⚪ potencial

   Elegíveis: lojas fora da rota, não fechadas nesse dia, sem visita/amostra/entrega com sucesso nos últimos 7 dias, e não `perdida`. Lojas `amostra`/`cliente` **sem** atraso não são sugeridas (podem ser adicionadas pelo mapa).
   - **Antes do cálculo:** lojas a ≤ 5 km (linha reta) de qualquer paragem escolhida. Sem paragens: "Adicione a primeira paragem pelo mapa".
   - **Depois do cálculo:** juntam-se as lojas a ≤ 3 km do percurso desenhado (inclui o trajeto desde a fábrica e entre regiões).
5. **Definições do dia:** hora de saída, hora limite de regresso, início e fim (fábrica por defeito; podem ser outro ponto do mapa, ex.: dormida noutra região), evitar portagens, tempo de serviço por paragem (pré-preenchido pelo motivo).
6. **"Calcular melhor ordem"** (§7.2) → paragens numeradas, linha da rota, km e horas totais, hora de chegada a cada paragem, regresso previsto.
7. **Ajuste manual:** arrastar paragens; adicionar/retirar paragens. Qualquer alteração recalcula as horas automaticamente (§7.3).
8. **Guardar.** Se houver paragens que não cabem: "N paragens não cabem — guardar mesmo assim?".

**Limite: 48 paragens por rota** — o serviço Directions do openrouteservice aceita 50 coordenadas incluindo início e fim (a otimização aceita até 50 *jobs*). Validado no servidor e nos testes.

### 7.2 Ordem — openrouteservice Optimization (VROOM)
- Chamado **apenas pelo servidor PHP**; a chave nunca vai para o browser.
- Pedido: 1 veículo (`driving-car`, início/fim da rota, `time_window` = [saída, regresso limite]); 1 *job* por paragem (exceto ⚠️ fechada) com `location`, `service` (segundos), `time_windows` e `priority`.
- **Tempo:** segundos = horas×3600 + minutos×60 a partir das horas locais (nunca a partir de instantes UTC — evita erros nos dias de mudança de hora). Cada janela é enviada como [início, fim − tempo de serviço], para o serviço acabar antes de a loja fechar.
- **Prioridades:** entregas = 100; visita pendente 🔁 e seguimentos em atraso = 2; restantes = 1. (O VROOM maximiza primeiro a soma das prioridades: como 48 × 2 < 100, nenhuma combinação de visitas vale mais do que uma entrega.)
- **Só coordenadas e identificadores numéricos** são enviados — nunca nomes, telefones ou moradas (termos do serviço).
- *Jobs* não atribuídos → paragem com aviso `nao_cabe` ("⚠️ Não cabe no horário"), sem hora prevista, no fim da lista. O utilizador decide: retirar, **mudar de dia** (= muda a data da encomenda e retira da rota) ou encurtar outras paragens.
- A otimização **não suporta evitar portagens**: a ordem é escolhida com portagens permitidas; as horas vêm sempre de §7.3.

### 7.3 Horas previstas — openrouteservice Directions (fonte única)
Depois de cada cálculo de ordem **e** de cada alteração manual, o servidor faz **uma** chamada Directions pela ordem fixa (com `avoid_features: ["tollways"]` quando "evitar portagens" está ligado) e calcula:
- chegada = partida anterior + duração do troço; se chegar antes da janela, **espera** pela abertura (incluindo esperar pela 2.ª janela do dia — sem aviso);
- `fora_de_horario` só se não restar nenhuma janela onde o serviço caiba nesse dia;
- regresso previsto ao fim; se passar da hora limite → aviso na rota ("regresso previsto 19:40").
Assim as horas mostradas correspondem sempre ao caminho que o motorista vai fazer, e o otimizador e o ajuste manual nunca dão horas diferentes para a mesma ordem.

### 7.4 Edição conforme o estado da rota
| Estado | O que se pode fazer |
|---|---|
| `rascunho` / `planeada` | Tudo. Guardar → `planeada`. Pode ser apagada (as encomendas voltam a ficar livres). |
| `em_curso` | Paragens feitas/não feitas ficam fixas no topo. Só as `pendente` podem ser adicionadas, retiradas ou reordenadas. O recálculo parte da **última paragem concluída, à hora atual**. Guardar mantém `em_curso`. |
| `concluida` | Só leitura, exceto corrigir resultados. Se for de hoje, adicionar uma paragem reabre-a (`em_curso`). |

**Edições simultâneas:** cada gravação envia a `versao` da rota (e `atualizado_em` da loja); se outra pessoa gravou entretanto → "Alterado por outra pessoa — recarregar". Só são enviados os campos alterados. Os resultados vindos do telemóvel estão isentos (§8.4).

### 7.5 Ligação encomenda ↔ paragem e fecho das rotas
- Uma paragem por loja por rota; uma paragem de entrega pode levar **várias** encomendas (`encomendas.paragem_id`).
- Uma encomenda está **"presa"** apenas enquanto estiver ligada a uma paragem `pendente` de uma rota com data de hoje ou futura.
- **Fecho automático** (tarefa noturna, e também no primeiro pedido de cada dia): rotas com data passada passam a `concluida`; paragens ainda `pendente` passam a `nao_feita` com resultado `nao_visitada` (com interação no histórico). As encomendas ficam livres e as visitas ficam 🔁 — entram na rota seguinte. Fechar uma rota à mão faz o mesmo.
- **Cancelar/mudar data** de uma encomenda: numa rota `rascunho`/`planeada` → sai da paragem (se a paragem ficar sem encomendas e o motivo for entrega, a paragem é retirada) e a rota é marcada "recalcular". Numa rota `em_curso` → a paragem fica, mas o telemóvel mostra "encomenda cancelada/adiada".

### 7.6 Falhas do motor
Se o openrouteservice falhar ou exceder o limite: "Cálculo automático indisponível — ordene à mão"; a rota continua editável por arrasto e pode ser guardada sem horas previstas.

## 8. Rota do dia (telemóvel)

### 8.1 Ecrã
- Abre a rota de hoje. **Cartão grande da próxima paragem:** nome, motivo, o que entregar (linhas das encomendas), hora prevista, e as notas da loja, da encomenda e do escritório — cada uma identificada.
- Atraso: se a última paragem foi concluída depois da hora prevista, mostra "atraso +X min", empurra as horas seguintes e assinala paragens que deixam de caber na janela.
- Paragens `nao_cabe` aparecem numa secção "Se houver tempo".
- Desenho "para olhar de relance": botões grandes, sem escrever enquanto se conduz; notas sempre opcionais.
- Atualiza ao voltar à app e a cada 60 s (envia primeiro a fila pendente, §8.4).

### 8.2 Navegação
- Botões **Google Maps** e **Waze** por paragem, destino único (o Waze só aceita um destino):
  - `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving&dir_action=navigate[&avoid=tolls]`
  - `https://waze.com/ul?ll=LAT,LNG&navigate=yes[&avoid_tolls=true]`
- Botão opcional **"Abrir paragens X–Y no Google Maps"** em blocos de 9 (configurável), sem origem, `waypoints` pela ordem; o rótulo diz quantas paragens leva. O Google aceita 9 paragens quando o link abre a **app** Google Maps, mas só 3 num browser móvel: na etapa 4 confirma-se no telemóvel da carrinha que abre a app; se não abrir, o bloco passa a 4.
- Links são `<a href>` tocados pelo utilizador (nunca abertos por código). Nenhum precisa de chave da Google.

### 8.3 Registar o resultado (um toque)

| Motivo | Botões | Estado da paragem e efeitos |
|---|---|---|
| entrega | **Entregue ✅** / Não entregue (fechada · recusou · outro) | Entregue → `feita`; todas as encomendas ligadas → `entregue`; interação `entrega`; fase → `cliente`. Não entregue → `nao_feita`; encomendas continuam `pendente` (recusou → marca `recusada_em`, e o planeamento mostra "⚠️ recusada" para o escritório decidir); interação `visita` com o motivo da falha. |
| amostra | **Amostra deixada ✅** / Não foi possível | Deixada → `feita`; interação `amostra`; fase → `amostra`. Não foi possível → `nao_feita`; interação `visita` com resultado; loja fica 🔁. |
| acompanhamento / angariação | **Interessado** / **Não interessado** / **Voltar depois** (+ nota, + "Nova encomenda" se houver rede) | Todos → `feita`; interação `visita`; efeitos de fase de §4.1. "Voltar depois" deixa a loja 🔁. |

- **Desfazer:** após cada toque aparece "Desfazer" durante 10 s, antes de o registo seguir.
- **Corrigir:** enquanto a rota não estiver concluída, o motorista pode mudar o resultado (ex.: loja fechada ao almoço, volta às 16h); depois disso o escritório corrige. Vale o registo mais recente. Reverter "Entregue" põe as encomendas de novo `pendente`; mudanças de fase não são revertidas sozinhas (ficam no histórico e o escritório corrige com um toque).
- Notas do motorista vão para a interação (nunca sobrepõem as notas do escritório).
- A rota passa a `em_curso` no primeiro registo e a `concluida` quando todas as paragens têm estado final, à mão, ou pelo fecho automático (§7.5).

### 8.4 Sem rede
- A rota do dia (paragens, encomendas, notas, coordenadas) fica guardada no telemóvel (IndexedDB) e é mostrada sem rede com "dados de HH:MM".
- Cada registo é **um item da fila** com `client_uuid`, `paragem_id`, `loja_id`, encomendas ligadas e `ocorrida_em` (hora do telemóvel, em UTC; o servidor limita-a à hora atual). O servidor aplica cada item **numa única transação** (paragem + encomendas + fase + interação) e ignora `client_uuid` repetidos.
- A fila é enviada ao recuperar a rede, ao abrir a app, antes de cada atualização e periodicamente; os registos ainda por enviar são mostrados por cima dos dados recebidos. Indicador "por enviar (N)".
- **O que aconteceu no terreno ganha:** se a paragem foi entretanto retirada pelo escritório, é reposta como `feita`; se a encomenda foi cancelada/adiada, fica entregue na mesma e o escritório vê o aviso "entrega registada numa encomenda cancelada".
- A fila sobrevive a fechar a app e a voltar a fazer login. O pedido usa sempre o token CSRF atual (não o do momento do registo); se a sessão tiver expirado, pede login e mantém a fila.
- O *service worker* guarda a "casca" da app; o mapa usa só mosaicos já vistos (sem descarregar mapas para offline).

## 9. Serviços externos e regras

| Serviço | Uso | Custo esperado | Notas |
|---|---|---|---|
| **Geoapify** (dados OpenStreetMap) | Autocompletar morada, geocodificação inversa, mosaicos do mapa | 0 € — plano gratuito: 3.000 créditos/dia, uso comercial permitido; mosaico = 0,25 créditos (~50 por sessão) | Resultados podem ser guardados. Atribuição obrigatória e visível: no mapa "Powered by Geoapify \| © OpenMapTiles © OpenStreetMap contributors"; "Powered by Geoapify" junto à pesquisa/morada sugerida. Se os mosaicos falharem, o mapa muda sozinho para os mosaicos padrão do OpenStreetMap ("© OpenStreetMap contributors"). |
| **openrouteservice** (HeiGIT) | Otimização (VROOM) e Directions | 0 € — plano Standard: 500 otimizações e 2.000 directions/dia, 40/min | Sem garantia de serviço. Servidores na UE. Proibido enviar dados pessoais. Atribuição no ecrã de planeamento: "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap". |
| **Google Maps / Waze (links)** | Navegação do motorista | 0 € | Sem chave nem conta. |
| **Leaflet**, **PHPMailer** | Mapa; envio de email | 0 € | Ficheiros copiados para o projeto (sem CDN, sem Composer em produção), com as licenças. |

**Porque não a Google Places/Routes:** com faturação portuguesa aplicam-se os termos europeus do Google Maps Platform (desde 8 jul 2025), que proíbem guardar nome/morada/telefone/coordenadas vindos da Google (só o `place_id`) e limitam coordenadas a 30 dias. A otimização de waypoints da Routes API não suporta janelas horárias; a Route Optimization API suporta, mas é paga, exige OAuth e está sujeita aos mesmos termos. Assim, **todas as coordenadas guardadas são "nossas"** (pino confirmado, GPS no local, ou geocoder que permite guardar).

## 10. Arquitetura técnica

- **Servidor:** PHP **8.4** simples (sem framework), PDO com *prepared statements* e um pedido por instrução, router próprio pequeno. Sem Composer em produção; bibliotecas pequenas copiadas para `src/Lib/` (PHPMailer) e `public/vendor/` (Leaflet). Composer só para ferramentas de teste, com a versão de PHP fixada em 8.4 (`config.platform.php`).
- **Base de dados:** MariaDB (versão da Hostinger confirmada com `SELECT VERSION()` na etapa 1 e usada igual em local e no CI).
- **Frontend:** HTML + CSS + JavaScript (módulos ES), sem compilação; Leaflet com etiquetas permanentes nos pinos. PWA instalável (manifest + service worker).
- **API:** JSON em `/api/...`; autenticação por sessão + token CSRF em cabeçalho; respostas da API nunca em cache.
- **URLs dos serviços externos configuráveis** (para os testes usarem um servidor de respostas gravadas).

### 10.1 Hostinger — disposição no servidor
- O CRM é criado como **site novo** ("Adicionar website" com o subdomínio, ex.: `crm.<domínio>`) — não pela ferramenta "Subdomínios", que o poria dentro do site principal. PHP 8.4 escolhido no hPanel; HTTPS forçado; **CDN e cache automática da Hostinger desligadas** para este site.
- Pastas em `/home/<user>/domains/crm.<domínio>/`:
  ```
  releases/<commit>/   # cada versão publicada (código completo)
  current -> releases/<commit>   # versão ativa (link)
  public_html -> current/public  # raiz web = só a pasta public/ (link)
  shared/              # só existe no servidor, nunca é substituída na publicação:
    config.php  backup.cnf  backups/  sessions/  logs/
  ```
  Confirmar na etapa 1 que o LiteSpeed segue o link de `public_html`; se não seguir, alternativa: copiar `public/` para `public_html/` e o resto para `current/`, com `index.php` a carregar a app a partir do caminho configurado.
- Todos os comandos (cron, publicação) usam o binário explícito `/opt/alt/php84/usr/bin/php` (o `php` do SSH é o da conta, não o do site); o primeiro passo da publicação verifica que é PHP ≥ 8.4.
- Cache HTTP (`public/.htaccess`): `no-cache` para `sw.js`, páginas e manifest; `no-store, private` para `/api/*`. O nome da cache do service worker leva o código da versão (preenchido na publicação), para os telemóveis atualizarem sempre a app; HTML/JS carregados "rede primeiro".

### 10.2 Tarefas agendadas (cron da Hostinger, em UTC)
- `bash …/current/bin/backup.sh` — todas as noites (§12).
- `…/php84 …/current/bin/tarefas-diarias.php` — fecho automático das rotas passadas (§7.5), limpeza de sessões expiradas, email semanal ao domingo.

### 10.3 Estrutura do repositório
```
purple-house-crm/
├── public/              # raiz web: index.php, assets/, vendor/leaflet, manifest, sw.js, .htaccess
├── src/
│   ├── Http/            # router, controladores
│   ├── Dominio/         # regras de negócio — funções puras, testáveis sem BD/rede
│   ├── Repositorios/    # acesso à BD
│   ├── Servicos/        # Geoapify, openrouteservice, email
│   └── Lib/PHPMailer/   # copiado, com licença
├── migrations/          # AAAAMMDDHHMM_descricao.sql
├── bin/                 # migrate.php, backup.sh, tarefas-diarias.php, seed-demo.php, reset-password.php, deploy-gate.sh, publicar-manual.sh
├── config/config.example.php
├── tests/               # Unit/, Integration/, e2e/ (Playwright), fixtures/ (respostas gravadas)
├── docs/superpowers/specs/
├── .github/workflows/
├── .claude/settings.json  # regras para o Claude Code (§13)
├── CLAUDE.md
└── README.md
```

## 11. Segurança e privacidade

- **Login:** email + palavra-passe (`password_hash`), limite de tentativas, sem registo público (só o admin cria contas). **Login persistente por dispositivo durante 30 dias** (token aleatório guardado com hash em `sessoes`, renovado com o uso), para o motorista não ter de escrever a palavra-passe na rua; sessões PHP guardadas em `shared/sessions`. O estado `ativo` é verificado em cada pedido (desativar um utilizador corta o acesso de imediato). Recuperação de emergência: `bin/reset-password.php` por SSH.
- **Perfis:** `admin` (tudo + definições/utilizadores) e `utilizador` (lojas, encomendas, rotas).
- HTTPS obrigatório; cookies `Secure`/`HttpOnly`/`SameSite=Lax`; CSRF; escaping de saída; *prepared statements*.
- **Chaves:** todas em `shared/config.php`, fora do Git. Geoapify usa **duas chaves**: uma só para mosaicos, que tem de ir para o browser e fica restrita ao endereço do CRM (origem/referer) no painel Geoapify; outra só no servidor (pesquisa e geocodificação inversa). A chave do openrouteservice fica só no servidor.
- **GPS:** apenas quando o utilizador toca em "Estou nesta loja" (na criação ou na ficha); autorização do browser na primeira vez; **nunca há seguimento contínuo** do motorista (Código do Trabalho, RGPD, orientações da CNPD). Guarda-se só o ponto da loja.

## 12. Cópias de segurança e migrações

- Cópia diária automática da Hostinger (incluída no plano).
- **Cópia própria todas as noites:** `bin/backup.sh` corre `mysqldump` (credenciais num ficheiro `shared/backup.cnf` com permissões 600, nunca na linha de comando) comprimido para `shared/backups/`, mantendo 30 dias. É um script de shell porque a Hostinger desliga no PHP as funções que executam programas.
- **Email semanal ao Bruce** com a cópia **encriptada** (zip AES-256; palavra-passe no `config.php` e guardada pelo Bruce num local seguro), enviado por SMTP autenticado da Hostinger (`smtp.hostinger.com:465`) a partir de uma caixa de correio dedicada. Confirmar na etapa 5 se a caixa de correio do plano é gratuita ou um período experimental de 1 ano (§16). As Definições mostram a data da última cópia e do último email com sucesso.
- **Migrações:** ficheiros `migrations/AAAAMMDDHHMM_descricao.sql` (data/hora no nome evita choques quando os dois sócios criam migrações em paralelo; o CI falha se houver prefixos repetidos). `bin/migrate.php` executa uma instrução de cada vez, pára no primeiro erro e só regista o ficheiro em `schema_migrations` (pelo nome completo) depois de tudo correr bem. Regras (no `CLAUDE.md`): uma alteração de estrutura por ficheiro; alterações **só aditivas** (a versão anterior do código tem de continuar a funcionar com a nova estrutura); nunca editar uma migração já publicada.

## 13. GitHub, colaboração e publicação

- **Organização GitHub gratuita "Purple House"** com o Bruce e o sócio como *owners*; repositório privado `purple-house-crm` (a empresa, e não uma conta pessoal, é dona do código). Segredos ao nível do repositório (no plano gratuito os segredos da organização não chegam a repositórios privados).
- **Segredos nunca no GitHub:** palavras-passe do hPanel, da BD e as chaves Geoapify/openrouteservice existem **só** no `shared/config.php` do servidor (e no `config.php` local de cada sócio, com chaves de desenvolvimento próprias). Os *Secrets* do GitHub guardam apenas: uma **chave SSH dedicada à publicação** (criada para isso, revogável), o endereço/porta/utilizador SSH e a impressão digital do servidor (nunca se desliga a verificação do servidor).
- **Chave de publicação limitada:** como a Hostinger tem um único utilizador SSH para todo o plano (incluindo a Cleide), a chave de publicação é registada no servidor com `restrict,command="~/phc-gate/deploy-gate.sh"`: só consegue enviar ficheiros para as pastas do CRM e correr os passos de publicação. A porta vive em `~/phc-gate/` (fora das versões publicadas, atualizada à mão), para que uma versão publicada não a possa substituir. Isto limita os comandos; a chave continua a ser tão sensível como o próprio acesso de publicação. Confirmar na etapa 1 que o gestor de chaves do hPanel mantém essa restrição.
- **Forma de trabalhar:** cada alteração num ramo próprio → *pull request* → testes automáticos → junção ao `main`. O ficheiro `.claude/settings.json` do projeto bloqueia o Claude Code de fazer *push* direto para `main` (substitui a proteção de ramo, que em repositórios privados de organizações exige o plano pago GitHub Team).
- **Dois sítios:**
  - **Site de teste** (`crm-teste.<domínio>`, base de dados própria com dados de demonstração): publicado **automaticamente** a cada junção ao `main` com testes aprovados. É aqui que o Bruce experimenta cada etapa, também no telemóvel.
  - **Produção** (`crm.<domínio>`): publicada **quando o Bruce (ou o sócio) carrega em "Publicar em produção"** no GitHub (ação manual), com a mesma versão já testada.
- **Passos de cada publicação (GitHub Actions):** verificar PHP 8.4 → enviar a nova versão para `releases/<commit>/` → **cópia de segurança da BD** (sempre) → migrações → mudar `current` para a nova versão → verificar `/api/saude`. Se algum passo falhar, a publicação pára e a versão anterior continua ativa; voltar atrás = mudar `current` para a versão anterior (guardam-se as 3 últimas). Publicações nunca correm em simultâneo (`concurrency`), e só a partir do `main`.
- **Minutos do GitHub Actions (2.000/mês grátis):** cache de dependências e do browser de testes, só Chromium, não correr para alterações só de documentação, relatórios guardados 3 dias. Se os minutos acabarem, `bin/publicar-manual.sh` faz a mesma publicação a partir do Mac.

## 14. Testes

- **Unitários (PHPUnit), sobre `src/Dominio/`:** transições de fase (incluindo `perdida` e o "só sobe"), temporizadores dos alertas, elegibilidade e ordenação das sugestões, conversão de janelas (fim − serviço, 2.ª janela, dias de mudança de hora), cálculo de chegadas/esperas/⚠️/regresso previsto, prioridades (teste: 1 entrega + 11 visitas em que só um dos lados cabe → a entrega fica), pedido ao VROOM sem dados pessoais, limite de 48 paragens, "presa"/fecho automático de rotas, links de navegação e blocos.
- **Integração:** API + MariaDB real (mesma versão da Hostinger) no CI; aplicação de um item da fila numa transação, `client_uuid` repetido, paragem removida entretanto, conflito de `versao`. Os serviços externos são substituídos por um **servidor de respostas gravadas** — os testes nunca chamam Geoapify/openrouteservice reais.
- **Ponta a ponta (Playwright, Chromium):** registar loja, criar e repetir encomenda, planear rota, executar a rota em vista de telemóvel, registo sem rede e reenvio, sessão expirada com fila pendente. Corre em cada *pull request* e é obrigatória para publicar.
- **Depois de cada publicação:** verificação automática no servidor real (`/api/saude`, página inicial, `.htaccess`).
- **Dados de demonstração:** `bin/seed-demo.php` cria lojas em várias regiões, produtos e encomendas; **recusa correr se a configuração não for `local` ou `teste`**.
- Validação final de cada etapa: o Bruce experimenta no site de teste com um dia "real" antes de publicar em produção.

## 15. Etapas de construção

Cada etapa termina no site de teste, é validada pelo Bruce e depois publicada em produção.

1. **Base:** repositório e organização, CI, publicação (teste + produção) com chave limitada, login persistente e perfis, regiões, lojas (adicionar/editar, duplicados, GPS), mapa com pinos coloridos e nomes, filtros, atribuições.
2. **Ficha e encomendas:** ficha, linha do tempo e efeitos de fase, produtos, encomendas (repetir, marcar entregue), alertas 📦 🔁 ⏰.
3. **Planear rota:** entregas automáticas, dias fechados, sugestões (raio + percurso), otimização VROOM, horas por Directions, ajuste manual, regras por estado, fecho automático.
4. **Rota do dia:** ecrã do telemóvel, navegação (confirmar blocos de 9 no telemóvel da carrinha), registos com desfazer/corrigir, PWA instalável, fila sem rede.
5. **Acabamentos:** cópias noturnas e email semanal encriptado, estado das cópias nas Definições, página de termos, melhorias de usabilidade.

## 16. Custos mensais

| Item | Custo |
|---|---|
| Hostinger (2 sites: teste e produção) | já pago |
| Geoapify, openrouteservice, links Google Maps/Waze, Leaflet, PHPMailer | 0 € |
| GitHub (organização gratuita, repo privado, 2.000 min de Actions) | 0 € |
| Caixa de correio para o email semanal | 0 € se incluída no plano; confirmar na etapa 5 se é período experimental (depois paga) |

## 17. Pré-requisitos

**Bruce**
1. Conta GitHub; criar a organização "Purple House"; convidar o sócio.
2. Escolher o domínio onde ficam `crm.` e `crm-teste.` (um domínio já existente na Hostinger).
3. No hPanel: ativar SSH; criar os dois sites e as duas bases de dados; escolher PHP 8.4; desligar CDN/cache nesses sites.
4. Criar contas gratuitas na Geoapify e no openrouteservice (as chaves vão para o `config.php` do servidor — nunca para o chat nem para o GitHub).
5. Instalar as ferramentas no Mac (requer a palavra-passe do Mac): Homebrew → `php@8.4`, `mariadb@<versão da Hostinger>`, `composer`, `node`, `gh`.

**Sócio** (também descrito no README)
1. Conta GitHub e aceitar o convite da organização; instalar o Claude Code.
2. Instalar as mesmas ferramentas no seu computador e fazer `gh auth login`.
3. Copiar `config/config.example.php` para `config/config.php` com as **suas** chaves de desenvolvimento Geoapify/openrouteservice (gratuitas) — não partilha as de produção.
4. Correr `bin/seed-demo.php` para ter dados de exemplo; receber do Bruce uma conta `admin` nos sites de teste e produção.
