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


async def _sessao_aberta(db, caixa_id: str) -> Dict:
    """A resolução central do módulo: a ÚNICA sessão aberta desta caixa (o
    índice único parcial em db.py garante que nunca há mais do que uma)."""
    sessao = await db[COLECOES["sessoes_caixa"]].find_one(
        {"caixa_id": caixa_id, "estado": "aberta"}
    )
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

    sessao = await db[COLECOES["sessoes_caixa"]].find_one(
        {"caixa_id": caixa["id"], "estado": "aberta"}, {"_id": 0}
    )
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

    aberta = await db[COLECOES["sessoes_caixa"]].find_one(
        {"caixa_id": dados.caixa_id, "estado": "aberta"}
    )
    if aberta:
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
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    # ANTES de somar seja o que for: uma emissão a decorrer numa conta desta
    # sessão ainda vai mudar o que o Z tem de dizer.
    em_emissao = await _venda_com_emissao_viva(db, sessao["id"])
    if em_emissao is not None:
        raise HTTPException(
            status_code=409,
            detail=_MSG_FECHO_COM_EMISSAO_EM_CURSO % em_emissao.get("id"),
        )

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

    # A verificação contra o Vendus é só leitura e NUNCA pode impedir o
    # fecho — apanhada aqui, além da guarda que já existe dentro da própria
    # função (dupla rede de segurança, regra 3 do dono).
    try:
        verificacao_vendus = await _verificar_vendas_dinheiro(db, sessao, vendas_dinheiro)
    except Exception as e:  # noqa: BLE001 — o fecho nunca pode falhar por causa disto
        logger.warning("[faturacao] verificação de fecho contra o Vendus falhou: %s", e)
        verificacao_vendus = {"nao_verificado": "Falha inesperada na verificação."}

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
    # levou). Condicionar a {"estado": "aberta"} e confirmar matched_count
    # é a mesma defesa que o índice único de sessão aberta (db.py) já dá na
    # ABERTURA — aqui aplicada ao FECHO.
    resultado = await db[COLECOES["sessoes_caixa"]].update_one(
        {"id": sessao["id"], "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_FECHO_EM_CONFLITO)

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
    (`SessaoJaNaoAberta`). São as duas necessárias — sem transacções
    multi-documento, uma pergunta antes e uma releitura depois é o mais
    perto que se chega de fechar a janela pelos dois lados."""
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
