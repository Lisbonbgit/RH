"""`/api/crm/rotas` — as rotas de um dia (F3: planear rota, versão simples).

Plano F3 §4; T3.18 (ler). Só o escritório (admin e utilizador do CRM): o
motorista dá 403 `sem_permissao`, quem não é membro 403 `sem_acesso_crm` e,
sem sessão, os 401/403 herdados do portal. Os parâmetros (`data`, `de`,
`ate`) leem-se como texto e validam-se no domínio (`dominio/validador_rota`,
T3.4); a forma das respostas está em `formatar_rota` (T3.16) e as leituras em
`rotas_bd` (T3.17): aqui só se valida, lê e responde.

- `GET /rotas?de=&ate=` → `{hoje, de, ate, rotas: [{id, data, estado,
  estado_efetivo, paragens}]}`, por `data`, com `paragens` a contar só as
  ativas. Sem `de`/`ate`, cada extremo por si é o da omissão (hoje − 14 e
  hoje + 60); os dois dias devolvem-se já resolvidos. A lista lê-se sem o
  `calculo` (a geometria tem dezenas de KB por rota, correção "T3.17 /
  T3.18"). 422 em `de`/`ate` (formato, fim antes do início, mais de 120
  dias), sem tocar na base.
- `GET /rotas/{data}` → a rota completa (`rota_api`), com as lojas das
  paragens ativas juntadas pela `PROJECAO_LOJA_ROTA`, ou a rota **virtual**
  de um dia sem rota (`existe: false`, com as horas e a fábrica das
  definições em vigor). Um dia anterior a hoje lê-se `concluida` e só de
  leitura (`editavel: false`), com ou sem rota (o fecho simples da F3).
  `calculo_disponivel` diz se há `CRM_ORS_CHAVE` (`ors.chave()`; ler nunca
  chama o openrouteservice). 422 em `data` (formato, ou mais de um ano a
  partir de hoje), sem tocar na base.

O "hoje" é o dia em Lisboa do relógio do CRM (`relogio.hoje()`), lido UMA vez
por pedido: a validação e a resposta usam o mesmo dia (à meia-noite não se
valida com um dia e responde com outro).
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio, rotas_bd
from .auth import ESCRITORIO
from .definicoes import em_vigor
from .dominio import validador_rota
from .dominio.datas import texto_data
from .erros import validacao
from .formatar_rota import resumo_rota_api, rota_api
from .servicos import ors

router = APIRouter()


@router.get("/rotas")
async def listar_rotas(
    membro: Dict = Depends(ESCRITORIO),
    de: Optional[str] = None,
    ate: Optional[str] = None,
) -> Dict:
    """As rotas dos dias `de`..`ate` (por omissão hoje − 14 / hoje + 60), por
    `data`, cada uma só com o resumo."""
    hoje = relogio.hoje()
    dias, erros = validador_rota.intervalo(de, ate, hoje)
    if erros:
        raise validacao(erros)
    inicio, fim = dias
    rotas = await rotas_bd.rotas_entre(bd.obter_db(), texto_data(inicio), texto_data(fim))
    return {
        "hoje": texto_data(hoje),
        "de": texto_data(inicio),
        "ate": texto_data(fim),
        "rotas": [resumo_rota_api(rota, hoje) for rota in rotas],
    }


@router.get("/rotas/{data}")
async def ver_rota(data: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """A rota do dia `data`, completa e com as lojas, ou a virtual de um dia
    sem rota."""
    hoje = relogio.hoje()
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    if erros:
        raise validacao(erros)
    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    lojas = await rotas_bd.lojas_da_rota(base, rota)
    definicoes = await em_vigor(base)
    return rota_api(
        rota,
        data=dia,
        hoje=hoje,
        lojas=lojas,
        definicoes=definicoes,
        calculo_disponivel=bool(ors.chave()),
    )
