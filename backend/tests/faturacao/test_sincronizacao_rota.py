"""**As portas da sincronização** — a CRON_KEY, a loja por escolher, e o que
acontece quando o Vendus não responde.

As contas de quem entra estão em test_sincronizacao_app.py, sem nada disto pelo
meio. Aqui pergunta-se só: com que autorização, com que configuração, e o que
fica gravado.

Nem rede nem Mongo: o cliente do Vendus e a colecção são duplos, e o duplo do
cliente só sabe fazer as DUAS leituras permitidas — qualquer outra chamada
(escrever um documento, mexer na caixa) rebenta com `AttributeError` em vez de
passar despercebida.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from faturacao import sincronizacao_rota as rota
from faturacao.db import COLECOES
from faturacao.vendus.emissao import VendusIndisponivel


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


LOJA = "98331284-ba8d-41b8-b074-4059902d68a9"
CAIXA = 360180538  # a caixa API onde a app e as cinco lojas emitem

# Os três documentos como o Vendus os devolveu mesmo, lidos em produção a
# 2026-09-04: a fatura da app, um orçamento de 740 € (que não é venda nenhuma)
# e uma fatura nossa (a `ext_ref` começa por `pos-`).
_FS_446 = {
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
_OT_740 = {"id": 371000001, "type": "OT", "external_reference": "",
           "amount_gross": "740.15"}
_NOSSA = {"id": 371000002, "type": "FS", "external_reference": "pos-a-b-c",
          "atcud": "X-1"}


# --- Os duplos ---------------------------------------------------------------

# `sincronizar` recebe a base de dados como argumento e os testes constroem
# `_DBFalsa()` sem argumentos nenhuns; a colecção que interessa é a que
# `_montar` deixa aqui. `monkeypatch.setitem` limpa-a no fim de cada teste.
_ESTADO = {}


class _ColeccaoFalsa:
    def __init__(self, gravados, insert_rebenta=None, ja_gravados=(),
                 colide_com_outro=False, nao_da_app=()):
        self.gravados = gravados
        self.insert_rebenta = insert_rebenta
        self.ja_gravados = set(ja_gravados)
        # Quem já leva `anulado: True` na base. Separado dos `ja_gravados`
        # porque é exactamente o que distingue a primeira volta da segunda.
        self.anulados = set()
        # Os que estão na base com `origem` diferente de `app` — as ~750 FS
        # reais das cinco lojas. Sem eles no duplo, a cerca do `origem: "app"`
        # não tinha como ficar vermelha.
        self.nao_da_app = set(nao_da_app)
        # O `insert_one` rebenta porque OUTRO documento já ocupa o `atcud` ou
        # a `ext_ref`, não porque este já lá esteja. É a diferença entre "duas
        # voltas em cima uma da outra" e "um documento novo deitado fora".
        self.colide_com_outro = colide_com_outro

    async def find_one(self, filtro, projeccao=None):
        if not self._corresponde(filtro):
            return None
        return {"_id": "x"}

    def _corresponde(self, filtro) -> bool:
        """O duplo tem de honrar o filtro TODO, não só o `vendus_document_id`.

        `_marcar_anulado` procura por `{vendus_document_id, anulado: {$ne:
        True}}`, e é o segundo termo que faz a idempotência: um duplo que o
        ignorasse contava a mesma anulação em todas as voltas — 288 vezes por
        dia — e o teste da segunda volta passava a verde a mentir.
        """
        if filtro.get("vendus_document_id") not in self.ja_gravados:
            return False
        if (filtro.get("origem") == "app"
                and filtro["vendus_document_id"] in self.nao_da_app):
            return False
        if filtro.get("anulado") == {"$ne": True}:
            return filtro["vendus_document_id"] not in self.anulados
        return True

    async def update_one(self, filtro, alteracao):
        if not self._corresponde(filtro):
            return SimpleNamespace(modified_count=0)
        if alteracao.get("$set", {}).get("anulado"):
            self.anulados.add(filtro["vendus_document_id"])
        return SimpleNamespace(modified_count=1)

    async def insert_one(self, documento):
        if self.insert_rebenta is not None:
            if not self.colide_com_outro:
                # A outra volta gravou-o MESMO: a partir daqui ele está lá,
                # como estaria no Mongo.
                self.ja_gravados.add(documento["vendus_document_id"])
            raise self.insert_rebenta
        self.gravados.append(documento)
        self.ja_gravados.add(documento["vendus_document_id"])


class _DefinicoesFalsas:
    """`fat_definicoes` como o Mongo a devolve: um documento por chave."""

    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, _filtro, _projeccao=None):
        return self.doc


class _DBFalsa:
    """Regista o NOME de cada colecção pedida.

    Numa base com ~750 Faturas Simplificadas fiscais reais, a colecção em que
    se escreve é o que separa uma sincronização de um estrago: um duplo que
    deita fora o nome deixa passar um `fat_vendas` no lugar de
    `fat_documentos` sem um único teste vermelho.
    """

    def __init__(self):
        self.pedidas = []

    def __getitem__(self, nome):
        self.pedidas.append(nome)
        if nome == COLECOES["definicoes"]:
            return _ESTADO.get("definicoes") or _DefinicoesFalsas(None)
        return _ESTADO.get("coleccao") or _ColeccaoFalsa([])


class _ClienteFalso:
    """Só sabe LER, e regista tudo o que lhe pediram."""

    def __init__(self, documentos, rebenta_ao_ler=False, rebenta_a_listar=False):
        self.documentos = list(documentos)
        # Um documento sem `id`, ou com um `id` ilegível (texto em vez de
        # número), não tem detalhe nenhum para ir buscar — não há GET por id
        # que se lhe faça. É por isso que os dois ficam de fora aqui.
        self.detalhes = {}
        for d in documentos:
            if not d.get("id"):
                continue
            try:
                self.detalhes[int(d["id"])] = d
            except (TypeError, ValueError):
                continue
        self.rebenta_ao_ler = rebenta_ao_ler
        self.rebenta_a_listar = rebenta_a_listar
        self.pedidos = []

    def __enter__(self):
        return self

    def __exit__(self, *_excepcao):
        return None

    def listar_documentos_por_dia(self, dia, register_id):
        self.pedidos.append(("listar", dia, register_id))
        if self.rebenta_a_listar:
            raise VendusIndisponivel("o Vendus não respondeu")
        return list(self.documentos)

    def ler_documento(self, documento_id):
        self.pedidos.append(("ler", int(documento_id)))
        if self.rebenta_ao_ler:
            raise VendusIndisponivel("o Vendus não respondeu")
        return self.detalhes.get(int(documento_id))


def _montar(monkeypatch, gravados, *, documentos, rebenta_ao_ler=False,
            rebenta_a_listar=False, insert_rebenta=None, ja_gravados=(),
            colide_com_outro=False, nao_da_app=()):
    monkeypatch.setitem(
        _ESTADO, "coleccao",
        _ColeccaoFalsa(gravados, insert_rebenta, ja_gravados, colide_com_outro,
                       nao_da_app))
    # As definições vêm da BASE, não de um `_definicoes` substituído: é o que
    # deixa `test_so_toca_nas_coleccoes_certas` ver as duas colecções que a
    # sincronização toca de verdade.
    monkeypatch.setitem(
        _ESTADO, "definicoes",
        _DefinicoesFalsas({"loja_id": LOJA, "ativo": True}))
    monkeypatch.setattr(rota, "obter_conta",
                        lambda *a, **kw: SimpleNamespace(chave="chave-de-teste"))
    monkeypatch.setattr(rota, "_register_id_configurado", lambda: CAIXA)
    cliente = _ClienteFalso(documentos, rebenta_ao_ler=rebenta_ao_ler,
                            rebenta_a_listar=rebenta_a_listar)
    monkeypatch.setattr(rota, "ClienteEmissaoVendus", lambda *a, **kw: cliente)
    return cliente


# --- A porta do cron ---------------------------------------------------------


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


def test_sem_cron_key_nem_a_palavra_None_abre_a_porta(monkeypatch):
    """A guarda é o `not chave`, não o `compare_digest`.

    Sem a variável, `chave` é `None` e `str(None)` é `"None"` — uma comparação
    que só olhasse para o `compare_digest` deixava entrar quem adivinhasse
    essa palavra de cinco letras. Sem `CRON_KEY` no ambiente NINGUÉM entra,
    seja qual for a chave que traga.
    """
    monkeypatch.delenv("CRON_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        _corre(rota.cron_sincronizar_app(key="None"))
    assert e.value.status_code == 403


# --- A configuração ----------------------------------------------------------


def test_sem_loja_escolhida_recusa_e_diz_porque(monkeypatch):
    async def _sem_loja(_db):
        return {}
    monkeypatch.setattr(rota, "_definicoes", _sem_loja)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert "loja" in " ".join(resultado["erros"]).lower()


def test_desligada_nas_definicoes_nao_corre(monkeypatch):
    """Não basta `erros` não estar vazio: `obter_conta()` sem `_montar` também
    devolve `None` e enche `erros` na mesma, com "sem conta Vendus
    configurada" — um `if False:` no lugar da guarda `ativo` passava a suite
    na mesma, por um motivo que nada tem a ver com estar desligada."""
    async def _desligada(_db):
        return {"loja_id": LOJA, "ativo": False}
    monkeypatch.setattr(rota, "_definicoes", _desligada)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["erros"] == ["desligada nas definições"]


# --- A gravação --------------------------------------------------------------


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


def test_um_documento_que_ja_temos_nao_se_vai_buscar_outra_vez(monkeypatch):
    """A volta dos 5 minutos relê dias inteiros já gravados: cada documento
    relido era um pedido ao Vendus que não faz falta nenhum."""
    gravados = []
    cliente = _montar(monkeypatch, gravados, documentos=[_FS_446],
                      ja_gravados=[370665072])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["repetidos"] == 1
    assert gravados == []
    assert ("ler", 370665072) not in cliente.pedidos


def test_o_vendus_em_baixo_nao_deixa_nada_a_meio(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446], rebenta_ao_ler=True)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["erros"], "diz o que correu mal"


def test_o_vendus_em_baixo_a_listar_tambem_acaba_a_volta(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446], rebenta_a_listar=True)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert gravados == []
    assert resultado["erros"]


def test_um_documento_repetido_nao_e_erro(monkeypatch):
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446],
            insert_rebenta=DuplicateKeyError("repetido"))
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["erros"] == []
    assert resultado["repetidos"] == 1
    assert resultado["gravados"] == 0


def test_um_duplicado_que_e_OUTRO_documento_nao_se_deita_fora(monkeypatch):
    """O `DuplicateKeyError` não quer dizer "já o temos".

    `fat_documentos` tem três chaves únicas (db.py:132-158) e o `find_one` de
    antes só cobre uma, `vendus_document_id`. Um choque em `atcud` ou na
    `ext_ref` parcial é um documento DIFERENTE — o caso real é uma NC da app
    (está em `TIPOS_ACEITES`) que traga a `external_reference` da FS que
    anula: a fatura fica, o estorno nunca entra, e a receita daquela loja fica
    inflacionada em silêncio, com `erros: []` e um `ler_documento` gasto ao
    Vendus em cada volta, para sempre.
    """
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446],
            insert_rebenta=DuplicateKeyError("atcud repetido"),
            colide_com_outro=True)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["repetidos"] == 0, "não é o mesmo documento outra vez"
    assert len(resultado["erros"]) == 1
    assert "FS 06P2026/446" in resultado["erros"][0]
    assert "manual" in resultado["erros"][0]


def test_um_documento_sem_id_na_lista_nao_derruba_a_volta(monkeypatch):
    """`deve_importar` deixa passar um documento sem `id` — decide por tipo,
    ref e estado. O `int(doc["id"])` levantava então um `KeyError`, que não é
    `VendusErro` nenhuma: escapava a `sincronizar` inteira, o documento
    seguinte nunca chegava a ser gravado, e o cron levava um 500 de cinco em
    cinco minutos."""
    sem_id = {"type": "FS", "external_reference": "LA-x", "number": "FS ?/?"}
    gravados = []
    _montar(monkeypatch, gravados, documentos=[sem_id, _FS_446])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 1, "o documento a seguir entra na mesma"
    assert gravados[0]["vendus_document_id"] == 370665072
    assert resultado["ignorados"] == 1
    assert resultado["erros"] == []
    assert any("sem id" in linha for linha in resultado["assinalados"])


def test_um_id_ilegivel_na_lista_nao_derruba_a_volta(monkeypatch):
    """Um `id` PRESENTE mas ilegível (texto em vez de número) passa a guarda
    do `not doc.get("id")` sem problema — é o `int(doc["id"])` a seguir que
    levantava `ValueError`, que também não é `VendusErro` nenhuma: o mesmo
    estrago do `KeyError` do id em falta, só com o gatilho menos provável."""
    id_ilegivel = {"id": "abc-nao-e-numero", "type": "FS",
                  "external_reference": "LA-x", "number": "FS ?/?"}
    gravados = []
    _montar(monkeypatch, gravados, documentos=[id_ilegivel, _FS_446])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 1, "o documento a seguir entra na mesma"
    assert gravados[0]["vendus_document_id"] == 370665072
    assert resultado["ignorados"] == 1
    assert resultado["erros"] == []
    assert any("ilegível" in linha for linha in resultado["assinalados"])


def test_o_documento_saltado_fica_a_vista_de_quem_pode_agir(monkeypatch):
    """Um documento saltado por avaria fica de fora PARA SEMPRE — a janela da
    volta é só hoje e ontem. Um `logger.warning` e uma chave em `motivos` não
    chegam a ninguém: `erros` fica vazio, o cron parece saudável, e uma FS
    real de 6,85 € desaparece do Dashboard sem nada visível."""
    ilegivel = dict(_FS_446, id=371000003, atcud="J6SHGSNX-445",
                    number="FS 06P2026/445", amount_gross="8,99")
    sem_atcud = dict(_FS_446, id=371000004, number="FS 06P2026/444")
    sem_atcud.pop("atcud")
    gravados = []
    cliente = _montar(monkeypatch, gravados,
                      documentos=[ilegivel, sem_atcud, _FS_446])
    del cliente.detalhes[370665072]  # e este desapareceu do Vendus
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["ignorados"] == 3
    assert len(resultado["assinalados"]) == 3, "um por documento, não um total"
    juntos = " | ".join(resultado["assinalados"])
    for numero in ("FS 06P2026/445", "FS 06P2026/444", "FS 06P2026/446"):
        assert numero in juntos, "identifica o documento, não só a razão"
    assert "ATCUD" in juntos and "desapareceu do Vendus" in juntos


def test_uma_exclusao_normal_nao_se_assinala(monkeypatch):
    """Um orçamento e uma fatura nossa ficam de fora de propósito, e todas as
    voltas os voltam a ver. Assinalá-los era encher a lista de ruído até
    ninguém olhar para ela — que é o mesmo que não ter lista."""
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446, _OT_740, _NOSSA])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["ignorados"] == 2
    assert resultado["assinalados"] == []


def test_so_toca_nas_coleccoes_certas(monkeypatch):
    """A colecção em que se escreve não é um detalhe: `fat_documentos` tem
    ~750 Faturas Simplificadas fiscais reais de cinco lojas."""
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446])
    db = _DBFalsa()
    _corre(rota.sincronizar(db, dias=["2026-09-01"]))
    assert gravados, "guarda: o caminho chegou mesmo à gravação"
    assert set(db.pedidas) == {"fat_definicoes", "fat_documentos"}


def test_o_vendus_sincrono_nunca_corre_no_event_loop(monkeypatch):
    """O cliente do Vendus é SÍNCRONO e `sincronizar` é `async`.

    Sem os dois `asyncio.to_thread`, cada leitura pendura o event loop do
    portal inteiro — o ponto, as escalas, o POS das cinco lojas — enquanto o
    Vendus responde (timeout de 60s). E não há teste que o note: o resultado
    da volta fica exactamente igual.
    """
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446])
    fora_do_loop = []
    verdadeiro = asyncio.to_thread

    async def _espia(funcao, *args, **kw):
        fora_do_loop.append(getattr(funcao, "__name__", str(funcao)))
        return await verdadeiro(funcao, *args, **kw)

    monkeypatch.setattr(rota.asyncio, "to_thread", _espia)
    _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert gravados, "guarda: a volta chegou mesmo ao fim"
    assert fora_do_loop == ["listar_documentos_por_dia", "ler_documento"]


# --- As definições do backoffice ---------------------------------------------


class _DBDefinicoes:
    """A base do PUT: `fat_lojas` só sabe dizer se a loja existe e
    `fat_definicoes` guarda o que lhe mandarem."""

    def __init__(self, *, lojas=()):
        self.lojas = set(lojas)
        self.gravado = None
        self.nome = None

    def __getitem__(self, nome):
        self.nome = nome
        return self

    async def find_one(self, filtro, _projeccao=None):
        if self.nome == COLECOES["lojas"]:
            return {"id": filtro["id"]} if filtro["id"] in self.lojas else None
        return self.gravado

    async def update_one(self, _filtro, alteracao, upsert=False):
        self.gravado = dict(alteracao["$set"])


def test_uma_loja_que_nao_existe_nao_se_grava(monkeypatch):
    """Uma `loja_id` órfã não dá erro nenhum a gravar — e depois a FS da app
    fica invisível em toda a vista filtrada por loja enquanto continua a
    contar no total de "todas as lojas". Dois números diferentes que ninguém
    consegue explicar."""
    db = _DBDefinicoes(lojas=[])
    monkeypatch.setattr(rota, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(rota.gravar_definicoes_app(
            rota.DefinicoesEntrada(loja_id="nao-existe-nenhures")))
    assert e.value.status_code in (404, 422)
    assert "loja" in str(e.value.detail).lower()
    assert db.gravado is None, "e não gravou nada"


def test_a_loja_que_existe_grava_se(monkeypatch):
    db = _DBDefinicoes(lojas=[LOJA])
    monkeypatch.setattr(rota, "obter_db", lambda: db)
    resultado = _corre(rota.gravar_definicoes_app(
        rota.DefinicoesEntrada(loja_id=LOJA)))
    assert resultado["loja_id"] == LOJA
    assert resultado["ativo"] is True


def test_um_total_ilegivel_nao_TAPA_os_documentos_seguintes(monkeypatch):
    """Um `amount_gross` que não se lê é um documento que fica de fora — não o
    fim da volta.

    `documento_para_gravar` levanta `VendusRespostaIlegivel` num total
    ilegível, e essa é uma `VendusErro`: apanhada pelo `except` de fora,
    acabava a volta INTEIRA. Só que, ao contrário do Vendus em baixo, isto
    repete-se para sempre — o mesmo documento volta a aparecer daí a cinco
    minutos, e tudo o que vem a seguir a ele nunca mais entrava. Fica de fora
    ele, contado e em voz alta, e a volta segue.
    """
    ilegivel = dict(_FS_446, id=371000003, atcud="J6SHGSNX-445",
                    number="FS 06P2026/445", amount_gross="8,99")
    gravados = []
    _montar(monkeypatch, gravados, documentos=[ilegivel, _FS_446])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 1
    assert gravados[0]["vendus_document_id"] == 370665072
    assert resultado["ignorados"] == 1
    assert resultado["erros"] == []


def test_um_documento_que_desapareceu_do_vendus_nao_rebenta(monkeypatch):
    gravados = []
    cliente = _montar(monkeypatch, gravados, documentos=[_FS_446])
    cliente.detalhes = {}  # o GET por id devolve None
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["ignorados"] == 1
    assert resultado["erros"] == []


def test_nunca_pede_ao_vendus_nada_alem_das_duas_LEITURAS(monkeypatch):
    """Escrever no Vendus, ou mexer em `registers/movements`, fechava a caixa
    por baixo da app. O duplo só tem os dois métodos de leitura — qualquer
    outra chamada rebentava aqui."""
    gravados = []
    cliente = _montar(monkeypatch, gravados, documentos=[_FS_446])
    _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert {p[0] for p in cliente.pedidos} == {"listar", "ler"}
    assert ("listar", "2026-09-01", CAIXA) in cliente.pedidos


# --- O router ----------------------------------------------------------------


def test_as_rotas_existem_mesmo():
    """Afirmar o endereço que o código escreve nunca apanha um prefixo errado
    — pergunta-se ao router. E pergunta-se também o MÉTODO: `ROTAS_DE_CRON`
    (test_protecao_rotas.py:56) é uma lista de CAMINHOS, por isso qualquer
    método naquele caminho fica dispensado da guarda de autenticação. Um
    `@router.get` no lugar do `@router.post` não partia teste nenhum e abria
    ao mundo, num GET, uma rota que escreve em `fat_documentos`.
    """
    from faturacao import router
    caminhos = {(r.path, metodo) for r in router.routes
                for metodo in getattr(r, "methods", ())}
    assert ("/api/faturacao/cron/sincronizar-app", "POST") in caminhos
    assert ("/api/faturacao/sincronizacao-app/definicoes", "GET") in caminhos
    assert ("/api/faturacao/sincronizacao-app/definicoes", "PUT") in caminhos
    assert ("/api/faturacao/sincronizacao-app/sincronizar-agora",
            "POST") in caminhos


# --- A anulação depois de importada ------------------------------------------

# O MESMO documento, agora com `status: "A"` — o dicionário, que é a forma em
# que ele vem no DETALHE (`estado_do_vendus` cobre as duas).
_FS_446_ANULADA = dict(_FS_446, status={"id": "A", "date": "2026-09-05 10:00:00"})


def test_uma_fatura_ja_gravada_que_e_anulada_deixa_de_contar(monkeypatch):
    """A especificação prometia-o e o código saltava antes de qualquer escrita.

    `deve_importar` devolve `(False, "anulada no Vendus")` e o atalho dos
    repetidos sai antes do `insert_one`: o documento que já estava em
    `fat_documentos` ficava intacto. O dono anulava no painel do Vendus uma FS
    da app já importada e ela continuava a somar receita no Dashboard, nos
    Relatórios e no email da noite — para sempre.
    """
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446_ANULADA],
            ja_gravados=[370665072])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"]))
    assert _ESTADO["coleccao"].anulados == {370665072}, "ficou marcada na base"
    assert len(resultado["anulados"]) == 1, "e contada uma vez"
    assert "FS 06P2026/446" in resultado["anulados"][0], "identifica qual"
    assert resultado["gravados"] == 0 and gravados == []


def test_a_mesma_anulacao_nao_se_conta_duas_vezes(monkeypatch):
    """O cron corre 288 vezes por dia e cada volta relê hoje e ontem.

    Uma marcação que se contasse outra vez em cada volta transformava uma
    anulação numa avalanche: o ecrã a anunciar «1 fatura anulada» de cinco em
    cinco minutos, para sempre, pela mesma fatura.
    """
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446_ANULADA],
            ja_gravados=[370665072])
    primeira = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"]))
    segunda = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"]))
    assert len(primeira["anulados"]) == 1
    assert segunda["anulados"] == [], "a segunda volta não a conta outra vez"
    assert _ESTADO["coleccao"].anulados == {370665072}


def test_uma_anulada_que_nunca_entrou_continua_de_fora(monkeypatch):
    """Marcar não é importar: uma FS anulada que nunca cá esteve não se grava
    nem se anuncia. Sem esta distinção, a lista de anuladas enchia-se de
    documentos que nunca contaram nada."""
    gravados = []
    cliente = _montar(monkeypatch, gravados, documentos=[_FS_446_ANULADA])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"]))
    assert gravados == [], "não grava nada"
    assert resultado["anulados"] == [], "nem anuncia uma marcação que não houve"
    assert _ESTADO["coleccao"].anulados == set()
    assert resultado["ignorados"] == 1
    assert ("ler", 370665072) not in cliente.pedidos, "nem gasta um GET"


def test_o_ensaio_nao_marca_a_anulacao(monkeypatch):
    """`simular` é o que se corre contra a PRODUÇÃO — a base com ~750 FS
    fiscais reais — para ver o que ia acontecer. Escrever ali durante um
    ensaio era exactamente o estrago que o ensaio existe para evitar."""
    gravados = []
    _montar(monkeypatch, gravados, documentos=[_FS_446_ANULADA],
            ja_gravados=[370665072])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"],
                                        simular=True))
    assert len(resultado["anulados"]) == 1, "diz o que ia marcar"
    assert _ESTADO["coleccao"].anulados == set(), "mas não marcou nada"


def test_uma_fatura_NOSSA_anulada_no_vendus_nao_se_toca(monkeypatch):
    """Esta caixa é a MESMA das cinco lojas: a esmagadora maioria do que lá
    está é nosso. Uma anulação de um documento do POS trata-se pela nota de
    crédito, não por aqui — `deve_importar` recusa-o pela `ext_ref` antes de
    sequer olhar para o estado, e é isso que impede esta rotina de mexer nas
    ~750 FS reais que não lhe dizem respeito."""
    nossa_anulada = dict(_NOSSA, id=371000002, number="FS 06P2026/100",
                         status={"id": "A", "date": "2026-09-05 10:00:00"})
    gravados = []
    _montar(monkeypatch, gravados, documentos=[nossa_anulada],
            ja_gravados=[371000002], nao_da_app=[371000002])
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-05"]))
    assert resultado["anulados"] == []
    assert _ESTADO["coleccao"].anulados == set()


# --- A porta para os dias que já passaram ------------------------------------


def _dias_lidos(cliente):
    return [pedido[1] for pedido in cliente.pedidos if pedido[0] == "listar"]


def _botao(monkeypatch, **kw):
    """O botão do backoffice, com a base e o Vendus em duplo."""
    cliente = _montar(monkeypatch, [], documentos=[])
    monkeypatch.setattr(rota, "obter_db", lambda: _DBFalsa())
    return cliente, _corre(rota.sincronizar_agora(**kw))


def test_sem_parametros_o_botao_continua_a_ler_ontem_e_hoje(monkeypatch):
    """As datas contam-se AQUI, não se pedem a `_dias_da_volta`.

    Escrito como `== rota._dias_da_volta()`, o teste mutava com o código:
    provado por mutação — reduzir a volta a só hoje deixava-o VERDE, porque os
    dois lados da igualdade saíam da mesma função. Ontem tem de lá estar
    sempre: é o que apanha a fatura das 23h50 que o Vendus só mostrou depois
    da meia-noite.
    """
    hoje = datetime.now(rota.LISBON_TZ).date()
    cliente, _resultado = _botao(monkeypatch)
    assert _dias_lidos(cliente) == [(hoje - timedelta(days=1)).isoformat(),
                                    hoje.isoformat()]


def test_um_intervalo_a_escolha_le_os_dias_certos(monkeypatch):
    """A única fatura da app que existe é de 2026-09-01. Ligado o cron a 05/09,
    ele NUNCA a ia buscar: `sincronizar(dias=_dias_da_volta())` devolve só
    ontem e hoje, e nenhuma das duas rotas aceitava datas. Qualquer paragem
    maior do que 24 horas perdia essas faturas para sempre."""
    cliente, _resultado = _botao(monkeypatch, de="2026-09-01", ate="2026-09-03")
    assert _dias_lidos(cliente) == ["2026-09-01", "2026-09-02", "2026-09-03"], \
        "os dois extremos INCLUÍDOS, e os dias do meio também"


def test_um_intervalo_demasiado_longo_e_recusado(monkeypatch):
    """Cada dia é um pedido ao Vendus (mais um por documento novo) e o ecrã
    desiste aos 120 s: sem tecto, o botão dizia "não respondeu" com a volta
    ainda a correr do lado de lá — e quem lê isso carrega outra vez."""
    with pytest.raises(HTTPException) as e:
        rota._dias_do_intervalo("2026-09-01", "2027-09-01")
    assert e.value.status_code == 422
    assert "máximo" in str(e.value.detail)


def test_uma_data_antes_do_PRIMEIRO_DIA_e_recusada():
    """`PRIMEIRO_DIA` é a decisão do dono sobre desde quando a receita da app
    entra no portal — a app emite desde 18/08. Até esta tarefa a constante não
    era lida por ninguém: uma única ocorrência em todo o repositório, a própria
    definição."""
    with pytest.raises(HTTPException) as e:
        rota._dias_do_intervalo("2026-08-31", "2026-09-01")
    assert e.value.status_code == 422
    assert rota.PRIMEIRO_DIA in str(e.value.detail)


def test_uma_data_no_futuro_e_recusada():
    amanha = (datetime.now(rota.LISBON_TZ).date() + timedelta(days=1)).isoformat()
    with pytest.raises(HTTPException) as e:
        rota._dias_do_intervalo(amanha, amanha)
    assert e.value.status_code == 422


def test_uma_data_sozinha_nao_serve():
    """Metade de um intervalo é uma pergunta por acabar. Deixá-la passar
    obrigava a inventar a outra metade — e a metade inventada é a que leria
    dias que ninguém pediu."""
    for de, ate in (("2026-09-01", None), (None, "2026-09-03")):
        with pytest.raises(HTTPException) as e:
            rota._dias_do_intervalo(de, ate)
        assert e.value.status_code == 422


def test_datas_ilegiveis_nao_rebentam():
    for de, ate in (("01/09/2026", "2026-09-03"), ("2026-09-01", "ontem")):
        with pytest.raises(HTTPException) as e:
            rota._dias_do_intervalo(de, ate)
        assert e.value.status_code == 422
