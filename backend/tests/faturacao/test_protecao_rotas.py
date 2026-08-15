"""Guarda de regressão: todas as rotas do módulo Faturação têm alguma
autenticação — nunca nenhuma.

Duas famílias de rotas, dois mecanismos, nunca misturados:
- Rotas de GESTÃO (backoffice) exigem o JWT via `gestor_atual`.
- Rotas do POS (prefixo `/api/faturacao/pos/`) exigem o mecanismo próprio do
  POS — `dispositivo_atual` ou `operador_atual` (ver faturacao/pos_auth.py)
  — e NUNCA `gestor_atual`: é a guarda central da Task 2 do Plano 2A — um
  administrador com sessão aberta no backoffice não pode vender sem se
  identificar com o PIN, senão a venda entra na caixa sem dono.

Duas excepções, as duas únicas rotas sem qualquer uma das guardas acima:
- `/api/faturacao/saude` — não toca em nada, propositadamente pública.
- `/api/faturacao/pos/emparelhar` — é o próprio bootstrap da cadeia de
  autenticação do POS: o dispositivo ainda não tem nenhum token nesse
  momento, por isso não pode depender de `dispositivo_atual` nem de
  `operador_atual`. A guarda aqui não é uma dependência do FastAPI — é o
  código de emparelhamento em si (de uso único, expira, comparado por
  hash) — coberta por test_pos_auth.py, não por este ficheiro.

Actualizado em consciência (era só `gestor_atual` para tudo excepto saúde,
até a Task 2 introduzir o mecanismo próprio do POS) — nunca simplesmente
apagado ou esvaziado para passar. Se o Plano 2A acrescentar mais rotas do
POS (abrir caixa, vender, ...), este ficheiro continua a bater certo sem
precisar de crescer a lista de excepções.
"""
from faturacao import router
from faturacao.auth import gestor_atual
from faturacao.pos_auth import dispositivo_atual, operador_atual

ROTAS_PUBLICAS = {"/api/faturacao/saude"}
ROTAS_BOOTSTRAP_POS = {"/api/faturacao/pos/emparelhar"}
PREFIXO_POS = "/api/faturacao/pos/"

_MECANISMOS_POS = (dispositivo_atual, operador_atual)


def _dependencias(route):
    """Todos os `call` das dependências da rota, recursivamente (para apanhar
    também o caso de uma dependência que por sua vez dependa de outra, não só
    o caso directo Depends(mecanismo))."""
    encontrados = set()

    def _procura(dependant):
        for d in dependant.dependencies:
            encontrados.add(d.call)
            _procura(d)

    _procura(route.dependant)
    return encontrados


def _exige(route, mecanismo) -> bool:
    return mecanismo in _dependencias(route)


def test_rotas_de_gestao_exigem_gestor_atual():
    """Toda a rota que não seja pública nem do POS continua a exigir
    gestor_atual — o mesmo comportamento de sempre, agora restrito às rotas
    de gestão (lojas, utilizadores, tipos de pagamento, motivos, catálogo,
    importação, dashboard, e a geração do código de emparelhamento)."""
    sem_protecao = [
        (route.path, sorted(route.methods))
        for route in router.routes
        if route.path not in ROTAS_PUBLICAS
        and not route.path.startswith(PREFIXO_POS)
        and not _exige(route, gestor_atual)
    ]
    assert sem_protecao == []


def test_rotas_do_pos_exigem_o_mecanismo_do_pos_e_nunca_gestor_atual():
    rotas_pos = [
        route for route in router.routes
        if route.path.startswith(PREFIXO_POS) and route.path not in ROTAS_BOOTSTRAP_POS
    ]
    assert rotas_pos, "esperava pelo menos uma rota do POS (além do bootstrap) para testar"

    sem_protecao = [
        (route.path, sorted(route.methods))
        for route in rotas_pos
        if not any(_exige(route, mecanismo) for mecanismo in _MECANISMOS_POS)
    ]
    assert sem_protecao == []

    com_jwt_de_gestao = [
        (route.path, sorted(route.methods))
        for route in rotas_pos
        if _exige(route, gestor_atual)
    ]
    assert com_jwt_de_gestao == []


def test_saude_e_o_bootstrap_do_pos_sao_as_unicas_rotas_sem_guarda():
    """O inverso dos dois testes acima: garante que ROTAS_PUBLICAS e
    ROTAS_BOOTSTRAP_POS não escondem mais rotas desprotegidas do que as
    esperadas — nenhuma rota fica de fora das três categorias acima."""
    sem_nenhuma_guarda = {
        route.path
        for route in router.routes
        if not _exige(route, gestor_atual)
        and not any(_exige(route, mecanismo) for mecanismo in _MECANISMOS_POS)
    }
    assert sem_nenhuma_guarda == ROTAS_PUBLICAS | ROTAS_BOOTSTRAP_POS
