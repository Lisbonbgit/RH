"""**Como correu a gaveta de cada loja** — a vista do backoffice.

O dono mostrou os Movimentos de Caixa do Vendus e pediu o mesmo: aberturas,
entradas, saídas e fechos, loja a loja. Duas coisas são deliberadamente
diferentes de lá:

- o Vendus mostra «Fecho de Caixa = valor de abertura + entradas em
  numerário», que é o ESPERADO. Ele não sabe quanto a funcionária contou na
  gaveta. Nós sabemos — e é o **contado**, com a diferença para o esperado, que
  responde à pergunta que interessa: bateu certo ou não?
- o Vendus tem botões «Alterar» na abertura e no fecho. **Aqui não há por
  onde**, e é de propósito: um Z assinado é o retrato de um instante, e
  reescrevê-lo depois destrói a única prova de que a gaveta bateu certo nesse
  dia. Um valor errado corrige-se com um MOVIMENTO, que fica registado com o
  nome de quem o fez. Há um teste a garantir que este módulo não ganha uma
  rota de escrita por distracção.

**Nenhuma soma nova.** Tudo sai de `caixa._resumo_do_turno` — a mesma função
que serve o Ponto de Caixa, o Z e o relatório diário — e os produtos vendidos
de `relatorio_diario._artigos_vendidos`. Uma quarta contabilidade sobre a mesma
gaveta era a maneira mais certa de um dia este ecrã e o papel que a funcionária
assinou discordarem, com alguém a ter de escolher em qual acreditar.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import gestor_atual
from .caixa import _resumo_do_turno
from .db import COLECOES, obter_db
from .relatorio_diario import _artigos_vendidos, _dia_do_documento

router = APIRouter()

# Tecto de turnos numa listagem. Cinco lojas × um turno por dia dão ~150 por
# mês; 2000 são mais de um ano de histórico e ainda cabem numa resposta.
TECTO = 2000


def _nome(quem) -> Optional[str]:
    """O `aberta_por`/`fechada_por` é o retrato de quem estava lá — um
    dicionário. Um turno antigo pode trazer só o texto."""
    if isinstance(quem, dict):
        return quem.get("nome") or quem.get("email")
    return quem or None


def _hora(instante: Optional[str]) -> Optional[str]:
    """A hora LOCAL, para o ecrã. O dia inteiro sai de `_dia_do_documento`,
    que já faz a conversão de fuso com todo o cuidado — aqui só se lhe pede a
    hora do mesmo instante, pela mesma porta, para as duas nunca divergirem.
    """
    if not instante:
        return None
    from datetime import datetime, timezone

    from .periodos import LISBON_TZ
    try:
        lido = datetime.fromisoformat(str(instante).replace("Z", "+00:00"))
    except ValueError:
        return None
    if lido.tzinfo is None:
        lido = lido.replace(tzinfo=timezone.utc)
    return lido.astimezone(LISBON_TZ).strftime("%H:%M")


async def _partes_do_turno(db, sessao: Dict) -> Dict:
    """O que `_resumo_do_turno` precisa, lido para UMA sessão."""
    sessao_id = sessao["id"]
    movimentos = await db[COLECOES["movimentos_caixa"]].find(
        {"sessao_id": sessao_id}, {"_id": 0}).to_list(500)
    vendas = await db[COLECOES["vendas"]].find(
        {"sessao_id": sessao_id}, {"_id": 0}).to_list(5000)
    notas = await db[COLECOES["notas_credito"]].find(
        {"sessao_id": sessao_id}, {"_id": 0}).to_list(500)
    return {"sessao": sessao, "movimentos": movimentos,
            "vendas": vendas, "notas_credito": notas}


def _fecho(sessao: Dict, resumo: Dict) -> Dict:
    """O fecho como ele é, sem preencher o que ninguém contou.

    Um turno aberto traz o esperado (que se calcula) e `None` no contado (que
    se conta). Pôr lá o esperado, ou um zero, era escrever no ecrã uma
    contagem que não aconteceu.
    """
    aberto = sessao.get("estado") == "aberta"
    contado = None if aberto else sessao.get("contado")
    return {
        "estado": "aberto" if aberto else "fechado",
        "hora": _hora(sessao.get("fechada_em")),
        "por": _nome(sessao.get("fechada_por")),
        "esperado": resumo["esperado"],
        "contado": contado,
        # A diferença sai da subtracção dos dois números que estão à vista, e
        # não de um campo gravado: assim o ecrã nunca mostra um par que não
        # bate com a pastilha ao lado (o defeito que o email do relatório
        # diário teve, ver `relatorio_diario._caixa_das_sessoes`).
        "diferenca": None if contado is None else round(
            float(contado) - float(resumo["esperado"] or 0), 2),
    }


@router.get("/caixa/historico")
async def historico(
    loja_id: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    _: dict = Depends(gestor_atual),
) -> List[dict]:
    """Os turnos do período, do mais recente para o mais antigo.

    `de`/`ate` são dias (`2026-08-01`) e comparam-se contra `aberta_em`, que é
    uma string ISO em UTC — a comparação de texto funciona porque o formato é
    ordenável, e o `ate` leva o dia INTEIRO (até ao fim dele) para o filtro
    não deixar de fora o turno de hoje só por ter começado às 12h.
    """
    db = obter_db()
    filtro: Dict = {}
    if loja_id:
        filtro["loja_id"] = loja_id
    if de or ate:
        janela = {}
        if de:
            janela["$gte"] = de
        if ate:
            janela["$lte"] = ate + "T23:59:59.999999+99:99"
        filtro["aberta_em"] = janela

    sessoes = await db[COLECOES["sessoes_caixa"]].find(filtro, {"_id": 0}) \
        .sort("aberta_em", -1).to_list(TECTO)

    lojas = {l["id"]: l.get("nome") for l in await db[COLECOES["lojas"]]
             .find({}, {"_id": 0, "id": 1, "nome": 1}).to_list(200)}
    caixas = {c["id"]: c.get("nome") for c in await db[COLECOES["caixas"]]
              .find({}, {"_id": 0, "id": 1, "nome": 1}).to_list(200)}

    saida = []
    for sessao in sessoes:
        partes = await _partes_do_turno(db, sessao)
        resumo = _resumo_do_turno(
            sessao, partes["movimentos"], partes["vendas"], partes["notas_credito"])
        saida.append({
            "id": sessao["id"],
            "loja_id": sessao.get("loja_id"),
            "loja_nome": lojas.get(sessao.get("loja_id")) or sessao.get("loja_id"),
            "caixa_nome": caixas.get(sessao.get("caixa_id")) or sessao.get("caixa_id"),
            "dia": _dia_do_documento({"emitido_em": sessao.get("aberta_em")}),
            "abertura": {
                "hora": _hora(sessao.get("aberta_em")),
                "valor": sessao.get("fundo"),
                "por": _nome(sessao.get("aberta_por")),
            },
            "fecho": _fecho(sessao, resumo),
            # O número grande do cartão: o que a loja facturou naquele turno.
            "faturacao": resumo["total_faturado"],
            "documentos": resumo["quantos_documentos"],
        })
    return saida


@router.get("/caixa/historico/{sessao_id}")
async def detalhe_do_turno(sessao_id: str, _: dict = Depends(gestor_atual)) -> dict:
    """Um turno por dentro — os mesmos números do Z, mais o que ele não mostra.

    O Z é o papel que sai da impressora no fecho; isto é o mesmo turno visto
    do escritório, com a lista dos movimentos (com motivo e autor) e os
    produtos vendidos, que no papel não cabiam.
    """
    db = obter_db()
    sessao = await db[COLECOES["sessoes_caixa"]].find_one({"id": sessao_id}, {"_id": 0})
    if not sessao:
        raise HTTPException(status_code=404, detail="Turno não encontrado.")

    partes = await _partes_do_turno(db, sessao)
    resumo = _resumo_do_turno(
        sessao, partes["movimentos"], partes["vendas"], partes["notas_credito"])

    loja = await db[COLECOES["lojas"]].find_one(
        {"id": sessao.get("loja_id")}, {"_id": 0, "nome": 1})
    caixa = await db[COLECOES["caixas"]].find_one(
        {"id": sessao.get("caixa_id")}, {"_id": 0, "nome": 1})

    movimentos = [
        {
            "id": m.get("id"),
            "tipo": m.get("tipo"),
            "valor": m.get("valor"),
            "motivo": m.get("motivo"),
            "por": _nome(m.get("por")),
            "hora": _hora(m.get("em")),
        }
        # Um movimento `por_confirmar` nunca chegou a ser dinheiro (ver
        # `caixa.registar_movimento`): não entrou em soma nenhuma e não pode
        # aparecer aqui a fingir que entrou.
        for m in partes["movimentos"] if not m.get("por_confirmar")
    ]
    movimentos.sort(key=lambda m: m["hora"] or "")

    return {
        "id": sessao["id"],
        "loja_nome": (loja or {}).get("nome") or sessao.get("loja_id"),
        "caixa_nome": (caixa or {}).get("nome") or sessao.get("caixa_id"),
        "dia": _dia_do_documento({"emitido_em": sessao.get("aberta_em")}),
        "abertura": {
            "hora": _hora(sessao.get("aberta_em")),
            "valor": sessao.get("fundo"),
            "por": _nome(sessao.get("aberta_por")),
        },
        "fecho": _fecho(sessao, resumo),
        # Daqui para baixo é o resumo TAL E QUAL — os mesmos nomes e os mesmos
        # valores do Z. Renomear um campo aqui era criar um segundo vocabulário
        # para a mesma gaveta.
        "esperado": resumo["esperado"],
        "entradas": resumo["entradas"],
        "saidas": resumo["saidas"],
        "vendas_dinheiro": resumo["vendas_dinheiro"],
        "pagamentos": resumo["pagamentos"],
        "pagamentos_por_registar": resumo["pagamentos_por_registar"],
        "mapa_imposto": resumo["mapa_imposto"],
        "base_tributavel": resumo["base_tributavel"],
        "iva_total": resumo["iva_total"],
        "total_faturado": resumo["total_faturado"],
        "quantos_documentos": resumo["quantos_documentos"],
        "movimentos": movimentos,
        "artigos": _artigos_vendidos([partes], None),
    }
