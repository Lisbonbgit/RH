"""O ecrã de finalizar deixa de perguntar o valor de um pagamento que não tem dúvida.

O dono, a percorrer o POS: «se a pessoa selecionar só um tipo de pagamento não
precisa mostrar esta caixa de valor que aparece em baixo. só aparece a opção de
colocar o valor de cada tipo de pagamento quando a pessoa selecionar dinheiro e
multibanco os dois. pois se o staff seleciona só uber ou só multibanco ou só
glovo. significa que o valor estava já certo.»

Medido no browser antes de mexer: com "Multibanco" sozinho numa conta de
8,50 €, o ecrã acrescentava uma linha de 630×94px — uma caixa de 502×64px com
o 8,50 já lá dentro, o botão da calculadora de 64×64 e o × de 48px — para
perguntar um número com uma única resposta possível. Em todas as vendas
normais do dia.

**Porque é que isto é um teste em Python a correr JavaScript.** A decisão vivia
dentro do `map` do JSX, onde nenhum teste lhe chega: mudá-la (ou desfazê-la)
não fazia nada ficar vermelho. Saiu para uma função pura e exportada,
`camposDeValorDoPagamento`, e este ficheiro CORRE-A em Node, exactamente como
está escrita no ecrã — sem uma segunda cópia da regra escrita aqui. É a
técnica do `test_resumo_do_ecra.py` e do `test_partes_por_cobrar_no_ecra.py`,
e a razão é a mesma: uma decisão que nenhum teste consegue executar é uma
decisão que se troca sem ninguém dar por isso.

O que este ficheiro NÃO pode deixar passar em silêncio, e por isso também tem
guardas de texto:

· que a regra volte a ser decidida à mão dentro do componente (o `map` do JSX
  tem de CHAMAR a função, não redescobri-la);
· que o **valor recebido** passe a depender do número de pagamentos. Não pode:
  é dele que sai o troco, e o dono foi explícito — «ainda fica disponível o
  valor recebido que dá muito jeito quando o pagamento é em dinheiro dar o
  troco né». Depende só do tipo dar troco, com ou sem repartição.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_POS_FINALIZAR = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosFinalizar.js"

_ASSINATURA_CENTIMOS = "const centimos = (valor) =>"
_ASSINATURA_CAMPOS = "export const camposDeValorDoPagamento = (pagamentos, totalCentimos) => {"
_ASSINATURA_QUADRO = (
    "export const mostrarQuadroDePagamentos = (pagamentos, comCampoDeValor) => {")
_ASSINATURA_TROCO = "const mostrarTroco ="


def _ler(ficheiro: Path) -> str:
    if not ficheiro.exists():
        pytest.fail(
            "Não encontrei %s. Se o ecrã mudou de sítio, este guarda tem de ir "
            "atrás dele — não se apaga." % ficheiro
        )
    return ficheiro.read_text(encoding="utf-8")


def _corpo_da_funcao(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O código de uma função, do início da assinatura até à chaveta que a
    fecha. Falha alto se a assinatura desapareceu: um guarda que não encontra
    o que devia vigiar e se cala passa a verde para sempre."""
    if assinatura not in texto:
        pytest.fail(
            "Não encontrei `%s` em %s. Se a função foi renomeada ou movida, a "
            "regra que ela cumpre continua a ter de ser guardada."
            % (assinatura, ficheiro.name)
        )
    inicio = texto.index(assinatura)
    i = texto.index("{", inicio + len(assinatura) - 1)
    profundidade = 0
    for fim in range(i, len(texto)):
        if texto[fim] == "{":
            profundidade += 1
        elif texto[fim] == "}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio:fim + 1]
    pytest.fail("A função `%s` em %s não fecha." % (assinatura, ficheiro.name))


def _corpo_da_seta(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O mesmo, para uma expressão de uma linha: até ao `;`."""
    if assinatura not in texto:
        pytest.fail("Não encontrei `%s` em %s." % (assinatura, ficheiro.name))
    inicio = texto.index(assinatura)
    fim = texto.index(";", inicio)
    return texto[inicio:fim + 1]


def _sem_comentarios(codigo: str) -> str:
    """O código sem os comentários — os comentários deste ecrã descrevem o
    defeito com as palavras dele, e um guarda que procurasse essas palavras no
    texto todo ficava vermelho por causa da explicação em vez do código."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", codigo, flags=re.S))


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    # O node deste Mac vive fora do PATH (ver a memória do projecto). Sem ele
    # o teste diz porque não correu, em vez de ficar verde a fingir.
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip(
        "Sem `node` para executar o JavaScript do ecrã "
        "(nem no PATH nem em ~/.local/node/bin)."
    )


def _o_que_o_ecra_pergunta(casos, tmp_path: Path):
    """Corre em Node a decisão tal como está escrita no `PosFinalizar.js` —
    sem cópia nenhuma dela escrita aqui."""
    ecra = _ler(_POS_FINALIZAR)
    guiao = tmp_path / "campos.js"
    guiao.write_text(
        "\n".join([
            # `export` fora: isto corre como um guião solto, não como módulo.
            _corpo_da_seta(ecra, _ASSINATURA_CENTIMOS, _POS_FINALIZAR),
            _corpo_da_funcao(ecra, _ASSINATURA_CAMPOS, _POS_FINALIZAR).replace("export ", "", 1),
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map(",
            "  ({ pagamentos, totalCentimos }) => camposDeValorDoPagamento(pagamentos, totalCentimos)",
            ")));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


# A conta que está no browser: um Açaí Grande de 8,50 €.
_TOTAL = 850


def _pagamento(tipo, valor):
    """Como o ecrã guarda um pagamento — o `valor` é sempre STRING, nunca
    Number (é um campo controlado a meio de ser escrito)."""
    return {"tipo_pagamento_id": tipo, "valor": valor, "auto": True}


@pytest.mark.parametrize("tipo", ["multibanco", "uber", "glovo", "dinheiro"])
def test_um_tipo_sozinho_nao_leva_caixa_de_valor(tipo, tmp_path):
    """A queixa do dono, com os quatro tipos que ele nomeou. Um só tipo
    escolhido quer dizer que o valor já estava certo: é o total da conta, e
    não há segunda resposta possível."""
    campos = _o_que_o_ecra_pergunta(
        [{"pagamentos": [_pagamento(tipo, "8.50")], "totalCentimos": _TOTAL}], tmp_path
    )[0]
    assert campos == [], (
        "Com %s sozinho o ecrã ainda pergunta o valor. Não há nada a decidir: "
        "é a conta toda." % tipo
    )


def test_dois_tipos_levam_uma_caixa_cada(tmp_path):
    """"só aparece a opção de colocar o valor de cada tipo de pagamento quando
    a pessoa selecionar dinheiro e multibanco os dois" — aí é a operadora que
    reparte, e nenhum dos dois valores se adivinha."""
    campos = _o_que_o_ecra_pergunta([{
        "pagamentos": [_pagamento("dinheiro", "3.50"), _pagamento("multibanco", "5.00")],
        "totalCentimos": _TOTAL,
    }], tmp_path)[0]
    assert campos == ["dinheiro", "multibanco"], (
        "Com a conta repartida por dois, os DOIS campos têm de aparecer — um "
        "por tipo."
    )


def test_tres_tipos_levam_tres_caixas(tmp_path):
    campos = _o_que_o_ecra_pergunta([{
        "pagamentos": [
            _pagamento("dinheiro", "2.50"),
            _pagamento("multibanco", "5.00"),
            _pagamento("uber", "1.00"),
        ],
        "totalCentimos": _TOTAL,
    }], tmp_path)[0]
    assert campos == ["dinheiro", "multibanco", "uber"]


def test_sem_pagamento_escolhido_nao_ha_campo_nenhum(tmp_path):
    """Antes de escolher como se paga não há linha nenhuma para mostrar — o
    ecrã pede é que se escolha um tipo."""
    for vazio in ([], None):
        campos = _o_que_o_ecra_pergunta(
            [{"pagamentos": vazio, "totalCentimos": _TOTAL}], tmp_path
        )[0]
        assert campos == []


def test_um_tipo_com_o_valor_errado_volta_a_ter_caixa(tmp_path):
    """O beco sem saída que esta regra tinha de evitar, com os números do
    balcão: Dinheiro (automático, 8,50) + Multibanco, escrever 5,00 no
    Multibanco, e retirar o Dinheiro. Fica UM pagamento — mas de 5,00 numa
    conta de 8,50, porque foi escrito à mão e o ecrã nunca reescreve por baixo
    da operadora.

    Sem esta linha o ecrã dizia "Falta distribuir € 3,50" com o EMITIR morto e
    **sem caixa nenhuma onde escrever**, com fila à frente."""
    campos = _o_que_o_ecra_pergunta([{
        "pagamentos": [{"tipo_pagamento_id": "multibanco", "valor": "5.00", "auto": False}],
        "totalCentimos": _TOTAL,
    }], tmp_path)[0]
    assert campos == ["multibanco"], (
        "Um pagamento sozinho que NÃO cobre a conta tem de continuar a ter "
        "caixa — senão não há por onde a corrigir."
    )


# OS VALORES SÃO O TESTE. Este guarda existe para uma coisa só: impedir que a
# comparação de dinheiro volte à vírgula flutuante. E até 2026-08-21 não a
# impedia — trocar `centimos(unico.valor) === totalCentimos` por
# `Number(unico.valor) * 100 === totalCentimos` deixava a suite TODA verde
# (1107 passed), porque os valores escolhidos (0,30 / 8,50 / 8,49 / "") são
# todos casos em que `Number(v) * 100` calha dar um inteiro exacto. Um teste
# que não consegue ficar vermelho é pior do que não existir: a próxima pessoa
# acredita nele.
#
# Estes três são os que apanham. Em Node:
#   Number('10.20') * 100 -> 1019.9999999999999
#   Number('1.15')  * 100 ->  114.99999999999999
#   Number('0.29')  * 100 ->   28.999999999999996
# São contas de balcão banais — um açaí de 10,20 €, um café e um bolo a 1,15 €,
# uma saca a 0,29 €. Com a comparação em vírgula flutuante, o ecrã dizia à
# operadora que faltava um cêntimo numa venda certa, e punha-lhe uma caixa de
# valor à frente para "corrigir" o que já estava certo.
#
# `test_os_valores_deste_ficheiro_sao_mesmo_a_armadilha` (aqui em baixo) prova
# em Node que estes pares são MESMO a armadilha — se alguém os trocar por
# valores inofensivos, é esse teste que fica vermelho a dizer porquê.
_ARMADILHAS_DA_VIRGULA_FLUTUANTE = (("10.20", 1020), ("1.15", 115), ("0.29", 29))


@pytest.mark.parametrize(
    "valor,total,esperado",
    [(valor, total, []) for valor, total in _ARMADILHAS_DA_VIRGULA_FLUTUANTE]
    + [
        # 0,1 + 0,2 dá 0.30000000000000004 em JS. A comparação é em CÊNTIMOS
        # INTEIROS, como no servidor (fiscal.py::finalizar) — se fosse em
        # vírgula flutuante, esta conta ficava para sempre a dizer que faltava
        # um cêntimo e a caixa aparecia numa venda que estava certa.
        ("0.30", 30, []),
        ("8.50", 850, []),
        # Um cêntimo a menos é um cêntimo a menos: a caixa tem de voltar.
        ("10.19", 1020, ["x"]),
        ("8.49", 850, ["x"]),
        # O campo em branco (`Number('') === 0`) não é o total de nada.
        ("", 850, ["x"]),
    ],
)
def test_a_comparacao_e_em_centimos_inteiros(valor, total, esperado, tmp_path):
    campos = _o_que_o_ecra_pergunta(
        [{"pagamentos": [_pagamento("x", valor)], "totalCentimos": total}], tmp_path
    )[0]
    assert campos == esperado, (
        "Com %r numa conta de %d cêntimos o ecrã devia pedir %r. Se isto caiu "
        "logo a seguir a mexer no `centimos`, a comparação voltou a ser em "
        "vírgula flutuante: Number(%r) * 100 não é %d."
        % (valor, total, esperado, valor, total)
    )


def test_os_valores_deste_ficheiro_sao_mesmo_a_armadilha(tmp_path):
    """O guarda do guarda: prova em Node que os valores de cima são os que
    distinguem `Math.round(v * 100)` de `v * 100`. Sem isto, o teste desta
    regra pode ser desarmado sem uma linha vermelha — bastava alguém escolher
    outros valores tão razoáveis como 8,50."""
    guiao = tmp_path / "armadilha.js"
    guiao.write_text(
        "const casos = %s;\n"
        "process.stdout.write(JSON.stringify("
        "casos.map(([valor, total]) => Number(valor) * 100 === total)));"
        % json.dumps([list(par) for par in _ARMADILHAS_DA_VIRGULA_FLUTUANTE]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert resultado.returncode == 0, resultado.stderr.decode("utf-8", "replace")
    exacto = json.loads(resultado.stdout.decode("utf-8"))
    assert exacto == [False] * len(_ARMADILHAS_DA_VIRGULA_FLUTUANTE), (
        "Estes valores deixaram de ser a armadilha: %s. Em vírgula flutuante "
        "eles TÊM de falhar a comparação — é essa a razão de existirem. Se "
        "alguém os trocou por valores certinhos, o teste do `centimos` deixou "
        "de guardar seja o que for; escolham outros que partam (0,29 / 1,15 / "
        "10,20 partem)."
        % list(zip(_ARMADILHAS_DA_VIRGULA_FLUTUANTE, exacto))
    )


# --- Guardas de texto: o que não se consegue executar ------------------------


def test_o_ecra_chama_a_funcao_em_vez_de_redescobrir_a_regra():
    """A decisão só está guardada enquanto for ESTA função a fazê-la. Escrita
    outra vez à mão dentro do JSX, os testes de cima continuavam verdes e o
    ecrã fazia outra coisa."""
    ecra = _sem_comentarios(_ler(_POS_FINALIZAR))
    assert "camposDeValorDoPagamento(pagamentos, totalCentimos)" in ecra, (
        "O PosFinalizar deixou de chamar `camposDeValorDoPagamento`. A regra "
        "não pode voltar para dentro do JSX, onde nenhum teste lhe chega."
    )
    assert "comCampoDeValor.includes(p.tipo_pagamento_id)" in ecra, (
        "A linha do pagamento deixou de perguntar à decisão se leva caixa de "
        "valor."
    )


def test_o_valor_recebido_nao_depende_de_quantos_pagamentos_ha():
    """«ainda fica disponível o valor recebido que dá muito jeito quando o
    pagamento é em dinheiro dar o troco né» — com um tipo ou com três. O
    `mostrarTroco` olha para o `da_troco` do TIPO e para mais nada; assim que
    olhasse para o número de pagamentos, o troco desaparecia exactamente na
    venda mais comum do balcão (dinheiro sozinho)."""
    ecra = _ler(_POS_FINALIZAR)
    linha = _sem_comentarios(_corpo_da_seta(ecra, _ASSINATURA_TROCO, _POS_FINALIZAR))
    assert "da_troco" in linha, "O `mostrarTroco` deixou de olhar para o `da_troco` do tipo."
    assert "length" not in linha and "comCampoDeValor" not in linha, (
        "O valor recebido passou a depender de quantos pagamentos há: %s\n"
        "Não pode. O troco sai do dinheiro, haja um tipo ou três." % linha.strip()
    )


# --- O passo seguinte do mesmo pedido ----------------------------------------
#
# O dono voltou ao mesmo ecrã, agora com o Multibanco sozinho numa conta de
# 34,90 €: «quando o staff clicar em somente uma forma de pagamento, nao
# precisa mostrar esse multibanco o valor total e o pagamento certo. (nao faz
# sentido) portanto tira isso.»
#
# A caixa de valor já tinha desaparecido (é disso que trata o resto deste
# ficheiro). O que sobrava era a LINHA a repetir «Multibanco 34,90 €» — o total
# que ela tem à frente, escrito outra vez — e o indicador verde «Pagamentos
# certos», a confirmar uma soma de uma parcela só. Duas afirmações verdadeiras
# e inúteis, em todas as vendas normais do dia.
#
# A regra sai do JSX pela mesma razão de sempre: uma decisão dentro de um
# `{... && (` não é executável por teste nenhum.


def _mostra_o_quadro(casos, tmp_path: Path):
    """Corre em Node a decisão tal como está escrita no ecrã."""
    ecra = _ler(_POS_FINALIZAR)
    guiao = tmp_path / "quadro.js"
    guiao.write_text(
        "\n".join([
            _corpo_da_funcao(ecra, _ASSINATURA_QUADRO, _POS_FINALIZAR).replace("export ", "", 1),
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map(",
            "  ({ pagamentos, comCampoDeValor }) =>",
            "    mostrarQuadroDePagamentos(pagamentos, comCampoDeValor)",
            ")));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if resultado.returncode != 0:
        pytest.fail("O JavaScript do ecrã não correu:\n%s"
                    % resultado.stderr.decode("utf-8", "replace"))
    return json.loads(resultado.stdout.decode("utf-8"))


@pytest.mark.parametrize("tipo", ["multibanco", "uber", "glovo", "dinheiro"])
def test_um_tipo_sozinho_NAO_mostra_quadro_nenhum(tipo, tmp_path):
    """«quando se clica em somente um, nao precisa aparecer nada» — nem a
    linha a repetir o total, nem o visto verde."""
    assert _mostra_o_quadro(
        [{"pagamentos": [_pagamento(tipo, "34.90")], "comCampoDeValor": []}],
        tmp_path)[0] is False


def test_dois_tipos_MOSTRAM_o_quadro(tmp_path):
    """«quando clicar em dinheiro e multibanco ai aparece as caixas em baixo
    para colocar o valor de cada pagamento» — e com elas o indicador, que aí
    tem mesmo uma soma para confirmar."""
    assert _mostra_o_quadro([{
        "pagamentos": [_pagamento("dinheiro", "10.00"), _pagamento("multibanco", "24.90")],
        "comCampoDeValor": ["dinheiro", "multibanco"],
    }], tmp_path)[0] is True


def test_um_tipo_com_o_valor_ERRADO_volta_a_mostrar_o_quadro(tmp_path):
    """O caso que não se pode esconder: tira-se um dos dois pagamentos depois
    de lhe ter escrito um valor à mão, e sobra um só que NÃO bate com o total.
    Aí há uma caixa para preencher — escondê-la deixava a operadora com o
    EMITIR morto e sem nada onde escrever."""
    assert _mostra_o_quadro([{
        "pagamentos": [_pagamento("multibanco", "10.00")],
        "comCampoDeValor": ["multibanco"],
    }], tmp_path)[0] is True


def test_sem_pagamento_nenhum_nao_ha_quadro(tmp_path):
    assert _mostra_o_quadro(
        [{"pagamentos": [], "comCampoDeValor": []}], tmp_path)[0] is False


def test_o_ecra_CHAMA_a_funcao_do_quadro_em_vez_de_a_redescobrir():
    """O mesmo guarda do `camposDeValorDoPagamento`: a regra pode voltar para
    dentro do JSX sem nada ficar vermelho, e a partir daí estes testes medem
    uma função que o ecrã já não usa."""
    ecra = _ler(_POS_FINALIZAR)
    assert "mostrarQuadroDePagamentos(pagamentos, comCampoDeValor)" in ecra, (
        "O ecrã não está a chamar `mostrarQuadroDePagamentos`.")
    # E o PORTÃO do JSX tem de ser o resultado dela. Sem esta segunda
    # asserção, trocar `{haQuadroDePagamentos && (` por `{pagamentos.length >
    # 0 && (` deixava a suite verde com o defeito do dono de volta ao ecrã —
    # medido, foi exactamente o que aconteceu.
    assert "{haQuadroDePagamentos && (" in ecra, (
        "O quadro dos pagamentos deixou de ser decidido por "
        "`mostrarQuadroDePagamentos` — a regra voltou para dentro do JSX.")


def test_a_RAZAO_do_bloqueio_continua_junto_ao_botao():
    """Esconder o indicador só é seguro porque TODA a razão que desliga o
    EMITIR já tem casa encostada ao botão. Se essa frase desaparecer um dia, o
    ecrã volta ao silêncio que o `motivoBloqueio` veio acabar — e desta vez sem
    o indicador para o compensar."""
    ecra = _ler(_POS_FINALIZAR)
    # A marcação inteira, e não só as palavras: "Para emitir" aparece também
    # nos comentários deste ficheiro, e a primeira versão deste teste casava
    # com um COMENTÁRIO — ficava verde com a frase apagada do ecrã.
    assert '<span className="font-semibold">Para emitir: </span>' in ecra, (
        "A frase que explica o EMITIR desligado desapareceu do ecrã.")
    assert "{motivoBloqueio.texto}" in ecra
