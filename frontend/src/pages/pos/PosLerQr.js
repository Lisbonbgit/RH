import React, { useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';
import { AlertTriangle, Camera, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { lerQrDePontos, detalhesErroPos, MSG_PONTOS_SEM_RESPOSTA,
  recadoDeCodigoQrErrado } from '@/lib/pos';

// A janela «Ler QR do cliente» dos pontos L'Açaí. Dois caminhos para o MESMO
// pedido (`lib/pos.js::lerQrDePontos`):
//
//  · o leitor do POS HP, que é um teclado: escreve o código onde estiver o
//    foco e dá Enter. Por isso o campo abre COM o foco e vive dentro de um
//    <form> — o Enter de um campo num formulário é a submissão, sem apanhar
//    teclas à mão;
//  · a câmara do Surface: `getUserMedia` e o `jsQR` a descodificar as imagens.
//    O Chrome para Windows não tem `BarcodeDetector`.
//
// **A câmara desliga porque esta janela só existe montada enquanto está
// aberta** (o PosFinalizar desmonta-a ao fechar). O efeito que liga a câmara
// devolve a limpeza que pára as pistas, e desmontar corre-a sempre: fechar
// pela cruz, pelo «Fechar», por uma leitura bem sucedida ou por trocar de
// conta. Uma luz de câmara acesa no balcão depois de fechar a janela é o
// defeito que isto evita.

// A câmara escolhida NESTE PC. Um Surface tem duas e só uma está virada para o
// cliente; sem isto, a funcionária escolhia-a em cada venda. É do PC e não da
// sessão — `localStorage` —, e o ecrã funciona sem ele.
const CHAVE_CAMERA = 'pos_camera_do_qr';
const cameraGuardada = () => {
  try { return localStorage.getItem(CHAVE_CAMERA) || ''; } catch (e) { return ''; }
};
const guardarCamera = (id) => {
  try { localStorage.setItem(CHAVE_CAMERA, id); } catch (e) { /* sem storage */ }
};

// **O apito da leitura.** O leitor do POS HP apita sozinho; a câmara do Surface
// não apita nada, e sem som a funcionária fica a olhar para o ecrã à espera de
// perceber se leu — com a fila à frente. Um oscilador do browser em vez de um
// ficheiro de som: não há nada para carregar, nada que falhe a meio de uma venda
// e nada para copiar para 5 PCs. Falhar é silêncio, nunca um erro: um PC sem
// placa de som não pode partir a leitura.
const apitar = (hz, ms) => {
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    const ctx = new Audio();
    // O Chrome arranca-o SUSPENSO enquanto o documento não tiver tido um toque.
    // Aqui já teve (abrir a janela é um clique), mas a leitura pela câmara
    // chega sozinha — e um `resume()` a mais não custa nada.
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    const vol = ctx.createGain();
    osc.frequency.value = hz;
    vol.gain.value = 0.12;                 // o balcão é perto do cliente
    osc.connect(vol).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + ms / 1000);
    osc.onended = () => ctx.close();
  } catch (e) { /* sem som, a leitura vale na mesma */ }
};
const APITO_LIDO = () => apitar(1320, 110);      // agudo e curto: leu
const APITO_RECUSADO = () => apitar(220, 260);   // grave e longo: não leu

// **Abrir a câmara sozinha ao abrir a janela?** É do PC, como a escolha da
// câmara, e pela mesma razão: as 5 caixas não são iguais. Numa loja lê-se com o
// leitor do POS HP, que não tem câmara nenhuma — lá isto desliga-se uma vez e
// ninguém volta a pensar nisso. Nas outras poupa um clique por cliente, com a
// fila à frente.
//
// Ligado por omissão: é o que serve a maioria das caixas, e quem não quer
// desliga. Um PC sem `localStorage` comporta-se como ligado.
const CHAVE_AUTO = 'pos_camera_auto_do_qr';
const autoGuardado = () => {
  try { return localStorage.getItem(CHAVE_AUTO) !== '0'; } catch (e) { return true; }
};
const guardarAuto = (ligado) => {
  try { localStorage.setItem(CHAVE_AUTO, ligado ? '1' : '0'); } catch (e) { /* sem storage */ }
};

const MSG_SEM_CAMERA =
  'Não foi possível abrir a câmara. Confirme que o browser a pode usar, ou leia o QR com o leitor.';

// **`titulo` e `rotuloFechar` são a MESMA janela com outra pergunta.** Aberta
// pelo cartão do ecrã de pagamento, a pergunta é «Ler QR do cliente» e sai-se
// por «Fechar». Aberta sozinha ao carregar em FINALIZAR (`PosVenda`), a
// pergunta é «Quer atribuir os pontos?» e sai-se por «Não» — porque aí ninguém
// pediu para ler nada, e a operadora tem de ver num relance que carregar em
// «Não» segue para o pagamento. O que a janela FAZ é igual nos dois sítios.
export default function PosLerQr({ vendaId, onLigada, onFechar, titulo, rotuloFechar }) {
  const [codigo, setCodigo] = useState('');
  const [aLer, setALer] = useState(false);
  const [erro, setErro] = useState(null);
  // `null` = câmara desligada; '' = a câmara por omissão do sistema; outro
  // texto = o `deviceId` escolhido.
  //
  // **Abre JÁ**, sem esperar por um segundo toque: o cliente está à frente com o
  // telemóvel na mão e cada clique é tempo de fila. Quem lê com o leitor do POS
  // HP não perde nada — o campo continua com o foco e o leitor escreve lá.
  const [auto, setAuto] = useState(autoGuardado);
  const [camera, setCamera] = useState(() => (autoGuardado() ? cameraGuardada() : null));
  // A câmara foi aberta por alguém, ou abriu-se sozinha? Só o pedido EXPLÍCITO
  // merece uma mensagem de erro: numa caixa SEM câmara (o POS HP), a abertura
  // automática falharia em TODAS as vendas e o balcão levava com um aviso
  // vermelho a cada cliente, sobre uma coisa que nem estava a tentar fazer.
  const pedidaPorAlguem = useRef(false);
  const [cameras, setCameras] = useState([]);
  const video = useRef(null);
  // Uma leitura de cada vez. O `aLer` do estado chega tarde de mais para
  // decidir: dois Enter seguidos correm antes do render, e a câmara
  // descodifica várias imagens por segundo.
  const ocupado = useRef(false);
  // O último código que a CÂMARA mandou. Depois de uma recusa o QR continua à
  // frente dela, e sem isto cada imagem voltava a perguntar pelo mesmo código
  // gasto. O leitor não passa por aqui: quem volta a ler com ele fá-lo de
  // propósito.
  const ultimoDaCamera = useRef('');

  // **Uma janela fechada não fala mais.** O `await lerQrDePontos` pode demorar
  // (o servidor espera até 4 s pela app, o tecto do axios é 15 s) e o
  // desmontar não cancela pedido nenhum: o `ler` continua vivo no closure e
  // volta a um ecrã que já é outro. Sem esta ref, a resposta atrasada de uma
  // leitura que a operadora já desistiu de esperar — carregou em «Não», ou
  // fechou a janela — apitava um «leu» sobre um ecrã sem leitura nenhuma e
  // chamava `onLigada`: no ecrã de pagamento repunha um cliente removido, e na
  // pergunta do FINALIZAR guardava na conta uma ligação que ela recusou e
  // mandava o ecrã para trás POR CIMA de uma Fatura Simplificada já emitida.
  //
  // Só se cala o desfecho. O pedido segue e a ligação nasce do lado da app —
  // não há nada a desfazer, e uma ligação que nunca chega a uma fatura não
  // credita ninguém.
  const vivo = useRef(true);
  useEffect(() => () => { vivo.current = false; }, []);

  const ler = async (texto) => {
    const lido = String(texto || '').trim();
    if (!lido || ocupado.current) return;
    // O formato responde-se aqui: quem escreveu o código da CONTA («LA») em vez
    // do QR («LQ») merece ouvir isso, e não um «QR inválido» do servidor que o
    // deixa a tentar outra vez o mesmo.
    const recado = recadoDeCodigoQrErrado(lido);
    if (recado) { APITO_RECUSADO(); setErro(recado); setCodigo(''); return; }
    ocupado.current = true;
    setALer(true);
    setErro(null);
    try {
      const { ligacao_id: id, primeiro_nome } = await lerQrDePontos(vendaId, lido);
      if (!vivo.current) return;
      APITO_LIDO();
      onLigada({ id, primeiro_nome });
    } catch (error) {
      if (!vivo.current) return;
      // 404 e 503 trazem a frase do servidor; sem resposta nenhuma (rede,
      // tecto de espera) a consequência para o balcão é a do 503.
      APITO_RECUSADO();
      setErro(detalhesErroPos(error, MSG_PONTOS_SEM_RESPOSTA).mensagem);
      // O leitor escreve POR CIMA do que estiver no campo: com o código
      // recusado lá dentro, a leitura seguinte chegava colada a ele e era
      // recusada também — sempre.
      setCodigo('');
    } finally {
      ocupado.current = false;
      setALer(false);
    }
  };
  // O ciclo da câmara corre fora do render e ficava com o `ler` do primeiro.
  const lerAgora = useRef(ler);
  lerAgora.current = ler;

  useEffect(() => {
    if (camera === null) return undefined;
    let parado = false;
    let stream = null;
    let volta = 0;
    const tela = document.createElement('canvas');
    const parar = () => {
      if (stream) stream.getTracks().forEach((pista) => pista.stop());
    };

    const olhar = () => {
      if (parado) return;
      const v = video.current;
      if (v && v.videoWidth > 0) {
        tela.width = v.videoWidth;
        tela.height = v.videoHeight;
        const ctx = tela.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(v, 0, 0, tela.width, tela.height);
        const imagem = ctx.getImageData(0, 0, tela.width, tela.height);
        // O QR da app é preto sobre branco: não vale a pena procurar o inverso.
        const achado = jsQR(imagem.data, tela.width, tela.height, { inversionAttempts: 'dontInvert' });
        if (achado?.data && achado.data !== ultimoDaCamera.current) {
          ultimoDaCamera.current = achado.data;
          lerAgora.current(achado.data);
        }
      }
      volta = requestAnimationFrame(olhar);
    };

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: camera ? { deviceId: { exact: camera } } : true,
        });
        // Fechou-se a janela enquanto o browser abria a câmara: a limpeza já
        // correu, sem pistas para parar — param-se aqui.
        if (parado) { parar(); return; }
        video.current.srcObject = stream;
        await video.current.play();
        // Os nomes das câmaras só vêm DEPOIS da autorização.
        const todas = await navigator.mediaDevices.enumerateDevices();
        if (parado) return;
        setCameras(todas.filter((d) => d.kind === 'videoinput'));
        olhar();
      } catch (e) {
        if (parado) return;
        parar();
        // Uma câmara guardada que já não existe não pode prender a janela
        // nesta mensagem para sempre.
        if (camera) guardarCamera('');
        if (pedidaPorAlguem.current) setErro(MSG_SEM_CAMERA);
        setCamera(null);
      }
    })();

    return () => {
      parado = true;
      if (volta) cancelAnimationFrame(volta);
      parar();
    };
  }, [camera]);

  return (
    <Dialog open onOpenChange={(aberta) => { if (!aberta) onFechar(); }}>
      {/* **Não se sai daqui por engano.** Por omissão o Radix fecha a janela
          ao primeiro toque FORA dela — e a cortina do diálogo cobre o ecrã
          todo, o botão FINALIZAR incluído. Numa caixa onde se carrega duas
          vezes por hábito, o segundo toque do duplo-clique aterrava na cortina
          e despachava a pergunta dos pontos em silêncio: a operadora via o
          ecrã de pagamento e nunca saberia que lhe tinha sido perguntada
          alguma coisa. As saídas ficam as que se vêem — ler o QR, o botão de
          baixo, a cruz e o ESC. */}
      <DialogContent className="max-w-lg" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{titulo || 'Ler QR do cliente'}</DialogTitle>
          <DialogDescription>
            O cliente abre a app L'Açaí e toca em «Mostrar QR na caixa» antes de pagar.
          </DialogDescription>
        </DialogHeader>

        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ler(codigo); }}>
          <Input
            id="qr-dos-pontos"
            value={codigo}
            onChange={(e) => setCodigo(e.target.value)}
            autoFocus
            autoComplete="off"
            // **Sem teclado do Windows por cima da câmara.** O campo mantém o
            // FOCO — o leitor do POS é um teclado e continua a escrever nele —,
            // mas com a câmara aberta diz-se ao browser que não há aqui nada
            // para escrever à mão, e o teclado no ecrã não salta. Fechada a
            // câmara (a caixa do leitor), volta ao normal.
            inputMode={camera === null ? undefined : 'none'}
            placeholder="Leia o QR da app com o leitor…"
            className="h-14 flex-1 font-mono text-lg"
          />
          <Button type="submit" className="h-14 px-6" disabled={aLer || !codigo.trim()}>
            {aLer ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Ler'}
          </Button>
        </form>

        {erro && (
          <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm">{erro}</p>
          </div>
        )}

        {camera === null ? (
          <Button
            type="button"
            variant="outline"
            className="h-12 w-full"
            onClick={() => {
              pedidaPorAlguem.current = true;
              setErro(null);
              setCamera(cameraGuardada());
            }}
          >
            <Camera className="h-5 w-5 mr-2" />
            Usar câmara
          </Button>
        ) : (
          <div className="space-y-2">
            <video ref={video} muted playsInline className="w-full rounded-xl bg-black" />
            {cameras.length > 1 && (
              <select
                aria-label="Câmara"
                value={camera}
                onChange={(e) => { guardarCamera(e.target.value); setCamera(e.target.value); }}
                className="h-12 w-full rounded-md border bg-background px-3"
              >
                <option value="">Câmara por omissão</option>
                {cameras.map((c, i) => (
                  <option key={c.deviceId || i} value={c.deviceId}>
                    {c.label || `Câmara ${i + 1}`}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {/* A preferência DESTE PC. Fica sempre à vista — escondê-la atrás da
            câmara aberta deixava-a inalcançável exactamente na caixa onde ela
            interessa, que é aquela onde a câmara não abre. */}
        <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={auto}
            onChange={(e) => {
              const ligado = e.target.checked;
              setAuto(ligado);
              guardarAuto(ligado);
              // Ligar aqui abre já, para se ver que ficou ligado. Desligar não
              // fecha o que está aberto: a leitura a decorrer não se interrompe.
              if (ligado && camera === null) {
                pedidaPorAlguem.current = true;
                setErro(null);
                setCamera(cameraGuardada());
              }
            }}
            data-testid="qr-camera-auto"
            className="h-4 w-4"
          />
          Abrir a câmara automaticamente nesta caixa
        </label>

        <Button type="button" variant="outline" className="h-12 w-full" onClick={onFechar}>
          {rotuloFechar || 'Fechar'}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
