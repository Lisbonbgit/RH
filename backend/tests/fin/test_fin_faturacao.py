"""**A faturação do nosso POS a entrar no Financeiro — as regras da soma.**

Cada teste aqui defende uma regra que, se partir, produz um número
perfeitamente credível e errado. É esse o perigo deste caminho: ninguém
desconfia de uma faturação que parece plausível.
"""
import asyncio

import pytest

import fin_faturacao as fin


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _doc(**over):
    base = {
        "id": "d1",
        "numero": "FS 06P2026/1",
        "tipo": "FS",
        "modo": "normal",
        "anulado": None,
        "total_bruto": 10.0,
        "total_liquido": 8.85,
        "loja_id": "loja-belem",
        "emitido_em": "2026-09-03T14:30:00+00:00",
    }
    base.update(over)
    return base


# --- O dia de Lisboa ---------------------------------------------------------

def test_uma_venda_da_meia_noite_de_lisboa_cai_no_dia_certo():
    """23:30 UTC no Verão são 00:30 do dia SEGUINTE em Lisboa. Cortar o dia
    pelo UTC punha a venda no dia anterior — todos os dias, e precisamente à
    hora a que as lojas fecham, que é quando o número interessa."""
    assert fin.dia_de_lisboa("2026-09-03T23:30:00+00:00") == "2026-09-04"


def test_no_inverno_lisboa_e_utc_e_o_dia_nao_se_desloca():
    """Em Janeiro Lisboa está em UTC. Um desvio de uma hora escrito à mão em
    vez do fuso a sério errava metade do ano."""
    assert fin.dia_de_lisboa("2026-01-15T23:30:00+00:00") == "2026-01-15"
    assert fin.dia_de_lisboa("2026-01-15T00:30:00+00:00") == "2026-01-15"


def test_uma_data_ilegivel_nao_vai_parar_a_hoje():
    assert fin.dia_de_lisboa("nao é uma data") is None
    assert fin.dia_de_lisboa(None) is None


# --- A soma ------------------------------------------------------------------

def test_uma_nota_de_credito_subtrai():
    """As NC vivem na mesma colecção, com total POSITIVO. Somá-las sem olhar
    ao tipo transformava uma devolução de 24,90 € num acréscimo de 24,90 € —
    um erro do DOBRO do valor devolvido."""
    r = fin.agregar([
        _doc(total_bruto=100.0, total_liquido=88.5),
        _doc(id="d2", tipo="NC", total_bruto=24.9, total_liquido=22.04),
    ])
    balde = r["baldes"][("loja-belem", "2026-09-03")]
    assert balde["bruto"] == pytest.approx(75.1)
    assert balde["liquido"] == pytest.approx(66.46)


def test_um_documento_anulado_nao_conta():
    r = fin.agregar([_doc(), _doc(id="d2", anulado=True, total_bruto=999.0)])
    assert r["baldes"][("loja-belem", "2026-09-03")]["bruto"] == pytest.approx(10.0)


def test_um_documento_de_ensaio_nao_e_dinheiro():
    """Durante a formação das operadoras saem documentos com totais
    realistas em `modo: tests`. Entravam como faturação a sério."""
    r = fin.agregar([_doc(), _doc(id="d2", modo="tests", total_bruto=500.0)])
    assert r["baldes"][("loja-belem", "2026-09-03")]["bruto"] == pytest.approx(10.0)


def test_um_documento_com_modo_DESCONHECIDO_conta():
    """`modo` a `None` é o que fica nos documentos recuperados pela
    verificação ou pela reconciliação — precisamente os que já custaram uma
    segunda tentativa. Filtrar por `== "normal"` apagava receita REAL."""
    r = fin.agregar([_doc(modo=None, total_bruto=42.0)])
    assert r["baldes"][("loja-belem", "2026-09-03")]["bruto"] == pytest.approx(42.0)


def test_documentos_de_lojas_diferentes_nao_se_misturam():
    r = fin.agregar([
        _doc(total_bruto=10.0),
        _doc(id="d2", loja_id="loja-oeiras", total_bruto=20.0),
    ])
    assert r["baldes"][("loja-belem", "2026-09-03")]["bruto"] == pytest.approx(10.0)
    assert r["baldes"][("loja-oeiras", "2026-09-03")]["bruto"] == pytest.approx(20.0)


def test_um_documento_sem_total_nao_e_somado_e_QUEIXA_SE():
    """Não somar em silêncio é metade; a outra metade é dizê-lo. Um
    documento perdido sem queixa é faturação que desaparece sem rasto."""
    r = fin.agregar([_doc(total_bruto=None, numero="FS 06P2026/77")])
    assert r["baldes"] == {}
    assert any("FS 06P2026/77" in q for q in r["queixas"])


def test_um_documento_sem_loja_queixa_se():
    r = fin.agregar([_doc(loja_id=None, numero="FS 06P2026/88")])
    assert r["baldes"] == {}
    assert any("FS 06P2026/88" in q for q in r["queixas"])


def test_um_liquido_em_falta_estraga_o_dia_INTEIRO_e_e_de_proposito():
    """Se UM documento do dia não trouxer o valor sem IVA, a soma dos outros
    é MENOR do que a verdade — e é dela que sai a taxa de IVA implícita e o
    relatório do IVA. Prefere-se não escrever o líquido do dia a escrever um
    líquido a que falta uma parte."""
    r = fin.agregar([_doc(), _doc(id="d2", total_liquido=None, total_bruto=50.0)])
    balde = r["baldes"][("loja-belem", "2026-09-03")]
    assert balde["bruto"] == pytest.approx(60.0), "o BRUTO conta na mesma"
    assert balde["liquido_completo"] is False


# --- As linhas do fin_sales --------------------------------------------------

UNIDADES = {
    "loja-belem": {"id": "u-belem", "company_id": "emp-1", "nome_da_loja": "L'açaí Belém"},
}


def test_a_linha_leva_o_custo_a_NONE_e_nao_a_zero():
    """Um `0.0` no custo lê-se como "custo apurado, deu zero", e o DRE passa
    a mostrar 100% de margem como se fosse um facto. O `fat_documentos` não
    guarda as linhas dos artigos: o custo não é zero, é DESCONHECIDO."""
    baldes = {("loja-belem", "2026-09-03"): {
        "bruto": 100.0, "liquido": 88.5, "docs": 3, "liquido_completo": True}}
    linha = fin.linhas_para_fin_sales(baldes, UNIDADES, "agora")[0]

    assert linha["amount_cost"] is None
    assert linha["amount"] == 100.0
    assert linha["amount_net"] == 88.5
    assert linha["source"] == "faturacao"
    assert linha["company_id"] == "emp-1" and linha["unit_id"] == "u-belem"


def test_sem_liquido_completo_a_linha_nao_inventa_um_valor_sem_iva():
    baldes = {("loja-belem", "2026-09-03"): {
        "bruto": 100.0, "liquido": 50.0, "docs": 2, "liquido_completo": False}}
    linha = fin.linhas_para_fin_sales(baldes, UNIDADES, "agora")[0]

    assert linha["amount_net"] is None
    assert linha["vat_rate"] is None, "sem líquido não há taxa que se possa afirmar"


def test_um_dia_a_zero_nao_gera_linha():
    """Um dia sem vendas não é uma venda de zero euros — a mesma regra do
    escritor do Vendus, senão o painel enchia-se de dias a 0,00 €."""
    baldes = {("loja-belem", "2026-09-03"): {
        "bruto": 0.0, "liquido": 0.0, "docs": 2, "liquido_completo": True}}
    assert fin.linhas_para_fin_sales(baldes, UNIDADES, "agora") == []


def test_uma_loja_sem_unidade_nao_gera_linha():
    baldes = {("loja-nova", "2026-09-03"): {
        "bruto": 100.0, "liquido": 88.5, "docs": 1, "liquido_completo": True}}
    assert fin.linhas_para_fin_sales(baldes, UNIDADES, "agora") == []


# --- A gravação --------------------------------------------------------------

class Coleccao:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.apagados = []

    def find(self, filtro=None, proj=None):
        return _Cursor([d for d in self.docs if _casa(d, filtro or {})])

    async def insert_many(self, novos):
        self.docs.extend(novos)

    async def delete_many(self, filtro):
        self.apagados.append(filtro)
        ficam = [d for d in self.docs if not _casa(d, filtro)]
        apagados = len(self.docs) - len(ficam)
        self.docs = ficam
        return type("R", (), {"deleted_count": apagados})()


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, n):
        return list(self.docs)[:n]


def _casa(doc, filtro):
    """Igualdade mais `$gte`/`$lte` — o que este módulo usa. Um duplo que
    ignorasse o filtro deixava passar um `delete_many` que apagava tudo."""
    for campo, esperado in filtro.items():
        valor = doc.get(campo)
        if isinstance(esperado, dict):
            if "$gte" in esperado and not (valor is not None and valor >= esperado["$gte"]):
                return False
            if "$lte" in esperado and not (valor is not None and valor <= esperado["$lte"]):
                return False
        elif valor != esperado:
            return False
    return True


class Base:
    def __init__(self, documentos, lojas, unidades, vendas=None):
        self.fat_documentos = Coleccao(documentos)
        self.fat_lojas = Coleccao(lojas)
        self.fin_units = Coleccao(unidades)
        self.fin_sales = Coleccao(vendas)


LOJAS = [{"id": "loja-belem", "nome": "L'açaí Belém"}]
UNIDADES_BD = [{"id": "u-belem", "name": "L'açaí Belem", "company_id": "emp-1"}]


def test_a_gravacao_casa_a_loja_com_a_unidade_apesar_do_acento():
    """No nosso módulo a loja é "L'açaí Belém"; no Financeiro a unidade é
    "L'açaí Belem". Sem tirar os acentos, a loja não casava e a faturação
    dela não entrava — que é exactamente o defeito que este módulo veio
    corrigir, noutro sítio."""
    base = Base([_doc()], LOJAS, UNIDADES_BD)

    r = _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert r["written"] == 1
    assert base.fin_sales.docs[0]["unit_id"] == "u-belem"
    assert r["errors"] == []


def test_a_gravacao_NAO_toca_nas_linhas_do_vendus():
    """Os dias 27–29/08 têm as duas origens ao mesmo tempo, e é o que se
    quer: são lojas diferentes, umas ainda no POS do Vendus, outras já no
    nosso. Apagar por dia sem filtrar a origem deitava fora metade da
    faturação desses dias."""
    do_vendus = {"id": "v1", "source": "vendus", "company_id": "emp-1",
                 "unit_id": "u-belem", "date": "2026-09-03", "amount": 55.0}
    base = Base([_doc()], LOJAS, UNIDADES_BD, vendas=[do_vendus])

    _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert do_vendus in base.fin_sales.docs, "a linha do Vendus tem de ficar"
    assert all(f.get("source") == "faturacao" for f in base.fin_sales.apagados)


def test_correr_duas_vezes_nao_duplica():
    """A gravação é idempotente: o cron corre de hora a hora sobre a mesma
    janela, e sem isto cada passagem somava outra vez o dia inteiro."""
    base = Base([_doc()], LOJAS, UNIDADES_BD)

    _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))
    _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    nossas = [v for v in base.fin_sales.docs if v.get("source") == "faturacao"]
    assert len(nossas) == 1


def test_um_dia_que_ficou_sem_vendas_e_LIMPO():
    """Todos os documentos do dia foram anulados. A linha antiga tem de sair
    — senão ficava lá para sempre uma venda que já não existe."""
    velha = {"id": "f1", "source": "faturacao", "company_id": "emp-1",
             "unit_id": "u-belem", "date": "2026-09-03", "amount": 999.0}
    base = Base([_doc(anulado=True)], LOJAS, UNIDADES_BD, vendas=[velha])

    r = _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert r["written"] == 0
    assert base.fin_sales.docs == []


def test_uma_loja_sem_unidade_diz_QUANTO_dinheiro_nao_entrou():
    """A queixa que teria poupado a semana em que a faturação da L'Açaí ficou
    de fora: ela existia, mas não dizia que eram mil e quinhentos euros por
    dia."""
    base = Base([_doc(loja_id="loja-nova", total_bruto=1500.0)],
                LOJAS + [{"id": "loja-nova", "nome": "App Online"}], UNIDADES_BD)

    r = _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert any("App Online" in q and "1500.00" in q for q in r["errors"]), r["errors"]


def test_uma_loja_sem_unidade_e_sem_vendas_nao_faz_barulho():
    """Um aviso que aparece todos os dias deixa de ser lido. Só se queixa de
    uma loja quando ela tem dinheiro por entrar."""
    base = Base([_doc()], LOJAS + [{"id": "loja-nova", "nome": "App Online"}],
                UNIDADES_BD)

    r = _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert r["errors"] == []


def test_um_documento_fora_do_intervalo_nao_e_gravado():
    """A leitura é propositadamente mais larga do que os dias pedidos (para o
    corte de Lisboa ser exacto nas pontas), mas o que se GRAVA é só o que
    cabe no intervalo."""
    base = Base(
        [_doc(emitido_em="2026-09-02T14:00:00+00:00", total_bruto=77.0),
         _doc(id="d2", emitido_em="2026-09-03T14:00:00+00:00", total_bruto=10.0)],
        LOJAS, UNIDADES_BD,
    )

    r = _corre(fin.sincronizar(base, "2026-09-03", "2026-09-03"))

    assert r["written"] == 1
    assert base.fin_sales.docs[0]["date"] == "2026-09-03"
    assert base.fin_sales.docs[0]["amount"] == 10.0
