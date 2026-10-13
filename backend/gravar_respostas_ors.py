"""Gravador das respostas do openrouteservice (plano F3, T3.12). **Só o dono o corre.**

    cd backend && .venv/bin/python gravar_respostas_ors.py --env-file .env.ors [--pasta tests/crm/fixtures/ors]

Regrava, a partir do openrouteservice verdadeiro, as respostas que os testes do
CRM usam para provar o formato real (as escritas à mão estão marcadas
"manual — regravar"). Os valores exatos dos testes das rotas vêm sempre de
respostas escritas no próprio teste; estas só provam a forma e os conjuntos.

- **A chave** vem só do ficheiro indicado (`dotenv_values`, sem interpolação:
  nunca lê nem escreve o `os.environ`). O dono usa um ficheiro próprio, fora do
  git e com o modo 600 (por exemplo `backend/.env.ors`; o `.gitignore` já
  ignora `.env.*`), nunca o `.env.local` da pré-visualização: esse tem a chave
  do simulador (`simulador-local`, T3.43), que o gravador recusa. A chave vai
  só no cabeçalho `Authorization`, nunca no URL nem na saída.
- **O URL é sempre o oficial** (`https://api.openrouteservice.org`): o
  `CRM_ORS_URL` (do ficheiro ou da shell) não conta. Não segue redireções.
- **Lista fechada:** `otimizacao-todas`, `otimizacao-uma-nao-cabe`,
  `direcoes-tres-paragens` e `direcoes-erro-2010`, montados do `cenarios.json`
  com `vroom.pedido_otimizacao` e `directions.pedido_direcoes` (ao ORS só vão
  coordenadas, segundos, prioridades e números). O `erro-429.json` fica sempre
  manual (um 429 não se provoca de forma garantida).
- **Só grava respostas que os testes aceitam:** cada uma lê-se com o
  `interpretar_*` e bate certo com o cenário (no "todas" cabem todas, no
  "uma-nao-cabe" fica de fora só a Torre de Belém, os 4 troços das três
  paragens têm distância e duração, e o 2010 aponta para o ponto no rio,
  contado a partir de 0). Se não bater, não grava nada e diz porquê: assim o
  `pytest tests/crm` continua verde depois de regravar.
- **Tudo ou nada:** primeiro todos os pedidos (pára no primeiro que falhe);
  depois cada ficheiro num temporário escondido na pasta (`.<ficheiro>.tmp`) e
  só no fim `os.replace`. Se a chave aparecer numa resposta, não grava nada.
  Cada JSON começa por `"_origem": "gravado em AAAA-MM-DD
  (gravar_respostas_ors.py)"` (o dia de Lisboa, `relogio.hoje`), indentado a 2
  espaços, com os acentos tal e qual.
- **Saída:** só os nomes dos ficheiros gravados. Os erros vão para o stderr,
  sem a chave nem o texto das exceções (só o tipo). Sai com 0 se gravou tudo e
  com 1 se não.

Não usa o `crm.servicos.ors` (o cliente das rotas, T3.11) de propósito: o
gravador precisa do corpo do erro 2010 tal como veio (o cliente transforma-o
numa falha) e vai sempre ao URL oficial. É síncrono: é um comando de terminal.
Os testes (`tests/crm/test_gravar_respostas_ors.py`) trocam o `_transporte`
por um `httpx.MockTransport` e nunca vão à rede.
"""
import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Callable, NamedTuple

import httpx
from dotenv import dotenv_values

from crm import relogio
from crm.dominio import directions, horas, polilinha, vroom
from crm.servicos import geoapify

URL_OFICIAL = "https://api.openrouteservice.org"
CAMINHO_OTIMIZACAO = "/optimization"
CAMINHO_DIRECOES = f"/v2/directions/{vroom.PERFIL}/json"

VARIAVEL_CHAVE = "CRM_ORS_CHAVE"

# O valor que a T3.43 escreve no backend/.env.local para o simulador local.
CHAVE_DO_SIMULADOR = "simulador-local"

PASTA_POR_OMISSAO = Path(__file__).resolve().parent / "tests" / "crm" / "fixtures" / "ors"
CENARIOS = "cenarios.json"

# A lista fechada (correção "T3.12 / T3.43"), pela ordem dos pedidos: cenário → secção do cenarios.json.
GRAVAVEIS = {
    "otimizacao-todas": "otimizacao",
    "otimizacao-uma-nao-cabe": "otimizacao",
    "direcoes-tres-paragens": "direcoes",
    "direcoes-erro-2010": "direcoes",
}

# O que cada cenário de otimização tem de deixar de fora (os testes da T3.6 contam com isto).
NAO_ATRIBUIDAS_ESPERADAS = {"otimizacao-todas": [], "otimizacao-uma-nao-cabe": ["torre_de_belem"]}

# O cenário que tem de dar o erro 2010 (ponto longe da estrada) e o ponto culpado.
CENARIO_DO_ERRO = "direcoes-erro-2010"
PONTO_FORA_DA_ESTRADA = "rio_tejo"
CODIGO_SEM_ESTRADA = 2010

TEMPO = httpx.Timeout(30.0, connect=5.0)

# Uma chave do ORS (hexadecimal, ou base64 nas chaves novas) e não curta demais. Sem espaços,
# aspas nem barras invertidas: pode ir num cabeçalho e o JSON nunca a escreve com escapes (a
# procura da chave nas respostas é pelo texto tal e qual).
_CHAVE_VALIDA = re.compile(r"[A-Za-z0-9+/=_.-]{20,}")

# As duas formas da mensagem do 2010: "…specified coordinate N: …" e a antiga "Could not find point N: …".
_COORDENADA_DO_ERRO = re.compile(r"(?:coordinate|point) ([0-9]+)")

_EXPLICACOES = {
    401: " — chave recusada ou quota diária esgotada",
    403: " — chave recusada ou quota diária esgotada",
    429: " — limite de pedidos, espere um minuto",
}

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte normal do httpx.
_transporte = None


class _Recusa(Exception):
    """Pára o gravador com uma mensagem para o stderr (nunca com a chave)."""

    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


class Pedido(NamedTuple):
    """Um pedido da lista fechada: o cenário, o caminho no ORS, o corpo e a
    verificação da resposta (levanta `_Recusa`)."""

    nome: str
    caminho: str
    corpo: dict
    conferir: Callable[[dict], None]
    espera_erro: bool


def principal(argv=None) -> int:
    argumentos = _leitor().parse_args(argv)
    pasta = Path(argumentos.pasta)

    try:
        chave = _ler_chave(Path(argumentos.env_file))
        lista = pedidos(_ler_cenarios(pasta))
        conteudos = _gravacoes(lista, chave)
    except _Recusa as recusa:
        print(recusa.mensagem, file=sys.stderr)
        return 1

    return _gravar(conteudos, pasta)


def _leitor():
    leitor = argparse.ArgumentParser(
        prog="gravar_respostas_ors.py",
        description="Regrava as respostas do openrouteservice usadas nos testes do CRM (só o dono).",
    )
    leitor.add_argument("--env-file", required=True, help="ficheiro com a CRM_ORS_CHAVE de desenvolvimento (ex.: .env.ors)")
    leitor.add_argument("--pasta", default=str(PASTA_POR_OMISSAO), help="pasta das fixtures do ORS (com o cenarios.json)")
    return leitor


# --- A chave ---------------------------------------------------------------------------------


def _ler_chave(caminho: Path) -> str:
    if not caminho.is_file():
        raise _Recusa(f"Não encontrei o ficheiro {caminho}.")

    valores = dotenv_values(caminho, interpolate=False, encoding="utf-8")
    chave = (valores.get(VARIAVEL_CHAVE) or "").strip()

    if chave == "":
        raise _Recusa("Falta a CRM_ORS_CHAVE no ficheiro indicado.")

    if chave == CHAVE_DO_SIMULADOR:
        raise _Recusa(
            "A CRM_ORS_CHAVE do ficheiro é a do simulador.\n"
            "Ponha a chave de desenvolvimento num ficheiro próprio (por exemplo backend/.env.ors, "
            "com chmod 600) e indique-o em --env-file."
        )

    if not _CHAVE_VALIDA.fullmatch(chave):
        raise _Recusa(
            "A CRM_ORS_CHAVE do ficheiro não parece uma chave do openrouteservice "
            "(curta demais, ou com espaços, aspas ou outros caracteres que uma chave não tem)."
        )

    if stat.S_IMODE(caminho.stat().st_mode) & 0o077:
        print(f"Aviso: o ficheiro {caminho} pode ser lido por outras contas deste computador; faça chmod 600.", file=sys.stderr)

    return chave


# --- Os pedidos ------------------------------------------------------------------------------


def _ler_cenarios(pasta: Path) -> dict:
    try:
        return json.loads((pasta / CENARIOS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _Recusa(f"Não consegui ler o {CENARIOS} da pasta {pasta}.") from None


def pedidos(cenarios) -> list:
    """Os pedidos da lista fechada, montados do `cenarios.json` como os testes
    da T3.6/T3.7 os montam (o id de cada paragem é o nome do ponto, que nunca
    vai ao ORS)."""
    try:
        return [_pedido(cenarios, nome, seccao) for nome, seccao in GRAVAVEIS.items()]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _Recusa(f"O {CENARIOS} não tem a forma esperada ({type(exc).__name__}).") from None


def _pedido(cenarios, nome, seccao) -> Pedido:
    pontos = cenarios["pontos"]
    cenario = cenarios[seccao][nome]

    def par(ponto):
        return (pontos[ponto]["lat"], pontos[ponto]["lng"])

    if seccao == "otimizacao":
        calculo = [
            vroom.paragem_calculo(
                {"id": p["ponto"], "motivo": p["motivo"], "tempo_servico_min": p["tempo_servico_min"]},
                {**pontos[p["ponto"]], "janelas": p["janelas"]},
            )
            for p in cenario["paragens"]
        ]
        pedido = vroom.pedido_otimizacao(
            calculo, par(cenario["inicio"]), par(cenario["fim"]),
            horas.segundos(cenario["saida"]), horas.segundos(cenario["limite"]),
        )
        if pedido.corpo is None or pedido.impossiveis:
            raise ValueError("paragem impossível")
        return Pedido(nome, CAMINHO_OTIMIZACAO, pedido.corpo, _conferir_otimizacao(nome, pedido.por_job), False)

    nomes = list(cenario["pontos"])
    corpo = directions.pedido_direcoes([par(p) for p in nomes], cenario["evitar_portagens"])
    if nome == CENARIO_DO_ERRO:
        return Pedido(nome, CAMINHO_DIRECOES, corpo, _conferir_erro(nome, nomes.index(PONTO_FORA_DA_ESTRADA)), True)
    return Pedido(nome, CAMINHO_DIRECOES, corpo, _conferir_direcoes(nome, len(nomes)), False)


# --- As verificações das respostas -----------------------------------------------------------


def _forma(nome, motivo):
    return _Recusa(f"A resposta para {nome} não tem a forma esperada ({motivo}); não se gravou nada.")


def _nao_bate(nome, motivo):
    return _Recusa(f"A resposta para {nome} não bate certo com o cenário ({motivo}); não se gravou nada.")


def _conferir_otimizacao(nome, por_job):
    esperadas = NAO_ATRIBUIDAS_ESPERADAS[nome]

    def conferir(dados):
        try:
            _, nao_atribuidas = vroom.interpretar_otimizacao(dados, por_job)
        except vroom.RespostaInvalida as exc:
            raise _forma(nome, exc.motivo) from None
        if sorted(nao_atribuidas) != sorted(esperadas):
            raise _nao_bate(
                nome, f"ficaram de fora {', '.join(nao_atribuidas) or 'nenhuma'}; esperava {', '.join(esperadas) or 'nenhuma'}"
            )

    return conferir


def _conferir_direcoes(nome, n_pontos):
    def conferir(dados):
        try:
            trocos = directions.interpretar_direcoes(dados, n_pontos)
        except vroom.RespostaInvalida as exc:
            raise _forma(nome, exc.motivo) from None
        if not all(valor > 0 for valor in trocos.duracoes + trocos.distancias):
            raise _nao_bate(nome, "um troço sem distância ou duração, com pontos todos diferentes")
        if len(polilinha.descodificar(trocos.geometria)) < 2:
            raise _nao_bate(nome, "a linha tem menos de 2 pontos")

    return conferir


def _conferir_erro(nome, indice_do_rio):
    def conferir(dados):
        erro = dados.get("error")
        if (
            not isinstance(erro, dict)
            or type(erro.get("code")) is not int
            or erro["code"] != CODIGO_SEM_ESTRADA
            or not isinstance(erro.get("message"), str)
        ):
            raise _Recusa(f"A resposta para {nome} não traz o erro 2010 do openrouteservice; não se gravou nada.")
        achado = _COORDENADA_DO_ERRO.search(erro["message"])
        if achado is None or int(achado.group(1)) != indice_do_rio:
            numero = "nenhuma" if achado is None else achado.group(1)
            raise _Recusa(
                f"A resposta para {nome} não aponta para o ponto do rio (coordenada {numero}; esperava "
                f"{indice_do_rio}, contando a partir de 0); não se gravou nada."
            )

    return conferir


# --- Os pedidos ao openrouteservice ----------------------------------------------------------


def _gravacoes(lista, chave) -> dict:
    """`{ficheiro: texto}` de todos os pedidos, ou `_Recusa` no primeiro que não sirva."""
    geoapify.silenciar_registos()
    origem = f"gravado em {relogio.hoje().isoformat()} (gravar_respostas_ors.py)"
    conteudos = {}

    with httpx.Client(timeout=TEMPO, transport=_transporte, follow_redirects=False) as cliente:
        for pedido in lista:
            dados = _pedir(cliente, pedido, chave)
            texto = json.dumps({"_origem": origem, **dados}, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            if chave in texto:
                raise _Recusa(f"A resposta para {pedido.nome} traz a chave; não se gravou nada.")
            conteudos[f"{pedido.nome}.json"] = texto

    return conteudos


def _pedir(cliente, pedido, chave) -> dict:
    nome = pedido.nome
    corpo = json.dumps(pedido.corpo, allow_nan=False).encode("utf-8")
    cabecalhos = {"Authorization": chave, "Content-Type": "application/json", "Accept": "application/json"}

    try:
        resposta = cliente.post(URL_OFICIAL + pedido.caminho, content=corpo, headers=cabecalhos)
    except Exception as exc:  # noqa: BLE001 — só o tipo: a mensagem pode trazer o URL ou o pedido
        raise _Recusa(f"O pedido para {nome} falhou (sem resposta: {type(exc).__name__}); não se gravou nada.") from None

    if chave.encode("utf-8") in resposta.content:
        raise _Recusa(f"A resposta para {nome} traz a chave; não se gravou nada.")

    estado = resposta.status_code
    if pedido.espera_erro and 200 <= estado <= 299:
        raise _Recusa(
            f"A resposta para {nome} trouxe uma rota em vez do erro 2010 do openrouteservice "
            "(o ponto do rio já não serve); não se gravou nada."
        )
    erro_lido = pedido.espera_erro and 400 <= estado <= 599 and estado not in _EXPLICACOES
    if not erro_lido and not 200 <= estado <= 299:
        raise _Recusa(f"O pedido para {nome} falhou (estado HTTP {estado}{_EXPLICACOES.get(estado, '')}); não se gravou nada.")

    try:
        dados = geoapify.ler_json(resposta.content)
    except ValueError:
        dados = None
    if not isinstance(dados, dict):
        raise _Recusa(f"A resposta para {nome} não é um objeto JSON; não se gravou nada.")

    dados.pop("_origem", None)
    pedido.conferir(dados)
    return dados


# --- A escrita (tudo ou nada) ----------------------------------------------------------------


def _gravar(conteudos, pasta: Path) -> int:
    temporarios = {}

    try:
        for ficheiro, texto in conteudos.items():
            temporario = pasta / f".{ficheiro}.tmp"
            temporarios[ficheiro] = temporario
            try:
                with open(temporario, "w", encoding="utf-8", newline="\n") as saida:
                    saida.write(texto)
            except OSError:
                print(f"Não foi possível escrever {ficheiro} na pasta {pasta}; não se gravou nada.", file=sys.stderr)
                return 1

        gravados = []
        for ficheiro in list(temporarios):
            try:
                os.replace(temporarios[ficheiro], pasta / ficheiro)
            except OSError:
                ja = f" Já ficaram gravados: {', '.join(gravados)}." if gravados else " Não se gravou nada."
                print(f"Não foi possível pôr {ficheiro} no lugar.{ja}", file=sys.stderr)
                return 1
            del temporarios[ficheiro]
            gravados.append(ficheiro)
            print(f"Gravado: {ficheiro}")
    finally:
        _apagar(temporarios.values())

    return 0


def _apagar(caminhos) -> None:
    """Apaga os temporários que ainda existam (só ficheiros: uma pasta com esse nome não é dele)."""
    for caminho in caminhos:
        if caminho.is_file():
            caminho.unlink()


if __name__ == "__main__":
    sys.exit(principal())
