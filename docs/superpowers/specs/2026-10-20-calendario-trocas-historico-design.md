# Calendário: trocas de pessoas e histórico — desenho

Data: 2026-10-20 (revisto a 2026-10-22 com a revisão do desenho). Ramo `matheus-calendario-trocas`
(de `main` 4e7b1a8). Assenta no calendário automático
(`docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`), que já está no ar.

## Pedido do dono

«Quero também que os administradores consigam trocar uma pessoa por outra. E também era bom um
histórico de qual utilizador mudou o quê.»

Decisões do dono (2026-10-20/22, não re-perguntar):
1. **Trocar** cobre dois casos:
   - **dia da escala:** num dia, a escala põe a Emily em Alfragide 14h–23h, mas vai a Beatrice;
   - **duas pessoas entre si:** num dia, a Emily e a Joana trocam de loja ou de turno.
2. **Só administradores** (papel `admin`) trocam e desfazem trocas. Os gerentes continuam a marcar
   idas como hoje.
3. **Contagem:** uma troca só conta quando quem entra é gestor (admin ou gerente). As idas normais
   contam como hoje.
4. **Histórico só do calendário**, aberto por um botão no topo do calendário, com a lista do mês.
5. **A troca muda só o calendário** (decisão por omissão, 2026-10-22): a escala do RH não muda, por
   isso o lembrete da app do ponto, a cerca da app do ponto e o «Em falta» do painel continuam a
   contar com quem sai (ver §4).

## 1. Uma troca é uma ida «no lugar de»

O cálculo já faz metade: a ida de um colaborador **tira à escala dele** as horas da ida nesse dia
(`backend/calendario.py`, `dia_do_calendario`, o `tirado`). Uma troca é uma ida (colecção
`bolso_idas`) com dois campos novos:

| Campo | O que é |
|---|---|
| `troca_id` | uuid comum às idas da mesma troca (1 ida na troca simples, 2 na troca entre si) |
| `no_lugar_de_emp` | `employee_id` de quem sai. O cálculo é por ficha (a escala vive na ficha), e assim a troca sobrevive a uma conta apagada |

O nome de quem sai **não** se grava na ida: resolve-se na resposta com o `nome_do_emp` (o mesmo
nome que a linha da escala mostra) e escreve-se só nos retratos do histórico.

**No cálculo** (`dia_do_calendario`, no ciclo das idas, fora do ramo do colaborador para valer
também quando quem entra é gestor): uma ida com `no_lugar_de_emp` tira à escala de quem sai as
horas da troca **só se**, nesse dia, a escala de quem sai está **na loja da troca**. Se a escala
de quem sai mudou depois (passou para outra loja), a troca deixa de lhe tirar horas e fica uma ida
normal, à vista — não abre um buraco inexplicado noutra loja.

**`extra` numa troca** é `true` só quando quem entra tem ausência aprovada nesse dia (a regra B, ver
abaixo); fora isso `false`: o «no lugar de X» já diz o que se passou, e numa troca de turnos as
duas pessoas ficavam «extra» sem o serem.

**Feriados:** a condição «a escala não põe ninguém» (`do_dia or feriados_da_loja(...)`, hoje em
linha no `dia_do_calendario`) passa para um ajudante único usado pelo cálculo e pelo `escala_de`.

**Forma da resposta do mês** (sempre presentes; `null` fora das trocas):
- `dias[].lojas[].pessoas[]` ganha `troca_id` e `no_lugar_de` (o nome de quem sai);
- `idas[]` ganha `troca_id` e `no_lugar_de`;
- o topo ganha `pode_trocar` (papel `admin`). `resposta_do_mes(..., pode_trocar=False)` e
  `contagem(..., papeis=None)` levam valor por omissão (há chamadas posicionais nos testes).
- Partem de propósito, e actualizam-se: `test_outubro.py` (compara a pessoa inteira) e
  `test_resposta_do_mes.py` (compara as chaves de `idas[]`).

### Troca simples (dia da escala)

`POST /api/bolso/calendario/trocas` com `{data, sai, entra, inicio, fim}` (`sai` e `entra` são
`user_id`). O servidor:
- tira a loja e as horas de quem sai da escala dele nesse dia, com a função pura nova
  `escala_de(dia, dados, emp_id)` (a escala menos as ausências aprovadas e menos o feriado da loja,
  pelo ajudante único);
- grava **uma** ida de `entra` nessa loja, `inicio`–`fim`, com `troca_id` novo e
  `no_lugar_de_emp`.

As horas vêm preenchidas com as de quem sai e podem encurtar-se (meio dia): têm de ficar **dentro**
das horas de quem sai.

Quem entra pode estar na escala noutra loja a essas horas: **aceita-se** (a loja dele fica com
buraco, a vermelho, que é a verdade), e o painel avisa antes, ao lado do nome: «na escala em
Amadora 14h–23h».

### Troca entre si

`POST /api/bolso/calendario/trocas/entre-si` com `{data, uma, outra}` (dois `user_id`, ambos na
escala nesse dia). Grava **duas** idas com o mesmo `troca_id`: cada pessoa vai para a loja e as
horas da outra, «no lugar» dela. **Turnos inteiros**, sem horas à escolha. Tudo ou nada, pela mesma
compensação do POST das idas. Recusa-se se loja e horas são iguais nas duas (não muda nada) ou se
alguma já tem troca nesse dia.

### Recusas (o servidor manda). Sem artigo nem género: o RH não guarda o género.

| Caso | Resposta |
|---|---|
| quem pede não é `admin` (nas três rotas `/trocas`) | **403** «Só os administradores trocam pessoas.» |
| quem sai não está na escala nesse dia (folga, ausência aprovada, feriado da loja) | **409** «Emily não está na escala a 27/10.» |
| as horas da troca saem das de quem sai | **409** «As horas da troca têm de estar dentro das de Emily (14h–23h).» |
| `sai` = `entra`, ou `uma` = `outra`, ou troca entre si sem diferença | **400** «Escolha outra pessoa.» |
| quem sai já tem troca nesse dia, com horas que se sobrepõem | **409** «Já há uma troca para Emily a 27/10 (Beatrice).» |
| quem entra tem ausência aprovada, ou já tem uma ida que choca | **409**, como nas idas (mesmas frases) |
| horas mal escritas, quem entra com papel que não se escala, quem sai sem conta | **400**, como nas idas |

Duas admins a trocar a mesma pessoa no mesmo segundo podem ambas passar: aceita-se, alargando o
comentário `ponytail:` que já existe na compensação (nenhum índice cobre «a mesma pessoa a sair»).

### Mudar e desfazer

- Uma troca **não se altera nem se apaga como ida**: `PUT` e `DELETE /calendario/idas/{id}` lêem a
  ida e, se tiver `troca_id`, dão **409** a toda a gente: «Isto é uma troca: desfaça-a e faça
  outra.» (Ordem: 404 → 409. O 403 por papel fica só nas rotas `/trocas`.)
- **Desfazer** = `DELETE /api/bolso/calendario/trocas/{troca_id}`. Só admin. Apaga **todas** as
  idas da troca, por isso a troca entre si nunca fica a meio.
- **Regra B do dono vale para as trocas:** uma ausência aprovada depois da troca não a apaga; a
  troca fica até uma admin a desfazer. Desfazer devolve cada pessoa à sua escala, e a ausência
  tira-a.
- O gerente continua a poder fazer o equivalente a uma troca entre si de horas iguais com duas idas
  normais, e a mudar a pessoa de uma ida pelo PUT. Não se bloqueia.

### Contagem

`calendario.contagem(idas, lojas, nomes, papeis=None)` salta as idas com `troca_id` cujo `user_id`
**não** é gestor. O servidor projecta `troca_id` nas idas e `role` nos utilizadores.

## 2. Histórico

Colecção nova `bolso_historico`, só de acrescentar, com índice em `datas` e em `quando`. Uma entrada
por pedido que mudou alguma coisa:

```
{ id, quando (ISO UTC), quem_id, quem_nome,
  acao: 'marcou' | 'alterou' | 'apagou' | 'trocou' | 'trocou entre si' | 'desfez a troca',
  datas: ['AAAA-MM-DD', …],     # os dias do calendário afectados
  antes: [retrato…], depois: [retrato…] }
retrato = { data, loja, nome, inicio, fim, no_lugar_de }   # nomes já escritos
```

- Escrevem-na as **seis** rotas de escrita: POST, PUT e DELETE das idas; POST das trocas e das
  trocas entre si; DELETE da troca. Sempre **depois** de a mudança estar gravada. Se a escrita do
  histórico falhar, a mudança fica (é o que a pessoa pediu) e o erro vai para o log do servidor.
- Um PUT que não muda nenhum dos cinco campos não grava entrada.
- `GET /api/bolso/calendario/historico?ano&mes`:
  `{"datas": {"$elemMatch": {"$gte": inicio, "$lte": fim}}}` (um `$gte`/`$lte` solto sobre um array
  apanhava um PUT de 30/09 para 02/11 no histórico de outubro), por `quando` descendente, no máximo
  300. Quem vê o calendário vê o histórico (admin, gerente, contabilista).
- Não há histórico para trás: começa no dia em que isto entrar no ar. O script das idas do
  WhatsApp e o de arranque escrevem directamente na base e não deixam entrada.

**Textos** (função pura `linhaDoHistorico(entrada)` em `lib/calendario.js`, testada), por exemplo:

| Acção | Linha |
|---|---|
| marcou | «20/10 às 14:32 · Carol · marcou Débora e Carol em Oeiras, 13h–22h · 6/10, 13/10, 20/10» |
| alterou | «… · Carol · alterou a ida de Débora: Alfragide 10h–14h, 27/10 → Oeiras 13h–22h, 28/10» |
| apagou | «… · Carol · apagou a ida de Débora em Alfragide, 10h–14h · 27/10» |
| trocou | «… · Carol · trocou Emily por Beatrice em Alfragide, 14h–23h · 27/10» |
| trocou entre si | «… · Carol · trocou Emily (Alfragide) com Joana (Amadora) · 27/10» |
| desfez a troca | «… · Carol · desfez a troca de Emily por Beatrice em Alfragide · 27/10» |

Um lote grande (31 dias × 2 pessoas) mostra os primeiros dias e «e mais N».

## 3. Ecrã

- **Trocar:** no Dia (vistas Semana e Mês, filtro Geral), a linha de uma pessoa da **escala**
  passa a ser um botão para admin (`pode_trocar`) quando a pessoa tem conta, com `aria-label`
  «Trocar Emily, 14h–23h». Abre o painel «Trocar Emily» (componente novo `PainelTroca`; o
  `PainelIda` não muda) com o dia, a loja e as horas dela, e duas opções (`Segmento`):
  - **Outra pessoa:** escolher uma pessoa (gestores e colaboradores, sem a própria); quem está na
    escala nesse dia noutra loja leva ao lado «na escala em Amadora 14h–23h»; horas preenchidas com
    as dela, que se podem encurtar;
  - **Trocar turnos:** escolher uma das pessoas na escala nesse dia (qualquer loja), cada uma com a
    loja e as horas. Só aparece quando a linha tocada é o turno inteiro de quem sai.
  A lista de quem está na escala sai de uma função pura `escaladosDoDia(dados, iso, sai)` em
  `lib/calendario.js`, sobre o mês **sem** o filtro de loja (como o `PainelIda`): só linhas
  `origem === 'escala'` com `user_id`, sem quem sai, uma por pessoa, com loja e horas.
- **A troca no ecrã** (Dia, Lista e Pessoal): quem entra aparece com uma segunda linha pequena
  «no lugar de Emily» por baixo do nome (o `truncate` cortava-a na mesma linha a 375 px) e a
  etiqueta «troca». Uma regra só para todas as vistas, no ponto comum `editar(idaId)`:
  - ida com `troca_id` e `pode_trocar` → abre o `PainelTroca` em «desfazer», que mostra a troca
    (as duas idas na troca entre si: «Desfazer apaga as duas») com «Desfazer a troca» (dois toques,
    como o Apagar);
  - ida com `troca_id` sem `pode_trocar` → texto, não é tocável;
  - ida sem `troca_id` → como hoje.
- **Histórico:** um botão com um relógio no cabeçalho do calendário, `aria-label` «Histórico»
  (44 px, entre o título e as setas; cabe a 375 px). Abre um painel em baixo, «Histórico de
  outubro» (o mês do dia escolhido, também na Semana que atravessa dois meses). O pedido sai só ao
  abrir o painel; os erros aparecem dentro dele (`mensagemDeErro`) e um 401 faz `logout()`, como as
  outras chamadas. Vazio: «Sem alterações registadas neste mês. O histórico começou em outubro de
  2026.»
- As quatro chamadas novas de `lib/bolso.js` usam caminhos literais e entram nos dois guardas:
  `tests/fin/test_caminhos_do_bolso.py` e `tests/calendario/test_chamadas_do_calendario.py`.

## 4. Fora de âmbito

- Trocar um gestor por outro: já se faz alterando a ida dele (outra pessoa, Guardar).
- Trocar quem está na escala **sem conta**: não se troca (o pedido é por `user_id`).
- Histórico das mudanças no portal (Locais, Escalas).
- Avisar quem foi trocado (notificações).
- **A app do ponto e o «Em falta» não vêem a troca** (decisão 5): a Emily trocada recebe na mesma o
  lembrete de entrada e aparece «Em falta» no painel; numa troca entre lojas, a cerca da app do
  ponto segue a loja da ficha, por isso quem vai para outra loja e não é isento leva «Está a X m do
  local de trabalho». Já acontecia com as idas; com as trocas vai notar-se mais.

## 5. Testes (o que prova cada regra)

1. Cálculo: troca simples (Beatrice no lugar da Emily, 27/10: a Emily sai, a Beatrice fica 14–23,
   `extra=false`); meio dia (a Emily fica no resto); troca entre si com lojas diferentes (Emily ↔
   Joana, 27/10) e com turnos diferentes na mesma loja (30/10); gestor no lugar de um colaborador;
   escala de quem sai mudada para outra loja depois da troca (não tira nada); ausência aprovada
   depois da troca (regra B); feriado nacional e feriado da loja pelo ajudante único; a pessoa sem
   conta continua a aparecer na escala.
2. `escala_de`: folga, ausência e feriado dão «não está na escala».
3. Contagem: troca com gestor conta; troca entre colaboradores não conta; ida normal de colaborador
   conta como hoje.
4. Rotas: cada recusa da tabela; tudo-ou-nada na troca entre si; PUT e DELETE de uma ida de troca
   dão 409; desfazer apaga as duas; o gerente leva 403 nas três rotas `/trocas`; `pode_trocar` só
   para admin.
5. Histórico: cada uma das seis rotas deixa uma entrada com o antes e o depois certos; um PUT sem
   diferenças não deixa; uma falha do histórico não desfaz a ida; o GET só devolve o mês pedido
   (incluindo o PUT de 30/09 para 02/11), por ordem; `linhaDoHistorico` para as seis acções e o
   lote grande.
6. Ecrã: o toque na linha da escala só existe para admin; o painel envia o corpo certo nas duas
   opções; «Trocar turnos» só no turno inteiro; `escaladosDoDia` sem filtro de loja; a troca
   aparece com «no lugar de» no Dia, na Lista e no Pessoal; o gerente vê-a como texto; Desfazer;
   o botão do histórico, a lista, o vazio e o 401 → logout. Os caminhos novos nos dois guardas.
7. Ensaio no browser a 375 px, em claro e escuro: o `PainelTroca`, o cabeçalho com cinco controlos,
   a linha com «no lugar de» e o painel do histórico.
