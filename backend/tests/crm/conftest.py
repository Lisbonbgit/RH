"""Variáveis de ambiente que têm de estar definidas ANTES de qualquer módulo de
teste do CRM ser colectado — o mesmo problema de ordem descrito em
tests/faturacao/conftest.py (ler esse docstring).

O pytest colecciona por ordem alfabética, e tests/crm vem ANTES de
tests/faturacao. O pacote `crm` vai importar `faturacao.auth` (T1.4), e com ele
o `faturacao/__init__.py` inteiro, logo `faturacao.pos_auth`, que lê
`POS_JWT_SECRET` de `os.environ` UMA VEZ, à importação. Sem isto aqui, o
conftest da faturação chegava tarde e o POS ficava com `None` na suite inteira.

O mesmo vale para o `server.py` (test_montagem.py, T1.9): lê `JWT_SECRET`,
`MONGO_URL` e `DB_NAME` ao ser importado. Se fosse importado antes de alguém
definir `JWT_SECRET`, congelava o valor por omissão enquanto `faturacao.auth`
lê "segredo-de-teste" do ambiente — e test_seguranca_login.py deixava de bater
certo.

Os valores são EXACTAMENTE os que os testes existentes já usam
(tests/faturacao/conftest.py, tests/faturacao/test_auth.py,
tests/test_seguranca_login.py, tests/fin/*). `setdefault` nunca sobrepõe um
valor que já lá esteja. `teste_sem_ligacao` é um nome de base que nenhum teste
chega a abrir: os testes do CRM usam sempre o duplo da base.
"""
import os

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
