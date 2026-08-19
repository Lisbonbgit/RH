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
_MSG_SESSAO_FECHADA_ENTRETANTO = (
    "Esta sessão foi fechada por outro pedido entretanto — não é possível "
    "registar o movimento."
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


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    return {"caixas": caixas, "caixa": caixa, "sessao_aberta": sessao, "ultimo_fecho": ultimo_fecho}


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


@router.post("/pos/caixa/movimento", status_code=201)
async def registar_movimento(
    dados: PedidoMovimento, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    # I2 ("o mesmo raciocínio para um movimento a cruzar-se com o fecho"):
    # entre a leitura acima (_sessao_aberta) e este ponto, um fecho
    # concorrente pode ter fechado a sessão — o Z desse fecho já foi
    # calculado sem este movimento. Uma escrita CONDICIONAL a
    # {"estado": "aberta"}, mesmo sem alterar nada de essencial, é o mais
    # perto que se chega de uma confirmação atómica sem transacções
    # multi-documento: se não encontrar a sessão ainda aberta, recusa — o
    # dinheiro deste movimento nunca fica sem fecho nenhum que o explique.
    confirmacao = await db[COLECOES["sessoes_caixa"]].update_one(
        {"id": sessao["id"], "estado": "aberta"}, {"$set": {"estado": "aberta"}}
    )
    if confirmacao.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_FECHADA_ENTRETANTO)

    movimento = {
        "id": str(uuid.uuid4()),
        "sessao_id": sessao["id"],
        "tipo": dados.tipo,
        "valor": dados.valor,
        "motivo": dados.motivo,
        "por": _quem(operador),
        "em": _agora(),
    }
    await db[COLECOES["movimentos_caixa"]].insert_one(dict(movimento))
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
    # pode passar a `emitida` (o núcleo fiscal recusa), por isso o que se lê
    # aqui é definitivo. Lidas de fresco em cada tentativa de fecho — uma
    # retoma de um fecho interrompido recalcula tudo do zero, nunca reaproveita
    # números de uma tentativa anterior.
    movimentos = await db[COLECOES["movimentos_caixa"]].find(
        {"sessao_id": sessao["id"]}
    ).to_list(10000)
    vendas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao["id"], "estado": "emitida"}
    ).to_list(10000)

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
