# Fatura por email — Servidor do POS (RH) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o servidor do POS suprimir o talão do cliente e pôr a fatura numa fila de envio por email quando — e só quando — o servidor tem prova de que o cliente leu o QR da app e escolheu recebê-la assim.

**Architecture:** A leitura do QR (`POST /pos/pontos/ler`) passa a gravar uma linha em `fat_pontos_qr` com índice TTL de 2 horas: é essa linha, do servidor, que decide o papel — nunca um campo do corpo do EMITIR, que vem do browser. Na emissão, `fiscal.py` troca a única linha que põe papel na fila por `if not await enfileirar_fatura_email(...): await enfileirar_venda_emitida(...)`, e a nova função devolve `True` só quando existe mesmo a linha `fatura_email:<documento_id>` na fila `fat_pontos_app` que já existe. O envio corre nessa fila com o tipo novo: descarrega o PDF certificado do Vendus com o `modo` do próprio documento e manda-o à app, com 25 s de folga porque ninguém está à espera ao balcão.

**Tech Stack:** Python 3.9 · FastAPI · Motor/MongoDB · httpx · pytest (backend/pytest.ini, duplos em memória, nenhum teste liga a Mongo nem à rede).

## Global Constraints

- Âmbito: **só** `/Users/matheus.moraes/Developer/RH/backend`. Nem um ficheiro do `frontend/`, nem nada do repo `applacai-fatura-email`.
- A decisão de não imprimir um documento fiscal vem **sempre** de `fat_pontos_qr`, nunca do corpo do pedido. `LigacaoDePontos` (`fiscal.py:1939-1948`) **não ganha campo nenhum**.
- `enfileirar_fatura_email` devolve `False` — e o papel sai — quando: `documento["modo"] != "normal"`; `documento["vendus_document_id"]` está vazio; a venda não tem `pontos_ligacao`; não há linha em `fat_pontos_qr` para aquele `ligacao_id` ou ela tem `fatura_por_email: False`; `venda["cliente_nif"]` está preenchido; a escrita falhou por qualquer razão.
- **A guarda do `vendus_document_id` é obrigatória e não é a do ATCUD.** `vendus/emissao._documento_da_criacao:702` só recusa quando faltam `id` **E** `atcud`: um 2xx com ATCUD e sem `id` é aceite de propósito e grava `vendus_document_id: None` (é por isso que `documentos.pdf_do_documento` tem o `_MSG_SEM_ID_NO_VENDUS` e um 422 dedicado, `documentos.py:892-894`). Sem ela o papel saltava-se e `_pdf_da_fatura` devolvia `b""` para sempre — 13 tentativas, `falhado` às 24 h, e nem papel nem email.
- `enfileirar_fatura_email` **não herda a guarda do ATCUD** de `enfileirar_credito` (`pontos_app.py:457-463`): um documento real pode não ter ATCUD, a app precisa dele para deduplicar os PONTOS, e o email precisa é do id do VENDUS.
- Um `DuplicateKeyError` na inserção da linha do email conta como **`True`**: a linha já lá estava, e devolver `False` fazia sair papel numa fatura que já ia por email.
- A venda lê-se de `venda_actualizada` (`fiscal.py:2271`), nunca do corpo: quem perde a corrida da reserva também chega àquela linha e só a venda gravada tem a verdade.
- Chave da linha: `fatura_email:<documento_id>`, na colecção `fat_pontos_app` que já existe, com o índice único que já existe (`db.py:385`).
- Payload da linha: `{ligacao_id, documento_id, vendus_document_id, numero, modo}` — **nunca os bytes do PDF**. A fila não tem TTL e fica para sempre.
- Índice TTL de `fat_pontos_qr`: **2 horas** (`expireAfterSeconds: 7200`), sobre um campo do tipo **Date** — o Mongo não expira por uma string, e não dá erro nenhum a dizê-lo.
- Timeouts de `_chamar_app`: **4 s** para quem está ao balcão (`ligar`, `creditar`, `estornar`), **25 s** para `fatura-email`, que corre em segundo plano.
- `_RESPOSTAS_FEITAS` passa a incluir `"enviado"` e `"ja_enviado"`.
- **O mapa `_ACCAO_DO_TIPO` lê-se com `.get` e nunca com `[...]`.** `enviar` é chamado por `cron_pontos_app` (`pontos_app.py:580-583`) sem `try` nenhum: um `KeyError` levantava-se DEPOIS de a reserva estar feita, o cron respondia 500 e a volta morria — os pontos e os emails de todas as lojas parados, em silêncio, a cada minuto. Um tipo desconhecido fecha a linha `sem_efeito` com log de erro.
- Sem PDF, a app **não** é chamada: é falha técnica e a fila repete (esperas de 1, 2, 5, 10 e 30 min, desistência ao fim de 24 h a falhar).
- Nada disto pode impedir uma fatura de sair nem devolver 5xx ao balcão: uma emissão com Fatura Simplificada já entregue à AT a responder erro é lida pelo ecrã como «não saiu nada» e convida a operadora a emitir a segunda.
- **Limitação conhecida, assumida:** nada impede que o MESMO `ligacao_id` suprima o papel de dois documentos (um QR lido uma vez e reaproveitado em duas contas). Do lado da app a segunda fatura é recusada (`find_one_and_update({id, documento_id: None})`); se essa recusa vier como 400/413/422, `enviar` fecha a linha `recusado` e o cliente fica sem papel e sem email. **Não se põe guarda aqui**: a única leitura possível seria `find_one({"tipo": "fatura_email", "payload.ligacao_id": …})`, sem índice nenhum que a sirva, num caminho que corre em TODAS as emissões — uma colecção que «fica para sempre» varrida por cada fatura das cinco lojas. Fica escrito, e o contrato da app (5xx para tudo o que não seja sucesso, desenho §`/fatura-email` ponto 4) é o que mantém a linha a repetir em vez de fechar.
- Suite: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest -q` → **3296 passed** em ~83 s, medido antes de começar. Config única: `backend/pytest.ini`.
- Duplos: `ColeccaoFalsa`/`DbFalsa`/`_corre` de `tests/faturacao/test_venda.py` (`:189` — assinatura `(registo, documentos, unico=, ceder=)`, com `count_documents` e `$gte`) **e** os homónimos de `tests/faturacao/test_fiscal.py` (`:194`, `:265` — assinatura `(documentos, indices_unicos=)`, sem `count_documents`). São classes DIFERENTES; cada tarefa diz qual usa.
- Armadilha do banco de ensaio: `DbFalsa.__getitem__` faz `setdefault`, por isso uma colecção nova nasce **sem índice único**. Uma prova de idempotência ali não prova nada sem registar a colecção com `unico=`.
- Português de Portugal nas docstrings, nos nomes e nas mensagens de commit.

---

### Task 1: A preferência do QR gravada no servidor (`fat_pontos_qr`)

**Files:**
- Modify: `backend/faturacao/db.py:88-94` (entrada nova em `COLECOES`)
- Modify: `backend/faturacao/db.py:380-389` (índice TTL novo em `INDICES`)
- Modify: `backend/faturacao/pontos_app.py:10-12` (docstring), `:104-167` (helper novo + `ler_qr_de_pontos`)
- Test: `backend/tests/faturacao/test_os_pontos_da_app.py:119-121` (o teste que já existe) e secção nova a seguir à linha 233
- Test: `backend/tests/faturacao/test_indices.py:283-296` (o TTL deixa de ser único)

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces:
  - `COLECOES["pontos_qr"] == "fat_pontos_qr"`
  - `async _gravar_qr_da_ligacao(db, ligacao_id: str, fatura_por_email: bool) -> bool` em `faturacao/pontos_app.py`
  - `POST /pos/pontos/ler` devolve `{"ligacao_id": str, "primeiro_nome": str, "fatura_por_email": bool}`
  - a linha gravada tem a forma `{"ligacao_id": str, "fatura_por_email": True, "criada_em": datetime}` — **a Task 3 lê exactamente estes dois primeiros campos.**

- [ ] **Step 1: Escrever o teste que falha**

Primeiro, **o teste que já existe e que esta tarefa parte**. Em `backend/tests/faturacao/test_os_pontos_da_app.py`, substituir as linhas 119-121 por:

```python
def test_ler_o_qr_devolve_a_ligacao_o_primeiro_nome_e_o_SIM_NAO_do_email(monkeypatch, app):
    """A resposta tem TRÊS chaves e não duas — e o `False` aqui não é um
    pormenor: o corpo da app não trouxe `fatura_por_email` nenhum, e o que sai
    é o que FICOU GRAVADO em `fat_pontos_qr` (nada), nunca o que a app disse.

    Sem linha não se promete email: o cartão do Finalizar desenha-se pelo valor
    que sai daqui, e um cartão a dizer «Fatura por email» por cima de um talão
    a sair é o ecrã a mentir à funcionária."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    assert _ler(monkeypatch, _db_do_ler()) == {
        "ligacao_id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```

Depois, a secção nova, logo a seguir a `test_uma_venda_que_ja_nao_esta_aberta_e_409_e_a_app_nem_e_chamada` (linha 233):

```python
# --- A preferência de fatura por email, gravada no SERVIDOR ---------------------
#
# A decisão de **não imprimir um documento fiscal** não pode vir do corpo de um
# pedido do browser. A ligação já viaja no `dados_pagamento` do finalizar
# (`fiscal.py:2136`) e isso chega para pontos; para SUPRIMIR papel não chega —
# um campo forjado, ou um defeito no ecrã, fazia desaparecer o documento do
# cliente. Daí `fat_pontos_qr`: é do servidor, caduca sozinha em 2 horas, e a
# AUSÊNCIA dela é o lado seguro (sai papel, como sempre).


def test_ler_o_qr_GRAVA_a_preferencia_de_fatura_por_email(monkeypatch, app):
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana",
                       "fatura_por_email": True})
    db = _db_do_ler()

    assert _ler(monkeypatch, db)["fatura_por_email"] is True

    [linha] = db[COLECOES["pontos_qr"]]._documentos
    assert (linha["ligacao_id"], linha["fatura_por_email"]) == ("lig-1", True)
    assert isinstance(linha["criada_em"], datetime), (
        "o TTL do Mongo só expira por um campo do tipo Date — sobre uma string "
        "não apaga nada, e não dá erro nenhum a dizê-lo")


def test_sem_preferencia_nao_fica_linha_nenhuma_na_coleccao(monkeypatch, app):
    """Uma preferência desligada e uma linha que não existe querem dizer a mesma
    coisa — sai papel. Gravar `False` era uma linha por leitura do QR para nada."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana",
                       "fatura_por_email": False})
    db = _db_do_ler()

    assert _ler(monkeypatch, db)["fatura_por_email"] is False
    assert db[COLECOES["pontos_qr"]]._documentos == []


def test_uma_escrita_FALHADA_devolve_falso_em_vez_de_prometer_email(monkeypatch, app):
    """**O ecrã nunca pode prometer o que não ficou gravado.** Sem a linha sai
    papel (`enfileirar_fatura_email`), e um cartão a dizer «Fatura por email»
    por cima de um talão a sair é o ecrã a mentir à funcionária.

    E não pode ser 500: a app já consumiu o código do QR quando chegamos aqui, e
    um erro faria a funcionária pedir ao cliente um código novo que já não
    serve para nada."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana",
                       "fatura_por_email": True})
    db = _db_do_ler()

    class _Rebenta:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db._coleccoes[COLECOES["pontos_qr"]] = _Rebenta()

    assert _ler(monkeypatch, db)["fatura_por_email"] is False


def test_a_coleccao_do_qr_apaga_se_sozinha_ao_fim_de_DUAS_HORAS():
    """Uma conta pode ficar aberta muito depois da leitura — daí não ser um
    minuto — mas a preferência é daquela ida ao balcão e não da conta. Duas
    horas é o compromisso escrito no desenho."""
    from faturacao.db import INDICES
    ttl = [opcoes for (coleccao, chaves, opcoes) in INDICES
           if coleccao == "fat_pontos_qr" and chaves == [("criada_em", 1)]]
    assert ttl == [{"expireAfterSeconds": 7200}]
```

E em `backend/tests/faturacao/test_indices.py`, substituir o teste das linhas 283-296 (título incluído):

```python
def test_so_o_PAPEL_e_a_PREFERENCIA_DO_QR_se_apagam_sozinhos():
    """Os TTL. A fila de impressão guarda os BYTES de cada talão de cinco lojas
    e `fat_pontos_qr` guarda uma escolha que só vale naquela ida ao balcão; sem
    eles, as duas cresciam para sempre. Nada de fiscal se perde — o documento e
    o talão certificado ficam em `fat_documentos`, e o registo do envio fica em
    `fat_pontos_app`, que NÃO tem TTL nenhum.

    E são estas duas e mais nenhuma: um TTL em `fat_documentos`, `fat_vendas`,
    `fat_pontos_app` ou `fat_refs_fiscais` apagava registo fiscal, e a reserva
    de uma venda emitida é o que sustenta a idempotência da emissão para
    sempre."""
    com_ttl = [
        (coleccao, chaves)
        for (coleccao, chaves, opcoes) in INDICES
        if "expireAfterSeconds" in opcoes
    ]
    assert com_ttl == [
        ("fat_trabalhos_impressao", [("apagar_depois_de", 1)]),
        ("fat_pontos_qr", [("criada_em", 1)]),
    ]
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_indices.py -q`

Expected: FAIL — `KeyError: 'pontos_qr'` em `test_ler_o_qr_GRAVA_a_preferencia_de_fatura_por_email`, `AssertionError` em `test_ler_o_qr_devolve_a_ligacao_o_primeiro_nome_e_o_SIM_NAO_do_email` (a resposta ainda tem duas chaves), lista vazia em `test_a_coleccao_do_qr_apaga_se_sozinha_ao_fim_de_DUAS_HORAS` e um só TTL em `test_so_o_PAPEL_e_a_PREFERENCIA_DO_QR_se_apagam_sozinhos`.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/db.py`, a seguir à entrada `"pontos_app"` (linha 93) e antes do `}` da linha 94:

```python
    "pontos_app": "fat_pontos_app",
    # **A PREFERÊNCIA DA LEITURA DO QR** (`pontos_app._gravar_qr_da_ligacao`):
    # uma linha por QR lido em que o cliente quer a fatura por email — e só
    # nesses. É a **fonte da verdade do papel**: a decisão de não imprimir um
    # documento fiscal não pode vir do corpo de um pedido do browser, onde um
    # campo forjado (ou um defeito no ecrã) fazia desaparecer o documento do
    # cliente.
    #
    # Caduca sozinha em 2 horas (índice TTL abaixo) porque a escolha é daquela
    # ida ao balcão, não da conta — e porque a falta da linha faz sair papel,
    # que é o lado seguro de uma colecção que se apaga.
    "pontos_qr": "fat_pontos_qr",
}
```

Em `backend/faturacao/db.py`, a seguir à linha 388 (`("fat_pontos_app", [("estado", 1), ("proxima_tentativa_em", 1)], {})`) e antes do `]` da linha 389:

```python
    ("fat_pontos_app", [("estado", 1), ("proxima_tentativa_em", 1)], {}),
    # **O TTL DA PREFERÊNCIA DO QR — 2 horas.** O campo é uma DATA a sério (e
    # não a string ISO que o resto do módulo grava): o Mongo só sabe expirar
    # por um campo do tipo Date, e um índice TTL sobre uma string não apaga
    # nada — nem dá erro, o que é pior. Aqui `expireAfterSeconds` são os 7200 e
    # não 0 porque a data gravada é a da CRIAÇÃO e não a da validade (ao
    # contrário de `fat_trabalhos_impressao.apagar_depois_de`).
    #
    # Nenhum registo fiscal mora aqui: o documento fica em `fat_documentos` e o
    # registo do envio em `fat_pontos_app`, que não tem TTL nenhum.
    ("fat_pontos_qr", [("criada_em", 1)], {"expireAfterSeconds": 7200}),
]
```

Em `backend/faturacao/pontos_app.py`, imediatamente antes de `@router.post("/pos/pontos/ler")` (linha 105):

```python
async def _gravar_qr_da_ligacao(db, ligacao_id: str, fatura_por_email: bool) -> bool:
    """Grava em `fat_pontos_qr` a preferência desta leitura, e diz se ficou lá.

    **É esta linha, e não o corpo do EMITIR, que decide se sai papel**
    (`enfileirar_fatura_email`). A ligação já viaja no `dados_pagamento` do
    finalizar (`fiscal.py:2136`) e isso é aceitável para pontos; para SUPRIMIR
    um documento fiscal não é — um campo forjado pelo browser, ou um defeito no
    ecrã, fazia desaparecer o documento do cliente. Esta linha é do servidor e
    caduca sozinha em 2 horas.

    **Só se escreve quando a preferência está LIGADA.** Uma preferência
    desligada e uma linha que não existe querem dizer exactamente a mesma coisa
    — sai papel — e a colecção fica com uma linha por fatura desmaterializada
    em vez de uma por leitura do QR.

    **Nunca levanta.** Uma escrita falhada é papel a sair, que é o lado seguro;
    levantar era um 503 ao balcão depois de a app já ter consumido o código do
    QR, e a funcionária a pedir ao cliente um código novo que já não servia."""
    if not fatura_por_email:
        return False
    try:
        await db[COLECOES["pontos_qr"]].insert_one({
            "ligacao_id": ligacao_id,
            "fatura_por_email": True,
            # Uma DATA a sério e não a string ISO do resto do módulo: o índice
            # TTL de `db.py` só expira por um campo do tipo Date.
            "criada_em": datetime.now(timezone.utc),
        })
    except Exception as e:  # noqa: BLE001 — sem linha sai papel, que é o lado seguro
        logger.error(
            "[faturacao] a preferência de fatura por email da ligação %s NÃO ficou "
            "gravada (a fatura desta venda sai em papel): %s", ligacao_id, e)
        return False
    return True


```

E em `backend/faturacao/pontos_app.py`, substituir o `return` de `ler_qr_de_pontos` (linhas 164-167):

```python
    ligacao_id = str(corpo["ligacao_id"])
    return {
        "ligacao_id": ligacao_id,
        "primeiro_nome": str(corpo.get("primeiro_nome") or ""),
        # **O que se devolve é o que ficou GRAVADO**, nunca o que a app disse.
        # O ecrã usa isto só para desenhar o cartão do Finalizar; se ele for
        # adulterado, o pior que acontece é o cartão mentir ao staff — mas se
        # devolvêssemos a preferência da app sem a gravar, o cartão prometia
        # email por cima de um talão a sair, que é a mentira que interessa.
        "fatura_por_email": await _gravar_qr_da_ligacao(
            db, ligacao_id, bool(corpo.get("fatura_por_email"))),
    }
```

E, na docstring do módulo (`pontos_app.py:10-12`), trocar a frase que passou a ser falsa:

```python
1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome e um sim/não à fatura por email. Não grava
   nada na VENDA — é o ecrã que guarda a ligação e a manda no finalizar
   (`fiscal.PedidoFinalizarVenda`) — mas grava a preferência do email em
   `fat_pontos_qr`, porque suprimir um documento fiscal não se decide por um
   campo do corpo de um pedido do browser.
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_indices.py tests/faturacao/test_arranque.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/db.py backend/faturacao/pontos_app.py \
        backend/tests/faturacao/test_os_pontos_da_app.py \
        backend/tests/faturacao/test_indices.py
git commit -m "Ler o QR grava a preferência de fatura por email em fat_pontos_qr

Suprimir um documento fiscal não se pode decidir por um campo do corpo de um
pedido do browser. A preferência passa a ficar numa colecção do servidor, com
índice TTL de 2 horas, e a AUSÊNCIA da linha é o lado seguro: sai papel.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: A fila aprende o tipo `fatura_email`

**Files:**
- Modify: `backend/faturacao/pontos_app.py:23-40` (imports), `:44-49` (timeouts), `:79` (`_chamar_app`), `:189` (`_RESPOSTAS_FEITAS`), `:416-417` (mapa e `_pdf_da_fatura`, a seguir a `_fechar`) e `:323-325` (o corpo de `enviar`)
- Test: `backend/tests/faturacao/test_os_pontos_da_app.py:17-25` (import de `base64`) e secção nova a seguir à linha 345

**Interfaces:**
- Consumes: nada da Task 1 — **mas partilha os MESMOS ficheiros** (`faturacao/pontos_app.py` e `tests/faturacao/test_os_pontos_da_app.py`). Corre a SEGUIR à Task 1, nunca ao lado: o `git add` do Step 5 da Task 1 nomeia esses ficheiros à letra e arrastava esta tarefa meio feita, e cada Step 4 media a suite contra uma árvore contaminada pela outra. Quem quiser mesmo paralelizar, separa em worktrees distintas.
- Produces:
  - `pontos_app._ACCAO_DO_TIPO == {"credito": "creditar", "estorno": "estornar", "fatura_email": "fatura-email"}`
  - `pontos_app._TIMEOUT_POR_ACCAO == {"fatura-email": 25.0}`
  - `async pontos_app._pdf_da_fatura(payload: Dict) -> bytes`
  - `enviar(db, linha_id=None, *, agora=None)` passa a saber enviar uma linha de `tipo == "fatura_email"`, com o corpo `{ligacao_id, documento_id, numero, pdf_base64}`, e a fechar `sem_efeito` um tipo que não conheça.
  - **A Task 3 depende disto:** só depois de a fila saber o tipo é que se pode enfileirar um; enfileirado antes, ia para `/estornar`.

- [ ] **Step 1: Escrever o teste que falha**

No topo de `backend/tests/faturacao/test_os_pontos_da_app.py`, acrescentar `import base64` à lista de imports (linhas 17-25, por ordem alfabética, antes de `import json`).

No fim da secção «A fila e o envio» (a seguir a `test_a_mesma_chave_so_entra_uma_vez_na_fila`, linha 345), acrescentar:

```python
# --- O tipo novo: a fatura por email --------------------------------------------

_PDF = b"%PDF-1.3\nfingido\n%%EOF"


def _fatura_email(**over):
    linha = pontos_app._linha_nova(
        "fatura_email", "fatura_email:doc-1",
        {"ligacao_id": "lig-1", "documento_id": "doc-1",
         "vendus_document_id": 368200354, "numero": "FS 05P2026/1824",
         "modo": "normal"},
        AGORA, documento_id="doc-1", venda_id="venda-1", loja_id="loja-1",
        primeiro_nome="Ana")
    linha.update(over)
    return linha


class _VendusDoPdf:
    """O cliente do Vendus a fingir, com o registo do que lhe foi pedido — é
    pelo `modo` que este duplo guarda que se prova a armadilha do 404."""

    pedidos = []

    def __init__(self, chave):
        self.chave = chave

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def pdf_do_documento(self, documento_id, modo):
        _VendusDoPdf.pedidos.append((documento_id, modo))
        return _PDF


@pytest.fixture
def vendus(monkeypatch):
    _VendusDoPdf.pedidos = []
    monkeypatch.setattr(pontos_app, "ClienteVendus", _VendusDoPdf)
    monkeypatch.setattr(
        pontos_app, "obter_conta",
        lambda *a, **kw: type("Conta", (), {"chave": "chave-teste"})())
    return _VendusDoPdf


def test_um_tipo_NOVO_nao_pode_ir_parar_a_estornar(monkeypatch, app, vendus):
    """O ternário que lá estava (`"creditar" if tipo == "credito" else
    "estornar"`) mandava qualquer tipo novo para `/estornar` — a app recebia um
    corpo que não conhece, respondia 422, e a linha fechava `recusado` sem
    ninguém perceber que o email nunca tinha sido tentado."""
    db, _ = _db_da_fila(_fatura_email())
    app.responde(200, {"estado": "enviado"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    assert str(app.pedidos[0].url) == \
        "http://olacai-api:8001/api/pos-integracao/fatura-email"


def test_um_tipo_DESCONHECIDO_fecha_a_linha_em_vez_de_MATAR_o_cron(monkeypatch, app):
    """**Um `KeyError` aqui era a pior avaria deste módulo.** `enviar` é chamado
    por `cron_pontos_app` sem `try` nenhum: a excepção subia DEPOIS de a reserva
    estar feita, a rota do cron respondia 500, e a volta morria — os pontos e os
    emails de TODAS as lojas parados, em silêncio, de minuto a minuto. É a mesma
    avaria que o comentário de `pontos_app.py:337-344` existe para impedir.

    Fecha-se a linha `sem_efeito`: larga a reserva, não repete, fica escrita."""
    db, fila = _db_da_fila(_fatura_email(tipo="marciano", chave="marciano:doc-9"))

    assert _corre(pontos_app.enviar(db, agora=AGORA)) is not None

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["motivo"]) == ("sem_efeito", "tipo_desconhecido")
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA, "a reserva tem de ser largada"
    assert app.pedidos == [], "um tipo que não se conhece não se manda a lado nenhum"


def test_a_volta_do_cron_SOBREVIVE_a_uma_linha_de_tipo_desconhecido(monkeypatch, app):
    """A prova pela porta a sério: com a linha estragada em primeiro lugar, a
    volta tem de continuar e enviar a boa que vem a seguir."""
    monkeypatch.setenv("CRON_KEY", "k")
    db, fila = _db_da_fila(
        _fatura_email(tipo="marciano", chave="marciano:doc-9"), _credito())
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    app.responde(200, {"estado": "creditado", "pontos": 17})

    assert _corre(pontos_app.cron_pontos_app(key="k"))["enviadas"] == 2
    assert [l["estado"] for l in fila.linhas()] == ["sem_efeito", "feito"]


@pytest.mark.parametrize("resposta", ["enviado", "ja_enviado"])
def test_enviado_e_ja_enviado_fecham_a_linha_como_FEITA(monkeypatch, app, vendus, resposta):
    """`ja_enviado` é a idempotência da app a responder: a fila repetiu, o email
    já tinha saído. Fora de `_RESPOSTAS_FEITAS`, isto caía no saco do 5xx e eram
    13 tentativas por 24 h de uma fatura já entregue."""
    db, fila = _db_da_fila(_fatura_email())
    app.responde(200, {"estado": resposta})

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert gravada["estado"] == "feito"
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA, "a reserva tem de ser largada"


def test_o_PDF_vai_no_corpo_e_NUNCA_fica_gravado_na_fila(monkeypatch, app, vendus):
    """A fila não tem TTL e fica para sempre. 92 KB por fatura para sempre não —
    daí o payload guardar só o id do documento e o PDF ser ido buscar a cada
    tentativa."""
    db, fila = _db_da_fila(_fatura_email())
    app.responde(200, {"estado": "enviado"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    corpo = app.corpo()
    assert corpo == {
        "ligacao_id": "lig-1", "documento_id": "doc-1",
        "numero": "FS 05P2026/1824",
        "pdf_base64": base64.b64encode(_PDF).decode(),
    }
    assert "pdf_base64" not in fila.linhas()[0]["payload"]
    assert "vendus_document_id" not in corpo, "o id do Vendus é nosso, não da app"


def test_o_MODO_DO_DOCUMENTO_e_o_que_vai_buscar_o_PDF(monkeypatch, app, vendus):
    """Um documento emitido em `tests` pedido com `mode=normal` responde 404 — o
    Vendus guarda os dois mundos separados (medido ao vivo na conta real, ver
    `ClienteVendus.pdf_do_documento`). O modo tem de sair do PAYLOAD da linha e
    nunca do modo em que a loja está hoje, que muda com um botão."""
    db, _ = _db_da_fila(_fatura_email(payload=dict(
        _fatura_email()["payload"], modo="tests")))
    app.responde(200, {"estado": "enviado"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    assert vendus.pedidos == [(368200354, "tests")]


def test_SEM_PDF_a_app_nem_e_chamada_e_a_fila_REPETE(monkeypatch, app, vendus):
    """Mandar a app enviar um email sem anexo era entregar ao cliente uma fatura
    que não é fatura nenhuma. Sem PDF é falha TÉCNICA: conta a tentativa, afasta
    a seguinte, e a volta do cron de 1 em 1 minuto tenta outra vez."""
    monkeypatch.setattr(_VendusDoPdf, "pdf_do_documento",
                        lambda self, documento_id, modo: b"")
    db, fila = _db_da_fila(_fatura_email())

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 1)
    assert gravada["proxima_tentativa_em"] > _iso(AGORA)
    assert app.pedidos == [], "a app não pode ser chamada sem o anexo"


def test_o_VENDUS_a_REBENTAR_tambem_e_falha_tecnica_e_nao_um_500(monkeypatch, app, vendus):
    """A ida buscar o PDF é rede: um timeout ou uma chave trocada levantam. Fora
    de um `try`, isso subia para o cron e matava a volta de todas as lojas."""
    def _rebenta(self, documento_id, modo):
        raise RuntimeError("Vendus em baixo")

    monkeypatch.setattr(_VendusDoPdf, "pdf_do_documento", _rebenta)
    db, fila = _db_da_fila(_fatura_email())

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 1)
    assert "Vendus em baixo" in gravada["ultimo_erro"]


def test_o_ENVIO_tem_25_s_e_quem_esta_ao_BALCAO_continua_com_4(monkeypatch, app, vendus):
    """Os 4 s são para a funcionária com o cliente à frente: uma app em baixo
    diz-se depressa e a fatura segue sem pontos. O envio do email leva o PDF em
    base64 (~120 KB de texto) e corre em segundo plano, onde ninguém espera —
    com 4 s cortava-se a meio e a fila repetia para sempre um envio que ia bem."""
    db, _ = _db_da_fila(_fatura_email(), _credito())
    app.responde(200, {"estado": "enviado"})
    _corre(pontos_app.enviar(db, agora=AGORA))
    app.responde(200, {"estado": "creditado", "pontos": 17})
    _corre(pontos_app.enviar(db, agora=AGORA))

    assert app.pedidos[0].extensions["timeout"]["read"] == 25.0
    assert app.pedidos[1].extensions["timeout"]["read"] == 4.0
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py -q`

Expected: FAIL — `test_um_tipo_NOVO_nao_pode_ir_parar_a_estornar` com `AssertionError: assert 'http://olacai-api:8001/api/pos-integracao/estornar' == '.../fatura-email'`, e `AttributeError: module 'faturacao.pontos_app' has no attribute 'ClienteVendus'` na fixture `vendus`.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/pontos_app.py`, substituir o bloco de imports (linhas 23-40) por:

```python
import asyncio
import base64
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import CODIGO_NAO_SUJEITO
from .venda import _garante_aberta, _obter_venda_da_loja
from .vendus.cliente import ClienteVendus, obter_conta
```

(Sem `from .importacao import _nif_configurado`: `obter_conta()` sem argumento já lê `FAT_NIF` do ambiente com a mesma omissão — `vendus/cliente.py:120` — e o gémeo desta função, `documentos.pdf_do_documento`, faz a mesma ida buscar. O que se poupa é `faturacao.pontos_app` a arrastar `faturacao.importacao` — e com ela `.catalogo`, `.fotos`, `.auth` — para o grafo de importação.)

A seguir a `TIMEOUT_SEGUNDOS = 4.0` (linha 49):

```python
TIMEOUT_SEGUNDOS = 4.0

# **O tempo por ACÇÃO.** Os 4 s acima são para quem está ao balcão à espera (o
# Ler, o creditar, o estornar): uma app em baixo diz-se depressa e a fatura
# segue sem pontos. O envio da fatura por email é outra coisa — leva o PDF em
# base64 (~120 KB de texto) e corre em segundo plano, onde ninguém espera por
# ele. Com 4 s cortava-se um envio que ia bem a meio, e a fila repetia-o para
# sempre a cada volta do cron.
_TIMEOUT_POR_ACCAO = {"fatura-email": 25.0}
```

Em `_chamar_app` (linha 79), trocar a construção do cliente:

```python
    async with httpx.AsyncClient(
        timeout=_TIMEOUT_POR_ACCAO.get(acao, TIMEOUT_SEGUNDOS),
        transport=_transporte,
    ) as http:
```

Na linha 189:

```python
# `enviado`/`ja_enviado` são a resposta do envio da fatura por email — o segundo
# é a idempotência da app a dizer «esta fatura já saiu». Fora desta lista, um
# `ja_enviado` caía no saco do 5xx: 13 tentativas espalhadas por 24 h de uma
# fatura que o cliente já tinha na caixa de correio.
_RESPOSTAS_FEITAS = ("creditado", "ja_creditado", "estornado", "ja_estornado",
                     "enviado", "ja_enviado")
```

A seguir a `_fechar` (linha 415) e antes do comentário `# --- O crédito, na emissão`:

```python
# **O tipo da linha → a rota da app, por MAPA e não por ternário.** O ternário
# que aqui estava (`"creditar" if tipo == "credito" else "estornar"`) mandava
# qualquer tipo NOVO para `/estornar`: a app recebia um corpo que não conhece,
# respondia 422, e a linha fechava `recusado` sem ninguém perceber que o envio
# nunca tinha sido tentado.
_ACCAO_DO_TIPO = {
    "credito": "creditar",
    "estorno": "estornar",
    "fatura_email": "fatura-email",
}


async def _pdf_da_fatura(payload: Dict) -> bytes:
    """O PDF **certificado** desta fatura, ido buscar ao Vendus. `b""` quando
    não há por onde o ir buscar.

    **Não é um PDF nosso, e é de propósito**: o documento fiscal é o do Vendus,
    com o ATCUD, o hash e o QR que a Autoridade Tributária conhece. É a mesma
    ida buscar que o botão «PDF da fatura» do backoffice já faz
    (`documentos.pdf_do_documento`).

    **O `mode` é o DO DOCUMENTO** e vem gravado no payload da linha, nunca o
    modo em que a loja está hoje: um documento emitido em `tests` pedido com
    `mode=normal` responde 404 — o Vendus guarda os dois mundos separados
    (medido ao vivo na conta real, ver `ClienteVendus.pdf_do_documento`). Um
    botão que mude o modo da loja não pode partir o reenvio de faturas antigas.

    Numa thread porque o cliente do Vendus é síncrono e a fila corre no event
    loop — o mesmo `asyncio.to_thread` da emissão e do botão do backoffice."""
    vendus_id = payload.get("vendus_document_id")
    if not vendus_id:
        return b""
    conta = obter_conta()
    if conta is None:
        return b""
    with ClienteVendus(conta.chave) as cliente:
        return await asyncio.to_thread(
            cliente.pdf_do_documento, vendus_id, payload.get("modo") or "normal")
```

Em `enviar`, substituir as linhas 323-325:

```python
    # **`.get` e nunca `[...]`.** Um `KeyError` aqui levantava-se DEPOIS de a
    # reserva estar feita e subia por `cron_pontos_app`, que não tem `try`
    # nenhum: a volta do cron respondia 500 e morria, parando os pontos e os
    # emails de todas as lojas em silêncio, de minuto a minuto. É a avaria que
    # o comentário logo abaixo (o `except Exception` da rede) existe para
    # impedir, e o ternário de antes nunca a podia provocar.
    acao = _ACCAO_DO_TIPO.get(linha["tipo"])
    if acao is None:
        logger.error(
            "[faturacao] pontos da app: a linha %s (%s) tem um tipo que este "
            "servidor não conhece (%r) — fica sem efeito e a volta do cron "
            "continua", linha["id"], linha["chave"], linha["tipo"])
        return await _fechar(db, linha, reserva, agora, {
            "estado": "sem_efeito", "motivo": "tipo_desconhecido"})
    corpo_do_pedido = linha["payload"]
    if linha["tipo"] == "fatura_email":
        # **Sem PDF não se chama a app.** Mandá-la enviar um email sem anexo era
        # entregar ao cliente uma fatura que não é fatura nenhuma. É falha
        # TÉCNICA (o Vendus pode estar em baixo, a conta por configurar) e por
        # isso a fila repete — com a espera crescente e as 24 h de sempre.
        try:
            pdf = await _pdf_da_fatura(linha["payload"])
        except Exception as e:  # noqa: BLE001 — o que vier do Vendus é técnico
            return await _falhou(db, linha, reserva, agora,
                                 "PDF do Vendus: %s %s" % (type(e).__name__, e))
        if not pdf:
            return await _falhou(db, linha, reserva, agora,
                                 "o Vendus não devolveu PDF nenhum")
        # O corpo é construído campo a campo e não é o payload com mais uma
        # chave: o `vendus_document_id` e o `modo` são nossos, servem para ir
        # buscar o PDF, e a app não tem nada que os receber.
        corpo_do_pedido = {
            "ligacao_id": linha["payload"]["ligacao_id"],
            "documento_id": linha["payload"]["documento_id"],
            "numero": linha["payload"].get("numero") or "",
            "pdf_base64": base64.b64encode(pdf).decode(),
        }
    try:
        resposta = await _chamar_app(acao, corpo_do_pedido)
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_documentos_do_backoffice.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py
git commit -m "A fila dos pontos aprende o tipo fatura_email

O ternário da acção passa a mapa lido com .get (um tipo novo ia para /estornar e
um KeyError matava a volta do cron), as respostas enviado/ja_enviado fecham a
linha como feita, e o envio leva 25 s porque descarrega o PDF certificado do
Vendus com o modo DO DOCUMENTO. Sem PDF a app não é chamada: a fila repete.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: O papel salta-se só quando a linha do email existe mesmo

**Files:**
- Modify: `backend/faturacao/pontos_app.py` (função nova `enfileirar_fatura_email`, a seguir a `enfileirar_credito`, linha 509)
- Modify: `backend/faturacao/fiscal.py:2296-2298`
- Test: `backend/tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py:16-26` (imports) e `:29-153`

**Interfaces:**
- Consumes: `COLECOES["pontos_qr"]` e a forma da linha `{ligacao_id, fatura_por_email}` (Task 1); `_ACCAO_DO_TIPO["fatura_email"]` (Task 2).
- Produces: `async enfileirar_fatura_email(db, venda: Dict, documento: Dict, *, agora: Optional[datetime] = None) -> bool` em `faturacao/pontos_app.py`. A linha nasce com `loja_id` — **a Task 6 conta por ele.**

- [ ] **Step 1: Escrever o teste que falha**

Em `backend/tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py`, acrescentar `from faturacao import pontos_app as pa` aos imports (a seguir à linha 21, `from faturacao import impressao as imp`), e substituir o bloco das linhas 29-153 por:

```python
@pytest.fixture(autouse=True)
def _indice_confirmado():
    """A rota `finalizar` recusa emitir sem o índice de idempotência
    confirmado no arranque (I3). É a mesma marca que `test_fiscal.py` põe, e
    é posta aqui pela mesma razão: sem ela estes testes mediam o 503 da
    configuração em falta e nunca chegavam ao papel."""
    db_mod.marcar_indice_idempotencia(True)
    yield
    db_mod.marcar_indice_idempotencia(None)


@pytest.fixture
def envios(monkeypatch):
    """A tentativa imediata substituída por um registo. Aqui prova-se o PAPEL:
    uma tarefa em segundo plano a falar com a app ficava viva depois do teste, e
    o asyncio só guarda referências FRACAS às tarefas (molde de
    `test_os_pontos_da_app.envios`)."""
    enviados = []
    monkeypatch.setattr(pa, "tentar_ja", lambda db, linha_id: enviados.append(linha_id))
    return enviados


class Explode:
    """Uma colecção que levanta em CADA escrita — o Atlas em baixo a meio de uma
    emissão que já entregou a fatura à Autoridade Tributária."""

    async def insert_one(self, doc):
        raise RuntimeError("Atlas em baixo")


def _chave_do_trabalho(doc):
    return doc.get("chave")


def _com_fila(db, qr=()):
    """Acrescenta ao duplo de `test_fiscal` as três colecções deste fio, com os
    índices únicos a serem cumpridos.

    **`fat_pontos_app` com `unico=` e não à solta:** o `DbFalsa.__getitem__` faz
    `setdefault`, por isso uma colecção nova nasce SEM índice nenhum — e uma
    prova de que a mesma emissão não manda dois emails passava por acaso. A
    chave é a mesma do índice de `db.py` (`fat_pontos_app.chave`), e é ela que
    decide se uma emissão a passar duas vezes faz um envio ou dois."""
    db._coleccoes[COLECOES["trabalhos_impressao"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    db._coleccoes[COLECOES["pontos_app"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    db._coleccoes[COLECOES["pontos_qr"]] = ColeccaoFalsa([], list(qr))
    return db


def _fila(db):
    return db._coleccoes[COLECOES["trabalhos_impressao"]]._documentos


def _emails(db):
    return [linha for linha in db._coleccoes[COLECOES["pontos_app"]]._documentos
            if linha["tipo"] == "fatura_email"]


# --- A emissão ----------------------------------------------------------------


class _VendusNormal(tf.ClienteEmissaoVendusFalso):
    """O duplo do Vendus da rota a devolver uma fatura REAL (modo `normal`). O
    `_bruto()` de `test_fiscal` devolve `tests`, e em `tests` o papel sai sempre
    — sem isto, o caso da preferência ligada passava pela razão errada."""

    def __init__(self, chave):
        super().__init__(chave)
        self.resposta_criar = tf._bruto(modo="normal")


def _finalizar(db, monkeypatch, cliente=None, pontos_ligacao=None, nif=None):
    tf._configura_vendus_env(monkeypatch)
    monkeypatch.setattr(tf.fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(
        tf.fiscal_mod, "ClienteEmissaoVendus", cliente or tf.ClienteEmissaoVendusFalso)
    tf.ClienteEmissaoVendusFalso.instancias.clear()
    return _corre(tf.finalizar(
        "venda-1",
        tf.PedidoFinalizarVenda(
            pagamentos=[tf.PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)],
            pontos_ligacao=pontos_ligacao, nif=nif),
        operador=tf._operador(),
    ))


def _db_de_venda(qr=()):
    return _com_fila(tf._db(
        vendas=[tf._venda(linhas=[tf._linha()])],
        tipos_pagamento=[tf._tipo_pagamento()],
    ), qr=qr)


def test_FINALIZAR_uma_venda_poe_UM_papel_na_fila_e_e_o_do_CLIENTE(monkeypatch):
    """O caminho inteiro: a rota que a operadora toca, o Vendus a devolver o
    documento, e o papel na fila da loja. **Um, e não dois.**

    O dono corrigiu o pressuposto de que esta rota partia: «não tem nada a
    ver com fatura, o staff é o único que faz a impressão do pedido». A ficha
    da cozinha sai quando alguém carrega em «Imprimir Pedido»
    (`impressao.imprimir_pedido`) — que é como um balcão trabalha: pica-se,
    manda-se para a cozinha, cobra-se no fim. Emitir a fatura já não manda
    papel nenhum à cozinha; se mandasse, uma conta dividida por três mandava
    três fichas do mesmo copo.

    Apagar a linha do `finalizar` que enfileira deixa todo o
    `test_impressao.py` verde — a fila continua perfeita, e o cliente fica
    sem o documento em papel que a lei lhe deve."""
    db = _db_de_venda()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"

    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["tipo"] == imp.TALAO
    assert trabalho["loja_id"] == "loja-1"
    assert trabalho["estado"] == imp.PENDENTE
    assert imp.COZINHA not in [t["impressora"] for t in _fila(db)]


def test_o_papel_do_cliente_e_o_talao_CERTIFICADO_que_o_vendus_devolveu(monkeypatch):
    """Byte a byte o que veio da emissão, e não uma reconstrução nossa: é o
    documento fiscal em papel, com o ATCUD e o QR que a app de fidelização
    lê."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    talao = [t for t in _fila(db) if t["impressora"] == imp.CAIXA][0]
    assert base64.b64decode(talao["bytes_b64"]) == documento["talao_escpos"]


def test_a_FATURA_CONTINUA_BOA_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """**A promessa que sustenta o desenho todo.**

    Uma emissão bem sucedida — com Fatura Simplificada REAL já entregue à
    Autoridade Tributária — a devolver erro por causa do papel era o pior
    desfecho possível: o ecrã lê um erro com a venda aparentemente por emitir
    como «não saiu nada, pode repetir», e a operadora emite a segunda fatura
    do mesmo cliente.

    Aqui a fila rebenta em cheio (a colecção levanta em cada escrita) e a
    resposta da rota tem de sair igual: venda emitida, documento gravado."""
    db = _db_de_venda()
    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"
    assert resultado["documento"]["atcud"] == "ATCUD-1"


def test_um_RETRY_da_mesma_emissao_nao_faz_um_segundo_talao(monkeypatch):
    """A rota é idempotente por desenho: a segunda tentativa encontra o
    documento já gravado e devolve-o tal e qual. Sem a chave da fila, essa
    segunda passagem enfileirava um segundo talão do mesmo cliente — e a
    operadora ficava com dois papéis iguais sem saber qual era qual."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    # A venda volta a `aberta` sem se lhe tirar a reserva nem o documento: é o
    # retrato de um retry que chega depois de a fatura já ter saído.
    db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "aberta"
    _finalizar(db, monkeypatch)
    assert len(_fila(db)) == 1


# --- O papel que NÃO sai: a fatura por email ------------------------------------
#
# Os quatro casos do desenho, todos pela ROTA REAL. A regra que os une: o papel
# só se salta quando a linha do email foi MESMO criada — as duas decisões são
# uma só, e não há desfecho em que não saia nem papel nem email.

_LIGACAO = {"id": "lig-1", "primeiro_nome": "Ana"}
_QR_LIGADO = [{"ligacao_id": "lig-1", "fatura_por_email": True}]


def test_1_SEM_LIGACAO_sai_papel_e_nao_ha_linha_de_email_nenhuma(monkeypatch, envios):
    """O caso normal, que é o de quase toda a gente: quem não mostra a app leva
    talão, como sempre."""
    db = _db_de_venda()

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1
    assert _emails(db) == []


def test_2_COM_A_PREFERENCIA_LIGADA_nao_sai_papel_e_fica_a_linha_do_email(monkeypatch, envios):
    """O caso que a funcionalidade existe para fazer. A preferência é lida de
    `fat_pontos_qr` — do servidor — e não do corpo do EMITIR."""
    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal,
                           pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert _fila(db) == [], "com a fatura a ir por email, o talão não se imprime"
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    [linha] = _emails(db)
    assert linha["chave"] == "fatura_email:%s" % documento["id"]
    assert linha["loja_id"] == "loja-1", "a loja é por onde o alarme do POS conta"
    assert linha["payload"] == {
        "ligacao_id": "lig-1",
        "documento_id": documento["id"],
        "vendus_document_id": documento["vendus_document_id"],
        "numero": "FS 2026/1",
        "modo": "normal",
    }
    # **`in` e não `== [id]`.** Nesta MESMA chamada a `finalizar`, o
    # `_ligar_venda_ao_documento` já enfileirou o crédito dos pontos
    # (`fiscal.py:1431-1433`) — modo normal, ligação gravada na venda antes da
    # emissão, ATCUD presente — e o `_enfileirar` de lá também chama
    # `tentar_ja`. O id do crédito está na lista ANTES de o papel se decidir; o
    # que se prende aqui é que o do email também lá vai parar.
    assert linha["id"] in envios, "a tentativa imediata do email tem de sair logo"


def test_2b_a_MESMA_emissao_a_passar_duas_vezes_manda_UM_email_e_nao_traz_papel(monkeypatch, envios):
    """**O `DuplicateKeyError` conta como sucesso.** O gancho da emissão corre
    mais do que uma vez por venda (o retry que reencontra o documento, a
    reconciliação de uma reserva presa); devolver `False` na segunda passagem
    fazia sair papel numa fatura que já ia por email."""
    db = _db_de_venda(qr=_QR_LIGADO)
    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)
    db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "aberta"

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_emails(db)) == 1
    assert _fila(db) == [], "a segunda passagem não pode fazer sair papel"


def test_3_com_a_FILA_DO_EMAIL_a_rebentar_o_PAPEL_SAI_a_mesma(monkeypatch, envios):
    """**O desfecho que não pode existir é não sair nem papel nem email.** Aqui
    a colecção da fila levanta em cada escrita: a linha do email não chega a
    existir, `enfileirar_fatura_email` devolve `False`, e o talão sai como se
    nada disto existisse — com a resposta da rota igual, porque as duas chamadas
    estão no mesmo `try/except`."""
    db = _db_de_venda(qr=_QR_LIGADO)
    db._coleccoes[COLECOES["pontos_app"]] = Explode()

    resultado = _finalizar(db, monkeypatch, cliente=_VendusNormal,
                           pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1, "sem linha de email, o papel tem de sair"


def test_4_em_MODO_TESTS_sai_papel_e_nao_se_manda_email_nenhum(monkeypatch, envios):
    """Uma fatura em `tests` não existe na AT. Mandá-la por email ao cliente era
    entregar-lhe um papel com ar de fatura que não é fatura nenhuma — e o `mode`
    de um documento de testes nem sequer devolve PDF pela porta normal."""
    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1
    assert _emails(db) == []


def test_uma_fatura_SEM_ID_DO_VENDUS_sai_em_PAPEL(monkeypatch, envios):
    """**A guarda que impede o único desfecho proibido.** O Vendus só é recusado
    quando faltam o `id` E o `atcud` (`vendus/emissao._documento_da_criacao`):
    um 2xx com ATCUD e sem `id` é aceite de propósito e grava
    `vendus_document_id: None` — é por isso que o botão «PDF da fatura» do
    backoffice tem um 422 dedicado (`documentos._MSG_SEM_ID_NO_VENDUS`).

    Sem esta guarda o papel saltava-se e `_pdf_da_fatura` devolvia `b""` para
    sempre: 13 tentativas, `falhado` às 24 h, e o cliente sem talão E sem
    email."""
    class _SemId(_VendusNormal):
        def __init__(self, chave):
            super().__init__(chave)
            self.resposta_criar = tf._bruto(modo="normal", id=None)

    db = _db_de_venda(qr=_QR_LIGADO)

    resultado = _finalizar(db, monkeypatch, cliente=_SemId, pontos_ligacao=_LIGACAO)

    assert resultado["estado"] == "emitida"
    assert len(_fila(db)) == 1, "sem id do Vendus não há PDF — o papel tem de sair"
    assert _emails(db) == []


def test_com_NIF_ESCRITO_o_papel_sai_a_mesma(monkeypatch, envios):
    """O NIF é por parte da conta e a ligação do QR é de quem mostrou a app:
    quando divergem, a fatura da empresa ia para a caixa de correio do colega.
    Quem escreve um NIF quer o documento ali."""
    db = _db_de_venda(qr=_QR_LIGADO)

    _finalizar(db, monkeypatch, cliente=_VendusNormal,
               pontos_ligacao=_LIGACAO, nif="219363935")

    assert len(_fila(db)) == 1
    assert _emails(db) == []


def test_sem_LINHA_NO_QR_o_papel_sai_mesmo_com_a_ligacao_na_venda(monkeypatch, envios):
    """A ligação na venda não chega: um `pontos_ligacao` forjado no corpo do
    EMITIR não pode fazer desaparecer o documento de ninguém. Sem a linha do
    servidor — porque expirou, porque a escrita falhou, porque o cliente não
    pediu — sai papel."""
    db = _db_de_venda()

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_fila(db)) == 1
    assert _emails(db) == []


def test_com_a_preferencia_DESLIGADA_na_linha_do_qr_sai_papel(monkeypatch, envios):
    db = _db_de_venda(qr=[{"ligacao_id": "lig-1", "fatura_por_email": False}])

    _finalizar(db, monkeypatch, cliente=_VendusNormal, pontos_ligacao=_LIGACAO)

    assert len(_fila(db)) == 1
    assert _emails(db) == []
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py -q`

Expected: FAIL — `test_2_COM_A_PREFERENCIA_LIGADA_nao_sai_papel_e_fica_a_linha_do_email` com `AssertionError: assert [{...talao...}] == []` (o papel continua a sair) e `ValueError: not enough values to unpack (expected 1, got 0)` na linha do email.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/pontos_app.py`, a seguir a `enfileirar_credito` (linha 509) e antes do comentário `# --- O estorno, na nota de crédito`:

```python
# --- A fatura por email, na emissão ---------------------------------------------


async def enfileirar_fatura_email(db, venda: Dict, documento: Dict, *,
                                  agora: Optional[datetime] = None) -> bool:
    """Põe na fila o envio por email desta Fatura Simplificada. **Devolve `True`
    só quando, no fim, existe mesmo a linha `fatura_email:<documento_id>`** — e
    é por esse `True` que `fiscal.finalizar` decide não pôr papel na fila.

    As duas decisões são UMA: o papel só se salta se o email foi mesmo
    enfileirado. Nunca há desfecho em que não saia papel nem email.

    Devolve `False` — e o talão sai como sempre — quando:

    - `documento["modo"] != "normal"`: uma fatura em `tests` não existe na AT, e
      o Vendus nem devolve PDF dela pela porta normal;
    - `documento["vendus_document_id"]` está vazio: **sem o id do Vendus não há
      PDF para ir buscar**, hoje nem daqui a um mês. O Vendus só é recusado
      quando faltam o `id` E o `atcud` (`vendus/emissao._documento_da_criacao`),
      por isso um 2xx com ATCUD e sem `id` é aceite de propósito e gravado com
      `vendus_document_id: None` — é o caso que `documentos.pdf_do_documento`
      traduz num 422 dedicado. Saltar o papel aqui era 13 tentativas de um PDF
      que nunca vem e o cliente sem talão E sem email;
    - a venda não tem `pontos_ligacao`: sem QR não há para onde enviar;
    - não há linha em `fat_pontos_qr` para aquela ligação, ou ela diz `False`:
      **é essa linha, do servidor, que decide**. Um `pontos_ligacao` forjado no
      corpo do EMITIR não pode fazer desaparecer o documento de ninguém;
    - `venda["cliente_nif"]` está preenchido: o NIF é por parte da conta e a
      ligação é de quem mostrou a app — quando divergem, a fatura da empresa ia
      para a caixa de correio do colega. Quem escreve um NIF quer o papel ali;
    - a escrita falhou por qualquer razão.

    **Um `DuplicateKeyError` conta como `True`.** A linha já lá estava — o
    gancho da emissão corre mais do que uma vez por venda — e devolver `False`
    aí fazia sair papel numa fatura que já ia por email.

    **Não herda a guarda do ATCUD do `enfileirar_credito`**: um documento REAL
    pode não o ter, a app precisa dele para deduplicar os PONTOS, e o email
    precisa é do id do VENDUS (acima). Herdá-la era o caso em que não sai papel
    nem email e não fica linha nenhuma para alguém ver.

    A venda vem de quem chama e é a GRAVADA (`fiscal.py:2271`), nunca o corpo do
    pedido: quem perde a corrida da reserva também chega àquela linha, e só a
    venda gravada tem a verdade.

    **O PDF não entra na linha**, só o id do documento e o modo com que ele foi
    emitido: a fila não tem TTL e fica para sempre, e 92 KB por fatura para
    sempre não. Quem o vai buscar é o envio (`_pdf_da_fatura`)."""
    if documento.get("modo") != "normal":
        return False
    if not documento.get("vendus_document_id"):
        logger.error(
            "[faturacao] a fatura %s não tem id do Vendus — sem ele não há PDF "
            "para enviar, e o talão sai em PAPEL como sempre", documento["id"])
        return False
    ligacao = (venda or {}).get("pontos_ligacao") or {}
    if not ligacao.get("id"):
        return False
    if (venda.get("cliente_nif") or "").strip():
        return False

    linha = _linha_nova(
        "fatura_email", "fatura_email:%s" % documento["id"],
        {
            "ligacao_id": str(ligacao["id"]),
            "documento_id": documento["id"],
            # Nosso e não da app: é por ele que se pede o PDF ao Vendus.
            "vendus_document_id": documento.get("vendus_document_id"),
            # `or ""` e não o `.get` cru, pela razão do crédito: em pydantic 2
            # um `None` explícito NÃO cai no default de um `str`.
            "numero": documento.get("numero") or "",
            # **O modo DO DOCUMENTO**, carimbado agora: um documento emitido em
            # `tests` pedido com `mode=normal` responde 404, e o botão que muda
            # o modo da loja não pode partir o reenvio de faturas antigas.
            "modo": documento.get("modo") or "normal",
        },
        agora or datetime.now(timezone.utc),
        documento_id=documento["id"], venda_id=venda.get("id"),
        # **A loja vai na linha**, e é por ela que o alarme do POS conta os
        # envios sem saída (`impressao.estado_da_impressao`).
        loja_id=venda.get("loja_id"),
        primeiro_nome=ligacao.get("primeiro_nome"))

    # A leitura do QR e a escrita da linha DENTRO do mesmo `try`: se a leitura
    # rebentasse cá fora, o `except` da rota do finalizar engolia-a e não saía
    # papel NEM email — o único desfecho que este desenho não admite.
    try:
        marca = await db[COLECOES["pontos_qr"]].find_one(
            {"ligacao_id": str(ligacao["id"])}, {"_id": 0, "fatura_por_email": 1})
        if not (marca or {}).get("fatura_por_email"):
            return False
        await db[COLECOES["pontos_app"]].insert_one(dict(linha))
    except DuplicateKeyError:
        return True
    except Exception as e:  # noqa: BLE001 — sem linha, o papel sai
        logger.error(
            "[faturacao] a fatura %s não entrou na fila do email (o talão sai em "
            "papel): %s", documento["id"], e)
        return False
    tentar_ja(db, linha["id"])
    return True
```

Em `backend/faturacao/fiscal.py`, substituir as linhas 2296-2298:

```python
    try:
        from .impressao import enfileirar_venda_emitida
        from .pontos_app import enfileirar_fatura_email
        # **As duas decisões são UMA.** O papel só se salta quando a linha do
        # email foi MESMO criada — `enfileirar_fatura_email` devolve `True` só
        # nesse caso, e devolve `False` para tudo o resto (modo de testes, sem
        # id do Vendus, sem QR lido, sem a marca do servidor em `fat_pontos_qr`,
        # com NIF escrito, escrita falhada). Nunca há desfecho em que o cliente
        # fique sem talão E sem email.
        #
        # A venda é a `venda_actualizada` e nunca o corpo do pedido: quem perde
        # a corrida da reserva (`_esperar_documento_do_vencedor`) também chega
        # aqui, e só a venda gravada tem a ligação e o NIF que valeram.
        if not await enfileirar_fatura_email(db, venda_actualizada or venda, documento):
            await enfileirar_venda_emitida(db, venda_actualizada or venda, documento)
    except Exception as e:  # noqa: BLE001 — perde-se o papel, nunca o registo
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py tests/faturacao/test_fiscal.py tests/faturacao/test_impressao.py tests/faturacao/test_os_pontos_da_app.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/pontos_app.py backend/faturacao/fiscal.py \
        backend/tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py
git commit -m "O talão salta-se só quando a linha do email existe mesmo

enfileirar_fatura_email devolve True só com a linha fatura_email:<doc> na fila,
e o finalizar passa a pôr papel apenas quando ela devolve False. A preferência
lê-se de fat_pontos_qr e a venda de venda_actualizada — nunca do corpo. Sem id
do Vendus não há PDF e o papel sai. Um DuplicateKeyError conta como sucesso.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: O envio do email visível no detalhe do documento

**Files:**
- Modify: `backend/faturacao/pontos_app.py:590-606` (`pontos_app_do_documento`)
- Modify: `backend/faturacao/documentos.py:846-855`
- Test: `backend/tests/faturacao/test_documentos_do_backoffice.py:283-364` (a secção dos pontos; o bloco novo vai a seguir à linha 364)

**Interfaces:**
- Consumes: a chave `fatura_email:<documento_id>` (Task 3).
- Produces: `pontos_app_do_documento(db, documento) -> Dict` passa a devolver `{"pontos": Optional[Dict], "fatura_email": Optional[Dict]}` (já não `Optional[Dict]`). `GET /documentos/{id}` ganha a chave `fatura_email` **sem mexer em `pontos_app`**, que continua exactamente com a forma de hoje — é o que a frente do backoffice (`FatDocumentos.js`) lê. `pontos_app._CAMPOS_PARA_O_ECRA` inclui `motivo` e `ultimo_erro` — **a Task 5 limpa-os ao reenviar por causa disto.**

- [ ] **Step 1: Escrever o teste que falha**

Em `backend/tests/faturacao/test_documentos_do_backoffice.py`, a seguir a `test_o_detalhe_do_POS_continua_SEM_a_linha_dos_pontos` (linha 364):

```python
# --- O envio da fatura por email, no mesmo detalhe -------------------------------


def _linha_de_email(documento_id, **over):
    linha = _linha_de_pontos("fatura_email:%s" % documento_id,
                             tipo="fatura_email", pontos=None)
    linha["payload"] = {"ligacao_id": "lig-1", "documento_id": documento_id,
                        "vendus_document_id": 368200354, "modo": "normal"}
    linha.update(over)
    return linha


def test_o_detalhe_da_fatura_diz_o_estado_do_ENVIO_POR_EMAIL(monkeypatch):
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:d1"),
                _linha_de_email("d1", estado="falhado", tentativas=13,
                                ultimo_erro="HTTP 503: em baixo"))

    r = _corre(documento_do_backoffice("d1", _={}))

    assert r["fatura_email"]["estado"] == "falhado"
    assert (r["fatura_email"]["tentativas"], r["fatura_email"]["ultimo_erro"]) \
        == (13, "HTTP 503: em baixo")
    assert r["pontos_app"]["estado"] == "feito", "a linha dos pontos fica como estava"


def test_uma_fatura_SEM_ATCUD_mostra_o_email_ainda_que_nao_tenha_pontos(monkeypatch):
    """**O caso que a procura por `credito:<id>` deixava invisível.** Um
    documento REAL pode não ter ATCUD, e sem ele `enfileirar_credito` não cria
    linha nenhuma (a app deduplica os pontos por ele). O envio do email NÃO
    herda essa guarda — existe à mesma, e é exactamente a fatura em que alguém
    precisa de ver o que lhe aconteceu."""
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_email("d1"))

    r = _corre(documento_do_backoffice("d1", _={}))

    assert r["pontos_app"] is None
    assert r["fatura_email"]["estado"] == "feito"


def test_uma_fatura_sem_envio_por_email_tem_a_chave_a_None(monkeypatch):
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:d1"))
    assert _corre(documento_do_backoffice("d1", _={}))["fatura_email"] is None


def test_o_corpo_do_envio_tambem_nao_sai_para_o_ecra(monkeypatch):
    """O payload do envio leva a ligação do cliente, como o dos pontos."""
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_email("d1"))
    r = _corre(documento_do_backoffice("d1", _={}))
    assert "payload" not in r["fatura_email"] and "lig-1" not in str(r)


def test_o_detalhe_do_POS_continua_sem_o_envio_por_email(monkeypatch):
    """A mesma promessa da linha dos pontos: o balcão não mostra isto, e o
    montador é o MESMO para as duas rotas."""
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_email("d1"))
    assert "fatura_email" not in _corre(obter_documento("d1", operador={"loja_id": "loja-1"}))
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_documentos_do_backoffice.py -q`

Expected: FAIL com `KeyError: 'fatura_email'` em `test_o_detalhe_da_fatura_diz_o_estado_do_ENVIO_POR_EMAIL` (e nos outros quatro da secção nova).

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/pontos_app.py`, substituir `pontos_app_do_documento` (linhas 590-606):

```python
# Só os campos que o ecrã escreve («17 pontos para Ana», «A tentar enviar (3
# tentativas — último erro: …)», «Recusado: pagamento por plataforma»). O corpo
# enviado à app fica de fora: tem a ligação do cliente, e o ecrã não precisa
# dela para nada.
_CAMPOS_PARA_O_ECRA = (
    "tipo", "estado", "pontos", "primeiro_nome", "motivo",
    "tentativas", "ultimo_erro", "atualizado_em")


async def _linha_para_o_ecra(db, chave: str) -> Optional[Dict]:
    linha = await db[COLECOES["pontos_app"]].find_one({"chave": chave}, {"_id": 0})
    if not linha:
        return None
    return {campo: linha.get(campo) for campo in _CAMPOS_PARA_O_ECRA}


async def pontos_app_do_documento(db, documento: Dict) -> Dict:
    """As duas linhas da fila que o detalhe de um documento no backoffice
    mostra: `pontos` (numa fatura o crédito, numa nota de crédito o estorno
    DELA) e `fatura_email` (o envio da fatura por email). Cada uma `None` quando
    não existe — o cliente não mostrou a app, ou levou talão.

    **Duas e não uma, porque nem sempre andam juntas.** Um documento REAL sem
    ATCUD não chega a ter linha de crédito (`enfileirar_credito` desiste, a app
    deduplica os pontos por ele) e tem linha de email à mesma — o envio não
    herda essa guarda. Procurar só por `credito:<id>` deixava esse envio
    invisível para toda a gente, e é exactamente a fatura em que alguém precisa
    de o ver."""
    tipo = "estorno" if documento.get("tipo") == "NC" else "credito"
    return {
        "pontos": await _linha_para_o_ecra(db, "%s:%s" % (tipo, documento.get("id"))),
        # Uma nota de crédito nunca tem linha de email (as notas saem sempre em
        # papel — a devolução é o momento em que o cliente está chateado), e a
        # chave `fatura_email:<nc-id>` não existe: dá `None` por si só.
        "fatura_email": await _linha_para_o_ecra(
            db, "fatura_email:%s" % documento.get("id")),
    }
```

Em `backend/faturacao/documentos.py`, substituir as linhas 846-855 (a última frase da docstring e o corpo):

```python
    Mais as duas linhas da fila da app, que só o gestor vê: **«Pontos L'Açaí»**
    (`pontos_app` — numa fatura o crédito, numa nota de crédito o estorno dela)
    e **o envio da fatura por email** (`fatura_email`). `None` cada uma quando
    não existe. O balcão não precisa delas e o POS não as lê."""
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    resposta = await _detalhe_do_documento(db, documento, com_contexto=True)
    linhas_da_app = await pontos_app_do_documento(db, documento)
    # Duas chaves e não um objecto aninhado: `pontos_app` fica com a forma
    # EXACTA de hoje, que é a que o `FatDocumentos.js` já lê.
    resposta["pontos_app"] = linhas_da_app["pontos"]
    resposta["fatura_email"] = linhas_da_app["fatura_email"]
    return resposta
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_documentos_do_backoffice.py tests/faturacao/test_documentos.py tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/pontos_app.py backend/faturacao/documentos.py \
        backend/tests/faturacao/test_documentos_do_backoffice.py
git commit -m "O detalhe do documento mostra o envio da fatura por email

pontos_app_do_documento passa a devolver as duas linhas da fila. Uma fatura sem
ATCUD não tem crédito e tem envio à mesma — procurar só por credito:<id>
deixava-o invisível. A chave pontos_app fica com a forma de hoje.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Reenviar a fatura por email (gestor, qualquer documento)

**Files:**
- Modify: `backend/faturacao/pontos_app.py:37-40` (import de `gestor_atual`) e o fim do ficheiro (rota nova, na secção «O backoffice»)
- Test: `backend/tests/faturacao/test_os_pontos_da_app.py` (secção nova «Reenviar», no fim do ficheiro)

**Interfaces:**
- Consumes: `_NUNCA`, `_iso`, `tentar_ja` e a chave `fatura_email:<documento_id>` (Tasks 2 e 3); `_CAMPOS_PARA_O_ECRA` (Task 4) — é por ele que `ultimo_erro` e `motivo` chegam ao ecrã, e é por isso que esta rota os limpa.
- Produces: `POST /api/faturacao/documentos/{documento_id}/reenviar-email` (gestor) → `{"reenviado": True, "estado": "pendente"}`, 404 com `_MSG_SEM_LINHA_DE_EMAIL` quando não há linha.

> **Nota de caminho, deliberada.** O desenho escreve `POST /pos/faturacao/documentos/{id}/reenviar-email`, mas o router do módulo já é montado com `prefix="/api/faturacao"` (`faturacao/__init__.py:33`): à letra, o endereço real ficava `/api/faturacao/pos/faturacao/documentos/...`, com «faturacao» duas vezes e um «pos» numa rota de gestor — e o prefixo `/api/faturacao/pos/` obriga, por `test_protecao_rotas.py`, ao mecanismo do POS em vez de `gestor_atual`. Usa-se o irmão que já existe — `@router.post("/documentos/{documento_id}/reimprimir")` (`impressao.py:924`), também de gestor, também sobre o documento — e o teste do caminho afirma o endereço **montado**, para a frente do backoffice não ter de o adivinhar.

- [ ] **Step 1: Escrever o teste que falha**

No fim de `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python
# --- Reenviar a fatura por email -------------------------------------------------
#
# **Para QUALQUER documento, não só para os falhados.** O caso frequente é «não
# me chegou» com a linha em `feito` — a caixa cheia, o relay da Apple com o
# reencaminhamento desligado, o email na pasta do spam. Um botão que só
# funcionasse sobre linhas falhadas não servia para o caso que existe.


def _linha_reposta(fila):
    return fila.linhas()[0]


def test_reenviar_repoe_os_SETE_campos_e_manda_ja(monkeypatch):
    """**Repor só o estado é um botão que dá uma tentativa e volta logo a
    `falhado`.** Com `tentativas: 13` e `primeira_falha_tecnica_em` de ontem, a
    primeira falha a seguir ao toque passava dos 24 h e desistia na hora; com
    `proxima_tentativa_em` no futuro, a linha ficava pendente meia hora sem
    ninguém perceber porquê; e com `a_enviar_ate` de uma reserva presa, o
    `find_one_and_update` de `enviar` nunca mais lhe pegava.

    E o `ultimo_erro`/`motivo` da falha anterior TÊM de sair com os outros: o
    detalhe do documento mostra os dois (`_CAMPOS_PARA_O_ECRA`), e uma linha
    acabada de repor a pendente a dizer «0 tentativas — último erro: HTTP 503»
    é o ecrã a mentir ao gestor sobre o estado de agora."""
    enviados = []
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: enviados.append(linha_id))
    db, fila = _db_da_fila(_fatura_email(
        estado="falhado", tentativas=13,
        primeira_falha_tecnica_em=_iso(AGORA - timedelta(hours=30)),
        proxima_tentativa_em=_iso(AGORA + timedelta(minutes=30)),
        a_enviar_ate=_iso(AGORA + timedelta(hours=3)),
        ultimo_erro="HTTP 503: em baixo", motivo="contrato_recusado"))
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)

    resposta = _corre(pontos_app.reenviar_fatura_por_email("doc-1", _={}))

    linha = _linha_reposta(fila)
    assert linha["estado"] == "pendente"
    assert linha["tentativas"] == 0
    assert linha["primeira_falha_tecnica_em"] is None
    assert linha["proxima_tentativa_em"] <= pontos_app._iso(
        datetime.now(timezone.utc))
    assert linha["a_enviar_ate"] == pontos_app._NUNCA
    assert linha["ultimo_erro"] is None
    assert linha["motivo"] is None
    assert enviados == [linha["id"]], "a tentativa imediata é DEPOIS da escrita"
    assert resposta["reenviado"] is True


def test_reenviar_serve_uma_linha_ja_FEITA(monkeypatch):
    """«Não me chegou» é o caso frequente, e a linha dele está em `feito`."""
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: None)
    db, fila = _db_da_fila(_fatura_email(estado="feito"))
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)

    _corre(pontos_app.reenviar_fatura_por_email("doc-1", _={}))

    assert _linha_reposta(fila)["estado"] == "pendente"


def test_reenviar_uma_fatura_que_nunca_teve_email_e_404(monkeypatch):
    """Não se inventa um envio: sem QR lido não há para onde mandar, e o que
    esta fatura tem é o botão de reimprimir na loja."""
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: None)
    db, _ = _db_da_fila(_credito())
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(pontos_app.reenviar_fatura_por_email("doc-1", _={}))

    assert e.value.status_code == 404


def test_a_rota_de_reenviar_esta_montada_no_router_e_e_ESTE_o_endereco():
    """O endereço afirmado é o MONTADO, com o prefixo do módulo — afirmar o
    caminho que o código escreve nunca apanha um prefixo errado, e é isso que já
    partiu o POS três vezes."""
    from faturacao import router
    caminhos = {(metodo, r.path) for r in router.routes for metodo in r.methods}
    assert ("POST", "/api/faturacao/documentos/{documento_id}/reenviar-email") in caminhos
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py -q -k reenviar`

Expected: FAIL com `AttributeError: module 'faturacao.pontos_app' has no attribute 'reenviar_fatura_por_email'`.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/pontos_app.py`, acrescentar `from .auth import gestor_atual` aos imports (imediatamente antes de `from .db import COLECOES, obter_db`) e, no fim do ficheiro:

```python
_MSG_SEM_LINHA_DE_EMAIL = (
    "Esta fatura não tem envio por email — o cliente não mostrou a app na caixa, "
    "ou pediu o talão. O documento fiscal continua bom e reimprime-se na loja."
)


@router.post("/documentos/{documento_id}/reenviar-email")
async def reenviar_fatura_por_email(
    documento_id: str, _: dict = Depends(gestor_atual)
) -> dict:
    """«Reenviar» — a fatura volta à fila do email. **Para QUALQUER documento
    com linha, não só para os falhados.**

    O caso frequente não é o da linha vermelha: é «não me chegou» com a linha em
    `feito`. «Enviado» aqui quer dizer «o Resend aceitou», não «entregou» — uma
    caixa cheia, um relay com o reencaminhamento desligado, a pasta do spam.
    Deixar este botão só para as falhadas era não ter botão nenhum para o
    problema que as pessoas trazem.

    **Repõe SETE campos numa escrita, e só depois manda.** Repor só o estado é
    um botão que dá uma tentativa e volta logo a `falhado`:

    - `tentativas` a 0, senão a espera seguinte começa já nos 30 minutos;
    - `primeira_falha_tecnica_em` a `None`, senão o relógio das 24 h vinha de
      ontem e a primeira falha a seguir ao toque desistia na hora;
    - `proxima_tentativa_em` a agora, senão a linha ficava à espera da hora que
      a última falha lhe marcou;
    - `a_enviar_ate` ao `_NUNCA`, senão uma reserva presa de um processo morto
      fazia o `find_one_and_update` de `enviar` nunca mais lhe pegar;
    - `estado` a `pendente`, que é o que o cron procura;
    - `ultimo_erro` e `motivo` a `None`, porque são o que o detalhe do documento
      ESCREVE no ecrã (`_CAMPOS_PARA_O_ECRA`): deixados lá, o gestor lia «A
      tentar enviar (0 tentativas — último erro: HTTP 503: em baixo)» ou
      «Recusado: contrato_recusado» sobre uma linha acabada de repor.

    Uma escrita condicional só no fim (`find_one_and_update`) e não uma leitura
    seguida de um `update`: duas pessoas a carregar no botão ao mesmo tempo
    escrevem a mesma coisa, e a resposta traz a linha como ficou.

    **Não cria linha nenhuma.** Uma fatura sem envio por email é uma fatura sem
    QR lido: não há endereço para onde mandar, e inventar um destinatário era
    mandar o documento de um cliente para a conta de outro. O que essa fatura
    tem é o «Imprimir» do separador Faturação."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    linha = await db[COLECOES["pontos_app"]].find_one_and_update(
        {"chave": "fatura_email:%s" % documento_id},
        {"$set": {
            "estado": "pendente",
            "tentativas": 0,
            "primeira_falha_tecnica_em": None,
            "proxima_tentativa_em": _iso(agora),
            "a_enviar_ate": _NUNCA,
            "ultimo_erro": None,
            "motivo": None,
            "atualizado_em": _iso(agora),
        }},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if linha is None:
        raise HTTPException(status_code=404, detail=_MSG_SEM_LINHA_DE_EMAIL)
    tentar_ja(db, linha["id"])
    return {"reenviado": True, "estado": linha["estado"]}
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_protecao_rotas.py tests/faturacao/test_caminhos_do_pos.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py
git commit -m "Botão de reenviar a fatura por email, para qualquer documento

O caso frequente é «não me chegou» com a linha em feito. Repõe os sete campos
numa escrita — estado, tentativas, relógio das 24 h, próxima tentativa, reserva,
último erro e motivo — e só depois manda; repor só o estado dava uma tentativa e
voltava a falhado, e o erro antigo ficava a mentir no ecrã do gestor.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: A loja vê os envios sem saída no alarme que já tem

**Files:**
- Modify: `backend/faturacao/impressao.py:741-788` (`estado_da_impressao`)
- Modify: `backend/faturacao/db.py:386-389` (índice novo em `INDICES`)
- Test: `backend/tests/faturacao/test_impressao.py` (secção nova no fim do ficheiro, a seguir à linha 1298)
- Test: `backend/tests/faturacao/test_indices.py` (teste novo a seguir a `test_a_pergunta_do_programa_da_loja_tem_indice_e_traz_a_ORDEM`, linha 280)

**Interfaces:**
- Consumes: `loja_id` na linha `fatura_email` (Task 3) e os estados que `_fechar`/`_falhou` escrevem (Task 2).
- Produces: `GET /pos/impressao/estado` ganha a chave `emails_falhados: int`. As chaves `ha_programa`, `ultima_recolha_em`, `por_sair` e `falhados` ficam como estão. `db.INDICES` ganha `("fat_pontos_app", [("loja_id", 1), ("tipo", 1), ("estado", 1)], {})`.

- [ ] **Step 1: Escrever o teste que falha**

No fim de `backend/tests/faturacao/test_impressao.py` (a seguir à linha 1298):

```python
# --- 12. Os envios por email SEM SAÍDA ---------------------------------------
#
# Uma fatura que ia por email e não foi **não tem papel a compensá-la** — ao
# contrário de tudo o resto desta fila, onde o talão está sempre a um toque de
# distância no separador Faturação. O POS já pergunta por este estado de 20 em
# 20 segundos: é o caminho mais barato para a falha chegar a uma pessoa no
# mesmo dia, e não se faz lista nova nenhuma por causa disso.


def _linha_de_email(**over):
    linha = {"id": "fe-1", "chave": "fatura_email:doc-1", "tipo": "fatura_email",
             "loja_id": "loja-1", "estado": "falhado"}
    linha.update(over)
    return linha


def _com_emails(db, *linhas):
    db._coleccoes[COLECOES["pontos_app"]] = ColeccaoFalsa([], list(linhas))
    return db


@pytest.mark.parametrize("estado", ["falhado", "recusado", "sem_efeito"])
def test_um_envio_sem_saida_acende_o_alarme_da_loja(monkeypatch, estado):
    """Os três são becos sem saída: nenhum volta a ser tentado sozinho, e em
    nenhum deles saiu papel."""
    db = _com_emails(_db(), _linha_de_email(estado=estado))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    assert _corre(estado_da_impressao(operador=_operador()))["emails_falhados"] == 1


@pytest.mark.parametrize("estado", ["pendente", "feito"])
def test_um_envio_a_caminho_ou_feito_nao_acende_nada(monkeypatch, estado):
    """Um `pendente` ainda vai ser tentado (a fila corre de minuto a minuto) e
    um `feito` já saiu. Acusar qualquer um deles era um aviso que se aprende a
    ignorar."""
    db = _com_emails(_db(), _linha_de_email(estado=estado))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    assert _corre(estado_da_impressao(operador=_operador()))["emails_falhados"] == 0


def test_o_alarme_e_da_LOJA_e_nao_das_outras(monkeypatch):
    """Cinco lojas partilham a colecção; a operadora de Belém não pode ver o
    envio falhado de Oeiras — e ainda menos carregar em «Já vi» por ele."""
    db = _com_emails(_db(),
                     _linha_de_email(estado="falhado"),
                     _linha_de_email(id="fe-2", chave="fatura_email:doc-2",
                                     loja_id="loja-2", estado="falhado"))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    assert _corre(estado_da_impressao(operador=_operador()))["emails_falhados"] == 1


def test_uma_linha_de_PONTOS_falhada_nao_conta_como_email_por_enviar(monkeypatch):
    """A mesma colecção guarda os créditos e os estornos. Um crédito falhado é
    chato — o cliente ficou sem pontos — mas a fatura dele SAIU em papel, e o
    aviso que este número acende diz outra coisa."""
    db = _com_emails(_db(), _linha_de_email(
        id="c-1", chave="credito:doc-1", tipo="credito", estado="falhado"))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    assert _corre(estado_da_impressao(operador=_operador()))["emails_falhados"] == 0


def test_uma_loja_SEM_envios_nenhuns_continua_a_responder_zero(monkeypatch):
    """A colecção pode nem existir — o duplo cria-a vazia, como o Mongo."""
    db = _db()
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    assert _corre(estado_da_impressao(operador=_operador()))["emails_falhados"] == 0
```

E em `backend/tests/faturacao/test_indices.py`, a seguir a `test_a_pergunta_do_programa_da_loja_tem_indice_e_traz_a_ORDEM` (linha 280):

```python
def test_o_alarme_dos_EMAILS_por_enviar_tem_indice_na_fila_dos_pontos():
    """`impressao.estado_da_impressao` corre de 20 em 20 segundos, em cinco
    lojas, o dia inteiro — e `fat_pontos_app` **fica para sempre** (`db.py:88`),
    ao contrário da fila do papel, que tem TTL de sete dias.

    Os dois índices que já lá estavam respondem a outras perguntas: `chave` é a
    unicidade, e `(estado, proxima_tentativa_em)` é a do cron. O filtro deste
    alarme é `{loja_id, tipo, estado}` e sem índice próprio era um varrimento
    completo de uma colecção que só cresce — a mesma razão, escrita com todas as
    letras, que pôs o índice de `fat_trabalhos_impressao` aqui em cima."""
    assert ("fat_pontos_app",
            [("loja_id", 1), ("tipo", 1), ("estado", 1)], {}) in INDICES
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_impressao.py tests/faturacao/test_indices.py -q`

Expected: FAIL com `KeyError: 'emails_falhados'` nos testes novos do `test_impressao.py` e `AssertionError` em `test_o_alarme_dos_EMAILS_por_enviar_tem_indice_na_fila_dos_pontos`.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/db.py`, a seguir à linha 388 e antes do `("fat_pontos_qr", …)` da Task 1:

```python
    ("fat_pontos_app", [("estado", 1), ("proxima_tentativa_em", 1)], {}),
    # A pergunta do ALARME do balcão — «esta loja tem faturas que iam por email
    # e não foram?» — feita de 20 em 20 segundos, em cinco lojas, o dia inteiro
    # (`impressao.estado_da_impressao`). Ao contrário da fila do papel, esta
    # colecção **fica para sempre**: sem índice próprio era um varrimento
    # completo de uma colecção que só cresce, e os dois índices de cima
    # respondem a outras perguntas (a unicidade e a do cron).
    ("fat_pontos_app", [("loja_id", 1), ("tipo", 1), ("estado", 1)], {}),
```

Em `backend/faturacao/impressao.py`, acrescentar ao fim da docstring de `estado_da_impressao` (linha 750):

```python
    E a mesma pergunta para as faturas que iam por email: **essas não têm papel
    a compensá-las**, e é por aqui que a loja fica a saber no mesmo dia.
    """
```

E, a seguir ao cálculo de `por_sair` (linha 771) e dentro do `return` (linhas 772-788):

```python
    # **As faturas que iam por email e não foram.** O único caso desta loja em
    # que falta um documento ao cliente e **não há papel a compensá-lo**: em
    # tudo o resto desta fila, o talão está a um toque de distância no separador
    # Faturação. Os três estados são becos sem saída — `falhado` desistiu ao fim
    # de 24 h, `recusado` é uma recusa da app ou do contrato que não muda por se
    # repetir, e `sem_efeito` fechou sem chegar a haver envio. Um `pendente` fica
    # de fora de propósito: a fila tenta-o de minuto a minuto, e acusá-lo era um
    # aviso que se aprende a ignorar.
    #
    # Contado no servidor e não na lista, porque o POS já pergunta por este
    # estado de 20 em 20 segundos: é o caminho mais barato para a falha chegar a
    # uma pessoa no mesmo dia, sem ecrã novo nenhum. O índice que o serve está
    # declarado em `db.INDICES` — esta colecção não tem TTL e só cresce.
    emails_falhados = await db[COLECOES["pontos_app"]].count_documents({
        "loja_id": loja_id,
        "tipo": "fatura_email",
        "estado": {"$in": ["falhado", "recusado", "sem_efeito"]},
    })
    return {
        "ha_programa": ultima_recolha is not None,
        "ultima_recolha_em": ultima_recolha,
        "por_sair": por_sair,
        "emails_falhados": emails_falhados,
```

(o resto do `return` — o comentário e a soma dos `falhados` — fica exactamente como está.)

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_impressao.py tests/faturacao/test_indices.py tests/faturacao/test_arranque.py tests/faturacao/test_o_separador_de_faturacao_no_ecra.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/impressao.py backend/faturacao/db.py \
        backend/tests/faturacao/test_impressao.py backend/tests/faturacao/test_indices.py
git commit -m "O estado da impressão conta as faturas por email sem saída

Falhado, recusado e sem_efeito são becos sem saída e nenhum tem papel a
compensá-lo. O POS já lê esta resposta de 20 em 20 segundos — é o caminho mais
barato para a falha chegar a uma pessoa no mesmo dia, sem lista nova nenhuma. E
com índice próprio: fat_pontos_app não tem TTL e só cresce.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: «X faturas por email, Y em papel» no relatório das 23:30

**Files:**
- Modify: `backend/faturacao/relatorio_rota.py:103-144` (`_juntar_dados`) e `:193-196` (`_produzir_e_enviar`)
- Modify: `backend/faturacao/relatorio_diario.py:234-244` (assinatura e docstring) e `:321-334` (bloco `geral`)
- Modify: `backend/faturacao/relatorio_email.py:382-403` (o cartão do herói)
- Test: `backend/tests/faturacao/test_relatorio_diario_com_app.py:153-163` (o duplo passa a casar filtros) e secção nova no fim

**Interfaces:**
- Consumes: as linhas `tipo: "fatura_email"` em `fat_pontos_app` (Task 3).
- Produces:
  - `_juntar_dados(db, dia)` devolve mais uma chave: `faturas_por_email: int`
  - `montar_relatorio(..., faturas_por_email: int = 0)`
  - `dados["geral"]` ganha `faturas_por_email` e `faturas_em_papel`
  - `html_do_relatorio` escreve a linha no cartão do herói.

- [ ] **Step 1: Escrever o teste que falha**

Primeiro, **o duplo tem de casar filtros**, senão o teste da rota fica verde com a implementação errada: o `_Coleccao.find` das linhas 161-162 ignora o filtro por completo, e um `_juntar_dados` que contasse TODAS as linhas de `fat_pontos_app` (créditos incluídos) ou filtrasse pelo campo de data errado passava na mesma. Em `backend/tests/faturacao/test_relatorio_diario_com_app.py`, substituir a classe `_Coleccao` (linhas 153-162) por:

```python
def _casa(doc, filtro):
    """Igualdade e `$gte` — o mínimo que este ficheiro precisa, e o mínimo que
    faz um teste de contagem valer alguma coisa. Sem isto, `_Coleccao` devolvia
    tudo a qualquer filtro e a contagem das faturas por email ficava verde com
    o tipo errado, com o campo de data errado, ou sem filtro nenhum."""
    for chave, valor in (filtro or {}).items():
        atual = doc.get(chave)
        if isinstance(valor, dict) and "$gte" in valor:
            if atual is None or not atual >= valor["$gte"]:
                return False
        elif atual != valor:
            return False
    return True


class _Coleccao:
    def __init__(self, docs=(), por_id=None):
        self._docs = list(docs)
        self._por_id = por_id or {}

    async def find_one(self, filtro, projeccao=None):
        return self._por_id.get(filtro.get("id"))

    def find(self, filtro=None, projeccao=None):
        return _Cursor([d for d in self._docs if _casa(d, filtro)])

    async def count_documents(self, filtro=None):
        return len([d for d in self._docs if _casa(d, filtro)])
```

Depois, no fim do ficheiro:

```python
# --- «X faturas por email, Y em papel» -------------------------------------------
#
# A medição que transforma a promessa num número, no canal que já existe. O
# tecto desta funcionalidade é a adopção do QR — que no dia em que foi construída
# era ZERO — e o número a vigiar é este, não o código.


def test_o_relatorio_diz_quantas_faturas_foram_por_EMAIL_e_quantas_em_PAPEL():
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[dict(DOC_APP, id="d%d" % i) for i in range(10)],
        turnos=[], faturas_por_email=3)

    assert dados["geral"]["faturas_por_email"] == 3
    assert dados["geral"]["faturas_em_papel"] == 7


def test_uma_NOTA_DE_CREDITO_nao_conta_como_papel_desta_linha():
    """As notas saem sempre em papel, mas esta linha é sobre o talão da COMPRA
    — misturá-las fazia o número em papel subir sem nada ter mudado."""
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[DOC_APP, dict(DOC_APP, id="n1", tipo="NC", total_bruto=-6.85)],
        turnos=[], faturas_por_email=1)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (1, 0)


def test_a_contagem_nunca_passa_o_total_de_faturas_do_dia():
    """A fila conta-se pelo dia UTC e os documentos pelo dia de LISBOA: na
    fronteira, os dois podem discordar. Duas linhas do mesmo email a dizerem
    «4 por email, -1 em papel» era o relatório a acusar-se a si próprio."""
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[DOC_APP], turnos=[], faturas_por_email=4)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (1, 0)


def test_a_linha_aparece_escrita_no_EMAIL_que_o_dono_abre():
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[dict(DOC_APP, id="d%d" % i) for i in range(10)],
        turnos=[], faturas_por_email=3)

    assert "3 faturas por email, 7 em papel" in html_do_relatorio(dados)


def test_num_dia_SEM_FATURAS_a_linha_nao_aparece():
    """Zero por email e zero em papel não é uma medição — é um dia fechado."""
    dados = montar_relatorio(dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
                             documentos=[], turnos=[], faturas_por_email=0)

    assert "em papel" not in html_do_relatorio(dados)


def test_a_ROTA_conta_as_linhas_do_DIA_e_so_as_do_EMAIL():
    """O módulo das contas é puro: se ninguém lhe disser quantas foram, o número
    nunca chega ao email das 23:30.

    A fixture traz de propósito uma linha de CRÉDITO e uma fatura por email de
    ONTEM: contar tudo, filtrar pelo campo errado ou não filtrar nada dá 4 e não
    2 — que são os três enganos que este teste vem prender."""
    from faturacao.db import COLECOES
    from faturacao.relatorio_rota import _juntar_dados

    db = _Db({COLECOES["pontos_app"]: _Coleccao([
        {"tipo": "fatura_email", "estado": "feito",
         "criado_em": "2026-09-01T12:00:00+00:00"},
        {"tipo": "fatura_email", "estado": "pendente",
         "criado_em": "2026-09-01T19:30:00+00:00"},
        {"tipo": "fatura_email", "estado": "feito",
         "criado_em": "2026-08-31T20:00:00+00:00"},
        {"tipo": "credito", "estado": "feito",
         "criado_em": "2026-09-01T12:00:01+00:00"},
    ])})
    assert _corre(_juntar_dados(db, "2026-09-01"))["faturas_por_email"] == 2


def test_o_relatorio_e_montado_COM_a_contagem_do_email(monkeypatch):
    from faturacao import relatorio_rota as rota

    vistos = {}

    async def juntar(db, dia):
        return {"documentos": [], "lojas": [], "turnos": [],
                "loja_da_app": None, "faturas_por_email": 5}

    def montar(**kw):
        vistos.update(kw)
        return {"dia": kw["dia"], "geral": {"faturacao": 0.0}, "lojas": []}

    async def enviar(html, para, assunto):
        return {"id": "e1"}

    monkeypatch.setattr(rota, "obter_db", lambda: _Db({}))
    monkeypatch.setattr(rota, "_juntar_dados", juntar)
    monkeypatch.setattr(rota, "montar_relatorio", montar)
    monkeypatch.setattr(rota, "html_do_relatorio", lambda dados, url_do_painel=None: "<p></p>")
    monkeypatch.setattr(rota, "_enviar", enviar)

    _corre(rota._produzir_e_enviar(["a@b.pt"], None))
    assert vistos.get("faturas_por_email") == 5
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_relatorio_diario_com_app.py -q`

Expected: FAIL com `TypeError: montar_relatorio() got an unexpected keyword argument 'faturas_por_email'` e `KeyError: 'faturas_por_email'` em `test_a_ROTA_conta_as_linhas_do_DIA_e_so_as_do_EMAIL`.

- [ ] **Step 3: Implementação mínima**

Em `backend/faturacao/relatorio_diario.py`, na assinatura (a seguir à linha 243) e na docstring (a seguir ao parágrafo do `loja_da_app`, linha 261):

```python
    loja_da_app: Optional[str] = None,
    faturas_por_email: int = 0,
) -> Dict:
```

```python
    `faturas_por_email` são as linhas de envio que a fila da app criou neste
    dia. Vem por parâmetro pela mesma razão que a loja da app: este módulo não
    lê base de dados nenhuma.
    """
```

E, imediatamente antes do `return` (linha 321), mais as duas chaves no bloco `geral`:

```python
    # **«X faturas por email, Y em papel».** A medição que transforma a promessa
    # num número — o tecto desta funcionalidade é a adopção do QR na caixa, e é
    # este o número a vigiar, não o código que a faz.
    #
    # As notas de crédito ficam de fora: saem sempre em papel (a devolução é o
    # momento em que o cliente está chateado), e contá-las aqui fazia o número
    # em papel subir sem nada ter mudado no talão da compra.
    #
    # O `min` não é decoração: a fila conta-se pelo dia UTC e os documentos pelo
    # dia de LISBOA, e na fronteira podem discordar. Duas linhas do mesmo email a
    # dizerem «4 por email, -1 em papel» era o relatório a acusar-se a si
    # próprio, e quem o lê deixava de acreditar no resto.
    faturas_de_hoje = [d for d in docs_de_hoje if d.get("tipo") != "NC"]
    por_email = min(faturas_por_email, len(faturas_de_hoje))

    return {
        "dia": dia,
        "ate": ate,
        "com_iva": com_iva,
        "ha_vendas": bool(docs_de_hoje),
        "geral": {
            "faturacao": faturacao,
            "faturacao_ontem": faturacao_ontem,
            "dia_de_ontem": dia_de_ontem,
            "variacao": _variacao(faturacao, faturacao_ontem),
            "documentos": len(docs_de_hoje),
            "faturas_por_email": por_email,
            "faturas_em_papel": len(faturas_de_hoje) - por_email,
            "caixa": _caixa_das_sessoes(turnos),
            "pagamentos": _junta_pagamentos([l["pagamentos"] for l in linhas_de_loja]),
        },
```

Em `backend/faturacao/relatorio_email.py`, a seguir ao bloco `aviso_sem_vendas` (linha 391) e no cartão do herói (linhas 393-403):

```python
    # **A medição do papel poupado, na única linha que cabe.** Não se acrescenta
    # cartão nenhum: isto é um número para vigiar, não uma secção. Num dia
    # fechado (zero e zero) não aparece — zero por email e zero em papel não é
    # uma medição, é um dia sem vendas, e o email já o diz acima.
    por_email = geral.get("faturas_por_email") or 0
    em_papel = geral.get("faturas_em_papel") or 0
    papelada = ('<p style="margin:10px 0 0;font-size:13px;color:%s;">'
                '%d faturas por email, %d em papel</p>'
                % (TEXTO_FRACO, por_email, em_papel)) if (por_email or em_papel) else ""

    heroi = _cartao(
        '<p style="margin:0;font-size:11px;color:%s;letter-spacing:.6px;'
        'text-transform:uppercase;font-weight:600;">Faturação do dia%s</p>'
        '<p style="margin:6px 0 0;font-size:38px;line-height:1.1;font-weight:700;'
        'color:%s;">%s</p>'
        '<div style="margin-top:12px;">%s</div>%s%s%s'
        '<div style="margin-top:18px;">%s</div>'
        % (TEXTO_FRACO, "" if dados.get("com_iva") else " (sem IVA)", TEXTO,
           _euros(faturacao), marca, ontem, papelada, aviso_sem_vendas,
           _grafico(dados.get("serie") or [])),
        margem_topo=0)
```

Em `backend/faturacao/relatorio_rota.py`, dentro de `_juntar_dados`, a seguir à leitura das sessões (linha 125) e no `return` (linhas 143-144):

```python
    # As linhas de envio por email criadas neste dia, contadas pelo `inicio_do_
    # dia` que a leitura das sessões já calculou — o dia de LISBOA, em UTC, como
    # tudo o resto deste módulo. **`count_documents` e não `find`**: é um número
    # e não uma lista, e sem tecto nenhum para truncar em silêncio.
    faturas_por_email = await db[COLECOES["pontos_app"]].count_documents({
        "tipo": "fatura_email",
        "criado_em": {"$gte": inicio_do_dia.isoformat()},
    })
```

```python
    return {"documentos": documentos, "lojas": lojas, "turnos": turnos,
            "loja_da_app": definicao_da_app.get("loja_id"),
            "faturas_por_email": faturas_por_email}
```

E em `_produzir_e_enviar` (linhas 193-196):

```python
    dados = montar_relatorio(
        dia=dia, ate=ate, lojas=partes["lojas"],
        documentos=partes["documentos"], turnos=partes["turnos"],
        loja_da_app=partes["loja_da_app"],
        # `.get` e não `[...]`: há testes que substituem `_juntar_dados` por um
        # duplo com as chaves de antes desta linha existir, e o relatório da
        # noite não pode deixar de sair por causa de uma chave que falta.
        faturas_por_email=partes.get("faturas_por_email") or 0)
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_relatorio_diario_com_app.py tests/faturacao/test_relatorio_diario.py tests/faturacao/test_relatorio_email.py tests/faturacao/test_relatorio_rota.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add backend/faturacao/relatorio_rota.py backend/faturacao/relatorio_diario.py \
        backend/faturacao/relatorio_email.py \
        backend/tests/faturacao/test_relatorio_diario_com_app.py
git commit -m "O relatório da noite leva «X faturas por email, Y em papel»

A medição que transforma a promessa num número, no canal que já existe. As notas
de crédito ficam de fora (saem sempre em papel) e a contagem nunca passa o total
de faturas do dia: a fila conta-se em UTC e os documentos em horas de Lisboa. O
duplo do teste passa a casar filtros, senão a contagem ficava verde sem filtrar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Fecho: a suite inteira

- [ ] **Passo final: correr tudo e comparar com a medida de partida**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest -q`

Expected: PASS, com o total **acima de 3296** (as tarefas acrescentam ~45 testes) e **zero** `skipped` novos. Ler `passed` **e** `skipped`: uma suite que salta testes em silêncio diz que está verde sem o estar.

---

## Notas da revisão

Os treze achados da crítica foram todos confirmados contra o código e **todos aplicados**. Nenhum estava errado. Três notas sobre a forma como foram aplicados, e um defeito que a crítica não apanhou:

1. **O achado do `ligacao_id` reaproveitado (baixa) foi aplicado pela via da limitação escrita, não pela da guarda.** A crítica oferecia duas saídas. A guarda proposta — `find_one({"tipo": "fatura_email", "payload.ligacao_id": …})` dentro do mesmo `try` — corre em **todas** as emissões com QR, sobre uma colecção que `db.py:88-92` diz que «fica para sempre», e não há índice em `payload.ligacao_id` nem forma barata de o ter (um índice por campo de payload numa colecção que cresce todos os dias). Trocava um desfecho raro por um varrimento de colecção no caminho de cada fatura das cinco lojas. Fica em **Global Constraints**, com o mecanismo da app (5xx para tudo o que não seja sucesso, §`/fatura-email` ponto 4 do desenho) escrito como o que mantém a linha a repetir em vez de fechar `recusado`.

2. **O achado do índice (média) foi aplicado pela via do índice, não pela do comentário.** A crítica deixava as duas em aberto. Uma linha em `db.INDICES` mais um teste em `test_indices.py` custa menos do que um parágrafo a defender um prefixo que não serve a pergunta — e é o que `db.py:363-368` já fez, com todas as letras, para a outra volta de poucos segundos.

3. **O achado dos `-k` (baixa) foi aplicado correndo o ficheiro inteiro nos Steps 2 de todas as tarefas**, e não afinando termos. Um `-k` afinado à mão volta a divergir na primeira vez que alguém acrescentar um teste com outro nome; o ficheiro inteiro nunca diverge, e é o que a Task 3 já fazia.

4. **Defeito que a crítica não apanhou, corrigido de passagem:** o `test_com_NIF_ESCRITO_o_papel_sai_a_mesma` do plano antigo usava `nif="244772903"` — que **não é um NIF português válido** (soma 190, resto 3, dígito de controlo 8 e não 3). `PedidoFinalizarVenda._valida_nif` (`fiscal.py:1961-1985`) recusa-o no validador do Pydantic: o teste rebentava com `ValidationError` antes de a rota correr e nunca chegava a medir o papel. Passou a `"219363935"`, que é o que o próprio `test_fiscal.py:1825` já usa. Na mesma volta, o `_finalizar` ganhou o parâmetro `nif=None` — a via que a crítica preferia — e o bloco morto com o `if False` desapareceu, junto com a nota em prosa que mandava não o escrever.
