"""As sugestões de lojas para aproveitar a viagem: perto das paragens (5 km) e
no caminho (3 km), F3.

Plano F3 §1 ("Sugestões") e desenho original §7. Calculam-se no servidor
(`GET /rotas/{data}/sugestoes`, T3.23), a partir das lojas que a API já leu,
em dois grupos pela ordem em que se mostram: **contactada** e depois
**potencial** (`FASES_SUGERIDAS`).

- Entra uma loja a ≤ 5 km em linha reta (`geo.distancia_metros`) de qualquer
  paragem ativa com loja e coordenadas (`lojas_das_paragens`).
- Com a linha da rota (`linha`: a polyline de `calculo.geometria` descodificada
  por `polilinha.descodificar`, que quem chama só passa com `calculo.atual`),
  entra também uma loja a ≤ 3 km dela: o **corredor**. Essa vem com
  `no_caminho: True` e a distância à linha. Uma loja perto pelos dois lados
  fica com a menor das duas distâncias e `no_caminho: False`; perto de uma
  paragem mas longe da linha, com a distância à paragem.
- Ficam de fora a perdida, a amostra e o cliente (qualquer fase que não seja
  uma das duas), as lojas fechadas nesse dia da semana
  (`rotas.fechada_neste_dia`), as que já estão na rota (`ids_na_rota`: quem
  chama diz quais, também as das paragens sem loja) e as sem coordenadas.
- Cada grupo vem pelos metros mostrados, depois pelo nome sem acentos nem
  maiúsculas (`texto.chave_comparacao`) e depois pelo `id`; mostra no máximo
  30 (`LIMITE_POR_GRUPO`), com `mais = N − 30`. Os dois grupos vêm sempre,
  mesmo vazios; sem nenhuma paragem com coordenadas, a resposta é só
  `{"sem_paragens": True, "no_caminho": False, "grupos": []}`.

Os metros mostrados (`distancia_m`: inteiros, meio-para-longe-do-zero como as
outras distâncias do CRM, `numeros.arredondar`) é que decidem o raio e o
corredor: "5000 m" entra, "5001 m" não — 5000,4 m entra, 5000,5 m não.

`distancia_a_linha` mede do ponto ao troço mais perto numa projeção
equirretangular local (os metros de um grau de latitude, `geo.METROS_POR_GRAU`,
vezes o cosseno da latitude do ponto na longitude): ±1 % contra a haversine
até 5 km, e muito mais barato. A **rejeição por caixa**: um troço a mais de
`limite` metros do ponto num dos eixos nem se mede. A caixa usa a mesma
métrica, por isso nunca deixa de fora um ponto a menos de `limite` do troço; o
resultado é exato até `limite` e, acima, só diz que passa do limite. É
O(lojas × troços), com os troços preparados uma vez por chamada (`_trocos`).

A data vem de fora (`date`, nunca texto nem `datetime`, como no `rotas`) e
nada sai deste módulo para a rede.
"""
import math
from datetime import date

from .geo import METROS_POR_GRAU, distancia_metros
from .numeros import arredondar, e_numero_json
from .rotas import fechada_neste_dia
from .texto import chave_comparacao

# Igual a RAIO_SUGESTOES_M e CORREDOR_M no planeador (plano §1): constantes do código na F3.
RAIO_SUGESTOES_M = 5000
CORREDOR_M = 3000
LIMITE_POR_GRUPO = 30

# Os grupos, pela ordem em que se mostram: só estas fases entram.
FASES_SUGERIDAS = ("contactada", "potencial")

# A caixa do corredor leva a folga do arredondamento: 3000,4 m mostra-se "3000 m"
# e entra, por isso não pode ser rejeitada antes de se medir.
_LIMITE_DA_CAIXA_DO_CORREDOR = CORREDOR_M + 0.5

LATITUDE_MAXIMA = 90
LONGITUDE_MAXIMA = 180


def sugerir(lojas, lojas_das_paragens, ids_na_rota, data, linha=None) -> dict:
    """As sugestões para a rota do dia `data` (`date`).

    `lojas` e `lojas_das_paragens` são listas (ou tuplos) de documentos com
    `id`, `nome`, `fase`, `lat`, `lng` e `dias_fechada` (as segundas só
    precisam das coordenadas); `ids_na_rota` os ids das lojas das paragens
    ativas (qualquer coleção, nunca um texto); `linha` a polyline descodificada
    (`[(lat, lng), …]`) ou `None` sem `calculo.atual`. Devolve
    `{"sem_paragens", "no_caminho", "grupos": [{"fase", "lojas": [{id, nome,
    fase, lat, lng, distancia_m, no_caminho}], "mais"}]}`, estruturas novas,
    sem mudar o que recebe. O que não é uma lista, um dicionário ou um `date`
    é `TypeError`; um ponto da linha estragado é `ValueError`.
    """
    _exigir_lista_de_dicionarios(lojas, "lojas")
    _exigir_lista_de_dicionarios(lojas_das_paragens, "lojas das paragens")
    if isinstance(ids_na_rota, str) or not hasattr(ids_na_rota, "__iter__"):
        raise TypeError("ids_na_rota é uma coleção de ids.")
    if type(data) is not date:
        raise TypeError("Os dias das rotas são datetime.date.")
    trocos = None if linha is None else _trocos(_pontos(linha))

    excluidas = set(ids_na_rota)
    pontos = [(loja["lat"], loja["lng"]) for loja in lojas_das_paragens if _tem_coordenadas(loja)]
    if not pontos:
        return {"sem_paragens": True, "no_caminho": False, "grupos": []}

    candidatas = {fase: [] for fase in FASES_SUGERIDAS}
    for loja in lojas:
        fase = loja.get("fase")
        if (
            not isinstance(fase, str)
            or fase not in candidatas
            or loja["id"] in excluidas
            or not _tem_coordenadas(loja)
            or fechada_neste_dia(loja, data)
        ):
            continue
        lat, lng = loja["lat"], loja["lng"]
        as_paragens = _metros(min(distancia_metros(lat, lng, p_lat, p_lng) for p_lat, p_lng in pontos))
        distancias = [as_paragens] if as_paragens <= RAIO_SUGESTOES_M else []
        if trocos:
            a_linha = _distancia_aos_trocos(lat, lng, trocos, _LIMITE_DA_CAIXA_DO_CORREDOR)
            if a_linha != math.inf and _metros(a_linha) <= CORREDOR_M:
                distancias.append(_metros(a_linha))
        if not distancias:
            continue
        sugestao = {
            "id": loja["id"],
            "nome": loja["nome"],
            "fase": fase,
            "lat": lat,
            "lng": lng,
            "distancia_m": min(distancias),
            "no_caminho": as_paragens > RAIO_SUGESTOES_M,
        }
        candidatas[fase].append((sugestao["distancia_m"], chave_comparacao(loja["nome"]), loja["id"], sugestao))

    grupos = []
    for fase in FASES_SUGERIDAS:
        encontradas = sorted(candidatas[fase], key=lambda candidata: candidata[:3])
        grupos.append(
            {
                "fase": fase,
                "lojas": [candidata[3] for candidata in encontradas[:LIMITE_POR_GRUPO]],
                "mais": max(0, len(encontradas) - LIMITE_POR_GRUPO),
            }
        )
    return {"sem_paragens": False, "no_caminho": bool(trocos), "grupos": grupos}


def distancia_a_linha(lat, lng, linha, limite=math.inf) -> float:
    """Os metros do ponto ao troço mais perto de `linha` (`[(lat, lng), …]`;
    um só ponto é um troço degenerado; sem pontos, `inf`).

    Só se medem os troços cuja caixa, alargada `limite` metros, contém o
    ponto: até `limite` o resultado é exato; acima, só diz que passa do
    limite (é a distância ao troço medido mais perto, que pode não ser o mais
    perto de todos, ou `inf` quando nenhum se mediu). `limite` é um número
    ≥ 0 (`inf` mede tudo). Um ponto estragado ou um
    limite inválido é `ValueError`; uma linha que não é lista é `TypeError`.
    """
    _exigir_ponto(lat, lng)
    if isinstance(limite, bool) or not isinstance(limite, (int, float)) or math.isnan(limite) or limite < 0:
        raise ValueError("O limite da distância à linha é um número de metros ≥ 0.")
    return _distancia_aos_trocos(lat, lng, _trocos(_pontos(linha)), limite)


def _distancia_aos_trocos(lat, lng, trocos, limite) -> float:
    """A conta de `distancia_a_linha` sobre os troços já preparados (`_trocos`)."""
    escala_lng = METROS_POR_GRAU * math.cos(math.radians(lat))
    folga_lat = limite / METROS_POR_GRAU
    folga_lng = limite / escala_lng if escala_lng > 0 else math.inf
    lat_de, lat_ate = lat - folga_lat, lat + folga_lat
    lng_de, lng_ate = lng - folga_lng, lng + folga_lng

    melhor = math.inf
    for lat_min, lat_max, lng_min, lng_max, lat_a, lng_a, lat_b, lng_b in trocos:
        if lat_max < lat_de or lat_min > lat_ate or lng_max < lng_de or lng_min > lng_ate:
            continue
        # O ponto fica na origem; o troço vai de (ax, ay) a (bx, by), em metros.
        ax = (lng_a - lng) * escala_lng
        ay = (lat_a - lat) * METROS_POR_GRAU
        bx = (lng_b - lng) * escala_lng
        by = (lat_b - lat) * METROS_POR_GRAU
        dx, dy = bx - ax, by - ay
        comprimento2 = dx * dx + dy * dy
        if comprimento2 > 0:
            # A projeção da origem sobre a reta do troço, presa às pontas.
            t = -(ax * dx + ay * dy) / comprimento2
            if t <= 0:
                px, py = ax, ay
            elif t >= 1:
                px, py = bx, by
            else:
                px, py = ax + t * dx, ay + t * dy
        else:
            px, py = ax, ay
        metros = math.hypot(px, py)
        if metros < melhor:
            melhor = metros
    return melhor


def _trocos(pontos) -> list:
    """Os troços de uma linha já validada, com a caixa de cada um:
    `(lat_min, lat_max, lng_min, lng_max, lat_a, lng_a, lat_b, lng_b)`."""
    if len(pontos) == 1:
        pontos = [pontos[0], pontos[0]]
    trocos = []
    for (lat_a, lng_a), (lat_b, lng_b) in zip(pontos, pontos[1:]):
        caixa = (min(lat_a, lat_b), max(lat_a, lat_b), min(lng_a, lng_b), max(lng_a, lng_b))
        trocos.append((*caixa, lat_a, lng_a, lat_b, lng_b))
    return trocos


def _pontos(linha) -> list:
    """A linha validada, como uma lista nova de pares `(lat, lng)`."""
    if not isinstance(linha, (list, tuple)):
        raise TypeError("A linha é uma lista de pares (lat, lng).")
    pontos = []
    for par in linha:
        if not isinstance(par, (list, tuple)) or len(par) != 2:
            raise ValueError("Um ponto da linha é um par (lat, lng).")
        lat, lng = par
        _exigir_ponto(lat, lng)
        pontos.append((lat, lng))
    return pontos


def _exigir_ponto(lat, lng):
    if not e_numero_json(lat) or not e_numero_json(lng):
        raise ValueError("A latitude e a longitude têm de ser números.")
    if not -LATITUDE_MAXIMA <= lat <= LATITUDE_MAXIMA or not -LONGITUDE_MAXIMA <= lng <= LONGITUDE_MAXIMA:
        raise ValueError("O ponto fica fora do mundo.")


def _exigir_lista_de_dicionarios(valor, nome):
    if not isinstance(valor, (list, tuple)):
        raise TypeError(f"As {nome} vêm numa lista de documentos.")
    if not all(isinstance(elemento, dict) for elemento in valor):
        raise TypeError(f"Cada uma das {nome} é um dicionário.")


def _tem_coordenadas(loja) -> bool:
    return e_numero_json(loja.get("lat")) and e_numero_json(loja.get("lng"))


def _metros(valor) -> int:
    """Os metros mostrados: ao metro, meio-para-longe-do-zero."""
    return int(arredondar(valor))
