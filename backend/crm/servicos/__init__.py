"""Serviços externos do CRM, chamados só pelo servidor.

Porta de src/Servicos do CRM autónomo (dossiê §8 e §11). A Geoapify desde a
F2 (`geoapify.py`: pedidos e respostas da pesquisa de morada e da morada
sugerida, mais o cliente HTTP cujo `ler_json` e `silenciar_registos` o outro
reutiliza) e o openrouteservice desde a F3 (`ors.py`: a otimização VROOM e o
Directions, só com coordenadas e números). As chaves vêm do ambiente e nunca
vão para o browser nem para os registos: a do openrouteservice vai só no
cabeçalho `Authorization`.
"""
