"""**CINCO LEITORES, UMA PERGUNTA.**

Havia cinco sítios a perguntar «que contas é que estão por resolver», cada um
com o seu filtro:

| quem | onde | para quê |
|---|---|---|
| a porta | `venda.py::_contas_do_balcao` | recusar abrir uma conta nova |
| o ecrã | `venda.py::venda_aberta` + `contas_repartidas` | mostrar à operadora |
| o travão | `caixa.py::_venda_com_emissao_viva` | impedir o fecho |
| o diálogo e o Z | `caixa.py::_contas_abertas_da_sessao` | contar o que fica por cobrar |
| o gestor | `caixa.py::_contas_esquecidas` | arrumar depois do Z |

Os ÂMBITOS são legitimamente diferentes (o posto, a sessão, todas as sessões)
e os FINS também. O que não podia ser diferente — e era — é o PREDICADO: o
que conta como «por resolver». Cinco rondas corrigiram-no num par de leitores
de cada vez, e de cada vez a divergência reapareceu entre outros dois.

**Medido pelas rotas reais, antes desta ronda:**

- uma RESERVA cuja venda já não existe (uma filha apagada pela compensação de
  `venda.py::_grava_as_partes`): o travão via-a (`{'id': 'filha-9'}`, e o
  `POST /pos/caixa/fechar` dava 409 a nomeá-la), o diálogo que a operadora lê
  ANTES de assinar dizia `quantas=0 total=0,00`. Ela lia «nada por cobrar»,
  carregava em FECHAR e levava um 409 com um id que não estava em ecrã nenhum;
- uma mãe `separada` SEM PARTES de 11,35 €: `GET /pos/venda/aberta` `null`,
  `GET /pos/venda/repartidas` `[]`, `/caixa/contas-esquecidas` 0, o diálogo
  `quantas=0 total=0,00` — e o `POST /pos/caixa/fechar` respondia **200 com o
  Z assinado a dizer «por cobrar 0,00 €»** por cima dela.

**A correcção é haver UMA função que decide.** Ela devolve, para um âmbito de
sessões, TODAS as contas por resolver, cada uma já classificada — porquê é que
está por resolver (`motivo`), se TRAVA o fecho (`tem_reserva_viva`), e se está
EM CURSO no balcão (`em_curso_no_balcao`). Os cinco consumidores filtram por
ATRIBUTOS que ela calculou; nenhum volta a decidir o que conta.

Se algum dia se escrever «esta função tem de devolver o mesmo que aquela»,
é o erro que já se cometeu cinco vezes.

## O predicado, por inteiro

Está por resolver:

1. **uma venda num estado NÃO TERMINAL.** Terminal são só duas: `emitida` (já
   é uma Fatura Simplificada) e `cancelada` (ninguém a vai pagar). O filtro é
   `$nin` sobre essas duas e não uma lista das que contam, de propósito e pela
   mesma razão do travão do fecho: um estado novo que apareça amanhã cai do
   lado de CONTAR, que é o lado seguro;
2. **uma mãe `separada` SEM PARTES NENHUMAS.** Uma mãe separada COM partes
   está resolvida — o dinheiro dela mudou-se para as filhas, e são elas que
   entram aqui enquanto estiverem por cobrar. Sem partes, não se mudou para
   lado nenhum: são euros que só existem naquele documento;
3. **uma RESERVA FISCAL VIVA** (`documento_id` por preencher e a venda dela
   ainda não `emitida`) — **incluindo uma reserva cuja venda já não existe**.
   É o critério de `fiscal.py::listar_reservas_presas`, e a pergunta faz-se
   do lado das RESERVAS precisamente para a venda apagada entrar.

## O âmbito

`sessao_ids` — a lista de sessões, ou `None` para TODAS (o âmbito do gestor,
que vê as várias lojas e os turnos todos). É o único parâmetro de âmbito, e não
há um `estado` nem um `dispositivo_id` que dois chamadores possam passar
diferente: o que cada um faz é FILTRAR o que sai daqui.

A pergunta às reservas é feita pelo prefixo da `ext_ref`
(`pos-{loja}-{sessão}-`, `fiscal.py::ext_ref_determinista`), que já carrega a
sessão — por isso não é preciso campo novo nenhum, e o índice único de
`ext_ref` serve a leitura. O prefixo constrói-se com a PRÓPRIA função que o
gera, nunca com uma segunda cópia do formato escrita aqui. Com `sessao_ids` a
`None` não há prefixo nenhum: fica o `{"documento_id": None}`, que é o mesmo
filtro barato de `fiscal.listar_reservas_presas`.
"""
import logging
import re
from typing import Dict, List, Optional

from .db import COLECOES

logger = logging.getLogger(__name__)

# Os dois estados de que já não se espera dinheiro nenhum. Tudo o resto conta.
ESTADOS_TERMINAIS = ("emitida", "cancelada")

# Tectos de leitura, como em todo o módulo — nenhuma leitura sem tecto. Um
# turno tem, no pior dos casos, um punhado de contas por resolver e um punhado
# de reservas por fechar.
_LIMITE_VENDAS = 1000
_LIMITE_RESERVAS = 200

MOTIVO_ABERTA = "conta_aberta"
MOTIVO_SEPARADA_SEM_PARTES = "mae_separada_sem_partes"
MOTIVO_EMISSAO_VIVA = "emissao_viva"
MOTIVO_ESTADO_DESCONHECIDO = "estado_desconhecido"


def _total_da_venda(venda: Optional[Dict]) -> Optional[float]:
    """O valor da conta, ou `None` quando não há venda ou já não se consegue
    somar.

    A regra é a que `caixa._contas_abertas_da_sessao` já tinha: o que não se
    pode perder é a EXISTÊNCIA da conta, e «não sabemos quanto vale» é uma
    resposta honesta que alguém consegue levar ao gestor. Uma linha que
    `precos.linha_de_venda` já não sabe avaliar não pode transformar o fecho
    num 500 — isso mandava a funcionária fechar outra vez uma caixa que não
    fechou.

    O valor sai do `_totais` de `venda.py` (import local, o ciclo de sempre
    deste pacote) e nunca de uma soma escrita aqui: a aritmética de dinheiro
    tem um só dono."""
    from .venda import _totais

    if venda is None:
        return None
    try:
        return _totais(venda)["total"]
    except Exception as e:  # noqa: BLE001 — ver a docstring
        logger.warning(
            "[faturacao] não foi possível somar a conta %s: %s (conta na mesma, "
            "sem valor).", venda.get("id"), e,
        )
        return None


def _item(venda: Optional[Dict], venda_id: str, motivo: str) -> Dict:
    venda = venda or {}
    return {
        "id": venda.get("id") or venda_id,
        # O documento inteiro, para quem precisa dele (o balcão devolve a
        # conta ao ecrã). `None` quando a venda já não existe — e essa
        # ausência é uma informação, não um buraco.
        "venda": venda or None,
        "loja_id": venda.get("loja_id"),
        "sessao_id": venda.get("sessao_id"),
        "caixa_id": venda.get("caixa_id"),
        "dispositivo_id": venda.get("dispositivo_id"),
        "operador_id": venda.get("operador_id"),
        "conta_mae_id": venda.get("conta_mae_id"),
        "criada_em": venda.get("criada_em"),
        "estado_da_venda": venda.get("estado"),
        "entregue_ao_gestor_em": venda.get("entregue_ao_gestor_em"),
        "total": _total_da_venda(venda or None),
        "motivo": motivo,
        # Preenchidos a seguir, por `contas_por_resolver`. Sempre presentes,
        # nunca ausentes: quem lê não pode ter de adivinhar se a falta da
        # chave quer dizer "não" ou "esta versão não responde a isso".
        "tem_reserva_viva": False,
        "em_curso_no_balcao": False,
    }


async def _tem_partes(db, venda_id: str) -> bool:
    return await db[COLECOES["vendas"]].find_one(
        {"conta_mae_id": venda_id}, {"_id": 0, "id": 1}
    ) is not None


async def _mae_ja_travou(db, venda: Dict, conhecidas: Dict) -> bool:
    """**RAIZ 1: uma parte não existe para ninguém enquanto a mãe não estiver
    `separada`.**

    As filhas nascem primeiro e a mãe trava a seguir (`venda._grava_as_partes`,
    e a ordem é deliberada — ver lá). Entre as duas escritas as filhas já
    estavam gravadas e a mãe ainda `aberta`: medido pelas rotas reais, nessa
    janela o `GET /pos/venda/repartidas` respondia **1 grupo com 3 partes**
    (3,79 + 3,78 + 3,78 €) e o `GET /pos/venda/aberta` devolvia uma PARTE de
    3,78 € como a conta em curso, no lugar da conta de 11,35 € que a operadora
    tinha à frente.

    Com esta pergunta a janela deixa de ser observável, e é isso que torna a
    compensação segura: as filhas podem ser apagadas porque ninguém as podia
    ver."""
    mae_id = venda.get("conta_mae_id")
    if not mae_id:
        return True
    if mae_id not in conhecidas:
        conhecidas[mae_id] = await db[COLECOES["vendas"]].find_one(
            {"id": mae_id}, {"_id": 0, "id": 1, "estado": 1}
        )
    mae = conhecidas[mae_id]
    # Uma parte cuja mãe foi apagada à mão da base não é uma parte de nada — e
    # esconder o dinheiro dela era o defeito ao contrário. Conta como conta
    # normal do balcão; quem a arruma é o gestor.
    return mae is None or mae.get("estado") == "separada"


async def contas_por_resolver(db, sessao_ids: List[str]) -> List[Dict]:
    """**Tudo o que estas sessões têm por resolver** — da mais antiga para a
    mais recente, com as que já não têm venda no fim.

    Ver o cabeçalho do ficheiro para o predicado por inteiro. Os cinco
    consumidores filtram o que sai daqui pelo seu FIM:

    - a porta e o ecrã: `em_curso_no_balcao` e o `dispositivo_id` do token;
    - o travão do fecho: `tem_reserva_viva` (e só essa — a regra 3 do dono é
      que o fecho não bloqueia por dinheiro que ninguém vai pagar);
    - o diálogo e o Z: tudo, com os subtotais que o ecrã desenha;
    - o gestor: as que já não estão num turno aberto, mais as entregues.
    """
    todas_as_sessoes = sessao_ids is None
    if not todas_as_sessoes and not sessao_ids:
        return []
    itens: Dict[str, Dict] = {}

    # 1) As vendas em estado NÃO TERMINAL destas sessões.
    filtro = {"estado": {"$nin": list(ESTADOS_TERMINAIS)}}
    if not todas_as_sessoes:
        filtro["sessao_id"] = {"$in": list(sessao_ids)}
    vendas = await (
        db[COLECOES["vendas"]]
        .find(filtro)
        .sort("criada_em", 1)
        .to_list(_LIMITE_VENDAS)
    )
    maes_conhecidas: Dict[str, Optional[Dict]] = {}
    for venda in vendas:
        estado = venda.get("estado")
        if estado == "separada":
            # Uma mãe separada COM partes está resolvida: o dinheiro mudou-se
            # para as filhas, e são elas que aparecem aqui enquanto estiverem
            # por cobrar. SEM partes é que não se mudou para lado nenhum.
            if await _tem_partes(db, venda["id"]):
                continue
            motivo = MOTIVO_SEPARADA_SEM_PARTES
        elif estado == "aberta":
            motivo = MOTIVO_ABERTA
        else:
            # O lado seguro do `$nin`: um estado que este ficheiro não conhece
            # conta, e diz por extenso que não o conhece.
            motivo = MOTIVO_ESTADO_DESCONHECIDO
        item = _item(venda, venda["id"], motivo)
        item["em_curso_no_balcao"] = (
            estado == "aberta"
            and not venda.get("entregue_ao_gestor_em")
            and await _mae_ja_travou(db, venda, maes_conhecidas)
        )
        itens[venda["id"]] = item

    # 2) As RESERVAS vivas destas sessões — incluindo aquelas cuja venda já
    #    não existe, que é o caso que nenhum leitor das vendas pode alcançar.
    from .fiscal import ext_ref_determinista

    filtro_das_reservas = {"documento_id": None}
    if not todas_as_sessoes:
        prefixos = []
        for sessao in await _sessoes(db, sessao_ids):
            # `["loja_id"]` e não `.get(...)`: uma sessão sem loja não existe
            # (`caixa.abrir_caixa` grava-a sempre) e o Z lê-a sem recuo nenhum.
            # Com um `.get`, uma sessão estragada dava o prefixo "pos-None-…-",
            # não casava com reserva nenhuma, e o travão do fecho desligava-se
            # em SILÊNCIO — que é a forma de falhar que ele existe para não ter.
            prefixos.append(
                {"ext_ref": {"$regex": "^" + re.escape(
                    ext_ref_determinista(sessao["loja_id"], sessao["id"], ""))}}
            )
        # Sem sessão nenhuma encontrada não há reserva que possa ser desta
        # leitura: uma condição impossível é melhor do que um filtro ausente,
        # que traria TODAS as reservas por resolver da base.
        filtro_das_reservas["$or"] = prefixos or [{"ext_ref": "\x00"}]
    reservas = await (
        db[COLECOES["refs_fiscais"]]
        .find(filtro_das_reservas)
        .to_list(_LIMITE_RESERVAS)
    )
    for reserva in reservas:
        venda_id = reserva.get("venda_id")
        venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
        # A reserva de uma venda EMITIDA fica em `fat_refs_fiscais` para
        # sempre de propósito (é ela que sustenta a idempotência,
        # `fiscal._gravar_documento`) — travar por causa dela era travar o
        # fecho de todas as noites.
        if venda is not None and venda.get("estado") == "emitida":
            continue
        item = itens.get(venda_id)
        if item is None:
            item = itens[venda_id] = _item(venda, venda_id, MOTIVO_EMISSAO_VIVA)
        item["tem_reserva_viva"] = True

    # Pela ordem em que nasceram, com as que já não têm venda no fim: é a
    # ordem em que uma lista de contas por cobrar se lê, e é determinística.
    return sorted(itens.values(), key=lambda i: (i["criada_em"] is None, i["criada_em"] or ""))


async def _sessoes(db, sessao_ids: List[str]) -> List[Dict]:
    return await (
        db[COLECOES["sessoes_caixa"]]
        .find({"id": {"$in": list(sessao_ids)}}, {"_id": 0, "id": 1, "loja_id": 1})
        .to_list(len(sessao_ids) + 1)
    )
