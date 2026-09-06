"""**Gestão de Bolso** — a faturação do grupo no telemóvel do gestor.

Uma secção só-leitura em `/bolso`, feita para o polegar: quanto se fez ontem,
hoje, este mês e este ano — do grupo inteiro, de cada empresa e de cada loja.

## As três regras que mandam neste ficheiro

**1. A comparação é sempre com o período EQUIVALENTE.** É o defeito do
dashboard do Vendus, e o `faturacao/periodos.py` existe por causa dele: a 13 de
Agosto ele comparava 13 dias de Agosto com Julho INTEIRO e anunciava −64%
quando o negócio ia a subir. Aqui o mês compara-se com os MESMOS dias do mês
anterior, e o ano com os mesmos dias do ano anterior.

**2. O cartão de HOJE não leva variação, e é de propósito.** O `fin_sales`
guarda dias, não horas: não há forma de comparar "hoje até às 9h" com "ontem
até às 9h". Comparar com ontem INTEIRO dá −85% todas as manhãs, todos os dias.
Mostra-se o valor e diz-se que o dia está a decorrer. Um número sem seta é
melhor do que uma seta inventada.

**3. Um número que não se sabe escreve-se "—", nunca zero.** Vale para o valor
sem IVA quando uma das linhas do dia não o traz (as linhas que vêm do nosso POS
podem não trazer — ver `fin_faturacao`), e vale para a percentagem quando não
há período anterior com que comparar.

## O que este módulo NÃO faz

Não escreve nada. Não soma `fat_documentos` a `fin_sales` — lê **só**
`fin_sales`, que é onde as três origens (Vendus, Moloni e o nosso POS) já estão
reunidas e reconciliadas. Quem quiser saber de onde veio cada euro olha para o
`source` das linhas, não para uma segunda soma feita aqui.
"""
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from faturacao.periodos import LISBON_TZ, variacao

logger = logging.getLogger(__name__)

# **Este módulo não tem rota nenhuma, e é de propósito.** A rota vive no
# `server.py`, onde já estão a base de dados e as guardas de pertença
# (`_fin_report_scope`); aqui fica só a matemática, que assim se testa com
# listas em memória — sem Mongo, sem rede, sem FastAPI. Foi essa separação que
# permitiu provar, com um teste, que uma venda das 00:30 cai no dia certo.

MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

# Quantos dias e meses vão nas séries do painel. Trinta dias cabem num
# telemóvel de lado a lado sem virar sopa de pixels; seis meses são o que
# responde a "estamos melhores do que no início do semestre?" sem obrigar a
# abrir o ecrã da Evolução (que mostra treze).
DIAS_DA_SERIE = 30
MESES_DA_SERIE = 6


def hoje_em_lisboa(agora: Optional[datetime] = None) -> date:
    """O dia de hoje no relógio de Lisboa.

    O servidor corre em UTC. Entre a meia-noite e a uma da manhã de Verão, em
    Lisboa já é o dia seguinte e em UTC ainda não — e o painel mostrava o dia
    errado exactamente à hora a que as lojas fecham a caixa.
    """
    agora = agora or datetime.now(LISBON_TZ)
    return agora.astimezone(LISBON_TZ).date()


def _dia_valido(ano: int, mes: int, dia: int) -> date:
    """A data, com o dia limitado ao último do mês.

    31 de Março menos um mês não é 31 de Fevereiro. Sem esta trava, a
    comparação do mês rebentava em quatro meses do ano — e rebentava com uma
    excepção, no meio de um painel de leitura.
    """
    return date(ano, mes, min(dia, monthrange(ano, mes)[1]))


def _mes_anterior(dia: date) -> date:
    return _dia_valido(dia.year if dia.month > 1 else dia.year - 1,
                       dia.month - 1 if dia.month > 1 else 12, dia.day)


def janelas(hoje: date) -> Dict[str, Optional[tuple]]:
    """Todos os intervalos de dias que o painel precisa, em datas de Lisboa.

    Cada valor é `(desde, ate)` inclusivo, ou `None` quando o período não
    existe — e `None` é uma resposta legítima, não um erro: no dia 1 de cada
    mês ainda não há um único dia COMPLETO deste mês, e é por isso que a
    comparação do mês nesse dia não se faz em vez de se fazer contra nada.
    """
    ontem = hoje - timedelta(days=1)
    anteontem = hoje - timedelta(days=2)
    primeiro_do_mes = hoje.replace(day=1)
    primeiro_do_ano = hoje.replace(month=1, day=1)

    # Os dias COMPLETOS deste mês/ano: do dia 1 até ontem. Se hoje é dia 1,
    # não há nenhum.
    mes_completo = (primeiro_do_mes, ontem) if ontem >= primeiro_do_mes else None
    ano_completo = (primeiro_do_ano, ontem) if ontem >= primeiro_do_ano else None

    mes_anterior = None
    if mes_completo:
        fim = _mes_anterior(ontem)
        mes_anterior = (fim.replace(day=1), fim)

    ano_anterior = None
    if ano_completo:
        fim = _dia_valido(ontem.year - 1, ontem.month, ontem.day)
        ano_anterior = (fim.replace(month=1, day=1), fim)

    return {
        "hoje": (hoje, hoje),
        "ontem": (ontem, ontem),
        "anteontem": (anteontem, anteontem),
        # O VALOR do mês/ano inclui hoje (é o que o gestor quer ver); a
        # COMPARAÇÃO usa só os dias completos, acima. São coisas diferentes e
        # é por isso que são duas janelas e não uma.
        "mes": (primeiro_do_mes, hoje),
        "ano": (primeiro_do_ano, hoje),
        "mes_completo": mes_completo,
        "mes_anterior": mes_anterior,
        "ano_completo": ano_completo,
        "ano_anterior": ano_anterior,
    }


def _iso(intervalo) -> Optional[tuple]:
    if not intervalo:
        return None
    return (intervalo[0].isoformat(), intervalo[1].isoformat())


def somar(linhas: List[Dict], intervalo) -> Dict:
    """Soma as linhas de `fin_sales` cujo dia cai no intervalo (inclusivo).

    `sem_iva` fica a `None` assim que UMA linha do intervalo não trouxer
    `amount_net`. A soma das outras seria menor do que a verdade, e é dela que
    sairia a margem e o IVA — prefere-se dizer que não se sabe.
    """
    if not intervalo:
        return {"total": None, "sem_iva": None, "linhas": 0}
    desde, ate = _iso(intervalo)
    total, sem_iva, quantas, completo = 0.0, 0.0, 0, True
    for l in linhas:
        dia = l.get("date")
        if not dia or dia < desde or dia > ate:
            continue
        total += float(l.get("amount") or 0)
        quantas += 1
        liquido = l.get("amount_net")
        if liquido is None:
            completo = False
        else:
            sem_iva += float(liquido)
    return {
        "total": round(total, 2),
        "sem_iva": round(sem_iva, 2) if completo else None,
        "linhas": quantas,
    }


def _formata_intervalo(intervalo) -> str:
    """"5 de setembro" ou "1 a 5 de setembro" — a frase que explica o que foi
    comparado com o quê. Sem ela, uma percentagem é uma afirmação sem
    contexto."""
    if not intervalo:
        return ""
    de, ate = intervalo
    if de == ate:
        return "%d de %s" % (de.day, MESES_PT[de.month - 1])
    if (de.month, de.year) == (ate.month, ate.year):
        return "%d a %d de %s" % (de.day, ate.day, MESES_PT[de.month - 1])
    # **O ANO tem de aparecer nesta forma.** Sem ele, a comparação do cartão do
    # Ano lia-se "1/1 a 5/9 vs 1/1 a 5/9" — a mesma frase dos dois lados, como
    # se o período fosse comparado consigo próprio. Um número ao lado de uma
    # frase que não faz sentido é um número em que se deixa de acreditar.
    return "%d/%d a %d/%d de %d" % (de.day, de.month, ate.day, ate.month, ate.year)


def cartao(linhas: List[Dict], janela, janela_actual=None, janela_anterior=None,
           nota: Optional[str] = None) -> Dict:
    """Um cartão do painel: o valor, e — quando faz sentido — a comparação.

    `janela` é o que o número GRANDE mostra. `janela_actual`/`janela_anterior`
    são o que a percentagem compara, e podem ser outras (o mês mostra-se até
    hoje mas compara-se até ontem). Sem elas, o cartão fica sem percentagem —
    que é o caso do cartão de hoje.
    """
    valor = somar(linhas, janela)
    saida = {
        "valor": valor["total"],
        "valor_sem_iva": valor["sem_iva"],
        "periodo": _formata_intervalo(janela),
        "variacao": None,
        "anterior": None,
        "comparacao": None,
        "nota": nota,
    }
    if janela_actual and janela_anterior:
        agora = somar(linhas, janela_actual)
        antes = somar(linhas, janela_anterior)
        saida["anterior"] = antes["total"]
        saida["variacao"] = variacao(agora["total"] or 0.0, antes["total"] or 0.0)
        saida["comparacao"] = "%s vs %s" % (
            _formata_intervalo(janela_actual), _formata_intervalo(janela_anterior)
        )
    return saida


def serie_de_dias(linhas: List[Dict], hoje: date, dias: int = DIAS_DA_SERIE) -> List[Dict]:
    """Os últimos N dias, TODOS eles — os dias sem vendas entram a zero.

    Saltar os dias vazios (que é o que o `fin_sales` faz: não gera linha para
    um dia sem vendas) desenhava um gráfico que encolhe os fins-de-semana
    fechados e mente sobre o ritmo do negócio.
    """
    por_dia = {}
    for l in linhas:
        por_dia[l.get("date")] = por_dia.get(l.get("date"), 0.0) + float(l.get("amount") or 0)
    saida = []
    for i in range(dias - 1, -1, -1):
        d = (hoje - timedelta(days=i)).isoformat()
        saida.append({"dia": d, "valor": round(por_dia.get(d, 0.0), 2)})
    return saida


def serie_de_meses(linhas: List[Dict], hoje: date, meses: int = MESES_DA_SERIE) -> List[Dict]:
    """Os últimos N meses, incluindo o corrente (que está a meio, e o ecrã
    di-lo)."""
    por_mes = {}
    for l in linhas:
        dia = l.get("date") or ""
        if len(dia) >= 7:
            por_mes[dia[:7]] = por_mes.get(dia[:7], 0.0) + float(l.get("amount") or 0)
    saida = []
    ancora = hoje.replace(day=1)
    for i in range(meses - 1, -1, -1):
        d = ancora
        for _ in range(i):
            d = (d - timedelta(days=1)).replace(day=1)
        chave = "%04d-%02d" % (d.year, d.month)
        saida.append({
            "mes": chave,
            "rotulo": MESES_PT[d.month - 1][:3],
            "valor": round(por_mes.get(chave, 0.0), 2),
            "em_curso": chave == "%04d-%02d" % (hoje.year, hoje.month),
        })
    return saida


def repartir(linhas: List[Dict], intervalo, campo: str, nomes: Dict) -> List[Dict]:
    """A repartição do período por empresa (no grupo) ou por loja (numa
    empresa), de maior para menor.

    Uma linha sem o campo (uma venda manual sem loja, por exemplo) não
    desaparece: aparece como **"Sem loja atribuída"**, com o valor à vista. É
    a mesma regra do resto do portal — nada se cala por não ter onde encaixar.
    """
    if not intervalo:
        return []
    desde, ate = _iso(intervalo)
    somas, sem_iva_completo = {}, {}
    for l in linhas:
        dia = l.get("date")
        if not dia or dia < desde or dia > ate:
            continue
        chave = l.get(campo) or "__sem__"
        somas[chave] = somas.get(chave, 0.0) + float(l.get("amount") or 0)
        if l.get("amount_net") is None:
            sem_iva_completo[chave] = False
        else:
            sem_iva_completo.setdefault(chave, True)
    saida = [
        {
            "id": None if chave == "__sem__" else chave,
            "nome": nomes.get(chave, "Sem loja atribuída" if chave == "__sem__" else chave),
            "valor": round(valor, 2),
        }
        for chave, valor in somas.items()
    ]
    return sorted(saida, key=lambda x: -x["valor"])


def dias_sem_linha(linhas: List[Dict], hoje: date, dias: int = 7) -> List[str]:
    """Os dias recentes (até ontem) sem uma única linha de venda.

    **Não afirma que ninguém sincronizou** — afirma o que se vê: não há
    vendas nesse dia. Pode ser uma loja fechada, pode ser uma leitura que não
    correu. Quem sabe distinguir é o registo de leituras (`bol_leituras`), e é
    ele que o ecrã mostra ao lado disto.
    """
    tem = {l.get("date") for l in linhas}
    return [
        d for d in (
            (hoje - timedelta(days=i)).isoformat() for i in range(1, dias + 1)
        ) if d not in tem
    ]
