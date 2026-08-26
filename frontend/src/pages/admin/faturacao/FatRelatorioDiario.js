import React, { useEffect, useState } from 'react';
import {
  getDefinicoesRelatorio, gravarDefinicoesRelatorio, enviarRelatorioAgora,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Switch } from '../../../components/ui/switch';
import { Alert, AlertDescription } from '../../../components/ui/alert';
import { Mail, Plus, Trash2, Send, Clock, Loader2 } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// A mesma regra do servidor (`DefinicoesEntrada.emails`), mas só para avisar
// ANTES de gravar — quem decide é o servidor. Um endereço inválido faz o
// Resend recusar o envio INTEIRO, e o relatório da noite não sai para
// ninguém, não só para quem se enganou a escrever.
const PARECE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export default function FatRelatorioDiario() {
  const [emails, setEmails] = useState([]);
  const [ativo, setAtivo] = useState(true);
  const [novo, setNovo] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erroNovo, setErroNovo] = useState('');

  useEffect(() => { carregar(); }, []);

  const carregar = async () => {
    setLoading(true);
    try {
      const { data } = await getDefinicoesRelatorio();
      setEmails(data.emails || []);
      setAtivo(data.ativo !== false);
    } catch (error) {
      toast.error('Erro ao carregar as definições do relatório');
    } finally {
      setLoading(false);
    }
  };

  // Grava a lista INTEIRA de uma vez (é o que o PUT do servidor recebe), e
  // recebe por parâmetro o que vai gravar em vez de o ler do estado: um
  // `setEmails` seguido de `gravar()` gravava a lista ANTERIOR, porque o
  // estado do React só chega no render seguinte.
  const gravar = async (novosEmails, novoAtivo) => {
    setSaving(true);
    try {
      await gravarDefinicoesRelatorio({ emails: novosEmails, ativo: novoAtivo });
      setEmails(novosEmails);
      setAtivo(novoAtivo);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível gravar.').mensagem);
      // Volta ao que o servidor tem: deixar o ecrã a mostrar uma lista que
      // não ficou gravada é a pior das duas mentiras possíveis aqui.
      carregar();
    } finally {
      setSaving(false);
    }
  };

  const juntar = async () => {
    const email = novo.trim().toLowerCase();
    if (!email) return;
    if (!PARECE_EMAIL.test(email)) {
      setErroNovo('Isto não parece um endereço de email.');
      return;
    }
    if (emails.includes(email)) {
      setErroNovo('Este email já está na lista.');
      return;
    }
    setErroNovo('');
    setNovo('');
    await gravar([...emails, email], ativo);
  };

  const tirar = async (email) => {
    await gravar(emails.filter((e) => e !== email), ativo);
  };

  const enviarAgora = async () => {
    setEnviando(true);
    try {
      const { data } = await enviarRelatorioAgora();
      toast.success(`Relatório enviado para ${(data.enviado_para || []).length} destinatário(s).`);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível enviar.').mensagem);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-relatorio-diario-page">
      <PageHeader
        icon={Mail}
        title="Relatório diário"
        subtitle="Faturação · Configuração"
      />

      <Alert className="border-primary/30 bg-accent/40">
        <Clock className="h-4 w-4" />
        <AlertDescription className="text-sm">
          O relatório sai <strong>todos os dias às 23:30</strong> com a faturação do próprio
          dia, o caixa de cada loja, os tipos de pagamento e os artigos mais vendidos.
          Uma venda feita depois dessa hora entra no relatório do dia seguinte — a hora vai
          escrita no email, para nunca haver dúvida.
        </AlertDescription>
      </Alert>

      <Card>
        <CardContent className="p-4 sm:p-5 space-y-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="font-medium">Envio automático</p>
              <p className="text-sm text-muted-foreground">
                {ativo ? 'Ligado — sai todos os dias às 23:30.' : 'Desligado — não sai nenhum email.'}
              </p>
            </div>
            <Switch
              checked={ativo}
              disabled={saving || loading}
              onCheckedChange={(v) => gravar(emails, v)}
              data-testid="relatorio-ativo-switch"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 sm:p-5 space-y-4">
          <div>
            <Label>Quem recebe</Label>
            <p className="text-sm text-muted-foreground mt-1">
              Toda a gente nesta lista recebe o relatório completo, com todas as lojas.
            </p>
          </div>

          <div className="flex flex-wrap gap-2 items-start">
            <div className="flex-1 min-w-[240px]">
              <Input
                value={novo}
                onChange={(e) => { setNovo(e.target.value); setErroNovo(''); }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); juntar(); } }}
                placeholder="nome@empresa.pt"
                disabled={saving}
                data-testid="relatorio-novo-email"
              />
              {erroNovo && <p className="text-sm text-destructive mt-1">{erroNovo}</p>}
            </div>
            <Button type="button" onClick={juntar} disabled={saving || !novo.trim()}
              data-testid="relatorio-juntar-btn">
              <Plus className="h-4 w-4 mr-1" />Juntar
            </Button>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : emails.length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-center"
              data-testid="relatorio-lista-vazia">
              <Mail className="h-8 w-8 text-muted-foreground/50 mx-auto mb-2" strokeWidth={1.5} />
              <p className="text-sm text-muted-foreground">
                Ninguém na lista — o relatório não é enviado a ninguém.
              </p>
            </div>
          ) : (
            <div className="divide-y rounded-md border" data-testid="relatorio-lista">
              {emails.map((email) => (
                <div key={email} className="flex items-center justify-between gap-3 px-3 py-2.5"
                  data-testid={`relatorio-email-${email}`}>
                  <span className="text-sm break-all">{email}</span>
                  <Button
                    type="button" variant="ghost" size="icon"
                    onClick={() => tirar(email)} disabled={saving}
                    aria-label={`Tirar ${email} da lista`}
                    data-testid={`relatorio-tirar-${email}`}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 sm:p-5">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="font-medium">Enviar agora</p>
              <p className="text-sm text-muted-foreground">
                Manda o relatório de hoje, até este momento, para quem está na lista —
                para veres como fica sem esperar pelas 23:30.
              </p>
            </div>
            <Button
              type="button" variant="outline"
              onClick={enviarAgora}
              disabled={enviando || emails.length === 0}
              data-testid="relatorio-enviar-agora-btn"
            >
              {enviando ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                : <Send className="h-4 w-4 mr-1" />}
              {enviando ? 'A enviar...' : 'Enviar agora'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
