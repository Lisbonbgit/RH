import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Alert, AlertDescription } from '../components/ui/alert';
import { toast } from 'sonner';
import { Building2, Mail, ArrowLeft, CheckCircle2 } from 'lucide-react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const normalizedEmail = email.trim();
  const resetLink = normalizedEmail
    ? `/redefinir-senha?email=${encodeURIComponent(normalizedEmail)}`
    : '/redefinir-senha';

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!email.trim()) {
      toast.error('Por favor, introduza o seu email');
      return;
    }

    setLoading(true);
    try {
      await axios.post(`${API_URL}/auth/forgot-password`, { email });
      setSubmitted(true);
    } catch (error) {
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4" data-testid="forgot-page">
      <div className="w-full max-w-md animate-fade-in" data-testid="forgot-page-container">
        <div className="flex items-center gap-3 mb-8 justify-center" data-testid="forgot-brand-header">
          <div className="p-3 bg-primary rounded-xl" data-testid="forgot-brand-icon">
            <Building2 className="h-6 w-6 text-primary-foreground" />
          </div>
          <span className="text-xl font-heading font-bold" data-testid="forgot-brand-title">RH grupo Lisbonb</span>
        </div>

        <Card className="border-0 shadow-lg" data-testid="forgot-card">
          <CardHeader className="space-y-1 pb-4" data-testid="forgot-card-header">
            <CardTitle className="text-2xl font-heading" data-testid="forgot-card-title">
              {submitted ? 'Email Enviado' : 'Esqueci a Palavra-passe'}
            </CardTitle>
            <CardDescription data-testid="forgot-card-description">
              {submitted
                ? 'Verifique a sua caixa de entrada para obter o código'
                : 'Introduza o seu email para receber um código de 6 dígitos'}
            </CardDescription>
          </CardHeader>
          <CardContent data-testid="forgot-card-content">
            {submitted ? (
              <div className="space-y-6" data-testid="forgot-success-state">
                <Alert className="border-green-200 bg-green-50" data-testid="forgot-success-alert">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <AlertDescription className="text-green-800" data-testid="forgot-success-message">
                    Se o email existir no sistema, receberá um código de 6 dígitos para redefinir a sua palavra-passe.
                    O código é válido por 1 hora.
                  </AlertDescription>
                </Alert>

                <div className="text-center space-y-4" data-testid="forgot-success-actions">
                  <p className="text-sm text-muted-foreground" data-testid="forgot-success-hint">
                    Não recebeu o email? Verifique a pasta de spam ou tente novamente.
                  </p>
                  <div className="flex flex-col gap-2">
                    <Link to={resetLink} data-testid="forgot-go-to-reset-link">
                      <Button className="w-full" data-testid="forgot-go-to-reset-button">
                        Já tenho o código
                      </Button>
                    </Link>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setSubmitted(false);
                        setEmail('');
                      }}
                      data-testid="forgot-try-another-email-button"
                    >
                      Tentar outro email
                    </Button>
                    <Link to="/login" data-testid="forgot-back-login-link">
                      <Button variant="ghost" className="w-full" data-testid="forgot-back-login-button">
                        <ArrowLeft className="h-4 w-4 mr-2" />
                        Voltar ao Login
                      </Button>
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4" data-testid="forgot-form">
                <div className="space-y-2" data-testid="forgot-email-field">
                  <Label htmlFor="email" data-testid="forgot-email-label">Email</Label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="email"
                      type="email"
                      placeholder="seu@email.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="pl-10"
                      required
                      data-testid="forgot-email-input"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  className="w-full"
                  disabled={loading}
                  data-testid="forgot-submit-btn"
                >
                  {loading ? 'A enviar...' : 'Enviar Código'}
                </Button>

                <div className="text-center" data-testid="forgot-back-login-section">
                  <Link
                    to="/login"
                    className="text-sm text-muted-foreground hover:text-primary inline-flex items-center gap-1"
                    data-testid="forgot-back-login-link-text"
                  >
                    <ArrowLeft className="h-3 w-3" />
                    Voltar ao Login
                  </Link>
                </div>
              </form>
            )}
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground mt-6" data-testid="forgot-footer-text">
          Sistema interno de gestão de recursos humanos
        </p>
      </div>
    </div>
  );
}
