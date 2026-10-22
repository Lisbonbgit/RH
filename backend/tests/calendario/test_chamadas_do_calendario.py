"""O que as chamadas do calendário em `lib/bolso.js` levam: parâmetros e corpos. (O caminho
confronta-se com o servidor em `tests/fin/test_caminhos_do_bolso.py`.)"""
from tests.bolso_js import AXIOS_FABRICADO, correr_js


def test_as_chamadas_do_calendario_levam_o_que_o_servidor_espera(tmp_path):
    r = correr_js(
        "global.SERVIDOR = () => ({});\n"
        "const b = importar('lib/bolso');\n"
        "await b.getCalendario(2026, 10);\n"
        "await b.getContagem(2026);\n"
        "await b.criarIdas({ datas: ['2026-10-06'], location_id: 'l1', user_ids: ['u1'], inicio: '13:00', fim: '22:00' });\n"
        "await b.mudarIda('i1', { data: '2026-10-07', location_id: 'l1', user_id: 'u1', inicio: '13:00', fim: '22:00' });\n"
        "await b.apagarIda('i1');\n"
        "await b.trocar({ data: '2026-10-27', sai: 'u1', entra: 'u2', inicio: '14:00', fim: '23:00' });\n"
        "await b.trocarEntreSi({ data: '2026-10-27', uma: 'u1', outra: 'u2' });\n"
        "await b.desfazerTroca('t1');\n"
        "await b.getHistorico(2026, 10);\n"
        "devolve(REGISTO);",
        tmp_path, simulados={"axios": AXIOS_FABRICADO})
    assert r == [
        ["GET", "/calendario", None, {"ano": 2026, "mes": 10}],
        ["GET", "/calendario/contagem", None, {"ano": 2026}],
        ["POST", "/calendario/idas",
         {"datas": ["2026-10-06"], "location_id": "l1", "user_ids": ["u1"], "inicio": "13:00", "fim": "22:00"}, None],
        ["PUT", "/calendario/idas/i1",
         {"data": "2026-10-07", "location_id": "l1", "user_id": "u1", "inicio": "13:00", "fim": "22:00"}, None],
        ["DELETE", "/calendario/idas/i1", None, None],
        ["POST", "/calendario/trocas",
         {"data": "2026-10-27", "sai": "u1", "entra": "u2", "inicio": "14:00", "fim": "23:00"}, None],
        ["POST", "/calendario/trocas/entre-si", {"data": "2026-10-27", "uma": "u1", "outra": "u2"}, None],
        ["DELETE", "/calendario/trocas/t1", None, None],
        ["GET", "/calendario/historico", None, {"ano": 2026, "mes": 10}],
    ]
