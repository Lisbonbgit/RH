"""O gravador das respostas do openrouteservice (plano F3, T3.12; correções
"T3.12 / T3.43").

O gravador só corre pelas mãos do dono (§0, regra 2). Estes testes nunca vão à
rede: o "openrouteservice" é um `httpx.MockTransport` escrito aqui
(`ServidorFalso`), que responde a cada cenário pelo conteúdo do pedido e
regista os pedidos. Além disso, um fixture `autouse` deste ficheiro
(`guarda_contra_a_rede`) instala por omissão um transporte que só regista e
responde 599, e corta o transporte verdadeiro do httpx e os `socket` (DNS e
ligações): um teste (ou uma mutação) que se esqueça do transporte falha no fim,
sem nunca chegar a `api.openrouteservice.org` — o gravador usa SEMPRE o URL
oficial, por isso a guarda tem de estar por baixo do próprio gravador.

As respostas "boas" são as fixtures escritas à mão da T3.6/T3.7 (sem o
`_origem`); cada teste grava numa cópia da pasta das fixtures (`tmp_path`),
nunca na verdadeira.
"""
import json
import logging
import os
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import gravar_respostas_ors as gravador
from crm import relogio
from crm.dominio import directions, horas, polilinha, vroom

FIXTURES = Path(__file__).parent / "fixtures" / "ors"

# A chave canária: nunca pode aparecer na saída, nos registos, no URL nem no corpo.
CHAVE = "canaria-do-gravador-0123456789abcdef"

URL_OTIMIZACAO = "https://api.openrouteservice.org/optimization"
URL_DIRECOES = "https://api.openrouteservice.org/v2/directions/driving-car/json"

NOMES = ["otimizacao-todas", "otimizacao-uma-nao-cabe", "direcoes-tres-paragens", "direcoes-erro-2010"]
URLS = [URL_OTIMIZACAO, URL_OTIMIZACAO, URL_DIRECOES, URL_DIRECOES]

# 23:30 em UTC a 15 de julho já é dia 16 em Lisboa (WEST, UTC+1): o `_origem`
# leva a data de Lisboa (`relogio.hoje`), não a de UTC nem a do relógio do Mac.
AGORA = datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)
ORIGEM = "gravado em 2026-07-16 (gravar_respostas_ors.py)"

MENSAGEM_DA_GUARDA = "pedido ao openrouteservice sem o transporte do teste"


# --- A guarda contra a rede ------------------------------------------------------------------


def guarda_contra_a_rede(monkeypatch):
    """O gerador do fixture `autouse`, à parte para os meta-testes o poderem
    chamar à mão. Dá a lista do que chegou à guarda e, no fim, exige que esteja
    vazia."""
    pedidos = []

    def _guarda(pedido):
        pedidos.append(str(pedido.url))
        return httpx.Response(599)

    def _sem_rede(*_args, **_kwargs):
        pedidos.append("rede verdadeira")
        raise AssertionError(MENSAGEM_DA_GUARDA)

    monkeypatch.setattr(gravador, "_transporte", httpx.MockTransport(_guarda))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _sem_rede)
    monkeypatch.setattr(socket, "create_connection", _sem_rede)
    monkeypatch.setattr(socket, "getaddrinfo", _sem_rede)
    yield pedidos
    assert pedidos == [], MENSAGEM_DA_GUARDA


@pytest.fixture(autouse=True)
def pedidos_sem_transporte(monkeypatch):
    """Em todos os testes deste ficheiro: a guarda contra a rede."""
    yield from guarda_contra_a_rede(monkeypatch)


@pytest.fixture(autouse=True)
def ambiente_intacto(monkeypatch):
    """O `os.environ` volta a ser o de antes (um gravador que escrevesse no
    ambiente não contaminava os testes seguintes), sem `CRM_ORS_*` da shell."""
    monkeypatch.delenv("CRM_ORS_CHAVE", raising=False)
    monkeypatch.delenv("CRM_ORS_URL", raising=False)
    antes = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(antes)


@pytest.fixture(autouse=True)
def relogio_fixo(monkeypatch):
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)


# --- O openrouteservice escrito à mão --------------------------------------------------------


def _ler(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


def _sem_origem(dados):
    return {chave: valor for chave, valor in dados.items() if chave != "_origem"}


def _respostas_boas():
    """`{cenário: (estado, corpo)}`: as fixtures da T3.6/T3.7 sem o `_origem`.
    A primeira leva um texto com acentos (gravado tal e qual, `ensure_ascii=False`)."""
    todas = _sem_origem(_ler("otimizacao-todas.json"))
    todas["metadata"] = {"service": "optimization", "nota_do_teste": "Praça do Comércio"}
    return {
        "otimizacao-todas": (200, todas),
        "otimizacao-uma-nao-cabe": (200, _sem_origem(_ler("otimizacao-uma-nao-cabe.json"))),
        "direcoes-tres-paragens": (200, _sem_origem(_ler("direcoes-tres-paragens.json"))),
        "direcoes-erro-2010": (404, _sem_origem(_ler("direcoes-erro-2010.json"))),
    }


def _cenario_do_pedido(pedido):
    """Que cenário é este pedido (pelo URL e pelo corpo), ou `None`."""
    try:
        corpo = json.loads(pedido.content)
        if str(pedido.url) == URL_OTIMIZACAO:
            torre = next(job for job in corpo["jobs"] if job["id"] == 3)
            return "otimizacao-uma-nao-cabe" if "time_windows" in torre else "otimizacao-todas"
        if str(pedido.url) == URL_DIRECOES:
            return "direcoes-tres-paragens" if len(corpo["coordinates"]) == 5 else "direcoes-erro-2010"
    except (ValueError, KeyError, TypeError, StopIteration):
        return None
    return None


class ServidorFalso:
    """Responde a cada cenário com `respostas[cenário]`: `(estado, corpo)` (um
    `dict`/lista vai como JSON, `bytes` tal e qual), uma exceção (levantada) ou
    uma função do pedido. Um pedido desconhecido leva 418."""

    def __init__(self, **trocas):
        self.pedidos = []
        self.respostas = {**_respostas_boas(), **{nome.replace("_", "-"): valor for nome, valor in trocas.items()}}

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        nome = _cenario_do_pedido(pedido)
        if nome is None:
            return httpx.Response(418)
        resposta = self.respostas[nome]
        if isinstance(resposta, Exception):
            raise resposta
        if callable(resposta):
            return resposta(pedido)
        estado, corpo = resposta
        if isinstance(corpo, bytes):
            return httpx.Response(estado, content=corpo)
        return httpx.Response(estado, json=corpo)


def _instalar(monkeypatch, servidor=None):
    servidor = servidor or ServidorFalso()
    monkeypatch.setattr(gravador, "_transporte", httpx.MockTransport(servidor))
    return servidor


# --- Ajudas ----------------------------------------------------------------------------------


def _pasta(tmp_path):
    """Uma cópia da pasta das fixtures, onde o gravador escreve."""
    destino = tmp_path / "ors"
    shutil.copytree(FIXTURES, destino)
    return destino


def _env(tmp_path, texto=f"CRM_ORS_CHAVE={CHAVE}\n", modo=0o600):
    caminho = tmp_path / ".env.ors"
    caminho.write_text(texto, encoding="utf-8")
    caminho.chmod(modo)
    return caminho


def _correr(pasta, env):
    return gravador.principal(["--env-file", str(env), "--pasta", str(pasta)])


def _conteudos(pasta):
    """Tudo o que está na pasta: `{nome: bytes}` (as pastas como `None`)."""
    return {p.name: (None if p.is_dir() else p.read_bytes()) for p in sorted(pasta.iterdir())}


def _saidas(capsys):
    """`(stdout, stderr)`, verificando que a chave não aparece em nenhuma."""
    saida = capsys.readouterr()
    assert CHAVE not in saida.out and CHAVE not in saida.err
    return saida.out, saida.err


def _temporarios(pasta):
    return sorted(p.name for p in pasta.iterdir() if p.name.endswith(".tmp"))


def _cenarios():
    return _ler("cenarios.json")


def _par(nome):
    ponto = _cenarios()["pontos"][nome]
    return (ponto["lat"], ponto["lng"])


def _pedido_otimizacao(nome):
    """O pedido de um cenário, como os testes da T3.6 o montam."""
    pontos = _cenarios()["pontos"]
    cenario = _cenarios()["otimizacao"][nome]
    calculo = [
        vroom.paragem_calculo(
            {"id": p["ponto"], "motivo": p["motivo"], "tempo_servico_min": p["tempo_servico_min"]},
            {**pontos[p["ponto"]], "janelas": p["janelas"]},
        )
        for p in cenario["paragens"]
    ]
    return vroom.pedido_otimizacao(
        calculo, _par(cenario["inicio"]), _par(cenario["fim"]),
        horas.segundos(cenario["saida"]), horas.segundos(cenario["limite"]),
    )


def _corpo_direcoes(nome):
    cenario = _cenarios()["direcoes"][nome]
    return directions.pedido_direcoes([_par(p) for p in cenario["pontos"]], cenario["evitar_portagens"])


def _corpos_esperados():
    return {
        "otimizacao-todas": _pedido_otimizacao("otimizacao-todas").corpo,
        "otimizacao-uma-nao-cabe": _pedido_otimizacao("otimizacao-uma-nao-cabe").corpo,
        "direcoes-tres-paragens": _corpo_direcoes("direcoes-tres-paragens"),
        "direcoes-erro-2010": _corpo_direcoes("direcoes-erro-2010"),
    }


# --- Constantes ------------------------------------------------------------------------------


def test_a_lista_fechada_e_o_url_oficial():
    """Correção "T3.12 / T3.43": só estes quatro; o `erro-429.json` fica sempre manual."""
    assert list(gravador.GRAVAVEIS) == NOMES
    assert gravador.URL_OFICIAL == "https://api.openrouteservice.org"
    assert gravador.CHAVE_DO_SIMULADOR == "simulador-local"
    assert gravador.PASTA_POR_OMISSAO == Path(__file__).resolve().parent / "fixtures" / "ors"


def test_o_env_file_e_obrigatorio(capsys):
    with pytest.raises(SystemExit) as saida:
        gravador.principal([])
    assert saida.value.code == 2
    capsys.readouterr()


# --- A chave ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    ["", "CRM_ORS_CHAVE=\n", "CRM_ORS_CHAVE=   \n", 'CRM_ORS_CHAVE=""\n', "CRM_ORS_CHAVE\n", "OUTRA=1\n",
     f"# CRM_ORS_CHAVE={CHAVE}\n", f"CRM_ORS_URL=https://api.openrouteservice.org\nCRM_ORS_CHAVE_X={CHAVE}\n"],
)
def test_sem_chave_sai_com_1_sem_pedidos_nem_ficheiros(tmp_path, monkeypatch, capsys, texto):
    servidor = _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path, texto)) == 1
    _, erros = _saidas(capsys)
    assert erros.splitlines()[0] == "Falta a CRM_ORS_CHAVE no ficheiro indicado."
    assert servidor.pedidos == []
    assert _conteudos(pasta) == antes


def test_a_chave_da_shell_nao_conta(tmp_path, monkeypatch, capsys):
    """Lê só o ficheiro indicado (`dotenv_values`), nunca o `os.environ`."""
    servidor = _instalar(monkeypatch)
    monkeypatch.setenv("CRM_ORS_CHAVE", CHAVE)
    assert _correr(_pasta(tmp_path), _env(tmp_path, "OUTRA=1\n")) == 1
    _, erros = _saidas(capsys)
    assert "Falta a CRM_ORS_CHAVE no ficheiro indicado." in erros
    assert servidor.pedidos == []


def test_sem_interpolacao_a_partir_da_shell(tmp_path, monkeypatch, capsys):
    """`${VAR}` no ficheiro não vai buscar nada ao ambiente (`interpolate=False`):
    o valor fica o texto literal, que não é uma chave."""
    servidor = _instalar(monkeypatch)
    monkeypatch.setenv("CHAVE_DA_SHELL", CHAVE)
    assert _correr(_pasta(tmp_path), _env(tmp_path, "CRM_ORS_CHAVE=${CHAVE_DA_SHELL}\n")) == 1
    _, erros = _saidas(capsys)
    assert "não parece uma chave" in erros
    assert servidor.pedidos == []


def test_ficheiro_que_nao_existe(tmp_path, monkeypatch, capsys):
    servidor = _instalar(monkeypatch)
    assert _correr(_pasta(tmp_path), tmp_path / "nao-existe.env") == 1
    _, erros = _saidas(capsys)
    assert erros.startswith("Não encontrei o ficheiro ")
    assert servidor.pedidos == []


@pytest.mark.parametrize(
    "texto",
    [
        "CRM_ORS_CHAVE=simulador-local\n",
        'CRM_ORS_CHAVE="simulador-local"\n',
        "CRM_ORS_URL=http://127.0.0.1:8013\nCRM_ORS_CHAVE=simulador-local\n",
        "export CRM_ORS_CHAVE=simulador-local\n",
    ],
)
def test_a_chave_do_simulador_e_recusada(tmp_path, monkeypatch, capsys, texto):
    """Correções "T3.12 / T3.43": o `.env.local` da pré-visualização tem a chave
    do simulador; nunca vai ao openrouteservice verdadeiro."""
    servidor = _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path, texto)) == 1
    _, erros = _saidas(capsys)
    assert erros.splitlines()[0] == "A CRM_ORS_CHAVE do ficheiro é a do simulador."
    assert ".env.ors" in erros  # diz onde pôr a chave de desenvolvimento
    assert servidor.pedidos == []
    assert _conteudos(pasta) == antes


@pytest.mark.parametrize(
    "chave",
    [
        "curta-demais", "com espaço-0123456789abcdef", "com\ttab-0123456789abcdefgh", "acentuação-0123456789abcdef",
        "com'aspas-0123456789abcdefgh", "com\\barra-0123456789abcdefgh", "com&e-comercial-0123456789abc",
    ],
)
def test_uma_chave_que_nao_pode_ir_num_cabecalho_e_recusada(tmp_path, monkeypatch, capsys, chave):
    servidor = _instalar(monkeypatch)
    assert _correr(_pasta(tmp_path), _env(tmp_path, f'CRM_ORS_CHAVE="{chave}"\n')) == 1
    saida = capsys.readouterr()
    assert chave not in saida.out + saida.err
    assert "não parece uma chave" in saida.err
    assert servidor.pedidos == []


def test_aviso_quando_o_ficheiro_pode_ser_lido_por_outros(tmp_path, monkeypatch, capsys):
    """O dono guarda a chave num ficheiro próprio com o modo 600 (correção
    "T3.12 / T3.43"); com outro modo, um aviso (grava na mesma)."""
    _instalar(monkeypatch)
    assert _correr(_pasta(tmp_path), _env(tmp_path, modo=0o644)) == 0
    _, erros = _saidas(capsys)
    assert "chmod 600" in erros


def test_sem_aviso_com_o_modo_600(tmp_path, monkeypatch, capsys):
    _instalar(monkeypatch)
    assert _correr(_pasta(tmp_path), _env(tmp_path)) == 0
    _, erros = _saidas(capsys)
    assert erros == ""


# --- Com sucesso -----------------------------------------------------------------------------


def test_com_sucesso_grava_os_quatro_ficheiros(tmp_path, monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")
    servidor = _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)

    assert _correr(pasta, _env(tmp_path)) == 0

    saida, erros = _saidas(capsys)
    assert saida.splitlines() == [f"Gravado: {nome}.json" for nome in NOMES]  # só os nomes
    assert erros == ""
    assert CHAVE not in caplog.text
    assert _temporarios(pasta) == []

    depois = _conteudos(pasta)
    assert set(depois) == set(antes)
    for nome in set(antes) - {f"{n}.json" for n in NOMES}:  # cenarios, erro-429, ponto-repetido
        assert depois[nome] == antes[nome], nome

    for nome, (_, servido) in _respostas_boas().items():
        texto = (pasta / f"{nome}.json").read_text(encoding="utf-8")
        assert texto.startswith('{\n  "_origem": "' + ORIGEM + '",\n')
        assert texto.endswith("}\n") and not texto.endswith("\n\n")
        dados = json.loads(texto)
        assert list(dados)[0] == "_origem"
        assert dados == {"_origem": ORIGEM, **servido}
        assert texto == json.dumps(dados, ensure_ascii=False, indent=2) + "\n"
    assert "Praça do Comércio" in (pasta / "otimizacao-todas.json").read_text(encoding="utf-8")


def test_os_ficheiros_gravados_leem_se_como_nos_testes_das_fixtures(tmp_path, monkeypatch, capsys):
    """Os mesmos testes da forma e dos conjuntos da T3.6/T3.7, sobre o que se gravou."""
    _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    assert _correr(pasta, _env(tmp_path)) == 0
    _saidas(capsys)

    def gravado(nome):
        return json.loads((pasta / f"{nome}.json").read_text(encoding="utf-8"))

    for nome, de_fora in (("otimizacao-todas", []), ("otimizacao-uma-nao-cabe", ["torre_de_belem"])):
        pedido = _pedido_otimizacao(nome)
        ordem, nao_atribuidas = vroom.interpretar_otimizacao(gravado(nome), pedido.por_job)
        assert nao_atribuidas == de_fora
        assert sorted(ordem + nao_atribuidas) == sorted(pedido.por_job.values())

    pontos = _cenarios()["direcoes"]["direcoes-tres-paragens"]["pontos"]
    trocos = directions.interpretar_direcoes(gravado("direcoes-tres-paragens"), len(pontos))
    assert len(trocos.duracoes) == len(pontos) - 1
    assert len(polilinha.descodificar(trocos.geometria)) >= 2

    erro = gravado("direcoes-erro-2010")
    assert erro["_origem"] == ORIGEM and erro["error"]["code"] == 2010


def test_os_pedidos_vao_ao_url_oficial_com_a_chave_so_no_cabecalho(tmp_path, monkeypatch, capsys):
    servidor = _instalar(monkeypatch)
    assert _correr(_pasta(tmp_path), _env(tmp_path)) == 0
    _saidas(capsys)

    assert [str(p.url) for p in servidor.pedidos] == URLS
    esperados = _corpos_esperados()
    for nome, pedido in zip(NOMES, servidor.pedidos):
        assert pedido.method == "POST"
        assert pedido.headers["Authorization"] == CHAVE
        assert pedido.headers["Content-Type"] == "application/json"
        assert pedido.headers["Accept"] == "application/json"
        assert CHAVE not in str(pedido.url)
        assert CHAVE.encode() not in pedido.content
        assert json.loads(pedido.content) == esperados[nome]
        # Só coordenadas e números: nenhum nome de ponto vai ao ORS (§0, regra 12). Os nomes
        # inteiros: "rio" sozinho está dentro de "priority".
        assert all(ponto.encode() not in pedido.content for ponto in _cenarios()["pontos"])
        assert b"fabrica" not in pedido.content and b"torre" not in pedido.content


def test_o_url_e_sempre_o_oficial_mesmo_com_o_crm_ors_url(tmp_path, monkeypatch, capsys):
    """Ignora o `CRM_ORS_URL` do ficheiro e o da shell (o simulador da T3.13, ou um engano)."""
    servidor = _instalar(monkeypatch)
    monkeypatch.setenv("CRM_ORS_URL", "http://exemplo.invalid")
    texto = f"CRM_ORS_URL=http://127.0.0.1:8013\nCRM_ORS_CHAVE={CHAVE}\n"
    assert _correr(_pasta(tmp_path), _env(tmp_path, texto)) == 0
    _saidas(capsys)
    assert [str(p.url) for p in servidor.pedidos] == URLS


def test_nao_mexe_no_os_environ(tmp_path, monkeypatch, capsys):
    _instalar(monkeypatch)
    antes = dict(os.environ)
    texto = f"CRM_ORS_CHAVE={CHAVE}\nCRM_ORS_URL=http://127.0.0.1:8013\nOUTRA_DO_FICHEIRO=1\n"
    assert _correr(_pasta(tmp_path), _env(tmp_path, texto)) == 0
    _saidas(capsys)
    assert dict(os.environ) == antes
    assert CHAVE not in os.environ.values()


def test_o_origem_da_resposta_e_substituido(tmp_path, monkeypatch, capsys):
    corpo = {"_origem": "outra coisa", **_respostas_boas()["otimizacao-uma-nao-cabe"][1]}
    _instalar(monkeypatch, ServidorFalso(otimizacao_uma_nao_cabe=(200, corpo)))
    pasta = _pasta(tmp_path)
    assert _correr(pasta, _env(tmp_path)) == 0
    _saidas(capsys)
    dados = json.loads((pasta / "otimizacao-uma-nao-cabe.json").read_text(encoding="utf-8"))
    assert list(dados)[0] == "_origem" and dados["_origem"] == ORIGEM


def test_o_erro_2010_no_formato_antigo_tambem_se_grava(tmp_path, monkeypatch, capsys):
    corpo = {"error": {"code": 2010, "message": "Could not find point 2: -9.0350000 38.7200000 within a radius of 350.0 meters."}}
    _instalar(monkeypatch, ServidorFalso(direcoes_erro_2010=(400, corpo)))
    pasta = _pasta(tmp_path)
    assert _correr(pasta, _env(tmp_path)) == 0
    _saidas(capsys)
    assert json.loads((pasta / "direcoes-erro-2010.json").read_text(encoding="utf-8")) == {"_origem": ORIGEM, **corpo}


# --- Tudo ou nada: um pedido que falha --------------------------------------------------------

FALHAS = {
    "sem resposta": (httpx.ConnectError("sem ligação"), "sem resposta: ConnectError"),
    "tempo esgotado": (httpx.ReadTimeout("devagar"), "sem resposta: ReadTimeout"),
    "estado 500": ((500, {"error": "Internal Server Error"}), "estado HTTP 500"),
    "estado 401": ((401, {"error": "Access to this API has been disallowed"}), "chave recusada ou quota diária esgotada"),
    "estado 403": ((403, {"error": "Quota exceeded"}), "chave recusada ou quota diária esgotada"),
    "estado 429": ((429, {"error": "Rate limit exceeded"}), "limite de pedidos"),
    "redireção": ((301, b""), "estado HTTP 301"),
    "não é JSON": ((200, b"<html>"), None),
    "uma lista": ((200, []), None),
    "NaN": ((200, b'{"code": NaN}'), None),
}


@pytest.mark.parametrize("posicao", range(4))
@pytest.mark.parametrize("falha", list(FALHAS))
def test_um_pedido_que_falha_nao_muda_nenhum_ficheiro(tmp_path, monkeypatch, capsys, posicao, falha):
    resposta, texto = FALHAS[falha]
    nome = NOMES[posicao]
    servidor = _instalar(monkeypatch, ServidorFalso(**{nome.replace("-", "_"): resposta}))
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)

    assert _correr(pasta, _env(tmp_path)) == 1

    saida, erros = _saidas(capsys)
    assert saida == ""
    assert nome in erros and "não se gravou nada" in erros
    if texto is not None and not (posicao == 3 and falha == "estado 500"):  # no 2010, um 500 é lido como o erro
        assert texto in erros
    assert _conteudos(pasta) == antes
    assert _temporarios(pasta) == []
    assert len(servidor.pedidos) == posicao + 1  # pára no primeiro que falha


def test_nao_segue_redirecoes(tmp_path, monkeypatch, capsys):
    def redirecionar(_pedido):
        return httpx.Response(307, headers={"Location": URL_OTIMIZACAO})

    servidor = _instalar(monkeypatch, ServidorFalso(otimizacao_todas=redirecionar))
    assert _correr(_pasta(tmp_path), _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "estado HTTP 307" in erros
    assert len(servidor.pedidos) == 1


def test_os_registos_nunca_tem_a_chave_numa_falha(tmp_path, monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")
    _instalar(monkeypatch, ServidorFalso(direcoes_tres_paragens=httpx.ConnectError(f"falhou com {CHAVE}")))
    assert _correr(_pasta(tmp_path), _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "sem resposta: ConnectError" in erros
    assert CHAVE not in caplog.text


# --- Respostas que não servem ----------------------------------------------------------------


def _com(nome, **trocas):
    estado, corpo = _respostas_boas()[nome]
    return (estado, {**corpo, **trocas})


def _sem(nome, chave):
    estado, corpo = _respostas_boas()[nome]
    return (estado, {k: v for k, v in corpo.items() if k != chave})


def _otimizacao_com_todas_atribuidas():
    """Para o "uma-nao-cabe": a resposta do "todas" (os mesmos 3 *jobs*, pela
    mesma ordem), que atribui a Torre de Belém."""
    return _respostas_boas()["otimizacao-todas"]


def _otimizacao_com_a_torre_de_fora():
    """Para o "todas": a resposta do "uma-nao-cabe", com a Torre de Belém de fora."""
    return _respostas_boas()["otimizacao-uma-nao-cabe"]


def _direcoes_com_um_troco_vazio():
    estado, corpo = _respostas_boas()["direcoes-tres-paragens"]
    corpo = json.loads(json.dumps(corpo))
    segmento = corpo["routes"][0]["segments"][1]
    segmento.pop("distance")
    segmento.pop("duration")
    return (estado, corpo)


def _erro(estado, codigo, mensagem):
    return (estado, {"error": {"code": codigo, "message": mensagem}})


RESPOSTAS_QUE_NAO_SERVEM = {
    "otimizacao sem routes": ("otimizacao-todas", _sem("otimizacao-todas", "routes"), "não tem a forma esperada"),
    "otimizacao com code 1": ("otimizacao-todas", _com("otimizacao-todas", code=1), "não tem a forma esperada"),
    "todas com a torre de fora": ("otimizacao-todas", _otimizacao_com_a_torre_de_fora(), "não bate certo com o cenário"),
    "uma-nao-cabe com todas": ("otimizacao-uma-nao-cabe", _otimizacao_com_todas_atribuidas(), "não bate certo com o cenário"),
    "direcoes sem routes": ("direcoes-tres-paragens", _sem("direcoes-tres-paragens", "routes"), "não tem a forma esperada"),
    "direcoes com um troço vazio": ("direcoes-tres-paragens", _direcoes_com_um_troco_vazio(), "não bate certo com o cenário"),
    "2010 que veio com rota": ("direcoes-erro-2010", (200, _respostas_boas()["direcoes-tres-paragens"][1]), "em vez do erro 2010"),
    "2010 com outro código": ("direcoes-erro-2010", _erro(404, 2009, "Route could not be found between coordinate 1 and 2."), "erro 2010"),
    "2010 com o código em texto": ("direcoes-erro-2010", _erro(404, "2010", "… specified coordinate 2: …"), "erro 2010"),
    "2010 com o código bool": ("direcoes-erro-2010", (404, {"error": {"code": True, "message": "coordinate 2"}}), "erro 2010"),
    "2010 sem mensagem": ("direcoes-erro-2010", (404, {"error": {"code": 2010}}), "erro 2010"),
    "2010 com o erro em texto": ("direcoes-erro-2010", (404, {"error": "Could not find routable point"}), "erro 2010"),
    "2010 sem o número": ("direcoes-erro-2010", _erro(404, 2010, "Could not find routable point."), "ponto do rio"),
    "2010 noutra coordenada": ("direcoes-erro-2010", _erro(404, 2010, "… of specified coordinate 1: -9.15 38.72."), "ponto do rio"),
    "2010 contado a partir de 1": ("direcoes-erro-2010", _erro(404, 2010, "… of specified coordinate 3: -9.035 38.72."), "ponto do rio"),
}


@pytest.mark.parametrize("caso", list(RESPOSTAS_QUE_NAO_SERVEM))
def test_uma_resposta_que_nao_serve_nao_grava_nada(tmp_path, monkeypatch, capsys, caso):
    nome, resposta, texto = RESPOSTAS_QUE_NAO_SERVEM[caso]
    _instalar(monkeypatch, ServidorFalso(**{nome.replace("-", "_"): resposta}))
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    saida, erros = _saidas(capsys)
    assert saida == ""
    assert nome in erros and texto in erros and "não se gravou nada" in erros
    assert _conteudos(pasta) == antes
    assert _temporarios(pasta) == []


@pytest.mark.parametrize("nome", NOMES)
@pytest.mark.parametrize("onde", ["no corpo", "num texto"])
def test_a_chave_numa_resposta_nao_grava_nada(tmp_path, monkeypatch, capsys, nome, onde):
    estado, corpo = _respostas_boas()[nome]
    if onde == "no corpo":
        corpo = {**corpo, "metadata": {"query": {"api_key": CHAVE}}}
    else:
        corpo = {**corpo, "info": f"pedido de {CHAVE} às 10:00"}
    _instalar(monkeypatch, ServidorFalso(**{nome.replace("-", "_"): (estado, corpo)}))
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert f"A resposta para {nome} traz a chave; não se gravou nada." in erros
    assert _conteudos(pasta) == antes


def test_a_chave_so_no_origem_da_resposta_tambem_conta(tmp_path, monkeypatch, capsys):
    """O `_origem` da resposta não se grava (é substituído), mas "a chave em
    qualquer resposta" chega para não gravar nada: procura-se no corpo tal como veio."""
    estado, corpo = _respostas_boas()["direcoes-tres-paragens"]
    _instalar(monkeypatch, ServidorFalso(direcoes_tres_paragens=(estado, {"_origem": f"eco {CHAVE}", **corpo})))
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "A resposta para direcoes-tres-paragens traz a chave; não se gravou nada." in erros
    assert _conteudos(pasta) == antes


def test_a_chave_escrita_com_escapes_no_json_tambem_conta(tmp_path, monkeypatch, capsys):
    """No corpo vem `\\u0063anaria…` (não está lá tal e qual), mas depois de lido
    é a chave: procura-se também no texto que se ia gravar."""
    estado, corpo = _respostas_boas()["otimizacao-todas"]
    texto = json.dumps({**corpo, "info": CHAVE}).replace(CHAVE, "\\u0063" + CHAVE[1:])
    assert CHAVE not in texto
    _instalar(monkeypatch, ServidorFalso(otimizacao_todas=(estado, texto.encode())))
    pasta = _pasta(tmp_path)
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "A resposta para otimizacao-todas traz a chave; não se gravou nada." in erros
    assert _conteudos(pasta) == antes


# --- Tudo ou nada: a escrita ------------------------------------------------------------------


def test_uma_falha_ao_escrever_nao_muda_nenhum_ficheiro(tmp_path, monkeypatch, capsys):
    """O temporário do último não se consegue escrever (uma pasta com esse
    nome): os outros temporários apagam-se e nenhum ficheiro muda."""
    _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    (pasta / ".direcoes-erro-2010.json.tmp").mkdir()
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    saida, erros = _saidas(capsys)
    assert saida == ""
    assert "direcoes-erro-2010.json" in erros and "não se gravou nada" in erros
    assert _conteudos(pasta) == antes
    assert _temporarios(pasta) == [".direcoes-erro-2010.json.tmp"]  # a pasta, que não é dele


def test_uma_falha_ao_por_no_lugar_diz_o_que_ficou_gravado(tmp_path, monkeypatch, capsys):
    """Raro (o PHP do autónomo faz o mesmo): o último não se põe no lugar
    porque há uma pasta com esse nome. Os três primeiros já foram; diz quais,
    sai com 1 e não deixa temporários."""
    _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    (pasta / "direcoes-erro-2010.json").unlink()
    (pasta / "direcoes-erro-2010.json").mkdir()
    (pasta / "direcoes-erro-2010.json" / "dentro").write_text("x", encoding="utf-8")
    assert _correr(pasta, _env(tmp_path)) == 1
    saida, erros = _saidas(capsys)
    assert saida.splitlines() == [f"Gravado: {nome}.json" for nome in NOMES[:3]]
    assert "direcoes-erro-2010.json" in erros
    assert "otimizacao-todas.json, otimizacao-uma-nao-cabe.json, direcoes-tres-paragens.json" in erros
    assert _temporarios(pasta) == []


# --- O cenarios.json --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "estragar",
    [
        lambda c: c.pop("direcoes"),
        lambda c: c["otimizacao"].pop("otimizacao-todas"),
        lambda c: c["pontos"].pop("rio_tejo"),
        lambda c: c["otimizacao"]["otimizacao-todas"].__setitem__("saida", "8h"),
        lambda c: c["direcoes"]["direcoes-erro-2010"].__setitem__("pontos", ["fabrica", "marques_de_pombal", "fabrica"]),
        lambda c: c["otimizacao"]["otimizacao-todas"]["paragens"][0].__setitem__("janelas", [{"inicio": "09:00", "fim": "09:05"}]),
    ],
    ids=["sem direcoes", "sem um cenario", "sem o rio", "hora mal escrita", "o 2010 sem o rio", "uma paragem impossivel"],
)
def test_um_cenarios_json_estragado_nao_faz_pedidos(tmp_path, monkeypatch, capsys, estragar):
    servidor = _instalar(monkeypatch)
    pasta = _pasta(tmp_path)
    cenarios = _cenarios()
    estragar(cenarios)
    (pasta / "cenarios.json").write_text(json.dumps(cenarios, ensure_ascii=False), encoding="utf-8")
    antes = _conteudos(pasta)
    assert _correr(pasta, _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "cenarios.json" in erros
    assert servidor.pedidos == []
    assert _conteudos(pasta) == antes


def test_uma_pasta_sem_o_cenarios_json(tmp_path, monkeypatch, capsys):
    servidor = _instalar(monkeypatch)
    pasta = tmp_path / "vazia"
    pasta.mkdir()
    assert _correr(pasta, _env(tmp_path)) == 1
    _, erros = _saidas(capsys)
    assert "cenarios.json" in erros
    assert servidor.pedidos == [] and list(pasta.iterdir()) == []


# --- A guarda (meta-testes) -------------------------------------------------------------------


def test_a_guarda_apanha_um_pedido_sem_o_transporte_do_teste(tmp_path, monkeypatch, capsys):
    gerador = guarda_contra_a_rede(monkeypatch)
    pedidos = next(gerador)
    assert _correr(_pasta(tmp_path), _env(tmp_path)) == 1  # 599 da guarda
    _saidas(capsys)
    assert pedidos == [URL_OTIMIZACAO]
    with pytest.raises(AssertionError, match=MENSAGEM_DA_GUARDA):
        next(gerador)


def test_a_guarda_corta_tambem_o_transporte_verdadeiro_e_os_sockets(monkeypatch):
    gerador = guarda_contra_a_rede(monkeypatch)
    pedidos = next(gerador)
    with pytest.raises(AssertionError):
        httpx.HTTPTransport().handle_request(httpx.Request("POST", "https://exemplo.invalid/"))
    with pytest.raises(AssertionError):
        socket.getaddrinfo("exemplo.invalid", 443)
    with pytest.raises(AssertionError):
        socket.create_connection(("exemplo.invalid", 443), timeout=0.01)
    assert pedidos == ["rede verdadeira"] * 3
    with pytest.raises(AssertionError, match=MENSAGEM_DA_GUARDA):
        next(gerador)
