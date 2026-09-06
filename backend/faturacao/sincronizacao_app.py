"""**Quem entra e quem fica de fora**, e nada mais.

Este ficheiro não sabe o que é Mongo nem o que é uma ligação ao Vendus. Recebe
o dicionário que o Vendus devolve e responde a uma pergunta de cada vez. É o
que permite que as armadilhas medidas — o `status` que muda de forma, os
orçamentos de 740 € — tenham um teste cada, sem servidor nenhum.

**A regra é uma lista de PERMITIDOS.** Foi medido na produção a 2026-09-04: a
Caixa Online tinha, além das nossas faturas e da única da app, cinco orçamentos
(`OT`) de 3.582,10 € e dois recibos (`RG`). Um orçamento não é venda nenhuma; um
recibo é o pagamento de uma fatura que já foi contada. Uma regra escrita ao
contrário — "tudo o que não começa por `pos-`" — punha 3.596,19 € de receita
inventada no Dashboard do dono. Um tipo novo que o Vendus invente amanhã fica de
fora sozinho, e o log di-lo.
"""
import uuid
from typing import Dict, FrozenSet, Optional, Tuple

from .vendus.emissao import _instante_do_vendus, _total_do_documento, _valor_monetario

# Só estes dois, e não também FT/FR: `documentos._TIPOS` responde 422 a
# qualquer outro tipo no filtro do backoffice, e um documento que entra na base
# mas não se consegue listar é pior do que um documento que não entra.
TIPOS_ACEITES: FrozenSet[str] = frozenset({"FS", "NC"})

_PREFIXO_NOSSO = "pos-"


def E_NOSSO(ext_ref: Optional[str]) -> bool:
    """A fatura saiu do nosso POS? É o `ext_ref_determinista` de `fiscal.py`."""
    return str(ext_ref or "").startswith(_PREFIXO_NOSSO)


def estado_do_vendus(doc: Dict) -> Optional[str]:
    """O estado (`N` normal, `A` anulado) venha ele em que forma vier.

    **Medido a 2026-09-04:** na LISTA (`GET documents/`) o Vendus manda
    `status: "N"`, uma string. No detalhe (`GET documents/{id}/`) manda
    `status: {"id": "N", "date": ..., "user_id": ...}`, um dicionário. Um
    `doc["status"] == "A"` escrito à mão acerta num sítio e falha no outro, em
    silêncio — e o silêncio, aqui, é uma fatura anulada a contar como receita.
    """
    estado = doc.get("status")
    if isinstance(estado, dict):
        estado = estado.get("id")
    return str(estado) if estado is not None else None


def e_de_teste(doc: Dict) -> bool:
    """Uma série de testes vem prefixada por `T` (`FS T06P2026/3`).

    Não se usa o modo em que o portal está AGORA: o que interessa é o modo em
    que aquele documento foi emitido. Um documento de teste não vale nada e não
    pode contar dinheiro.
    """
    numero = str(doc.get("number") or "")
    # "FS T06P2026/3" -> a segunda palavra começa por T
    partes = numero.split()
    return len(partes) > 1 and partes[1].startswith("T")


def deve_importar(doc: Dict) -> Tuple[bool, str]:
    """`(entra, motivo)` — e o motivo é sempre escrito, mesmo quando entra.

    Quem chama regista o motivo no log. Uma sincronização que diga "ignorei 7"
    sem dizer porquê é uma sincronização que ninguém consegue auditar quando os
    números não baterem.
    """
    tipo = str(doc.get("type") or "").strip().upper()
    if tipo not in TIPOS_ACEITES:
        return False, "tipo %s não é uma venda" % (tipo or "(vazio)")

    ref = doc.get("external_reference")
    if E_NOSSO(ref):
        return False, "é nossa (ext_ref começa por pos-)"

    estado = estado_do_vendus(doc)
    if estado == "A":
        return False, "anulada no Vendus"

    if e_de_teste(doc):
        return False, "documento de teste (série T), sem valor fiscal"

    if not str(ref or "").strip():
        # Entra na mesma: é receita real daquela caixa. Mas fica dito.
        return True, "sem referência externa — emitida à mão no painel do Vendus"

    return True, "da app (ref %s)" % ref


# O Vendus escreve o NIF do consumidor final assim. Copiá-lo para
# `cliente_nif` enchia o ecrã de Clientes de tracinhos.
_NIF_VAZIO = {"", "---------", "999999990"}


def _nif_do_cliente(cru: Dict) -> Optional[str]:
    nif = str((cru.get("client") or {}).get("fiscal_id") or "").strip()
    return None if nif in _NIF_VAZIO else nif


def documento_para_gravar(cru: Dict, loja_id: str) -> Dict:
    """O documento do Vendus traduzido para o que `fat_documentos` guarda.

    Os campos são os mesmos 15 que `fiscal._gravar_documento` monta
    (fiscal.py:1197-1250), menos os dois que um documento sem conta de balcão
    não pode ter — `venda_id` fica `None`, e não há `talao_escpos` nenhum — e
    mais dois que só estes têm: `origem` e `linhas_vendus`.

    **Recusa-se a gravar sem ATCUD, sem id do Vendus, ou sem data legível.**
    A data tem a sua própria razão, escrita onde é levantada. Os dois índices são
    únicos SIMPLES (db.py:132-133), não `sparse`: dois documentos com o campo a
    `None` colidem um com o outro, e o segundo desaparecia com um erro que não
    diz nada. Melhor recusar em voz alta e deixar quem chama contá-lo.
    """
    if not cru.get("atcud"):
        raise ValueError("documento do Vendus sem ATCUD: não se grava "
                         "(o índice é único e dois nulos colidem)")
    if not cru.get("id"):
        raise ValueError("documento do Vendus sem id: não se grava "
                         "(o índice é único e dois nulos colidem)")

    # **Recusa-se também sem data legível** — e aqui, ao contrário do POS
    # (`fiscal.py:1196` faz `bruto.get("emitido_em") or _agora()`), NÃO se cai
    # no instante actual. A diferença é que aqui não há segunda oportunidade:
    # `atcud` e `vendus_document_id` são índices ÚNICOS, portanto uma fatura
    # gravada com a data errada fica com ela PARA SEMPRE — nunca mais pode ser
    # regravada no dia certo. E errada seria: um documento de 01/09 lido a
    # 05/09 ia parar ao dia 05, a inflacionar um dia e a esvaziar o outro,
    # sem nada no ecrã a dizê-lo. Pior ainda, `None` a direito era invisível:
    # todos os filtros por intervalo comparam `emitido_em`
    # (dashboard.py:498, relatorios.py:620), e um documento sem ele não conta
    # para janela NENHUMA — desaparecia de todos os ecrãs de dinheiro, sem
    # erro nenhum. Recusar deixa-a de fora com um `assinalado` visível
    # (`sincronizacao_rota._saltar`), que é recuperável.
    emitido_em = _instante_do_vendus(cru)
    if not emitido_em:
        raise ValueError("documento do Vendus sem data legível: não se grava "
                         "(sem `emitido_em` não conta para janela nenhuma e "
                         "o ATCUD único impede regravá-lo no dia certo)")

    ref = str(cru.get("external_reference") or "").strip()
    return {
        # O nosso uuid: é por ele que o ecrã de Documentos e o PDF abrem a
        # fatura (documentos.py:135). O id do Vendus vive no seu campo.
        "id": str(uuid.uuid4()),
        "vendus_document_id": int(cru["id"]),
        "atcud": cru["atcud"],
        "numero": cru.get("number"),
        "tipo": str(cru.get("type") or "").strip().upper(),
        "modo": "normal",
        # `_total_do_documento`, não `_valor_monetario`: um `amount_gross`
        # PRESENTE mas ilegível tem de levantar `VendusRespostaIlegivel` em
        # vez de gravar `total: None` em silêncio. Os índices únicos de
        # `atcud` e `vendus_document_id` impedem uma segunda tentativa — um
        # documento gravado sem total fica assim PARA SEMPRE, e o ecrã de
        # Documentos lê `total` a direito, sem fallback nenhum. A referência
        # é o número do documento (ou o id do Vendus, quando aquele faltar),
        # nunca `ext_ref` — esse pode vir vazio (ver `deve_importar`) e um
        # log de erro fiscal com uma referência em branco não identifica
        # nada.
        "total": _total_do_documento(
            cru.get("amount_gross"), str(cru.get("number") or cru["id"])
        ),
        "total_bruto": _valor_monetario(cru.get("amount_gross")),
        # Sem alternativa nenhuma no Dashboard (dashboard.py:78): não gravar
        # isto é a app a valer 0,00 € no modo "sem IVA".
        "total_liquido": _valor_monetario(cru.get("amount_net")),
        "cliente_nif": _nif_do_cliente(cru),
        "emitido_em": emitido_em,
        "loja_id": loja_id,
        # Nunca "": `db.py:153-156` declara `ext_ref` único parcial sobre
        # strings. Esse índice não chegou a criar-se em produção (o antigo
        # colide), por isso hoje não rebentava — mas rebenta no dia em que
        # for reposto, e uma fatura perdida por isso não se recupera.
        # `None` fica certo nos dois mundos.
        "ext_ref": ref or None,
        "venda_id": None,
        "origem": "app",
        "linhas_vendus": cru.get("items") or [],
    }
