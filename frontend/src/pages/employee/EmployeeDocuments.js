import React, { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { getFolders, getDocuments, uploadDocument } from '../../lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Badge } from '../../components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import { FileText, Folder, Download, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

export default function EmployeeDocuments() {
  const { user } = useAuth();
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (user?.employee_id) {
      fetchFolders();
    }
  }, [user]);

  useEffect(() => {
    if (selectedFolder) {
      fetchDocuments();
    }
  }, [selectedFolder]);

  const fetchFolders = async () => {
    setLoading(true);
    try {
      const response = await getFolders(user.employee_id);
      setFolders(response.data);
    } catch (error) {
      toast.error('Erro ao carregar pastas');
    } finally {
      setLoading(false);
    }
  };

  const fetchDocuments = async () => {
    try {
      const response = await getDocuments({ folder_id: selectedFolder.id });
      setDocuments(response.data);
    } catch (error) {
      toast.error('Erro ao carregar documentos');
    }
  };

  const handleDownload = async (doc) => {
    try {
      const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';
      const token = localStorage.getItem('token');
      const response = await fetch(`${API_URL}/documents/${doc.id}/download`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = doc.name;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      toast.error('Erro ao descarregar documento');
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadFile) {
      toast.error('Selecione um ficheiro');
      return;
    }
    setSaving(true);
    try {
      await uploadDocument(selectedFolder.id, uploadFile);
      toast.success('Documento enviado com sucesso');
      setUploadDialogOpen(false);
      setUploadFile(null);
      fetchDocuments();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao enviar documento');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in pb-4" data-testid="employee-documents-page">
      <div>
        <h1 className="text-xl font-heading font-bold">Meus Documentos</h1>
        <p className="text-sm text-muted-foreground">Visualize e envie documentos</p>
      </div>

      {/* Folders */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Folder className="h-4 w-4" />
            Pastas
          </CardTitle>
        </CardHeader>
        <CardContent>
          {folders.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              Sem pastas disponíveis
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {folders.map((folder) => (
                <Button
                  key={folder.id}
                  variant={selectedFolder?.id === folder.id ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setSelectedFolder(folder)}
                  data-testid={`folder-${folder.id}`}
                >
                  <Folder className="h-4 w-4 mr-2" />
                  {folder.name}
                  {folder.allow_employee_upload && (
                    <Badge variant="secondary" className="ml-2 text-xs">
                      Upload
                    </Badge>
                  )}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Documents */}
      {selectedFolder && (
        <Card data-testid="documents-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  Documentos em "{selectedFolder.name}"
                </CardTitle>
                <CardDescription>
                  {documents.length} documento{documents.length !== 1 ? 's' : ''}
                </CardDescription>
              </div>
              {selectedFolder.allow_employee_upload && (
                <Button size="sm" onClick={() => setUploadDialogOpen(true)} data-testid="upload-btn">
                  <Upload className="h-4 w-4 mr-2" />
                  Enviar
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {documents.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                Sem documentos nesta pasta
              </p>
            ) : (
              <div className="space-y-2">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between p-3 bg-muted rounded-lg"
                    data-testid={`document-${doc.id}`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <p className="font-medium text-sm truncate">{doc.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {format(parseISO(doc.created_at), 'dd/MM/yyyy')}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDownload(doc)}
                      data-testid={`download-doc-${doc.id}`}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!selectedFolder && folders.length > 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Folder className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="font-medium text-lg">Selecione uma Pasta</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Escolha uma pasta para ver os documentos
            </p>
          </CardContent>
        </Card>
      )}

      {/* Upload Dialog */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent data-testid="upload-dialog">
          <DialogHeader>
            <DialogTitle>Enviar Documento</DialogTitle>
            <DialogDescription>
              Enviar documento para "{selectedFolder?.name}"
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleUpload}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="file">Selecionar Ficheiro *</Label>
                <Input
                  id="file"
                  type="file"
                  onChange={(e) => setUploadFile(e.target.files[0])}
                  required
                  data-testid="file-input"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setUploadDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="submit-upload-btn">
                {saving ? 'A enviar...' : 'Enviar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
