"""**Calendário das lojas** — onde falta gente, calculado (nunca guardado).

O dono quer que o calendário faça sozinho a conta que a Carol e a Débora faziam de cabeça
(desenho `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`, secção 2): com o
horário de cada loja, a escala de cada pessoa, as ausências aprovadas no RH e as idas
marcadas, diz onde falta gente.

**Este módulo não fala com o Mongo nem com o FastAPI, e é de propósito** (o mesmo princípio
do `bolso.py`): as rotas vivem no `server.py` e trazem para aqui listas de dicionários; aqui
fica só a matemática, que assim se testa com listas em memória.

Horas em minutos desde a meia-noite; intervalos `(inicio, fim)` semiabertos. Dias da semana
0 = segunda … 6 = domingo, como o `work_days` do RH. Horários que passam da meia-noite estão
fora do âmbito (nenhuma loja passa hoje).
"""
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

Intervalo = Tuple[int, int]

GESTORES = ("admin", "gerente")
ESCALAVEIS = ("admin", "gerente", "colaborador")
NOME_SEM_CONTA = "(conta removida)"
NOME_SEM_LOJA = "(loja removida)"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def minutos(hhmm_: str) -> int:
    horas, mins = hhmm_.split(":")
    return int(horas) * 60 + int(mins)


def hhmm(total: int) -> str:
    return "%02d:%02d" % (total // 60, total % 60)


def hora_curta(hhmm_: str) -> str:
    """«10:00» -> «10h», «11:30» -> «11h30» — como se escreve numa mensagem."""
    horas, mins = hhmm_.split(":")
    return "%dh" % int(horas) if mins == "00" else "%dh%s" % (int(horas), mins)


def data_curta(iso: str) -> str:
    return "%s/%s" % (iso[8:10], iso[5:7])


def primeiro_nome(nome: Optional[str]) -> str:
    partes = (nome or "").split()
    return partes[0] if partes else ""


def unir(intervalos: List[Intervalo]) -> List[Intervalo]:
    """A união, ordenada; intervalos encostados juntam-se e os vazios desaparecem."""
    fora = []  # type: List[Intervalo]
    for inicio, fim in sorted(i for i in intervalos if i[0] < i[1]):
        if fora and inicio <= fora[-1][1]:
            fora[-1] = (fora[-1][0], max(fora[-1][1], fim))
        else:
            fora.append((inicio, fim))
    return fora


def subtrair(base: List[Intervalo], tirar: List[Intervalo]) -> List[Intervalo]:
    """`base` menos `tirar`, em intervalos. É daqui que saem os buracos."""
    resto = unir(base)
    for t_inicio, t_fim in unir(tirar):
        novo = []
        for inicio, fim in resto:
            if t_fim <= inicio or t_inicio >= fim:
                novo.append((inicio, fim))
                continue
            if inicio < t_inicio:
                novo.append((inicio, t_inicio))
            if t_fim < fim:
                novo.append((t_fim, fim))
        resto = novo
    return resto


def recortar(intervalo: Intervalo, janela: Intervalo) -> Optional[Intervalo]:
    """A parte de `intervalo` dentro de `janela`; `None` se não se tocarem (encostar não é tocar)."""
    inicio, fim = max(intervalo[0], janela[0]), min(intervalo[1], janela[1])
    return (inicio, fim) if inicio < fim else None


def horario_do_dia(loja: Optional[Dict], dia: date) -> Tuple[str, Optional[Intervalo]]:
    """O estado da loja nesse dia e, se abre, as horas.

    Estados: `sem_horario` (a loja não entra no calendário: Pizzaria, escritórios, loja
    apagada), `por_abrir` (antes de `aberta_desde`), `fechada` (o dia da semana está em
    `fechada`) e `aberta` (com a excepção desse dia da semana, ou o horário geral).
    Feriado NÃO fecha a loja — decisão do dono.
    """
    horario = (loja or {}).get("horario")
    if not horario:
        return "sem_horario", None
    desde = loja.get("aberta_desde")
    if desde and dia.isoformat() < desde:
        return "por_abrir", None
    semana = dia.weekday()
    if semana in (horario.get("fechada") or []):
        return "fechada", None
    excecao = next((e for e in horario.get("excecoes") or [] if e.get("dia") == semana), None)
    fonte = excecao or horario
    return "aberta", (minutos(fonte["abre"]), minutos(fonte["fecha"]))


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo anónimo gregoriano — o mesmo do `server._easter_sunday`)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> Dict[date, str]:
    """Os feriados nacionais COM NOME.

    O `server.get_pt_holidays` devolve as mesmas datas num `set` (os nomes estão lá em
    comentários) e guarda-as numa cache que o saldo de férias usa; este dicionário é
    construído à parte para não lhe tocar. Um teste confere que as datas são as mesmas.
    """
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Ano Novo",
        p - timedelta(days=2): "Sexta-feira Santa",
        p: "Páscoa",
        date(ano, 4, 25): "Dia da Liberdade",
        date(ano, 5, 1): "Dia do Trabalhador",
        p + timedelta(days=60): "Corpo de Deus",
        date(ano, 6, 10): "Dia de Portugal",
        date(ano, 8, 15): "Assunção de Nossa Senhora",
        date(ano, 10, 5): "Implantação da República",
        date(ano, 11, 1): "Todos os Santos",
        date(ano, 12, 1): "Restauração da Independência",
        date(ano, 12, 8): "Imaculada Conceição",
        date(ano, 12, 25): "Natal",
    }


def _cai_no_dia(feriado: Dict, dia: date) -> bool:
    # Compara números e nunca constrói a data: um personalizado de 30/02 (o formulário
    # aceita-o) simplesmente nunca cai em dia nenhum, em vez de dar um 500.
    try:
        return (int(feriado["month"]), int(feriado["day"])) == (dia.month, dia.day)
    except (KeyError, TypeError, ValueError):
        return False


def feriados_do_dia(dia: date, personalizados: List[Dict]) -> List[str]:
    """Os do dia inteiro: o nacional (se houver) e os personalizados de âmbito grupo."""
    nomes = []
    nacional = feriados_nacionais(dia.year).get(dia)
    if nacional:
        nomes.append(nacional)
    nomes += [h.get("name") or "Feriado" for h in personalizados
              if not h.get("company_id") and not h.get("location_id") and _cai_no_dia(h, dia)]
    return nomes


def feriados_da_loja(dia: date, personalizados: List[Dict], loja: Dict) -> List[str]:
    """Os personalizados da empresa da loja ou da própria loja (a regra «OU» do saldo de férias)."""
    return [h.get("name") or "Feriado" for h in personalizados
            if _cai_no_dia(h, dia) and (
                (h.get("company_id") and h.get("company_id") == loja.get("company_id"))
                or (h.get("location_id") and h.get("location_id") == loja.get("id")))]
