"""Tipos de pagamento do POS.

Um tipo tem um nome livre (o que a funcionária vê: "Glovo", "Uber Eats") e um
código fiscal do Vendus por trás (TB, NU, CD...). É por isso que "Glovo" pode ser
um botão próprio sem deixar de ser transferência bancária aos olhos do fisco.

NUNCA escrevemos nos métodos de pagamento do Vendus — só mapeamos.

O `vendus_payment_method_id` é a metade dessa ligação que vem de LÁ: o id
numérico do método na conta Vendus. Sem ele, `fiscal.py::finalizar` recusa a
emissão com 422 — a fatura tem de dizer à Autoridade Tributária COMO o
cliente pagou, e não há forma de o adivinhar. Até aqui esses ids eram postos
à mão, directamente na base de dados de produção, o que queria dizer que
acrescentar um método novo (um MB Way, um Bolt) obrigava a chamar um
programador. `GET /tipos-pagamento/metodos-vendus` é o que fecha esse buraco:
lê a lista da conta Vendus para o ecrã a poder mostrar e o dono escolher.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .importacao import _nif_configurado
from .vendus.cliente import ClienteVendus, VendusErro, obter_conta

router = APIRouter()

# Códigos documentados em https://www.vendus.pt/ws/v1.1/registers/movements.doc
TIPOS_FISCAIS = {
    "NU": "Numerário",
    "CD": "Cartão de Débito",
    "CC": "Cartão de Crédito",
    "TB": "Transferência Bancária",
    "MB": "Referência MB",
    "MBWAY": "MB Way",
    "CH": "Cheque",
    "TR": "Ticket Restaurante",
    "CO": "Cartão Oferta",
    "CS": "Compensação de Saldos",
    "OU": "Outro",
}


class TipoPagamentoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    tipo_fiscal: str
    da_troco: bool = False
    ordem: int = 0
    ativo: bool = True
    vendus_payment_method_id: Optional[str] = None

    @field_validator("tipo_fiscal")
    @classmethod
    def _valida(cls, v):
        if v not in TIPOS_FISCAIS:
            raise ValueError("Tipo fiscal desconhecido: " + str(v))
        return v


@router.get("/tipos-pagamento")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["tipos_pagamento"]].find({}, {"_id": 0}).sort("ordem", 1).to_list(100)


@router.get("/tipos-pagamento/codigos-fiscais")
async def codigos(_: dict = Depends(gestor_atual)) -> dict:
    return TIPOS_FISCAIS


def _metodos_para_o_ecra(metodos: List[dict]) -> List[dict]:
    """Converte os métodos como o Vendus os dá para os três campos que o ecrã
    precisa: `id`, `titulo` e `tipo_fiscal`.

    O `id` sai SEMPRE como texto, mesmo quando o Vendus o manda como número.
    É o que vai ser gravado em `vendus_payment_method_id`, que é
    `Optional[str]` no modelo aqui em cima, e que `fiscal.py` compara com os
    ids que lê de volta dos documentos do Vendus por `str(...)` (ver
    fiscal.py:1689, a identificação do dinheiro no fecho de caixa). Deixar um
    número escapar daqui punha um int no campo, e a comparação `"145234375"
    == 145234375` é falsa em silêncio — o fecho deixava de reconhecer o
    dinheiro como dinheiro. Uma cadeia, um tipo, do princípio ao fim.

    Um método sem `id` é ignorado: o único uso desta lista é escolher um id
    para gravar, e uma linha que não se pode escolher só serviria para
    confundir. `title`/`name` como reserva pelo mesmo motivo do resto do
    módulo (ver importacao._sincronizar_categorias) — contas antigas do
    Vendus não têm todas os mesmos nomes de campo.

    NÃO se reordena a lista. A ordem é a que a conta Vendus tem, que é a
    mesma que o dono vê no backoffice do Vendus — e este é exactamente o
    ecrã onde ele está a comparar as duas listas lado a lado. Ordenar aqui
    por título fazia as duas deixarem de bater certo, sem ganho nenhum."""
    saida: List[dict] = []
    for metodo in metodos:
        if not isinstance(metodo, dict):
            continue
        identificador = str(metodo.get("id") or "").strip()
        if not identificador:
            continue
        saida.append({
            "id": identificador,
            "titulo": str(metodo.get("title") or metodo.get("name") or "").strip(),
            # O código fiscal do método no Vendus (NU, CD, TB, ...) — o mesmo
            # alfabeto do `tipo_fiscal` daqui, o que deixa o ecrã mostrar ao
            # lado de cada método o que ele é aos olhos do fisco. `type` é o
            # campo do Vendus; `payment_type` fica como reserva porque não há
            # chave de API nesta máquina para confirmar o nome ao vivo, e a
            # alternativa a esta reserva era uma coluna vazia sem explicação.
            # Não se filtra por TIPOS_FISCAIS: um código que não conheçamos é
            # para MOSTRAR, não para esconder — esconder o método fazia
            # desaparecer da lista precisamente o que o dono estaria à procura.
            "tipo_fiscal": str(metodo.get("type") or metodo.get("payment_type") or "").strip(),
        })
    return saida


@router.get("/tipos-pagamento/metodos-vendus")
async def metodos_vendus(_: dict = Depends(gestor_atual)) -> List[dict]:
    """Os métodos de pagamento da conta Vendus configurada, para o ecrã ligar
    cada tipo de pagamento nosso ao id de lá (`vendus_payment_method_id`).

    Devolve uma lista de `{"id": str, "titulo": str, "tipo_fiscal": str}`.

    Sob `gestor_atual`, nunca sob o mecanismo do POS: isto é configuração de
    backoffice. O balcão não escolhe métodos do Vendus — nem sequer chega a
    ver o `vendus_payment_method_id` (ver pos_catalogo.tipos_pagamento_do_pos,
    que só deixa sair o booleano `pronto`).

    Sem cache, de propósito — não é esquecimento. Este ecrã abre-se uma vez
    por mês, quando entra um método novo; uma cache traria a pergunta de
    quando a invalidar e esconderia exactamente o caso que interessa: o
    método ACABADO de criar no Vendus, que é o motivo pelo qual o dono está
    a abrir o ecrã.

    Uma lista vazia quer dizer "esta conta não tem métodos de pagamento" e
    mais nada. É por isso que nem a falta de configuração nem uma avaria do
    Vendus podem devolver `[]`: são estados diferentes, e dizê-los com a
    mesma resposta era mentir ao dono num ecrã de configuração fiscal."""
    nif = _nif_configurado()
    conta = obter_conta(nif)
    if conta is None:
        # 400, como em importacao.importar_vendus (o outro sítio onde o
        # backoffice lê do Vendus): falta configuração NOSSA, não é avaria do
        # Vendus. Distingui-los pelo código deixa o ecrã dizer a coisa certa.
        raise HTTPException(
            status_code=400,
            detail=(
                "Conta Vendus não configurada para o NIF %s. Defina VENDUS_ACCOUNTS "
                "no .env (ver backend/.env.example) com uma entrada cujo company_nif "
                "seja esse NIF — sem isto não há como listar os métodos de "
                "pagamento do Vendus." % nif
            ),
        )

    try:
        # `asyncio.to_thread`: o httpx.Client é síncrono e chamá-lo
        # directamente prendia o event loop — o portal inteiro (RH, Financeiro)
        # ficava à espera do Vendus. Mesmo padrão de importacao.py e fiscal.py.
        with ClienteVendus(conta.chave) as cliente:
            metodos = await asyncio.to_thread(cliente.listar_metodos_pagamento)
    except VendusErro as e:
        raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)

    return _metodos_para_o_ecra(metodos)


@router.post("/tipos-pagamento", status_code=201)
async def criar(dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    tipo = dados.model_dump()
    tipo.update({"id": str(uuid.uuid4()), "protegido": False,
                 "criado_em": datetime.now(timezone.utc).isoformat()})
    await db[COLECOES["tipos_pagamento"]].insert_one(dict(tipo))
    return tipo


@router.put("/tipos-pagamento/{tipo_id}")
async def editar(tipo_id: str, dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})
    if not atual:
        raise HTTPException(status_code=404, detail="Tipo de pagamento não encontrado")
    if atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser alterado.",
        )
    await db[COLECOES["tipos_pagamento"]].update_one({"id": tipo_id}, {"$set": dados.model_dump()})
    return await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})


@router.delete("/tipos-pagamento/{tipo_id}")
async def apagar(tipo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id})
    if atual and atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser apagado.",
        )
    r = await db[COLECOES["tipos_pagamento"]].delete_one({"id": tipo_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tipo de pagamento não encontrado")
    return {"apagado": True}
