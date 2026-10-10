"""Leitura do corpo dos pedidos de escrita do CRM.

As rotas de escrita NÃO usam modelos Pydantic (plano §1, "Corpos JSON"): leem
o corpo com a dependência `corpo_json` e validam-no no domínio
(`crm/dominio`), para os erros por campo serem as mensagens pt-PT do domínio
(como no CRM autónomo) e não a lista em inglês do FastAPI. Um efeito disto: o
FastAPI não lê nem valida o corpo antes das dependências, por isso a sessão é
verificada primeiro — desde que seja declarada primeiro.

Regra (correções do plano, T1.3/T2.15): a dependência de perfil vem SEMPRE
antes de `corpo_json` na assinatura da rota. O FastAPI resolve as
dependências pela ordem em que são declaradas; ao contrário, um pedido sem
sessão e com JSON inválido recebia 400 em vez de 403/401
(tests/crm/test_erros.py prova os dois sentidos).

Porta de Pedido::json() do CRM autónomo, com duas diferenças assumidas:
- não se exige `Content-Type: application/json`: lá servia de defesa para as
  sessões em cookie; no portal a sessão vai no cabeçalho Authorization, que
  um formulário de outro site não consegue enviar;
- a mensagem é sempre a mesma ("O pedido não é JSON válido.").
"""
import json

from fastapi import Request

from .erros import MENSAGEM_JSON_INVALIDO, erro


def _recusar_constante(nome: str):
    # O json.loads aceita NaN, Infinity e -Infinity, que não são JSON (o
    # json_decode do PHP e o JSON.parse do browser recusam-nos).
    raise ValueError(f"constante não JSON: {nome}")


async def corpo_json(request: Request) -> dict:
    """O corpo do pedido como dicionário.

    - corpo vazio (ou só espaços) → `{}`, como no CRM autónomo: a validação
      do domínio é que diz o que falta (422 com os campos);
    - tem de ser um OBJETO JSON em UTF-8; uma lista, um texto, `null`, um
      número, JSON partido, bytes que não são UTF-8, um BOM no início, NaN ou
      Infinity, ou um objeto fundo demais → 400 `json_invalido`.
    """
    bruto = await request.body()
    if not bruto.strip():
        return {}
    try:
        valor = json.loads(bruto.decode("utf-8"), parse_constant=_recusar_constante)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # JSONDecodeError é um ValueError. RecursionError: o descodificador do
        # Python desiste a partir de uns milhares de níveis (sem isto, 500).
        raise erro(400, "json_invalido", MENSAGEM_JSON_INVALIDO) from None
    if not isinstance(valor, dict):
        raise erro(400, "json_invalido", MENSAGEM_JSON_INVALIDO)
    return valor
