# CRM — Lista de clientes, consumo e marcas, e contactos

Data: 2026-11-07. Aprovado pelo dono do projeto, com um pedido acrescentado: a marca tem de poder ficar registada como
"o cliente não quer revelar", para ninguém voltar a perguntar. Revisto contra o código antes de construir.

## O que é

Três partes que servem o mesmo fim: conhecer cada cliente e lembrar o que já se falou com ele.

1. **Lista de clientes:** uma página com todas as lojas, separadas pela fase (a cor do pino) e com pesquisa.
2. **Consumo e marcas:** campos novos na ficha da loja.
3. **Contactos:** blocos numerados na ficha (1.º contacto, 2.º contacto…), acrescentados a cada contacto com a loja.

## 1. Lista de clientes

Página nova `clientes`, nas duas casas (`/crm/clientes` e `/admin/crm/clientes`). Funciona sem o Google: não usa o mapa.

- Mostra **todas as lojas, de todas as fases**, pelo nome (a ordem do `GET /lojas`).
- **Pastilhas de fase:** "Todas" e uma por fase, pela ordem do funil, com a cor do pino e o número de lojas. Escolhe-se
  uma de cada vez. Os números contam só as lojas que batem com a pesquisa em curso, para se ver onde estão os
  resultados.
- **Pesquisa:** filtra enquanto se escreve, no browser. Ignora maiúsculas e acentos ("cafe" encontra "Café"). Procura no
  nome, na pessoa de contacto, no telefone (sem contar os espaços), na localidade e na marca. Com várias palavras, cada
  uma tem de aparecer, em qualquer dos campos, mesmo que só como parte de uma palavra ("café lisboa" encontra o Café em
  Lisboa). Numa loja com a marca por revelar, o texto pesquisável da marca é "não quer revelar": encontra-se com "não
  revela", "revelar" e "não quer revelar", e "cliente" não a traz.
- **Cada linha:** a cor e o nome, a fase em texto (a cor nunca é a única pista), a localidade, a marca, o consumo e a
  data do último contacto, ou "Ainda sem contactos". O que estiver vazio não aparece, exceto o último contacto. Com a
  marca por revelar, lê-se "Marca: não revela".
- **Abrir a ficha:** cada linha é um `Link` para a ficha com `state: {origem: 'clientes'}`, sem nada no endereço. Uma
  função pura com teste, `veioDaLista(state)`, decide se a ficha mostra "Voltar à lista", ao lado de "Ver no mapa" e só
  com a ficha carregada. "Voltar à lista" é um `Link` para `${base}/clientes`, não um `navigate(-1)`. A ficha aberta pelo
  mapa, por ligação direta ou por "Sim, abrir X" não o mostra. Numa falha fica o "Voltar ao mapa", e depois de apagar a
  loja continua-se a ir para o mapa, com o aviso.
- A pesquisa e a fase escolhidas ficam na sessão do browser (`sessionStorage`, chave `crm.clientes`, à prova de falhas e
  com a normalização do `carregarFiltros`), para continuarem lá ao voltar da ficha. Não se misturam com os filtros do
  mapa.
- **Estados:** a carregar; falha com "Tentar novamente"; sem lojas, com ligação para "Nova loja"; sem resultados com
  texto na pesquisa, "Limpar pesquisa", que só limpa o texto e deixa a fase; sem resultados sem texto, só a frase "Sem
  lojas nesta fase.", porque as pastilhas continuam visíveis.

**Na construção:**

- `ITENS_MENU_CRM` ganha `{chave: 'clientes', rotulo: 'Clientes', caminho: 'clientes', soAdmin: false}` a seguir ao Mapa.
  O menu fica Mapa, Clientes, Rotas, Nova loja, Definições.
- Ícone `Users` do lucide nos dois `ICONES` (`CrmLayout.js` e `seccaoCrm.js`), pela ordem do menu.
- `CrmClientes` entra lazy em `rotasCrm.js`, com `<Route path="clientes" element={pagina('clientes', CrmClientes)} />`.
- A página importa `../../components/crm/crm.css` e reutiliza `crm-amostra-fase pino--<fase>`, sem CSS novo: as páginas
  são lazy, e sem o import a cor não aparece a quem abre a lista diretamente.
- As regras ficam num módulo puro com testes, `lib/crm/listaClientes.js`; a página só desenha, como o resto do CRM.

## 2. Consumo e marcas

Bloco "Consumo e marcas" no formulário da ficha, depois das notas, gravado pelo botão Guardar da ficha. Fica só na
ficha, como o Instagram e o site: a "Nova loja" continua curta. O `POST /lojas` aceita os campos na mesma.

| Campo                  | No ecrã                      | Valor                   | Limite         |
| ---------------------- | ---------------------------- | ----------------------- | -------------- |
| `consumo_semanal`      | Consumo semanal              | texto livre             | 100 caracteres |
| `marca_atual`          | Marca atual                  | texto livre             | 100 caracteres |
| `marca_nao_revela`     | O cliente não quer revelar   | `true` ou `false`       |                |
| `outros_sorbets`       | Trabalha com outros sorbets? | `true`, `false`, `null` |                |
| `outros_sorbets_quais` | Quais?                       | texto livre             | 255 caracteres |

O consumo é texto livre por escolha do dono ("2 baldes grandes"): não se ordena nem se soma.

### "O cliente não quer revelar"

Uma caixa por baixo da marca. Serve para ninguém voltar a perguntar, e por isso tem de se ver bem:

- Marcada, o campo da marca fica vazio e desativado e aparece o aviso "Não voltar a perguntar a marca."
- A lista mostra "Marca: não revela".
- Desmarcada antes de guardar, o campo repõe o texto que lá estava. Um toque por engano não apaga uma marca que custou
  a saber. Numa loja que já vinha marcada, abre vazio.

### "Trabalha com outros sorbets?"

Três respostas: Sim, Não e Por saber (`null`, a resposta de quem ainda não perguntou, para não ficar um "Não" falso).
"Quais?" só aparece com Sim. Sair de Sim esconde o campo, e voltar a Sim antes de guardar repõe o texto.

### Regras do formulário

- O texto da marca e de "Quais?" fica guardado nos valores do formulário enquanto estiver escondido. O que se envia é
  `null` enquanto a caixa estiver marcada ou a resposta for diferente de Sim. Marcar e desmarcar, ou Sim, Não, Sim,
  deixam o `camposAlterados` vazio e a ficha sem alterações.
- No `formularioLoja.js`, `marca_nao_revela` (só `true` conta, senão `false`) e `outros_sorbets` (`true`, `false`, senão
  `null`) entram em `valoresVazios`, `preencherComLoja` e `valoresDoFormulario` da ficha, sem passar pelo `textoOuVazio`.
  O `valorAceite` aceita booleanos nos dois, e `null` no segundo.
- Os três textos ficam numa lista própria, não no `CAMPOS_TEXTO_FICHA`: essa lista vem antes das horas, e estes campos
  vêm depois das notas.
- Os cinco campos entram em `camposDoFormulario({ficha: true})` depois de `notas`, para os 422 ficarem junto ao campo.
- O `FormularioLoja` ganha forma de desativar só a marca, e o `focar` do grupo Sim, Não, Por saber.

### Regras do servidor

- Os cinco campos entram em `CAMPOS` a seguir a `notas`, que passa a 26. Cada booleano tem ramo próprio no `_campo`.
- `marca_nao_revela` em falta ou `null` dá `false` no validador: nunca é `None` em `dados`. `outros_sorbets` em falta ou
  `null` dá `None` (Por saber). Nos dois só conta o booleano JSON (`type(valor) is bool`): `1` e `"true"` dão 422 no
  campo.
- **A marca depende só do pedido e fica no validador**, que acrescenta a chave derivada apenas nestes casos:
  `marca_nao_revela` a `true` leva `marca_atual` a `None`, mesmo que o pedido traga texto; texto na `marca_atual`, depois
  de aparado, sem `marca_nao_revela` a `true` no pedido, passa `marca_nao_revela` a `false`, porque o cliente revelou.
- **Os sorbets dependem da loja gravada e ficam na rota**, depois da comparação da versão e antes de `_valores_novos`,
  como as janelas, e só se o pedido trouxer `outros_sorbets` ou `outros_sorbets_quais`. O estado final é
  `alteracoes.get("outros_sorbets", antes.get("outros_sorbets"))`; se não for `True`, `outros_sorbets_quais` passa a
  `None`. No `criacao`, a mesma regra sobre os dados do pedido.
- As lojas que já existem não têm estes campos e leem-se com `.get`, como o Instagram: sem migração. Na API,
  `marca_nao_revela` sai sempre como `true` ou `false` (`doc.get("marca_nao_revela") is True`).
- `dados_lojas_demo()` passa a trazer `marca_nao_revela: False`. Atualiza-se o "21" nos comentários e docstrings.

## 3. Contactos

Secção "Contactos" na ficha, num cartão próprio, **fora do formulário**: entre os dados da loja e a zona de apagar.
Tem o seu próprio botão de guardar e não depende do Guardar da ficha. As regras ficam num módulo puro,
`lib/crm/contactos.js`, separado do `criarFicha`: o Guardar e o Recarregar da ficha não lhe tocam.

### No ecrã

- O mais recente em cima. Cada contacto mostra o número ("3.º contacto"), a data, o tipo, o resumo e quem o escreveu,
  com "corrigido" se tiver sido alterado.
- A secção tem o estado "A carregar os contactos…". "Adicionar contacto" só fica ativo depois de haver um `hoje` do
  servidor.
- "Adicionar contacto", no topo da secção, abre um bloco dentro da secção, não um diálogo, com a data (hoje), o tipo
  (três pastilhas: Visita, Chamada, Mensagem, com Visita escolhida) e o resumo. O resumo é obrigatório e tem como exemplo
  "O que foi falado e o próximo passo."
- Só há um bloco aberto de cada vez: com um aberto, "Adicionar contacto" e os "Corrigir" ficam desativados.
- A data pode ser passada, para registar contactos antigos, e nunca futura. O "hoje" vem do servidor (a regra do
  `lib/crm/datas.js`: o frontend não lê o relógio do browser para decidir o dia).
- Ao abrir o bloco, volta a pedir-se o `GET` dos contactos, como o diálogo da rota, porque a ficha pode estar aberta
  desde a véspera. O bloco abre logo com o último `hoje` conhecido e Guardar fica desativado até à resposta. A resposta
  atualiza o máximo e, se a pessoa ainda não mexeu na data, a data. Se o pedido falhar, fica o último `hoje` e Guardar
  volta a ativo.
- Quem escreveu um contacto e os administradores do CRM veem "Corrigir" e "Apagar". Apagar pergunta "Apagar este
  contacto?" num `AlertDialog`, com o foco na escolha que não apaga.
- **Foco:** ao abrir o bloco, vai para o resumo. Ao cancelar ou guardar, volta ao botão que o abriu, ou a "Adicionar
  contacto" se ele já não existir. Depois de apagar, vai para "Adicionar contacto".
- **Sucesso:** um toast, "Contacto guardado" ou "Contacto apagado". Com o resumo vazio, Guardar fica desativado e o
  motivo aparece num `aria-live`, como na ficha.
- **Nada do que se escreveu se perde num erro:** se a gravação falhar, o bloco fica aberto com o texto e a mensagem. Sem
  rede, o botão diz "Guardar — sem rede", como na ficha. Se a pessoa mudar o tipo, a data ou o resumo depois de uma
  falha, o bloco gera um `client_uuid` novo; só o reenvio exato usa o mesmo. No pior caso ficam dois contactos e quem
  escreveu apaga um, em vez de se perder texto.
- Se a lista dos contactos não carregar, só esta secção mostra o erro e "Tentar novamente": o resto da ficha funciona.
- Sem contactos: "Ainda sem contactos. Adicione o primeiro."

### Dados

Cada contacto é uma linha em `crm_interacoes`, a coleção que já existe para a linha do tempo de cada loja:

```
{id, loja_id, tipo, resultado: null, notas: <resumo>, paragem_id: null, utilizador_id, ocorrida_em,
 criado_em, editado_em: null, client_uuid}
```

`tipo` é `visita`, `chamada` ou `mensagem`. `TIPOS_CONTACTO` fica em `crm/dominio/contactos.py` e, numa só linha, em
`lib/crm/contactos.js`.

`mensagem` é um tipo novo e uma exceção ao §4.2 do desenho original: também atualiza `ultima_interacao_em` e, na F5, cala
o alerta dos 7 dias. O §5.11 e a tabela de `crm_interacoes` do dossiê atualizam-se na mesma entrega.

Assim, as visitas que o motorista registar na F4 podem aparecer na mesma lista, e a regra de uma loja com histórico não
se apagar já funciona sem mudanças.

### API

Módulo novo `backend/crm/contactos.py`, com `ESCRITORIO` em todas as rotas, classificadas no teste de proteção:

- `GET /lojas/{loja_id}/contactos`
- `POST /lojas/{loja_id}/contactos` com `{tipo, data, resumo, client_uuid?}` → 201
- `PATCH /lojas/{loja_id}/contactos/{contacto_id}` com `{tipo?, data?, resumo?}`
- `DELETE /lojas/{loja_id}/contactos/{contacto_id}`

As quatro devolvem o mesmo: `{hoje, contactos: [{id, numero, tipo, data, resumo, autor, pode_alterar, corrigido}]}`, do
mais recente para o mais antigo. Devolver a lista inteira deixa a numeração só com o servidor, porque um contacto com
data antiga renumera os outros.

### Regras

- **Relógio:** nas escritas, `agora = relogio.agora()` uma vez e `hoje = relogio.hoje(agora)`, para a validação, os
  instantes gravados e a resposta. No GET, `relogio.hoje()`. A resposta leva `hoje` por `datas.texto_data`.
- `data` é `AAAA-MM-DD` (`dominio.datas.ler_data`), entre 2000-01-01 e o `hoje`.
- `resumo` é obrigatório depois de aparado, até 5000 caracteres. Os erros são 422 por campo, como na loja.
- `ocorrida_em` é o instante do pedido se a data for hoje, e as 12:00 de Lisboa desse dia se for outra. Num PATCH que não
  muda a data, fica como estava. Na API, `data` é o dia de Lisboa do `ocorrida_em`.
- **Dois auxiliares em `relogio.py`**, com testes, incluindo o verão às 23:30Z e os dias da mudança de hora:
  `dia_lisboa(instante) -> date` lê só `AAAA-MM-DDTHH:MM:SSZ`, com `[0-9]` e `fullmatch`, e dá `ValueError` no resto;
  `meio_dia_lisboa(dia) -> str` devolve `instante(datetime(a, m, d, 12, tzinfo=FUSO_LISBOA))`. A `data` da API, a
  comparação do PATCH e o `ultimo_contacto` usam `dia_lisboa`, nunca um corte do texto, que daria o dia de UTC.
- A ordem é `ocorrida_em`, `criado_em`, `id`. O número é a posição, com 1 para o mais antigo. Inserir um contacto antigo
  ou apagar um renumera os outros, e isso é o esperado.
- O GET lista só as linhas de `visita`, `chamada` e `mensagem`. A F4 revê esta lista junto com as do recálculo.
- `autor` é o `name` da conta do portal, lido de uma vez com `$in`; se a conta já não existir, "Conta removida". O email
  nunca sai.
- `pode_alterar` é `membro["crm_perfil"] == "admin" or doc["utilizador_id"] == membro["user_id"]`, nunca o `role` do
  portal, e só em linhas com `paragem_id: null`: as outras saem com `pode_alterar: false`.
- **Ordem do PATCH:** corpo (422, sem ler a base; uma chave presente com `null` ou vazio é erro do campo) → loja (404) →
  contacto (404) → permissão (403 `sem_permissao`) → escrita. No DELETE, a mesma, sem o corpo.
- Sem nada a mudar (corpo vazio ou valores iguais), o PATCH responde 200 com a lista, sem escrever e sem `editado_em`.
- Loja que não existe, contacto que não existe, de outra loja ou de um tipo que não seja `visita`, `chamada` ou
  `mensagem`: 404.
- **`client_uuid`:** um uuid4 gerado por cada bloco aberto, com `novoUuid4()` em `ids.js`, que usa `crypto.randomUUID`
  quando existir e, senão, a alternativa do `PosNotaCredito.js`; o módulo dos contactos recebe-a por parâmetro, para os
  testes. No servidor, se vier e não for `null`, tem de passar `ids.e_uuid4`, senão 422 no campo; ausente ou `null`
  grava-se `null`. Antes de gravar faz-se `find_one`, porque o CRM pode arrancar sem índices, e o `DuplicateKeyError` do
  `insert_one` apanha a corrida, como em `membros.py`. Um repetido da mesma loja não cria outra linha: volta a aplicar os
  `$max` da loja com o `tipo` e o `ocorrida_em` da linha já gravada e responde com a lista, como se tivesse corrido bem.
  Um repetido de outra loja dá 422 em `client_uuid`, nunca sucesso.
- **Guardar um contacto não muda a fase da loja.** A fase continua a mudar-se à mão.
- **Não mexe no `atualizado_em` da loja:** a ficha aberta noutro sítio não recebe um conflito falso.

### Último contacto

Os campos `ultima_interacao_em` e `ultima_visita_ou_entrega_em` já existem na loja, a `null`, e passam a escrever-se:

- O POST usa `$max`, porque os instantes ordenam como texto. `ultima_visita_ou_entrega_em` só muda com `visita`.
- O PATCH e o DELETE recalculam a partir das interações, porque a data pode ter recuado. O primeiro campo conta `visita`,
  `chamada`, `mensagem`, `amostra` e `entrega`. O segundo conta `visita`, `amostra` e `entrega` com sucesso, como manda o
  §4.2. Um contacto da ficha (`resultado: null`) conta como sucesso; os resultados de falha só nascem na F4, que os junta
  a esta regra. O recálculo usa `find(…).sort(…).limit(1).to_list(1)`.
- Sem transações, como na `mudanca_fase`: o contacto grava-se primeiro. Se a atualização da loja falhar, fica uma linha
  `[crm]` no registo sem dados pessoais e responde-se com sucesso.

O resumo do `GET /lojas` ganha `localidade`, `consumo_semanal`, `marca_atual`, `marca_nao_revela` e `ultimo_contacto`
(o dia de Lisboa do `ultima_interacao_em`, `AAAA-MM-DD`, ou `null`).

`ultimo_contacto` é calculado, não é um campo da base. `CAMPOS_RESUMO` continua a ser as chaves da API, numa só linha (o
`ecraMapa.test.js` lê-a com um regex), e a `PROJECAO_RESUMO` de `lojas.py` deixa de sair só dele: é `CAMPOS_RESUMO` sem
`ultimo_contacto`, mais `ultima_interacao_em`. O `resumo_loja_api` lê `localidade` com `doc["localidade"]` e os novos com
`.get`.

O cartão do mapa troca "Última ação: ainda sem histórico" por "Último contacto: 5 nov 2026", ou "Ainda sem contactos". A
linha sai de uma função pura em `ecraMapa.js`, com teste, e sai o `TEXTO_ULTIMA_ACAO`.

`rotuloDataCurta(data)` em `datas.js` escreve "5 nov 2026": dia sem zero, lista fixa `MESES_CURTOS` (jan, fev, mar, abr,
mai, jun, jul, ago, set, out, nov, dez), sem `Intl`, e `null` se a data for inválida. Usa-se no cartão, na lista e em
cada contacto.

## Acesso

Administrador e Utilizador do CRM, como o resto do escritório. O perfil `motorista` só entra no terreno na F4, e a app
"Lisbonb RH" continua sem CRM: tudo isto é no browser.

## Privacidade

Os resumos são texto livre e podem ter dados pessoais. A página de Privacidade passa a dizer, em "Dados guardados", que
se guardam o consumo, as marcas, os resumos dos contactos e quem os escreveu. A data da página passa a 7 de novembro de
2026.

Os §3 e §5 da página só falam da relação laboral, e estes dados são de pessoas das lojas. O item do CRM passa a dizer a
finalidade e o prazo de conservação. O texto é legal e o dono do projeto revê-o antes de publicar. Proposta: "Usamos
estes dados para gerir a relação comercial com as lojas. Ficam no CRM enquanto a loja lá estiver, e corrigem-se ou
apagam-se a pedido da pessoa."

## Testes

- **pytest:**
  - O validador dos campos novos, incluindo `1` e `"true"` nos booleanos.
  - O `formatar` e a proteção das rotas.
  - Cada regra dos contactos: permissões, ordem das recusas, PATCH sem mudanças, recálculo do último contacto, loja com
    contactos que não se apaga.
  - A falha entre o `insert_one` e o `$max`, seguida de um reenvio com o mesmo `client_uuid`.
  - Um `GET /lojas` com uma loja com `ultima_interacao_em` preenchido, não só o `resumo_loja_api`.
  - Mudam com o resumo: `test_formatar.py`, a `PROJECAO_RESUMO` escrita à mão no `test_lojas_criar.py`, e as listas fixas
    de campos no `test_dominio_validador_*`.
- **Duplo do Mongo:**
  - `$max` entra no duplo (`_OPERADORES_DE_ATUALIZACAO` e `_aplicar_atualizacao`), com `null` ou campo em falta abaixo de
    texto e outras misturas de tipos a dar `NotImplementedError`, e testes em `test_duplos.py`.
  - Os testes do POST verificam a loja gravada e que não há linha `[crm]`: o `except Exception` da escrita esconderia a
    falha.
  - O repetido testa-se com um documento já guardado e, para a corrida, com `antes_de("insert_one", …)` e
    `falhar={"insert_one": DuplicateKeyError(…)}`, sem mexer em `unicos_declarados`.
  - `$max` e repetido provam-se também em `test_mongo_local.py`.
- **Consistência:** `TIPOS_CONTACTO` comparados em `test_consistencia_frontend.py` com `_listas_do_js`.
- **Jest:**
  - `listaClientes`, com os exemplos da pesquisa.
  - Os contactos, incluindo o `client_uuid` novo depois de uma falha com alterações.
  - O formulário da ficha: marcar e desmarcar, Sim, Não, Sim, com o `camposAlterados` vazio.
  - As diferenças do PATCH com `false` e `null`.
  - `acesso.test.js`: as listas fixas do menu, as páginas lazy e os `ICONES`.
  - O fixture `TRES_LOJAS` do `ecraMapa.test.js`, a `LOJA` do `ficha.test.js` (com `marca_nao_revela: false`) e as listas
    fixas do `formularioLoja.test.js`.
- **No browser, em local:** a lista, a pesquisa, a separação por fase, a ficha e os contactos, no computador e à largura
  de um telemóvel, incluindo recarregar em `/crm/clientes` e ver as cores das pastilhas e das linhas.

## Fora do âmbito

Filtro por região na lista, pesquisa dentro dos resumos, exportar para Excel, ordenar ou somar o consumo, mudanças de
fase na lista de contactos, contactos registados pelo motorista (F4), mudança de fase automática por contacto,
"não quer revelar" nos outros sorbets, a marca no cartão do mapa, e rascunhos guardados ao sair da página.
