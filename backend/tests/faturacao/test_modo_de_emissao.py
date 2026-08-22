"""A pergunta «isto está em teste ou está a sério?», respondida pelo SERVIDOR.

**Porque este ficheiro existe.** O dono perguntou «neste momento está tudo em
teste né? posso fazer faturas aqui normal.» e ninguém soube responder sem ir ao
servidor ler uma variável de ambiente. Enquanto a resposta viver só lá, os dois
enganos caros ficam ambos possíveis, e são simétricos:

- em `tests` sem ninguém avisar, a operadora julga que está a vender a sério, o
  cliente leva um talão sem valor nenhum e **nada chega à Autoridade
  Tributária** — a loja pensa que facturou o dia;
- em `normal` com o aviso ligado, ela julga que está a treinar e emite **Faturas
  Simplificadas REAIS** em nome da Fordaimon Foods (NIF 517542510).

Por isso a resposta não pode ser adivinhada de nenhum dos lados, e há **três**
estados e não dois: `tests`, `normal`, e **não se sabe**. Este ficheiro guarda o
lado do servidor dos três.

**A fonte é a MESMA que a emissão usa.** `vendus/emissao.py::_modo_configurado`
já se recusa a emitir quando `VENDUS_MODE` não é explicitamente 'tests' ou
'normal' (ver a docstring de `VendusModoInvalido` — a versão anterior caía em
'tests' em silêncio, e uma loja podia facturar um dia inteiro para o vazio). A
rota tem de reflectir essa mesma verdade: com a variável ausente ou estragada,
o que sai daqui é o terceiro estado — nunca um dos dois conhecidos.

**Os âmbitos de autenticação, e porque são dois.** Isto diz a quem pergunta se
a empresa está a emitir a sério, e por isso não fica aberto a ninguém. São duas
rotas, uma por família, porque `test_protecao_rotas.py` guarda (e bem) que as
duas famílias nunca se misturam:

- `/api/faturacao/pos/modo-de-emissao` — o **dispositivo**, e de propósito NÃO o
  operador. A faixa tem de continuar de pé durante a troca de operador, que é um
  dos momentos em que o ecrã não tem token de operador nenhum; pendurá-la no
  `operador_atual` era apagá-la exactamente aí.
- `/api/faturacao/modo-de-emissao` — o **gestor**, para o backoffice.
"""
import asyncio

import pytest

from faturacao import modo as modo_mod
from faturacao.auth import gestor_atual
from faturacao.pos_auth import dispositivo_atual, operador_atual
from faturacao.vendus.emissao import VendusModoInvalido, _modo_configurado


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- O que o servidor sabe ----------------------------------------------------


@pytest.mark.parametrize("configurado", ["tests", "normal"])
def test_o_modo_valido_sai_tal_e_qual(monkeypatch, configurado):
    """Os dois estados conhecidos saem com o nome EXACTO que a emissão usa —
    nunca traduzidos, nunca abreviados: é o mesmo par de palavras dos dois
    lados (`_MODOS_VALIDOS` em vendus/emissao.py)."""
    monkeypatch.setenv("VENDUS_MODE", configurado)
    assert modo_mod.modo_de_emissao() == configurado


@pytest.mark.parametrize("valor", [None, "", "producao", "TESTS", "tests ", "1"])
def test_sem_modo_valido_o_servidor_diz_que_nao_sabe(monkeypatch, valor):
    """Ausente ou estragado, a resposta é `None` — o terceiro estado.

    Nunca 'tests' (o ecrã ficava a gritar por causa de uma variável mal
    escrita, e a operadora aprendia a ignorar a faixa) e muito menos 'normal'
    (o ecrã calava-se por cima de uma emissão que se recusa a acontecer)."""
    if valor is None:
        monkeypatch.delenv("VENDUS_MODE", raising=False)
    else:
        monkeypatch.setenv("VENDUS_MODE", valor)
    assert modo_mod.modo_de_emissao() is None


@pytest.mark.parametrize("valor", ["producao", ""])
def test_o_terceiro_estado_e_exactamente_o_que_a_emissao_RECUSA(monkeypatch, valor):
    """A prova de que os dois lêem a MESMA verdade, e não duas parecidas.

    Não basta que a rota devolva `None` para um valor esquisito: tem de
    devolver `None` **exactamente** quando a emissão se recusaria a emitir. Se
    alguém amanhã acrescentar um modo novo à emissão sem o acrescentar aqui (ou
    ao contrário), este teste apanha a divergência — que é o único sítio onde
    ela dói: o ecrã a dizer uma coisa e a fatura a fazer outra."""
    monkeypatch.setenv("VENDUS_MODE", valor)
    with pytest.raises(VendusModoInvalido):
        _modo_configurado()
    assert modo_mod.modo_de_emissao() is None


# --- As duas rotas ------------------------------------------------------------


@pytest.mark.parametrize("configurado", ["tests", "normal"])
def test_as_duas_rotas_dizem_o_mesmo_modo(monkeypatch, configurado):
    """POS e backoffice não podem responder coisas diferentes sobre a mesma
    empresa: é a mesma pergunta feita de dois sítios."""
    monkeypatch.setenv("VENDUS_MODE", configurado)
    do_pos = _corre(modo_mod.modo_de_emissao_do_pos(dispositivo={"id": "d-1"}))
    do_backoffice = _corre(modo_mod.modo_de_emissao_do_backoffice(utilizador={"id": "u-1"}))
    assert do_pos == {"modo": configurado}
    assert do_backoffice == {"modo": configurado}


def test_as_duas_rotas_dizem_que_nao_sabem_em_vez_de_escolher(monkeypatch):
    """Sem `VENDUS_MODE` válido, as rotas respondem 200 com `modo: null`.

    200 e não um erro, de propósito: um 500 aqui era indistinguível, do lado do
    ecrã, de o servidor estar em baixo — e as duas coisas têm de acabar no
    MESMO terceiro estado, por isso mais vale dizê-lo com todas as letras."""
    monkeypatch.delenv("VENDUS_MODE", raising=False)
    assert _corre(modo_mod.modo_de_emissao_do_pos(dispositivo={"id": "d-1"})) == {"modo": None}
    assert _corre(
        modo_mod.modo_de_emissao_do_backoffice(utilizador={"id": "u-1"})
    ) == {"modo": None}


def test_a_resposta_nao_diz_mais_nada(monkeypatch):
    """Só o modo. Isto responde-se a um PC de balcão emparelhado e a resposta
    não pode arrastar consigo o nome da conta Vendus, a caixa API, o NIF ou
    seja o que for da configuração da empresa."""
    monkeypatch.setenv("VENDUS_MODE", "normal")
    resposta = _corre(modo_mod.modo_de_emissao_do_pos(dispositivo={"id": "d-1"}))
    assert set(resposta) == {"modo"}


# --- Os âmbitos, nomeados um a um ---------------------------------------------
#
# O varrimento de `test_protecao_rotas.py` já prova que nenhuma destas fica sem
# guarda nenhuma. O que ele NÃO prova — e é o que interessa aqui — é QUAL das
# guardas do POS está em cada uma: trocar `dispositivo_atual` por
# `operador_atual` passa lá sem uma palavra, e apaga a faixa exactamente no
# momento em que ela tem de aguentar (a troca de operador).


def _dependencias(rota):
    encontradas = set()

    def _procura(dependant):
        for d in dependant.dependencies:
            encontradas.add(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontradas


def _rota(caminho):
    for rota in modo_mod.router.routes:
        if rota.path == caminho:
            return rota
    pytest.fail(
        "Não encontrei a rota %s. Se ela mudou de caminho, o ecrã que a chama "
        "(frontend/src/lib/pos.js) tem de ir atrás dela — e este guarda "
        "também." % caminho
    )


def test_a_rota_do_pos_pede_o_DISPOSITIVO_e_nunca_o_operador():
    """O dispositivo, e não o operador: é o único token que o POS tem sempre,
    incluindo no instante em que ninguém está identificado. Ver o cabeçalho."""
    dependencias = _dependencias(_rota("/pos/modo-de-emissao"))
    assert dispositivo_atual in dependencias
    assert operador_atual not in dependencias
    assert gestor_atual not in dependencias


def test_a_rota_do_backoffice_pede_o_GESTOR_e_nunca_as_do_pos():
    dependencias = _dependencias(_rota("/modo-de-emissao"))
    assert gestor_atual in dependencias
    assert dispositivo_atual not in dependencias
    assert operador_atual not in dependencias


def test_a_rota_do_backoffice_nao_vive_debaixo_de_pos():
    """Se um dia alguém a arrastasse para debaixo de `/pos/`, o varrimento de
    `test_protecao_rotas.py` passava a lê-la como rota do POS e a pedir-lhe o
    mecanismo do POS — o JWT de gestão deixava de ser exigido sem nenhum teste
    se queixar. Mesmo raciocínio (e mesmo perigo) do
    `test_metodos_vendus_e_rota_de_gestao_e_nunca_do_pos`."""
    caminhos = {rota.path for rota in modo_mod.router.routes}
    assert "/modo-de-emissao" in caminhos
    assert not any(c.startswith("/pos/") and c.endswith("/modo-de-emissao") and c != "/pos/modo-de-emissao" for c in caminhos)


def test_as_duas_rotas_estao_penduradas_no_router_do_modulo():
    """Um router escrito e nunca incluído em `faturacao/__init__.py` é uma
    rota que não existe — e o ecrã responde-lhe com o terceiro estado para
    sempre, sem ninguém perceber porquê. Já aconteceu neste módulo: as sete
    chamadas do POS foram todas para /api/pos/... (404) e ninguém deu por
    isso, porque os ecrãs desenham-se na mesma sem servidor nenhum."""
    from faturacao import router as router_do_modulo

    caminhos = {rota.path for rota in router_do_modulo.routes}
    assert "/api/faturacao/pos/modo-de-emissao" in caminhos
    assert "/api/faturacao/modo-de-emissao" in caminhos


@pytest.mark.parametrize("caminho", ["/pos/modo-de-emissao", "/modo-de-emissao"])
def test_as_duas_rotas_sao_GET_e_so_GET(caminho):
    """Uma leitura. Não escreve nada, pode ser pedida as vezes que forem
    precisas, e não há aqui nenhuma forma de MUDAR o modo — mudá-lo é mexer no
    servidor, com intenção, não um toque num ecrã de balcão."""
    assert _rota(caminho).methods == {"GET"}
