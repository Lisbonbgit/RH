import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  getProdutos, getProdutosSemIva, getProdutosSemVendus, criarProduto, editarProduto, apagarProduto, mudarEstadoProduto,
  getCategorias, getSubcategorias, getGrupos, importarVendus,
  carregarFotoProduto, urlDaFotoProduto,
  detalhesErro, temMaisDe2CasasDecimais,
} from '../../../lib/faturacao';
import { reduzirImagem, TIPOS_ACEITES } from '../../../lib/fotos';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import { Checkbox } from '../../../components/ui/checkbox';
import { Alert, AlertTitle, AlertDescription } from '../../../components/ui/alert';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import {
  Package, Plus, Pencil, Trash2, AlertTriangle, RefreshCw, Search, X, Link2,
  ImagePlus, Loader2, ImageOff,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const NOME_MAX = 120;

// Códigos do Vendus (faturacao/precos.py:_TAXAS) — a mesma fonte de verdade
// que faz a venda. Não se inventa um código novo aqui.
const TAXA_OPCOES = [
  { value: 'NOR', label: 'NOR — 23% (Normal)' },
  { value: 'INT', label: 'INT — 13% (Intermédia)' },
  { value: 'RED', label: 'RED — 6% (Reduzida)' },
  { value: 'ISE', label: 'ISE — Isento (0%)' },
];
const TAXA_LABEL = Object.fromEntries(TAXA_OPCOES.map((t) => [t.value, t.label]));

const fmtEUR = (n) => new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

const emptyForm = {
  nome: '', categoria_id: '', subcategoria_id: '', preco: '', preco_custo: '', tax_id: '', foto_url: '', grupos_personalizacao: [], ativo: true,
};

export default function FatProdutos() {
  const [produtos, setProdutos] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [grupos, setGrupos] = useState([]);
  const [semIva, setSemIva] = useState([]);
  const [semVendus, setSemVendus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [togglingId, setTogglingId] = useState(null);

  const [aCarregarFoto, setACarregarFoto] = useState(false);
  const inputFoto = useRef(null);

  const [filtroTexto, setFiltroTexto] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('');
  const [somenteSemIva, setSomenteSemIva] = useState(false);
  const [somenteSemVendus, setSomenteSemVendus] = useState(false);
  const tabelaRef = useRef(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [importResultOpen, setImportResultOpen] = useState(false);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [p, c, g, s, sub, sv] = await Promise.all([
        getProdutos(), getCategorias(), getGrupos(), getProdutosSemIva(), getSubcategorias(),
        getProdutosSemVendus()]);
      setProdutos(p.data || []);
      setCategorias(c.data || []);
      setSubcategorias(sub.data || []);
      setGrupos(g.data || []);
      setSemIva(s.data || []);
      setSemVendus(sv.data || []);
    } catch (error) {
      toast.error('Erro ao carregar produtos');
    } finally {
      setLoading(false);
    }
  };

  const categoriasPorId = useMemo(() => Object.fromEntries(categorias.map((c) => [c.id, c])), [categorias]);
  const gruposPorId = useMemo(() => Object.fromEntries(grupos.map((g) => [g.id, g])), [grupos]);
  const semIvaIds = useMemo(() => new Set(semIva.map((p) => p.id)), [semIva]);
  // Quem está ligado ao Vendus é o SERVIDOR que diz, com a mesma função que
  // monta o `id` da linha da fatura. O ecrã não repete a regra: um
  // `vendus_ref` escrito à mão com lixo lá dentro é verdadeiro para o
  // JavaScript e nada para a emissão, e o ícone mentia exactamente aí.
  const semVendusIds = useMemo(() => new Set(semVendus.map((p) => p.id)), [semVendus]);
  // Os que se vendem mesmo. Um produto desligado não está na grelha do POS,
  // por isso não cria artigo nenhum no Vendus — contá-lo no aviso era
  // assustar por causa de coisa que ninguém vende.
  const semVendusAtivos = useMemo(
    () => semVendus.filter((p) => p.ativo !== false), [semVendus]);

  const produtosFiltrados = useMemo(() => {
    const texto = filtroTexto.trim().toLowerCase();
    return produtos.filter((p) => {
      if (filtroCategoria && p.categoria_id !== filtroCategoria) return false;
      if (texto && !p.nome.toLowerCase().includes(texto)) return false;
      if (somenteSemIva && !semIvaIds.has(p.id)) return false;
      if (somenteSemVendus && !semVendusIds.has(p.id)) return false;
      return true;
    });
  }, [produtos, filtroCategoria, filtroTexto, somenteSemIva, semIvaIds,
      somenteSemVendus, semVendusIds]);

  const verProdutosSemIva = () => {
    setSomenteSemIva(true);
    setSomenteSemVendus(false);
    setFiltroCategoria('');
    setFiltroTexto('');
    tabelaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const verProdutosSemVendus = () => {
    setSomenteSemVendus(true);
    setSomenteSemIva(false);
    setFiltroCategoria('');
    setFiltroTexto('');
    tabelaRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // --- Formulário de produto ---

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setFieldErrors({});
    setDialogOpen(true);
  };

  const openEdit = (produto) => {
    setEditing(produto);
    setForm({
      nome: produto.nome || '',
      categoria_id: produto.categoria_id || '',
      subcategoria_id: produto.subcategoria_id || '',
      preco_custo: produto.preco_custo === null || produto.preco_custo === undefined
        ? '' : String(produto.preco_custo),
      preco: produto.preco != null ? String(produto.preco) : '',
      tax_id: produto.tax_id || '',
      foto_url: produto.foto_url || '',
      grupos_personalizacao: produto.grupos_personalizacao || [],
      ativo: produto.ativo !== false,
    });
    setFieldErrors({});
    setDialogOpen(true);
  };

  // **O carregamento da foto acontece AQUI, e não no Gravar.** O ficheiro sobe
  // assim que é escolhido e o que fica no formulário é o ENDEREÇO que o
  // servidor devolveu — a partir daí é um `foto_url` como qualquer outro, e o
  // Gravar não tem de saber que houve um ficheiro. É também o que deixa a
  // pré-visualização mostrar a foto REAL, servida pelo servidor, e não um
  // `blob:` local que desaparece ao fechar o diálogo.
  //
  // Uma foto carregada e o produto não gravado a seguir deixa um ficheiro
  // órfão no disco. É o preço desta ordem, e é pequeno (uma imagem de 60 KB);
  // a alternativa — segurar o ficheiro até ao Gravar — obrigava o formulário a
  // carregar o `File` inteiro e a tratar o erro do envio no meio do erro da
  // gravação, com o dono à espera.
  const escolherFoto = async (ficheiro) => {
    if (!ficheiro) return;
    setACarregarFoto(true);
    try {
      const reduzida = await reduzirImagem(ficheiro);
      const { data } = await carregarFotoProduto(reduzida);
      setForm((prev) => ({ ...prev, foto_url: data.foto_url }));
      toast.success('Foto carregada');
    } catch (error) {
      // A frase do servidor, e não uma nossa: é ele que sabe se recusou por
      // tamanho ou por não ser uma imagem, e as duas pedem coisas diferentes.
      toast.error(detalhesErro(error, 'Não foi possível carregar a foto.').mensagem);
    } finally {
      setACarregarFoto(false);
      // O mesmo ficheiro escolhido duas vezes seguidas não dispara `onChange`
      // se o valor do campo não for limpo — e a segunda tentativa, depois de
      // um erro, é exactamente o que a pessoa faz a seguir.
      if (inputFoto.current) inputFoto.current.value = '';
    }
  };

  const toggleGrupo = (id) => {
    setForm((prev) => ({
      ...prev,
      grupos_personalizacao: prev.grupos_personalizacao.includes(id)
        ? prev.grupos_personalizacao.filter((g) => g !== id)
        : [...prev.grupos_personalizacao, id],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nome = form.nome.trim();
    const erros = {};
    if (!nome) erros.nome = 'Indique o nome do produto';
    else if (nome.length > NOME_MAX) erros.nome = `O nome não pode ter mais de ${NOME_MAX} caracteres`;
    if (!form.categoria_id) erros.categoria_id = 'Escolha a categoria';
    const preco = Number(form.preco);
    if (form.preco === '' || !Number.isFinite(preco)) erros.preco = 'Indique um preço válido';
    else if (preco < 0) erros.preco = 'O preço não pode ser negativo';
    else if (temMaisDe2CasasDecimais(form.preco)) erros.preco = 'O preço não pode ter mais de 2 casas decimais';
    if (!form.tax_id) erros.tax_id = 'Escolha o IVA';
    if (Object.keys(erros).length > 0) {
      setFieldErrors(erros);
      toast.error('Há campos por corrigir');
      return;
    }

    const payload = {
      nome,
      categoria_id: form.categoria_id,
      // Vazio no formulário quer dizer "sem subcategoria" — e vai como `null`,
      // que é o que o servidor guarda. Uma string vazia era um id que não
      // existe, e o produto ficava a apontar para nada.
      subcategoria_id: form.subcategoria_id || null,
      // Vazio quer dizer "não sei o custo" e vai como `null` — nunca zero, que
      // o relatório leria como "custa nada" e daria lucro total.
      preco_custo: form.preco_custo.trim() === '' ? null : Number(form.preco_custo),
      preco,
      tax_id: form.tax_id,
      foto_url: form.foto_url.trim() || null,
      grupos_personalizacao: form.grupos_personalizacao,
      ativo: form.ativo,
    };
    // O PUT do servidor substitui o registo inteiro. vendus_ref não tem campo
    // neste formulário (é o produto importado do Vendus, não se edita à mão)
    // — sem o reenviar aqui, gravar o produto punha-o a null e cortava, em
    // silêncio, a ligação que a importação usa para não duplicar (mesmo
    // padrão de empresa_id em FatLojas e de employee_id em FatUtilizadores).
    if (editing) payload.vendus_ref = editing.vendus_ref ?? null;

    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarProduto(editing.id, payload); toast.success('Produto atualizado'); }
      else { await criarProduto(payload); toast.success('Produto criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este produto já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar o produto');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarProduto(alvo.id);
      toast.success('Produto eliminado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este produto já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar o produto');
      }
    }
  };

  const handleToggleEstado = async (produto) => {
    const novoEstado = !(produto.ativo !== false);
    setTogglingId(produto.id);
    try {
      await mudarEstadoProduto(produto.id, novoEstado);
      toast.success(novoEstado ? 'Produto ativado' : 'Produto desativado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este produto já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao mudar o estado do produto');
      }
    } finally {
      setTogglingId(null);
    }
  };

  // --- Importação do Vendus ---

  const handleImportar = async () => {
    setImporting(true);
    try {
      const { data } = await importarVendus();
      setImportResult(data);
      setImportResultOpen(true);
      const resumo = `${data.produtos_lidos} produtos e ${data.categorias_lidas} categorias lidos do Vendus`;
      const temProblemas = (data.problemas || []).length > 0;
      if (temProblemas) toast.warning(`Importação concluída com avisos — ${resumo}`);
      else toast.success(`Importação concluída — ${resumo}`);
      fetchAll();
    } catch (error) {
      const { mensagem } = detalhesErro(error, 'Erro ao importar do Vendus');
      toast.error(mensagem);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-produtos-page">
      <PageHeader icon={Package} title="Produtos" subtitle="O catálogo vendido no POS e na app — importado do Vendus">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={handleImportar}
            disabled={importing}
            title="Traz categorias e produtos da conta Vendus configurada"
            data-testid="importar-vendus-btn"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${importing ? 'animate-spin' : ''}`} />
            {importing ? 'A importar...' : 'Importar do Vendus'}
          </Button>
          <Button onClick={openNew} data-testid="add-produto-btn"><Plus className="h-4 w-4 mr-2" />Novo produto</Button>
        </div>
      </PageHeader>

      {semIva.length > 0 && (
        <Alert variant="destructive" data-testid="alerta-sem-iva">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {semIva.length === 1
              ? '1 produto sem IVA definido'
              : `${semIva.length} produtos sem IVA definido`}
          </AlertTitle>
          <AlertDescription>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                Um produto sem IVA não pode ser vendido — o sistema recusa a venda em vez de adivinhar uma taxa.
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="border-destructive/50 text-destructive hover:bg-destructive/10 shrink-0"
                onClick={verProdutosSemIva}
                data-testid="ver-produtos-sem-iva-btn"
              >
                Ver produtos
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {semVendusAtivos.length > 0 && (
        <Alert data-testid="alerta-sem-vendus" className="border-amber-300 bg-amber-50 text-amber-900">
          <Link2 className="h-4 w-4" />
          <AlertTitle>
            {semVendusAtivos.length === 1
              ? '1 produto à venda sem ligação ao Vendus'
              : `${semVendusAtivos.length} produtos à venda sem ligação ao Vendus`}
          </AlertTitle>
          <AlertDescription>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                A fatura não consegue dizer ao Vendus <em>qual</em> é o artigo, e o Vendus não o
                encontra pelo nome — <strong>cria um artigo novo a cada venda</strong>, sem categoria
                e com uma referência inventada. «Importar do Vendus» liga os que já existam lá com o
                mesmo nome e categoria.
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="border-amber-400 text-amber-900 hover:bg-amber-100 shrink-0"
                onClick={verProdutosSemVendus}
                data-testid="ver-produtos-sem-vendus-btn"
              >
                Ver produtos
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <div ref={tabelaRef} className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={filtroTexto}
            onChange={(e) => setFiltroTexto(e.target.value)}
            placeholder="Pesquisar por nome..."
            className="pl-8"
            data-testid="filtro-texto-produto"
          />
        </div>
        <Select value={filtroCategoria || '__todas__'} onValueChange={(v) => setFiltroCategoria(v === '__todas__' ? '' : v)}>
          <SelectTrigger className="w-56" data-testid="filtro-categoria-select"><SelectValue placeholder="Todas as categorias" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__todas__">Todas as categorias</SelectItem>
            {categorias.map((c) => (
              <SelectItem key={c.id} value={c.id}>{c.nome}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {somenteSemIva && (
          <Badge
            variant="outline"
            className="bg-red-50 text-red-700 border-red-200 gap-1.5 cursor-pointer h-9 px-3"
            onClick={() => setSomenteSemIva(false)}
            data-testid="limpar-filtro-sem-iva"
          >
            Só sem IVA <X className="h-3.5 w-3.5" />
          </Badge>
        )}
        {somenteSemVendus && (
          <Badge
            variant="outline"
            className="bg-amber-50 text-amber-800 border-amber-300 gap-1.5 cursor-pointer h-9 px-3"
            onClick={() => setSomenteSemVendus(false)}
            data-testid="limpar-filtro-sem-vendus"
          >
            Só sem Vendus <X className="h-3.5 w-3.5" />
          </Badge>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : produtosFiltrados.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Package className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem produtos</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {produtos.length === 0
                  ? 'Importe do Vendus ou crie o primeiro produto.'
                  : 'Nenhum produto corresponde ao filtro.'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    {/* A coluna que responde à pergunta do dono («ainda não
                        consigo colocar as imagens») de relance: quais é que já
                        têm foto e quais é que ainda não têm. */}
                    <TableHead className="w-14">Foto</TableHead>
                    <TableHead>Nome</TableHead>
                    <TableHead>Categoria</TableHead>
                    <TableHead>Preço</TableHead>
                    <TableHead>IVA</TableHead>
                    <TableHead>Personalizações</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {produtosFiltrados.map((produto) => {
                    const semIvaProduto = semIvaIds.has(produto.id);
                    return (
                      <TableRow
                        key={produto.id}
                        data-testid={`produto-row-${produto.id}`}
                        className={semIvaProduto ? 'bg-red-50/60 hover:bg-red-50' : undefined}
                      >
                        <TableCell>
                          <div className="h-10 w-10 rounded-md border overflow-hidden bg-muted flex items-center justify-center">
                            {urlDaFotoProduto(produto.foto_url) ? (
                              <img
                                src={urlDaFotoProduto(produto.foto_url)}
                                alt=""
                                loading="lazy"
                                decoding="async"
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <ImageOff className="h-4 w-4 text-muted-foreground/50" />
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            {produto.nome}
                            {semVendusIds.has(produto.id) ? (
                              <Badge
                                variant="outline"
                                className="bg-amber-50 text-amber-800 border-amber-300 gap-1 shrink-0"
                                title="A fatura não leva o id do artigo — o Vendus cria um artigo novo a cada venda"
                              >
                                <AlertTriangle className="h-3 w-3" />Sem Vendus
                              </Badge>
                            ) : (
                              <Link2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-label="Ligado ao Vendus" />
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{categoriasPorId[produto.categoria_id]?.nome || '—'}</TableCell>
                        <TableCell>{fmtEUR(produto.preco)}</TableCell>
                        <TableCell>
                          {produto.tax_id ? (
                            <Badge variant="outline" className="bg-slate-100 text-slate-700 border-slate-200" title={TAXA_LABEL[produto.tax_id]}>
                              {produto.tax_id}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 gap-1">
                              <AlertTriangle className="h-3 w-3" />Sem IVA
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {(produto.grupos_personalizacao || []).length === 0 ? (
                            <span className="text-sm text-muted-foreground">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1 max-w-[220px]">
                              {produto.grupos_personalizacao.map((gid) => (
                                <Badge key={gid} variant="secondary">{gruposPorId[gid]?.nome || gid}</Badge>
                              ))}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={produto.ativo !== false}
                              onCheckedChange={() => handleToggleEstado(produto)}
                              disabled={togglingId === produto.id}
                              data-testid={`produto-estado-switch-${produto.id}`}
                            />
                            <span className="text-sm text-muted-foreground">{produto.ativo !== false ? 'Ativo' : 'Inativo'}</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="ghost" size="icon" onClick={() => openEdit(produto)} data-testid={`edit-produto-${produto.id}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(produto)} data-testid={`delete-produto-${produto.id}`}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog criar/editar produto */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="produto-dialog" className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar produto' : 'Novo produto'}</DialogTitle>
            <DialogDescription>Um produto pertence a uma só categoria, com um preço e um IVA.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="produto-nome">Nome *</Label>
                <Input
                  id="produto-nome"
                  value={form.nome}
                  onChange={(e) => { setForm({ ...form, nome: e.target.value }); setFieldErrors((prev) => ({ ...prev, nome: undefined })); }}
                  placeholder="Ex: Açaí Regular"
                  required
                  maxLength={NOME_MAX}
                  aria-invalid={!!fieldErrors.nome}
                  data-testid="produto-nome-input"
                />
                {fieldErrors.nome && <p className="text-xs text-destructive">{fieldErrors.nome}</p>}
              </div>

              <div className="space-y-2">
                <Label>Categoria *</Label>
                <Select
                  value={form.categoria_id}
                  onValueChange={(v) => { setForm({ ...form, categoria_id: v }); setFieldErrors((prev) => ({ ...prev, categoria_id: undefined })); }}
                >
                  <SelectTrigger aria-invalid={!!fieldErrors.categoria_id} data-testid="produto-categoria-select">
                    <SelectValue placeholder="Selecionar categoria" />
                  </SelectTrigger>
                  <SelectContent>
                    {categorias.map((c) => (
                      <SelectItem key={c.id} value={c.id}>{c.nome}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {categorias.length === 0 && <p className="text-xs text-muted-foreground">Crie uma categoria primeiro.</p>}
                {fieldErrors.categoria_id && <p className="text-xs text-destructive">{fieldErrors.categoria_id}</p>}
              </div>

              {/* A subcategoria é opcional e só arruma a grelha do POS. Só se
                  mostram as da categoria escolhida: uma subcategoria de outra
                  categoria fazia o produto desaparecer da grelha, e o servidor
                  recusa-a (`_valida_referencias`) — o ecrã não a oferece. */}
              <div className="space-y-2">
                <Label>Subcategoria</Label>
                <Select
                  value={form.subcategoria_id || 'nenhuma'}
                  onValueChange={(v) => setForm({ ...form, subcategoria_id: v === 'nenhuma' ? '' : v })}
                  disabled={!form.categoria_id}
                >
                  <SelectTrigger data-testid="produto-subcategoria-select">
                    <SelectValue placeholder="Sem subcategoria" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="nenhuma">Sem subcategoria</SelectItem>
                    {subcategorias
                      .filter((s) => s.categoria_id === form.categoria_id)
                      .map((s) => (
                        <SelectItem key={s.id} value={s.id}>{s.nome}</SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Arruma a grelha do POS. Sem subcategoria, o produto aparece em "Outros".
                  Criam-se em Categorias.
                </p>
              </div>

              <div className="grid grid-cols-3 gap-4">
                {/* O PREÇO DE CUSTO é opcional e é o que acende as colunas
                    "Custos" e "Resultado" dos relatórios. Sem ele, essas
                    células mostram "—": um zero fazia o lucro parecer total. */}
                <div className="space-y-2">
                  <Label htmlFor="produto-custo">Custo (€)</Label>
                  <Input
                    id="produto-custo"
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.preco_custo}
                    onChange={(e) => setForm({ ...form, preco_custo: e.target.value })}
                    placeholder="—"
                    data-testid="produto-custo-input"
                  />
                  <p className="text-xs text-muted-foreground">Para o lucro nos relatórios.</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="produto-preco">Preço (€) *</Label>
                  <Input
                    id="produto-preco"
                    type="number"
                    step="0.01"
                    min="0"
                    value={form.preco}
                    onChange={(e) => { setForm({ ...form, preco: e.target.value }); setFieldErrors((prev) => ({ ...prev, preco: undefined })); }}
                    placeholder="8.99"
                    aria-invalid={!!fieldErrors.preco}
                    data-testid="produto-preco-input"
                  />
                  {fieldErrors.preco && <p className="text-xs text-destructive">{fieldErrors.preco}</p>}
                </div>
                <div className="space-y-2">
                  <Label>IVA *</Label>
                  <Select
                    value={form.tax_id}
                    onValueChange={(v) => { setForm({ ...form, tax_id: v }); setFieldErrors((prev) => ({ ...prev, tax_id: undefined })); }}
                  >
                    <SelectTrigger aria-invalid={!!fieldErrors.tax_id} data-testid="produto-tax-select">
                      <SelectValue placeholder="Selecionar IVA" />
                    </SelectTrigger>
                    <SelectContent>
                      {TAXA_OPCOES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {fieldErrors.tax_id && <p className="text-xs text-destructive">{fieldErrors.tax_id}</p>}
                </div>
              </div>

              {/* **A FOTO.** O pedido do dono: «em produtos no backoffice ainda
                  não consigo colocar as imagens dos produtos … as que você não
                  conseguir [do Vendus] deixe no backoffice a opção de fazer
                  upload.»

                  O caminho normal passa a ser o FICHEIRO do computador; o
                  endereço continua a existir para quem o queira (uma foto que
                  já viva noutro sítio), mas em segundo plano, que é onde
                  pertence — colar um endereço não é o que alguém faz com uma
                  fotografia que tirou ao açaí.

                  A imagem é reduzida AQUI antes de sair (640 px no lado maior,
                  WebP): a grelha do POS carrega dezenas destas de uma vez num
                  PC de loja. Quem RECUSA o que for grande de mais, ou o que
                  não for uma imagem, é o servidor — e a frase que ele devolve
                  é a que aparece. */}
              <div className="space-y-2">
                <Label>Foto do produto (opcional)</Label>
                <div className="flex items-start gap-3">
                  <div className="h-20 w-20 shrink-0 rounded-lg border overflow-hidden bg-muted flex items-center justify-center">
                    {urlDaFotoProduto(form.foto_url) ? (
                      <img
                        src={urlDaFotoProduto(form.foto_url)}
                        alt=""
                        className="h-full w-full object-cover"
                        data-testid="produto-foto-previsualizacao"
                      />
                    ) : (
                      <ImageOff className="h-6 w-6 text-muted-foreground/50" />
                    )}
                  </div>
                  <div className="space-y-2 min-w-0 flex-1">
                    <input
                      ref={inputFoto}
                      type="file"
                      accept={TIPOS_ACEITES}
                      className="hidden"
                      onChange={(e) => escolherFoto(e.target.files?.[0])}
                      data-testid="produto-foto-ficheiro"
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={aCarregarFoto}
                        onClick={() => inputFoto.current?.click()}
                        data-testid="produto-foto-escolher"
                      >
                        {aCarregarFoto
                          ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          : <ImagePlus className="h-4 w-4 mr-2" />}
                        {aCarregarFoto
                          ? 'A enviar a foto…'
                          : (form.foto_url ? 'Trocar a foto' : 'Escolher ficheiro')}
                      </Button>
                      {form.foto_url && !aCarregarFoto && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setForm((prev) => ({ ...prev, foto_url: '' }))}
                          data-testid="produto-foto-remover"
                        >
                          <X className="h-4 w-4 mr-1" /> Remover
                        </Button>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      JPEG, PNG ou WebP. A imagem é reduzida antes de ser
                      enviada — a grelha do POS carrega dezenas de fotos de uma
                      vez no PC da loja.
                    </p>
                    <Input
                      id="produto-foto"
                      value={form.foto_url}
                      onChange={(e) => setForm({ ...form, foto_url: e.target.value })}
                      placeholder="ou cole aqui um endereço https://..."
                      data-testid="produto-foto-input"
                    />
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Personalizações</Label>
                <div className="flex flex-col gap-2 max-h-40 overflow-y-auto border rounded-md p-3" data-testid="produto-grupos-options">
                  {grupos.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Sem grupos de personalização criados ainda.</p>
                  ) : (
                    grupos.map((grupo) => (
                      <label key={grupo.id} className="flex items-center gap-2 text-sm cursor-pointer">
                        <Checkbox
                          checked={form.grupos_personalizacao.includes(grupo.id)}
                          onCheckedChange={() => toggleGrupo(grupo.id)}
                          data-testid={`produto-grupo-checkbox-${grupo.id}`}
                        />
                        {grupo.nome}
                      </label>
                    ))
                  )}
                </div>
              </div>

              {editing?.vendus_ref && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <Link2 className="h-3.5 w-3.5" />Este produto veio do Vendus (ref. {editing.vendus_ref}). Uma nova importação atualiza nome, preço, IVA e categoria; as personalizações e a foto ficam como estão aqui.
                </p>
              )}

              <div className="flex items-center gap-2 pt-1">
                <Switch id="produto-ativo" checked={form.ativo} onCheckedChange={(v) => setForm({ ...form, ativo: v })} data-testid="produto-ativo-switch" />
                <Label htmlFor="produto-ativo" className="cursor-pointer">Produto ativo</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-produto-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar produto</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Resultado da importação */}
      <Dialog open={importResultOpen} onOpenChange={setImportResultOpen}>
        <DialogContent data-testid="import-result-dialog">
          <DialogHeader>
            <DialogTitle>Importação do Vendus</DialogTitle>
            <DialogDescription>Confirme estes números contra o backoffice do Vendus.</DialogDescription>
          </DialogHeader>
          {importResult && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Categorias lidas</p>
                  <p className="text-xl font-semibold" data-testid="import-categorias-lidas">{importResult.categorias_lidas}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Produtos lidos</p>
                  <p className="text-xl font-semibold" data-testid="import-produtos-lidos">{importResult.produtos_lidos}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Produtos criados</p>
                  <p className="text-xl font-semibold text-teal-700">{importResult.produtos_criados}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground">Produtos atualizados</p>
                  <p className="text-xl font-semibold text-blue-700">{importResult.produtos_atualizados}</p>
                </div>
              </div>
              {(importResult.problemas || []).length > 0 ? (
                <div className="space-y-1.5">
                  <p className="text-sm font-medium text-amber-700 flex items-center gap-1.5">
                    <AlertTriangle className="h-4 w-4" />
                    {importResult.problemas.length === 1 ? '1 aviso' : `${importResult.problemas.length} avisos`} — não impedem o resto da importação, mas convém rever
                  </p>
                  <div className="max-h-52 overflow-y-auto rounded-md border bg-amber-50/50 p-2 space-y-1">
                    {importResult.problemas.map((problema, i) => (
                      <p key={i} className="text-xs text-amber-900" data-testid={`import-problema-${i}`}>{problema}</p>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Sem avisos a reportar.</p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setImportResultOpen(false)} data-testid="fechar-import-result-btn">Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
