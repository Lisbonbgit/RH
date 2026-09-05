# Secção Conciliação — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o Excel mensal da diretora financeira por uma secção no Financeiro onde ela classifica, anota e documenta os movimentos do banco, com os cartões de resumo que a folha dela tem.

**Architecture:** A secção assenta no que já existe. `fin_movements` ganha três campos (`category`, `note`, `manual`); a lista de categorias passa a viver no documento da empresa e a ser partilhada com as faturas; os cartões calculam-se no ecrã a partir dos movimentos do mês, exceto o saldo por banco, que precisa de um endpoint novo porque o desempate intra-dia é por `_id` e o `_id` nunca sai do servidor. A ligação a faturas, o motor de sugestões e os carimbos aprendidos usam-se tal e qual.

**Tech Stack:** FastAPI + Motor/MongoDB (backend, tudo em `backend/server.py`); React 18 + CRA/craco + shadcn/ui + lucide-react + sonner (frontend); pytest puro com duplos escritos à mão (backend); jest via `craco test` para os módulos puros de `frontend/src/lib`.

## Global Constraints

- **Repo:** `/Users/matheus.moraes/Developer/RH`. **Ramo:** `matheus-conciliacao`. Nunca trabalhar no `main`.
- **Português de Portugal** em tudo o que o utilizador lê e nos nomes dos testes.
- **Backend:** todo o código do Financeiro vive em `backend/server.py`. Não criar módulos novos para ele.
- **Permissões:** ler exige `fin_require_member(company_id, current_user)`; escrever exige `fin_require_editor(...)`. O contabilista é só-leitura.
- **`company_id="all"`** resolve-se por `_fin_report_scope(company_id, current_user)` (server.py:8512), que devolve a string ou `{"$in": [...]}`.
- **Pydantic 2.12.5** — usar `payload.model_dump(exclude_unset=True)`, nunca `.dict()`.
- **Testes backend:** `cd backend && ./.venv/bin/python -m pytest -q`. Base actual: **2820 passed**. Um teste novo nunca liga a Mongo: `MONGO_URL`/`DB_NAME` no ambiente **antes** de `import server`, duplo próprio no ficheiro, `monkeypatch.setattr(server, "db", ...)`.
- **Testes frontend:** `cd frontend && CI=true yarn test --watchAll=false <ficheiro>`. Só para módulos puros de `src/lib`.
- **`None` não é zero.** Regra da casa: um valor desconhecido mostra-se como `—`, nunca como `0`.
- **Dinheiro** formata-se sempre com `eur()` de `src/lib/finance.js`.
- **Commits** terminam com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Estrutura de ficheiros

**Criar**
- `frontend/src/lib/conciliacao.js` — aritmética pura dos cartões (resumo por categoria, %, plataformas, descrição do movimento). Sem React, sem HTTP.
- `frontend/src/lib/conciliacao.test.js` — jest do acima.
- `frontend/src/lib/finance.test.js` — jest das categorias.
- `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js` — a página: carregamento, separadores, estado.
- `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoCartoes.js` — os cinco cartões de topo.
- `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoTabela.js` — a tabela mensal.
- `frontend/src/pages/admin/financeiro/conciliacao/DialogoFatura.js` — o diálogo de ligar/anexar documento.
- `backend/migrar_categorias.py` — migração única, com `--aplicar` obrigatório para escrever.
- `backend/tests/fin/test_as_categorias_sao_da_empresa.py`
- `backend/tests/fin/test_a_linha_manual_nao_finge_saldo.py`
- `backend/tests/fin/test_so_se_apaga_uma_linha_manual.py`
- `backend/tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py`
- `backend/tests/fin/test_anexar_num_movimento_de_entrada.py`
- `backend/tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py`
- `backend/tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py`

**Modificar**
- `backend/server.py` — modelos, endpoints novos, índices, categorias da empresa.
- `frontend/src/lib/finance.js` — lista de categorias partilhada.
- `frontend/src/lib/api.js` — wrappers HTTP novos.
- `frontend/src/App.js` — rota.
- `frontend/src/components/layouts/AdminLayout.js` — entrada no menu.
- `frontend/src/pages/admin/financeiro/FinPagamentos.js` — passa a ler a lista da empresa; perde duas abas.
- `frontend/src/pages/admin/financeiro/FinRelatorios.js` — passa a ler a lista da empresa.
- `frontend/src/pages/admin/financeiro/FinInicio.js` — editor de categorias por empresa.

---

### Task 1: A lista de categorias, num sítio só

Hoje a lista está escrita à mão em `FinPagamentos.js:48-58` e outra vez em `FinRelatorios.js:35-39`. Antes de a coluna nova criar uma terceira cópia, extrai-se.

**Files:**
- Modify: `frontend/src/lib/finance.js` (acrescentar no fim)
- Test: `frontend/src/lib/finance.test.js` (criar)

**Interfaces:**
- Consumes: nada.
- Produces: `CATEGORIAS_PADRAO: {id: string, label: string}[]`, `categoriasDaEmpresa(company): {id,label}[]`, `categoriaLabel(cats, id): string`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/lib/finance.test.js`:

```js
import { CATEGORIAS_PADRAO, categoriasDaEmpresa, categoriaLabel } from './finance';

describe('categorias do Financeiro', () => {
  test('a lista por omissão tem as categorias do Excel da diretora financeira', () => {
    const ids = CATEGORIAS_PADRAO.map((c) => c.id);
    expect(ids).toContain('entradas');
    expect(ids).toContain('fornecedor');
    expect(ids).toContain('utilitarios');
    // As duas que só existem no sistema não podem desaparecer, senão as
    // faturas já gravadas com elas ficam órfãs.
    expect(ids).toContain('rendas');
    expect(ids).toContain('outros');
  });

  test('uma empresa sem lista própria usa a lista por omissão', () => {
    expect(categoriasDaEmpresa({ id: 'e1' })).toBe(CATEGORIAS_PADRAO);
    expect(categoriasDaEmpresa({ id: 'e1', categorias: [] })).toBe(CATEGORIAS_PADRAO);
    expect(categoriasDaEmpresa(null)).toBe(CATEGORIAS_PADRAO);
  });

  test('uma empresa com lista própria manda nela', () => {
    const minhas = [{ id: 'gelo', label: 'Gelo' }];
    expect(categoriasDaEmpresa({ id: 'e1', categorias: minhas })).toBe(minhas);
  });

  test('uma categoria desconhecida mostra a chave crua, não desaparece', () => {
    // Uma fatura antiga com "mercadoria" tem de continuar a mostrar alguma
    // coisa no ecrã enquanto a migração não corre.
    expect(categoriaLabel(CATEGORIAS_PADRAO, 'mercadoria')).toBe('mercadoria');
    expect(categoriaLabel(CATEGORIAS_PADRAO, 'fornecedor')).toBe('Fornecedor');
    expect(categoriaLabel(CATEGORIAS_PADRAO, null)).toBe('');
  });
});
```

- [ ] **Step 2: Correr o teste e ver falhar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn test --watchAll=false src/lib/finance.test.js
```

Esperado: FAIL — `CATEGORIAS_PADRAO is not defined` / `categoriasDaEmpresa is not a function`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Acrescentar no fim de `frontend/src/lib/finance.js`:

```js
// Categorias do Financeiro. Uma lista SÓ, partilhada pelas faturas (relatório
// de Resultados) e pelos movimentos (Conciliação) — duas listas dariam dois
// números para a mesma pergunta. É a lista do Excel da diretora financeira,
// mais `rendas` e `outros`, que já existiam gravadas nas faturas.
export const CATEGORIAS_PADRAO = [
  { id: 'entradas', label: 'Entradas' },
  { id: 'salarios', label: 'Salários' },
  { id: 'utilitarios', label: 'Utilitários' },
  { id: 'servicos', label: 'Serviços' },
  { id: 'impostos', label: 'Impostos' },
  { id: 'investimento', label: 'Investimento Equipamentos' },
  { id: 'supermercado', label: 'Supermercado' },
  { id: 'fornecedor', label: 'Fornecedor' },
  { id: 'seguros', label: 'Seguros' },
  { id: 'marketing', label: 'Marketing' },
  { id: 'cartoes_credito', label: 'Cartões de Crédito' },
  { id: 'dominios_sites', label: 'Domínios e Sites' },
  { id: 'transporte', label: 'Transporte' },
  { id: 'rendas', label: 'Rendas' },
  { id: 'outros', label: 'Outros' },
];

// A lista é POR EMPRESA (cada empresa tem o seu "Excel"). Sem lista própria,
// vale a de omissão.
export const categoriasDaEmpresa = (company) => {
  const cats = company && Array.isArray(company.categorias) ? company.categorias : null;
  return cats && cats.length ? cats : CATEGORIAS_PADRAO;
};

// Devolve a chave crua quando não conhece a categoria: um valor legado nunca
// pode sumir do ecrã só porque saiu da lista.
export const categoriaLabel = (cats, id) => {
  if (!id) return '';
  const found = (cats || []).find((c) => c.id === id);
  return found ? found.label : id;
};
```

- [ ] **Step 4: Correr o teste e ver passar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn test --watchAll=false src/lib/finance.test.js
```

Esperado: PASS, 4 testes.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/lib/finance.js frontend/src/lib/finance.test.js && git commit -m "As categorias do Financeiro num sítio só

Estavam escritas à mão em FinPagamentos.js e outra vez em FinRelatorios.js.
A lista passa a ser a do Excel da diretora financeira, por empresa, com
categoriaLabel a devolver a chave crua para nenhum valor legado sumir do ecrã.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: As categorias vivem na empresa

**Files:**
- Modify: `backend/server.py:3224-3234` (modelos), `backend/server.py:3376-3387` (PUT)
- Test: `backend/tests/fin/test_as_categorias_sao_da_empresa.py` (criar)

**Interfaces:**
- Consumes: `fin_require_owner`, `_fin_norm_nif` (já existem).
- Produces: `FIN_CATEGORIAS_PADRAO: list[dict]`, `_fin_categorias_da_empresa(company_id) -> list[dict]`, campo `categorias` em `FinCompanyCreate`/`FinCompanyResponse`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/fin/test_as_categorias_sao_da_empresa.py`:

```python
"""**Um PUT à empresa não pode apagar as categorias dela.**

O `fin_update_company` faz um `$set` explícito com `name` e `nif`. Acrescentar
`categorias` ao modelo e escrevê-lo sempre significa que qualquer ecrã que
guarde o nome da empresa — e o de Configurações guarda — apaga a lista de
categorias que a diretora financeira montou, sem ninguém dar por isso.

Por isso o campo só se escreve quando vem MESMO no pedido (`exclude_unset`),
e a lista de omissão serve quem nunca a personalizou.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class EmpresasFalsas:
    def __init__(self, guardadas):
        self.guardadas = list(guardadas)
        self.updates = []

    async def find_one(self, filtro, proj=None):
        for doc in self.guardadas:
            if doc.get("id") == filtro.get("id"):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        self.updates.append(update)
        for doc in self.guardadas:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, empresas):
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_owner", passa)


def test_guardar_so_o_nome_nao_apaga_as_categorias(monkeypatch, sem_permissoes):
    empresas = EmpresasFalsas([
        {"id": "e1", "name": "Fordaimon", "nif": "500000000",
         "categorias": [{"id": "gelo", "label": "Gelo"}]},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    payload = server.FinCompanyCreate(name="Fordaimon Foods", nif="500000000")
    _corre(server.fin_update_company("e1", payload, {"user_id": "u1"}))

    assert "categorias" not in empresas.updates[0]["$set"], (
        "o PUT escreveu categorias sem ninguém as ter enviado — isto apaga a "
        "lista da empresa de cada vez que se muda o nome"
    )
    assert empresas.guardadas[0]["categorias"] == [{"id": "gelo", "label": "Gelo"}]


def test_enviar_categorias_guarda_as_categorias(monkeypatch, sem_permissoes):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon", "nif": None}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    payload = server.FinCompanyCreate(
        name="Fordaimon", categorias=[{"id": "gelo", "label": "Gelo"}]
    )
    _corre(server.fin_update_company("e1", payload, {"user_id": "u1"}))

    assert empresas.guardadas[0]["categorias"] == [{"id": "gelo", "label": "Gelo"}]


def test_uma_empresa_sem_lista_usa_a_de_omissao(monkeypatch):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon"}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    cats = _corre(server._fin_categorias_da_empresa("e1"))

    assert cats is server.FIN_CATEGORIAS_PADRAO
    ids = [c["id"] for c in cats]
    assert "entradas" in ids and "fornecedor" in ids and "rendas" in ids


def test_uma_lista_vazia_nao_deixa_a_empresa_sem_categorias(monkeypatch):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon", "categorias": []}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    assert _corre(server._fin_categorias_da_empresa("e1")) is server.FIN_CATEGORIAS_PADRAO
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_as_categorias_sao_da_empresa.py -q
```

Esperado: FAIL — `AttributeError: module 'server' has no attribute '_fin_categorias_da_empresa'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `backend/server.py`, **imediatamente antes** de `class FinCompanyCreate` (linha 3224):

```python
# Categorias do Financeiro. Uma lista SÓ, partilhada pelas faturas (DRE) e
# pelos movimentos (Conciliação). Espelha CATEGORIAS_PADRAO de
# frontend/src/lib/finance.js — se mudar aqui, muda lá.
FIN_CATEGORIAS_PADRAO = [
    {"id": "entradas", "label": "Entradas"},
    {"id": "salarios", "label": "Salários"},
    {"id": "utilitarios", "label": "Utilitários"},
    {"id": "servicos", "label": "Serviços"},
    {"id": "impostos", "label": "Impostos"},
    {"id": "investimento", "label": "Investimento Equipamentos"},
    {"id": "supermercado", "label": "Supermercado"},
    {"id": "fornecedor", "label": "Fornecedor"},
    {"id": "seguros", "label": "Seguros"},
    {"id": "marketing", "label": "Marketing"},
    {"id": "cartoes_credito", "label": "Cartões de Crédito"},
    {"id": "dominios_sites", "label": "Domínios e Sites"},
    {"id": "transporte", "label": "Transporte"},
    {"id": "rendas", "label": "Rendas"},
    {"id": "outros", "label": "Outros"},
]


async def _fin_categorias_da_empresa(company_id: str):
    """A lista da empresa, ou a de omissão. Nunca devolve vazio: um ecrã sem
    categorias nenhumas deixava a diretora financeira sem forma de classificar."""
    comp = await db.fin_companies.find_one({"id": company_id}, {"_id": 0, "categorias": 1})
    cats = (comp or {}).get("categorias")
    if isinstance(cats, list) and cats:
        return cats
    return FIN_CATEGORIAS_PADRAO


class FinCategoria(BaseModel):
    id: str
    label: str
```

Depois, alterar os dois modelos (server.py:3224-3234):

```python
class FinCompanyCreate(BaseModel):
    name: str
    nif: Optional[str] = None
    categorias: Optional[List[FinCategoria]] = None

class FinCompanyResponse(BaseModel):
    id: str
    name: str
    nif: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None
    categorias: Optional[List[FinCategoria]] = None
```

E o corpo do `fin_update_company` (server.py:3376-3387) passa a:

```python
@api_router.put("/fin/companies/{company_id}", response_model=FinCompanyResponse)
async def fin_update_company(company_id: str, payload: FinCompanyCreate, current_user: dict = Depends(get_current_user)):
    await fin_require_owner(company_id, current_user)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica o nome da empresa.")
    campos = {"name": name, "nif": _fin_norm_nif(payload.nif)}
    # `exclude_unset`: as categorias só se escrevem quando vêm MESMO no pedido.
    # Sem isto, guardar o nome da empresa apagava a lista que ela montou.
    if "categorias" in payload.model_dump(exclude_unset=True):
        cats = [{"id": c.id.strip(), "label": c.label.strip()} for c in (payload.categorias or [])]
        cats = [c for c in cats if c["id"] and c["label"]]
        vistos = set()
        unicas = []
        for c in cats:
            if c["id"] in vistos:
                continue
            vistos.add(c["id"])
            unicas.append(c)
        if not unicas:
            raise HTTPException(status_code=400, detail="A empresa precisa de pelo menos uma categoria.")
        campos["categorias"] = unicas
    await db.fin_companies.update_one({"id": company_id}, {"$set": campos})
    updated = await db.fin_companies.find_one({"id": company_id}, {"_id": 0})
    return FinCompanyResponse(**updated, role="owner")
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_as_categorias_sao_da_empresa.py -q && ./.venv/bin/python -m pytest -q
```

Esperado: 4 passed no primeiro; **2824 passed** no total.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py backend/tests/fin/test_as_categorias_sao_da_empresa.py && git commit -m "Categorias por empresa, sem as apagar sem querer

Cada empresa tem a sua lista. O PUT só a escreve quando ela vem mesmo no
pedido — senão guardar o nome da empresa apagava a lista toda.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: A migração das faturas já gravadas

`mercadoria` e `energia_agua` deixam de existir. As faturas que as têm são reescritas — uma vez, com ensaio antes.

**Files:**
- Create: `backend/migrar_categorias.py`
- Test: `backend/tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py`

**Interfaces:**
- Consumes: `FIN_CATEGORIAS_PADRAO` (Task 2).
- Produces: `MAPA_CATEGORIAS: dict[str,str]`, `categoria_migrada(valor) -> str|None`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py`:

```python
"""**A migração não pode deixar uma fatura com categoria órfã.**

`mercadoria` e `energia_agua` desaparecem da lista. Uma fatura que fique com
esses valores deixa de aparecer no relatório de Resultados com nome — aparece
com a chave crua, ou não aparece de todo se alguém filtrar pela lista.

Este teste percorre todos os valores que alguma vez foram escritos e exige que
cada um caia numa categoria que EXISTE na lista nova.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402
from migrar_categorias import MAPA_CATEGORIAS, categoria_migrada  # noqa: E402

VALORES_ANTIGOS = [
    "mercadoria", "rendas", "energia_agua", "salarios",
    "servicos", "impostos", "outros",
]


def test_todo_o_valor_antigo_cai_numa_categoria_que_existe():
    ids_novos = {c["id"] for c in server.FIN_CATEGORIAS_PADRAO}
    for antigo in VALORES_ANTIGOS:
        novo = categoria_migrada(antigo)
        assert novo in ids_novos, f"{antigo} ficaria órfão em {novo!r}"


def test_os_dois_que_mudam_de_nome_mudam_para_o_certo():
    assert MAPA_CATEGORIAS["mercadoria"] == "fornecedor"
    assert MAPA_CATEGORIAS["energia_agua"] == "utilitarios"


def test_o_que_ja_esta_certo_fica_como_esta():
    assert categoria_migrada("servicos") == "servicos"
    assert categoria_migrada("impostos") == "impostos"


def test_uma_categoria_desconhecida_vai_para_outros_e_nao_se_perde():
    # Valores soltos escritos à mão em produção não podem ficar sem casa.
    assert categoria_migrada("qualquer_coisa") == "outros"


def test_sem_categoria_continua_sem_categoria():
    # Uma fatura por classificar não pode passar a "Outros": isso esconderia
    # trabalho por fazer atrás de um número credível.
    assert categoria_migrada(None) is None
    assert categoria_migrada("") is None
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py -q
```

Esperado: FAIL — `ModuleNotFoundError: No module named 'migrar_categorias'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Criar `backend/migrar_categorias.py`:

```python
"""Migração única das categorias das faturas (2026-09).

`mercadoria` passa a `fornecedor` e `energia_agua` a `utilitarios`, para que a
Conciliação e o relatório de Resultados falem a mesma língua. Corre em ensaio
por omissão; só escreve com `--aplicar`.

    cd backend && ./.venv/bin/python migrar_categorias.py            # ensaio
    cd backend && ./.venv/bin/python migrar_categorias.py --aplicar  # a sério
"""
import asyncio
import os
import sys

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402

MAPA_CATEGORIAS = {
    "mercadoria": "fornecedor",
    "energia_agua": "utilitarios",
    "rendas": "rendas",
    "salarios": "salarios",
    "servicos": "servicos",
    "impostos": "impostos",
    "outros": "outros",
}


def categoria_migrada(valor):
    """Categoria nova, ou None se a fatura estava por classificar.

    Por classificar continua por classificar: mandá-la para "Outros" escondia
    trabalho por fazer atrás de um número que parece completo."""
    if not valor:
        return None
    return MAPA_CATEGORIAS.get(valor, "outros")


async def _correr(aplicar: bool):
    faturas = await server.db.fin_invoices.find(
        {"category": {"$nin": [None, ""]}}, {"_id": 0, "id": 1, "category": 1}
    ).to_list(50000)
    mudancas = {}
    for inv in faturas:
        antiga = inv.get("category")
        nova = categoria_migrada(antiga)
        if nova and nova != antiga:
            mudancas.setdefault((antiga, nova), []).append(inv["id"])
    total = sum(len(v) for v in mudancas.values())
    for (antiga, nova), ids in sorted(mudancas.items()):
        print(f"  {antiga} -> {nova}: {len(ids)} faturas")
    print(f"{'A APLICAR' if aplicar else 'ENSAIO'}: {total} faturas a mudar de categoria")
    if not aplicar:
        print("Nada foi escrito. Corre outra vez com --aplicar.")
        return
    for (antiga, nova), ids in mudancas.items():
        await server.db.fin_invoices.update_many(
            {"id": {"$in": ids}}, {"$set": {"category": nova}}
        )
    print(f"Feito: {total} faturas reescritas.")


if __name__ == "__main__":
    asyncio.run(_correr("--aplicar" in sys.argv))
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py -q
```

Esperado: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/migrar_categorias.py backend/tests/fin/test_a_migracao_de_categorias_nao_perde_faturas.py && git commit -m "Migração das categorias das faturas, com ensaio por omissão

mercadoria -> fornecedor, energia_agua -> utilitarios. Uma fatura por
classificar continua por classificar: mandá-la para Outros esconderia
trabalho por fazer atrás de um número que parece completo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Pagamentos e Relatórios passam a ler a lista da empresa

**Files:**
- Modify: `frontend/src/pages/admin/financeiro/FinPagamentos.js:47-58`
- Modify: `frontend/src/pages/admin/financeiro/FinRelatorios.js:35-39` e `:303`

**Interfaces:**
- Consumes: `categoriasDaEmpresa`, `categoriaLabel` (Task 1).
- Produces: nada de novo.

- [ ] **Step 1: Apagar a lista escrita à mão do Pagamentos**

Em `FinPagamentos.js`, apagar as linhas 47-58 (o bloco `const CATEGORIAS = [...]` e o `categoriaLabel`) e acrescentar ao import que já existe de `../../../lib/finance`:

```js
import { eur, fmtDate, kpiTone, categoriasDaEmpresa, categoriaLabel } from '../../../lib/finance';
```

Dentro do componente, onde `selectedCompany` já está disponível pelo `useOutletContext`, acrescentar:

```js
  // A lista é da empresa escolhida (cada empresa tem o seu "Excel").
  const CATEGORIAS = categoriasDaEmpresa(selectedCompany);
```

E substituir cada uso de `CATEGORIAS.map((c) => ...)` por `CATEGORIAS.map((c) => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)`, e cada `categoriaLabel(v)` por `categoriaLabel(CATEGORIAS, v)`.

- [ ] **Step 2: O mesmo no Relatórios**

Em `FinRelatorios.js`, apagar o `const CAT_LABEL = {...}` (linhas 35-39) e acrescentar ao import de `../../../lib/finance`: `categoriasDaEmpresa, categoriaLabel`. Dentro do componente:

```js
  const CATEGORIAS = categoriasDaEmpresa(selectedCompany);
```

E na linha 303, trocar:

```js
                        <Row key={cat} label={CAT_LABEL[cat] || cat} value={eur(-Math.abs(val))} muted />
```

por:

```js
                        <Row key={cat} label={cat === 'sem_categoria' ? 'Sem categoria' : categoriaLabel(CATEGORIAS, cat)} value={eur(-Math.abs(val))} muted />
```

- [ ] **Step 3: Confirmar que não ficou nenhuma cópia**

```bash
cd ~/Developer/RH && grep -rn "mercadoria\|energia_agua\|CAT_LABEL" frontend/src/ --include="*.js" | grep -v node_modules | grep -v ".test.js"
```

Esperado: **zero linhas**. Se aparecer alguma, é uma cópia por extrair.

- [ ] **Step 4: Compilar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully` (avisos de lint são aceitáveis; erros não).

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro/FinPagamentos.js frontend/src/pages/admin/financeiro/FinRelatorios.js && git commit -m "Pagamentos e Relatórios passam a ler a lista da empresa

As duas cópias escritas à mão desapareceram. A categoria de uma fatura passa
a ser escolhida da lista da empresa a que a fatura pertence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Editor de categorias em Configurações

**Files:**
- Modify: `frontend/src/pages/admin/financeiro/FinInicio.js`

**Interfaces:**
- Consumes: `updateFinCompany` (api.js, já existe), `categoriasDaEmpresa`, `CATEGORIAS_PADRAO`.
- Produces: nada para outras tasks.

- [ ] **Step 1: Estado e diálogo**

Em `FinInicio.js`, acrescentar aos imports:

```js
import { categoriasDaEmpresa, CATEGORIAS_PADRAO } from '../../../lib/finance';
import { Plus, Trash2 } from 'lucide-react';
```

(se `Plus`/`Trash2` já estiverem importados, não duplicar) e ao estado do componente:

```js
  // Dialog categorias
  const [catsDialog, setCatsDialog] = useState(false);
  const [catsCompany, setCatsCompany] = useState(null);
  const [cats, setCats] = useState([]);

  const openCatsDialog = (company) => {
    setCatsCompany(company);
    setCats(categoriasDaEmpresa(company).map((c) => ({ ...c })));
    setCatsDialog(true);
  };

  const idDaEtiqueta = (label) =>
    label.toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');

  const saveCats = async () => {
    const limpas = cats
      .map((c) => ({ id: (c.id || idDaEtiqueta(c.label || '')), label: (c.label || '').trim() }))
      .filter((c) => c.id && c.label);
    if (!limpas.length) {
      toast.error('A empresa precisa de pelo menos uma categoria.');
      return;
    }
    try {
      await updateFinCompany(catsCompany.id, {
        name: catsCompany.name, nif: catsCompany.nif, categorias: limpas,
      });
      toast.success('Categorias guardadas.');
      setCatsDialog(false);
      fetchAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
    }
  };
```

- [ ] **Step 2: Botão na linha da empresa**

Ao lado do botão de editar empresa (por volta da linha 251), acrescentar:

```jsx
                            <Button variant="ghost" size="icon" title="Categorias"
                              onClick={() => openCatsDialog(company)}
                              data-testid={`fin-cats-${company.id}`}>
                              <Tags className="h-4 w-4" />
                            </Button>
```

e `Tags` ao import de `lucide-react`.

- [ ] **Step 3: O diálogo**

A seguir ao diálogo de empresa que já existe:

```jsx
      {/* Dialog categorias da empresa */}
      <Dialog open={catsDialog} onOpenChange={setCatsDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Categorias · {catsCompany?.name}</DialogTitle>
            <DialogDescription>
              Estas categorias são usadas na Conciliação e no relatório de Resultados.
              Cada empresa tem as suas.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {cats.map((c, i) => (
              <div key={c.id || i} className="flex items-center gap-2">
                <Input value={c.label}
                  onChange={(e) => setCats(cats.map((x, j) => j === i ? { ...x, label: e.target.value } : x))}
                  data-testid={`fin-cat-input-${i}`} />
                <Button variant="ghost" size="icon" title="Remover"
                  onClick={() => setCats(cats.filter((_, j) => j !== i))}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            ))}
          </div>
          <Button variant="outline" size="sm" onClick={() => setCats([...cats, { id: '', label: '' }])}
            data-testid="fin-cat-add">
            <Plus className="h-4 w-4 mr-2" />Acrescentar categoria
          </Button>
          <p className="text-xs text-muted-foreground">
            Mudar o nome de uma categoria não desclassifica nada: as linhas já
            classificadas continuam nela. Remover uma categoria deixa as linhas
            dela a mostrar a chave antiga — reclassifica-as antes.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCats(CATEGORIAS_PADRAO.map((c) => ({ ...c })))}>
              Repor a lista de origem
            </Button>
            <Button onClick={saveCats} data-testid="fin-cats-save">Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 4: Compilar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully`.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro/FinInicio.js && git commit -m "Editor de categorias por empresa em Configurações

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Categoria, descrição e anotação no movimento

**Files:**
- Modify: `backend/server.py` (modelo novo junto a `FinMovementTitle`, linha 4565; endpoint novo a seguir ao `set-title`, linha 4759)
- Modify: `frontend/src/lib/api.js:233`
- Test: `backend/tests/fin/test_os_campos_do_movimento.py` (criar)

**Interfaces:**
- Consumes: `_fin_categorias_da_empresa` (Task 2), `fin_require_editor`.
- Produces: `PUT /api/fin/movements/{id}` que aceita `{title?, category?, note?}` e devolve o movimento; wrapper `updateFinMovement(id, campos)`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/fin/test_os_campos_do_movimento.py`:

```python
"""**Um campo que não vem no pedido não pode ser apagado.**

A tabela da Conciliação guarda campo a campo: mudar a categoria manda só a
categoria. Se o endpoint escrevesse sempre os três campos, escolher uma
categoria apagava a anotação que a diretora financeira acabou de escrever ao
lado — e ninguém ligaria as duas coisas.

E a categoria tem de ser da lista DA EMPRESA: aceitar texto livre é como não
ter lista nenhuma, e os cartões de resumo passam a somar categorias que não
existem em sítio nenhum.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados):
        self.guardados = [dict(d) for d in guardados]
        self.updates = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        self.updates.append(update)
        for doc in self.guardados:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, movimentos, empresas):
        self.fin_movements = movimentos
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def _base(monkeypatch, mv_extra=None):
    mv = {"id": "m1", "company_id": "e1", "amount": -10.0,
          "title": "MAKRO", "note": "combinado com a Rafaela", "category": None}
    mv.update(mv_extra or {})
    movimentos = ColeccaoFalsa([mv])
    empresas = ColeccaoFalsa([{"id": "e1", "categorias": [{"id": "supermercado", "label": "Supermercado"}]}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos, empresas))
    return movimentos


def test_mudar_so_a_categoria_nao_apaga_a_anotacao(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementFields(category="supermercado")
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    escrito = movimentos.updates[0]["$set"]
    assert escrito == {"category": "supermercado"}, (
        "o endpoint escreveu campos que ninguém enviou — isto apaga a anotação "
        "de quem só mudou a categoria"
    )
    assert movimentos.guardados[0]["note"] == "combinado com a Rafaela"


def test_uma_anotacao_vazia_limpa_a_anotacao(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementFields(note="")
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    assert movimentos.guardados[0]["note"] is None


def test_uma_categoria_fora_da_lista_da_empresa_e_recusada(monkeypatch, sem_permissoes):
    _base(monkeypatch)

    payload = server.FinMovementFields(category="criptomoedas")
    with pytest.raises(HTTPException) as erro:
        _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))
    assert erro.value.status_code == 400


def test_limpar_a_categoria_e_sempre_permitido(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch, {"category": "supermercado"})

    payload = server.FinMovementFields(category=None)
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    assert movimentos.guardados[0]["category"] is None
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_os_campos_do_movimento.py -q
```

Esperado: FAIL — `module 'server' has no attribute 'FinMovementFields'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `backend/server.py`, a seguir a `class FinMovementTitle` (linha 4565):

```python
class FinMovementFields(BaseModel):
    """Campos que a Conciliação edita célula a célula. Todos opcionais: o que
    não vier no pedido não é escrito (ver `exclude_unset` no endpoint)."""
    title: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None
```

E a seguir ao `fin_set_movement_title` (que acaba na linha 4759):

```python
@api_router.put("/fin/movements/{movement_id}")
async def fin_update_movement(movement_id: str, payload: FinMovementFields, current_user: dict = Depends(get_current_user)):
    """Descrição, categoria e anotação do movimento (a tabela da Conciliação).
    Só escreve os campos que vierem MESMO no pedido."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    enviados = payload.model_dump(exclude_unset=True)
    campos = {}
    if "title" in enviados:
        campos["title"] = (payload.title or "").strip() or None
    if "note" in enviados:
        campos["note"] = (payload.note or "").strip() or None
    if "category" in enviados:
        cat = (payload.category or "").strip() or None
        if cat:
            validas = {c["id"] for c in await _fin_categorias_da_empresa(mv["company_id"])}
            if cat not in validas:
                raise HTTPException(status_code=400, detail="Categoria fora da lista da empresa.")
        campos["category"] = cat
    if campos:
        await db.fin_movements.update_one({"id": movement_id}, {"$set": campos})
    return await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
```

Em `frontend/src/lib/api.js`, a seguir a `setFinMovementTitle` (linha 233):

```js
// Conciliação: guarda campo a campo (o que não for enviado não é tocado).
export const updateFinMovement = (id, campos) =>
  axios.put(`${API_URL}/fin/movements/${id}`, campos);
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_os_campos_do_movimento.py -q && ./.venv/bin/python -m pytest -q
```

Esperado: 4 passed; total **2833 passed**.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py backend/tests/fin/test_os_campos_do_movimento.py frontend/src/lib/api.js && git commit -m "Categoria, descrição e anotação no movimento

Guarda campo a campo: mudar a categoria não apaga a anotação ao lado. A
categoria tem de ser da lista da empresa — texto livre é como não ter lista.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Linhas escritas à mão

**Files:**
- Modify: `backend/server.py` (modelo junto a `FinMovementFields`; endpoints a seguir ao `fin_update_movement`)
- Modify: `frontend/src/lib/api.js`
- Test: `backend/tests/fin/test_a_linha_manual_nao_finge_saldo.py`, `backend/tests/fin/test_so_se_apaga_uma_linha_manual.py`

**Interfaces:**
- Consumes: `_fin_categorias_da_empresa`, `_fin_clean_num`, `fin_require_editor`.
- Produces: `POST /api/fin/movements` → documento com `manual: True`, `source: "manual"`, sem `balance` e sem `dedup_key`; `DELETE /api/fin/movements/{id}`; wrappers `createFinMovement(data)`, `deleteFinMovement(id)`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/fin/test_a_linha_manual_nao_finge_saldo.py`:

```python
"""**Uma linha escrita à mão não pode fingir que passou no banco.**

O saldo de cada conta é o `balance` do último movimento. Se uma linha manual
gravasse `balance`, o cartão "Valor Contas" passava a mostrar um saldo que o
banco nunca disse — e é esse número que a diretora financeira usa para decidir
o que pode pagar.

E não pode ter `dedup_key`: o dedup do importador procura por essa chave, e uma
linha manual a partilhá-la faria o extrato a sério ser descartado como repetido.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados=None):
        self.guardados = [dict(d) for d in (guardados or [])]
        self.inseridos = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc):
        self.inseridos.append(doc)
        self.guardados.append(dict(doc))


class BaseFalsa:
    def __init__(self, movimentos, empresas):
        self.fin_movements = movimentos
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def _base(monkeypatch):
    movimentos = ColeccaoFalsa()
    empresas = ColeccaoFalsa([{"id": "e1", "categorias": [{"id": "entradas", "label": "Entradas"}]}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos, empresas))
    return movimentos


def test_a_linha_manual_nao_grava_saldo(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementCreate(
        company_id="e1", date_lancamento="2026-09-01",
        description="Dinheiro Restante Mês Anterior", amount=1104.97, category="entradas",
    )
    _corre(server.fin_create_movement(payload, {"user_id": "u1"}))

    doc = movimentos.inseridos[0]
    assert doc.get("balance") is None
    assert "dedup_key" not in doc
    assert doc["manual"] is True
    assert doc["source"] == "manual"
    assert doc["account_id"] is None


def test_a_linha_manual_aceita_montante_negativo(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementCreate(
        company_id="e1", date_lancamento="2026-09-01", description="Ajuste", amount=-50.0,
    )
    _corre(server.fin_create_movement(payload, {"user_id": "u1"}))

    assert movimentos.inseridos[0]["amount"] == -50.0
```

Criar `backend/tests/fin/test_so_se_apaga_uma_linha_manual.py`:

```python
"""**O DELETE não pode apagar um movimento do banco.**

A tabela da Conciliação tem um caixote do lixo por linha. Se ele apagasse
movimentos importados do extrato, um clique enganado tirava dinheiro real do
sistema — e o importador não o traz de volta, porque o dedup vê o `dedup_key`
antigo... que já não existe. O extrato é para reimportar, não para apagar.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados):
        self.guardados = [dict(d) for d in guardados]
        self.apagados = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def delete_one(self, filtro):
        self.apagados.append(filtro)


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def test_apagar_um_movimento_do_banco_e_recusado(monkeypatch, sem_permissoes):
    movimentos = ColeccaoFalsa([
        {"id": "m1", "company_id": "e1", "source": "bank_import", "manual": False},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    with pytest.raises(HTTPException) as erro:
        _corre(server.fin_delete_movement("m1", {"user_id": "u1"}))

    assert erro.value.status_code == 400
    assert movimentos.apagados == []


def test_apagar_uma_linha_manual_e_permitido(monkeypatch, sem_permissoes):
    movimentos = ColeccaoFalsa([
        {"id": "m2", "company_id": "e1", "source": "manual", "manual": True},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    _corre(server.fin_delete_movement("m2", {"user_id": "u1"}))

    assert movimentos.apagados == [{"id": "m2"}]


def test_um_movimento_antigo_sem_o_campo_manual_nao_se_apaga(monkeypatch, sem_permissoes):
    # Todos os movimentos importados antes desta obra não têm o campo. A
    # ausência tem de valer "não é manual", nunca o contrário.
    movimentos = ColeccaoFalsa([{"id": "m3", "company_id": "e1", "source": "bank_pdf"}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    with pytest.raises(HTTPException):
        _corre(server.fin_delete_movement("m3", {"user_id": "u1"}))
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_a_linha_manual_nao_finge_saldo.py tests/fin/test_so_se_apaga_uma_linha_manual.py -q
```

Esperado: FAIL — `module 'server' has no attribute 'FinMovementCreate'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `backend/server.py`, a seguir a `class FinMovementFields`:

```python
class FinMovementCreate(BaseModel):
    """Linha escrita à mão na Conciliação (ex.: 'Dinheiro Restante Mês Anterior')."""
    company_id: str
    date_lancamento: str
    description: Optional[str] = None
    amount: float
    category: Optional[str] = None
    note: Optional[str] = None
```

E a seguir ao `fin_update_movement`:

```python
@api_router.post("/fin/movements")
async def fin_create_movement(payload: FinMovementCreate, current_user: dict = Depends(get_current_user)):
    """Linha à mão. Não tem conta, não tem saldo e não tem dedup_key: não passou
    no banco, e o cartão de saldo e o importador não a podem confundir com quem
    passou."""
    await fin_require_editor(payload.company_id, current_user)
    data = (payload.date_lancamento or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        raise HTTPException(status_code=400, detail="Data inválida (aaaa-mm-dd).")
    amt = _fin_clean_num(payload.amount)
    if amt is None:
        raise HTTPException(status_code=400, detail="Montante inválido.")
    cat = (payload.category or "").strip() or None
    if cat:
        validas = {c["id"] for c in await _fin_categorias_da_empresa(payload.company_id)}
        if cat not in validas:
            raise HTTPException(status_code=400, detail="Categoria fora da lista da empresa.")
    doc = {
        "id": str(uuid.uuid4()),
        "account_id": None,
        "company_id": payload.company_id,
        "date_lancamento": data,
        "date_valor": None,
        "description": (payload.description or "").strip() or None,
        "amount": amt,
        "balance": None,
        "currency": "EUR",
        "title": None,
        "category": cat,
        "note": (payload.note or "").strip() or None,
        "invoice_id": None,
        "link_auto": False,
        "attachment_path": None,
        "manual": True,
        "source": "manual",
        "created_by": current_user["user_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.fin_movements.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api_router.delete("/fin/movements/{movement_id}")
async def fin_delete_movement(movement_id: str, current_user: dict = Depends(get_current_user)):
    """Apaga uma linha escrita à mão. Movimentos do banco NÃO se apagam — o
    extrato é para reimportar, e apagar um deixava-o irrecuperável pelo dedup."""
    mv = await db.fin_movements.find_one({"id": movement_id}, {"_id": 0})
    if not mv:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    await fin_require_editor(mv["company_id"], current_user)
    if not mv.get("manual"):
        raise HTTPException(status_code=400, detail="Só se apagam linhas escritas à mão.")
    await db.fin_movements.delete_one({"id": movement_id})
    return {"message": "Linha apagada."}
```

Em `frontend/src/lib/api.js`, a seguir a `updateFinMovement`:

```js
export const createFinMovement = (data) => axios.post(`${API_URL}/fin/movements`, data);
export const deleteFinMovement = (id) => axios.delete(`${API_URL}/fin/movements/${id}`);
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/ -q && ./.venv/bin/python -m pytest -q
```

Esperado: os 5 novos passam; total **2838 passed**.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py backend/tests/fin/test_a_linha_manual_nao_finge_saldo.py backend/tests/fin/test_so_se_apaga_uma_linha_manual.py frontend/src/lib/api.js && git commit -m "Linhas escritas à mão na Conciliação

Sem conta, sem saldo e sem dedup_key: não passaram no banco e nem o cartão de
saldo nem o importador as podem confundir com quem passou. Só estas se apagam.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: O saldo de cada banco

**Files:**
- Modify: `backend/server.py` (endpoint a seguir ao `fin_upsert_bank_account`, linha 4648)
- Modify: `frontend/src/lib/api.js`
- Test: `backend/tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py`

**Interfaces:**
- Consumes: `_fin_report_scope`, `_fin_num`.
- Produces: `GET /api/fin/bank-accounts/balances?company_id` → `{"contas": [{account_id, company_id, bank, name, account_number, balance, date}], "total": float}`; wrapper `getFinBankBalances(companyId)`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py`:

```python
"""**O saldo de uma conta é o do ÚLTIMO movimento, e "último" tem regra.**

Num dia com vários movimentos na mesma conta, a data não chega para desempatar.
O painel já resolve isto com `sort=[("date_lancamento", -1), ("_id", -1)]` — a
ordem de inserção do extrato. É por isso que este cálculo não pode ser feito no
browser: o `_id` vem excluído de todas as projeções e o frontend não consegue
reproduzir o desempate; mostraria um saldo arbitrário do dia.

E uma linha escrita à mão não tem saldo nenhum — não pode ser escolhida como o
último movimento, senão o cartão passa a mostrar `None` como se fosse 0.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ContasFalsas:
    def __init__(self, guardadas):
        self.guardadas = [dict(d) for d in guardadas]

    def find(self, filtro, proj=None):
        docs = [dict(d) for d in self.guardadas
                if d.get("company_id") == filtro.get("company_id")]
        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()


class MovimentosFalsos:
    """Guarda a ordenação pedida e responde-lhe a sério (ordem de inserção como
    substituto honesto do _id)."""

    def __init__(self, guardados):
        self.guardados = [dict(d, _ordem=i) for i, d in enumerate(guardados)]
        self.sorts = []

    async def find_one(self, filtro, proj=None, sort=None):
        self.sorts.append(sort)
        candidatos = []
        for doc in self.guardados:
            ok = True
            for campo, esperado in filtro.items():
                valor = doc.get(campo)
                if isinstance(esperado, dict) and "$ne" in esperado:
                    if valor == esperado["$ne"]:
                        ok = False
                elif valor != esperado:
                    ok = False
            if ok:
                candidatos.append(doc)
        if not candidatos:
            return None
        for campo, direccao in reversed(sort or []):
            chave = "_ordem" if campo == "_id" else campo
            candidatos.sort(key=lambda d: (d.get(chave) is None, d.get(chave)),
                            reverse=(direccao == -1))
        return dict(candidatos[0])


class BaseFalsa:
    def __init__(self, contas, movimentos):
        self.fin_bank_accounts = contas
        self.fin_movements = movimentos


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def scope(company_id, current_user):
        return company_id
    monkeypatch.setattr(server, "_fin_report_scope", scope)


def test_no_mesmo_dia_ganha_o_ultimo_inserido(monkeypatch, sem_permissoes):
    contas = ContasFalsas([{"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"}])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": 100.0},
        {"id": "m2", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": 3192.91},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    assert movimentos.sorts[0] == [("date_lancamento", -1), ("_id", -1)], (
        "sem o desempate por _id o saldo do dia sai arbitrário"
    )
    assert res["contas"][0]["balance"] == 3192.91


def test_uma_linha_a_mao_nunca_e_o_saldo(monkeypatch, sem_permissoes):
    contas = ContasFalsas([{"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"}])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-01", "balance": 3192.91},
        {"id": "m2", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": None, "manual": True},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    assert res["contas"][0]["balance"] == 3192.91


def test_uma_conta_sem_movimentos_diz_nao_sei_e_nao_zero(monkeypatch, sem_permissoes):
    contas = ContasFalsas([
        {"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"},
        {"id": "c2", "company_id": "e1", "bank": "Revolut", "name": "Revolut"},
    ])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-01", "balance": 3192.91},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    por_nome = {c["name"]: c for c in res["contas"]}
    assert por_nome["Revolut"]["balance"] is None, "desconhecido não é zero"
    assert res["total"] == 3192.91
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py -q
```

Esperado: FAIL — `module 'server' has no attribute 'fin_bank_account_balances'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `backend/server.py`, a seguir ao `fin_upsert_bank_account` (acaba na linha 4648, antes do comentário `# ---------- Movimentos ----------`):

```python
@api_router.get("/fin/bank-accounts/balances")
async def fin_bank_account_balances(company_id: str, current_user: dict = Depends(get_current_user)):
    """Saldo de CADA conta (o cartão "Valor Contas" da Conciliação).

    Não pode ser feito no frontend: o desempate intra-dia é por `_id` (ordem de
    inserção do extrato) e o `_id` vem excluído de todas as projeções, por isso
    o browser mostraria um movimento arbitrário do dia."""
    scope = await _fin_report_scope(company_id, current_user)
    accounts = await db.fin_bank_accounts.find({"company_id": scope}, {"_id": 0}).to_list(2000)
    contas = []
    for acc in accounts:
        last = await db.fin_movements.find_one(
            {"account_id": acc.get("id"), "balance": {"$ne": None}},
            {"_id": 0, "balance": 1, "date_lancamento": 1},
            sort=[("date_lancamento", -1), ("_id", -1)],
        )
        contas.append({
            "account_id": acc.get("id"),
            "company_id": acc.get("company_id"),
            "bank": acc.get("bank"),
            "name": acc.get("name") or acc.get("bank"),
            "account_number": acc.get("account_number"),
            # None = não sabemos (conta sem movimentos). Nunca 0.
            "balance": _fin_num(last.get("balance")) if last else None,
            "date": last.get("date_lancamento") if last else None,
        })
    contas.sort(key=lambda c: (c.get("name") or "").lower())
    total = round(sum(c["balance"] for c in contas if c["balance"] is not None), 2)
    return {"contas": contas, "total": total}
```

Em `frontend/src/lib/api.js`, a seguir a `getFinBankAccounts`:

```js
// Saldo de cada conta (cartão "Valor Contas" da Conciliação).
export const getFinBankBalances = (companyId) =>
  axios.get(`${API_URL}/fin/bank-accounts/balances`, { params: { company_id: companyId } });
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py -q && ./.venv/bin/python -m pytest -q
```

Esperado: 3 passed; total **2841 passed**.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py backend/tests/fin/test_o_saldo_por_conta_desempata_pelo_id.py frontend/src/lib/api.js && git commit -m "Saldo de cada banco, com o desempate certo

O saldo é o do último movimento, e no mesmo dia desempata-se por _id — que o
browser não vê. Uma conta sem movimentos diz \"não sei\", não diz zero.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Índices, e a tranca que não pode voltar

`fin_movements` não tem um único índice, e a vista mensal varre a coleção inteira. E o anexo em movimentos de entrada tem de continuar a funcionar: hoje a proibição é só do lado do ecrã, e um teste impede que alguém a leve para o servidor.

**Files:**
- Modify: `backend/server.py:8971-8977` (bloco `create_index`)
- Test: `backend/tests/fin/test_anexar_num_movimento_de_entrada.py`

**Interfaces:**
- Consumes: nada.
- Produces: nada.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/fin/test_anexar_num_movimento_de_entrada.py`:

```python
"""**Uma ENTRADA também tem direito a documento.**

No Extrato, o botão de anexar e o de ligar fatura só aparecem em movimentos com
`amount < 0`. A Conciliação mostra o mês inteiro, e metade do que interessa à
diretora financeira são entradas: Glovo, Uber, fecho de TPA. Se alguém levar a
regra do ecrã para o servidor, essas linhas ficam sem forma de guardar o
comprovativo.

Este teste existe para essa regra nunca lá chegar.
"""
import asyncio
import io
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados):
        self.guardados = [dict(d) for d in guardados]

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        for doc in self.guardados:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


class FicheiroFalso:
    """O mínimo do UploadFile que o endpoint usa: só o `.file`."""
    def __init__(self, dados=b"%PDF-1.4 teste"):
        self.file = io.BytesIO(dados)
        self.filename = "comprovativo.pdf"


def test_anexar_a_uma_entrada_do_glovo_funciona(monkeypatch, tmp_path):
    movimentos = ColeccaoFalsa([
        {"id": "m1", "company_id": "e1", "amount": 3633.00, "description": "Glovo"},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))
    monkeypatch.setattr(server, "UPLOAD_DIR", tmp_path)

    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)

    _corre(server.fin_attach_movement("m1", FicheiroFalso(), {"user_id": "u1"}))

    assert movimentos.guardados[0]["attachment_path"], (
        "o anexo foi recusado numa entrada — a regra do ecrã chegou ao servidor"
    )
    assert (tmp_path / "fin_movements" / "m1.pdf").exists()
```

- [ ] **Step 2: Correr e ver o estado actual**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_anexar_num_movimento_de_entrada.py -q
```

Esperado: **PASS** — o servidor hoje não tem a tranca. Este teste é uma cerca, não uma correcção: se falhar, alguém já lá pôs a regra e há que a tirar.

- [ ] **Step 3: Acrescentar os índices**

Em `backend/server.py`, dentro do `try:` do arranque (linha 8971), acrescentar a seguir às linhas de `fin_sales`:

```python
        # A vista mensal da Conciliação filtra por empresa + mês, e o saldo por
        # conta procura o último movimento de cada conta. Sem índice, as duas
        # varrem a coleção inteira.
        await db.fin_movements.create_index([("company_id", 1), ("date_lancamento", -1)])
        await db.fin_movements.create_index([("account_id", 1), ("date_lancamento", -1)])
        await db.fin_movements.create_index([("invoice_id", 1)])
```

- [ ] **Step 4: Correr a suite toda**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest -q
```

Esperado: **2842 passed**.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py backend/tests/fin/test_anexar_num_movimento_de_entrada.py && git commit -m "Índices em fin_movements, e uma cerca para as entradas

A coleção não tinha índice nenhum. E fica um teste a impedir que a regra do
ecrã (só saídas têm documento) alguma vez chegue ao servidor.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: A aritmética dos cartões

Os cartões calculam-se no ecrã. Para terem teste, a aritmética sai do componente.

**Files:**
- Create: `frontend/src/lib/conciliacao.js`
- Test: `frontend/src/lib/conciliacao.test.js`

**Interfaces:**
- Consumes: nada (recebe as categorias por argumento).
- Produces:
  - `descricaoDoMovimento(mv): string`
  - `resumoPorCategoria(movimentos, categorias): {id, label, total}[]` — `total` **com sinal**
  - `percentagensSobreEntradas(linhas): {id, label, pct}[]` — `pct` é `null` quando não há entradas
  - `plataformasDasEntradas(movimentos): {nome, total}[]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `frontend/src/lib/conciliacao.test.js`:

```js
import {
  descricaoDoMovimento, resumoPorCategoria,
  percentagensSobreEntradas, plataformasDasEntradas,
} from './conciliacao';

const CATS = [
  { id: 'entradas', label: 'Entradas' },
  { id: 'fornecedor', label: 'Fornecedor' },
  { id: 'supermercado', label: 'Supermercado' },
  { id: 'salarios', label: 'Salários' },
];

describe('descrição do movimento', () => {
  test('o que a diretora financeira escreveu ganha ao texto do banco', () => {
    expect(descricaoDoMovimento({ title: 'MAKRO', description: 'COMPRA 4512 MAKRO CASH' })).toBe('MAKRO');
  });
  test('sem reescrita, fica o texto do banco', () => {
    expect(descricaoDoMovimento({ description: 'COMPRA 4512' })).toBe('COMPRA 4512');
  });
  test('sem nada, não fica em branco', () => {
    expect(descricaoDoMovimento({})).toBe('(sem descrição)');
  });
});

describe('resumo por categoria', () => {
  const MOVS = [
    { category: 'entradas', amount: 3633.0 },
    { category: 'entradas', amount: 2460.92 },
    { category: 'fornecedor', amount: -2268.91 },
    { category: 'supermercado', amount: -65.8 },
  ];

  test('soma por categoria e guarda o SINAL', () => {
    const linhas = resumoPorCategoria(MOVS, CATS);
    const porId = Object.fromEntries(linhas.map((l) => [l.id, l.total]));
    expect(porId.entradas).toBeCloseTo(6093.92, 2);
    expect(porId.fornecedor).toBeCloseTo(-2268.91, 2);
  });

  test('uma categoria sem movimentos aparece a zero, como no Excel', () => {
    const linhas = resumoPorCategoria(MOVS, CATS);
    expect(linhas.find((l) => l.id === 'salarios').total).toBe(0);
  });

  test('a ordem é a da lista da empresa', () => {
    expect(resumoPorCategoria(MOVS, CATS).slice(0, 4).map((l) => l.id))
      .toEqual(['entradas', 'fornecedor', 'supermercado', 'salarios']);
  });

  test('o que está por classificar não desaparece nem se cala', () => {
    const linhas = resumoPorCategoria([{ amount: -10 }], CATS);
    const sem = linhas.find((l) => l.id === 'sem_categoria');
    expect(sem.total).toBe(-10);
    expect(sem.label).toBe('Sem categoria');
  });

  test('uma categoria legada fora da lista aparece com a chave crua', () => {
    const linhas = resumoPorCategoria([{ category: 'mercadoria', amount: -5 }], CATS);
    expect(linhas.find((l) => l.id === 'mercadoria').total).toBe(-5);
  });
});

describe('percentagens sobre as entradas', () => {
  test('cada categoria a dividir pelas entradas, em valor absoluto', () => {
    const linhas = resumoPorCategoria([
      { category: 'entradas', amount: 7630.69 },
      { category: 'supermercado', amount: -135.84 },
    ], CATS);
    const pcts = percentagensSobreEntradas(linhas);
    expect(pcts.find((p) => p.id === 'supermercado').pct).toBeCloseTo(1.78, 2);
  });

  test('as entradas não aparecem a dividir-se por si próprias', () => {
    const linhas = resumoPorCategoria([{ category: 'entradas', amount: 100 }], CATS);
    expect(percentagensSobreEntradas(linhas).find((p) => p.id === 'entradas')).toBeUndefined();
  });

  test('sem entradas, a percentagem é desconhecida — não é zero', () => {
    const linhas = resumoPorCategoria([{ category: 'supermercado', amount: -50 }], CATS);
    expect(percentagensSobreEntradas(linhas).find((p) => p.id === 'supermercado').pct).toBeNull();
  });
});

describe('plataformas', () => {
  test('agrupa as entradas pela descrição e ordena pela maior', () => {
    const plats = plataformasDasEntradas([
      { category: 'entradas', title: 'Glovo', amount: 3633.0 },
      { category: 'entradas', title: 'Fecho TPA Teya', amount: 2460.92 },
      { category: 'entradas', title: 'Glovo', amount: 100.0 },
      { category: 'fornecedor', title: 'Glovo', amount: -50.0 },
    ]);
    expect(plats).toEqual([
      { nome: 'Glovo', total: 3733.0 },
      { nome: 'Fecho TPA Teya', total: 2460.92 },
    ]);
  });
});
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn test --watchAll=false src/lib/conciliacao.test.js
```

Esperado: FAIL — `Cannot find module './conciliacao'`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Criar `frontend/src/lib/conciliacao.js`:

```js
// Aritmética dos cartões da Conciliação. Sem React e sem HTTP de propósito:
// é a parte que tem de estar certa ao cêntimo, e assim tem teste.

export const descricaoDoMovimento = (mv) =>
  (mv && (mv.title || mv.description)) || '(sem descrição)';

// Soma por categoria, na ordem da lista da empresa. O total mantém o SINAL
// (entradas positivas, despesas negativas): quem mostra é que decide se põe o
// valor absoluto, como no Excel.
export const resumoPorCategoria = (movimentos, categorias) => {
  const somas = new Map();
  for (const mv of movimentos || []) {
    const id = mv.category || 'sem_categoria';
    somas.set(id, (somas.get(id) || 0) + (Number(mv.amount) || 0));
  }
  const conhecidas = new Set((categorias || []).map((c) => c.id));
  const linhas = (categorias || []).map((c) => ({
    id: c.id, label: c.label, total: somas.get(c.id) || 0,
  }));
  // Categorias legadas e o que está por classificar entram no fim. Não se
  // escondem: são exatamente o trabalho que falta fazer.
  for (const [id, total] of somas) {
    if (conhecidas.has(id)) continue;
    linhas.push({ id, label: id === 'sem_categoria' ? 'Sem categoria' : id, total });
  }
  return linhas;
};

// Cada categoria em % das Entradas. `pct` é null quando não há entradas —
// desconhecido não é zero.
export const percentagensSobreEntradas = (linhas) => {
  const entradas = (linhas || []).find((l) => l.id === 'entradas');
  const base = Math.abs((entradas && entradas.total) || 0);
  return (linhas || [])
    .filter((l) => l.id !== 'entradas')
    .map((l) => ({
      id: l.id, label: l.label,
      pct: base ? (Math.abs(l.total) / base) * 100 : null,
    }));
};

// O cartão "Plataformas" do Excel: as entradas agrupadas pela descrição que
// ela própria escreveu ("Glovo", "Fecho TPA Teya"). Sem campo novo nenhum.
export const plataformasDasEntradas = (movimentos) => {
  const somas = new Map();
  for (const mv of movimentos || []) {
    if (mv.category !== 'entradas') continue;
    const nome = descricaoDoMovimento(mv);
    somas.set(nome, (somas.get(nome) || 0) + (Number(mv.amount) || 0));
  }
  return [...somas.entries()]
    .map(([nome, total]) => ({ nome, total: Math.round(total * 100) / 100 }))
    .sort((a, b) => b.total - a.total);
};
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn test --watchAll=false src/lib/conciliacao.test.js
```

Esperado: PASS, 11 testes.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/lib/conciliacao.js frontend/src/lib/conciliacao.test.js && git commit -m "A aritmética dos cartões da Conciliação, com teste

Fora do componente de propósito: é a parte que tem de estar certa ao cêntimo.
Sem entradas, a percentagem é desconhecida — não é zero.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: A página e a tabela mensal

**Files:**
- Create: `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js`
- Create: `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoTabela.js`
- Modify: `frontend/src/App.js:32` (import) e `:230` (rota)
- Modify: `frontend/src/components/layouts/AdminLayout.js:113`

**Interfaces:**
- Consumes: `getFinMovements`, `updateFinMovement`, `createFinMovement`, `deleteFinMovement` (api.js), `categoriasDaEmpresa`, `categoriaLabel`, `eur`, `fmtDate`, `descricaoDoMovimento`.
- Produces: componente `ConciliacaoTabela({ movimentos, categorias, podeEditar, aoGuardar, aoApagar, aoAbrirFaturas })`.

- [ ] **Step 1: A entrada no menu e a rota**

Em `AdminLayout.js`, a seguir à linha 113 (`Extrato`):

```js
      { path: '/admin/financeiro/conciliacao', label: 'Conciliação', icon: Scale },
```

e `Scale` ao import de `lucide-react` no topo do ficheiro.

Em `App.js`, a seguir à linha 32:

```js
import FinConciliacao from './pages/admin/financeiro/conciliacao/FinConciliacao';
```

e a seguir à linha 230:

```jsx
        <Route path="financeiro/conciliacao" element={<FinConciliacao />} />
```

- [ ] **Step 2: A tabela**

Criar `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoTabela.js`:

```jsx
import React, { useState } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../../components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../../components/ui/select';
import { Input } from '../../../../components/ui/input';
import { Button } from '../../../../components/ui/button';
import { Badge } from '../../../../components/ui/badge';
import { Paperclip, Link2, Trash2, Pencil } from 'lucide-react';
import { eur, fmtDate } from '../../../../lib/finance';
import { descricaoDoMovimento } from '../../../../lib/conciliacao';

const SEM_CATEGORIA = '__sem__';

// Célula de texto que só vira campo quando se clica nela (mesmo gesto da
// justificação no Extrato).
function CelulaTexto({ valor, placeholder, podeEditar, aoGuardar, testid }) {
  const [aEditar, setAEditar] = useState(false);
  const [texto, setTexto] = useState(valor || '');
  if (!podeEditar) return <span className="text-sm">{valor || ''}</span>;
  if (!aEditar) {
    return (
      <button type="button" onClick={() => { setTexto(valor || ''); setAEditar(true); }}
        className="text-left text-sm hover:underline decoration-dotted w-full"
        data-testid={testid}>
        {valor || <span className="text-muted-foreground">{placeholder}</span>}
      </button>
    );
  }
  const fechar = () => { setAEditar(false); if ((valor || '') !== texto) aoGuardar(texto); };
  return (
    <Input autoFocus value={texto} className="h-8 text-sm"
      onChange={(e) => setTexto(e.target.value)}
      onBlur={fechar}
      onKeyDown={(e) => {
        if (e.key === 'Enter') fechar();
        if (e.key === 'Escape') setAEditar(false);
      }} />
  );
}

export default function ConciliacaoTabela({ movimentos, categorias, podeEditar, aoGuardar, aoApagar, aoAbrirFaturas }) {
  if (!movimentos.length) {
    return <p className="text-center text-muted-foreground py-10">Sem movimentos neste mês.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">Data</TableHead>
            <TableHead className="w-40">Categoria</TableHead>
            <TableHead>Descrição</TableHead>
            <TableHead className="text-right w-32">Montante</TableHead>
            <TableHead className="w-44">Faturas</TableHead>
            <TableHead className="hidden lg:table-cell">Anotações</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {movimentos.map((mv) => (
            <TableRow key={mv.id} data-testid={`fin-conc-row-${mv.id}`}>
              <TableCell className="whitespace-nowrap text-sm">{fmtDate(mv.date_lancamento)}</TableCell>
              <TableCell>
                {podeEditar ? (
                  <Select value={mv.category || SEM_CATEGORIA}
                    onValueChange={(v) => aoGuardar(mv, { category: v === SEM_CATEGORIA ? null : v })}>
                    <SelectTrigger className="h-8 w-36 text-xs" data-testid={`fin-conc-cat-${mv.id}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={SEM_CATEGORIA}>Sem categoria</SelectItem>
                      {categorias.map((c) => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                ) : (
                  <span className="text-sm">{mv.category || '—'}</span>
                )}
              </TableCell>
              <TableCell>
                <CelulaTexto valor={mv.title} placeholder={descricaoDoMovimento(mv)} podeEditar={podeEditar}
                  testid={`fin-conc-desc-${mv.id}`}
                  aoGuardar={(t) => aoGuardar(mv, { title: t })} />
                {mv.manual && <Badge variant="outline" className="ml-2 text-[10px]">à mão</Badge>}
                {mv.title && mv.description && (
                  <p className="text-[11px] text-muted-foreground truncate">{mv.description}</p>
                )}
              </TableCell>
              <TableCell className={`text-right whitespace-nowrap tabular-nums ${
                (Number(mv.amount) || 0) < 0 ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>
                {eur(mv.amount)}
              </TableCell>
              <TableCell>
                <Button variant="ghost" size="sm" className="h-8 px-2"
                  onClick={() => aoAbrirFaturas(mv)} data-testid={`fin-conc-doc-${mv.id}`}>
                  {mv.invoice_id
                    ? <><Link2 className="h-3.5 w-3.5 mr-1 text-emerald-600" /><span className="text-xs">Ligada</span></>
                    : mv.attachment_path
                      ? <><Paperclip className="h-3.5 w-3.5 mr-1" /><span className="text-xs">Anexo</span></>
                      : <><Pencil className="h-3.5 w-3.5 mr-1 opacity-50" /><span className="text-xs text-muted-foreground">Ligar</span></>}
                </Button>
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <CelulaTexto valor={mv.note} placeholder="—" podeEditar={podeEditar}
                  testid={`fin-conc-nota-${mv.id}`}
                  aoGuardar={(t) => aoGuardar(mv, { note: t })} />
              </TableCell>
              <TableCell>
                {podeEditar && mv.manual && (
                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Apagar linha"
                    onClick={() => aoApagar(mv)} data-testid={`fin-conc-del-${mv.id}`}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 3: A página**

Criar `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js`:

```jsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { toast } from 'sonner';
import { Scale, Plus } from 'lucide-react';
import PageHeader from '../../../../components/PageHeader';
import MonthPicker from '../../../../components/MonthPicker';
import { Card, CardContent } from '../../../../components/ui/card';
import { Button } from '../../../../components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../../components/ui/tabs';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '../../../../components/ui/dialog';
import { Input } from '../../../../components/ui/input';
import { Label } from '../../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../../components/ui/select';
import {
  getFinMovements, updateFinMovement, createFinMovement, deleteFinMovement,
} from '../../../../lib/api';
import { categoriasDaEmpresa, todayISO } from '../../../../lib/finance';
import ConciliacaoTabela from './ConciliacaoTabela';

const mesAtual = () => todayISO().slice(0, 7);

export default function FinConciliacao() {
  const { selectedCompany } = useOutletContext();
  const [month, setMonth] = useState(mesAtual());
  const [movimentos, setMovimentos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [novaLinha, setNovaLinha] = useState(null);

  const companyId = selectedCompany ? selectedCompany.id : null;
  const categorias = useMemo(() => categoriasDaEmpresa(selectedCompany), [selectedCompany]);
  const podeEditar = !!selectedCompany && ['owner', 'partner'].includes(selectedCompany.role);

  const carregar = useCallback(async () => {
    if (!companyId) { setMovimentos([]); return; }
    setLoading(true);
    try {
      const { data } = await getFinMovements({ company_id: companyId, month });
      setMovimentos(data || []);
    } catch (e) {
      toast.error('Não foi possível carregar os movimentos.');
    } finally {
      setLoading(false);
    }
  }, [companyId, month]);

  useEffect(() => { carregar(); }, [carregar]);

  const guardar = async (mv, campos) => {
    // Otimista: a célula não pode piscar a cada tecla guardada.
    setMovimentos((lista) => lista.map((x) => x.id === mv.id ? { ...x, ...campos } : x));
    try {
      await updateFinMovement(mv.id, campos);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
      carregar();
    }
  };

  const apagar = async (mv) => {
    try {
      await deleteFinMovement(mv.id);
      setMovimentos((lista) => lista.filter((x) => x.id !== mv.id));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível apagar.');
    }
  };

  const criar = async () => {
    try {
      await createFinMovement({ ...novaLinha, company_id: companyId });
      setNovaLinha(null);
      carregar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível criar a linha.');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-conciliacao-page">
      <PageHeader icon={Scale} title="Conciliação"
        subtitle="O mês do banco, classificado e com os documentos ligados">
        <MonthPicker value={month} onChange={setMonth} className="w-44" testid="fin-conc-month" />
        {podeEditar && (
          <Button variant="outline" size="sm" data-testid="fin-conc-nova"
            onClick={() => setNovaLinha({ date_lancamento: `${month}-01`, description: '', amount: '', category: null })}>
            <Plus className="h-4 w-4 mr-2" />Linha
          </Button>
        )}
      </PageHeader>

      {!selectedCompany ? (
        <Card><CardContent className="p-6 text-center text-muted-foreground">
          Escolhe uma empresa no topo. Cada empresa tem a sua conciliação.
        </CardContent></Card>
      ) : (
        <Tabs defaultValue="mapa" className="space-y-4">
          <TabsList>
            <TabsTrigger value="mapa" data-testid="fin-conc-tab-mapa">Mapa do mês</TabsTrigger>
          </TabsList>
          <TabsContent value="mapa" className="space-y-4">
            <Card><CardContent className="p-0">
              {loading
                ? <div className="flex justify-center h-24 items-center">
                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                  </div>
                : <ConciliacaoTabela
                    movimentos={movimentos} categorias={categorias} podeEditar={podeEditar}
                    aoGuardar={guardar} aoApagar={apagar} aoAbrirFaturas={() => {}} />}
            </CardContent></Card>
          </TabsContent>
        </Tabs>
      )}

      <Dialog open={!!novaLinha} onOpenChange={(o) => !o && setNovaLinha(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Linha escrita à mão</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Data</Label>
              <Input type="date" value={novaLinha?.date_lancamento || ''}
                onChange={(e) => setNovaLinha({ ...novaLinha, date_lancamento: e.target.value })} /></div>
            <div><Label>Descrição</Label>
              <Input value={novaLinha?.description || ''} placeholder="Dinheiro Restante Mês Anterior"
                onChange={(e) => setNovaLinha({ ...novaLinha, description: e.target.value })} /></div>
            <div><Label>Montante</Label>
              <Input type="number" step="0.01" value={novaLinha?.amount ?? ''}
                placeholder="Negativo se for dinheiro a sair"
                onChange={(e) => setNovaLinha({ ...novaLinha, amount: e.target.value })} /></div>
            <div><Label>Categoria</Label>
              <Select value={novaLinha?.category || ''}
                onValueChange={(v) => setNovaLinha({ ...novaLinha, category: v })}>
                <SelectTrigger><SelectValue placeholder="Escolhe" /></SelectTrigger>
                <SelectContent>
                  {categorias.map((c) => <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>)}
                </SelectContent>
              </Select></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNovaLinha(null)}>Cancelar</Button>
            <Button onClick={criar} data-testid="fin-conc-nova-guardar">Criar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 4: Compilar e ver no browser**

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully`. Depois abrir `/admin/financeiro/conciliacao` com uma empresa escolhida e confirmar: a tabela mostra os movimentos do mês, o dropdown de categoria guarda, a descrição e a anotação guardam ao carregar Enter, e o botão `+ Linha` cria uma linha com o selo "à mão".

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro/conciliacao frontend/src/App.js frontend/src/components/layouts/AdminLayout.js && git commit -m "A secção Conciliação e a tabela mensal

Uma linha por movimento do banco, com categoria, descrição e anotação
editáveis na própria célula, mais as linhas escritas à mão bem marcadas.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Os cartões de topo

**Files:**
- Create: `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoCartoes.js`
- Modify: `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js`

**Interfaces:**
- Consumes: `resumoPorCategoria`, `percentagensSobreEntradas`, `plataformasDasEntradas` (Task 10); `getFinBankBalances` (Task 8); `getFinReconcilePending` (já existe).
- Produces: componente `ConciliacaoCartoes({ movimentos, categorias, saldos, pendentes })`.

- [ ] **Step 1: O componente**

Criar `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoCartoes.js`:

```jsx
import React, { useMemo } from 'react';
import { Card, CardContent } from '../../../../components/ui/card';
import { Landmark, PieChart, Store, Receipt } from 'lucide-react';
import { eur, kpiTone } from '../../../../lib/finance';
import {
  resumoPorCategoria, percentagensSobreEntradas, plataformasDasEntradas,
} from '../../../../lib/conciliacao';

// Linha label/valor, igual à do relatório de Resultados.
function Linha({ label, value, bold, muted }) {
  return (
    <div className="flex items-center justify-between">
      <span className={`text-sm ${muted ? 'text-muted-foreground' : ''}`}>{label}</span>
      <span className={`text-sm tabular-nums ${bold ? 'font-bold font-heading' : ''}`}>{value}</span>
    </div>
  );
}

function Bloco({ titulo, icone: Icone, cor, children }) {
  const tone = kpiTone(cor);
  return (
    <Card><CardContent className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <div className={`h-8 w-8 rounded-lg ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
          <Icone className="h-4 w-4" />
        </div>
        <p className="text-sm font-semibold">{titulo}</p>
      </div>
      <div className="space-y-1">{children}</div>
    </CardContent></Card>
  );
}

export default function ConciliacaoCartoes({ movimentos, categorias, saldos, pendentes }) {
  const resumo = useMemo(() => resumoPorCategoria(movimentos, categorias), [movimentos, categorias]);
  const pcts = useMemo(() => percentagensSobreEntradas(resumo), [resumo]);
  const plataformas = useMemo(() => plataformasDasEntradas(movimentos), [movimentos]);

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Bloco titulo="Resumo do orçamento" icone={PieChart} cor={0}>
        {resumo.map((l) => (
          // Valor absoluto, como no Excel: o sinal já se lê na categoria.
          <Linha key={l.id} label={l.label} value={eur(Math.abs(l.total))}
            muted={l.total === 0} bold={l.id === 'entradas'} />
        ))}
      </Bloco>

      <Bloco titulo="Resumo em %" icone={PieChart} cor={1}>
        {pcts.filter((p) => p.pct === null || p.pct > 0).map((p) => (
          <Linha key={p.id} label={p.label}
            value={p.pct === null ? '—' : `${p.pct.toLocaleString('pt-PT', { maximumFractionDigits: 2 })}%`} />
        ))}
        {pcts.every((p) => p.pct === null) && (
          <p className="text-xs text-muted-foreground">Sem entradas neste mês: não há por onde dividir.</p>
        )}
      </Bloco>

      <Bloco titulo="Valor Contas" icone={Landmark} cor={2}>
        {(saldos?.contas || []).map((c) => (
          <Linha key={c.account_id} label={c.name || c.bank || 'Conta'}
            value={c.balance === null ? '—' : eur(c.balance)} />
        ))}
        {!(saldos?.contas || []).length && (
          <p className="text-xs text-muted-foreground">Sem contas bancárias nesta empresa.</p>
        )}
        {!!(saldos?.contas || []).length && (
          <div className="pt-2 mt-1 border-t">
            <Linha label="Total" value={eur(saldos.total)} bold />
          </div>
        )}
      </Bloco>

      <div className="space-y-4">
        <Bloco titulo="Plataformas" icone={Store} cor={3}>
          {plataformas.length
            ? plataformas.map((p) => <Linha key={p.nome} label={p.nome} value={eur(p.total)} />)
            : <p className="text-xs text-muted-foreground">
                Classifica as entradas para elas aparecerem aqui.
              </p>}
          {!!plataformas.length && (
            <div className="pt-2 mt-1 border-t">
              <Linha label="Total" value={eur(plataformas.reduce((s, p) => s + p.total, 0))} bold />
            </div>
          )}
        </Bloco>
        <Bloco titulo="Faturas por pagar" icone={Receipt} cor={4}>
          <Linha label="Total" value={eur(pendentes?.totais?.faturas_por_pagar_valor || 0)} bold />
          <Linha label="Movimentos por ligar"
            value={String(pendentes?.totais?.movimentos_por_ligar_n ?? '—')} muted />
        </Bloco>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Ligar à página**

Em `FinConciliacao.js`, acrescentar aos imports:

```jsx
import { getFinBankBalances, getFinReconcilePending } from '../../../../lib/api';
import ConciliacaoCartoes from './ConciliacaoCartoes';
```

(juntar `getFinBankBalances` e `getFinReconcilePending` ao import de `lib/api` que já existe), estado novo:

```jsx
  const [saldos, setSaldos] = useState(null);
  const [pendentes, setPendentes] = useState(null);
```

e dentro de `carregar`, a seguir ao `setMovimentos(data || [])`:

```jsx
      const [s, p] = await Promise.all([
        getFinBankBalances(companyId).catch(() => ({ data: null })),
        getFinReconcilePending(companyId, month).catch(() => ({ data: null })),
      ]);
      setSaldos(s.data);
      setPendentes(p.data);
```

e no JSX, dentro do `TabsContent value="mapa"`, **antes** do `<Card>` da tabela:

```jsx
            <ConciliacaoCartoes movimentos={movimentos} categorias={categorias}
              saldos={saldos} pendentes={pendentes} />
```

- [ ] **Step 3: Compilar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully`.

- [ ] **Step 4: Conferir com o Excel**

Abrir `/admin/financeiro/conciliacao` no mês de Setembro da empresa do Açaí, classificar meia dúzia de linhas e confirmar contra o print do Excel: o Resumo do orçamento soma por categoria, o Resumo em % divide pelas Entradas, o Valor Contas mostra Millennium e Revolut em separado com o total, e as Plataformas agrupam as entradas pelo nome que se escreveu.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro/conciliacao && git commit -m "Os cartões de topo da Conciliação

Resumo por categoria, percentagens sobre as entradas, saldo de cada banco e
plataformas — os quatro blocos do Excel, mais as faturas por pagar.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: A coluna Faturas

**Files:**
- Create: `frontend/src/pages/admin/financeiro/conciliacao/DialogoFatura.js`
- Modify: `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js`

**Interfaces:**
- Consumes: `getFinReconcileSuggestions`, `getFinInvoices`, `linkFinMovement`, `unlinkFinMovement`, `attachFinMovement` (todos já em api.js).
- Produces: componente `DialogoFatura({ movimento, companyId, aberto, aoFechar, aoMudar })`.

- [ ] **Step 1: O diálogo**

Criar `frontend/src/pages/admin/financeiro/conciliacao/DialogoFatura.js`:

```jsx
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Link2, Paperclip, X } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '../../../../components/ui/dialog';
import { Button } from '../../../../components/ui/button';
import { Input } from '../../../../components/ui/input';
import { Badge } from '../../../../components/ui/badge';
import {
  getFinReconcileSuggestions, getFinInvoices,
  linkFinMovement, unlinkFinMovement, attachFinMovement,
} from '../../../../lib/api';
import { eur, fmtDate, normSup } from '../../../../lib/finance';
import { descricaoDoMovimento } from '../../../../lib/conciliacao';

export default function DialogoFatura({ movimento, companyId, aberto, aoFechar, aoMudar }) {
  const [sugestoes, setSugestoes] = useState([]);
  const [faturas, setFaturas] = useState([]);
  const [procura, setProcura] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const ficheiroRef = useRef(null);

  useEffect(() => {
    if (!aberto || !movimento) return;
    setProcura('');
    getFinReconcileSuggestions(companyId)
      .then(({ data }) => setSugestoes((data || []).filter((s) => s.movement?.id === movimento.id)))
      .catch(() => setSugestoes([]));
    getFinInvoices(companyId)
      .then(({ data }) => setFaturas((data || []).filter((f) => !f.paid || f.id === movimento.invoice_id)))
      .catch(() => setFaturas([]));
  }, [aberto, movimento, companyId]);

  const encontradas = useMemo(() => {
    const q = normSup(procura);
    if (!q) return faturas.slice(0, 20);
    return faturas.filter((f) =>
      normSup(f.supplier || '').includes(q) || String(f.invoice_number || '').includes(procura),
    ).slice(0, 20);
  }, [faturas, procura]);

  if (!movimento) return null;

  const ligar = async (invoiceId) => {
    setOcupado(true);
    try {
      await linkFinMovement(movimento.id, invoiceId);
      toast.success('Fatura ligada.');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível ligar.');
    } finally { setOcupado(false); }
  };

  const desligar = async () => {
    setOcupado(true);
    try {
      await unlinkFinMovement(movimento.id);
      toast.success('Fatura desligada. Voltou a "por pagar".');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error('Não foi possível desligar.');
    } finally { setOcupado(false); }
  };

  const anexar = async (file) => {
    if (!file) return;
    setOcupado(true);
    try {
      await attachFinMovement(movimento.id, file);
      toast.success('Documento anexado.');
      aoMudar();
      aoFechar();
    } catch (e) {
      toast.error('Não foi possível anexar.');
    } finally { setOcupado(false); }
  };

  return (
    <Dialog open={aberto} onOpenChange={(o) => !o && aoFechar()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{descricaoDoMovimento(movimento)}</DialogTitle>
          <DialogDescription>
            {fmtDate(movimento.date_lancamento)} · {eur(movimento.amount)}
          </DialogDescription>
        </DialogHeader>

        {movimento.invoice_id ? (
          <div className="rounded-xl border p-3 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate">Fatura ligada</p>
              <p className="text-xs text-muted-foreground">
                Desligar repõe a fatura como "por pagar".
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={desligar} disabled={ocupado}>
              <X className="h-4 w-4 mr-1" />Desligar
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {!!sugestoes.length && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sugestões</p>
                {sugestoes.map((s) => (
                  <div key={s.invoice.id} className="rounded-xl border p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold truncate">
                          {s.invoice.supplier} · {s.invoice.invoice_number || 's/nº'}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {fmtDate(s.invoice.issue_date)} · {eur(s.invoice.amount)}
                        </p>
                      </div>
                      <Badge className={s.confianca === 'alta'
                        ? 'bg-emerald-600 hover:bg-emerald-600'
                        : 'bg-amber-500 hover:bg-amber-500'}>
                        {s.confianca === 'alta' ? 'Confiança alta' : 'Confiança média'}
                      </Badge>
                    </div>
                    <div className="flex justify-end">
                      <Button size="sm" disabled={ocupado} onClick={() => ligar(s.invoice.id)}>
                        <Link2 className="h-4 w-4 mr-1" />Ligar
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Procurar fatura
              </p>
              <Input value={procura} onChange={(e) => setProcura(e.target.value)}
                placeholder="Fornecedor ou número" data-testid="fin-conc-procura" />
              <div className="max-h-56 overflow-y-auto space-y-1">
                {encontradas.map((f) => (
                  <button key={f.id} type="button" disabled={ocupado} onClick={() => ligar(f.id)}
                    className="w-full text-left rounded-lg border p-2 hover:bg-muted/50">
                    <p className="text-sm font-medium truncate">
                      {f.supplier} · {f.invoice_number || 's/nº'}
                      {f.source === 'estoque' && <Badge variant="outline" className="ml-2 text-[10px]">loja</Badge>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {fmtDate(f.issue_date)} · {eur(f.amount)}
                    </p>
                  </button>
                ))}
                {!encontradas.length && (
                  <p className="text-xs text-muted-foreground py-2">Nenhuma fatura por pagar encontrada.</p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="pt-2 border-t">
          <input ref={ficheiroRef} type="file" accept=".pdf" className="hidden"
            onChange={(e) => { anexar(e.target.files?.[0]); e.target.value = ''; }} />
          <Button variant="outline" size="sm" disabled={ocupado}
            onClick={() => ficheiroRef.current?.click()} data-testid="fin-conc-anexar">
            <Paperclip className="h-4 w-4 mr-2" />
            {movimento.attachment_path ? 'Substituir o documento anexado' : 'Anexar um documento'}
          </Button>
          <p className="text-[11px] text-muted-foreground mt-1">
            É um anexo por linha: anexar outro substitui o que lá está.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Ligar à página**

Em `FinConciliacao.js`:

```jsx
import DialogoFatura from './DialogoFatura';
```

estado:

```jsx
  const [movDoc, setMovDoc] = useState(null);
```

trocar `aoAbrirFaturas={() => {}}` por `aoAbrirFaturas={setMovDoc}`, e antes do fecho do `</div>` da página:

```jsx
      <DialogoFatura movimento={movDoc} companyId={companyId} aberto={!!movDoc}
        aoFechar={() => setMovDoc(null)} aoMudar={carregar} />
```

- [ ] **Step 3: Compilar**

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully`.

- [ ] **Step 4: Exercitar o caminho todo no browser**

Numa saída sem fatura: abrir o diálogo, ligar uma fatura pela sugestão, confirmar que a linha passa a "Ligada" e que a fatura aparece paga no Pagamentos. Desligar e confirmar que volta a "por pagar". **Numa ENTRADA** (uma transferência do Glovo): anexar um PDF e confirmar que fica com "Anexo" — é o caminho que o Extrato proíbe.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro/conciliacao && git commit -m "A coluna Faturas: sugestões, procura e anexo

Reaproveita o motor que já existe. Ao contrário do Extrato, também deixa
anexar documento a uma ENTRADA — que é metade do que interessa no mês.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: As abas mudam de casa

O Pagamentos tem hoje `Conciliação` (`TabsContent value="conciliacao"`, linhas 1031-1108) e `Por conciliar` (1111-1219). Passam para a secção nova.

**Files:**
- Modify: `frontend/src/pages/admin/financeiro/FinPagamentos.js:763-771`, `:1031-1219`
- Modify: `frontend/src/pages/admin/financeiro/conciliacao/FinConciliacao.js`
- Create: `frontend/src/pages/admin/financeiro/conciliacao/ConciliacaoSugestoes.js`

**Interfaces:**
- Consumes: o mesmo JSX e as mesmas funções que já estão no FinPagamentos.
- Produces: componente `ConciliacaoSugestoes({ companyId, month, podeEditar })`.

- [ ] **Step 1: Mover o JSX**

Criar `ConciliacaoSugestoes.js` com o conteúdo dos dois `TabsContent` do FinPagamentos (linhas 1031-1108 e 1111-1219), mais o estado e as funções que eles usam (`sugestoes`, `pending`, `loadSuggestions`, `loadPending`, `doDismiss`, `doLink`, `doAutoReconcile`), transpostos tal e qual. Ajustar os caminhos dos imports de `../../../` para `../../../../`.

**Não reescrever a lógica.** É uma mudança de casa: o mesmo código, noutro ficheiro.

- [ ] **Step 2: Tirar do Pagamentos**

Em `FinPagamentos.js`, apagar os dois `<TabsTrigger>` (linhas 763-771: o de `conciliacao`, com o badge de contagem, e o de `porconciliar`) e os dois `<TabsContent>` (1031-1108 e 1111-1219). Apagar também o estado e as funções que ficaram sem uso, e os imports que deixaram de ser usados.

- [ ] **Step 3: Os separadores na secção nova**

Em `FinConciliacao.js`, a `TabsList` passa a:

```jsx
          <TabsList>
            <TabsTrigger value="mapa" data-testid="fin-conc-tab-mapa">Mapa do mês</TabsTrigger>
            <TabsTrigger value="sugestoes" data-testid="fin-conc-tab-sugestoes">Sugestões</TabsTrigger>
            <TabsTrigger value="porligar" data-testid="fin-conc-tab-porligar">Por ligar</TabsTrigger>
          </TabsList>
```

com os dois `TabsContent` novos a renderizar `<ConciliacaoSugestoes ... />`.

- [ ] **Step 4: Confirmar que não sobrou nada**

```bash
cd ~/Developer/RH && grep -n "conciliacao\|porconciliar\|btn-auto-reconcile" frontend/src/pages/admin/financeiro/FinPagamentos.js
```

Esperado: **zero linhas**. Depois:

```bash
cd ~/Developer/RH/frontend && CI=true yarn build 2>&1 | tail -20
```

Esperado: `Compiled successfully`, sem avisos de variáveis por usar no FinPagamentos.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/financeiro && git commit -m "As abas de conciliação mudam-se do Pagamentos para a Conciliação

Havia duas coisas com o mesmo nome em sítios diferentes. Agora a palavra
aponta para um sítio só, e o Pagamentos volta a ser só faturas.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: O primeiro teste do motor de conciliação

O motor existe há meses e nunca teve rede. Já que a secção nova assenta nele, fica um teste na regra que mais dinheiro protege.

**Files:**
- Test: `backend/tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py`

**Interfaces:**
- Consumes: `server._fin_reconcile_score`.
- Produces: nada.

- [ ] **Step 1: Ler a função antes de a testar**

```bash
cd ~/Developer/RH && sed -n '4990,5030p' backend/server.py
```

Confirmar a assinatura exacta (`_fin_reconcile_score(inv, mov, rule, carimbos)`), o nome dos campos que lê e a pontuação de cada sinal. **O teste tem de bater com o que lá está**, não com o que este plano supõe.

- [ ] **Step 2: Escrever o teste**

Criar `backend/tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py`:

```python
"""**Um pagamento não pode conciliar com uma fatura ainda por emitir.**

O motor pontua pares fatura↔movimento e o montante igual vale metade da
pontuação de corte sozinho. Sem a guarda da data, uma renda de 1.200 € paga em
Agosto casa com a fatura de 1.200 € emitida em Setembro — e o sistema dá a de
Setembro por paga, com a de Agosto a ficar por pagar para sempre.

Este é o primeiro teste deste motor. Ele está em produção desde que a
conciliação existe.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _fatura(emissao):
    return {
        "id": "f1", "company_id": "e1", "supplier": "EDP Comercial",
        "invoice_number": "FT 2026/812", "amount": 1200.0,
        "issue_date": emissao, "due_date": emissao,
    }


def _movimento(data):
    return {
        "id": "m1", "company_id": "e1", "date_lancamento": data,
        "amount": -1200.0, "description": "PAGAMENTO SERVICOS EDP COMERCIAL",
    }


def test_pagar_antes_de_a_fatura_existir_nao_pontua():
    score, _razoes = server._fin_reconcile_score(
        _fatura("2026-09-01"), _movimento("2026-08-15"), None, {}
    )
    assert score < 65, (
        "um pagamento de Agosto casou com uma fatura emitida em Setembro — a "
        "de Setembro fica dada por paga e a de Agosto por pagar para sempre"
    )


def test_o_mesmo_par_com_as_datas_pela_ordem_certa_pontua():
    score, _razoes = server._fin_reconcile_score(
        _fatura("2026-08-01"), _movimento("2026-08-15"), None, {}
    )
    assert score >= 65
```

- [ ] **Step 3: Correr**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py -q
```

Esperado: PASS. **Se falhar, é um defeito a sério** — parar, e tratá-lo como bug (a guarda não existe ou não faz o que diz), não ajustar o teste até ficar verde.

- [ ] **Step 4: Provar que o teste morde**

Comentar a guarda da data dentro de `_fin_reconcile_score`, correr outra vez e confirmar que o primeiro teste **falha**. Repor a guarda e confirmar que volta a passar.

```bash
cd ~/Developer/RH/backend && PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py -q
```

> `PYTHONDONTWRITEBYTECODE=1` não é adorno: neste Mac o bytecode vai para `~/Library/Caches/com.apple.python` e uma mutação reposta no mesmo segundo não recompila — a suite mediria o passado.

- [ ] **Step 5: Correr tudo e commit**

```bash
cd ~/Developer/RH/backend && ./.venv/bin/python -m pytest -q
cd ~/Developer/RH/frontend && CI=true yarn test --watchAll=false src/lib/
cd ~/Developer/RH && git add backend/tests/fin/test_a_conciliacao_nao_paga_antes_de_emitir.py && git commit -m "O primeiro teste do motor de conciliação

Está em produção desde que a conciliação existe e nunca teve um.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Depois do plano: o dia da migração

A migração das categorias **não corre sozinha**. Quando tudo estiver junto ao `main` e no ar:

1. Cópia de segurança da coleção: `mongodump --db <DB_NAME> --collection fin_invoices`.
2. Ensaio no servidor: `cd ~/RH/backend && python migrar_categorias.py` — ler os números.
3. A sério: `python migrar_categorias.py --aplicar`.
4. Abrir Relatórios → Resultados e confirmar que as despesas aparecem com os nomes novos.

Publicar segue a skill `fluxo` (juntar ao `main`, publicar só o `main`, confirmar `/api/health`).
