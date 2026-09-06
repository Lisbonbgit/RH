# Plano — As faturas da app L'Açaí no módulo de Faturação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: usar `superpowers:subagent-driven-development`
> (recomendado) ou `superpowers:executing-plans` para implementar tarefa a tarefa.
> Os passos usam caixas (`- [ ]`) para acompanhamento.

**Objetivo:** o portal Lisbonb passa a ir buscar ao Vendus as Faturas Simplificadas
emitidas pela app móvel L'Açaí e a mostrá-las na loja "App Online", com os mesmos
números que o Vendus mostra.

**Arquitetura:** um cron novo lê os documentos do dia na Caixa Online do Vendus
(`ClienteEmissaoVendus.listar_documentos_por_dia`, que já existe e já pagina),
descarta o que é nosso e o que não é venda, vai buscar o detalhe por id (que é o
único sítio onde vivem o ATCUD e as linhas) e grava em `fat_documentos` com
`origem: "app"`. O motor de relatórios aprende a repartir um documento sem venda
pelas linhas em cru do Vendus. Nada é escrito no Vendus e a app não é tocada.

**Stack:** Python 3 / FastAPI / Motor (MongoDB) / httpx / pytest. Frontend React.

**Especificação:** `docs/superpowers/specs/2026-09-04-faturas-da-app-design.md`

## Restrições globais

Cada uma destas, sozinha, chega para pôr números errados no ecrã do dono. Valem
para todas as tarefas.

- **Só `FS` e `NC`.** `documentos._TIPOS = {"FS", "NC"}` (documentos.py:476) responde
  **422** a qualquer outro tipo. `OT`, `RG`, `PF`, `DC`, `GT` ficam de fora, contados
  e registados no log. Lista de permitidos, nunca de proibidos.
- **Nunca gravar `atcud: None` nem `vendus_document_id: None`** — os índices são
  únicos **simples** (db.py:132-133), dois nulos colidem entre si.
- **Nunca gravar `ext_ref: ""`.** `db.py:153-156` declara-o único parcial sobre
  strings, e a string vazia é uma string. **Medido em produção a 2026-09-04: esse
  índice não existe** — o `ext_ref_1` que lá está é simples, sem `unique`, porque o
  antigo colidiu (`IndexKeySpecsConflict` no arranque, já registado no ledger). Hoje
  não rebenta; rebenta no dia em que o índice for reposto. Grava-se `None`.
  (`vendus_document_id` e `atcud` **são** únicos em produção — confirmado.)
- **`emitido_em` é uma string ISO com offset `+00:00`**, produzida por
  `vendus/emissao._instante_do_vendus`. Nunca `Z`: os filtros comparam strings
  (dashboard.py:498, relatorios.py:620) e `Z` ordena depois de `+`.
- **Gravar sempre `total_bruto` E `total_liquido`.** O `total_liquido` não tem campo
  alternativo (dashboard.py:78); sem ele o Dashboard "sem IVA" mostra 0,00 €.
- **O `status` do Vendus é uma string na lista (`"N"`) e um dicionário no detalhe
  (`{"id": "N"}`).** Ler os dois com um helper, nunca comparar diretamente.
- **`GET documents/{id}/` não aceita `view`** — responde 403 P001.
- **A app nunca é tocada.** Nada é escrito no Vendus. `fat_vendas`, sessões de caixa
  e `fat_refs_fiscais` não são lidas nem escritas por nada deste plano.
- **Nunca chamar `registers/movements`** — fechava a caixa por baixo da app.
- Testes: `cd backend && python -m pytest`. Comentários e mensagens em PT-PT.
- Commits terminam com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Estrutura dos ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `backend/faturacao/sincronizacao_app.py` **(novo)** | As contas puras: classificar, converter, construir artigos. Sem Mongo, sem rede. |
| `backend/faturacao/sincronizacao_rota.py` **(novo)** | A rota do cron, a definição da loja e a gravação. Toca no Mongo e na rede. |
| `backend/faturacao/vendus/emissao.py` | **Modificar:** método `ler_documento(id)` (o único sítio com ATCUD e linhas). |
| `backend/faturacao/relatorios.py` | **Modificar:** `eventos_dos_documentos` reparte um documento sem venda pelas `linhas_vendus`. |
| `backend/faturacao/__init__.py` | **Modificar:** registar o router novo. |
| `backend/faturacao/documentos.py` | **Modificar:** o detalhe mostra `origem` e as linhas da app. |
| `frontend/src/pages/admin/faturacao/FatLojas.js` | **Modificar:** escolher a loja da app + "Sincronizar agora". |
| `frontend/src/pages/admin/faturacao/FatDocumentos.js` | **Modificar:** "Origem: App", esconder Reimprimir. |
| `faturacao-app-cron.sh` **(novo)** | O disparo de 5 em 5 minutos. |

As contas puras vivem separadas da rota de propósito: é o que permite testar as
dez armadilhas sem Mongo nem rede, e é o padrão que `caixa_math.py` e
`relatorio_diario.py` já seguem nesta casa.

---

### Task 1: As contas puras da sincronização

**Ficheiros:**
- Criar: `backend/faturacao/sincronizacao_app.py`
- Testar: `backend/tests/faturacao/test_sincronizacao_app.py`

**Interfaces:**
- Consome: nada (módulo puro, sem imports do projeto exceto `relatorios`).
- Produz:
  - `E_NOSSO(ext_ref: Optional[str]) -> bool`
  - `estado_do_vendus(doc: Dict) -> Optional[str]`
  - `deve_importar(doc: Dict) -> Tuple[bool, str]` — `(entra, motivo)`
  - `TIPOS_ACEITES: FrozenSet[str]` — `{"FS", "NC"}`

- [ ] **Passo 1: escrever os testes que falham**

```python
"""**Quem entra e quem fica de fora** — as contas puras da sincronização das
faturas da app, sem Mongo e sem rede.

Os casos não são inventados: são os documentos que estavam mesmo na Caixa
Online do Vendus a 2026-09-04, lidos em produção. Os cinco orçamentos de
740,15 € são a razão de este ficheiro existir — uma regra que só olhasse para o
prefixo `pos-` importava-os como receita.
"""
from faturacao.sincronizacao_app import (
    E_NOSSO,
    TIPOS_ACEITES,
    deve_importar,
    estado_do_vendus,
)


def _doc(**campos):
    base = {"id": 370665072, "type": "FS", "status": "N",
            "external_reference": "LA00028", "amount_gross": "6.85"}
    base.update(campos)
    return base


def test_a_fatura_da_app_entra():
    entra, motivo = deve_importar(_doc())
    assert entra is True, motivo


def test_uma_fatura_nossa_fica_de_fora():
    entra, motivo = deve_importar(_doc(external_reference="pos-abc-def-ghi"))
    assert entra is False
    assert "pos" in motivo


def test_um_orcamento_de_740_euros_nao_e_facturacao():
    # O caso real: 5 destes na Caixa Online, 3.582,10 € que nunca foram vendas.
    entra, motivo = deve_importar(
        _doc(type="OT", external_reference="", amount_gross="740.15"))
    assert entra is False
    assert "OT" in motivo


def test_um_recibo_nao_entra_porque_o_dinheiro_ja_foi_contado():
    entra, motivo = deve_importar(_doc(type="RG", external_reference=""))
    assert entra is False
    assert "RG" in motivo


def test_uma_nota_de_credito_da_app_entra():
    entra, _ = deve_importar(_doc(type="NC", external_reference="LA00031"))
    assert entra is True


def test_um_tipo_que_o_vendus_invente_amanha_fica_de_fora_sozinho():
    entra, motivo = deve_importar(_doc(type="XPTO"))
    assert entra is False
    assert "XPTO" in motivo


def test_um_documento_anulado_nao_entra():
    entra, motivo = deve_importar(_doc(status="A"))
    assert entra is False
    assert "anulad" in motivo.lower()


def test_o_estado_le_se_na_lista_e_no_detalhe():
    # Na lista o Vendus manda a string; no GET por id manda o dicionário.
    assert estado_do_vendus({"status": "N"}) == "N"
    assert estado_do_vendus({"status": {"id": "A", "date": "..."}}) == "A"
    assert estado_do_vendus({}) is None


def test_uma_fatura_de_teste_nunca_entra():
    entra, motivo = deve_importar(_doc(number="FS T06P2026/3"))
    assert entra is False
    assert "teste" in motivo.lower()


def test_uma_fatura_a_mao_sem_referencia_entra_na_mesma():
    # Receita real da Caixa Online que não é nossa: entra, e o log avisa.
    entra, _ = deve_importar(_doc(external_reference=""))
    assert entra is True


def test_so_fs_e_nc():
    assert TIPOS_ACEITES == frozenset({"FS", "NC"})


def test_e_nosso_nao_se_engana_com_none():
    assert E_NOSSO("pos-abc") is True
    assert E_NOSSO("LA00028") is False
    assert E_NOSSO(None) is False
    assert E_NOSSO("") is False
```

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_app.py -v
```

Esperado: FAIL — `ModuleNotFoundError: No module named 'faturacao.sincronizacao_app'`

- [ ] **Passo 3: escrever o módulo**

```python
"""**Quem entra e quem fica de fora**, e nada mais.

Este ficheiro não sabe o que é Mongo nem o que é uma ligação ao Vendus. Recebe
o dicionário que o Vendus devolve e responde a uma pergunta de cada vez. É o
que permite que as armadilhas medidas — o `status` que muda de forma, os
orçamentos de 740 € — tenham um teste cada, sem servidor nenhum.

**A regra é uma lista de PERMITIDOS.** Foi medido na produção a 2026-09-04: a
Caixa Online tinha, além das nossas faturas e da única da app, cinco orçamentos
(`OT`) de 3.582,10 € e dois recibos (`RG`). Um orçamento não é venda nenhuma; um
recibo é o pagamento de uma fatura que já foi contada. Uma regra escrita ao
contrário — "tudo o que não começa por `pos-`" — punha 3.596,19 € de receita
inventada no Dashboard do dono. Um tipo novo que o Vendus invente amanhã fica de
fora sozinho, e o log di-lo.
"""
from typing import Dict, FrozenSet, Optional, Tuple

# Só estes dois, e não também FT/FR: `documentos._TIPOS` responde 422 a
# qualquer outro tipo no filtro do backoffice, e um documento que entra na base
# mas não se consegue listar é pior do que um documento que não entra.
TIPOS_ACEITES: FrozenSet[str] = frozenset({"FS", "NC"})

_PREFIXO_NOSSO = "pos-"


def E_NOSSO(ext_ref: Optional[str]) -> bool:
    """A fatura saiu do nosso POS? É o `ext_ref_determinista` de `fiscal.py`."""
    return str(ext_ref or "").startswith(_PREFIXO_NOSSO)


def estado_do_vendus(doc: Dict) -> Optional[str]:
    """O estado (`N` normal, `A` anulado) venha ele em que forma vier.

    **Medido a 2026-09-04:** na LISTA (`GET documents/`) o Vendus manda
    `status: "N"`, uma string. No detalhe (`GET documents/{id}/`) manda
    `status: {"id": "N", "date": ..., "user_id": ...}`, um dicionário. Um
    `doc["status"] == "A"` escrito à mão acerta num sítio e falha no outro, em
    silêncio — e o silêncio, aqui, é uma fatura anulada a contar como receita.
    """
    estado = doc.get("status")
    if isinstance(estado, dict):
        estado = estado.get("id")
    return str(estado) if estado is not None else None


def e_de_teste(doc: Dict) -> bool:
    """Uma série de testes vem prefixada por `T` (`FS T06P2026/3`).

    Não se usa o modo em que o portal está AGORA: o que interessa é o modo em
    que aquele documento foi emitido. Um documento de teste não vale nada e não
    pode contar dinheiro.
    """
    numero = str(doc.get("number") or "")
    # "FS T06P2026/3" -> a segunda palavra começa por T
    partes = numero.split()
    return len(partes) > 1 and partes[1].startswith("T")


def deve_importar(doc: Dict) -> Tuple[bool, str]:
    """`(entra, motivo)` — e o motivo é sempre escrito, mesmo quando entra.

    Quem chama regista o motivo no log. Uma sincronização que diga "ignorei 7"
    sem dizer porquê é uma sincronização que ninguém consegue auditar quando os
    números não baterem.
    """
    tipo = str(doc.get("type") or "").strip().upper()
    if tipo not in TIPOS_ACEITES:
        return False, "tipo %s não é uma venda" % (tipo or "(vazio)")

    ref = doc.get("external_reference")
    if E_NOSSO(ref):
        return False, "é nossa (ext_ref começa por pos-)"

    estado = estado_do_vendus(doc)
    if estado == "A":
        return False, "anulada no Vendus"

    if e_de_teste(doc):
        return False, "documento de teste (série T), sem valor fiscal"

    if not str(ref or "").strip():
        # Entra na mesma: é receita real daquela caixa. Mas fica dito.
        return True, "sem referência externa — emitida à mão no painel do Vendus"

    return True, "da app (ref %s)" % ref
```

- [ ] **Passo 4: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_app.py -v
```

Esperado: 12 passed

- [ ] **Passo 5: validar os testes por mutação**

Trocar `if tipo not in TIPOS_ACEITES:` por `if False:` e correr outra vez.
Esperado: **falham** `test_um_orcamento_de_740_euros_nao_e_facturacao`,
`test_um_recibo_nao_entra...` e `test_um_tipo_que_o_vendus_invente...`.
Repor a linha. Um teste verde que não fica vermelho quando se parte a regra
não está a testar nada.

```bash
cd backend && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/faturacao/test_sincronizacao_app.py -v
```

(O `PYTHONDONTWRITEBYTECODE=1` não é decoração: neste Mac o bytecode vai para
`~/Library/Caches/com.apple.python` e uma mutação reposta no mesmo segundo não
recompila — a suite mede o passado.)

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/sincronizacao_app.py backend/tests/faturacao/test_sincronizacao_app.py
git commit -m "Separar quem entra de quem fica de fora na sincronização da app

Uma lista de permitidos (FS, NC) e não de proibidos: medido em produção, a
Caixa Online tinha 3.582,10 EUR de orçamentos e dois recibos que uma regra
escrita ao contrário importava como receita.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Ler um documento do Vendus com ATCUD e linhas

**Ficheiros:**
- Modificar: `backend/faturacao/vendus/emissao.py` (método novo em `ClienteEmissaoVendus`)
- Testar: `backend/tests/faturacao/test_ler_documento_vendus.py`

**Interfaces:**
- Consome: `ClienteEmissaoVendus` (emissao.py:222), `_corpo_como_lista`,
  `VendusRespostaIlegivel`, `_register_id_configurado`.
- Produz: `ClienteEmissaoVendus.ler_documento(documento_id: int) -> Optional[Dict]`
  — o documento cru do Vendus (com `atcud`, `items`, `taxes`), ou `None` no 404.

- [ ] **Passo 1: escrever os testes que falham**

```python
"""**O GET de um documento por id** — o único sítio onde vivem o ATCUD e as
linhas.

Medido no Vendus a 2026-09-04: a lista (`GET documents/`), mesmo com
`view=detailed`, devolve 18 campos e NENHUM deles é `atcud` ou `items`. O
documento por id devolve 25, com os dois. E esse pedido NÃO aceita `view` —
responde 403 P001.
"""
import httpx
import pytest

from faturacao.vendus.emissao import ClienteEmissaoVendus


def _cliente(responder):
    return ClienteEmissaoVendus("chave-de-teste",
                                transport=httpx.MockTransport(responder),
                                dormir=lambda _s: None)


def test_traz_o_atcud_e_as_linhas():
    def responder(pedido):
        assert pedido.url.path.endswith("/documents/370665072/")
        return httpx.Response(200, json=[{
            "id": 370665072, "number": "FS 06P2026/446",
            "atcud": "J6SHGSNX-446", "type": "FS",
            "amount_gross": "6.85", "amount_net": "6.06",
            "items": [{"qty": 1, "title": "Açaí Mini",
                       "amounts": {"gross_total": "6.85", "net_total": "6.06"},
                       "tax": {"id": "INT", "rate": 13}}],
        }])
    with _cliente(responder) as c:
        doc = c.ler_documento(370665072)
    assert doc["atcud"] == "J6SHGSNX-446"
    assert doc["items"][0]["title"] == "Açaí Mini"


def test_nunca_manda_o_parametro_view():
    # O Vendus responde 403 P001 a um `view` num GET por id. O teste confronta
    # o pedido que sai, não a intenção de quem o escreveu.
    vistos = []

    def responder(pedido):
        vistos.append(str(pedido.url))
        return httpx.Response(200, json=[{"id": 1, "atcud": "X-1"}])
    with _cliente(responder) as c:
        c.ler_documento(1)
    assert "view" not in vistos[0]


def test_um_404_e_none_e_nao_uma_avaria():
    def responder(_pedido):
        return httpx.Response(404, json={"errors": [{"code": "A001"}]})
    with _cliente(responder) as c:
        assert c.ler_documento(999) is None


def test_um_corpo_que_nao_se_le_nao_vira_documento_vazio():
    from faturacao.vendus.emissao import VendusRespostaIlegivel

    def responder(_pedido):
        return httpx.Response(200, content=b"nao e json")
    with _cliente(responder) as c:
        with pytest.raises(VendusRespostaIlegivel):
            c.ler_documento(1)
```

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_ler_documento_vendus.py -v
```

Esperado: FAIL — `AttributeError: 'ClienteEmissaoVendus' object has no attribute 'ler_documento'`

- [ ] **Passo 3: escrever o método**

Acrescentar a `ClienteEmissaoVendus`, a seguir a `listar_documentos_por_dia`:

```python
    def ler_documento(self, documento_id: int) -> Optional[Dict]:
        """UM documento do Vendus, cru, com o ATCUD e as linhas.

        **Porque é que isto não é a lista.** Medido a 2026-09-04: a lista
        (`GET documents/`), mesmo com `view=detailed`, devolve 18 campos e
        nenhum deles é `atcud` ou `items` — traz `payments` e `amount_gross`,
        que é para o que foi feita. O ATCUD é obrigatório para gravar (o índice
        é único) e as linhas são o que faz a fatura valer mais do que zero nos
        Relatórios. Os dois só existem aqui.

        **E este pedido não leva `view`.** O Vendus responde 403 P001 a um
        `view` num GET por id — o detalhe já vem todo. Está escrito na docstring
        deste módulo e confirmado no código de produção da pizzaria
        (`~/dev/pizzaria/backend/vendus/client.py::get_document_detail`).

        `None` no 404 (o documento não existe) — não é avaria. Um 2xx cujo
        corpo não se lê continua a ser `VendusRespostaIlegivel`, nunca um
        documento vazio: quem chama tem de saber a diferença entre «não há» e
        «não consegui ler».
        """
        resposta = self._pedir_get_com_retentativas(
            "documents/%d/" % int(documento_id), None)
        if resposta is None:
            return None
        dados = _corpo_como_lista(resposta)
        return dados[0] if dados else None
```

- [ ] **Passo 4: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_ler_documento_vendus.py -v
```

Esperado: 4 passed

- [ ] **Passo 5: não partir o que já lá estava**

```bash
cd backend && python -m pytest tests/faturacao/ -q
```

Esperado: tudo verde (o método é novo, nada o chamava).

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/vendus/emissao.py backend/tests/faturacao/test_ler_documento_vendus.py
git commit -m "Ler um documento do Vendus por id, com ATCUD e linhas

A lista não os traz — medido: 18 campos, nenhum é atcud ou items. E o GET por
id não aceita view (403 P001).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Converter um documento do Vendus no nosso formato

**Ficheiros:**
- Modificar: `backend/faturacao/sincronizacao_app.py`
- Testar: `backend/tests/faturacao/test_sincronizacao_app.py`

**Interfaces:**
- Consome: `deve_importar`, `estado_do_vendus` (Task 1);
  `vendus/emissao._normaliza_documento` e `_instante_do_vendus`.
- Produz: `documento_para_gravar(cru: Dict, loja_id: str) -> Dict` — o dicionário
  pronto para `fat_documentos`. Levanta `ValueError` se faltar `atcud` ou `id`.

- [ ] **Passo 1: escrever os testes que falham**

Acrescentar a `test_sincronizacao_app.py`:

```python
import pytest

from faturacao.sincronizacao_app import documento_para_gravar

LOJA = "98331284-ba8d-41b8-b074-4059902d68a9"

# O documento como o Vendus o devolveu mesmo, lido em produção a 2026-09-04.
FS_446 = {
    "id": 370665072, "type": "FS", "number": "FS 06P2026/446",
    "atcud": "J6SHGSNX-446", "date": "2026-09-01",
    "local_time": "2026-09-01 14:43:25",
    "status": {"id": "N", "date": "2026-09-01 13:43:25"},
    "amount_gross": "6.85", "amount_net": "6.06",
    "external_reference": "LA00028",
    "client": {"name": "Matheus Augusto Flores de Moraes", "fiscal_id": "244772903"},
    "items": [{"qty": 1, "title": "Açaí Mini",
               "amounts": {"gross_total": "6.85", "net_total": "6.06"},
               "tax": {"id": "INT", "rate": 13}}],
}


def test_traz_os_dois_totais_porque_o_liquido_nao_tem_alternativa():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["total_bruto"] == 6.85
    assert d["total_liquido"] == 6.06
    assert d["total"] == 6.85


def test_a_hora_e_a_do_vendus_e_sai_em_utc_com_offset():
    d = documento_para_gravar(FS_446, LOJA)
    # 14:43 de Lisboa em Setembro (UTC+1) são 13:43 UTC.
    assert d["emitido_em"].startswith("2026-09-01T13:43:25")
    assert d["emitido_em"].endswith("+00:00"), "um Z parte os filtros por string"
    assert "Z" not in d["emitido_em"]


def test_guarda_a_loja_a_origem_e_as_linhas():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["loja_id"] == LOJA
    assert d["origem"] == "app"
    assert d["linhas_vendus"][0]["title"] == "Açaí Mini"


def test_nao_tem_venda_nem_talao():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["venda_id"] is None
    assert "talao_escpos" not in d


def test_o_id_e_nosso_e_o_do_vendus_fica_a_parte():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["vendus_document_id"] == 370665072
    assert d["id"] != 370665072
    assert len(d["id"]) == 36, "uuid nosso — é por ele que o ecrã abre o documento"


def test_copia_o_nif_do_cliente():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["cliente_nif"] == "244772903"


def test_um_consumidor_final_nao_leva_nif_de_tracinhos():
    cru = dict(FS_446, client={"name": "Consumidor Final", "fiscal_id": "---------"})
    assert documento_para_gravar(cru, LOJA)["cliente_nif"] is None


def test_uma_referencia_vazia_grava_none_e_nunca_string_vazia():
    # O índice de ext_ref é único parcial SOBRE STRINGS: dois "" colidem.
    cru = dict(FS_446, external_reference="")
    assert documento_para_gravar(cru, LOJA)["ext_ref"] is None


def test_sem_atcud_recusa_se_a_gravar():
    cru = dict(FS_446); cru.pop("atcud")
    with pytest.raises(ValueError, match="ATCUD"):
        documento_para_gravar(cru, LOJA)


def test_sem_id_do_vendus_recusa_se_a_gravar():
    cru = dict(FS_446); cru.pop("id")
    with pytest.raises(ValueError, match="id"):
        documento_para_gravar(cru, LOJA)


def test_uma_nota_de_credito_guarda_o_tipo_para_o_sinal_ficar_certo():
    cru = dict(FS_446, type="NC")
    assert documento_para_gravar(cru, LOJA)["tipo"] == "NC"
```

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_app.py -v -k "totais or hora or linhas or nif or atcud"
```

Esperado: FAIL — `ImportError: cannot import name 'documento_para_gravar'`

- [ ] **Passo 3: escrever a conversão**

Acrescentar a `sincronizacao_app.py` (e os imports no topo):

```python
import uuid

from .vendus.emissao import _instante_do_vendus, _valor_monetario

# O Vendus escreve o NIF do consumidor final assim. Copiá-lo para
# `cliente_nif` enchia o ecrã de Clientes de tracinhos.
_NIF_VAZIO = {"", "---------", "999999990"}


def _nif_do_cliente(cru: Dict) -> Optional[str]:
    nif = str((cru.get("client") or {}).get("fiscal_id") or "").strip()
    return None if nif in _NIF_VAZIO else nif


def documento_para_gravar(cru: Dict, loja_id: str) -> Dict:
    """O documento do Vendus traduzido para o que `fat_documentos` guarda.

    Os campos são os mesmos 15 que `fiscal._gravar_documento` monta
    (fiscal.py:1197-1250), menos os três que um documento sem conta de balcão
    não pode ter — `venda_id` fica `None`, e não há `talao_escpos` nenhum — e
    mais dois que só estes têm: `origem` e `linhas_vendus`.

    **Recusa-se a gravar sem ATCUD ou sem id do Vendus.** Os dois índices são
    únicos SIMPLES (db.py:132-133), não `sparse`: dois documentos com o campo a
    `None` colidem um com o outro, e o segundo desaparecia com um erro que não
    diz nada. Melhor recusar em voz alta e deixar quem chama contá-lo.
    """
    if not cru.get("atcud"):
        raise ValueError("documento do Vendus sem ATCUD: não se grava "
                         "(o índice é único e dois nulos colidem)")
    if not cru.get("id"):
        raise ValueError("documento do Vendus sem id: não se grava "
                         "(o índice é único e dois nulos colidem)")

    ref = str(cru.get("external_reference") or "").strip()
    return {
        # O nosso uuid: é por ele que o ecrã de Documentos e o PDF abrem a
        # fatura (documentos.py:135). O id do Vendus vive no seu campo.
        "id": str(uuid.uuid4()),
        "vendus_document_id": int(cru["id"]),
        "atcud": cru["atcud"],
        "numero": cru.get("number"),
        "tipo": str(cru.get("type") or "").strip().upper(),
        "modo": "normal",
        "total": _valor_monetario(cru.get("amount_gross")),
        "total_bruto": _valor_monetario(cru.get("amount_gross")),
        # Sem alternativa nenhuma no Dashboard (dashboard.py:78): não gravar
        # isto é a app a valer 0,00 € no modo "sem IVA".
        "total_liquido": _valor_monetario(cru.get("amount_net")),
        "cliente_nif": _nif_do_cliente(cru),
        "emitido_em": _instante_do_vendus(cru),
        "loja_id": loja_id,
        # Nunca "": `db.py:153-156` declara `ext_ref` único parcial sobre
        # strings. Esse índice não chegou a criar-se em produção (o antigo
        # colide), por isso hoje não rebentava — mas rebenta no dia em que
        # for reposto, e uma fatura perdida por isso não se recupera.
        # `None` fica certo nos dois mundos.
        "ext_ref": ref or None,
        "venda_id": None,
        "origem": "app",
        "linhas_vendus": cru.get("items") or [],
    }
```

- [ ] **Passo 4: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_app.py -v
```

Esperado: 23 passed

- [ ] **Passo 5: validar por mutação**

Trocar `"ext_ref": ref or None` por `"ext_ref": ref` e correr.
Esperado: falha `test_uma_referencia_vazia_grava_none_e_nunca_string_vazia`.
Repor.

- [ ] **Passo 6: commit**

```bash
git add backend/faturacao/sincronizacao_app.py backend/tests/faturacao/test_sincronizacao_app.py
git commit -m "Traduzir um documento do Vendus para fat_documentos

Com as três armadilhas dos índices: sem ATCUD ou sem id recusa-se a gravar
(únicos simples, dois nulos colidem) e a referência vazia grava None e nunca
string vazia (único parcial sobre strings).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Os Relatórios param de mostrar a app a zero

Esta é a tarefa que faz o dinheiro aparecer. Sem ela o Dashboard mostra 6,85 € e
as nove vistas dos Relatórios mostram 0,00 € para a mesma fatura.

**Ficheiros:**
- Modificar: `backend/faturacao/relatorios.py` (`eventos_dos_documentos`, ~linha 521)
- Testar: `backend/tests/faturacao/test_relatorios_da_app.py`

**Interfaces:**
- Consome: `relatorios._artigo` (relatorios.py:356), `relatorios.centimos`
  (relatorios.py:79), `relatorios._SEM_DEFINICAO` (relatorios.py:76).
- Produz: `relatorios._artigos_das_linhas_vendus(documento: Dict, categorias: Dict) -> List[Dict]`

- [ ] **Passo 1: escrever os testes que falham**

```python
"""**A fatura da app vale o que vale, também nos Relatórios.**

Sem isto, `_artigos_da_fatura` devolve `[]` a um documento sem venda
(relatorios.py:391) — e um `[]` não levanta excepção nenhuma, portanto o evento
é criado na mesma, com a soma de uma lista vazia: zero. O resultado media-se
assim: o cartão «Faturação Hoje» do Dashboard mostrava 6,85 € e as nove vistas
dos Relatórios mostravam 0,00 €, sem nenhum dos dois parecer errado.
"""
import asyncio

from faturacao.relatorios import _artigos_das_linhas_vendus, eventos_dos_documentos

LINHAS = [{"qty": 1, "title": "Açaí Mini",
           "amounts": {"gross_total": "6.85", "net_total": "6.06"},
           "tax": {"id": "INT", "rate": 13}}]

DOC = {"id": "abc", "tipo": "FS", "emitido_em": "2026-09-01T13:43:25+00:00",
       "loja_id": "loja-app", "total_bruto": 6.85, "total_liquido": 6.06,
       "origem": "app", "linhas_vendus": LINHAS, "venda_id": None}


def test_o_dinheiro_da_linha_e_o_do_vendus():
    artigos = _artigos_das_linhas_vendus(DOC, {})
    assert len(artigos) == 1
    assert artigos[0]["bruto_c"] == 685
    assert artigos[0]["liquido_c"] == 606, "6,85 a 13% dá 6,06 de base"


def test_o_custo_e_none_e_nunca_zero():
    # Zero dava 100% de margem no relatório de rentabilidade. Não sabemos o
    # custo dos artigos da app: `None` é a verdade e o ecrã escreve "—".
    assert _artigos_das_linhas_vendus(DOC, {})[0]["custo_c"] is None


def test_a_quantidade_vem_da_linha():
    doc = dict(DOC, linhas_vendus=[dict(LINHAS[0], qty=3)])
    assert _artigos_das_linhas_vendus(doc, {})[0]["quantidade"] == 3


def test_o_artigo_fica_sem_definicao_e_nao_desaparece():
    a = _artigos_das_linhas_vendus(DOC, {})[0]
    assert a["produto_id"] is None
    assert a["produto_nome"] == "Açaí Mini"
    assert a["categoria_id"] is None


def test_um_documento_sem_linhas_nao_rebenta():
    assert _artigos_das_linhas_vendus(dict(DOC, linhas_vendus=[]), {}) == []


def test_o_evento_da_app_deixa_de_valer_zero():
    class _Col:
        def find(self, *a, **k):
            return self
        def __getattr__(self, _n):
            return lambda *a, **k: self
        async def to_list(self, _n):
            return []
    class _DB:
        def __getitem__(self, _n):
            return _Col()

    eventos = asyncio.get_event_loop().run_until_complete(
        eventos_dos_documentos(_DB(), [DOC]))
    assert len(eventos) == 1
    assert eventos[0]["bruto_c"] == 685, "era 0 antes desta tarefa"
    assert eventos[0]["quantidade"] == 1
    assert eventos[0]["custo_c"] is None
```

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_relatorios_da_app.py -v
```

Esperado: FAIL — `ImportError: cannot import name '_artigos_das_linhas_vendus'`

- [ ] **Passo 3: escrever a função**

Acrescentar a `relatorios.py`, a seguir a `_artigos_da_fatura`:

```python
def _artigos_das_linhas_vendus(documento: Dict, categorias: Dict) -> List[Dict]:
    """Os artigos de um documento que não tem conta de balcão nenhuma.

    **Porque é que isto existe.** `_artigos_da_fatura` começa com
    `if not venda: return []`. Um `[]` não levanta excepção, portanto o
    documento não é descartado pelo `except` de quem chama: vira um evento com
    a soma de uma lista vazia, ou seja **zero**. Media-se assim — a fatura da
    app valia 6,85 € no cartão do Dashboard (que lê `total_bruto` do próprio
    documento) e 0,00 € nas nove vistas dos Relatórios, sem nenhum dos dois
    números parecer errado. E o aviso que existe para isto — «N faturas não se
    deixaram repartir» — conta documentos menos eventos, e o evento existia.

    As linhas vêm como o Vendus as mandou (`items` do `GET documents/{id}/`).
    Reaproveita-se `_artigo`, que é onde as regras do dinheiro já vivem: com
    `produto=None` o `custo_c` sai `None` sozinho — e tem mesmo de ser `None`,
    porque um custo de 0 € contra 6,85 € de venda dá 100% de margem no
    relatório de rentabilidade.
    """
    artigos = []
    for linha in documento.get("linhas_vendus") or []:
        montantes = linha.get("amounts") or {}
        artigos.append(_artigo(
            None, categorias, None,
            linha.get("title") or _SEM_DEFINICAO,
            float(linha.get("qty") or 0),
            centimos(montantes.get("gross_total")),
            (linha.get("tax") or {}).get("rate"),
        ))
    return artigos
```

- [ ] **Passo 4: ligá-la ao motor**

Em `eventos_dos_documentos`, dentro do `try`, trocar

```python
            artigos = (
                _artigos_da_nota(nota, venda, produtos, categorias) if ehNC
                else _artigos_da_fatura(venda, produtos, categorias)
            )
```

por

```python
            # Um documento sem venda mas com as linhas do Vendus reparte-se por
            # elas. É o caso das faturas da app (`origem: "app"`), que não têm
            # conta de balcão nenhuma — ver `_artigos_das_linhas_vendus`.
            if venda is None and doc.get("linhas_vendus"):
                artigos = _artigos_das_linhas_vendus(doc, categorias)
            else:
                artigos = (
                    _artigos_da_nota(nota, venda, produtos, categorias) if ehNC
                    else _artigos_da_fatura(venda, produtos, categorias)
                )
```

- [ ] **Passo 5: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_relatorios_da_app.py -v
```

Esperado: 6 passed

- [ ] **Passo 6: não partir os relatórios que já lá estavam**

```bash
cd backend && python -m pytest tests/faturacao/ -q
```

Esperado: tudo verde. Se algum teste dos Relatórios ou do Dashboard falhar,
**parar** — significa que o ramo novo apanhou documentos que não são da app.

- [ ] **Passo 7: validar por mutação**

Trocar `centimos(montantes.get("gross_total"))` por `0` e correr.
Esperado: falham `test_o_dinheiro_da_linha_e_o_do_vendus` e
`test_o_evento_da_app_deixa_de_valer_zero`. Repor.

- [ ] **Passo 8: commit**

```bash
git add backend/faturacao/relatorios.py backend/tests/faturacao/test_relatorios_da_app.py
git commit -m "Repartir pelas linhas do Vendus a fatura que não tem conta

Sem isto a app valia 6,85 EUR no Dashboard e 0,00 EUR nas nove vistas: o
_artigos_da_fatura devolve [] em vez de levantar, o evento é criado na mesma
com a soma de uma lista vazia, e o aviso de 'não se deixou repartir' — que
conta documentos menos eventos — ficava a zero. O custo fica None e não 0,
senão a margem lê 100%.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: A rota do cron, a definição da loja e a gravação

**Ficheiros:**
- Criar: `backend/faturacao/sincronizacao_rota.py`
- Modificar: `backend/faturacao/__init__.py`
- Testar: `backend/tests/faturacao/test_sincronizacao_rota.py`

**Interfaces:**
- Consome: `deve_importar`, `documento_para_gravar` (Tasks 1 e 3);
  `ClienteEmissaoVendus.ler_documento` (Task 2) e `listar_documentos_por_dia`;
  `db.COLECOES`, `db.obter_db`, `auth.gestor_atual`,
  `vendus.cliente.obter_conta`, `vendus.emissao._register_id_configurado`.
- Produz:
  - `router` (APIRouter) com `GET/PUT /sincronizacao-app/definicoes`,
    `POST /sincronizacao-app/sincronizar-agora`, `POST /cron/sincronizar-app`
  - `async def sincronizar(db, *, dias: List[str], simular: bool = False) -> Dict`
    → `{"lidos": int, "gravados": int, "ignorados": int, "motivos": Dict[str, int],
       "erros": List[str], "simulado": bool}`

- [ ] **Passo 1: escrever os testes que falham**

```python
"""**As portas da sincronização** — a CRON_KEY, a loja por escolher, e o que
acontece quando o Vendus não responde.

As contas de quem entra estão em test_sincronizacao_app.py, sem nada disto pelo
meio. Aqui pergunta-se só: com que autorização, com que configuração, e o que
fica gravado.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import sincronizacao_rota as rota


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_sem_chave_certa_a_porta_fecha(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "a-chave-certa")
    with pytest.raises(HTTPException) as e:
        _corre(rota.cron_sincronizar_app(key="a-errada"))
    assert e.value.status_code == 403


def test_sem_cron_key_no_ambiente_a_porta_fecha(monkeypatch):
    monkeypatch.delenv("CRON_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        _corre(rota.cron_sincronizar_app(key="qualquer"))
    assert e.value.status_code == 403


def test_sem_loja_escolhida_recusa_e_diz_porque(monkeypatch):
    async def _sem_loja(_db):
        return {}
    monkeypatch.setattr(rota, "_definicoes", _sem_loja)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert "loja" in " ".join(resultado["erros"]).lower()


def test_simular_nao_grava_nada(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"],
                                        simular=True))
    assert resultado["simulado"] is True
    assert resultado["gravados"] == 1, "diz o que ia gravar"
    assert gravados == [], "mas não gravou nada"


def test_grava_a_fatura_da_app_e_ignora_o_orcamento(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446, _OT_740, _NOSSA])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 1
    assert resultado["ignorados"] == 2
    assert gravados[0]["origem"] == "app"
    assert gravados[0]["total_bruto"] == 6.85


def test_o_vendus_em_baixo_nao_deixa_nada_a_meio(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446], rebenta_ao_ler=True)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["erros"], "diz o que correu mal"


def test_um_documento_repetido_nao_e_erro(monkeypatch):
    from pymongo.errors import DuplicateKeyError
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446],
            insert_rebenta=DuplicateKeyError("repetido"))
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["erros"] == []
    assert resultado["repetidos"] == 1
```

Os apoios de teste (`_DBFalsa`, `_montar`, `_FS_446`, `_OT_740`, `_NOSSA`) vão no
mesmo ficheiro; `_FS_446` é o documento real da Task 3, `_OT_740` é
`{"id": 371000001, "type": "OT", "external_reference": "", "amount_gross": "740.15"}`
e `_NOSSA` é `{"id": 371000002, "type": "FS", "external_reference": "pos-a-b-c", "atcud": "X-1"}`.

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_rota.py -v
```

Esperado: FAIL — `ModuleNotFoundError: No module named 'faturacao.sincronizacao_rota'`

- [ ] **Passo 3: escrever o módulo**

O ficheiro segue `relatorio_rota.py` linha a linha no que toca à porta do cron
(`compare_digest`, 403, sem JWT) e às definições em `fat_definicoes`. As peças
que ele tem de ter, e que os testes acima já fixam:

```python
"""**Ir buscar ao Vendus as faturas que não saíram do nosso POS.**

A app L'Açaí emite pela MESMA caixa API e pela MESMA série que as cinco lojas.
Este módulo lê essa caixa, deixa passar só o que é venda e não é nosso, e grava
na loja que o gestor escolher. Não escreve nada no Vendus e não sabe o que é a
app: só sabe ler uma caixa e reconhecer o que lá não devia estar sozinho.

A decisão de quem entra vive em `sincronizacao_app.py`, sem Mongo nem rede.
Aqui é só a autorização, a configuração e a gravação.
"""
import asyncio
import logging
import os
import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .sincronizacao_app import deve_importar, documento_para_gravar
from .vendus.cliente import obter_conta
from .vendus.emissao import ClienteEmissaoVendus, VendusErro, _register_id_configurado

logger = logging.getLogger(__name__)
router = APIRouter()

CHAVE = "sincronizacao_app"
PRIMEIRO_DIA = "2026-09-01"   # decisão do dono; a app emite desde 18/08


class DefinicoesEntrada(BaseModel):
    loja_id: Optional[str] = None
    ativo: bool = True


async def _definicoes(db) -> Dict:
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE}, {"_id": 0})
    return doc or {}

async def sincronizar(db, *, dias: List[str], simular: bool = False) -> Dict:
    """Lê os dias pedidos e grava o que for para gravar.

    **Falha inteira, nunca a meio.** Se o Vendus não responder, a volta acaba
    sem gravar e diz porquê — a volta seguinte (5 minutos) apanha tudo. É o que
    torna isto seguro de correr tantas vezes quantas se quiser.

    `simular=True` faz tudo menos a gravação: é como se prova, contra a
    produção, o que ia acontecer antes de deixar acontecer.
    """
    resultado = {"lidos": 0, "gravados": 0, "ignorados": 0, "repetidos": 0,
                 "motivos": {}, "erros": [], "simulado": simular}

    definicoes = await _definicoes(db)
    loja_id = definicoes.get("loja_id")
    if not loja_id:
        resultado["erros"].append(
            "sem loja escolhida para as vendas da app — escolha-a em "
            "Configuração → Lojas. Adivinhar a loja era pôr a receita da app "
            "na loja errada.")
        return resultado
    if not definicoes.get("ativo", True):
        resultado["erros"].append("desligada nas definições")
        return resultado

    conta = obter_conta()
    if conta is None:
        resultado["erros"].append("sem conta Vendus configurada")
        return resultado
    register_id = _register_id_configurado()
    if register_id is None:
        resultado["erros"].append("VENDUS_REGISTER_ID não configurado")
        return resultado

    coleccao = db[COLECOES["documentos"]]
    try:
        with ClienteEmissaoVendus(conta.chave, timeout=60) as cliente:
            for dia in dias:
                documentos = await asyncio.to_thread(
                    cliente.listar_documentos_por_dia, dia, register_id)
                resultado["lidos"] += len(documentos)

                for doc in documentos:
                    entra, motivo = deve_importar(doc)
                    if not entra:
                        resultado["ignorados"] += 1
                        resultado["motivos"][motivo] = \
                            resultado["motivos"].get(motivo, 0) + 1
                        continue

                    # Um documento que já temos não se vai buscar outra vez: é
                    # um pedido ao Vendus por documento, e a esmagadora maioria
                    # das voltas relê dias inteiros que já estão gravados.
                    if await coleccao.find_one(
                            {"vendus_document_id": int(doc["id"])}, {"_id": 1}):
                        resultado["repetidos"] += 1
                        continue

                    # O ATCUD e as linhas só existem no GET por id.
                    cru = await asyncio.to_thread(cliente.ler_documento, doc["id"])
                    if cru is None:
                        resultado["motivos"]["desapareceu do Vendus"] = \
                            resultado["motivos"].get("desapareceu do Vendus", 0) + 1
                        resultado["ignorados"] += 1
                        continue

                    try:
                        pronto = documento_para_gravar(cru, loja_id)
                    except ValueError as e:
                        # Sem ATCUD ou sem id: fica de fora, mas em voz alta.
                        logger.warning("[sinc-app] documento %s não se grava: %s",
                                       doc.get("number"), e)
                        resultado["ignorados"] += 1
                        resultado["motivos"][str(e)] = \
                            resultado["motivos"].get(str(e), 0) + 1
                        continue

                    resultado["gravados"] += 1
                    if simular:
                        continue
                    try:
                        await coleccao.insert_one(pronto)
                    except DuplicateKeyError:
                        # Duas voltas em cima uma da outra. Não é avaria.
                        resultado["gravados"] -= 1
                        resultado["repetidos"] += 1
    except VendusErro as e:
        # A volta acaba aqui. O que já foi gravado fica (cada documento é uma
        # gravação independente e idempotente); o que faltava vem na próxima.
        resultado["erros"].append("%s: %s" % (type(e).__name__, e))
        logger.warning("[sinc-app] volta interrompida: %s", e)

    logger.info("[sinc-app] %s: lidos=%d gravados=%d ignorados=%d repetidos=%d %s",
                "ENSAIO" if simular else "a sério", resultado["lidos"],
                resultado["gravados"], resultado["ignorados"],
                resultado["repetidos"], resultado["motivos"])
    return resultado


def _dias_da_volta() -> List[str]:
    """Hoje e ontem, em dias de Lisboa.

    Ontem também, sempre: apanha a fatura das 23h50 que o Vendus só mostrou
    depois da meia-noite, e as anulações do dia anterior. Duas leituras por
    volta é o preço de não precisar de guardar estado nenhum.
    """
    from .periodos import LISBON_TZ
    from datetime import datetime, timedelta
    hoje = datetime.now(LISBON_TZ).date()
    return [(hoje - timedelta(days=1)).isoformat(), hoje.isoformat()]


@router.get("/sincronizacao-app/definicoes")
async def ler_definicoes_app(_: dict = Depends(gestor_atual)) -> dict:
    return await _definicoes(obter_db())


@router.put("/sincronizacao-app/definicoes")
async def gravar_definicoes_app(dados: DefinicoesEntrada,
                                _: dict = Depends(gestor_atual)) -> dict:
    await obter_db()[COLECOES["definicoes"]].update_one(
        {"id": CHAVE}, {"$set": dados.model_dump()}, upsert=True)
    return await _definicoes(obter_db())


@router.post("/sincronizacao-app/sincronizar-agora")
async def sincronizar_agora(_: dict = Depends(gestor_atual)) -> dict:
    """O botão do backoffice. Lê hoje e ontem, como o cron."""
    return await sincronizar(obter_db(), dias=_dias_da_volta())


@router.post("/cron/sincronizar-app")
async def cron_sincronizar_app(key: str = Query(...)) -> dict:
    """A porta dos 5 minutos. Protegida pela `CRON_KEY`, sem JWT — o mesmo
    padrão de `/cron/relatorio-diario` e de `/api/fin/cron/*`.

    `compare_digest` e não `==`: uma comparação que pára no primeiro carácter
    diferente diz, pelo tempo que demora, quantos caracteres estavam certos.
    """
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return await sincronizar(obter_db(), dias=_dias_da_volta())
```

**A primeira volta é diferente das outras.** `_dias_da_volta` dá hoje e ontem; o
histórico desde `PRIMEIRO_DIA` faz-se UMA vez, à mão, no ensaio da Task 6
(`dias=["2026-09-01", ..., "2026-09-04"]`). Não se põe lógica de retoma no cron
para uma coisa que acontece uma vez: o cron lê dois dias e é tudo o que precisa
de saber fazer.

- [ ] **Passo 4: registar o router**

Em `backend/faturacao/__init__.py`, a seguir a `router.include_router(_nota_credito)`:

```python
from .sincronizacao_rota import router as _sincronizacao  # noqa: E402
router.include_router(_sincronizacao)
```

- [ ] **Passo 5: confrontar o router, não a intenção**

```python
def test_as_rotas_existem_mesmo():
    # Afirmar o endereço que o código escreve nunca apanha um prefixo errado.
    # Pergunta-se ao router.
    from faturacao import router
    caminhos = {r.path for r in router.routes}
    assert "/api/faturacao/cron/sincronizar-app" in caminhos
    assert "/api/faturacao/sincronizacao-app/definicoes" in caminhos
    assert "/api/faturacao/sincronizacao-app/sincronizar-agora" in caminhos
```

- [ ] **Passo 6: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_sincronizacao_rota.py -v
cd backend && python -m pytest tests/faturacao/ -q
```

Esperado: tudo verde.

- [ ] **Passo 7: commit**

```bash
git add backend/faturacao/sincronizacao_rota.py backend/faturacao/__init__.py backend/tests/faturacao/test_sincronizacao_rota.py
git commit -m "A porta do cron da sincronização, e a loja como definição

A loja escolhe-se no backoffice e sem ela a sincronização recusa-se a correr:
adivinhar a loja era pôr a receita da app na loja errada.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: O ensaio contra a produção, sem gravar nada

Esta tarefa não escreve código de produção. É o portão antes de deixar escrever
na base que o dono usa para contar dinheiro.

**Ficheiros:** nenhum alterado.

- [ ] **Passo 1: publicar o ramo em produção**

Seguir a skill `fluxo` (secção B): juntar ao main atualizado e publicar. **Sem
instalar o cron** — o endpoint fica lá, ninguém lhe toca.

- [ ] **Passo 2: escolher a loja no backoffice**

Configuração → Lojas → "App Online" → marcar como loja das vendas da app.

- [ ] **Passo 3: correr o ensaio**

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose exec -T backend python -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from faturacao.sincronizacao_rota import sincronizar
async def m():
    c=AsyncIOMotorClient(os.environ[\"MONGO_URL\"]); db=c[os.environ[\"DB_NAME\"]]
    dias=[\"2026-09-0%d\"%d for d in range(1,5)]
    print(await sincronizar(db, dias=dias, simular=True))
asyncio.run(m())
"'
```

- [ ] **Passo 4: confrontar com o Vendus**

O resultado tem de dizer **`gravados: 1`** para 01/09–04/09 (a `FS 06P2026/446`,
6,85 €) e **ignorar os cinco `OT` e os dois `RG`**. Se disser mais do que isso,
**parar** e perceber o que entrou a mais antes de seguir.

- [ ] **Passo 5: mostrar o resultado ao dono e esperar o "sim"**

O ensaio diz o que ia acontecer. A gravação a sério é decisão dele, não minha.

---

### Task 7: Ligar a sério

**Ficheiros:**
- Criar: `faturacao-app-cron.sh`
- Modificar: `DEPLOY.md`

- [ ] **Passo 1: escrever o script**

```bash
#!/usr/bin/env bash
# Sincronizacao das faturas da app L'Acai — de 5 em 5 minutos.
#
# Vai buscar ao Vendus os documentos da Caixa Online que NAO sairam do nosso
# POS e grava-os na loja "App Online". Le sempre HOJE e ONTEM: apanha os
# atrasos e as anulacoes tardias sem ter de guardar estado nenhum.
#
# Corre DENTRO do contentor backend (localhost:8000, sem timeout de proxy), no
# mesmo padrao dos outros crons desta casa.
#
# A hora nao importa aqui (corre o dia todo), mas o servidor esta' em UTC — ver
# relatorio-diario-cron.sh, onde isso morde.
#
# Instalar (no servidor), UMA vez:
#   crontab -e
#   */5 * * * *  /root/RH/faturacao-app-cron.sh >> /var/log/rh-sinc-app.log 2>&1
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/faturacao/cron/sincronizar-app?key="+os.environ["CRON_KEY"], method="POST"), timeout=600).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sincronizacao da app disparada"
```

```bash
chmod +x faturacao-app-cron.sh
```

- [ ] **Passo 2: a primeira volta a sério (só um dia)**

```bash
ssh root@187.124.4.163 'cd ~/RH && ./faturacao-app-cron.sh'
```

- [ ] **Passo 3: confirmar no ecrã, não no log**

Abrir o portal → Faturação → Relatórios → 01/09 a 04/09, e confirmar:
- a loja "App Online" aparece com **6,85 €** e **1 documento**;
- o total do Diário de 01/09 passou de **1.545,65 €** para **1.552,50 €**;
- a vista **Produtos** mostra "Açaí Mini" com quantidade 1 e o total das nove
  vistas continua igual ao do Diário;
- a margem do "Açaí Mini" aparece como **"—"** e não como 100%.

- [ ] **Passo 4: instalar o cron**

```bash
ssh root@187.124.4.163 'crontab -l | grep -q faturacao-app-cron || (crontab -l; echo "*/5 * * * *  /root/RH/faturacao-app-cron.sh >> /var/log/rh-sinc-app.log 2>&1") | crontab -'
ssh root@187.124.4.163 'crontab -l'
```

- [ ] **Passo 5: documentar e commitar**

Acrescentar o script à lista de crons em `DEPLOY.md` (linha ~192).

```bash
git add faturacao-app-cron.sh DEPLOY.md
git commit -m "Ligar a sincronização das faturas da app de 5 em 5 minutos

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Os ecrãs

**Ficheiros:**
- Modificar: `backend/faturacao/documentos.py` (`_detalhe_do_documento`, `_quem_e_onde`)
- Modificar: `frontend/src/pages/admin/faturacao/FatDocumentos.js`
- Modificar: `frontend/src/pages/admin/faturacao/FatLojas.js`
- Testar: `backend/tests/faturacao/test_documentos_da_app.py`

- [ ] **Passo 1: escrever os testes do backend que falham**

```python
"""**Uma fatura da app aberta no ecrã de Documentos.**

O detalhe monta-se a partir da venda. Estes documentos não têm venda nenhuma, e
o ecrã não pode ler essa ausência como "esta fatura não levou nada".
"""
import asyncio

from faturacao.documentos import _detalhe_do_documento

DOC = {"id": "abc", "numero": "FS 06P2026/446", "atcud": "J6SHGSNX-446",
       "tipo": "FS", "modo": "normal", "total": 6.85, "total_bruto": 6.85,
       "total_liquido": 6.06, "emitido_em": "2026-09-01T13:43:25+00:00",
       "loja_id": "loja-app", "venda_id": None, "origem": "app",
       "linhas_vendus": [{"qty": 1, "title": "Açaí Mini",
                          "amounts": {"gross_total": "6.85", "net_total": "6.06"},
                          "tax": {"id": "INT", "rate": 13}}]}


def test_as_linhas_da_app_aparecem_no_detalhe():
    d = asyncio.get_event_loop().run_until_complete(
        _detalhe_do_documento(_DBSemVenda(), DOC))
    assert len(d["linhas"]) == 1
    assert d["linhas"][0]["descricao"] == "Açaí Mini"


def test_o_total_nao_aparece_divergente():
    # `total_divergente` compara o total com a soma das linhas. Sem as linhas
    # da app, o ecrã acendia um aviso de fatura estragada numa fatura sã.
    d = asyncio.get_event_loop().run_until_complete(
        _detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["total_divergente"] is False


def test_a_origem_diz_app_e_nao_pos():
    d = asyncio.get_event_loop().run_until_complete(
        _detalhe_do_documento(_DBSemVenda(), DOC, com_contexto=True))
    assert d["origem"] == "App L'Açaí"
    assert d["operador_nome"] is None
    assert d["caixa_nome"] is None


def test_nao_ha_talao_para_reimprimir():
    d = asyncio.get_event_loop().run_until_complete(
        _detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["tem_talao"] is False
```

- [ ] **Passo 2: correr e ver falhar**

```bash
cd backend && python -m pytest tests/faturacao/test_documentos_da_app.py -v
```

Esperado: FAIL — as linhas vêm vazias e `origem` diz `"POS"`.

- [ ] **Passo 3: no backend, alimentar o detalhe pelas linhas do Vendus**

Em `documentos.py`, acrescentar antes de `_detalhe_do_documento`:

```python
def _linhas_das_linhas_vendus(documento: Dict) -> List[Dict]:
    """As linhas de uma fatura que não tem conta de balcão nenhuma.

    O ecrã de Documentos monta as linhas a partir da venda. Estes documentos
    não têm venda, e a ausência das linhas não pode ser lida como "esta fatura
    não levou nada" — pior, `total_divergente` compara o total com a soma das
    linhas e acendia um aviso de fatura estragada numa fatura sã.
    """
    linhas = []
    for linha in documento.get("linhas_vendus") or []:
        montantes = linha.get("amounts") or {}
        linhas.append({
            "descricao": linha.get("title") or "—",
            "quantidade": float(linha.get("qty") or 0),
            "preco_unitario": float(montantes.get("gross_unit") or 0),
            "total": float(montantes.get("gross_total") or 0),
            "taxa": (linha.get("tax") or {}).get("rate"),
            # Não há produto nosso do outro lado: o ecrã escreve o nome que o
            # Vendus mandou e não finge que conhece o artigo.
            "produto_id": None,
        })
    return linhas
```

Em `_detalhe_do_documento`, trocar

```python
    linhas = _linhas_da_fatura(venda)
```

por

```python
    # Sem venda mas com as linhas do Vendus: é uma fatura da app.
    linhas = (_linhas_das_linhas_vendus(documento)
              if venda is None and documento.get("linhas_vendus")
              else _linhas_da_fatura(venda))
```

e, no dicionário devolvido, trocar

```python
        "mapa_imposto": mapa,
```

por

```python
        "mapa_imposto": (_mapa_das_linhas_vendus(documento)
                         if venda is None and documento.get("linhas_vendus")
                         else mapa),
```

com

```python
def _mapa_das_linhas_vendus(documento: Dict) -> List[Dict]:
    """O mapa de imposto a partir das linhas do Vendus, agrupado por taxa."""
    por_taxa: Dict = {}
    for linha in documento.get("linhas_vendus") or []:
        montantes = linha.get("amounts") or {}
        taxa = (linha.get("tax") or {}).get("rate")
        entrada = por_taxa.setdefault(taxa, {"taxa": taxa, "base": 0.0, "iva": 0.0})
        bruto = float(montantes.get("gross_total") or 0)
        base = float(montantes.get("net_total") or 0)
        entrada["base"] += base
        entrada["iva"] += bruto - base
    return [{"taxa": v["taxa"], "base": round(v["base"], 2),
             "iva": round(v["iva"], 2)} for v in por_taxa.values()]
```

Em `_quem_e_onde`, trocar

```python
        "origem": "POS",
```

por

```python
        # A app não tem operador nem caixa, e a linha do ecrã tem de o dizer
        # em vez de deixar dois traços sem explicação.
        "origem": "App L'Açaí" if documento.get("origem") == "app" else "POS",
```

- [ ] **Passo 4: no ecrã de Documentos, esconder o que não existe**

Em `FatDocumentos.js`, esconder o botão **Reimprimir** quando `!aberto.tem_talao`
(a origem já aparece na linha 453, que lê `aberto.origem`).

- [ ] **Passo 5: no ecrã de Lojas, escolher a loja e sincronizar**

Em `FatLojas.js`, dentro do cartão de cada loja: uma etiqueta "Vendas da app"
quando é a loja escolhida, um botão para a escolher (PUT
`/sincronizacao-app/definicoes`), e um botão "Sincronizar agora" (POST
`/sincronizacao-app/sincronizar-agora`) que mostra o resultado num toast.

- [ ] **Passo 6: correr e ver passar**

```bash
cd backend && python -m pytest tests/faturacao/ -q
```

- [ ] **Passo 7: ver no browser, não só nos testes**

Publicar, abrir o portal, abrir a `FS 06P2026/446` no ecrã de Documentos e
confirmar: mostra "Açaí Mini", diz "App L'Açaí", o PDF do Vendus abre, e não há
botão de Reimprimir. **Os ecrãs do POS desenham-se sem servidor nenhum — dois
defeitos já foram a produção assim.**

- [ ] **Passo 8: commit**

```bash
git add backend/faturacao/documentos.py frontend/src/pages/admin/faturacao/FatDocumentos.js frontend/src/pages/admin/faturacao/FatLojas.js backend/tests/faturacao/test_documentos_da_app.py
git commit -m "Mostrar uma fatura da app no ecrã de Documentos e escolher a loja

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: O email diário não mente sobre a loja da app

**Ficheiros:**
- Modificar: `backend/faturacao/relatorio_diario.py`
- Testar: `backend/tests/faturacao/test_relatorio_diario_com_app.py`

- [ ] **Passo 1: escrever os testes que falham**

```python
"""A loja da app no email das 23:30 — com faturação, sem caixa.

Ela não tem sessão de caixa nenhuma e não vai ter: a app cobra por Stripe. O
email não pode escrever "não fechou a caixa" sobre uma loja que não tem gaveta,
nem somar a receita dela à repartição por tipo de pagamento das outras cinco.
"""
from faturacao.relatorio_diario import montar_dados

LOJAS = [{"id": "loja-app", "nome": "App Online"},
         {"id": "loja-1", "nome": "L'açaí Belém"}]

DOC_APP = {"id": "d1", "tipo": "FS", "loja_id": "loja-app",
           "emitido_em": "2026-09-01T13:43:25+00:00",
           "total_bruto": 6.85, "total_liquido": 6.06, "origem": "app"}


def _dados(turnos=()):
    return montar_dados(dia="2026-09-01", ate="23:30", com_iva=True,
                        docs_de_hoje=[DOC_APP], docs_de_ontem=[],
                        lojas=LOJAS, turnos=list(turnos))


def _linha_da_app():
    return [l for l in _dados()["lojas"] if l["nome"] == "App Online"][0]


def test_a_loja_da_app_aparece_com_facturacao():
    linha = _linha_da_app()
    assert linha["faturacao"] == 6.85
    assert linha["documentos"] == 1


def test_nao_diz_que_a_loja_da_app_nao_fechou_a_caixa():
    linha = _linha_da_app()
    assert linha["caixa"] is None
    assert linha["sem_vendas"] is False


def test_a_app_nao_entra_na_reparticao_por_tipo_de_pagamento():
    # A app cobra por Stripe: não passa pela gaveta de ninguém. Somá-la aqui
    # punha a repartição a discordar do dinheiro contado nas lojas.
    linha = _linha_da_app()
    assert linha["pagamentos"] == []


def test_a_facturacao_geral_inclui_a_app_na_mesma():
    assert _dados()["geral"]["faturacao"] == 6.85
```

Confirmar a assinatura real de `montar_dados` antes de escrever o teste:

```bash
cd backend && grep -n "def montar_dados" -A 12 faturacao/relatorio_diario.py
```

Se os parâmetros diferirem, ajustar a chamada `_dados()` — os **assertos** ficam
como estão, que é o que interessa.

- [ ] **Passo 2: correr, ver falhar, corrigir, ver passar**

```bash
cd backend && python -m pytest tests/faturacao/test_relatorio_diario_com_app.py -v
```

- [ ] **Passo 3: enviar um a sério e lê-lo**

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose exec -T backend python -c "import os, urllib.request as u; print(u.urlopen(u.Request(\"http://localhost:8000/api/faturacao/cron/relatorio-diario?key=\"+os.environ[\"CRON_KEY\"], method=\"POST\"), timeout=600).read().decode()[:300])"'
```

Abrir o email e confirmar que a loja "App Online" lá está com o valor certo e
sem uma coluna de caixa a acusar ninguém.

- [ ] **Passo 4: commit**

```bash
git add backend/faturacao/relatorio_diario.py backend/tests/faturacao/test_relatorio_diario_com_app.py
git commit -m "A loja da app no email diário: com faturação, sem caixa

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Revisão do plano contra a especificação

| Requisito da spec | Tarefa |
|---|---|
| Regra de quem entra (só FS/NC, não `pos-`, não anulado, não teste) | 1 |
| Ler o ATCUD e as linhas | 2 |
| Gravar no formato de `fat_documentos`, com `origem` e `linhas_vendus` | 3 |
| Os três campos que não existem (`venda_id`, caixa, operador) | 3 |
| `emitido_em` com o instante do Vendus, em ISO `+00:00` | 3 |
| Dashboard (Hoje/Mensal/Anual + cartão da loja) | nenhuma — funciona só com a Task 3 |
| As nove vistas dos Relatórios | 4 |
| Produtos e Categorias com "sem correspondência" | 4 |
| Custo `None` para a margem não mentir | 4 |
| Cron de 5 em 5 minutos + `CRON_KEY` | 5, 7 |
| Loja como definição, recusa sem ela | 5 |
| Janela hoje+ontem (`_dias_da_volta`) | 5 |
| Histórico desde 01/09, uma vez à mão | 6 |
| Falhar inteiro, nunca a meio | 5 |
| Repetidos ignorados em silêncio | 5 |
| Ensaio sem gravar contra a produção | 6 |
| Botão "Sincronizar agora" | 8 |
| Documentos: origem, linhas, PDF, sem Reimprimir | 8 |
| Clientes (NIF da app) | nenhuma — funciona só com a Task 3 (`cliente_nif`) |
| Email diário com a loja sem caixa | 9 |
| Anulações apanhadas na janela de dois dias | 5 |

Sem lacunas. As três linhas "nenhuma" são de propósito: o mapeamento do código
mostrou que o Dashboard e o ecrã de Clientes leem os campos do documento
diretamente, e passam a incluir a app assim que ela existir em `fat_documentos`.
