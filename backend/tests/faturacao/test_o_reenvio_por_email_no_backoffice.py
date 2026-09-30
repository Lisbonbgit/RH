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

**As FRASES estão todas numa tabela** (`_ESTADOS_DO_EMAIL`), como as do gémeo
`textoDosPontosApp` estão no `_ESTADOS_DOS_PONTOS` do mesmo ficheiro de testes:
o `textoDoEnvioPorEmail` tem oito saídas e uma frase sem caso é uma frase que
se pode reescrever — ou apagar — com a suite verde. A montagem do botão
(carregar, reler) fica à parte, no cenário `falhada`: essa é interacção e não
texto.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
from .test_o_ecra_de_documentos_no_backoffice import _FATURA, _LISTA, _LOJAS

_BASE_EMAIL = {
    "estado": "pendente", "tentativas": 0, "motivo": None, "ultimo_erro": None,
    "atualizado_em": "2026-09-17T18:05:00+00:00",
}

# Cada saída do `textoDoEnvioPorEmail` (`FatDocumentos.js:123-152`) tem aqui a
# sua linha, e a frase é a que o gestor LÊ — partir qualquer uma das frases no
# ficheiro põe vermelho o caso respectivo, e só esse.
_ESTADOS_DO_EMAIL = [
    # **«Enviada» é o que o servidor de envio aceitou, e não o que o cliente
    # recebeu.** É esta frase que impede o gestor de responder «foi enviada» a
    # quem está a dizer a verdade; sem caso, bastava alguém encurtá-la.
    ("feito", {"estado": "feito", "tentativas": 1},
     "Enviada — aceite pelo servidor de envio (não é prova de entrega)"),
    ("a_tentar", {"tentativas": 3, "ultimo_erro": "HTTP 503"},
     "A tentar enviar (3 tentativas — último erro: HTTP 503)"),
    # O singular e o «sem detalhe» na mesma linha: são os dois ramos pequenos
    # do mesmo texto, e uma tentativa sem erro guardado é o que dá a fila logo
    # a seguir ao primeiro empurrão.
    ("a_tentar_uma_vez_sem_erro", {"tentativas": 1},
     "A tentar enviar (1 tentativa — último erro: sem detalhe)"),
    ("a_espera", {}, "À espera de ser enviada."),
    # **Pendente com 0 tentativas mas com erro.** Há caminhos que esperam de
    # propósito sem gastar tentativa — e o grave é a integração sem chave, em
    # que NENHUM email está a ser enviado em lado nenhum. É a única janela que
    # o gestor tem para esse caso; decidida a frase só por `tentativas`,
    # aparecia a frase tranquila em todas as faturas e calava o motivo.
    ("a_espera_com_erro", {"ultimo_erro": "integração não configurada"},
     "À espera — último erro: integração não configurada"),
    # O motivo sai em PORTUGUÊS, pelo mapa que já lá estava
    # (`MOTIVOS_DOS_PONTOS`, `FatDocumentos.js:66-79`): os dois blocos ficam
    # lado a lado no mesmo diálogo, e um em português e outro em código-máquina
    # era o mesmo motivo escrito de duas maneiras à mesma pessoa.
    ("recusado", {"estado": "recusado", "tentativas": 1, "motivo": "ligacao_ja_usada"},
     "Recusado pela app: aquele QR já deu pontos noutra fatura"),
    ("sem_efeito", {"estado": "sem_efeito"},
     "Sem efeito — esta fatura não chegou a ir por email."),
    # **O cliente ficou sem documento nenhum** — o talão não saiu (decisão do
    # dono) e o email também não. A única forma de alguém dar por isso é a
    # frase dizê-lo, com o erro ao lado: sem o erro, o gestor não sabe se foi o
    # endereço, se foi a app ou se foi o envio.
    ("falhado", {"estado": "falhado", "tentativas": 13,
                 "ultimo_erro": "HTTP 500: {\"detail\":\"envio falhou\"}"},
     "Falhou ao fim de 24 h — último erro: HTTP 500: {\"detail\":\"envio falhou\"}. "
     "O cliente ficou sem documento: reenvie, ou mande reimprimir na loja."),
    # Um estado que este ecrã ainda não conheça aparece em CRU, nunca em
    # silêncio — é a regra do gémeo dos pontos.
    ("estado_desconhecido", {"estado": "coisa_que_ainda_nao_existe"},
     "Estado desconhecido: coisa_que_ainda_nao_existe"),
]

_FALHADA = dict(_FATURA, fatura_email=dict(
    _BASE_EMAIL, estado="falhado", tentativas=13,
    ultimo_erro="HTTP 500: {\"detail\":\"envio falhou\"}"))
# Como a linha fica DEPOIS de o botão a repor: pendente, zero tentativas, sem
# erro nenhum — é o que prova que o ecrã releu o documento em vez de desenhar
# o que tinha.
_REPOSTA = dict(_FATURA, fatura_email=dict(
    _BASE_EMAIL, atualizado_em="2026-09-17T18:30:00+00:00"))


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
def estados(tmp_path_factory):
    """O MESMO documento aberto uma vez por estado, com a resposta do servidor
    trocada entre cliques — o molde do `pontos` do
    `test_o_ecra_de_documentos_no_backoffice.py`. O `sem_email` fica em último
    de propósito: prova que o bloco DESAPARECE, e não só que nunca apareceu."""
    casos = {
        nome: dict(_FATURA, fatura_email=dict(_BASE_EMAIL, **mudancas))
        for nome, mudancas, _frase in _ESTADOS_DO_EMAIL
    }
    casos["sem_email"] = dict(_FATURA, fatura_email=None)
    cenario = "\n".join([
        _COMPONENTES,
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatDocumentos = carregar(path.join(ADMIN, 'FatDocumentos.js')).default;",
        "const CASOS = %s;" % json.dumps(casos, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: %s });"
        % json.dumps(_LOJAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_LISTA, ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatDocumentos)); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const linha = alvo.querySelector('[data-testid=\"documento-d1\"]');",
        "if (!linha) throw new Error('sem linha da fatura: ' + textoVisivel(alvo).slice(0, 400));",
        "const saida = {};",
        "for (const [nome, documento] of Object.entries(CASOS)) {",
        "  RESPOSTAS_GESTAO['/faturacao/documentos/d1'] = () => ({ data: documento });",
        "  await act(async () => { linha.click(); });",
        "  await act(async () => {});",
        "  const bloco = alvo.querySelector('[data-testid=\"documento-fatura-email\"]');",
        "  saida[nome] = { aberta: textoVisivel(alvo).includes('Itens'),",
        "    email: bloco ? textoVisivel(bloco) : null,",
        "    tem_botao: !!alvo.querySelector('[data-testid=\"documento-reenviar-email\"]') };",
        "}",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp("estados-do-email"),
        "montar-estados-do-email.js")


@pytest.mark.parametrize("nome,frase", [(n, f) for n, _m, f in _ESTADOS_DO_EMAIL])
def test_o_detalhe_diz_o_que_aconteceu_ao_EMAIL_desta_fatura(estados, nome, frase):
    caso = estados[nome]
    assert caso["aberta"], "o detalhe do documento não abriu"
    assert caso["email"] is not None, "o detalhe não mostra a linha do email"
    assert "Fatura por email" in caso["email"], caso["email"]
    assert frase in caso["email"], caso["email"]
    # O botão reenvia QUALQUER documento com linha de email, e não só os
    # falhados: o caso frequente é a linha estar em `feito` e o cliente não ter
    # nada na caixa.
    assert caso["tem_botao"] is True, caso


def test_o_motivo_da_recusa_nunca_aparece_em_CRU(estados):
    """A frase já é afirmada em português na tabela; o que este guarda junta é
    que o código-máquina não vem ATRÁS dela entre parênteses."""
    assert "ligacao_ja_usada" not in estados["recusado"]["email"], \
        estados["recusado"]["email"]


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


def test_um_documento_que_NAO_ia_por_email_nao_mostra_bloco_nem_botao(estados):
    """A esmagadora maioria dos documentos. Um bloco vazio ou um «—» lia-se
    como «o email perdeu-se», e o botão convidava a mandar por email uma
    fatura de um cliente que nunca deu email nenhum."""
    assert estados["sem_email"]["aberta"]
    assert estados["sem_email"]["email"] is None
    assert estados["sem_email"]["tem_botao"] is False
