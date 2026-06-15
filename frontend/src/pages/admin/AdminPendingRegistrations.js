import React, { useState, useEffect } from 'react';
import { getPendingRegistrations, approveRegistration, rejectRegistration } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { UserPlus, Check, X, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

export default function AdminPendingRegistrations() {
  const { user } = useAuth();
  const [registrations, setRegistrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedReg, setSelectedReg] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null); // 'approve' or 'reject'

  const isMasterAdmin = user?.is_master_admin === true;

  useEffect(() => {
    if (isMasterAdmin) {
      fetchRegistrations();
    } else {
      setLoading(false);
    }
  }, [isMasterAdmin]);

  const fetchRegistrations = async () => {
    setLoading(true);
    try {
      const response = await getPendingRegistrations();
      setRegistrations(response.data);
    } catch (error) {
      if (error.response?.status !== 403) {
        toast.error('Erro ao carregar registos pendentes');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    try {
      await approveRegistration(selectedReg.id, 'admin');
      toast.success(`${selectedReg.name} aprovado com sucesso`);
      setConfirmAction(null);
      setSelectedReg(null);
      fetchRegistrations();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao aprovar registo');
    }
  };

  const handleReject = async () => {
    try {
      await rejectRegistration(selectedReg.id);
      toast.success(`Registo de ${selectedReg.name} rejeitado`);
      setConfirmAction(null);
      setSelectedReg(null);
      fetchRegistrations();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao rejeitar registo');
    }
  };

  if (!isMasterAdmin) {
    return (
      <div className="space-y-6 animate-fade-in" data-testid="admin-pending-page">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <ShieldAlert className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="font-medium text-lg">Acesso Restrito</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Apenas o administrador master pode gerir pedidos de registo.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-pending-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-heading font-bold">Pedidos de Registo</h1>
        <p className="text-muted-foreground mt-1">Aprovar ou rejeitar novos utilizadores</p>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : registrations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <UserPlus className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem pedidos pendentes</h3>
              <p className="text-sm text-muted-foreground mt-1">Nenhum pedido de registo a aguardar aprovação</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="hidden sm:table-cell">Data do Pedido</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {registrations.map((reg) => (
                    <TableRow key={reg.id} data-testid={`registration-row-${reg.id}`}>
                      <TableCell className="font-medium">{reg.name}</TableCell>
                      <TableCell>{reg.email}</TableCell>
                      <TableCell className="hidden sm:table-cell text-muted-foreground">
                        {format(parseISO(reg.created_at), 'dd/MM/yyyy HH:mm')}
                      </TableCell>
                      <TableCell>
                        <Badge className="badge-pendente">Pendente</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedReg(reg);
                              setConfirmAction('approve');
                            }}
                            data-testid={`approve-${reg.id}`}
                          >
                            <Check className="h-4 w-4 text-green-600" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedReg(reg);
                              setConfirmAction('reject');
                            }}
                            data-testid={`reject-${reg.id}`}
                          >
                            <X className="h-4 w-4 text-red-600" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Approve Dialog */}
      <AlertDialog open={confirmAction === 'approve'} onOpenChange={() => setConfirmAction(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Aprovar Registo</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende aprovar o registo de <strong>{selectedReg?.name}</strong> ({selectedReg?.email})?
              <br /><br />
              O utilizador terá acesso como Administrador.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleApprove} className="bg-green-600 hover:bg-green-700" data-testid="confirm-approve-btn">
              Aprovar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reject Dialog */}
      <AlertDialog open={confirmAction === 'reject'} onOpenChange={() => setConfirmAction(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Rejeitar Registo</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende rejeitar o registo de <strong>{selectedReg?.name}</strong> ({selectedReg?.email})?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleReject} className="bg-destructive text-destructive-foreground" data-testid="confirm-reject-btn">
              Rejeitar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
