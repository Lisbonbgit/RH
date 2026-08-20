"""Guarda de regressão: o resumo do ECRÃ diz o mesmo que o título da FATURA.

Porque este ficheiro existe. A operadora confere a linha pelo resumo que o
POS lhe mostra por baixo do nome do produto ("Levar · Maria" / "Nutella 2× ·
Morango 1×"). Esse resumo dividia as opções só pelo interruptor
`sai_na_fatura`, e o título da fatura divide-as por outra regra: uma opção
COM PREÇO aparece sempre, esteja o interruptor como estiver
(`precos._descricao_das_opcoes` — "o interruptor esconde o que não custa
nada, nunca um euro"). Resultado, com um grupo de toppings desligado por
engano: o servidor somava as DUAS doses do "Extra caramelo" e escrevia
"(Extra caramelo 2×)" na Fatura Simplificada, e o ecrã mostrava-o UMA vez e
sem dose, encostado ao "Levar". A operadora confere pelo ecrã, e o ecrã não
lhe dizia que foram duas.

A técnica é a do `test_caminhos_do_pos.py` e do
`test_mapeamento_nao_se_perde.py` — ler o frontend e confrontá-lo com a
verdade do servidor —, com uma diferença que aqueles dois declaram não ter:
aqui o JavaScript é mesmo EXECUTADO. Não há infra-estrutura de testes no
frontend (nem um `*.test.js`, e os módulos do POS importam React e os
`@/components/ui`, que exigiriam configuração de jest que não existe), mas as
funções em causa são puras e não importam nada — extraem-se do ficheiro pelo
texto e correm-se em Node, e o que se compara é a saída delas com a do
`precos.linha_de_venda`. Sem isto ficava outra vez a valer só o que está
escrito em comentários, que foi exactamente o que deixou este defeito passar
duas revisões.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from faturacao.precos import linha_de_venda

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_POS = _RAIZ / "frontend" / "src" / "pages" / "pos"
_PERSONALIZACOES = _POS / "PosPersonalizacoes.js"
_PEDIDO_GUIADO = _POS / "PosPedidoGuiado.js"
_DIALOGO = _POS / "PosDialogoProduto.js"


def _ler(ficheiro: Path) -> str:
    if not ficheiro.exists():
        pytest.fail(
            "Não encontrei %s. Se o ecrã mudou de sítio, este guarda tem de "
            "ir atrás dele — não se apaga." % ficheiro
        )
    return ficheiro.read_text(encoding="utf-8")


def _corpo_da_funcao(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O código de uma função, do início da assinatura até à chaveta que a
    fecha. Conta as chavetas: os `${...}` dos template literals são pares e
    não a atrapalham. Se alguém escrever uma chaveta desemparelhada num
    comentário lá dentro, isto falha — e falhar alto é o que se quer, porque
    a alternativa é o guarda passar a medir outra coisa em silêncio."""
    if assinatura not in texto:
        pytest.fail(
            "Não encontrei `%s` em %s. Se a função foi renomeada ou movida, a "
            "regra que ela cumpre continua a ter de ser guardada."
            % (assinatura, ficheiro.name)
        )
    inicio = texto.index(assinatura)
    i = texto.index("{", inicio)
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


_ASSINATURA_PREDICADO = "export const ehIndicacaoDeServico"
_ASSINATURA_RESUMO = "export function resumoDoPedido(linha)"
_ASSINATURA_DIALOGO = "const tituloDoPedido = (linha)"


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    # O node deste Mac vive fora do PATH (ver a memória do projecto). Não é
    # uma configuração que se possa exigir de quem corre a suite, por isso
    # procura-se, e se não houver o teste diz porque não correu em vez de
    # ficar verde a fingir. O guarda do texto, aqui em baixo, esse corre
    # sempre.
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip(
        "Sem `node` para executar o JavaScript do ecrã "
        "(nem no PATH nem em ~/.local/node/bin)."
    )


def _resumo_no_ecra(linha: dict, tmp_path: Path) -> dict:
    """Corre em Node o resumo do ecrã — o mesmo código que está no ficheiro
    do POS, sem cópia nenhuma escrita aqui — para a linha dada."""
    predicado = _corpo_da_seta(
        _ler(_PERSONALIZACOES), _ASSINATURA_PREDICADO, _PERSONALIZACOES)
    resumo = _corpo_da_funcao(
        _ler(_PEDIDO_GUIADO), _ASSINATURA_RESUMO, _PEDIDO_GUIADO)
    dialogo = _corpo_da_funcao(_ler(_DIALOGO), _ASSINATURA_DIALOGO, _DIALOGO)

    guiao = tmp_path / "resumo.js"
    guiao.write_text(
        # `export` fora: isto corre como um guião solto, não como módulo.
        "\n".join([
            predicado.replace("export ", "", 1),
            resumo.replace("export ", "", 1),
            dialogo,
            "const linha = %s;" % json.dumps(linha),
            "process.stdout.write(JSON.stringify({"
            "  resumo: resumoDoPedido(linha),"
            "  dialogo: tituloDoPedido(linha),"
            "}));",
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


def _do_titulo_da_fatura(titulo: str):
    """As opções do título ("Açaí (Extra caramelo 2×, Morango)") em pares
    (nome, doses). O título omite o `1×`; o ecrã escreve-o sempre — é a única
    diferença combinada entre os dois, e é aqui que ela se desfaz para se
    poder comparar o resto."""
    dentro = re.search(r"\((.*)\)$", titulo)
    if not dentro:
        return []
    return [_par(pedaco) for pedaco in dentro.group(1).split(", ")]


def _do_ecra(frase: str):
    """O mesmo, para "Extra caramelo 2× · Morango 1×"."""
    return [_par(pedaco) for pedaco in frase.split(" · ")] if frase else []


def _par(pedaco: str):
    achado = re.match(r"^(.*) (\d+)×$", pedaco)
    return (achado.group(1), int(achado.group(2))) if achado else (pedaco, 1)


# A linha do defeito, tal como sai do balcão: um grupo de serviço escondido
# (o "Levar"), um grupo de TOPPINGS que o gestor desligou por engano — com
# uma opção paga de duas doses lá dentro — e um topping normal. O desconto de
# preço negativo está aqui pela mesma razão que está no `precos.py`: o
# catálogo já não o deixa criar, mas o caminho até à linha continua aberto, e
# um euro a menos também é um euro.
_LINHA = {
    "opcoes": [
        {"nome": "Levar", "preco": 0, "sai_na_fatura": False},
        {"nome": "Extra caramelo", "preco": 0.5, "sai_na_fatura": False},
        {"nome": "Extra caramelo", "preco": 0.5, "sai_na_fatura": False},
        {"nome": "Morango", "preco": 0, "sai_na_fatura": True},
        {"nome": "Desconto fidelidade", "preco": -1.0, "sai_na_fatura": False},
    ],
    "respostas_texto": [{"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"}],
}


def test_o_ecra_mostra_as_doses_que_a_fatura_cobra(tmp_path):
    """O que o ecrã põe nas ESCOLHAS (com dose) é exactamente o que a fatura
    põe no título, com as mesmas doses e pela mesma ordem."""
    titulo = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1, _LINHA["opcoes"]
    )["title"]
    saida = _resumo_no_ecra(_LINHA, tmp_path)

    assert _do_ecra(saida["resumo"]["escolhas"]) == _do_titulo_da_fatura(titulo)

    # E o que fica de fora é só o que não custa nada: o serviço e o nome do
    # copo. Antes desta correcção, o "Extra caramelo" pago estava nesta
    # frase — uma vez, sem dose.
    assert saida["resumo"]["servico"] == "Levar · Maria"


def test_o_dialogo_do_produto_le_a_linha_como_o_resumo_da_conta(tmp_path):
    """O bloco só de leitura do diálogo do produto (`tituloDoPedido`) divide
    as opções pela mesma pergunta — os dois ecrãs mostram a mesma linha e não
    podem dizer coisas diferentes sobre ela."""
    saida = _resumo_no_ecra(_LINHA, tmp_path)
    campos = {c["label"]: c["valor"] for c in saida["dialogo"]}

    assert campos["Serviço"] == "Levar"
    assert campos["Nome"] == "Maria"
    assert _do_ecra(campos["Personalizações"].replace(", ", " · ")) == _do_ecra(
        saida["resumo"]["escolhas"]
    )


def test_os_dois_ecras_perguntam_pela_MESMA_funcao():
    """Sem `node`, este é o guarda que resta — e é o que impede a regra de
    voltar a ser escrita à mão em cada ecrã.

    A divisão entre serviço e escolhas está numa função só
    (`ehIndicacaoDeServico`, no PosPersonalizacoes.js), e é ela que carrega o
    porquê. Enquanto cada ecrã lia o `sai_na_fatura` por sua conta, o mesmo
    defeito estava escrito duas vezes e corrigiu-se uma."""
    for ficheiro, assinatura, extrair in (
        (_PEDIDO_GUIADO, _ASSINATURA_RESUMO, _corpo_da_funcao),
        (_DIALOGO, _ASSINATURA_DIALOGO, _corpo_da_funcao),
    ):
        texto = _ler(ficheiro)
        assert "ehIndicacaoDeServico" in texto, (
            "%s tem de importar `ehIndicacaoDeServico` do PosPersonalizacoes."
            % ficheiro.name
        )
        corpo = extrair(texto, assinatura, ficheiro)
        assert "sai_na_fatura" not in corpo, (
            "%s voltou a ler o `sai_na_fatura` à mão em `%s`. A pergunta é a do "
            "título da fatura e vive em `ehIndicacaoDeServico` — uma opção COM "
            "PREÇO é sempre uma escolha, com a dose." % (ficheiro.name, assinatura)
        )
