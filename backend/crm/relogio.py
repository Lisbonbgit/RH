"""O relógio do CRM: a fonte única do "agora" e o formato dos instantes.

Porta mínima de src/Dominio/Relogio/* do CRM autónomo: instantes sempre em
UTC, venha o processo com o fuso que vier (o Mac está em Lisboa, o contentor
em UTC).

Formato (plano §1, "Tempo"): todos os instantes `*_em` e `fase_desde`,
exceto `atualizado_em`, guardam-se como texto de largura fixa
`AAAA-MM-DDTHH:MM:SSZ`, escritos SÓ por `instante()`. O texto ordena por
caracteres: misturar `+00:00` (o que o isoformat do Python dá, por isso
proibido no pacote crm — varrimento em tests/crm/test_instantes_gravados.py)
ou casas decimais partia a ordenação, o índice `(loja_id, ocorrida_em)` e o
`$max` da F4.

Os `atualizado_em` são carimbos (T2.8): sempre com 6 casas
(`AAAA-MM-DDTHH:MM:SS.ffffffZ`), escritos SÓ por `carimbo()` e
`proximo_carimbo()`, e estritamente crescentes em cada documento. São a
versão do bloqueio otimista (`update_one({"id", "atualizado_em": versao})`):
o Mongo compara-os como texto, e a largura fixa faz essa ordem igual à do
tempo.

Substituível: tudo o que precisa das horas chama `relogio.agora()` (ou
`relogio.instante()`/`relogio.carimbo()`) através do módulo, e os testes
param-no com `monkeypatch.setattr(relogio, "agora", lambda: <datetime UTC>)`.
"""
import re
from datetime import datetime, timedelta, timezone

# O carimbo exato, só com algarismos ASCII ([0-9], nunca \d) e sem nada antes
# nem depois (fullmatch: o `$` aceitava um "\n" final).
_CARIMBO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{6})Z")

_UM_MICROSSEGUNDO = timedelta(microseconds=1)


def agora() -> datetime:
    """O instante atual, com fuso UTC."""
    return datetime.now(timezone.utc)


def _em_utc(momento: "datetime | None") -> datetime:
    """`momento` (por omissão, `agora()`) em UTC. Uma datetime sem fuso é
    recusada (ValueError): seria a hora de Lisboa no Mac e a de UTC no
    contentor."""
    if momento is None:
        momento = agora()
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("o relógio do CRM precisa de uma datetime com fuso")
    return momento.astimezone(timezone.utc)


def instante(momento: "datetime | None" = None) -> str:
    """`momento` (por omissão, `agora()`) como `AAAA-MM-DDTHH:MM:SSZ`, em UTC.

    Os microssegundos cortam-se (não se arredonda para o segundo seguinte).
    Uma datetime sem fuso é recusada (ValueError).
    """
    u = _em_utc(momento)
    return f"{u.year:04d}-{u.month:02d}-{u.day:02d}T{u.hour:02d}:{u.minute:02d}:{u.second:02d}Z"


def carimbo(momento: "datetime | None" = None) -> str:
    """`momento` (por omissão, `agora()`) como `AAAA-MM-DDTHH:MM:SS.ffffffZ`,
    em UTC, sempre com as 6 casas (o `Formatar::instanteMicro` do autónomo).
    É o `atualizado_em` de um documento novo; para alterar um que já existe,
    `proximo_carimbo`. Uma datetime sem fuso é recusada (ValueError)."""
    u = _em_utc(momento)
    return (
        f"{u.year:04d}-{u.month:02d}-{u.day:02d}"
        f"T{u.hour:02d}:{u.minute:02d}:{u.second:02d}.{u.microsecond:06d}Z"
    )


def _ler(valor) -> "datetime | None":
    """O carimbo `valor` como datetime UTC, ou None se não for um carimbo
    exato com uma data e uma hora que existam."""
    if not isinstance(valor, str):
        return None
    partes = _CARIMBO.fullmatch(valor)
    if partes is None:
        return None
    try:
        return datetime(*(int(p) for p in partes.groups()), tzinfo=timezone.utc)
    except ValueError:  # 30 de fevereiro, 24:00, segundo 60, ano 0…
        return None


def ler_carimbo(valor) -> "str | None":
    """O `atualizado_em` que o cliente devolve no PATCH, já verificado: o
    próprio texto, se for um carimbo exato (6 casas, `Z`, nada antes nem
    depois) com uma data e uma hora que existam; senão None (o
    `Formatar::lerInstanteMicro` do autónomo).

    Devolve-se o texto porque a versão se guarda no formato da API: vai
    direta para o filtro `{"id": id, "atualizado_em": versao}` da atualização
    condicional, e nunca é um operador do Mongo (`{"$gt": ""}` → None).
    """
    return valor if _ler(valor) is not None else None


def proximo_carimbo(momento: datetime, anterior: str) -> str:
    """A versão nova de um documento cujo `atualizado_em` é `anterior`: o
    carimbo de `momento` ou, se o relógio estiver atrás (no mesmo
    microssegundo ou antes), o do microssegundo a seguir ao anterior — muda
    SEMPRE e é sempre maior (o `GREATEST(?, atualizado_em + INTERVAL 1
    MICROSECOND)` do `LojasRepositorio::atualizar` do autónomo).

    `anterior` tem de ser um carimbo (ValueError, senão): sem o ler não se
    garante que o novo é maior. Depois do último que existe
    (9999-12-31T23:59:59.999999Z) não há seguinte (OverflowError). Uma
    datetime sem fuso é recusada (ValueError).
    """
    lido = _ler(anterior)
    if lido is None:
        raise ValueError("o anterior não é um carimbo AAAA-MM-DDTHH:MM:SS.ffffffZ")
    return carimbo(max(_em_utc(momento), lido + _UM_MICROSSEGUNDO))
