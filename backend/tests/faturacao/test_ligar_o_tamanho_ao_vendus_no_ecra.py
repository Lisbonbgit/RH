"""**Ligar cada tamanho ao artigo dele no Vendus** — o ecrã onde se faz.

Sem esta ligação, as cinco lojas facturam todos os açaís no mesmo artigo do
Vendus, seja qual for o tamanho: o dinheiro certo, o artigo errado, e o
catálogo do Vendus a não responder a nenhuma pergunta.

Duas coisas que só se vêem montando o ecrã:

1. **a ligação só aparece no grupo do TAMANHO.** Um topping não é outro
   artigo, e um campo de ligação ao lado da Nutella convidava a preenchê-lo —
   com o açaí inteiro a passar a ser facturado como «Nutella»;
2. **o Guardar manda `vendus_ref` SEMPRE**, também a `null`. Omiti-lo deixava
   a ligação anterior gravada, e desligar um tamanho era impossível.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_TAMANHO = {
    "id": "g-tam", "nome": "Tamanho", "tipo": "opcoes", "ativo": True,
    "min_select": 1, "max_select": 1, "sai_na_fatura": True,
    "e_variante": True,
    "opcoes": [
        {"id": "o-mini", "nome": "Mini", "preco": 5.85, "ativa": True},
        {"id": "o-reg", "nome": "Regular", "preco": 8.99, "ativa": True,
         "vendus_ref": "145268982"},
    ],
}
_TOPPINGS = {
    "id": "g-top", "nome": "Toppings", "tipo": "opcoes", "ativo": True,
    "min_select": 0, "max_select": 0, "sai_na_fatura": True,
    "e_variante": False,
    "opcoes": [{"id": "o-nut", "nome": "Nutella", "preco": 1.0, "ativa": True}],
}
_ARTIGOS = [
    {"id": "171258472", "nome": "Açaí Mini", "referencia": "ACAI-MINI"},
    {"id": "145268982", "nome": "Açaí Regular", "referencia": "ACAI-REG"},
]


def _monta(grupo, leituras, tmp_path, nome, artigos=None):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Ecra = carregar(path2.join(ADMIN, 'FatPersonalizacoes.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/grupos-personalizacao'] = () => ({ data: %s });"
        % json.dumps([grupo], ensure_ascii=False),
        # O PUT leva o id no caminho; a chave nomeia o método para não
        # colidir com o GET da listagem, que acaba no mesmo prefixo.
        "RESPOSTAS_GESTAO['PUT /faturacao/grupos-personalizacao/%s'] = () => ({ data: {} });"
        % grupo["id"],
        "RESPOSTAS_GESTAO['/faturacao/vendus/artigos'] = () => ({ data: %s });"
        % json.dumps(artigos if artigos is not None else _ARTIGOS, ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra)); });",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const clicar = async (t) => { const el = porTestid(t);",
        "  if (!el) throw new Error('sem ' + t);",
        "  await act(async () => { el.dispatchEvent(new window.MouseEvent('click',",
        "    { bubbles: true })); }); await act(async () => {}); };",
        "await clicar('edit-grupo-%s');" % grupo["id"],
        # O que o ecrã MANDOU, e não o que respondemos: o arnês guarda o
        # corpo de cada pedido em `pedidos`.
        "const gravou = () => pedidos.filter((p) => p.metodo === 'put'",
        "  && String(p.url).includes('/grupos-personalizacao/')).map((p) => p.corpo);",
        "const saida = {};",
    ] + leituras + [
        "saida.gravado = gravou();",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => { "
        "process.stderr.write(String(e && e.stack || e)); process.exit(1); });" % guiao,
        tmp_path, nome)


def test_o_grupo_do_TAMANHO_mostra_a_ligacao_em_cada_opcao(tmp_path):
    saida = _monta(_TAMANHO, [
        "saida.mini = !!porTestid('opcao-vendus-0');",
        "saida.ligarMini = !!porTestid('ligar-artigo-0');",
        "saida.regularJaLigado = !!porTestid('trocar-artigo-1');",
        "saida.textoDoRegular = (porTestid('opcao-vendus-1') || {}).textContent;",
    ], tmp_path, "tamanho.js")
    assert saida["mini"] and saida["ligarMini"], "o Mini não tem por onde ligar"
    assert saida["regularJaLigado"], "o Regular já está ligado e não o mostra"
    assert "Ref. 145268982" in saida["textoDoRegular"], saida["textoDoRegular"]


def test_um_grupo_QUE_NAO_E_TAMANHO_nao_mostra_ligacao_nenhuma(tmp_path):
    """A restrição, no ecrã. O backend também a impõe
    (`precos.id_vendus_da_variante`), mas um campo que não faz nada é pior do
    que campo nenhum: preenche-se, e depois não acontece nada."""
    saida = _monta(_TOPPINGS, [
        "saida.temLigacao = !!porTestid('opcao-vendus-0');",
        "saida.temOpcao = !!porTestid('opcao-row-0');",
    ], tmp_path, "toppings.js")
    assert saida["temOpcao"], "o ecrã nem chegou a desenhar a opção"
    assert saida["temLigacao"] is False


def test_escolher_um_artigo_liga_o_tamanho_e_mostra_o_NOME(tmp_path):
    """Depois de ler o catálogo, o ecrã diz «Açaí Mini» e não «Ref. 171258472»
    — é pelo nome que o dono confirma que ligou ao artigo certo."""
    saida = _monta(_TAMANHO, [
        "await clicar('ligar-artigo-0');",
        "await clicar('artigo-do-tamanho-171258472');",
        "saida.texto = (porTestid('opcao-vendus-0') || {}).textContent;",
    ], tmp_path, "escolher.js")
    assert "Açaí Mini" in saida["texto"], saida["texto"]


def test_o_GUARDAR_manda_a_referencia_de_cada_opcao(tmp_path):
    saida = _monta(_TAMANHO, [
        "await clicar('ligar-artigo-0');",
        "await clicar('artigo-do-tamanho-171258472');",
        # `requestSubmit` e não um clique: o botão é `type=submit` e em jsdom
        # o clique nem sempre dispara o `onSubmit` do formulário.
        "await act(async () => { porTestid('save-grupo-btn').form.dispatchEvent(",
        "  new window.Event('submit', { bubbles: true, cancelable: true })); });",
        "await act(async () => {});",
    ], tmp_path, "guardar.js")
    assert saida["gravado"], "não gravou nada"
    opcoes = saida["gravado"][-1]["opcoes"]
    assert opcoes[0]["vendus_ref"] == "171258472"
    assert opcoes[1]["vendus_ref"] == "145268982", "perdeu a ligação que já existia"


def test_DESLIGAR_um_tamanho_manda_null_e_nao_omite(tmp_path):
    """Omitir o campo deixava a ligação anterior gravada: o dono desligava, o
    ecrã dizia que estava desligado, e a fatura continuava a sair no artigo
    antigo."""
    saida = _monta(_TAMANHO, [
        "await clicar('desligar-artigo-1');",
        # `requestSubmit` e não um clique: o botão é `type=submit` e em jsdom
        # o clique nem sempre dispara o `onSubmit` do formulário.
        "await act(async () => { porTestid('save-grupo-btn').form.dispatchEvent(",
        "  new window.Event('submit', { bubbles: true, cancelable: true })); });",
        "await act(async () => {});",
    ], tmp_path, "desligar.js")
    opcoes = saida["gravado"][-1]["opcoes"]
    assert "vendus_ref" in opcoes[1], "o campo foi OMITIDO — a ligação fica lá"
    assert opcoes[1]["vendus_ref"] is None


def test_o_catalogo_do_Vendus_em_baixo_DIZ_o_que_se_passa(tmp_path):
    """Uma lista vazia com ar de sucesso dizia «esta conta não tem artigos», e
    o tamanho ficava por ligar por engano. A frase é a do servidor: é ele que
    sabe se a conta não está configurada ou se o Vendus está em baixo."""
    saida = _monta(_TAMANHO, [
        "RESPOSTAS_GESTAO['/faturacao/vendus/artigos'] = () => {",
        "  const e = new Error('502'); e.response = { status: 502, data:",
        "    { detail: 'O Vendus não respondeu.' } }; throw e; };",
        "await clicar('ligar-artigo-0');",
        "saida.erro = (porTestid('erro-artigos-vendus') || {}).textContent;",
    ], tmp_path, "vendus-em-baixo.js")
    assert saida["erro"] and "Vendus" in saida["erro"], saida["erro"]
