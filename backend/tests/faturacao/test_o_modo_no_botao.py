"""**O modo de emissão passa a virar-se num botão, e não por `ssh`.**

O dono, no dia de pôr a primeira loja a faturar: «aquele botão de colocar no
modo de formação/teste podia já estar funcionando».

Até aqui o modo vivia numa variável de ambiente (`VENDUS_MODE`) e mudá-lo
obrigava a entrar no servidor, editar o `.env` e recriar o contentor. Foi feito
assim de propósito — para não se virar por engano — mas o preço era não haver
travão nenhum à mão de quem está ao balcão.

**O que NÃO pode mudar, e é o que este ficheiro guarda.**

O engano que este módulo existe para prevenir é simétrico e é caro nos dois
lados: em `tests` sem aviso, a operadora julga que vende e nada chega à
Autoridade Tributária; em `normal` a julgar que treina, saem Faturas
Simplificadas REAIS em nome da Fordaimon Foods. Por isso:

1. continua a haver TRÊS estados, e o terceiro («não se sabe») continua a
   RECUSAR a emissão em vez de escolher um lado por omissão;
2. a faixa do POS e a emissão continuam a ler a MESMA verdade — o pior desfecho
   possível é o ecrã dizer uma coisa enquanto a fatura faz outra;
3. quem muda tem de dizer PARA ONDE, nunca «alterna»: um duplo toque num
   botão que alterna passa a real e volta a testes sem ninguém dar por isso.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import modo as modo_mod
from faturacao.vendus.emissao import VendusModoInvalido


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coleccao:
    def __init__(self, registo, doc=None):
        self.registo = registo
        self.doc = doc

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return dict(self.doc) if self.doc else None

    async def update_one(self, filtro, atualizacao, upsert=False):
        self.registo.append(("update_one", filtro, atualizacao, upsert))
        self.doc = dict(atualizacao["$set"])
        return None


class _Db:
    def __init__(self, coleccao):
        self._c = coleccao

    def __getitem__(self, nome):
        return self._c


def _db(registo, doc=None):
    return _Db(_Coleccao(registo, doc))


# --- A verdade guardada ------------------------------------------------------


def test_sem_nada_guardado_vale_a_VARIAVEL_DE_AMBIENTE(monkeypatch):
    """O que já está em produção não pode mudar de comportamento no dia do
    deploy: sem ninguém ter tocado no botão, o modo continua a ser o do `.env`."""
    monkeypatch.setenv("VENDUS_MODE", "tests")
    registo = []
    monkeypatch.setattr(modo_mod, "obter_db", lambda: _db(registo))
    assert _corre(modo_mod.modo_efectivo(_db(registo))) == "tests"


def test_o_que_esta_GUARDADO_ganha_a_variavel(monkeypatch):
    """É esse o objectivo do botão: mandar mais do que o `.env`, sem `ssh`."""
    monkeypatch.setenv("VENDUS_MODE", "tests")
    registo = []
    guardado = _db(registo, {"id": "modo_emissao", "modo": "normal"})
    assert _corre(modo_mod.modo_efectivo(guardado)) == "normal"


def test_um_valor_guardado_ESTRAGADO_cai_no_terceiro_estado(monkeypatch):
    """`None` e não «tests»: um valor que não se percebe não pode escolher um
    dos dois lados em silêncio — a emissão recusa-se, que é o desfecho seguro."""
    monkeypatch.setenv("VENDUS_MODE", "normal")
    registo = []
    estragado = _db(registo, {"id": "modo_emissao", "modo": "XPTO"})
    assert _corre(modo_mod.modo_efectivo(estragado)) is None


def test_sem_nada_guardado_E_sem_variavel_tambem_e_o_terceiro_estado(monkeypatch):
    monkeypatch.delenv("VENDUS_MODE", raising=False)
    registo = []
    monkeypatch.setattr(modo_mod, "obter_db", lambda: _db(registo))
    assert _corre(modo_mod.modo_efectivo(_db(registo))) is None


# --- Mudar pelo botão --------------------------------------------------------


def test_mudar_EXIGE_dizer_para_onde(monkeypatch):
    """Nunca «alterna». Um duplo toque num botão que alterna passa a real e
    volta a testes sem ninguém dar por isso — e as faturas que saíram pelo meio
    são reais para sempre."""
    with pytest.raises(Exception):
        modo_mod.ModoEntrada(modo="alternar")


def test_mudar_para_normal_GUARDA_quem_e_quando(monkeypatch):
    """Uma mudança destas tem de deixar rasto: é a diferença entre «alguém pôs
    isto a real às 14h» e «não se sabe»."""
    registo = []
    monkeypatch.setattr(modo_mod, "obter_db", lambda: _db(registo))
    resultado = _corre(modo_mod.mudar_modo_de_emissao(
        modo_mod.ModoEntrada(modo="normal"),
        {"email": "matheus@lisbonb.pt", "name": "Matheus"}))
    assert resultado["modo"] == "normal"
    escrita = next(c for c in registo if c[0] == "update_one")
    gravado = escrita[2]["$set"]
    assert gravado["modo"] == "normal"
    assert gravado["mudado_por"] == "matheus@lisbonb.pt"
    assert gravado["mudado_em"]


def test_voltar_a_testes_e_o_mesmo_caminho(monkeypatch):
    """O travão tem de ser tão fácil como o arranque — é o que se usa quando
    alguma coisa corre mal com o cliente à frente."""
    registo = []
    monkeypatch.setattr(modo_mod, "obter_db",
                        lambda: _db(registo, {"id": "modo_emissao", "modo": "normal"}))
    assert _corre(modo_mod.mudar_modo_de_emissao(
        modo_mod.ModoEntrada(modo="tests"), {"email": "a@b.pt"}))["modo"] == "tests"


# --- A garantia que não pode cair --------------------------------------------


def test_a_EMISSAO_recebe_o_modo_de_quem_o_resolveu():
    """**O guarda central deste ficheiro.**

    A emissão corre em código síncrono, dentro de uma thread, e não consegue
    ler a base de dados. Quem resolve o modo é a camada assíncrona
    (`fiscal.py`), que o passa para baixo. Se um dia alguém tirar esse
    `modo=` da chamada, a emissão volta a cair na variável de ambiente — e o
    botão passa a mentir: o ecrã diz `normal` e a fatura sai em `tests`, sem
    nada partir e sem nenhum outro teste ficar vermelho.

    Por isso a asserção é sobre a CHAMADA, e não sobre um valor."""
    from pathlib import Path
    modulos = Path(__file__).resolve().parents[2] / "faturacao"
    # **Os DOIS documentos, e não só a fatura.** Escrevi este guarda a olhar só
    # para o `fiscal.py` e a mutação mostrou o buraco: tirar o `modo` da nota
    # de crédito não punha nada vermelho. Uma nota emitida em `tests` para
    # corrigir uma fatura REAL não corrige coisa nenhuma — fica a fatura de pé
    # na Autoridade Tributária e o cliente com o dinheiro devolvido.
    for ficheiro in ("fiscal.py", "nota_credito.py"):
        texto = (modulos / ficheiro).read_text(encoding="utf-8")
        assert "modo=modo_da_emissao" in texto, (
            "O `%s` deixou de passar o modo à emissão — a partir daqui ela lê "
            "a variável de ambiente e o botão do backoffice mente." % ficheiro)
        assert "await modo_efectivo(db)" in texto, (
            "O `%s` deixou de resolver o modo pela fonte única." % ficheiro)


def test_a_emissao_RECUSA_um_modo_que_nao_percebe():
    """O terceiro estado, do lado de dentro: entregue um valor inventado, a
    emissão levanta em vez de emitir. É esta recusa que faz do «não se sabe»
    um estado seguro e não um `tests` disfarçado."""
    from faturacao.vendus.emissao import _modo_valido
    for mau in (None, "", "TESTS", "normal ", "producao", 1):
        with pytest.raises(VendusModoInvalido):
            _modo_valido(mau)
    assert _modo_valido("tests") == "tests"
    assert _modo_valido("normal") == "normal"


def test_as_DUAS_rotas_de_leitura_usam_a_mesma_fonte():
    """A faixa do POS e o ecrã do backoffice não podem divergir: uma a dizer
    que está em testes enquanto a outra diz que está a sério é o pior estado
    possível deste sistema."""
    from pathlib import Path
    origem = Path(modo_mod.__file__).read_text(encoding="utf-8")
    assert origem.count("await modo_efectivo(obter_db())") >= 2, (
        "Uma das rotas de leitura do modo deixou de usar `modo_efectivo`.")
