import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { toast } from 'sonner';
import { Lock, Mail, MapPin, CalendarCheck, FileText, Clock } from 'lucide-react';

const BrandMark = ({ size = 'md', glass = false }) => {
  const dims = size === 'lg' ? 'h-12 w-12 text-2xl rounded-2xl' : 'h-10 w-10 text-xl rounded-xl';
  return (
    <div
      className={`${dims} flex items-center justify-center font-heading font-bold ${
        glass ? 'bg-white/15 text-white backdrop-blur-sm ring-1 ring-white/25' : 'brand-gradient text-white shadow-lg shadow-primary/30'
      }`}
    >
      L
    </div>
  );
};

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated, user } = useAuth();
  const [loading, setLoading] = useState(false);

  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  React.useEffect(() => {
    if (isAuthenticated && user) {
      navigate(user.role === 'admin' ? '/admin' : '/colaborador');
    }
  }, [isAuthenticated, user, navigate]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const userData = await login(loginEmail, loginPassword);
      toast.success('Sessão iniciada com sucesso!');
      navigate(userData.role === 'admin' ? '/admin' : '/colaborador');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao iniciar sessão');
    } finally {
      setLoading(false);
    }
  };

  const features = [
    { icon: MapPin, label: 'Ponto com localização' },
    { icon: CalendarCheck, label: 'Férias e ausências' },
    { icon: FileText, label: 'Documentos seguros' },
  ];

  return (
    <div className="min-h-screen flex">
      {/* Left side - Hero */}
      <div className="hidden lg:flex lg:w-[55%] relative overflow-hidden brand-gradient text-white">
        {/* texturas / profundidade */}
        <div
          className="absolute inset-0 opacity-60"
          style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.10) 1px, transparent 0)', backgroundSize: '24px 24px' }}
        />
        <div className="absolute -top-24 -right-24 h-80 w-80 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-cyan-300/20 blur-3xl" />

        <div className="relative z-10 flex flex-col justify-between p-14 w-full">
          <div className="flex items-center gap-3">
            <BrandMark size="lg" glass />
            <div className="leading-tight">
              <div className="text-xl font-heading font-bold">Lisbonb</div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-white/70 font-semibold">Gestão de RH</div>
            </div>
          </div>

          <div>
            <h1 className="text-4xl xl:text-5xl font-heading font-bold leading-[1.08] tracking-tight">
              A sua equipa,<br />
              <span className="text-white/85">no seu lugar.</span>
            </h1>
            <p className="mt-5 text-base text-white/75 max-w-md leading-relaxed">
              Colaboradores, controlo de ponto, férias e documentos — tudo numa
              plataforma simples, segura e à medida do grupo Lisbonb.
            </p>

            <div className="mt-9 flex flex-wrap gap-3">
              {features.map((f) => (
                <div key={f.label} className="flex items-center gap-2 bg-white/10 ring-1 ring-white/15 rounded-full px-4 py-2 text-sm text-white/90">
                  <f.icon className="h-4 w-4" />
                  {f.label}
                </div>
              ))}
            </div>
          </div>

          {/* cartão flutuante de atmosfera */}
          <div className="flex items-center gap-4 bg-white/10 ring-1 ring-white/15 backdrop-blur-sm rounded-2xl p-4 max-w-sm">
            <div className="h-12 w-12 rounded-xl bg-white/15 flex items-center justify-center">
              <Clock className="h-6 w-6" />
            </div>
            <div>
              <div className="font-heading font-semibold">Entrada registada · 09:02</div>
              <div className="text-xs text-white/70">Loja Algueirão · localização confirmada</div>
            </div>
          </div>
        </div>
      </div>

      {/* Right side - Login Form */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-8 bg-app-grid">
        <div className="w-full max-w-md animate-fade-in">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
            <BrandMark />
            <span className="text-xl font-heading font-bold">RH grupo <span className="text-brand-gradient">Lisbonb</span></span>
          </div>

          <Card className="border border-border/70 shadow-[0_20px_60px_-25px_hsl(var(--primary)/0.35)] rounded-2xl">
            <CardHeader className="space-y-1.5 pb-4">
              <CardTitle className="text-2xl font-heading font-bold">Bem-vindo de volta</CardTitle>
              <CardDescription>
                Introduza as suas credenciais para aceder ao sistema
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleLogin} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="login-email">Email</Label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="login-email"
                      type="email"
                      placeholder="seu@email.com"
                      value={loginEmail}
                      onChange={(e) => setLoginEmail(e.target.value)}
                      className="pl-10 h-11"
                      required
                      data-testid="login-email-input"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="login-password">Palavra-passe</Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="login-password"
                      type="password"
                      placeholder="••••••••"
                      value={loginPassword}
                      onChange={(e) => setLoginPassword(e.target.value)}
                      className="pl-10 h-11"
                      required
                      data-testid="login-password-input"
                    />
                  </div>
                </div>
                <Button
                  type="submit"
                  className="w-full h-11 text-base shadow-lg shadow-primary/25"
                  disabled={loading}
                  data-testid="login-submit-btn"
                >
                  {loading ? 'A entrar...' : 'Entrar'}
                </Button>

                <div className="text-center">
                  <Link
                    to="/esqueci-senha"
                    className="text-sm text-muted-foreground hover:text-primary transition-colors"
                    data-testid="forgot-password-link"
                  >
                    Esqueci a palavra-passe
                  </Link>
                </div>
              </form>
            </CardContent>
          </Card>

          <p className="text-center text-sm text-muted-foreground mt-6">
            © {new Date().getFullYear()} Grupo Lisbonb · Sistema interno de RH
          </p>
        </div>
      </div>
    </div>
  );
}
