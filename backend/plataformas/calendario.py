"""**Os períodos e as datas de pagamento das plataformas** — aritmética de
calendário pura, sem Mongo, sem rede e sem email.

Cada plataforma paga ao seu ritmo, e é esse ritmo que decide DE QUE PERÍODO
fala o relatório de segunda-feira:

- **Uber Eats** e **Bolt Food**: a semana corre de segunda a domingo e é paga
  na segunda-feira seguinte. Na manhã de segunda, a semana de que se fala é a
  que acabou ontem.
- **Glovo**: paga de quinze em quinze dias. As vendas de 1 a 15 são pagas no
  dia 5 do mês seguinte; as de 16 até ao fim do mês, no dia 20 do mês seguinte.

**Estas datas foram ditadas pelo dono e são a regra de negócio inteira.** Se
a Glovo mudar as condições, muda-se aqui — num sítio só, com testes que dizem
o que se partiu. Não há uma segunda cópia destas contas em lado nenhum.

Tudo aqui trabalha com `datetime.date` e devolve `date`. A conversão de e para
texto ISO faz-se nas bordas (nas rotas e no email), porque é lá que os valores
entram e saem da base de dados.
"""
import calendar
from datetime import date, timedelta
from typing import Dict, Tuple

# As três plataformas, pela ordem em que aparecem no email. A chave é o que vai
# para a base de dados e para o JSON; o nome é o que se lê.
PLATAFORMAS = (
    {"chave": "uber", "nome": "Uber Eats", "ritmo": "semana"},
    {"chave": "bolt", "nome": "Bolt Food", "ritmo": "semana"},
    {"chave": "glovo", "nome": "Glovo", "ritmo": "quinzena"},
)

NOMES = {p["chave"]: p["nome"] for p in PLATAFORMAS}

# Os dias do mês em que a Glovo paga cada quinzena, no mês SEGUINTE ao das
# vendas. Ditado pelo dono; ver a docstring do módulo.
DIA_PAGAMENTO_GLOVO_1A15 = 5
DIA_PAGAMENTO_GLOVO_16AFIM = 20


def semana_fechada(hoje: date) -> Tuple[date, date]:
    """A última semana de segunda a domingo que já ACABOU.

    Numa segunda-feira (o dia em que o relatório sai) é a semana que acabou
    ontem. Num dia qualquer a meio da semana é a semana anterior — e nunca a
    que está a decorrer, porque uma semana a meio não tem relatório nenhum das
    plataformas e o email diria números que ainda vão mudar.
    """
    # `weekday()` dá 0 à segunda. Recuar `weekday + 1` dias cai sempre no
    # domingo anterior: de segunda recua 1 dia, de domingo recua 7.
    fim = hoje - timedelta(days=hoje.weekday() + 1)
    return fim - timedelta(days=6), fim


def chave_da_semana(inicio: date) -> str:
    """`2026-W35` — o identificador ISO da semana, usado como chave do envio.

    Sai do calendário ISO e não do ano civil do dia 1 de Janeiro: a semana que
    começa a 29 de Dezembro de 2025 é a `2026-W01`, e uma chave feita com
    `inicio.year` chamar-lhe-ia `2025-W01` — a mesma chave que a primeira
    semana de Janeiro de 2025 já tinha usado. Duas semanas com a mesma chave é
    um relatório que não é enviado porque «já foi».
    """
    ano_iso, semana_iso, _ = inicio.isocalendar()
    return "%04d-W%02d" % (ano_iso, semana_iso)


def pagamento_semanal(fim: date) -> date:
    """A segunda-feira a seguir ao domingo em que a semana fechou.

    É quando a Uber e a Bolt pagam — e, na manhã de segunda em que o relatório
    sai, é hoje.
    """
    return fim + timedelta(days=1)


def _ultimo_dia_do_mes(dia: date) -> date:
    """O dia 28, 29, 30 ou 31 — conforme o mês, e conforme o ano ser bissexto.

    `calendar.monthrange` é da biblioteca padrão e já sabe isto tudo. Uma
    tabela de dias por mês escrita à mão neste ficheiro era uma segunda
    verdade sobre Fevereiro à espera de discordar da primeira.
    """
    return dia.replace(day=calendar.monthrange(dia.year, dia.month)[1])


def _mes_seguinte(dia: date) -> Tuple[int, int]:
    """(ano, mês) do mês a seguir a este. Dezembro passa a Janeiro do ano
    seguinte — a viragem que um `mes + 1` cru transformava no mês 13."""
    if dia.month == 12:
        return dia.year + 1, 1
    return dia.year, dia.month + 1


def quinzena_de(dia: date) -> Tuple[date, date]:
    """A quinzena a que este dia pertence: 1 a 15, ou 16 até ao fim do mês."""
    if dia.day <= 15:
        return dia.replace(day=1), dia.replace(day=15)
    return dia.replace(day=16), _ultimo_dia_do_mes(dia)


def quinzena_fechada(hoje: date) -> Tuple[date, date]:
    """A última quinzena que já acabou POR INTEIRO.

    Recua-se a partir do INÍCIO da quinzena em curso, e não um dia a partir de
    hoje. A diferença aparece no último dia do mês: a 31 de Agosto, "ontem"
    (dia 30) ainda pertence à quinzena de 16 a 31, que só fecha ao fim do dia
    de hoje — e o relatório apresentava-a como fechada com as vendas de hoje
    por contar. A que fechou mesmo é a de 1 a 15.

    Recuar um dia a partir do início trata as viragens de mês e de ano sem
    nenhum caso especial escrito: a 1 de Janeiro leva a 31 de Dezembro do ano
    anterior.
    """
    inicio_em_curso, _ = quinzena_de(hoje)
    return quinzena_de(inicio_em_curso - timedelta(days=1))


def pagamento_glovo(inicio: date) -> date:
    """Quando é paga a quinzena que começou neste dia.

    A quinzena de 1 a 15 é paga no dia 5 do mês seguinte; a de 16 ao fim do
    mês, no dia 20 do mês seguinte. Decide-se pelo dia de INÍCIO (1 ou 16) e
    não pelo fim, porque o fim muda com o mês e o início não.
    """
    ano, mes = _mes_seguinte(inicio)
    dia = DIA_PAGAMENTO_GLOVO_1A15 if inicio.day <= 15 else DIA_PAGAMENTO_GLOVO_16AFIM
    return date(ano, mes, dia)


def dias_ate(alvo: date, hoje: date) -> int:
    """Quantos dias faltam. Negativo quando a data já passou — e é isso que
    distingue "falta uma semana" de "já devia ter entrado há uma semana"."""
    return (alvo - hoje).days


def periodo_da_plataforma(chave: str, hoje: date) -> Dict:
    """O período fechado de que o relatório de hoje fala, para uma plataforma,
    com a data em que é pago.

    Devolve sempre o mesmo formato para as três, para o email não ter de saber
    qual delas paga a que ritmo:

        {"tipo", "inicio", "fim", "chave", "pagamento", "dias_para_pagamento",
         "pago"}

    `pago` é a leitura honesta da data: a Uber e a Bolt pagam no próprio dia em
    que o email sai (`dias_para_pagamento == 0`), e a Glovo pode ter a data já
    passada quando o relatório é aberto uma semana depois.
    """
    if chave == "glovo":
        inicio, fim = quinzena_fechada(hoje)
        pagamento = pagamento_glovo(inicio)
        tipo = "quinzena"
        identificador = "%s..%s" % (inicio.isoformat(), fim.isoformat())
    else:
        inicio, fim = semana_fechada(hoje)
        pagamento = pagamento_semanal(fim)
        tipo = "semana"
        identificador = chave_da_semana(inicio)
    return {
        "tipo": tipo,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "chave": identificador,
        "pagamento": pagamento.isoformat(),
        "dias_para_pagamento": dias_ate(pagamento, hoje),
        "pago": pagamento <= hoje,
    }


def calendario_glovo(hoje: date) -> Dict:
    """O bloco de calendário da Glovo — o que o email mostra MESMO quando não
    chegou email nenhum da Glovo.

    O dono pediu-o por extenso: a Uber e a Bolt pagam todas as segundas, a
    Glovo não, e o que ele quer saber na segunda de manhã é em que ponto está
    a quinzena e quando é que o dinheiro entra. Isto é calendário, não é
    leitura de email nenhum — e é por isso que nunca falha nem fica a "—".
    """
    inicio_curso, fim_curso = quinzena_de(hoje)
    inicio_fechada, fim_fechada = quinzena_fechada(hoje)
    pagamento_fechada = pagamento_glovo(inicio_fechada)
    pagamento_curso = pagamento_glovo(inicio_curso)
    return {
        "em_curso": {
            "inicio": inicio_curso.isoformat(),
            "fim": fim_curso.isoformat(),
            "dias_para_fechar": dias_ate(fim_curso, hoje),
            "pagamento": pagamento_curso.isoformat(),
            "dias_para_pagamento": dias_ate(pagamento_curso, hoje),
        },
        "fechada": {
            "inicio": inicio_fechada.isoformat(),
            "fim": fim_fechada.isoformat(),
            "pagamento": pagamento_fechada.isoformat(),
            "dias_para_pagamento": dias_ate(pagamento_fechada, hoje),
            "pago": pagamento_fechada <= hoje,
        },
    }
