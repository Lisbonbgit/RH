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
from typing import Dict, FrozenSet, Optional, Tuple

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
