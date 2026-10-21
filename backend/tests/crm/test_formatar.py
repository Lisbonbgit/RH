"""As lojas entre a base e a API: `crm/formatar.py` (plano T2.10; dossiê §3 e §6).

Porta de tests/Unit/Http/FormatarTest.php do CRM autónomo (etiqueta
`referencia-standalone`), com os nomes de lá, para o modelo do portal:

- lá a linha vinha do PDO (decimais e datas em texto, horas "HH:MM:SS", dias
  num SET); aqui o documento do Mongo já guarda os instantes no formato da API
  (`relogio.instante`/`carimbo`, T2.8), lat/lng em números, as janelas numa
  lista `[{inicio, fim}]` e os dias numa lista. O `loja_api` converte as
  janelas (`campos_de_janelas`, T2.6), põe os dias pela ordem da semana (o
  que o SET do MariaDB fazia) e as coordenadas em `float` (o `(float)` do PHP);
- os casos `umInstanteDaBd…`, `oInstanteComMicrossegundos…` e
  `versoesInvalidas` já estão em test_relogio.py (T2.8); `horas` e `dias`
  passam a ser as janelas da lista e os dias da lista;
- novos: `documento_loja` (o `LojasRepositorio::criar`, com o documento do
  Mongo: `id` uuid4, `loc` GeoJSON, janelas em lista, os quatro
  temporizadores a null) e `documento_localizacao` (lat, lng e `loc` sempre
  juntos, plano §3).

As formas esperadas escrevem-se aqui à mão, chave a chave e pela ordem: não se
calculam com o código que se está a testar.
"""
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from bson.int64 import Int64

from crm import formatar
from crm.dominio import validador_loja

from .formatos import instantes_fora_do_formato

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-10T09:30:15Z"
AGORA_CARIMBO = "2026-10-10T09:30:15.987654Z"

LOJA = "00000000-0000-4000-8000-000000000007"
LISBOA = "00000000-0000-4000-8000-000000000002"
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

# A loja completa da API, pela ordem do plano §4 ("Loja completa (API)"), com o
# `instagram` e o `site` de 2026-10-13 a seguir à pessoa de contacto.
CAMPOS_API = (
    "id", "nome", "fase", "fase_desde", "regiao_id", "morada", "codigo_postal", "localidade",
    "lat", "lng", "origem_coords", "precisao_m", "google_place_id",
    "telefone", "pessoa_contacto", "instagram", "site", "notas",
    "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim", "dias_fechada",
    "visita_pendente_motivo", "visita_pendente_desde", "ultima_interacao_em", "ultima_visita_ou_entrega_em",
    "criado_por", "criado_em", "atualizado_em",
)

# O documento de crm_lojas, pela ordem do plano §3.
CAMPOS_BASE = (
    "id", "nome", "fase", "fase_desde", "regiao_id", "morada", "codigo_postal", "localidade",
    "lat", "lng", "loc", "origem_coords", "precisao_m", "google_place_id",
    "telefone", "pessoa_contacto", "instagram", "site", "notas",
    "janelas", "dias_fechada",
    "visita_pendente_motivo", "visita_pendente_desde", "ultima_interacao_em", "ultima_visita_ou_entrega_em",
    "criado_por", "criado_em", "atualizado_em",
)


def _doc_completo():
    """Uma loja como o Mongo a devolve (com o `_id` do insert), com todos os campos."""
    return {
        "_id": ObjectId(),
        "id": LOJA,
        "nome": "Café Central",
        "fase": "cliente",
        "fase_desde": "2026-10-01T08:00:00Z",
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "loc": {"type": "Point", "coordinates": [-9.1369, 38.7108]},
        "origem_coords": "gps",
        "precisao_m": 12,
        "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janelas": [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}],
        "dias_fechada": ["sab", "dom"],
        "visita_pendente_motivo": "amostra",
        "visita_pendente_desde": "2026-10-02T10:00:00Z",
        "ultima_interacao_em": "2026-10-02T11:00:00Z",
        "ultima_visita_ou_entrega_em": "2026-10-02T12:00:00Z",
        "criado_por": "u-rui",
        "criado_em": "2026-09-30T07:00:00Z",
        "atualizado_em": "2026-10-03T09:00:00.654321Z",
    }


def _doc_minimo():
    """Só os obrigatórios; o resto a null, sem janelas nem dias. As coordenadas
    escritas à mão como inteiros (39 e −8)."""
    return {
        **dict.fromkeys(CAMPOS_BASE),
        "id": "00000000-0000-4000-8000-000000000001",
        "nome": "Bar",
        "fase": "potencial",
        "fase_desde": "2026-10-03T09:00:00Z",
        "lat": 39,
        "lng": -8,
        "loc": {"type": "Point", "coordinates": [-8, 39]},
        "origem_coords": "pin_manual",
        "janelas": [],
        "dias_fechada": [],
        "criado_em": "2026-10-03T09:00:00Z",
        "atualizado_em": "2026-10-03T09:00:00.000000Z",
    }


def _tipos(dicionario):
    return {campo: type(valor) for campo, valor in dicionario.items()}


# --- loja_api: a loja completa ---------------------------------------------------------------


def test_os_campos_da_api_sao_os_do_plano():
    assert formatar.CAMPOS_API == CAMPOS_API


def test_a_loja_completa_vem_com_os_tipos_da_api():
    """`aLojaCompletaVemComOsTiposDaApi`."""
    esperado = {
        "id": LOJA,
        "nome": "Café Central",
        "fase": "cliente",
        "fase_desde": "2026-10-01T08:00:00Z",
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "origem_coords": "gps",
        "precisao_m": 12,
        "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["sab", "dom"],
        "visita_pendente_motivo": "amostra",
        "visita_pendente_desde": "2026-10-02T10:00:00Z",
        "ultima_interacao_em": "2026-10-02T11:00:00Z",
        "ultima_visita_ou_entrega_em": "2026-10-02T12:00:00Z",
        "criado_por": "u-rui",
        "criado_em": "2026-09-30T07:00:00Z",
        "atualizado_em": "2026-10-03T09:00:00.654321Z",
    }
    loja = formatar.loja_api(_doc_completo())
    # O assertSame do PHP: valores, ordem das chaves e tipos.
    assert list(loja.items()) == list(esperado.items())
    assert _tipos(loja) == _tipos(esperado)


def test_os_campos_opcionais_sem_valor_vem_a_null():
    """`osCamposOpcionaisSemValorVemANull`."""
    loja = formatar.loja_api(_doc_minimo())
    opcionais = {campo: valor for campo, valor in loja.items() if campo not in (
        "id", "nome", "fase", "fase_desde", "lat", "lng", "origem_coords", "criado_em", "atualizado_em",
    )}
    assert list(opcionais.items()) == list({
        "regiao_id": None, "morada": None, "codigo_postal": None, "localidade": None,
        "precisao_m": None, "google_place_id": None,
        "telefone": None, "pessoa_contacto": None, "instagram": None, "site": None, "notas": None,
        "janela1_inicio": None, "janela1_fim": None, "janela2_inicio": None, "janela2_fim": None,
        "dias_fechada": [],
        "visita_pendente_motivo": None, "visita_pendente_desde": None,
        "ultima_interacao_em": None, "ultima_visita_ou_entrega_em": None,
        "criado_por": None,
    }.items())
    assert loja["id"] == "00000000-0000-4000-8000-000000000001"
    # O (float) do PHP: 39 escrito à mão sai 39.0 (e "lat":39.0 no JSON).
    assert (loja["lat"], type(loja["lat"])) == (39.0, float)
    assert (loja["lng"], type(loja["lng"])) == (-8.0, float)


def test_a_api_nunca_mostra_o_id_do_mongo_o_loc_nem_a_lista_das_janelas():
    loja = formatar.loja_api(_doc_completo())
    assert tuple(loja) == CAMPOS_API
    assert "_id" not in loja and "loc" not in loja and "janelas" not in loja


@pytest.mark.parametrize(
    "janelas, planas",
    [
        ([], (None, None, None, None)),
        ([{"inicio": "09:30", "fim": "12:00"}], ("09:30", "12:00", None, None)),
        (
            [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}],
            ("10:00", "13:00", "15:00", "19:00"),
        ),
        ([{"inicio": "00:00", "fim": "23:59"}], ("00:00", "23:59", None, None)),
    ],
    ids=["sem janelas", "manhã", "duas janelas", "meia-noite e fim do dia"],
)
def test_as_janelas_da_lista_ficam_planas_em_hh_mm(janelas, planas):
    """O `umaHoraFicaEmHhMm` (`horas`): na base já são "HH:MM", numa lista."""
    loja = formatar.loja_api({**_doc_minimo(), "janelas": janelas})
    assert (loja["janela1_inicio"], loja["janela1_fim"], loja["janela2_inicio"], loja["janela2_fim"]) == planas


@pytest.mark.parametrize(
    "guardados, api",
    [
        ([], []),
        (["dom"], ["dom"]),
        (["seg", "qua", "sab"], ["seg", "qua", "sab"]),
        (["dom", "seg"], ["seg", "dom"]),
        (["dom", "sab", "dom"], ["sab", "dom"]),
    ],
    ids=["nenhum", "um", "vários", "fora de ordem (pela ordem da semana)", "repetido (uma vez)"],
)
def test_os_dias_fechada_ficam_uma_lista_pela_ordem_da_semana(guardados, api):
    """`osDiasFechadaFicamUmaLista` (`dias`). O SET do MariaDB devolvia-os pela
    ordem da semana e sem repetidos (`lerUmaLojaGravadaPorSql…`: 'dom,seg' →
    ['seg', 'dom']); aqui faz-se o mesmo a uma lista escrita à mão na base."""
    loja = formatar.loja_api({**_doc_minimo(), "dias_fechada": guardados})
    assert loja["dias_fechada"] == api


def test_os_numeros_que_o_mongo_devolve_noutros_tipos_leem_se():
    """O Mongo devolve um int64 como `Int64`, e o mongosh escreve os números
    como double: 7.0 na precisão é 7, como o `(int)` do PHP."""
    loja = formatar.loja_api({**_doc_minimo(), "lat": Int64(39), "precisao_m": Int64(7)})
    assert (loja["lat"], type(loja["lat"])) == (39.0, float)
    assert (loja["precisao_m"], type(loja["precisao_m"])) == (7, int)
    loja = formatar.loja_api({**_doc_minimo(), "precisao_m": 7.0})
    assert (loja["precisao_m"], type(loja["precisao_m"])) == (7, int)


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("janelas", [{"inicio": "10:00"}]),
        ("janelas", [{"inicio": "13:00", "fim": "10:00"}]),
        ("janelas", None),
        ("dias_fechada", "seg,dom"),
        ("dias_fechada", ["sabado"]),
        ("dias_fechada", None),
        ("lat", True),
        ("lat", "38.7108"),
        ("lat", None),
        ("lng", float("nan")),
        ("precisao_m", True),
        ("precisao_m", "7"),
        ("precisao_m", 7.5),
    ],
    ids=[
        "janela a meio", "janela ao contrário", "janelas null",
        "dias em texto", "dia desconhecido", "dias null",
        "lat bool", "lat em texto", "lat null", "lng NaN",
        "precisão bool", "precisão em texto", "precisão com casas",
    ],
)
def test_um_documento_estragado_e_um_erro_de_programacao(campo, valor):
    """O CRM só grava o que o `documento_loja` monta. Um documento estragado à
    mão é `ValueError` (um 500), e nunca uma resposta com outra forma (o
    frontend contava com ela)."""
    with pytest.raises(ValueError):
        formatar.loja_api({**_doc_minimo(), campo: valor})


def test_um_documento_sem_um_campo_e_um_erro_de_programacao():
    doc = _doc_completo()
    del doc["morada"]
    with pytest.raises(KeyError):
        formatar.loja_api(doc)


def test_uma_loja_gravada_antes_do_instagram_e_do_site_le_se_com_eles_a_null():
    """Os dois campos entraram em 2026-10-13 sem migração: um documento de
    antes não os tem, e a API devolve-os a null (lidos com `.get`) em vez de
    rebentar com `KeyError`. Com eles no documento, vêm tal e qual."""
    doc = _doc_completo()
    del doc["instagram"]
    del doc["site"]
    loja = formatar.loja_api(doc)
    assert tuple(loja) == CAMPOS_API
    assert (loja["instagram"], loja["site"]) == (None, None)
    assert "instagram" not in doc and "site" not in doc, "O documento recebido não se toca."


def test_uma_loja_gravada_antes_do_identificador_do_lugar_le_se_com_ele_a_null():
    """O `google_place_id` entrou com o mapa Google (2026-10-18, plano §3) sem
    migração: um documento de antes não tem a chave e a API devolve-a a null
    (lida com `.get`), em vez de rebentar com `KeyError`; com ela no documento
    vem tal e qual, a seguir à precisão."""
    doc = _doc_completo()
    del doc["google_place_id"]
    loja = formatar.loja_api(doc)
    assert tuple(loja) == CAMPOS_API
    assert loja["google_place_id"] is None
    assert "google_place_id" not in doc, "O documento recebido não se toca."

    loja = formatar.loja_api(_doc_completo())
    assert loja["google_place_id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert list(loja).index("google_place_id") == list(loja).index("precisao_m") + 1


def test_a_loja_da_api_e_uma_estrutura_nova():
    doc = _doc_completo()
    copia = deepcopy(doc)
    loja = formatar.loja_api(doc)
    loja["dias_fechada"].append("seg")
    assert doc == copia


# --- resumo_loja_api: o pino do mapa ---------------------------------------------------------


def test_o_resumo_do_mapa_tem_so_os_campos_do_pino():
    """`oResumoDoMapaTemSoOsCamposDoPino`, mais a `pessoa_contacto` (revisão
    das alterações do dono, 2026-10-13): a linha "Contacto: pessoa · telefone"
    do cartão do mapa lê-a do resumo, que é a loja que o pino tem."""
    resumo = formatar.resumo_loja_api({
        "id": LOJA,
        "nome": "Café Central",
        "fase": "cliente",
        "regiao_id": LISBOA,
        "lat": 38.7108,
        "lng": -9.1369,
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "D. Amélia",
    })
    esperado = {
        "id": LOJA,
        "nome": "Café Central",
        "fase": "cliente",
        "regiao_id": LISBOA,
        "lat": 38.7108,
        "lng": -9.1369,
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "D. Amélia",
    }
    assert list(resumo.items()) == list(esperado.items())

    minimo = _doc_minimo()
    resumo = formatar.resumo_loja_api({campo: minimo[campo] for campo in formatar.CAMPOS_RESUMO})
    assert list(resumo.items()) == list({
        "id": "00000000-0000-4000-8000-000000000001", "nome": "Bar", "fase": "potencial", "regiao_id": None,
        "lat": 39.0, "lng": -8.0, "telefone": None, "pessoa_contacto": None,
    }.items())
    assert type(resumo["lat"]) is float and type(resumo["lng"]) is float


def test_o_resumo_ignora_os_outros_campos_do_documento():
    resumo = formatar.resumo_loja_api(_doc_completo())
    assert tuple(resumo) == ("id", "nome", "fase", "regiao_id", "lat", "lng", "telefone", "pessoa_contacto")
    assert tuple(resumo) == formatar.CAMPOS_RESUMO


def test_o_resumo_traz_o_que_a_linha_de_contacto_do_cartao_mostra():
    """O `contactoDaLoja` de `frontend/src/lib/crm/ecraMapa.js` lê a pessoa e o
    telefone da loja do pino, que vem do GET /lojas: têm de estar no resumo
    (o `ecraMapa.test.js` lê a linha `CAMPOS_RESUMO = (…)` deste módulo)."""
    assert {"pessoa_contacto", "telefone"} <= set(formatar.CAMPOS_RESUMO)
    assert "instagram" not in formatar.CAMPOS_RESUMO and "site" not in formatar.CAMPOS_RESUMO


def test_o_resumo_do_mapa_nao_traz_o_identificador_do_lugar():
    """Plano do mapa Google §4: a lista `GET /lojas` não traz o `google_place_id`
    (`CAMPOS_RESUMO` não muda); só a loja completa o tem."""
    assert formatar.CAMPOS_RESUMO == ("id", "nome", "fase", "regiao_id", "lat", "lng", "telefone", "pessoa_contacto")
    assert "google_place_id" in formatar.CAMPOS_API
    assert "google_place_id" not in formatar.resumo_loja_api(_doc_completo())


# --- documento_localizacao: lat, lng e loc sempre juntos --------------------------------------


def test_a_localizacao_leva_lat_lng_e_o_ponto_geojson_em_lng_lat():
    localizacao = formatar.documento_localizacao(38.7108, -9.1369)
    assert list(localizacao.items()) == [
        ("lat", 38.7108),
        ("lng", -9.1369),
        ("loc", {"type": "Point", "coordinates": [-9.1369, 38.7108]}),
    ]
    assert list(localizacao["loc"]) == ["type", "coordinates"]


def test_a_localizacao_guarda_as_coordenadas_em_float():
    localizacao = formatar.documento_localizacao(39, -8)
    assert _tipos(localizacao) == {"lat": float, "lng": float, "loc": dict}
    assert [type(c) for c in localizacao["loc"]["coordinates"]] == [float, float]


def test_cada_localizacao_e_uma_estrutura_nova():
    a = formatar.documento_localizacao(38.7108, -9.1369)
    b = formatar.documento_localizacao(38.7108, -9.1369)
    assert a == b and a["loc"] is not b["loc"] and a["loc"]["coordinates"] is not b["loc"]["coordinates"]


@pytest.mark.parametrize(
    "lat, lng",
    [
        (True, -9.1369),
        (38.7108, False),
        (None, -9.1369),
        ("38.7108", -9.1369),
        (float("nan"), -9.1369),
        (38.7108, float("inf")),
        (90.000001, -9.1369),
        (-90.5, -9.1369),
        (38.7108, 180.5),
        (38.7108, -180.000001),
    ],
    ids=[
        "lat bool", "lng bool", "lat null", "lat texto", "lat NaN", "lng inf",
        "lat > 90", "lat < -90", "lng > 180", "lng < -180",
    ],
)
def test_uma_localizacao_que_nao_e_um_ponto_valido_e_um_erro_de_programacao(lat, lng):
    """O Mongo recusa gravar um `loc` fora do mundo (WriteError, conferido na
    T2.8). Chega aqui só o que o validador já aceitou (Portugal); o resto é
    `ValueError` antes de se tentar gravar."""
    with pytest.raises(ValueError):
        formatar.documento_localizacao(lat, lng)


def test_os_limites_do_mundo_sao_pontos_validos():
    assert formatar.documento_localizacao(90, 180)["loc"]["coordinates"] == [180.0, 90.0]
    assert formatar.documento_localizacao(-90, -180)["loc"]["coordinates"] == [-180.0, -90.0]


# --- documento_loja: a loja nova, como fica gravada -------------------------------------------


def _dados():
    """Os 21 campos como o `validador_loja.criacao` os devolve sem erros
    (escritos à mão)."""
    return {
        "nome": "Café Central",
        "fase": "amostra",
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "origem_coords": "gps",
        "precisao_m": 12,
        "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["sab", "dom"],
    }


def test_a_loja_nova_tem_a_forma_da_base():
    """O `LojasRepositorio::criar`: a fase começa agora (`fase_desde ==
    criado_em`), `atualizado_em` com microssegundos é a versão, e os quatro
    temporizadores começam a null."""
    doc = formatar.documento_loja(_dados(), "u-rui", AGORA)
    assert UUID4.fullmatch(doc["id"])
    assert list(doc.items()) == list({
        "id": doc["id"],
        "nome": "Café Central",
        "fase": "amostra",
        "fase_desde": AGORA_INSTANTE,
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "loc": {"type": "Point", "coordinates": [-9.1369, 38.7108]},
        "origem_coords": "gps",
        "precisao_m": 12,
        "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janelas": [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}],
        "dias_fechada": ["sab", "dom"],
        "visita_pendente_motivo": None,
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "criado_por": "u-rui",
        "criado_em": AGORA_INSTANTE,
        "atualizado_em": AGORA_CARIMBO,
    }.items())
    assert tuple(doc) == CAMPOS_BASE


def test_a_loja_nova_passa_no_verificador_dos_instantes():
    """Correções do plano, linha "§1 Decisões (Tempo) / T2.8"."""
    assert instantes_fora_do_formato(formatar.documento_loja(_dados(), "u-rui", AGORA)) == []


def test_a_loja_nova_conta_o_agora_em_utc():
    lisboa = timezone(timedelta(hours=1))
    doc = formatar.documento_loja(_dados(), "u-rui", datetime(2026, 10, 10, 10, 30, 15, 987654, tzinfo=lisboa))
    assert (doc["fase_desde"], doc["criado_em"], doc["atualizado_em"]) == (
        AGORA_INSTANTE, AGORA_INSTANTE, AGORA_CARIMBO,
    )


def test_um_agora_sem_fuso_e_recusado():
    with pytest.raises(ValueError):
        formatar.documento_loja(_dados(), "u-rui", datetime(2026, 10, 10, 9, 30, 15))


def test_cada_loja_nova_tem_um_id_uuid4_novo():
    ids = {formatar.documento_loja(_dados(), "u-rui", AGORA)["id"] for _ in range(50)}
    assert len(ids) == 50
    assert all(UUID4.fullmatch(i) for i in ids)


def test_a_loja_nova_nao_mexe_nos_dados_e_nao_partilha_listas_com_eles():
    dados = _dados()
    copia = deepcopy(dados)
    doc = formatar.documento_loja(dados, "u-rui", AGORA)
    assert dados == copia
    dados["dias_fechada"].append("seg")
    assert doc["dias_fechada"] == ["sab", "dom"]


def test_sem_janelas_nem_dias_a_loja_nova_guarda_listas_vazias():
    dados = {**_dados(), "janela1_inicio": None, "janela1_fim": None, "janela2_inicio": None,
             "janela2_fim": None, "dias_fechada": []}
    doc = formatar.documento_loja(dados, None, AGORA)
    assert (doc["janelas"], doc["dias_fechada"], doc["criado_por"]) == ([], [], None)


def test_a_loja_nova_sem_identificador_do_lugar_grava_null_a_seguir_a_precisao():
    doc = formatar.documento_loja({**_dados(), "google_place_id": None}, "u-rui", AGORA)
    assert "google_place_id" in doc and doc["google_place_id"] is None
    assert list(doc).index("google_place_id") == list(doc).index("precisao_m") + 1
    assert tuple(doc) == CAMPOS_BASE


def test_janelas_por_validar_nunca_se_gravam():
    """O `janelas_para_lista` (T2.6) recusa uma janela a meio: nunca se grava."""
    with pytest.raises(ValueError):
        formatar.documento_loja({**_dados(), "janela1_fim": None}, "u-rui", AGORA)


def test_ida_e_volta_a_api_devolve_os_campos_validados():
    """O que o validador aceitou é o que a API devolve, com os campos do servidor."""
    dados = _dados()
    loja = formatar.loja_api(formatar.documento_loja(dados, "u-rui", AGORA))
    assert {campo: loja[campo] for campo in validador_loja.CAMPOS} == dados
    assert (loja["fase_desde"], loja["criado_em"], loja["atualizado_em"], loja["criado_por"]) == (
        AGORA_INSTANTE, AGORA_INSTANTE, AGORA_CARIMBO, "u-rui",
    )


def test_a_loja_nova_a_partir_do_validador():
    """O corpo do `criarDevolve201ComALojaCompleta`, pelo validador da T2.5."""
    dados, erros = validador_loja.criacao({
        "nome": "  Café Central ", "fase": "amostra", "lat": 38.7108004, "lng": -9.1369,
        "origem_coords": "gps", "precisao_m": 12.4, "google_place_id": " ChIJN1t_tDeuEmsRUsoyG83frY4 ",
        "telefone": "+351  912 345 678",
        "janela1_inicio": "09:30", "janela1_fim": "12:00", "dias_fechada": ["dom", "seg"],
    })
    assert erros == {}
    doc = formatar.documento_loja(dados, "u-rui", AGORA)
    assert (doc["nome"], doc["lat"], doc["lng"], doc["precisao_m"], doc["google_place_id"], doc["telefone"]) == (
        "Café Central", 38.7108, -9.1369, 12, "ChIJN1t_tDeuEmsRUsoyG83frY4", "+351 912 345 678",
    )
    assert doc["loc"] == {"type": "Point", "coordinates": [-9.1369, 38.7108]}
    assert doc["janelas"] == [{"inicio": "09:30", "fim": "12:00"}]
    assert doc["dias_fechada"] == ["seg", "dom"]
