"""Guarda de regressão: o cêntimo que o ECRÃ promete é o cêntimo que a
FATURA cobra.

Porque este ficheiro existe. O POS mostra, antes de dividir, quanto vai pagar
cada pessoa — é o número que a operadora lê em voz alta com o cliente à
frente. Essa previsão é feita em JavaScript (`lib/pos.js::contasDaLinha` e
`PosReparticao::fatiasDaLinha`) e a repartição verdadeira é feita em Python
(`venda.py::_partes_de_uma_linha`), e as duas só valem alguma coisa enquanto
disserem o mesmo.

O defeito que o motivou: o `cent()` do ecrã era `Math.round(valor * 100) /
100`. Duas coisas erradas de uma vez — multiplicar por 100 empurra o valor
para cima do meio cêntimo (7,15 × 10 ÷ 100 é 0,714999…, mas × 100 dá 71,5
redondo) e o `Math.round` arredonda o meio PARA CIMA, enquanto o `round(x, 2)`
do Python olha para o valor exacto do double e arredonda PARA O PAR. Medido no
browser: um Açaí Regular de 7,15 € com −10 % na linha, dividido por dois,
mostrava as pastilhas **3,22 / 3,21** — soma 6,43 — por baixo de um total de
**6,44 €** escrito ao lado, e o servidor devolvia **3,22 / 3,22**. A segunda
pessoa pagava um cêntimo a mais do que o ecrã lhe tinha prometido.

A técnica é a do `test_resumo_do_ecra.py`: não há infra-estrutura de testes no
frontend, mas estas funções são puras — extraem-se do ficheiro pelo texto,
correm-se em Node, e o que se compara é a saída delas com a do servidor. Nunca
uma CÓPIA delas escrita aqui: uma cópia deixaria este guarda verde com o ecrã
errado, que é exactamente a forma de falhar que ele existe para apanhar.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from faturacao.reparticao import repartir_centimos
from faturacao.venda import _bruto_da_linha, _centimos, _desconto_da_linha, _linha_vendus

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_LIB_POS = _RAIZ / "frontend" / "src" / "lib" / "pos.js"
_REPARTICAO = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosReparticao.js"

_ASSINATURA_CENT = "export const arredondarComoOServidor = (valor) =>"
_ASSINATURA_CONTAS = "export const contasDaLinha = (linha) =>"
_ASSINATURA_REPARTIR = "export const repartirCentimos = (totalCentimos, partes) =>"
_ASSINATURA_CENTIMOS = "const centimos = (valor) =>"
_ASSINATURA_FATIAS = "const fatiasDaLinha = (linha, partes) =>"

# O `cent` de antes da correcção. Vive aqui, e só aqui, para a prova por
# mutação do fim do ficheiro: é o ÚNICO sítio do repositório onde esta linha
# ainda existe.
_CENT_ANTIGO = "const cent = (valor) => Math.round(valor * 100) / 100;"

# O arredondamento a DUAS CASAS escrito à mão — `Math.round(x * 100) / 100`.
# Não confundir com a passagem a cêntimos INTEIROS (`Math.round(euros * 100)`,
# sem a divisão), que é a fronteira certa entre a vírgula flutuante e os
# inteiros e vive de propósito no PosVenda e no PosReparticao.
_RE_ARREDONDA_A_DUAS_CASAS = re.compile(r"Math\.round\([^;\n]*\*\s*100\s*\)\s*/\s*100")


def _sem_comentarios(codigo: str) -> str:
    """O código sem comentários. Os comentários deste ecrã citam a linha do
    defeito, e um guarda que a procurasse no texto todo ficava vermelho por
    causa da explicação em vez do código."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", codigo, flags=re.S))


def _ler(ficheiro: Path) -> str:
    if not ficheiro.exists():
        pytest.fail(
            "Não encontrei %s. Se o ecrã mudou de sítio, este guarda tem de ir "
            "atrás dele — não se apaga." % ficheiro
        )
    return ficheiro.read_text(encoding="utf-8")


def _corpo_da_funcao(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O código de uma função, do início da assinatura até à chaveta que a
    fecha. Conta as chavetas: os `${...}` dos template literals são pares e
    não a atrapalham. Uma chaveta desemparelhada num comentário lá dentro faz
    isto falhar — e falhar alto é o que se quer, porque a alternativa é o
    guarda passar a medir outra coisa em silêncio."""
    if assinatura not in texto:
        pytest.fail(
            "Não encontrei `%s` em %s. Se a função foi renomeada ou movida, a "
            "regra que ela cumpre continua a ter de ser guardada."
            % (assinatura, ficheiro.name)
        )
    inicio = texto.index(assinatura)
    # A chaveta procura-se a partir do FIM da assinatura, e não do princípio:
    # uma arrow function que desestrutura os parâmetros
    # (`({ venda, partes }) =>`) tem uma chaveta DENTRO da assinatura, e
    # começar por essa devolvia só a lista de parâmetros — o guião gerado
    # rebentava com um `SyntaxError` em vez de correr a decisão. Nenhuma das
    # funções que ESTE ficheiro extrai desestrutura, por isso a diferença não
    # se via aqui; via-se em quem o importa (`test_um_posto_uma_conta.py`, que
    # corre o `razaoDaGrelhaMorta`). O gémeo desta função em
    # `test_partes_por_cobrar_no_ecra.py` já tinha esta correcção — e é a
    # existência do gémeo que a fez faltar aqui.
    i = texto.index("{", inicio + len(assinatura))
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
    """O mesmo, para uma arrow function de uma expressão só: até ao `;`."""
    if assinatura not in texto:
        pytest.fail("Não encontrei `%s` em %s." % (assinatura, ficheiro.name))
    inicio = texto.index(assinatura)
    fim = texto.index(";", inicio)
    return texto[inicio:fim + 1]


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    # O node deste Mac vive fora do PATH (ver a memória do projecto). Não é uma
    # configuração que se possa exigir de quem corre a suite, por isso
    # procura-se; se não houver, o teste diz porque não correu em vez de ficar
    # verde a fingir. O guarda de texto, no fim do ficheiro, esse corre sempre.
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip(
        "Sem `node` para executar o JavaScript do ecrã "
        "(nem no PATH nem em ~/.local/node/bin)."
    )


def _codigo_do_ecra(cent: str = None) -> str:
    """O JavaScript do ecrã, lido dos ficheiros e pronto a correr solto.

    `cent` permite trocar SÓ o arredondamento — é o que a prova por mutação
    usa para voltar a pôr lá o de antes e ver este guarda ficar vermelho."""
    lib = _ler(_LIB_POS)
    reparticao = _ler(_REPARTICAO)
    return "\n".join([
        cent if cent is not None else "%s\nconst cent = arredondarComoOServidor;"
        % _corpo_da_funcao(lib, _ASSINATURA_CENT, _LIB_POS).replace("export ", "", 1),
        # `export` fora: isto corre como um guião solto, não como módulo.
        _corpo_da_funcao(lib, _ASSINATURA_CONTAS, _LIB_POS).replace("export ", "", 1),
        _corpo_da_funcao(lib, _ASSINATURA_REPARTIR, _LIB_POS).replace("export ", "", 1),
        _corpo_da_seta(reparticao, _ASSINATURA_CENTIMOS, _REPARTICAO),
        _corpo_da_funcao(reparticao, _ASSINATURA_FATIAS, _REPARTICAO),
    ])


def _no_ecra(casos, tmp_path: Path, cent: str = None):
    """Corre em Node, para cada caso, a leitura da linha (`contasDaLinha`) e a
    previsão da divisão por N pessoas (`fatiasDaLinha`) — o mesmo código que
    está nos ficheiros do POS."""
    guiao = tmp_path / "arredondamento.js"
    guiao.write_text(
        "\n".join([
            _codigo_do_ecra(cent),
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map(({ linha, pessoas }) => {",
            "  const contas = contasDaLinha(linha);",
            "  const fatias = fatiasDaLinha(linha, pessoas)"
            "    .map((f) => (f ? f.totalCentimos : null));",
            "  return { contas, fatias };",
            "})));",
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


def _no_servidor(linha, pessoas):
    """A MESMA linha lida pelo servidor, e repartida como
    `venda.py::_partes_de_uma_linha` a reparte: o bruto por N e o desconto por
    N, em cêntimos, e a fatia de cada pessoa é a diferença entre os dois."""
    li = _linha_vendus(linha)
    bruto = _bruto_da_linha(li)
    desconto = _desconto_da_linha(li)
    bruto_c = _centimos(bruto)
    if bruto_c == 0:
        fatias = [0 if i == 0 else None for i in range(pessoas)]
    else:
        brutos = repartir_centimos(bruto_c, pessoas)
        descontos = repartir_centimos(_centimos(desconto), pessoas)
        fatias = [
            None if b == 0 else b - d for b, d in zip(brutos, descontos)
        ]
    return {
        "unitario": li["gross_price"],
        "bruto": bruto,
        "desconto": desconto,
        "total": round(bruto - desconto, 2),
        "fatias": fatias,
    }


def _linha(preco, quantidade=1, desconto_pct=None, desconto_eur=None, opcoes=None):
    return {
        "id": "li-1",
        "produto_nome": "Açaí Regular",
        "produto_preco": preco,
        "produto_tax_id": "INT",
        "quantidade": quantidade,
        "opcoes": opcoes or [],
        "preco_override": None,
        "tax_override": None,
        "desconto_pct": desconto_pct,
        "desconto_eur": desconto_eur,
    }


# As percentagens de desconto que o balcão usa, e as que caem em cima do meio
# cêntimo com mais frequência (12,5 % é a pior de todas: sobre um preço em
# cêntimos redondos, o desconto acaba em 0,125 exacto muitas vezes).
_PERCENTAGENS = (5, 10, 12.5, 15, 20, 25, 33, 50)


def _casos():
    """A malha de casos. Não é uma amostra bonita: são preços de açaí ao
    cêntimo, cruzados com as percentagens da casa, as quantidades do balcão e
    as divisões que se fazem à mesa — é lá que o meio cêntimo mora."""
    casos = []
    # O caso EXACTO do browser, primeiro e por escrito: 7,15 € com -10 %,
    # dividido por dois. O ecrã prometia 3,22 / 3,21, o servidor dava 3,22 / 3,22.
    casos.append({"linha": _linha(7.15, 1, desconto_pct=10), "pessoas": 2})
    for centimos_preco in range(1, 1601):
        preco = centimos_preco / 100
        for pct in _PERCENTAGENS:
            casos.append({"linha": _linha(preco, 1, desconto_pct=pct), "pessoas": 2})
    for centimos_preco in range(1, 401):
        preco = centimos_preco / 100
        for pct in _PERCENTAGENS:
            for quantidade in (2, 3):
                for pessoas in (2, 3, 4):
                    casos.append({
                        "linha": _linha(preco, quantidade, desconto_pct=pct),
                        "pessoas": pessoas,
                    })
    # Com opções pagas somadas ao unitário (é onde o `cent` do unitário entra),
    # e com desconto em EUROS, que o servidor trata por outro ramo.
    for centimos_preco in range(1, 401):
        preco = centimos_preco / 100
        casos.append({
            "linha": _linha(preco, 2, desconto_pct=12.5,
                            opcoes=[{"nome": "Nutella", "preco": 0.75},
                                    {"nome": "Morango", "preco": 0.05}]),
            "pessoas": 3,
        })
        casos.append({
            "linha": _linha(preco, 1, desconto_eur=min(0.13, preco)),
            "pessoas": 2,
        })
    # Uma linha que JÁ É uma parte (quantidade com cinco casas): é assim que
    # ela aparece no painel de quem cobra a segunda divisão.
    for quantidade in (0.33370, 0.5, 1.66667):
        casos.append({"linha": _linha(8.99, quantidade, desconto_pct=10), "pessoas": 2})
    # Um artigo oferecido: não vale nada e vai inteiro para a primeira pessoa.
    casos.append({"linha": _linha(0.0, 1), "pessoas": 3})
    return casos


def test_a_leitura_da_linha_no_ecra_e_a_do_servidor(tmp_path):
    """Unitário, bruto, desconto e total: os quatro números que o painel da
    conta escreve por baixo do artigo têm de ser os mesmos que o servidor
    calcula com `precos.linha_de_venda`."""
    casos = _casos()
    no_ecra = _no_ecra(casos, tmp_path)

    divergentes = []
    for caso, saida in zip(casos, no_ecra):
        esperado = _no_servidor(caso["linha"], caso["pessoas"])
        for campo in ("unitario", "bruto", "desconto", "total"):
            if saida["contas"][campo] != esperado[campo]:
                divergentes.append(
                    "%s de %s = %s no ecrã, %s no servidor"
                    % (campo, caso["linha"], saida["contas"][campo], esperado[campo])
                )
    assert divergentes == [], (
        "%d leituras da linha divergem entre o ecrã e o servidor. As primeiras: %s"
        % (len(divergentes), divergentes[:5])
    )


def test_a_previsao_da_divisao_e_a_reparticao_do_servidor(tmp_path):
    """O número que a operadora lê na pastilha de cada pessoa, antes de
    carregar em DIVIDIR, é o que essa pessoa vai mesmo pagar."""
    casos = _casos()
    no_ecra = _no_ecra(casos, tmp_path)

    divergentes = []
    for caso, saida in zip(casos, no_ecra):
        esperado = _no_servidor(caso["linha"], caso["pessoas"])
        if saida["fatias"] != esperado["fatias"]:
            divergentes.append(
                "%s por %d: %s no ecrã, %s no servidor"
                % (caso["linha"], caso["pessoas"], saida["fatias"], esperado["fatias"])
            )
    assert divergentes == [], (
        "%d divisões divergem entre a previsão do ecrã e a repartição do "
        "servidor — é o cêntimo que a fatura desmente à frente do cliente. As "
        "primeiras: %s" % (len(divergentes), divergentes[:5])
    )


def test_o_caso_do_browser_ao_centimo(tmp_path):
    """O defeito, escrito com os números que se viram no ecrã: 7,15 € com
    −10 %, dividido por duas pessoas. 3,22 / 3,22, nunca 3,22 / 3,21 — e a
    soma das duas é o total que está escrito ao lado."""
    caso = {"linha": _linha(7.15, 1, desconto_pct=10), "pessoas": 2}
    saida = _no_ecra([caso], tmp_path)[0]

    assert saida["contas"]["desconto"] == 0.71, (
        "10 %% de 7,15 € são 0,71 € (o `round` do Python arredonda 0,714999… "
        "para baixo), não %s." % saida["contas"]["desconto"]
    )
    assert saida["contas"]["total"] == 6.44
    assert saida["fatias"] == [322, 322]
    assert sum(saida["fatias"]) == _centimos(saida["contas"]["total"]), (
        "As pastilhas somam %s cêntimos e o total escrito ao lado é %s — foi "
        "exactamente esta diferença que se viu no browser."
        % (sum(saida["fatias"]), _centimos(saida["contas"]["total"]))
    )


def test_o_guarda_apanha_o_arredondamento_de_antes(tmp_path):
    """Prova por mutação, feita aqui dentro e não à mão: com o `cent` de antes
    (`Math.round(valor * 100) / 100`) estes mesmos casos divergem do servidor.
    Se este teste falhar, é porque os dois de cima deixaram de medir seja o que
    for — passavam a verde com o ecrã errado."""
    casos = _casos()
    no_ecra = _no_ecra(casos, tmp_path, cent=_CENT_ANTIGO)

    divergentes = [
        caso for caso, saida in zip(casos, no_ecra)
        if saida["fatias"] != _no_servidor(caso["linha"], caso["pessoas"])["fatias"]
    ]
    assert len(divergentes) > 0, (
        "Com o arredondamento antigo, nenhum destes casos divergiu do servidor "
        "— a malha de casos deixou de conter meios-cêntimos e os guardas de "
        "cima ficaram a verificar o vazio."
    )


def test_o_ecra_nao_volta_a_arredondar_como_o_javascript():
    """Sem `node`, é este o guarda que resta — e é o que impede a linha de
    voltar por distracção, num `git revert` ou numa "simplificação". O
    `Math.round(v * 100) / 100` arredonda o meio para CIMA e passa pelo
    produto por 100; o `round(x, 2)` do Python não faz nem uma coisa nem
    outra."""
    lib = _ler(_LIB_POS)
    corpo = _corpo_da_funcao(lib, _ASSINATURA_CENT, _LIB_POS)
    assert "Math.round(valor * 100)" not in corpo, (
        "O `cent` do POS voltou a ser `Math.round(valor * 100) / 100`. Esse "
        "arredondamento não é o do servidor: num desconto em percentagem que "
        "caia a meio do cêntimo, o ecrã promete um valor e a Fatura "
        "Simplificada cobra outro."
    )
    assert "toFixed(2)" in corpo, (
        "O `cent` do POS deixou de decidir pelo valor exacto do double "
        "(`toFixed(2)`) — se mudou de técnica, este guarda tem de ir atrás "
        "dela, mas a igualdade com o `round(x, 2)` do Python não se negoceia."
    )


def test_ha_UM_arredondamento_no_pos_e_todos_os_ecras_o_usam():
    """A outra metade da mesma regra. O `PosDialogoProduto` tinha a sua CÓPIA
    desta função — com o mesmo defeito e um comentário a dá-lo por inevitável
    — e por isso escrevia "TOTAL DA LINHA € 6,43" para o artigo de 7,15 € com
    −10 % que o servidor grava a 6,44 €. O que é diferente em cada ecrã é a
    ENTRADA (o diálogo trabalha sobre campos de texto a meio de serem
    escritos); a ORDEM dos passos e o ARREDONDAMENTO são os mesmos nos dois —
    ver `test_o_dialogo_faz_a_conta_pela_MESMA_ordem_do_contasDaLinha`, que o
    corre em vez de o afirmar."""
    ecras = _RAIZ / "frontend" / "src" / "pages" / "pos"
    # Sem os comentários: eles descrevem o defeito COM A LINHA DELE, e um
    # guarda que procurasse no texto todo ficava vermelho por causa da
    # explicação em vez do código.
    #
    # O que se procura é o arredondamento a DUAS CASAS (`… * 100) / 100`), e
    # não a passagem a cêntimos inteiros (`Math.round(euros * 100)`): essa é
    # a fronteira certa entre a vírgula flutuante e os inteiros, e está em dois
    # ecrãs de propósito.
    copias = [
        ficheiro.name
        for ficheiro in sorted(ecras.glob("*.js"))
        if _RE_ARREDONDA_A_DUAS_CASAS.search(_sem_comentarios(_ler(ficheiro)))
    ]
    assert copias == [], (
        "Estes ecrãs do POS voltaram a ter o seu próprio arredondamento a duas "
        "casas: %s. Há um só, e é o `arredondarComoOServidor` do lib/pos.js — "
        "importa-se, não se copia." % ", ".join(copias)
    )
    dialogo = _ler(ecras / "PosDialogoProduto.js")
    assert "arredondarComoOServidor" in dialogo, (
        "O diálogo do produto deixou de importar o arredondamento do lib/pos.js "
        "— o total que ele mostra antes de Gravar volta a poder divergir um "
        "cêntimo do que o servidor grava."
    )


# --- A ORDEM dos passos, que não é "diferente de propósito" -------------------
#
# Aqui esteve escrito, em três sítios ao mesmo tempo (neste ficheiro, no
# `lib/pos.js` e no `PosDialogoProduto.js`), que "a ORDEM das contas é
# diferente em cada ecrã de propósito". **Não é.** Os passos do diálogo são,
# um a um, os do `contasDaLinha` e os do `precos.linha_de_venda`: as opções
# somam ao unitário, o unitário multiplica pela quantidade, o desconto entra
# por último, com arredondamento a cada passo. O que é diferente é a ENTRADA —
# o diálogo lê campos de texto a meio de serem escritos (`'' `, `'7,1'`), o
# `contasDaLinha` lê uma linha que o servidor já aceitou.
#
# A distinção não é uma questão de redacção. Foi um comentário exactamente
# assim, sobre o ARREDONDAMENTO, que deu por inevitável a divergência de um
# cêntimo que este ficheiro veio corrigir: uma frase que dá licença é uma
# frase que a próxima alteração usa. Por isso a ordem deixou de ser afirmada
# em prosa e passou a ser CORRIDA.

_DIALOGO = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosDialogoProduto.js"

# Os cinco passos do diálogo, pela ordem em que ele os faz. Lidos do ficheiro,
# nunca copiados para aqui — uma cópia ficava verde no dia em que o ecrã
# mudasse, que é o dia que interessa.
_PASSOS_DO_DIALOGO = (
    "extraOpcoes", "precoUnitario", "brutoLinha", "descontoLinha", "totalLinha",
)


def _passo(texto: str, nome: str) -> str:
    """A linha `const <nome> = …;` do diálogo, tal como lá está."""
    marca = "\n  const %s = " % nome
    if marca not in texto:
        pytest.fail(
            "Não encontrei o passo `%s` em %s. Se a conta da linha do diálogo "
            "mudou de forma, este guarda tem de ir atrás dela — a igualdade "
            "com o `contasDaLinha` não se negoceia." % (nome, _DIALOGO.name)
        )
    inicio = texto.index(marca) + 1
    return texto[inicio:texto.index("\n", inicio)]


def _os_dois_calculos(casos, tmp_path: Path):
    """Corre, lado a lado e em Node, a conta da linha dos DOIS ecrãs: a do
    `lib/pos.js` (sobre uma linha gravada) e a do `PosDialogoProduto` (sobre os
    campos do formulário), cada uma tal como está escrita no seu ficheiro."""
    dialogo = _ler(_DIALOGO)
    guiao = tmp_path / "ordem.js"
    guiao.write_text(
        "\n".join([
            _codigo_do_ecra(),
            "function noDialogo(precoNumero, opcoes, qtdNumero, pctNumero, eurNumero) {",
            "\n".join(_passo(dialogo, nome) for nome in _PASSOS_DO_DIALOGO),
            "  return { unitario: precoUnitario, bruto: brutoLinha,"
            "           desconto: descontoLinha, total: totalLinha };",
            "}",
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map((c) => ({",
            "  dialogo: noDialogo(c.preco, c.opcoes, c.quantidade, c.pct, c.eur),",
            "  linha: contasDaLinha({",
            "    produto_preco: c.preco, preco_override: null, opcoes: c.opcoes,",
            "    quantidade: c.quantidade, desconto_pct: c.pct, desconto_eur: c.eur,",
            "  }),",
            "}))));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript dos dois ecrãs não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


def _casos_da_ordem():
    """Onde uma ordem trocada se nota: com opções (somar o extra DEPOIS de
    multiplicar pela quantidade dá outro número), com quantidade > 1, e com um
    desconto em percentagem (aplicá-lo antes da quantidade dá outro número
    ainda). Sem nada disso, todas as ordens dão o mesmo e o guarda não guarda
    nada."""
    casos = []
    for preco in (7.15, 8.99, 1.00, 0.15, 12.34):
        for quantidade in (1, 2, 3, 7):
            for opcoes in ([], [{"preco": 0.55}], [{"preco": 0.55}, {"preco": 1.20}]):
                for pct, eur in ((None, None), (10, None), (33, None), (None, 0.50)):
                    casos.append({
                        "preco": preco, "quantidade": quantidade, "opcoes": opcoes,
                        "pct": pct, "eur": eur,
                    })
    return casos


def test_o_dialogo_faz_a_conta_pela_MESMA_ordem_do_contasDaLinha(tmp_path):
    """Corrido, não afirmado: para os mesmos números, os dois ecrãs dão o
    mesmo unitário, o mesmo bruto, o mesmo desconto e o mesmo total."""
    casos = _casos_da_ordem()
    saida = _os_dois_calculos(casos, tmp_path)

    divergentes = [
        (caso, r["dialogo"], r["linha"])
        for caso, r in zip(casos, saida)
        if r["dialogo"] != r["linha"]
    ]
    assert divergentes == [], (
        "O diálogo do produto e o `contasDaLinha` deixaram de dar o mesmo "
        "número para a mesma linha — e é o do servidor que vai para a fatura. "
        "Os primeiros: %s" % divergentes[:3]
    )
    # Rede de segurança do próprio teste: sem casos com opções, quantidade > 1
    # e desconto, uma ordem trocada passaria despercebida.
    assert len(casos) > 100


def test_a_malha_da_ordem_apanha_mesmo_uma_ordem_trocada(tmp_path):
    """A prova por mutação, no próprio ficheiro. Troca-se a ORDEM do diálogo
    para o erro clássico — somar o extra das opções depois de multiplicar pela
    quantidade — e confirma-se que o teste de cima ficaria vermelho. Sem isto,
    ele podia estar a comparar uma malha onde todas as ordens dão o mesmo."""
    dialogo = _ler(_DIALOGO)
    guiao = tmp_path / "ordem_trocada.js"
    passos = [_passo(dialogo, nome) for nome in _PASSOS_DO_DIALOGO]
    # A mutação: o extra das opções deixa de entrar no unitário e passa a
    # entrar depois da quantidade.
    passos[1] = "  const precoUnitario = cent(precoNumero || 0);"
    passos[2] = "  const brutoLinha = cent(precoUnitario * (qtdNumero || 0) + extraOpcoes);"
    casos = _casos_da_ordem()
    guiao.write_text(
        "\n".join([
            _codigo_do_ecra(),
            "function noDialogo(precoNumero, opcoes, qtdNumero, pctNumero, eurNumero) {",
            "\n".join(passos),
            "  return { unitario: precoUnitario, bruto: brutoLinha,"
            "           desconto: descontoLinha, total: totalLinha };",
            "}",
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map((c) => ({",
            "  dialogo: noDialogo(c.preco, c.opcoes, c.quantidade, c.pct, c.eur),",
            "  linha: contasDaLinha({",
            "    produto_preco: c.preco, preco_override: null, opcoes: c.opcoes,",
            "    quantidade: c.quantidade, desconto_pct: c.pct, desconto_eur: c.eur,",
            "  }),",
            "}))));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert resultado.returncode == 0, resultado.stderr.decode("utf-8", "replace")
    saida = json.loads(resultado.stdout.decode("utf-8"))
    divergentes = [r for r in saida if r["dialogo"] != r["linha"]]
    assert len(divergentes) > 0, (
        "Com a ordem trocada, nenhum caso divergiu — a malha de casos deixou "
        "de conter opções com quantidade acima de 1, e o guarda de cima está a "
        "verificar o vazio."
    )
