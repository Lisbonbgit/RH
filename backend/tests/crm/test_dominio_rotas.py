"""As regras da rota de um dia (crm/dominio/rotas.py e crm/dominio/ids.py), F3 / T3.3.

O CRM autónomo não tem código de rotas: as regras vêm do desenho original
(§4.3 motivos, §7.2 prioridades, §7 planeamento) e do plano F3 (§1 e §3):

- o motivo de uma paragem vem pré-escolhido pela fase (potencial/perdida →
  angariação, contactada → amostra, amostra/cliente → acompanhamento);
- prioridades do VROOM: entrega 100, as outras 1 (48 × 1 < 100: nenhuma soma
  de visitas vale uma entrega);
- um dia anterior a hoje lê-se como `concluida` e não se escreve
  (`rota_fechada`); uma rota com algum registo do motorista (mesmo numa
  paragem retirada) só se vê no escritório (`rota_em_curso`);
- as paragens ativas ordenam-se pela `ordem`; a F4 pode repor uma paragem
  retirada só com `removida_em: null`, deixando `ordem: null` (correções
  "T3.3 / T3.16" e "T3.3 (ativas com ordem nula)"): essa vai para o fim;
- o escritório só escreve pelos caminhos `paragens.<índice>.<campo do
  escritório>`: os campos do terreno, o `id` e o `loja_id` ficam de fora
  ("o terreno ganha", desenho §4.3).
"""
import ast
import copy
import random
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

import crm.dominio.rotas as rotas
from crm.dominio import ids, validador_loja
from crm.dominio.fases import ORDEM
from crm.dominio.ids import e_uuid4
from crm.dominio.rotas import (
    AVISOS,
    CAMPOS_DO_ESCRITORIO,
    CAMPOS_DO_TERRENO,
    CAMPOS_IMUTAVEIS,
    ESTADOS,
    ESTADOS_COM_REGISTO,
    ESTADOS_EDITAVEIS,
    LIMITE_PARAGENS,
    MOTIVO_POR_FASE,
    MOTIVOS,
    PRIORIDADE_ENTREGA,
    PRIORIDADE_OUTRAS,
    SECCOES,
    ativas,
    aviso,
    bloqueio_de_escrita,
    caminhos_paragem,
    estado_efetivo,
    fechada_neste_dia,
    motivo_por_fase,
    nova_ordem,
    prioridade,
    seccoes,
    servico_padrao,
)

HOJE = date(2026, 10, 12)  # uma segunda-feira
ONTEM = date(2026, 10, 11)
AMANHA = date(2026, 10, 13)

# As chaves de uma paragem no modelo de dados (plano F3 §3).
CHAVES_DA_PARAGEM = {
    "id", "loja_id", "ordem", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe", "chegada_prevista",
    "espera_min", "fora_de_horario", "adicionada_em", "adicionada_por", "removida_em", "estado", "resultado",
    "concluida_em",
}


def _paragem(nome, ordem, **campos):
    """Uma paragem como está na base (§3), com `id`/`loja_id` legíveis nos testes."""
    return {
        "id": f"p-{nome}", "loja_id": f"l-{nome}", "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": "membro-1",
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None,
        **campos,
    }


def _retirada(nome, **campos):
    return _paragem(nome, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _rota(estado="rascunho", paragens=()):
    return {"id": "r-1", "data": "2026-10-12", "estado": estado, "versao": 3, "paragens": list(paragens)}


def _loja(nome, dias_fechada=()):
    return {"id": f"l-{nome}", "nome": nome, "dias_fechada": list(dias_fechada)}


def _ids(lista):
    return [p["id"] for p in lista]


# --- motivos -----------------------------------------------------------------------------------


def test_os_motivos_sao_os_quatro_do_desenho_por_esta_ordem():
    assert MOTIVOS == ("entrega", "amostra", "acompanhamento", "angariacao")
    assert isinstance(MOTIVOS, tuple)


def test_os_motivos_estao_numa_so_linha_do_codigo():
    """A T3.27 compara o `MOTIVOS` do `lib/crm/rota.js` (uma linha) com este:
    aqui também fica numa só linha, para se ler e procurar do mesmo jeito."""
    codigo = Path(rotas.__file__).read_text(encoding="utf-8")
    linhas = re.findall(r'^MOTIVOS = \(("[a-z_]+"(?:, "[a-z_]+")*)\)$', codigo, re.M)
    assert len(linhas) == 1
    assert tuple(re.findall(r'"([a-z_]+)"', linhas[0])) == MOTIVOS


def test_o_motivo_por_fase_e_o_do_desenho():
    assert dict(MOTIVO_POR_FASE) == {
        "perdida": "angariacao",
        "potencial": "angariacao",
        "contactada": "amostra",
        "amostra": "acompanhamento",
        "cliente": "acompanhamento",
    }


def test_o_motivo_por_fase_cobre_as_cinco_fases_pela_ordem_do_funil():
    assert tuple(MOTIVO_POR_FASE) == ORDEM
    assert set(MOTIVO_POR_FASE.values()) <= set(MOTIVOS)


def test_o_motivo_por_fase_nao_se_altera_por_engano():
    assert isinstance(MOTIVO_POR_FASE, MappingProxyType)
    with pytest.raises(TypeError):
        MOTIVO_POR_FASE["contactada"] = "entrega"


@pytest.mark.parametrize(
    "fase, motivo",
    [("perdida", "angariacao"), ("potencial", "angariacao"), ("contactada", "amostra"),
     ("amostra", "acompanhamento"), ("cliente", "acompanhamento")],
    ids=["perdida", "potencial", "contactada", "amostra", "cliente"],
)
def test_motivo_por_fase_pre_escolhe_o_motivo(fase, motivo):
    assert motivo_por_fase(fase) == motivo


@pytest.mark.parametrize(
    "fase",
    ["arquivada", "", None, "Cliente", " contactada", "contactada\n", 2, True, ["contactada"], {"fase": "cliente"}],
    ids=["desconhecida", "vazia", "nula", "maiúscula", "espaço antes", "nova linha", "número", "bool", "lista",
         "objeto"],
)
def test_motivo_por_fase_de_uma_fase_desconhecida_e_angariacao(fase):
    # Sem rebentar, mesmo com uma lista ou um objeto (não servem de chave).
    assert motivo_por_fase(fase) == "angariacao"


# --- prioridades ---------------------------------------------------------------------------------


def test_a_entrega_tem_prioridade_100():
    assert PRIORIDADE_ENTREGA == 100
    assert prioridade("entrega") == 100
    assert type(prioridade("entrega")) is int


@pytest.mark.parametrize("motivo", ["amostra", "acompanhamento", "angariacao"])
def test_as_outras_visitas_tem_prioridade_1(motivo):
    assert PRIORIDADE_OUTRAS == 1
    assert prioridade(motivo) == 1
    assert type(prioridade(motivo)) is int


def test_o_limite_e_de_48_paragens():
    assert LIMITE_PARAGENS == 48
    assert type(LIMITE_PARAGENS) is int


def test_nenhuma_soma_de_visitas_vale_uma_entrega():
    """O VROOM maximiza primeiro a soma das prioridades (desenho original
    §7.2): com 48 × 1 < 100, uma rota cheia de visitas nunca troca uma entrega."""
    assert LIMITE_PARAGENS * PRIORIDADE_OUTRAS < PRIORIDADE_ENTREGA
    for motivo in MOTIVOS:
        if motivo != "entrega":
            assert (LIMITE_PARAGENS - 1) * prioridade(motivo) < prioridade("entrega")


@pytest.mark.parametrize("motivo", ["Entrega", "", None, "visita", "angariação", 1])
def test_prioridade_de_um_motivo_desconhecido_e_erro_de_programacao(motivo):
    with pytest.raises(ValueError):
        prioridade(motivo)


# --- estado_efetivo --------------------------------------------------------------------------------


def test_os_estados_da_rota():
    assert ESTADOS == ("rascunho", "planeada", "em_curso", "concluida")
    assert ESTADOS_EDITAVEIS == ("rascunho", "planeada")
    assert ESTADOS_COM_REGISTO == ("feita", "nao_feita")


@pytest.mark.parametrize("estado", [None, "rascunho", "planeada", "em_curso", "concluida"])
@pytest.mark.parametrize("dia", [ONTEM, date(2026, 1, 1), date(2025, 10, 12)], ids=["ontem", "em janeiro", "há um ano"])
def test_um_dia_anterior_a_hoje_le_se_sempre_concluido(estado, dia):
    assert estado_efetivo(estado, dia, HOJE) == "concluida"


@pytest.mark.parametrize("estado", [None, "rascunho", "planeada", "em_curso", "concluida"])
@pytest.mark.parametrize("dia", [HOJE, AMANHA, date(2027, 10, 12)], ids=["hoje", "amanhã", "daqui a um ano"])
def test_hoje_e_o_futuro_devolvem_o_estado_gravado(estado, dia):
    assert estado_efetivo(estado, dia, HOJE) == estado


@pytest.mark.parametrize(
    "dia, hoje",
    [("2026-10-11", HOJE), (ONTEM, "2026-10-12"), (datetime(2026, 10, 11, tzinfo=timezone.utc), HOJE),
     (ONTEM, datetime(2026, 10, 12, tzinfo=timezone.utc)), (None, HOJE), ("2026-10-11", "2026-10-12"),
     (datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc), datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))],
    ids=["dia em texto", "hoje em texto", "dia com hora", "hoje com hora", "dia nulo", "os dois em texto",
         "os dois com hora"],
)
def test_estado_efetivo_so_compara_dias(dia, hoje):
    # Um texto ou um instante no lugar do dia é um erro de programação, mesmo
    # quando os dois se deixavam comparar: o instante UTC das 23:30 de 11 já é
    # dia 12 em Lisboa (WEST).
    with pytest.raises(TypeError):
        estado_efetivo("rascunho", dia, hoje)


# --- bloqueio_de_escrita -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rota",
    [None, _rota(), _rota("planeada", [_paragem("a", 0)]), _rota("em_curso", [_paragem("a", 0, estado="feita")])],
    ids=["sem rota", "rascunho vazio", "planeada", "em curso com registo"],
)
def test_um_dia_passado_esta_sempre_fechado(rota):
    assert bloqueio_de_escrita(rota, ONTEM, HOJE) == "rota_fechada"
    assert bloqueio_de_escrita(rota, date(2025, 1, 1), HOJE) == "rota_fechada"


@pytest.mark.parametrize("dia", [HOJE, AMANHA], ids=["hoje", "amanhã"])
def test_um_dia_sem_rota_de_hoje_ou_do_futuro_pode_receber_a_primeira_paragem(dia):
    assert bloqueio_de_escrita(None, dia, HOJE) is None


@pytest.mark.parametrize("estado", ["rascunho", "planeada"])
@pytest.mark.parametrize("dia", [HOJE, AMANHA], ids=["hoje", "amanhã"])
def test_uma_rota_editavel_sem_registos_do_terreno_escreve_se(estado, dia):
    rota = _rota(estado, [_paragem("a", 0), _paragem("b", 1), _retirada("c")])
    assert bloqueio_de_escrita(rota, dia, HOJE) is None


@pytest.mark.parametrize("estado", ["em_curso", "concluida", "arquivada", None])
def test_uma_rota_fora_dos_estados_editaveis_esta_em_curso(estado):
    assert bloqueio_de_escrita(_rota(estado, [_paragem("a", 0)]), HOJE, HOJE) == "rota_em_curso"


@pytest.mark.parametrize("registo", ["feita", "nao_feita"])
@pytest.mark.parametrize("estado", ["rascunho", "planeada"])
def test_uma_paragem_ativa_com_registo_do_motorista_bloqueia(registo, estado):
    rota = _rota(estado, [_paragem("a", 0), _paragem("b", 1, estado=registo)])
    assert bloqueio_de_escrita(rota, AMANHA, HOJE) == "rota_em_curso"


@pytest.mark.parametrize("registo", ["feita", "nao_feita"])
def test_uma_paragem_retirada_com_registo_do_motorista_tambem_bloqueia(registo):
    rota = _rota("planeada", [_paragem("a", 0), _retirada("b", estado=registo)])
    assert bloqueio_de_escrita(rota, HOJE, HOJE) == "rota_em_curso"


def test_uma_paragem_reposta_pelo_motorista_com_ordem_nula_bloqueia():
    # A F4 repõe uma retirada só com `removida_em: null` (contrato do §3).
    rota = _rota("planeada", [_paragem("a", 0), _paragem("b", None, estado="feita", resultado="interessado")])
    assert bloqueio_de_escrita(rota, HOJE, HOJE) == "rota_em_curso"


def test_bloqueio_de_escrita_nao_muda_a_rota():
    rota = _rota("planeada", [_paragem("a", 0), _retirada("b", estado="feita")])
    antes = copy.deepcopy(rota)
    bloqueio_de_escrita(rota, HOJE, HOJE)
    assert rota == antes


@pytest.mark.parametrize(
    "dia, hoje",
    [("2026-10-11", HOJE), ("2026-10-11", "2026-10-12"), (ONTEM, datetime(2026, 10, 12, tzinfo=timezone.utc))],
    ids=["dia em texto", "os dois em texto", "hoje com hora"],
)
def test_bloqueio_de_escrita_so_compara_dias(dia, hoje):
    with pytest.raises(TypeError):
        bloqueio_de_escrita(None, dia, hoje)


# --- ativas ------------------------------------------------------------------------------------------


def test_ativas_tira_as_retiradas_e_ordena_pela_ordem():
    lista = [_paragem("a", 2), _retirada("b"), _paragem("c", 0), _paragem("d", 1)]
    assert _ids(ativas(lista)) == ["p-c", "p-d", "p-a"]


def test_ativas_desempata_pela_posicao_na_lista():
    lista = [_paragem("a", 1), _paragem("b", 0), _paragem("c", 1), _paragem("d", 0)]
    assert _ids(ativas(lista)) == ["p-b", "p-d", "p-a", "p-c"]


def test_ativas_aceita_uma_paragem_reposta_pelo_motorista_com_ordem_nula():
    """Correções "T3.3 / T3.16" e "T3.3 (ativas com ordem nula)": o terreno
    repõe só com `removida_em: null` e a `ordem` fica `None`. Sem rebentar
    (comparar `None` com `int` dá TypeError) e para o fim, pela posição."""
    reposta = _paragem("b", None, estado="feita", resultado="interessado", concluida_em="2026-10-12T10:00:00Z")
    lista = [_paragem("a", 1), reposta, _retirada("c"), _paragem("d", 0), _paragem("e", None), _paragem("f", 2)]
    assert _ids(ativas(lista)) == ["p-d", "p-a", "p-f", "p-b", "p-e"]


def test_ativas_poe_a_ordem_zero_antes_das_nulas():
    lista = [_paragem("a", None), _paragem("b", 0)]
    assert _ids(ativas(lista)) == ["p-b", "p-a"]


def test_ativas_de_nenhuma_paragem_e_uma_lista_vazia():
    assert ativas([]) == []
    assert ativas([_retirada("a"), _retirada("b")]) == []


def test_ativas_devolve_uma_lista_nova_sem_mudar_a_recebida():
    lista = [_paragem("a", 1), _paragem("b", 0)]
    antes = copy.deepcopy(lista)
    resultado = ativas(lista)
    assert lista == antes
    assert resultado is not lista
    # As paragens são as mesmas (sem cópia): o chamador lê-as.
    assert resultado[0] is lista[1]


# --- fechada_neste_dia ----------------------------------------------------------------------------------


def test_uma_loja_fechada_a_segunda_esta_fechada_na_segunda_e_nao_na_terca():
    loja = _loja("a", ["seg"])
    assert fechada_neste_dia(loja, date(2026, 10, 12)) is True
    assert fechada_neste_dia(loja, date(2026, 10, 13)) is False


@pytest.mark.parametrize(
    "loja",
    [_loja("a"), {"id": "l-a", "dias_fechada": None}, {"id": "l-a"}],
    ids=["lista vazia", "nula", "sem a chave"],
)
def test_uma_loja_sem_dias_fechada_nunca_esta_fechada(loja):
    for n in range(7):
        assert fechada_neste_dia(loja, date(2026, 10, 12 + n)) is False


@pytest.mark.parametrize(
    "dia, nome",
    [(date(2026, 10, 12), "seg"), (date(2026, 10, 13), "ter"), (date(2026, 10, 14), "qua"),
     (date(2026, 10, 15), "qui"), (date(2026, 10, 16), "sex"), (date(2026, 10, 17), "sab"),
     (date(2026, 10, 18), "dom")],
    ids=["seg", "ter", "qua", "qui", "sex", "sab", "dom"],
)
def test_cada_dia_da_semana_conta_so_o_seu_nome(dia, nome):
    assert fechada_neste_dia(_loja("a", [nome]), dia) is True
    outros = [d for d in ("seg", "ter", "qua", "qui", "sex", "sab", "dom") if d != nome]
    assert fechada_neste_dia(_loja("a", outros), dia) is False


# --- seccoes ----------------------------------------------------------------------------------------------


def _lojas(*lojas):
    return {loja["id"]: loja for loja in lojas}


@pytest.mark.parametrize(
    "loja, paragem, seccao",
    [
        (None, _paragem("a", 0), "sem_loja"),
        (None, _paragem("a", 0, nao_cabe=True), "sem_loja"),
        (_loja("a", ["seg"]), _paragem("a", 0), "fechada"),
        (_loja("a", ["seg"]), _paragem("a", 0, nao_cabe=True), "fechada"),
        (_loja("a", ["seg"]), _paragem("a", 0, manter_fechada=True), "rota"),
        (_loja("a", ["seg"]), _paragem("a", 0, manter_fechada=True, nao_cabe=True), "nao_cabe"),
        (_loja("a", ["ter"]), _paragem("a", 0, nao_cabe=True), "nao_cabe"),
        (_loja("a", ["ter"]), _paragem("a", 0), "rota"),
        (_loja("a"), _paragem("a", 0, manter_fechada=True), "rota"),
    ],
    ids=["loja apagada", "loja apagada e não cabe", "fechada", "fechada e não cabe", "fechada mas manter",
         "fechada, manter e não cabe", "não cabe", "na rota", "manter sem estar fechada"],
)
def test_a_seccao_de_cada_paragem_pela_precedencia(loja, paragem, seccao):
    lojas = _lojas(loja) if loja is not None else {}
    [(p, l, s, numero)] = seccoes([paragem], lojas, HOJE)  # HOJE é segunda
    assert p is paragem
    assert l is loja
    assert s == seccao
    assert numero == (1 if seccao == "rota" else None)


def test_so_a_seccao_rota_e_numerada_de_1_a_k_pela_ordem():
    lojas = _lojas(_loja("a"), _loja("b", ["seg"]), _loja("c"), _loja("d"), _loja("f"), _loja("g", ["seg"]))
    lista = [
        _paragem("a", 0),
        _paragem("b", 1),  # fechada à segunda
        _paragem("c", 2),
        _paragem("d", 3, nao_cabe=True),
        _paragem("e", 4),  # loja apagada
        _paragem("f", 5),
        _paragem("g", 6, manter_fechada=True),
    ]
    resultado = seccoes(lista, lojas, HOJE)
    assert [(p["id"], s, n) for p, _, s, n in resultado] == [
        ("p-a", "rota", 1),
        ("p-b", "fechada", None),
        ("p-c", "rota", 2),
        ("p-d", "nao_cabe", None),
        ("p-e", "sem_loja", None),
        ("p-f", "rota", 3),
        ("p-g", "rota", 4),
    ]
    assert all(type(n) is int for _, _, s, n in resultado if s == "rota")


def test_as_seccoes_seguem_a_ordem_das_ativas_sem_as_retiradas():
    lojas = _lojas(_loja("a"), _loja("b"), _loja("c"), _loja("d"))
    lista = [_paragem("a", 2), _retirada("b"), _paragem("c", 0), _paragem("d", None)]
    resultado = seccoes(lista, lojas, HOJE)
    assert [(p["id"], n) for p, _, _, n in resultado] == [("p-c", 1), ("p-a", 2), ("p-d", 3)]
    assert resultado == seccoes(ativas(lista), lojas, HOJE)


def test_a_mesma_paragem_muda_de_seccao_com_o_dia():
    lojas = _lojas(_loja("a", ["dom"]))
    assert seccoes([_paragem("a", 0)], lojas, date(2026, 10, 18))[0][2] == "fechada"
    assert seccoes([_paragem("a", 0)], lojas, date(2026, 10, 19))[0][2] == "rota"


def test_seccoes_de_nenhuma_paragem_e_uma_lista_vazia():
    assert seccoes([], {}, HOJE) == []


def test_as_seccoes_e_os_avisos_conhecidos():
    assert SECCOES == ("rota", "fechada", "nao_cabe", "sem_loja")
    assert AVISOS == ("nenhum", "fechada_neste_dia", "nao_cabe", "fora_de_horario")


# --- aviso --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paragem, seccao, atual, esperado",
    [
        (_paragem("a", 0), "fechada", True, "fechada_neste_dia"),
        (_paragem("a", 0, fora_de_horario=True), "fechada", True, "fechada_neste_dia"),
        (_paragem("a", 0, nao_cabe=True), "nao_cabe", True, "nao_cabe"),
        (_paragem("a", 0, nao_cabe=True), "nao_cabe", False, "nao_cabe"),
        (_paragem("a", 0, fora_de_horario=True), "rota", True, "fora_de_horario"),
        (_paragem("a", 0, fora_de_horario=True), "rota", False, "nenhum"),
        (_paragem("a", 0), "rota", True, "nenhum"),
        (_paragem("a", 0, fora_de_horario=True), "sem_loja", True, "nenhum"),
        (_paragem("a", 0), "sem_loja", False, "nenhum"),
    ],
    ids=["fechada", "fechada e fora de horário", "não cabe", "não cabe sem cálculo atual",
         "fora de horário com o cálculo atual", "fora de horário com horas velhas", "sem aviso",
         "loja apagada", "loja apagada sem cálculo"],
)
def test_o_aviso_de_cada_paragem(paragem, seccao, atual, esperado):
    assert aviso(paragem, seccao, atual) == esperado
    assert esperado in AVISOS


@pytest.mark.parametrize("seccao", ["", "Rota", "fechadas", None])
def test_aviso_de_uma_seccao_desconhecida_e_erro_de_programacao(seccao):
    with pytest.raises(ValueError):
        aviso(_paragem("a", 0), seccao, True)


# --- nova_ordem ------------------------------------------------------------------------------------------------


def test_nova_ordem_com_todas_as_paragens_e_a_ordem_pedida():
    lista = [_paragem("a", 0), _paragem("b", 1), _paragem("c", 2)]
    assert nova_ordem(lista, ["p-c", "p-a", "p-b"]) == ["p-c", "p-a", "p-b"]


def test_nova_ordem_e_leniente_as_ativas_em_falta_vao_para_o_fim_pela_ordem_delas():
    lista = [_paragem("a", 0), _paragem("b", 1), _paragem("c", 2), _paragem("d", 3)]
    assert nova_ordem(lista, ["p-c"]) == ["p-c", "p-a", "p-b", "p-d"]
    assert nova_ordem(lista, ["p-d", "p-b"]) == ["p-d", "p-b", "p-a", "p-c"]
    assert nova_ordem(lista, []) == ["p-a", "p-b", "p-c", "p-d"]


def test_nova_ordem_segue_a_ordem_das_ativas_e_nao_a_posicao_na_lista():
    lista = [_paragem("a", 2), _retirada("b"), _paragem("c", 0), _paragem("d", None), _paragem("e", 1)]
    assert nova_ordem(lista, ["p-a"]) == ["p-a", "p-c", "p-e", "p-d"]


@pytest.mark.parametrize(
    "pedidos",
    [["p-x"], ["p-a", "p-x"], ["p-b"], ["p-a", "p-a"], ["p-c", "p-a", "p-c"]],
    ids=["desconhecida", "uma conhecida e uma desconhecida", "retirada", "repetida", "repetida no fim"],
)
def test_nova_ordem_recusa_ids_que_nao_estao_entre_as_ativas_ou_repetidos(pedidos):
    lista = [_paragem("a", 0), _retirada("b"), _paragem("c", 1)]
    with pytest.raises(ValueError):
        nova_ordem(lista, pedidos)


def test_nova_ordem_nao_muda_o_que_recebe_e_devolve_uma_lista_nova():
    lista = [_paragem("a", 0), _paragem("b", 1)]
    pedidos = ["p-b"]
    antes = copy.deepcopy(lista)
    resultado = nova_ordem(lista, pedidos)
    assert lista == antes
    assert pedidos == ["p-b"]
    assert resultado is not pedidos


# --- servico_padrao ------------------------------------------------------------------------------------------


DEFINICOES = {
    "servico_entrega_min": 10,
    "servico_amostra_min": 11,
    "servico_acompanhamento_min": 15,
    "servico_angariacao_min": 16,
}


@pytest.mark.parametrize(
    "motivo, minutos",
    [("entrega", 10), ("amostra", 11), ("acompanhamento", 15), ("angariacao", 16)],
)
def test_o_tempo_de_servico_padrao_e_o_do_motivo_nas_definicoes(motivo, minutos):
    assert servico_padrao(motivo, DEFINICOES) == minutos


@pytest.mark.parametrize("motivo", ["", None, "Entrega", "visita", "entrega_min"])
def test_servico_padrao_de_um_motivo_desconhecido_e_erro_de_programacao(motivo):
    with pytest.raises(ValueError):
        servico_padrao(motivo, {**DEFINICOES, "servico__min": 1, "servico_None_min": 1})


# --- campos do terreno e do escritório ---------------------------------------------------------------------------


def test_os_campos_do_terreno():
    assert CAMPOS_DO_TERRENO == ("estado", "resultado", "concluida_em")


def test_os_campos_do_escritorio():
    assert CAMPOS_DO_ESCRITORIO == (
        "ordem", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe", "chegada_prevista", "espera_min",
        "fora_de_horario", "removida_em", "adicionada_em", "adicionada_por",
    )


def test_os_campos_imutaveis():
    assert CAMPOS_IMUTAVEIS == ("id", "loja_id")


def test_os_tres_conjuntos_de_campos_sao_disjuntos_e_cobrem_a_paragem():
    terreno, escritorio, imutaveis = set(CAMPOS_DO_TERRENO), set(CAMPOS_DO_ESCRITORIO), set(CAMPOS_IMUTAVEIS)
    assert terreno.isdisjoint(escritorio)
    assert terreno.isdisjoint(imutaveis)
    assert escritorio.isdisjoint(imutaveis)
    assert terreno | escritorio | imutaveis == CHAVES_DA_PARAGEM
    assert len(CAMPOS_DO_TERRENO) + len(CAMPOS_DO_ESCRITORIO) + len(CAMPOS_IMUTAVEIS) == len(CHAVES_DA_PARAGEM)
    assert set(_paragem("a", 0)) == CHAVES_DA_PARAGEM


# --- caminhos_paragem ----------------------------------------------------------------------------------------------


def test_caminhos_paragem_escreve_os_caminhos_da_paragem_pelo_indice():
    assert caminhos_paragem(3, {"ordem": 0, "motivo": "amostra"}) == {
        "paragens.3.ordem": 0,
        "paragens.3.motivo": "amostra",
    }


@pytest.mark.parametrize("campo", CAMPOS_DO_ESCRITORIO)
def test_caminhos_paragem_aceita_cada_campo_do_escritorio(campo):
    assert caminhos_paragem(0, {campo: None}) == {f"paragens.0.{campo}": None}


def test_caminhos_paragem_guarda_a_ordem_das_chaves_e_os_valores():
    valor = {"lat": 1}
    campos = {"removida_em": "2026-10-12T09:00:00Z", "ordem": None, "chegada_prevista": valor}
    caminhos = caminhos_paragem(47, campos)
    assert list(caminhos) == ["paragens.47.removida_em", "paragens.47.ordem", "paragens.47.chegada_prevista"]
    assert caminhos["paragens.47.chegada_prevista"] is valor


def test_caminhos_paragem_sem_campos_nao_escreve_nada():
    assert caminhos_paragem(0, {}) == {}


def test_caminhos_paragem_nao_muda_os_campos_recebidos():
    campos = {"ordem": 1}
    caminhos = caminhos_paragem(2, campos)
    assert campos == {"ordem": 1}
    assert caminhos is not campos


@pytest.mark.parametrize("campo", CAMPOS_DO_TERRENO)
def test_caminhos_paragem_recusa_os_campos_do_terreno(campo):
    with pytest.raises(ValueError):
        caminhos_paragem(0, {campo: "feita"})


@pytest.mark.parametrize("campo", ["id", "loja_id"])
def test_caminhos_paragem_recusa_os_campos_imutaveis(campo):
    with pytest.raises(ValueError):
        caminhos_paragem(0, {campo: "x"})


@pytest.mark.parametrize(
    "campo",
    ["notas", "", "Ordem", "ordem ", "ordem.x", "$set", "paragens.0.estado", "estado.0", "client_uuid"],
    ids=["notas", "vazio", "maiúscula", "espaço", "subcampo", "operador", "caminho completo", "subcampo do terreno",
         "da fila da F4"],
)
def test_caminhos_paragem_recusa_um_campo_desconhecido(campo):
    with pytest.raises(ValueError):
        caminhos_paragem(0, {campo: 1})


def test_caminhos_paragem_recusa_tudo_se_um_dos_campos_for_do_terreno():
    with pytest.raises(ValueError):
        caminhos_paragem(1, {"ordem": 0, "estado": "pendente", "motivo": "amostra"})


@pytest.mark.parametrize(
    "indice",
    [-1, True, False, "3", 3.0, None, "$", "$[]"],
    ids=["negativo", "True", "False", "texto", "decimal", "nulo", "posicional", "todos"],
)
def test_caminhos_paragem_recusa_um_indice_que_nao_e_um_inteiro_natural(indice):
    with pytest.raises(ValueError):
        caminhos_paragem(indice, {"ordem": 0})


@pytest.mark.parametrize("campos", [[("ordem", 0)], None, "ordem"], ids=["lista de pares", "nulo", "texto"])
def test_caminhos_paragem_so_aceita_um_dicionario(campos):
    with pytest.raises(ValueError):
        caminhos_paragem(0, campos)


# --- ids.e_uuid4 -----------------------------------------------------------------------------------------------------


def test_e_uuid4_usa_o_mesmo_padrao_do_validador_da_loja():
    assert ids.PADRAO_UUID4 is validador_loja._UUID4


def test_o_ids_nao_compila_uma_copia_do_padrao():
    """O `re.compile` guarda os padrões em cache: uma cópia com o mesmo texto
    devolvia o mesmo objeto e passava no `is`. O `ids.py` importa-o e não
    compila nada (uma cópia divergia do `validador_loja` sem ninguém ver)."""
    arvore = ast.parse(Path(ids.__file__).read_text(encoding="utf-8"))
    importa_re = any(
        isinstance(no, ast.Import) and any(nome.name == "re" for nome in no.names)
        or isinstance(no, ast.ImportFrom) and no.module == "re"
        for no in ast.walk(arvore)
    )
    compila = any(isinstance(no, ast.Attribute) and no.attr == "compile" for no in ast.walk(arvore))
    assert (importa_re, compila) == (False, False)


def test_e_uuid4_aceita_os_uuid4_do_python():
    gerador = random.Random(33)
    for _ in range(300):
        assert e_uuid4(str(uuid.UUID(int=gerador.getrandbits(128), version=4))) is True
    assert e_uuid4(str(uuid.uuid4())) is True


@pytest.mark.parametrize(
    "valor",
    [
        "123E4567-E89B-42D3-A456-426614174000",
        "123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-52d3-a456-426614174000",
        "123e4567-e89b-42d3-c456-426614174000",
        "00000000-0000-0000-0000-000000000000",
        "{123e4567-e89b-42d3-a456-426614174000}",
        "123e4567e89b42d3a456426614174000",
        "123e4567-e89b-42d3-a456-426614174000\n",
        " 123e4567-e89b-42d3-a456-426614174000",
        "123e4567-e89b-42d3-a456-42661417400０",
        "123e4567-e89b-42d3-a456-4266141740000",
        "",
        None,
        123,
        b"123e4567-e89b-42d3-a456-426614174000",
        uuid.UUID("123e4567-e89b-42d3-a456-426614174000"),
        ["123e4567-e89b-42d3-a456-426614174000"],
    ],
    ids=["maiúsculas", "versão 1", "versão 5", "variante c", "nulo (nil)", "chavetas", "sem hífenes",
         "nova linha no fim", "espaço antes", "algarismo de largura total", "um a mais", "vazio", "None", "número",
         "bytes", "objeto UUID", "lista"],
)
def test_e_uuid4_recusa_o_que_nao_e_um_uuid4_em_texto_minusculo(valor):
    assert e_uuid4(valor) is False
