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

**E a decomposição faz-se DOCUMENTO A DOCUMENTO.** Fazia-se uma vez só, no
fim, sobre o total do turno por taxa — e dava outro número. Medido em 40
turnos simulados de 180 documentos: coincidiu em 3, com diferenças de −14 a
+6 cêntimos (num turno de 4 439,72 €, base 3 754,12 € contra 3 754,26 €). O
número que a AT vê e que a contabilista reconcilia é o do DOCUMENTO; um Z
que arredonde ao nível do turno não bate com a soma dos talões, e é o Z que
está errado. O meio-cêntimo arredonda onde a declaração é feita.

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
    isso é uma escolha que ninguém tomou).

    **O SINAL trata-se à parte, e é por causa da nota de crédito.** Uma NC
    entra aqui com o total NEGATIVO (é isso que a torna uma devolução no
    mapa do turno) e a divisão inteira do Python arredonda para −infinito,
    não para zero. Fazer a conta sobre o valor ABSOLUTO e repor o sinal no
    fim garante, por construção, que creditar uma fatura inteira a cancela
    EXACTAMENTE, ao cêntimo, nas três colunas — em vez de o garantir por
    acaso.

    **Honestamente: com as taxas de HOJE isto não muda um único resultado.**
    Mediu-se: para 0 %, 6 %, 13 % e 23 %, e para todos os totais até
    4 000,00 €, a versão com sinal e a versão ingénua dão o mesmo número. A
    álgebra diz porquê — as duas só divergem quando `2·base − (100+taxa)` é
    múltiplo de `2·(100+taxa)`, o que exige um denominador par com o resíduo
    certo, e 100, 106, 113 e 123 nunca o têm. Fica escrito porque uma
    mutação que o remova NÃO parte nenhum teste, e sem esta nota o próximo
    leitor concluiria que o guarda não está coberto em vez de que não é
    distinguível. Fica na mesma: custa uma multiplicação e deixa de ser
    preciso repetir esta prova no dia em que aparecer uma taxa nova."""
    sinal = -1 if total_centimos < 0 else 1
    numerador = abs(total_centimos) * 100
    denominador = 100 + taxa
    return sinal * ((2 * numerador + denominador) // (2 * denominador))


def _centimos_por_taxa(itens: List[Dict]) -> Dict[Optional[str], int]:
    """Quanto vale, em cêntimos, cada taxa DENTRO de um documento.

    À parte de `mapa_de_imposto` porque a mesma redução serve dois sítios: o
    mapa do turno (uma venda emitida) e o mapa de uma nota de crédito
    (`centimos_por_taxa_da_nota`, que soma as linhas creditadas). Uma segunda
    cópia desta soma era a forma óbvia de a nota de crédito deixar de
    cancelar exactamente a fatura que anula."""
    por_taxa: Dict[Optional[str], int] = {}
    for item in itens or []:
        tax_id = item.get("tax_id")
        por_taxa[tax_id] = por_taxa.get(tax_id, 0) + _centimos(_liquido_da_linha(item))
    return por_taxa


def _mapa_dos_documentos(documentos: List[Dict[Optional[str], int]]) -> List[Dict]:
    """O mapa de imposto de uma lista de DOCUMENTOS, cada um já reduzido a
    `{tax_id: cêntimos}` — o núcleo partilhado por tudo o que neste módulo
    produz um mapa.

    Um documento pode vir com cêntimos NEGATIVOS (é uma nota de crédito), e
    daí em diante nada muda: a base e o IVA de cada documento decompõem-se
    exactamente como os de uma fatura, com o sinal que o documento tiver."""
    por_taxa: Dict[Optional[str], Dict] = {}
    for centimos_deste in documentos:
        for tax_id, centimos in centimos_deste.items():
            linha = por_taxa.get(tax_id)
            if linha is None:
                linha = por_taxa[tax_id] = {
                    "centimos": 0, "base": 0, "iva": 0, "documentos": 0}
            linha["centimos"] += centimos
            linha["documentos"] += 1
            # **A BASE E O IVA SOMAM-SE DOCUMENTO A DOCUMENTO**, e não uma vez
            # no fim sobre o total do turno. É a mesma decomposição, feita ao
            # nível em que a declaração é feita: a AT vê documentos, a
            # contabilista reconcilia documentos, e o meio-cêntimo de cada um
            # deles arredonda no documento — não uma vez sobre a soma de 180.
            #
            # **Medido, com 40 turnos simulados de 180 documentos cada:** a
            # soma do turno e a soma documento a documento coincidiram em 3.
            # Diferenças de −14 a +6 cêntimos; num turno de 4 439,72 € o Z
            # dizia base 3 754,12 € e a soma por documento dava 3 754,26 €.
            # Nenhum dos dois números estava «errado» — mas só um deles é o
            # que a contabilista consegue reconstituir a partir dos talões, e
            # é esse que tem de sair no Z.
            #
            # A propriedade que já estava certa não se toca: o IVA é o RESTO
            # (`total − base`), nunca uma segunda multiplicação, e agora é o
            # resto DE CADA DOCUMENTO. `base + iva == total` continua exacto
            # por construção — em cada documento, e portanto na soma.
            taxa_desta = _TAXA_DO_CODIGO.get(tax_id)
            if taxa_desta is not None:
                base_deste = _base_em_centimos(centimos, taxa_desta)
                linha["base"] += base_deste
                linha["iva"] += centimos - base_deste

    saida = []
    for tax_id, linha in por_taxa.items():
        taxa = _TAXA_DO_CODIGO.get(tax_id)
        total_centimos = linha["centimos"]
        if taxa is None:
            base_centimos = iva_centimos = None
        else:
            base_centimos = linha["base"]
            iva_centimos = linha["iva"]
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


def mapa_da_nota(nota: Dict) -> List[Dict]:
    """O mapa de imposto de UMA nota de crédito, em POSITIVO — o que o ecrã
    mostra das linhas seleccionadas (Taxa · Base · IVA · Total), e o que a
    nota de crédito já emitida mostra quando alguém a abre.

    Positivo porque é assim que uma nota de crédito se lê no papel: ela
    própria diz o que credita, e é o DOCUMENTO que tem sinal negativo no
    turno. O sinal vive num sítio só — `centimos_por_taxa_da_nota` — e este
    mapa é a mesma função com o sinal desfeito, para não haver duas
    decomposições de IVA a poderem discordar sobre a mesma nota.

    Serve também a PRÉ-VISUALIZAÇÃO, com uma nota ainda por gravar: quem
    chama monta `{"linhas": [...]}` e recebe o mesmo mapa que a nota emitida
    vai ter. O ecrã não soma euros nenhuns — nem para pré-visualizar."""
    return _mapa_dos_documentos([
        {tax_id: -centimos
         for tax_id, centimos in centimos_por_taxa_da_nota(nota).items()}
    ])


def centimos_por_taxa_da_nota(nota: Dict) -> Dict[Optional[str], int]:
    """As linhas creditadas de uma nota de crédito GRAVADA, reduzidas a
    `{tax_id: cêntimos}` — e já com o sinal NEGATIVO que uma devolução tem
    no mapa do turno.

    Lê o retrato gravado (`linhas`, com o `tax_id` e o `total` de cada linha
    creditada) e não recalcula nada a partir da venda: a fatura de origem
    pode ter sido creditada em duas vezes, e o que esta nota vale é o que
    ficou escrito nela quando foi emitida — que é também o que foi entregue
    à Autoridade Tributária."""
    por_taxa: Dict[Optional[str], int] = {}
    for linha in nota.get("linhas") or []:
        tax_id = linha.get("tax_id")
        por_taxa[tax_id] = por_taxa.get(tax_id, 0) - _centimos(linha.get("total"))
    return por_taxa


def mapa_de_imposto(vendas: List[Dict], notas_credito: Optional[List[Dict]] = None) -> List[Dict]:
    """O mapa de imposto das vendas EMITIDAS de uma sessão, menos as notas de
    crédito emitidas nela.

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

    **As notas de crédito entram aqui, e entram como DOCUMENTOS.** Cada uma é
    um documento fiscal real do turno, com o sinal ao contrário: conta uma vez
    na coluna `documentos` da taxa que tocou (é o que o Vendus imprime, e o
    que a contabilista conta) e subtrai a base, o IVA e o total. Só as
    EMITIDAS — uma nota cuja emissão ficou por apurar não é documento nenhum
    até alguém confirmar que saiu, e um Z que a descontasse estava a devolver
    dinheiro que talvez nunca tenha sido devolvido.
    """
    documentos = [
        _centimos_por_taxa(_itens_vendus(venda))
        for venda in vendas or []
        if venda.get("estado") == "emitida"
    ]
    documentos.extend(
        centimos_por_taxa_da_nota(nota)
        for nota in notas_credito or []
        if nota.get("estado") == "emitida"
    )
    return _mapa_dos_documentos(documentos)


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
