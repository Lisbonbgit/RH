"""**A taxa de depósito de embalagem (SDR)** — a caução que a lei manda cobrar.

Desde 10 de abril de 2026, as embalagens primárias não reutilizáveis de bebidas
em plástico, metais ferrosos e alumínio, com menos de 3 litros, pagam **0,10 €
de depósito** — e a fatura **tem obrigatoriamente de o discriminar em linha
separada**, com o valor **não sujeito a tributação** (artigo 30.º-E do
Decreto-Lei n.º 152-D/2017, na redação do UNILEX).

Ficam de fora o vidro, as embalagens de serviço (os copos do açaí) e as bebidas
com mais de 25% de ingredientes lácteos.

## As três decisões deste módulo

**1. Não é receita.** É uma caução: o dinheiro entra na gaveta e não é nosso —
o cliente pode reavê-lo num ponto de recolha. Por isso conta no `esperado` do
turno e NÃO conta na facturação. Os dois números aparecem com legenda, porque
dois números certos lado a lado sem legenda produzem uma leitura falsa.

**2. A linha é DERIVADA, nunca gravada.** Sai de uma função pura sobre as
linhas da conta. Uma linha gravada podia divergir do resto da conta depois de
uma edição; uma derivada não pode, por construção.

**3. Sem desconto, por construção e não por guarda.** `linha_do_deposito` não
recebe desconto nenhum — não há por onde lho aplicar. Um desconto sobre uma
caução era devolver ao cliente dinheiro que ainda é dele.

## O que NÃO está aqui

O **reembolso ao balcão**. As cinco lojas têm menos de 50 m² e estão isentas da
obrigação de recolha (artigo 30.º-H, alínea c); um estabelecimento HORECA
também não é automaticamente ponto de recolha (artigo 30.º-G). Construir um
fluxo de devolução que ninguém vai usar é código para manter sem razão.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .precos import CODIGO_NAO_SUJEITO, _tem_mais_de_2_casas_decimais

router = APIRouter()

CHAVE_DEFINICOES = "deposito"

# O valor está na lei, não na nossa cabeça: 0,10 € por embalagem. Fica como
# valor por omissão e é editável — se a lei mudar o montante, muda-se aqui sem
# um deploy — mas nunca é adivinhado.
VALOR_LEGAL = 0.10

# O que sai no título da linha da fatura. Curto de propósito: é o que o cliente
# lê no talão, e «Depósito» é a palavra da lei.
TITULO = "Depósito"


async def definicoes(db) -> Dict:
    """A configuração do depósito, com os valores por omissão já aplicados.

    **Ausente quer dizer DESLIGADO**, como no desconto automático de stock e
    pela mesma razão: uma definição que se liga sozinha no dia do deploy é a
    pior maneira de estrear uma cobrança nova a cinco lojas. O dono liga-a
    quando estiver pronto, depois de ver o ecrã.

    `db` vem por parâmetro e nunca de um `obter_db()` cá dentro — é o que
    torna isto testável sem base de dados, e o molde é o `modo_efectivo`.
    """
    doc = await db[COLECOES["definicoes"]].find_one(
        {"id": CHAVE_DEFINICOES}, {"_id": 0}) or {}
    return {
        "ativo": bool(doc.get("ativo")),
        "valor": float(doc.get("valor") if doc.get("valor") is not None else VALOR_LEGAL),
        "vendus_ref": doc.get("vendus_ref"),
        "mudado_em": doc.get("mudado_em"),
        "mudado_por": doc.get("mudado_por"),
    }


def embalagens_da_venda(venda: Optional[Dict]) -> float:
    """Quantas embalagens com depósito esta conta tem.

    Soma as QUANTIDADES das linhas carimbadas, e não conta linhas: três águas
    numa linha só são três embalagens, e uma conta repartida em três grava
    quantidades fraccionárias (0,3337) — é a mesma armadilha que o consumo de
    stock já conhece.

    Lê o CARIMBO da linha (`deposito_unitario`) e nunca o produto de hoje: o
    que já foi vendido não muda porque alguém mexeu na configuração à tarde.
    """
    total = 0.0
    for linha in (venda or {}).get("linhas") or []:
        if linha.get("deposito_unitario"):
            total += float(linha.get("quantidade") or 0)
    return round(total, 4)


def linhas_do_deposito(
    venda: Optional[Dict], vendus_ref: Optional[str] = None
) -> List[Dict]:
    """As linhas de depósito desta conta, no formato Vendus.

    **Uma por VALOR unitário distinto**, e não uma só com o primeiro que
    aparecer. Dentro de uma conta os valores são quase sempre iguais — mas o
    carimbo é por linha, e se o dono afinar o montante a meio de uma conta
    aberta ficam dois. Somar tudo a um preço só cobrava ao cliente um valor
    que nunca esteve em lado nenhum; assim a fatura mostra o que aconteceu.

    Ordenadas por valor, para a fatura sair sempre igual para a mesma conta.
    """
    por_valor: Dict[float, float] = {}
    for linha in (venda or {}).get("linhas") or []:
        unitario = linha.get("deposito_unitario")
        if not unitario:
            continue
        valor = round(float(unitario), 2)
        por_valor[valor] = por_valor.get(valor, 0.0) + float(linha.get("quantidade") or 0)

    saida = []
    for valor in sorted(por_valor):
        item = linha_do_deposito(round(por_valor[valor], 4), valor, vendus_ref)
        if item is not None:
            saida.append(item)
    return saida


def valor_do_deposito(venda: Optional[Dict]) -> float:
    """Quanto é o depósito desta conta, em euros.

    Multiplica pelo valor CARIMBADO em cada linha — não pelo valor de hoje.
    Uma conta aberta ontem, com o montante legal a mudar de madrugada,
    fecha-se ao preço a que foi aberta."""
    total_centimos = 0
    for linha in (venda or {}).get("linhas") or []:
        unitario = linha.get("deposito_unitario")
        if not unitario:
            continue
        total_centimos += round(
            float(unitario) * 100 * float(linha.get("quantidade") or 0))
    return round(total_centimos / 100.0, 2)


def linha_do_deposito(
    quantidade: float, valor: float, vendus_ref: Optional[str]
) -> Optional[Dict]:
    """A linha do depósito como ela viaja para o Vendus — ou `None` quando não
    há embalagens nenhumas nesta conta.

    **`tax_id` é `NS`, não `ISE`.** Não é IVA a zero, é fora do imposto, e a
    diferença é o que o SAF-T lê (ver `precos.CODIGO_NAO_SUJEITO`).

    **Não recebe desconto nenhum**, e é essa a garantia: um desconto sobre uma
    caução era devolver ao cliente dinheiro que ainda é dele. Não é uma guarda
    que se possa esquecer de aplicar — é um parâmetro que não existe.

    O `id` só entra se for um inteiro positivo, exactamente como nas linhas
    dos produtos: mandar ao Vendus um `id` que ele não reconheça arrisca a
    recusa do documento INTEIRO com o cliente à frente.
    """
    if not quantidade or quantidade <= 0:
        return None
    linha = {
        "title": TITULO,
        "qty": quantidade,
        "gross_price": round(float(valor), 2),
        "tax_id": CODIGO_NAO_SUJEITO,
    }
    texto = str(vendus_ref or "").strip()
    if texto.isdecimal() and int(texto) > 0:
        linha["id"] = int(texto)
    return linha


# --- a configuração, no backoffice -------------------------------------------

class DefinicoesEntrada(BaseModel):
    ativo: bool
    # `gt=0`: um depósito de zero não é um depósito, é uma linha a mais na
    # fatura de toda a gente. `le=5`: o valor legal são 0,10 € — um dedo
    # enganado que escreva 100 cobra cem euros de caução por uma lata.
    valor: float = Field(default=VALOR_LEGAL, gt=0, le=5)
    # A referência do artigo de depósito na conta Vendus. Sem ela a linha sai
    # só com o título e o Vendus cria um artigo novo a cada venda — feio, mas
    # não impede de facturar, tal como nos produtos.
    vendus_ref: Optional[str] = None

    @classmethod
    def _valida(cls, v):
        return v

    def limpo(self) -> Dict:
        if _tem_mais_de_2_casas_decimais(self.valor):
            raise HTTPException(
                status_code=422,
                detail="O valor do depósito não pode ter mais de 2 casas decimais.")
        return {
            "ativo": self.ativo,
            "valor": round(float(self.valor), 2),
            "vendus_ref": (self.vendus_ref or "").strip() or None,
        }


@router.get("/deposito")
async def obter_definicoes(_: dict = Depends(gestor_atual)) -> dict:
    return await definicoes(obter_db())


@router.put("/deposito")
async def gravar_definicoes(
    dados: DefinicoesEntrada, gestor: dict = Depends(gestor_atual)
) -> dict:
    """Liga, desliga e afina o depósito.

    Fica registado QUEM mudou e QUANDO, como no modo de emissão: é uma
    cobrança nova ao cliente e a pergunta «desde quando é que isto está
    ligado?» tem de ter resposta sem ir ao histórico de ninguém."""
    from datetime import datetime, timezone

    db = obter_db()
    alteracoes = dados.limpo()
    alteracoes["mudado_em"] = datetime.now(timezone.utc).isoformat()
    alteracoes["mudado_por"] = gestor.get("email") or gestor.get("id")
    await db[COLECOES["definicoes"]].update_one(
        {"id": CHAVE_DEFINICOES}, {"$set": alteracoes}, upsert=True)
    return await definicoes(db)


@router.get("/deposito/produtos")
async def produtos_com_deposito(_: dict = Depends(gestor_atual)) -> List[dict]:
    """Que produtos cobram depósito — a lista que o ecrã mostra.

    Ordenada por categoria e nome, como a grelha do backoffice: quem vem
    conferir a lista contra a do Vendus lê-a de cima a baixo.
    """
    db = obter_db()
    produtos = await db[COLECOES["produtos"]].find(
        {"tem_deposito": True},
        {"_id": 0, "id": 1, "nome": 1, "categoria_id": 1, "ativo": 1},
    ).sort("nome", 1).to_list(500)
    return produtos
