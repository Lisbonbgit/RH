"""As funções de DINHEIRO do `lib/pos.js`, cada uma com um guarda que consegue
ficar vermelho.

**Porque este ficheiro existe.** O `arredondarComoOServidor` — a função que faz
o ecrã arredondar como o servidor — não tinha guarda NENHUM sobre si próprio.
O que havia era `test_arredondamento_do_ecra.py`, que o exercita de fora, por
dentro do `contasDaLinha`: apanha muito, mas apanha por acidente da malha de
casos escolhida para OUTRA coisa. Bastava alguém estreitar essa malha (foi
exactamente assim que outro guarda deste módulo se descobriu inútil — escolhia
0,30 e 8,50, que dão exacto nos dois modos) para o arredondamento do dinheiro
ficar sem ninguém a olhar.

Medido, em Node, sobre a mutação que esteve mesmo no working tree
(`Math.round` → `Math.trunc` dentro do `arredondarComoOServidor`): as duas
formas divergem em **9174 de 200 000** valores — 0,29 € → 0,28 €, 1,15 € →
1,14 €, 10,20 € → 10,19 €. Um cêntimo por baixo, no número que a operadora lê
em voz alta com o cliente à frente.

**Como é que estes guardas não podem ser enganados pela escolha dos valores.**
Nenhum caso é escrito à mão. As malhas são GERADAS (todos os cêntimos de um
intervalo, todos os múltiplos ímpares de 0,125, os produtos das percentagens
da casa, e os negativos), e cada teste traz consigo a prova de que a malha
contém mesmo a armadilha: corre-se a MESMA malha com a função MUTADA e exige-se
que ela divirja. Uma malha inofensiva deixa esse teste vermelho, com a razão
escrita.

E nunca uma CÓPIA da função: o JavaScript é extraído do ficheiro e corrido em
Node, pela técnica do `test_arredondamento_do_ecra.py` — de onde vêm, sem
segunda escrita, os utilitários de extracção e o `node` deste Mac.
"""
import json
import subprocess
from pathlib import Path

import pytest

from faturacao.precos import _tem_mais_de_2_casas_decimais

# Os utilitários de extracção e o `node` vivem no guarda irmão e importam-se de
# lá. Uma segunda cópia deles aqui era mais um sítio para divergir — e a
# extracção é precisamente o que não pode divergir, senão os dois ficheiros
# passam a medir textos diferentes.
from .test_arredondamento_do_ecra import (
    _LIB_POS,
    _corpo_da_funcao,
    _corpo_da_seta,
    _ler,
    _node,
)

_ASSINATURA_CENT = "export const arredondarComoOServidor = (valor) =>"
_ASSINATURA_CENTIMOS_POS = "const centimosPos = (valor) =>"
_ASSINATURA_NUMERO_POS = "export const numeroPos = (valor) =>"
_ASSINATURA_EUROS_POS = "const eurosPos = (valor) =>"
_ASSINATURA_COMECAR = "export const razaoDeNaoComecar = (porCobrar) =>"
_ASSINATURA_CASAS = "export const temMaisDe2CasasDecimaisPos = (valor) =>"
_ASSINATURA_OUTRA_CAIXA = "export const contaDeOutraCaixa = (venda, caixaId) =>"


def _sem_export(codigo: str) -> str:
    return codigo.replace("export ", "", 1)


def _correr(tmp_path: Path, nome: str, codigo: str):
    """Corre um guião em Node e devolve o JSON que ele escreveu."""
    guiao = tmp_path / ("%s.js" % nome)
    guiao.write_text(codigo, encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


# --- 1. O arredondamento: `arredondarComoOServidor` ----------------------------


def _cent(mutacao=None) -> str:
    """O corpo da função, tal como está no ficheiro — ou com uma mutação
    aplicada por substituição de texto, para a prova por mutação do fim de
    cada teste. A mutação é aplicada ao texto LIDO, e não a uma cópia escrita
    aqui: se a linha mutada já não existir, o `assert` rebenta e diz que a
    função mudou de forma."""
    corpo = _sem_export(_corpo_da_funcao(_ler(_LIB_POS), _ASSINATURA_CENT, _LIB_POS))
    if mutacao is None:
        return corpo
    antes, depois = mutacao
    assert antes in corpo, (
        "A mutação %r já não se aplica ao `arredondarComoOServidor` — a função "
        "mudou de forma e esta prova deixou de provar o que diz. Vai lê-la e "
        "escolhe a mutação que hoje corresponde ao mesmo erro." % antes
    )
    return corpo.replace(antes, depois)


# As três mutações, cada uma o erro que ela representa.
_TRUNCA = (
    "Math.round(Number(Math.abs(x).toFixed(2)) * 100)",
    "Math.trunc(Number(Math.abs(x).toFixed(2)) * 100)",
)
_SEM_DESEMPATE = (
    "const escolhido = empate && centimos % 2 === 1 ? centimos - 1 : centimos;",
    "const escolhido = centimos;",
)
_SEM_SINAL = (
    "return (x < 0 ? -escolhido : escolhido) / 100;",
    "return escolhido / 100;",
)


def _valores_do_arredondamento():
    """A malha. Gerada, nunca escrita à mão, e com as quatro famílias onde o
    cêntimo se decide:

    1. **todos os cêntimos até 1000 €** — é aqui que vive a divergência do
       `Math.trunc` (o `Number(x.toFixed(2)) * 100` cai por baixo do inteiro
       em 0,29 → 28,999999999999996);
    2. **todos os múltiplos ímpares de 0,125** — os ÚNICOS valores que o
       binário representa exactamente em cima do meio cêntimo, e por isso os
       únicos onde o `toFixed` sobe e o `round` do Python vai para o par;
    3. **os descontos da casa sobre os preços da casa** (`preço × pct / 100`),
       que é a conta de onde os valores VÊM no ecrã;
    4. **os negativos de tudo isso** — um desconto em euros maior do que o
       bruto dá um total negativo, e o ramo do sinal não tinha guarda nenhum.
    """
    valores = [c / 100 for c in range(1, 100001)]
    valores += [n * 0.125 for n in range(1, 4001, 2)]
    for centimos_preco in range(1, 4001):
        preco = centimos_preco / 100
        for pct in (5, 10, 12.5, 15, 20, 25, 33, 50):
            valores.append(preco * pct / 100)
    valores += [-v for v in list(valores)]
    valores += [0.0, -0.0]
    return valores


def _no_ecra(valores, tmp_path, mutacao=None):
    return _correr(tmp_path, "arredondar", "\n".join([
        _cent(mutacao),
        "const valores = %s;" % json.dumps(valores),
        "process.stdout.write(JSON.stringify("
        "valores.map((v) => arredondarComoOServidor(v))));",
    ]))


def test_o_arredondamento_do_ecra_e_o_round_do_python(tmp_path):
    """**A regra, sem intermediário nenhum**: para todo o valor, o
    `arredondarComoOServidor` do ecrã dá o mesmo que o `round(x, 2)` do Python,
    que é o arredondamento com que o servidor grava a linha da fatura.

    Os `contasDaLinha`, `PosDialogoProduto` e `PosReparticao` são todos
    construídos por cima desta função. Um cêntimo errado aqui é um cêntimo
    errado em todos eles ao mesmo tempo."""
    valores = _valores_do_arredondamento()
    no_ecra = _no_ecra(valores, tmp_path)

    divergentes = [
        (v, saida, round(v, 2))
        for v, saida in zip(valores, no_ecra)
        if saida != round(v, 2)
    ]
    assert divergentes == [], (
        "%d de %d valores arredondam de maneira diferente no ecrã e no "
        "servidor. Os primeiros (valor, ecrã, servidor): %s"
        % (len(divergentes), len(valores), divergentes[:5])
    )


@pytest.mark.parametrize("nome,mutacao", [
    ("Math.round -> Math.trunc", _TRUNCA),
    ("sem o desempate ao par", _SEM_DESEMPATE),
    ("perde o sinal dos negativos", _SEM_SINAL),
])
def test_a_malha_apanha_mesmo_cada_uma_das_tres_mutacoes(nome, mutacao, tmp_path):
    """**A prova de que a malha não é inofensiva**, feita mutação a mutação.

    É este teste que impede o de cima de ser enganado pela escolha dos valores:
    se alguém trocar a malha por preços redondos (0,30 e 8,50 dão exacto nos
    três modos — foi assim que outro guarda deste módulo se descobriu inútil),
    é aqui que aparece a linha vermelha a explicar porquê."""
    valores = _valores_do_arredondamento()
    mutado = _no_ecra(valores, tmp_path, mutacao=mutacao)

    divergentes = [
        v for v, saida in zip(valores, mutado) if saida != round(v, 2)
    ]
    assert len(divergentes) > 0, (
        "Com a mutação «%s», NENHUM dos %d valores da malha divergiu do "
        "servidor. A malha deixou de conter a armadilha e o guarda de cima "
        "está a verificar o vazio." % (nome, len(valores))
    )


def test_os_numeros_medidos_da_mutacao_que_esteve_no_working_tree(tmp_path):
    """Os três casos que se mediram, escritos por extenso: com o `Math.trunc`,
    0,29 € viravam 0,28 €, 1,15 € viravam 1,14 € e 10,20 € viravam 10,19 €.

    Não substitui a malha — nomeia o estrago, para quem ler o vermelho saber
    o que estava em jogo sem ter de reconstruir a medição."""
    casos = [0.29, 1.15, 10.20]
    assert _no_ecra(casos, tmp_path) == [0.29, 1.15, 10.20]
    assert _no_ecra(casos, tmp_path, mutacao=_TRUNCA) == [0.28, 1.14, 10.19], (
        "A mutação medida deixou de dar os números medidos — se a função mudou "
        "de forma, esta memória tem de ir atrás dela."
    )


# --- 2. A fronteira dos cêntimos: `centimosPos` e a frase que a usa ------------


def _guiao_da_frase(porCobrar, mutacao=None):
    lib = _ler(_LIB_POS)
    centimos = _corpo_da_seta(lib, _ASSINATURA_CENTIMOS_POS, _LIB_POS)
    if mutacao is not None:
        antes, depois = mutacao
        assert antes in centimos, (
            "A mutação %r já não se aplica ao `centimosPos`." % antes)
        centimos = centimos.replace(antes, depois)
    return "\n".join([
        centimos,
        # `numeroPos` vem com ele: `eurosPos` passou a ser uma casca à volta
        # dela, e é lá que está a defesa contra o `undefined` pintado de zero.
        _sem_export(_corpo_da_funcao(lib, _ASSINATURA_NUMERO_POS, _LIB_POS)),
        _corpo_da_seta(lib, _ASSINATURA_EUROS_POS, _LIB_POS),
        _sem_export(_corpo_da_funcao(lib, _ASSINATURA_COMECAR, _LIB_POS)),
        "const casos = %s;" % json.dumps(porCobrar),
        "process.stdout.write(JSON.stringify("
        "casos.map((c) => razaoDeNaoComecar(c))));",
    ])


_TRUNCA_CENTIMOS = (
    "Math.round((Number(valor) || 0) * 100)",
    "Math.trunc((Number(valor) || 0) * 100)",
)


def _partes(totais):
    return [{"id": "p%d" % i, "estado": "aberta", "totais": {"total": t}}
            for i, t in enumerate(totais)]


def _casos_da_frase():
    """Grupos de partes por cobrar cujo total, em cêntimos, é uma armadilha
    para a passagem de euros a cêntimos: todos os valores até 20 € cujo
    `× 100` NÃO dá um inteiro exacto em vírgula flutuante binária.

    Não são escolhidos à mão — são procurados: é a diferença entre um guarda
    que apanha o defeito e um que calha ter apanhado."""
    return [_partes([c / 100]) for c in range(1, 2001)] + [
        _partes([c / 100, (c + 7) / 100, (c + 13) / 100])
        for c in range(1, 501)
    ]


def test_a_frase_que_manda_acabar_a_conta_diz_o_euro_certo(tmp_path):
    """A frase que a operadora lê quando toca num produto com partes por
    cobrar traz o que falta receber. Esse número passa por `centimosPos` — a
    fronteira entre a vírgula flutuante e os inteiros — e é o único sítio deste
    ficheiro onde o dinheiro de VÁRIAS contas se soma.

    Compara-se com a soma feita em cêntimos INTEIROS do lado do Python: é a
    regra 1 do módulo (o dinheiro soma-se em cêntimos, nunca em floats) posta
    a correr em vez de afirmada."""
    casos = _casos_da_frase()
    frases = _correr(tmp_path, "frase", _guiao_da_frase(casos))

    errados = []
    for grupo, frase in zip(casos, frases):
        centimos = sum(int(round(p["totais"]["total"] * 100)) for p in grupo)
        esperado = "%s,%02d" % ("{:,}".format(centimos // 100).replace(",", " "),
                                centimos % 100)
        if esperado not in (frase or ""):
            errados.append((centimos, esperado, frase))
    assert errados == [], (
        "%d frases escrevem um euro diferente do que falta receber. As "
        "primeiras (cêntimos, esperado, frase): %s"
        % (len(errados), [(c, e, f[:70]) for c, e, f in errados[:3]])
    )


def test_a_malha_da_frase_apanha_a_perda_do_centimo(tmp_path):
    """A prova por mutação: com `Math.round` → `Math.trunc` no `centimosPos`,
    estas frases passam a prometer um cêntimo a menos. Sem isto, a malha podia
    ser toda de valores redondos e o guarda de cima não guardava nada."""
    casos = _casos_da_frase()
    frases = _correr(tmp_path, "frase_mutada",
                     _guiao_da_frase(casos, mutacao=_TRUNCA_CENTIMOS))

    errados = 0
    for grupo, frase in zip(casos, frases):
        centimos = sum(int(round(p["totais"]["total"] * 100)) for p in grupo)
        esperado = "%s,%02d" % ("{:,}".format(centimos // 100).replace(",", " "),
                                centimos % 100)
        if esperado not in (frase or ""):
            errados += 1
    assert errados > 0, (
        "Com o `centimosPos` a truncar, NENHUMA das %d frases mudou de valor — "
        "a malha deixou de conter valores cujo `× 100` cai por baixo do "
        "inteiro, e o guarda de cima está a verificar o vazio." % len(casos)
    )


# --- 3. O crivo das duas casas decimais ----------------------------------------


def _casos_das_casas():
    """Os valores que o campo de dinheiro do POS deixa escrever, e os que ele
    tem de recusar: inteiros, uma casa, duas casas, três casas e as
    representações que o JavaScript escreve de outra maneira."""
    valores = []
    for c in range(0, 1001):
        valores += [c, c / 10, c / 100, c / 1000]
    valores += [0.005, 2.675, 8.999, 1e21, 1e-7, 0.1 + 0.2]
    return valores


def test_o_crivo_do_ecra_recusa_exactamente_o_que_o_servidor_recusa(tmp_path):
    """`temMaisDe2CasasDecimaisPos` existe para o ecrã dizer NÃO antes de o
    servidor dizer NÃO — e para isso tem de dizer não às MESMAS coisas. Um
    crivo mais apertado do que o do servidor recusa dinheiro legítimo com o
    cliente à frente; um mais largo deixa entrar um valor que o servidor
    devolve em 422 depois do toque.

    O do servidor é `precos._tem_mais_de_2_casas_decimais`, importado — nunca
    reescrito aqui."""
    valores = _casos_das_casas()
    lib = _ler(_LIB_POS)
    no_ecra = _correr(tmp_path, "casas", "\n".join([
        _sem_export(_corpo_da_funcao(lib, _ASSINATURA_CASAS, _LIB_POS)),
        "const valores = %s;" % json.dumps(valores),
        "process.stdout.write(JSON.stringify("
        "valores.map((v) => temMaisDe2CasasDecimaisPos(v))));",
    ]))

    divergentes = [
        (v, ecra, _tem_mais_de_2_casas_decimais(v))
        for v, ecra in zip(valores, no_ecra)
        if ecra != _tem_mais_de_2_casas_decimais(v)
    ]
    # `1e21` e `1e-7` saem em notação exponencial nos DOIS lados e os dois
    # respondem `False`; se um dia deixarem de concordar, aparece aqui.
    assert divergentes == [], (
        "%d valores são julgados de maneira diferente pelo ecrã e pelo "
        "servidor. Os primeiros (valor, ecrã, servidor): %s"
        % (len(divergentes), divergentes[:5])
    )


def test_a_malha_do_crivo_apanha_um_crivo_deslocado(tmp_path):
    """A prova por mutação: `casas.length > 2` → `>= 2` (recusar dois
    decimais) e `> 3` (deixar passar três). A malha tem de apanhar os dois —
    senão não contém nem valores de duas casas nem de três."""
    lib = _ler(_LIB_POS)
    corpo = _sem_export(_corpo_da_funcao(lib, _ASSINATURA_CASAS, _LIB_POS))
    assert "return casas.length > 2;" in corpo, (
        "O crivo do ecrã mudou de forma e estas mutações deixaram de se "
        "aplicar — vai lê-lo e escolhe as que hoje representam o mesmo erro.")
    valores = _casos_das_casas()

    for nome, mutado in (
        ("recusa duas casas", corpo.replace(
            "return casas.length > 2;", "return casas.length >= 2;")),
        ("deixa passar três", corpo.replace(
            "return casas.length > 2;", "return casas.length > 3;")),
    ):
        no_ecra = _correr(tmp_path, "casas_mutado", "\n".join([
            mutado,
            "const valores = %s;" % json.dumps(valores),
            "process.stdout.write(JSON.stringify("
            "valores.map((v) => temMaisDe2CasasDecimaisPos(v))));",
        ]))
        divergentes = [
            v for v, ecra in zip(valores, no_ecra)
            if ecra != _tem_mais_de_2_casas_decimais(v)
        ]
        assert len(divergentes) > 0, (
            "Com o crivo a «%s», nenhum dos %d valores divergiu do servidor — "
            "a malha não contém valores dessa forma." % (nome, len(valores))
        )


# --- 4. A conta que veio de outra caixa ----------------------------------------


def test_a_nota_da_outra_caixa_so_aparece_quando_e_mesmo_outra(tmp_path):
    """`contaDeOutraCaixa` decide se o painel escreve «esta conta ficou aberta
    noutra caixa deste PC». É a metade humana da correcção da raiz: a conta
    passou a estar à frente da operadora venha da caixa que vier, e ela precisa
    de ler de ONDE.

    Falso quando falta um dos dois ids — não se inventa uma diferença a partir
    do que não se sabe —, e falso na caixa própria, senão uma loja com uma
    caixa só passava a ter a nota em todas as contas."""
    lib = _ler(_LIB_POS)
    casos = [
        {"venda": {"caixa_id": "caixa-1"}, "caixa": "caixa-2", "esperado": True},
        {"venda": {"caixa_id": "caixa-1"}, "caixa": "caixa-1", "esperado": False},
        {"venda": {"caixa_id": None}, "caixa": "caixa-2", "esperado": False},
        {"venda": {"caixa_id": "caixa-1"}, "caixa": None, "esperado": False},
        {"venda": None, "caixa": "caixa-2", "esperado": False},
    ]
    saida = _correr(tmp_path, "outra_caixa", "\n".join([
        _sem_export(_corpo_da_seta(lib, _ASSINATURA_OUTRA_CAIXA, _LIB_POS)),
        "const casos = %s;" % json.dumps(casos),
        "process.stdout.write(JSON.stringify("
        "casos.map((c) => contaDeOutraCaixa(c.venda, c.caixa))));",
    ]))
    assert saida == [c["esperado"] for c in casos]
