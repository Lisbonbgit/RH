"""**O endereço que o script do cron escreve, confrontado com o router.**

Este ficheiro existe por causa de um erro que já aconteceu três vezes nesta
casa: um caminho afirmado à mão num teste diz o que o programador escreveu,
não o que o servidor serve. Aqui o endereço não é afirmado — é LIDO do
`plataformas-semanal-cron.sh` e resolvido contra as rotas a sério.

O que isto apanha: alguém muda o prefixo do pacote, ou o nome da rota, os
testes do backend continuam todos verdes, e o cron passa a bater num 404
todas as segundas de manhã — em silêncio, porque um cron que falha não avisa
ninguém. O relatório simplesmente deixa de sair.
"""
import os
import re

import pytest

import plataformas

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(RAIZ, "plataformas-semanal-cron.sh")


@pytest.fixture(scope="module")
def texto_do_script():
    assert os.path.exists(SCRIPT), "o script do cron desapareceu: %s" % SCRIPT
    with open(SCRIPT, encoding="utf-8") as ficheiro:
        return ficheiro.read()


def _rotas_post():
    return {r.path for r in plataformas.router.routes if "POST" in r.methods}


def test_o_endereco_do_script_e_uma_rota_que_existe_mesmo(texto_do_script):
    enderecos = re.findall(r'"(http://localhost:8000(/api/[^"?]+))', texto_do_script)
    assert enderecos, "o script não chama nenhum endereço — foi reescrito?"
    for completo, caminho in enderecos:
        assert caminho in _rotas_post(), (
            "o cron bate em %s, que não é nenhuma rota POST deste módulo. "
            "Rotas a sério: %s" % (caminho, sorted(_rotas_post())))


def test_o_script_leva_a_CRON_KEY_do_ambiente_do_contentor(texto_do_script):
    """A chave nunca no crontab: quem lê o `crontab -l` de um servidor não
    tem de ficar com a chave que abre a porta do cron."""
    assert 'os.environ["CRON_KEY"]' in texto_do_script
    assert "?key=" in texto_do_script


def test_o_script_corre_dentro_do_contentor_e_nao_pelo_proxy(texto_do_script):
    """`localhost:8000` por dentro, e não o domínio público: a leitura da caixa
    pode demorar minutos e o Caddy corta a ligação muito antes disso."""
    assert "docker compose exec -T backend" in texto_do_script
    assert "rh.lisbonb.com" not in texto_do_script


def test_o_script_e_executavel():
    """Um script sem o bit de execução instala-se na mesma no crontab e falha
    todas as segundas com «Permission denied» — no log que ninguém abre."""
    assert os.access(SCRIPT, os.X_OK), (
        "falta o bit de execução: git update-index --chmod=+x "
        "plataformas-semanal-cron.sh")


def test_a_linha_do_crontab_esta_escrita_e_e_a_de_segunda_feira(texto_do_script):
    """O cabeçalho é a única instrução de instalação que existe (nesta casa os
    crons documentam-se no próprio script, não no DEPLOY.md). Se a linha lá
    dentro deixar de ser a de segunda-feira, quem a copiar instala outra
    coisa."""
    assert re.search(r"^#\s+0 8 \* \* 1\s+/root/RH/plataformas-semanal-cron\.sh",
                     texto_do_script, re.MULTILINE), \
        "a linha de exemplo do crontab mudou ou desapareceu do cabeçalho"
    # `* * 1` é segunda-feira; um `* * *` aqui era um email por dia.
    assert "CRON_TZ=Europe/Lisbon" in texto_do_script
