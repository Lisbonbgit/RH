"""Os identificadores do CRM: uuid4 em texto minúsculo, como o `str(uuid.uuid4())` (F3).

As rotas recebem ids de paragens e de lojas no corpo (`ordem`, `paragens`,
`retirar`, `loja_id`) e verificam-nos aqui. O padrão é o próprio objeto do
`validador_loja._UUID4` (o mesmo `re.Pattern`, não uma cópia): esse fica no
sítio, numa só linha, porque o `frontend/src/lib/crm/ids.test.js` o lê do
ficheiro (T2.21).
"""
from .validador_loja import _UUID4 as PADRAO_UUID4


def e_uuid4(valor) -> bool:
    """Um uuid4 em texto minúsculo, nada antes nem depois (`fullmatch`).

    Maiúsculas, outras versões, chavetas, um "\\n" no fim, bytes ou um
    `uuid.UUID` não contam.
    """
    return isinstance(valor, str) and PADRAO_UUID4.fullmatch(valor) is not None
