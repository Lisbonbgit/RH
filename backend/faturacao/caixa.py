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
_MSG_CAIXA_JA_ABERTA = "Esta caixa já tem uma sessão aberta."
_MSG_SEM_SESSAO_ABERTA = "Esta caixa não tem nenhuma sessão aberta."


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
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

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
    await db[COLECOES["sessoes_caixa"]].update_one({"id": sessao["id"]}, {"$set": atualizacao})

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
