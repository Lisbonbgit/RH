import pytest
from pydantic import ValidationError

from faturacao.motivos import MotivoEntrada


def test_motivo_valido():
    assert MotivoEntrada(texto="Cliente enganou-se no NIF").texto == "Cliente enganou-se no NIF"


def test_motivo_vazio_e_recusado():
    with pytest.raises(ValidationError):
        MotivoEntrada(texto="")


def test_motivo_demasiado_longo_e_recusado():
    """Vai para o campo notes do documento fiscal — não pode ser um romance."""
    with pytest.raises(ValidationError):
        MotivoEntrada(texto="x" * 201)
