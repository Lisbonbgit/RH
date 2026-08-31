import React, { useState, useEffect, useCallback } from 'react';
import {
  getEstoqueProdutos, criarEstoqueProduto, editarEstoqueProduto, apagarEstoqueProduto, mergeEstoqueProdutos,
} from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Badge } from '../../../components/ui/badge';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../components/ui/dialog';
import { Package, Plus, Trash2, Combine } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const MARCAS = [['lacai', "L'açaí"], ['lenha_brasa', 'Lenha e Brasa'], ['purple', 'Purple House']];
const MEDIDAS = ['kg', 'L', 'un', 'caixa'];
const PESO_UNIDADES = ['g', 'kg', 'ml', 'L'];
const parseNum = (v) => { const n = Number(String(v ?? '').trim().replace(',', '.')); return Number.isFinite(n) ? n : NaN; };
const temPeso = (m) => m === 'un' || m === 'caixa';

// Reduz uma imagem para ~128px (JPEG) → data URL, como a app do estoque (≤150KB).
function fileToFoto(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onload = () => { img.src = reader.result; };
    reader.onerror = reject;
    img.onload = () => {
      const max = 128;
      const escala = Math.min(1, max / Math.max(img.width, img.height));
      const w = Math.round(img.width * escala), h = Math.round(img.height * escala);
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      c.getContext('2d').drawImage(img, 0, 0, w, h);
      resolve(c.toDataURL('image/jpeg', 0.8));
    };
    img.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function ProdutoDialog({ marca, produto, onClose, onSaved, onDelete }) {
  const editar = !!produto;
  const [nome, setNome] = useState(produto?.nome || '');
  const [medida, setMedida] = useState(produto?.unidade_medida || 'kg');
  const [fornecedor, setFornecedor] = useState(produto?.fornecedor || '');
  const [codigo, setCodigo] = useState(produto?.codigo_barras || '');
  const [pesoValor, setPesoValor] = useState(produto?.peso_valor != null ? String(produto.peso_valor) : '');
  const [pesoUnidade, setPesoUnidade] = useState(produto?.peso_unidade || 'g');
  const [foto, setFoto] = useState(produto?.foto || null);
  const [ilimitado, setIlimitado] = useState(produto?.ilimitado || false);
  const [saving, setSaving] = useState(false);

  async function escolherFoto(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    try { setFoto(await fileToFoto(f)); } catch { toast.error('Não foi possível ler a imagem.'); }
  }

  async function guardar() {
    if (!nome.trim()) return toast.error('Indica o nome do produto.');
    const pesoOk = temPeso(medida) && parseNum(pesoValor) > 0;
    const base = {
      nome: nome.trim(),
      unidade_medida: medida,
      fornecedor: fornecedor.trim(),
      codigo_barras: codigo.trim(),
    };
    if (pesoOk) { base.peso_valor = parseNum(pesoValor); base.peso_unidade = pesoUnidade; }
    else if (editar) { base.peso_valor = 0; } // limpa o peso
    base.ilimitado = ilimitado;
    if (foto !== (produto?.foto || null)) base.foto = foto || '';
    setSaving(true);
    try {
      if (editar) {
        await editarEstoqueProduto(produto.id, base);
        toast.success('Produto atualizado.');
      } else {
        await criarEstoqueProduto({ ...base, marca });
        toast.success('Produto criado.');
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível guardar.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editar ? 'Editar produto' : 'Novo produto'}</DialogTitle>
          <DialogDescription>{editar ? produto.nome : `Novo produto no catálogo.`}</DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label>Nome</Label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: Polpa de açaí" />
        </div>

        <div className="space-y-1.5">
          <Label>Medida</Label>
          <Select value={medida} onValueChange={setMedida}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{MEDIDAS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
          </Select>
        </div>

        {temPeso(medida) && (
          <div className="space-y-1.5">
            <Label>Peso por unidade (opcional)</Label>
            <div className="flex items-center gap-2">
              <Input inputMode="decimal" value={pesoValor} onChange={(e) => setPesoValor(e.target.value)} className="w-24" placeholder="ex.: 4,5" />
              <Select value={pesoUnidade} onValueChange={setPesoUnidade}>
                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                <SelectContent>{PESO_UNIDADES.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
        )}

        <div className="space-y-1.5">
          <Label>Fornecedor (opcional)</Label>
          <Input value={fornecedor} onChange={(e) => setFornecedor(e.target.value)} placeholder="ex.: Makro" />
        </div>

        <div className="space-y-1.5">
          <Label>Código de barras (opcional)</Label>
          <Input value={codigo} onChange={(e) => setCodigo(e.target.value)} placeholder="scan no telemóvel, ou à mão" />
        </div>

        <label className="flex items-start gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={ilimitado} onChange={(e) => setIlimitado(e.target.checked)} className="h-4 w-4 mt-0.5" />
          <span>
            Artigo ilimitado (não conta no stock)
            <span className="block text-[11px] text-muted-foreground">Ex.: água — entra nas receitas mas nunca falta nem se desconta.</span>
          </span>
        </label>

        <div className="space-y-1.5">
          <Label>Foto (opcional)</Label>
          <div className="flex items-center gap-3">
            {foto ? <img src={foto} alt="" className="h-12 w-12 rounded-lg object-cover" /> : <div className="h-12 w-12 rounded-lg bg-muted" />}
            <input type="file" accept="image/*" onChange={escolherFoto} className="text-sm" />
            {foto && <Button type="button" variant="ghost" size="sm" onClick={() => setFoto('')}>Remover</Button>}
          </div>
        </div>

        <Button onClick={guardar} disabled={saving} className="w-full mt-2">
          {saving ? 'A guardar…' : (editar ? 'Guardar alterações' : 'Criar produto')}
        </Button>
        {editar && (
          <Button type="button" variant="ghost" className="w-full text-destructive" disabled={saving} onClick={onDelete}>
            <Trash2 className="h-4 w-4 mr-1" /> Apagar produto
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function EstoqueCatalogo() {
  const [marca, setMarca] = useState('lacai');
  const [produtos, setProdutos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busca, setBusca] = useState('');
  const [dialog, setDialog] = useState(null); // {produto} edit | {} novo
  const [modoJuntar, setModoJuntar] = useState(false);
  const [selecionados, setSelecionados] = useState([]); // ids, o 1º é o principal

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getEstoqueProdutos(marca);
      setProdutos(r.data || []);
    } catch {
      toast.error('Não foi possível carregar o catálogo.');
      setProdutos([]);
    } finally {
      setLoading(false);
    }
  }, [marca]);

  useEffect(() => { load(); setModoJuntar(false); setSelecionados([]); }, [load]);

  const filtrados = produtos.filter((p) => !busca.trim() || (p.nome || '').toLowerCase().includes(busca.trim().toLowerCase()));

  async function apagar(p) {
    if (!window.confirm(`Apagar "${p.nome}"? Isto remove-o do catálogo e o seu stock/histórico em todas as lojas.`)) return;
    try {
      await apagarEstoqueProduto(p.id);
      toast.success('Produto apagado.');
      setDialog(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível apagar.');
    }
  }

  function toggleSel(id) {
    setSelecionados((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  }

  async function juntar() {
    if (selecionados.length < 2) return toast.error('Escolhe o principal e pelo menos um duplicado.');
    const [principal, ...duplicados] = selecionados;
    const nomeP = produtos.find((p) => p.id === principal)?.nome;
    if (!window.confirm(`Juntar ${duplicados.length} produto(s) em "${nomeP}"? O stock soma-se e os outros são apagados.`)) return;
    try {
      await mergeEstoqueProdutos({ principal_id: principal, duplicados });
      toast.success('Produtos juntos.');
      setModoJuntar(false); setSelecionados([]);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Não foi possível juntar.');
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Estoque · Catálogo" subtitle="Os produtos de cada marca — criar, editar, apagar e juntar duplicados.">
        <Select value={marca} onValueChange={setMarca}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent>{MARCAS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
        </Select>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Procurar produto…" value={busca} onChange={(e) => setBusca(e.target.value)} className="w-56" />
        <div className="flex-1" />
        {modoJuntar ? (
          <>
            <span className="text-sm text-muted-foreground">
              {selecionados.length === 0 ? 'Escolhe o principal (1.º) e os duplicados.' : `Principal: ${produtos.find((p) => p.id === selecionados[0])?.nome} · ${selecionados.length - 1} duplicado(s)`}
            </span>
            <Button variant="outline" onClick={() => { setModoJuntar(false); setSelecionados([]); }}>Cancelar</Button>
            <Button onClick={juntar} disabled={selecionados.length < 2}>Juntar</Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={() => setModoJuntar(true)}><Combine className="h-4 w-4 mr-1" /> Juntar duplicados</Button>
            <Button onClick={() => setDialog({})}><Plus className="h-4 w-4 mr-1" /> Novo produto</Button>
          </>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : filtrados.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">{produtos.length === 0 ? 'Sem produtos nesta marca.' : 'Nenhum produto corresponde à procura.'}</p>
          ) : (
            <div className="divide-y">
              {filtrados.map((p) => {
                const idx = selecionados.indexOf(p.id);
                return (
                  <div
                    key={p.id}
                    className="p-4 flex items-center gap-3 cursor-pointer hover:bg-muted/50 transition-colors"
                    onClick={() => modoJuntar ? toggleSel(p.id) : setDialog({ produto: p })}
                    role="button"
                    tabIndex={0}
                  >
                    {modoJuntar && (
                      <div className={`h-6 w-6 rounded-full border flex items-center justify-center text-xs shrink-0 ${idx >= 0 ? 'bg-primary text-primary-foreground border-primary' : 'border-input'}`}>
                        {idx === 0 ? '★' : idx > 0 ? idx : ''}
                      </div>
                    )}
                    {p.foto ? (
                      <img src={p.foto} alt="" className="h-9 w-9 rounded-lg object-cover shrink-0" />
                    ) : (
                      <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                        <Package className="h-4 w-4 text-muted-foreground" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{p.nome}</p>
                      <p className="text-xs text-muted-foreground">
                        {p.unidade_medida}
                        {p.peso_valor ? ` · ${p.peso_valor} ${p.peso_unidade || ''}` : ''}
                        {p.fornecedor ? ` · ${p.fornecedor}` : ''}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {p.ilimitado && <Badge variant="secondary">ilimitado</Badge>}
                      {p.tem_receita && <Badge variant="outline">receita</Badge>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {dialog && (
        <ProdutoDialog
          marca={marca}
          produto={dialog.produto}
          onClose={() => setDialog(null)}
          onSaved={load}
          onDelete={() => apagar(dialog.produto)}
        />
      )}
    </div>
  );
}
