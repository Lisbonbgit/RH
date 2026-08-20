# Dividir e separar a conta — plano de implementação

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.
> Os passos usam `- [ ]` para acompanhamento.

**Spec:** `docs/superpowers/specs/2026-08-20-dividir-separar-conta-design.md`

**Goal:** três amigos levam dois açaís e uma Coca-Cola; ou dividem a conta por igual, ou cada
um paga o que consumiu — e **cada um leva a sua Fatura Simplificada**.

**Arquitectura:** cada parte é uma **venda normal**. Dividir ou separar cria contas-filhas a
partir da conta-mãe, e daí em diante cada uma tem a sua referência determinística, a sua
reserva atómica e a sua idempotência. **Nada muda em `precos.linha_de_venda`, `fiscal.py` ou
`caixa_math`** — é isso que mantém intacto o núcleo onde esta semana se encontraram os
defeitos mais caros.

**Stack:** FastAPI + Motor (Python 3.9.6) · React 19 + Tailwind + shadcn/ui · sem
dependências novas.

## Global Constraints

- **Python 3.9.6** — `Optional[X]`, `Dict`, `List[X]`. Nunca `X | Y`, `match`, `list[str]`.
- **Nada acrescentado ao `backend/server.py`.**
- Colecções com prefixo `fat_`; rotas do POS em `/pos/…`.
- **Nenhum teste liga à base de dados nem à rede.** Duplos em memória.
- `cd backend && .venv/bin/pytest tests/faturacao -q` — baseline **918 verdes**. **Sem
  `pip install`.** Não existe `timeout` neste macOS.
- Frontend: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` e
  `cd frontend && CI=false yarn build`.
- **Sem dependências novas.** Tokens de design, **nunca cores fixas**.
- **PT-PT** em texto visível, comentários e docstrings, e explicam **porquê**.
- **O dinheiro conta-se em CÊNTIMOS (inteiros), nunca em vírgula flutuante.** É a regra
  central deste plano.
- **O crivo das 2 casas decimais nos PREÇOS fica intocado**
  (`precos._tem_mais_de_2_casas_decimais`). Só a *quantidade* ganha casas.
- **Prova por mutação:** parte a linha que o teste diz proteger, vê-o vermelho pela razão
  certa, desfaz. Neste módulo já aconteceu **cinco vezes** um teste passar a defender um
  defeito.

## Estrutura dos ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `backend/faturacao/reparticao.py` (**criar**) | a matemática dos cêntimos — pura, sem I/O |
| `backend/faturacao/venda.py` (modificar) | quantidade decimal; rotas de dividir e separar |
| `backend/faturacao/db.py` (modificar) | índice de `conta_mae_id` |
| `frontend/src/lib/pos.js` (modificar) | os dois wrappers novos |
| `frontend/src/pages/pos/PosReparticao.js` (**criar**) | o ecrã de dividir/separar |
| `frontend/src/pages/pos/PosFinalizar.js` (modificar) | os dois botões e o cartão |
| `frontend/src/pages/pos/PosVenda.js` (modificar) | passar entre as partes |

---

## Task 1: A matemática dos cêntimos

**Files:**
- Create: `backend/faturacao/reparticao.py`
- Test: `backend/tests/faturacao/test_reparticao.py`

**Interfaces:**
- Produces:
  - `reparticao.repartir_centimos(total_centimos: int, partes: int) -> List[int]`
  - `reparticao.quantidade_para(valor_centimos: int, preco: float) -> float`

**Contexto:** é o coração deste plano e é **puro** — sem base de dados, sem rede, sem
Pydantic. Tudo o resto se apoia nisto.

Medido contra a conta Vendus real, com um Açaí Regular de 8,99 € por três: `qty 0.333`
factura 2,99 (três somam 8,97) e `qty 0.3333` factura 3,00 (três somam 9,00). **Nenhuma dá
8,99** — mandar a mesma fracção a toda a gente declara à AT um valor diferente do que entrou
na gaveta.

- [ ] **Passo 1: escrever o teste que falha**

```python
import pytest
from faturacao.reparticao import quantidade_para, repartir_centimos


def test_as_partes_somam_sempre_o_total():
    """A regra que não se negoceia. Sem ela, as faturas de uma conta
    dividida declaram à AT um valor diferente do que entrou na gaveta."""
    for total in range(1, 400):
        for n in range(1, 8):
            partes = repartir_centimos(total, n)
            assert sum(partes) == total, (total, n, partes)
            assert len(partes) == n


def test_o_centimo_que_sobra_vai_para_as_primeiras():
    # 899 cêntimos por três: 300, 300, 299 — nunca mais de um cêntimo de
    # diferença entre duas pessoas.
    assert repartir_centimos(899, 3) == [300, 300, 299]
    assert repartir_centimos(1000, 3) == [334, 333, 333]
    assert repartir_centimos(10, 4) == [3, 3, 2, 2]


def test_divisao_exacta_nao_inventa_diferencas():
    assert repartir_centimos(900, 3) == [300, 300, 300]


def test_uma_parte_leva_tudo():
    assert repartir_centimos(899, 1) == [899]


def test_zero_partes_e_recusado():
    with pytest.raises(ValueError):
        repartir_centimos(899, 0)


def test_a_quantidade_reproduz_o_valor_ao_centimo():
    """O que interessa não é a fracção bonita — é que `qty × preço`,
    arredondado como o Vendus arredonda, dê EXACTAMENTE o valor da parte."""
    for centimos in (300, 299, 1, 899):
        q = quantidade_para(centimos, 8.99)
        assert round(q * 8.99, 2) == centimos / 100


def test_a_quantidade_de_um_preco_zero_e_recusada():
    """Um preço zero não produz valor nenhum: não há quantidade que o
    resolva, e devolver 0 escondia o problema numa fatura."""
    with pytest.raises(ValueError):
        quantidade_para(300, 0)
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_reparticao.py -q`
Esperado: FAIL — `ModuleNotFoundError: faturacao.reparticao`.

- [ ] **Passo 3: implementar**

```python
"""A matemática de repartir uma conta — pura, sem I/O.

Tudo aqui se conta em **cêntimos inteiros**, nunca em vírgula flutuante. É a
mesma razão que está no cabeçalho de `precos.py`: `round()` sobre a
representação binária come cêntimos sem avisar. Numa conta dividida isso não
é um arredondamento infeliz — é a soma das faturas a declarar à AT um valor
diferente do que entrou na gaveta, e a acumular em cada divisão do dia.
"""
from typing import List

# Casas decimais da QUANTIDADE. São mais do que as 2 dos preços de propósito,
# e por uma razão diferente: uma quantidade não é dinheiro, é o que PRODUZ o
# dinheiro, e é preciso resolução para o valor final cair no cêntimo certo.
# Cinco chegam e o Vendus aceita-as (medido contra a conta real).
CASAS_DA_QUANTIDADE = 5


def repartir_centimos(total_centimos: int, partes: int) -> List[int]:
    """Reparte `total_centimos` por `partes`, e as partes **somam sempre** o
    total.

    O cêntimo que sobra vai para as PRIMEIRAS partes, não para a última: a
    diferença entre duas pessoas nunca passa de um cêntimo, e quem paga
    primeiro é quem leva o cêntimo a mais — o que é mais fácil de explicar ao
    balcão do que a última pessoa levar todos os que sobraram.
    """
    if partes < 1:
        raise ValueError("Uma conta reparte-se por pelo menos uma parte.")
    base, resto = divmod(int(total_centimos), int(partes))
    return [base + (1 if i < resto else 0) for i in range(partes)]


def quantidade_para(valor_centimos: int, preco: float) -> float:
    """A quantidade que, ao preço dado, produz exactamente este valor.

    Não devolve a fracção "bonita" (1/3): devolve a que o Vendus, ao fazer
    `qty × gross_price` e arredondar a 2 casas, transforma no valor exacto
    desta parte. E **confirma-o antes de devolver** — o Vendus arredonda de
    forma previsível, mas a defesa deste módulo nunca é acreditar num
    comportamento externo; é medi-lo. Medido: `0.3333 × 8.99` sai 3,00 € na
    conta real, e é assim que se escolhe o número.
    """
    if not preco:
        raise ValueError(
            "Não há quantidade que produza %d cêntimos a um preço de %s."
            % (valor_centimos, preco)
        )
    alvo = valor_centimos / 100.0
    q = round(alvo / preco, CASAS_DA_QUANTIDADE)
    if round(q * preco, 2) == alvo:
        return q
    # O arredondamento da divisão caiu do lado errado. Anda um passo mínimo
    # para cada lado — mais do que isso e o preço é que não produz este valor.
    passo = 10 ** -CASAS_DA_QUANTIDADE
    for candidato in (round(q + passo, CASAS_DA_QUANTIDADE),
                      round(q - passo, CASAS_DA_QUANTIDADE)):
        if round(candidato * preco, 2) == alvo:
            return candidato
    raise ValueError(
        "Nenhuma quantidade com %d casas produz %.2f € ao preço de %s — "
        "repartir esta linha perderia um cêntimo."
        % (CASAS_DA_QUANTIDADE, alvo, preco)
    )
```

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_reparticao.py -q`
Esperado: PASS, 7 testes.

- [ ] **Passo 5: mutação**

Troca `base + (1 if i < resto else 0)` por `base`.
Esperado: `test_as_partes_somam_sempre_o_total` vermelho já no primeiro total que não divide
certo. Repõe.

Segunda mutação: em `quantidade_para`, devolve `round(alvo / preco, 2)` sem a verificação.
Esperado: `test_a_quantidade_reproduz_o_valor_ao_centimo` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/reparticao.py backend/tests/faturacao/test_reparticao.py
git commit -m "Faturação: repartir uma conta ao cêntimo, sem vírgula flutuante"
```

---

## Task 2: A quantidade aceita fracções

**Files:**
- Modify: `backend/faturacao/venda.py` (`PedidoJuntarLinha`, `PedidoEditarLinha`)
- Test: `backend/tests/faturacao/test_venda.py`

**Interfaces:**
- Consumes: `reparticao.CASAS_DA_QUANTIDADE` (Task 1).
- Produces: `quantidade: float` com no máximo 5 casas, `> 0`.

**Contexto:** hoje é `quantidade: int = Field(default=1, ge=1)` (venda.py:121) e
`Optional[int]` no editar (venda.py:134). Uma parte de uma conta dividida precisa de `0.3337`.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_a_quantidade_aceita_uma_fraccao_de_cinco_casas():
    p = venda.PedidoJuntarLinha(produto_id="p1", quantidade=0.33370)
    assert p.quantidade == 0.33370


def test_a_quantidade_recusa_mais_de_cinco_casas():
    """Mais casas do que estas e o valor final deixa de ser previsível —
    é a mesma defesa dos preços, noutra escala."""
    with pytest.raises(ValidationError):
        venda.PedidoJuntarLinha(produto_id="p1", quantidade=0.333703)


def test_a_quantidade_recusa_zero_e_negativos():
    for q in (0, -1):
        with pytest.raises(ValidationError):
            venda.PedidoJuntarLinha(produto_id="p1", quantidade=q)


def test_a_quantidade_inteira_continua_a_ser_inteira():
    """O caminho normal do balcão não pode ganhar casas decimais: 2 açaís
    são 2, e é isso que tem de sair no papel."""
    p = venda.PedidoJuntarLinha(produto_id="p1", quantidade=2)
    assert p.quantidade == 2
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_venda.py -q -k quantidade_aceita`
Esperado: FAIL — o Pydantic corta `0.33370` para `0`.

- [ ] **Passo 3: implementar**

Acrescentar em `venda.py`, junto aos outros crivos:

```python
def _recusa_quantidade_impossivel(v):
    """A quantidade ganha casas decimais para as contas divididas (uma parte
    de três de um açaí é 0.3337), mas não ganha resolução infinita: acima das
    casas que `reparticao` usa, o valor final deixa de ser previsível e o
    crivo passa a esconder o erro em vez de o apanhar. `gt=0` e não `ge=0`
    porque uma linha de quantidade zero não é uma venda — é uma linha que não
    devia existir, e deixá-la entrar dava uma fatura com um artigo a 0,00 €.
    """
    if v is None:
        return v
    if v <= 0:
        raise ValueError("A quantidade tem de ser maior do que zero.")
    casas = repr(float(v)).partition(".")[2]
    if len(casas) > CASAS_DA_QUANTIDADE:
        raise ValueError(
            "A quantidade %s tem mais de %d casas decimais."
            % (v, CASAS_DA_QUANTIDADE)
        )
    return v
```

e nos dois modelos, `quantidade: float = 1` / `quantidade: Optional[float] = None`, com
`@field_validator("quantidade")` a chamar o crivo.

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS. **Se algum teste de PREÇO mudar de valor, pára** — esta task não toca em
dinheiro.

- [ ] **Passo 5: mutação**

Troca `if len(casas) > CASAS_DA_QUANTIDADE` por `if False`.
Esperado: `test_a_quantidade_recusa_mais_de_cinco_casas` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/venda.py backend/tests/faturacao/test_venda.py
git commit -m "Venda: a quantidade aceita fracções, com o mesmo cuidado dos preços"
```

---

## Task 3: Dividir a conta

**Files:**
- Modify: `backend/faturacao/venda.py`, `backend/faturacao/db.py`
- Test: `backend/tests/faturacao/test_venda.py`, `test_indices.py`

**Interfaces:**
- Consumes: `repartir_centimos`, `quantidade_para` (Task 1); quantidade decimal (Task 2).

**Antes de escrever os testes:** o `test_venda.py` já tem `_db(registo, …)`, `_venda(**over)`
(id `"venda-1"`), `_linha(**over)` e `_corre(...)`. **Usa-os.** Se um nome usado abaixo não
bater com o do ficheiro, o que manda é o ficheiro — não cries um paralelo.
- Produces: `POST /pos/venda/{venda_id}/dividir` com corpo `{"partes": N}`, que devolve
  `{"conta_mae": {...}, "partes": [venda, venda, …]}`. A mãe fica `estado: "separada"`; cada
  parte é uma venda normal com `conta_mae_id`.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_dividir_por_tres_produz_tres_contas_que_somam_o_total(monkeypatch):
    registo = []
    # Conta: 1 Açaí Regular a 8,99. 899 cêntimos por três -> 300, 300, 299.
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(produto_nome="Açaí Regular", produto_preco=8.99, quantidade=1)])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)

    r = _corre(venda.dividir_conta("venda-1", venda.PedidoDividir(partes=3), operador=_OPERADOR))

    totais = [p["totais"]["total"] for p in r["partes"]]
    assert totais == [3.00, 3.00, 2.99]
    assert round(sum(totais), 2) == 8.99, "as partes TÊM de somar a conta"
    assert r["conta_mae"]["estado"] == "separada"
    assert all(p["conta_mae_id"] == "venda-1" for p in r["partes"])


def test_a_conta_mae_deixa_de_aceitar_alteracoes(monkeypatch):
    """Depois de dividida, quem emite são as filhas. Mexer na mãe deixava
    as partes a faturar linhas que já não existem."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="separada")])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(venda.juntar_linha("venda-1", venda.PedidoJuntarLinha(produto_id="p1"),
                                  operador=_OPERADOR))
    assert e.value.status_code == 409


def test_dividir_uma_conta_ja_dividida_e_recusado(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(estado="separada")])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(venda.dividir_conta("venda-1", venda.PedidoDividir(partes=2), operador=_OPERADOR))
    assert e.value.status_code == 409


def test_o_desconto_global_tambem_se_reparte(monkeypatch):
    """A spec di-lo e é fácil esquecer: se o desconto ficasse só na mãe,
    as três partes somavam mais do que o cliente pagou."""
    registo = []
    db = _db(registo, vendas=[_venda(
        linhas=[_linha(produto_preco=9.00, quantidade=1)],
        desconto_global_eur=3.00)])
    monkeypatch.setattr(venda, "obter_db", lambda: db)

    r = _corre(venda.dividir_conta("venda-1", venda.PedidoDividir(partes=3),
                                   operador=_OPERADOR))
    assert round(sum(p["totais"]["total"] for p in r["partes"]), 2) == 6.00


def test_as_partes_herdam_as_personalizacoes_da_linha(monkeypatch):
    """Três pessoas a partilhar um açaí com Nutella: cada fatura tem de
    dizer que era um açaí COM Nutella. As opções vão inteiras para cada
    parte — o que se reparte é a quantidade, e o preço unitário já as
    inclui."""
    registo = []
    nutella = {"id": "o1", "grupo_id": "g1", "nome": "Nutella", "preco": 0.95}
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(produto_nome="Açaí", produto_preco=8.99, quantidade=1,
               opcoes=[nutella])])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)

    r = _corre(venda.dividir_conta("venda-1", venda.PedidoDividir(partes=3),
                                   operador=_OPERADOR))
    for parte in r["partes"]:
        assert parte["linhas"][0]["opcoes"] == [nutella]


def test_dividir_uma_conta_vazia_e_recusado(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(venda.dividir_conta("venda-1", venda.PedidoDividir(partes=2), operador=_OPERADOR))
    assert e.value.status_code == 422
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_venda.py -q -k dividir_por_tres`
Esperado: FAIL — `venda` não tem `dividir_conta`.

- [ ] **Passo 3: implementar**

`PedidoDividir(BaseModel)` com `partes: int = Field(ge=2, le=20)` (duas é o mínimo que faz
sentido; vinte é um tecto para um dedo distraído não criar mil contas).

A rota, com a mesma disciplina do resto do módulo — `_obter_venda_da_loja`,
`_garante_aberta`, `_garante_sem_emissao`:

1. Recusa se não houver linhas (422) — uma conta vazia não se divide.
2. **Por cada linha**, reparte o bruto em cêntimos por N (`repartir_centimos`) e calcula a
   quantidade de cada parte (`quantidade_para`). Faz o mesmo ao desconto global da conta —
   se ele ficasse só na mãe, as partes somavam mais do que o cliente pagou.
   **As opções da linha vão inteiras para cada parte**: o que se reparte é a quantidade, e o
   preço unitário já as inclui. Três pessoas a partilhar um açaí com Nutella têm de ver
   "Nutella" nas três faturas.
3. Cria N vendas com `conta_mae_id`, `caixa_id`/`sessao_id`/`operador_id` da mãe, e as
   linhas repartidas.
4. Passa a mãe a `separada` — **com escrita condicionada** a `{"estado": "aberta"}` e
   decidindo pelo `matched_count`, como o `cancelar_venda` já faz. Se não casar, apaga as
   filhas que criou e responde 409: outra pessoa mexeu na conta entretanto.

E `_garante_aberta` passa a recusar `separada` com uma mensagem própria — *"esta conta foi
dividida; quem emite são as partes"* — em vez do genérico.

`db.py`: índice em `("fat_vendas", [("conta_mae_id", 1)], {"sparse": True})`.

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS.

- [ ] **Passo 5: mutação**

Na criação das partes, troca a quantidade calculada por `1 / partes`.
Esperado: `test_dividir_por_tres_produz_tres_contas_que_somam_o_total` vermelho com
`[3.0, 3.0, 3.0] != [3.0, 3.0, 2.99]`. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/venda.py backend/faturacao/db.py backend/tests/faturacao/
git commit -m "Venda: dividir a conta em partes que somam sempre o total"
```

---

## Task 4: Separar a conta

**Files:**
- Modify: `backend/faturacao/venda.py`
- Test: `backend/tests/faturacao/test_venda.py`

**Interfaces:**
- Produces: `POST /pos/venda/{venda_id}/separar` com corpo
  `{"partes": [{"linhas": [{"linha_id": str, "quantidade": float}]}, …]}`, que devolve o
  mesmo formato da Task 3.

**Contexto:** aqui não há fracções — o staff atribui **unidades inteiras** (uma linha de 2
açaís pode ir 1 para cada). É por isso que esta task é mais simples do que a anterior, e é
também porque a spec pôs as fracções fora de âmbito no separar.

- [ ] **Passo 1: escrever o teste que falha**

```python
def test_separar_reparte_os_artigos_pelas_pessoas(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="l1", produto_nome="Açaí Regular", produto_preco=8.99, quantidade=2),
        _linha(id="l2", produto_nome="Coca-Cola", produto_preco=0.95, quantidade=1)])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)

    r = _corre(venda.separar_conta("venda-1", venda.PedidoSeparar(partes=[
        {"linhas": [{"linha_id": "l1", "quantidade": 1},
                    {"linha_id": "l2", "quantidade": 1}]},
        {"linhas": [{"linha_id": "l1", "quantidade": 1}]},
    ]), operador=_OPERADOR))

    assert [p["totais"]["total"] for p in r["partes"]] == [9.94, 8.99]
    assert round(sum(p["totais"]["total"] for p in r["partes"]), 2) == 18.93


def test_separar_recusa_deixar_artigos_por_atribuir(monkeypatch):
    """Um artigo que não é de ninguém sai da loja sem fatura e sem
    pagamento. Recusa-se aqui, com o cliente à frente, e não depois no
    fecho de caixa."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="l1", produto_preco=8.99, quantidade=2)])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(venda.separar_conta("venda-1", venda.PedidoSeparar(partes=[
            {"linhas": [{"linha_id": "l1", "quantidade": 1}]},
        ]), operador=_OPERADOR))
    assert e.value.status_code == 422
    assert "por atribuir" in e.value.detail


def test_separar_recusa_atribuir_mais_do_que_existe(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(id="l1", quantidade=1)])])
    monkeypatch.setattr(venda, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(venda.separar_conta("venda-1", venda.PedidoSeparar(partes=[
            {"linhas": [{"linha_id": "l1", "quantidade": 1}]},
            {"linhas": [{"linha_id": "l1", "quantidade": 1}]},
        ]), operador=_OPERADOR))
    assert e.value.status_code == 422
```

- [ ] **Passo 2: correr e ver falhar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao/test_venda.py -q -k separar_reparte`
Esperado: FAIL — `venda` não tem `separar_conta`.

- [ ] **Passo 3: implementar**

A rota, com as mesmas guardas da Task 3. A verificação central: **a soma das quantidades
atribuídas a cada linha tem de dar exactamente a quantidade dessa linha** — nem menos (um
artigo sem dono sai sem fatura) nem mais (fatura-se o que não se vendeu). As duas dão 422
com mensagens diferentes, porque o que a operadora tem de fazer é diferente.

Reutiliza a criação das partes da Task 3 (extrai-a para um ajudante em vez de a duplicar).

- [ ] **Passo 4: correr e ver passar**

Comando: `cd backend && .venv/bin/pytest tests/faturacao -q`
Esperado: PASS.

- [ ] **Passo 5: mutação**

Apaga a verificação do "por atribuir".
Esperado: `test_separar_recusa_deixar_artigos_por_atribuir` vermelho. Repõe.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/venda.py backend/tests/faturacao/test_venda.py
git commit -m "Venda: separar a conta sem deixar artigos por atribuir"
```

---

## Task 5: O POS mostra e emite as partes

**Files:**
- Modify: `frontend/src/lib/pos.js`
- Create: `frontend/src/pages/pos/PosReparticao.js`
- Modify: `frontend/src/pages/pos/PosFinalizar.js`, `PosVenda.js`

**Interfaces:**
- Consumes: `POST /pos/venda/{id}/dividir` e `/separar` (Tasks 3 e 4).

- [ ] **Passo 1: os wrappers**

```js
export const dividirConta = (vendaId, partes) =>
  api.post(`/pos/venda/${vendaId}/dividir`, { partes });

export const separarConta = (vendaId, partes) =>
  api.post(`/pos/venda/${vendaId}/separar`, { partes });
```

- [ ] **Passo 2: o ecrã**

No finalizar, dois botões — **Dividir Conta** e **Separar Conta** —, exclusivos.

**Dividir:** um contador de pessoas (`−` `2` `+`). Escolhido o número, um cartão:

> **Divisão de Conta** · 1/3 Pessoas · Falta Receber: 5,99 €
> **2,99 € / Pessoa** · Total: 8,99 €

**Separar:** toca-se nos artigos que são desta pessoa. Mostra-se o que está atribuído e **o
que falta** — e o botão de confirmar só acende quando não falta nada, porque o servidor
recusa com 422 e é melhor a operadora ver isso antes de carregar do que depois.

Em ambos, a conta da direita mostra por linha a **fatia desta pessoa**, como o POS do Vendus
faz (a coluna `1` / `0.5` à esquerda do artigo).

Emite-se parte a parte. **Uma parte que não é paga cancela-se** — é o `cancelarVenda` que já
existe, e o ecrã diz o que isso significa: os artigos saem sem fatura e sem dinheiro.

- [ ] **Passo 3: compilar**

Comando: `cd frontend && CI=false yarn build`
Esperado: `Compiled with warnings`, **nenhum em `pos/`**.

- [ ] **Passo 4: percorrer no browser**

Servidor de mentira pronto em `.../scratchpad/pos-mock.js` (serve o build e responde à API).
**Compila com `REACT_APP_BACKEND_URL=` vazio**, senão o build aponta para produção. Semeia o
`localStorage` (`pos_device_token`, `pos_loja_id`, `pos_loja_nome`, `pos_operator_token`,
`pos_operador`, `pos_caixa_id`). Percorre: conta com um açaí de 8,99 → Dividir por 3 → as
três partes dizem 3,00 / 3,00 / **2,99** → emitir a primeira → *Falta Receber* desce →
cancelar a terceira. **Mata o servidor no fim.**

- [ ] **Passo 5: commit**

```bash
git add frontend/src/lib/pos.js frontend/src/pages/pos/
git commit -m "POS: dividir e separar a conta no finalizar"
```

---

## Verificação final

- [ ] Suite verde (esperado ~940) e `CI=false yarn build` limpo
- [ ] `pytest tests/faturacao/test_caminhos_do_pos.py` verde — nenhuma chamada órfã
- [ ] **As partes somam sempre o total** — o teste que percorre 400 totais × 7 divisões
- [ ] Uma conta dividida **não aceita alterações** na mãe
- [ ] Separar **recusa** deixar artigos por atribuir
- [ ] Uma parte não paga **cancela-se**, e fica registado quem cancelou
- [ ] Nada mudou em `precos.linha_de_venda`, `fiscal.py` nem `caixa_math`
