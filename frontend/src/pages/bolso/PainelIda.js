import React, { useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { apagarIda, criarIdas, mudarIda } from '@/lib/bolso';
import {
  feriadosDoMes, mensagemDeErro, outrosDiasComBuraco, pessoasIniciais, textoDoAtalho, tituloDoDia,
} from '@/lib/calendario';
import { GrelhaDoMes } from './partilhado';

// O painel de uma ida: **tapar** um buraco (a loja e as horas vêm do buraco), **marcar** uma
// ida de raiz, ou **editar** uma que já existe (Guardar e Apagar; um dia, uma pessoa).
//
// O servidor é que decide se a ida é possível (sobreposição, férias, loja fechada) e diz
// porquê; o painel mostra esse texto tal como vem e fica aberto para se corrigir.
//
// `painel`: { modo: 'tapar' | 'marcar' | 'editar', nomeDaLoja?, inicial: { datas, location_id,
// inicio, fim, user_ids?, ida_id?, nome? } }. Monta-se de novo a cada abertura (o ecrã dá-lhe
// uma `key`), por isso o estado começa sempre no `inicial`. No `marcar` as horas chegam vazias
// e a loja também (desenho, secção 4: «o mesmo painel vazio, com a loja a escolher»), ou a do
// filtro de loja do ecrã; as horas enche-as o painel, com o horário dessa loja (`horarioDe`).
//
// Vermelho de texto: `text-destructive-strong dark:text-destructive`, o par que passa sobre o
// fundo do painel nos dois temas (6,2:1 e 4,7:1). O `text-destructive` sozinho dá 3,8:1 no
// claro; o `-strong` do escuro foi afinado para texto BRANCO sobre pastilha e dá 3,0:1 como
// texto (index.css, `--destructive-strong`).

const MAXIMO_DE_PESSOAS = 2; // o servidor recusa mais (POST /api/bolso/calendario/idas)

export default function PainelIda({ painel, dados, hoje, onFechar, onGuardado }) {
  const { logout } = useAuth();
  const { modo, inicial } = painel;
  const editar = modo === 'editar';
  // O horário da loja num dia, se estiver aberta. Uma só regra para as horas da loja que vem
  // no `inicial` e da que se escolher depois (`escolherLoja`).
  const horarioDe = (id, iso) => (dados.dias || []).find((d) => d.data === iso)
    ?.lojas.find((l) => l.location_id === id && l.estado === 'aberta');
  const base = (inicial.datas || [])[0];
  const daLoja = horarioDe(inicial.location_id, base);
  const [loja, setLoja] = useState(inicial.location_id || '');
  const [pessoas, setPessoas] = useState(() => inicial.user_ids || pessoasIniciais(dados));
  const [inicio, setInicio] = useState(inicial.inicio || daLoja?.abre || '');
  const [fim, setFim] = useState(inicial.fim || daLoja?.fecha || '');
  const [datas, setDatas] = useState(inicial.datas || []);
  const [aGravar, setAGravar] = useState(false);
  const [erro, setErro] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [confirmarApagar, setConfirmarApagar] = useState(false);

  const nomeDaLoja = (dados.lojas || []).find((l) => l.id === loja)?.nome || '';
  const outros = editar ? [] : outrosDiasComBuraco(dados, base, loja, inicio, fim).filter((d) => !datas.includes(d));
  const quantas = datas.length * pessoas.length;
  const pronto = Boolean(loja && inicio && fim && quantas > 0 && !aGravar);
  const gestores = (dados.pessoas || []).filter((p) => p.tipo === 'gestor');
  const colaboradores = (dados.pessoas || []).filter((p) => p.tipo !== 'gestor');

  const tocarPessoa = (id) => {
    setAviso(null);
    if (editar) { setPessoas([id]); return; }
    if (pessoas.includes(id)) { setPessoas(pessoas.filter((p) => p !== id)); return; }
    if (pessoas.length >= MAXIMO_DE_PESSOAS) { setAviso('No máximo duas pessoas de cada vez.'); return; }
    setPessoas([...pessoas, id]);
  };
  const tocarDia = (iso) => {
    if (editar) { setDatas([iso]); return; }
    setDatas(datas.includes(iso) ? datas.filter((d) => d !== iso) : [...datas, iso].sort());
  };

  // No `marcar`, escolher a loja enche as horas com o horário dela no dia (o primeiro
  // escolhido); trocar de loja volta a enchê-las enquanto forem as da loja anterior. Horas
  // mexidas à mão ficam.
  const escolherLoja = (id) => {
    const antes = horarioDe(loja, datas[0]);
    const nova = horarioDe(id, datas[0]);
    const porMexer = (!inicio && !fim) || (antes && inicio === antes.abre && fim === antes.fecha);
    setLoja(id);
    if (modo === 'marcar' && nova && porMexer) { setInicio(nova.abre); setFim(nova.fecha); }
  };

  // 401: o `lib/bolso.js` já tentou a re-entrada pelo Face ID e não deu → login normal
  // (desenho §5.4), pela mesma porta do ecrã. Mostrar o erro deixava a pessoa num painel
  // sem sessão.
  const falhou = (e) => {
    if (e?.response?.status === 401) { logout(); return; }
    setErro(mensagemDeErro(e));
    setAGravar(false);
    setConfirmarApagar(false);
  };

  const gravar = async () => {
    setAGravar(true);
    setErro(null);
    try {
      if (editar) {
        await mudarIda(inicial.ida_id, { data: datas[0], location_id: loja, user_id: pessoas[0], inicio, fim });
      } else {
        await criarIdas({ datas, location_id: loja, user_ids: pessoas, inicio, fim });
      }
      onGuardado();
    } catch (e) {
      falhou(e);
    }
  };

  // Apagar pede dois toques: é irreversível e o botão fica ao lado do Guardar.
  const apagar = async () => {
    if (!confirmarApagar) { setConfirmarApagar(true); return; }
    setAGravar(true);
    setErro(null);
    try {
      await apagarIda(inicial.ida_id);
      onGuardado();
    } catch (e) {
      falhou(e);
    }
  };

  const titulo = editar
    ? `Ida de ${inicial.nome || ''}`.trim()
    : modo === 'tapar' ? `Tapar ${painel.nomeDaLoja || nomeDaLoja}` : 'Marcar ida';
  const rotulo = 'text-[13px] font-semibold text-muted-foreground';
  const campo = 'mt-1 h-11 w-full rounded-lg border bg-background px-3 text-[15px] tabular-nums';

  return (
    <Sheet open onOpenChange={(aberto) => { if (!aberto) onFechar(); }}>
      <SheetContent
        side="bottom" hideClose aria-describedby={undefined}
        className="p-0 gap-0 rounded-t-2xl max-h-[92dvh] flex flex-col"
      >
        <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
          <div className="min-w-0 flex-1">
            <SheetTitle className="text-base truncate">{titulo}</SheetTitle>
            {base && <p className="text-[12px] text-muted-foreground truncate first-letter:uppercase">{tituloDoDia(base)}</p>}
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
          <label className="block">
            <span className={rotulo}>Loja</span>
            <select aria-label="Loja" value={loja} onChange={(e) => escolherLoja(e.target.value)} className={campo}>
              {!loja && <option value="">Escolher…</option>}
              {(dados.lojas || []).map((l) => <option key={l.id} value={l.id}>{l.nome}</option>)}
            </select>
          </label>

          <fieldset>
            <legend className={rotulo}>{editar ? 'Pessoa' : 'Pessoas'}</legend>
            {[['Gestores', gestores], ['Colaboradores', colaboradores]].map(([grupo, lista]) => (
              lista.length > 0 && (
                <div key={grupo} className="mt-1">
                  <p className="text-[11px] text-muted-foreground">{grupo}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {lista.map((p) => (
                      <button
                        key={p.id} type="button" aria-pressed={pessoas.includes(p.id)} onClick={() => tocarPessoa(p.id)}
                        className={`h-11 px-4 rounded-full text-sm font-semibold focus-visible:outline-none
                                    focus-visible:ring-2 focus-visible:ring-ring ${pessoas.includes(p.id)
                          ? 'bg-primary text-primary-foreground dark:text-background' : 'bg-muted text-foreground'}`}
                      >
                        {p.nome}
                      </button>
                    ))}
                  </div>
                </div>
              )
            ))}
            {aviso && <p className="mt-1 text-[12px] text-warning-strong">{aviso}</p>}
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

          <div>
            <p className={rotulo}>{editar ? 'Dia' : 'Dias'}</p>
            <div className="mt-1 rounded-xl border p-1">
              <GrelhaDoMes
                ano={dados.ano} mes={dados.mes} hoje={hoje} escolhidos={datas} onTocar={tocarDia}
                feriados={feriadosDoMes(dados)}
              />
            </div>
            {outros.length > 0 && (
              <button
                type="button" onClick={() => setDatas([...new Set([...datas, ...outros])].sort())}
                className="mt-2 w-full min-h-11 rounded-lg border px-3 py-2 text-left text-[14px] font-semibold
                           active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {textoDoAtalho(base, nomeDaLoja)}
              </button>
            )}
          </div>

          {erro && <p role="alert" className="text-[14px] text-destructive-strong dark:text-destructive whitespace-pre-line">{erro}</p>}

          <div className="flex gap-2">
            {editar && (
              <button
                type="button" onClick={apagar} disabled={aGravar}
                className="h-12 px-4 rounded-xl border font-semibold text-destructive-strong dark:text-destructive disabled:opacity-50
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {confirmarApagar ? 'Tocar de novo para apagar' : 'Apagar'}
              </button>
            )}
            <button
              type="button" onClick={gravar} disabled={!pronto}
              className="flex-1 h-12 rounded-xl bg-primary text-primary-foreground dark:text-background font-semibold
                         inline-flex items-center justify-center gap-2 disabled:opacity-50
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {aGravar && <Loader2 className="h-4 w-4 animate-spin" />}
              {editar ? 'Guardar' : `Marcar ${quantas} ${quantas === 1 ? 'ida' : 'idas'}`}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
