"""O histórico no ecrã do Calendário (desenho das trocas, §3): o botão «Histórico» do cabeçalho
abre um painel em baixo com as mudanças do mês do dia escolhido. O `BolsoCalendario` montado
num DOM com o servidor fabricado e o relógio parado na terça, 27/10/2026; a semana de hoje (26/10
a 1/11) atravessa outubro e novembro.
"""
import json

from . import dados_semana_normal as sn
from .test_ecra_do_calendario import _ecra, _semana, _servidor

# O histórico servido à parte do mês: `HISTORICO` é a resposta (ou `{ erro }`).
SERVIR_O_HISTORICO = """
const HISTORICO = %s;
const servidorDoMes = global.SERVIDOR;
global.SERVIDOR = (metodo, url, ...resto) => (metodo === 'GET' && url === '/calendario/historico'
  ? HISTORICO : servidorDoMes(metodo, url, ...resto));
"""
AJUDAS = """
const dlg = () => document.querySelector('[role="dialog"]');
const historicos = () => REGISTO.filter((x) => x[1] === '/calendario/historico').map((x) => [x[0], x[3]]);
const abrir = async () => { await clicar(botao('Histórico')); await esperar(); };
"""


def _servir(resposta):
    return SERVIR_O_HISTORICO % json.dumps(resposta, ensure_ascii=False)


def _retrato(data, loja, nome, inicio, fim, no_lugar_de=None):
    return {"data": data, "loja": loja, "nome": nome, "inicio": inicio, "fim": fim, "no_lugar_de": no_lugar_de}


ENTRADAS = [
    {"id": "h2", "quando": "2026-10-27T08:05:00+00:00", "quem_id": sn.DEBORA, "quem_nome": "Débora Ferreira",
     "acao": "trocou", "datas": ["2026-10-27"], "antes": [],
     "depois": [_retrato("2026-10-27", "Alfragide", "Beatrice", "14:00", "23:00", "Emily")]},
    {"id": "h1", "quando": "2026-10-20T13:32:00+00:00", "quem_id": sn.CAROL, "quem_nome": "Carol Santos",
     "acao": "apagou", "datas": ["2026-10-13"], "depois": [],
     "antes": [_retrato("2026-10-13", "Loja Oeiras", "Débora Ferreira", "13:00", "22:00")]},
]


def test_o_historico_pede_so_ao_abrir_e_o_mes_do_dia_escolhido_mesmo_na_semana_de_dois_meses(tmp_path):
    outubro, novembro = _semana()
    r = _ecra(tmp_path, AJUDAS + """
const b = botao('Histórico');
const botaoNoCabecalho = { cabecalho: !!b.closest('header'), alvo: b.classList.contains('h-11') && b.classList.contains('w-11') };
const antes = historicos();
await abrir();
const outubro = { titulo: dlg().querySelector('h2').textContent, pedidos: historicos() };
await clicar(botao('Fechar', dlg()));
// Na mesma semana, o domingo 1/11 é de novembro: o histórico passa a ser o de novembro.
await clicar(document.querySelector('main [data-celula="2026-11-01"]'));
await abrir();
devolve({ botaoNoCabecalho, antes, outubro, novembro: { titulo: dlg().querySelector('h2').textContent, pedidos: historicos() },
          meses: REGISTO.filter((x) => x[1] === '/calendario').length });
""", outubro, novembro=novembro, vista=None, antes=_servir({"entradas": []}))
    assert r["botaoNoCabecalho"] == {"cabecalho": True, "alvo": True}
    assert r["antes"] == []
    assert r["outubro"] == {"titulo": "Histórico de outubro", "pedidos": [["GET", {"ano": 2026, "mes": 10}]]}
    assert r["novembro"] == {"titulo": "Histórico de novembro",
                             "pedidos": [["GET", {"ano": 2026, "mes": 10}], ["GET", {"ano": 2026, "mes": 11}]]}
    # Abrir e fechar o painel não volta a pedir os meses (só os dois da semana, ao abrir o ecrã).
    assert r["meses"] == 2


def test_a_lista_do_historico_e_uma_linha_por_entrada_pela_ordem_do_servidor(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, AJUDAS + """
await abrir();
devolve([...dlg().querySelectorAll('li')].map((li) => li.textContent));
""", mes, antes=_servir({"entradas": ENTRADAS}))
    assert r == ["às 08:05 · Débora · trocou Emily por Beatrice em Alfragide, 14h–23h · 27/10",
                 "20/10 às 14:32 · Carol · apagou a ida de Débora em Oeiras, 13h–22h · 13/10"]


def test_sem_entradas_o_painel_diz_desde_quando_ha_historico_e_quem_so_le_tambem_o_ve(tmp_path):
    mes, _ = _servidor(eu=sn.CONTABILISTA, pode_marcar=False)
    r = _ecra(tmp_path, AJUDAS + """
await abrir();
devolve({ texto: dlg().textContent, linhas: dlg().querySelectorAll('li').length });
""", mes, antes=_servir({"entradas": []}))
    assert r == {"texto": "Histórico de outubroSem alterações registadas neste mês. "
                          "O histórico começou em outubro de 2026.", "linhas": 0}


def test_um_erro_do_historico_aparece_dentro_do_painel(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, AJUDAS + """
await abrir();
devolve({ alerta: dlg().querySelector('[role="alert"]')?.textContent,
          noEcra: [...document.querySelectorAll('main [role="alert"]')].length, vazio: dlg().textContent.includes('Sem alterações') });
""", mes, antes=_servir({"erro": {"response": {"status": 500, "data": {"detail": "A base de dados não respondeu."}}}}))
    assert r == {"alerta": "A base de dados não respondeu.", "noEcra": 0, "vazio": False}


def test_sessao_expirada_ao_abrir_o_historico_so_faz_logout(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, AJUDAS + """
await abrir();
devolve(REGISTO.filter((x) => x[0] === 'logout' || x[0] === 'navigate'));
""", mes, antes=_servir({"erro": {"response": {"status": 401}}}))
    assert r == [["logout"]]
