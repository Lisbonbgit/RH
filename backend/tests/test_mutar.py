"""A ferramenta da prova por mutação repõe SEMPRE o ficheiro — apanhe ou não apanhe."""
import sys

from tests import mutar

FALHA = [sys.executable, "-c", "import sys; sys.exit(1)"]
PASSA = [sys.executable, "-c", "import sys; sys.exit(0)"]


def test_mutacao_apanhada_devolve_0_e_repoe(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + FALHA) == 0
    assert f.read_text(encoding="utf-8") == "A = 1\n"


def test_mutacao_nao_apanhada_devolve_1_e_repoe(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + PASSA) == 1
    assert f.read_text(encoding="utf-8") == "A = 1\n"


def test_o_texto_tem_de_aparecer_exactamente_uma_vez(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\nA = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + FALHA) == 2
    assert mutar.main([str(f), "B = 1", "A = 2", "--"] + FALHA) == 2
    assert f.read_text(encoding="utf-8") == "A = 1\nA = 1\n"
