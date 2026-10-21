"""O que os formulários dos Locais e das Escalas mandam ao servidor.

A passagem entre o que o servidor guarda (`horario`, `aberta_desde`, `dias`) e o que o
ecrã mostra vive em `frontend/src/lib/horarios.js`. Aqui corre-se o ficheiro VERDADEIRO
em Node (pelo ajudante comum `tests/bolso_js.py`) — nunca uma cópia, que ficaria verde
com o ecrã errado. Mais abaixo (Tarefas 6 e 7), os guardas de que os dois ecrãs o usam
mesmo: uma função pura testada não prova nada se a linha que a chama desaparecer.

Precisa de `frontend/node_modules` (`cd frontend && yarn install --frozen-lockfile`, com o yarn
em ~/.local/node/bin) e de `node` (no PATH ou em ~/.local/node/bin); sem eles SALTA e diz porquê.
"""
import json
import re
import tempfile
from pathlib import Path

from tests.bolso_js import SRC, correr_js

_LOCAIS = SRC / "pages" / "admin" / "AdminLocations.js"
_ESCALAS = SRC / "pages" / "admin" / "AdminSchedules.js"

BELEM = {
    "abre": "11:30", "fecha": "19:00",
    "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}],
    "fechada": [1],
}


def _no_node(guiao):
    """Corre `guiao` pelo ajudante comum (`tests/bolso_js.py`): a mesma porta para o node,
    o mesmo babel e o stderr a contar, como nos testes do calendário do bolso."""
    with tempfile.TemporaryDirectory() as pasta:
        return correr_js(guiao, Path(pasta))


def _corre(expressao):
    """Avalia `expressao` (JavaScript, com `h` = o módulo lib/horarios.js) e devolve o JSON."""
    return _no_node("const h = importar('lib/horarios');\ndevolve(%s);" % expressao)


# ---- Locais ----

def test_o_horario_de_belem_vai_ao_formulario_e_volta_igual():
    volta = _corre("h.formularioParaHorario(h.horarioParaFormulario(%s, '2026-10-24'))" % json.dumps(BELEM))
    assert volta == {"horario": BELEM, "aberta_desde": "2026-10-24"}


def test_o_formulario_mostra_o_domingo_com_outro_horario_e_a_terca_fechada():
    form = _corre("h.horarioParaFormulario(%s, null)" % json.dumps(BELEM))
    assert (form["tem"], form["abre"], form["fecha"], form["abertaDesde"]) == (True, "11:30", "19:00", "")
    assert [d["modo"] for d in form["dias"]] == ["geral", "fechada", "geral", "geral", "geral", "geral", "outro"]
    assert form["dias"][6] == {"modo": "outro", "abre": "11:30", "fecha": "20:00"}


def test_sem_horario_manda_as_duas_chaves_a_null():
    # O PUT só escreve o que vem no corpo: o formulário novo manda SEMPRE as duas chaves.
    assert _corre("h.formularioParaHorario(h.horarioParaFormulario(null, null))") == {
        "horario": None, "aberta_desde": None}


def test_desligar_o_horario_tira_o_e_marcar_dias_poe_os():
    form = _corre("h.horarioParaFormulario(null, null)")
    form.update({"tem": True, "abre": "13:00", "fecha": "22:00"})
    form["dias"][1] = {"modo": "fechada", "abre": "", "fecha": ""}
    form["dias"][6] = {"modo": "outro", "abre": "13:00", "fecha": "20:00"}
    assert _corre("h.formularioParaHorario(%s)" % json.dumps(form)) == {
        "horario": {"abre": "13:00", "fecha": "22:00",
                    "excecoes": [{"dia": 6, "abre": "13:00", "fecha": "20:00"}], "fechada": [1]},
        "aberta_desde": None}
    # A data só se vê com o horário ligado, mas o valor fica no formulário: desligar
    # o horário tem de a tirar também.
    form["abertaDesde"] = "2026-10-24"
    form["tem"] = False
    assert _corre("h.formularioParaHorario(%s)" % json.dumps(form)) == {"horario": None, "aberta_desde": None}


def test_o_resumo_do_horario_na_tabela():
    assert _corre("h.resumoDoHorario(%s)" % json.dumps(BELEM)) == "11:30–19:00 · Dom 11:30–20:00 · fecha Ter"
    assert _corre("h.resumoDoHorario(null)") == ""


# ---- Escalas ----

DIAS = [
    {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 3, "location_id": None, "inicio": "13:00", "fim": "22:00"},
]


def test_os_dias_da_escala_seguem_os_dias_marcados_e_por_ordem():
    por_dia = {
        "0": {"location_id": "amadora", "inicio": "", "fim": ""},
        "3": {"location_id": "", "inicio": "13:00", "fim": "22:00"},
        "5": {"location_id": "oeiras", "inicio": "", "fim": ""},   # dia desmarcado: não vai
    }
    assert _corre("h.formularioParaDias([3, 0, 2], %s)" % json.dumps(por_dia)) == [
        {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
        {"dia": 2, "location_id": None, "inicio": None, "fim": None},
        {"dia": 3, "location_id": None, "inicio": "13:00", "fim": "22:00"},
    ]


def test_os_dias_gravados_voltam_ao_formulario_e_saem_iguais():
    assert _corre("h.formularioParaDias([0, 3], h.diasParaFormulario(%s))" % json.dumps(DIAS)) == DIAS
    assert _corre("h.diasParaFormulario(null)") == {}
    assert _corre("h.diasParaFormulario(%s)" % json.dumps(DIAS))["3"] == {
        "location_id": "", "inicio": "13:00", "fim": "22:00"}


def test_o_resumo_dos_dias_na_tabela():
    lojas = json.dumps({"amadora": "Amadora"})
    assert _corre("h.resumoDosDias(%s, (id) => (%s)[id])" % (json.dumps(DIAS), lojas)) == \
        "Seg Amadora · Qui loja da ficha 13:00–22:00"
    perdida = json.dumps([{"dia": 2, "location_id": "x", "inicio": None, "fim": None}])
    assert _corre("h.resumoDosDias(%s, () => undefined)" % perdida) == "Qua (loja removida)"


# ---- Os ecrãs usam mesmo o lib/horarios.js, e compilam ----

def _compila(ficheiro):
    """O ecrã passa pelo Babel com o preset de React: apanha um JSX partido sem
    esperar pelo build de produção."""
    _no_node("\n".join([
        "const ficheiro = %s;" % json.dumps(str(ficheiro)),
        "require('@babel/core').transformSync(require('fs').readFileSync(ficheiro, 'utf-8'), {",
        "  presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],",
        "  filename: ficheiro, babelrc: false, configFile: false,",
        "});",
        "devolve(null);",
    ]))


def test_o_formulario_dos_locais_carrega_e_manda_o_horario():
    texto = _LOCAIS.read_text(encoding="utf-8")
    # Ao abrir uma loja, o horário gravado vai para o formulário…
    assert "horario: horarioParaFormulario(location.horario, location.aberta_desde)," in texto
    # …uma loja nova começa sem horário…
    assert "horario: horarioParaFormulario(null, null)," in texto
    # …e o corpo do POST/PUT leva SEMPRE as duas chaves.
    assert "...formularioParaHorario(formData.horario)," in texto
    # 422 legível: nunca o array do Pydantic directo no toast.
    assert "toast.error(detalhesErro(error, 'Erro ao guardar local').mensagem);" in texto


def test_tocar_no_texto_do_horario_marca_a_caixa():
    # Medido no browser: sem id/htmlFor, tocar no texto não marcava a caixa — só a bolinha.
    texto = _LOCAIS.read_text(encoding="utf-8")
    marca = texto.index('data-testid="location-horario-tem"')
    caixa = texto[texto.rindex("<Checkbox", 0, marca):texto.index("/>", marca)]
    achado = re.search(r'\bid="([^"]+)"', caixa)
    assert achado, "O Checkbox location-horario-tem não tem id"
    rotulo = re.search(r'<label\b[^>]*\bhtmlFor="%s"[^>]*>(.*?)</label>' % re.escape(achado.group(1)), texto, re.S)
    assert rotulo, "Nenhum <label> com htmlFor=%r" % achado.group(1)
    assert "Esta loja tem horário" in rotulo.group(1)


def test_o_ecra_dos_locais_compila():
    _compila(_LOCAIS)


def test_o_formulario_das_escalas_carrega_e_manda_os_dias():
    texto = _ESCALAS.read_text(encoding="utf-8")
    # Ao editar, a loja e as horas de cada dia vão para o formulário…
    assert "porDia: diasParaFormulario(template.dias)," in texto
    # …e o MESMO corpo, com `dias` dos dias marcados, vai no criar e no editar.
    assert "dias: formularioParaDias(templateForm.workDays, templateForm.porDia)," in texto
    assert "await updateSchedule(editingTemplate.id, corpo);" in texto
    assert "await createSchedule(corpo);" in texto
    # A «Hora de início» continua lá: é o que o lembrete do ponto lê.
    assert "startTime: templateForm.startTime || null," in texto
    assert "toast.error(detalhesErro(error, 'Erro ao guardar escala').mensagem);" in texto
    # O seletor da loja só oferece lojas com horário (uma entrada noutra loja não conta
    # no calendário), mas não esconde a que já está escolhida.
    assert "locations.filter((loc) => loc.horario || loc.id === d.location_id).map((loc) => (" in texto


def test_o_ecra_das_escalas_compila():
    _compila(_ESCALAS)
