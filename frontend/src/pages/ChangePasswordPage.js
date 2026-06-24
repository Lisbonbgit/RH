import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { toast } from 'sonner';
import { Lock, ShieldCheck, AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription } from '../components/ui/alert';

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const { user, changePassword, logout } = useAuth();
  const [loading, setLoading] = useState(false);
  
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState({});

  const validateForm = () => {
    const newErrors = {};
    
    if (!currentPassword) {
      newErrors.currentPassword = 'Palavra-passe atual é obrigatória';
    }
    
    if (!newPassword) {
      newErrors.newPassword = 'Nova palavra-passe é obrigatória';
    } else if (newPassword.length < 8) {
      newErrors.newPassword = 'A palavra-passe deve ter pelo menos 8 caracteres';
    }
    
    if (!confirmPassword) {
      newErrors.confirmPassword = 'Confirmação de palavra-passe é obrigatória';
    } else if (newPassword !== confirmPassword) {
      newErrors.confirmPassword = 'As palavras-passe não coincidem';
    }
    
    if (currentPassword && newPassword && currentPassword === newPassword) {
      newErrors.newPassword = 'A nova palavra-passe deve ser diferente da atual';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!validateForm()) {
      return;
    }
    
    setLoading(true);
    try {
      await changePassword(currentPassword, newPassword);
      toast.success('Palavra-passe alterada com sucesso!');
      navigate(user.role === 'admin' ? '/admin' : '/colaborador');
    } catch (error) {
      const message = error.response?.data?.detail || 'Erro ao alterar palavra-passe';
      toast.error(message);
      if (message.includes('atual')) {
        setErrors({ currentPassword: message });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
    toast.info('Sessão terminada');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-app-grid p-4">
      <div className="w-full max-w-md animate-fade-in">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="h-11 w-11 rounded-xl brand-gradient flex items-center justify-center font-heading font-bold text-white text-xl shadow-lg shadow-primary/30">
            L
          </div>
          <span className="text-xl font-heading font-bold">RH grupo <span className="text-brand-gradient">Lisbonb</span></span>
        </div>

        <Card className="border-0 shadow-lg">
          <CardHeader className="space-y-1 pb-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-primary" />
              <CardTitle className="text-2xl font-heading">Alterar Palavra-passe</CardTitle>
            </div>
            <CardDescription>
              Por motivos de segurança, deve alterar a sua palavra-passe temporária.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alert className="mb-6 border-amber-200 bg-amber-50">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              <AlertDescription className="text-amber-800">
                A sua palavra-passe temporária deve ser alterada antes de continuar a usar o sistema.
              </AlertDescription>
            </Alert>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="current-password">Palavra-passe Atual</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="current-password"
                    type="password"
                    placeholder="••••••••"
                    value={currentPassword}
                    onChange={(e) => {
                      setCurrentPassword(e.target.value);
                      setErrors({ ...errors, currentPassword: '' });
                    }}
                    className={`pl-10 ${errors.currentPassword ? 'border-red-500' : ''}`}
                    required
                    data-testid="current-password-input"
                  />
                </div>
                {errors.currentPassword && (
                  <p className="text-sm text-red-500">{errors.currentPassword}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="new-password">Nova Palavra-passe</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="new-password"
                    type="password"
                    placeholder="••••••••"
                    value={newPassword}
                    onChange={(e) => {
                      setNewPassword(e.target.value);
                      setErrors({ ...errors, newPassword: '' });
                    }}
                    className={`pl-10 ${errors.newPassword ? 'border-red-500' : ''}`}
                    required
                    minLength={8}
                    data-testid="new-password-input"
                  />
                </div>
                {errors.newPassword && (
                  <p className="text-sm text-red-500">{errors.newPassword}</p>
                )}
                <p className="text-xs text-muted-foreground">Mínimo de 8 caracteres</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirmar Nova Palavra-passe</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="confirm-password"
                    type="password"
                    placeholder="••••••••"
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value);
                      setErrors({ ...errors, confirmPassword: '' });
                    }}
                    className={`pl-10 ${errors.confirmPassword ? 'border-red-500' : ''}`}
                    required
                    data-testid="confirm-password-input"
                  />
                </div>
                {errors.confirmPassword && (
                  <p className="text-sm text-red-500">{errors.confirmPassword}</p>
                )}
              </div>

              <div className="flex gap-3 pt-2">
                <Button 
                  type="button"
                  variant="outline"
                  className="flex-1"
                  onClick={handleLogout}
                  data-testid="logout-btn"
                >
                  Terminar Sessão
                </Button>
                <Button 
                  type="submit" 
                  className="flex-1" 
                  disabled={loading}
                  data-testid="change-password-btn"
                >
                  {loading ? 'A alterar...' : 'Alterar Palavra-passe'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground mt-6">
          Sistema interno de gestão de recursos humanos
        </p>
      </div>
    </div>
  );
}
