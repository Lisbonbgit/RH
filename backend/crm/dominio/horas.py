"""As horas da rota em segundos desde a meia-noite local (F3).

Plano F3 §1 ("Horas"): o cálculo conta o tempo em segundos desde a
meia-noite de Lisboa, a partir do texto "HH:MM" do relógio (`h*3600 + m*60`),
e nunca a partir de instantes UTC. Por isso as horas não mudam nos dias de
mudança de hora: "02:30" a 2026-03-29 (que não existe em Lisboa) conta pelo
texto. Este módulo não importa `datetime` nem `zoneinfo` (o teste varre-o).

- **Do texto aos segundos:** `segundos` (as horas validadas como as da ficha
  da loja, por `janelas.hora`) e `janelas_em_segundos` (a lista da base,
  `[{inicio, fim}]`; `[]` quer dizer "sem restrição" e dá `None`).
- **Dos segundos ao texto:** `hora_de_segundos` arredonda ao minuto
  meio-para-longe-do-zero (`numeros.arredondar`; o `round` do Python ia para
  o par: 30,5 min → 30); a partir das 24:00, depois de arredondar, a hora já é
  do dia seguinte e fica `None`. `minutos_de_segundos` dá as esperas.
- **Para o VROOM:** `janelas_vroom` passa as janelas de receção a janelas do
  início do serviço, `[a, b − s]`, só onde o serviço cabe (`b − s ≥ a`).
  `None` (sem restrição) é diferente de `[]` (nenhuma janela leva o serviço:
  a paragem é impossível e não vai ao VROOM, T3.6).
"""
from . import janelas
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .validador_loja import campos_de_janelas

SEGUNDOS_POR_MINUTO = 60
SEGUNDOS_POR_HORA = 3600

# As 24:00 em minutos: uma hora que chega aqui depois de arredondar é do dia seguinte.
MINUTOS_POR_DIA = 1440


def segundos(texto) -> int:
    """Uma hora "HH:MM" em segundos desde a meia-noite: `h*3600 + m*60`.

    Só aceita o que a ficha da loja aceita (`janelas.hora`): vazia, `None`,
    "8:00", "24:00" ou o que não é texto dão `ValueError`.
    """
    valor, erro = janelas.hora(texto)
    if valor is None or erro is not None:
        raise ValueError(f"Hora inválida (HH:MM): {texto!r}")
    horas, minutos = valor.split(":")
    return int(horas) * SEGUNDOS_POR_HORA + int(minutos) * SEGUNDOS_POR_MINUTO


def hora_de_segundos(valor):
    """Segundos desde a meia-noite → "HH:MM", com o minuto arredondado
    meio-para-longe-do-zero (1770 s = 29,5 min → "00:30"; 1830 s → "00:31").

    `None` a partir das 24:00 depois de arredondar (86 370 s → 1440 min), e
    também para um negativo, um não finito, um bool ou o que não é número.
    """
    if not e_numero_json(valor) or valor < 0:
        return None
    minutos = int(arredondar(valor / SEGUNDOS_POR_MINUTO))
    if minutos >= MINUTOS_POR_DIA:
        return None
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def minutos_de_segundos(valor) -> int:
    """Uma duração em segundos → minutos inteiros, meio-para-longe-do-zero
    (89,9 s → 1; 90 s → 2). Um negativo, um não finito ou o que não é número
    é um erro de programação: `ValueError`."""
    if not e_numero_json(valor) or valor < 0:
        raise ValueError(f"Duração inválida em segundos: {valor!r}")
    return int(arredondar(valor / SEGUNDOS_POR_MINUTO))


def janelas_em_segundos(lista):
    """As janelas da base (`[{inicio, fim}]`, 0 a 2) → `[(início_s, fim_s)]`.

    `[]` → `None`: sem janelas, a loja recebe a qualquer hora (sem
    restrição). Só aceita o que o `validador_loja.janelas_para_lista` grava
    (`campos_de_janelas`): o resto é `ValueError`. Devolve uma lista nova.
    """
    campos_de_janelas(lista)
    if not lista:
        return None
    return [(segundos(janela["inicio"]), segundos(janela["fim"])) for janela in lista]


def janelas_vroom(janelas_s, servico_s):
    """As janelas do início do serviço para o VROOM: `[[a, b − s]]`, listas novas.

    O serviço tem de acabar dentro da janela de receção, por isso começa no
    máximo em `b − s`. Uma janela onde o serviço não cabe sai (`b − s == a`
    ainda cabe, a começar à abertura). `None` (sem restrição) → `None`;
    nenhuma janela leva o serviço → `[]`.

    `servico_s` é um inteiro de segundos ≥ 0 e as janelas pares de inteiros
    (`janelas_em_segundos`); o resto é `ValueError`.
    """
    if not e_inteiro_json(servico_s) or servico_s < 0:
        raise ValueError(f"Tempo de serviço inválido em segundos: {servico_s!r}")
    if janelas_s is None:
        return None
    if not isinstance(janelas_s, (list, tuple)):
        raise ValueError("As janelas em segundos têm de ser uma lista de pares.")
    resultado = []
    for janela in janelas_s:
        if not isinstance(janela, (list, tuple)) or len(janela) != 2 or not all(e_inteiro_json(x) for x in janela):
            raise ValueError("Cada janela em segundos é um par de inteiros (início, fim).")
        inicio, fim = janela
        if fim - servico_s >= inicio:
            resultado.append([inicio, fim - servico_s])
    return resultado
