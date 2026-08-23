"""A JANELA E O CICLO — o programa que o funcionário vê.

Isto é a casca: uma janela `tkinter` na barra de tarefas e uma thread a
perguntar ao servidor se há trabalho. As decisões todas estão em `nucleo.py`
(e testam-se), e a conversa com a impressora está em `windows.py` (e não se
testa em lado nenhum a não ser à frente da impressora).

## PORQUE É QUE É `tkinter` E NÃO UM ÍCONE NA BANDEJA

`tkinter` vem com o Python — não é mais uma dependência a instalar, nem mais
uma coisa a faltar no dia em que se voltar a compilar isto. E uma janela
minimizada JÁ ESTÁ na barra de tarefas, que é onde o dono a quis.

Um ícone na bandeja do relógio precisava de uma biblioteca a mais e escondia
o programa ainda melhor — e o problema deste programa nunca vai ser estar
demasiado à vista. Vai ser o contrário.

## O QUE A JANELA TEM DE FAZER, E É SÓ ISTO

1. **Dizer que está a trabalhar** — e ficar minimizada, calada, o dia inteiro.
2. **GRITAR quando não consegue falar com o servidor.** Salta para a frente,
   fica vermelha e diz o que fazer. Um programa de impressão silenciosamente
   morto é pior do que nenhum: a loja continua a vender, os clientes
   continuam a sair sem papel, e ninguém descobre até ao fecho.
3. **Deixar configurar** — o servidor, o código da loja e as duas impressoras.
4. **Imprimir uma página de teste**, que é a única forma de o dono descobrir
   num clique se os bytes entram em cru na impressora ou se o driver os está
   a desenhar.
"""
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import nucleo, windows

logger = logging.getLogger("agente_impressao")

TITULO = "Impressão L'Açaí"

_COR_BEM = "#166534"
_COR_MAL = "#b91c1c"


class Agente:
    """O ciclo, a correr numa thread própria.

    Thread e não `after()` do tkinter porque cada volta faz pedidos de rede
    que podem demorar até 20 segundos: no fio do tkinter, isso era a janela
    congelada — e uma janela congelada é indistinguível de um programa morto,
    que é exactamente a confusão que este programa não pode causar.

    A janela e a thread só trocam duas coisas, ambas por `queue` (a única
    forma segura): o ciclo põe lá o que quer mostrar, a janela lê de 200 em
    200 ms."""

    def __init__(self, definicoes):
        self.definicoes = definicoes
        self.falhas_seguidas = 0
        self.ultimo_erro = ""
        self.mensagens = queue.Queue()
        self._parar = threading.Event()
        # `Event` e não `time.sleep`: quando o funcionário muda as definições
        # ou fecha o programa, a espera acaba NO INSTANTE em vez de arrastar
        # até um minuto — que é o tecto da espera depois de falhar.
        self._acordar = threading.Event()

    def servidor(self):
        return nucleo.Servidor(
            self.definicoes.get("servidor", ""),
            self.definicoes.get("device_token", ""),
        )

    def mudar_definicoes(self, definicoes):
        self.definicoes = definicoes
        self.falhas_seguidas = 0
        self.ultimo_erro = ""
        self._acordar.set()

    def parar(self):
        self._parar.set()
        self._acordar.set()

    def correr(self):
        while not self._parar.is_set():
            espera = nucleo.espera_apos_falhas(self.falhas_seguidas)
            if nucleo.esta_configurado(self.definicoes):
                try:
                    saidos = nucleo.uma_volta(
                        self.servidor(), self.definicoes, windows.imprimir_em_cru)
                    self.falhas_seguidas = 0
                    self.ultimo_erro = ""
                    if saidos:
                        self._anunciar("Saíram %d." % saidos)
                except nucleo.ErroDoServidor as e:
                    self.falhas_seguidas += 1
                    self.ultimo_erro = str(e)
                except Exception as e:  # noqa: BLE001
                    # Nada — nada — pode matar este ciclo. Um programa de
                    # impressão que morre por uma excepção que ninguém previu
                    # deixa a loja a vender sem papel até alguém reparar.
                    self.falhas_seguidas += 1
                    self.ultimo_erro = "Erro inesperado: %s" % e
                    logger.exception("volta da fila rebentou")
            self._anunciar(None)
            self._acordar.wait(espera)
            self._acordar.clear()

    def _anunciar(self, nota):
        self.mensagens.put((
            nucleo.estado_legivel(self.definicoes, self.falhas_seguidas, self.ultimo_erro),
            nucleo.ha_problema(self.definicoes, self.falhas_seguidas),
            nota,
        ))


class Janela:
    def __init__(self, raiz, agente):
        self.raiz = raiz
        self.agente = agente
        self.ja_gritou = False
        raiz.title(TITULO)
        raiz.geometry("560x340")
        raiz.protocol("WM_DELETE_WINDOW", self._fechar)

        moldura = ttk.Frame(raiz, padding=16)
        moldura.pack(fill="both", expand=True)

        self.rotulo = tk.Label(
            moldura, text="A arrancar…", justify="left", anchor="w",
            wraplength=510, font=("Segoe UI", 11, "bold"),
        )
        self.rotulo.pack(fill="x")

        self.detalhe = tk.Label(
            moldura, text="", justify="left", anchor="w", wraplength=510,
            fg="#525252", font=("Segoe UI", 9),
        )
        self.detalhe.pack(fill="x", pady=(6, 12))

        botoes = ttk.Frame(moldura)
        botoes.pack(fill="x")
        ttk.Button(botoes, text="Definições…", command=self.abrir_definicoes).pack(side="left")
        ttk.Button(
            botoes, text="Imprimir página de teste (caixa)",
            command=lambda: self.pagina_de_teste(nucleo.CAIXA),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            botoes, text="… (cozinha)",
            command=lambda: self.pagina_de_teste(nucleo.COZINHA),
        ).pack(side="left", padx=(8, 0))

        self.historico = tk.Text(moldura, height=8, wrap="word", state="disabled")
        self.historico.pack(fill="both", expand=True, pady=(14, 0))

        self.raiz.after(200, self._ler_mensagens)

    # --- o que a thread mandou ---

    def _ler_mensagens(self):
        while True:
            try:
                texto, mal, nota = self.agente.mensagens.get_nowait()
            except queue.Empty:
                break
            self.rotulo.config(text=texto, fg=_COR_MAL if mal else _COR_BEM)
            if nota:
                self._escrever(nota)
            if mal and not self.ja_gritou:
                # **Salta para a frente, uma vez.** Uma vez e não a cada
                # volta: um programa que se põe à frente de três em três
                # segundos torna o PC do balcão inutilizável, e a operadora
                # aprende a fechá-lo — que é o pior desfecho possível.
                self.raiz.deiconify()
                self.raiz.lift()
                self.ja_gritou = True
            if not mal:
                self.ja_gritou = False
        self.raiz.after(200, self._ler_mensagens)

    def _escrever(self, linha):
        from datetime import datetime
        self.historico.config(state="normal")
        self.historico.insert("end", "%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), linha))
        self.historico.see("end")
        self.historico.config(state="disabled")

    # --- os botões ---

    def abrir_definicoes(self):
        DialogoDefinicoes(self.raiz, self.agente, ao_gravar=self._depois_de_gravar)

    def _depois_de_gravar(self, definicoes):
        self.agente.mudar_definicoes(definicoes)
        self._escrever("Definições gravadas.")

    def pagina_de_teste(self, papel):
        """Vai buscar os bytes ao servidor e manda-os DIRECTAMENTE à
        impressora — sem passar pela fila.

        Sem a fila de propósito: o que esta página tem de provar é o último
        salto, e só ele. Se saísse da fila e não aparecesse papel, ficavam
        três suspeitos em vez de um.

        Corre no fio da janela e não na thread: é um clique, a pessoa está à
        frente, e um segundo de janela parada é o que ela espera de um botão."""
        nome = nucleo.impressora_de(self.agente.definicoes, papel)
        if not nome:
            messagebox.showwarning(TITULO, nucleo.MSG_SEM_IMPRESSORA % papel)
            return
        try:
            dados = self.agente.servidor().pagina_de_teste(papel)
            windows.imprimir_em_cru(nome, dados)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(TITULO, "Não foi possível imprimir:\n\n%s" % e)
            return
        self._escrever("Página de teste enviada para %r." % nome)
        messagebox.showinfo(
            TITULO,
            "A página de teste foi para a impressora «%s».\n\n"
            "Se saiu uma página com «PAGINA DE TESTE» em cima e os acentos "
            "certos, está tudo bem.\n\n"
            "Se saiu uma folha com letras e sinais soltos, o Windows está a "
            "DESENHAR os comandos em vez de os mandar em cru — veja o passo 6 "
            "do INSTALAR-IMPRESSAO.md.\n\n"
            "Se não saiu nada, veja o papel, o cabo e se é mesmo esta a "
            "impressora." % nome,
        )

    def _fechar(self):
        """O X da janela MINIMIZA, não fecha.

        É a decisão certa nesta casa: o X é onde a mão vai para "tirar isto da
        frente", e fechar mesmo deixava a loja a vender sem papel a partir
        daquele clique — sem nada no ecrã a dizê-lo. Quem quer mesmo fechar
        usa a barra de tarefas."""
        self.raiz.iconify()


class DialogoDefinicoes(tk.Toplevel):
    """O que se escolhe UMA vez, quando se instala.

    **As impressoras escolhem-se de uma lista e nunca se escrevem à mão** — a
    lista é a do próprio Windows (`windows.listar_impressoras`). Um nome com
    uma letra trocada dava um programa que parece configurado e nunca imprime
    nada, e ninguém percebia porquê."""

    def __init__(self, pai, agente, ao_gravar):
        super().__init__(pai)
        self.agente = agente
        self.ao_gravar = ao_gravar
        self.title("Definições — " + TITULO)
        self.transient(pai)
        self.grab_set()

        d = dict(agente.definicoes)
        moldura = ttk.Frame(self, padding=16)
        moldura.pack(fill="both", expand=True)

        ttk.Label(moldura, text="Endereço do servidor").grid(row=0, column=0, sticky="w")
        self.servidor = ttk.Entry(moldura, width=46)
        self.servidor.insert(0, d.get("servidor") or "https://lisbonb.com")
        self.servidor.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 10))

        ttk.Label(
            moldura,
            text="Código de emparelhamento da loja (só na primeira vez)",
        ).grid(row=2, column=0, sticky="w")
        self.codigo = ttk.Entry(moldura, width=46)
        self.codigo.grid(row=3, column=0, columnspan=2, sticky="we")
        ttk.Label(
            moldura, foreground="#525252", wraplength=430, justify="left",
            text=("O gestor gera este código no portal, em Faturação → "
                  "Dispositivos. Vale 15 minutos e só serve uma vez. "
                  + ("Este PC já está emparelhado — deixe em branco para não mexer."
                     if d.get("device_token") else "")),
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 12))

        try:
            lista = windows.listar_impressoras()
        except Exception as e:  # noqa: BLE001
            lista = []
            ttk.Label(moldura, foreground=_COR_MAL, wraplength=430, justify="left",
                      text="Não foi possível ler as impressoras do Windows: %s" % e,
                      ).grid(row=5, column=0, columnspan=2, sticky="w")

        ttk.Label(moldura, text="Impressora da CAIXA (o talão do cliente)").grid(
            row=6, column=0, sticky="w", pady=(8, 0))
        self.caixa = ttk.Combobox(moldura, values=lista, width=44, state="readonly")
        self.caixa.set(nucleo.impressora_de(d, nucleo.CAIXA) or "")
        self.caixa.grid(row=7, column=0, columnspan=2, sticky="we")

        ttk.Label(moldura, text="Impressora da COZINHA (a ficha do pedido)").grid(
            row=8, column=0, sticky="w", pady=(10, 0))
        self.cozinha = ttk.Combobox(moldura, values=lista, width=44, state="readonly")
        self.cozinha.set(nucleo.impressora_de(d, nucleo.COZINHA) or "")
        self.cozinha.grid(row=9, column=0, columnspan=2, sticky="we")

        botoes = ttk.Frame(moldura)
        botoes.grid(row=10, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="left")
        ttk.Button(botoes, text="Gravar", command=self.gravar).pack(side="left", padx=(8, 0))

    def gravar(self):
        d = dict(self.agente.definicoes)
        d["servidor"] = self.servidor.get().strip()
        d["impressoras"] = {
            nucleo.CAIXA: self.caixa.get().strip(),
            nucleo.COZINHA: self.cozinha.get().strip(),
        }
        codigo = self.codigo.get().strip()
        if codigo:
            # **O emparelhamento acontece AQUI e não no ciclo**: a pessoa está
            # à frente e tem de saber já se o código serviu. Um código
            # recusado que só aparecesse como "sem ligação" daí a dez segundos
            # mandava-a procurar a internet em vez do código.
            try:
                resposta = nucleo.Servidor(d["servidor"]).emparelhar(codigo)
            except nucleo.ErroDoServidor as e:
                messagebox.showerror(
                    TITULO,
                    "Não foi possível emparelhar com esse código:\n\n%s\n\n"
                    "Códigos valem 15 minutos e só servem uma vez — peça outro "
                    "ao gestor." % e)
                return
            d["device_token"] = resposta.get("device_token")
            d["loja_id"] = resposta.get("loja_id")
            d["loja_nome"] = resposta.get("loja_nome")
        if not d.get("device_token"):
            messagebox.showwarning(
                TITULO, "Falta o código de emparelhamento — sem ele este PC não "
                        "pode ir buscar trabalho nenhum.")
            return
        nucleo.gravar_definicoes(d)
        self.ao_gravar(d)
        self.destroy()


def main():
    try:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            filename=nucleo.caminho_do_log(),
        )
    except Exception:  # noqa: BLE001
        # O log é conveniência; a impressão da loja não é. Um ficheiro que não
        # se consegue abrir (pasta sem permissões, disco cheio, a pen ainda
        # montada) não pode ser a razão de um `.exe` sem consola não fazer
        # RIGOROSAMENTE NADA ao duplo clique. Arranca-se sem ficheiro de log.
        logging.basicConfig(level=logging.INFO)
    definicoes = nucleo.ler_definicoes()
    agente = Agente(definicoes)

    raiz = tk.Tk()
    janela = Janela(raiz, agente)

    fio = threading.Thread(target=agente.correr, daemon=True)
    fio.start()

    if nucleo.esta_configurado(definicoes):
        # Configurado, arranca minimizado: é o dia normal, e o dia normal
        # deste programa é não se dar por ele.
        raiz.iconify()
    else:
        # Por configurar, abre as Definições logo. Sem isto, um `.exe` posto a
        # arrancar com o Windows aparecia minimizado, calado e por configurar
        # — e a loja ficava a achar que estava instalado.
        raiz.after(300, janela.abrir_definicoes)

    try:
        raiz.mainloop()
    finally:
        agente.parar()


if __name__ == "__main__":
    sys.exit(main())
