"""**O ecrã do Consumo** — e a frase que ele é obrigado a dizer.

A tabela é a parte fácil. A parte que interessa é o aviso: as vendas da app
NÃO estão lá dentro, e o ecrã tem de o dizer em letra visível. Um relatório
que mostrasse 4,2 kg de granola sem avisar que faltam 214 vendas da app estava
a dizer «foi isto que saiu do armazém» — e a diferença ia aparecer na
contagem do mês como um roubo que não houve.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_SO_BALCAO = {
    "de": "2026-09-01", "ate": "2026-09-07",
    "documentos_do_balcao": 120, "documentos_da_app": 0, "documentos_por_medir": 0,
    "truncado": False,
    "linhas": [
        {"estoque_produto_id": "est-granola", "nome": "Granola", "unidade": "kg",
         "quantidade": 4.2, "doses": 140, "ligado_ao_estoque": True},
        {"estoque_produto_id": None, "nome": "Nutella", "unidade": "kg",
         "quantidade": 1.1, "doses": 55, "ligado_ao_estoque": False},
    ],
}


def _monta(resposta, leituras, tmp_path, nome, falhar=False):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Ecra = carregar(path2.join(ADMIN, 'FatConsumo.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: [] });",
        ("RESPOSTAS_GESTAO['/faturacao/consumo'] = () => { const e = new Error('502');"
         " e.response = { status: 502, data: { detail: 'O servidor não respondeu.' } };"
         " throw e; };") if falhar else
        ("RESPOSTAS_GESTAO['/faturacao/consumo'] = () => ({ data: %s });"
         % json.dumps(resposta, ensure_ascii=False)),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra)); });",
        "await act(async () => {}); await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const saida = {};",
        "saida.texto = alvo.textContent;",
    ] + leituras + [
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => { "
        "process.stderr.write(String(e && e.stack || e)); process.exit(1); });" % guiao,
        tmp_path, nome)


def test_a_tabela_mostra_o_que_saiu_com_a_unidade(tmp_path):
    saida = _monta(_SO_BALCAO, [
        "saida.granola = (porTestid('consumo-linha-est-granola') || {}).textContent;",
    ], tmp_path, "tabela.js")
    assert "Granola" in saida["granola"]
    assert "4,2 kg" in saida["granola"], saida["granola"]
    assert "140" in saida["granola"], "as doses não aparecem"


def test_uma_linha_por_ligar_diz_se_no_ecra(tmp_path):
    saida = _monta(_SO_BALCAO, [
        "saida.aviso = !!porTestid('consumo-aviso-por-ligar');",
        "saida.nutella = (porTestid('consumo-linha-Nutella') || {}).textContent;",
    ], tmp_path, "por-ligar.js")
    assert saida["aviso"], "não avisa que há linhas sem artigo do Estoque"
    assert "por ligar" in saida["nutella"], saida["nutella"]


def test_SEM_vendas_da_app_nao_ha_aviso_nenhum(tmp_path):
    """O aviso é para quando ele é verdade. Um aviso permanente deixa de se
    ler ao terceiro dia."""
    saida = _monta(_SO_BALCAO, [
        "saida.aviso = !!porTestid('consumo-aviso-app');",
    ], tmp_path, "sem-app.js")
    assert saida["aviso"] is False


def test_COM_vendas_da_app_o_ecra_DIZ_que_elas_faltam(tmp_path):
    """A frase que este ecrã existe para dizer. Sem ela, o dono lê 4,2 kg como
    «foi isto que saiu» e a diferença aparece na contagem do mês como um roubo
    que não houve."""
    com_app = dict(_SO_BALCAO, documentos_da_app=214)
    saida = _monta(com_app, [
        "saida.aviso = (porTestid('consumo-aviso-app') || {}).textContent;",
    ], tmp_path, "com-app.js")
    assert saida["aviso"], "não há aviso nenhum sobre as vendas da app"
    assert "214" in saida["aviso"], saida["aviso"]
    assert "balcão" in saida["aviso"], saida["aviso"]


def test_sem_gramagens_escritas_o_ecra_EXPLICA_o_vazio(tmp_path):
    """Uma tabela vazia sem explicação lê-se como avaria. O que se passa é que
    ninguém escreveu ainda o que cada personalização gasta — e o ecrã diz
    exactamente onde se escreve."""
    vazio = dict(_SO_BALCAO, linhas=[])
    saida = _monta(vazio, [], tmp_path, "vazio.js")
    assert "Personalizações" in saida["texto"], saida["texto"][:400]


def test_o_servidor_em_baixo_DIZ_o_que_se_passa(tmp_path):
    saida = _monta(None, [
        "saida.erro = !!porTestid('consumo-erro');",
    ], tmp_path, "erro.js", falhar=True)
    assert saida["erro"], "o erro passou por tabela vazia"
