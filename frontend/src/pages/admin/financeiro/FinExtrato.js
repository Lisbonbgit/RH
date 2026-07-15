import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  getFinCompanies, getFinInvoices, getFinBankAccounts, createFinBankAccount,
  getFinMovements, importFinMovements, importFinMovementsPdf, setFinMovementTitle,
  linkFinMovement, unlinkFinMovement, attachFinMovement, automatchFinMovements,
} from '../../../lib/api';
import { eur, fmtDate, todayISO, normSup } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  Landmark, Upload, RefreshCw, Download, Link2, Unlink, Paperclip, Plus, Check, Search,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';
import MonthPicker from '../../../components/MonthPicker';

const LS_KEY = 'fin_selected_company';
const COMPANY_ALL = 'all';
const ACC_NONE = '__all__';

// Mês atual no formato YYYY-MM
const thisMonth = () => todayISO().slice(0, 7);

// ---------- Helpers de parse do .xlsx ----------
// Normaliza texto de cabeçalho: minúsculas, sem acentos, sem espaços extra.
const normHeader = (s) =>
  String(s || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

// Converte 'YYYY-MM-DD' / 'DD-MM-YYYY' / 'DD/MM/YYYY' para ISO (YYYY-MM-DD); senão devolve cru.
const toISODate = (raw) => {
  const s = String(raw || '').trim();
  if (!s) return '';
  let m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/); // já ISO
  if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
  m = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})/); // DD-MM-YYYY
  if (m) {
    let y = m[3];
    if (y.length === 2) y = '20' + y;
    return `${y}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
  }
  return s;
};

// Interpreta a string crua de montante/saldo PT (ex.: "-1.234,56" ou "-994.34") para Number.
const parseAmount = (raw) => {
  let s = String(raw == null ? '' : raw).trim();
  if (!s) return 0;
  s = s.replace(/[^\d.,-]/g, ''); // tira € e espaços
  // Se tem vírgula como último separador decimal (formato PT): tira pontos de milhares, vírgula->ponto
  if (s.includes(',') && s.lastIndexOf(',') > s.lastIndexOf('.')) {
    s = s.replace(/\./g, '').replace(',', '.');
  } else {
    s = s.replace(/,/g, ''); // formato com ponto decimal: tira vírgulas de milhares
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
};

// Lê o ficheiro do Millennium BCP e devolve { account_number, rows }.
const parseBankXlsx = (arrayBuffer) => {
  const XLSX = window.XLSX;
  if (!XLSX) throw new Error('Biblioteca XLSX não carregada. Recarrega a página.');
  const wb = XLSX.read(arrayBuffer, { type: 'array' });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, raw: false, defval: '' });

  // 1) Número da conta: primeira célula com >= 8 dígitos nas primeiras ~8 linhas.
  let accountNumber = '';
  outer:
  for (let r = 0; r < Math.min(8, aoa.length); r++) {
    for (const cell of aoa[r]) {
      const digits = String(cell || '').replace(/\D+/g, '');
      if (digits.length >= 8) { accountNumber = digits; break outer; }
    }
  }

  // 2) Linha de cabeçalho: contém pelo menos "data" + ("montante" ou "saldo" ou "descri").
  let headerRow = -1;
  for (let r = 0; r < aoa.length; r++) {
    const cells = aoa[r].map(normHeader);
    const joined = cells.join('|');
    const hasData = joined.includes('data');
    const hasMontante = joined.includes('montante') || joined.includes('valor') || joined.includes('saldo') || joined.includes('descri');
    if (hasData && hasMontante) { headerRow = r; break; }
  }
  if (headerRow === -1) throw new Error('Não encontrei a linha de cabeçalho (Data / Montante / Saldo).');

  const header = aoa[headerRow].map(normHeader);
  const findCol = (...needles) =>
    header.findIndex((h) => needles.some((n) => h.includes(n)));

  const cDataLanc = findCol('data lancamento', 'data lanc', 'data movimento', 'data mov');
  const cDataValor = findCol('data valor', 'valor data');
  const cDesc = findCol('descri');
  const cMontante = findCol('montante', 'valor', 'importancia');
  const cSaldo = findCol('saldo');
  const cMoeda = findCol('moeda', 'divisa', 'currency');

  // Colunas de data por fallback: 1ª data = lançamento, 2ª = valor.
  let colLanc = cDataLanc, colValor = cDataValor;
  if (colLanc === -1 || colValor === -1) {
    const dateCols = header.map((h, i) => (h.includes('data') ? i : -1)).filter((i) => i >= 0);
    if (colLanc === -1) colLanc = dateCols[0] ?? -1;
    if (colValor === -1) colValor = dateCols[1] ?? colLanc;
  }

  const rows = [];
  for (let r = headerRow + 1; r < aoa.length; r++) {
    const row = aoa[r];
    if (!row || row.length === 0) continue;
    const rawMontante = cMontante >= 0 ? row[cMontante] : '';
    const rawSaldo = cSaldo >= 0 ? row[cSaldo] : '';
    const dLanc = colLanc >= 0 ? row[colLanc] : '';
    const desc = cDesc >= 0 ? row[cDesc] : '';
    // Linha válida = tem data de lançamento E montante não vazio.
    const hasAny = String(dLanc || '').trim() && String(rawMontante == null ? '' : rawMontante).trim();
    if (!hasAny) continue;
    rows.push({
      date_lancamento: toISODate(dLanc),
      date_valor: toISODate(colValor >= 0 ? row[colValor] : dLanc),
      description: String(desc || '').trim(),
      amount: String(rawMontante == null ? '' : rawMontante).trim(), // STRING CRUA p/ dedup
      balance: String(rawSaldo == null ? '' : rawSaldo).trim(),       // STRING CRUA
      currency: cMoeda >= 0 ? String(row[cMoeda] || '').trim() || 'EUR' : 'EUR',
    });
  }
  return { account_number: accountNumber, rows };
};

export default function FinExtrato() {
  const { selectedCompany } = useOutletContext();
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState(ACC_NONE);
  const [month, setMonth] = useState(thisMonth());
  const [movements, setMovements] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  // Diálogo "Exportar": escolher o mês a exportar (independente do que está no ecrã).
  const [exportOpen, setExportOpen] = useState(false);
  const [exportMonth, setExportMonth] = useState(thisMonth());

  // edição inline do título
  const [editingId, setEditingId] = useState(null);
  const [titleDraft, setTitleDraft] = useState('');

  // dialog ligar fatura
  const [linkFor, setLinkFor] = useState(null);
  const [linkSearch, setLinkSearch] = useState('');

  // dialog nova conta (company_id: destino; preenchido também no fluxo do PDF
  // quando a conta do extrato ainda não está registada)
  const [accDialog, setAccDialog] = useState(false);
  const [accForm, setAccForm] = useState({ account_number: '', bank: 'Millennium BCP', account_name: '', company_id: '' });
  // PDF à espera de a conta ser registada (re-importa automaticamente depois)
  const pendingPdfRef = useRef(null);

  const company = companies.find((c) => c.id === companyId) || null;
  const canEdit = company && (company.role === 'owner' || company.role === 'partner');
  // Importar/registar conta não exige uma empresa selecionada: o PDF deteta a
  // empresa pela conta e o dialog de conta tem o seu próprio seletor. Basta o
  // utilizador poder editar ALGUMA empresa (inclui o modo "Todas as empresas").
  const canImport = canEdit || companies.some((c) => c.role === 'owner' || c.role === 'partner');
  const companyName = (id) => companies.find((c) => c.id === id)?.name || '';
  // Pode editar a empresa de ESTE movimento? (as ações por-movimento têm de
  // funcionar em "Todas as empresas", onde company/canEdit são nulos.)
  const canEditCompany = (id) => {
    const c = companies.find((x) => x.id === id);
    return !!c && (c.role === 'owner' || c.role === 'partner');
  };

  useEffect(() => { loadCompanies(); }, []);
  useEffect(() => {
    if (companyId) {
      localStorage.setItem(LS_KEY, companyId);
      setAccountId(ACC_NONE);
      loadAccounts();
      loadInvoices();
      pickLatestMonth();
    }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (companyId) loadMovements();
  }, [companyId, accountId, month]); // eslint-disable-line react-hooks/exhaustive-deps
  // Empresa ativa vem do seletor global do topo (secção Financeiro).
  useEffect(() => {
    setCompanyId(selectedCompany ? selectedCompany.id : COMPANY_ALL);
  }, [selectedCompany]);

  const loadCompanies = async () => {
    try {
      const c = await getFinCompanies();
      setCompanies(c.data);
      // Válido: "Todas as empresas" ou uma empresa existente que não a "Por classificar".
      const valid = companyId === COMPANY_ALL ||
        c.data.some((x) => x.id === companyId && normSup(x.name) !== 'por classificar');
      if (c.data.length && !valid) setCompanyId(COMPANY_ALL);
    } catch (e) {
      toast.error('Erro ao carregar empresas');
    }
  };

  const loadAccounts = async () => {
    try {
      const r = await getFinBankAccounts(companyId === COMPANY_ALL ? undefined : companyId);
      setAccounts(r.data || []);
    } catch (e) {
      setAccounts([]);
    }
  };

  const loadInvoices = async () => {
    try {
      const r = await getFinInvoices(companyId);
      setInvoices(r.data || []);
    } catch (e) {
      setInvoices([]);
    }
  };

  const loadMovements = async () => {
    setLoading(true);
    try {
      const params = { company_id: companyId };
      if (accountId !== ACC_NONE) params.account_id = accountId;
      if (month) params.month = month;
      const r = await getFinMovements(params);
      setMovements(r.data || []);
    } catch (e) {
      toast.error('Erro ao carregar movimentos');
      setMovements([]);
    } finally {
      setLoading(false);
    }
  };

  // Ao entrar (ou trocar de empresa), salta para o mês mais recente COM
  // movimentos — senão a página abre no mês atual, que pode não ter nada
  // (ex.: importaste junho e estamos em julho) e parece que "não há dados".
  const pickLatestMonth = async () => {
    try {
      const r = await getFinMovements({ company_id: companyId });
      const all = r.data || [];
      if (!all.length) return; // sem dados nenhuns: fica no mês atual
      const latest = all.reduce((mx, m) => {
        const d = String(m.date_lancamento || '').slice(0, 7);
        return d > mx ? d : mx;
      }, '');
      if (latest && latest !== month) setMonth(latest);
    } catch (_) { /* fica no mês atual */ }
  };

  const invoiceById = useMemo(() => {
    const m = {};
    invoices.forEach((i) => { m[i.id] = i; });
    return m;
  }, [invoices]);

  // ---------- Importar ----------
  // PDF do banco: a extração e o roteamento (pelo nº de conta) são no backend.
  const doImportPdf = async (file) => {
    setBusy(true);
    try {
      const res = await importFinMovementsPdf(file);
      const d = res.data || {};
      pendingPdfRef.current = null;
      toast.success(
        `${d.company_name || 'Empresa'} · conta ${String(d.account_number || '').slice(-4)}: ` +
        `${d.inserted ?? 0} novos · ${d.skipped ?? 0} já existiam`,
        { description: d.periodo ? `Período ${fmtDate(d.periodo.de)} – ${fmtDate(d.periodo.ate)}` : undefined }
      );
      // Mostrar o resultado: muda para a empresa do extrato (se não estivermos em "Todas").
      if (d.company_id && companyId !== COMPANY_ALL && companyId !== d.company_id) {
        setCompanyId(d.company_id);
      } else {
        await Promise.all([loadAccounts(), loadMovements()]);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 404 && detail && detail.code === 'conta_desconhecida') {
        // Conta nova: guarda o PDF, pré-preenche o registo e pergunta a empresa.
        pendingPdfRef.current = file;
        const holderNorm = normSup(detail.holder || '');
        const reais = companies.filter((c) => normSup(c.name) !== 'por classificar');
        const sugestao = (holderNorm && reais.find((c) => {
          const n = normSup(c.name);
          return n && (holderNorm.includes(n) || n.includes(holderNorm));
        })) || null;
        setAccForm({
          account_number: detail.account_number || '',
          bank: 'Millennium BCP',
          account_name: detail.holder || '',
          company_id: sugestao?.id || '',
        });
        setAccDialog(true);
        toast.info('Conta nova detetada no extrato', {
          description: 'Confirma a empresa a que pertence para concluir a importação.',
        });
      } else {
        toast.error(typeof detail === 'string' ? detail : (err.message || 'Erro ao importar o PDF'));
      }
    } finally {
      setBusy(false);
    }
  };

  const onImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // permite reimportar o mesmo ficheiro
    if (!file) return;
    const isPdf = /\.pdf$/i.test(file.name) || file.type === 'application/pdf';
    if (isPdf) { await doImportPdf(file); return; }
    // O .xlsx não deteta a empresa sozinho — precisa de uma escolhida no topo.
    if (companyId === COMPANY_ALL) {
      toast.info('Para importar .xlsx, escolhe primeiro a empresa no topo — ou usa o PDF, que deteta a empresa sozinho.');
      return;
    }
    if (!window.XLSX) { toast.error('Biblioteca de leitura não carregada. Recarrega a página.'); return; }
    setBusy(true);
    try {
      const buf = await file.arrayBuffer();
      const { account_number, rows } = parseBankXlsx(buf);
      if (!rows.length) { toast.error('Não encontrei movimentos no ficheiro.'); return; }
      const acc = accountId !== ACC_NONE ? accounts.find((a) => a.id === accountId) : null;
      const payload = {
        company_id: companyId,
        account_number: account_number || acc?.account_number || '',
        bank: acc?.bank || 'Millennium BCP',
        account_name: acc?.name || '',
        rows,
      };
      const res = await importFinMovements(payload);
      const inserted = res.data?.inserted ?? res.data?.created ?? 0;
      const ignored = res.data?.ignored ?? res.data?.skipped ?? (rows.length - inserted);
      toast.success(`Importado: ${inserted} novos · ${ignored} ignorados`);
      await Promise.all([loadAccounts(), loadMovements()]);
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Erro ao importar ficheiro');
    } finally {
      setBusy(false);
    }
  };

  const doAutomatch = async () => {
    setBusy(true);
    try {
      const res = await automatchFinMovements(companyId);
      const n = res.data?.linked ?? res.data?.matched ?? 0;
      toast.success(`${n} ligadas automaticamente`);
      await loadMovements();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao conciliar');
    } finally {
      setBusy(false);
    }
  };

  // ---------- Título inline ----------
  const startEditTitle = (mv) => { setEditingId(mv.id); setTitleDraft(mv.title || ''); };
  const saveTitle = async (mv) => {
    const t = titleDraft.trim();
    setEditingId(null);
    if (t === (mv.title || '')) return;
    try {
      await setFinMovementTitle(mv.id, t);
      setMovements((prev) => prev.map((m) => (m.id === mv.id ? { ...m, title: t } : m)));
    } catch (e) {
      toast.error('Erro ao guardar justificação');
      loadMovements();
    }
  };

  // ---------- Ligar / desligar fatura ----------
  const doLink = async (mv, invoiceId) => {
    try {
      await linkFinMovement(mv.id, invoiceId);
      toast.success('Fatura ligada');
      setLinkFor(null);
      setLinkSearch('');
      loadMovements();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao ligar fatura');
    }
  };
  const doUnlink = async (mv) => {
    try {
      await unlinkFinMovement(mv.id);
      toast.success('Fatura desligada');
      loadMovements();
    } catch (e) {
      toast.error('Erro ao desligar');
    }
  };

  // ---------- Anexar PDF ----------
  const onAttach = async (mv, e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      await attachFinMovement(mv.id, file);
      toast.success('PDF anexado');
      loadMovements();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao anexar');
    }
  };

  // ---------- Nova conta ----------
  const submitAccount = async (e) => {
    e.preventDefault();
    // Empresa destino: a escolhida no dialog (fluxo PDF) ou a do seletor.
    const destino = accForm.company_id || (companyId !== COMPANY_ALL ? companyId : '');
    if (!destino) { toast.error('Escolhe a empresa da conta.'); return; }
    try {
      await createFinBankAccount({
        company_id: destino,
        account_number: accForm.account_number || null,
        bank: accForm.bank || null,
        account_name: accForm.account_name || null,
      });
      toast.success('Conta criada');
      setAccDialog(false);
      setAccForm({ account_number: '', bank: 'Millennium BCP', account_name: '', company_id: '' });
      await loadAccounts();
      // Havia um PDF à espera desta conta? Retoma a importação.
      if (pendingPdfRef.current) {
        const f = pendingPdfRef.current;
        pendingPdfRef.current = null;
        await doImportPdf(f);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao criar conta');
    }
  };

  // ---------- Exportar ZIP ----------
  // Constrói e descarrega o ZIP a partir de uma lista de movimentos + rótulo do mês.
  const zipFromMovements = async (mvs, mLabel) => {
    if (!window.JSZip) { toast.error('Biblioteca de ZIP não carregada. Recarrega a página.'); return; }
    if (!window.XLSX) { toast.error('Biblioteca de Excel não carregada. Recarrega a página.'); return; }
    if (!mvs.length) { toast.error('Sem movimentos nesse mês para exportar.'); return; }
    const JSZip = window.JSZip;
    const XLSX = window.XLSX;
    const zip = new JSZip();

    // Folha Excel com os movimentos do mês.
    const data = mvs.map((m) => ({
      'Data Lançamento': fmtDate(m.date_lancamento),
      'Data Valor': fmtDate(m.date_valor),
      'Descrição': m.description || '',
      'Montante': Number(m.amount) || 0,
      'Saldo': m.balance != null && m.balance !== '' ? Number(m.balance) : '',
      'Justificação': m.title || '',
      'Fatura ligada': m.invoice_id ? invoiceLabel(invoiceById[m.invoice_id], m) : '',
    }));
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Extrato');
    const wbout = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
    zip.file(`extrato_${mLabel || 'todos'}.xlsx`, wbout);

    // Pasta pdfs/ com os anexos disponíveis (best-effort).
    const withPdf = mvs.filter((m) => m.attachment_path);
    if (withPdf.length) {
      const folder = zip.folder('pdfs');
      const base = process.env.REACT_APP_BACKEND_URL + '/api';
      for (const m of withPdf) {
        try {
          const resp = await fetch(`${base}/fin/movements/${m.id}/attachment`, {
            headers: authHeader(),
          });
          if (!resp.ok) continue;
          const blob = await resp.blob();
          const name = `${m.date_lancamento || 'mov'}_${m.id}.pdf`;
          folder.file(name, blob);
        } catch (_) { /* continua se um PDF falhar */ }
      }
    }

    const out = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(out);
    const a = document.createElement('a');
    a.href = url;
    a.download = `extrato_${company?.name || (companyId === COMPANY_ALL ? 'todas-as-empresas' : 'empresa')}_${mLabel || 'todos'}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success('ZIP gerado');
  };

  // Exporta o mês escolhido no diálogo (vai buscar os movimentos desse mês,
  // independente do que está a ser visto no ecrã).
  const runExport = async () => {
    setExportOpen(false);
    setBusy(true);
    try {
      const params = { company_id: companyId };
      if (exportMonth) params.month = exportMonth;
      const r = await getFinMovements(params);
      await zipFromMovements(r.data || [], exportMonth);
    } catch (e) {
      toast.error('Erro ao gerar o extrato');
    } finally {
      setBusy(false);
    }
  };

  // Token para o fetch direto do anexo (axios usa interceptor; aqui replicamos o header se existir).
  const authHeader = () => {
    const t = localStorage.getItem('token') || localStorage.getItem('access_token');
    return t ? { Authorization: `Bearer ${t}` } : {};
  };

  const invoiceLabel = (inv, mv) => {
    if (!inv) return mv?.invoice_id ? `#${mv.invoice_id}` : '';
    return [inv.supplier, inv.invoice_number].filter(Boolean).join(' · ') || `#${inv.id}`;
  };

  // ---------- Agrupar por dia ----------
  const groups = useMemo(() => {
    const sorted = [...movements].sort((a, b) =>
      String(b.date_lancamento || '').localeCompare(String(a.date_lancamento || '')));
    const map = {};
    sorted.forEach((m) => {
      const k = m.date_lancamento || '—';
      (map[k] = map[k] || []).push(m);
    });
    return Object.entries(map).map(([day, items]) => {
      const subtotal = items.reduce((s, m) => s + (Number(m.amount) || 0), 0);
      return { day, items, subtotal };
    });
  }, [movements]);

  const linkInvoices = useMemo(() => {
    const q = linkSearch.trim().toLowerCase();
    // Só faturas da MESMA empresa do movimento (importa em "Todas as empresas").
    const list = invoices.filter((i) =>
      i.approval_status !== 'rejected' && (!linkFor || i.company_id === linkFor.company_id));
    if (!q) return list.slice(0, 50);
    return list.filter((i) =>
      [i.supplier, i.invoice_number, i.nif, i.amount, i.description]
        .filter(Boolean).some((f) => String(f).toLowerCase().includes(q))
    ).slice(0, 50);
  }, [invoices, linkSearch, linkFor]);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-extrato-page">
      <PageHeader icon={Landmark} title="Extrato / Tesouraria" subtitle="Importar extrato do banco, conciliar e exportar">
        {/* Empresa/loja vêm do seletor global do topo. Aqui só o mês para navegar. */}
        <MonthPicker value={month} onChange={setMonth} className="w-44" testid="fin-month-picker" />
      </PageHeader>

      {companies.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Ainda não tens empresas. Cria uma no separador <b>Início</b> primeiro.
        </CardContent></Card>
      ) : (
        <>
          {/* Barra de ações */}
          <div className="flex items-center gap-2 flex-wrap">
            {canImport && (
              <Button asChild variant="outline" disabled={busy} data-testid="fin-import-btn">
                <label className="cursor-pointer">
                  <Upload className="h-4 w-4 mr-2" />Importar extrato (PDF/xlsx)
                  <input type="file" accept=".pdf,.xlsx,.xls" className="hidden"
                    onChange={onImportFile} disabled={busy} />
                </label>
              </Button>
            )}
            {canEdit && (
              <Button variant="outline" onClick={doAutomatch} disabled={busy} data-testid="fin-automatch-btn">
                <RefreshCw className="h-4 w-4 mr-2" />Conciliar
              </Button>
            )}
            <Button variant="outline" disabled={busy}
              onClick={() => { setExportMonth(month || thisMonth()); setExportOpen(true); }}
              data-testid="fin-export-btn">
              <Download className="h-4 w-4 mr-2" />Exportar ZIP
            </Button>
            {canImport && (
              <Button variant="ghost" onClick={() => setAccDialog(true)} data-testid="fin-new-account-btn">
                <Plus className="h-4 w-4 mr-2" />Nova conta
              </Button>
            )}
          </div>

          {/* Em "Todas as empresas" o extrato junta as contas todas (sem saldo
              contínuo). Um extrato bancário é por conta — sugere escolher a empresa. */}
          {companyId === COMPANY_ALL && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 dark:bg-amber-950/40 dark:border-amber-800 px-3 py-2 text-sm">
              <Landmark className="h-4 w-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
              <p className="text-amber-800 dark:text-amber-200">
                Estás a ver <b>todas as contas juntas</b>. Escolhe uma empresa no seletor do topo para
                o extrato dessa conta em separado (com saldo). Cada movimento é arquivado pela
                <b> conta bancária</b> a que pertence.
              </p>
            </div>
          )}

          {/* Lista de movimentos agrupada por dia */}
          <Card>
            <CardContent className="p-4 space-y-5">
              {loading ? (
                <div className="flex justify-center h-24 items-center">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                </div>
              ) : groups.length === 0 ? (
                <p className="text-center text-muted-foreground py-10">
                  Sem movimentos em <b>{month || 'todos os meses'}</b>. Muda o mês no topo ou importa o extrato do banco.
                </p>
              ) : (
                groups.map(({ day, items, subtotal }) => (
                  <div key={day} className="space-y-2">
                    <div className="flex items-center justify-between border-b pb-1">
                      <span className="text-sm font-semibold">{fmtDate(day)}</span>
                      <span className={`text-sm font-medium ${subtotal < 0 ? 'text-destructive' : 'text-emerald-600'}`}>
                        {eur(subtotal)}
                      </span>
                    </div>
                    {items.map((mv) => {
                      const amount = Number(mv.amount) || 0;
                      const isOut = amount < 0;
                      const inv = mv.invoice_id ? invoiceById[mv.invoice_id] : null;
                      return (
                        <div key={mv.id} className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between"
                          data-testid={`fin-mov-${mv.id}`}>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium truncate">{mv.description || '(sem descrição)'}</p>
                              {companyId === COMPANY_ALL && companyName(mv.company_id) && (
                                <Badge variant="outline" className="text-[10px] shrink-0">{companyName(mv.company_id)}</Badge>
                              )}
                            </div>
                            {/* Justificação inline */}
                            <div className="mt-1">
                              {editingId === mv.id ? (
                                <Input
                                  autoFocus
                                  value={titleDraft}
                                  onChange={(e) => setTitleDraft(e.target.value)}
                                  onBlur={() => saveTitle(mv)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') saveTitle(mv);
                                    if (e.key === 'Escape') setEditingId(null);
                                  }}
                                  className="h-7 text-xs max-w-md"
                                  placeholder="Justificação..."
                                  data-testid={`fin-title-input-${mv.id}`}
                                />
                              ) : (
                                <button type="button"
                                  className="text-xs text-muted-foreground hover:text-foreground hover:underline text-left"
                                  onClick={() => canEditCompany(mv.company_id) && startEditTitle(mv)}
                                  data-testid={`fin-title-${mv.id}`}>
                                  {mv.title ? mv.title : (canEditCompany(mv.company_id) ? '+ Adicionar justificação' : '—')}
                                </button>
                              )}
                            </div>
                            {/* Fatura ligada */}
                            {inv || mv.invoice_id ? (
                              <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                                <Badge variant="secondary" className="text-[11px]">
                                  <Link2 className="h-3 w-3 mr-1" />{invoiceLabel(inv, mv)}
                                </Badge>
                                {mv.link_auto && <Badge variant="outline" className="text-[10px]">auto</Badge>}
                                {canEditCompany(mv.company_id) && (
                                  <Button variant="ghost" size="sm" className="h-6 px-2 text-xs"
                                    onClick={() => doUnlink(mv)} data-testid={`fin-unlink-${mv.id}`}>
                                    <Unlink className="h-3 w-3 mr-1" />Desligar
                                  </Button>
                                )}
                              </div>
                            ) : (
                              canEditCompany(mv.company_id) && isOut && (
                                <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                                  <Button variant="outline" size="sm" className="h-7 px-2 text-xs"
                                    onClick={() => { setLinkFor(mv); setLinkSearch(''); }}
                                    data-testid={`fin-link-${mv.id}`}>
                                    <Link2 className="h-3 w-3 mr-1" />Ligar fatura
                                  </Button>
                                  <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs">
                                    <label className="cursor-pointer">
                                      <Paperclip className="h-3 w-3 mr-1" />Anexar PDF
                                      <input type="file" accept=".pdf,application/pdf" className="hidden"
                                        onChange={(e) => onAttach(mv, e)} />
                                    </label>
                                  </Button>
                                </div>
                              )
                            )}
                            {mv.attachment_path && (
                              <p className="mt-1 text-[11px] text-muted-foreground flex items-center gap-1">
                                <Paperclip className="h-3 w-3" />PDF anexado
                              </p>
                            )}
                          </div>
                          <div className="flex flex-col items-end shrink-0">
                            <span className={`text-sm font-semibold ${isOut ? 'text-destructive' : 'text-emerald-600'}`}>
                              {eur(amount)}
                            </span>
                            {mv.balance != null && mv.balance !== '' && (
                              <span className="text-[11px] text-muted-foreground">Saldo {eur(mv.balance)}</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* Dialog: ligar fatura */}
      <Dialog open={!!linkFor} onOpenChange={(o) => { if (!o) { setLinkFor(null); setLinkSearch(''); } }}>
        <DialogContent className="max-w-lg" data-testid="fin-link-dialog">
          <DialogHeader>
            <DialogTitle>Ligar fatura ao movimento</DialogTitle>
            <DialogDescription>
              {linkFor ? `${linkFor.description || ''} · ${eur(linkFor.amount)}` : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input className="pl-9" placeholder="Pesquisar fornecedor, nº, valor..."
              value={linkSearch} onChange={(e) => setLinkSearch(e.target.value)}
              data-testid="fin-link-search" />
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1">
            {linkInvoices.length === 0 ? (
              <p className="text-center text-muted-foreground py-6 text-sm">Sem faturas.</p>
            ) : (
              linkInvoices.map((i) => (
                <button key={i.id} type="button"
                  className="w-full flex items-center justify-between rounded-md border p-2 text-left hover:bg-accent"
                  onClick={() => doLink(linkFor, i.id)}
                  data-testid={`fin-link-option-${i.id}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{i.supplier || '(sem fornecedor)'}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {[i.invoice_number, fmtDate(i.issue_date)].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-sm">{eur(i.amount)}</span>
                    <Check className="h-4 w-4 text-muted-foreground" />
                  </div>
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Dialog: nova conta */}
      <Dialog open={accDialog} onOpenChange={setAccDialog}>
        <DialogContent className="max-w-md" data-testid="fin-account-dialog">
          <DialogHeader>
            <DialogTitle>Nova conta bancária</DialogTitle>
            <DialogDescription>Regista uma conta para organizar os extratos.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submitAccount} className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Empresa *</Label>
              <Select value={accForm.company_id || (companyId !== COMPANY_ALL ? companyId : '')}
                onValueChange={(v) => setAccForm({ ...accForm, company_id: v })}>
                <SelectTrigger data-testid="fin-acc-company"><SelectValue placeholder="Escolhe a empresa" /></SelectTrigger>
                <SelectContent>
                  {companies.filter((c) => normSup(c.name) !== 'por classificar').map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Nome da conta</Label>
              <Input value={accForm.account_name}
                onChange={(e) => setAccForm({ ...accForm, account_name: e.target.value })}
                placeholder="Ex.: Conta principal" data-testid="fin-acc-name" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Banco</Label>
              <Input value={accForm.bank}
                onChange={(e) => setAccForm({ ...accForm, bank: e.target.value })}
                data-testid="fin-acc-bank" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Nº da conta / IBAN</Label>
              <Input value={accForm.account_number}
                onChange={(e) => setAccForm({ ...accForm, account_number: e.target.value })}
                data-testid="fin-acc-number" />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAccDialog(false)}>Cancelar</Button>
              <Button type="submit" data-testid="fin-save-account-btn">Guardar</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Diálogo: exportar extrato — escolher o mês */}
      <Dialog open={exportOpen} onOpenChange={setExportOpen}>
        <DialogContent className="sm:max-w-sm" data-testid="fin-export-dialog">
          <DialogHeader>
            <DialogTitle>Exportar extrato</DialogTitle>
            <DialogDescription>Escolhe o mês a exportar (Excel + PDFs anexados num ZIP).</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label className="text-xs">Mês</Label>
            <MonthPicker value={exportMonth} onChange={setExportMonth} className="w-full" testid="fin-export-month" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExportOpen(false)}>Cancelar</Button>
            <Button onClick={runExport} disabled={busy} data-testid="fin-export-confirm">
              <Download className="h-4 w-4 mr-2" />{busy ? 'A gerar...' : 'Exportar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
