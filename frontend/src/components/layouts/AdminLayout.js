import React, { useState, useEffect } from 'react';
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { getNotifications, markAllNotificationsRead, getCompanies, getFinCompanies, getFinUnits } from '../../lib/api';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { ScrollArea } from '../ui/scroll-area';
import { Separator } from '../ui/separator';
import ThemeToggle from '../ThemeToggle';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  Sheet,
  SheetContent,
  SheetTrigger,
} from '../ui/sheet';
import {
  Building2,
  LayoutDashboard,
  Users,
  MapPin,
  Clock,
  Clock4,
  Calendar,
  CalendarRange,
  CalendarOff,
  FileText,
  Bell,
  LogOut,
  Menu,
  ChevronDown,
  User,
  Check,
  ShieldCheck,
  Settings,
  Receipt,
  TrendingUp,
  BarChart3,
  Truck,
  Landmark,
  Scale,
  Megaphone,
  CalendarDays,
  Star,
  Store,
  Package,
  Percent,
  Monitor,
  Banknote,
  LayoutGrid,
  ShieldAlert,
  ShoppingCart,
  ArrowLeftRight,
  History,
  ClipboardList,
  Factory,
  Boxes,
  UserRound,
  Smartphone,
  Bike
} from 'lucide-react';
import { toast } from 'sonner';

// Universo "Gestão Lisbonb": secções de topo, cada uma com os seus módulos.
const sections = [
  {
    key: 'painel',
    label: 'Painel',
    home: '/admin/painel',
    // O Resumo (o ecrã de telemóvel) vive aqui: sem o acrescentar aos dois
    // `match`, tocar-lhe acendia o grupo RH — o apanha-tudo por exclusão.
    match: (p) => p.startsWith('/admin/painel') || p.startsWith('/admin/resumo'),
    items: [
      { path: '/admin/painel', label: 'Global', icon: LayoutDashboard, exact: true },
      { path: '/admin/painel/plataformas', label: 'Plataformas', icon: Bike },
      { path: '/admin/resumo', label: 'Resumo', icon: Smartphone, exact: true },
    ],
  },
  {
    key: 'rh',
    label: 'RH',
    home: '/admin',
    match: (p) => !p.startsWith('/admin/painel') && !p.startsWith('/admin/resumo') && !p.startsWith('/admin/financeiro') && !p.startsWith('/admin/marketing') && !p.startsWith('/admin/estoque') && !p.startsWith('/admin/faturacao'),
    items: [
      { path: '/admin', label: 'Dashboard', icon: LayoutDashboard, exact: true },
      { path: '/admin/empresas', label: 'Empresas', icon: Building2 },
      { path: '/admin/locais', label: 'Locais', icon: MapPin },
      { path: '/admin/colaboradores', label: 'Colaboradores', icon: Users },
      { path: '/admin/ponto', label: 'Controlo de Ponto', icon: Clock },
      { path: '/admin/relatorio-horas', label: 'Relatório de Horas', icon: Clock4 },
      { path: '/admin/ausencias', label: 'Férias e Ausências', icon: Calendar },
      { path: '/admin/mapa-ferias', label: 'Mapa de Férias', icon: CalendarRange },
      { path: '/admin/feriados', label: 'Feriados', icon: CalendarOff },
      { path: '/admin/escalas', label: 'Escalas', icon: Calendar },
      { path: '/admin/documentos', label: 'Documentos', icon: FileText },
    ],
  },
  {
    key: 'financeiro',
    label: 'Financeiro',
    home: '/admin/financeiro/vendas',
    match: (p) => p.startsWith('/admin/financeiro'),
    items: [
      { path: '/admin/financeiro/vendas', label: 'Vendas', icon: TrendingUp },
      { path: '/admin/financeiro/pagamentos', label: 'Pagamentos', icon: Receipt },
      { path: '/admin/financeiro/relatorios', label: 'Relatórios', icon: BarChart3 },
      { path: '/admin/financeiro/fornecedores', label: 'Fornecedores', icon: Truck },
      { path: '/admin/financeiro/extrato', label: 'Extrato', icon: Landmark },
      { path: '/admin/financeiro/conciliacao', label: 'Conciliação', icon: Scale },
    ],
  },
  {
    key: 'estoque',
    label: 'Estoque',
    home: '/admin/estoque/visao-geral',
    match: (p) => p.startsWith('/admin/estoque'),
    items: [
      { path: '/admin/estoque/visao-geral', label: 'Visão geral', icon: LayoutGrid },
      { path: '/admin/estoque/stock', label: 'Stock', icon: Package },
      { path: '/admin/estoque/catalogo', label: 'Catálogo', icon: Boxes },
      { path: '/admin/estoque/lista-compras', label: 'Lista de compras', icon: ShoppingCart },
      { path: '/admin/estoque/compras', label: 'Compras', icon: Truck },
      { path: '/admin/estoque/transferencias', label: 'Transferências', icon: ArrowLeftRight },
      { path: '/admin/estoque/fichas', label: 'Fichas técnicas', icon: ClipboardList },
      { path: '/admin/estoque/producao', label: 'Produção', icon: Factory },
      { path: '/admin/estoque/faturas', label: 'Faturas', icon: Receipt },
      { path: '/admin/estoque/definicoes', label: 'Definições', icon: Settings },
      { path: '/admin/estoque/unidades', label: 'Unidades', icon: Store },
      { path: '/admin/estoque/utilizadores', label: 'Utilizadores', icon: Users },
      { path: '/admin/estoque/pessoas', label: 'Pessoas', icon: UserRound },
      { path: '/admin/estoque/historico', label: 'Histórico', icon: History },
    ],
  },
  {
    // O módulo Faturação tem navegação própria, pedida pelo dono e decalcada
    // do backoffice do Vendus que ele usa hoje: um carril estreito à esquerda
    // com Gestão/POS, um painel à direita com os itens do grupo escolhido, e
    // a Configuração presa ao fundo, fora do carril. O bloco `rail` é o que
    // liga essa navegação especial (ver `SecaoComCarril` mais abaixo); as
    // outras secções não o declaram e continuam a desenhar a lista corrida.
    key: 'faturacao',
    label: 'Faturação',
    home: '/admin/faturacao/dashboard',
    match: (p) => p.startsWith('/admin/faturacao'),
    rail: {
      tabs: [
        { group: 'Gestão', label: 'Gestão', icon: LayoutGrid },
        { group: 'POS', label: 'POS', icon: Monitor },
      ],
      // A Configuração não é uma aba do carril — fica presa ao fundo (ver
      // pinnedGroup em SecaoComCarril), com os seus próprios itens pendurados
      // como filhos, o mesmo mecanismo do Produtos.
      pinnedGroup: 'Configuração',
      // "Iniciar Ponto de Venda" deixou de ser um item de menu: no Vendus é
      // um botão largo no topo da secção POS, que abre o ecrã de venda num
      // separador novo — e agora é uma rota de topo fora do /admin, porque a
      // funcionária da loja entra com PIN, sem sessão de backoffice.
      cta: {
        POS: { label: 'Iniciar Ponto de Venda', icon: Monitor, href: '/faturacao/pos' },
      },
    },
    items: [
      { group: 'Gestão', path: '/admin/faturacao/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      // Produtos abre três sub-itens, como no backoffice do Vendus: o catálogo,
      // as categorias (Venda ao Público / Vendas Aplicações) e os grupos de
      // personalização (os toppings) que depois se atribuem aos produtos.
      { group: 'Gestão', path: '/admin/faturacao/produtos', label: 'Produtos', icon: Package },
      { group: 'Gestão', path: '/admin/faturacao/produtos/lista', label: 'Produtos', pai: '/admin/faturacao/produtos' },
      { group: 'Gestão', path: '/admin/faturacao/produtos/categorias', label: 'Categorias', pai: '/admin/faturacao/produtos' },
      { group: 'Gestão', path: '/admin/faturacao/produtos/personalizacoes', label: 'Personalizações', pai: '/admin/faturacao/produtos' },
      { group: 'Gestão', path: '/admin/faturacao/documentos', label: 'Documentos', icon: FileText },
      // Logo a seguir aos Documentos, que é onde estão as faturas que saíram:
      // esta é a lista das que ficaram a meio. Fica na Gestão (o grupo que
      // abre por omissão) de propósito — quem chega aqui tem a loja ao
      // telefone a dizer que a caixa não fecha, e não pode ter de procurar.
      { group: 'Gestão', path: '/admin/faturacao/reservas-presas', label: 'Reservas Fiscais Presas', icon: ShieldAlert },
      { group: 'Gestão', path: '/admin/faturacao/taloes-desconto', label: 'Talões de Desconto', icon: Percent },
      { group: 'Gestão', path: '/admin/faturacao/clientes', label: 'Clientes', icon: Users },
      { group: 'Gestão', path: '/admin/faturacao/relatorios', label: 'Relatórios', icon: BarChart3 },
      { group: 'Gestão', path: '/admin/faturacao/compras', label: 'Compras', icon: Truck },

      { group: 'POS', path: '/admin/faturacao/movimentos-caixa', label: 'Movimentos de Caixa', icon: Banknote },
      { group: 'POS', path: '/admin/faturacao/pos-lojas', label: 'Lojas', icon: Store },

      // A Configuração pendura os 4 ecrãs já construídos no mesmo item pai,
      // tal como o Produtos pendura a Lista/Categorias/Personalizações.
      { group: 'Configuração', path: '/admin/faturacao/config', label: 'Configuração', icon: Settings },
      { group: 'Configuração', path: '/admin/faturacao/config/lojas', label: 'Lojas e Caixas', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/pagamentos', label: 'Tipos de Pagamento', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/utilizadores', label: 'Utilizadores', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/motivos', label: 'Motivos - Notas Crédito', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/dispositivos', label: 'Dispositivos', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/relatorio-diario', label: 'Relatório diário', pai: '/admin/faturacao/config' },
      { group: 'Configuração', path: '/admin/faturacao/config/modo-de-emissao', label: 'Modo de emissão', pai: '/admin/faturacao/config' },
    ],
  },
  {
    key: 'marketing',
    label: 'Marketing',
    home: '/admin/marketing',
    match: (p) => p.startsWith('/admin/marketing'),
    items: [
      { path: '/admin/marketing', label: 'Campanhas', icon: Megaphone, exact: true },
      { path: '/admin/marketing/calendario', label: 'Calendário', icon: CalendarDays },
      { path: '/admin/marketing/avaliacoes', label: 'Avaliações', icon: Star },
      { path: '/admin/marketing/relatorios', label: 'Relatórios', icon: BarChart3 },
    ],
  },
];

// Estilo comum de uma linha de navegação — usado na lista corrida das secções
// simples, no painel do carril da Faturação e na Configuração presa ao fundo.
const classeItemNav = (isActive, indentado) =>
  `flex items-center gap-3 rounded-lg text-sm transition-colors ${
    indentado ? 'px-3 py-2 font-normal' : 'px-3 py-2.5 font-medium'
  } ${
    isActive
      ? 'bg-primary text-primary-foreground font-medium'
      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

// Uma entrada de navegação, com os filhos que ela possa ter pendurados por
// baixo (seta que roda, abertura suave, fio vertical). É o mecanismo que já
// existia para o Produtos — aqui vira um componente para poder ser reutilizado
// também pela Configuração presa ao fundo do carril da Faturação.
function ItemNav({ item, filhos, location, onNavigate }) {
  const aberto = filhos.length > 0 && location.pathname.startsWith(item.path);
  return (
    <>
      <NavLink
        to={item.path}
        end={item.exact}
        onClick={onNavigate}
        className={({ isActive }) =>
          // Um pai com o ramo aberto não fica pintado de azul: quem está
          // seleccionado é o filho. O pai só ganha o tom de texto cheio, para
          // se ver que é ali que estamos.
          `${classeItemNav(isActive && !aberto, false)} ${aberto ? 'text-foreground font-medium' : ''}`
        }
        data-testid={`nav-${item.path.split('/').pop() || 'dashboard'}`}
      >
        {item.icon && <item.icon className="h-4 w-4 shrink-0" />}
        <span className="flex-1">{item.label}</span>
        {filhos.length > 0 && (
          <ChevronDown
            className={`h-4 w-4 shrink-0 opacity-60 transition-transform duration-200 motion-reduce:transition-none ${
              aberto ? 'rotate-0' : '-rotate-90'
            }`}
          />
        )}
      </NavLink>

      {filhos.length > 0 && (
        // Abertura suave: a grelha passa de 0fr para 1fr, o que anima a altura
        // sem ninguém ter de a medir. Quem tiver o sistema com menos
        // movimento salta a transição.
        <div
          className="grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none"
          style={{ gridTemplateRows: aberto ? '1fr' : '0fr' }}
          aria-hidden={!aberto}
        >
          <div className="overflow-hidden">
            <div className="ml-[22px] border-l border-border pl-3 space-y-1 py-1">
              {filhos.map((filho) => (
                <NavLink
                  key={filho.path}
                  to={filho.path}
                  end={filho.exact}
                  tabIndex={aberto ? 0 : -1}
                  onClick={onNavigate}
                  className={({ isActive }) => classeItemNav(isActive, true)}
                  data-testid={`nav-${filho.path.split('/').pop()}`}
                >
                  {filho.label}
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// A lista corrida de itens de uma secção — com cabeçalhos de grupo opcionais
// (`item.group`) e filhos pendurados no pai (`item.pai`). É o que a barra
// lateral sempre desenhou; o painel do carril da Faturação reutiliza-a com
// `showGroupHeaders={false}`, já que o próprio carril identifica o grupo.
function ListaNav({ items, location, onNavigate, showGroupHeaders = true }) {
  const raiz = items.filter((i) => !i.pai);
  const filhosDe = (caminho) => items.filter((i) => i.pai === caminho);
  let grupoAnterior = null;

  return (
    <nav className="space-y-1">
      {raiz.map((item) => {
        const abreGrupo = showGroupHeaders && item.group && item.group !== grupoAnterior;
        grupoAnterior = item.group || null;

        return (
          <React.Fragment key={item.path}>
            {abreGrupo && (
              <p className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-semibold">
                {item.group}
              </p>
            )}
            <ItemNav item={item} filhos={filhosDe(item.path)} location={location} onNavigate={onNavigate} />
          </React.Fragment>
        );
      })}
    </nav>
  );
}

// O carril estreito (Gestão/POS) + o painel com os itens do grupo escolhido —
// a navegação do módulo Faturação, decalcada do backoffice do Vendus. Só
// entra em jogo quando a secção declara `rail`; as outras continuam a usar a
// ListaNav directamente, em lista corrida.
function SecaoComCarril({ section, items, location, navigate, onNavigate }) {
  const { tabs, pinnedGroup, cta } = section.rail;

  // O grupo activo deduz-se do caminho actual: de entre todos os itens com
  // `group`, o mais específico (caminho mais longo) cujo caminho é o próprio
  // ou um prefixo do actual.
  const activeItem = [...items]
    .filter((i) => i.group)
    .sort((a, b) => b.path.length - a.path.length)
    .find((i) => location.pathname === i.path || location.pathname.startsWith(`${i.path}/`));
  const activeGroup = activeItem ? activeItem.group : null;

  // O painel só mostra itens quando o grupo activo é uma aba do carril — a
  // Configuração (presa em baixo) mostra os seus filhos ali mesmo, não aqui.
  const itemsDoGrupo = tabs.some((t) => t.group === activeGroup)
    ? items.filter((i) => i.group === activeGroup)
    : [];

  const ctaAtivo = cta && cta[activeGroup];

  const pinnedItems = pinnedGroup ? items.filter((i) => i.group === pinnedGroup) : [];
  const pinnedRaiz = pinnedItems.find((i) => !i.pai);
  const pinnedFilhos = pinnedRaiz ? pinnedItems.filter((i) => i.pai === pinnedRaiz.path) : [];

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex flex-1 min-h-0">
        {/* Carril */}
        <div className="w-16 shrink-0 border-r border-border bg-muted/40 flex flex-col items-center gap-1 py-3">
          {tabs.map((tab) => {
            const isActive = tab.group === activeGroup;
            // Um clique no carril navega para o primeiro item desse grupo.
            const alvo = items.find((i) => i.group === tab.group && !i.pai);
            return (
              <button
                key={tab.group}
                type="button"
                onClick={() => { if (alvo) navigate(alvo.path); onNavigate?.(); }}
                className={`flex flex-col items-center justify-center gap-1 w-14 rounded-lg py-2 text-[10px] font-semibold uppercase tracking-wide transition-colors ${
                  isActive
                    ? 'bg-card text-primary shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-card/60'
                }`}
                data-testid={`rail-${tab.group}`}
              >
                <tab.icon className="h-5 w-5" />
                <span className="truncate max-w-full px-0.5">{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Painel */}
        <ScrollArea className="flex-1 min-w-0 px-3 pt-3">
          {ctaAtivo && (
            <a
              href={ctaAtivo.href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onNavigate}
              className="mb-4 flex items-center justify-center gap-2 rounded-xl bg-primary text-primary-foreground py-3 px-3 text-sm font-semibold shadow-md shadow-primary/30 hover:opacity-90 transition-opacity motion-reduce:transition-none"
              data-testid="pos-iniciar-btn"
            >
              <ctaAtivo.icon className="h-5 w-5 shrink-0" />
              <span>{ctaAtivo.label}</span>
            </a>
          )}
          <ListaNav items={itemsDoGrupo} location={location} onNavigate={onNavigate} showGroupHeaders={false} />
        </ScrollArea>
      </div>

      {/* Configuração — presa ao fundo, separada por uma linha, fora do carril */}
      {pinnedRaiz && (
        <div className="border-t border-border px-3 py-2 shrink-0">
          <ItemNav item={pinnedRaiz} filhos={pinnedFilhos} location={location} onNavigate={onNavigate} />
        </div>
      )}
    </div>
  );
}

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const activeSection = sections.find((s) => s.match(location.pathname)) || sections[0];
  const [notifications, setNotifications] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [units, setUnits] = useState([]);           // lojas da empresa selecionada (Financeiro)
  const [selectedUnit, setSelectedUnit] = useState(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const isMasterAdmin = user?.is_master_admin === true;

  useEffect(() => {
    fetchNotifications();
  }, []);

  // O seletor de empresa carrega a lista certa conforme a secção: RH/Marketing
  // usam as empresas do RH; o Financeiro tem as suas próprias empresas. Ao mudar
  // de secção, limpa a seleção (as empresas são universos diferentes).
  useEffect(() => {
    setSelectedCompany(null);
    setSelectedUnit(null);
    setUnits([]);
    fetchCompanies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection.key]);

  // Lojas (unidades) da empresa selecionada — no Financeiro e no Estoque (ambos
  // usam as empresas/lojas do Financeiro). Ao trocar de empresa, limpa a loja e
  // recarrega as lojas dessa empresa.
  useEffect(() => {
    setSelectedUnit(null);
    if ((activeSection.key === 'financeiro' || activeSection.key === 'estoque') && selectedCompany) {
      getFinUnits(selectedCompany.id).then((r) => setUnits(r.data || [])).catch(() => setUnits([]));
    } else {
      setUnits([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany, activeSection.key]);

  const fetchNotifications = async () => {
    try {
      const response = await getNotifications();
      setNotifications(response.data);
    } catch (error) {
      console.error('Error fetching notifications:', error);
    }
  };

  const fetchCompanies = async () => {
    try {
      const response = (activeSection.key === 'financeiro' || activeSection.key === 'estoque')
        ? await getFinCompanies()
        : await getCompanies();
      setCompanies(response.data || []);
    } catch (error) {
      console.error('Error fetching companies:', error);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications(notifications.map(n => ({ ...n, read: true })));
      toast.success('Notificações marcadas como lidas');
    } catch (error) {
      toast.error('Erro ao marcar notificações');
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
    toast.success('Sessão terminada');
  };

  const unreadCount = notifications.filter(n => !n.read).length;

  const NavContent = () => (
    <div className="flex flex-col h-full">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl brand-gradient flex items-center justify-center font-heading font-bold text-white text-xl shadow-lg shadow-primary/30">
            L
          </div>
          <div className="leading-tight">
            <h1 className="font-heading font-bold text-lg">Lisbonb</h1>
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-semibold">Gestão Lisbonb</p>
          </div>
        </div>
      </div>

      <Separator />

      {/* Seletor de secções (Painel / RH / Financeiro / Marketing).
          Grelha 2x2: com 4 secções, 4 colunas ficam estreitas demais na
          sidebar e os nomes ("Financeiro", "Marketing") sobrepõem-se. */}
      <div className="px-4 pt-4">
        <div className="grid grid-cols-2 gap-1 p-1 bg-muted rounded-xl">
          {sections.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => { navigate(s.home); setMobileOpen(false); }}
              className={`text-xs font-semibold py-1.5 px-2 rounded-lg truncate transition-colors ${
                activeSection.key === s.key
                  ? 'bg-card text-primary shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              data-testid={`section-${s.key}`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Company Selector (todas as secções) */}
      <div className="p-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="w-full justify-between" data-testid="company-selector">
              <span className="truncate">
                {selectedCompany ? selectedCompany.name : 'Todas as Empresas'}
              </span>
              <ChevronDown className="h-4 w-4 ml-2 shrink-0" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-56">
            <DropdownMenuLabel>Selecionar Empresa</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem 
              onClick={() => setSelectedCompany(null)}
              data-testid="company-all"
            >
              {!selectedCompany && <Check className="h-4 w-4 mr-2" />}
              <span className={!selectedCompany ? 'font-medium' : ''}>Todas as Empresas</span>
            </DropdownMenuItem>
            {companies.map(company => (
              <DropdownMenuItem
                key={company.id}
                onClick={() => setSelectedCompany(company)}
                data-testid={`company-${company.id}`}
              >
                {selectedCompany?.id === company.id && <Check className="h-4 w-4 mr-2" />}
                <span className={selectedCompany?.id === company.id ? 'font-medium' : ''}>{company.name}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Seletor de LOJA (só no Financeiro, com uma empresa escolhida e lojas). */}
        {activeSection.key === 'financeiro' && selectedCompany && units.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="w-full justify-between mt-2" data-testid="unit-selector">
                <span className="truncate">{selectedUnit ? selectedUnit.name : 'Todas as lojas'}</span>
                <ChevronDown className="h-4 w-4 ml-2 shrink-0" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-56">
              <DropdownMenuLabel>Selecionar Loja</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setSelectedUnit(null)} data-testid="unit-all">
                {!selectedUnit && <Check className="h-4 w-4 mr-2" />}
                <span className={!selectedUnit ? 'font-medium' : ''}>Todas as lojas</span>
              </DropdownMenuItem>
              {units.map((u) => (
                <DropdownMenuItem key={u.id} onClick={() => setSelectedUnit(u)} data-testid={`unit-${u.id}`}>
                  {selectedUnit?.id === u.id && <Check className="h-4 w-4 mr-2" />}
                  <span className={selectedUnit?.id === u.id ? 'font-medium' : ''}>{u.name}</span>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {(() => {
        const visiveis = activeSection.items.filter(item => !item.masterOnly || isMasterAdmin);
        const fecharMobile = () => setMobileOpen(false);

        // Só a Faturação declara `rail` — carril + painel, como o Vendus. As
        // outras secções não declaram nada de especial e caem na lista
        // corrida de sempre.
        return activeSection.rail ? (
          <SecaoComCarril
            section={activeSection}
            items={visiveis}
            location={location}
            navigate={navigate}
            onNavigate={fecharMobile}
          />
        ) : (
          <ScrollArea className="flex-1 px-3 pt-2">
            <ListaNav items={visiveis} location={location} onNavigate={fecharMobile} />
          </ScrollArea>
        );
      })()}

      {isMasterAdmin && (
        <div className="lg:hidden p-4 border-t">
          <button
            type="button"
            onClick={() => { navigate('/admin/gestores'); setMobileOpen(false); }}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            data-testid="group-admin-sidebar"
          >
            <ShieldCheck className="h-4 w-4 text-primary" />
            Administração do grupo
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-background">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-64 lg:flex-col border-r bg-card">
        <NavContent />
      </aside>

      {/* Mobile Header */}
      <header className="lg:hidden sticky top-0 z-40 flex h-16 items-center gap-4 border-b bg-card px-4">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" data-testid="mobile-menu-btn">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-64">
            <NavContent />
          </SheetContent>
        </Sheet>

        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg brand-gradient flex items-center justify-center font-heading font-bold text-white text-base">
            L
          </div>
          <span className="font-heading font-bold">Lisbonb</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={() => navigate('/admin/financeiro/configuracoes')}
            title="Configurações (empresas e lojas)" data-testid="fin-config-btn">
            <Settings className="h-5 w-5" />
          </Button>
          <ThemeToggle />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="relative" data-testid="notifications-btn">
                <Bell className="h-5 w-5" />
                {unreadCount > 0 && (
                  <Badge className="absolute -top-1 -right-1 h-5 w-5 p-0 flex items-center justify-center text-xs">
                    {unreadCount}
                  </Badge>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <DropdownMenuLabel className="flex items-center justify-between">
                Notificações
                {unreadCount > 0 && (
                  <Button variant="ghost" size="sm" onClick={handleMarkAllRead}>
                    Marcar todas como lidas
                  </Button>
                )}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <ScrollArea className="h-64">
                {notifications.length === 0 ? (
                  <div className="p-4 text-center text-sm text-muted-foreground">
                    Sem notificações
                  </div>
                ) : (
                  notifications.slice(0, 10).map(notification => (
                    <DropdownMenuItem key={notification.id} className="flex flex-col items-start p-3">
                      <div className="flex items-center gap-2 w-full">
                        {!notification.read && <div className="h-2 w-2 rounded-full bg-primary" />}
                        <span className="font-medium text-sm">{notification.title}</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{notification.message}</p>
                    </DropdownMenuItem>
                  ))
                )}
              </ScrollArea>
            </DropdownMenuContent>
          </DropdownMenu>

          <Button variant="ghost" size="icon" onClick={handleLogout} data-testid="logout-btn">
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {/* Desktop Header */}
      <header className="hidden lg:flex lg:ml-64 h-16 items-center justify-between border-b bg-card px-6">
        <div />
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/admin/financeiro/configuracoes')}
            title="Configurações (empresas e lojas)" data-testid="fin-config-btn-desktop">
            <Settings className="h-5 w-5" />
          </Button>
          <ThemeToggle />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="relative" data-testid="notifications-btn-desktop">
                <Bell className="h-5 w-5" />
                {unreadCount > 0 && (
                  <Badge className="absolute -top-1 -right-1 h-5 w-5 p-0 flex items-center justify-center text-xs">
                    {unreadCount}
                  </Badge>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <DropdownMenuLabel className="flex items-center justify-between">
                Notificações
                {unreadCount > 0 && (
                  <Button variant="ghost" size="sm" onClick={handleMarkAllRead}>
                    Marcar todas como lidas
                  </Button>
                )}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <ScrollArea className="h-64">
                {notifications.length === 0 ? (
                  <div className="p-4 text-center text-sm text-muted-foreground">
                    Sem notificações
                  </div>
                ) : (
                  notifications.slice(0, 10).map(notification => (
                    <DropdownMenuItem key={notification.id} className="flex flex-col items-start p-3">
                      <div className="flex items-center gap-2 w-full">
                        {!notification.read && <div className="h-2 w-2 rounded-full bg-primary" />}
                        <span className="font-medium text-sm">{notification.title}</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{notification.message}</p>
                    </DropdownMenuItem>
                  ))
                )}
              </ScrollArea>
            </DropdownMenuContent>
          </DropdownMenu>

          <Separator orientation="vertical" className="h-6" />

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="gap-2" data-testid="user-menu">
                <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                  <User className="h-4 w-4" />
                </div>
                <span className="font-medium">{user?.name}</span>
                <ChevronDown className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {isMasterAdmin && (
                <>
                  <DropdownMenuItem onClick={() => navigate('/admin/gestores')} data-testid="group-admin-menu-item">
                    <ShieldCheck className="h-4 w-4 mr-2 text-primary" />
                    Administração do grupo
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem onClick={handleLogout} data-testid="logout-menu-item">
                <LogOut className="h-4 w-4 mr-2" />
                Terminar Sessão
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* Main Content */}
      <main className="lg:ml-64 min-h-[calc(100vh-4rem)]">
        <div className="p-4 md:p-6 lg:p-8">
          <Outlet context={{ selectedCompany, selectedUnit, units, companies, refreshCompanies: fetchCompanies }} />
        </div>
      </main>
    </div>
  );
}
