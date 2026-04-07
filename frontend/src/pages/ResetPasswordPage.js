import React, { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Alert, AlertDescription } from '../components/ui/alert';
import { toast } from 'sonner';
import { Building2, Lock, ArrowLeft, CheckCircle2, Loader2, Mail } from 'lucide-react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const prefillEmail = searchParams.get('email') || '';

  const [email, setEmail] = useState(prefillEmail);
  const [code, setCode] = useState('');
  const [codeVerified, setCodeVerified] = useState(false);
  const [verifyingCode, setVerifyingCode] = useState(false);
  const [userEmail, setUserEmail] = useState(prefillEmail);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState({});

  const validateCodeForm = () => {
    const newErrors = {};

    if (!email.trim()) {
      newErrors.email = 'O email é obrigatório';
    }

    if (!code.trim()) {
      newErrors.code = 'O código é obrigatório';
    } else if (!/^\d{6}$/.test(code.trim())) {
      newErrors.code = 'O código deve ter 6 dígitos';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validatePasswordForm = () => {
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

  const handleVerifyCode = async (e) => {
    e.preventDefault();

    if (!validateCodeForm()) {
      return;
    }

    setVerifyingCode(true);
    try {
      const response = await axios.post(`${API_URL}/auth/verify-reset-code`, {
        email,
        code
      });
      setCodeVerified(true);
      setUserEmail(response.data.email || email);
      toast.success('Código confirmado com sucesso!');
    } catch (error) {
      const message = error.response?.data?.detail || 'Erro ao verificar código';
      toast.error(message);
    } finally {
      setVerifyingCode(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!validatePasswordForm()) {
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API_URL}/auth/reset-password`, {
        email,
        code,
        new_password: newPassword
      });
      setSuccess(true);
      toast.success('Palavra-passe redefinida com sucesso!');
    } catch (error) {
      const message = error.response?.data?.detail || 'Erro ao redefinir palavra-passe';
      toast.error(message);

      if (message.includes('expirado') || message.includes('inválido')) {
        setCodeVerified(false);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4" data-testid="reset-page">
      <div className="w-full max-w-md animate-fade-in" data-testid="reset-page-container">
        <div className="flex items-center gap-3 mb-8 justify-center" data-testid="reset-brand-header">
          <div className="p-3 bg-primary rounded-xl" data-testid="reset-brand-icon">
            <Building2 className="h-6 w-6 text-primary-foreground" />
          </div>
          <span className="text-xl font-heading font-bold" data-testid="reset-brand-title">RH grupo Lisbonb</span>
        </div>

        <Card className="border-0 shadow-lg" data-testid="reset-card">
          {success ? (
            <>
              <CardHeader className="space-y-1 pb-4" data-testid="reset-success-header">
                <CardTitle className="text-2xl font-heading" data-testid="reset-success-title">Palavra-passe Redefinida</CardTitle>
                <CardDescription data-testid="reset-success-description">
                  A sua nova palavra-passe foi definida com sucesso
                </CardDescription>
              </CardHeader>
              <CardContent data-testid="reset-success-content">
                <Alert className="mb-6 border-green-200 bg-green-50" data-testid="reset-success-alert">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <AlertDescription className="text-green-800" data-testid="reset-success-message">
                    A sua palavra-passe foi alterada com sucesso.
                    Pode agora fazer login com a nova palavra-passe.
                  </AlertDescription>
                </Alert>

                <Button
                  className="w-full"
                  onClick={() => navigate('/login')}
                  data-testid="reset-go-login-button"
                >
                  Ir para o Login
                </Button>
              </CardContent>
            </>
          ) : codeVerified ? (
            <>
              <CardHeader className="space-y-1 pb-4" data-testid="reset-password-header">
                <CardTitle className="text-2xl font-heading" data-testid="reset-password-title">Nova Palavra-passe</CardTitle>
                <CardDescription data-testid="reset-password-description">
                  Defina uma nova palavra-passe para {userEmail}
                </CardDescription>
              </CardHeader>
              <CardContent data-testid="reset-password-content">
                <Alert className="mb-6 border-green-200 bg-green-50" data-testid="reset-code-confirmed-alert">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <AlertDescription className="text-green-800" data-testid="reset-code-confirmed-message">
                    Código confirmado com sucesso. Pode agora definir a sua nova palavra-passe.
                  </AlertDescription>
                </Alert>
                <form onSubmit={handleSubmit} className="space-y-4" data-testid="reset-password-form">
                  <div className="space-y-2" data-testid="reset-new-password-field">
                    <Label htmlFor="new-password" data-testid="reset-new-password-label">Nova Palavra-passe</Label>
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
                      <p className="text-sm text-red-500" data-testid="reset-new-password-error">{errors.newPassword}</p>
                    )}
                    <p className="text-xs text-muted-foreground" data-testid="reset-new-password-hint">Mínimo de 8 caracteres</p>
                  </div>

                  <div className="space-y-2" data-testid="reset-confirm-password-field">
                    <Label htmlFor="confirm-password" data-testid="reset-confirm-password-label">Confirmar Palavra-passe</Label>
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
                      <p className="text-sm text-red-500" data-testid="reset-confirm-password-error">{errors.confirmPassword}</p>
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

                  <div className="flex flex-col gap-2" data-testid="reset-password-actions">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setCodeVerified(false)}
                      data-testid="reset-change-code-button"
                    >
                      Usar outro código
                    </Button>
                    <Link
                      to="/login"
                      className="text-sm text-muted-foreground hover:text-primary inline-flex items-center gap-1 justify-center"
                      data-testid="reset-back-login-link"
                    >
                      <ArrowLeft className="h-3 w-3" />
                      Voltar ao Login
                    </Link>
                  </div>
                </form>
              </CardContent>
            </>
          ) : (
            <>
              <CardHeader className="space-y-1 pb-4" data-testid="reset-code-header">
                <CardTitle className="text-2xl font-heading" data-testid="reset-code-title">Confirmar Código</CardTitle>
                <CardDescription data-testid="reset-code-description">
                  Introduza o código de 6 dígitos enviado para o seu email
                </CardDescription>
              </CardHeader>
              <CardContent data-testid="reset-code-content">
                <form onSubmit={handleVerifyCode} className="space-y-4" data-testid="reset-code-form">
                  <div className="space-y-2" data-testid="reset-email-field">
                    <Label htmlFor="reset-email" data-testid="reset-email-label">Email</Label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="reset-email"
                        type="email"
                        placeholder="seu@email.com"
                        value={email}
                        onChange={(e) => {
                          setEmail(e.target.value);
                          setErrors({ ...errors, email: '' });
                        }}
                        className={`pl-10 ${errors.email ? 'border-red-500' : ''}`}
                        required
                        data-testid="reset-email-input"
                      />
                    </div>
                    {errors.email && (
                      <p className="text-sm text-red-500" data-testid="reset-email-error">{errors.email}</p>
                    )}
                  </div>

                  <div className="space-y-2" data-testid="reset-code-field">
                    <Label htmlFor="reset-code" data-testid="reset-code-label">Código de 6 dígitos</Label>
                    <Input
                      id="reset-code"
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      placeholder="000000"
                      value={code}
                      onChange={(e) => {
                        const value = e.target.value.replace(/\D/g, '');
                        setCode(value);
                        setErrors({ ...errors, code: '' });
                      }}
                      className={errors.code ? 'border-red-500' : ''}
                      required
                      data-testid="reset-code-input"
                    />
                    {errors.code && (
                      <p className="text-sm text-red-500" data-testid="reset-code-error">{errors.code}</p>
                    )}
                  </div>

                  <Button
                    type="submit"
                    className="w-full"
                    disabled={verifyingCode}
                    data-testid="reset-verify-code-btn"
                  >
                    {verifyingCode ? (
                      <span className="flex items-center justify-center gap-2">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        A confirmar...
                      </span>
                    ) : (
                      'Confirmar Código'
                    )}
                  </Button>
                </form>

                <div className="space-y-2 mt-6" data-testid="reset-code-actions">
                  <Link to="/esqueci-senha" data-testid="reset-request-new-code-link">
                    <Button variant="outline" className="w-full" data-testid="reset-request-new-code-btn">
                      Solicitar novo código
                    </Button>
                  </Link>
                  <Link to="/login" data-testid="reset-back-login-button-link">
                    <Button variant="ghost" className="w-full" data-testid="reset-back-login-button">
                      <ArrowLeft className="h-4 w-4 mr-2" />
                      Voltar ao Login
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </>
          )}
        </Card>

        <p className="text-center text-sm text-muted-foreground mt-6" data-testid="reset-footer-text">
          Sistema interno de gestão de recursos humanos
        </p>
      </div>
    </div>
  );
}
