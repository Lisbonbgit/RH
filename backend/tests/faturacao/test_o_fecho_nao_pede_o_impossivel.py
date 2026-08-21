"""O diálogo do fecho só pede o que a operadora consegue fazer.

**O defeito.** Uma conta ENTREGUE AO GESTOR (`venda.py::entregar_ao_gestor`)
cuja reserva fiscal ele já libertou chega ao ecrã do fecho com
`trava_o_fecho: false`, e caía no monte do "por cobrar" — debaixo da frase
«Se ainda houver quem pague, cobre-as antes de fechar; se ninguém pagar,
cancele-as». **Nenhuma das duas saídas é executável:** as escritas do balcão
recusam-na (`venda.py::_garante_do_balcao`) e ela não aparece em ecrã nenhum
do POS de onde se lhe possa tocar (`venda.py::_contas_do_balcao` exclui-a pela
marca). O servidor sempre mandou a marca — `entregue_ao_gestor` —, e o
`ContasPorCobrar` nunca a leu.

É a mesma família de defeito que a raiz desta ronda: um ecrã a pedir o que a
rota recusa. Aqui não custa dinheiro, custa uma tentativa falhada e um
telefonema, com a gaveta contada e a funcionária à espera de ir para casa.

O que este ficheiro guarda, e como:

- **a partição em TRÊS famílias, corrida em Node** — as três linhas do
  `PosFecharCaixa.js` são filtros puros, extraem-se do ficheiro e correm-se
  sobre uma grelha com todas as combinações de `trava_o_fecho` ×
  `entregue_ao_gestor`, incluindo as ausências (um servidor anterior a estes
  campos);
- **o euro de cada família, somado no SERVIDOR** — três subtotais que somam o
  total, para o ecrã nunca ter de subtrair um do outro em JavaScript (regra 1:
  o browser não faz aritmética de dinheiro).
"""
import json
import subprocess
from pathlib import Path

import pytest

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod

from .test_arredondamento_do_ecra import _RAIZ, _corpo_da_seta, _ler, _node
from .test_venda import (  # noqa: F401
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _reserva,
    _sessao,
    _venda,
)

_FECHAR = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosFecharCaixa.js"

_LINHA_TRAVAM = "const travam = todas.filter("
_LINHA_GESTOR = "const doGestor = todas.filter("
_LINHA_POR_COBRAR = "const porCobrar = todas.filter("


# --- A partição das três famílias, corrida ------------------------------------


def _familias(contas, tmp_path: Path):
    """Corre em Node as TRÊS linhas do ecrã, tal como estão escritas no
    ficheiro — nunca uma cópia delas aqui, que ficava verde no dia em que o
    ecrã mudasse, que é o dia que interessa."""
    ecra = _ler(_FECHAR)
    guiao = tmp_path / "familias.js"
    guiao.write_text("\n".join([
        "const todas = %s;" % json.dumps(contas),
        _corpo_da_seta(ecra, _LINHA_TRAVAM, _FECHAR),
        _corpo_da_seta(ecra, _LINHA_GESTOR, _FECHAR),
        _corpo_da_seta(ecra, _LINHA_POR_COBRAR, _FECHAR),
        "process.stdout.write(JSON.stringify({",
        "  travam: travam.map((c) => c.id),",
        "  doGestor: doGestor.map((c) => c.id),",
        "  porCobrar: porCobrar.map((c) => c.id),",
        "}));",
    ]), encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if resultado.returncode != 0:
        pytest.fail("O JavaScript do ecrã não correu:\n%s"
                    % resultado.stderr.decode("utf-8", "replace"))
    return json.loads(resultado.stdout.decode("utf-8"))


# Todas as combinações que o servidor pode mandar, incluindo as AUSÊNCIAS — um
# servidor anterior a estes campos não manda nem um nem outro, e o ecrã não
# pode passar a dizer que TODAS as contas travam o fecho (ou que são todas do
# gestor) por causa de uma chave que falta.
_GRELHA = [
    {"id": "so-por-cobrar", "trava_o_fecho": False, "entregue_ao_gestor": False},
    {"id": "trava", "trava_o_fecho": True, "entregue_ao_gestor": False},
    {"id": "do-gestor", "trava_o_fecho": False, "entregue_ao_gestor": True},
    {"id": "entregue-e-ainda-travada", "trava_o_fecho": True,
     "entregue_ao_gestor": True},
    {"id": "servidor-antigo"},
    {"id": "so-a-marca-antiga", "trava_o_fecho": False},
    {"id": "so-a-marca-do-gestor", "entregue_ao_gestor": True},
]


def test_a_conta_do_gestor_sai_do_monte_do_por_cobrar(tmp_path):
    """**O defeito, na linha em que ele vivia.** A conta entregue e já
    destravada tem de sair da família a quem o ecrã manda «cobre-as ou
    cancele-as» — nenhuma dessas saídas é executável sobre ela."""
    familias = _familias(_GRELHA, tmp_path)
    assert "do-gestor" not in familias["porCobrar"], (
        "A conta já entregue ao gestor continua no monte do «por cobrar», "
        "debaixo de uma frase que manda cobrá-la ou cancelá-la — e a rota "
        "recusa as duas coisas (`venda.py::_garante_do_balcao`)."
    )
    assert familias["doGestor"] == ["do-gestor", "so-a-marca-do-gestor"]


def test_a_que_IMPEDE_o_fecho_manda_sobre_a_marca_do_gestor(tmp_path):
    """Uma conta entregue que AINDA tem a reserva viva (o estado logo a seguir
    à entrega, antes de o gestor a libertar) pertence à família urgente: é a
    única sobre a qual carregar em FECHAR CAIXA devolve um erro. Contá-la nas
    duas punha o ecrã a dizer que há mais contas do que existem."""
    familias = _familias(_GRELHA, tmp_path)
    assert "entregue-e-ainda-travada" in familias["travam"]
    assert "entregue-e-ainda-travada" not in familias["doGestor"]
    assert "entregue-e-ainda-travada" not in familias["porCobrar"]


def test_as_tres_familias_sao_uma_particao(tmp_path):
    """Cada conta aparece em EXACTAMENTE uma família. Uma conta em duas caixas
    conta-se duas vezes no ecrã do fecho; uma conta em nenhuma desaparece do
    último sítio onde a operadora a podia ver antes de assinar."""
    familias = _familias(_GRELHA, tmp_path)
    vistas = familias["travam"] + familias["doGestor"] + familias["porCobrar"]
    assert sorted(vistas) == sorted(c["id"] for c in _GRELHA), (
        "As famílias não são uma partição: %s" % familias)


def test_um_servidor_anterior_a_estas_marcas_nao_assusta_ninguem(tmp_path):
    """A regra da comparação estrita (`=== true` / `!== true`), corrida em vez
    de afirmada: sem as chaves, a conta é uma conta normal por cobrar — nunca
    uma que impede o fecho nem uma que já é de outra pessoa."""
    familias = _familias([{"id": "servidor-antigo"}], tmp_path)
    assert familias == {
        "travam": [], "doGestor": [], "porCobrar": ["servidor-antigo"]}


# --- O euro de cada família, somado no servidor --------------------------------


def _op(**over):
    o = _operador(dispositivo_id="pc-balcao")
    o.update(over)
    return o


def _conta(**over):
    v = _venda(dispositivo_id="pc-balcao", linhas=[_linha()],
               entregue_ao_gestor_em=None, criada_em="2026-08-21T10:00:00+00:00")
    v.update(over)
    return v


def test_cada_familia_traz_o_seu_euro_e_os_tres_somam_o_total(monkeypatch):
    """O ecrã escreve um euro em cima de cada caixa e **não pode somar nem
    subtrair nenhum deles** (regra 1: o browser não faz aritmética de
    dinheiro). Por isso os três subtotais saem do servidor já fechados ao
    cêntimo, e os três somam o total.

    `total_por_cobrar` NÃO muda de significado — continua a ser tudo o que não
    trava, que é o que já está gravado nos Z assinados; `total_do_balcao` e
    `total_do_gestor` são as duas metades dele."""
    # Três contas de 8,99 €: uma normal, uma travada, uma entregue e destravada.
    db = _db(
        [],
        caixas=[_caixa()],
        sessoes=[_sessao()],
        vendas=[
            _conta(id="v-balcao"),
            _conta(id="v-travada"),
            _conta(id="v-gestor",
                   entregue_ao_gestor_em="2026-08-21T10:20:00+00:00"),
        ],
        refs=[_reserva(venda_id="v-travada")],
        produtos=[_produto()],
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda: db)

    # A pergunta faz-se à função que os DOIS momentos usam — o
    # `GET /pos/caixa/contas-abertas` (o aviso ANTES de fechar) e o retrato que
    # o Z grava. `fechar_caixa` não serve aqui: com uma reserva viva na conta
    # travada, ele recusa, e é essa a resposta certa (ver
    # `test_reserva_viva_trava_o_fecho.py`).
    abertas = _corre(caixa_mod._contas_abertas_da_sessao(
        db, "sessao-1", dispositivo_id="pc-balcao"))

    assert abertas["total"] == 26.97
    assert abertas["total_que_trava"] == 8.99
    assert abertas["total_por_cobrar"] == 17.98
    assert abertas["total_do_balcao"] == 8.99, (
        "O euro da caixa «fica por cobrar neste turno» ainda inclui a conta "
        "que já é do gestor: o ecrã escreve %s por cima de uma lista mais "
        "curta e contradiz-se." % abertas["total_do_balcao"])
    assert abertas["total_do_gestor"] == 8.99
    assert abertas["quantas_do_gestor"] == 1
    assert round(
        abertas["total_que_trava"]
        + abertas["total_do_balcao"]
        + abertas["total_do_gestor"], 2) == abertas["total"], (
        "As três famílias já não somam o total do retrato — há dinheiro numa "
        "caixa que o ecrã não desenha, ou contado duas vezes.")


def test_a_conta_entregue_que_ainda_trava_conta_so_uma_vez(monkeypatch):
    """A mesma regra do ecrã, do lado do servidor: entregue E travada é da
    família urgente e não entra no euro do gestor."""
    db = _db(
        [],
        caixas=[_caixa()],
        sessoes=[_sessao()],
        vendas=[_conta(id="v-1",
                       entregue_ao_gestor_em="2026-08-21T10:20:00+00:00")],
        refs=[_reserva(venda_id="v-1")],
        produtos=[_produto()],
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda: db)

    # O fecho recusa (a reserva está viva), por isso a pergunta faz-se à função
    # que o ecrã do «antes de fechar» também usa.
    abertas = _corre(caixa_mod._contas_abertas_da_sessao(
        db, "sessao-1", dispositivo_id="pc-balcao"))
    assert abertas["quantas_travam"] == 1
    assert abertas["quantas_do_gestor"] == 0
    assert abertas["total_do_gestor"] == 0.0
    assert abertas["total_do_balcao"] == 0.0
