# Faturação L'Açaí — Plano 1: Fundação, Configuração e Catálogo

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: usar
> `superpowers:subagent-driven-development` (recomendado) ou
> `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam
> caixas (`- [ ]`) para acompanhamento.

**Spec:** `docs/superpowers/specs/2026-08-13-faturacao-lacai-design.md`

**Goal:** Criar o esqueleto do módulo Faturação dentro do Gestão Lisbonb e ter, no fim, um
backoffice onde se configuram lojas, caixas, utilizadores, tipos de pagamento e motivos de nota de
crédito, e onde o catálogo do Vendus (produtos, categorias, personalizações, preços, IVA) está
importado e editável — com IVA obrigatório por artigo.

**Architecture:** Pacote Python novo `backend/faturacao/`, com o seu próprio cliente Motor e a sua
própria descodificação de JWT, montado no `server.py` com duas linhas. Toda a lógica de negócio
(preços, IVA, PIN, importação) vive em módulos **puros, sem I/O**, testados sem base de dados —
o padrão que já funciona em `~/dev/pizzaria/backend/pos/`. No frontend, uma quarta secção no
`AdminLayout`, com as páginas em `pages/admin/faturacao/`.

**Tech Stack:** FastAPI 0.110 · Motor 3.3 / MongoDB Atlas · Pydantic 2.12 · PyJWT · bcrypt ·
httpx · React 19 / CRACO / Tailwind / shadcn · pytest 8

---

## Global Constraints

- **Python 3.9.6** (o único disponível na máquina). **Sem** `X | Y` em anotações de tipo, **sem**
  `match`, **sem** `list[str]` — usar `Optional[X]`, `Union[X, Y]`, `List[str]` de `typing`.
- **Nada é acrescentado ao `backend/server.py`** além de duas linhas (import + `include_router`).
- **Prefixo `fat_`** em todas as colecções novas. **Prefixo `/api/faturacao/`** em todas as rotas.
- **Não existe MongoDB local nem Docker.** Todos os testes deste plano são de lógica pura ou usam
  duplos de teste. Nenhum teste liga a uma base de dados.
- **O `.venv` local já existe** em `backend/.venv` (Python 3.9), criado na Task 1. Correr sempre
  `backend/.venv/bin/pytest`. **Não voltar a correr `pip install -r requirements.txt`** e **não
  alterar os pins do repositório**: `python-multipart==0.0.21` e `dnspython==2.8.0` exigem Python
  ≥3.10 e não instalam nesta máquina, mas a produção corre Python 3.11 no Docker e está correcta.
  O `.venv` foi montado com esses dois pins rebaixados apenas localmente.
- **O módulo nunca escreve no Vendus neste plano.** Só lê (importação do catálogo).
- **PT-PT** em todo o texto visível e nos comentários.
- Identidade visual existente: tokens em `frontend/src/index.css`, componentes shadcn em
  `frontend/src/components/ui/`, notificações com `sonner`.
- Cada tarefa termina com um commit no ramo `matheus-faturacao-lacai`.

---

## Decisão tomada (2026-08-13)

O dono escolheu que **categoria = Venda ao Público / Vendas Aplicações**, como no Vendus. Cada
produto pertence a **uma** categoria e tem **um** preço e **um** IVA. Os separadores do POS são as
categorias, tal como hoje.

Foi-lhe apresentada a alternativa (um produto com dois preços e categorias por família, que
acabava com os artigos duplicados) e ele preferiu manter a gestão igual à que já conhece.
Consequência aceite e registada na spec §9.1: "Açaí Regular" e "Açaí Regular App" continuam a ser
dois produtos, e os toppings continuam duplicados entre personalização e produto "Extra ...".

## Estrutura de ficheiros

**Backend — criar:**

| Ficheiro | Responsabilidade |
|---|---|
| `backend/pytest.ini` | Configuração do pytest (`pythonpath = .`) |
| `backend/faturacao/__init__.py` | Router raiz `/api/faturacao` + inclusão dos sub-routers |
| `backend/faturacao/db.py` | Cliente Motor próprio (preguiçoso) + criação de índices |
| `backend/faturacao/auth.py` | Descodificação do JWT do backoffice + dependências de perfil |
| `backend/faturacao/precos.py` | **Puro:** IVA, validação de produto, linha de venda |
| `backend/faturacao/pins.py` | **Puro:** normalização e verificação de PIN |
| `backend/faturacao/lojas.py` | Endpoints de Lojas e Caixas |
| `backend/faturacao/pagamentos.py` | Endpoints de Tipos de Pagamento |
| `backend/faturacao/utilizadores.py` | Endpoints de Utilizadores |
| `backend/faturacao/motivos.py` | Endpoints de Motivos de Nota de Crédito |
| `backend/faturacao/catalogo.py` | Endpoints de Categorias, Personalizações e Produtos |
| `backend/faturacao/importacao.py` | **Puro (transformação) + endpoint:** importar do Vendus |
| `backend/faturacao/vendus/__init__.py` | — |
| `backend/faturacao/vendus/cliente.py` | Cliente HTTP do Vendus (só leitura nesta fase) |
| `backend/tests/faturacao/*` | Testes |

**Backend — modificar:**

| Ficheiro | Alteração |
|---|---|
| `backend/server.py` | 2 linhas: import + `include_router` |
| `backend/requirements.txt` | `+ pytest>=8.0,<9` |

**Frontend — criar:** `src/lib/faturacao.js` e `src/pages/admin/faturacao/` (10 páginas).
**Frontend — modificar:** `src/components/layouts/AdminLayout.js`, `src/App.js`.

---

## Task 1: Infraestrutura de testes e esqueleto do pacote

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/faturacao/__init__.py`
- Create: `backend/faturacao/db.py`
- Create: `backend/tests/faturacao/__init__.py`
- Create: `backend/tests/faturacao/test_saude.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/server.py`

**Interfaces:**
- Produces: `faturacao.router` (`APIRouter` com prefixo `/api/faturacao`);
  `faturacao.db.obter_db()` → base de dados Motor (preguiçosa);
  `faturacao.db.COLECOES` (dict com os nomes das colecções).

- [ ] **Step 1: Criar o ambiente virtual e instalar as dependências**

O repositório não tem `.venv`. Criar um, com o Python 3.9 do sistema:

```bash
cd ~/Developer/RH/backend
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pip install -q "pytest>=8.0,<9"
```

Acrescentar ao fim de `backend/requirements.txt`:

```
# --- Testes ---
pytest>=8.0,<9
```

Acrescentar `backend/.venv/` ao `.gitignore` se ainda não estiver lá.

- [ ] **Step 2: Escrever o teste que falha**

Criar `backend/pytest.ini`:

```ini
[pytest]
# backend/ no sys.path -> permite "import faturacao..." nos testes
pythonpath = .
testpaths = tests
python_files = test_*.py
```

Criar `backend/tests/faturacao/__init__.py` (vazio).

Criar `backend/tests/faturacao/test_saude.py`:

```python
"""O router do módulo existe, monta em /api/faturacao e responde sem base de dados.

Este teste NÃO importa o server.py de propósito: o server.py lê os.environ["DB_NAME"]
ao ser importado e rebentaria fora do servidor. O pacote faturacao tem de conseguir
ser importado e testado sozinho.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from faturacao import router


def _cliente():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_saude_responde_ok():
    r = _cliente().get("/api/faturacao/saude")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "modulo": "faturacao"}


def test_prefixo_do_router():
    assert router.prefix == "/api/faturacao"
```

- [ ] **Step 3: Correr o teste para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_saude.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao'`.

- [ ] **Step 4: Escrever a implementação mínima**

Criar `backend/faturacao/db.py`:

```python
"""Acesso à base de dados do módulo Faturação.

O cliente é criado à PRIMEIRA UTILIZAÇÃO (e não ao importar o módulo) para que o
pacote possa ser importado em testes sem MONGO_URL/DB_NAME definidos.
"""
import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# Nomes das colecções, todos com prefixo fat_ (convenção do repositório: fin_, mkt_).
COLECOES = {
    "lojas": "fat_lojas",
    "caixas": "fat_caixas",
    "utilizadores": "fat_utilizadores",
    "tipos_pagamento": "fat_tipos_pagamento",
    "motivos_nc": "fat_motivos_nc",
    "categorias": "fat_categorias",
    "grupos_personalizacao": "fat_grupos_personalizacao",
    "produtos": "fat_produtos",
}

_cliente = None  # type: Optional[AsyncIOMotorClient]


def obter_db():
    """Devolve a base de dados, criando o cliente na primeira chamada."""
    global _cliente
    if _cliente is None:
        _cliente = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _cliente[os.environ["DB_NAME"]]
```

Criar `backend/faturacao/__init__.py`:

```python
"""Módulo Faturação L'Açaí — POS e backoffice das lojas.

Vive como pacote próprio (e não dentro do server.py) por duas razões: o server.py
já tem 8150 linhas, e um pacote isolado significa que uma avaria aqui não derruba
o RH, o Financeiro nem o Marketing.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/faturacao", tags=["faturacao"])


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Não toca na base de dados de propósito."""
    return {"estado": "ok", "modulo": "faturacao"}
```

- [ ] **Step 5: Correr o teste para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 2 passed.

- [ ] **Step 6: Montar o router no server.py**

Em `backend/server.py`, imediatamente **antes** da linha `app.include_router(api_router)`
(perto da linha 8112), acrescentar:

```python
from faturacao import router as faturacao_router
app.include_router(faturacao_router)
```

- [ ] **Step 7: Confirmar que o server.py continua a importar**

```bash
cd ~/Developer/RH/backend && MONGO_URL=mongodb://localhost:27017 DB_NAME=teste JWT_SECRET=x \
  .venv/bin/python -c "import server; print('import ok')"
```

Esperado: `import ok`. (Não liga a nada — o Motor só liga na primeira operação.)

- [ ] **Step 8: Commit**

```bash
cd ~/Developer/RH
git add backend/pytest.ini backend/faturacao/ backend/tests/faturacao/ \
        backend/requirements.txt backend/server.py .gitignore
git commit -m "Faturação: esqueleto do pacote, router montado e infraestrutura de testes"
```

---

## Task 2: Índices do módulo

Os índices únicos deste módulo não são optimização — são a garantia de que não há duas sessões de
caixa abertas na mesma caixa e, mais tarde, de que não sai uma segunda fatura da mesma venda. O
repositório **não cria um único índice** hoje; este módulo passa a criar os seus no arranque.

**Files:**
- Modify: `backend/faturacao/db.py`
- Create: `backend/tests/faturacao/test_indices.py`

**Interfaces:**
- Consumes: `COLECOES` (Task 1)
- Produces: `faturacao.db.INDICES` (lista de `(coleccao, chaves, opcoes)`);
  `async faturacao.db.criar_indices(db)`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_indices.py`:

```python
"""Os índices são declarados como dados e aplicados por criar_indices.

Testa-se com um duplo que regista as chamadas, para não ser preciso um Mongo.
"""
import asyncio

from faturacao.db import INDICES, criar_indices


class ColeccaoFalsa:
    def __init__(self, nome, registo):
        self.nome = nome
        self.registo = registo

    async def create_index(self, chaves, **opcoes):
        self.registo.append((self.nome, chaves, opcoes))
        return "ok"


class DbFalsa:
    def __init__(self):
        self.registo = []

    def __getitem__(self, nome):
        return ColeccaoFalsa(nome, self.registo)


def test_declara_indice_unico_de_pin_por_loja():
    chaves = [(c, k) for (c, k, o) in INDICES if c == "fat_utilizadores" and o.get("unique")]
    assert ("fat_utilizadores", [("loja_id", 1), ("pin_hash", 1)]) in chaves


def test_criar_indices_aplica_todos():
    db = DbFalsa()
    asyncio.get_event_loop().run_until_complete(criar_indices(db))
    assert len(db.registo) == len(INDICES)


def test_criar_indices_nao_rebenta_se_um_falhar():
    """Um índice que falhe (ex.: dados antigos duplicados) não pode impedir o arranque."""

    class ColeccaoRebentada(ColeccaoFalsa):
        async def create_index(self, chaves, **opcoes):
            raise RuntimeError("índice duplicado")

    class DbRebentada(DbFalsa):
        def __getitem__(self, nome):
            return ColeccaoRebentada(nome, self.registo)

    asyncio.get_event_loop().run_until_complete(criar_indices(DbRebentada()))
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_indices.py -v
```

Esperado: FALHA com `ImportError: cannot import name 'INDICES'`.

- [ ] **Step 3: Implementar**

Acrescentar a `backend/faturacao/db.py`:

```python
import logging

logger = logging.getLogger(__name__)

# (coleccao, chaves, opcoes). Declarados como dados para serem testáveis sem Mongo.
INDICES = [
    ("fat_lojas", [("empresa_id", 1)], {}),
    ("fat_caixas", [("loja_id", 1)], {}),
    ("fat_utilizadores", [("loja_id", 1), ("pin_hash", 1)], {"unique": True}),
    ("fat_utilizadores", [("ativo", 1)], {}),
    ("fat_tipos_pagamento", [("ordem", 1)], {}),
    ("fat_categorias", [("ordem", 1)], {}),
    ("fat_produtos", [("categoria_id", 1)], {}),
    ("fat_produtos", [("ativo", 1)], {}),
    ("fat_produtos", [("vendus_ref", 1)], {"sparse": True}),
    ("fat_grupos_personalizacao", [("nome", 1)], {}),
]


async def criar_indices(db):
    """Aplica os índices. Uma falha é registada mas NÃO impede o arranque —
    o módulo tem de subir mesmo que um índice não possa ser criado."""
    for coleccao, chaves, opcoes in INDICES:
        try:
            await db[coleccao].create_index(chaves, **opcoes)
        except Exception as e:  # noqa: BLE001 — arrancar é mais importante
            logger.error("[faturacao] índice %s %s falhou: %s", coleccao, chaves, e)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 5 passed.

- [ ] **Step 5: Ligar ao arranque da aplicação**

Em `backend/faturacao/__init__.py`, acrescentar:

```python
from .db import COLECOES, criar_indices, obter_db  # noqa: F401


async def arrancar():
    """Chamado pelo server.py no arranque."""
    await criar_indices(obter_db())
```

Em `backend/server.py`, dentro da função de `startup` existente (a que chama
`ensure_master_admin_exists`, perto da linha 8134), acrescentar como **última** linha do corpo:

```python
    from faturacao import arrancar as faturacao_arrancar
    await faturacao_arrancar()
```

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/ backend/tests/faturacao/ backend/server.py
git commit -m "Faturação: índices do módulo criados no arranque"
```

---

## Task 3: Autenticação do backoffice

**Files:**
- Create: `backend/faturacao/auth.py`
- Create: `backend/tests/faturacao/test_auth.py`

**Interfaces:**
- Produces: `faturacao.auth.descodificar_token(token)` → `dict`;
  `faturacao.auth.utilizador_atual` (dependência FastAPI);
  `faturacao.auth.gestor_atual` (dependência que exige perfil de gestão);
  `faturacao.auth.PERFIS_GESTAO = ["admin", "gerente", "contabilista"]`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_auth.py`:

```python
"""Descodificação do JWT do backoffice. Mesmo segredo e mesmo formato do server.py,
mas implementado aqui para o pacote não depender do server.py (import circular).
"""
import os

import jwt
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "segredo-de-teste")

from faturacao.auth import PERFIS_GESTAO, descodificar_token, exigir_gestao


def _token(**extra):
    dados = {"user_id": "u1", "email": "a@b.pt", "role": "admin"}
    dados.update(extra)
    return jwt.encode(dados, os.environ["JWT_SECRET"], algorithm="HS256")


def test_descodifica_token_valido():
    assert descodificar_token(_token())["email"] == "a@b.pt"


def test_token_com_segredo_errado_e_recusado():
    mau = jwt.encode({"user_id": "u1"}, "outro-segredo", algorithm="HS256")
    with pytest.raises(HTTPException) as e:
        descodificar_token(mau)
    assert e.value.status_code == 401


def test_token_lixo_e_recusado():
    with pytest.raises(HTTPException) as e:
        descodificar_token("isto-nao-e-um-token")
    assert e.value.status_code == 401


def test_perfis_de_gestao_sao_os_do_repositorio():
    assert PERFIS_GESTAO == ["admin", "gerente", "contabilista"]


def test_colaborador_nao_passa_na_gestao():
    with pytest.raises(HTTPException) as e:
        exigir_gestao({"role": "colaborador"})
    assert e.value.status_code == 403


def test_admin_passa_na_gestao():
    assert exigir_gestao({"role": "admin"})["role"] == "admin"
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_auth.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.auth'`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/auth.py`:

```python
"""Autenticação do backoffice do módulo Faturação.

Repete ~15 linhas do server.py de propósito: se importasse o server.py, e o
server.py importa este pacote para o montar, tínhamos um import circular.
Mesmo JWT_SECRET, mesmo algoritmo, mesmo formato de payload.
"""
import os
from typing import Dict

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Os mesmos papéis do server.py (MANAGER_ROLES). Ver server.py:62.
PERFIS_GESTAO = ["admin", "gerente", "contabilista"]

# Valor por omissão copiado de server.py:52. A paridade é deliberada: se os dois
# divergirem, o portal emite tokens que este módulo recusa.
JWT_SECRET_POR_OMISSAO = "hr-system-secret-key-2024"

_seguranca = HTTPBearer(auto_error=True)


def descodificar_token(token: str) -> Dict:
    try:
        segredo = os.environ.get("JWT_SECRET", JWT_SECRET_POR_OMISSAO)
        return jwt.decode(token, segredo, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")


def exigir_gestao(utilizador: Dict) -> Dict:
    if utilizador.get("role") not in PERFIS_GESTAO:
        raise HTTPException(status_code=403, detail="Sem permissão para esta área")
    return utilizador


async def utilizador_atual(
    credenciais: HTTPAuthorizationCredentials = Depends(_seguranca),
) -> Dict:
    return descodificar_token(credenciais.credentials)


async def gestor_atual(utilizador: Dict = Depends(utilizador_atual)) -> Dict:
    return exigir_gestao(utilizador)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 11 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/auth.py backend/tests/faturacao/test_auth.py
git commit -m "Faturação: autenticação do backoffice (JWT próprio, sem import circular)"
```

---

## Task 4: Lógica pura de preços e IVA

O ponto mais importante deste plano. A app de hoje resolve o IVA com
`prod.get('vat_rate', 13)` — um produto sem IVA sai a 13% sem erro nenhum. Bastaria criar
"Coca-Cola 33cl" sem preencher o IVA para faturar refrigerantes a 13% em vez de 23% durante meses.
Aqui, **um produto sem IVA definido não pode ser vendido**.

**Files:**
- Create: `backend/faturacao/precos.py`
- Create: `backend/tests/faturacao/test_precos.py`

**Interfaces:**
- Produces:
  `tax_id_de_taxa(taxa) -> Optional[str]`;
  `erros_do_produto(produto) -> List[str]`;
  `linha_de_venda(produto, quantidade, opcoes, preco_override, tax_override, desconto_pct, desconto_eur) -> dict`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_precos.py`:

```python
"""Preços, IVA e linhas de venda — lógica pura, sem I/O.

Modelo: um produto pertence a uma categoria (Venda ao Público ou Vendas Aplicações)
e tem UM preço e UM IVA — como no Vendus (spec D7).
"""
import pytest

from faturacao.precos import erros_do_produto, linha_de_venda, tax_id_de_taxa


def _produto(**over):
    p = {"id": "p1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}
    p.update(over)
    return p


# --- IVA -------------------------------------------------------------------

def test_taxas_conhecidas():
    assert tax_id_de_taxa(23) == "NOR"
    assert tax_id_de_taxa(13) == "INT"
    assert tax_id_de_taxa(6) == "RED"
    assert tax_id_de_taxa(0) == "ISE"


def test_taxa_desconhecida_nao_inventa_nada():
    """A app antiga devolvia INT por omissão. Aqui devolve None: quem chama decide,
    e o produto fica marcado como incompleto em vez de sair a 13% em silêncio."""
    assert tax_id_de_taxa(17) is None
    assert tax_id_de_taxa(None) is None
    assert tax_id_de_taxa("treze") is None


# --- Validação -------------------------------------------------------------

def test_produto_completo_nao_tem_erros():
    assert erros_do_produto(_produto()) == []


def test_produto_sem_iva_tem_erro():
    p = _produto()
    del p["tax_id"]
    assert erros_do_produto(p) == ["Sem IVA definido"]


def test_produto_sem_preco_tem_erro():
    p = _produto()
    del p["preco"]
    assert erros_do_produto(p) == ["Sem preço definido"]


def test_produto_sem_preco_nem_iva():
    assert erros_do_produto({"nome": "X"}) == ["Sem preço definido", "Sem IVA definido"]


def test_preco_zero_e_valido():
    """Um artigo a 0,00€ (ex.: 'Incluído') é legítimo — o que não pode é faltar o campo."""
    assert erros_do_produto(_produto(preco=0)) == []


# --- Linha de venda --------------------------------------------------------

def test_linha_simples():
    li = linha_de_venda(_produto(), 2)
    assert li == {"title": "Açaí Regular", "qty": 2, "gross_price": 8.99, "tax_id": "INT"}


def test_linha_com_opcoes_soma_ao_preco_unitario():
    """As personalizações entram no preço unitário da linha, como a app já faz em
    produção — e não como linhas separadas na fatura."""
    opcoes = [{"nome": "Nutella", "preco": 0.95}, {"nome": "Banana", "preco": 0.0}]
    li = linha_de_venda(_produto(), 1, opcoes=opcoes)
    assert li["gross_price"] == 9.94
    assert li["title"] == "Açaí Regular (Nutella, Banana)"


def test_linha_recusa_produto_sem_iva():
    p = _produto()
    del p["tax_id"]
    with pytest.raises(ValueError) as e:
        linha_de_venda(p, 1)
    assert "IVA" in str(e.value)


def test_linha_recusa_produto_sem_preco():
    p = _produto()
    del p["preco"]
    with pytest.raises(ValueError) as e:
        linha_de_venda(p, 1)
    assert "preço" in str(e.value)


def test_override_de_preco_e_de_iva():
    li = linha_de_venda(_produto(), 1, preco_override=7.5, tax_override="NOR")
    assert li["gross_price"] == 7.5
    assert li["tax_id"] == "NOR"


def test_override_de_preco_zero_e_respeitado():
    """0 é um preço, não é 'vazio'. Um `if preco_override:` daria 8,99 aqui."""
    assert linha_de_venda(_produto(), 1, preco_override=0)["gross_price"] == 0.0


def test_desconto_em_euros_tem_precedencia_sobre_percentagem():
    """O Vendus só aceita um dos dois por linha. O € ganha, como na Pizzaria."""
    li = linha_de_venda(_produto(), 1, desconto_pct=10, desconto_eur=2)
    assert li["discount_amount"] == 2.0
    assert "discount_percentage" not in li


def test_desconto_em_percentagem():
    li = linha_de_venda(_produto(), 1, desconto_pct=10)
    assert li["discount_percentage"] == 10.0
    assert "discount_amount" not in li


def test_quantidade_zero_conta_como_um():
    assert linha_de_venda(_produto(), 0)["qty"] == 1
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_precos.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.precos'`.

- [ ] **Step 3: Escrever a implementação**

Criar `backend/faturacao/precos.py`:

```python
"""Preços, IVA e construção da linha de venda — puro, sem I/O.

Regra de ouro deste módulo: NUNCA inventar um IVA. A app antiga tinha
`vat_rate = prod.get('vat_rate', 13)`, e bastava criar um refrigerante sem IVA
para o faturar a 13% em vez de 23% durante meses. Aqui, sem IVA não há venda.

Modelo (spec D7): um produto pertence a uma categoria — Venda ao Público ou
Vendas Aplicações — e tem UM preço e UM IVA.
"""
from typing import Dict, List, Optional

# Códigos de imposto do Vendus.
_TAXAS = {23: "NOR", 13: "INT", 6: "RED", 0: "ISE"}


def tax_id_de_taxa(taxa) -> Optional[str]:
    """Converte uma percentagem de IVA no código do Vendus. Devolve None se a
    taxa for desconhecida ou ausente — quem chama tem de tratar isso."""
    try:
        return _TAXAS.get(int(round(float(taxa))))
    except (TypeError, ValueError):
        return None


def erros_do_produto(produto: Dict) -> List[str]:
    """Lista, em português, o que falta a um produto para poder ser vendido."""
    erros = []
    if produto.get("preco") is None:
        erros.append("Sem preço definido")
    if not produto.get("tax_id"):
        erros.append("Sem IVA definido")
    return erros


def linha_de_venda(
    produto: Dict,
    quantidade: int = 1,
    opcoes: Optional[List[Dict]] = None,
    preco_override: Optional[float] = None,
    tax_override: Optional[str] = None,
    desconto_pct: Optional[float] = None,
    desconto_eur: Optional[float] = None,
) -> Dict:
    """Constrói a linha no formato que o Vendus aceita.

    As personalizações somam ao preço unitário (é o que a app já faz em produção)
    e os nomes vão entre parêntesis no título, para saírem no talão.
    """
    tax_id = tax_override or produto.get("tax_id")
    if not tax_id:
        raise ValueError(
            "O produto '%s' não tem IVA definido e não pode ser vendido."
            % produto.get("nome", "?")
        )

    # Cuidado: `preco_override or produto[...]` daria 8,99 quando o override é 0.
    base = preco_override if preco_override is not None else produto.get("preco")
    if base is None:
        raise ValueError("O produto '%s' não tem preço definido." % produto.get("nome", "?"))

    opcoes = opcoes or []
    extra = sum(float(o.get("preco", 0) or 0) for o in opcoes)

    titulo = produto.get("nome", "Produto")
    nomes = [o.get("nome") for o in opcoes if o.get("nome")]
    if nomes:
        titulo = "%s (%s)" % (titulo, ", ".join(nomes))

    linha = {
        "title": titulo[:100],
        "qty": quantidade or 1,
        "gross_price": round(float(base) + extra, 2),
        "tax_id": tax_id,
    }

    # O Vendus só aceita um dos dois por linha. O € tem precedência.
    if desconto_eur:
        linha["discount_amount"] = round(float(desconto_eur), 2)
    elif desconto_pct:
        linha["discount_percentage"] = float(desconto_pct)

    return linha
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_precos.py -v
```

Esperado: 13 passed.

- [ ] **Step 5: Validar os testes por mutação**

Um teste verde não vale nada até se o ver vermelho pela razão certa. Fazer **uma de cada vez**,
confirmar que o teste indicado falha, e reverter antes da seguinte:

1. Em `tax_id_de_taxa`, trocar o `return None` do `except` por `return "INT"` →
   `test_taxa_desconhecida_nao_inventa_nada` tem de falhar.
2. Em `linha_de_venda`, trocar `base = preco_override if preco_override is not None else ...`
   por `base = preco_override or produto.get("preco")` →
   `test_override_de_preco_zero_e_respeitado` tem de falhar.
3. Em `linha_de_venda`, trocar o `elif desconto_pct` por `if desconto_pct` →
   `test_desconto_em_euros_tem_precedencia_sobre_percentagem` tem de falhar.
4. Em `erros_do_produto`, remover a verificação do `tax_id` →
   `test_produto_sem_iva_tem_erro` tem de falhar.

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/precos.py backend/tests/faturacao/test_precos.py
git commit -m "Faturação: preços, IVA e linha de venda (IVA obrigatório, sem valores por omissão)"
```

---

## Task 5: Lógica pura do PIN

**Files:**
- Create: `backend/faturacao/pins.py`
- Create: `backend/tests/faturacao/test_pins.py`

**Interfaces:**
- Produces: `normalizar_pin(bruto) -> str`; `hash_pin(pin) -> str`;
  `pin_valido(pin, hash_guardado) -> bool`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_pins.py`:

```python
"""PIN de 4 dígitos do POS — lógica pura."""
import pytest

from faturacao.pins import hash_pin, normalizar_pin, pin_valido


def test_normaliza_espacos():
    assert normalizar_pin(" 1234 ") == "1234"


def test_recusa_pin_curto():
    with pytest.raises(ValueError):
        normalizar_pin("123")


def test_recusa_pin_longo():
    with pytest.raises(ValueError):
        normalizar_pin("12345")


def test_recusa_letras():
    with pytest.raises(ValueError):
        normalizar_pin("12a4")


def test_aceita_pin_com_zeros_a_esquerda():
    assert normalizar_pin("0007") == "0007"


def test_hash_nao_e_o_pin():
    assert hash_pin("1234") != "1234"


def test_hash_muda_de_cada_vez():
    """bcrypt tem sal — dois hashes do mesmo PIN são diferentes."""
    assert hash_pin("1234") != hash_pin("1234")


def test_verificacao():
    h = hash_pin("1234")
    assert pin_valido("1234", h) is True
    assert pin_valido("4321", h) is False


def test_verificacao_com_hash_lixo_nao_rebenta():
    assert pin_valido("1234", "isto-nao-e-um-hash") is False
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_pins.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.pins'`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/pins.py`:

```python
"""PIN de 4 dígitos usado para entrar no POS.

Guardado com bcrypt, como as palavras-passe. Um PIN de 4 dígitos tem só 10.000
combinações, por isso o índice único (loja_id, pin_hash) não impede colisões
entre lojas — impede repetidos DENTRO da mesma loja, que é o que interessa para
saber quem fez cada venda.
"""
import re

import bcrypt

_SO_DIGITOS = re.compile(r"^\d{4}$")


def normalizar_pin(bruto) -> str:
    pin = str(bruto or "").strip()
    if not _SO_DIGITOS.match(pin):
        raise ValueError("O PIN tem de ter exactamente 4 dígitos.")
    return pin


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(normalizar_pin(pin).encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def pin_valido(pin: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(str(pin).encode("utf-8"), str(hash_guardado).encode("utf-8"))
    except (ValueError, TypeError):
        return False
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 33 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/pins.py backend/tests/faturacao/test_pins.py
git commit -m "Faturação: PIN de 4 dígitos (bcrypt)"
```

---

## Task 6: Endpoints de Lojas e Caixas

**Files:**
- Create: `backend/faturacao/lojas.py`
- Create: `backend/tests/faturacao/test_lojas.py`
- Modify: `backend/faturacao/__init__.py`

**Interfaces:**
- Consumes: `obter_db`, `COLECOES` (Task 1), `gestor_atual` (Task 3)
- Produces: router com
  `GET/POST /lojas`, `GET/PUT/DELETE /lojas/{id}`,
  `GET/POST /lojas/{id}/caixas`, `PUT/DELETE /caixas/{id}`;
  modelos `LojaEntrada`, `CaixaEntrada`.

**Nota de desenho:** o `register_id` do Vendus **não** é campo da loja nem da caixa. É uma
variável de ambiente única (`FAT_VENDUS_REGISTER_ID`), lida no Plano 2. Não há selector nenhum na
interface — assim é impossível apontar por engano para outro sítio (spec §10).

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_lojas.py`:

```python
"""Validação dos modelos de Loja e Caixa (sem base de dados)."""
import pytest
from pydantic import ValidationError

from faturacao.lojas import CaixaEntrada, LojaEntrada


def test_loja_minima():
    lj = LojaEntrada(nome="L'Açaí Belém")
    assert lj.nome == "L'Açaí Belém"
    assert lj.cae is None


def test_loja_sem_nome_e_recusada():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="")


def test_loja_completa():
    lj = LojaEntrada(
        nome="L'Açaí Algueirão",
        morada="Rua Ribeiro dos Reis 15B",
        codigo_postal="2725-175",
        localidade="Algueirão",
        email="geral@olacai.com",
        telefone="216086715",
        cae="56103",
    )
    assert lj.codigo_postal == "2725-175"


def test_codigo_postal_invalido_e_recusado():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="X", codigo_postal="2725")


def test_caixa_exige_nome():
    with pytest.raises(ValidationError):
        CaixaEntrada(nome="")


def test_caixa_nao_tem_campo_de_register_vendus():
    """O register_id do Vendus é configuração do sistema, nunca da interface."""
    assert "register_id" not in CaixaEntrada.model_fields
    assert "vendus_register_id" not in CaixaEntrada.model_fields
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_lojas.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.lojas'`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/lojas.py`:

```python
"""Lojas e Caixas — Configuração do módulo Faturação.

Uma loja tem uma ou mais caixas. A caixa é o sítio onde a sessão de dinheiro
vive (Plano 2). O register_id do Vendus NÃO aparece aqui de propósito: é um só
para todo o sistema e vive em variável de ambiente.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()

_CP = re.compile(r"^\d{4}-\d{3}$")


class LojaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    morada: Optional[str] = None
    codigo_postal: Optional[str] = None
    localidade: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    cae: Optional[str] = None
    empresa_id: Optional[str] = None
    rh_location_id: Optional[str] = None
    ativa: bool = True

    @field_validator("codigo_postal")
    @classmethod
    def _valida_cp(cls, v):
        if v and not _CP.match(v):
            raise ValueError("Código postal tem de ser no formato 0000-000")
        return v


class CaixaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    ativa: bool = True


def _agora():
    return datetime.now(timezone.utc).isoformat()


@router.get("/lojas")
async def listar_lojas(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["lojas"]].find({}, {"_id": 0}).sort("nome", 1).to_list(500)


@router.post("/lojas", status_code=201)
async def criar_loja(dados: LojaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    loja = dados.model_dump()
    loja.update({"id": str(uuid.uuid4()), "criada_em": _agora()})
    await db[COLECOES["lojas"]].insert_one(dict(loja))
    return loja


@router.get("/lojas/{loja_id}")
async def obter_loja(loja_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    loja = await db[COLECOES["lojas"]].find_one({"id": loja_id}, {"_id": 0})
    if not loja:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    return loja


@router.put("/lojas/{loja_id}")
async def editar_loja(loja_id: str, dados: LojaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["lojas"]].update_one({"id": loja_id}, {"$set": dados.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    return await db[COLECOES["lojas"]].find_one({"id": loja_id}, {"_id": 0})


@router.delete("/lojas/{loja_id}")
async def apagar_loja(loja_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    if await db[COLECOES["caixas"]].count_documents({"loja_id": loja_id}) > 0:
        raise HTTPException(status_code=409, detail="A loja ainda tem caixas. Apague-as primeiro.")
    await db[COLECOES["lojas"]].delete_one({"id": loja_id})
    return {"apagada": True}


@router.get("/lojas/{loja_id}/caixas")
async def listar_caixas(loja_id: str, _: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["caixas"]].find({"loja_id": loja_id}, {"_id": 0}).to_list(100)


@router.post("/lojas/{loja_id}/caixas", status_code=201)
async def criar_caixa(loja_id: str, dados: CaixaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    if not await db[COLECOES["lojas"]].find_one({"id": loja_id}):
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    caixa = dados.model_dump()
    caixa.update({"id": str(uuid.uuid4()), "loja_id": loja_id, "criada_em": _agora()})
    await db[COLECOES["caixas"]].insert_one(dict(caixa))
    return caixa


@router.put("/caixas/{caixa_id}")
async def editar_caixa(caixa_id: str, dados: CaixaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["caixas"]].update_one({"id": caixa_id}, {"$set": dados.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Caixa não encontrada")
    return await db[COLECOES["caixas"]].find_one({"id": caixa_id}, {"_id": 0})


@router.delete("/caixas/{caixa_id}")
async def apagar_caixa(caixa_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    await db[COLECOES["caixas"]].delete_one({"id": caixa_id})
    return {"apagada": True}
```

Em `backend/faturacao/__init__.py`, acrescentar depois da criação do `router`:

```python
from .lojas import router as _lojas
router.include_router(_lojas)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 39 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/ backend/tests/faturacao/test_lojas.py
git commit -m "Faturação: endpoints de Lojas e Caixas"
```

---

## Task 7: Endpoints de Tipos de Pagamento

O ecrã é **só de leitura sobre o Vendus**: nunca criamos nem alteramos métodos lá. A nossa
configuração é um mapeamento local (nome no POS → código fiscal do Vendus). O método que a app
usa fica marcado `protegido` e não é editável — se alguém o desactivasse, a app passava a cobrar
no Stripe sem emitir fatura, em silêncio (spec §12).

**Files:**
- Create: `backend/faturacao/pagamentos.py`
- Create: `backend/tests/faturacao/test_pagamentos.py`
- Modify: `backend/faturacao/__init__.py`

**Interfaces:**
- Produces: `TIPOS_FISCAIS` (dict código → nome); `TipoPagamentoEntrada`;
  `GET/POST /tipos-pagamento`, `PUT/DELETE /tipos-pagamento/{id}`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_pagamentos.py`:

```python
"""Tipos de pagamento: nome livre + código fiscal do Vendus + dá troco."""
import pytest
from pydantic import ValidationError

from faturacao.pagamentos import TIPOS_FISCAIS, TipoPagamentoEntrada


def test_codigos_fiscais_do_vendus():
    """Os códigos são os documentados em registers/movements.doc."""
    assert TIPOS_FISCAIS["NU"] == "Numerário"
    assert TIPOS_FISCAIS["CD"] == "Cartão de Débito"
    assert TIPOS_FISCAIS["CC"] == "Cartão de Crédito"
    assert TIPOS_FISCAIS["TB"] == "Transferência Bancária"
    assert TIPOS_FISCAIS["MBWAY"] == "MB Way"


def test_tipo_valido():
    t = TipoPagamentoEntrada(nome="Glovo", tipo_fiscal="TB", da_troco=False)
    assert t.tipo_fiscal == "TB"


def test_tipo_fiscal_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        TipoPagamentoEntrada(nome="Inventado", tipo_fiscal="XX")


def test_dinheiro_da_troco_por_omissao_e_falso():
    """Quem cria decide. Não se adivinha — 'Glovo' com troco seria um erro caro."""
    assert TipoPagamentoEntrada(nome="X", tipo_fiscal="NU").da_troco is False


def test_nome_obrigatorio():
    with pytest.raises(ValidationError):
        TipoPagamentoEntrada(nome="", tipo_fiscal="NU")
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_pagamentos.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.pagamentos'`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/pagamentos.py`:

```python
"""Tipos de pagamento do POS.

Um tipo tem um nome livre (o que a funcionária vê: "Glovo", "Uber Eats") e um
código fiscal do Vendus por trás (TB, NU, CD...). É por isso que "Glovo" pode ser
um botão próprio sem deixar de ser transferência bancária aos olhos do fisco.

NUNCA escrevemos nos métodos de pagamento do Vendus — só mapeamos.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()

# Códigos documentados em https://www.vendus.pt/ws/v1.1/registers/movements.doc
TIPOS_FISCAIS = {
    "NU": "Numerário",
    "CD": "Cartão de Débito",
    "CC": "Cartão de Crédito",
    "TB": "Transferência Bancária",
    "MB": "Referência MB",
    "MBWAY": "MB Way",
    "CH": "Cheque",
    "TR": "Ticket Restaurante",
    "CO": "Cartão Oferta",
    "CS": "Compensação de Saldos",
    "OU": "Outro",
}


class TipoPagamentoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    tipo_fiscal: str
    da_troco: bool = False
    ordem: int = 0
    ativo: bool = True
    vendus_payment_method_id: Optional[str] = None

    @field_validator("tipo_fiscal")
    @classmethod
    def _valida(cls, v):
        if v not in TIPOS_FISCAIS:
            raise ValueError("Tipo fiscal desconhecido: " + str(v))
        return v


@router.get("/tipos-pagamento")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["tipos_pagamento"]].find({}, {"_id": 0}).sort("ordem", 1).to_list(100)


@router.get("/tipos-pagamento/codigos-fiscais")
async def codigos(_: dict = Depends(gestor_atual)) -> dict:
    return TIPOS_FISCAIS


@router.post("/tipos-pagamento", status_code=201)
async def criar(dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    tipo = dados.model_dump()
    tipo.update({"id": str(uuid.uuid4()), "protegido": False,
                 "criado_em": datetime.now(timezone.utc).isoformat()})
    await db[COLECOES["tipos_pagamento"]].insert_one(dict(tipo))
    return tipo


@router.put("/tipos-pagamento/{tipo_id}")
async def editar(tipo_id: str, dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})
    if not atual:
        raise HTTPException(status_code=404, detail="Tipo de pagamento não encontrado")
    if atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser alterado.",
        )
    await db[COLECOES["tipos_pagamento"]].update_one({"id": tipo_id}, {"$set": dados.model_dump()})
    return await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})


@router.delete("/tipos-pagamento/{tipo_id}")
async def apagar(tipo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id})
    if atual and atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser apagado.",
        )
    await db[COLECOES["tipos_pagamento"]].delete_one({"id": tipo_id})
    return {"apagado": True}
```

Em `backend/faturacao/__init__.py`:

```python
from .pagamentos import router as _pagamentos
router.include_router(_pagamentos)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 44 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/ backend/tests/faturacao/test_pagamentos.py
git commit -m "Faturação: tipos de pagamento (mapeamento local, protegidos não editáveis)"
```

---

## Task 8: Endpoints de Utilizadores do POS

**Files:**
- Create: `backend/faturacao/utilizadores.py`
- Create: `backend/tests/faturacao/test_utilizadores.py`
- Modify: `backend/faturacao/__init__.py`

**Interfaces:**
- Consumes: `hash_pin`, `normalizar_pin` (Task 5)
- Produces: `PERFIS_POS = ["administrador", "operador_caixa", "contabilista"]`;
  `UtilizadorEntrada`; `GET/POST /utilizadores`, `PUT /utilizadores/{id}`,
  `PUT /utilizadores/{id}/pin`, `PUT /utilizadores/{id}/estado`

**Regra:** quem sai fica **inactivo**, nunca apagado — senão parte-se o histórico de quem fez cada
venda. Não há endpoint DELETE de propósito.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_utilizadores.py`:

```python
"""Utilizadores do POS: nome, PIN, perfil, lojas onde entram."""
import pytest
from pydantic import ValidationError

from faturacao.utilizadores import PERFIS_POS, UtilizadorEntrada


def test_perfis_sao_os_tres_decididos():
    """O dono decidiu NÃO ter 'Encarregada de Loja' (spec D16)."""
    assert PERFIS_POS == ["administrador", "operador_caixa", "contabilista"]


def test_utilizador_valido():
    u = UtilizadorEntrada(nome="Rafaela Prates", pin="1234", perfil="operador_caixa",
                          lojas=["loja-1"])
    assert u.pin == "1234"


def test_perfil_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="1234", perfil="encarregada", lojas=[])


def test_pin_invalido_e_recusado():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="12", perfil="operador_caixa", lojas=[])


def test_operador_tem_de_ter_pelo_menos_uma_loja():
    with pytest.raises(ValidationError):
        UtilizadorEntrada(nome="X", pin="1234", perfil="operador_caixa", lojas=[])


def test_administrador_pode_nao_ter_lojas():
    """O administrador entra em qualquer loja."""
    u = UtilizadorEntrada(nome="Matheus", pin="9999", perfil="administrador", lojas=[])
    assert u.lojas == []


def test_nao_existe_endpoint_de_apagar():
    """Quem sai fica inactivo. Apagar partiria o histórico de vendas."""
    from faturacao.utilizadores import router
    metodos = {(r.path, m) for r in router.routes for m in getattr(r, "methods", set())}
    assert not [p for (p, m) in metodos if m == "DELETE"]
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_utilizadores.py -v
```

Esperado: FALHA com `ModuleNotFoundError: No module named 'faturacao.utilizadores'`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/utilizadores.py`:

```python
"""Utilizadores do POS.

Entram com PIN de 4 dígitos, nunca vêem o backoffice. Quem sai da empresa fica
INACTIVO, nunca apagado — o histórico de vendas aponta para o utilizador, e
apagá-lo deixaria vendas órfãs. Por isso não há DELETE aqui.

O campo employee_id liga (opcionalmente) ao colaborador do RH, para herdar a
foto que já existe no perfil dele e mostrá-la na tela de descanso do POS.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pins import hash_pin, normalizar_pin

router = APIRouter()

PERFIS_POS = ["administrador", "operador_caixa", "contabilista"]


class UtilizadorEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    pin: str
    perfil: str
    lojas: List[str] = []
    employee_id: Optional[str] = None

    @field_validator("pin")
    @classmethod
    def _valida_pin(cls, v):
        return normalizar_pin(v)

    @field_validator("perfil")
    @classmethod
    def _valida_perfil(cls, v):
        if v not in PERFIS_POS:
            raise ValueError("Perfil desconhecido: " + str(v))
        return v

    @model_validator(mode="after")
    def _operador_precisa_de_loja(self):
        if self.perfil == "operador_caixa" and not self.lojas:
            raise ValueError("Um operador de caixa tem de ter pelo menos uma loja.")
        return self


class MudarPin(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _valida(cls, v):
        return normalizar_pin(v)


class MudarEstado(BaseModel):
    ativo: bool


def _publico(u: dict) -> dict:
    """Nunca devolver o hash do PIN para fora."""
    return {k: v for k, v in u.items() if k not in ("_id", "pin_hash")}


@router.get("/utilizadores")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    us = await db[COLECOES["utilizadores"]].find({}).sort("nome", 1).to_list(500)
    return [_publico(u) for u in us]


@router.post("/utilizadores", status_code=201)
async def criar(dados: UtilizadorEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    u = dados.model_dump()
    pin = u.pop("pin")
    u.update({
        "id": str(uuid.uuid4()),
        "pin_hash": hash_pin(pin),
        "ativo": True,
        "criado_em": datetime.now(timezone.utc).isoformat(),
    })
    await db[COLECOES["utilizadores"]].insert_one(dict(u))
    return _publico(u)


@router.put("/utilizadores/{utilizador_id}")
async def editar(utilizador_id: str, dados: UtilizadorEntrada,
                 _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    u = dados.model_dump()
    u.pop("pin", None)  # o PIN muda no seu próprio endpoint
    r = await db[COLECOES["utilizadores"]].update_one({"id": utilizador_id}, {"$set": u})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return _publico(await db[COLECOES["utilizadores"]].find_one({"id": utilizador_id}))


@router.put("/utilizadores/{utilizador_id}/pin")
async def mudar_pin(utilizador_id: str, dados: MudarPin,
                    _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["utilizadores"]].update_one(
        {"id": utilizador_id}, {"$set": {"pin_hash": hash_pin(dados.pin)}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return {"atualizado": True}


@router.put("/utilizadores/{utilizador_id}/estado")
async def mudar_estado(utilizador_id: str, dados: MudarEstado,
                       _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["utilizadores"]].update_one(
        {"id": utilizador_id}, {"$set": {"ativo": dados.ativo}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return {"ativo": dados.ativo}
```

Em `backend/faturacao/__init__.py`:

```python
from .utilizadores import router as _utilizadores
router.include_router(_utilizadores)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 51 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/ backend/tests/faturacao/test_utilizadores.py
git commit -m "Faturação: utilizadores do POS (PIN, 3 perfis, inactivar em vez de apagar)"
```

---

## Task 9: Motivos de Nota de Crédito

**Files:**
- Create: `backend/faturacao/motivos.py`
- Create: `backend/tests/faturacao/test_motivos.py`
- Modify: `backend/faturacao/__init__.py`

**Interfaces:**
- Produces: `MotivoEntrada`; `GET/POST /motivos-nc`, `PUT/DELETE /motivos-nc/{id}`,
  `PUT /motivos-nc/{id}/predefinir`

**Nota:** em Portugal o motivo vai em **texto livre** no campo `notes` do documento — o campo
`ncr_id` da API do Vendus é específico de Cabo Verde. Aqui só se guarda a lista de textos.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_motivos.py`:

```python
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
```

- [ ] **Step 2: Correr para confirmar que falha**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_motivos.py -v
```

Esperado: FALHA com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Criar `backend/faturacao/motivos.py`:

```python
"""Motivos para emissão de notas de crédito.

Em Portugal o motivo vai em texto livre no campo `notes` do documento — o campo
`ncr_id` da API do Vendus está marcado como específico de Cabo Verde.
Usado no Plano 2, configurado aqui.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()


class MotivoEntrada(BaseModel):
    texto: str = Field(min_length=1, max_length=200)


@router.get("/motivos-nc")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["motivos_nc"]].find({}, {"_id": 0}).to_list(100)


@router.post("/motivos-nc", status_code=201)
async def criar(dados: MotivoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    m = {"id": str(uuid.uuid4()), "texto": dados.texto, "predefinido": False}
    await db[COLECOES["motivos_nc"]].insert_one(dict(m))
    return m


@router.put("/motivos-nc/{motivo_id}")
async def editar(motivo_id: str, dados: MotivoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["motivos_nc"]].update_one(
        {"id": motivo_id}, {"$set": {"texto": dados.texto}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")
    return await db[COLECOES["motivos_nc"]].find_one({"id": motivo_id}, {"_id": 0})


@router.put("/motivos-nc/{motivo_id}/predefinir")
async def predefinir(motivo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    await db[COLECOES["motivos_nc"]].update_many({}, {"$set": {"predefinido": False}})
    r = await db[COLECOES["motivos_nc"]].update_one(
        {"id": motivo_id}, {"$set": {"predefinido": True}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")
    return {"predefinido": motivo_id}


@router.delete("/motivos-nc/{motivo_id}")
async def apagar(motivo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    await db[COLECOES["motivos_nc"]].delete_one({"id": motivo_id})
    return {"apagado": True}
```

Em `backend/faturacao/__init__.py`:

```python
from .motivos import router as _motivos
router.include_router(_motivos)
```

- [ ] **Step 4: Correr para confirmar que passa**

```bash
cd ~/Developer/RH/backend && .venv/bin/pytest tests/faturacao/ -v
```

Esperado: 54 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH
git add backend/faturacao/ backend/tests/faturacao/test_motivos.py
git commit -m "Faturação: motivos de nota de crédito"
```

---

## Estado: o resto do Plano 1

A decisão do catálogo já está tomada (ver acima). As tarefas seguintes escrevem-se a seguir às
Tasks 1-9, quando estas estiverem implementadas e revistas — assim o detalhe delas parte de código
real e não de suposições:

- **Task 10:** Categorias e Grupos de Personalização (endpoints + validação de `min_select`/`max_select`)
- **Task 11:** Produtos (endpoints, categoria, preço, `tax_id` obrigatório, ecrã "Produtos sem IVA")
- **Task 12:** Cliente Vendus de leitura + importação do catálogo (com paginação — o bug do
  `per_page` em falta que existe hoje no import da Pizzaria importa só 20 produtos)
- **Task 13:** Frontend — secção Faturação no `AdminLayout` (incluindo a correcção do apanha-tudo
  do RH), rotas em `App.js`, `lib/faturacao.js`, e as páginas de Configuração
- **Task 14:** Frontend — páginas do Catálogo e ecrã "Produtos sem IVA definido"

---

## Verificação final do Plano 1

- [ ] `cd ~/Developer/RH/backend && .venv/bin/pytest tests/ -v` — tudo verde
- [ ] `cd ~/Developer/RH/frontend && CI=false yarn build` — compila
- [ ] O RH, o Financeiro e o Marketing continuam a funcionar (abrir cada secção no browser)
- [ ] Criar uma loja, uma caixa, um utilizador com PIN e um tipo de pagamento pelo backoffice
- [ ] Importar o catálogo do Vendus e confirmar a contagem de produtos contra o backoffice do Vendus
- [ ] O ecrã "Produtos sem IVA definido" mostra a lista e impede a publicação enquanto não estiver vazia
