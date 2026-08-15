"""Variáveis de ambiente que têm de estar definidas ANTES de qualquer
módulo de teste ser colectado — nunca depois.

`faturacao.pos_auth.POS_JWT_SECRET` é lido de `os.environ` UMA VEZ, à
importação do módulo (deliberado: ver C4 na revisão do núcleo fiscal — nunca
um valor por omissão escondido no código). Isso significa que o `os.environ.
setdefault("POS_JWT_SECRET", ...)` que já vivia no topo de test_pos_auth.py
só protegia esse ficheiro SE ele fosse o primeiro a importar
`faturacao.pos_auth` — mas o pytest colecciona os ficheiros por ordem
alfabética, e `test_arranque.py` (que importa o pacote `faturacao` inteiro,
logo `faturacao.venda`, logo `faturacao.pos_auth`) vem antes. Sem isto aqui,
`POS_JWT_SECRET` ficava `None` para a suite inteira assim que outro ficheiro
fosse colectado primeiro — um teste isolado passava, a suite completa não.

Um `conftest.py` corre antes de QUALQUER colecção de testes no seu
directório (e sub-directórios) — é o único sítio garantidamente cedo que
chega."""
import os

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
