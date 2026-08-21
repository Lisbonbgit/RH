"""O mapa de imposto de um turno — taxa · nº de documentos · base · IVA ·
total. Puro, sem I/O.

É o que a contabilista pede e o que o POS não sabia responder.
`fat_documentos` guarda o `total_bruto` e o `total_liquido` do documento
INTEIRO, nunca a repartição por taxa — e no cardápio há duas que se
misturam na mesma conta: 13 % (INT) nos açaís, 23 % (NOR) nos
refrigerantes, brigadeiros, embalagem e entrega. Um açaí e uma Coca-Cola no
mesmo talão são um documento com duas bases, e nenhum campo gravado o diz.

## A armadilha, e porque é que este ficheiro é tão curto

O desconto GLOBAL incide sobre o líquido já depois dos descontos por linha,
e tem de ser repartido pelas taxas na MESMA proporção em que foi repartido
pelas linhas — senão a base declarada por taxa não bate com o total do
documento. Escrever essa repartição outra vez aqui era a forma óbvia de a
fazer, e era a errada: seria uma segunda cópia da aritmética mais delicada
do módulo, a viver ao lado da original e a divergir dela na primeira
alteração de qualquer uma das duas.

Por isso este mapa não reparte nada. Pergunta a `fiscal._itens_vendus` —
**a mesma função que construiu as linhas que foram entregues à AT** — quais
foram as linhas do documento, e lê de cada uma o `tax_id` e o líquido que
lá está: `qty × gross_price`, menos a `discount_percentage` (que é o
desconto próprio da linha MAIS a fatia do global que lhe calhou, já
convertida numa percentagem que reproduz o cêntimo exacto — ver
`fiscal._percentagem_que_reproduz`). A conta que este ficheiro faz sobre
esse líquido é a MESMA que o Vendus faz do lado dele, linha a linha:
`round(bruto × (1 - pct/100), 2)`.

Consequência prática: não há aqui nenhuma decisão de repartição que possa
discordar da emissão, porque não há aqui repartição nenhuma.

**E `reparticao.repartir_centimos` não serve para isto**, apesar de ser o
repartidor com soma garantida do módulo: ele reparte em partes IGUAIS (a
ferramenta certa do `dividir_conta`, que divide um valor por N pessoas). O
desconto global sobre linhas de valores diferentes é PROPORCIONAL — usá-lo
aqui punha metade de um desconto em cima da Coca-Cola de 1,15 € e a outra
metade em cima do açaí de 10,20 €, e a base declarada por taxa deixava de
bater com o documento. O repartidor proporcional do módulo é
`fiscal._distribuir_centimos`, e é precisamente esse que
`fiscal._itens_vendus` já usou.

## Base e IVA

O `gross_price` é COM IVA (é o preço que o cliente lê no cardápio), por
isso o líquido de cada linha é o total com imposto. A base tira-se dele:
`base = total × 100 / (100 + taxa)`, e o IVA é o que sobra —
`iva = total - base`, nunca calculado à parte. Assim `base + iva` dá o
total EXACTAMENTE, por construção e não por sorte, e a soma das bases mais
a soma dos IVAs dá o total dos documentos do turno ao cêntimo.

Tudo em cêntimos inteiros, e a divisão da base é em aritmética inteira com
o meio-cêntimo para cima (`(2·num + den) // (2·den)`): `round()` sobre
floats faz arredondamento bancário sobre a representação binária, e este é
um número que vai numa declaração de imposto.
"""
from typing import Dict, List, Optional

from .fiscal import _itens_vendus
from .precos import _TAXAS

# O caminho inverso de `precos._TAXAS`: do código do Vendus (INT/NOR/RED/ISE)
# para a percentagem. Derivado do mesmo dicionário, e não escrito outra vez,
# para não haver forma de acrescentar uma taxa lá e ela não chegar aqui.
_TAXA_DO_CODIGO = {codigo: taxa for taxa, codigo in _TAXAS.items()}


def _centimos(valor) -> int:
    return int(round(float(valor or 0) * 100))


def _liquido_da_linha(item: Dict) -> float:
    """O que esta linha do documento vale, com IVA e já com todos os
    descontos — a MESMA fórmula que o Vendus aplica do lado dele
    (`gross × qty`, depois `× (1 - pct/100)`, arredondado ao cêntimo)."""
    bruto = round(item["qty"] * item["gross_price"], 2)
    pct = item.get("discount_percentage") or 0.0
    return round(bruto * (1 - pct / 100.0), 2)


def _base_em_centimos(total_centimos: int, taxa: int) -> int:
    """A base tributável de um total COM IVA, em cêntimos inteiros e com o
    meio-cêntimo arredondado para CIMA.

    `(2·num + den) // (2·den)` é `floor(num/den + 0.5)` só com inteiros —
    sem passar pelo float, e portanto sem o arredondamento bancário do
    `round()` (que a 0,5 vai para o par mais próximo, e num mapa de imposto
    isso é uma escolha que ninguém tomou)."""
    numerador = total_centimos * 100
    denominador = 100 + taxa
    return (2 * numerador + denominador) // (2 * denominador)


def mapa_de_imposto(vendas: List[Dict]) -> List[Dict]:
    """O mapa de imposto das vendas EMITIDAS de uma sessão.

    Uma linha por taxa: `{"tax_id", "taxa", "documentos", "base", "iva",
    "total"}`. `documentos` é quantos DOCUMENTOS tocaram essa taxa (um
    talão com um açaí e uma Coca-Cola conta uma vez em cada uma das duas
    linhas), e não quantas linhas de artigo — é o número que a contabilista
    pede e o que o Vendus imprime.

    Só `estado == "emitida"`: uma conta aberta não é documento nenhum, e uma
    cancelada nunca chegou a ser.

    **Um `tax_id` que não conheça** (nada no caminho de hoje o produz —
    `catalogo.erros_do_produto` e `precos.linha_de_venda` recusam qualquer
    código fora de NOR/INT/RED/ISE — mas o `produto_tax_id` de uma linha é
    um retrato gravado, e um retrato antigo pode trazer o que lá estiver)
    sai com `taxa`, `base` e `iva` a `None` e o `total` preenchido. Não se
    inventa uma taxa (a regra de ouro de `precos.py`) e não se deixa cair o
    dinheiro: o ecrã mostra "—" nas colunas do imposto e a linha continua a
    somar para o total do turno, que é onde alguém dá por ela.
    """
    por_taxa: Dict[Optional[str], Dict] = {}
    for venda in vendas or []:
        if venda.get("estado") != "emitida":
            continue
        # Primeiro agrega DENTRO do documento, e só depois soma ao turno: é
        # isso que faz `documentos` contar documentos e não linhas.
        centimos_deste = {}
        for item in _itens_vendus(venda):
            tax_id = item.get("tax_id")
            centimos_deste[tax_id] = (
                centimos_deste.get(tax_id, 0) + _centimos(_liquido_da_linha(item))
            )
        for tax_id, centimos in centimos_deste.items():
            linha = por_taxa.get(tax_id)
            if linha is None:
                linha = por_taxa[tax_id] = {"centimos": 0, "documentos": 0}
            linha["centimos"] += centimos
            linha["documentos"] += 1

    saida = []
    for tax_id, linha in por_taxa.items():
        taxa = _TAXA_DO_CODIGO.get(tax_id)
        total_centimos = linha["centimos"]
        if taxa is None:
            base_centimos = iva_centimos = None
        else:
            base_centimos = _base_em_centimos(total_centimos, taxa)
            # O IVA é o RESTO, nunca uma segunda multiplicação: é isto que
            # garante `base + iva == total` ao cêntimo, sem depender de os
            # dois arredondamentos caírem do mesmo lado.
            iva_centimos = total_centimos - base_centimos
        saida.append({
            "tax_id": tax_id,
            "taxa": taxa,
            "documentos": linha["documentos"],
            "base": None if base_centimos is None else base_centimos / 100.0,
            "iva": None if iva_centimos is None else iva_centimos / 100.0,
            "total": total_centimos / 100.0,
        })
    # Por taxa crescente (0, 6, 13, 23), com as desconhecidas no fim — a
    # ordem em que um mapa de imposto se lê, e determinística.
    saida.sort(key=lambda linha: (linha["taxa"] is None, linha["taxa"] or 0))
    return saida


def totais_do_mapa(mapa: List[Dict]) -> Dict:
    """A última linha da tabela: a base, o IVA e o total do turno inteiro.

    Somada DO MAPA e não das vendas outra vez, de propósito: o número que o
    ecrã mostra por baixo de uma tabela tem de ser a soma da tabela que está
    por cima dele, e não um segundo cálculo que pode não dar o mesmo.

    É esta linha que torna VISÍVEL ao balcão a única coisa que interessa num
    mapa de imposto: que a soma das bases mais a soma dos IVAs dá o total
    dos documentos do turno, ao cêntimo. Uma linha de taxa desconhecida
    (`base` e `iva` a `None`) conta para o total e não para as outras duas —
    e é assim que ela tem de dar nas vistas, com as duas colunas a não
    fecharem com a terceira."""
    return {
        "base": sum(_centimos(linha["base"]) for linha in mapa or []) / 100.0,
        "iva": sum(_centimos(linha["iva"]) for linha in mapa or []) / 100.0,
        "total": sum(_centimos(linha["total"]) for linha in mapa or []) / 100.0,
    }
