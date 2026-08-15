"""A emissão da Fatura Simplificada, com idempotência (Plano 2B, Task 3) —
o coração do módulo inteiro: é este ficheiro que liga a conta do balcão
(`venda.py`) ao Vendus (`vendus/emissao.py`) e emite o documento fiscal real.

**Onde os erros custam dinheiro.** A partir do dia em que isto entra em
produção, é este código que emite os documentos fiscais das 5 lojas do
dono. Uma fatura emitida duas vezes é uma cobrança a dobrar à Autoridade
Tributária, que só se corrige emitindo uma nota de crédito — e no fecho do
dia aparece como dinheiro a menos na gaveta, que a funcionária tem de
justificar ou pagar do bolso. Já aconteceu um bug destes num projecto
anterior do mesmo dono (`~/dev/pizzaria`); as defesas abaixo nasceram dele.

## A sequência (spec §6.1)

1. **Referência determinística** — `ext_ref_determinista`: depende só da
   identidade da venda (loja + sessão + id), NUNCA de um relógio. Duas
   tentativas da mesma venda produzem sempre a mesma referência.
2. **Reserva atómica, ANTES de tocar no Vendus** — insere em
   `fat_refs_fiscais` com índice único em `ext_ref` (declarado em `db.py`).
   Quem perde a corrida (`DuplicateKeyError`) NUNCA emite: ou o documento do
   vencedor já existe (devolve-o), ou está a ser escrito agora mesmo
   (espera por ele, com um orçamento limitado de tentativas).
3. **Emitir** e gravar em `fat_documentos` (índices únicos em
   `vendus_document_id` e em `atcud` — a quarta defesa, ver
   `ConflitoDocumentoFiscal`).
4. **Se a emissão falhar por indisponibilidade** (timeout, ligação, ou um
   5xx persistente — tudo o que `vendus.emissao` tipifica como
   `VendusIndisponivel`, porque em qualquer um destes casos não sabemos se o
   Vendus chegou a processar o pedido): UMA chamada exacta por
   `external_reference`, nunca um varrimento dos documentos do dia — essa é
   a armadilha documentada em `~/dev/pizzaria/backend/server.py`
   (`per_page=200` sem paginar: numa loja com 240 talões a fatura original
   nem entra na lista lida, e sai uma segunda fatura real). Se a verificação
   não encontrar nada, ou ela própria rebentar, o erro original propaga-se
   — nunca se "emite à mesma" só porque a verificação falhou.

`finalizar_venda` é o núcleo puro desta sequência: recebe `emitir` e
`verificar` já como duas funções assíncronas de UM argumento (a `ext_ref`),
para os testes poderem substituir o Vendus por duplos triviais sem threads
nem rede. É a rota `POST /pos/venda/{venda_id}/finalizar`, mais abaixo, que
liga esses dois parâmetros ao `ClienteEmissaoVendus` real, através de
`asyncio.to_thread` (o `httpx.Client` é síncrono — chamá-lo directamente
bloquearia o event loop do portal inteiro, RH e Financeiro incluídos).
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from .db import COLECOES, obter_db
from .importacao import _nif_configurado
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais
from .venda import (
    _bruto_da_linha,
    _desconto_da_linha,
    _desconto_global_eur,
    _garante_aberta,
    _linha_vendus,
    _obter_venda_da_loja,
    _totais,
    _venda_publica,
)
from .vendus.cliente import VendusErro, VendusIndisponivel, obter_conta
from .vendus.emissao import ClienteEmissaoVendus, _register_id_configurado

router = APIRouter()

# Orçamento de espera de quem perde a reserva: a reserva já existe mas o
# documento ainda não foi gravado (o vencedor está a meio da chamada ao
# Vendus). 50 tentativas × 50ms = 2,5s no pior caso em produção — uma venda
# ao balcão não pode ficar pendurada minutos a fio, mas 2,5s cobre folgado
# uma chamada HTTP normal ao Vendus.
_TENTATIVAS_ESPERA_VENCEDOR = 50
_ESPERA_ENTRE_TENTATIVAS_S = 0.05

_MSG_LINHAS_VAZIAS = "A venda não tem nenhuma linha — nada para faturar."
_MSG_TOTAL_NAO_POSITIVO = (
    "O total da venda tem de ser positivo para emitir uma fatura — "
    "confirme os descontos aplicados."
)
_MSG_TIPO_PAGAMENTO_INEXISTENTE = "Tipo de pagamento não encontrado ou inactivo."
_MSG_TIPO_PAGAMENTO_SEM_VENDUS = (
    "Este tipo de pagamento não tem um método do Vendus associado — "
    "não pode ser usado para emitir uma fatura real."
)


class FiscalErro(Exception):
    """Erro base deste módulo (distinto de VendusErro — este é sobre a
    NOSSA orquestração da idempotência, não sobre a comunicação HTTP em
    si)."""


class EmissaoEmCurso(FiscalErro):
    """A reserva desta venda já existe e o documento ainda não ficou
    disponível dentro do orçamento de espera — a emissão pode estar mesmo a
    decorrer noutro pedido, ou ter ficado presa a meio. Quem chama devolve
    isto ao POS como "tente novamente dentro de momentos", nunca inventa um
    documento."""


class ConflitoDocumentoFiscal(FiscalErro):
    """O Vendus devolveu um documento cujo `vendus_document_id` ou `atcud`
    colide com um já gravado para uma referência externa DIFERENTE — não
    devia poder acontecer com um Vendus saudável, mas se acontecer a reserva
    NÃO se liberta (o Vendus emitiu mesmo um documento fiscal real; libertar
    a reserva convidaria a emitir um segundo) e o erro é alto e claro, para
    investigação manual."""


def _itens_vendus(venda: Dict) -> List[Dict]:
    """As linhas da venda no formato Vendus, com o desconto GLOBAL da venda
    (já resolvido a euros por `venda._desconto_global_eur` — o € tem sempre
    precedência sobre a percentagem, mesma regra do desconto por linha)
    dobrado dentro do desconto de CADA linha como uma ÚNICA
    `discount_percentage`.

    Porquê não um campo de desconto ao nível do documento inteiro: o Vendus
    documenta `discount_amount`/`discount_percentage` no `POST documents/`,
    mas agrupados com `discount_code`/`discount_code_apply` — é o recurso de
    "cartões de desconto" (cupões), não um desconto genérico independente
    dele (confirmado nos docs cacheados do Vendus, ver o relatório da
    tarefa). Sem conseguir confirmar isto ao vivo (sem chave de API nesta
    máquina), não se usa às cegas um campo cujo comportamento fora desse
    contexto não está documentado.

    Em vez disso, o MESMO raciocínio do `combine_global` da Pizzaria
    (`~/dev/pizzaria/backend/pos/pricing.py`), já validado em produção:
    a percentagem da própria linha compõe-se multiplicativamente com a
    percentagem equivalente do desconto global — `1-(1-p)(1-g)` — nunca
    dois descontos em paralelo. O desconto global aplica-se SEMPRE por cima
    do desconto da linha, igual ao que `venda._totais` já calcula."""
    linhas_vendus = [_linha_vendus(li) for li in venda.get("linhas", [])]
    if not linhas_vendus:
        return []

    subtotal = round(sum(_bruto_da_linha(li) for li in linhas_vendus), 2)
    desconto_linhas = round(sum(_desconto_da_linha(li) for li in linhas_vendus), 2)
    liquido_linhas = round(subtotal - desconto_linhas, 2)
    desconto_global = _desconto_global_eur(venda, liquido_linhas)
    pct_global = (
        round(100.0 * desconto_global / liquido_linhas, 6) if liquido_linhas > 0 else 0.0
    )
    pct_global = max(0.0, min(100.0, pct_global))

    saida = []
    for li in linhas_vendus:
        qty = li.get("qty", 1) or 1
        unit = float(li.get("gross_price", 0) or 0)
        gross = round(unit * qty, 2)

        damount = li.get("discount_amount")
        dpct = li.get("discount_percentage")
        if damount:
            liquido_apos_linha = max(0.0, gross - float(damount))
            pct_linha = round(100.0 * (1 - liquido_apos_linha / gross), 6) if gross > 0 else 0.0
        else:
            pct_linha = float(dpct or 0)

        eff = round(100.0 * (1 - (1 - pct_linha / 100.0) * (1 - pct_global / 100.0)), 6)

        item = {chave: li[chave] for chave in ("title", "qty", "gross_price", "tax_id") if chave in li}
        if eff > 0:
            item["discount_percentage"] = eff
        saida.append(item)
    return saida


def ext_ref_determinista(loja_id: str, sessao_id: str, venda_id: str) -> str:
    """`pos-{loja}-{sessao}-{venda}` — depende só da IDENTIDADE da venda,
    nunca de um relógio nem do conteúdo das linhas. Duas tentativas da
    mesma venda (duplo-toque, retry) produzem sempre a mesma referência —
    é isso que faz a reserva atómica funcionar como idempotência. O prefixo
    `pos-` é o que separa os nossos documentos dos da app L'Açaí na mesma
    caixa API partilhada (spec §5.2)."""
    return "pos-%s-%s-%s" % (loja_id, sessao_id, venda_id)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _reservar(db, ext_ref: str, venda_id: str) -> bool:
    """A reserva atómica (passo 2). `True` se esta chamada ganhou a corrida;
    `False` se perdeu (já existe uma reserva para esta `ext_ref`) — é o
    índice único em `ext_ref` (db.py) que decide, não uma leitura antes de
    inserir."""
    try:
        await db[COLECOES["refs_fiscais"]].insert_one({
            "id": str(uuid.uuid4()),
            "ext_ref": ext_ref,
            "venda_id": venda_id,
            "criado_em": _agora(),
        })
        return True
    except DuplicateKeyError:
        return False


async def _libertar_reserva(db, ext_ref: str) -> None:
    """Remove a reserva desta `ext_ref` — chamado quando algo falha DEPOIS
    de reservar (nunca depois de o Vendus confirmar que emitiu, ver
    ConflitoDocumentoFiscal), para a próxima tentativa poder reservar de
    novo em vez de ficar presa atrás de uma reserva órfã."""
    await db[COLECOES["refs_fiscais"]].delete_one({"ext_ref": ext_ref})


async def _esperar_documento_do_vencedor(
    db,
    ext_ref: str,
    esperar: Callable[[float], Awaitable[None]],
    tentativas: int,
) -> Dict:
    """Quem perde a reserva chega aqui: OU o documento do vencedor já existe
    (devolve-o de imediato), OU ainda está a ser escrito (espera, com um
    orçamento limitado — nunca para sempre)."""
    for _ in range(tentativas):
        documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if documento is not None:
            return documento
        await esperar(_ESPERA_ENTRE_TENTATIVAS_S)
    raise EmissaoEmCurso(
        "Já existe uma reserva de emissão para esta venda (ext_ref=%s) mas "
        "o documento ainda não ficou disponível — tente novamente dentro de "
        "momentos." % ext_ref
    )


async def finalizar_venda(
    db,
    venda: Dict,
    emitir: Callable[[str], Awaitable[Dict]],
    verificar: Callable[[str], Awaitable[Optional[Dict]]],
    esperar: Optional[Callable[[float], Awaitable[None]]] = None,
    tentativas_espera: int = _TENTATIVAS_ESPERA_VENCEDOR,
) -> Dict:
    """O núcleo da Task 3 — a sequência das quatro defesas (ver a docstring
    do módulo). `emitir(ext_ref)` e `verificar(ext_ref)` já vêm resolvidos
    para ESTA venda (linhas, pagamentos, cliente, register_id — tudo isso é
    responsabilidade de quem chama, normalmente a rota `finalizar` mais
    abaixo); este núcleo só sabe de reserva, emissão-ou-verificação, e
    gravação — é o que o torna testável sem tocar em rede nem em threads.
    """
    esperar = esperar if esperar is not None else asyncio.sleep
    ext_ref = ext_ref_determinista(venda["loja_id"], venda["sessao_id"], venda["id"])

    ganhou = await _reservar(db, ext_ref, venda["id"])
    if not ganhou:
        return await _esperar_documento_do_vencedor(db, ext_ref, esperar, tentativas_espera)

    try:
        try:
            bruto = await emitir(ext_ref)
        except VendusIndisponivel:
            # Não sabemos se o pedido chegou a ser processado do outro
            # lado — UMA verificação exacta, nunca um varrimento (ver a
            # docstring do módulo).
            encontrado = await verificar(ext_ref)
            if encontrado is None:
                raise
            bruto = encontrado
    except Exception:
        # Qualquer falha a partir daqui significa que NENHUM documento foi
        # confirmado como emitido para esta venda — a reserva liberta-se,
        # para a próxima tentativa (correcção de dados, nova tentativa
        # manual) poder reservar de novo.
        await _libertar_reserva(db, ext_ref)
        raise

    documento = {
        "id": str(uuid.uuid4()),
        "vendus_document_id": bruto.get("id"),
        "atcud": bruto.get("atcud"),
        "numero": bruto.get("numero"),
        "total": bruto.get("total"),
        "modo": bruto.get("modo"),
        "ext_ref": ext_ref,
        "venda_id": venda["id"],
        "loja_id": venda["loja_id"],
        "emitido_em": _agora(),
    }
    try:
        await db[COLECOES["documentos"]].insert_one(dict(documento))
    except DuplicateKeyError:
        existente = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
        if existente is not None:
            # Uma tentativa anterior desta MESMA venda já gravou o
            # documento (ex.: um retry depois de a resposta se ter
            # perdido) — reutiliza-o, sem inventar um segundo.
            documento = existente
        else:
            # O Vendus DEVOLVEU um documento (`bruto`) mas gravá-lo colide
            # com outro já gravado para uma ext_ref DIFERENTE (mesmo
            # vendus_document_id ou atcud) — ver ConflitoDocumentoFiscal: a
            # reserva NÃO se liberta, porque o documento fiscal existe
            # mesmo.
            raise ConflitoDocumentoFiscal(
                "O Vendus devolveu um documento (id=%r, atcud=%r) que colide "
                "com outro já gravado localmente para uma referência "
                "DIFERENTE — a reserva de %s foi mantida (o documento fiscal "
                "existe) e isto precisa de investigação manual." % (
                    bruto.get("id"), bruto.get("atcud"), ext_ref,
                )
            )

    await db[COLECOES["vendas"]].update_one(
        {"id": venda["id"]},
        {"$set": {"estado": "emitida", "documento_id": documento["id"]}},
    )
    return documento


# --- A rota: liga o núcleo acima ao Vendus real e à conta do balcão --------


class PagamentoEntrada(BaseModel):
    tipo_pagamento_id: str = Field(min_length=1)
    valor: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("valor")
    @classmethod
    def _valida_valor(cls, v):
        if _tem_mais_de_2_casas_decimais(v):
            raise ValueError(
                "O valor %s tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento." % v
            )
        return v


class PedidoFinalizarVenda(BaseModel):
    pagamentos: List[PagamentoEntrada] = Field(min_length=1)
    # Opcional: sem NIF, o Vendus assume Consumidor Final (ver
    # vendus/emissao.py). Normalizado só a dígitos — "123 456 789" e
    # "123456789" têm de ser a mesma coisa para o Vendus.
    nif: Optional[str] = None

    @field_validator("nif")
    @classmethod
    def _valida_nif(cls, v):
        if v is None or not v.strip():
            return None
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) != 9:
            raise ValueError("O NIF tem de ter 9 dígitos.")
        return digitos


def _resposta_documento(documento: Dict) -> Dict:
    return {
        "id": documento.get("id"),
        "vendus_document_id": documento.get("vendus_document_id"),
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "total": documento.get("total"),
        # O ecrã tem de poder avisar se saiu em modo 'tests' (sem valor
        # fiscal) — ver a docstring de VendusModoInvalido em vendus/emissao.py.
        "modo": documento.get("modo"),
    }


@router.post("/pos/venda/{venda_id}/finalizar")
async def finalizar(
    venda_id: str, dados: PedidoFinalizarVenda, operador: Dict = Depends(operador_atual)
) -> dict:
    """Emite a Fatura Simplificada real desta venda (spec §7.4 "Finalizar").

    A validação de configuração (conta Vendus, register_id) e de dados
    (linhas presentes, total positivo, pagamentos a bater com o total, tipos
    de pagamento válidos e mapeados no Vendus) corre TODA antes de tocar na
    reserva atómica — um erro de configuração ou de dados não pode gastar
    uma tentativa de emissão nem confundir o operador com um 502 do Vendus
    quando o problema é, por exemplo, um pagamento mal somado."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    if not venda.get("linhas"):
        raise HTTPException(status_code=422, detail=_MSG_LINHAS_VAZIAS)

    totais = _totais(venda)
    if totais["total"] <= 0:
        raise HTTPException(status_code=422, detail=_MSG_TOTAL_NAO_POSITIVO)

    soma_pagamentos = round(sum(p.valor for p in dados.pagamentos), 2)
    if soma_pagamentos != totais["total"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "A soma dos pagamentos (%.2f €) não bate com o total da "
                "venda (%.2f €)." % (soma_pagamentos, totais["total"])
            ),
        )

    pagamentos_venda: List[Dict] = []
    pagamentos_vendus: List[Dict] = []
    for p in dados.pagamentos:
        tipo = await db[COLECOES["tipos_pagamento"]].find_one({"id": p.tipo_pagamento_id})
        if not tipo or not tipo.get("ativo", True):
            raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_INEXISTENTE)
        if not tipo.get("vendus_payment_method_id"):
            raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_SEM_VENDUS)
        # Snapshot do tipo (nome, tipo_fiscal) — o mesmo raciocínio de
        # venda.py::_produto_snapshot: o fecho de caixa (Task 4) lê
        # `tipo_fiscal` directamente daqui para separar dinheiro de
        # multibanco, sem precisar de reconsultar fat_tipos_pagamento (que
        # podia entretanto ter mudado) para reconstruir o Z de um dia antigo.
        pagamentos_venda.append({
            "tipo_pagamento_id": tipo["id"],
            "nome": tipo.get("nome"),
            "tipo_fiscal": tipo.get("tipo_fiscal"),
            "valor": p.valor,
        })
        pagamentos_vendus.append({"id": tipo["vendus_payment_method_id"], "amount": p.valor})

    conta = obter_conta(_nif_configurado())
    if conta is None:
        raise HTTPException(
            status_code=502,
            detail=(
                "Conta Vendus não configurada para o NIF %s. Defina "
                "VENDUS_ACCOUNTS no .env — sem isto não há como emitir." % _nif_configurado()
            ),
        )
    register_id = _register_id_configurado()
    if register_id is None:
        raise HTTPException(
            status_code=502,
            detail="VENDUS_REGISTER_ID não está configurado — sem isto não há como emitir.",
        )

    # A partir daqui grava-se já o que a operadora escolheu (pagamentos e
    # NIF) — mesmo que a emissão a seguir falhe ou tenha de esperar por um
    # vencedor, esta informação fica disponível para o fecho de caixa (Task
    # 4) e para uma eventual repetição não perder o que já foi escolhido.
    await db[COLECOES["vendas"]].update_one(
        {"id": venda_id},
        {"$set": {"pagamentos": pagamentos_venda, "cliente_nif": dados.nif}},
    )

    itens = _itens_vendus(venda)
    cliente_payload = {"fiscal_id": dados.nif} if dados.nif else None

    with ClienteEmissaoVendus(conta.chave) as cliente_vendus:

        async def emitir(ref: str) -> Dict:
            return await asyncio.to_thread(
                cliente_vendus.criar_fatura_simplificada,
                linhas=itens,
                pagamentos=pagamentos_vendus,
                cliente=cliente_payload,
                external_reference=ref,
                register_id=register_id,
            )

        async def verificar(ref: str) -> Optional[Dict]:
            return await asyncio.to_thread(
                cliente_vendus.procurar_por_referencia_externa, ref, register_id
            )

        try:
            documento = await finalizar_venda(db, venda, emitir, verificar)
        except EmissaoEmCurso as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ConflitoDocumentoFiscal as e:
            raise HTTPException(status_code=500, detail=str(e))
        except VendusErro as e:
            raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)

    venda_actualizada = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    resposta = _venda_publica(venda_actualizada)
    resposta["pagamentos"] = venda_actualizada.get("pagamentos", [])
    resposta["cliente_nif"] = venda_actualizada.get("cliente_nif")
    resposta["documento"] = _resposta_documento(documento)
    return resposta
