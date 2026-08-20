# Pedido guiado no POS — plano de implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.
> Os passos usam `- [ ]` para acompanhamento.

**Spec:** `docs/superpowers/specs/2026-08-20-pedido-guiado-design.md`

**Goal:** ao tocar num açaí, o POS abre um pop-up que conduz o pedido — levar ou comer aqui,
toppings com doses, nome do cliente — e só depois de Gravar é que a linha vai para a conta.

**Arquitectura:** o pedido guiado **não é um ecrã fixo**. É a sequência dos grupos de
personalização do próprio produto, um passo por grupo, pela ordem em que estão atribuídos.
O que decide quais os artigos que o abrem é a atribuição dos grupos no backoffice — não uma
marca no produto nem código. A única peça nova no modelo é o **tipo texto**; o resto sai do
modelo de grupos que já existe (`min_select`/`max_select`, opções com preço).

**Stack:** FastAPI + Motor (Python 3.9.6) · React 19 + Tailwind + shadcn/ui · sem
dependências novas.

## Global Constraints

- **Python 3.9.6** — `Optional[X]`, `Dict`, `List[X]`. Nunca `X | Y`, `match`, `list[str]`.
- **Nada acrescentado ao `backend/server.py`.**
- Colecções com prefixo `fat_`; rotas do POS em `/pos/…` (o `/api/faturacao` vem do
  router-pai).
- **Nenhum teste liga à base de dados nem à rede.** Duplos em memória, como o resto da suite.
- `cd backend && .venv/bin/pytest tests/faturacao -q` — baseline **896 verdes**. **Sem
  `pip install`.** Não existe `timeout` neste macOS.
- Frontend: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` e
  `cd frontend && CI=false yarn build`.
- **Sem dependências novas.** Tokens de design (`--primary`, `--card`, `--warning`,
  `--destructive`…), **nunca cores fixas** — o portal tem modo claro E escuro.
- **PT-PT** em texto visível, comentários e docstrings. Os comentários explicam **porquê** e
  nomeiam o defeito concreto que evitam.
- Todas as chamadas do POS por `frontend/src/lib/pos.js`; as do backoffice por
  `frontend/src/lib/faturacao.js`. O guarda `backend/tests/faturacao/test_caminhos_do_pos.py`
  confronta os dois ficheiros com as rotas reais — **corre-o**.
- **Prova por mutação:** parte a linha que o teste diz proteger, vê-o vermelho pela razão
  certa, desfaz. Neste módulo já aconteceu quatro vezes um teste passar a defender um defeito.

## Estrutura dos ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `backend/faturacao/catalogo.py` (modificar) | `tipo` e `sai_na_fatura` no grupo |
| `backend/faturacao/precos.py` (modificar) | agregar doses no título; respeitar `sai_na_fatura` |
| `backend/faturacao/venda.py` (modificar) | guardar `respostas_texto` e o retrato do `sai_na_fatura` |
| `backend/faturacao/pos_catalogo.py` (modificar) | devolver os campos novos ao POS |
| `backend/faturacao/talao.py` (**criar**) | o texto do pedido da cozinha — puro, sem I/O |
| `frontend/src/pages/pos/PosPedidoGuiado.js` (**criar**) | o pop-up flutuante, um passo por grupo |
| `frontend/src/pages/pos/PosVenda.js` (modificar) | abrir o pop-up; mostrar o pedido na linha |
| `frontend/src/pages/pos/PosDialogoProduto.js` (modificar) | bloco de títulos + "Editar pedido" |
| `frontend/src/pages/admin/faturacao/FatPersonalizacoes.js` (modificar) | tipo e "sai na fatura" |

---

## Task 1: O grupo ganha tipo e "sai na fatura"

**Files:**
- Modify: `backend/faturacao/catalogo.py` (`GrupoPersonalizacaoEntrada`)
- Test: `backend/tests/faturacao/test_catalogo.py`

**Interfaces:**
- Produces: `GrupoPersonalizacaoEntrada.tipo: str` (`"opcoes"` | `"texto"`, omissão
  `"opcoes"`) e `.sai_na_fatura: bool` (omissão `True`). Constante
  `catalogo.TIPOS_DE_GRUPO = frozenset({"opcoes", "texto"})`.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_grupo_de_texto_nao_precisa_de_opcoes():
    """Um grupo 'Nome' não tem opções nenhumas — o validador do mínimo, que
    compara min_select com len(opcoes), não se pode aplicar-lhe."""
    g = GrupoPersonalizacaoEntrada(nome="Nome", tipo="texto", min_select=1, opcoes=[])
    assert g.tipo == "texto"
    assert g.sai_na_fatura is True


def test_grupo_recusa_tipo_desconhecido():
    with pytest.raises(ValidationError):
        GrupoPersonalizacaoEntrada(nome="Nome", tipo="livre")


def test_grupo_de_opcoes_continua_a_recusar_minimo_maior_que_as_opcoes():
    """A guarda de sempre não pode ter sido desligada para todos ao ser
    desligada para o tipo texto."""
    with pytest.raises(ValidationError):
        GrupoPersonalizacaoEntrada(
            nome="Tamanho", min_select=3,
            opcoes=[{"nome": "Pequeno"}, {"nome": "Grande"}],
        )
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_catalogo.py -q -k grupo_de_texto`
Esperado: FAIL — `ValidationError` por `tipo` não existir.

- [ ] **Passo 3: implementar**

Em `catalogo.py`, antes de `GrupoPersonalizacaoEntrada`:

```python
# Um grupo é uma lista de opções (o de sempre) ou um campo de texto livre.
# O texto nasceu do "Nome" que se escreve no copo do açaí: é a única coisa
# do pedido guiado que não é uma escolha entre alternativas.
TIPOS_DE_GRUPO = frozenset({"opcoes", "texto"})
```

E no modelo:

```python
    tipo: str = "opcoes"
    # Se as escolhas deste grupo entram no título da linha da Fatura
    # Simplificada. Liga-se nos toppings (que descrevem o produto e mudam o
    # preço) e desliga-se no Nome e no "Consumir na loja", que são para a
    # cozinha. Ver `precos.linha_de_venda`: uma opção PAGA sai na fatura de
    # qualquer maneira — este interruptor esconde o que não custa nada,
    # nunca um euro.
    sai_na_fatura: bool = True

    @field_validator("tipo")
    @classmethod
    def _valida_tipo(cls, v):
        if v not in TIPOS_DE_GRUPO:
            raise ValueError(
                "Tipo de grupo desconhecido: '%s'. Use um destes: %s"
                % (v, ", ".join(sorted(TIPOS_DE_GRUPO)))
            )
        return v
```

E no `_valida_selecao`, os dois `raise` do mínimo passam a correr só para `opcoes`:

```python
    @model_validator(mode="after")
    def _valida_selecao(self):
        # Um grupo de TEXTO não tem opções: `min_select >= 1` quer dizer
        # "resposta obrigatória", e comparar isso com len(opcoes) recusava
        # sempre um Nome obrigatório. As duas guardas abaixo são sobre
        # escolher de uma lista, e só a essa se aplicam.
        if self.tipo != "opcoes":
            return self
        if self.max_select > 0 and self.min_select > self.max_select:
            raise ValueError(
                "O mínimo de escolhas (%d) não pode ser maior do que o máximo (%d)."
                % (self.min_select, self.max_select)
            )
        if self.min_select > len(self.opcoes):
            raise ValueError(
                "O mínimo de escolhas (%d) não pode ser maior do que o número de opções "
                "do grupo (%d)." % (self.min_select, len(self.opcoes))
            )
        return self
```

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS, 899 verdes.

- [ ] **Passo 5: mutação**

Apaga `if self.tipo != "opcoes": return self`.
Esperado: `test_grupo_de_texto_nao_precisa_de_opcoes` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/catalogo.py backend/tests/faturacao/test_catalogo.py
git commit -m "Catálogo: um grupo de personalização pode ser texto livre"
```

---

## Task 2: Doses no título, e o que fica de fora da fatura

**Files:**
- Modify: `backend/faturacao/precos.py` (`linha_de_venda`)
- Test: `backend/tests/faturacao/test_precos.py`

**Interfaces:**
- Consumes: `sai_na_fatura` da Task 1, que chega em cada opção como
  `opcao["sai_na_fatura"]` (retrato gravado pela Task 3).
- Produces: título agregado — `"Açaí Small (Nutella 2×, Morango)"`.

**Contexto:** `linha_de_venda` recebe `opcoes` como lista simples, e a **repetição já
significa dose** (`extra = sum(...)` soma cada entrada). O que muda é só o TÍTULO.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_opcao_repetida_aparece_com_a_dose_no_titulo():
    nutella = {"nome": "Nutella", "preco": 0.95}
    linha = linha_de_venda({"nome": "Açaí Small", "preco": 7.20, "tax_id": "INT"},
                           1, [nutella, nutella, {"nome": "Morango", "preco": 0}])
    assert linha["title"] == "Açaí Small (Nutella 2×, Morango)"
    # duas doses pagas: 7,20 + 0,95 + 0,95
    assert linha["gross_price"] == 9.10


def test_a_ordem_do_titulo_e_a_da_primeira_escolha():
    """Agregar não pode reordenar: a operadora escolheu por uma ordem e o
    cliente lê essa ordem no talão."""
    a = {"nome": "Morango", "preco": 0}
    b = {"nome": "Nutella", "preco": 0.95}
    linha = linha_de_venda({"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1, [a, b, a])
    assert linha["title"] == "Açaí (Morango 2×, Nutella)"


def test_opcao_gratuita_de_grupo_escondido_nao_vai_ao_titulo():
    linha = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1,
        [{"nome": "Levar", "preco": 0, "sai_na_fatura": False},
         {"nome": "Nutella", "preco": 0.95}],
    )
    assert linha["title"] == "Açaí (Nutella)"
    assert linha["gross_price"] == 5.95


def test_opcao_PAGA_vai_ao_titulo_mesmo_com_o_interruptor_desligado():
    """O interruptor esconde o que não custa nada. Nunca um euro: o cliente
    está a ser cobrado por isto e a fatura tem de o dizer."""
    linha = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1,
        [{"nome": "Whey", "preco": 0.95, "sai_na_fatura": False}],
    )
    assert linha["title"] == "Açaí (Whey)"
    assert linha["gross_price"] == 5.95
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_precos.py -q -k dose`
Esperado: FAIL — `"Açaí Small (Nutella, Nutella, Morango)" != "Açaí Small (Nutella 2×, Morango)"`.

- [ ] **Passo 3: implementar**

Em `precos.py`, substituir o bloco do título:

```python
    titulo = produto.get("nome", "Produto")
    nomes = [o.get("nome") for o in opcoes if o.get("nome")]
    if nomes:
        titulo = "%s (%s)" % (titulo, ", ".join(nomes))
```

por:

```python
    titulo = produto.get("nome", "Produto")
    descricao = _descricao_das_opcoes(opcoes)
    if descricao:
        titulo = "%s (%s)" % (titulo, descricao)
```

E acrescentar, acima de `linha_de_venda`:

```python
def _descricao_das_opcoes(opcoes: List[Dict]) -> str:
    """As opções como saem no título da linha: "Nutella 2×, Morango".

    Duas regras, e as duas nasceram de uma decisão do dono:

    - **As repetições agregam-se.** Cada toque na Nutella junta uma dose e
      cobra outra vez; escrever "Nutella, Nutella, Nutella" no talão do
      cliente é a mesma informação, ilegível. A ORDEM é a da primeira
      escolha — agregar não pode reordenar, porque a operadora escolheu por
      uma ordem e é essa que o cliente lê.
    - **Um grupo com `sai_na_fatura` desligado não aparece.** É o caso do
      "Nome" (que é do copo) e do "Consumir na loja" (que é da cozinha):
      não descrevem o produto e não têm valor fiscal.

    A excepção que não se negoceia: **uma opção PAGA aparece sempre**,
    esteja o interruptor como estiver. O cliente está a ser cobrado por ela
    e a fatura tem de o dizer — o interruptor esconde o que não custa nada,
    nunca um euro. Sem esta linha, desligar o interruptor por engano num
    grupo de toppings escondia da fatura o que lá foi cobrado.
    """
    contagem = {}   # nome -> doses
    ordem = []      # os nomes pela ordem da primeira escolha
    for o in opcoes:
        nome = o.get("nome")
        if not nome:
            continue
        pago = float(o.get("preco", 0) or 0) > 0
        if not pago and o.get("sai_na_fatura") is False:
            continue
        if nome not in contagem:
            ordem.append(nome)
            contagem[nome] = 0
        contagem[nome] += 1
    return ", ".join(
        nome if contagem[nome] == 1 else "%s %d×" % (nome, contagem[nome])
        for nome in ordem
    )
```

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS. **Se algum teste de PREÇO mudar de valor, pára** — esta task não toca em
dinheiro, só no texto do título.

- [ ] **Passo 5: mutação**

Troca `if not pago and o.get("sai_na_fatura") is False:` por
`if o.get("sai_na_fatura") is False:`.
Esperado: `test_opcao_PAGA_vai_ao_titulo_mesmo_com_o_interruptor_desligado` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/precos.py backend/tests/faturacao/test_precos.py
git commit -m "Preços: doses agregadas no título, e o que não custa nada pode ficar fora"
```

---

## Task 3: A linha guarda o pedido

**Files:**
- Modify: `backend/faturacao/venda.py` (`PedidoJuntarLinha`, `PedidoEditarLinha`,
  `juntar_linha`)
- Test: `backend/tests/faturacao/test_venda.py`

**Interfaces:**
- Consumes: `sai_na_fatura` (Task 1).
- Produces: na linha gravada, `opcoes[i]["sai_na_fatura"]` (retrato) e
  `linha["respostas_texto"] = [{"grupo_id", "nome_grupo", "texto"}]`.

**Antes de escrever os testes:** lê o topo do `test_venda.py` e usa os ajudantes e as
fixtures que já lá estão (`_db`, `_corre`, e as constantes de venda/produto). Os nomes
usados nos exemplos abaixo são os do ficheiro — se algum não bater, **usa o que existe** em
vez de criares um paralelo.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_juntar_linha_guarda_as_respostas_de_texto(monkeypatch):
    # `_db(...)` é o ajudante que este ficheiro já tem (test_venda.py:159) —
    # aceita `vendas`, `produtos`, `caixas`, `sessoes`. NÃO inventes outro.
    registo = []
    db = _db(registo, vendas=[_VENDA_ABERTA], produtos=[_PRODUTO_OK])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    r = _corre(venda.juntar_linha("v1", venda.PedidoJuntarLinha(
        produto_id="p1", quantidade=1,
        respostas_texto=[{"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"}],
    ), operador=_OPERADOR))
    assert r["linhas"][0]["respostas_texto"] == [
        {"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"}
    ]


def test_juntar_linha_carimba_o_sai_na_fatura_de_cada_opcao(monkeypatch):
    """Retrato, pela mesma razão que o preço: o gestor pode desligar o
    interruptor amanhã, e o que saiu no papel não muda."""
    registo = []
    db = _db(registo, vendas=[_VENDA_ABERTA], produtos=[_PRODUTO_OK])
    # O grupo tem de existir na colecção que o `juntar_linha` vai consultar
    # para tirar o retrato do `sai_na_fatura`.
    db["fat_grupos_personalizacao"] = _coleccao([
        {"id": "g1", "nome": "Consumir na loja", "sai_na_fatura": False,
         "opcoes": [{"id": "o1", "nome": "Levar", "preco": 0}]},
    ])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    r = _corre(venda.juntar_linha("v1", venda.PedidoJuntarLinha(
        produto_id="p1", quantidade=1,
        opcoes=[{"id": "o1", "grupo_id": "g1", "nome": "Levar", "preco": 0}],
    ), operador=_OPERADOR))
    assert r["linhas"][0]["opcoes"][0]["sai_na_fatura"] is False
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_venda.py -q -k respostas_de_texto`
Esperado: FAIL — `PedidoJuntarLinha` não aceita `respostas_texto`.

- [ ] **Passo 3: implementar**

Em `venda.py`, acrescentar o modelo da resposta e o campo nos dois pedidos:

```python
class RespostaTexto(BaseModel):
    """A resposta a um grupo de tipo texto — hoje, o nome que se escreve no
    copo. Guarda-se também o `nome_grupo` (um retrato, como o `produto_nome`)
    para o talão da cozinha poder ser lido daqui a um mês sem ir buscar o
    grupo, que pode ter mudado de nome ou desaparecido."""

    grupo_id: str = Field(min_length=1)
    nome_grupo: Optional[str] = None
    texto: str = Field(max_length=120)
```

`PedidoJuntarLinha` e `PedidoEditarLinha` ganham:

```python
    respostas_texto: List[RespostaTexto] = Field(default_factory=list)   # juntar
    respostas_texto: Optional[List[RespostaTexto]] = None                # editar
```

E em `juntar_linha`, ANTES de montar a `linha`, carimbar o `sai_na_fatura` em cada opção:

```python
    # Retrato do `sai_na_fatura` do grupo no momento da escolha, pela mesma
    # razão que a linha já guarda `produto_preco`: o gestor pode desligar o
    # interruptor amanhã, e o que saiu no papel não muda. Sem isto, o título
    # de uma fatura reimpressa mudava consoante a configuração de hoje.
    grupos_da_linha = {}
    ids = [o.get("grupo_id") for o in dados.opcoes if o.get("grupo_id")]
    if ids:
        for g in await db[COLECOES["grupos_personalizacao"]].find(
            {"id": {"$in": ids}}, {"_id": 0, "id": 1, "sai_na_fatura": 1}
        ).to_list(len(ids)):
            grupos_da_linha[g["id"]] = g.get("sai_na_fatura", True)

    opcoes = []
    for o in dados.opcoes:
        o = dict(o)
        o["sai_na_fatura"] = grupos_da_linha.get(o.get("grupo_id"), True)
        opcoes.append(o)
```

e a `linha` passa a levar `"opcoes": opcoes` e
`"respostas_texto": [r.model_dump() for r in dados.respostas_texto]`.

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS.

- [ ] **Passo 5: mutação**

Troca `grupos_da_linha.get(o.get("grupo_id"), True)` por `True`.
Esperado: `test_juntar_linha_carimba_o_sai_na_fatura_de_cada_opcao` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/venda.py backend/tests/faturacao/test_venda.py
git commit -m "Venda: a linha guarda as respostas de texto e o retrato do sai-na-fatura"
```

---

## Task 4: O POS recebe os campos novos

**Files:**
- Modify: `backend/faturacao/pos_catalogo.py` (`_grupo_publico`)
- Test: `backend/tests/faturacao/test_pos_catalogo.py`

**Interfaces:**
- Produces: cada grupo em `GET /pos/catalogo` passa a trazer `tipo` e `sai_na_fatura`.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_o_catalogo_do_pos_diz_o_tipo_e_o_sai_na_fatura_do_grupo(monkeypatch):
    db = _db({"fat_grupos_personalizacao": [
        {"id": "g1", "nome": "Nome", "tipo": "texto", "sai_na_fatura": False,
         "min_select": 0, "max_select": 0, "opcoes": [], "ativo": True},
    ]})
    monkeypatch.setattr(pos_catalogo, "obter_db", lambda: db)
    r = _corre(pos_catalogo.catalogo_do_pos(_={}))
    g = r["grupos_personalizacao"][0]
    assert g["tipo"] == "texto"
    assert g["sai_na_fatura"] is False


def test_um_grupo_antigo_sem_os_campos_vale_como_lista_que_sai_na_fatura(monkeypatch):
    """Os grupos gravados antes desta alteração não têm os campos. O POS não
    pode rebentar por causa disso, e o valor por omissão tem de ser o
    comportamento de sempre."""
    db = _db({"fat_grupos_personalizacao": [
        {"id": "g1", "nome": "Toppings", "min_select": 0, "max_select": 0,
         "opcoes": [], "ativo": True},
    ]})
    monkeypatch.setattr(pos_catalogo, "obter_db", lambda: db)
    g = _corre(pos_catalogo.catalogo_do_pos(_={}))["grupos_personalizacao"][0]
    assert g["tipo"] == "opcoes"
    assert g["sai_na_fatura"] is True
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_pos_catalogo.py -q -k tipo_e_o_sai`
Esperado: FAIL — `KeyError: 'tipo'`.

- [ ] **Passo 3: implementar**

Em `_grupo_publico`, acrescentar ao dicionário devolvido:

```python
        # Um grupo gravado antes destes campos existirem vale como o que
        # sempre foi: uma lista de opções que sai na fatura. Os `.get` com
        # omissão são o que impede o POS de rebentar num catálogo antigo.
        "tipo": grupo.get("tipo", "opcoes"),
        "sai_na_fatura": grupo.get("sai_na_fatura", True),
```

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS.

- [ ] **Passo 5: mutação**

Troca `grupo.get("tipo", "opcoes")` por `grupo["tipo"]`.
Esperado: `test_um_grupo_antigo_sem_os_campos…` vermelho com `KeyError`. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/pos_catalogo.py backend/tests/faturacao/test_pos_catalogo.py
git commit -m "POS: o catálogo diz o tipo e o sai-na-fatura de cada grupo"
```

---

## Task 5: O texto do pedido da cozinha

**Files:**
- Create: `backend/faturacao/talao.py`
- Test: `backend/tests/faturacao/test_talao.py`

**Interfaces:**
- Produces: `talao.pedido_da_cozinha(venda: Dict) -> str`.

**Contexto:** função **pura**, sem I/O — recebe a venda como `_venda_publica` a devolve. O
agente de impressão (Plano 3) não existe; isto constrói o texto agora para sair em papel
sem se mexer em mais nada quando ele existir.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_o_pedido_sai_no_formato_que_o_dono_escreveu():
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria"}],
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0},
            {"id": "o1", "grupo_id": "g2", "nome": "Leite condensado", "preco": 0},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
        ],
    }]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n"
        "\n"
        "1 Açaí Small — MARIA\n"
        "Levar\n"
        "\n"
        "1x Leite condensado\n"
        "2x Nutella\n"
    )


def test_uma_linha_sem_nome_nem_opcoes_sai_na_mesma():
    venda = {"linhas": [{"produto_nome": "Café Expresso", "quantidade": 2}]}
    assert pedido_da_cozinha(venda) == "Pedido\n\n2 Café Expresso\n"


def test_duas_linhas_ficam_separadas():
    venda = {"linhas": [
        {"produto_nome": "Café Expresso", "quantidade": 1},
        {"produto_nome": "Água 50cl", "quantidade": 1},
    ]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n\n1 Café Expresso\n\n1 Água 50cl\n"
    )
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_talao.py -q`
Esperado: FAIL — `ModuleNotFoundError: faturacao.talao`.

- [ ] **Passo 3: implementar**

```python
"""O texto do pedido que vai para a cozinha.

Puro e sem I/O de propósito: recebe a venda tal como `venda._venda_publica`
a devolve e produz texto. O agente de impressão (Plano 3) ainda não existe —
quando existir, é este texto que sai em papel, sem se mexer aqui.

O formato é o que o dono escreveu, e cada linha dele tem uma razão: o NOME em
maiúsculas na linha do artigo porque é o que se escreve no copo e é o que a
pessoa da cozinha procura primeiro; o serviço (levar/comer aqui) logo a
seguir porque muda o que ela faz com o copo; e as doses à frente do topping
porque "2x Nutella" lê-se de relance e "Nutella, Nutella" não.
"""
from typing import Dict, List


def _doses(opcoes: List[Dict]) -> List[str]:
    """As opções agregadas, pela ordem da primeira escolha. Mesma regra do
    título da fatura (`precos._descricao_das_opcoes`), outro formato: aqui a
    dose vem À FRENTE, que é como uma ficha de cozinha se lê."""
    contagem = {}
    ordem = []
    for o in opcoes or []:
        nome = o.get("nome")
        if not nome:
            continue
        if nome not in contagem:
            ordem.append(nome)
            contagem[nome] = 0
        contagem[nome] += 1
    return ["%dx %s" % (contagem[n], n) for n in ordem]


def _nome_no_copo(linha: Dict) -> str:
    """A PRIMEIRA resposta de texto da linha. Convenção, não configuração:
    quem põe um grupo de texto num açaí está a pedir o nome do cliente, e um
    ajuste por grupo para dizer onde é que cada resposta aparece no talão
    seria uma definição a mais para o mesmo resultado."""
    for r in linha.get("respostas_texto") or []:
        texto = (r.get("texto") or "").strip()
        if texto:
            return texto
    return ""


def pedido_da_cozinha(venda: Dict) -> str:
    partes = ["Pedido\n"]
    for linha in venda.get("linhas") or []:
        nome = _nome_no_copo(linha)
        cabecalho = "%d %s" % (linha.get("quantidade", 1), linha.get("produto_nome") or "?")
        if nome:
            cabecalho += " — %s" % nome.upper()
        bloco = [cabecalho]

        # As opções SEM preço de grupos que não vão à fatura são as
        # indicações de serviço (Levar / Comer aqui): vão logo por baixo do
        # artigo, sem dose, porque só há uma.
        servico = [o.get("nome") for o in (linha.get("opcoes") or [])
                   if o.get("sai_na_fatura") is False and o.get("nome")]
        bloco.extend(dict.fromkeys(servico))

        toppings = _doses([o for o in (linha.get("opcoes") or [])
                           if o.get("sai_na_fatura") is not False])
        if toppings:
            bloco.append("")
            bloco.extend(toppings)
        partes.append("\n".join(bloco) + "\n")
    return "\n".join(partes)
```

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_talao.py -q`
Esperado: PASS, 3 testes.

- [ ] **Passo 5: mutação**

Em `_doses`, troca `"%dx %s"` por `"%s"`.
Esperado: `test_o_pedido_sai_no_formato_que_o_dono_escreveu` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/talao.py backend/tests/faturacao/test_talao.py
git commit -m "Faturação: o texto do pedido da cozinha"
```

---

## Task 6: O pop-up do pedido guiado

**Files:**
- Create: `frontend/src/pages/pos/PosPedidoGuiado.js`
- Modify: `frontend/src/pages/pos/PosVenda.js`

**Interfaces:**
- Consumes: `grupo.tipo` e `grupo.sai_na_fatura` (Task 4); `PosPersonalizacoes`
  (`errosDeSelecao`, `resumoDaSelecao`).
- Produces:

```jsx
<PosPedidoGuiado
  produto={produto}
  grupos={grupos}              // só os deste produto, do catálogo
  linha={null}                 // ou a linha, quando se está a editar
  aGravar={false}
  onGravar={({ opcoes, respostas_texto }) => {}}
  onFechar={() => {}}
/>
```

- [ ] **Passo 1: o componente**

Um `Dialog` do shadcn (`components/ui/dialog`) — **flutuante e ao centro**, não o painel
direito: a grelha e a conta ficam à vista por trás, e a operadora vê o que já picou
enquanto monta o pedido.

Um passo por grupo, pela ordem em que vêm no produto. Cabeçalho com o **título do grupo** e
o passo (`2 de 3`). Regras por tipo:

- **`opcoes`** — botões grandes; cada toque **soma uma dose** e mostra o contador (`2×`);
  **carregar 2 segundos apaga** aquela opção por inteiro. O carregar-longo tem de se ver a
  acontecer (um anel a encher, ou o botão a esmorecer): ninguém adivinha um gesto invisível,
  e sem sinal ela solta antes dos 2s e conclui que não funciona.

  **O `max_select` conta OPÇÕES DIFERENTES, nunca doses.** Nos toppings do açaí não há
  máximo nenhum (`max_select: 0`) e o cliente pede o que quiser — mas o "Consumir na loja"
  tem `max_select: 1`, e aí escolher *Comer aqui* **substitui** *Levar* em vez de somar,
  porque são alternativas e não doses. Sem esta distinção, ou o açaí ficava limitado a três
  colheres, ou o serviço deixava escolher os dois ao mesmo tempo — os dois estão errados.
  Três doses de Nutella nunca esgotam um máximo.

  O mínimo (`min_select >= 1`), se o gestor o tiver posto, continua a valer e impede o
  avanço; conta opções diferentes, pela mesma razão.
- **`texto`** — um `Input` grande com o título do grupo por cima. `min_select >= 1` torna-o
  obrigatório; a omissão (0) deixa avançar em branco.

Rodapé: **Anterior** / **Seguinte**, e no último passo **Gravar**. Fechar sem gravar não põe
nada na conta.

- [ ] **Passo 2: ligar no `PosVenda.js`**

`tocarProduto` passa a decidir:

```js
// Um produto COM grupos abre o pedido guiado; sem grupos vai direito para a
// conta, como sempre foi. É a atribuição dos grupos no backoffice — e nada
// no código — que decide quais os artigos que abrem a conversa ao balcão.
const grupos = gruposDoProduto(produto);
if (grupos.length > 0) { setPedidoGuiado({ produto, grupos, linha: null }); return; }
```

- [ ] **Passo 3: a linha na conta**

Por baixo do nome do produto, em pequeno: `Levar · Maria` e `Nutella 2× · Leite condensado 1×`.
É o que a operadora confere com o cliente antes de finalizar.

- [ ] **Passo 4: compilar**

Comando: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd frontend && CI=false yarn build`
Esperado: `Compiled with warnings` (os 15 avisos pré-existentes de `AuthContext.js` e
`admin/*`), **nenhum em `pos/`**.

- [ ] **Passo 5: percorrer no browser**

Há um servidor de mentira pronto em
`.../scratchpad/pos-mock.js` (serve o build e responde à API do POS). **Compila com
`REACT_APP_BACKEND_URL=` vazio**, senão o build aponta para produção (o `.env.production` é
versionado por causa da app Capacitor). Semeia o `localStorage`
(`pos_device_token`, `pos_loja_id`, `pos_loja_nome`, `pos_operator_token`, `pos_operador`,
`pos_caixa_id`), acrescenta ao duplo um açaí com os três grupos, e percorre: tocar → serviço
→ dois toques na Nutella → carregar 2s para apagar → nome → Gravar → a linha na conta com
tudo. **Mata o servidor no fim.**

- [ ] **Passo 6: commit**

```bash
git add frontend/src/pages/pos/PosPedidoGuiado.js frontend/src/pages/pos/PosVenda.js
git commit -m "POS: o pedido guiado, feito com as personalizações do produto"
```

---

## Task 7: Corrigir uma linha já gravada

**Files:**
- Modify: `frontend/src/pages/pos/PosDialogoProduto.js`
- Modify: `frontend/src/pages/pos/PosVenda.js`

- [ ] **Passo 1: o bloco de títulos**

No topo do diálogo do produto, um bloco só de leitura:

> **Serviço** Levar · **Nome** Maria · **Personalizações** Nutella 2×, Leite condensado 1×
> `[ Editar pedido ]`

- [ ] **Passo 2: o botão reabre o pop-up**

`onEditarPedido` volta a `PosPedidoGuiado` com a `linha` preenchida. Ao gravar, a linha é
actualizada (`editarLinha`), não criada.

**Porque não se volta directamente ao pop-up ao tocar na linha:** corrigir "esqueci-me da
Nutella" acontece muitas vezes ao dia, mas dar um desconto naquela linha também — e se o
caminho de correcção escondesse o desconto, a operadora ficava sem saída sem apagar a linha
e picar tudo de novo.

- [ ] **Passo 3: compilar e percorrer**

Mesmo servidor de mentira. Editar uma linha guiada: mudar a Nutella de 2 para 3, mudar o
nome, gravar, e confirmar que o **desconto e o preço continuam acessíveis** no mesmo ecrã.

- [ ] **Passo 4: commit**

```bash
git add frontend/src/pages/pos/PosDialogoProduto.js frontend/src/pages/pos/PosVenda.js
git commit -m "POS: corrigir um pedido guiado sem perder o desconto da linha"
```

---

## Task 8: O backoffice cria os grupos

**Files:**
- Modify: `frontend/src/pages/admin/faturacao/FatPersonalizacoes.js`

- [ ] **Passo 1: o tipo**

No diálogo do grupo, um selector **Tipo**: *Lista de opções* · *Texto livre*, com uma frase a
dizer o que cada um faz ao balcão. Escolhido *Texto livre*, a lista de opções **desaparece**
(um grupo de texto não tem opções) e o mínimo passa a ler-se como *"resposta obrigatória"*.

- [ ] **Passo 2: o "sai na fatura"**

Um interruptor com a frase: *"As escolhas deste grupo aparecem na fatura do cliente. Desligue
num grupo que seja só para a cozinha — o nome no copo, ou levar/comer aqui."* E por baixo, em
pequeno: *"Uma opção paga aparece sempre, mesmo com isto desligado."*

- [ ] **Passo 3: compilar**

Comando: `cd frontend && CI=false yarn build` — limpo.

- [ ] **Passo 4: correr o guarda dos caminhos**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_caminhos_do_pos.py -q`
Esperado: PASS — nenhuma chamada nova órfã.

- [ ] **Passo 5: commit**

```bash
git add frontend/src/pages/admin/faturacao/FatPersonalizacoes.js
git commit -m "Backoffice: grupos de texto livre e o interruptor de sair na fatura"
```

---

## Verificação final

- [ ] Suite verde (esperado ~910) e `CI=false yarn build` limpo
- [ ] **O dono consegue, sozinho:** criar os três grupos, atribuí-los ao Açaí Small, e ver o
      pedido guiado abrir ao balcão — sem tocar em código nem chamar ninguém
- [ ] Um produto **sem** grupos continua a ir para a conta com um toque
- [ ] A fatura mostra `(Nutella 2×)` e **não** mostra o nome nem o levar/comer aqui
- [ ] Uma opção **paga** aparece na fatura mesmo com o interruptor desligado
- [ ] Uma conta aberta **antes** desta alteração continua a faturar (linhas sem os campos novos)
- [ ] O texto do pedido da cozinha bate com o formato que o dono escreveu
