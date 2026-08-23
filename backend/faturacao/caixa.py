"""Sessão de caixa do POS: abrir, registar movimentos e fechar com o
relatório Z (Tasks 3 e 4 do Plano 2A, spec §7.2/§7.5/§7.6).

A sessão é sempre resolvida no SERVIDOR, nunca a partir de um valor que o
corpo do pedido diga que é a sessão: o cliente indica a caixa (`caixa_id`,
escolhida uma vez no PC ao entrar — spec §7.1) e o servidor procura, ele
próprio, a sessão ABERTA dessa caixa, confirmando primeiro que a caixa
pertence à loja do operador autenticado (`operador_atual`, ver
faturacao/pos_auth.py). Um `sessao_id` vindo directamente do corpo seria um
convite a lançar movimentos na sessão de outra pessoa ou de outra loja — por
isso `PedidoMovimento` nem sequer declara esse campo: mesmo que apareça no
JSON, o pydantic ignora-o (ver test_movimento_ignora_sessao_id... em
test_caixa_endpoints.py, que documenta a mutação perigosa que isto evita).

O índice único PARCIAL em {caixa_id, estado: "aberta"} (faturacao/db.py) é a
própria garantia de que nunca há duas sessões abertas na mesma caixa, mesmo
com dois PCs a tentar ao mesmo tempo — sem ele, o fecho e o Z (Task 4)
deixavam de fazer sentido. Este módulo confirma isso com uma leitura antes de
abrir, mas é o índice, não a leitura, que decide a corrida real.

Dinheiro: os valores de movimento (e a contagem do fecho, Task 4) passam pelo
mesmo crivo de 2 casas decimais de faturacao/precos.py
(`_tem_mais_de_2_casas_decimais`), reutilizado e não reescrito — round() sobre
a representação binária come cêntimos sem avisar.

**Os TRÊS estados de uma sessão, e porque é que são três.** `aberta`,
`a_fechar` e `fechada`. O do meio não é um detalhe de arrumação: é o
mecanismo de exclusão mútua entre o FECHO e a EMISSÃO de faturas (ver
`fechar_caixa`, secção "A JANELA"). O fecho marca `a_fechar` ANTES de somar
seja o que for, e só depois pergunta se há alguma emissão viva; uma emissão
que chegue a partir daí é recusada pelo próprio núcleo fiscal, que exige a
sessão `aberta` (`fiscal.py::_garante_venda_ainda_aberta`, e a pergunta de
entrada `_garante_sessao_da_venda_aberta`). Marcar-primeiro-perguntar-depois
é a ordem toda: perguntar primeiro e escrever depois — que é o que este
módulo fazia — deixa exactamente a janela por onde saiu uma FS real para um
turno que fechou a seguir.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .caixa_math import (
    _centimos,
    devolucoes_acima_do_recebido,
    diferenca,
    esperado,
    por_tipo_de_pagamento,
    soma_vendas_dinheiro,
    tirado_da_gaveta_a_mais,
    total_por_tipo,
)
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais

logger = logging.getLogger(__name__)

router = APIRouter()

_MSG_CAIXA_INEXISTENTE = "Caixa não encontrada."
_MSG_SEM_CAIXA_CONFIGURADA = (
    "Não há nenhuma caixa activa configurada para esta loja. Contacte o gestor."
)
_MSG_CAIXA_JA_ABERTA = "Esta caixa já tem uma sessão aberta."
_MSG_SEM_SESSAO_ABERTA = "Esta caixa não tem nenhuma sessão aberta."
_MSG_SESSAO_A_MEIO_DE_UM_FECHO = (
    "Esta caixa está a meio de um fecho de turno — o Z ainda não saiu. "
    "Carregue outra vez em FECHAR CAIXA para o concluir; só depois se pode "
    "abrir contas novas ou mexer no dinheiro da gaveta."
)
_MSG_FECHO_JA_EM_CURSO = (
    "Outro pedido está a fechar esta sessão neste preciso momento — o Z é um "
    "só. Espere alguns segundos e veja o resultado no ecrã da caixa."
)
# AS QUATRO SAÍDAS DA RECUSA DE UM MOVIMENTO (ver
# `_porque_o_movimento_nao_entrou`). A confirmação exige
# `{"estado": "aberta"}` e a MESMA falha (`matched_count == 0`) cobre
# situações que pedem à operadora coisas diferentes — e uma delas pode ainda
# ser desfeita. O 409 descreve a caixa como ela está no instante em que a
# operadora o lê, nunca o pior caso.
_MSG_SESSAO_FECHADA_ENTRETANTO = (
    "Esta sessão foi fechada por outro pedido entretanto — não é possível "
    "registar o movimento. Ele NÃO entrou em nenhum Z: reponha o dinheiro na "
    "gaveta ou registe o movimento outra vez, já na sessão nova."
)
_MSG_MOVIMENTO_COM_FECHO_A_DECORRER = (
    "A caixa está a FECHAR o turno neste momento — enquanto o Z está a ser "
    "calculado não entra nem sai dinheiro da gaveta. O movimento NÃO ficou "
    "registado e NÃO entrou em nenhum Z; nada mudou no sistema. Espere "
    "alguns segundos e registe-o outra vez: um fecho demora um instante, e "
    "um que apanhe uma emissão a meio nesta caixa é recusado e desfeito por "
    "ele próprio. Se o turno fechar mesmo, o ecrã da caixa dir-lho-á com "
    "outras palavras."
)
_MSG_MOVIMENTO_NA_MESMA_SESSAO_OUTRA_VEZ = (
    "Um fecho de turno apanhou este movimento a meio e recusou-o — e esse "
    "fecho foi ele próprio desfeito: a caixa continua ABERTA, na MESMA "
    "sessão, e nenhum Z foi assinado. O movimento NÃO ficou registado e NÃO "
    "entrou em nenhum Z — registe-o outra vez, aqui mesmo."
)
_MSG_MOVIMENTO_NAO_REGISTADO = (
    "Não foi possível registar este movimento: a sessão de caixa mudou de "
    "estado no instante exacto em que ele ia entrar. Ele NÃO entrou em "
    "nenhum Z e nada ficou registado — veja o ecrã da caixa e registe-o "
    "outra vez na sessão que lá estiver."
)
_MSG_FECHO_EM_CONFLITO = (
    "Esta sessão já foi fechada por outro pedido — o Z já foi emitido, "
    "não se fecha duas vezes."
)
_MSG_FECHO_COM_EMISSAO_EM_CURSO = (
    "A conta %s desta caixa tem uma emissão de fatura em curso ou por "
    "confirmar — o turno não se fecha a meio de uma emissão: o Z sairia sem "
    "essa venda e o dinheiro dela ficava na gaveta como sobra por "
    "justificar. Espere alguns segundos e feche outra vez. Se a conta ficar "
    "assim presa, é o gestor que a resolve primeiro, na lista de reservas "
    "fiscais presas do backoffice."
)
# **A OUTRA emissão fiscal viva desta caixa: uma nota de crédito a meio.**
# O mesmo estrago do de cima, ao contrário: a devolução sai da gaveta (ou do
# Multibanco) DEPOIS de o Z estar assinado, e a operadora fica a dever à
# gaveta um dinheiro que o Z nunca contou. A saída é a mesma — esperar uns
# segundos — porque uma nota de crédito reservada ou é emitida (e conta) ou
# rebenta (e a reserva desaparece), tudo dentro de uma chamada ao Vendus.
#
# **E a frase nomeia a saída, porque ela existe.** Uma intenção fica
# `reservada` para sempre se a rota morrer entre o `insert` e o `$set` final —
# um reinício, um deploy, o 409 da corrida do crédito. Sem a última frase, a
# loja lia «espere alguns segundos», esperava, e levava 409 outra vez, sem
# fim: medido, três tentativas seguidas de fecho, 409 sempre. Com UM PC por
# loja, isso é o turno que não fecha e ninguém com botão.
_MSG_FECHO_COM_NOTA_DE_CREDITO_EM_CURSO = (
    "Há uma NOTA DE CRÉDITO desta caixa em curso ou por confirmar — o turno "
    "não se fecha a meio de uma devolução: o Z sairia sem ela e o dinheiro "
    "devolvido ficava na gaveta como falta por justificar. Espere alguns "
    "segundos e feche outra vez. Se ela ficar assim presa, é o gestor que a "
    "resolve primeiro, no backoffice: Faturação → Reservas Fiscais Presas, no "
    "cartão «Notas de Crédito Presas»."
)
# O retrato das contas abertas não estabilizou (ver
# `_retrato_estavel_das_contas_abertas`). A caixa fica marcada `a_fechar` de
# propósito: é essa marca que impede escritas NOVAS, e é ela que faz a
# tentativa seguinte estabilizar. Não assinar em silêncio é o ponto todo —
# um Z que não descreve as contas como elas estão vale menos do que nenhum.
_MSG_FECHO_SEM_RETRATO_ESTAVEL = (
    "O turno NÃO foi fechado: as contas desta caixa continuaram a mudar "
    "enquanto o Z estava a ser calculado, e um Z que não diga o que ficou "
    "por cobrar não se assina. Nada se perdeu e nenhum Z saiu — a caixa "
    "ficou marcada como A FECHAR e, a partir daqui, já não aceita "
    "alterações às contas. Carregue outra vez em FECHAR CAIXA daqui a "
    "alguns segundos: o que estava a meio já terá acabado."
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sessao_publica(sessao: Optional[Dict]) -> Optional[Dict]:
    """A sessão como o ecrã da caixa a vê — sem `movimentos_confirmados`, que
    é escrituração interna do fecho (ver `registar_movimento`) e não diz nada
    à funcionária.

    Cópia, nunca um `pop` no dicionário recebido — e a razão certa, porque a
    que aqui estava era falsa: dizia que "nos duplos dos testes [o find_one]
    pode ser o próprio documento guardado", e os duplos deste repo devolvem
    cópia funda, como o Motor. Nem em produção nem nos testes um `pop` chega à
    colecção.

    O que se defende é o contrato desta função: é uma PROJECÇÃO e não pode
    mutilar o que lhe dão. Hoje os dois chamadores (`estado_caixa`) passam-lhe
    leituras acabadas de fazer e descartáveis, por isso um `pop` ainda não
    estragava nada; o próximo que lhe passe uma sessão que ainda vai usar
    perde-lhe a lista `movimentos_confirmados` — e é dessa lista que sai o Z
    (`fechar_caixa`), ou seja, dinheiro a cair fora do fecho por causa de uma
    função de LEITURA. `test_sessao_publica_nao_mexe_no_dicionario_que_recebe`
    mede isto na função, e não pela rota, precisamente porque pela rota o
    `pop` é invisível."""
    if sessao is None:
        return None
    return {c: v for c, v in sessao.items() if c != "movimentos_confirmados"}


def _recusa_mais_de_2_casas(v):
    """Mesmo crivo de precos.py, reutilizado e não reescrito: round(x, 2)
    sobre a representação binária come cêntimos sem avisar."""
    if _tem_mais_de_2_casas_decimais(v):
        raise ValueError(
            "O valor %s tem mais de 2 casas decimais — a caixa recusa-o "
            "para não perder um cêntimo no arredondamento." % v
        )
    return v


def _quem(operador: Dict) -> Dict:
    return {"id": operador.get("operador_id"), "nome": operador.get("nome")}


class PedidoAbrirCaixa(BaseModel):
    caixa_id: str = Field(min_length=1)
    fundo: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("fundo")
    @classmethod
    def _valida_fundo(cls, v):
        return _recusa_mais_de_2_casas(v)


class PedidoMovimento(BaseModel):
    # Deliberadamente SEM campo sessao_id — ver a docstring do módulo: a
    # sessão é sempre resolvida no servidor a partir da caixa + operador,
    # nunca de um valor que o corpo do pedido diga que é a sessão.
    caixa_id: str = Field(min_length=1)
    tipo: Literal["entrada", "saida"]
    valor: float = Field(gt=0, allow_inf_nan=False)
    motivo: Optional[str] = Field(default=None, max_length=200)

    @field_validator("valor")
    @classmethod
    def _valida_valor(cls, v):
        return _recusa_mais_de_2_casas(v)

    @model_validator(mode="after")
    def _valida_motivo_obrigatorio_em_saida(self):
        if self.tipo == "saida" and not (self.motivo and self.motivo.strip()):
            raise ValueError("O motivo é obrigatório numa saída de dinheiro.")
        return self


class PedidoFecharCaixa(BaseModel):
    # Também sem sessao_id — o fecho resolve a sessão aberta da mesma forma
    # que o movimento, pela mesma razão (ver docstring do módulo).
    caixa_id: str = Field(min_length=1)
    contado: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("contado")
    @classmethod
    def _valida_contado(cls, v):
        return _recusa_mais_de_2_casas(v)


async def _obter_caixa_da_loja(db, caixa_id: str, loja_id: str) -> Dict:
    """Confirma que a caixa existe E pertence à loja do operador autenticado
    — o âmbito nunca é só o id, para uma caixa de outra loja nunca poder ser
    usada, mesmo por acidente."""
    caixa = await db[COLECOES["caixas"]].find_one({"id": caixa_id})
    if not caixa or caixa.get("loja_id") != loja_id:
        raise HTTPException(status_code=404, detail=_MSG_CAIXA_INEXISTENTE)
    return caixa


async def _sessao_viva(db, caixa_id: str, projecao: Optional[Dict] = None) -> Optional[Dict]:
    """A sessão desta caixa que ainda espera um Z — a `aberta`, ou, se não
    houver, uma que tenha ficado em `a_fechar` (um fecho que morreu a meio,
    ver `fechar_caixa`). `None` quando a caixa está mesmo fechada.

    DUAS leituras exactas em vez de um `$in`, de propósito: um `$in` obriga
    todos os duplos de base de dados dos testes (aqui e no do núcleo fiscal,
    que também chama o fecho) a saber interpretar operadores de Mongo, e um
    duplo que os interpreta mal deixa passar defeitos com toda a suite verde.
    A igualdade exacta é o que eles já replicam fielmente.

    Ler duas vezes é seguro porque os estados só andam para a frente
    (`aberta` → `a_fechar` → `fechada`): a única sessão que as duas leituras
    podem falhar é uma que passou a `fechada` pelo meio — e essa, para quem
    pergunta, já não é uma sessão por fechar. A excepção é a marca desfeita
    (`a_fechar` → `aberta`, quando o fecho é recusado por uma emissão viva),
    e aí continua a valer o que a docstring do módulo diz desde o início:
    quem decide a corrida real da ABERTURA é o índice único parcial de
    db.py, não esta leitura."""
    colecao = db[COLECOES["sessoes_caixa"]]
    aberta = await colecao.find_one({"caixa_id": caixa_id, "estado": "aberta"}, projecao)
    if aberta is not None:
        return aberta
    return await colecao.find_one({"caixa_id": caixa_id, "estado": "a_fechar"}, projecao)


async def _sessao_aberta(db, caixa_id: str) -> Dict:
    """A resolução central do módulo: a ÚNICA sessão aberta desta caixa (o
    índice único parcial em db.py garante que nunca há mais do que uma).

    `estado: "aberta"` EXACTO, e é para continuar assim: quem chama isto é
    quem vai lançar dinheiro ou abrir contas (`registar_movimento`,
    `venda.py::abrir_venda`, `venda.py::venda_aberta`), e uma sessão a meio
    de um fecho (`a_fechar`) não pode aceitar nem uma coisa nem outra — o Z
    dela está a ser calculado neste instante. Só o FECHO aceita as duas (ver
    `_sessao_por_fechar`).

    A segunda leitura existe só para a MENSAGEM, e só no caminho do erro: sem
    ela, uma caixa que ficou em `a_fechar` (um fecho que morreu a meio)
    respondia "esta caixa não tem nenhuma sessão aberta" a tudo — verdade
    literal, e uma pista completamente errada para quem está ao balcão, que
    fica sem saber que basta carregar outra vez em FECHAR CAIXA."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one(
        {"caixa_id": caixa_id, "estado": "aberta"}
    )
    if not sessao:
        a_fechar = await db[COLECOES["sessoes_caixa"]].find_one(
            {"caixa_id": caixa_id, "estado": "a_fechar"}
        )
        if a_fechar is not None:
            raise HTTPException(status_code=409, detail=_MSG_SESSAO_A_MEIO_DE_UM_FECHO)
        raise HTTPException(status_code=409, detail=_MSG_SEM_SESSAO_ABERTA)
    return sessao


async def _sessao_por_fechar(db, caixa_id: str) -> Dict:
    """A sessão que o FECHO aceita: `aberta`, ou `a_fechar` quando é a retoma
    de um fecho que morreu a meio.

    É esta diferença que torna o estado intermédio SEGURO. Se o
    `fechar_caixa` só aceitasse `aberta`, um processo que morresse entre a
    marca e a escrita final deixava a caixa num beco sem saída: não fechava
    (não há sessão `aberta`) e não abria (`abrir_caixa` recusa — e ainda bem,
    a sessão antiga tem vendas por meter num Z). Aceitando as duas, o remédio
    é o gesto óbvio: carregar outra vez em FECHAR CAIXA. Nada se perde, porque
    as somas do Z são todas recalculadas do zero em cada tentativa — nunca se
    reaproveita nenhum número de uma tentativa anterior."""
    sessao = await _sessao_viva(db, caixa_id)
    if not sessao:
        raise HTTPException(status_code=409, detail=_MSG_SEM_SESSAO_ABERTA)
    return sessao


@router.get("/pos/caixa/estado")
async def estado_caixa(
    caixa_id: Optional[str] = None, operador: Dict = Depends(operador_atual)
) -> dict:
    """O que o ecrã de entrada na "app" precisa para decidir o que mostrar:
    a lista de caixas activas da loja do operador, qual delas está resolvida
    (auto-escolhida quando só há uma; a pedido, via `caixa_id`, quando há
    mais do que uma — a mesma ambiguidade que o PC guarda depois em
    localStorage, spec §7.1), se tem sessão aberta, e — quando não tem — o
    resumo do último fecho (quem, quando, com quanto), para o ecrã "Caixa
    Fechada" (Task 2).

    Só leitura: nunca abre, fecha nem escreve nada. Sem `caixa_id` e com
    mais do que uma caixa activa, devolve a lista e `caixa: None` — o
    frontend pergunta qual, nunca escolhe pela funcionária (o mesmo
    raciocínio do PIN em conflito: escolher a primeira seria escolher
    errado)."""
    db = obter_db()
    loja_id = operador["loja_id"]
    caixas = (
        await db[COLECOES["caixas"]]
        .find({"loja_id": loja_id, "ativa": True}, {"_id": 0})
        .sort("nome", 1)
        .to_list(100)
    )
    if not caixas:
        raise HTTPException(status_code=404, detail=_MSG_SEM_CAIXA_CONFIGURADA)

    caixa = None
    if caixa_id:
        caixa = next((c for c in caixas if c["id"] == caixa_id), None)
        if not caixa:
            raise HTTPException(status_code=404, detail=_MSG_CAIXA_INEXISTENTE)
    elif len(caixas) == 1:
        caixa = caixas[0]

    if not caixa:
        return {"caixas": caixas, "caixa": None, "sessao_aberta": None, "ultimo_fecho": None}

    # `_sessao_viva`, e não só a `aberta`: uma sessão que ficou a meio de um
    # fecho (o processo morreu entre a marca e a escrita final) TEM de
    # continuar a aparecer aqui como sessão por fechar. Se desaparecesse, o
    # ecrã do POS mostrava "Caixa Fechada" com o resumo do fecho ANTERIOR — a
    # funcionária só teria à frente o botão de ABRIR (que é recusado, e bem) e
    # nenhuma forma de chegar ao único botão que resolve isto, que é o FECHAR.
    # O `estado` vai dentro da própria sessão, para o ecrã o poder distinguir
    # quando quiser.
    sessao = await _sessao_viva(db, caixa["id"], {"_id": 0})
    ultimo_fecho = None
    if not sessao:
        anteriores = await (
            db[COLECOES["sessoes_caixa"]]
            .find({"caixa_id": caixa["id"], "estado": "fechada"}, {"_id": 0})
            .sort("fechada_em", -1)
            .to_list(1)
        )
        ultimo_fecho = anteriores[0] if anteriores else None

    return {
        "caixas": caixas, "caixa": caixa,
        "sessao_aberta": _sessao_publica(sessao),
        "ultimo_fecho": _sessao_publica(ultimo_fecho),
    }


@router.post("/pos/caixa/abrir", status_code=201)
async def abrir_caixa(dados: PedidoAbrirCaixa, operador: Dict = Depends(operador_atual)) -> dict:
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])

    # As DUAS, não só a `aberta`: o índice único parcial de db.py só cobre
    # `estado: "aberta"`, por isso uma sessão em `a_fechar` (fecho
    # interrompido) não colide com nada e deixava abrir uma sessão nova por
    # cima dela. Ficavam duas sessões vivas na mesma caixa: a nova a receber
    # as vendas e a velha para sempre sem Z, com as vendas dela a não entrar
    # em fecho nenhum — exactamente o estrago que este módulo inteiro existe
    # para evitar, só que por outra porta.
    viva = await _sessao_viva(db, dados.caixa_id)
    if viva:
        if viva.get("estado") == "a_fechar":
            raise HTTPException(status_code=409, detail=_MSG_SESSAO_A_MEIO_DE_UM_FECHO)
        raise HTTPException(status_code=409, detail=_MSG_CAIXA_JA_ABERTA)

    sessao = {
        "id": str(uuid.uuid4()),
        "caixa_id": dados.caixa_id,
        "loja_id": operador["loja_id"],
        "aberta_por": _quem(operador),
        "aberta_em": _agora(),
        "fundo": dados.fundo,
        "estado": "aberta",
        "fechada_por": None,
        "fechada_em": None,
        "contado": None,
        "esperado": None,
        "diferenca": None,
        # Sempre presente, mesmo a None (mesma regra dos campos de fecho
        # acima): quem lê uma sessão não pode ter de adivinhar se a ausência
        # da chave quer dizer "nenhum fecho começou" ou "versão antiga".
        "fecho_iniciado_em": None,
    }
    await db[COLECOES["sessoes_caixa"]].insert_one(dict(sessao))
    return sessao


async def _porque_o_movimento_nao_entrou(db, sessao_id: str) -> str:
    """A mensagem do 409 de `registar_movimento` — escolhida pelo estado que a
    SESSÃO tem NO MOMENTO EM QUE A MENSAGEM É ENVIADA, e não pelo pior caso.

    A confirmação do movimento exige `{"estado": "aberta"}`, e uma das razões
    por que isso falha é a marca `a_fechar` — que pode ainda ser DESFEITA: o
    fecho põe a marca ANTES de perguntar pela emissão viva e volta a `aberta`
    quando encontra uma (ver `fechar_caixa`). Nessa janela, a mensagem única
    de antes dizia à operadora três coisas falsas ao mesmo tempo — que a
    sessão "foi fechada", que há uma "sessão nova", e implicitamente que um Z
    foi assinado — e mandava-a fazer a única coisa errada: ir registar o
    movimento noutro lado. A caixa acaba a noite `aberta`, na mesma sessão,
    sem Z nenhum.

    É a mesma invariante das duas mensagens do cancelamento
    (`venda.py::_porque_nao_foi_cancelada`) e das duas da emissão
    (`fiscal.py::SessaoEmFechoAgora`), e o mesmo padrão: dizer à operadora que
    o turno acabou só pode acontecer se o turno tiver MESMO acabado.

    As três saídas, todas verdadeiras no instante em que se lêem:
    1. `fechada` — o Z está assinado e esta sessão acabou: o movimento
       repete-se na sessão nova (`_MSG_SESSAO_FECHADA_ENTRETANTO`);
    2. `a_fechar` — o Z está a ser calculado NESTE momento; é uma espera de
       segundos e o fecho ainda pode ser recusado e desfeito
       (`_MSG_MOVIMENTO_COM_FECHO_A_DECORRER`);
    3. `aberta` — o fecho que recusou este movimento foi ele próprio desfeito:
       a caixa é a MESMA e continua aberta
       (`_MSG_MOVIMENTO_NA_MESMA_SESSAO_OUTRA_VEZ`).

    Estado inesperado (a sessão desapareceu, ou está num estado que este
    módulo não escreve): não se inventa um diagnóstico — vale a mensagem que
    não afirma nada sobre a caixa e manda olhar para o ecrã.

    Uma leitura a mais, e só no caminho do erro: o caminho normal do
    movimento não passa por aqui."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": sessao_id})
    estado = (sessao or {}).get("estado")
    if estado == "fechada":
        return _MSG_SESSAO_FECHADA_ENTRETANTO
    if estado == "a_fechar":
        return _MSG_MOVIMENTO_COM_FECHO_A_DECORRER
    if estado == "aberta":
        return _MSG_MOVIMENTO_NA_MESMA_SESSAO_OUTRA_VEZ
    return _MSG_MOVIMENTO_NAO_REGISTADO


@router.post("/pos/caixa/movimento", status_code=201)
async def registar_movimento(
    dados: PedidoMovimento, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    movimento = {
        "id": str(uuid.uuid4()),
        "sessao_id": sessao["id"],
        "tipo": dados.tipo,
        "valor": dados.valor,
        "motivo": dados.motivo,
        "por": _quem(operador),
        "em": _agora(),
    }

    # A ORDEM DESTAS DUAS ESCRITAS É O PONTO TODO (o defeito da sexta
    # revisão). Antes era: confirmar a sessão (escrita condicional, o
    # `matched_count` a decidir — a defesa I2) e SÓ DEPOIS inserir o
    # movimento. A confirmação é uma FOTOGRAFIA: prova que a sessão estava
    # aberta naquele instante. O dinheiro, porém, só entra no sistema no
    # `insert_one` seguinte — noutra colecção, e sem condição nenhuma — e
    # entre as duas cabia um fecho inteiro, porque o fecho lê
    # `fat_movimentos_caixa` DEPOIS da marca `a_fechar` e escreve o Z a
    # seguir. A marca congela as VENDAS (o núcleo fiscal recusa emitir com a
    # sessão em `a_fechar`) e não congelava os movimentos. Medido, sobre as
    # rotas reais: a Rafaela tira 20,00 € para o fornecedor do gelo e regista
    # a saída; a Ana conta a gaveta e fecha — «Z assinado: fundo=50.00
    # saidas=0.00 esperado=50.00 contado=30.00 diferenca=-20.00» — e só
    # depois «o movimento gravou-se AGORA: 201», numa sessão já `fechada`. A
    # funcionária assina um Z que acusa uma falta de 20,00 € numa gaveta que
    # está certa, e os 20 € não entram em Z nenhum: nem neste (assinado) nem
    # no seguinte (que filtra pelo sessao_id da sessão nova).
    #
    # A correcção: o movimento entra PRIMEIRO, marcado `por_confirmar`, e a
    # escrita que o torna dinheiro é a MESMA que confirma a sessão — um só
    # `update_one` condicionado a `{"estado": "aberta"}` que empurra o `id`
    # deste movimento para a lista da sessão. Uma escrita só, num documento
    # só, é o que se pode ter sem transacções multi-documento; e é o MESMO
    # documento em que o fecho põe a marca `a_fechar`, por isso as duas
    # serializam e uma delas vê sempre a outra:
    #   - se esta chegar primeiro, o `id` está na lista antes da marca, e o
    #     fecho lê a lista DEPOIS da marca -> o movimento entra no Z;
    #   - se a marca chegar primeiro, esta condição falha -> o movimento é
    #     RECUSADO e a linha que se inseriu acima é apagada. Nada fica.
    # Não há terceira ordem. O `insert_one` deixa de ser a escrita que decide
    # (é só o registo), e por isso já não importa que não seja condicional.
    await db[COLECOES["movimentos_caixa"]].insert_one(
        dict(movimento, por_confirmar=True)
    )

    confirmacao = await db[COLECOES["sessoes_caixa"]].update_one(
        {"id": sessao["id"], "estado": "aberta"},
        {
            "$set": {"estado": "aberta"},
            "$push": {"movimentos_confirmados": movimento["id"]},
        },
    )
    if confirmacao.matched_count == 0:
        # A linha inserida acima nunca chegou a ser dinheiro (o `id` não
        # entrou na lista de nenhuma sessão, logo nenhum Z a conta). Apaga-se
        # para não ficar lixo na colecção; e mesmo que este apagar falhe, ela
        # continua marcada `por_confirmar` e fora de qualquer soma.
        await db[COLECOES["movimentos_caixa"]].delete_one({"id": movimento["id"]})
        # A mensagem escolhe-se AGORA, com a sessão relida — depois da
        # limpeza e o mais perto possível do instante em que a operadora a
        # lê. Ver `_porque_o_movimento_nao_entrou`.
        raise HTTPException(
            status_code=409,
            detail=await _porque_o_movimento_nao_entrou(db, sessao["id"]),
        )

    # A marca sai da linha AGORA que ela já está na lista da sessão. É uma
    # conveniência (quem olhar para a colecção sozinha distingue uma linha
    # boa de uma que ficou a meio), nunca a garantia — a garantia é a lista.
    # Por isso vai em try/except, pelo mesmo motivo do carimbo da reserva em
    # `fiscal.py::_ligar_venda_ao_documento`: um movimento que JÁ está
    # confirmado não pode virar um 500 no ecrã do balcão — isso mandava a
    # funcionária registá-lo outra vez e o Z contava-o a dobrar.
    try:
        await db[COLECOES["movimentos_caixa"]].update_one(
            {"id": movimento["id"]}, {"$set": {"por_confirmar": False}}
        )
    except Exception as e:  # noqa: BLE001 — marca de conveniência, nunca a garantia
        logger.warning(
            "[faturacao] movimento %s confirmado na sessão %s mas a marca "
            "`por_confirmar` não saiu: %s (o Z conta-o à mesma — quem manda "
            "é a lista da sessão).", movimento["id"], sessao["id"], e,
        )
    return movimento


async def _movimentos_que_contam(db, sessao: Dict) -> list:
    """As entradas e saídas de uma sessão que contam mesmo para a gaveta.

    Conta o movimento que está na lista `movimentos_confirmados` da SESSÃO
    OU o que foi escrito ANTES dessa lista existir (esses não têm
    `por_confirmar` nenhum e nunca entraram em lista nenhuma — uma sessão
    aberta no turno do deploy não pode ver os seus movimentos desaparecer do
    Z). Fica de fora só o que ficou a meio: inserido, `por_confirmar: True`,
    e nunca confirmado em sessão nenhuma — dinheiro que ninguém tirou da
    gaveta, porque quem o pediu levou 409 ou nem chegou a receber resposta.

    **Uma função e não duas.** O Z (`fechar_caixa`) e o Ponto de Caixa
    (`ponto_de_caixa`, a conferência a meio do turno) fazem esta mesma
    leitura, e um filtro copiado nos dois sítios era uma diferença à espera
    de acontecer: a operadora confere a gaveta às 15h com um número e às 23h
    o Z dá-lhe outro, sem nada no meio que o explique.

    Quem passa a `sessao` decide de que retrato dela se lê a lista: o fecho
    passa a sessão RELIDA depois da marca `a_fechar` (a fronteira exacta do
    turno), o Ponto de Caixa passa a que tem em mão — a meio do turno não há
    fronteira nenhuma a respeitar, e o número que ele dá vale para o
    instante em que foi pedido."""
    confirmados = set(sessao.get("movimentos_confirmados") or [])
    movimentos = await db[COLECOES["movimentos_caixa"]].find(
        {"sessao_id": sessao["id"]}
    ).to_list(10000)
    return [
        m for m in movimentos
        if m.get("id") in confirmados or m.get("por_confirmar") is not True
    ]


def _resumo_do_turno(
    sessao: Dict, movimentos: list, vendas: list, notas_credito: list = None
) -> Dict:
    """Os números de um turno — os mesmos para o Ponto de Caixa e para o Z.

    **As notas de crédito do turno entram como o que são: dinheiro que saiu.**
    Não há aqui um total de devoluções nem uma coluna nova — elas atravessam
    as MESMAS duas funções por onde as vendas passam (`mapa_de_imposto` e
    `por_tipo_de_pagamento`), com o sinal ao contrário. É isso que faz a
    devolução em dinheiro baixar o `esperado` da gaveta e a devolução no
    Glovo não lhe tocar, sem uma segunda contabilidade a explicar a mesma
    gaveta.

    Recebe o que já foi lido da base de dados e não lê nada: é aritmética
    pura sobre listas, e é a ÚNICA que os dois ecrãs usam. O Ponto de Caixa
    é literalmente o Z sem o fecho — o mesmo `esperado`, os mesmos
    movimentos, o mesmo desdobramento por tipo de pagamento e o mesmo mapa
    de imposto — e a única forma de isso continuar verdade daqui a um ano é
    não haver dois sítios onde estas somas se fazem.

    `total_faturado` é a soma da tabela do imposto, e não das vendas outra
    vez: o número que aparece por baixo de uma tabela tem de ser a soma da
    tabela que está por cima dele.

    O import de `mapa_imposto` é LOCAL pela mesma razão que o de `fiscal.py`
    em `_verificar_vendas_dinheiro`, mais abaixo: o mapa de imposto lê as
    linhas do documento por `fiscal._itens_vendus`, e `fiscal.py` importa de
    `venda.py`, que importa deste módulo — um import no topo do ficheiro
    fechava o ciclo `caixa → mapa_imposto → fiscal → venda → caixa`."""
    from .mapa_imposto import mapa_de_imposto, totais_do_mapa

    mapa = mapa_de_imposto(vendas, notas_credito)
    totais = totais_do_mapa(mapa)
    vendas_dinheiro = soma_vendas_dinheiro(vendas, notas_credito)
    pagamentos = por_tipo_de_pagamento(vendas, notas_credito)
    # **O que foi FACTURADO e não tem pagamento nenhum por baixo.** Em
    # cêntimos inteiros e do lado do servidor, como tudo o resto.
    #
    # Medido no ecrã: uma venda emitida SEM `pagamentos` (um documento gravado
    # por uma versão anterior, uma reconciliação que trouxe o documento do
    # Vendus sem os pagamentos) não entra em linha nenhuma de
    # `por_tipo_de_pagamento` — a coluna somava 10,20 € debaixo de um "Total
    # cobrado 11,35 €". 1,15 € desaparecidos sem uma palavra, e o ecrã não
    # pode somar a coluna para dar por isso (a aritmética de dinheiro é do
    # servidor). Com esta linha a coluna volta a somar o rodapé, e o que falta
    # tem nome.
    por_registar = round(
        (_centimos(totais["total"])
         - sum(_centimos(linha["total"]) for linha in pagamentos)) / 100.0, 2)
    esperado_do_turno = esperado(sessao.get("fundo"), vendas_dinheiro, movimentos)
    return {
        "fundo": sessao.get("fundo"),
        "vendas_dinheiro": vendas_dinheiro,
        "entradas": total_por_tipo(movimentos, "entrada"),
        "saidas": total_por_tipo(movimentos, "saida"),
        "esperado": esperado_do_turno,
        # **O QUE SAIU DA GAVETA A MAIS, e o porquê ao lado.** Um turno só
        # pode tirar da gaveta o que lá pôs, e isso lê-se nas VENDAS EM
        # DINHEIRO — não no `esperado`. Medido: fatura de 24,14 € paga 5,00 em
        # dinheiro + 19,14 em Multibanco, açaí de 20,40 € devolvido em
        # DINHEIRO → `vendas_dinheiro` −15,40 €. A operadora conta a gaveta,
        # bate certo — e saíram 15,40 € que aquele turno não recebeu.
        #
        # **Contra o `esperado` isto falhava nos dois sentidos**, e os dois
        # foram medidos aqui: um reforço de troco de 20,00 € apagava o aviso
        # (esperado 54,60 €, aviso 0,00 — o vazamento intacto), e uma sangria
        # de 30,00 € para o cofre acendia-o sem devolução nenhuma (esperado
        # 44,14 €, aviso 5,86 €). Os movimentos de caixa são rotina e têm rota
        # própria; as vendas em dinheiro nenhum deles consegue mexer.
        #
        # Os dois SEMPRE presentes, mesmo a zero, pela regra do
        # `pagamentos_por_registar` aqui em baixo.
        "tirado_da_gaveta_a_mais": tirado_da_gaveta_a_mais(vendas_dinheiro),
        # E o LEITOR de `nota_credito.devolucao.acima_do_recebido`, que até
        # aqui era um campo só de escrita: é ele que transforma «faltam
        # 15,40 €» em «devolveram-se 15,40 € por um meio que estas faturas não
        # receberam». **Pergunta PRÓPRIA**, e não um adorno do de cima: um
        # turno pode ter a gaveta bem e ainda assim ter devolvido por um meio
        # que a fatura não recebeu (ver `caixa_math`).
        "devolucoes_acima_do_recebido": devolucoes_acima_do_recebido(notas_credito),
        # O desdobramento que o Z não tinha: quanto entrou em dinheiro, em
        # multibanco, no Uber Eats, no Bolt, no Glovo. Sem ele ninguém
        # conseguia bater o rolo do terminal de Multibanco nem o extracto do
        # Glovo contra o turno, e o gestor fechava o mês a somar à mão.
        "pagamentos": pagamentos,
        # SEMPRE presente, mesmo a 0.0 — a mesma regra do
        # `emissao_por_confirmar` de `venda.py`: quem desenha não pode ter de
        # adivinhar se a ausência quer dizer "está tudo cobrado" ou "esta
        # versão do servidor não sabe responder a isso".
        "pagamentos_por_registar": por_registar,
        "mapa_imposto": mapa,
        # A última linha da tabela do imposto, do lado do servidor: o ecrã
        # não soma colunas (regra da casa — a aritmética de dinheiro é do
        # servidor, e um total recalculado no browser é uma segunda verdade).
        "base_tributavel": totais["base"],
        "iva_total": totais["iva"],
        "total_faturado": totais["total"],
        # Documentos FISCAIS do turno, e uma nota de crédito é um deles — é o
        # que o Vendus conta e o que a contabilista reconcilia. Contá-la
        # deixava-a de fora do único número do Z que diz quantos papéis saíram.
        "quantos_documentos": (
            sum(1 for v in vendas if v.get("estado") == "emitida")
            + sum(1 for n in notas_credito or [] if n.get("estado") == "emitida")
        ),
    }


async def _nota_de_credito_em_curso(db, sessao: Dict) -> Optional[Dict]:
    """A primeira nota de crédito desta sessão que RESERVOU e ainda não se
    sabe se saiu — ou `None`, o caso normal.

    É o gémeo de `_venda_com_emissao_viva`, e existe pelo mesmo par
    (marcar, depois perguntar) que fecha a janela do fecho: a rota da nota de
    crédito grava a intenção ANTES de falar com o Vendus e só depois relê a
    sessão, exigindo-a `aberta` (`nota_credito.emitir_nota_credito`). Para
    qualquer ordem possível, uma das duas partes vê sempre a outra — a
    intenção nasce antes da marca e é apanhada aqui, ou nasce depois e é a
    releitura da sessão que a manda abortar sem emitir.

    `estado: "reservada"` e mais nada: uma nota `emitida` já entrou no resumo
    do turno (é isso que o Z tem de dizer) e uma `incerta` ficou por apurar —
    essa não trava o fecho, porque não há nada a esperar dela: ninguém sabe se
    o documento saiu, e prender a caixa de uma loja até alguém ir ao Vendus era
    a regra 3 do dono ao contrário."""
    return await db[COLECOES["notas_credito"]].find_one(
        {"sessao_id": sessao["id"], "estado": "reservada"}, {"_id": 0}
    )


async def _notas_de_credito_do_turno(db, sessao: Dict) -> list:
    """As notas de crédito EMITIDAS nesta sessão de caixa.

    A sessão é a do turno em que a devolução aconteceu, e não a da fatura de
    origem: o cliente que volta amanhã é creditado no turno de amanhã, e é da
    gaveta de amanhã que sai o dinheiro. É por isso que
    `nota_credito.emitir_nota_credito` grava o `sessao_id` da sessão ABERTA no
    momento da devolução.

    Uma função e não duas leituras copiadas, pela razão de
    `_movimentos_que_contam` aqui em cima: o Ponto de Caixa e o Z têm de ver
    exactamente o mesmo conjunto, ou a operadora confere a gaveta às 15h com
    um número e às 23h o Z dá-lhe outro."""
    return await db[COLECOES["notas_credito"]].find(
        {"sessao_id": sessao["id"], "estado": "emitida"}
    ).to_list(10000)


@router.get("/pos/caixa/ponto")
async def ponto_de_caixa(
    caixa_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """O Ponto de Caixa: a conferência a meio do turno, **sem fechar nada**.

    A operadora quer saber se a gaveta bate certo às 15h, em vez de
    descobrir às 23h que houve um erro de troco que já não consegue
    reconstituir. E serve a rendição de turno — uma sai, outra entra, sem
    fechar a caixa.

    **Não fecha, não assina, não muda nada.** É um GET e não escreve uma
    única vez: nem marca `a_fechar` (que travaria as emissões durante a
    conferência), nem carimba a sessão, nem toca nos movimentos. Pode ser
    pedido as vezes que forem precisas, dos dois PCs do mesmo balcão, e no
    meio de uma venda.

    Devolve o MESMO que o Z devolve (`_resumo_do_turno`), menos o que só o
    fecho tem: o contado e a diferença. O `esperado` é o mesmo número, pela
    mesma função — é essa a razão de este ecrã existir."""
    db = obter_db()
    # `caixa_id` é OBRIGATÓRIO aqui, ao contrário do `estado_caixa` (que o
    # aceita ausente para o ecrã de entrada poder perguntar qual é a caixa
    # quando a loja tem mais do que uma). Quem chega ao Ponto de Caixa já
    # está dentro da app, com uma sessão aberta e uma caixa escolhida — não
    # há ambiguidade nenhuma para resolver, e adivinhá-la seria a mesma
    # escolha errada que o ecrã de entrada existe para não fazer.
    caixa = await _obter_caixa_da_loja(db, caixa_id, operador["loja_id"])
    sessao = await _sessao_viva(db, caixa["id"], {"_id": 0})
    if not sessao:
        raise HTTPException(status_code=409, detail=_MSG_SEM_SESSAO_ABERTA)

    movimentos = await _movimentos_que_contam(db, sessao)
    vendas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao["id"], "estado": "emitida"}
    ).to_list(10000)
    notas_credito = await _notas_de_credito_do_turno(db, sessao)

    resumo = _resumo_do_turno(sessao, movimentos, vendas, notas_credito)
    resumo.update({
        "caixa": {"id": caixa["id"], "nome": caixa.get("nome")},
        "sessao": _sessao_publica(sessao),
        # O instante da conferência. Um Ponto de Caixa é uma fotografia de um
        # momento e a folha continua na bancada depois de a venda seguinte
        # entrar — sem a hora impressa nela, meia hora depois ninguém sabe se
        # o número ainda vale.
        "momento": _agora(),
        "operador": _quem(operador),
    })
    return resumo


@router.post("/pos/caixa/fechar")
async def fechar_caixa(
    dados: PedidoFecharCaixa, operador: Dict = Depends(operador_atual)
) -> dict:
    """Fecha a sessão aberta da caixa e devolve o relatório Z.

    Regra 3 do dono (vem de um erro já cometido noutro projecto): o fecho
    NUNCA bloqueia por a contagem não bater — regista a diferença e segue
    em frente, para a funcionária poder ir para casa. O esperado calcula-se
    sempre das NOSSAS vendas (regra 1), nunca do Vendus — a verificação
    contra o Vendus (Plano 2B, Task 4) é só uma segunda opinião de leitura,
    nunca a fonte de verdade, e nunca pode bloquear o fecho.

    A ÚNICA coisa que bloqueia o fecho é uma emissão fiscal viva numa venda
    desta sessão (ver `_venda_com_emissao_viva`) — e isso não contradiz a
    regra 3: a regra 3 é sobre a contagem não bater, e aqui o problema é
    outro, é fechar as contas antes de o dinheiro estar contado.

    **A JANELA (o defeito que esta rota tinha, e a forma da correcção).**
    A pergunta pela emissão viva e a leitura das vendas eram feitas logo no
    princípio, mas o `estado: "fechada"` só era escrito no FIM — e entre as
    duas coisas corria a verificação contra o Vendus, que é I/O de REDE (um
    GET por cada dia da janela, 30 s de tempo limite e até 3 tentativas com
    esperas). Um FINALIZAR que caísse nessa janela relia a sessão, via-a
    **ainda aberta — porque ela estava mesmo** — e emitia. Reproduzido, com
    as rotas reais: `vendas_dinheiro=0,00 esperado=50,00 contado=58,99
    diferenca=+8,99`, uma FS REAL de 8,99 € entregue à AT, e a venda
    `emitida` numa sessão `fechada`. A Ana assina um Z que não tem a venda,
    os 8,99 € ficam na gaveta como sobra por justificar, e a venda não entra
    em Z nenhum — nem neste (já assinado) nem no seguinte (que filtra pelo
    `sessao_id` da sessão nova). As duas defesas existiam; era a janela entre
    elas que estava aberta.

    **Porque é que "perguntar outra vez mesmo antes de escrever" NÃO chega.**
    Essa é a correcção óbvia e é a errada, por uma questão de ordem: a
    emissão cria a reserva e só DEPOIS relê a sessão. Uma reserva que nasça
    entre a última pergunta do fecho e a escrita do `fechada` não é vista
    pelo fecho (a pergunta já passou) e não vê o fecho (a escrita ainda não
    aconteceu) — a janela fica mais estreita e continua lá. É um problema de
    exclusão mútua, não de mais uma verificação.

    **A correcção: MARCAR primeiro, perguntar depois.** O fecho escreve
    `estado: "a_fechar"` (atomicamente, condicionado ao estado que leu) ANTES
    de perguntar pela emissão viva. A partir dessa marca, o núcleo fiscal
    recusa-se sozinho a emitir — `fiscal.py::_garante_venda_ainda_aberta`
    exige `estado == "aberta"` na sessão DA VENDA depois de ganhar a reserva,
    e qualquer coisa diferente de `aberta` faz libertar a reserva e abortar
    sem falar com o Vendus. Assim, para qualquer ordem possível, uma das duas
    partes vê sempre a outra:
      - a reserva nasce ANTES da marca → a pergunta que vem a seguir à marca
        encontra-a, e o fecho desfaz-se (volta a `aberta`) e recusa;
      - a reserva nasce DEPOIS da marca → a releitura da sessão que a emissão
        faz a seguir encontra `a_fechar` e aborta sem emitir.
    Não há terceira ordem: uma escrita e uma leitura sobre o MESMO documento
    não podem passar uma pela outra sem que pelo menos uma veja a outra.

    A pergunta pela emissão viva continua a ser feita também ANTES da marca,
    e não é redundante: é ela que trata o caso normal (uma emissão a decorrer
    mesmo, sem corrida nenhuma) sem chegar a mexer na sessão — sem isso, uma
    marca posta e desfeita durante uma emissão legítima fazia-a abortar por
    nada, e o cliente ficava com a fatura por sair.

    **A verificação contra o Vendus passou para DEPOIS do fecho estar
    escrito.** É só uma segunda opinião de leitura e nada no Z depende dela;
    tê-la no meio era o que dava à janela os seus 30 a 90 segundos de
    largura. Feita depois, a marca `a_fechar` dura o que duram três escritas
    locais (milissegundos), e é esse o tempo — e só esse — em que uma emissão
    concorrente pode ser recusada por causa de um fecho a decorrer.
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_por_fechar(db, dados.caixa_id)

    # ANTES de mexer na sessão: uma emissão a decorrer numa conta desta
    # sessão ainda vai mudar o que o Z tem de dizer. Aqui recusa-se sem
    # escrever NADA — a caixa fica exactamente como estava, e a emissão que
    # está a decorrer não é perturbada por uma marca posta e desfeita.
    em_emissao = await _venda_com_emissao_viva(db, sessao)
    if em_emissao is not None:
        raise HTTPException(
            status_code=409,
            detail=_MSG_FECHO_COM_EMISSAO_EM_CURSO % em_emissao.get("id"),
        )
    if await _nota_de_credito_em_curso(db, sessao) is not None:
        raise HTTPException(
            status_code=409, detail=_MSG_FECHO_COM_NOTA_DE_CREDITO_EM_CURSO
        )

    # A MARCA. Condicionada ao estado que acabámos de ler (`aberta` no caso
    # normal, `a_fechar` quando isto é a retoma de um fecho que morreu a
    # meio): dois fechos em paralelo, só um passa daqui, e é o
    # `matched_count` que o decide — como no resto do módulo.
    marca = await db[COLECOES["sessoes_caixa"]].update_one(
        {"id": sessao["id"], "estado": sessao["estado"]},
        {"$set": {"estado": "a_fechar", "fecho_iniciado_em": _agora()}},
    )
    if marca.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_FECHO_JA_EM_CURSO)

    # A MESMA pergunta, agora do outro lado da marca — é este par
    # (marcar, depois perguntar) que fecha a janela, e não a pergunta
    # sozinha. Uma emissão que tenha ganho a reserva mesmo antes da marca é
    # apanhada aqui; e a partir da marca nenhuma outra consegue emitir.
    em_emissao = await _venda_com_emissao_viva(db, sessao)
    nota_em_curso = (
        None if em_emissao is not None
        else await _nota_de_credito_em_curso(db, sessao)
    )
    if em_emissao is not None or nota_em_curso is not None:
        # Desfaz a marca — condicionada a `a_fechar`, para nunca reabrir uma
        # sessão que outro pedido já tenha fechado entretanto. A caixa fica
        # como estava e a funcionária tenta outra vez daqui a uns segundos.
        await db[COLECOES["sessoes_caixa"]].update_one(
            {"id": sessao["id"], "estado": "a_fechar"},
            {"$set": {"estado": "aberta", "fecho_iniciado_em": None}},
        )
        raise HTTPException(
            status_code=409,
            detail=(
                _MSG_FECHO_COM_EMISSAO_EM_CURSO % em_emissao.get("id")
                if em_emissao is not None
                else _MSG_FECHO_COM_NOTA_DE_CREDITO_EM_CURSO
            ),
        )

    # As somas, DEPOIS da marca: a partir daqui nenhuma venda desta sessão
    # pode passar a `emitida` (o núcleo fiscal recusa) e nenhum movimento novo
    # se pode confirmar (a confirmação exige `estado: "aberta"`, ver
    # `registar_movimento`), por isso o que se lê aqui é definitivo. Lidas de
    # fresco em cada tentativa de fecho — uma retoma de um fecho interrompido
    # recalcula tudo do zero, nunca reaproveita números de uma tentativa
    # anterior.
    #
    # A SESSÃO RELÊ-SE, e é depois da marca de propósito: `movimentos_
    # confirmados` é a lista que a confirmação de cada movimento empurra na
    # MESMA escrita em que verifica que a sessão está aberta. Lida do
    # documento que já leva a marca `a_fechar`, ela é a fronteira exacta do
    # turno: tudo o que entrou antes está lá, e nada mais pode entrar.
    # Ler a lista do `sessao` de cima (lido ANTES da marca) perdia um
    # movimento confirmado nesse intervalo.
    sessao_marcada = await db[COLECOES["sessoes_caixa"]].find_one({"id": sessao["id"]})
    movimentos = await _movimentos_que_contam(db, sessao_marcada or sessao)
    vendas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao["id"], "estado": "emitida"}
    ).to_list(10000)

    # O que NÃO virou fatura nenhuma neste turno. Lido depois da marca, como
    # tudo o resto aqui, e por isso definitivo — mas o "por isso" custou uma
    # ronda a ficar verdadeiro, e a lista das razões escreve-se por extenso
    # de propósito. Até esta ronda dizia-se aqui que "a partir da marca
    # nenhuma conta nova pode nascer nesta sessão, porque `abrir_venda`
    # resolve a sessão por `_sessao_aberta`". Só o `abrir_venda` é que passava
    # por lá: medido pelas rotas reais, com a sessão em `a_fechar` o
    # `POST /pos/venda/{id}/dividir` passava e nasciam 3 contas `aberta`
    # nesta sessão, e com a sessão já `fechada` o mesmo `dividir` e o
    # `POST /pos/venda/{id}/linhas` passavam outra vez — a conta subia de
    # 14,10 € para 21,15 € debaixo de um Z assinado. O que torna esta leitura
    # definitiva são as TRÊS guardas, e não uma:
    #   - nenhuma conta nova nasce nesta sessão — `venda.py::abrir_venda`
    #     resolve a sessão por `_sessao_aberta`, que só aceita `aberta`;
    #   - nenhuma conta desta sessão muda de valor nem se reparte — as seis
    #     rotas de escrita de `venda.py` (linhas, desconto, dividir, separar)
    #     confirmam a sessão DESTA venda
    #     (`venda.py::_garante_sessao_desta_venda_aberta`);
    #   - nenhuma das abertas passa a `emitida` — o núcleo fiscal recusa
    #     (`fiscal.py::_garante_sessao_da_venda_aberta`).
    # A sétima rota de escrita, o `cancelar_venda`, passa de propósito: não
    # muda o valor de conta nenhuma e é a única forma de arrumar uma conta que
    # ninguém pagou (ver a docstring dela).
    #
    # **E as três guardas continuam a não ser exclusão mútua** — foi o que
    # esta ronda mediu. Elas PERGUNTAM pela sessão e não a prendem: uma rota
    # que passe a pergunta um instante antes da marca ainda escreve depois
    # dela, e o Z assinado com `{quantas: 1, total: 14.10}` ficava a
    # contradizer uma conta que a base já tinha a 21,15 €. Por isso o retrato
    # não se tira uma vez: tira-se até dar duas vezes o mesmo (ver
    # `_retrato_estavel_das_contas_abertas`), e só então se assina.
    #
    # Não trava o fecho — ver `_contas_abertas_da_sessao` — mas fica escrito
    # no Z e no documento da sessão, para o gestor o encontrar amanhã sem ter
    # de adivinhar o que aconteceu ao dinheiro que a operadora diz ter visto
    # no ecrã.
    contas_abertas = await _retrato_estavel_das_contas_abertas(
        db, sessao["id"], dispositivo_id=operador.get("dispositivo_id")
    )

    # Os números do turno — a MESMA função que o Ponto de Caixa usa a meio da
    # tarde, e não uma segunda cópia dela. É essa partilha que garante que o
    # `esperado` que a operadora viu às 15h e o que sai no Z às 23h são o
    # mesmo cálculo, e que o desdobramento por tipo de pagamento não pode
    # discordar entre os dois ecrãs.
    # As devoluções do turno, lidas DEPOIS da marca `a_fechar` como tudo o
    # resto aqui — e definitivas pela mesma razão que as vendas: uma nota de
    # crédito exige a sessão ABERTA (`nota_credito.emitir_nota_credito`), e a
    # partir da marca não há sessão aberta nenhuma para esta caixa.
    notas_credito = await _notas_de_credito_do_turno(db, sessao)

    resumo = _resumo_do_turno(sessao, movimentos, vendas, notas_credito)
    vendas_dinheiro = resumo["vendas_dinheiro"]
    esperado_valor = resumo["esperado"]
    diferenca_valor = diferenca(esperado_valor, dados.contado)

    fechada_em = _agora()
    fechada_por = _quem(operador)
    atualizacao = {
        "estado": "fechada",
        "fechada_por": fechada_por,
        "fechada_em": fechada_em,
        "contado": dados.contado,
        "esperado": esperado_valor,
        "diferenca": diferenca_valor,
        # Gravado na sessão, e não só devolvido: o Z que a operadora leva é
        # papel, e a pergunta "o que é que ficou por cobrar na noite de
        # terça?" faz-se dias depois, no backoffice. Um número que só existe
        # numa resposta HTTP que ninguém guardou não responde a nada.
        "contas_abertas": contas_abertas,
    }
    # I2 (a revisão do núcleo fiscal): esta escrita não tinha condição de
    # estado nenhuma — dois fechos concorrentes da MESMA sessão passavam os
    # dois, e o último a escrever "ganhava" em silêncio (uma respondeu 50€,
    # a outra 30€, ficava só 30€ com diferenca=-20, e saíam dois Z
    # diferentes que o backoffice contradiz o papel que a funcionária
    # levou). Condicionar ao estado e confirmar `matched_count` é a mesma
    # defesa que o índice único de sessão aberta (db.py) já dá na ABERTURA —
    # aqui aplicada ao FECHO. A condição é `a_fechar` (a marca posta acima):
    # só quem a pôs pode escrever o Z, e ninguém a pode pisar sem passar
    # primeiro pela marca.
    resultado = await db[COLECOES["sessoes_caixa"]].update_one(
        {"id": sessao["id"], "estado": "a_fechar"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_FECHO_EM_CONFLITO)

    # O turno fechou: o que ficou aberto já não está à frente de ninguém.
    # Depois do Z estar escrito, de propósito — ver a função.
    await _largar_o_posto_das_contas_abertas(db, sessao["id"])

    # A verificação contra o Vendus é I/O de rede e vem DEPOIS de o fecho
    # estar escrito, de propósito (ver "A JANELA", na docstring): nada no Z
    # depende dela, e no meio era ela que mantinha a sessão em suspenso
    # durante dezenas de segundos. Continua embrulhada em try/except, além da
    # guarda que já existe dentro da própria função: o fecho JÁ ESTÁ FEITO, e
    # nem uma excepção inesperada aqui pode transformá-lo num 500 no ecrã —
    # isso mandava a funcionária fechar outra vez uma caixa já fechada
    # (regra 3 do dono, dupla rede de segurança).
    try:
        verificacao_vendus = await _verificar_vendas_dinheiro(db, sessao, vendas_dinheiro)
    except Exception as e:  # noqa: BLE001 — o fecho nunca pode falhar por causa disto
        logger.warning("[faturacao] verificação de fecho contra o Vendus falhou: %s", e)
        verificacao_vendus = {"nao_verificado": "Falha inesperada na verificação."}

    # Construído campo a campo (não `dict(sessao)`): sessao vem de find_one
    # sem projecção e, em Mongo real, traria _id — nunca deixar isso vazar
    # para uma resposta JSON.
    return {
        "id": sessao["id"],
        "caixa_id": sessao["caixa_id"],
        "loja_id": sessao["loja_id"],
        "aberta_por": sessao["aberta_por"],
        "aberta_em": sessao["aberta_em"],
        "fundo": sessao["fundo"],
        "vendas_dinheiro": vendas_dinheiro,
        "entradas": resumo["entradas"],
        "saidas": resumo["saidas"],
        "estado": atualizacao["estado"],
        "fechada_por": fechada_por,
        "fechada_em": fechada_em,
        "contado": dados.contado,
        "esperado": esperado_valor,
        "diferenca": diferenca_valor,
        # **O que saiu da gaveta a mais, e o porquê.** No Z como no Ponto de
        # Caixa: é o MESMO componente a desenhar os dois, e um número que a
        # operadora vê às 15h e não encontra no papel que assina às 23h é pior
        # do que não existir.
        "tirado_da_gaveta_a_mais": resumo["tirado_da_gaveta_a_mais"],
        "devolucoes_acima_do_recebido": resumo["devolucoes_acima_do_recebido"],
        # O desdobramento por tipo de pagamento e o mapa de imposto do turno
        # — as duas coisas que o Z não dizia.
        #
        # **Acrescentados à RESPOSTA, e não ao que se grava.** O que fica
        # escrito na sessão (`atualizacao`, acima) não muda uma vírgula: um Z
        # já assinado continua a ler-se exactamente como se lia, e nenhum
        # turno antigo passa a ter campos que não tinha. Podiam gravar-se,
        # como se gravam as `contas_abertas` — mas essas são um retrato de um
        # instante que mais ninguém consegue reconstituir, e estas duas
        # DERIVAM-SE inteiras das vendas emitidas da sessão, que ficam no
        # Mongo para sempre e já não podem mudar. Guardar uma cópia de um
        # número que se recalcula é criar uma segunda verdade para amanhã
        # alguém encontrar diferente da primeira.
        "pagamentos": resumo["pagamentos"],
        "pagamentos_por_registar": resumo["pagamentos_por_registar"],
        "mapa_imposto": resumo["mapa_imposto"],
        "base_tributavel": resumo["base_tributavel"],
        "iva_total": resumo["iva_total"],
        "total_faturado": resumo["total_faturado"],
        "quantos_documentos": resumo["quantos_documentos"],
        # SEMPRE presente, mesmo com `quantas: 0` — a mesma regra do
        # `emissao_por_confirmar` em `venda.py`: o ecrã não pode ter de
        # adivinhar se a ausência da chave quer dizer "não ficou nada por
        # cobrar" ou "esta versão do servidor não sabe responder a isso".
        "contas_abertas": contas_abertas,
        "verificacao_vendus": verificacao_vendus,
    }


async def _largar_o_posto_das_contas_abertas(db, sessao_id: str) -> None:
    """**O turno fechou: as contas que ficaram abertas já não estão à frente de
    ninguém.** Tira-lhes a etiqueta `posto_em_curso`.

    Não muda o `estado` de nada, não mexe em dinheiro nenhum e não contradiz o
    Z: as contas continuam `aberta`, continuam a valer o que o Z registou
    (`_contas_abertas_da_sessao`) e continuam a aparecer ao gestor
    (`_contas_esquecidas`). O que muda é só de quem elas são — a mesma
    distinção do `venda.entregar_ao_gestor`, aplicada ao turno inteiro.

    **Porque é que isto tem de existir.** A chave do índice único parcial de
    `db.py` passou a ser do POSTO (`"{loja_id}|{dispositivo_id}"`) e já não da
    sessão — foi assim que a corrida entre duas caixas do mesmo PC se fechou
    (ver `venda._etiqueta_do_posto`). Sem sessão na chave, uma conta esquecida
    num turno fechado continuava a ocupar o posto no dia seguinte: o
    `abrir_venda` apanhava `DuplicateKeyError` enquanto a leitura dele — que
    só varre sessões ABERTAS — respondia "o balcão está livre". Um 409 que a
    porta não sabe explicar é o beco que esta ronda veio fechar, e seria um
    beco novo no lugar do velho.

    **DEPOIS do Z estar escrito, e sem poder derrubá-lo.** O fecho já está
    feito quando isto corre; uma falha aqui não pode transformá-lo num 500 no
    ecrã, que mandava a funcionária fechar outra vez uma caixa já fechada
    (regra 3 do dono). Por isso é `try/except` com registo, como a verificação
    contra o Vendus logo a seguir. Se falhar mesmo, o desfecho não é silencioso:
    o `abrir_venda` do dia seguinte relê o posto, não encontra nada, e diz por
    extenso que há uma conta de um turno fechado a impedir a conta nova e que
    quem a arruma é o gestor (`venda._MSG_ETIQUETA_PRESA`).

    `update_many` e não uma passagem conta a conta: são todas a mesma escrita,
    e um turno tem no máximo um punhado de contas abertas."""
    try:
        await db[COLECOES["vendas"]].update_many(
            {"sessao_id": sessao_id, "estado": "aberta"},
            {"$unset": {"posto_em_curso": ""}},
        )
    except Exception as e:  # noqa: BLE001 — o fecho nunca pode falhar por causa disto
        logger.warning(
            "[faturacao] não foi possível largar o posto das contas abertas da "
            "sessão %s: %s. Se alguma delas tiver ficado com a etiqueta, o PC "
            "dela recusa a conta seguinte até o gestor a arrumar.", sessao_id, e,
        )


# O tecto da leitura das reservas por resolver DESTA sessão (o filtro já é o
# prefixo da sessão, e não a colecção inteira): um turno tem, no pior dos
# casos, um punhado delas. Existe pela mesma razão que todos os outros deste
# módulo — nenhuma leitura sem tecto.
_LIMITE_RESERVAS_DA_SESSAO = 200


async def _venda_com_emissao_viva(db, sessao: Dict) -> Optional[Dict]:
    """A primeira conta desta sessão com uma RESERVA FISCAL VIVA — ou `None`,
    o caso normal.

    **Porque é que isto trava o fecho.** O fecho lia as vendas `emitida`,
    calculava o Z e fechava, sem perguntar mais nada. Dois PCs na mesma
    caixa (a configuração que `venda.venda_aberta` documenta como estado
    estável) chegavam a isto: às 23:58 a Rafaela carrega em FINALIZAR e o
    Vendus demora; a Ana, no outro PC, conta a gaveta e fecha. Medido:
    `vendas_dinheiro=0,00  esperado=50,00  contado=58,99  diferenca=+8,99`,
    e a seguir a FS REAL de 8,99 € a sair para uma sessão já fechada. O Z
    que a funcionária assinou não tinha essa venda, os 8,99 € ficavam na
    gaveta como sobra por justificar, e a venda `emitida` não entrava em Z
    nenhum — nem neste, nem no seguinte (que filtra pelo `sessao_id` da
    sessão nova). Fechar a caixa a meio de uma emissão é fechar as contas
    antes de o dinheiro estar contado.

    **A pergunta é pela RESERVA, e não pelo estado da venda — e é aí que ela
    estava errada.** Perguntava-se pelas contas AINDA ABERTAS com reserva, e o
    buraco tem a forma exacta de uma venda `cancelada`. Medido pelas rotas
    reais: a operadora cancela a conta de 8,99 €; na janela entre o `$set
    cancelada` e a segunda pergunta pela reserva, outro separador abre a conta
    seguinte e a emissão desta reserva; a compensação `venda.py::_repor_aberta`
    colide com o índice único do posto e ENGOLE o `DuplicateKeyError`. A venda
    fica `cancelada` com a reserva viva — a operadora ouve «a conta NÃO foi
    cancelada … está travada» e ela está cancelada — e o
    `POST /pos/caixa/fechar` respondia **200 com o Z a 0,00** por cima de uma
    Fatura Simplificada que podia ter saído. Só `/fiscal/reservas-presas` a
    mostrava.

    O que não se pode fechar por cima é uma EMISSÃO viva; o estado em que a
    venda ficou é ortogonal a isso. Por isso o filtro é `estado != "emitida"`,
    e não uma lista de estados: um estado novo que apareça amanhã cai do lado
    de TRAVAR, que é o lado seguro. `emitida` é a única excepção, e é a
    fronteira do outro lado — a reserva de uma venda emitida fica em
    `fat_refs_fiscais` para sempre de propósito (é ela que sustenta a
    idempotência, `fiscal.py::_gravar_documento`) e travaria o fecho de todas
    as noites.

    **É o MESMO critério de `fiscal.py::listar_reservas_presas`** — «a reserva
    existe e a venda dela ainda não está `emitida`» —, e não uma paráfrase: é
    isso que impede a lista do gestor e o travão do fecho de discordarem sobre
    a mesma conta, que é como esta se escapou. A marca `documento_id` da
    reserva NÃO entra aqui, pela mesma razão que não decide lá: ela é uma marca
    de conveniência que pode falhar (`_ligar_venda_ao_documento` engole o erro
    de propósito), e uma venda emitida cuja reserva ficou por marcar travaria o
    fecho para sempre.

    **A pergunta faz-se do lado das RESERVAS, e é aí que ela estava errada
    outra vez.** A ronda anterior mudou o filtro do estado e manteve a
    DIRECÇÃO: partia de `{"sessao_id": …}` em `fat_vendas` e só depois
    perguntava a `fat_refs_fiscais` por cada venda encontrada. Uma reserva cuja
    venda JÁ NÃO EXISTE nunca era alcançada — e as vendas são mesmo apagadas:
    `venda.py::_grava_as_partes` faz `delete_one` das filhas em dois caminhos,
    e as filhas são visíveis em `/pos/venda/repartidas` entre o insert e o
    travão da mãe, por isso um `finalizar` pode ter reservado numa delas.
    Medido com controlo, pelas rotas reais: a MESMA reserva com a venda
    presente dá **409**; sem a venda dá **200, com o Z assinado** por cima de
    uma Fatura Simplificada que podia estar a nascer. `/fiscal/reservas-presas`
    mostrava-a (com `estado_da_venda=None`); o fecho não.

    **E, desde esta ronda, quem responde a isso é `por_resolver`.** A pergunta
    do lado das reservas ESTAVA aqui, escrita uma vez — e era essa a raiz: o
    diálogo que a operadora lê antes de assinar (`_contas_abertas_da_sessao`)
    continuava a partir das vendas e não a via. Medido: a mesma reserva órfã
    dava `travão -> {'id': 'filha-9'}` e `POST /pos/caixa/fechar` **409**, e o
    diálogo dizia **`quantas=0 total=0,00`**; ela lia «nada por cobrar»,
    carregava em FECHAR e levava um 409 com um id que não estava em ecrã
    nenhum. Agora os dois lêem a MESMA função, e a diferença entre eles é só o
    filtro do fim: este trava, aquele conta.

    Uma reserva de uma sessão ANTIGA não entra (o âmbito é a lista de sessões
    que se passa, e o prefixo da `ext_ref` já carrega a sessão): o fecho de
    hoje não pode ficar refém de uma reserva presa de anteontem — essa é do
    gestor (`/fiscal/reservas-presas`), e a caixa de hoje fecha na mesma.

    **A conta entregue ao gestor conta aqui na mesma**, e é de propósito: a
    marca (`venda.py::entregar_ao_gestor`) diz de quem é a conta, não o que
    foi facturado. Enquanto a reserva fiscal dela estiver viva, pode estar a
    nascer uma Fatura Simplificada REAL do outro lado — e fechar a caixa a
    meio disso é fechar as contas antes de o dinheiro estar contado, seja de
    quem for a conta. Quem a destranca é o gestor, no backoffice; a partir daí
    ela deixa de travar o fecho e passa a entrar no Z como dinheiro por
    receber, que é o que ela é.

    A outra metade desta defesa está em `fiscal.py`: depois de ganhar a
    reserva, a emissão relê a SESSÃO e aborta se ela já não estiver aberta
    (`SessaoJaNaoAberta`). São as duas necessárias, e não bastam por si só:
    o que as liga é a ORDEM em que `fechar_caixa` as usa — marcar a sessão
    `a_fechar` e só DEPOIS fazer esta pergunta (ver "A JANELA", na docstring
    de `fechar_caixa`). Esta função é chamada duas vezes por fecho, uma de
    cada lado da marca, e as duas chamadas têm papéis diferentes: a de antes
    evita perturbar uma emissão legítima; a de depois é a que fecha a
    janela."""
    # **O predicado é de `por_resolver.contas_por_resolver`, e já não daqui.**
    # Import local: `por_resolver` importa `venda` e `fiscal`, que importam
    # este módulo — o ciclo de sempre deste pacote, resolvido como os outros.
    #
    # Este leitor filtra pelo seu FIM e não volta a decidir o que conta: das
    # contas por resolver desta sessão, as que TRAVAM são as que têm uma
    # RESERVA VIVA — e só essas. A regra 3 do dono é que o fecho não bloqueia
    # por dinheiro que ninguém vai pagar; o que não se pode fechar por cima é
    # uma EMISSÃO viva.
    from .por_resolver import contas_por_resolver

    for item in await contas_por_resolver(db, [sessao["id"]]):
        if item["tem_reserva_viva"]:
            # A venda pode já não existir (uma filha apagada pela compensação
            # de `venda._grava_as_partes`): o que trava o fecho é a EMISSÃO, e
            # ela existe na mesma. Quem chama só precisa do `id` para a
            # mensagem e para o gestor a ir procurar a
            # `/fiscal/reservas-presas`, que é onde ela aparece.
            return item["venda"] or {"id": item["id"]}
    return None


async def _nome_dos_dispositivos(db, ids) -> Dict:
    """O nome de cada PC emparelhado, por id — para o ecrã poder dizer "PC
    Drive-Thru" onde só tinha um uuid.

    Um punhado de ids (os postos de uma loja), por isso um `$in` chega e não
    há N leituras. Um id sem documento (o PC foi revogado desde então) fica
    simplesmente de fora: quem lê trata a ausência como "outro posto", que é
    a verdade que se sabe."""
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    encontrados = await db[COLECOES["dispositivos"]].find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "nome": 1}
    ).to_list(len(ids))
    return {d["id"]: d.get("nome") for d in encontrados if d.get("id")}


async def _contas_abertas_da_sessao(db, sessao_id: str, dispositivo_id=None) -> Dict:
    """Quantas contas desta sessão ficam por cobrar, e quanto valem.

    **O buraco que isto fecha.** A faixa que a operadora lia no balcão, por
    cima das partes de uma conta repartida, prometia-lhe isto: "enquanto não
    forem cobradas ou canceladas, ficam abertas no servidor e o fecho desta
    caixa vai contá-las". Não contava. O Z lê `{"sessao_id": …, "estado":
    "emitida"}` e mais nada, e o único travão do fecho —
    `_venda_com_emissao_viva` — exige uma RESERVA FISCAL, que uma parte que
    nunca chegou ao EMITIR não tem. Dividida uma conta de 14,10 € por duas
    pessoas e cobrada nenhuma, a caixa fechava, o Z saía sem uma palavra
    sobre elas, e os 14,10 € por receber não apareciam em relatório nenhum —
    nem neste, nem no da sessão seguinte, que filtra por outro `sessao_id`.

    **E porque é que isto NÃO trava o fecho.** Seria a correcção fácil e é a
    errada: uma parte que ninguém vai pagar (o cliente foi-se embora, a
    operadora esqueceu-se de a cancelar) prendia a loja para sempre — regra 3
    do dono, o fecho não bloqueia, regista e segue. E também não se resolve
    mudando a frase da faixa para "não conta": o dinheiro por receber existe
    à mesma, e um Z que não o menciona é um Z que esconde. Conta-se, escreve-
    se no Z e diz-se à operadora ANTES de ela assinar — que é o que
    `GET /pos/caixa/contas-abertas` serve.

    **Não é só sobre partes, nem só sobre as `aberta`.** A pergunta é feita a
    TUDO o que a sessão tem por resolver (`por_resolver.contas_por_resolver`):
    a conta que ficou meia-picada quando o cliente desistiu, a conta travada
    que ficou à espera do gestor, a que a operadora já lhe ENTREGOU
    (`venda.py::entregar_ao_gestor`), as partes de quem dividiu — e, desde
    esta ronda, a mãe `separada` SEM PARTES (11,35 € que saíam de um Z
    assinado) e a RESERVA VIVA cuja venda já não existe (a que o travão do
    fecho nomeava num 409 e esta lista não tinha).
    Todas são a mesma coisa do ponto de vista do turno — dinheiro que o ecrã
    mostrou e que não entrou em fatura nenhuma. A entregue ao gestor conta
    aqui na mesma, e tem de contar: sair do BALCÃO não é ser cobrada, e o Z é
    o único registo de que aqueles euros ficaram por receber neste turno. Sai
    marcada (`entregue_ao_gestor`), porque a operadora não a pode cobrar nem
    cancelar e o ecrã não lhe pode pedir isso.

    **A sessão, e não o dispositivo.** Ao contrário de
    `venda.contas_repartidas` (que responde ao ECRÃ de um posto), o Z é do
    TURNO: uma conta aberta no "PC Drive-Thru" tem de aparecer no Z da caixa
    que os dois postos partilham, senão volta a haver dinheiro por receber que
    ninguém vê.

    **E é por isso que cada conta diz de que POSTO é.** O âmbito desta lista
    é o turno, mas todas as acções do ecrã são do posto: `GET
    /pos/venda/repartidas` filtra pelo `dispositivo_id` do token. Medido: dois
    postos na mesma caixa, o Drive-Thru divide a conta dele e não cobra
    ninguém; o fecho pedido do Balcão listava as três contas do turno (28,20
    €) e mandava-a cobrá-las, e o ecrã do Balcão respondia `0 grupos`. A
    operadora lia uma instrução que não conseguia cumprir. Alargar o âmbito
    das ACÇÕES seria pior (uma operadora a cobrar a conta do outro posto é
    outro problema, e mais caro); o que estava errado era o texto, e o texto
    só pode dizer a verdade se souber de quem é cada conta. Sai o
    `dispositivo_id` em cru e o `dispositivo_nome` para o ecrã o poder
    escrever por extenso.

    **E se ela trava o fecho ou não** (`trava_o_fecho`). Nem todas estas
    contas são iguais perante o botão FECHAR CAIXA: uma conta com RESERVA
    FISCAL viva recusa-o mesmo (`_venda_com_emissao_viva`, e está certo que
    recuse), enquanto as outras não travam nada. O ecrã dizia "Não impedem o
    fecho" sobre todas — medido no browser: o diálogo listou 2 partes e uma
    conta travada, e carregar em Fechar Caixa devolveu 409 por causa da
    travada. O critério é o MESMO de `_venda_com_emissao_viva` (a conta está
    `aberta` e existe uma reserva para ela), feito conta a conta em vez de
    parar na primeira.

    `dispositivo_id` é o posto de onde a pergunta foi feita — no fecho, o PC
    onde a operadora carregou em FECHAR CAIXA. Sai na resposta para quem a
    desenha poder comparar sem ter de adivinhar quem está a perguntar (o
    token do POS não viaja para o browser em texto legível).

    O `import` de `por_resolver` é LOCAL pela mesma razão do
    `_verificar_vendas_dinheiro` aqui em baixo: ele importa `venda.py`, que
    importa deste módulo, e um import no topo fechava o ciclo. E o valor de
    cada conta vem do `_totais` de `venda.py` (por `por_resolver`), nunca de
    uma soma escrita aqui — o valor de uma conta sai sempre de
    `precos.linha_de_venda`, em todo o módulo (regra 1 do cabeçalho de
    `venda.py`).
    """
    # **O predicado é de `por_resolver.contas_por_resolver`, e já não daqui** —
    # é a MESMA função que o travão do fecho lê, e é essa identidade que é a
    # correcção. Enquanto esta pergunta partisse das VENDAS e o travão das
    # RESERVAS, havia contas que travavam o fecho sem aparecerem aqui (a
    # reserva órfã: 409 a nomear `filha-9`, diálogo `quantas=0 total=0,00`) e
    # dinheiro que não travava nem aparecia (a mãe `separada` sem partes:
    # 11,35 € e um Z assinado a dizer 0,00 €).
    #
    # O que este leitor faz é o SEU fim: contar tudo, com os subtotais que o
    # ecrã desenha. Não filtra nada — o âmbito é o turno inteiro.
    from .por_resolver import contas_por_resolver

    itens = await contas_por_resolver(db, [sessao_id])

    nomes = await _nome_dos_dispositivos(
        db, [i["dispositivo_id"] for i in itens]
    )

    contas = []
    total = 0.0
    total_que_trava = 0.0
    total_por_cobrar = 0.0
    total_do_balcao = 0.0
    total_do_gestor = 0.0
    for item in itens:
        valor = item["total"]
        trava = item["tem_reserva_viva"]
        entregue = bool(item["entregue_ao_gestor_em"])
        if valor is not None:
            total = round(total + valor, 2)
            # Os dois SUBTOTAIS saem daqui, e não de uma soma no browser. É a
            # regra 1 do cabeçalho de `venda.py` (o valor de uma conta sai
            # sempre do servidor) aplicada ao que o ecrã passou a precisar
            # desta ronda: ele mostra as duas famílias em caixas separadas, e
            # cada caixa tem o seu próprio euro em cima. Somá-los no
            # JavaScript era pôr o ecrã a fazer aritmética de dinheiro — a
            # única coisa que este módulo nunca lhe deixa fazer.
            if trava:
                total_que_trava = round(total_que_trava + valor, 2)
            else:
                total_por_cobrar = round(total_por_cobrar + valor, 2)
                # E, dentro das que não travam, de que lado está: ainda no
                # BALCÃO (a operadora cobra-a ou cancela-a antes de fechar) ou
                # já do GESTOR (ela não lhe pode fazer nem uma coisa nem
                # outra). São TRÊS famílias no ecrã e não duas — ver
                # `entregue_ao_gestor`, no dicionário aqui em baixo —, e cada
                # caixa tem de ter o SEU euro em cima: escrever o total das
                # três por cima de uma lista de uma delas era o ecrã a
                # contradizer-se, e subtrair um do outro em JavaScript era pôr
                # o browser a fazer aritmética de dinheiro.
                #
                # `total_por_cobrar` NÃO muda de significado — continua a ser
                # tudo o que não trava, que é o que já está gravado nos Z
                # assinados. Os dois de baixo são subtotais NOVOS, e somam-no.
                if entregue:
                    total_do_gestor = round(total_do_gestor + valor, 2)
                else:
                    total_do_balcao = round(total_do_balcao + valor, 2)
        contas.append({
            # `item["id"]` e não `venda["id"]`: uma reserva órfã não tem venda
            # nenhuma, e o id dela é a única forma de o gestor a ir procurar a
            # `/fiscal/reservas-presas`. Era essa entrada que o 409 do fecho
            # nomeava e esta lista não tinha.
            "id": item["id"],
            "total": valor,
            "criada_em": item["criada_em"],
            # **PORQUÊ é que esta conta está por resolver** — `conta_aberta`,
            # `mae_separada_sem_partes`, `emissao_viva` (a reserva sem venda) ou
            # `estado_desconhecido`. Sem isto o ecrã tinha três coisas
            # diferentes com o mesmo aspecto, e a operadora recebia a mesma
            # instrução ("cobre-a ou cancele-a") para uma que não se cobra nem
            # se cancela. Ver `por_resolver`.
            "motivo": item["motivo"],
            # O estado em que a venda ficou, ou `None` quando ela já não
            # existe. Uma informação, não um buraco: quem lê tem de poder
            # distinguir "a conta está aberta" de "não há conta nenhuma, só a
            # reserva".
            "estado_da_venda": item["estado_da_venda"],
            # Qual delas é uma PARTE de uma conta repartida, e de qual. É o que
            # distingue "faltou cobrar uma pessoa" de "ficou uma conta a meio"
            # — duas conversas diferentes com o gestor no dia seguinte.
            "conta_mae_id": item["conta_mae_id"],
            # De que POSTO é — ver a docstring. Sempre presentes as duas
            # chaves (o nome a `None` quando o PC já foi revogado), pela
            # regra do `emissao_por_confirmar` em venda.py: quem desenha não
            # pode ter de adivinhar se a ausência quer dizer "não se sabe" ou
            # "esta versão do servidor não responde a isso".
            "dispositivo_id": item["dispositivo_id"],
            "dispositivo_nome": nomes.get(item["dispositivo_id"]),
            # A que IMPEDE o fecho, separada das que não impedem nada.
            "trava_o_fecho": trava,
            # A que JÁ NÃO É DO BALCÃO. O ecrã do fecho lista estas contas e
            # manda cobrá-las ou cancelá-las; esta a operadora não consegue
            # fazer nem uma coisa nem outra — é do gestor, e está na lista
            # dele (`GET /caixa/contas-esquecidas`). Sem esta chave, o
            # diálogo do fecho voltava a dar uma instrução que ninguém ali
            # consegue cumprir, que é o mesmo defeito do texto que o
            # `dispositivo_nome` veio corrigir.
            "entregue_ao_gestor": entregue,
        })
    return {
        "quantas": len(contas),
        "total": total,
        # As duas metades de `total`, já somadas aqui — ver o comentário no
        # ciclo. `quantas_travam` acompanha-as pela mesma razão: o ecrã
        # escreve "1 conta IMPEDE o fecho" e não pode ter de contar a lista.
        "quantas_travam": sum(1 for c in contas if c["trava_o_fecho"]),
        "total_que_trava": total_que_trava,
        "total_por_cobrar": total_por_cobrar,
        # As duas metades de `total_por_cobrar`: o que ainda está no BALCÃO
        # (cobrar ou cancelar antes de fechar) e o que já é do GESTOR (não se
        # cobra nem se cancela aqui). A frase de cada família é outra porque as
        # saídas são outras, e por isso cada uma precisa do seu euro exacto.
        # `and not trava_o_fecho` de propósito, e a par do que o ecrã desenha:
        # uma conta ENTREGUE que ainda tem a reserva viva continua a IMPEDIR o
        # fecho (é o estado logo a seguir à entrega, antes de o gestor libertar
        # a reserva), e essa pertence à primeira família — a urgente. Contá-la
        # nas duas punha o ecrã a dizer que há mais contas do que existem.
        "total_do_balcao": total_do_balcao,
        "quantas_do_gestor": sum(
            1 for c in contas
            if c["entregue_ao_gestor"] and not c["trava_o_fecho"]),
        "total_do_gestor": total_do_gestor,
        "contas": contas,
        "dispositivo_id": dispositivo_id,
    }


# Quantas vezes se volta a tirar o retrato antes de desistir de assinar o Z.
# É um TECTO e não folga, pelo mesmo raciocínio do `_TENTATIVAS` de
# `venda.py`: cada ronda custa uma releitura das contas abertas desta sessão
# (um punhado de documentos), e o que está no fim dele não é perda nenhuma —
# é um 409 que diz a verdade e uma caixa que continua marcada `a_fechar`,
# à espera do segundo toque em FECHAR CAIXA.
_RONDAS_DO_RETRATO = 5


async def _retrato_estavel_das_contas_abertas(db, sessao_id, dispositivo_id) -> Dict:
    """O retrato das contas abertas TIRADO ATÉ DAR DUAS VEZES O MESMO — e é
    isso que faz o Z descrever o turno no instante em que é assinado.

    **O defeito, medido pelas rotas reais.** A guarda que `venda.py` ganhou na
    ronda passada (`_garante_sessao_desta_venda_aberta`) PERGUNTA pela sessão
    e não a prende: entre a pergunta e a escrita da rota ainda há idas ao
    Mongo, e um fecho inteiro cabe lá dentro. Reproduzido, com as funções
    reais e o fecho a correr nessa janela: o Z é assinado com
    `contas_abertas` `{quantas: 1, total: 14.10}` e a seguir
      - `POST /pos/venda/{id}/linhas` responde 201 e a conta fica a 21,15 €;
      - `PUT /pos/venda/{id}/desconto` responde 200 e grava 50 % (7,05 €);
      - `dividir`/`separar` criam partes `aberta` numa sessão já `fechada`.
    O `contas_abertas` gravado na sessão continuava a dizer 14,10 € nos
    quatro casos. **O estrago não é a escrita landar — é o Z mentir**: ele é
    o único registo de que aqueles euros ficaram por receber, ninguém volta a
    olhar para a sessão depois do fecho, e o número que lá está era o de
    antes.

    **Porque é que voltar a tirar o retrato chega, e não é um `sleep`
    disfarçado.** A marca `a_fechar` é posta ANTES de qualquer soma (ver
    `fechar_caixa`, "A JANELA"). A partir dela **nenhum escritor NOVO passa a
    guarda** — as seis rotas que mexem no dinheiro exigem a sessão desta venda
    `aberta`. Logo o conjunto de escritas em voo no instante da marca é
    FINITO, e cada uma delas está a poucas idas ao Mongo de aterrar: drena
    sozinho. Duas leituras seguidas a dar exactamente o mesmo são a evidência,
    à distância de uma ida-e-volta completa, de que já não está a aterrar
    nada — e é sobre a última delas que o Z é assinado.

    **O que isto NÃO promete, dito por inteiro.** Não é exclusão mútua: uma
    escrita que passou a guarda antes da marca e que só aterre DEPOIS da
    última leitura ainda apanha o Z já assinado. O que se compra é evidência —
    a janela deixa de ser "tudo o que acontecer entre a única leitura e a
    escrita do Z" e passa a ser "uma escrita que sobreviva a duas leituras
    concordantes e ainda assim aterre a seguir". Fechá-la a sério exigia
    carimbar cada venda da sessão na marca e condicionar as sete escritas a
    esse carimbo (mutação atómica por documento, sem transacções) — mais sete
    sítios a mudar e uma escrita por conta em cada fecho; fica registado aqui
    como o degrau seguinte, se algum dia se medir que faz falta.

    **E arruma o cancelamento, que é a única escrita que passa de propósito.**
    O `venda.cancelar_venda` não passa pela guarda (é a saída de uma conta que
    ninguém pagou, ver a docstring dele) e, com uma leitura só, um cancelar
    que aterrasse depois dela ficava de fora do Z: a retoma do fecho passava a
    responder `{'quantas': 0, 'total': 0.0}` onde a primeira tentativa dizia
    1 conta / 14,10 €. Com o retrato repetido, o cancelamento aparece na
    releitura e o Z descreve o que está mesmo lá no momento em que assina —
    a conta cancelada deixa de ser "por cobrar", que é a verdade, e é a mesma
    verdade que o Z já contava para um cancelamento anterior à marca. É por
    isso que o 409 de `arrumar_conta_esquecida` deixou de prometer um estrago
    que já não existe (ver `_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER`).

    Não estabilizar não é assinar na mesma: é 409. A caixa fica em `a_fechar`
    — o estado de que se sai carregando outra vez em FECHAR CAIXA
    (`_sessao_por_fechar`) — e essa marca é precisamente o que faz a
    tentativa seguinte encontrar tudo parado."""
    retrato = await _contas_abertas_da_sessao(
        db, sessao_id, dispositivo_id=dispositivo_id)
    for _ in range(_RONDAS_DO_RETRATO - 1):
        outra_vez = await _contas_abertas_da_sessao(
            db, sessao_id, dispositivo_id=dispositivo_id)
        if outra_vez == retrato:
            return outra_vez
        # Não é ruído: cada linha destas é uma escrita que aterrou DEPOIS de
        # a caixa estar marcada a fechar. Uma ou outra é o normal (uma rota
        # que passou a guarda mesmo antes da marca); muitas, todos os dias,
        # querem dizer que a guarda está a deixar passar coisa nova.
        logger.warning(
            "[faturacao] as contas abertas da sessão %s mudaram durante o "
            "fecho (%s → %s por cobrar); a tirar o retrato outra vez.",
            sessao_id, retrato.get("total"), outra_vez.get("total"),
        )
        retrato = outra_vez
    raise HTTPException(status_code=409, detail=_MSG_FECHO_SEM_RETRATO_ESTAVEL)


@router.get("/pos/caixa/contas-abertas")
async def contas_abertas_da_caixa(
    caixa_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """O que vai ficar por cobrar se a caixa fechar agora — para a operadora
    poder ver isso ANTES de assinar o Z, e não depois.

    Só leitura, e é essa a decisão de desenho: a alternativa era o próprio
    `POST /pos/caixa/fechar` recusar o primeiro pedido e pedir uma
    confirmação. Não se fez, por duas razões. A primeira é que essa recusa
    tinha de acontecer DEPOIS da marca `a_fechar` (antes dela, a lista podia
    mudar entre a pergunta e o fecho), e desfazer a marca para pedir uma
    confirmação é abrir outra vez a janela que `fechar_caixa` fechou. A
    segunda é a regra 3 do dono: o fecho não tem portas. Uma leitura à parte
    dá a informação a tempo sem pôr nada disso em jogo — e o Z que sai a
    seguir traz a lista outra vez, essa já definitiva (calculada depois da
    marca, quando mais nenhuma conta desta sessão pode nascer, mudar de valor
    ou ser repartida — ver a lista das três guardas em `fechar_caixa`).

    Usa `_sessao_viva` e não `_sessao_aberta`: uma sessão que ficou a meio de
    um fecho continua a ter contas abertas, e é precisamente nessa que a
    operadora vai carregar em FECHAR outra vez. Sem sessão viva nenhuma não
    há nada por cobrar — responde-se com zero, e não com um erro."""
    db = obter_db()
    await _obter_caixa_da_loja(db, caixa_id, operador["loja_id"])
    sessao = await _sessao_viva(db, caixa_id, {"_id": 0})
    if sessao is None:
        return {
            "quantas": 0, "total": 0.0, "quantas_travam": 0,
            "total_que_trava": 0.0, "total_por_cobrar": 0.0, "contas": [],
            "dispositivo_id": operador.get("dispositivo_id"),
        }
    return await _contas_abertas_da_sessao(
        db, sessao["id"], dispositivo_id=operador.get("dispositivo_id")
    )


async def _verificar_vendas_dinheiro(db, sessao: Dict, vendas_dinheiro_local: float) -> Optional[Dict]:
    """Ponte para `fiscal.py::verificar_vendas_dinheiro_no_vendus`, com um
    import LOCAL (não ao nível do módulo) de propósito: `fiscal.py` importa
    de `venda.py`, que por sua vez importa deste módulo
    (`_obter_caixa_da_loja`/`_sessao_aberta`) — um `import` de `fiscal.py`
    aqui no topo do ficheiro fechava um ciclo (`caixa → fiscal → venda →
    caixa`). Adiar a importação para dentro da chamada resolve-o sem mudar
    a ordem de carregamento em `__init__.py`. Uma função à parte (em vez de
    inline em `fechar_caixa`) também é o que torna isto substituível nos
    testes com `monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", ...)`."""
    from .fiscal import verificar_vendas_dinheiro_no_vendus
    return await verificar_vendas_dinheiro_no_vendus(db, sessao, vendas_dinheiro_local)


# --- As contas que sobreviveram ao Z (o buraco a seguir ao fecho) --------------
#
# **Medido, com números.** 14,10 € divididos por 2, ninguém cobrado, caixa
# fechada, turno seguinte aberto. `GET /pos/venda/repartidas` → `[]`; `GET
# /pos/venda/aberta` → `null`; `GET /pos/caixa/contas-abertas` →
# `{quantas: 0}`. As duas partes continuavam na base a `estado=aberta` com o
# `sessao_id` do turno anterior, e NENHUM ecrã voltava a mostrá-las. O
# `contas_abertas` que o fecho grava na sessão não tinha um único leitor em
# todo o repositório: escrevia-se para o Z de papel e mais nada.
#
# Não é um acidente dos ecrãs do POS — é o desenho deles, e está certo:
# `venda_aberta` e `contas_repartidas` resolvem a sessão por `_sessao_aberta`,
# porque um balcão só mostra o turno que está a decorrer. O que faltava era o
# outro lado.
#
# **Porque é que a saída é o BACKOFFICE, e não um ecrã novo no POS.** Três
# razões, e a terceira decide:
#   1. A operadora do turno seguinte não tem nada que fazer a uma conta de um
#      turno que ela não fechou — mexer nela mudava um Z que outra pessoa
#      assinou. As rotas de escrita da venda recusam-lhe isso desde esta ronda
#      (`venda.py::_garante_sessao_desta_venda_aberta`), e um ecrã que lhe
#      mostrasse contas em que ela não pode tocar era o defeito 4 outra vez:
#      uma instrução que ela não consegue cumprir.
#   2. A pergunta é do GESTOR e é sobre dinheiro do passado ("o que é que
#      ficou por receber na noite de terça, e porquê?"), não sobre o cliente
#      que está à frente.
#   3. O ecrã já existe e é onde ele vai quando alguma coisa fica pendurada: a
#      lista das reservas fiscais presas. Uma conta aberta de um turno fechado
#      é o mesmo género de problema — ficou a meio, ninguém a resolve sozinha,
#      e é preciso alguém ir perguntar o que aconteceu. Um ecrã NOVO para isto
#      era um segundo sítio a que ele teria de se lembrar de ir.

_LIMITE_CONTAS_ESQUECIDAS = 500

_MSG_CONTA_ESQUECIDA_INEXISTENTE = "Conta não encontrada."
_MSG_CONTA_ESQUECIDA_JA_RESOLVIDA = (
    "Esta conta já não está aberta — foi cobrada, cancelada ou repartida "
    "entretanto. Recarregue a lista."
)
# **E a saída de quando não está lá ninguém.** A frase dizia só «cobra-se ou
# cancela-se no balcão, por quem está lá» — e há uma configuração documentada
# (dois PCs na mesma caixa, `venda.venda_aberta`) em que não está lá ninguém:
# a conta ficou aberta num POSTO que morreu, foi revogado, ou de onde a
# operadora saiu. Medido com 11,64 € abertos em `pc-que-morreu` e a operadora
# no `pc-balcao`, turno a decorrer: o diálogo e o Z contam
# `quantas=1 total=11,64` (o dinheiro aparece, e isso está certo), mas
# `GET /pos/venda/aberta` `null`, `/repartidas` `[]`,
# `/caixa/contas-esquecidas` `[]`, `arrumar` 409 a mandar ao balcão e
# `entregar-ao-gestor` do outro posto 409. Zero saídas.
#
# A saída REAL é fechar o turno — a conta entra no Z como ficando por cobrar,
# que é o que ela é, e a partir daí está nesta lista e arruma-se aqui —, e era
# a única que esta frase não nomeava. Não se inventa acção nova: um gestor a
# cancelar à distância a conta de um posto de um turno a decorrer é o defeito
# que a marca `entregue_ao_gestor` veio fechar. O que faltava era a verdade
# escrita.
_MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO = (
    "A caixa desta conta está ABERTA neste momento — esta conta é do turno "
    "que está a decorrer e é no POS que ela se resolve: cobra-se ou "
    "cancela-se NO POSTO ONDE ELA ESTÁ, por quem está lá. E se já não estiver "
    "ninguém nesse posto (o PC morreu, foi revogado, ou a operadora está "
    "noutro), a saída é FECHAR O TURNO: a conta entra no Z como ficando por "
    "cobrar, que é o que ela é, e a partir daí arruma-se aqui. Nada foi "
    "alterado."
)
# O turno DELA está a fechar-se agora. Cancelá-la neste instante tirava-a da
# lista que o Z está a somar (`_contas_abertas_da_sessao` é lida depois da
# marca `a_fechar`) — o Z sairia sem a mencionar, e o registo de que aqueles
# euros ficaram por receber desaparecia. É uma espera de segundos; e um fecho
# que tenha ficado preso destranca-se no POS, carregando outra vez em FECHAR
# CAIXA (ver `_MSG_SESSAO_A_MEIO_DE_UM_FECHO`), não por aqui.
_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER = (
    "A caixa desta conta está a FECHAR o turno neste momento — o Z está a ser "
    "calculado e esta conta ainda vai entrar nele como ficando por cobrar. "
    "Nada foi alterado. Espere que o fecho termine e recarregue a lista; se o "
    "fecho tiver ficado preso, é no POS que se conclui (FECHAR CAIXA outra "
    "vez), e só depois é que esta conta se arruma aqui."
)
# **A família que NÃO se arruma, e que por isso tem nome e texto próprios.**
#
# A regra desta ronda é: toda a conta que o predicado declara POR RESOLVER tem
# de ter pelo menos uma acção executável que a resolva. Esta é a única que não
# pode ter, e a razão é a mesma que a põe na lista: `por_resolver` conta os
# estados por `$nin` sobre os dois terminais, de propósito, para um estado que
# apareça amanhã cair do lado de CONTAR. Contar é seguro; AGIR não é. «Dar por
# perdida» escreve `cancelada`, que é declarar «isto nunca foi pago» — e sobre
# um estado que esta versão não conhece não se pode declarar nada: ele pode
# muito bem querer dizer «pago, à espera de conferência», e o botão apagava a
# receita.
#
# Por isso ela fica onde o dinheiro é contado (no Z e na lista do gestor, que é
# o que impede o dinheiro de ficar invisível) mas SEM o botão — e com esta
# frase no lugar dele, que diz o que se sabe, o que não se sabe e a quem se
# leva. Um botão que devolve 409 e uma lista que o volta a desenhar a seguir é
# um ciclo fechado sobre si próprio; uma frase que diz «isto não se resolve
# aqui, e porquê» não é.
_MSG_CONTA_ESQUECIDA_ESTADO_DESCONHECIDO = (
    "Esta conta está num estado que esta versão do sistema não conhece "
    "(«%s»). Ela CONTA como dinheiro por receber — é por isso que aparece "
    "aqui e no Z do turno —, mas não se arruma por aqui: dar por perdida "
    "escreve «cancelada», e isso declara que nunca foi paga. Sobre um estado "
    "que o sistema não sabe ler, isso não se pode declarar. Guarde a "
    "referência desta conta e leve-a a quem mantém o sistema; nada foi "
    "alterado."
)
_MSG_CONTA_ESQUECIDA_TRAVADA = (
    "Esta conta tem uma reserva fiscal por resolver — pode ter uma Fatura "
    "Simplificada real do lado da AT. Não se arruma por aqui: resolva-a "
    "primeiro em Reservas Fiscais Presas (reconciliar, ou libertar depois de "
    "confirmar no Vendus que não saiu documento nenhum) e só então é que se "
    "sabe o que fazer a esta conta."
)
# **A ÓRFÃ tem UMA saída, e a frase de cima nomeava-lhe duas.** Reconciliar
# liga o documento do Vendus à VENDA, e a venda desta já não existe (a filha
# apagada pela compensação de `venda._grava_as_partes`):
# `fiscal.reconciliar_reserva_presa` responde 404 «não existe nenhuma venda
# com este id — não há nada para reconciliar». Metade da instrução era falsa,
# e uma instrução meia-falsa gasta-se na metade errada primeiro.
_MSG_CONTA_ESQUECIDA_TRAVADA_SEM_VENDA = (
    "Esta reserva fiscal ficou sem venda nenhuma por baixo — pode ter uma "
    "Fatura Simplificada real do lado da AT. Não se arruma por aqui, e "
    "também não há nada para reconciliar (reconciliar liga o documento à "
    "venda, e a venda já não existe). A saída é LIBERTAR, em Reservas Fiscais "
    "Presas, depois de confirmar no Vendus que não saiu documento nenhum para "
    "esta referência."
)
# **A SEGUNDA família que não pode ter acção executável** — a primeira é o
# `estado_desconhecido`, aqui em cima, e a regra é a mesma: ou acção
# executável, ou nome e texto próprios.
#
# A reserva viva SEM `ext_ref` são dados estragados (`fiscal._reservar`
# escreve-a sempre). Medido com 11,64 € e o turno fechado:
# `/caixa/contas-esquecidas` mostrava-a como `conta_aberta` com o crachá
# «Reserva fiscal por resolver» e a frase de cima mandava-a a Reservas
# Fiscais Presas — e lá LIBERTAR responde 409
# (`fiscal._MSG_LIBERTAR_SEM_EXT_REF`). Três rotas, zero saídas,
# permanentemente, com o ecrã a desenhar-lhe «resolva a reserva na lista
# acima… e volte aqui»: voltar traz a mesma linha.
#
# **Porque é que não se lhe dá acção executável.** A única rota que a
# destrancaria é a que autoriza uma SEGUNDA Fatura Simplificada da mesma
# venda, e a confirmação humana que ela exige — «abra o Vendus, procure ESTA
# referência e veja que não há documento» — não se pode pedir sobre uma
# referência que não existe. Um caminho novo ali, para dados estragados, é
# exactamente onde uma segunda FS real nasceria.
#
# **O que a frase tem de dizer, e diz:** que RECONCILIAR ainda a pode salvar
# (essa procura o documento pela referência que a emissão TERIA usado,
# `ext_ref_determinista` — a mesma fórmula), que LIBERTAR não a resolve e
# porquê, e que se o Vendus não tiver nada esta conta não se resolve em ecrã
# nenhum: guarda-se a referência e leva-se a quem mantém o sistema.
_MSG_CONTA_ESQUECIDA_RESERVA_ESTRAGADA = (
    "Esta conta tem uma reserva fiscal ESTRAGADA: ficou sem referência "
    "externa (`ext_ref`), que é o campo por onde se procura no Vendus. Não se "
    "arruma aqui — pode ter uma Fatura Simplificada real do lado da AT — e "
    "também NÃO se liberta em Reservas Fiscais Presas: libertar exige que "
    "alguém confirme no Vendus que não saiu documento nenhum para a "
    "referência, e sem referência não há o que procurar. O que ainda a pode "
    "salvar é Reconciliar, nessa mesma lista: essa procura o documento pela "
    "referência que a emissão teria usado e, se ele existir, traz a fatura "
    "para o sistema. Se o Vendus não tiver nada para esta venda, ela não se "
    "resolve em ecrã nenhum: guarde a referência desta conta e leve-a a quem "
    "mantém o sistema. Nada foi alterado."
)


async def _contas_esquecidas(db) -> list:
    """Todas as contas que ficaram `aberta` num turno que já não está aberto.

    **A pergunta começa pelas VENDAS e não pelas sessões**, e é o contrário do
    que parece: as sessões que não estão abertas são TODAS as que alguma vez
    existiram (uma por caixa e por dia, para sempre), e as vendas `aberta` são
    um punhado — as que estão mesmo em curso agora, mais estas. Começar pelas
    sessões era varrer um ano de turnos para encontrar duas contas.

    Uma sessão pode aparecer muitas vezes seguidas nesta lista (as partes de
    uma conta repartida são todas do mesmo turno), por isso as sessões e as
    caixas lêem-se UMA vez cada e ficam em memória durante a passagem — o
    mesmo cuidado de `_nome_dos_dispositivos`.

    **O tecto (`_LIMITE_CONTAS_ESQUECIDAS`) corta pelo lado certo.** A
    ordenação é `criada_em` ASCENDENTE e é feita antes do corte, por isso o
    que fica de fora é o mais RECENTE — que é, quase sempre, o turno que está
    a decorrer e que esta lista deita fora a seguir. As esquecidas, essas, são
    as mais velhas: entram sempre. A conta ENTREGUE AO GESTOR é a única desta
    lista que pode ser de hoje, e cai do lado certo do corte pela mesma razão:
    o tecto só morde com centenas de contas abertas ao mesmo tempo, e nessa
    altura o problema já não é este ecrã.

    O valor sai do `_totais` de `venda.py` (por `por_resolver`) e nunca de uma
    soma escrita aqui, e uma conta que já não se consegue somar entra na mesma
    com o valor a `None`: a regra é a de `_contas_abertas_da_sessao` — o que
    não se pode perder é a EXISTÊNCIA dela, e "não sabemos quanto vale" é uma
    resposta honesta que o gestor consegue levar a quem lá estava."""
    # **O predicado é de `por_resolver.contas_por_resolver`, e já não daqui** —
    # a MESMA função do travão, do diálogo e do balcão. Esta lista perguntava
    # por `{"estado": "aberta"}` e por isso não via nem a mãe `separada` sem
    # partes nem a reserva órfã: as duas famílias de dinheiro que os outros
    # leitores viam e esta não. Medido depois de o gestor carregar em LIBERTAR
    # numa mãe de 11,64 €: `/fiscal/reservas-presas` 0, esta lista 0, o
    # diálogo 0,00 € e um Z assinado a dizer «por cobrar 0,00 €».
    #
    # **O âmbito é TODAS as sessões** (`sessao_ids=None`), e continua a não ser
    # um varrimento: as duas leituras são as mesmas que esta lista já fazia —
    # as vendas em estado não terminal (um punhado: as que estão mesmo em curso
    # agora, mais estas) e as reservas por resolver
    # (`{"documento_id": None}`, o filtro barato de `listar_reservas_presas`).
    # Começar pelas SESSÕES é que seria varrer um ano de turnos para encontrar
    # duas contas.
    from .por_resolver import contas_por_resolver

    itens = await contas_por_resolver(db, None)

    sessoes: Dict = {}
    caixas: Dict = {}
    saida = []
    for item in itens:
        venda = item["venda"] or {}
        sessao_id = item["sessao_id"]
        if sessao_id not in sessoes:
            sessoes[sessao_id] = await db[COLECOES["sessoes_caixa"]].find_one(
                {"id": sessao_id}, {"_id": 0}
            )
        sessao = sessoes[sessao_id]
        # A sessão ABERTA é o turno a decorrer: essa conta está no ecrã de
        # alguém neste instante e não é um esquecimento. Uma sessão que
        # desapareceu (`None`) entra: é dinheiro sem turno nenhum, que é ainda
        # mais invisível do que o resto.
        #
        # **A EXCEPÇÃO, e é ela que fecha o buraco da conta que ressuscitava.**
        # Uma conta ENTREGUE AO GESTOR (`venda.py::entregar_ao_gestor`) não
        # está no ecrã de ninguém — foi tirada do balcão de propósito, e a
        # marca é a prova gravada disso. Enquanto esta lista a excluísse por
        # causa do turno estar aberto, ela não aparecia em sítio NENHUM onde
        # alguém a fosse procurar: nem em `/pos/venda/aberta`, nem em
        # `/pos/venda/repartidas`, nem em `/fiscal/reservas-presas` assim que o
        # gestor libertasse a reserva. Ficava só no Z, horas depois. A frase
        # que estava aqui — «essa conta está no ecrã de alguém neste instante»
        # — deixou de ser verdade para esta família, e é para ela que a lista
        # existe.
        # **E a mãe `separada` sem partes, e a reserva órfã, entram com o turno
        # ABERTO.** Pela mesma razão da entrega: não estão no ecrã de ninguém.
        # A mãe separada não volta ao balcão (`GET /pos/venda/aberta` responde
        # `null` sobre ela, e `alterar`/`cancelar` respondem 409); a reserva
        # órfã não tem venda nenhuma para pôr num ecrã. Deixá-las cá fora
        # enquanto o turno estivesse aberto era repetir, para elas, o buraco
        # que a entrega já tinha fechado.
        # `em_curso_no_balcao` é o atributo que o PREDICADO já calculou (a
        # conta `aberta`, não entregue). Estava aqui reescrito à mão
        # (`motivo == "conta_aberta" and not entregue`) — a mesma decisão em
        # dois sítios, que é a forma como esta família de defeitos nasce, e a
        # mesma que `arrumar_conta_esquecida` tem de fazer para o botão e a
        # lista não poderem discordar.
        if (item["em_curso_no_balcao"] and sessao is not None
                and sessao.get("estado") == "aberta"):
            continue

        caixa_id = venda.get("caixa_id")
        if caixa_id not in caixas:
            caixas[caixa_id] = await db[COLECOES["caixas"]].find_one(
                {"id": caixa_id}, {"_id": 0}
            )
        caixa = caixas[caixa_id] or {}

        saida.append({
            "id": item["id"],
            "loja_id": item["loja_id"],
            "total": item["total"],
            "criada_em": item["criada_em"],
            "conta_mae_id": item["conta_mae_id"],
            # PORQUÊ é que está aqui, e em que estado ficou a venda — as
            # mesmas duas chaves de `_contas_abertas_da_sessao`, e pela mesma
            # razão: "cobre-a ou dê-a por perdida" não é a instrução certa
            # para uma reserva sem venda nenhuma. Ver `por_resolver`.
            "motivo": item["motivo"],
            "estado_da_venda": item["estado_da_venda"],
            "caixa_id": caixa_id,
            "caixa_nome": caixa.get("nome"),
            "sessao_id": sessao_id,
            # `None` quando a sessão desapareceu da base — e é uma informação,
            # não um buraco: quem lê tem de poder distinguir "o turno fechou"
            # de "não há turno nenhum onde procurar".
            "sessao_estado": (sessao or {}).get("estado"),
            "sessao_fechada_em": (sessao or {}).get("fechada_em"),
            "sessao_fechada_por": (sessao or {}).get("fechada_por"),
            # Quem estava a picar. É por aqui que o gestor sabe a quem
            # perguntar o que aconteceu àquele cliente.
            "operador_id": item["operador_id"],
            "dispositivo_id": item["dispositivo_id"],
            # A que NÃO se arruma por aqui: tem uma reserva fiscal e pode ter
            # uma FS real do lado da AT. Aparece na mesma (o dinheiro não pode
            # ficar invisível), marcada, e o ecrã manda-o ao card de cima.
            "reserva_fiscal_por_resolver": item["tem_reserva_viva"],
            # E se essa reserva está ESTRAGADA (sem `ext_ref`): sem isto o
            # ecrã desenhava-lhe o bloco genérico «resolva a reserva na lista
            # acima e volte aqui», e voltar traz a mesma linha — LIBERTAR
            # responde-lhe 409. Ver `_MSG_CONTA_ESQUECIDA_RESERVA_ESTRAGADA`.
            "reserva_fiscal_estragada": item["reserva_sem_ext_ref"],
            # A que chegou aqui pela porta NOVA: a operadora entregou-a, e o
            # turno dela pode ainda estar a decorrer. Sem estas duas chaves, o
            # gestor via uma conta de hoje no meio das esquecidas de ontem sem
            # perceber porquê — e não sabia a quem perguntar o que aconteceu
            # àquele cliente.
            "entregue_ao_gestor_em": item["entregue_ao_gestor_em"],
            "entregue_ao_gestor_por": venda.get("entregue_ao_gestor_por"),
        })
    return saida


@router.get("/caixa/contas-esquecidas")
async def listar_contas_esquecidas(_: Dict = Depends(gestor_atual)) -> list:
    """As contas por cobrar que já não têm ninguém no POS que lhes chegue: as
    de turnos JÁ FECHADOS, e as que a operadora ENTREGOU ao gestor (essas
    aparecem mesmo com o turno a decorrer — ver `_contas_esquecidas`) — o
    leitor que o
    `contas_abertas` do Z nunca teve.

    Rota de GESTÃO (`gestor_atual`) e não do POS, e sem prefixo `/pos/`: ver
    o comentário desta secção. Devolve todas as lojas, como
    `fiscal.listar_reservas_presas` — é o ecrã que filtra, e o gestor de
    várias lojas precisa de ver as várias.

    Só leitura. Nada aqui mexe numa sessão fechada: um Z assinado não se
    reabre para nada, e muito menos para uma listagem."""
    return await _contas_esquecidas(obter_db())


@router.post("/caixa/contas-esquecidas/{venda_id}/arrumar")
async def arrumar_conta_esquecida(
    venda_id: str, gestor: Dict = Depends(gestor_atual)
) -> dict:
    """Dá por perdida uma conta que o predicado declara POR RESOLVER e que já
    não tem ninguém no POS que lhe chegue: passa-a a `cancelada`, com o nome
    de quem o decidiu.

    **A regra desta ronda, e é ela que decide tudo o que está aqui em baixo:
    toda a conta que `por_resolver.contas_por_resolver` declara por resolver
    tem de ter pelo menos uma acção EXECUTÁVEL que a resolva.** Uma lista que
    mostra uma linha, desenha-lhe um botão e devolve 409 quando ele é
    carregado — e a recarga traz a mesma linha de volta — é um ciclo fechado
    sobre si próprio, e é pior do que não ter botão nenhum.

    Medido, antes desta ronda, sobre uma mãe `separada` sem partes de 11,64 €:
    sete rotas e ZERO saídas, com o turno aberto e com o turno fechado —
    `arrumar` 409 «Esta conta já não está aberta», alterar 409, cancelar 409,
    `GET /pos/venda/aberta` `null`, `GET /pos/venda/repartidas` `[]`. E a
    mensagem que o próprio sistema escrevia (`fiscal._MSG_LIBERTAR_A_SEGUIR_-
    REPARTIDA`) mandava o gestor «resolva-a aqui, em Contas por Resolver — dê-a
    por perdida se ninguém a pagou»: uma saída nomeada, zero executáveis.

    **O que passou a poder arrumar-se**, e é a leitura directa da regra:

    - `conta_aberta` — a de sempre;
    - `mae_separada_sem_partes` — a divisão que morreu a meio. O POS recusa-a
      toda (`_garante_aberta` responde 409 a alterar e a cancelar) e ela nem
      chega ao ecrã: se não for aqui, não é em lado nenhum.

    **O que continua a NÃO se arrumar aqui, e cada um com a sua saída
    nomeada:**

    - `emissao_viva` — vai primeiro a Reservas Fiscais Presas, e é lá que se
      descobre se saiu uma FS real. LIBERTAR e Reconciliar existem e correm;
    - `estado_desconhecido` — não tem saída nenhuma, e por isso deixou de ser
      tratada como as outras: tem nome e texto próprios
      (`_MSG_CONTA_ESQUECIDA_ESTADO_DESCONHECIDO`), e o ecrã não lhe desenha
      botão nenhum. Ver lá o porquê.

    **A pergunta é feita ao MESMO predicado que desenhou a lista**
    (`por_resolver.contas_por_resolver`), e não a um conjunto de condições
    reescrito aqui: era assim que o botão e a lista discordavam — a lista
    passou a mostrar a mãe `separada` e este botão continuava a exigir
    `estado == "aberta"`. Custa uma leitura das vendas em estado não terminal
    (um punhado) por clique, que é exactamente a leitura que a lista ao lado
    já fez.

    **Porque é que existe um botão, e não só uma lista.** Uma lista que nunca
    se esvazia deixa de ser lida — e a partir daí volta a haver dinheiro
    invisível, só que agora com um ecrã por cima a fingir o contrário. O que
    se guarda é a DIRECÇÃO do caminho fácil: a acção destrutiva pede uma
    declaração explícita no ecrã (o mesmo desenho de LIBERTAR, em
    `FatReservasPresas`), porque cancelar declara "isto nunca foi pago" e isso
    pode ser falso — o cliente pode ter pago em dinheiro e a operadora
    esquecido-se de finalizar. Primeiro pergunta-se a quem lá estava; só
    depois se arruma.

    **O que ela NÃO faz: mexer no Z.** O Z daquele turno já registou esta
    conta como ficando por cobrar, com o valor que ela tinha
    (`_contas_abertas_da_sessao`), e continua a dizer exactamente isso — que é
    a verdade do turno. Cancelar não muda o valor de nada nem faz nascer nada:
    escreve só o desfecho, para o dinheiro deixar de estar em suspenso.

    **A escrita é a do POS, não uma segunda cópia dela.** Delega em
    `venda._cancelar_conta` — a mesma função que `venda.cancelar_venda` usa —,
    e é isso que lhe dá de graça a disciplina toda que lá está: a escrita
    condicionada ao estado que se leu (o `matched_count` decide, não a
    leitura), a segunda pergunta pela reserva DEPOIS de escrever, e a
    compensação que repõe esse mesmo estado se uma reserva aparecer no meio.
    Uma reescrita disto aqui era garantir que um dia divergiam — e a metade que
    divergisse era a que mexe num documento fiscal. O que muda de um chamador
    para o outro é só QUEM pode ser cancelado, e essa decisão é de cada lado.

    O `operador` que se lhe passa é o GESTOR vestido de operador: a loja vem
    da própria venda (o gestor não tem uma), e o `nome` é o email dele, que é
    a identidade que o backoffice conhece. Fica em `cancelada_por` e distingue-
    se sozinho de um nome próprio de operadora ao balcão.

    As cinco recusas, todas antes de qualquer escrita:
    - a conta já não está por resolver (alguém a cobrou, cancelou ou repartiu
      entretanto — ou nunca existiu, e aí é 404);
    - o turno DELA ainda está aberto E ela ainda está EM CURSO NO BALCÃO —
      isso resolve-se no POS, por quem lá está, e não aqui. É o MESMO
      `em_curso_no_balcao` por que a lista se filtra, e por isso a linha que o
      gestor vê é exactamente a linha que este botão aceita. Uma conta
      ENTREGUE AO GESTOR, e a mãe `separada`, não caem nesta recusa: essas já
      não têm ninguém no POS que lhes chegue;
    - o turno DELA está a fechar-se neste instante — o Z está a somar a lista
      onde esta conta entra, e cancelá-la agora fazia-a desaparecer dele (ver
      `_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER`);
    - tem uma reserva fiscal por resolver — essa vai primeiro a Reservas
      Fiscais Presas, e é lá que se descobre se saiu uma FS real;
    - está num estado que este sistema não conhece — ver
      `_MSG_CONTA_ESQUECIDA_ESTADO_DESCONHECIDO`."""
    from .por_resolver import MOTIVO_ESTADO_DESCONHECIDO, contas_por_resolver
    from .venda import _cancelar_conta

    db = obter_db()
    item = next(
        (i for i in await contas_por_resolver(db, None) if i["id"] == venda_id),
        None,
    )
    if item is None:
        # A distinção interessa a quem está a olhar para o ecrã: "não existe"
        # e "já foi resolvida" mandam-no a sítios diferentes. Uma mãe
        # `separada` COM partes cai aqui de propósito — ela está resolvida, e
        # quem se cobra são as partes.
        existe = await db[COLECOES["vendas"]].find_one(
            {"id": venda_id}, {"_id": 0, "id": 1})
        raise HTTPException(
            status_code=409 if existe else 404,
            detail=(_MSG_CONTA_ESQUECIDA_JA_RESOLVIDA if existe
                    else _MSG_CONTA_ESQUECIDA_INEXISTENTE),
        )

    if item["tem_reserva_viva"]:
        # As três frases são a MESMA recusa com três verdades diferentes por
        # baixo, e uma frase que nomeie a saída de outra família é um beco: a
        # estragada não se liberta, a órfã não se reconcilia.
        raise HTTPException(status_code=409, detail=(
            _MSG_CONTA_ESQUECIDA_RESERVA_ESTRAGADA
            if item["reserva_sem_ext_ref"]
            else _MSG_CONTA_ESQUECIDA_TRAVADA_SEM_VENDA
            if item["venda"] is None
            else _MSG_CONTA_ESQUECIDA_TRAVADA
        ))
    if item["motivo"] == MOTIVO_ESTADO_DESCONHECIDO:
        raise HTTPException(
            status_code=409,
            detail=_MSG_CONTA_ESQUECIDA_ESTADO_DESCONHECIDO % item["estado_da_venda"],
        )

    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": item["sessao_id"]})
    # A recusa do turno ABERTO é sobre quem está EM CURSO NO BALCÃO, e é a
    # razão de ser da marca de entrega: uma conta ENTREGUE AO GESTOR
    # (`venda.py::entregar_ao_gestor`) já NÃO se resolve no POS — foi tirada
    # do balcão precisamente porque a operadora não a consegue cobrar nem
    # cancelar. Mandá-la de volta a "quem lá está" era nomear uma saída que
    # não existe. Pela MESMA razão, a mãe `separada` sem partes também não cai
    # aqui: o POS recusa-lhe tudo e ela nem aparece no ecrã.
    if (item["em_curso_no_balcao"] and sessao is not None
            and sessao.get("estado") == "aberta"):
        raise HTTPException(
            status_code=409, detail=_MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO)
    if sessao is not None and sessao.get("estado") == "a_fechar":
        raise HTTPException(
            status_code=409, detail=_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER)

    # `item["venda"]` nunca é `None` aqui: o único item do predicado que pode
    # não ter venda é a reserva órfã, e essa traz sempre `tem_reserva_viva`,
    # que foi recusado lá em cima.
    return await _cancelar_conta(db, item["venda"], operador={
        "loja_id": item["loja_id"],
        "operador_id": gestor.get("user_id"),
        "nome": gestor.get("email"),
    })
