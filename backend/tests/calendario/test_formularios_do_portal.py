"""O que os formulários dos Locais e das Escalas mandam ao servidor.

A passagem entre o que o servidor guarda (`horario`, `aberta_desde`, `dias`) e o que o
ecrã mostra vive em `frontend/src/lib/horarios.js`. Aqui corre-se o ficheiro VERDADEIRO
em Node (o Babel só troca `export` por CommonJS) — nunca uma cópia, que ficaria verde
com o ecrã errado. Mais abaixo (Tarefas 6 e 7), os guardas de que os dois ecrãs o usam
mesmo: uma função pura testada não prova nada se a linha que a chama desaparecer.

Precisa de `frontend/node_modules` (o atalho para ~/Developer/RH/frontend/node_modules)
e de `node` (no PATH ou em ~/.local/node/bin); sem eles SALTA e diz porquê.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[3]
_FRONTEND = _RAIZ / "frontend"
_HORARIOS = _FRONTEND / "src" / "lib" / "horarios.js"
_LOCAIS = _FRONTEND / "src" / "pages" / "admin" / "AdminLocations.js"
_ESCALAS = _FRONTEND / "src" / "pages" / "admin" / "AdminSchedules.js"

BELEM = {
    "abre": "11:30", "fecha": "19:00",
    "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}],
    "fechada": [1],
}


def _node():
    caminho = shutil.which("node")
    if caminho:
        return caminho
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip("Sem `node` (nem no PATH nem em ~/.local/node/bin): o JavaScript dos formulários NÃO foi testado.")


def _no_node(guiao):
    if not (_FRONTEND / "node_modules" / "@babel" / "core").exists():
        pytest.skip("Sem frontend/node_modules: ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules")
    resultado = subprocess.run(
        [_node(), "-e", guiao],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(_FRONTEND),
        env={"NODE_PATH": str(_FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin"},
    )
    if resultado.returncode != 0:
        pytest.fail("O JavaScript não correu:\n" + resultado.stderr.decode("utf-8", "replace"))
    return json.loads(resultado.stdout.decode("utf-8"))


def _corre(expressao):
    """Avalia `expressao` (JavaScript, com `h` = o módulo lib/horarios.js) e devolve o JSON."""
    return _no_node("\n".join([
        "const fs = require('fs');",
        "const babel = require('@babel/core');",
        "const Module = require('module');",
        "const ficheiro = %s;" % json.dumps(str(_HORARIOS)),
        "const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],",
        "  filename: ficheiro, babelrc: false, configFile: false,",
        "}).code;",
        "const m = new Module(ficheiro, null);",
        "m._compile(codigo, ficheiro);",
        "const h = m.exports;",
        "process.stdout.write(JSON.stringify(%s));" % expressao,
    ]))


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
        "const fs = require('fs');",
        "const babel = require('@babel/core');",
        "const ficheiro = %s;" % json.dumps(str(ficheiro)),
        "babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "  presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],",
        "  filename: ficheiro, babelrc: false, configFile: false,",
        "});",
        "process.stdout.write('null');",
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


def test_o_ecra_dos_locais_compila():
    _compila(_LOCAIS)
