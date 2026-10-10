// O layout da área própria do CRM (`/crm/*`), no aspeto do portal: barra
// lateral só com os itens do CRM e "Voltar ao portal", tema e terminar sessão;
// no telemóvel a barra abre numa gaveta (`Sheet`). Um colaborador membro entra
// por aqui e não vê nada do resto do portal.
//
// Usa a mesma guarda das rotas (`GuardaCrm`): quem não pode entrar volta ao
// início sem ver a barra do CRM. As regras (itens, área cheia) estão em
// `lib/crm/acesso.js`, com testes; aqui só se desenham.
import React, { useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  ArrowLeft,
  ChevronDown,
  LogOut,
  Map as IconeMapa, // nunca `Map`: tapava o Map do JavaScript
  MapPinPlus,
  Menu,
  Settings,
  User,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useEstadoCrm } from '../../hooks/useEstadoCrm';
import { ecraCheioDoCrm, itensMenuCrm } from '../../lib/crm/acesso';
import { GuardaCrm } from '../crm/GuardaCrm';
import ThemeToggle from '../ThemeToggle';
import { Button } from '../ui/button';
import { ScrollArea } from '../ui/scroll-area';
import { Separator } from '../ui/separator';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '../ui/sheet';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';

// O ícone de cada item de `ITENS_MENU_CRM`, pela `chave`.
const ICONES = { mapa: IconeMapa, 'loja-nova': MapPinPlus, definicoes: Settings };

const classeItem = (ativo) =>
  `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
    ativo ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

function MenuCrm({ itens, aoNavegar }) {
  return (
    <div className="flex h-full flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl brand-gradient flex items-center justify-center font-heading font-bold text-white text-xl shadow-lg shadow-primary/30">
            L
          </div>
          <div className="leading-tight">
            <p className="font-heading font-bold text-lg">Lisbonb</p>
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground font-semibold">CRM Purple House</p>
          </div>
        </div>
      </div>

      <Separator />

      <ScrollArea className="flex-1 px-3 pt-4">
        <nav className="space-y-1" aria-label="Menu do CRM">
          {itens.map((item) => {
            const Icone = ICONES[item.chave];
            return (
              <NavLink
                key={item.chave}
                to={item.caminho}
                onClick={aoNavegar}
                className={({ isActive }) => classeItem(isActive)}
                data-testid={`crm-nav-${item.chave}`}
              >
                {Icone && <Icone className="h-4 w-4 shrink-0" aria-hidden="true" />}
                <span>{item.rotulo}</span>
              </NavLink>
            );
          })}
        </nav>
      </ScrollArea>

      <div className="border-t p-3">
        <Link to="/" onClick={aoNavegar} className={classeItem(false)} data-testid="crm-voltar-portal">
          <ArrowLeft className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>Voltar ao portal</span>
        </Link>
      </div>
    </div>
  );
}

function CascaCrm() {
  const { user, logout } = useAuth();
  const { eu } = useEstadoCrm();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [menuAberto, setMenuAberto] = useState(false);

  const itens = itensMenuCrm(eu);
  const cheio = ecraCheioDoCrm(pathname);
  const fecharMenu = () => setMenuAberto(false);

  const terminarSessao = () => {
    logout();
    navigate('/login');
    toast.success('Sessão terminada');
  };

  return (
    <div className="min-h-screen bg-background" data-testid="crm-layout">
      {/* Barra lateral (computador) */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-64 lg:flex-col border-r bg-card">
        <MenuCrm itens={itens} />
      </aside>

      {/* Cabeçalho (telemóvel) */}
      <header className="lg:hidden sticky top-0 z-40 flex h-16 items-center gap-4 border-b bg-card px-4">
        <Sheet open={menuAberto} onOpenChange={setMenuAberto}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Abrir o menu do CRM" data-testid="crm-mobile-menu-btn">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-64" aria-describedby={undefined}>
            <SheetTitle className="sr-only">Menu do CRM</SheetTitle>
            <MenuCrm itens={itens} aoNavegar={fecharMenu} />
          </SheetContent>
        </Sheet>

        <div className="flex items-center gap-2 min-w-0">
          <div className="h-8 w-8 shrink-0 rounded-lg brand-gradient flex items-center justify-center font-heading font-bold text-white text-base">
            L
          </div>
          <span className="font-heading font-bold truncate">CRM</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <Button
            variant="ghost"
            size="icon"
            onClick={terminarSessao}
            title="Terminar sessão"
            aria-label="Terminar sessão"
            data-testid="crm-logout-btn"
          >
            <LogOut className="h-5 w-5" />
          </Button>
        </div>
      </header>

      {/* Cabeçalho (computador) */}
      <header className="hidden lg:flex lg:ml-64 h-16 items-center justify-between border-b bg-card px-6">
        <div />
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <Separator orientation="vertical" className="h-6" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="gap-2" data-testid="crm-user-menu">
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
              <DropdownMenuItem onClick={terminarSessao} data-testid="crm-logout-menu-item">
                <LogOut className="h-4 w-4 mr-2" />
                Terminar Sessão
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* Conteúdo: o mapa ocupa a área toda (sem margens); o resto tem as de sempre. */}
      <main
        className={`lg:ml-64 ${cheio ? 'h-[calc(100vh-4rem)] overflow-hidden' : 'min-h-[calc(100vh-4rem)]'}`}
        data-ecra-cheio={cheio ? 'true' : 'false'}
      >
        <div className={cheio ? 'h-full' : 'p-4 md:p-6 lg:p-8'}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export default function CrmLayout() {
  return (
    <GuardaCrm>
      <CascaCrm />
    </GuardaCrm>
  );
}
