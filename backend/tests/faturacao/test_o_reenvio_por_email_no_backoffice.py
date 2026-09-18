"""**O envio por email no detalhe do documento** — montado e carregado, não lido.

O gestor é quem atende o «não me chegou». A linha `fatura_email:<id>` da fila
existe do lado do servidor desde a emissão, e sem este ecrã não aparecia em
lado nenhum: nem o estado, nem a razão, nem uma forma de repetir.

O botão **reenvia qualquer documento**, e não só os falhados — o caso
frequente é a linha estar em `feito` e o cliente não ter o email na caixa.
Quem repõe os cinco campos da linha é o servidor; daqui vai o id.

A técnica é a de `test_o_ecra_de_documentos_no_backoffice.py`: jsdom, o React
a sério, o axios de GESTÃO fabricado à frente, e o que se afirma é o que o
gestor LÊ (`textoVisivel`) e o que o ecrã MANDA. Os caminhos comparam-se com
`endswith`: o `url` guardado traz o prefixo do `REACT_APP_BACKEND_URL`, que em
Node não existe e vem literalmente como `undefined/api`.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
from .test_o_ecra_de_documentos_no_backoffice import _FATURA, _LISTA, _LOJAS

_FALHADA = dict(_FATURA, fatura_email={
    "estado": "falhado", "tentativas": 13, "motivo": None,
    "ultimo_erro": "HTTP 500: {\"detail\":\"envio falhou\"}",
    "atualizado_em": "2026-09-17T18:05:00+00:00"})
# Como a linha fica DEPOIS de o botão a repor: pendente, zero tentativas, sem
# erro nenhum — é o que prova que o ecrã releu o documento em vez de desenhar
# o que tinha.
_REPOSTA = dict(_FATURA, fatura_email={
    "estado": "pendente", "tentativas": 0, "motivo": None, "ultimo_erro": None,
    "atualizado_em": "2026-09-17T18:30:00+00:00"})
_RECUSADA = dict(_FATURA, fatura_email={
    "estado": "recusado", "tentativas": 1, "motivo": "ligacao_ja_usada",
    "ultimo_erro": None, "atualizado_em": "2026-09-17T18:05:00+00:00"})
_SEM_EMAIL = dict(_FATURA, fatura_email=None)


def _cenario(detalhe_inicial):
    return "\n".join([
        _COMPONENTES,
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatDocumentos = carregar(path.join(ADMIN, 'FatDocumentos.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: %s });"
        % json.dumps(_LOJAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_LISTA, ensure_ascii=False),
        "let detalhe = %s;" % json.dumps(detalhe_inicial, ensure_ascii=False),
        "const REPOSTA = %s;" % json.dumps(_REPOSTA, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos/d1'] = () => ({ data: detalhe });",
        # O servidor repõe a linha e responde; a leitura seguinte já traz a
        # linha reposta. É assim que se vê se o ecrã releu ou se mentiu.
        "RESPOSTAS_GESTAO['POST /faturacao/documentos/d1/reenviar-email'] = () => {",
        "  detalhe = REPOSTA;",
        "  return { data: { reenviada: true } };",
        "};",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(FatDocumentos)); });",
        "  await act(async () => {});",
        "  await act(async () => {});",
        "  const linha = alvo.querySelector('[data-testid=\"documento-d1\"]');",
        "  if (!linha) throw new Error('sem linha da fatura: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { linha.click(); });",
        "  await act(async () => {});",
        "  const bloco = () => alvo.querySelector('[data-testid=\"documento-fatura-email\"]');",
        "  const botao = () => alvo.querySelector('[data-testid=\"documento-reenviar-email\"]');",
        "  const saida = {",
        "    aberto: bloco() ? textoVisivel(bloco()) : null,",
        "    tem_botao: !!botao(),",
        "    reimprimir: !!alvo.querySelector('[data-testid=\"documento-reimprimir\"]'),",
        "    pdf: !!alvo.querySelector('[data-testid=\"documento-pdf\"]'),",
        # Sempre presente, para a falha de antes da implementação ser uma
        # asserção legível e não um KeyError vindo do Python.
        "    depois: null,",
        "  };",
        "  if (botao()) {",
        "    await act(async () => { botao().click(); });",
        "    await act(async () => {});",
        "    saida.depois = bloco() ? textoVisivel(bloco()) : null;",
        "  }",
        "  saida.pedidos = pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url);",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])


def _quantos(pedidos, sufixo):
    # `sufixo` é "VERBO /caminho". Um `p.endswith(sufixo)` directo nunca
    # bateria: `p` é "VERBO " + url, e o `url` (`API_URL` = `undefined/api`
    # em Node, ver o preâmbulo do módulo) mete sempre esse prefixo ENTRE o
    # verbo e o caminho — "POST undefined/api/faturacao/.../reenviar-email"
    # não pode terminar em "POST /faturacao/.../reenviar-email" com outra
    # coisa a meio. Por isso compara-se o verbo à parte (`casa()` do
    # preâmbulo de montagem faz o mesmo) e só o CAMINHO por `endswith`.
    metodo, caminho = sufixo.split(" ", 1)
    return sum(
        1 for p in pedidos
        if p.startswith(metodo + " ") and p[len(metodo) + 1:].endswith(caminho)
    )


@pytest.fixture(scope="module")
def falhada(tmp_path_factory):
    return _montar_no_node(
        _cenario(_FALHADA), tmp_path_factory.mktemp("reenvio"), "reenvio.js")


@pytest.fixture(scope="module")
def recusada(tmp_path_factory):
    return _montar_no_node(
        _cenario(_RECUSADA), tmp_path_factory.mktemp("reenvio-recusada"),
        "reenvio-recusada.js")


@pytest.fixture(scope="module")
def sem_email(tmp_path_factory):
    return _montar_no_node(
        _cenario(_SEM_EMAIL), tmp_path_factory.mktemp("reenvio-sem"), "reenvio-sem.js")


def test_o_detalhe_diz_que_o_envio_FALHOU_e_o_ultimo_erro(falhada):
    """«Falhou ao fim de 24 h» sem o erro é uma notícia sem saída: o gestor
    tem de poder dizer à loja se foi o endereço, se foi a app ou se foi o
    envio."""
    assert falhada["aberto"] is not None, "o detalhe não mostra a linha do email"
    assert "Fatura por email" in falhada["aberto"], falhada["aberto"]
    assert "Falhou ao fim de 24 h" in falhada["aberto"], falhada["aberto"]
    assert "envio falhou" in falhada["aberto"], falhada["aberto"]
    assert "ficou sem documento" in falhada["aberto"], falhada["aberto"]


def test_um_motivo_de_recusa_aparece_em_PORTUGUES_como_o_dos_pontos(recusada):
    """Os dois blocos ficam lado a lado no mesmo diálogo, e a fila é a mesma
    (`fat_pontos_app`): um em português e outro em código-máquina era o mesmo
    motivo escrito de duas maneiras à mesma pessoa. O mapa
    `MOTIVOS_DOS_PONTOS` já existe no mesmo ficheiro (`FatDocumentos.js:66-79`),
    é o que o `textoDosPontosApp` (`:81-110`) usa, e a função nova entra logo a
    seguir a ele — não se escreve uma segunda tabela."""
    assert "aquele QR já deu pontos noutra fatura" in recusada["aberto"], \
        recusada["aberto"]
    assert "ligacao_ja_usada" not in recusada["aberto"], recusada["aberto"]


def test_o_botao_de_reenviar_esta_ao_lado_dos_dois_que_ja_la_estavam(falhada):
    assert falhada["tem_botao"] is True
    assert falhada["reimprimir"] is True
    assert falhada["pdf"] is True


def test_reenviar_pede_ao_servidor_e_RELE_o_documento(falhada):
    """O ecrã não escreve «a caminho» por sua conta: volta a perguntar ao
    servidor e desenha a linha como ela ficou. Um ecrã que se pintasse sozinho
    dizia «à espera» mesmo quando a reposição falhou."""
    assert _quantos(falhada["pedidos"],
                    "POST /faturacao/documentos/d1/reenviar-email") == 1, \
        falhada["pedidos"]
    assert _quantos(falhada["pedidos"], "GET /faturacao/documentos/d1") == 2, \
        falhada["pedidos"]
    assert falhada["depois"] is not None, "o bloco do email desapareceu do ecrã"
    assert "À espera de ser enviada." in falhada["depois"], falhada["depois"]
    assert "Falhou" not in falhada["depois"], falhada["depois"]


def test_um_documento_que_NAO_ia_por_email_nao_mostra_bloco_nem_botao(sem_email):
    """A esmagadora maioria dos documentos. Um bloco vazio ou um «—» lia-se
    como «o email perdeu-se», e o botão convidava a mandar por email uma
    fatura de um cliente que nunca deu email nenhum."""
    assert sem_email["aberto"] is None
    assert sem_email["tem_botao"] is False
