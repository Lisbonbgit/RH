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
  Megaphone,
  CalendarDays,
  Star,
  Store,
  CreditCard,
  FileMinus,
  Package,
  Percent,
  Monitor,
  Banknote,
  UserCog
} from 'lucide-react';
import { toast } from 'sonner';

// Universo "Gestão Lisbonb": secções de topo, cada uma com os seus módulos.
const sections = [
  {
    key: 'painel',
    label: 'Painel',
    home: '/admin/painel',
    match: (p) => p.startsWith('/admin/painel'),
    items: [
      { path: '/admin/painel', label: 'Global', icon: LayoutDashboard, exact: true },
    ],
  },
  {
    key: 'rh',
    label: 'RH',
    home: '/admin',
    match: (p) => !p.startsWith('/admin/painel') && !p.startsWith('/admin/financeiro') && !p.startsWith('/admin/marketing') && !p.startsWith('/admin/estoque') && !p.startsWith('/admin/faturacao'),
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
    ],
  },
  {
    key: 'estoque',
    label: 'Estoque',
    home: '/admin/estoque/faturas',
    match: (p) => p.startsWith('/admin/estoque'),
    items: [
      { path: '/admin/estoque/faturas', label: 'Faturas', icon: Receipt },
    ],
  },
  {
    // O módulo Faturação tem estrutura própria, pedida pelo dono e decalcada do
    // backoffice do Vendus que ele usa hoje: duas secções (Gestão e POS) e a
    // Configuração à parte, em baixo. O campo `group` desenha esses cabeçalhos
    // na barra lateral (ver a navegação mais abaixo).
    key: 'faturacao',
    label: 'Faturação',
    home: '/admin/faturacao/dashboard',
    match: (p) => p.startsWith('/admin/faturacao'),
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
      { group: 'Gestão', path: '/admin/faturacao/taloes-desconto', label: 'Talões de Desconto', icon: Percent },
      { group: 'Gestão', path: '/admin/faturacao/clientes', label: 'Clientes', icon: Users },
      { group: 'Gestão', path: '/admin/faturacao/relatorios', label: 'Relatórios', icon: BarChart3 },
      { group: 'Gestão', path: '/admin/faturacao/compras', label: 'Compras', icon: Truck },

      { group: 'POS', path: '/admin/faturacao/pos', label: 'Iniciar Ponto de Venda', icon: Monitor },
      { group: 'POS', path: '/admin/faturacao/movimentos-caixa', label: 'Movimentos de Caixa', icon: Banknote },
      { group: 'POS', path: '/admin/faturacao/pos-lojas', label: 'Lojas', icon: Store },

      { group: 'Configuração', path: '/admin/faturacao/config/lojas', label: 'Lojas e Caixas', icon: Store },
      { group: 'Configuração', path: '/admin/faturacao/config/pagamentos', label: 'Tipos de Pagamento', icon: CreditCard },
      { group: 'Configuração', path: '/admin/faturacao/config/utilizadores', label: 'Utilizadores', icon: UserCog },
      { group: 'Configuração', path: '/admin/faturacao/config/motivos', label: 'Motivos - Notas Crédito', icon: FileMinus },
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

      <ScrollArea className="flex-1 px-3 pt-2">
        <nav className="space-y-1">
          {(() => {
            const visiveis = activeSection.items.filter(item => !item.masterOnly || isMasterAdmin);
            // Os sub-itens declaram o caminho do `pai`. Aqui pendura-se cada um
            // no seu pai, para o ramo poder abrir e fechar como um todo em vez
            // de os itens aparecerem soltos no meio da lista.
            const raiz = visiveis.filter(i => !i.pai);
            const filhosDe = (caminho) => visiveis.filter(i => i.pai === caminho);

            const classeItem = (isActive, indentado) =>
              `flex items-center gap-3 rounded-lg text-sm transition-colors ${
                indentado ? 'px-3 py-2 font-normal' : 'px-3 py-2.5 font-medium'
              } ${
                isActive
                  ? 'bg-primary text-primary-foreground font-medium'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`;

            let grupoAnterior = null;
            return raiz.map((item) => {
              // Cabeçalho de grupo: só quando o grupo muda, e só nas secções que
              // os declaram (as antigas não têm `group` e continuam uma lista
              // corrida, como sempre).
              const abreGrupo = item.group && item.group !== grupoAnterior;
              grupoAnterior = item.group || null;

              const filhos = filhosDe(item.path);
              const aberto = filhos.length > 0 && location.pathname.startsWith(item.path);

              return (
                <React.Fragment key={item.path}>
                  {abreGrupo && (
                    <p className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-semibold">
                      {item.group}
                    </p>
                  )}

                  <NavLink
                    to={item.path}
                    end={item.exact}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      // Um pai com o ramo aberto não fica pintado de azul: quem
                      // está seleccionado é o filho. O pai só ganha o tom de
                      // texto cheio, para se ver que é ali que estamos.
                      `${classeItem(isActive && !aberto, false)} ${
                        aberto ? 'text-foreground font-medium' : ''
                      }`
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
                    // Abertura suave: a grelha passa de 0fr para 1fr, o que anima
                    // a altura sem ninguém ter de a medir. Quem tiver o sistema
                    // com menos movimento salta a transição.
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
                              onClick={() => setMobileOpen(false)}
                              className={({ isActive }) => classeItem(isActive, true)}
                              data-testid={`nav-${filho.path.split('/').pop()}`}
                            >
                              {filho.label}
                            </NavLink>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </React.Fragment>
              );
            });
          })()}
        </nav>
      </ScrollArea>

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
