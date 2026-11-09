# CRM Purple House — fase "A aguardar fecho" (pino verde)

Data: 2026-11-09. Pedido do dono, depois de a lista de Clientes e os contactos
(desenho de 2026-11-07) estarem em produção. Desenho aprovado em conversa
("pode ser como você disse").

## 1. O que se pede

Uma fase nova do funil, com pino **verde**, entre "Amostra recebida" e
"Cliente": a loja já recebeu a amostra, já houve o contacto seguinte, e agora
a equipa contacta-a para acertar **condições de pagamento e entregas**. O dono
chamou-lhe "A aguardar fechamento"; aceitou a forma portuguesa **"A aguardar
fecho"**.

## 2. Decisões

| Assunto | Decisão |
|---|---|
| Chave (API, histórico, classe CSS) | `fecho` — nunca muda, como as outras (desenho original §4.1) |
| Nome no ecrã (`rotulo` em `lib/crm/fases.js`) | "A aguardar fecho" |
| Cor do pino | `#2e9e4f`, sem contorno (`contorno: null`) |
| `ORDEM` (regras automáticas) | `perdida, potencial, contactada, amostra, fecho, cliente` |
| `FUNIL` (mostrar e filtrar) | `potencial, contactada, amostra, fecho, cliente, perdida` |
| Lojas existentes | Nenhuma muda. A fase dá-se **à mão**, na ficha (um toque na pastilha), como qualquer outra; a mudança fica no histórico (`mudanca_fase`) como hoje |
| Regras automáticas (F4/F5, ainda por construir) | Nenhum resultado atribui `fecho`. A tabela do §5.1 do dossiê não muda: "Entregue → cliente" sobe por cima de `fecho`; "Amostra deixada → amostra" **não desce** uma loja em `fecho` (só sobe) |
| Rota — motivo pré-escolhido (`MOTIVO_POR_FASE`) | `fecho → acompanhamento` (como `amostra` e `cliente`) |
| Rota — sugestões "aproveitar a viagem" (`FASES_SUGERIDAS`) | Continua `(contactada, potencial)`: `fecho` fica de fora, como `amostra` e `cliente` |
| Filtros do mapa guardados | Ver §3 |
| Seed local | Mais uma loja "(demo)" em `fecho` (passa a 25); a mensagem "Criadas: …" e os testes acompanham |

Tudo o resto deriva das constantes: os pinos do mapa, os filtros do mapa, as
pastilhas (com contagem) da lista de Clientes, as pastilhas da ficha, o cartão
da loja, o anel da paragem na rota e a lista de paragens leem `ORDEM`, `FUNIL`
e `FASES`, e a cor vem da classe `.pino--fecho` no `crm.css`. Não há novos
campos, nem mudanças nos contactos, no consumo ou nas marcas.

## 3. Filtros do mapa já guardados (migração)

Os filtros do mapa ficam no `localStorage` (`crm.filtros`) como a lista das
fases **mostradas**. Quem gravou filtros antes desta fase tem lá as cinco de
antes; sem cuidado, as lojas em `fecho` ficavam escondidas no mapa sem a
pessoa saber (e o botão "Filtros" ficava marcado).

Regra: ao guardar, grava-se também `conhecidas: [...ORDEM]` (as fases que
existiam quando se guardou). Ao carregar, qualquer fase da `ORDEM` que **não**
esteja em `conhecidas` é nova desde então e **entra** no conjunto das
mostradas. Sem `conhecidas` (o formato antigo), as conhecidas são as cinco de
antes (`perdida, potencial, contactada, amostra, cliente`), por isso `fecho`
entra. Uma fase que esteja em `conhecidas` e não esteja em `fases` foi
escondida de propósito e **fica** escondida. Um conjunto gravado vazio
continua vazio, exceto pelas fases novas. `filtrosAtivos` continua a comparar
o tamanho com `ORDEM.length`.

## 4. Testes

- Servidor: `test_dominio_fases` (seis fases, literais), `test_dominio_rotas`
  (`fecho → acompanhamento`), `test_rotas_adicionar` (uma loja em `fecho`
  entra com `acompanhamento` e os minutos desse motivo), `test_dominio_sugestoes`
  (`fecho` excluída, também ao lado das paragens), `test_seed_local` (25 lojas,
  seis fases, contagens), `test_consistencia_frontend` (automático, pela
  `ORDEM`).
- Portal: `fases.test.js` (seis fases, rótulos, cores, `FUNIL`),
  `css.test.js` (automático), `filtros.test.js` (a migração do §3: formato
  antigo, `conhecidas` incompleta, `fecho` escondida de propósito, conjunto
  vazio, `guardarFiltros` escreve `conhecidas`), `listaClientes.test.js`,
  `formularioLoja.test.js`, `rota.test.js` (seis pares), e o que mais a
  suite apontar.
- Aceitação local no browser (1280 px e 375 px): pino verde no mapa, filtro,
  pastilha na lista de Clientes com contagem, mudar uma loja para `fecho` na
  ficha e ver o histórico, cartão da loja, anel verde na paragem de uma rota.

## 5. Documentação

- `CRM_PORTING_GUIDE.md` §5.1: `ORDEM`/`FUNIL`, linha nova na tabela, nota
  datada de 2026-11-09 (só à mão; as regras automáticas não a atribuem; a
  migração dos filtros); §5 "Âmbito simples" (motivos por fase) e §5
  sugestões, onde enumeram fases; §12 se falar das 24 lojas do seed.
- Desenho original (`2026-10-02-…-desenho-original.md` §4.1): linha nova na
  tabela e nota datada, como a do 2026-10-13.

## 6. Fora do âmbito

Regras automáticas novas, mudanças nos campos da ficha ou nos contactos,
alertas por tempo numa fase (F5).
