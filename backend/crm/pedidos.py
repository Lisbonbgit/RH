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
import re

from fastapi import Request

from .erros import MENSAGEM_JSON_INVALIDO, erro

# Um surrogate (U+D800–U+DFFF) que ficou sozinho depois do json.loads: um par
# certo em escape (alto e depois baixo) já chega junto, como um só carácter.
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _recusar_constante(nome: str):
    # O json.loads aceita NaN, Infinity e -Infinity, que não são JSON (o
    # json_decode do PHP e o JSON.parse do browser recusam-nos).
    raise ValueError(f"constante não JSON: {nome}")


def _tem_surrogate_sozinho(valor) -> bool:
    """Há um surrogate sozinho neste texto, ou nos textos desta lista (a
    qualquer profundidade de listas)? Os objetos não se percorrem: cada um já
    foi visto pelo `_objeto` quando o json.loads o construiu. Sem recursão: o
    json.loads lê listas mais fundas do que a pilha de uma função recursiva."""
    pendentes = [valor]
    while pendentes:
        atual = pendentes.pop()
        if isinstance(atual, str):
            if _SURROGATE.search(atual) is not None:
                return True
        elif isinstance(atual, list):
            pendentes.extend(atual)
    return False


def _objeto(pares):
    """O `object_pairs_hook` do json.loads: cada objeto, ao ser lido, com TODOS
    os pares — também os de uma chave repetida, que o dict deixa cair (fica o
    último, como no PHP). O `json_decode` recusa o corpo inteiro ao ler um
    surrogate sozinho, mesmo num valor que uma chave repetida tapa depois; por
    isso a verificação é aqui, e não no dicionário já feito."""
    for chave, valor in pares:
        if _tem_surrogate_sozinho(chave) or _tem_surrogate_sozinho(valor):
            raise ValueError("surrogate sozinho")
    return dict(pares)


async def corpo_json(request: Request) -> dict:
    """O corpo do pedido como dicionário.

    - corpo vazio (ou só espaços) → `{}`, como no CRM autónomo: a validação
      do domínio é que diz o que falta (422 com os campos);
    - tem de ser um OBJETO JSON em UTF-8; uma lista, um texto, `null`, um
      número, JSON partido, bytes que não são UTF-8, um BOM no início, NaN ou
      Infinity, ou um objeto fundo demais → 400 `json_invalido`;
    - um surrogate sozinho em escape (`"\\ud800"`, num valor ou numa chave, a
      qualquer profundidade, também tapado por uma chave repetida) também →
      400, como o `json_decode` do PHP ("Single unpaired UTF-16 surrogate").
      O `json.loads` aceitava-o, e esse texto rebentava depois com
      UnicodeEncodeError no BSON do Mongo e na resposta (um 500).
    """
    bruto = await request.body()
    if not bruto.strip():
        return {}
    try:
        valor = json.loads(bruto.decode("utf-8"), parse_constant=_recusar_constante, object_pairs_hook=_objeto)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # JSONDecodeError é um ValueError. RecursionError: o descodificador do
        # Python desiste a partir de uns milhares de níveis (sem isto, 500).
        raise erro(400, "json_invalido", MENSAGEM_JSON_INVALIDO) from None
    if not isinstance(valor, dict):
        raise erro(400, "json_invalido", MENSAGEM_JSON_INVALIDO)
    return valor
