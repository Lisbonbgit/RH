"""O filtro **«por enviar»** do separador Faturação — executado, não lido.

**Não há lista nova.** O separador já lista os documentos da loja e já tem um
«Imprimir» em cada um: quem ficou sem email e precisa de papel tem-no a um
toque. O que faltava era a PERGUNTA — quais é que estão por enviar —, e isso é
um filtro sobre a lista que já existe.

**E a pergunta responde-se no SERVIDOR.** O documento traz
`fatura_email_por_enviar`, que é o mesmo sinal que o alarme da loja conta
(`impressao.py::estado_da_impressao`), janela incluída. Decidido aqui, o botão
acendia no minuto normal entre o EMITIR e o cron — em TODAS as faturas por
email — com o alarme calado ao lado, e um contador que acende no caso normal
ensina-se a ignorar. Pior ainda ao contrário: um `pendente` encalhado acendia o
alarme e não aparecia neste filtro, e a operadora não tinha onde dar o papel.

A técnica é a do `test_o_separador_de_faturacao_no_ecra.py`, e o molde da
biblioteca de UI e dos documentos vem de lá inteiro (uma segunda cópia
divergia da primeira no dia em que uma fosse corrigida). O que se afirma é o
que a operadora LÊ.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_o_separador_de_faturacao_no_ecra import _COMPONENTES, _documento

# Cinco documentos da mesma loja, e os cinco casos que existem ao balcão.
# Os dois primeiros são os que interessam: o cliente está neste momento sem
# documento nenhum, porque o talão não saiu.
_ENCALHADA = _documento(id="doc-1", numero="FS 05P2026/1824",
                        fatura_email_por_enviar=True)
_FALHADA = _documento(id="doc-2", numero="FS 05P2026/1825",
                      fatura_email_por_enviar=True)
_ENVIADA = _documento(id="doc-3", numero="FS 05P2026/1826",
                      fatura_email_por_enviar=False)
# Acabou de sair e vai a caminho: o servidor ainda não a conta, e o ecrã também
# não. O minuto normal entre o EMITIR e o cron não é um alarme.
_A_CAMINHO = _documento(id="doc-4", numero="FS 05P2026/1827",
                        fatura_email_por_enviar=False)
# A esmagadora maioria: o cliente não mostrou a app, e o talão saiu como sempre.
_EM_PAPEL = _documento(id="doc-5", numero="FS 05P2026/1828",
                       fatura_email_por_enviar=False)


def _cenario(documentos):
    return "\n".join([
        _COMPONENTES,
        "const PosFaturacao = carregar(path.join(POS, 'PosFaturacao.js')).default;",
        "RESPOSTAS_POS['/pos/documentos'] = () => ({ data: { documentos: %s,"
        " limite: 200, ha_mais: false } });" % json.dumps(documentos, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(",
        "    PosFaturacao, { caixa: { id: 'c1', nome: 'Balcão' }, onContaCopiada: () => {} }));",
        "  });",
        "  await act(async () => {});",
        "  const carregar_em = async (texto) => {",
        "    const b = [...alvo.querySelectorAll('button')].find(",
        "      (x) => (x.textContent || '').includes(texto) && !x.disabled);",
        "    if (!b) throw new Error('sem botão vivo com o texto ' + texto + ' — no ecrã: '",
        "      + textoVisivel(alvo).slice(0, 500));",
        "    await act(async () => { b.click(); });",
        "    await act(async () => {});",
        "  };",
        "  await carregar_em('Documentos');",
        "  await carregar_em('Faturação');",
        "  const todas = textoVisivel(alvo);",
        "  await carregar_em('Por enviar');",
        "  const filtrada = textoVisivel(alvo);",
        "  await carregar_em('Por enviar');",
        "  const outra_vez = textoVisivel(alvo);",
        "  process.stdout.write(JSON.stringify({ todas, filtrada, outra_vez }));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    return _montar_no_node(
        _cenario([_ENCALHADA, _FALHADA, _ENVIADA, _A_CAMINHO, _EM_PAPEL]),
        tmp_path_factory.mktemp("por-enviar"), "por-enviar.js")


@pytest.fixture(scope="module")
def ecra_sem_nenhuma(tmp_path_factory):
    return _montar_no_node(
        _cenario([_ENVIADA, _A_CAMINHO, _EM_PAPEL]),
        tmp_path_factory.mktemp("por-enviar-zero"), "por-enviar-zero.js")


def test_a_lista_abre_com_TUDO_e_o_botao_diz_quantas_estao_por_enviar(ecra):
    """O número no botão é a razão de ele existir: sem ele, a operadora tinha
    de o carregar para saber se havia alguma."""
    for numero in ("FS 05P2026/1824", "FS 05P2026/1825", "FS 05P2026/1826",
                   "FS 05P2026/1827", "FS 05P2026/1828"):
        assert numero in ecra["todas"], ecra["todas"][:600]
    assert "Por enviar (2)" in ecra["todas"], ecra["todas"][:600]


def test_o_filtro_deixa_so_as_que_o_SERVIDOR_marcou_como_por_enviar(ecra):
    """**E nenhuma delas tem papel a compensá-la**, porque o talão não saiu: o
    cliente daquela fatura está neste momento sem documento nenhum. Uma fatura
    já enviada, uma que acabou de entrar na fila, ou uma que nunca foi por
    email, não têm nada a fazer nesta lista."""
    assert "FS 05P2026/1824" in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1825" in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1826" not in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1827" not in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1828" not in ecra["filtrada"], ecra["filtrada"][:600]


def test_desligar_o_filtro_devolve_a_lista_inteira(ecra):
    """Um filtro que não se desliga é uma lista nova com outro nome."""
    assert "FS 05P2026/1828" in ecra["outra_vez"], ecra["outra_vez"][:600]


def test_sem_nenhuma_por_enviar_o_ecra_DIZ_isso_e_nao_fala_de_pesquisa(ecra_sem_nenhuma):
    """«Nenhuma fatura destas bate com o que escreveu» a quem não escreveu nada
    é uma resposta a uma pergunta que ninguém fez — e manda-a procurar um erro
    de escrita que não existe."""
    assert "está à espera de ir por email" in ecra_sem_nenhuma["filtrada"], \
        ecra_sem_nenhuma["filtrada"][:600]
    assert "bate com o que escreveu" not in ecra_sem_nenhuma["filtrada"], \
        ecra_sem_nenhuma["filtrada"][:600]
