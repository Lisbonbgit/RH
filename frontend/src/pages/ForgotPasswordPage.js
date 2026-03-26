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
      // Show success even on error to prevent email enumeration
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

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
          <CardHeader className="space-y-1 pb-4">
            <CardTitle className="text-2xl font-heading">
              {submitted ? 'Email Enviado' : 'Esqueci a Palavra-passe'}
            </CardTitle>
            <CardDescription>
              {submitted 
                ? 'Verifique a sua caixa de entrada' 
                : 'Introduza o seu email para receber um link de redefinição'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {submitted ? (
              <div className="space-y-6">
                <Alert className="border-green-200 bg-green-50">
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                  <AlertDescription className="text-green-800">
                    Se o email existir no sistema, receberá um link para redefinir a sua palavra-passe. 
                    O link é válido por 1 hora.
                  </AlertDescription>
                </Alert>
                
                <div className="text-center space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Não recebeu o email? Verifique a pasta de spam ou tente novamente.
                  </p>
                  <div className="flex flex-col gap-2">
                    <Button 
                      variant="outline"
                      onClick={() => {
                        setSubmitted(false);
                        setEmail('');
                      }}
                    >
                      Tentar outro email
                    </Button>
                    <Link to="/login">
                      <Button variant="ghost" className="w-full">
                        <ArrowLeft className="h-4 w-4 mr-2" />
                        Voltar ao Login
                      </Button>
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
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
                  {loading ? 'A enviar...' : 'Enviar Link de Redefinição'}
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
            )}
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground mt-6">
          Sistema interno de gestão de recursos humanos
        </p>
      </div>
    </div>
  );
}
