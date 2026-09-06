"""**A migração não pode deixar uma fatura com categoria órfã.**

`mercadoria` e `energia_agua` desaparecem da lista. Uma fatura que fique com
esses valores deixa de aparecer no relatório de Resultados com nome — aparece
com a chave crua, ou não aparece de todo se alguém filtrar pela lista.

Este teste percorre todos os valores que alguma vez foram escritos e exige que
cada um caia numa categoria que EXISTE na lista nova.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402
from migrar_categorias import MAPA_CATEGORIAS, categoria_migrada  # noqa: E402

VALORES_ANTIGOS = [
    "mercadoria", "rendas", "energia_agua", "salarios",
    "servicos", "impostos", "outros",
]


def test_todo_o_valor_antigo_cai_numa_categoria_que_existe():
    ids_novos = {c["id"] for c in server.FIN_CATEGORIAS_PADRAO}
    for antigo in VALORES_ANTIGOS:
        novo = categoria_migrada(antigo)
        assert novo in ids_novos, f"{antigo} ficaria órfão em {novo!r}"


def test_os_dois_que_mudam_de_nome_mudam_para_o_certo():
    assert MAPA_CATEGORIAS["mercadoria"] == "fornecedor"
    assert MAPA_CATEGORIAS["energia_agua"] == "utilitarios"


def test_o_que_ja_esta_certo_fica_como_esta():
    assert categoria_migrada("servicos") == "servicos"
    assert categoria_migrada("impostos") == "impostos"


def test_uma_categoria_desconhecida_vai_para_outros_e_nao_se_perde():
    # Valores soltos escritos à mão em produção não podem ficar sem casa.
    assert categoria_migrada("qualquer_coisa") == "outros"


def test_sem_categoria_continua_sem_categoria():
    # Uma fatura por classificar não pode passar a "Outros": isso esconderia
    # trabalho por fazer atrás de um número credível.
    assert categoria_migrada(None) is None
    assert categoria_migrada("") is None
