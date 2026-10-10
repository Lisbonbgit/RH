"""Regras de negócio do CRM, como funções puras.

Portadas de src/Dominio do CRM autónomo (etiqueta `referencia-standalone`),
com os cenários do PHPUnit em pytest (tests/crm/test_dominio_*.py). Aqui não
há FastAPI, base de dados nem relógio: recebem valores e devolvem valores (ou
a mensagem de erro em pt-PT), e as rotas é que leem, gravam e respondem.

Armadilhas da porta (plano §9 e §10; dossiê §2.1): textos com
`texto.aparar` (o str.strip() não tira o U+FEFF), `re.fullmatch` e `[0-9]`
(nunca `\\d` nem `$`), `isinstance(x, str) and x in LISTA` em vez do
`in_array(…, true)`, e `bool` nunca conta como número.
"""
