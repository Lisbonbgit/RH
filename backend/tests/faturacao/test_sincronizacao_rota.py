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
                 colide_com_outro=False):
        self.gravados = gravados
        self.insert_rebenta = insert_rebenta
        self.ja_gravados = set(ja_gravados)
        # O `insert_one` rebenta porque OUTRO documento já ocupa o `atcud` ou
        # a `ext_ref`, não porque este já lá esteja. É a diferença entre "duas
        # voltas em cima uma da outra" e "um documento novo deitado fora".
        self.colide_com_outro = colide_com_outro

    async def find_one(self, filtro, projeccao=None):
        existe = filtro.get("vendus_document_id") in self.ja_gravados
        return {"_id": "x"} if existe else None

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
        # Um documento sem `id` não tem detalhe nenhum para ir buscar — não
        # há GET por id que se lhe faça. É por isso que ele fica de fora aqui.
        self.detalhes = {int(d["id"]): d for d in documentos if d.get("id")}
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
            colide_com_outro=False):
    monkeypatch.setitem(
        _ESTADO, "coleccao",
        _ColeccaoFalsa(gravados, insert_rebenta, ja_gravados, colide_com_outro))
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
    async def _desligada(_db):
        return {"loja_id": LOJA, "ativo": False}
    monkeypatch.setattr(rota, "_definicoes", _desligada)
    resultado = _corre(rota.sincronizar(_DBFalsa(), dias=["2026-09-01"]))
    assert resultado["gravados"] == 0
    assert resultado["erros"]


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
