"""**Dividir e separar, do toque à cobrança** — montado e carregado, não lido.

O dono usou o POS ao balcão e disse que esta parte estava confusa. O que se
mudou não foi a matemática: foi o CAMINHO. Antes, os dois botões levavam a um
ecrã à parte — previsão, pastilhas por pessoa, um botão para repartir e outro
para escolher quem se cobra — e só depois disso é que alguém pagava. Agora:

- **dividir** é um toque: o número de pessoas vive num stepper encostado aos
  botões, e a seguir ao toque o ecrã já está a cobrar a PRIMEIRA pessoa;
- **separar** volta à conta e deixa tocar nos produtos desta pessoa, com o
  «cobrar esta pessoa» a gravar UMA parte de cada vez
  (`POST /pos/venda/{id}/separar-parte`) — o resto continua a ser a conta.

Nada disto se prova a ler o ficheiro: monta-se o `PosVenda` a sério em Node,
com o servidor fabricado à frente do axios, CARREGA-SE nos botões, e afirma-se
o que saiu no pedido e o que ficou no ecrã. É a mesma disciplina do
test_o_x_de_apagar_na_conta.py, e a razão é a de sempre — estes ecrãs
desenham-se sem servidor nenhum, e já foram dois defeitos a produção assim.
"""
import json

import pytest

from faturacao.venda import _venda_publica

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_COOKIE = "Cookie Tradicional"
_ACAI = "Açaí Regular"


def _linha(id_, produto_id, nome, preco):
    return {
        "id": id_, "produto_id": produto_id, "produto_nome": nome,
        "produto_preco": preco, "produto_tax_id": "INT", "quantidade": 1,
        "opcoes": [], "respostas_texto": [], "preco_override": None,
        "tax_override": None, "desconto_pct": None, "desconto_eur": None,
    }


_L_COOKIE = _linha("l1", "p-cookie", _COOKIE, 3.80)
_L_ACAI = _linha("l2", "p-acai", _ACAI, 8.99)


def _conta(id_, linhas, estado="aberta", mae=None):
    return _venda_publica({
        "id": id_, "loja_id": "l1", "caixa_id": "c1", "sessao_id": "s1",
        "operador_id": "o1", "dispositivo_id": "pc-1", "linhas": linhas,
        "desconto_global_pct": None, "desconto_global_eur": None,
        "estado": estado, "criada_em": "2026-08-25T10:00:00+00:00",
        "conta_mae_id": mae,
    })


def _produto(id_, nome, preco):
    return {
        "id": id_, "nome": nome, "categoria_id": "cat-1", "preco": preco,
        "tax_id": "INT", "foto_url": None, "grupos_personalizacao": [],
        "ativo": True, "vendavel": True, "erros": [],
    }


_CATALOGO = {
    "categorias": [{"id": "cat-1", "nome": "Venda ao Público", "ordem": 0, "ativa": True}],
    "produtos": [_produto("p-cookie", _COOKIE, 3.80), _produto("p-acai", _ACAI, 8.99)],
}


def _arranque(respostas_extra):
    """O POS montado com a conta dos dois artigos à frente, e o ecrã de
    pagamento aberto — que é onde os dois botões vivem."""
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: 'Loja' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosVenda = carregar(path2.join(POS, 'PosVenda.js')).default;",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });"
        % json.dumps(_CATALOGO, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [",
        "  { id: 'tp-1', nome: 'Dinheiro', da_troco: true, pronto: true } ] });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: { grupos: [] } });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        respostas_extra,
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(PosVenda, {",
        "  operador: { id: 'o1', nome: 'Ana' }, caixa: { id: 'c1', nome: 'Balcão' },",
        "  sessao: { id: 's1', fundo: 50 }, lojaNome: 'Loja',",
        "  onSair: () => {}, onCaixaFechada: () => {}, modo: 'normal' })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const botao = (texto) => [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(texto) && !b.disabled);",
        "const carregar_em = async (texto) => {",
        "  const b = botao(texto);",
        "  if (!b) throw new Error('sem botão vivo com o texto ' + texto + ' — no ecrã: '",
        "    + textoVisivel(alvo).slice(0, 500));",
        "  await act(async () => { b.click(); });",
        "  await act(async () => {});",
        "};",
        "await carregar_em('FINALIZAR');",
    ])


def _correr(cenario, tmp_path_factory, nome):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp(nome), "montar-%s.js" % nome)


# --- Dividir: um toque, e já se está a cobrar a primeira pessoa ---------------


@pytest.fixture(scope="module")
def dividir(tmp_path_factory):
    parte1 = _conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)], mae="v-1")
    parte2 = _conta("p-2", [_linha("x2", "p-acai", _ACAI, 8.99)], mae="v-1")
    cenario = _arranque("\n".join([
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_conta("v-1", [_L_COOKIE, _L_ACAI]), ensure_ascii=False),
        "RESPOSTAS_POS['POST /pos/venda/v-1/dividir'] = () => ({ data: %s });"
        % json.dumps({
            "modo": "dividir",
            "conta_mae": _conta("v-1", [_L_COOKIE, _L_ACAI], estado="separada"),
            "partes": [parte1, parte2],
        }, ensure_ascii=False),
    ]))
    return _correr("\n".join([
        cenario,
        "const noPagamento = textoVisivel(alvo);",
        "await carregar_em('Dividir Conta');",
        "const aCobrarAPrimeira = textoVisivel(alvo);",
        # **A seta de voltar.** É um botão só com ícone (sem texto), por isso
        # apanha-se pelo ícone. Dois toques: se a seta cobrasse a pessoa
        # seguinte, o segundo trazia de volta a primeira — o vaivém que o dono
        # apanhou ao usar o POS.
        "const seta = () => [...alvo.querySelectorAll('button')].find(",
        "  (b) => b.querySelector('[data-icone=\"ArrowLeft\"]'));",
        "if (!seta()) throw new Error('sem seta de voltar no ecra de pagamento');",
        "await act(async () => { seta().click(); });",
        "await act(async () => {});",
        "const depoisDaSeta = textoVisivel(alvo);",
        "process.stdout.write(JSON.stringify({",
        "  noPagamento, aCobrarAPrimeira, depoisDaSeta, depois: textoVisivel(alvo),",
        "  pedidos: pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url),",
        "  corpos: pedidos.filter((p) => p.corpo).map((p) => p.corpo),",
        "}));",
    ]), tmp_path_factory, "dividir")


def test_o_ecra_de_pagamento_tem_o_stepper_das_pessoas(dividir):
    """Sem esta afirmação, o resto media o vazio — e o stepper é a peça que
    faz o dividir caber num toque."""
    assert "Pessoas" in dividir["noPagamento"], dividir["noPagamento"][:500]
    assert "Dividir Conta" in dividir["noPagamento"]
    assert "Separar Conta" in dividir["noPagamento"]


def test_o_toque_em_dividir_manda_o_numero_de_pessoas(dividir):
    assert any(p.endswith("/pos/venda/v-1/dividir") for p in dividir["pedidos"]), \
        dividir["pedidos"]
    assert {"partes": 2} in dividir["corpos"], dividir["corpos"]


def test_a_seta_de_voltar_sai_do_pagamento_em_vez_de_cobrar_a_pessoa_seguinte(dividir):
    """**O defeito que o dono apanhou a usar o POS.** Esta função serve as duas
    saídas do ecrã de pagamento — o botão que fecha a fatura acabada de sair e
    a seta de voltar — e o salto para a pessoa seguinte tinha ficado nas duas:
    tocava-se na seta para sair da pessoa 1 e aterrava-se na 2, tocava-se outra
    vez e voltava-se à 1, sem forma de sair.

    Quem acabou de emitir tem `documento`; a seta não tem nada."""
    assert "Pessoa 2 de 2" not in dividir["depoisDaSeta"], \
        dividir["depoisDaSeta"][:400]
    assert "Cobrar as partes" in dividir["depoisDaSeta"], \
        dividir["depoisDaSeta"][:400]


def test_a_seguir_ao_toque_ja_se_esta_a_cobrar_a_primeira_pessoa(dividir):
    """O ponto todo desta mudança: entre o toque e a fatura não há ecrã
    nenhum. Antes, aqui estava uma lista de pastilhas à espera de que alguém
    escolhesse por onde começar — quando a resposta é sempre a primeira."""
    assert "Pessoa 1 de 2" in dividir["aCobrarAPrimeira"], dividir["aCobrarAPrimeira"][:600]
    assert "€ 3,80" in dividir["aCobrarAPrimeira"], dividir["aCobrarAPrimeira"][:600]
    assert "EMITIR" in dividir["aCobrarAPrimeira"].upper(), dividir["aCobrarAPrimeira"][:600]


# --- Separar: uma pessoa de cada vez, na conta --------------------------------


@pytest.fixture(scope="module")
def separar(tmp_path_factory):
    parte = _conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)], mae="v-1")
    resto = _conta("v-1", [_L_ACAI])
    cenario = _arranque("\n".join([
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_conta("v-1", [_L_COOKIE, _L_ACAI]), ensure_ascii=False),
        "RESPOSTAS_POS['POST /pos/venda/v-1/separar-parte'] = () => ({ data: %s });"
        % json.dumps({"parte": parte, "conta": resto}, ensure_ascii=False),
    ]))
    return _correr("\n".join([
        cenario,
        "await carregar_em('Separar Conta');",
        "const naConta = textoVisivel(alvo);",
        # **A grelha, a meio de uma atribuição.** O cartão do produto está lá
        # do lado e a mão vai lá dar — e um artigo picado agora entra na conta
        # por baixo do que se está a montar. Toca-se nele de propósito, e o que
        # se afirma é que NÃO saiu pedido nenhum de juntar linha.
        "const cartao = [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(%s)" % json.dumps(_ACAI),
        "    && !(b.textContent || '').includes('cada'));",
        "if (cartao) { await act(async () => { cartao.click(); });",
        "  await act(async () => {}); }",
        "const depoisDoCartao = pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url);",
        # Tocar no produto desta pessoa: a linha da conta é um botão nativo,
        # e o corpo dela é o que passa a juntar unidades.
        # A linha da CONTA, e não o produto da grelha: os dois têm o nome do
        # artigo, e é o "cada" do preço unitário que só a linha da conta tem.
        # (O primeiro `find` apanhava o cartão da grelha — e a grelha, agora,
        # está morta enquanto se separa.)
        "const linha = [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(%s)" % json.dumps(_COOKIE),
        "    && (b.textContent || '').includes('cada'));",
        "if (!linha) throw new Error('sem linha do cookie: ' + naConta.slice(0, 400));",
        "await act(async () => { linha.click(); });",
        "await act(async () => {});",
        "const comUm = textoVisivel(alvo);",
        "await carregar_em('COBRAR ESTA PESSOA');",
        "process.stdout.write(JSON.stringify({",
        "  naConta, comUm, depoisDoCartao, depois: textoVisivel(alvo),",
        "  pedidos: pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url),",
        "  corpos: pedidos.filter((p) => p.corpo).map((p) => p.corpo),",
        "}));",
    ]), tmp_path_factory, "separar")


def test_separar_volta_a_conta_para_se_tocar_nos_produtos(separar):
    """A atribuição faz-se onde estão as linhas — na conta — e não num ecrã
    terceiro. É o que o ecrã diz, e é o que a mão vai fazer."""
    assert "Esta pessoa leva" in separar["naConta"], separar["naConta"][:600]
    assert "€ 0,00" in separar["naConta"], separar["naConta"][:600]
    assert _COOKIE in separar["naConta"] and _ACAI in separar["naConta"]


def test_a_grelha_esta_morta_enquanto_se_separa(separar):
    """Descoberto por este teste, e não por leitura: a grelha continuava viva
    durante a atribuição e o primeiro `find` do cenário apanhou o cartão do
    produto em vez da linha da conta. Um toque ali junta um artigo à conta que
    se está a repartir — muda o total por baixo das mãos da operadora."""
    assert not [p for p in separar["depoisDoCartao"] if "/linhas" in p], \
        separar["depoisDoCartao"]
    assert separar["comUm"].count(_ACAI) >= 1


def test_tocar_no_produto_poe_no_e_o_valor_sobe(separar):
    assert "€ 3,80" in separar["comUm"], separar["comUm"][:600]
    assert "COBRAR ESTA PESSOA" in separar["comUm"].upper()


def test_cobrar_esta_pessoa_manda_as_unidades_escolhidas(separar):
    assert any(p.endswith("/pos/venda/v-1/separar-parte") for p in separar["pedidos"]), \
        separar["pedidos"]
    assert {"linhas": [{"linha_id": "l1", "quantidade": 1}]} in separar["corpos"], \
        separar["corpos"]


def test_a_seguir_fica_se_a_cobrar_a_parte_desta_pessoa(separar):
    assert "€ 3,80" in separar["depois"], separar["depois"][:600]
    assert "EMITIR" in separar["depois"].upper(), separar["depois"][:600]
