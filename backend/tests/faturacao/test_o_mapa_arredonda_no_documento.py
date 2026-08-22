"""**O mapa de imposto arredonda no DOCUMENTO, não no turno.**

O mapa agregava os cêntimos de cada taxa ao longo do turno inteiro e só no fim
é que tirava a base do total — uma decomposição, para 180 documentos. A soma
DOCUMENTO A DOCUMENTO, que é o que a AT vê e o que a contabilista reconcilia a
partir dos talões, dá outro número.

**Medido, em 40 turnos simulados de 180 documentos cada** (preços 0,29 · 1,15 ·
10,20 · 8,99 · 2,99 · 3,45 · 0,85 · 6,30 · 12,75 · 1,99, quantidades 1 a 3,
taxas INT e NOR ao acaso, semente fixa): **coincidiu em 3**. Diferenças de −14
a +6 cêntimos; num turno de 4 439,72 € o Z dizia base 3 754,12 € e a soma por
documento dava 3 754,26 €.

Nenhum dos dois números está "errado" em aritmética. Só um deles é o que alguém
consegue reconstituir a partir dos documentos, e é esse que tem de sair no Z.

O que NÃO muda, e está aqui prendido: o IVA continua a ser o RESTO
(`total − base`), nunca uma segunda multiplicação — agora o resto de cada
documento —, e `soma das bases + soma dos IVAs == total dos documentos` continua
exacto ao cêntimo.
"""
import random

from faturacao.mapa_imposto import (
    _TAXA_DO_CODIGO,
    _base_em_centimos,
    _centimos,
    _liquido_da_linha,
    mapa_de_imposto,
    totais_do_mapa,
)
from faturacao.fiscal import _itens_vendus

ACAI = "INT"
REFRI = "NOR"


def _linha(nome, preco, tax_id, quantidade=1, **extra):
    linha = {
        "id": "linha-%s" % nome, "produto_nome": nome, "produto_preco": preco,
        "produto_tax_id": tax_id, "quantidade": quantidade,
    }
    linha.update(extra)
    return linha


def _venda(linhas, id="venda-1", **extra):
    venda = {
        "id": id, "estado": "emitida", "linhas": linhas,
        "desconto_global_pct": None, "desconto_global_eur": None,
    }
    venda.update(extra)
    return venda


def _soma_documento_a_documento(vendas):
    """**O oráculo: a soma que a contabilista faz a partir dos talões.**

    Escrita aqui à mão de propósito — decompõe cada documento com
    `_base_em_centimos` (a mesma aritmética inteira, que é a parte que já
    estava provada) e soma as decomposições. Se fosse `mapa_de_imposto` outra
    vez, isto era um espelho e não um oráculo."""
    base = iva = total = 0
    for v in vendas:
        if v.get("estado") != "emitida":
            continue
        por_taxa = {}
        for item in _itens_vendus(v):
            por_taxa[item.get("tax_id")] = (
                por_taxa.get(item.get("tax_id"), 0)
                + _centimos(_liquido_da_linha(item)))
        for tax_id, centimos in por_taxa.items():
            total += centimos
            taxa = _TAXA_DO_CODIGO.get(tax_id)
            if taxa is not None:
                b = _base_em_centimos(centimos, taxa)
                base += b
                iva += centimos - b
    return base, iva, total


def _turno_ao_acaso(rng, quantos=180):
    precos = [0.29, 1.15, 10.20, 8.99, 2.99, 3.45, 0.85, 6.30, 12.75, 1.99]
    vendas = []
    for d in range(quantos):
        linhas = [
            _linha("p%d" % k, rng.choice(precos), rng.choice([ACAI, REFRI]),
                   quantidade=rng.randint(1, 3))
            for k in range(rng.randint(1, 4))
        ]
        vendas.append(_venda(linhas, id="v%d" % d))
    return vendas


def test_o_z_diz_o_mesmo_que_a_soma_dos_talões_em_40_turnos():
    """O guarda inteiro, com os números que mediram o defeito: 40 turnos de
    180 documentos. Antes coincidia em 3."""
    rng = random.Random(20260821)
    discordancias = []
    for turno in range(40):
        vendas = _turno_ao_acaso(rng)
        totais = totais_do_mapa(mapa_de_imposto(vendas))
        base, iva, total = _soma_documento_a_documento(vendas)
        if (_centimos(totais["base"]), _centimos(totais["iva"])) != (base, iva):
            discordancias.append((
                turno, totais["total"], totais["base"], base / 100.0,
                _centimos(totais["base"]) - base))

    assert not discordancias, (
        "O mapa voltou a arredondar ao nível do turno: em %d dos 40 turnos a "
        "base do Z não é a soma das bases dos documentos. Primeiro: turno de "
        "%.2f € — o Z diz %.2f, os talões dão %.2f (%+d cêntimos)."
        % (len(discordancias), discordancias[0][1], discordancias[0][2],
           discordancias[0][3], discordancias[0][4])
    )


def test_um_turno_pequeno_onde_a_diferenca_se_ve_a_olho():
    """O mesmo defeito num turno que cabe numa linha, para se ver de onde vem.

    Três documentos de 1,15 € a 23 %: a base de cada um é
    `115 × 100 / 123 = 93,49…` → 93 cêntimos, e 3 × 93 = 279. Somados primeiro
    (345 cêntimos) e decompostos no fim dá `345 × 100 / 123 = 280,48…` → 280.
    Um cêntimo de diferença em três documentos de 1,15 €, e é o cêntimo que a
    contabilista não consegue reconstituir."""
    vendas = [_venda([_linha("refri", 1.15, REFRI)], id="v%d" % i) for i in range(3)]

    mapa = mapa_de_imposto(vendas)
    assert [(l["tax_id"], l["documentos"], l["base"], l["iva"], l["total"])
            for l in mapa] == [("NOR", 3, 2.79, 0.66, 3.45)], (
        "A base deixou de ser a soma das bases dos três documentos.")


def test_o_iva_continua_a_ser_o_resto_e_nao_uma_segunda_multiplicacao():
    """A propriedade que já estava certa e não se toca: em cada linha do mapa,
    `base + iva == total` ao cêntimo. Se o IVA passasse a ser uma segunda
    multiplicação, os dois arredondamentos podiam cair do mesmo lado e a linha
    deixava de fechar."""
    rng = random.Random(7)
    for _ in range(20):
        mapa = mapa_de_imposto(_turno_ao_acaso(rng, quantos=25))
        for linha in mapa:
            if linha["taxa"] is None:
                continue
            assert _centimos(linha["base"]) + _centimos(linha["iva"]) == _centimos(
                linha["total"]), ("A linha %r não fecha: %r" % (linha["tax_id"], linha))


def test_a_soma_das_bases_mais_a_dos_ivas_da_o_total_do_turno():
    """E o rodapé fecha com as colunas, que é o que torna o mapa legível."""
    rng = random.Random(11)
    for _ in range(20):
        vendas = _turno_ao_acaso(rng, quantos=40)
        totais = totais_do_mapa(mapa_de_imposto(vendas))
        assert _centimos(totais["base"]) + _centimos(totais["iva"]) == _centimos(
            totais["total"]), totais


# --- Duas das TRÊS mutações que sobreviveram à ronda anterior ------------------


def test_a_ordem_do_mapa_e_por_taxa_crescente_com_a_desconhecida_no_fim():
    """A ordem está documentada («por taxa crescente, com as desconhecidas no
    fim — a ordem em que um mapa de imposto se lê, e determinística») e não
    tinha guarda nenhum: apagar o `sort` deixava a suite inteira verde, e a
    tabela do Z passava a sair pela ordem em que as taxas apareceram no turno,
    que muda de noite para noite."""
    vendas = [
        _venda([_linha("desconhecida", 1.15, "XPTO")], id="v1"),
        _venda([_linha("refri", 1.15, REFRI)], id="v2"),
        _venda([_linha("acai", 10.20, ACAI)], id="v3"),
        _venda([_linha("isento", 0.29, "ISE")], id="v4"),
    ]

    assert [l["tax_id"] for l in mapa_de_imposto(vendas)] == [
        "ISE", "INT", "NOR", "XPTO"], (
        "O mapa deixou de sair por taxa crescente com a desconhecida no fim.")


def test_uma_taxa_desconhecida_nao_ganha_base_nem_iva_nem_perde_o_dinheiro():
    """A regra de ouro de `precos.py` aplicada ao mapa: não se inventa uma
    taxa, e não se deixa cair o dinheiro."""
    mapa = mapa_de_imposto([_venda([_linha("x", 1.15, "XPTO")])])

    assert mapa == [{"tax_id": "XPTO", "taxa": None, "documentos": 1,
                     "base": None, "iva": None, "total": 1.15}]
    totais = totais_do_mapa(mapa)
    assert (totais["base"], totais["iva"], totais["total"]) == (0.0, 0.0, 1.15), (
        "A linha desconhecida tem de contar para o total e NÃO para a base nem "
        "para o IVA — e é assim que ela dá nas vistas.")
