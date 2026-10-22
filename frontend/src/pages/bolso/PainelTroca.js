import React, { useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { desfazerTroca, trocar, trocarEntreSi } from '@/lib/bolso';
import {
  escaladosDoDia, intervaloCurto, mensagemDeErro, nomeCurto, nomeCurtoDaLoja, tituloDoDia,
} from '@/lib/calendario';
import { Calha, Segmento } from './partilhado';

// O painel de uma troca (desenho das trocas, §3; só administradores — o servidor recusa o resto):
// **trocar** uma pessoa da escala por outra (horas que se podem encurtar) ou os turnos inteiros
// de duas pessoas da escala, ou **desfazer** uma troca feita (todas as idas dela).
//
// `painel`: { modo: 'trocar', data, location_id, nomeDaLoja, sai: { user_id, nome, inicio, fim },
// turnoInteiro } | { modo: 'desfazer', troca_id, idas: [as idas da troca, de `dados.idas`] }.
// `dados` é o mês SEM o filtro de loja (quem está na escala noutra loja conta). Como o PainelIda:
// monta-se de novo a cada abertura, o servidor diz porque recusa e o painel fica aberto.

const rotulo = 'text-[13px] font-semibold text-muted-foreground';
const campo = 'mt-1 h-11 w-full rounded-lg border bg-background px-3 text-[15px] tabular-nums';
const pastilha = (escolhida) => `min-h-11 px-4 py-1 rounded-2xl text-left text-sm font-semibold focus-visible:outline-none
  focus-visible:ring-2 focus-visible:ring-ring ${escolhida ? 'bg-primary text-primary-foreground dark:text-background' : 'bg-muted text-foreground'}`;
const pequeno = (escolhida) => `block text-[12px] font-normal ${escolhida ? '' : 'text-muted-foreground'}`;

export default function PainelTroca({ painel, dados, onFechar, onGuardado }) {
  const { logout } = useAuth();
  const desfazer = painel.modo === 'desfazer';
  const data = desfazer ? painel.idas[0]?.data : painel.data;
  const sai = painel.sai || {};
  const [opcao, setOpcao] = useState('outra');
  const [escolhida, setEscolhida] = useState(null);
  const [inicio, setInicio] = useState(sai.inicio || '');
  const [fim, setFim] = useState(sai.fim || '');
  const [aGravar, setAGravar] = useState(false);
  const [erro, setErro] = useState(null);
  const [confirmar, setConfirmar] = useState(false);

  const escalados = desfazer ? [] : escaladosDoDia(dados, data, sai.user_id);
  const noutraLoja = (id) => escalados.find((e) => e.user_id === id && e.location_id !== painel.location_id);
  const outras = (dados.pessoas || []).filter((p) => p.id !== sai.user_id);
  const grupos = [['Gestores', outras.filter((p) => p.tipo === 'gestor')],
    ['Colaboradores', outras.filter((p) => p.tipo !== 'gestor')]];
  const turnos = opcao === 'turnos' && painel.turnoInteiro;

  const escolherOpcao = (o) => { setOpcao(o); setEscolhida(null); setErro(null); };

  // 401: o `lib/bolso.js` já tentou a re-entrada pelo Face ID → só `logout()`, como o PainelIda.
  const enviar = async (pedido) => {
    setAGravar(true);
    setErro(null);
    try {
      await pedido();
      onGuardado();
    } catch (e) {
      if (e?.response?.status === 401) { logout(); return; }
      setErro(mensagemDeErro(e));
      setAGravar(false);
      setConfirmar(false);
    }
  };
  const gravar = () => enviar(() => (turnos
    ? trocarEntreSi({ data, uma: sai.user_id, outra: escolhida })
    : trocar({ data, sai: sai.user_id, entra: escolhida, inicio, fim })));
  // Desfazer pede dois toques, como o Apagar da ida.
  const desfazerJa = () => {
    if (!confirmar) { setConfirmar(true); return; }
    enviar(() => desfazerTroca(painel.troca_id));
  };

  const titulo = desfazer ? 'Troca' : `Trocar ${sai.nome || ''}`.trim();
  const subtitulo = [data && tituloDoDia(data), !desfazer && painel.nomeDaLoja].filter(Boolean).join(' · ');
  const pronto = Boolean(escolhida && (turnos || (inicio && fim)) && !aGravar);

  return (
    <Sheet open onOpenChange={(aberto) => { if (!aberto) onFechar(); }}>
      <SheetContent
        side="bottom" hideClose aria-describedby={undefined}
        className="p-0 gap-0 rounded-t-2xl max-h-[92dvh] flex flex-col"
      >
        <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
          <div className="min-w-0 flex-1">
            <SheetTitle className="text-base truncate">{titulo}</SheetTitle>
            {subtitulo && <p className="text-[12px] text-muted-foreground truncate first-letter:uppercase">{subtitulo}</p>}
          </div>
          <SheetClose
            aria-label="Fechar"
            className="h-11 w-11 inline-flex items-center justify-center rounded-lg
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-5 w-5" />
          </SheetClose>
        </div>

        <div className="overflow-y-auto px-4 pt-3 pb-4 space-y-4 safe-area-inset-bottom">
          {desfazer ? (
            <>
              <ul className="divide-y rounded-xl border">
                {painel.idas.map((i) => (
                  <li key={i.id} className="px-3 py-2 text-[14px]">
                    <p className="font-semibold">{i.nome} no lugar de {nomeCurto(i.no_lugar_de)}</p>
                    <p className="text-[12px] text-muted-foreground tabular-nums">
                      {nomeCurtoDaLoja(i.loja)} · {intervaloCurto(i.inicio, i.fim)}
                    </p>
                  </li>
                ))}
              </ul>
              {painel.idas.length > 1 && <p className="text-[13px] text-muted-foreground">Desfazer apaga as duas.</p>}
            </>
          ) : (
            <>
              {painel.turnoInteiro && (
                <Calha>
                  <Segmento activo={opcao === 'outra'} onClick={() => escolherOpcao('outra')}>Outra pessoa</Segmento>
                  <Segmento activo={opcao === 'turnos'} onClick={() => escolherOpcao('turnos')}>Trocar turnos</Segmento>
                </Calha>
              )}
              {turnos ? (
                <fieldset>
                  <legend className={rotulo}>Com quem está na escala</legend>
                  {escalados.length === 0 && <p className="mt-1 text-[14px] text-muted-foreground">Mais ninguém na escala neste dia.</p>}
                  <div className="mt-1 flex flex-wrap gap-2">
                    {escalados.map((e) => (
                      <button
                        key={e.user_id} type="button" aria-pressed={escolhida === e.user_id}
                        onClick={() => setEscolhida(e.user_id)} className={pastilha(escolhida === e.user_id)}
                      >
                        {e.nome}
                        <span className={pequeno(escolhida === e.user_id)}>{nomeCurtoDaLoja(e.loja)} {intervaloCurto(e.inicio, e.fim)}</span>
                      </button>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <>
                  <fieldset>
                    <legend className={rotulo}>Quem vai</legend>
                    {grupos.map(([grupo, lista]) => (
                      lista.length > 0 && (
                        <div key={grupo} className="mt-1">
                          <p className="text-[11px] text-muted-foreground">{grupo}</p>
                          <div className="mt-1 flex flex-wrap gap-2">
                            {lista.map((p) => {
                              const escala = noutraLoja(p.id);
                              return (
                                <button
                                  key={p.id} type="button" aria-pressed={escolhida === p.id}
                                  onClick={() => setEscolhida(p.id)} className={pastilha(escolhida === p.id)}
                                >
                                  {p.nome}
                                  {escala && (
                                    <span className={pequeno(escolhida === p.id)}>
                                      na escala em {nomeCurtoDaLoja(escala.loja)} {intervaloCurto(escala.inicio, escala.fim)}
                                    </span>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )
                    ))}
                  </fieldset>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="block">
                      <span className={rotulo}>Das</span>
                      <input type="time" aria-label="Hora de início" value={inicio} onChange={(e) => setInicio(e.target.value)} className={campo} />
                    </label>
                    <label className="block">
                      <span className={rotulo}>Às</span>
                      <input type="time" aria-label="Hora de fim" value={fim} onChange={(e) => setFim(e.target.value)} className={campo} />
                    </label>
                  </div>
                </>
              )}
            </>
          )}

          {erro && <p role="alert" className="text-[14px] text-destructive-strong dark:text-destructive whitespace-pre-line">{erro}</p>}

          {desfazer ? (
            <button
              type="button" onClick={desfazerJa} disabled={aGravar}
              className="w-full h-12 rounded-xl border font-semibold text-destructive-strong dark:text-destructive disabled:opacity-50
                         inline-flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {aGravar && <Loader2 className="h-4 w-4 animate-spin" />}
              {confirmar ? 'Tocar de novo para desfazer' : 'Desfazer a troca'}
            </button>
          ) : (
            <button
              type="button" onClick={gravar} disabled={!pronto}
              className="w-full h-12 rounded-xl bg-primary text-primary-foreground dark:text-background font-semibold
                         inline-flex items-center justify-center gap-2 disabled:opacity-50
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {aGravar && <Loader2 className="h-4 w-4 animate-spin" />}
              {turnos ? 'Trocar turnos' : 'Trocar'}
            </button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
