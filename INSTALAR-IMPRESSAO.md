# Pôr a impressão a funcionar numa loja

Estas instruções são para quem vai à loja fazer isto — não é preciso perceber
nada de programação. Leva cerca de dez minutos por loja.

No fim, a loja passa a ter:

- o **talão do cliente** a sair na impressora do balcão sempre que se cobra;
- a **ficha do pedido** a sair na impressora da cozinha;
- o **Z** a sair quando se fecha a caixa;
- a **gaveta a abrir** pelo botão «Abrir Gaveta»;
- o botão **«Imprimir»** de uma fatura antiga a dar segunda via.

---

## Antes de ir à loja

### 1. Compilar o programa (uma vez só, para todas as lojas)

Isto faz-se **num PC Windows** — não dá para fazer num Mac. Só é preciso
repetir se o programa mudar.

1. Instalar o **Python** (python.org, versão 3.11 ou mais recente). Na
   primeira janela do instalador, ligar a caixa **«Add python.exe to PATH»**.
2. Abrir a **Linha de Comandos** e escrever, uma linha de cada vez:

   ```
   cd caminho\para\o\projecto
   pip install -r agente_impressao\requirements.txt
   pyinstaller agente.spec
   ```

3. Aparece um ficheiro em `dist\ImpressaoLacai.exe`. **É esse o programa** —
   um ficheiro só, que funciona em qualquer PC Windows sem instalar nada.

Copiar esse ficheiro para uma pen.

### 2. Pedir um código para cada loja

Cada PC precisa do seu **código de emparelhamento** — é o que autoriza aquele
PC a ir buscar os talões daquela loja.

No portal, com conta de gestor:

1. **Faturação → Configuração → Dispositivos**
2. Escolher a loja, dar um nome ao PC (por exemplo *PC Balcão — Colombo*) e
   carregar em gerar.
3. Aparece um código de 8 caracteres (por exemplo `A1B2C3D4`).

**Atenção:** o código **vale 15 minutos e só serve uma vez**. Não vale a pena
gerar os cinco de manhã para os usar à tarde — gere-se um na altura de o usar.

> Se o PC da loja **já abre o POS**, ele já foi emparelhado uma vez. O
> programa de impressão precisa **do seu próprio código**, novo: são duas
> autorizações separadas, e é isso que permite tirar a impressão a um PC sem
> tirar o POS.

---

## Na loja

### 3. Confirmar que as duas impressoras estão instaladas no Windows

Em **Definições do Windows → Bluetooth e dispositivos → Impressoras e
scanners**, têm de aparecer as duas: a do balcão e a da cozinha.

Se faltar alguma, instale-a primeiro (com o CD/instalador da Epson ou da
TP8002). **Não interessa se está ligada por USB ou por cabo de rede** — o que
interessa é aparecer nessa lista com um nome.

Aproveite para **apontar os nomes exactos** como aparecem ali. Vai precisar
deles no passo 5.

### 4. Copiar e abrir o programa

1. Copiar o `ImpressaoLacai.exe` da pen para o PC — sugestão:
   `C:\LAcai\ImpressaoLacai.exe`
2. Fazer duplo clique.
3. Na primeira vez, abre sozinho a janela das **Definições**.

### 5. Preencher as Definições

| Campo | O que pôr |
|---|---|
| **Endereço do servidor** | `https://lisbonb.com` |
| **Código de emparelhamento** | o código de 8 caracteres do passo 2 |
| **Impressora da CAIXA** | a do balcão, escolhida na lista |
| **Impressora da COZINHA** | a da cozinha, escolhida na lista |

As impressoras **escolhem-se da lista**, nunca se escrevem à mão: um nome com
uma letra trocada dá um programa que parece configurado e nunca imprime nada.

Carregar em **Gravar**.

- Se o código estiver bom, a janela passa a dizer **«A trabalhar»** a verde,
  com o nome da loja.
- Se disser que o código não serve, peça outro ao gestor — provavelmente
  passaram os 15 minutos.

### 6. Imprimir a página de teste — **este passo não se salta**

Carregar em **«Imprimir página de teste (caixa)»**, e depois no **«… (cozinha)»**.

O que sair da impressora diz tudo:

| O que saiu | O que quer dizer | O que fazer |
|---|---|---|
| Uma página com **PÁGINA DE TESTE** em cima, os acentos certos («Açaí, ção») e cada linha a caber numa linha | **Está tudo bem.** | Nada. Passe ao passo 7. |
| Uma folha com **letras e sinais soltos** (coisas como `ESC @ ESC t`) | O Windows está a **desenhar** os comandos em vez de os mandar em cru. | Ver **«Se sair lixo»**, mais abaixo. |
| A página sai, mas **os acentos estão trocados** (sai «A?a?» em vez de «Açaí») | Aquela impressora usa outra tabela de letras. | Avisar quem programa — muda-se **um número** no sistema. |
| A página sai, mas as três linhas da **hierarquia** saem todas iguais às outras (a que diz «CORPO DUPLO» não sai maior, a do negrito não sai mais escura, a do meio não vai ao meio) | Aquela impressora ignora esses comandos. | Avisar quem programa — **a ficha da cozinha vai sair toda no mesmo tamanho** e é preciso decidir o que fazer. |
| A página sai mas **o papel não corta** | Aquela impressora usa outro comando de corte. | Avisar quem programa — muda-se **um número** no sistema. |
| A linha dos números **dá a volta** e continua por baixo | O papel é de 58 mm, não de 80 mm. | Avisar quem programa. |
| **Não sai nada** e o programa diz que não conseguiu | Papel, cabo, impressora desligada, ou é outra impressora. | Ver o rolo e o cabo; confirmar que escolheu a impressora certa. |
| **Não sai nada** e o programa diz que correu bem | Os bytes chegaram ao Windows e ficaram lá. | Ver a fila de impressão do Windows (duplo clique na impressora): normalmente está um trabalho preso ou a impressora está «em pausa». |

#### Se sair lixo (letras e sinais soltos)

Isto resolve-se **nas definições da impressora**, no Windows, e nunca no
programa:

1. **Definições do Windows → Impressoras e scanners** → clicar na impressora →
   **Propriedades da impressora**.
2. Separador **Avançadas**: escolher **«Imprimir directamente para a
   impressora»** (em vez de «Colocar documentos em spool»).
3. Se continuar, o problema é o **controlador (driver)**: o que está instalado
   está a desenhar páginas. Reinstalar a impressora escolhendo o controlador
   **de talões / ESC/POS** do fabricante — a Epson chama-lhe normalmente
   *TM-m30 (ESC/POS)*, não *TM-m30 (Advanced Printer Driver)* em modo página.
4. Voltar ao passo 6 e imprimir outra vez a página de teste.

### 7. Pôr o programa a arrancar com o Windows

Para não haver um dia em que alguém reinicia o PC e a loja passa a manhã a
vender sem papel:

1. Clicar com o botão direito no `ImpressaoLacai.exe` → **Mostrar mais opções**
   → **Criar atalho**.
2. Carregar nas teclas **Windows + R**, escrever `shell:startup` e dar Enter.
   Abre uma pasta.
3. **Arrastar o atalho para dentro dessa pasta.**

Reiniciar o PC e confirmar que o programa aparece sozinho na barra de tarefas.

### 8. A prova final — com uma venda a sério

Isto é o que confirma que a cadeia toda funciona, e não só a impressora:

1. Abrir o POS no browser, entrar com o PIN.
2. Fazer uma conta pequena e, **antes de cobrar**, carregar em **«Imprimir
   Pedido»**: **tem de sair a ficha na cozinha**, com a conta ainda aberta. É
   assim que a loja trabalha — pica-se, manda-se para a cozinha, cobra-se no
   fim — e o botão pode ser carregado outra vez sempre que o papel encravar ou
   a ficha se perder.
3. **Finalizar** a conta: **tem de sair o talão do cliente no balcão**, em
   poucos segundos. **A cozinha não recebe nada aqui**, e não é avaria: a
   ficha da cozinha é sempre do botão do passo 2 — senão uma conta dividida
   por três mandava três fichas do mesmo copo.
4. No menu **Caixa → Abrir Gaveta**: a gaveta tem de abrir.
5. No separador **Faturação**, abrir essa fatura e carregar em **Imprimir**:
   tem de sair a segunda via, igual à primeira.
6. Se a venda foi mesmo real, emitir uma **nota de crédito** para a anular.

---

## O dia a dia

**O programa fica minimizado na barra de tarefas e não se fala com ele.**

- **O X da janela minimiza, não fecha.** É de propósito: fechá-lo deixava a
  loja a vender sem papel a partir desse clique.
- Se ele **saltar para a frente a vermelho**, é porque não consegue falar com
  o servidor. Ver a internet da loja. **Os talões não se perdem** — ficam à
  espera no servidor e saem quando a ligação voltar.
- No POS, por baixo do botão **Abrir Gaveta**, aparece um aviso quando há
  papéis à espera ou quando algum não chegou mesmo a sair.
- Esse aviso **desliga-se em «Já vi os papéis que falharam»**, no mesmo menu,
  depois de os reimprimir pelo separador Faturação. Não apaga nem resolve
  nada: só tira o aviso do ecrã. Sem isso ele ficava lá **sete dias**, e um
  aviso que não se desliga é um aviso que se aprende a ignorar.

### Se a impressora ficar sem papel

O programa insiste **cinco minutos** — tempo de alguém dar por isso e pôr um
rolo. Posto o rolo, o papel sai sozinho e não é preciso fazer nada. Passados
os cinco minutos desiste, e o aviso acima diz quantos papéis ficaram por sair:
reimprimem-se pelo separador **Faturação**.

### Se ninguém abriu o programa

O POS **diz-o**: os botões de imprimir ficam apagados com a frase *«Não há
nenhum programa de impressão a responder nesta loja»*. Isso é de propósito —
um botão que parecesse funcionar deixava a operadora a dar o cliente por
servido sem papel nenhum ter existido.

### O que fica por imprimir de ontem

Nada. Um talão que fique à espera mais de **meia hora** é deitado fora, e o
pedido de abrir a gaveta ao fim de **dois minutos** (um impulso atrasado abria
a gaveta do dinheiro com ninguém à frente dela). Uma loja que abre de manhã não
tem vinte talões da véspera a sair.

**Não se perde nada com isso:** o talão fica guardado com a fatura e
reimprime-se num toque no separador Faturação.

### Quando a loja tem PC novo

Gerar um código novo (passo 2), copiar o programa, configurar. E no portal, em
**Faturação → Configuração → Dispositivos**, **revogar** o PC antigo — a
partir daí ele deixa de conseguir ir buscar talões.

---

## O que é preciso do lado do servidor

Para quem trata do servidor, e não da loja:

1. **Nada de novo a instalar.** As rotas da impressão entram com o resto do
   módulo de Faturação, no mesmo processo.
2. **Índices novos** em `fat_trabalhos_impressao` — criam-se sozinhos no
   arranque (`faturacao/db.py`), como os outros. São três: a chave única (é o
   que impede o mesmo talão de entrar duas vezes na fila), a pesquisa por loja,
   e um **TTL de 7 dias** que apaga a história do papel já resolvido.
3. **`POS_JWT_SECRET`** tem de continuar definido no `.env` — já era preciso
   para o POS e nada mudou.
4. O deploy é o do costume (`git ls-files` + rsync **com `--exclude '.env'`**).

### Onde ver o que se passou

- No POS: `GET /pos/impressao/estado` — quantos estão por sair, quantos
  falharam, e se há programa a ouvir.
- No PC da loja: `%APPDATA%\AgenteImpressaoLacai\agente.log`.
- Na base de dados: `fat_trabalhos_impressao` guarda cada papel dos últimos 7
  dias, com o estado, quantas vezes foi tentado e o erro. **Não é registo
  fiscal de nada** — o documento e o talão certificado ficam em
  `fat_documentos`, para sempre.
