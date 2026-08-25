"""**Os clientes que pedem fatura com NIF.**

Pedido do dono numa frase: «clientes — nada mais é do que salvar os clientes
que pedirem fatura com NIF».

## Quem é um cliente aqui, e porque não há um botão de "criar cliente"

Um cliente **nasce de uma compra**, nunca de um formulário: é um NIF que
apareceu numa Fatura Simplificada. Isso não é uma simplificação — é o que
impede as duas listas de existirem. Uma tabela de clientes escrita à mão fica
cheia de gente que nunca comprou e a faltar quem comprou ontem, e a pergunta
«quanto é que este cliente já gastou?» passa a ter duas respostas.

Por isso a LISTA é derivada dos documentos, e a colecção `fat_clientes` guarda
só o que os documentos não sabem: o **nome**, o email, o telefone e uma nota.
O NIF é a chave, e é o único campo que não se edita — mudá-lo era passar as
compras de uma pessoa para outra.

## O dinheiro

Somado a partir de `fat_documentos` (nunca das vendas), com as **notas de
crédito a subtrair** — a mesma regra do resumo do ecrã de Documentos e do
rodapé dos relatórios do Vendus. As contagens vão separadas: faturas e
rectificações não se somam no mesmo número.

Tudo em cêntimos inteiros.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()

# Tecto do que se agrega de uma vez. Só entram documentos COM NIF — que são uma
# fracção pequena do total (a esmagadora maioria é Consumidor Final) — por isso
# isto são muitos meses de cinco lojas. Passando daí, a resposta diz que está
# truncada em vez de apresentar um parcial como se fosse tudo.
_TECTO = 20000


def _centimos(valor) -> int:
    return int(round(float(valor or 0) * 100))


class ClienteEntrada(BaseModel):
    """O que se pode dizer sobre um cliente — e o NIF não está aqui.

    Ele é a chave (vem no caminho) e não se edita: trocá-lo não era corrigir um
    nome, era passar as compras de uma pessoa para outra."""

    nome: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=160)
    telefone: Optional[str] = Field(default=None, max_length=40)
    notas: Optional[str] = Field(default=None, max_length=500)


def _resumo_por_nif(documentos: List[Dict]) -> Dict[str, Dict]:
    """As compras de cada NIF: quantas, quanto e quando foi a última.

    Puro de propósito — é a única conta desta secção e a que decide os números
    que o gestor lê. As NC subtraem no dinheiro e contam à parte; a data da
    última compra é a do documento mais recente, seja ele fatura ou nota."""
    por_nif: Dict[str, Dict] = {}
    for doc in documentos:
        nif = doc.get("cliente_nif")
        if not nif:
            continue
        actual = por_nif.setdefault(nif, {
            "nif": nif, "faturas": 0, "notas_credito": 0,
            "centimos": 0, "ultima_compra_em": None,
        })
        if doc.get("tipo") == "NC":
            actual["notas_credito"] += 1
            actual["centimos"] -= _centimos(doc.get("total"))
        else:
            actual["faturas"] += 1
            actual["centimos"] += _centimos(doc.get("total"))
        quando = doc.get("emitido_em")
        if quando and (actual["ultima_compra_em"] is None
                       or quando > actual["ultima_compra_em"]):
            actual["ultima_compra_em"] = quando
    return por_nif


async def _identidades(db, nifs: List[str]) -> Dict[str, Dict]:
    if not nifs:
        return {}
    fichas = await (
        db[COLECOES["clientes"]]
        .find({"nif": {"$in": nifs}}, {"_id": 0})
        .to_list(len(nifs))
    )
    return {f["nif"]: f for f in fichas}


def _cliente_publico(resumo: Dict, ficha: Optional[Dict]) -> Dict:
    return {
        "nif": resumo["nif"],
        "nome": (ficha or {}).get("nome"),
        "email": (ficha or {}).get("email"),
        "telefone": (ficha or {}).get("telefone"),
        "notas": (ficha or {}).get("notas"),
        "faturas": resumo["faturas"],
        "notas_credito": resumo["notas_credito"],
        "total": resumo["centimos"] / 100.0,
        "ultima_compra_em": resumo["ultima_compra_em"],
    }


@router.get("/clientes")
async def listar_clientes(
    q: Optional[str] = None, _: dict = Depends(gestor_atual)
) -> dict:
    """Os clientes que já pediram fatura com NIF, do que mais gastou para o
    que menos gastou.

    A pesquisa é por NIF **ou** por nome — quem procura não sabe (nem tem de
    saber) que o nome vive numa ficha à parte e o NIF no documento.
    """
    db = obter_db()
    documentos = await (
        db[COLECOES["documentos"]]
        .find({"cliente_nif": {"$ne": None}},
              {"_id": 0, "cliente_nif": 1, "total": 1, "tipo": 1, "emitido_em": 1})
        .to_list(_TECTO)
    )
    por_nif = _resumo_por_nif(documentos)
    fichas = await _identidades(db, list(por_nif))

    clientes = [_cliente_publico(r, fichas.get(nif)) for nif, r in por_nif.items()]
    if q:
        procurado = q.strip().lower()
        clientes = [
            c for c in clientes
            if procurado in c["nif"].lower()
            or procurado in (c["nome"] or "").lower()
        ]
    clientes.sort(key=lambda c: c["total"], reverse=True)
    return {
        "clientes": clientes,
        "truncado": len(documentos) >= _TECTO,
    }


@router.get("/clientes/{nif}")
async def obter_cliente(nif: str, _: dict = Depends(gestor_atual)) -> dict:
    """Um cliente: a ficha e o que ele já comprou.

    Um NIF que nunca comprou dá 404 — não há aqui clientes sem compras, e
    inventar um em branco fazia parecer que a lista tinha buracos."""
    db = obter_db()
    documentos = await (
        db[COLECOES["documentos"]]
        .find({"cliente_nif": nif},
              {"_id": 0, "cliente_nif": 1, "total": 1, "tipo": 1, "emitido_em": 1})
        .to_list(_TECTO)
    )
    por_nif = _resumo_por_nif(documentos)
    if nif not in por_nif:
        raise HTTPException(status_code=404, detail="Este NIF ainda não comprou nada.")
    fichas = await _identidades(db, [nif])
    return _cliente_publico(por_nif[nif], fichas.get(nif))


@router.put("/clientes/{nif}")
async def gravar_cliente(
    nif: str, dados: ClienteEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    """Põe um nome (e o contacto) num NIF que já comprou.

    **Só se grava sobre quem comprou.** Um `upsert` livre transformava este
    ecrã numa agenda de contactos com gente que nunca cá entrou — e a lista de
    clientes deixava de responder à pergunta para que existe.
    """
    db = obter_db()
    comprou = await db[COLECOES["documentos"]].find_one(
        {"cliente_nif": nif}, {"_id": 0, "id": 1})
    if not comprou:
        raise HTTPException(status_code=404, detail="Este NIF ainda não comprou nada.")
    await db[COLECOES["clientes"]].update_one(
        {"nif": nif}, {"$set": dict(dados.model_dump(), nif=nif)}, upsert=True
    )
    return await obter_cliente(nif, _=_)
