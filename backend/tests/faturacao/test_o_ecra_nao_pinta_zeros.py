"""**O dinheiro que não é um número nunca se desenha como zero.**

Havia OITO cópias da mesma linha espalhadas pelo POS::

    const euros = (valor) =>
      `€ ${(Number(valor) || 0).toLocaleString('pt-PT', …)}`;

e esse `|| 0` transformava `undefined`, `null`, `NaN`, `''`, `{}` e `'abc'` num
"€ 0,00" perfeitamente legível. Medido no ecrã:

- uma venda emitida **sem `pagamentos`** deixava a coluna "Por tipo de
  pagamento" a somar 10,20 € debaixo de um "Total cobrado 11,35 €" — 1,15 €
  desaparecidos sem uma palavra;
- um `resumo` **ausente** (o servidor não respondeu, o campo mudou de nome)
  pintava um turno INTEIRO de € 0,00, com "Deve estar na gaveta € 0,00" — a
  funcionária fecha a gaveta com 200 € lá dentro a acreditar que está certo.

A formatação passa a ser UMA (`lib/pos.js::numeroPos`), e um valor que não seja
um número finito sai "?": não se parece com um número, não se soma de cabeça, e
obriga a perguntar. Zero continua a ser "0,00", que é uma resposta e não uma
ausência.

A técnica é a de `test_resumo_do_ecra.py` e `test_dinheiro_do_ecra_do_pos.py`:
o JavaScript é MESMO executado, extraído do ficheiro do POS sem cópia nenhuma
escrita aqui. E o guarda do TEXTO, esse, corre sempre — é ele que apanha o dia
em que alguém volte a escrever a nona cópia.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from .test_resumo_do_ecra import _corpo_da_funcao, _ler, _node

_RAIZ = Path(__file__).resolve().parents[3]
_LIB_POS = _RAIZ / "frontend" / "src" / "lib" / "pos.js"
_POS = _RAIZ / "frontend" / "src" / "pages" / "pos"
_RESUMO = _POS / "PosResumoDoTurno.js"

_ASSINATURA_NUMERO = "export const numeroPos = (valor) =>"

# **TODOS os ecrãs do POS, e não uma lista deles.** Estava aqui uma tupla de 7
# nomes, com um comentário a dizer que ela era à mão «de propósito, é ela que
# faz o guarda falhar quando alguém acrescentar um ecrã novo». Não fazia: a
# pasta tem 15 ficheiros, e os DOIS que tinham mesmo a sua cópia da formatação
# (`PosMenuCaixa.js` e `PosCaixaFechada.js`, medidos — campo ausente «€ 0,00»,
# campo a `null` «€ 0,00») eram, precisamente, dois dos oito que não estavam na
# lista. Uma lista que não contém aquilo que o guarda procura faz o guarda
# medir o vazio, e o comentário dizia o contrário.
#
# Percorre-se a PASTA. Um ecrã novo entra sozinho — e nunca mais há uma lista
# para alguém se esquecer de actualizar.
_MINIMO_DE_ECRAS = 15


def _ecras_do_pos():
    ficheiros = sorted(p.name for p in _POS.glob("*.js"))
    assert len(ficheiros) >= _MINIMO_DE_ECRAS, (
        "A pasta `pages/pos` tem %d ficheiros e o guarda contava com pelo "
        "menos %d — se ecrãs foram mesmo apagados, baixe-se este número de "
        "propósito; um glob que deixe de casar deixa este guarda a verificar "
        "o vazio, que é exactamente o que ele veio corrigir."
        % (len(ficheiros), _MINIMO_DE_ECRAS)
    )
    return ficheiros


def _formatado(valores, tmp_path):
    """Corre `numeroPos` em Node — o código que está mesmo no `lib/pos.js`."""
    corpo = _corpo_da_funcao(_ler(_LIB_POS), _ASSINATURA_NUMERO, _LIB_POS)
    guiao = tmp_path / "euros.js"
    guiao.write_text("\n".join([
        corpo.replace("export ", "", 1),
        "const casos = %s;" % json.dumps(valores),
        "process.stdout.write(JSON.stringify(casos.map((c) => numeroPos(c))));",
    ]), encoding="utf-8")
    r = subprocess.run([_node(), str(guiao)], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if r.returncode != 0:
        pytest.fail("O JavaScript do ecrã não correu:\n%s"
                    % r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


def test_as_seis_ausencias_deixam_de_se_ler_como_zero(tmp_path):
    """As seis que o `|| 0` engolia. `null` e `''` estão aqui de propósito,
    apesar de o `Number()` os converter em 0: são exactamente as duas ausências
    que chegam de uma resposta JSON e de um campo de texto vazio."""
    casos = [None, "", "abc", {}, [], "  "]
    assert _formatado(casos, tmp_path) == ["?"] * len(casos), (
        "Uma ausência voltou a desenhar-se como um número.")


def test_o_undefined_e_o_nan_tambem(tmp_path):
    """`undefined` e `NaN` não têm representação em JSON — vão por JavaScript."""
    corpo = _corpo_da_funcao(_ler(_LIB_POS), _ASSINATURA_NUMERO, _LIB_POS)
    guiao = tmp_path / "euros2.js"
    guiao.write_text("\n".join([
        corpo.replace("export ", "", 1),
        "process.stdout.write(JSON.stringify("
        "[numeroPos(undefined), numeroPos(NaN), numeroPos(1/0)]));",
    ]), encoding="utf-8")
    r = subprocess.run([_node(), str(guiao)], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert json.loads(r.stdout.decode("utf-8")) == ["?", "?", "?"]


def test_o_zero_continua_a_ser_zero(tmp_path):
    """Zero é uma RESPOSTA, não uma ausência: uma gaveta que deve ter 0,00 € é
    informação, e transformá-la em "?" era o defeito ao contrário."""
    assert _formatado([0, 0.0, "0", "0,00".replace(",", ".")], tmp_path) == [
        "0,00", "0,00", "0,00", "0,00"]


def test_os_numeros_continuam_a_sair_com_duas_casas_e_virgula(tmp_path):
    """E o formato português não muda: duas casas e vírgula decimal."""
    assert _formatado([11.35, 0.29, 1.15, 10.2], tmp_path) == [
        "11,35", "0,29", "1,15", "10,20"]


def test_nenhum_ecra_do_pos_volta_a_ter_a_sua_copia():
    """**O guarda que corre sempre, mesmo sem `node`.**

    Eram oito cópias, e é assim que uma família de defeitos nasce: corrigia-se
    uma e as outras sete ficavam. Nenhum ecrã do POS pode voltar a escrever a
    sua — a formatação vem de `lib/pos.js`.

    E percorre a PASTA inteira, não uma lista de nomes: com a lista, duas
    cópias vivas (`PosMenuCaixa.js` e `PosCaixaFechada.js`) ficaram oito meses
    à vista de um guarda que não olhava para elas."""
    culpados = []
    for nome in _ecras_do_pos():
        texto = _ler(_POS / nome)
        # O que se procura é a FORMATAÇÃO (o `toLocaleString('pt-PT')` com o
        # `|| 0` colado), e não o `centimosPos` — esse também tem um `|| 0` e
        # está certo: converter para cêntimos inteiros um campo vazio dá mesmo
        # zero, e é sobre esse zero que a comparação em inteiros trabalha.
        if re.search(r"\|\|\s*0\)[^\n]*\n?[^\n]*toLocaleString\('pt-PT'", texto):
            culpados.append(nome)
    assert not culpados, (
        "Voltou a haver uma cópia da formatação de dinheiro em %s. O `|| 0` "
        "pinta `undefined` de € 0,00, e foi assim que um turno inteiro de "
        "zeros passou por um Z." % ", ".join(culpados)
    )


def test_o_resumo_ausente_nao_se_desenha_como_um_turno_de_zeros():
    """Guarda de texto sobre o `PosResumoDoTurno`: com `resumo` a `undefined`,
    o componente tem de sair pela porta antes de desenhar a tabela.

    Um bloco inteiro de "€ ?" também não é resposta nenhuma — a resposta é
    dizer que não há números e mandar NÃO fechar a caixa."""
    texto = _ler(_RESUMO)
    assert "if (!resumo) {" in texto, (
        "O `PosResumoDoTurno` voltou a desenhar a tabela sem resumo nenhum.")
    saida = texto[texto.index("if (!resumo) {"):]
    saida = saida[:saida.index("\n  }")]
    assert "Não são zero" in saida and "NÃO feche a caixa" in saida, (
        "A frase do resumo ausente deixou de dizer que os números não são zero "
        "— e de mandar não fechar a caixa por ali.")


def _predicado(assinatura, casos, tmp_path, nome_da_funcao):
    """Corre em Node um dos predicados do resumo — o código que está mesmo no
    `lib/pos.js`, sem cópia nenhuma escrita aqui.

    É por isto que eles vivem lá e não dentro do JSX: uma condição escrita no
    meio de uma tabela não se corre em lado nenhum, e um guarda que só procure o
    TEXTO da frase fica verde com a condição desligada (`false && …`)."""
    corpo = _corpo_da_funcao(_ler(_LIB_POS), assinatura, _LIB_POS)
    guiao = tmp_path / ("%s.js" % nome_da_funcao)
    guiao.write_text("\n".join([
        corpo.replace("export ", "", 1),
        "const casos = %s;" % json.dumps(casos),
        "process.stdout.write(JSON.stringify(casos.map((c) => %s(c))));"
        % nome_da_funcao,
    ]), encoding="utf-8")
    r = subprocess.run([_node(), str(guiao)], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if r.returncode != 0:
        pytest.fail("O JavaScript do ecrã não correu:\n%s"
                    % r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


def test_o_ecra_repara_mesmo_numa_taxa_que_o_servidor_nao_conhece(tmp_path):
    """«XPTO (?) | 1 | — | — | € 1,15» e o rodapé a somar 9,03 + 1,17 contra um
    total de 11,35: ao balcão lê-se como um total partido. A decisão corre em
    Node, não se lê no ficheiro."""
    mapa_bom = [{"tax_id": "INT", "taxa": 13, "base": 9.03, "iva": 1.17},
                {"tax_id": "NOR", "taxa": 23, "base": 0.93, "iva": 0.22}]
    mapa_mau = mapa_bom + [{"tax_id": "XPTO", "taxa": None, "base": None, "iva": None}]
    assert _predicado(
        "export const temTaxaDesconhecida = (mapa) =>",
        [[], mapa_bom, mapa_mau, [{"tax_id": "X"}]], tmp_path,
        "temTaxaDesconhecida",
    ) == [False, False, True, True], (
        "O ecrã deixou de reparar que há uma taxa que o servidor não conhece — "
        "e a última linha da tabela volta a não fechar sem uma palavra.")


def test_o_ecra_so_desenha_a_linha_do_por_registar_quando_ha_algo_por_registar(tmp_path):
    """`0` é o caso normal (está tudo cobrado) e não desenha linha nenhuma; um
    valor que não seja um número não pode ligar uma linha de dinheiro em
    branco. E 1,15 € tem de a ligar."""
    casos = [
        None, {}, {"pagamentos_por_registar": 0}, {"pagamentos_por_registar": 0.0},
        {"pagamentos_por_registar": None}, {"pagamentos_por_registar": "1.15"},
        {"pagamentos_por_registar": 1.15}, {"pagamentos_por_registar": 11.35},
        {"pagamentos_por_registar": -0.29},
    ]
    assert _predicado(
        "export const haPagamentosPorRegistar = (resumo) =>",
        casos, tmp_path, "haPagamentosPorRegistar",
    ) == [False, False, False, False, False, False, True, True, True], (
        "A linha do que ficou por registar voltou a acender-se (ou a apagar-se) "
        "na altura errada.")


def test_uma_taxa_desconhecida_avisa_que_o_total_nao_fecha():
    """«XPTO (?) | 1 | — | — | € 1,15» e o rodapé a somar 9,03 + 1,17 contra um
    total de 11,35: ao balcão lê-se como um total partido. A linha do Total
    passa a trazer a razão por baixo."""
    texto = _ler(_RESUMO)
    assert "comTaxaDesconhecida" in texto, (
        "O ecrã deixou de reparar que há uma taxa que o servidor não conhece.")
    assert "NÃO somam o Total" in texto, (
        "O aviso de que a Base e o IVA não somam o Total desapareceu — a "
        "tabela volta a parecer uma soma errada.")


def test_o_que_ficou_por_registar_aparece_na_coluna_dos_pagamentos():
    """O número vem SOMADO do servidor (`pagamentos_por_registar`) e o ecrã só
    o desenha — nunca soma a coluna para o descobrir."""
    texto = _ler(_RESUMO)
    assert "pagamentos_por_registar" in texto, (
        "A linha do que ficou por registar desapareceu do ecrã: a coluna volta "
        "a somar menos do que o rodapé, sem uma palavra.")
    assert "Sem tipo de pagamento registado" in texto
    # Só o CÓDIGO: o comentário do topo do ficheiro fala de `reduce` de
    # propósito, para explicar porque é que não há nenhum.
    codigo = "\n".join(
        linha for linha in texto.split("\n")
        if not linha.strip().startswith("//") and not linha.strip().startswith("*"))
    assert ".reduce(" not in codigo, (
        "O ecrã voltou a somar dinheiro — a aritmética é do servidor.")


# --- O ecrã do fecho não manda cobrar o que não se cobra -----------------------

_FECHAR = _POS / "PosFecharCaixa.js"


def test_o_dialogo_do_fecho_nao_manda_cobrar_a_conta_que_o_balcao_nao_alcanca():
    """Uma mãe `separada` a quem a divisão morreu a meio chega agora a este
    diálogo (antes não chegava a lado nenhum). Se caísse no monte do "por
    cobrar", a operadora lia «cobre-as antes de fechar; se ninguém pagar,
    cancele-as» — e as duas saídas devolvem 409 sobre ela, que nem sequer
    aparece num ecrã de onde se lhe possa pegar.

    É o mesmo defeito que o `entregue_ao_gestor` veio corrigir: pedir-lhe o que
    a rota recusa custa-lhe uma tentativa e um telefonema."""
    texto = _ler(_FECHAR)
    assert "foraDoAlcanceDoBalcao" in texto, (
        "O diálogo do fecho voltou a tratar todas as contas por cobrar como "
        "cobráveis no balcão.")
    assert "estado_da_venda != null" in texto, (
        "A comparação deixou de proteger a resposta de um servidor anterior a "
        "este campo — que passaria a dizer que NENHUMA conta se cobra.")
    assert "não se cobra no balcão" in texto
    assert "Contas por Resolver" in texto, (
        "A ressalva deixou de dizer ONDE é que essa conta se resolve.")


# --- «Ontem: 0,00 €» quando ontem foram 45,90 € ------------------------------


def test_o_ecra_diz_ATE_QUANDO_conta_o_ontem_de_cada_loja():
    """O dono: «teve faturação ontem em oeiras. mas está a dizer que foi
    0,00 €.» A conta estava certa — a loja abriu a caixa às 19:09 e ele viu o
    painel às 17:25, e o «Ontem» dos cartões pára à mesma hora a que hoje vai.
    A ETIQUETA é que mentia: «Ontem: 0,00 €» lê-se como «ontem a loja não fez
    nada».

    Afirmado sobre o ficheiro do ecrã e não sobre um valor: o que se prende
    aqui é que a etiqueta CARREGA a hora, e não o número que ela mostra."""
    from pathlib import Path
    ecra = (Path(__file__).resolve().parents[2].parent / "frontend" / "src" /
            "pages" / "admin" / "faturacao" / "FatDashboard.js").read_text(encoding="utf-8")
    # O «Ontem» deixou de levar hora: passou a ser o dia anterior INTEIRO.
    # O que continua a precisar dela é o MENSAL, que compara um mês a meio com
    # o mesmo pedaço do mês anterior.
    assert "Ontem{ateAsHoras}" not in ecra, (
        "O «Ontem» voltou a dizer uma hora de corte que já não existe.")
    assert "Anterior{ateAsHoras}" in ecra, (
        "A etiqueta do «Anterior» mensal por loja perdeu a hora de corte.")
    assert "dashboard?.hora_de_corte" in ecra, (
        "O ecrã deixou de ler a `hora_de_corte` que o servidor manda.")
