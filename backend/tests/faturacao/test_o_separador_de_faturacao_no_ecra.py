"""O separador **Faturação** — **executado**, não lido.

Os ecrãs do POS desenham-se sem servidor nenhum: dois defeitos foram a
produção exactamente assim, e um deles teve o POS inteiramente morto com a
suite verde. Por isso nada aqui é textual.

Três níveis, e nenhum deles procura palavras num ficheiro:

1. as DECISÕES vivem em `lib/pos.js` e correm-se em **Node**, extraídas do
   ficheiro (nunca uma cópia escrita aqui — uma cópia fica verde com o ecrã
   errado, que é a forma de falhar que isto existe para apanhar);
2. o SEPARADOR é montado em React, num DOM (jsdom), com o servidor fabricado
   à frente do axios do `lib/pos` — o caminho todo é o verdadeiro: o toque no
   botão, o `useEffect`, o pedido, a resposta a chegar à lista;
3. e o que se afirma é o que a OPERADORA LÊ (`textoVisivel`), não o
   `textContent`: uma classe de estilo (`hidden`, `sr-only`) apagou uma faixa
   inteira deste módulo com 1478 testes verdes.

**O que o preâmbulo partilhado (de `test_a_faixa_do_modo_no_ecra.py`) faz de
diferente aqui.** Lá, toda a biblioteca de UI entra como marcas vazias, e
isso chega — a faixa do modo desenha-se sozinha. Aqui não: o painel só abre
depois de alguém CARREGAR no botão «Faturação», e um `<Button>` sem `onClick`
nunca abre nada. Por isso o cenário põe em `global.__componentes` uma
biblioteca mínima que responde ao dedo: um `<button>` a sério (com o
`disabled`, que é meia prova do «Copiar para a venda» morto), um `<input>` a
sério (a pesquisa), e um `Dialog` que só desenha o conteúdo quando `open`.
Um `Dialog` que desenhasse sempre punha estes guardas a medir um painel que
ninguém abriu.

**O que este ficheiro NÃO cobre, dito com todas as letras.** O que se vê
mede-se com a folha de estilo à mão do preâmbulo (`hidden`, `flex`,
`invisible`, `sr-only`). Esconder alguma coisa por outro caminho (largura
zero, `opacity-0`, mandá-la para fora do ecrã) passa por aqui sem acordar
ninguém. E o `disabled` de um botão prova-se pelo atributo, não pelo pixel.
"""
import json
from pathlib import Path

import pytest

from .test_arredondamento_do_ecra import (
    _LIB_POS,
    _corpo_da_funcao,
    _corpo_da_seta,
    _ler,
)
# O preâmbulo de montagem (jsdom + babel + o servidor fabricado + o
# `textoVisivel`) vem de lá inteiro, e NÃO copiado: é o mesmo carregador, e uma
# segunda cópia divergia da primeira no dia em que uma delas fosse corrigida.
from .test_a_faixa_do_modo_no_ecra import _correr_no_node, _montar_no_node

_ASSINATURA_SEM_ACENTOS = "export const semAcentosPos = (texto) =>"
# Sem a chaveta final, e é de propósito: `_corpo_da_funcao` procura a
# abertura do corpo A PARTIR do fim da assinatura, e uma assinatura que já
# a inclua fá-lo apanhar a chaveta SEGUINTE — a do objecto de opções do
# `toLocaleString` — e devolver meia função, que o node recusa com um
# `SyntaxError`. Falhou assim à primeira, em todos os sete extractos.
_ASSINATURA_NUMERO = "export const numeroPos = (valor) =>"
_ASSINATURA_EUROS = "export const eurosPos = (valor) =>"
_ASSINATURA_MOMENTO = "export const momentoDaFaturaPos = (iso, agora) =>"
_ASSINATURA_RESUMO = "export const resumoDosArtigosPos = (documento) =>"
_ASSINATURA_PESQUISA = "export const casaComAPesquisaPos = (documento, texto) =>"
_ASSINATURA_COPIAR = "export const razaoDeNaoCopiar = ({ contaEmCurso, documento }) =>"


def _decisao_solta() -> str:
    """As decisões do separador, extraídas do `lib/pos.js` e prontas a correr
    como um guião solto (sem `export`, sem `import`)."""
    lib = _ler(_LIB_POS)
    pedacos = [
        _corpo_da_seta(lib, _ASSINATURA_SEM_ACENTOS, _LIB_POS),
        _corpo_da_seta(lib, _ASSINATURA_EUROS, _LIB_POS),
        _corpo_da_funcao(lib, _ASSINATURA_NUMERO, _LIB_POS),
        _corpo_da_funcao(lib, _ASSINATURA_MOMENTO, _LIB_POS),
        _corpo_da_funcao(lib, _ASSINATURA_RESUMO, _LIB_POS),
        _corpo_da_funcao(lib, _ASSINATURA_PESQUISA, _LIB_POS),
        _corpo_da_funcao(lib, _ASSINATURA_COPIAR, _LIB_POS),
    ]
    return "\n".join(p.replace("export ", "", 1) for p in pedacos)


def _correr(expressao: str, tmp_path: Path, nome: str):
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "process.stdout.write(JSON.stringify(%s));" % expressao,
        ]),
        tmp_path, nome,
    )


# --- Nível 1: a hora que a operadora lê --------------------------------------
#
# «O cliente voltou amanhã» é o caso que o dono nomeou. Sem a data, duas
# faturas das 21:41 de dois dias diferentes lêem-se iguais na mesma lista, e
# não há forma de saber qual é a dele.

_AGORA = "2026-08-22T15:00:00"


@pytest.mark.parametrize(
    "iso,esperado",
    [
        # Hoje: só a hora — é o caso da esmagadora maioria e o que cabe.
        ("2026-08-22T11:12:00", "11:12"),
        ("2026-08-22T00:05:00", "00:05"),
        ("2026-08-22T23:59:00", "23:59"),
        # Ontem: dito por extenso, que é como se fala ao balcão.
        ("2026-08-21T21:41:00", "Ontem 21:41"),
        ("2026-08-21T00:01:00", "Ontem 00:01"),
        # Mais atrás: com a data.
        ("2026-08-19T18:00:00", "19/08 18:00"),
        ("2026-07-31T09:30:00", "31/07 09:30"),
    ],
)
def test_a_hora_de_hoje_e_a_de_ontem_lem_se_diferentes(tmp_path, iso, esperado):
    assert _correr(
        "momentoDaFaturaPos(%s, new Date(%s))" % (json.dumps(iso), json.dumps(_AGORA)),
        tmp_path, "momento.js",
    ) == esperado


@pytest.mark.parametrize("iso", [None, "", "não é uma data", 0, [], {}])
def test_uma_data_ilegivel_da_um_traco_e_nao_rebenta_a_lista(tmp_path, iso):
    """Uma fatura com o `emitido_em` estragado não pode levar a lista inteira
    atrás dela — o que a operadora precisa (o número, o total, os artigos)
    continua lá."""
    assert _correr(
        "momentoDaFaturaPos(%s, new Date(%s))" % (json.dumps(iso), json.dumps(_AGORA)),
        tmp_path, "momento-mau.js",
    ) == "—"


# --- Nível 1b: o que o cliente levou -----------------------------------------


def test_o_resumo_diz_o_que_ele_levou(tmp_path):
    documento = {"artigos": [{"nome": "Açaí Regular", "quantidade": 1},
                             {"nome": "Coca-Cola", "quantidade": 2}],
                 "mais_artigos": 0}
    assert _correr("resumoDosArtigosPos(%s)" % json.dumps(documento),
                   tmp_path, "resumo.js") == "1× Açaí Regular · 2× Coca-Cola"


def test_o_resumo_conta_os_que_nao_couberam(tmp_path):
    documento = {"artigos": [{"nome": "Açaí Regular", "quantidade": 1}],
                 "mais_artigos": 3}
    assert _correr("resumoDosArtigosPos(%s)" % json.dumps(documento),
                   tmp_path, "resumo-mais.js") == "1× Açaí Regular +3"


def test_uma_quantidade_fraccionaria_nao_vira_um_numero_inteiro(tmp_path):
    """A parte de uma conta dividida é 0.3337 de um açaí. Arredondá-la a `0`
    fazia a linha dizer «0× Açaí Regular», e a operadora concluía que a fatura
    não era daquele cliente."""
    documento = {"artigos": [{"nome": "Açaí Regular", "quantidade": 0.3337}],
                 "mais_artigos": 0}
    assert _correr("resumoDosArtigosPos(%s)" % json.dumps(documento),
                   tmp_path, "resumo-fraccao.js") == "0.33× Açaí Regular"


# --- Nível 1c: a pesquisa ----------------------------------------------------
#
# Ao balcão escreve-se "acai" e o produto chama-se "Açaí". Uma pesquisa que só
# casasse a acentuação exacta era uma pesquisa que nunca encontrava nada com
# pressa em cima.

_DOC_DA_PESQUISA = {
    "numero": "FS 05P2026/1824", "atcud": "JFT7-1824", "total": 11.64,
    "artigos": [{"nome": "Açaí Regular", "quantidade": 1}],
    "pagamentos": [{"nome": "Multibanco", "valor": 11.64}],
}


@pytest.mark.parametrize(
    "procura,casa",
    [
        ("", True),          # sem pesquisa, está tudo na lista
        ("   ", True),
        ("1824", True),      # o número que vem escrito no talão rasgado
        ("fs 05p", True),    # em minúsculas
        ("JFT7", True),      # o código AT
        ("acai", True),      # SEM acento — é assim que se escreve ao balcão
        ("AÇAÍ", True),      # e com acento também
        ("11,64", True),     # «paguei onze e sessenta e quatro»
        ("11.64", True),     # com ponto, que é o que sai de um teclado numérico
        ("multibanco", True),
        ("1825", False),
        ("morango", False),
    ],
)
def test_a_pesquisa_encontra_pelo_numero_pelo_valor_e_pelo_artigo(tmp_path, procura, casa):
    assert _correr(
        "casaComAPesquisaPos(%s, %s)" % (json.dumps(_DOC_DA_PESQUISA), json.dumps(procura)),
        tmp_path, "pesquisa.js",
    ) is casa


# --- Nível 1d: porque é que «Copiar para a venda» está morto ------------------


def test_com_uma_conta_no_posto_a_copia_esta_morta_e_diz_o_que_fazer(tmp_path):
    """**Um PC atende UM cliente de cada vez.** Quem recusa é o servidor (409);
    isto é o ecrã a dizê-lo ANTES do toque, e a frase tem de nomear a saída —
    cobrar ou cancelar a conta que está à frente."""
    razao = _correr(
        "razaoDeNaoCopiar({ contaEmCurso: { id: 'v-1' }, documento: "
        "{ tem_venda: true, linhas: [{}] } })",
        tmp_path, "copiar-ocupado.js",
    )
    assert razao is not None
    assert "um cliente de cada vez" in razao
    assert "cobre-a ou cancele-a" in razao


def test_sem_conta_no_posto_a_copia_esta_viva(tmp_path):
    assert _correr(
        "razaoDeNaoCopiar({ contaEmCurso: null, documento: "
        "{ tem_venda: true, linhas: [{}] } })",
        tmp_path, "copiar-livre.js",
    ) is None


def test_uma_fatura_sem_conta_de_origem_nao_se_copia(tmp_path):
    razao = _correr(
        "razaoDeNaoCopiar({ contaEmCurso: null, documento: "
        "{ tem_venda: false, linhas: [] } })",
        tmp_path, "copiar-orfa.js",
    )
    assert razao is not None
    assert "não há linhas para copiar" in razao


# --- Nível 2: o SEPARADOR montado, e o que a operadora LÊ ---------------------

# A biblioteca de UI mínima que responde ao dedo. Ver a docstring do módulo:
# sem ela o painel nunca abre, porque um `<Button>` sem `onClick` não abre
# nada, e um `Dialog` que desenhe sempre punha isto a medir um painel que
# ninguém abriu.
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled,",
    "  className: props.className, type: 'button',",
    "  'data-desligado': props.disabled ? 'sim' : 'nao',",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "  className: props.className,",
    "});",
    "const Caixa = (props) => (props.open",
    "  ? React.createElement('div', { 'data-dialogo': 'aberto' }, props.children)",
    "  : null);",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  if (nome === 'Dialog') return Caixa;",
    "  return Div;",
    "} });",
])


def _documento(**over):
    d = {
        "id": "doc-1", "numero": "FS 05P2026/1824", "atcud": "JFT7-1824",
        "emitido_em": "2026-08-22T11:12:00", "total": 11.64, "tipo": "FS",
        "modo": "normal", "mais_artigos": 0, "tem_venda": True,
        "artigos": [{"nome": "Açaí Regular", "quantidade": 1},
                    {"nome": "Coca-Cola", "quantidade": 1}],
        "pagamentos": [{"nome": "Multibanco", "valor": 11.64}],
    }
    d.update(over)
    return d


def _fatura(**over):
    f = {
        "id": "doc-1", "numero": "FS 05P2026/1824", "atcud": "JFT7-1824",
        "tipo": "FS", "modo": "normal", "emitido_em": "2026-08-22T11:12:00",
        "cliente_nif": None, "tem_venda": True, "venda_id": "v-1",
        "linhas": [
            {"titulo": "Açaí Regular (Nutella)", "quantidade": 1,
             "preco_unitario": 10.49, "desconto": 0.0, "total": 10.49},
            {"titulo": "Coca-Cola", "quantidade": 1,
             "preco_unitario": 1.15, "desconto": 0.0, "total": 1.15},
        ],
        "pagamentos": [{"nome": "Multibanco", "valor": 11.64}],
        "mapa_imposto": [
            {"tax_id": "INT", "taxa": 13, "documentos": 1, "base": 9.28,
             "iva": 1.21, "total": 10.49},
            {"tax_id": "NOR", "taxa": 23, "documentos": 1, "base": 0.93,
             "iva": 0.22, "total": 1.15},
        ],
        "totais_imposto": {"base": 10.21, "iva": 1.43, "total": 11.64},
        "total": 11.64, "total_das_linhas": 11.64, "total_divergente": False,
        "tem_talao": False,
    }
    f.update(over)
    return f


def _cenario(*, documentos, fatura, conta_aberta, ha_mais=False, limite=200,
             abrir_fatura=True):
    """Monta o `PosFaturacao` a sério, carrega no botão «Faturação», abre a
    primeira fatura da lista, e devolve o que ficou LEGÍVEL no ecrã em cada
    passo."""
    return "\n".join([
        _COMPONENTES,
        "const PosFaturacao = carregar(path.join(POS, 'PosFaturacao.js')).default;",
        "RESPOSTAS_POS['/pos/documentos'] = () => ({ data: { documentos: %s,"
        " limite: %d, ha_mais: %s } });" % (
            json.dumps(documentos), limite, "true" if ha_mais else "false"),
        "RESPOSTAS_POS['/pos/documentos/doc-1'] = () => ({ data: %s });"
        % json.dumps(fatura),
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(conta_aberta),
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(",
        "    PosFaturacao, { caixa: { id: 'c1', nome: 'Balcão' }, onContaCopiada: () => {} }));",
        "  });",
        "  await act(async () => {});",
        "  const saida = { fechado: textoVisivel(alvo) };",
        "  const abrir = [...alvo.querySelectorAll('button')].find(",
        "    (b) => (b.textContent || '').includes('Faturação'));",
        "  await act(async () => { abrir.click(); });",
        "  await act(async () => {});",
        "  saida.lista = textoVisivel(alvo);",
        "  if (%s) {" % ("true" if abrir_fatura else "false"),
        "    const linha = [...alvo.querySelectorAll('button')].find(",
        "      (b) => (b.textContent || '').includes('FS 05P2026/1824'));",
        "    await act(async () => { linha.click(); });",
        "    await act(async () => {});",
        "    saida.fatura = textoVisivel(alvo);",
        "    const copiar = [...alvo.querySelectorAll('button')].find(",
        "      (b) => (b.textContent || '').includes('Copiar para a venda'));",
        "    saida.copiar_desligado = copiar ? copiar.getAttribute('data-desligado') : 'sem-botao';",
        "    const imprimir = [...alvo.querySelectorAll('button')].find(",
        "      (b) => (b.textContent || '').includes('Imprimir'));",
        "    saida.imprimir_desligado = imprimir ? imprimir.getAttribute('data-desligado') : 'sem-botao';",
        "    const nc = [...alvo.querySelectorAll('button')].find(",
        "      (b) => (b.textContent || '').includes('Nota de Crédito'));",
        "    saida.nc_desligado = nc ? nc.getAttribute('data-desligado') : 'sem-botao';",
        "  }",
        "  saida.pedidos = pedidos.map((p) => p.url);",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])


@pytest.fixture(scope="module")
def ecra_normal(tmp_path_factory):
    return _montar_no_node(
        _cenario(documentos=[_documento()], fatura=_fatura(), conta_aberta=None),
        tmp_path_factory.mktemp("fat"), "faturacao.js")


def test_o_painel_so_abre_depois_de_alguem_CARREGAR(ecra_normal):
    """Antes do toque, o balcão continua a ser o balcão: nem uma linha de
    fatura em ecrã nenhum. É o que faz o resto deste ficheiro medir alguma
    coisa — se o painel estivesse sempre desenhado, todos os guardas a seguir
    ficavam verdes sem que ninguém o tivesse aberto."""
    assert "Faturação" in ecra_normal["fechado"]
    assert "FS 05P2026/1824" not in ecra_normal["fechado"]


def test_a_lista_MOSTRA_o_que_a_operadora_precisa_de_ler(ecra_normal):
    """As quatro coisas com que o cliente volta: o número que traz no talão, o
    total que se lembra de ter pago, o que levou, e como pagou."""
    lista = ecra_normal["lista"]
    assert "FS 05P2026/1824" in lista
    assert "€ 11,64" in lista
    assert "1× Açaí Regular · 1× Coca-Cola" in lista
    assert "Multibanco" in lista
    assert "11:12" in lista


def test_a_lista_pergunta_ao_SERVIDOR_e_nao_inventa_nada(ecra_normal):
    """Um ecrã que desenhasse a lista sem a pedir estava a mostrar faturas que
    não existem. E a conta em curso pergunta-se TAMBÉM — é ela que decide se o
    «Copiar para a venda» está vivo, e uma resposta guardada de há dez minutos
    dizia «o balcão está livre» com um cliente a meio."""
    urls = " ".join(ecra_normal["pedidos"])
    assert "/pos/documentos" in urls
    assert "/pos/venda/aberta" in urls


def test_a_fatura_aberta_MOSTRA_a_tabela_e_o_mapa_de_imposto(ecra_normal):
    fatura = ecra_normal["fatura"]
    assert "FS 05P2026/1824" in fatura
    assert "Açaí Regular (Nutella)" in fatura
    assert "Consumidor Final" in fatura
    assert "JFT7-1824" in fatura
    # O mapa de imposto, e a linha que fecha: 10,21 + 1,43 = 11,64.
    assert "13%" in fatura and "23%" in fatura
    assert "€ 10,21" in fatura and "€ 1,43" in fatura
    assert "€ 11,64" in fatura


def test_a_fatura_aberta_mostra_os_TRES_botoes_e_dois_estao_desligados(ecra_normal):
    """Imprimir e Nota de Crédito ficam à vista e desligados COM A RAZÃO — a
    mesma regra do menu Caixa. Copiar para a venda é o único que funciona
    nesta ronda."""
    fatura = ecra_normal["fatura"]
    assert "Imprimir" in fatura and "Nota de Crédito" in fatura
    assert "Copiar para a venda" in fatura
    assert ecra_normal["imprimir_desligado"] == "sim"
    assert ecra_normal["nc_desligado"] == "sim"
    assert ecra_normal["copiar_desligado"] == "nao"
    assert "agente de impressão" in fatura
    assert "nota de crédito é a ronda seguinte" in fatura


@pytest.fixture(scope="module")
def ecra_com_conta_no_posto(tmp_path_factory):
    return _montar_no_node(
        _cenario(documentos=[_documento()], fatura=_fatura(),
                 conta_aberta={"id": "v-9", "estado": "aberta", "linhas": [{}],
                               "totais": {"total": 8.99}}),
        tmp_path_factory.mktemp("fat-ocupado"), "faturacao-ocupado.js")


def test_com_o_posto_OCUPADO_o_botao_esta_morto_e_a_RAZAO_LE_SE(ecra_com_conta_no_posto):
    """**A prova que mais interessa deste ficheiro.** O ecrã tem de dizer que
    não dá ANTES do toque — e dizê-lo por escrito, não escondido num `title`
    que ninguém abre com pressa em cima.

    Um botão morto sem razão manda a operadora carregar três vezes e chamar o
    gestor; a frase manda-a acabar a conta que tem à frente, que é a saída."""
    assert ecra_com_conta_no_posto["copiar_desligado"] == "sim"
    fatura = ecra_com_conta_no_posto["fatura"]
    assert "Há uma conta por resolver neste posto" in fatura
    assert "um cliente de cada vez" in fatura


@pytest.fixture(scope="module")
def ecra_divergente(tmp_path_factory):
    return _montar_no_node(
        _cenario(
            documentos=[_documento(total=11.63)],
            fatura=_fatura(total=11.63, total_das_linhas=11.64,
                           total_divergente=True),
            conta_aberta=None),
        tmp_path_factory.mktemp("fat-divergente"), "faturacao-divergente.js")


def test_um_total_que_nao_bate_com_as_linhas_GRITA_no_ecra(ecra_divergente):
    """Um cêntimo. Nunca devia acontecer — e é por isso que tem de aparecer:
    se aparecer, aconteceu alguma coisa que ninguém previu, e o ecrã não pode
    escolher um dos dois números em silêncio.

    Os DOIS números têm de estar legíveis: sem eles a faixa diz «não bate» e
    não diz com o quê."""
    fatura = ecra_divergente["fatura"]
    assert "não bate com a soma das linhas" in fatura
    assert "€ 11,63" in fatura
    assert "€ 11,64" in fatura
    assert "sem falar com o gestor" in fatura


@pytest.fixture(scope="module")
def ecra_em_testes(tmp_path_factory):
    return _montar_no_node(
        _cenario(documentos=[_documento(modo="tests")],
                 fatura=_fatura(modo="tests"), conta_aberta=None),
        tmp_path_factory.mktemp("fat-testes"), "faturacao-testes.js")


def test_uma_fatura_de_TESTES_diz_na_lista_e_na_fatura_que_nao_vale_nada(ecra_em_testes):
    """O carimbo é do DOCUMENTO e não do modo de agora: um turno que começou em
    `tests` e a que o gestor mudou o servidor a meio tem documentos dos dois
    tipos na mesma lista."""
    assert "SEM VALOR FISCAL" in ecra_em_testes["lista"]
    assert "Documento SEM VALOR FISCAL" in ecra_em_testes["fatura"]
    assert "Autoridade Tributária" in ecra_em_testes["fatura"]


@pytest.fixture(scope="module")
def ecra_truncado(tmp_path_factory):
    return _montar_no_node(
        _cenario(documentos=[_documento()], fatura=_fatura(), conta_aberta=None,
                 ha_mais=True, limite=200, abrir_fatura=False),
        tmp_path_factory.mktemp("fat-truncado"), "faturacao-truncado.js")


def test_uma_lista_truncada_DIZ_que_esta_truncada(ecra_truncado):
    """Uma lista truncada que não se assume mente sobre o que não encontrou: a
    operadora procura, não encontra, e conclui que a fatura não existe.

    O NÚMERO vem do servidor (`limite`) e não escrito no ecrã — duas cópias do
    mesmo tecto acabam sempre com o ecrã a prometer um alcance que já não é o
    real."""
    assert "200 mais recentes" in ecra_truncado["lista"]


@pytest.fixture(scope="module")
def ecra_completo(tmp_path_factory):
    return _montar_no_node(
        _cenario(documentos=[_documento()], fatura=_fatura(), conta_aberta=None,
                 ha_mais=False, abrir_fatura=False),
        tmp_path_factory.mktemp("fat-completo"), "faturacao-completo.js")


def test_uma_lista_inteira_nao_inventa_um_aviso_de_truncagem(ecra_completo):
    assert "Estão aqui todas" in ecra_completo["lista"]
    assert "mais recentes" not in ecra_completo["lista"].replace(
        "da mais recente para a mais antiga", "")


@pytest.fixture(scope="module")
def ecra_orfa(tmp_path_factory):
    return _montar_no_node(
        _cenario(
            documentos=[_documento(tem_venda=False, artigos=[], pagamentos=[])],
            fatura=_fatura(tem_venda=False, linhas=[], pagamentos=[],
                           mapa_imposto=[],
                           totais_imposto={"base": 0.0, "iva": 0.0, "total": 0.0},
                           total_das_linhas=0.0),
            conta_aberta=None),
        tmp_path_factory.mktemp("fat-orfa"), "faturacao-orfa.js")


def test_uma_fatura_sem_conta_de_origem_ABRE_e_diz_o_que_lhe_falta(ecra_orfa):
    """O DOCUMENTO existe, tem número e ATCUD — escondê-lo era esconder um
    documento fiscal real. O que não se pode é desenhá-lo como uma fatura
    vazia, que se lê como «o cliente não levou nada»."""
    assert "A conta de origem já não está guardada" in ecra_orfa["lista"]
    assert "FS 05P2026/1824" in ecra_orfa["fatura"]
    assert "€ 11,64" in ecra_orfa["fatura"]
    assert "a conta de origem desta fatura já não está guardada" in ecra_orfa["fatura"]
    assert ecra_orfa["copiar_desligado"] == "sim"


# --- Nível 3: a MONTAGEM — o botão está mesmo na barra do POS -----------------
#
# Testar as peças não testa o fio entre elas: o `PosFaturacao` pode estar
# perfeito e não estar montado em lado nenhum, e a suite fica verde com o
# separador ausente do balcão. Foi medido neste módulo, com a faixa do modo.


@pytest.fixture(scope="module")
def barra_do_pos(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1',"
        " loja_nome: 'Loja do Guarda' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosApp = carregar(path.join(POS, 'PosApp.js')).default;",
        "const CAIXA = { id: 'c1', nome: 'Caixa 1' };",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/caixa/estado'] = () => ({ data: {",
        "  caixas: [CAIXA], caixa: CAIXA, ultimo_fecho: null,",
        "  sessao_aberta: { aberta_por: { nome: 'Ana' },",
        "    aberta_em: '2026-08-22T09:00:00', fundo: 50 },",
        "} });",
        "RESPOSTAS_POS['/pos/documentos'] = () => ({ data: { documentos: [%s],"
        " limite: 200, ha_mais: false } });" % json.dumps(_documento()),
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosApp)); });",
        "  await act(async () => {});",
        "  const saida = { barra: textoVisivel(alvo) };",
        "  const abrir = [...alvo.querySelectorAll('button')].find(",
        "    (b) => (b.textContent || '').includes('Faturação'));",
        "  saida.tem_botao = !!abrir;",
        "  if (abrir) {",
        "    await act(async () => { abrir.click(); });",
        "    await act(async () => {});",
        "    saida.aberto = textoVisivel(alvo);",
        "  }",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("barra"), "barra.js")


def test_o_separador_ESTA_na_barra_do_POS_ao_lado_do_Caixa(barra_do_pos):
    """O `PosApp` montado a sério, com a caixa aberta. É este o guarda que a
    remoção do `<PosFaturacao />` do `PosMenuCaixa` não sobrevive — e sem ele o
    separador podia estar impecável e não estar no balcão."""
    assert "Loja do Guarda" in barra_do_pos["barra"], "Não é a barra do POS."
    assert "Faturação" in barra_do_pos["barra"]
    assert "Caixa" in barra_do_pos["barra"]
    assert barra_do_pos["tem_botao"] is True


def test_o_toque_no_separador_abre_a_lista_a_partir_da_barra(barra_do_pos):
    """E abre com dados do servidor: o número da fatura que o `/pos/documentos`
    fabricado devolveu."""
    assert "FS 05P2026/1824" in barra_do_pos["aberto"]


# --- Nível 3b: o FIO entre o separador e o ecrã de venda ----------------------
#
# **O beco que este guarda existe para não deixar reabrir.** «Copiar para a
# venda» abre uma conta NOVA no servidor, e o `PosVenda` — que é quem mostra a
# conta — não estava lá para a ver. Sem o sinal que os liga, ele continuava a
# desenhar o balcão VAZIO, a operadora tocava num produto, e o
# `POST /pos/venda` respondia 409 sobre uma conta que não estava em ecrã
# nenhum: exactamente o «um posto, uma conta» outra vez, reaberto por um lado
# novo.
#
# Aqui o `PosVenda` entra REAL — tira-se do conjunto dos substituídos do
# preâmbulo, que é um `Set` e por isso se pode destrancar sem tocar nele. Com
# o `PosVenda` de marca vazia, este guarda ficava verde com o fio cortado, que
# é o defeito inteiro.

_CATALOGO = {
    "categorias": [{"id": "cat-1", "nome": "Açaís", "ordem": 1}],
    "produtos": [{"id": "p-acai", "nome": "Açaí Regular", "categoria_id": "cat-1",
                  "preco": 10.20, "tax_id": "INT", "foto_url": None,
                  "grupos_personalizacao": [], "vendavel": True, "erros": []}],
    "grupos_personalizacao": [],
    "produtos_ocultos_categoria_inativa": 0,
}

_CONTA_COPIADA = {
    "id": "v-nova", "loja_id": "l1", "caixa_id": "c1", "sessao_id": "s1",
    "operador_id": "o1", "estado": "aberta", "criada_em": "2026-08-22T15:10:00",
    "desconto_global_pct": None, "desconto_global_eur": None,
    "cancelada_em": None, "cancelada_por": None, "conta_mae_id": None,
    "emissao_por_confirmar": False, "entregue_ao_gestor_em": None,
    "entregue_ao_gestor_por": None,
    "linhas": [{"id": "li-1", "produto_id": "p-acai", "produto_nome": "Açaí Regular",
                "produto_preco": 10.20, "produto_tax_id": "INT", "quantidade": 1,
                "opcoes": [], "respostas_texto": [], "preco_override": None,
                "tax_override": None, "desconto_pct": None, "desconto_eur": None}],
    "totais": {"subtotal": 10.20, "desconto_linhas": 0.0,
               "desconto_global": 0.0, "total": 10.20},
}


@pytest.fixture(scope="module")
def copia_no_balcao(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        # O `PosVenda` entra REAL — é ele que tem de reparar que nasceu uma
        # conta. Ver o comentário desta secção.
        "SUBSTITUIDOS.delete(path.join(POS, 'PosVenda.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1',"
        " loja_nome: 'Loja do Guarda' });",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosApp = carregar(path.join(POS, 'PosApp.js')).default;",
        "const CAIXA = { id: 'c1', nome: 'Caixa 1' };",
        # **O servidor tem memória**: antes da cópia não há conta em curso;
        # depois há. É esse o facto que o ecrã tem de ir descobrir — cravar a
        # conta desde o início fazia este guarda ficar verde com o fio
        # cortado, porque o `carregarTudo` do arranque já a trazia.
        "let contaNoServidor = null;",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "RESPOSTAS_POS['/pos/caixa/estado'] = () => ({ data: {",
        "  caixas: [CAIXA], caixa: CAIXA, ultimo_fecho: null,",
        "  sessao_aberta: { aberta_por: { nome: 'Ana' },",
        "    aberta_em: '2026-08-22T09:00:00', fundo: 50 },",
        "} });",
        "RESPOSTAS_POS['/pos/catalogo'] = () => ({ data: %s });" % json.dumps(_CATALOGO),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: [] });",
        "RESPOSTAS_POS['/pos/venda/repartidas'] = () => ({ data: [] });",
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: contaNoServidor });",
        "RESPOSTAS_POS['/pos/documentos'] = () => ({ data: { documentos: [%s],"
        " limite: 200, ha_mais: false } });" % json.dumps(_documento()),
        "RESPOSTAS_POS['/pos/documentos/doc-1'] = () => ({ data: %s });"
        % json.dumps(_fatura()),
        "RESPOSTAS_POS['/pos/documentos/doc-1/copiar-para-venda'] = () => {",
        "  contaNoServidor = %s;" % json.dumps(_CONTA_COPIADA),
        "  return { data: { venda: contaNoServidor, nao_copiados: [],",
        "    copiada_de: { documento_id: 'doc-1', numero: 'FS 05P2026/1824' } } };",
        "};",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosApp)); });",
        "  await act(async () => {});",
        "  await act(async () => {});",
        "  const saida = { antes: textoVisivel(alvo) };",
        "  const abrir = [...alvo.querySelectorAll('button')].find(",
        "    (b) => (b.textContent || '').includes('Faturação'));",
        "  await act(async () => { abrir.click(); });",
        "  await act(async () => {});",
        "  const linha = [...alvo.querySelectorAll('button')].find(",
        "    (b) => (b.textContent || '').includes('FS 05P2026/1824'));",
        "  await act(async () => { linha.click(); });",
        "  await act(async () => {});",
        "  const copiar = [...alvo.querySelectorAll('button')].find(",
        "    (b) => (b.textContent || '').includes('Copiar para a venda'));",
        "  saida.copiar_desligado = copiar.getAttribute('data-desligado');",
        "  await act(async () => { copiar.click(); });",
        "  await act(async () => {});",
        "  await act(async () => {});",
        "  saida.depois = textoVisivel(alvo);",
        "  saida.pedidos = pedidos.map((p) => p.metodo + ' ' + p.url);",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("copia"), "copia.js")


def test_antes_da_copia_o_balcao_esta_VAZIO(copia_no_balcao):
    """A metade que faz o guarda a seguir medir alguma coisa: se a conta já
    estivesse no ecrã antes do toque, «apareceu depois de copiar» não provava
    nada."""
    assert "Não existem produtos associados" in copia_no_balcao["antes"]


def test_a_copia_PEDE_ao_servidor_e_a_conta_APARECE_no_balcao(copia_no_balcao):
    """O fio inteiro, do dedo até ao painel da conta: o toque, o
    `POST /pos/documentos/{id}/copiar-para-venda`, e o `PosVenda` a reler a
    conta e a desenhá-la.

    Sem o sinal que liga o separador ao ecrã de venda, o balcão ficava a dizer
    «Não existem produtos associados» com uma conta aberta no servidor — e o
    produto seguinte levava um 409 sobre uma conta invisível."""
    assert copia_no_balcao["copiar_desligado"] == "nao"
    pedidos = " ".join(copia_no_balcao["pedidos"])
    # Só o caminho: o prefixo é o `REACT_APP_BACKEND_URL`, que em Node não
    # existe (sai "undefined/") — e não é ele que se está a guardar aqui.
    assert "post " in pedidos.lower()
    assert "/pos/documentos/doc-1/copiar-para-venda" in pedidos
    # E a conta é RELIDA ao servidor a seguir — não desenhada a partir da
    # resposta da cópia. A verdade da conta vem sempre de `GET
    # /pos/venda/aberta`, como em todo o `PosVenda`.
    assert pedidos.index("/pos/venda/aberta", pedidos.index("copiar-para-venda")) > 0
    depois = copia_no_balcao["depois"]
    assert "Açaí Regular" in depois
    assert "€ 10,20" in depois
    assert "Não existem produtos associados" not in depois
