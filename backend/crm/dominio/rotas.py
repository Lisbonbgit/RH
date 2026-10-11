"""As regras da rota de um dia: motivos, prioridades, estado ao ler, secções e
caminhos de escrita (F3).

O CRM autónomo não tem código de rotas: as regras vêm do desenho original
(§4.3 motivos, §7.2 prioridades) e do plano F3 (§1 e §3). Uma rota é um
documento de `crm_rotas` com as `paragens` embutidas, que só se acrescentam
(retirar é suave, com `removida_em`).

- **Motivo:** pré-escolhido pela fase (`motivo_por_fase`); o tempo de serviço
  por omissão vem das definições (`servico_padrao`).
- **Prioridades do VROOM:** entrega 100, as outras 1. Como
  48 × 1 < 100, nenhuma soma de visitas vale mais do que uma entrega (a F5
  junta a prioridade 2 das visitas pendentes 🔁: 48 × 2 < 100).
- **Fecho simples:** um dia anterior a hoje lê-se `concluida` e não se
  escreve (`rota_fechada`). Uma rota fora de `rascunho`/`planeada`, ou com
  algum registo do motorista (mesmo numa paragem retirada), só se vê no
  escritório (`rota_em_curso`). A F4 abre aqui as suas exceções.
- **O terreno ganha (desenho §4.3):** o escritório escreve só pelos caminhos
  `paragens.<índice>.<campo do escritório>` (`caminhos_paragem`); os campos do
  terreno só se escrevem ao criar a paragem.

Os dias (`data`, `hoje`) são `date` (`datas.ler_data`, `relogio.hoje`), nunca
texto nem instantes.
"""
from datetime import date
from types import MappingProxyType

from .datas import dia_da_semana

# Igual a MOTIVOS em frontend/src/lib/crm/rota.js (test_consistencia_frontend.py, T3.27): manter numa só linha.
MOTIVOS = ("entrega", "amostra", "acompanhamento", "angariacao")

# A pré-escolha do motivo ao adicionar à rota (desenho original §4.3), pela
# ordem das fases (`fases.ORDEM`). A F5 junta a entrega (encomenda pendente
# até ao dia) e o motivo da visita pendente 🔁.
# Igual a MOTIVO_POR_FASE em frontend/src/lib/crm/rota.js (T3.27).
MOTIVO_POR_FASE = MappingProxyType({"perdida": "angariacao", "potencial": "angariacao", "contactada": "amostra", "amostra": "acompanhamento", "cliente": "acompanhamento"})

# Sem fase conhecida, a loja ainda está por angariar.
_MOTIVO_SEM_FASE = "angariacao"

PRIORIDADE_ENTREGA = 100
PRIORIDADE_OUTRAS = 1

# O Directions aceita 50 coordenadas: 48 paragens mais o início e o fim.
# Igual a LIMITE_PARAGENS em frontend/src/lib/crm/rota.js (T3.27).
LIMITE_PARAGENS = 48

# Os estados gravados de uma rota. A F3 só escreve `rascunho`/`planeada`; a
# F4 grava `em_curso` e a F5 `concluida` (fecho noturno).
ESTADOS = ("rascunho", "planeada", "em_curso", "concluida")
ESTADOS_EDITAVEIS = ("rascunho", "planeada")

# Os estados de uma paragem que são um registo do motorista: a partir do
# primeiro, a rota é só de leitura no escritório (`rotas_bd` filtra também
# por eles com `"paragens.estado": {"$nin": ...}`).
ESTADOS_COM_REGISTO = ("feita", "nao_feita")

# As secções do planeador, pela ordem da precedência em `seccoes`, e os avisos.
SECCOES = ("rota", "fechada", "nao_cabe", "sem_loja")
AVISOS = ("nenhum", "fechada_neste_dia", "nao_cabe", "fora_de_horario")

# Os campos de uma paragem (plano F3 §3), em três conjuntos disjuntos:
# - os do terreno (F4, alargados lá), que o escritório só escreve ao criar a paragem;
# - os do escritório, os únicos que `caminhos_paragem` aceita;
# - os imutáveis, que nascem com a paragem e nunca mudam.
CAMPOS_DO_TERRENO = ("estado", "resultado", "concluida_em")
CAMPOS_DO_ESCRITORIO = (
    "ordem",
    "motivo",
    "tempo_servico_min",
    "manter_fechada",
    "nao_cabe",
    "chegada_prevista",
    "espera_min",
    "fora_de_horario",
    "removida_em",
    "adicionada_em",
    "adicionada_por",
)
CAMPOS_IMUTAVEIS = ("id", "loja_id")


def motivo_por_fase(fase) -> str:
    """O motivo pré-escolhido para uma loja nesta fase; uma fase desconhecida
    (ou que nem é texto) dá `angariacao`, sem rebentar."""
    if not isinstance(fase, str):
        return _MOTIVO_SEM_FASE
    return MOTIVO_POR_FASE.get(fase, _MOTIVO_SEM_FASE)


def prioridade(motivo) -> int:
    """A prioridade do *job* no VROOM: entrega 100, as outras visitas 1.

    Um motivo que não é dos `MOTIVOS` é um erro de programação (os motivos
    gravados passaram pelo validador): `ValueError`.
    """
    _exigir_motivo(motivo)
    return PRIORIDADE_ENTREGA if motivo == "entrega" else PRIORIDADE_OUTRAS


def servico_padrao(motivo, definicoes):
    """O tempo de serviço por omissão de um motivo, em minutos: a definição
    `servico_<motivo>_min` em vigor (`definicoes.combinar`)."""
    _exigir_motivo(motivo)
    return definicoes[f"servico_{motivo}_min"]


def estado_efetivo(estado, data: date, hoje: date):
    """O estado ao ler: um dia anterior a hoje é sempre `concluida` (o fecho
    simples da F3, sem gravar nada); hoje e o futuro têm o estado gravado
    (`None` numa rota virtual)."""
    return "concluida" if _passado(data, hoje) else estado


def bloqueio_de_escrita(rota, data: date, hoje: date):
    """Porque é que o escritório não pode escrever nesta rota, ou `None`.

    - um dia anterior a hoje → `"rota_fechada"` (com ou sem rota);
    - sem rota (hoje ou futuro) → `None`: a primeira paragem cria-a;
    - um estado fora de `ESTADOS_EDITAVEIS`, ou alguma paragem com um registo
      do motorista (`feita`/`nao_feita`), **mesmo retirada** →
      `"rota_em_curso"`;
    - senão `None`.
    """
    if _passado(data, hoje):
        return "rota_fechada"
    if rota is None:
        return None
    if rota.get("estado") not in ESTADOS_EDITAVEIS or any(
        paragem.get("estado") in ESTADOS_COM_REGISTO for paragem in rota["paragens"]
    ):
        return "rota_em_curso"
    return None


def ativas(paragens) -> list:
    """As paragens não retiradas (`removida_em` nulo), por `ordem`, e no
    empate pela posição na lista. Lista nova, com as mesmas paragens.

    Uma paragem ativa com `ordem` nula (a F4 repõe uma retirada só com
    `removida_em: null`, contrato do §3) vai para o fim, pela posição: nunca
    se compara `None` com um inteiro.
    """
    com_posicao = [(posicao, p) for posicao, p in enumerate(paragens) if p.get("removida_em") is None]
    com_posicao.sort(key=_chave_da_ordem)
    return [p for _, p in com_posicao]


def _chave_da_ordem(par):
    """`(ordem nula?, ordem, posição)`: a chave da correção "T3.3 (ativas com ordem nula)"."""
    posicao, paragem = par
    ordem = paragem["ordem"]
    return (ordem is None, ordem if ordem is not None else 0, posicao)


def fechada_neste_dia(loja, data: date) -> bool:
    """A loja fecha neste dia da semana (`dias_fechada`)? Sem dias → `False`."""
    return dia_da_semana(data) in (loja.get("dias_fechada") or ())


def seccoes(paragens, lojas_por_id, data: date) -> list:
    """`[(paragem, loja, seccao, numero)]` das paragens ativas, pela ordem de `ativas`.

    A secção, por esta precedência:
    - `"sem_loja"`: a loja já não existe (`lojas_por_id` não a tem);
    - `"fechada"`: a loja fecha nesse dia e a paragem não tem `manter_fechada`;
    - `"nao_cabe"`: o último cálculo não a conseguiu encaixar;
    - `"rota"`: as outras.

    Só a secção `"rota"` é numerada, de 1 a k pela ordem; as outras têm
    `numero` `None`. As retiradas saem (passa-se tudo por `ativas`).
    """
    resultado = []
    numero = 0
    for paragem in ativas(paragens):
        loja = lojas_por_id.get(paragem["loja_id"])
        if loja is None:
            seccao = "sem_loja"
        elif fechada_neste_dia(loja, data) and not paragem.get("manter_fechada"):
            seccao = "fechada"
        elif paragem.get("nao_cabe"):
            seccao = "nao_cabe"
        else:
            seccao = "rota"
        if seccao == "rota":
            numero += 1
        resultado.append((paragem, loja, seccao, numero if seccao == "rota" else None))
    return resultado


def aviso(paragem, seccao, calculo_atual: bool) -> str:
    """O ⚠️ de uma paragem, pela secção: `fechada` → `"fechada_neste_dia"`;
    `nao_cabe` → `"nao_cabe"`; na rota, `"fora_de_horario"` só se o último
    Directions o disse e as horas ainda servem (`calculo_atual`); senão
    `"nenhum"` (também numa loja apagada)."""
    if seccao not in SECCOES:
        raise ValueError(f"Secção desconhecida: {seccao!r}")
    if seccao == "fechada":
        return "fechada_neste_dia"
    if seccao == "nao_cabe":
        return "nao_cabe"
    if seccao == "rota" and calculo_atual and paragem.get("fora_de_horario"):
        return "fora_de_horario"
    return "nenhum"


def nova_ordem(paragens, ids) -> list:
    """Os ids das paragens ativas pela nova ordem: primeiro os `ids` pedidos,
    depois as ativas em falta, pela ordem delas (leniente: o planeador pode
    mandar só parte da lista).

    Um id que não é de uma paragem ativa (desconhecido ou retirada) ou
    repetido dá `ValueError` (o validador e a rota já o recusaram com 422).
    """
    por_ordem = [p["id"] for p in ativas(paragens)]
    conhecidos = set(por_ordem)
    vistos = set()
    for id_ in ids:
        if id_ not in conhecidos:
            raise ValueError(f"Esta paragem não está na rota: {id_!r}")
        if id_ in vistos:
            raise ValueError(f"Paragem repetida na ordem: {id_!r}")
        vistos.add(id_)
    return [*ids, *(id_ for id_ in por_ordem if id_ not in vistos)]


def caminhos_paragem(indice, campos) -> dict:
    """O `$set` de campos do escritório numa paragem: `{"paragens.<índice>.<campo>": valor}`.

    Pela ordem das chaves de `campos`. `ValueError` (sem escrever nada) com
    um campo do terreno, um campo imutável (`id`, `loja_id`) ou desconhecido,
    um índice que não é um inteiro ≥ 0 (um `bool` não conta; nada de
    posicionais `$`) ou `campos` que não é um dicionário.
    """
    if type(indice) is not int or indice < 0:
        raise ValueError(f"Índice de paragem inválido: {indice!r}")
    if not isinstance(campos, dict):
        raise ValueError("Os campos da paragem têm de vir num dicionário.")
    for campo in campos:
        if campo not in CAMPOS_DO_ESCRITORIO:
            raise ValueError(f"O escritório não escreve o campo {campo!r} de uma paragem.")
    return {f"paragens.{indice}.{campo}": valor for campo, valor in campos.items()}


def _passado(data: date, hoje: date) -> bool:
    """`data` é anterior a `hoje`? Os dois têm de ser `date` (nem texto nem
    `datetime`, que é uma subclasse: o instante UTC daria o dia errado)."""
    if type(data) is not date or type(hoje) is not date:
        raise TypeError("Os dias das rotas são datetime.date.")
    return data < hoje


def _exigir_motivo(motivo):
    if not isinstance(motivo, str) or motivo not in MOTIVOS:
        raise ValueError(f"Motivo desconhecido: {motivo!r}")
