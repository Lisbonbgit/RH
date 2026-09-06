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


def _monta(resposta, leituras, tmp_path, nome, falhar=False, falhar_na_segunda=False):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Ecra = carregar(path2.join(ADMIN, 'FatConsumo.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: [] });",
        ("RESPOSTAS_GESTAO['/faturacao/consumo'] = () => { const e = new Error('502');"
         " e.response = { status: 502, data: { detail: 'O servidor não respondeu.' } };"
         " throw e; };") if falhar else
        ("let vezes = 0;\n"
         "RESPOSTAS_GESTAO['/faturacao/consumo'] = () => { vezes += 1;"
         " if (vezes > 1) { const e = new Error('502');"
         " e.response = { status: 502, data: { detail: 'O servidor não respondeu.' } };"
         " throw e; } return { data: %s }; };"
         % json.dumps(resposta, ensure_ascii=False)) if falhar_na_segunda else
        ("RESPOSTAS_GESTAO['/faturacao/consumo'] = () => ({ data: %s });"
         % json.dumps(resposta, ensure_ascii=False)),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra)); });",
        "await act(async () => {}); await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const clicar = async (t) => { const el = porTestid(t);",
        "  if (!el) throw new Error('sem ' + t);",
        "  await act(async () => { el.dispatchEvent(new window.MouseEvent('click',",
        "    { bubbles: true })); }); await act(async () => {});",
        "  await act(async () => {}); };",
        "const escrever = async (t, valor) => { const el = porTestid(t);",
        "  const setter = Object.getOwnPropertyDescriptor(",
        "    window.HTMLInputElement.prototype, 'value').set;",
        "  await act(async () => { setter.call(el, valor);",
        "    el.dispatchEvent(new window.Event('change', { bubbles: true })); });",
        "  await act(async () => {}); };",
        "const pedidosAoConsumo = () => pedidos.filter(",
        "  (p) => String(p.url).includes('/faturacao/consumo')).length;",
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


def test_um_erro_LIMPA_a_tabela_do_periodo_anterior(tmp_path):
    """O caso que faz o dono escrever o número errado na folha da contagem.

    Muda-se de «1–7 set» para «1–30 ago», carrega-se em Ver, e o servidor
    falha. As datas em cima já são as de agosto; se a tabela de setembro ficar
    por baixo, é aquele número que ele copia — com uma faixa vermelha pelo
    meio que se lê como «não conseguiu actualizar», não como «isto é de outro
    mês»."""
    saida = _monta(_SO_BALCAO, [
        "saida.antes = alvo.textContent.includes('Granola');",
        "await clicar('consumo-procurar');",
        "saida.temErro = !!porTestid('consumo-erro');",
        "saida.aindaTemTabela = alvo.textContent.includes('4,2 kg');",
        "saida.aindaTemRodape = !!porTestid('consumo-rodape');",
    ], tmp_path, "erro-limpa.js", falhar_na_segunda=True)
    assert saida["antes"], "a primeira leitura nem chegou a mostrar a tabela"
    assert saida["temErro"], "o erro não apareceu"
    assert saida["aindaTemTabela"] is False, "ficaram os quilos do período anterior"
    assert saida["aindaTemRodape"] is False, "ficou o rodapé do período anterior"


def test_uma_data_APAGADA_nao_vai_ao_servidor(tmp_path):
    """O axios não omite uma string vazia: ia `de=` e o servidor devolvia
    «Invalid isoformat string» — inglês do Python na cara do dono. A pergunta
    responde-se no ecrã."""
    saida = _monta(_SO_BALCAO, [
        "const antes = pedidosAoConsumo();",
        "await escrever('consumo-de', '');",
        "await clicar('consumo-procurar');",
        "saida.pediuOutraVez = pedidosAoConsumo() > antes;",
        "saida.erro = (porTestid('consumo-erro') || {}).textContent;",
    ], tmp_path, "data-apagada.js")
    assert saida["pediuOutraVez"] is False, "foi ao servidor com uma data vazia"
    assert "datas" in (saida["erro"] or "").lower(), saida["erro"]


def test_as_devolucoes_aparecem_no_rodape_e_nao_como_vendas(tmp_path):
    """Uma devolução não vendeu nada, mas o dono quer saber que houve."""
    com_nc = dict(_SO_BALCAO, notas_de_credito=3)
    saida = _monta(com_nc, [
        "saida.rodape = (porTestid('consumo-rodape') || {}).textContent;",
    ], tmp_path, "com-nc.js")
    assert "3 devolu" in saida["rodape"], saida["rodape"]
