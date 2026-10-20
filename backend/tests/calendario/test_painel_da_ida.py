"""O painel de uma ida (`pages/bolso/PainelIda.js`) montado num DOM, com o servidor fabricado
à frente do axios do `lib/bolso.js` e o mês tal como o servidor o calcula (desenho, secção 4,
«Tapar um buraco»)."""
import json

import pytest

import calendario
from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, correr_js

from . import dados_semana_normal as sn

ATALHO = "Também nas outras terças deste mês com buraco em Oeiras"
TAPAR_OEIRAS = {"modo": "tapar", "nomeDaLoja": "Oeiras",
                "inicial": {"datas": ["2026-10-06"], "location_id": sn.OEIRAS, "inicio": "13:00", "fim": "22:00"}}
IDA = {"modo": "editar", "inicial": {"ida_id": "i-1", "datas": ["2026-10-06"], "location_id": sn.OEIRAS,
                                     "user_ids": [sn.DEBORA], "inicio": "13:00", "fim": "22:00",
                                     "nome": "Débora Ferreira"}}


def _mes(idas=()):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    return calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True)


def _painel(tmp_path, painel, cenario, resposta=None, idas=()):
    """Monta o PainelIda com `painel` e corre `cenario` (que tem `dlg`, o diálogo); o servidor
    fabricado responde `resposta` a todos os pedidos."""
    return correr_js("\n".join([
        "const DADOS = %s;" % json.dumps(_mes(idas), ensure_ascii=False),
        "const PAINEL = %s;" % json.dumps(painel, ensure_ascii=False),
        "const RESPOSTA = %s;" % json.dumps({} if resposta is None else resposta, ensure_ascii=False),
        "global.SERVIDOR = () => RESPOSTA;",
        "const PainelIda = importar('pages/bolso/PainelIda').default;",
        "await montar(React.createElement(PainelIda, { painel: PAINEL, dados: DADOS, hoje: '2026-10-27',",
        "  onFechar: () => REGISTO.push(['fechar']), onGuardado: () => REGISTO.push(['guardado']) }));",
        "const dlg = document.querySelector('[role=\"dialog\"]');",
        cenario,
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)


def test_tapar_comeca_no_buraco_e_em_mim(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
devolve({
  titulo: dlg.querySelector('h2').textContent,
  loja: dlg.querySelector('[aria-label="Loja"]').value,
  inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
  fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
  escolhidas: [...dlg.querySelectorAll('fieldset button[aria-pressed="true"]')].map((b) => b.textContent),
  grupos: [...dlg.querySelectorAll('fieldset p')].map((p) => p.textContent),
  primeiraPessoa: dlg.querySelector('fieldset button').textContent,
  dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')),
  fechoGrande: !!botao('Fechar', dlg),
  fechoPequeno: [...dlg.querySelectorAll('.sr-only')].some((s) => s.textContent === 'Close'),
});
""")
    assert r == {"titulo": "Tapar Oeiras", "loja": sn.OEIRAS, "inicio": "13:00", "fim": "22:00",
                 "escolhidas": ["Débora Ferreira"], "grupos": ["Gestores", "Colaboradores"],
                 "primeiraPessoa": "Carol Santos", "dias": ["2026-10-06"],
                 "fechoGrande": True, "fechoPequeno": False}


def test_o_atalho_marca_as_outras_tercas_e_marcar_manda_uma_ida_por_dia(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('%s', dlg));
const dias = [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia'));
const atalhoDepois = !!botao('%s', dlg);
await clicar(botao('Marcar 4 idas', dlg));
await esperar();
devolve({ dias, atalhoDepois, registo: REGISTO });
""" % (ATALHO, ATALHO), resposta={"criadas": 4})
    assert r["dias"] == ["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"]
    assert r["atalhoDepois"] is False
    assert r["registo"] == [
        ["POST", "/calendario/idas", {"datas": ["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"],
                                      "location_id": sn.OEIRAS, "user_ids": [sn.DEBORA],
                                      "inicio": "13:00", "fim": "22:00"}, None],
        ["guardado"]]


def test_o_atalho_so_conta_as_tercas_cujo_buraco_contem_as_horas(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('%s', dlg));
devolve([...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')));
""" % ATALHO, idas=[sn.ida("2026-10-20", sn.OEIRAS, sn.CAROL, "13:00", "17:00")])
    assert r == ["2026-10-06", "2026-10-13", "2026-10-27"]


def test_o_erro_do_servidor_aparece_em_texto_e_o_painel_fica_aberto(tmp_path):
    texto = "Débora já está em Alfragide das 10h às 14h a 06/10.\nMude as horas ou apague primeiro a outra ida."
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
const alerta = dlg.querySelector('[role="alert"]');
devolve({ alerta: alerta.textContent, aberto: !!document.querySelector('[role="dialog"]'),
          activo: !botao('Marcar 1 ida', dlg).disabled, registo: REGISTO.map((x) => x[0]),
          cor: [...alerta.classList].filter((c) => c.includes('destructive')) });
""", resposta={"erro": {"response": {"status": 409, "data": {"detail": texto}}}})
    # A cor é o par medido (6,2:1 no claro, 4,7:1 no escuro); o `text-destructive` sozinho dá
    # 3,8:1 no claro e o `-strong` sozinho 3,0:1 no escuro.
    assert r == {"alerta": texto, "aberto": True, "activo": True, "registo": ["POST"],
                 "cor": ["text-destructive-strong", "dark:text-destructive"]}


def test_sem_rede_diz_que_nao_houve_resposta(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
devolve(dlg.querySelector('[role="alert"]').textContent);
""", resposta={"erro": {"message": "Network Error"}})
    assert r == "Sem resposta do servidor. Verifique a rede e tente outra vez."


def test_no_maximo_duas_pessoas(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Carol Santos', dlg));
await clicar(botao('Guilherme Gestor', dlg));
devolve({ escolhidas: [...dlg.querySelectorAll('fieldset button[aria-pressed="true"]')].map((b) => b.textContent),
          aviso: texto().includes('No máximo duas pessoas de cada vez.'), marcar: !!botao('Marcar 2 idas', dlg) });
""")
    assert r == {"escolhidas": ["Carol Santos", "Débora Ferreira"], "aviso": True, "marcar": True}


def test_editar_guarda_uma_ida_com_o_que_mudou(tmp_path):
    r = _painel(tmp_path, IDA, """
await escrever(dlg.querySelector('[aria-label="Hora de início"]'), '15:00');
await clicar(botao('Carol Santos', dlg));
await clicar(dlg.querySelector('[data-dia="2026-10-13"]'));
const titulo = dlg.querySelector('h2').textContent;
await clicar(botao('Guardar', dlg));
await esperar();
devolve({ titulo, registo: REGISTO });
""")
    assert r == {"titulo": "Ida de Débora Ferreira", "registo": [
        ["PUT", "/calendario/idas/i-1", {"data": "2026-10-13", "location_id": sn.OEIRAS, "user_id": sn.CAROL,
                                         "inicio": "15:00", "fim": "22:00"}, None],
        ["guardado"]]}


def test_apagar_pede_dois_toques(tmp_path):
    r = _painel(tmp_path, IDA, """
const cor = [...botao('Apagar', dlg).classList].filter((c) => c.includes('destructive'));
await clicar(botao('Apagar', dlg));
const depoisDeUm = REGISTO.length;
await clicar(botao('Tocar de novo para apagar', dlg));
await esperar();
devolve({ cor, depoisDeUm, registo: REGISTO });
""")
    assert r == {"cor": ["text-destructive-strong", "dark:text-destructive"], "depoisDeUm": 0,
                 "registo": [["DELETE", "/calendario/idas/i-1", None, None], ["guardado"]]}


def test_marcar_de_raiz_comeca_sem_loja_e_as_horas_vem_da_loja_escolhida(tmp_path):
    # Desenho, secção 4: «+ Marcar ida abre o mesmo painel vazio, com a loja a escolher».
    painel = {"modo": "marcar", "inicial": {"datas": ["2026-10-27"], "location_id": "", "inicio": "", "fim": ""}}
    r = _painel(tmp_path, painel, """
const campo = (rotulo) => dlg.querySelector('[aria-label="' + rotulo + '"]');
const horas = () => [campo('Hora de início').value, campo('Hora de fim').value];
const vazio = { loja: campo('Loja').value, horas: horas(), bloqueado: botao('Marcar 1 ida', dlg).disabled };
await escrever(campo('Loja'), '%s');
const benfica = horas();
await escrever(campo('Loja'), '%s');
const alfragide = horas();
await escrever(campo('Hora de início'), '15:00');
await escrever(campo('Loja'), '%s');
const mexidas = horas();
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
devolve({ titulo: dlg.querySelector('h2').textContent, vazio, benfica, alfragide, mexidas, corpo: REGISTO[0][2] });
""" % (sn.BENFICA, sn.ALFRAGIDE, sn.OEIRAS))
    assert r["titulo"] == "Marcar ida"
    assert r["vazio"] == {"loja": "", "horas": ["", ""], "bloqueado": True}
    # Benfica e Alfragide a 27/10: o horário de cada uma. Depois de mexer nas horas, trocar
    # de loja já não as apaga.
    assert (r["benfica"], r["alfragide"], r["mexidas"]) == (
        ["13:00", "22:00"], ["10:00", "23:00"], ["15:00", "23:00"])
    assert r["corpo"] == {"datas": ["2026-10-27"], "location_id": sn.OEIRAS, "user_ids": [sn.DEBORA],
                          "inicio": "15:00", "fim": "23:00"}


@pytest.mark.parametrize("painel,botoes,verbo", [
    (TAPAR_OEIRAS, ["Marcar 1 ida"], "POST"),
    (IDA, ["Apagar", "Tocar de novo para apagar"], "DELETE"),
])
def test_um_401_ao_gravar_ou_apagar_faz_logout_sem_mostrar_erro(tmp_path, painel, botoes, verbo):
    """Fase 3: o 401 só chega ao painel se a re-entrada pelo Face ID não deu
    (`lib/bolso.js`) → login normal (desenho §5.4), e não um erro num painel sem sessão."""
    r = _painel(tmp_path, painel, """
for (const nome of %s) await clicar(botao(nome, dlg));
await esperar();
devolve({ registo: REGISTO.map((x) => x[0]), erroAVista: texto().includes('Sessão expirada.') });
""" % json.dumps(botoes, ensure_ascii=False),
        resposta={"erro": {"response": {"status": 401, "data": {"detail": "Sessão expirada."}}}})
    assert r == {"registo": [verbo, "logout"], "erroAVista": False}
