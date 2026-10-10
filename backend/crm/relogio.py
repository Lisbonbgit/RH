"""O relógio do CRM: a fonte única do "agora" e o formato dos instantes.

Porta mínima de src/Dominio/Relogio/* do CRM autónomo: instantes sempre em
UTC, venha o processo com o fuso que vier (o Mac está em Lisboa, o contentor
em UTC).

Formato (plano §1, "Tempo"): todos os instantes `*_em` e `fase_desde`,
exceto `atualizado_em`, guardam-se como texto de largura fixa
`AAAA-MM-DDTHH:MM:SSZ`, escritos SÓ por `instante()`. O texto ordena por
caracteres: misturar `+00:00` (o que o isoformat do Python dá, por isso
proibido no pacote crm — grep da T2.8) ou
casas decimais partia a ordenação, o índice `(loja_id, ocorrida_em)` e o
`$max` da F4. Os `atualizado_em` (6 casas, estritamente crescentes) chegam
na T2.8 com `carimbo`, `ler_carimbo` e `proximo_carimbo`.

Substituível: tudo o que precisa das horas chama `relogio.agora()` (ou
`relogio.instante()`) através do módulo, e os testes param-no com
`monkeypatch.setattr(relogio, "agora", lambda: <datetime UTC>)`.
"""
from datetime import datetime, timezone


def agora() -> datetime:
    """O instante atual, com fuso UTC."""
    return datetime.now(timezone.utc)


def instante(momento: "datetime | None" = None) -> str:
    """`momento` (por omissão, `agora()`) como `AAAA-MM-DDTHH:MM:SSZ`, em UTC.

    Os microssegundos cortam-se (não se arredonda para o segundo seguinte).
    Uma datetime sem fuso é recusada (ValueError): seria a hora de Lisboa no
    Mac e a de UTC no contentor.
    """
    if momento is None:
        momento = agora()
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("instante() precisa de uma datetime com fuso")
    u = momento.astimezone(timezone.utc)
    return f"{u.year:04d}-{u.month:02d}-{u.day:02d}T{u.hour:02d}:{u.minute:02d}:{u.second:02d}Z"
