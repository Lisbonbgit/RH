"""Guarda de regressão: todas as rotas do módulo Faturação exigem autenticação
de gestão (gestor_atual), excepto /api/faturacao/saude — verificado até aqui
só à mão.

NOTA para o Plano 2: as rotas de POS vão usar outro mecanismo de autenticação
(token de dispositivo, não o JWT de gestão via gestor_atual). Quando essas
rotas existirem, este teste tem de ser actualizado EM CONSCIÊNCIA — por
exemplo, alargando ROTAS_PUBLICAS ou trocando a verificação por rota consoante
o grupo de rotas — e nunca simplesmente apagado ou esvaziado para o fazer
passar.
"""
from faturacao import router
from faturacao.auth import gestor_atual

ROTAS_PUBLICAS = {"/api/faturacao/saude"}


def _exige_gestor_atual(route):
    """Procura gestor_atual entre as dependências da rota (recursivamente,
    para apanhar também o caso de uma dependência que por sua vez dependa de
    gestor_atual, não só o caso directo Depends(gestor_atual))."""

    def _procura(dependant):
        for d in dependant.dependencies:
            if d.call is gestor_atual:
                return True
            if _procura(d):
                return True
        return False

    return _procura(route.dependant)


def test_todas_as_rotas_exigem_gestor_atual_excepto_saude():
    sem_protecao = [
        (route.path, sorted(route.methods))
        for route in router.routes
        if route.path not in ROTAS_PUBLICAS and not _exige_gestor_atual(route)
    ]
    assert sem_protecao == []


def test_saude_e_a_unica_rota_publica():
    """O inverso do teste anterior: garante que ROTAS_PUBLICAS não está a
    esconder mais rotas desprotegidas do que as esperadas."""
    rotas_publicas_reais = {
        route.path for route in router.routes if not _exige_gestor_atual(route)
    }
    assert rotas_publicas_reais == ROTAS_PUBLICAS
