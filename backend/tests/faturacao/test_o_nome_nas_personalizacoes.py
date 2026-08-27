"""**Um botão só na linha da conta — e o nome do cliente a continuar a poder
mudar-se.**

O dono, no diálogo de uma linha já gravada: «quero que fique somente o editar
personalizações. o editar pedido não é preciso. só se repete o que já tem nas
personalizações.»

Só que não repetia. O «Editar pedido» reabria o pedido guiado, e era o ÚNICO
sítio onde o NOME DO CLIENTE se podia corrigir: o painel das Personalizações
ignorava os grupos de texto por inteiro (está escrito no `ehGrupoDeOpcoes`).
Tirar o botão sem mais fazia com que um «Matheus» escrito onde era «Mateus»
só se corrigisse apagando a linha e refazendo o pedido — com o cliente à
frente, e o nome é o que vai no copo e o maior elemento da ficha da cozinha.

Por isso o botão sai E o nome entra no painel. É isso que estes testes
prendem: o que o dono pediu, e o que não se pode perder pelo caminho.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_PRODUTO = {"id": "p1", "nome": "Açaí", "preco": 7.20, "tax_id": "INT",
            "foto_url": None, "grupos_personalizacao": ["g-nome", "g-top"]}
_GRUPOS = [
    {"id": "g-nome", "nome": "Nome no copo", "tipo": "texto",
     "min_escolhas": 0, "max_escolhas": 0, "opcoes": [], "sai_na_fatura": False},
    {"id": "g-top", "nome": "Toppings", "tipo": "opcoes",
     "min_escolhas": 0, "max_escolhas": 3, "sai_na_fatura": True,
     "opcoes": [{"id": "o-am", "nome": "Amendoim", "preco": 0},
                {"id": "o-mo", "nome": "Morango", "preco": 0}]},
]
_LINHA = {
    "id": "l1", "produto_id": "p1", "produto_nome": "Açaí", "quantidade": 1,
    "produto_preco": 7.20, "produto_tax_id": "INT",
    "opcoes": [{"id": "o-am", "grupo_id": "g-top", "nome": "Amendoim",
                "preco": 0, "nome_grupo": "Toppings"}],
    "respostas_texto": [{"grupo_id": "g-nome", "nome_grupo": "Nome no copo",
                         "texto": "Matheus"}],
    "preco_override": None, "tax_override": None,
    "desconto_pct": None, "desconto_eur": None,
}


def _guiao(passos):
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const Dialogo = carregar(path2.join(POS, 'PosDialogoProduto.js')).default;",
        "const gravados = [];",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(Dialogo, {",
        "  produto: %s," % json.dumps(_PRODUTO, ensure_ascii=False),
        "  grupos: %s," % json.dumps(_GRUPOS, ensure_ascii=False),
        "  linha: %s," % json.dumps(_LINHA, ensure_ascii=False),
        "  aGravar: false,",
        "  onGravar: (dados) => gravados.push(dados),",
        "  onVoltar: () => {}, onRemover: () => {},",
        "  onEditarPedido: () => {},",
        "})); });",
        "await act(async () => {});",
        "const texto = () => textoVisivel(alvo);",
        "const botaoDe = (t) => Array.from(alvo.querySelectorAll('button'))",
        "  .find((b) => (b.textContent || '').includes(t));",
        "const carregar_em = async (n) => { await act(async () => { n.click(); });",
        "  await act(async () => {}); };",
        "const saida = {};",
    ] + passos + ["saida.gravados = gravados;",
                  "process.stdout.write(JSON.stringify(saida));"])


def _monta(passos, tmp, nome):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao(passos), tmp, nome)


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    return _monta([
        "saida.na_linha = texto();",
        "saida.tem_editar_pedido = !!botaoDe('Editar pedido');",
        "await carregar_em(botaoDe('Editar Personalizações'));",
        "saida.no_painel = texto();",
        # Corrigir o nome e concluir.
        "const campo = alvo.querySelector('[data-testid=\"resposta-g-nome\"]');",
        "saida.tem_campo_do_nome = !!campo;",
        "saida.valor_inicial = campo ? campo.value : null;",
        # Defensivo de propósito: sem o campo, o guião tem de CONTINUAR até
        # ao fim para as asserções correrem e dizerem o que falta — um
        # TypeError a meio faz todos os testes falharem com a mesma mensagem
        # inútil, e esconde os que já estariam certos.
        # Pelo setter NATIVO, e não por `campo.value = ...`: o React tem o seu
        # próprio registo do valor de um campo controlado, e escrever por cima
        # dele deixa esse registo a dizer que nada mudou — o `onChange` não
        # chega a correr e o teste media um ecrã que não recebeu a escrita.
        # Mesmo ajudante de `test_as_notas_de_credito_presas_no_ecra.py`.
        "function escrever(el, valor) {",
        "  const proto = dom.window.HTMLInputElement.prototype;",
        "  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);",
        "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
        "}",
        "if (campo) {",
        "  await act(async () => { escrever(campo, 'Mateus'); });",
        "  await act(async () => {});",
        "}",
        "const concluir = botaoDe('Concluir');",
        "if (concluir) await carregar_em(concluir);",
        "const gravar = botaoDe('Gravar');",
        "if (gravar) await carregar_em(gravar);",
    ], tmp_path_factory.mktemp("dialogo"), "dialogo.js")


def test_o_botao_EDITAR_PEDIDO_desapareceu(ecra):
    """«o editar pedido não é preciso» — literalmente o pedido do dono."""
    assert not ecra["tem_editar_pedido"], (
        "O «Editar pedido» ainda está no ecrã da linha.")
    assert "Editar pedido" not in ecra["na_linha"]


def test_o_EDITAR_PERSONALIZACOES_continua_la(ecra):
    assert "Editar Personalizações" in ecra["na_linha"]


def test_o_NOME_do_cliente_passa_a_viver_no_painel(ecra):
    """O que não se pode perder ao tirar o outro botão: o painel ignorava os
    grupos de texto por inteiro, e o nome era o que vai no copo."""
    assert ecra["tem_campo_do_nome"], (
        "O painel das Personalizações não tem por onde escrever o nome — "
        "tirar o «Editar pedido» deixou a linha sem como o corrigir.")
    assert ecra["valor_inicial"] == "Matheus", ecra["valor_inicial"]
    assert "Nome no copo" in ecra["no_painel"]


def test_corrigir_o_nome_CHEGA_ao_servidor(ecra):
    """Um ecrã que aceitasse a correcção e não a mandasse a lado nenhum
    desenhava-se exactamente igual — e o copo saía com o nome errado."""
    assert ecra["gravados"], "O Gravar não chamou o servidor."
    respostas = ecra["gravados"][-1].get("respostas_texto")
    assert respostas, "O `respostas_texto` não viajou no Gravar."
    assert respostas[0]["texto"] == "Mateus", respostas
    assert respostas[0]["grupo_id"] == "g-nome"


def test_as_OPCOES_continuam_a_viajar_no_mesmo_gravar(ecra):
    """A correcção do nome não pode custar as personalizações: as duas coisas
    saem no MESMO pedido, e um `respostas_texto` que substituísse as `opcoes`
    apagava o Amendoim da conta."""
    gravado = ecra["gravados"][-1]
    assert [o["id"] for o in gravado["opcoes"]] == ["o-am"], gravado["opcoes"]
    assert gravado["quantidade"] == 1
