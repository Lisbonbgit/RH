import React, { useState, useEffect } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Alert, AlertDescription } from '../components/ui/alert';
import { toast } from 'sonner';
import { Building2, Lock, ArrowLeft, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');
  
  const [verifying, setVerifying] = useState(true);
  const [tokenValid, setTokenValid] = useState(false);
  const [userEmail, setUserEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState({});

  useEffect(() => {
    if (!token) {
      setVerifying(false);
      setTokenValid(false);
      return;
    }
    
    verifyToken();
  }, [token]);

  const verifyToken = async () => {
    try {
      const response = await axios.get(`${API_URL}/auth/verify-reset-token?token=${token}`);
      setTokenValid(true);
      setUserEmail(response.data.email);
    } catch (error) {
      setTokenValid(false);
    } finally {
      setVerifying(false);
    }
  };

  const validateForm = () => {
    const newErrors = {};
    
    if (!newPassword) {
      newErrors.newPassword = 'Nova palavra-passe é obrigatória';
    } else if (newPassword.length < 8) {
      newErrors.newPassword = 'A palavra-passe deve ter pelo menos 8 caracteres';
    }
    
    if (!confirmPassword) {
      newErrors.confirmPassword = 'Confirmação é obrigatória';
    } else if (newPassword !== confirmPassword) {
      newErrors.confirmPassword = 'As palavras-passe não coincidem';
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
      await axios.post(`${API_URL}/auth/reset-password`, {
        token,
        new_password: newPassword
      });
      setSuccess(true);
      toast.success('Palavra-passe redefinida com sucesso!');
    } catch (error) {
      const message = error.response?.data?.detail || 'Erro ao redefinir palavra-passe';
      toast.error(message);
      
      if (message.includes('expirado') || message.includes('inválido')) {
        setTokenValid(false);
      }
    } finally {
      setLoading(false);
    }
  };

  // Loading state while verifying token
  if (verifying) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4 text-primary" />
          <p className="text-muted-foreground">A verificar link...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-md animate-fade-in">
        <div className="flex items-center gap-3 mb-8 justify-center">
          <div className="p-3 bg-primary rounded-xl">
            <Building2 className="h-6 w-6 text-primary-foreground" />
          </div>
          <span className="text-xl font-heading font-bold">RH grupo Lisbonb</span>
        </div>

        <Card className="border-0 shadow-lg">
          {!token || !tokenValid ? (
            // Invalid or missing token
            <>
              <CardHeader className="space-y-1 pb-4">
                <CardTitle className="text-2xl font-heading">Link Inválido</CardTitle>
                <CardDescription>
                  O link de redefinição não é válido ou expirou
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Alert className="mb-6 border-amber-200 bg-amber-50">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                  <AlertDescription className="text-amber-800">
                    Este link de redefinição de palavra-passe é inválido ou já expirou. 
                    Os links são válidos apenas por 1 hora.
                  </AlertDescription>
                </Alert>
                
                <div className="space-y-3">
                  <Link to="/esqueci-senha">
                    <Button className="w-full">
                      Solicitar Novo Link
                    </Button>
                  </Link>
                  <Link to="/login">
                    <Button variant="ghost" className="w-full">
                      <ArrowLeft className="h-4 w-4 mr-2" />
                      Voltar ao Login
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </>
          ) : success ? (
            // Success state
            <>
              <CardHeader className="space-y-1 pb-4">
                <CardTitle className="text-2xl font-heading">Palavra-passe Redefinida</CardTitle>
                <CardDescription>
                  A sua nova palavra-passe foi definida com sucesso
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Alert className="mb-6 border-green-200 bg-green-50">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <AlertDescription className="text-green-800">
                    A sua palavra-passe foi alterada com sucesso. 
                    Pode agora fazer login com a nova palavra-passe.
                  </AlertDescription>
                </Alert>
                
                <Button 
                  className="w-full" 
                  onClick={() => navigate('/login')}
                >
                  Ir para o Login
                </Button>
              </CardContent>
            </>
          ) : (
            // Reset form
            <>
              <CardHeader className="space-y-1 pb-4">
                <CardTitle className="text-2xl font-heading">Nova Palavra-passe</CardTitle>
                <CardDescription>
                  Defina uma nova palavra-passe para {userEmail}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmit} className="space-y-4">
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
                        data-testid="new-password-input"
                      />
                    </div>
                    {errors.newPassword && (
                      <p className="text-sm text-red-500">{errors.newPassword}</p>
                    )}
                    <p className="text-xs text-muted-foreground">Mínimo de 8 caracteres</p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="confirm-password">Confirmar Palavra-passe</Label>
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

                  <Button 
                    type="submit" 
                    className="w-full" 
                    disabled={loading}
                    data-testid="reset-password-btn"
                  >
                    {loading ? 'A redefinir...' : 'Redefinir Palavra-passe'}
                  </Button>
                  
                  <div className="text-center">
                    <Link 
                      to="/login" 
                      className="text-sm text-muted-foreground hover:text-primary inline-flex items-center gap-1"
                    >
                      <ArrowLeft className="h-3 w-3" />
                      Voltar ao Login
                    </Link>
                  </div>
                </form>
              </CardContent>
            </>
          )}
        </Card>

        <p className="text-center text-sm text-muted-foreground mt-6">
          Sistema interno de gestão de recursos humanos
        </p>
      </div>
    </div>
  );
}
