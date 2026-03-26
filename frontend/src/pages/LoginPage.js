import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { toast } from 'sonner';
import { Building2, Users, Lock, Mail } from 'lucide-react';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated, user } = useAuth();
  const [loading, setLoading] = useState(false);
  
  // Login form
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Redirect if already authenticated
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
      toast.success('Login efetuado com sucesso!');
      navigate(userData.role === 'admin' ? '/admin' : '/colaborador');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao fazer login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-background">
      {/* Left side - Hero */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden">
        <div 
          className="absolute inset-0 bg-cover bg-center"
          style={{ 
            backgroundImage: 'url(https://images.unsplash.com/photo-1758873268631-fa944fc5cad2?crop=entropy&cs=srgb&fm=jpg&q=85)',
          }}
        />
        <div className="absolute inset-0 bg-primary/80" />
        <div className="relative z-10 flex flex-col justify-center p-12 text-white">
          <div className="flex items-center gap-3 mb-8">
            <div className="p-3 bg-white/10 rounded-xl backdrop-blur-sm">
              <Building2 className="h-8 w-8" />
            </div>
            <span className="text-2xl font-heading font-bold">RH grupo Lisbonb</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-heading font-bold mb-6 leading-tight">
            Sistema de Gestão<br />de Recursos Humanos
          </h1>
          <p className="text-lg text-white/80 max-w-md leading-relaxed">
            Gestão simplificada de colaboradores, controlo de ponto, 
            férias e documentos numa única plataforma.
          </p>
          <div className="mt-12 flex gap-8">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-white/70" />
              <span className="text-sm text-white/70">Múltiplas Empresas</span>
            </div>
            <div className="flex items-center gap-3">
              <Lock className="h-5 w-5 text-white/70" />
              <span className="text-sm text-white/70">Seguro e Fiável</span>
            </div>
          </div>
        </div>
      </div>

      {/* Right side - Login Form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md animate-fade-in">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center gap-3 mb-8 justify-center">
            <div className="p-3 bg-primary rounded-xl">
              <Building2 className="h-6 w-6 text-primary-foreground" />
            </div>
            <span className="text-xl font-heading font-bold">RH grupo Lisbonb</span>
          </div>

          <Card className="border-0 shadow-lg">
            <CardHeader className="space-y-1 pb-4">
              <CardTitle className="text-2xl font-heading">Bem-vindo</CardTitle>
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
                      className="pl-10"
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
                      className="pl-10"
                      required
                      data-testid="login-password-input"
                    />
                  </div>
                </div>
                <Button 
                  type="submit" 
                  className="w-full" 
                  disabled={loading}
                  data-testid="login-submit-btn"
                >
                  {loading ? 'A entrar...' : 'Entrar'}
                </Button>
                
                <div className="text-center">
                  <Link 
                    to="/esqueci-senha" 
                    className="text-sm text-muted-foreground hover:text-primary"
                    data-testid="forgot-password-link"
                  >
                    Esqueci a palavra-passe
                  </Link>
                </div>
              </form>
            </CardContent>
          </Card>

          <p className="text-center text-sm text-muted-foreground mt-6">
            Sistema interno de gestão de recursos humanos
          </p>
        </div>
      </div>
    </div>
  );
}
