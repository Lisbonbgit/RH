"""**A gaveta abre com a caixa fechada.**

Pedido do dono. A gaveta é uma gaveta: guarda-se lá o fundo à noite, tira-se
troco de manhã antes de abrir o turno, procura-se uma moeda que caiu. Nada
disso é uma venda — e obrigar a abrir um turno de caixa para lhe mexer punha
um Z falso no sistema só para destrancar uma gaveta.

**Não se abriu porta nenhuma:** a rota do servidor (`impressao.abrir_gaveta`)
nunca exigiu turno, só a operadora autenticada. O que faltava era o BOTÃO, que
só existia no menu Caixa — e esse menu não se desenha com o turno fechado.

O que ela continua a não fazer: não regista movimento, não mexe em dinheiro e
não deixa vender.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES


def _monta(leituras, tmp_path, nome, ha_programa=True):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const POS2 = path2.join(RAIZ, 'pages', 'pos');",
        "SUBSTITUIDOS.delete(path2.join(POS2, 'PosCaixaFechada.js'));",
        "const Ecra = carregar(path2.join(POS2, 'PosCaixaFechada.js')).default;",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data: %s });"
        % json.dumps({"ha_programa": ha_programa, "por_sair": 0, "falhados": 0}),
        "let abriu = 0;",
        "RESPOSTAS_POS['POST /pos/impressao/gaveta'] = () => { abriu += 1;",
        "  return { data: { trabalho_id: 't1', aceite: true } }; };",
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra, {",
        "  caixa: { id: 'c1', nome: 'Balcão' }, ultimoFecho: null,",
        "  onAberta: () => {} })); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const saida = {};",
    ] + leituras + [
        "saida.abriu = abriu;",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao, tmp_path, "gaveta-%s.js" % nome)


def test_o_botao_da_gaveta_ESTA_no_ecra_de_caixa_fechada(tmp_path):
    """O que faltava. Antes disto, a única forma de abrir a gaveta era abrir
    um turno de caixa — um Z falso para destrancar uma gaveta."""
    saida = _monta(
        ["const b = porTestid('abrir-gaveta-caixa-fechada');",
         "saida.existe = !!b;",
         "saida.desligado = b ? !!b.disabled : null;",
         # `textoVisivel` e nao `textContent`: um botao com `hidden` continua
         # no DOM e le-se na mesma por essa porta — e um botao que o ecra nao
         # desenha e' exactamente o defeito que isto vem corrigir.
         "saida.ecra = textoVisivel(alvo);"],
        tmp_path, "existe")
    assert saida["existe"], "não há botão de gaveta no ecrã de caixa fechada"
    assert "Abrir Gaveta" in saida["ecra"], saida["ecra"]
    assert saida["desligado"] is False


def test_carregar_no_botao_PEDE_MESMO_a_gaveta_ao_servidor(tmp_path):
    """Afirmado sobre a CHAMADA e não sobre o ecrã: um botão que desenha bem
    e não chama nada é exactamente o defeito que isto vem corrigir."""
    saida = _monta(
        ["const b = porTestid('abrir-gaveta-caixa-fechada');",
         "await act(async () => { b.click(); });",
         "await act(async () => {});"],
        tmp_path, "clique")
    assert saida["abriu"] == 1


def test_sem_programa_de_impressao_o_botao_DIZ_porque_nao_pode(tmp_path):
    """A gaveta abre PELA impressora — é um impulso ESC/POS pelo cabo. Sem
    programa a ouvir não há impulso nenhum, e um botão morto sem explicação
    deixa a operadora a carregar nele."""
    saida = _monta(
        ["const b = porTestid('abrir-gaveta-caixa-fechada');",
         "saida.desligado = !!b.disabled;",
         "saida.ecra = textoVisivel(alvo);"],
        tmp_path, "sem-programa", ha_programa=False)
    assert saida["desligado"] is True
    assert saida["abriu"] == 0
    assert "impress" in saida["ecra"].lower(), saida["ecra"][-300:]


def test_a_gaveta_NAO_abre_a_caixa_nem_deixa_vender(tmp_path):
    """A gaveta é só a gaveta. O botão de abrir o turno continua a ser outro,
    e carregar na gaveta não o substitui."""
    saida = _monta(
        ["await act(async () => { porTestid('abrir-gaveta-caixa-fechada').click(); });",
         "await act(async () => {});",
         "saida.ecra = textoVisivel(alvo);"],
        tmp_path, "so-a-gaveta")
    assert "Caixa Fechada" in saida["ecra"], "o ecrã mudou de estado"
    assert "Abrir Caixa" in saida["ecra"], "o botão de abrir o turno desapareceu"
