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
from .caixa_math import diferenca, esperado, soma_vendas_dinheiro, total_por_tipo
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
    em_emissao = await _venda_com_emissao_viva(db, sessao["id"])
    if em_emissao is not None:
        raise HTTPException(
            status_code=409,
            detail=_MSG_FECHO_COM_EMISSAO_EM_CURSO % em_emissao.get("id"),
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
    em_emissao = await _venda_com_emissao_viva(db, sessao["id"])
    if em_emissao is not None:
        # Desfaz a marca — condicionada a `a_fechar`, para nunca reabrir uma
        # sessão que outro pedido já tenha fechado entretanto. A caixa fica
        # como estava e a funcionária tenta outra vez daqui a uns segundos.
        await db[COLECOES["sessoes_caixa"]].update_one(
            {"id": sessao["id"], "estado": "a_fechar"},
            {"$set": {"estado": "aberta", "fecho_iniciado_em": None}},
        )
        raise HTTPException(
            status_code=409,
            detail=_MSG_FECHO_COM_EMISSAO_EM_CURSO % em_emissao.get("id"),
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
    confirmados = set((sessao_marcada or sessao).get("movimentos_confirmados") or [])
    movimentos = await db[COLECOES["movimentos_caixa"]].find(
        {"sessao_id": sessao["id"]}
    ).to_list(10000)
    # Conta o movimento que está na lista da sessão OU o que foi escrito
    # ANTES desta correcção existir (esses não têm `por_confirmar` nenhum e
    # nunca entraram em lista nenhuma — uma sessão aberta no turno do deploy
    # não pode ver os seus movimentos desaparecer do Z). Fica de fora só o
    # que ficou a meio: inserido, `por_confirmar: True`, e nunca confirmado
    # em sessão nenhuma — dinheiro que ninguém tirou da gaveta, porque quem o
    # pediu levou 409 ou nem chegou a receber resposta.
    movimentos = [
        m for m in movimentos
        if m.get("id") in confirmados or m.get("por_confirmar") is not True
    ]
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

    vendas_dinheiro = soma_vendas_dinheiro(vendas)
    entradas = total_por_tipo(movimentos, "entrada")
    saidas = total_por_tipo(movimentos, "saida")
    esperado_valor = esperado(sessao["fundo"], vendas_dinheiro, movimentos)
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
        "entradas": entradas,
        "saidas": saidas,
        "estado": atualizacao["estado"],
        "fechada_por": fechada_por,
        "fechada_em": fechada_em,
        "contado": dados.contado,
        "esperado": esperado_valor,
        "diferenca": diferenca_valor,
        # SEMPRE presente, mesmo com `quantas: 0` — a mesma regra do
        # `emissao_por_confirmar` em `venda.py`: o ecrã não pode ter de
        # adivinhar se a ausência da chave quer dizer "não ficou nada por
        # cobrar" ou "esta versão do servidor não sabe responder a isso".
        "contas_abertas": contas_abertas,
        "verificacao_vendus": verificacao_vendus,
    }


async def _venda_com_emissao_viva(db, sessao_id: str) -> Optional[Dict]:
    """A primeira conta AINDA ABERTA desta sessão que tenha uma reserva
    fiscal — ou `None`, o caso normal.

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

    A pergunta é feita às contas ABERTAS: a reserva de uma venda `emitida`
    fica lá para sempre de propósito (é ela que sustenta a idempotência,
    `fiscal.py::_gravar_documento`) e travaria o fecho de todas as noites.
    Uma sessão tem um punhado de contas abertas, por isso a leitura é
    pequena e a pergunta pela reserva é uma por conta — nunca um varrimento
    de `fat_refs_fiscais`, que ao fim de um ano tem centenas de milhares de
    reservas resolvidas.

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
    abertas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao_id, "estado": "aberta"}
    ).to_list(1000)
    for venda in abertas:
        reserva = await db[COLECOES["refs_fiscais"]].find_one(
            {"venda_id": venda.get("id")}
        )
        if reserva is not None:
            return venda
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

    **Não é só sobre partes.** A pergunta é feita a TODAS as contas `aberta`
    da sessão: a conta que ficou meia-picada quando o cliente desistiu, a
    conta travada que ficou à espera do gestor, a que a operadora já lhe
    ENTREGOU (`venda.py::entregar_ao_gestor`) e as partes de quem dividiu.
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

    O `import` de `venda.py` é LOCAL pela mesma razão do
    `_verificar_vendas_dinheiro` aqui em baixo: `venda.py` importa deste
    módulo, e um import no topo fechava o ciclo. E é o `_totais` DELE, não uma
    soma escrita aqui — o valor de uma conta sai sempre de
    `precos.linha_de_venda`, em todo o módulo (regra 1 do cabeçalho de
    `venda.py`).
    """
    from .venda import _totais

    abertas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao_id, "estado": "aberta"}
    ).sort("criada_em", 1).to_list(1000)

    nomes = await _nome_dos_dispositivos(
        db, [v.get("dispositivo_id") for v in abertas]
    )

    contas = []
    total = 0.0
    total_que_trava = 0.0
    total_por_cobrar = 0.0
    for venda in abertas:
        try:
            valor = _totais(venda)["total"]
        except Exception as e:  # noqa: BLE001 — o fecho nunca falha por isto
            # Uma linha que `linha_de_venda` já não sabe avaliar (um produto
            # que perdeu o IVA no retrato, uma conta gravada por uma versão
            # anterior) não pode transformar o fecho num 500 — isso mandava a
            # funcionária fechar outra vez uma caixa que não fechou. A conta
            # CONTA-SE na mesma, com o valor a `None`: o que não se pode
            # perder é a existência dela, e "não sabemos quanto vale" é uma
            # resposta honesta que a operadora consegue levar ao gestor.
            logger.warning(
                "[faturacao] não foi possível somar a conta aberta %s da sessão "
                "%s: %s (entra no Z sem valor).", venda.get("id"), sessao_id, e,
            )
            valor = None
        trava = await db[COLECOES["refs_fiscais"]].find_one(
            {"venda_id": venda.get("id")}
        ) is not None
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
        contas.append({
            "id": venda.get("id"),
            "total": valor,
            "criada_em": venda.get("criada_em"),
            # Qual delas é uma PARTE de uma conta repartida, e de qual. É o que
            # distingue "faltou cobrar uma pessoa" de "ficou uma conta a meio"
            # — duas conversas diferentes com o gestor no dia seguinte.
            "conta_mae_id": venda.get("conta_mae_id"),
            # De que POSTO é — ver a docstring. Sempre presentes as duas
            # chaves (o nome a `None` quando o PC já foi revogado), pela
            # regra do `emissao_por_confirmar` em venda.py: quem desenha não
            # pode ter de adivinhar se a ausência quer dizer "não se sabe" ou
            # "esta versão do servidor não responde a isso".
            "dispositivo_id": venda.get("dispositivo_id"),
            "dispositivo_nome": nomes.get(venda.get("dispositivo_id")),
            # A que IMPEDE o fecho, separada das que não impedem nada.
            "trava_o_fecho": trava,
            # A que JÁ NÃO É DO BALCÃO. O ecrã do fecho lista estas contas e
            # manda cobrá-las ou cancelá-las; esta a operadora não consegue
            # fazer nem uma coisa nem outra — é do gestor, e está na lista
            # dele (`GET /caixa/contas-esquecidas`). Sem esta chave, o
            # diálogo do fecho voltava a dar uma instrução que ninguém ali
            # consegue cumprir, que é o mesmo defeito do texto que o
            # `dispositivo_nome` veio corrigir.
            "entregue_ao_gestor": bool(venda.get("entregue_ao_gestor_em")),
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
_MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO = (
    "A caixa desta conta está ABERTA neste momento — esta conta é do turno "
    "que está a decorrer e é no POS que ela se resolve: cobra-se ou "
    "cancela-se no balcão, por quem está lá. Só depois de o turno fechar é "
    "que ela passa a ser um problema de gestão."
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
_MSG_CONTA_ESQUECIDA_TRAVADA = (
    "Esta conta tem uma reserva fiscal por resolver — pode ter uma Fatura "
    "Simplificada real do lado da AT. Não se arruma por aqui: resolva-a "
    "primeiro em Reservas Fiscais Presas (reconciliar, ou libertar depois de "
    "confirmar no Vendus que não saiu documento nenhum) e só então é que se "
    "sabe o que fazer a esta conta."
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

    O valor sai do `_totais` de `venda.py` (import local, o ciclo de sempre) e
    nunca de uma soma escrita aqui, e uma conta que já não se consegue somar
    entra na mesma com o valor a `None`: a regra é a de
    `_contas_abertas_da_sessao` — o que não se pode perder é a EXISTÊNCIA
    dela, e "não sabemos quanto vale" é uma resposta honesta que o gestor
    consegue levar a quem lá estava."""
    from .venda import _totais

    abertas = await db[COLECOES["vendas"]].find(
        {"estado": "aberta"}
    ).sort("criada_em", 1).to_list(_LIMITE_CONTAS_ESQUECIDAS)

    sessoes: Dict = {}
    caixas: Dict = {}
    saida = []
    for venda in abertas:
        sessao_id = venda.get("sessao_id")
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
        entregue = bool(venda.get("entregue_ao_gestor_em"))
        if not entregue and sessao is not None and sessao.get("estado") == "aberta":
            continue

        caixa_id = venda.get("caixa_id")
        if caixa_id not in caixas:
            caixas[caixa_id] = await db[COLECOES["caixas"]].find_one(
                {"id": caixa_id}, {"_id": 0}
            )
        caixa = caixas[caixa_id] or {}

        try:
            valor = _totais(venda)["total"]
        except Exception as e:  # noqa: BLE001 — ver a docstring
            logger.warning(
                "[faturacao] não foi possível somar a conta esquecida %s: %s "
                "(entra na lista sem valor).", venda.get("id"), e,
            )
            valor = None

        saida.append({
            "id": venda.get("id"),
            "loja_id": venda.get("loja_id"),
            "total": valor,
            "criada_em": venda.get("criada_em"),
            "conta_mae_id": venda.get("conta_mae_id"),
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
            "operador_id": venda.get("operador_id"),
            "dispositivo_id": venda.get("dispositivo_id"),
            # A que NÃO se arruma por aqui: tem uma reserva fiscal e pode ter
            # uma FS real do lado da AT. Aparece na mesma (o dinheiro não pode
            # ficar invisível), marcada, e o ecrã manda-o ao card de cima.
            "reserva_fiscal_por_resolver": await db[
                COLECOES["refs_fiscais"]
            ].find_one({"venda_id": venda.get("id")}) is not None,
            # A que chegou aqui pela porta NOVA: a operadora entregou-a, e o
            # turno dela pode ainda estar a decorrer. Sem estas duas chaves, o
            # gestor via uma conta de hoje no meio das esquecidas de ontem sem
            # perceber porquê — e não sabia a quem perguntar o que aconteceu
            # àquele cliente.
            "entregue_ao_gestor_em": venda.get("entregue_ao_gestor_em"),
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
    """Dá por perdida uma conta aberta de um turno já fechado — ou uma que a
    operadora entregou ao gestor, seja qual for o estado do turno: passa-a a
    `cancelada`, com o nome de quem o decidiu.

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
    `venda.cancelar_venda`, e é isso que lhe dá de graça a disciplina toda que
    lá está: a escrita condicionada a `{"estado": "aberta"}` (o `matched_count`
    decide, não a leitura), a segunda pergunta pela reserva DEPOIS de escrever,
    e a compensação que repõe `aberta` se uma reserva aparecer no meio. Uma
    reescrita disto aqui era garantir que um dia divergiam — e a metade que
    divergisse era a que mexe num documento fiscal.

    O `operador` que se lhe passa é o GESTOR vestido de operador: a loja vem
    da própria venda (o gestor não tem uma), e o `nome` é o email dele, que é
    a identidade que o backoffice conhece. Fica em `cancelada_por` e distingue-
    se sozinho de um nome próprio de operadora ao balcão.

    As quatro recusas, todas antes de qualquer escrita:
    - a conta já não está `aberta` (alguém a resolveu entretanto);
    - o turno DELA ainda está aberto E ela ainda é do balcão — isso resolve-se
      no POS, por quem lá está, e não aqui. Uma conta ENTREGUE AO GESTOR não
      cai nesta recusa: essa já não tem ninguém no POS que lhe chegue;
    - o turno DELA está a fechar-se neste instante — o Z está a somar a lista
      onde esta conta entra, e cancelá-la agora fazia-a desaparecer dele (ver
      `_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER`);
    - tem uma reserva fiscal por resolver — essa vai primeiro a Reservas
      Fiscais Presas, e é lá que se descobre se saiu uma FS real."""
    from .venda import cancelar_venda

    db = obter_db()
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if not venda:
        raise HTTPException(status_code=404, detail=_MSG_CONTA_ESQUECIDA_INEXISTENTE)
    if venda.get("estado") != "aberta":
        raise HTTPException(
            status_code=409, detail=_MSG_CONTA_ESQUECIDA_JA_RESOLVIDA)

    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": venda.get("sessao_id")})
    # A recusa do turno ABERTO tem uma excepção, e é a razão de ser da marca:
    # uma conta ENTREGUE AO GESTOR (`venda.py::entregar_ao_gestor`) já NÃO se
    # resolve no POS — foi tirada do balcão precisamente porque a operadora não
    # a consegue cobrar nem cancelar. Mandá-la de volta a "quem lá está" era
    # nomear uma saída que não existe, e a conta ficava sem nenhuma até o turno
    # fechar. É deste par — a lista que passou a mostrá-la com o turno aberto e
    # este botão que passou a poder arrumá-la — que sai a promessa de que ela
    # continua do gestor até ele a resolver.
    if (
        not venda.get("entregue_ao_gestor_em")
        and sessao is not None
        and sessao.get("estado") == "aberta"
    ):
        raise HTTPException(
            status_code=409, detail=_MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO)
    if sessao is not None and sessao.get("estado") == "a_fechar":
        raise HTTPException(
            status_code=409, detail=_MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER)

    if await db[COLECOES["refs_fiscais"]].find_one({"venda_id": venda_id}) is not None:
        raise HTTPException(status_code=409, detail=_MSG_CONTA_ESQUECIDA_TRAVADA)

    return await cancelar_venda(venda_id, operador={
        "loja_id": venda.get("loja_id"),
        "operador_id": gestor.get("user_id"),
        "nome": gestor.get("email"),
    })
