"""**O voucher L'Açaí no cartão da caixa** — montado e carregado, não lido.

A recompensa deixou de valer só nos pedidos feitos e pagos na app: o MESMO QR
que já dá pontos traz agora o desconto ao balcão. Quem decide é a app (a
elegibilidade é uma regra de dinheiro e fica num sítio só); o POS aplica-a na
linha e emite — e a conta pode ficar a 0,00 € com a Fatura Simplificada a sair
à mesma.

**Duas regras mandam em tudo o que está aqui, e os testes são sobre elas:**

1. **Nada disto pode impedir uma fatura de sair.** App em baixo, tecto de
   espera esgotado ou resposta estranha = venda normal, sem desconto, com o
   EMITIR vivo.
2. **Falhar fechado e EM VOZ ALTA.** Uma categoria sem correspondência é *sem
   desconto*, nunca um desconto errado — mas tem de aparecer no cartão. Um
   voucher que não se aplica sem ninguém perceber porquê é o pior desfecho de
   todos.

Os ecrãs do POS desenham-se todos sem servidor nenhum, e já foram defeitos a
produção exactamente assim. Por isso monta-se o `PosVenda` INTEIRO, com o
servidor fabricado à frente do axios, carrega-se nos botões, e o que se afirma
é o que a operadora LÊ (`textoVisivel`) e o que o ecrã MANDA
(`pedidos[i].corpo`). O `PosVenda` e não o `PosFinalizar` sozinho: entre o
cartão e o `POST /pos/venda/{id}/finalizar` há dois ficheiros, e o corpo desse
pedido — os pagamentos e a ligação dos pontos — é metade do que se vem provar.
"""
import json

import pytest

from faturacao.venda import _venda_publica

# Os cinco nomes estão todos AQUI EM CIMA de propósito: um import acrescentado
# a meio do ficheiro faz a parte que o usa rebentar na RECOLHA (`NameError`,
# antes de correr teste nenhum) se alguém executar as tarefas por outra ordem.
from .test_o_dividir_e_o_separar_no_ecra import (  # noqa: F401
    _L_ACAI, _L_COOKIE, _arranque, _conta, _correr,
)
from .test_os_pontos_no_ecra_do_pos import _CODIGO, _EMITIDA, _UTEIS  # noqa: F401

_TITULO = "Açaí Médio grátis"
# A frase do desconto já aplicado, como ela sai do `estadoDoVoucher`: o título
# que a APP mandou, e o valor formatado pelo `eurosPos` do resto do POS.
_APLICADO = "Açaí Médio grátis (− € 8,99)"
_SEM_PRODUTO = ("Açaí Médio grátis: não há nada nesta conta que sirva — "
                "acrescente o produto antes de emitir.")
_SEM_CASAR = ("Tem um voucher que não consegui casar com esta conta — a venda "
              "segue sem desconto. Avise o gestor.")

_ROTA = "POST /pos/venda/v-1/voucher"


def _com_voucher(linha, valor, marcada=True):
    """A linha como o SERVIDOR a devolve depois de aplicar o voucher: o
    desconto no `desconto_eur` (daí para a frente é a máquina que já existe) e
    a MARCA `voucher_id`, que é o que distingue uma oferta de fidelidade de um
    desconto que a funcionária deu de cabeça.

    `marcada=False` é justamente o desconto dado de cabeça — o mesmo dinheiro,
    sem a marca. É esse que não pode abrir o travão do total a zero."""
    linha = dict(linha, desconto_eur=valor)
    if marcada:
        linha["voucher_id"] = "vc-1"
    return linha


# 3,80 + 8,99 = 12,79 — a conta de sempre destes ficheiros.
_CONTA = _conta("v-1", [_L_COOKIE, _L_ACAI])
# A mesma conta com o açaí oferecido: 12,79 − 8,99 = 3,80.
_CONTA_DESCONTADA = _conta("v-1", [_L_COOKIE, _com_voucher(_L_ACAI, 8.99)])
# Só o açaí, e oferecido: 0,00 €. É o caso normal de uma recompensa ao balcão.
_SO_ACAI = _conta("v-1", [_L_ACAI])
_A_ZERO = _conta("v-1", [_com_voucher(_L_ACAI, 8.99)])
# O mesmo zero, SEM a marca: um desconto manual de 100 %, que não pede PIN a
# ninguém.
_A_ZERO_SEM_MARCA = _conta("v-1", [_com_voucher(_L_ACAI, 8.99, marcada=False)])
# **A MARCA ÓRFÃ**: a linha ficou com o `voucher_id` e sem desconto nenhum, e o
# zero vem de um desconto GLOBAL de 100 % que a operadora deu de cabeça.
#
# Não é um caso inventado: `PUT /pos/venda/{id}/linhas/{linha_id}` aceita
# `desconto_eur` e não conhece o `voucher_id`, por isso limpar o desconto da
# linha deixa a marca para trás. Os totais vêm do servidor
# (`_venda_publica`/`_totais`), como em todas as contas deste ficheiro — um zero
# escrito à mão aqui não provava que o ecrã o vê a zero.
_A_ZERO_MARCA_ORFA = _venda_publica(dict(
    _conta("v-1", [dict(_L_ACAI, voucher_id="vc-1")]), desconto_global_pct=100))

# **A app em baixo, vista pela rota do POS: um 200 que é um «não sei».** Todas
# as chaves do contrato a `null` — a rota não pode devolver erro, porque nada
# disto pode impedir uma fatura de sair — e `app_indisponivel: true` a dizer que
# a ausência não é uma resposta. A conta volta EXACTAMENTE como estava, com o
# desconto que já lá tinha.
_APP_INDISPONIVEL = {
    "voucher_id": None, "valor": None, "titulo": None, "linha_id_alvo": None,
    "motivo": None, "app_indisponivel": True, "venda": _CONTA_DESCONTADA,
}

_VOUCHER_APLICADO = {
    "voucher_id": "vc-1", "valor": 8.99, "titulo": _TITULO,
    "linha_id_alvo": "l2", "venda": _CONTA_DESCONTADA,
}


def _cenario(conta, voucher_js, extra=""):
    """O POS montado no Finalizar, com o cliente dos pontos JÁ na gaveta.

    Pela gaveta, e não pela leitura do QR, porque é o caminho mais exigente: a
    ligação existe no instante da MONTAGEM, e é aí que a pergunta do voucher
    tem de nascer. (É também o que acontece a sério sempre que a operadora sai
    do Finalizar para juntar mais um artigo e volta.)"""
    return _arranque("\n".join([
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(conta, ensure_ascii=False),
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(_EMITIDA, ensure_ascii=False),
        _UTEIS,
        "const CONTA = %s;" % json.dumps(_CONTA, ensure_ascii=False),
        "let respostaDoVoucher = %s;" % voucher_js,
        "RESPOSTAS_POS['%s'] = () => respostaDoVoucher();" % _ROTA,
        "lib.guardarPontosDaConta('v-1', { id: 'lig-1', primeiro_nome: 'Ana' });",
        extra,
    ]))


# O cartão SOZINHO, e não o ecrã todo: as frases do voucher têm de estar onde a
# funcionária está a olhar quando lê o nome do cliente.
_CARTAO = "\n".join([
    "const cartao = () => {",
    "  const el = alvo.querySelector('[data-testid=\"cartao-pontos\"]');",
    "  return el ? textoVisivel(el) : null;",
    "};",
])

# Emitir, e guardar o que saiu. `carregar_em` REBENTA se o botão estiver morto
# — é isso que torna «o EMITIR está vivo» uma afirmação e não um desejo.
_EMITIR = "\n".join([
    "const emitirVivo = !!botao('EMITIR DOCUMENTO');",
    "await carregar_em('EMITIR DOCUMENTO');",
    # Três, e não um: entre o toque e o `onEmitir` há agora a segunda pergunta
    # do voucher, que é um `await` a mais do que havia.
    "await act(async () => {});",
    "await act(async () => {});",
    "const corpos = pedidos.filter((p) => p.url.endsWith('/pos/venda/v-1/finalizar'))",
    "  .map((p) => p.corpo);",
    "const doVoucher = pedidos.filter((p) => p.url.endsWith('/pos/venda/v-1/voucher'))",
    "  .map((p) => p.corpo);",
])

_COM_DINHEIRO = "await carregar_em('Dinheiro');\n" + _EMITIR


def _montar(conta, voucher_js, passos, tmp_path_factory, nome, extra=""):
    return _correr("\n".join([
        _cenario(conta, voucher_js, extra),
        _CARTAO,
        passos,
    ]), tmp_path_factory, nome)


# --- Os quatro estados do cartão ---------------------------------------------


@pytest.fixture(scope="module")
def sem_voucher(tmp_path_factory):
    """O cliente tem conta e não tem recompensa nenhuma por usar — a resposta
    muda (`{}`) é o caso mais comum de todos."""
    return _montar(_CONTA, "() => ({ data: {} })", "\n".join([
        "const noCartao = cartao();",
        "const ecra = textoVisivel(alvo);",
        _COM_DINHEIRO,
        "process.stdout.write(JSON.stringify({ noCartao, ecra, emitirVivo, corpos, doVoucher }));",
    ]), tmp_path_factory, "voucher-sem")


@pytest.fixture(scope="module")
def aplicado(tmp_path_factory):
    """O desconto entrou: o cartão di-lo e o total lá em baixo já é o de pagar."""
    return _montar(_CONTA, "() => ({ data: %s })" % json.dumps(
        _VOUCHER_APLICADO, ensure_ascii=False), "\n".join([
            "const noCartao = cartao();",
            "const ecra = textoVisivel(alvo);",
            "const dividirVivo = !!botao('Dividir Conta');",
            "const separarVivo = !!botao('Separar Conta');",
            _COM_DINHEIRO,
            "process.stdout.write(JSON.stringify({ noCartao, ecra, emitirVivo,",
            "  dividirVivo, separarVivo, corpos, doVoucher }));",
        ]), tmp_path_factory, "voucher-aplicado")


@pytest.fixture(scope="module")
def sem_produto(tmp_path_factory):
    """Tem recompensa e nada nesta conta serve. **É este estado que transforma
    um voucher perdido numa venda**: ela lê, diz ao cliente, e ainda vai a
    tempo de acrescentar o produto."""
    return _montar(_CONTA, "() => ({ data: { motivo: 'sem_linha_elegivel', titulo: %s } })"
                   % json.dumps(_TITULO), "\n".join([
                       "const noCartao = cartao();",
                       "const ecra = textoVisivel(alvo);",
                       _COM_DINHEIRO,
                       "process.stdout.write(JSON.stringify({ noCartao, ecra, emitirVivo, corpos }));",
                   ]), tmp_path_factory, "voucher-sem-produto")


@pytest.fixture(scope="module")
def sem_casar(tmp_path_factory):
    """A ponte das categorias não casou — sem desconto, e **nunca em
    silêncio**."""
    return _montar(_CONTA, "() => ({ data: { motivo: 'categoria_sem_correspondencia' } })",
                   "\n".join([
                       "const noCartao = cartao();",
                       _COM_DINHEIRO,
                       "process.stdout.write(JSON.stringify({ noCartao, emitirVivo, corpos }));",
                   ]), tmp_path_factory, "voucher-sem-casar")


def test_sem_recompensa_o_cartao_fica_exactamente_como_era(sem_voucher):
    """O estado de hoje não se toca: quem não tem voucher continua a ler o
    nome, o visto e por onde vai a fatura — e mais nada."""
    assert "Pontos para: Ana ✓ · Fatura em papel" in sem_voucher["noCartao"], \
        sem_voucher["noCartao"]
    for frase in ("grátis", "voucher", "recompensa", "Recompensa"):
        assert frase not in sem_voucher["noCartao"], sem_voucher["noCartao"]
    # E a conta é a de sempre: 12,79 € cobrados por inteiro.
    assert sem_voucher["emitirVivo"] is True
    assert sem_voucher["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], sem_voucher["corpos"][0]


def test_com_o_desconto_aplicado_o_cartao_diz_QUAL_e_QUANTO(aplicado):
    assert "Pontos para: Ana ✓" in aplicado["noCartao"], aplicado["noCartao"]
    assert _APLICADO in aplicado["noCartao"], aplicado["noCartao"]


def test_com_o_desconto_aplicado_o_TOTAL_do_ecra_ja_e_o_de_pagar(aplicado):
    """**O número que ela vai cobrar.** O total nunca se soma no browser: quem
    o calcula é o servidor, e a rota do voucher devolve a MESMA conta já com o
    `desconto_eur` na linha. Um ecrã a mostrar 12,79 € com 3,80 € gravados
    cobrava ao cliente o que a recompensa lhe tinha acabado de tirar."""
    # O TOTAL, e não um «3,80» qualquer no meio do ecrã: o subtotal continua a
    # dizer 12,79 € de propósito (é o que o cliente consumiu), e é a linha de
    # baixo — a que ela cobra — que tem de ter descido.
    assert "Total € 3,80" in aplicado["ecra"], aplicado["ecra"][:600]
    assert "Subtotal: € 12,79" in aplicado["ecra"], aplicado["ecra"][:600]
    assert "Descontos nas linhas: − € 8,99" in aplicado["ecra"], aplicado["ecra"][:600]
    # E é isso que sai no pedido: o pagamento automático leva o total certo.
    assert aplicado["emitirVivo"] is True
    assert aplicado["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 3.8}], aplicado["corpos"][0]
    assert aplicado["corpos"][0]["pontos_ligacao"] == {
        "id": "lig-1", "primeiro_nome": "Ana"}, aplicado["corpos"][0]


def test_o_ecra_pergunta_pelo_voucher_ao_LIGAR_e_outra_vez_no_EMITIR(aplicado):
    """Duas perguntas, e a segunda existe porque **a conta pode ter mudado**:
    entre a leitura do QR e o toque em EMITIR ela acrescentou produtos, tirou
    outros, deu um desconto — e o açaí que servia o voucher pode já lá não
    estar."""
    assert aplicado["doVoucher"] == [
        {"ligacao_id": "lig-1"}, {"ligacao_id": "lig-1"}], aplicado["doVoucher"]


def test_com_recompensa_e_nada_que_sirva_o_cartao_MANDA_acrescentar_o_produto(sem_produto):
    assert _SEM_PRODUTO in sem_produto["noCartao"], sem_produto["noCartao"]
    # E a venda segue na mesma: isto é um recado, não um travão.
    assert "Total € 12,79" in sem_produto["ecra"], sem_produto["ecra"][:600]
    assert sem_produto["emitirVivo"] is True
    assert sem_produto["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], sem_produto["corpos"][0]


def test_a_ponte_das_categorias_a_falhar_GRITA_no_cartao(sem_casar):
    """**A segunda regra de ouro, e a única que se pode perder em silêncio.**
    Sem desconto está certo — nunca um desconto errado. Calado é que não pode
    ficar: uma categoria por preencher no backoffice apagava a recompensa de
    todos os clientes sem ninguém perceber porquê, e o sintoma seria «a app não
    funciona»."""
    assert _SEM_CASAR in sem_casar["noCartao"], sem_casar["noCartao"]
    assert sem_casar["emitirVivo"] is True
    assert sem_casar["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], sem_casar["corpos"][0]


def test_os_QUATRO_estados_dizem_coisas_DIFERENTES(
        sem_voucher, aplicado, sem_produto, sem_casar):
    """A afirmação que apanha as três saídas de uma vez: um cartão que deixe de
    ler a resposta, uma frase copiada para as três, ou o ramo do voucher
    apagado do JSX dão todos o MESMO texto quatro vezes."""
    lidos = [sem_voucher["noCartao"], aplicado["noCartao"],
             sem_produto["noCartao"], sem_casar["noCartao"]]
    assert len(set(lidos)) == 4, lidos


# --- O «Remover» desfaz as DUAS coisas ---------------------------------------


@pytest.fixture(scope="module")
def removido(tmp_path_factory):
    """Com o desconto já aplicado, a operadora tira o cliente da fatura."""
    return _montar(_CONTA, "() => ({ data: %s })" % json.dumps(
        _VOUCHER_APLICADO, ensure_ascii=False), "\n".join([
            "const comDesconto = textoVisivel(alvo);",
            # A resposta ao «Remover»: a conta volta inteira, sem desconto
            # nenhum — é o que o servidor devolve depois de libertar o voucher.
            "respostaDoVoucher = () => ({ data: { venda: CONTA } });",
            "await carregar_em('Remover');",
            "const depois = textoVisivel(alvo);",
            "const noCartao = cartao();",
            "const guardada = lib.lerPontosDaConta('v-1');",
            # O outro lado do travão de repartir: com o servidor a CONFIRMAR que
            # o voucher saiu, os botões têm de voltar à vida. Um travão que
            # nunca se abre é uma conta que ninguém consegue dividir.
            "const dividirDepois = !!botao('Dividir Conta');",
            _COM_DINHEIRO,
            "process.stdout.write(JSON.stringify({ comDesconto, depois, noCartao,",
            "  guardada, dividirDepois, emitirVivo, corpos, doVoucher }));",
        ]), tmp_path_factory, "voucher-removido")


def test_o_Remover_tira_o_cliente_E_liberta_o_voucher(removido):
    """**As duas coisas, ou nenhuma.** Tirar o cliente e deixar o voucher preso
    até à meia-noite era o pior dos dois mundos: o cliente ficava sem desconto
    E sem recompensa, com os pontos já gastos.

    O `ligacao_id: null` é o pedido que liberta — e é o mesmo que tira o
    desconto da linha, por isso a conta volta inteira no mesmo passo."""
    assert removido["noCartao"] is None, removido["depois"][:600]
    assert removido["guardada"] is None
    assert removido["doVoucher"][1] == {"ligacao_id": None}, removido["doVoucher"]


def test_depois_do_Remover_o_total_volta_a_ser_o_da_conta_inteira(removido):
    """Sem isto, o desconto ficava no ecrã depois de o cliente sair da fatura —
    e a fatura saía 8,99 € abaixo do que a conta vale, com o voucher devolvido
    ao cliente."""
    assert "Total € 3,80" in removido["comDesconto"], removido["comDesconto"][:600]
    assert "Total € 12,79" in removido["depois"], removido["depois"][:600]
    assert removido["emitirVivo"] is True
    assert removido["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], removido["corpos"][0]
    assert removido["corpos"][0]["pontos_ligacao"] is None, removido["corpos"][0]


# --- A regra de ouro: nada disto impede uma fatura de sair --------------------


@pytest.fixture(scope="module")
def app_em_baixo(tmp_path_factory):
    """A rota do voucher em baixo (503), nas DUAS chamadas — a da ligação e a
    do EMITIR."""
    return _montar(_CONTA, "falha(503, 'A app não respondeu.')", "\n".join([
        "const noCartao = cartao();",
        "const ecra = textoVisivel(alvo);",
        _COM_DINHEIRO,
        "process.stdout.write(JSON.stringify({ noCartao, ecra, emitirVivo, corpos }));",
    ]), tmp_path_factory, "voucher-em-baixo")


def test_com_a_app_em_baixo_a_venda_segue_NORMAL_e_o_EMITIR_nao_fica_preso(app_em_baixo):
    """**A regra de ouro da integração, escrita e inegociável.** App em baixo,
    tecto de espera esgotado ou resposta estranha = venda normal, sem desconto.

    Um `throw` que subisse desta chamada matava o EMITIR de uma venda que não
    tem nada a ver com fidelidade nenhuma — e o balcão parava por causa de uma
    coisa que não é fiscal."""
    assert "Pontos para: Ana ✓" in app_em_baixo["noCartao"], app_em_baixo["noCartao"]
    assert "grátis" not in app_em_baixo["noCartao"], app_em_baixo["noCartao"]
    assert "Total € 12,79" in app_em_baixo["ecra"], app_em_baixo["ecra"][:600]
    assert app_em_baixo["emitirVivo"] is True
    assert len(app_em_baixo["corpos"]) == 1, app_em_baixo["corpos"]
    assert app_em_baixo["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], app_em_baixo["corpos"][0]
    # E os PONTOS seguem à mesma: o voucher falhou, o cliente não.
    assert app_em_baixo["corpos"][0]["pontos_ligacao"] == {
        "id": "lig-1", "primeiro_nome": "Ana"}, app_em_baixo["corpos"][0]


# --- A conta a 0,00 € ---------------------------------------------------------


@pytest.fixture(scope="module")
def a_zero(tmp_path_factory):
    """Um açaí, oferecido: 0,00 €. **Sem escolher pagamento nenhum** — a zero
    não há dinheiro a repartir, e o servidor recusa `valor: 0`."""
    aplicado_a_zero = dict(_VOUCHER_APLICADO, venda=_A_ZERO)
    return _montar(_A_ZERO, "() => ({ data: %s })" % json.dumps(
        aplicado_a_zero, ensure_ascii=False), "\n".join([
            "const ecra = textoVisivel(alvo);",
            # Vivo ANTES de se escolher pagamento nenhum — a zero não há nada a
            # repartir. E a seguir toca-se em «Dinheiro», que é o gesto que ela
            # faz todos os dias sem pensar: o EMITIR tem de continuar vivo e o
            # pagamento de 0,00 € NÃO pode viajar.
            "const vivoSemPagamento = !!botao('EMITIR DOCUMENTO');",
            "await carregar_em('Dinheiro');",
            _EMITIR,
            "process.stdout.write(JSON.stringify({ ecra, vivoSemPagamento,",
            "  emitirVivo, corpos }));",
        ]), tmp_path_factory, "voucher-a-zero")


@pytest.fixture(scope="module")
def a_zero_sem_marca(tmp_path_factory):
    """O MESMO zero, com um desconto manual de 100 % em vez da recompensa: a
    linha não tem `voucher_id`."""
    return _montar(_A_ZERO_SEM_MARCA, "() => ({ data: {} })", "\n".join([
        "const ecra = textoVisivel(alvo);",
        "const emitirVivo = !!botao('EMITIR DOCUMENTO');",
        "process.stdout.write(JSON.stringify({ ecra, emitirVivo }));",
    ]), tmp_path_factory, "voucher-a-zero-sem-marca")


def test_a_conta_a_ZERO_com_recompensa_emite_sem_pagamento_nenhum(a_zero):
    """**A decisão 3 do dono:** a conta pode ficar a 0,00 € e a Fatura
    Simplificada sai à mesma — zero euros, zero pontos. (A app já o faz: a FS
    06P2026/1081 saiu a 0,00 € com 100 % de desconto numa linha.)

    E sai **sem pagamentos**: o servidor recusa `valor: 0`
    (`fiscal.py::PagamentoEntrada`) e a soma de zero pagamentos é 0, que é
    exactamente o total."""
    assert "Total € 0,00" in a_zero["ecra"], a_zero["ecra"][:600]
    assert a_zero["vivoSemPagamento"] is True, a_zero["ecra"][:600]
    assert a_zero["emitirVivo"] is True, a_zero["ecra"][:600]
    assert len(a_zero["corpos"]) == 1, a_zero["corpos"]
    # **Mesmo com «Dinheiro» escolhido.** Ela toca nele por hábito, e o que
    # nasce é um pagamento de 0,00 € — que o servidor recusa com 422. A lista
    # vai vazia à mesma.
    assert a_zero["corpos"][0]["pagamentos"] == [], a_zero["corpos"][0]


def test_a_conta_a_zero_DIZ_porque_e_que_nao_ha_nada_a_cobrar(a_zero):
    """Um EMITIR aceso sem se escolher pagamento nenhum é o contrário do que
    ela faz todos os dias. Sem uma frase, fica a tocar nos tipos de pagamento à
    procura do passo que falta, com o cliente à frente."""
    assert "não há nada a cobrar" in a_zero["ecra"], a_zero["ecra"][:600]


def test_um_zero_SEM_a_marca_do_voucher_continua_a_ser_RECUSADO(a_zero_sem_marca):
    """**O travão, e a razão de ele não se abrir para toda a gente.** Um
    desconto manual de 100 % não pede PIN a ninguém: se o zero passasse sem a
    marca `voucher_id`, qualquer pessoa ao balcão emitia Faturas Simplificadas
    reais a 0,00 € sem ter trocado pontos nenhuns.

    O servidor faz o MESMO travão (`fiscal.py::finalizar`) — este ecrã só não o
    pode convidar a recusar com o cliente à frente."""
    assert a_zero_sem_marca["emitirVivo"] is False, a_zero_sem_marca["ecra"][:600]
    assert "O total tem de ser positivo para emitir" in a_zero_sem_marca["ecra"], \
        a_zero_sem_marca["ecra"][:600]
    # E não promete recompensa nenhuma: o desconto é da funcionária, não da
    # fidelidade, e um ecrã a dizer o contrário sobre uma conta a 0,00 € era a
    # frase que fazia o gestor procurar pontos que ninguém gastou.
    assert "recompensa" not in a_zero_sem_marca["ecra"], a_zero_sem_marca["ecra"][:600]


# --- A conta mudou entre a leitura e o EMITIR ---------------------------------


@pytest.fixture(scope="module")
def mudou_no_emitir(tmp_path_factory):
    """O desconto entra ao ler o QR e, no toque em EMITIR, a app diz que já não
    há voucher nenhum (a conta mudou, ou o voucher foi usado noutro sítio)."""
    return _montar(_CONTA, "() => ({ data: %s })" % json.dumps(
        _VOUCHER_APLICADO, ensure_ascii=False), "\n".join([
            "await carregar_em('Dinheiro');",
            "const antes = textoVisivel(alvo);",
            "respostaDoVoucher = () => ({ data: { venda: CONTA } });",
            "await carregar_em('EMITIR DOCUMENTO');",
            "await act(async () => {});",
            "await act(async () => {});",
            "const depois = textoVisivel(alvo);",
            "const noCartao = cartao();",
            "const corposDoPrimeiro = pedidos.filter(",
            "  (p) => p.url.endsWith('/pos/venda/v-1/finalizar')).map((p) => p.corpo);",
            # Ela lê o que mudou e carrega outra vez — e agora sai.
            _EMITIR,
            "process.stdout.write(JSON.stringify({ antes, depois, noCartao,",
            "  corposDoPrimeiro, emitirVivo, corpos }));",
        ]), tmp_path_factory, "voucher-mudou")


def test_se_a_recompensa_MUDOU_no_EMITIR_o_ecra_nao_emite_as_cegas(mudou_no_emitir):
    """A conta que o ecrã mostrava deixou de ser a conta que vai ser cobrada.
    Emitir aqui às cegas dava um 422 do servidor («os pagamentos não somam o
    total») com um painel vermelho e nenhuma explicação — e, com o pagamento
    escrito à mão, a operadora ficava a olhar para dois números que não batem
    sem saber qual deles mudou."""
    assert mudou_no_emitir["corposDoPrimeiro"] == [], mudou_no_emitir["corposDoPrimeiro"]
    assert "Total € 3,80" in mudou_no_emitir["antes"], mudou_no_emitir["antes"][:600]
    assert "Total € 12,79" in mudou_no_emitir["depois"], mudou_no_emitir["depois"][:600]
    assert "grátis" not in mudou_no_emitir["noCartao"], mudou_no_emitir["noCartao"]


def test_e_o_toque_SEGUINTE_emite_com_a_conta_certa(mudou_no_emitir):
    """Não é um beco: ela lê o cartão, vê o total novo, e carrega outra vez."""
    assert mudou_no_emitir["emitirVivo"] is True
    assert len(mudou_no_emitir["corpos"]) == 1, mudou_no_emitir["corpos"]
    assert mudou_no_emitir["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 12.79}], mudou_no_emitir["corpos"][0]


def test_uma_conta_com_recompensa_NAO_se_reparte_e_diz_porque(aplicado):
    """**Fase 1, escrita no desenho:** a ligação vive na gaveta presa ao id
    desta conta e já hoje não passa para as partes. Repartida, o desconto
    ficava na conta-mãe que ninguém vai cobrar e o voucher preso até à
    meia-noite — o cliente sem desconto E sem recompensa, com os pontos já
    gastos.

    A razão vive encostada aos botões que ela está a tentar carregar, como o
    `motivoBloqueio` do EMITIR: não há forma de os desligar em silêncio."""
    assert aplicado["dividirVivo"] is False, aplicado["ecra"][:600]
    assert aplicado["separarVivo"] is False, aplicado["ecra"][:600]
    assert "não se pode repartir" in aplicado["ecra"], aplicado["ecra"][:600]
    # **E diz onde está o trinco, não só o gesto.** «Retire o cliente» sozinho
    # mandava-a para um botão que responde 422: o «Remover» limpa o cartão num
    # instante, mas quem tira a marca da linha é o servidor.
    assert "só destrancam quando o desconto sair do total" in aplicado["ecra"], \
        aplicado["ecra"][:600]


# --- Os três defeitos que a revisão adversarial encontrou ---------------------
#
# As duas suites estavam VERDES por cima de um contrato partido: cada lado
# provava o seu contra um BONECO do outro. Estes três cenários são os que
# nenhuma das duas fazia — e os três são sobre a MESMA coisa, que é o ecrã e o
# servidor não fazerem a mesma pergunta sobre a mesma conta.


@pytest.fixture(scope="module")
def marca_orfa_a_zero(tmp_path_factory):
    """A operadora editou a linha (o desconto da recompensa foi-se, a MARCA
    ficou) e deu um desconto global de 100 %. A conta está a 0,00 € por mão
    dela, com uma marca órfã na linha."""
    return _montar(_A_ZERO_MARCA_ORFA, "() => ({ data: {} })", "\n".join([
        "const ecra = textoVisivel(alvo);",
        "const emitirVivo = !!botao('EMITIR DOCUMENTO');",
        "const dividirVivo = !!botao('Dividir Conta');",
        "process.stdout.write(JSON.stringify({ ecra, emitirVivo, dividirVivo }));",
    ]), tmp_path_factory, "voucher-marca-orfa")


def test_uma_MARCA_ORFA_nao_abre_o_travao_do_zero_e_o_ecra_diz_a_VERDADE(marca_orfa_a_zero):
    """**O ecrã e o servidor faziam perguntas DIFERENTES sobre a mesma conta.**

    O servidor exige a marca **E** o desconto (`fiscal.py::_tem_linha_de_voucher`);
    o ecrã contentava-se com a marca. A rota de editar linha aceita `desconto_eur`
    e não conhece o `voucher_id`, por isso limpar o desconto deixa a marca para
    trás — e com um desconto global de 100 % por cima o ecrã dizia «não há nada a
    cobrar», acendia o EMITIR e mandava a lista de pagamentos VAZIA. O servidor
    respondia 422 a falar de recompensas sobre um desconto que ela deu de cabeça.

    Falha segura, e ainda assim o pior sítio para ela cair: um beco sem saída com
    o cliente à frente e o ecrã a garantir-lhe que estava tudo bem. Agora faz a
    MESMA pergunta, e a razão que ela lê é a do desconto que ela deu."""
    assert marca_orfa_a_zero["emitirVivo"] is False, marca_orfa_a_zero["ecra"][:800]
    assert "O total tem de ser positivo para emitir" in marca_orfa_a_zero["ecra"], \
        marca_orfa_a_zero["ecra"][:800]
    # E NÃO a frase da conta oferecida: prometer «não há nada a cobrar» sobre uma
    # conta que o servidor recusa é a mentira que fazia o beco.
    assert "não há nada a cobrar" not in marca_orfa_a_zero["ecra"], \
        marca_orfa_a_zero["ecra"][:800]
    assert "recompensa L'Açaí — não há" not in marca_orfa_a_zero["ecra"], \
        marca_orfa_a_zero["ecra"][:800]


@pytest.fixture(scope="module")
def app_em_baixo_no_emitir(tmp_path_factory):
    """O desconto entrou ao ler o QR e, no toque em EMITIR, a rota do POS
    responde 200 com tudo a `null` e `app_indisponivel: true` — a app não
    respondeu, e a conta continua descontada do lado do servidor.

    A emissão fica PENDENTE de propósito: é a única forma de olhar para o cartão
    no instante em que isto acontece, em vez de olhar para o documento emitido
    que o substitui."""
    return _montar(_CONTA, "() => ({ data: %s })" % json.dumps(
        _VOUCHER_APLICADO, ensure_ascii=False), "\n".join([
            # O `sonner` do banco de ensaio engole os avisos. Aqui o aviso É o
            # defeito: a frase que não pode ser dita.
            "const avisos = [];",
            "sonner.toast.warning = (m) => { avisos.push(String(m)); };",
            "await carregar_em('Dinheiro');",
            "const antes = cartao();",
            "respostaDoVoucher = () => ({ data: %s });" % json.dumps(
                _APP_INDISPONIVEL, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => new Promise(() => {});",
            "await carregar_em('EMITIR DOCUMENTO');",
            "await act(async () => {});",
            "await act(async () => {});",
            "const noCartao = cartao();",
            "const ecra = textoVisivel(alvo);",
            "const corpos = pedidos.filter((p) => p.url.endsWith('/pos/venda/v-1/finalizar'))",
            "  .map((p) => p.corpo);",
            "process.stdout.write(JSON.stringify({ antes, noCartao, ecra, avisos, corpos }));",
        ]), tmp_path_factory, "voucher-app-em-baixo-no-emitir")


def test_a_app_em_baixo_no_EMITIR_nao_apaga_o_cartao_nem_PRENDE_a_fatura(app_em_baixo_no_emitir):
    """**A regra de ouro 1, pela porta dos fundos.** A rota do POS não devolve
    erro quando a app não responde: devolve 200 com tudo a `null`, porque nada
    disto pode impedir uma fatura de sair. O ecrã lia essas chaves a `null` como
    «este cliente não tem recompensa nenhuma» e fazia as duas coisas erradas de
    uma vez:

     · apagava do cartão a linha «Açaí Médio grátis» com o desconto **ainda
       gravado na conta** — o total em baixo continuava descontado, e ninguém
       sabia porquê;
     · e recusava o EMITIR com «A recompensa desta conta mudou», que é FALSO:
       não mudou nada, a app é que não respondeu.

    Um `catch` e este 200 são a mesma coisa, e tratam-se da mesma maneira."""
    assert _APLICADO in app_em_baixo_no_emitir["antes"], app_em_baixo_no_emitir["antes"]
    # O cartão não se apaga: a recompensa continua escrita onde ela está a olhar.
    assert _APLICADO in app_em_baixo_no_emitir["noCartao"], \
        app_em_baixo_no_emitir["noCartao"]
    # E o total continua a ser o que o servidor tem gravado.
    assert "Total € 3,80" in app_em_baixo_no_emitir["ecra"], \
        app_em_baixo_no_emitir["ecra"][:800]
    # **A fatura SAI.** Um pedido de emissão, com o total certo.
    assert len(app_em_baixo_no_emitir["corpos"]) == 1, app_em_baixo_no_emitir["corpos"]
    assert app_em_baixo_no_emitir["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 3.8}], app_em_baixo_no_emitir["corpos"][0]
    # E a frase falsa não é dita a ninguém.
    assert app_em_baixo_no_emitir["avisos"] == [], app_em_baixo_no_emitir["avisos"]


@pytest.fixture(scope="module")
def removido_com_a_app_em_baixo(tmp_path_factory):
    """Com o desconto aplicado, a operadora toca em «Remover» — e o pedido que
    liberta o voucher NÃO CHEGA a confirmar: rede da loja a piscar, o backend a
    reiniciar, ou uma das guardas da rota a recusar. Do lado do servidor a marca
    e o desconto continuam na linha, e é isso que decide tudo o que se afirma."""
    return _montar(_CONTA, "() => ({ data: %s })" % json.dumps(
        _VOUCHER_APLICADO, ensure_ascii=False), "\n".join([
            "respostaDoVoucher = falha(503, 'Servidor indisponível.');",
            "await carregar_em('Remover');",
            "const depois = textoVisivel(alvo);",
            "const noCartao = cartao();",
            "const dividirVivo = !!botao('Dividir Conta');",
            "const separarVivo = !!botao('Separar Conta');",
            _COM_DINHEIRO,
            "process.stdout.write(JSON.stringify({ depois, noCartao, dividirVivo,",
            "  separarVivo, emitirVivo, corpos }));",
        ]), tmp_path_factory, "voucher-removido-app-em-baixo")


def test_depois_do_Remover_o_Dividir_NAO_destranca_por_estado_velho(
        removido_com_a_app_em_baixo, removido):
    """**O defeito do dinheiro.** O «Remover» atirava fora a única cópia da
    conta que tinha visto o desconto e o ecrã voltava ao prop da venda — que
    nunca o viu — no instante ANTES de o servidor ter libertado coisa nenhuma.

    O `haLinhaDeVoucher` passava a falso e o **Dividir destrancava**, com a marca
    ainda gravada nas linhas: dividir copia-a para cada parte, e cada parte
    emitia uma Fatura Simplificada real a 0,00 €. O servidor recusa repartir uma
    conta com voucher (Fase 1), por isso o ecrã estava a convidar ao 422 — e, no
    caminho em que o 422 não chegasse primeiro, a uma conta inteira oferecida.

    E o total: com o pedido a falhar, o ecrã mostrava 12,79 € sobre uma conta que
    o servidor tem a 3,80 €. O EMITIR mandava pagamentos que não somam o total.
    Agora quem manda na conta é sempre o servidor: a conta fica como ele a tem
    até ele dizer o contrário — e quando o disser (fixture `removido`), os botões
    destrancam."""
    assert removido_com_a_app_em_baixo["dividirVivo"] is False, \
        removido_com_a_app_em_baixo["depois"][:800]
    assert removido_com_a_app_em_baixo["separarVivo"] is False, \
        removido_com_a_app_em_baixo["depois"][:800]
    assert "não se pode repartir" in removido_com_a_app_em_baixo["depois"], \
        removido_com_a_app_em_baixo["depois"][:800]
    # O cliente saiu do cartão — isso é da operadora e a fila é dela.
    assert removido_com_a_app_em_baixo["noCartao"] is None, \
        removido_com_a_app_em_baixo["depois"][:800]
    # **A conta continua a ser a que o servidor tem**, e é essa que se cobra: a
    # fatura sai, e a soma bate certo.
    assert "Total € 3,80" in removido_com_a_app_em_baixo["depois"], \
        removido_com_a_app_em_baixo["depois"][:800]
    assert removido_com_a_app_em_baixo["emitirVivo"] is True
    assert removido_com_a_app_em_baixo["corpos"][0]["pagamentos"] == [
        {"tipo_pagamento_id": "tp-1", "valor": 3.8}], \
        removido_com_a_app_em_baixo["corpos"][0]
    # E o travão ABRE quando o servidor confirma que o voucher saiu — senão era
    # uma conta que ninguém consegue dividir.
    assert removido["dividirDepois"] is True, removido["depois"][:800]
