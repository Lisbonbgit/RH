import React, { useState, useEffect } from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { getNotifications, markAllNotificationsRead } from '../../lib/api';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { ScrollArea } from '../ui/scroll-area';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import {
  LayoutDashboard,
  Clock,
  Calendar,
  FileText,
  Bell,
  LogOut,
  User,
  ChevronDown
} from 'lucide-react';
import { toast } from 'sonner';

const navItems = [
  { path: '/colaborador', label: 'Início', icon: LayoutDashboard, exact: true },
  { path: '/colaborador/ponto', label: 'Registar Ponto', icon: Clock },
  { path: '/colaborador/ausencias', label: 'Ausências', icon: Calendar },
  { path: '/colaborador/documentos', label: 'Documentos', icon: FileText },
];

export default function EmployeeLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);

  useEffect(() => {
    fetchNotifications();
  }, []);

  const fetchNotifications = async () => {
    try {
      const response = await getNotifications();
      setNotifications(response.data);
    } catch (error) {
      console.error('Error fetching notifications:', error);
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

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b bg-card px-4">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg brand-gradient flex items-center justify-center font-heading font-bold text-white text-base">
            L
          </div>
          <span className="font-heading font-bold">Lisbonb</span>
        </div>

        <div className="flex items-center gap-2">
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

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" data-testid="user-menu">
                <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                  <User className="h-4 w-4" />
                </div>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                <div>
                  <p className="font-medium">{user?.name}</p>
                  <p className="text-xs text-muted-foreground">{user?.email}</p>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} data-testid="logout-menu-item">
                <LogOut className="h-4 w-4 mr-2" />
                Terminar Sessão
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 p-4 pb-20">
        <Outlet />
      </main>

      {/* Bottom Navigation */}
      <nav className="fixed bottom-0 left-0 right-0 border-t bg-card safe-area-inset-bottom">
        <div className="flex justify-around items-center h-16">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.exact}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-colors ${
                  isActive
                    ? 'text-primary'
                    : 'text-muted-foreground'
                }`
              }
              data-testid={`nav-${item.path.split('/').pop() || 'inicio'}`}
            >
              <item.icon className="h-5 w-5" />
              <span className="text-xs font-medium">{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
