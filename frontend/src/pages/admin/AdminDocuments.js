import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getEmployees, getFolders, createFolder, getDocuments, uploadDocument, deleteDocument, deleteFolder } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Checkbox } from '../../components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { ScrollArea } from '../../components/ui/scroll-area';
import { FileText, Folder, Plus, Upload, Download, Trash2, User, FolderPlus } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

export default function AdminDocuments() {
  const { selectedCompany } = useOutletContext();
  const [employees, setEmployees] = useState([]);
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [folders, setFolders] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [folderDialogOpen, setFolderDialogOpen] = useState(false);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [deleteDocDialogOpen, setDeleteDocDialogOpen] = useState(false);
  const [deleteFolderDialogOpen, setDeleteFolderDialogOpen] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [folderToDelete, setFolderToDelete] = useState(null);
  const [folderForm, setFolderForm] = useState({ name: '', allow_employee_upload: false });
  const [uploadFile, setUploadFile] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchEmployees();
  }, [selectedCompany]);

  useEffect(() => {
    if (selectedEmployee) {
      fetchFolders();
    }
  }, [selectedEmployee]);

  useEffect(() => {
    if (selectedFolder) {
      fetchDocuments();
    }
  }, [selectedFolder]);

  const fetchEmployees = async () => {
    setLoading(true);
    try {
      const response = await getEmployees({ company_id: selectedCompany?.id });
      setEmployees(response.data);
      setSelectedEmployee(null);
      setFolders([]);
      setDocuments([]);
    } catch (error) {
      toast.error('Erro ao carregar colaboradores');
    } finally {
      setLoading(false);
    }
  };

  const fetchFolders = async () => {
    try {
      const response = await getFolders(selectedEmployee.id);
      setFolders(response.data);
      setSelectedFolder(null);
      setDocuments([]);
    } catch (error) {
      toast.error('Erro ao carregar pastas');
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

  const handleCreateFolder = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await createFolder({
        name: folderForm.name,
        employee_id: selectedEmployee.id,
        allow_employee_upload: folderForm.allow_employee_upload
      });
      toast.success('Pasta criada com sucesso');
      setFolderDialogOpen(false);
      setFolderForm({ name: '', allow_employee_upload: false });
      fetchFolders();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao criar pasta');
    } finally {
      setSaving(false);
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

  const handleDeleteDocument = async () => {
    try {
      await deleteDocument(selectedDocument.id);
      toast.success('Documento eliminado com sucesso');
      setDeleteDocDialogOpen(false);
      setSelectedDocument(null);
      fetchDocuments();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar documento');
    }
  };

  const handleDeleteFolder = async () => {
    try {
      await deleteFolder(folderToDelete.id);
      toast.success('Pasta eliminada com sucesso');
      setDeleteFolderDialogOpen(false);
      setFolderToDelete(null);
      if (selectedFolder?.id === folderToDelete.id) {
        setSelectedFolder(null);
        setDocuments([]);
      }
      fetchFolders();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar pasta');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-documents-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-heading font-bold">Documentos</h1>
        <p className="text-muted-foreground mt-1">
          {selectedCompany ? `Documentos de ${selectedCompany.name}` : 'Gerir documentos dos colaboradores'}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Employee List */}
        <Card className="lg:col-span-1">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <User className="h-4 w-4" />
              Colaboradores
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[400px]">
              {loading ? (
                <div className="flex items-center justify-center h-20">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
                </div>
              ) : employees.length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  Sem colaboradores
                </div>
              ) : (
                <div className="space-y-1 p-2">
                  {employees.map((emp) => (
                    <button
                      key={emp.id}
                      onClick={() => setSelectedEmployee(emp)}
                      className={`w-full text-left p-3 rounded-lg transition-colors ${
                        selectedEmployee?.id === emp.id
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-muted'
                      }`}
                      data-testid={`employee-${emp.id}`}
                    >
                      <p className="font-medium text-sm">{emp.name}</p>
                      <p className={`text-xs ${selectedEmployee?.id === emp.id ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                        {emp.position}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Folders and Documents */}
        <div className="lg:col-span-3 space-y-4">
          {selectedEmployee ? (
            <>
              {/* Folders */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Folder className="h-4 w-4" />
                      Pastas de {selectedEmployee.name}
                    </CardTitle>
                    <Button size="sm" onClick={() => setFolderDialogOpen(true)} data-testid="create-folder-btn">
                      <FolderPlus className="h-4 w-4 mr-2" />
                      Nova Pasta
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {folders.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">
                      Sem pastas criadas
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {folders.map((folder) => (
                        <div key={folder.id} className="flex items-center gap-1">
                          <Button
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
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => {
                              setFolderToDelete(folder);
                              setDeleteFolderDialogOpen(true);
                            }}
                            data-testid={`delete-folder-${folder.id}`}
                          >
                            <Trash2 className="h-3 w-3 text-destructive" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Documents */}
              {selectedFolder && (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        Documentos em "{selectedFolder.name}"
                      </CardTitle>
                      <Button size="sm" onClick={() => setUploadDialogOpen(true)} data-testid="upload-document-btn">
                        <Upload className="h-4 w-4 mr-2" />
                        Enviar Documento
                      </Button>
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
                                  Enviado por {doc.uploaded_by_name} • {format(parseISO(doc.created_at), 'dd/MM/yyyy')}
                                </p>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleDownload(doc)}
                                data-testid={`download-doc-${doc.id}`}
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => {
                                  setSelectedDocument(doc);
                                  setDeleteDocDialogOpen(true);
                                }}
                                data-testid={`delete-doc-${doc.id}`}
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-center">
                <User className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="font-medium text-lg">Selecione um Colaborador</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Escolha um colaborador para ver e gerir os seus documentos
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Create Folder Dialog */}
      <Dialog open={folderDialogOpen} onOpenChange={setFolderDialogOpen}>
        <DialogContent data-testid="folder-dialog">
          <DialogHeader>
            <DialogTitle>Nova Pasta</DialogTitle>
            <DialogDescription>
              Criar uma nova pasta para {selectedEmployee?.name}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateFolder}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="folder_name">Nome da Pasta *</Label>
                <Input
                  id="folder_name"
                  value={folderForm.name}
                  onChange={(e) => setFolderForm({ ...folderForm, name: e.target.value })}
                  placeholder="Ex: Certificados"
                  required
                  data-testid="folder-name-input"
                />
              </div>
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="allow_upload"
                  checked={folderForm.allow_employee_upload}
                  onCheckedChange={(checked) => setFolderForm({ ...folderForm, allow_employee_upload: checked })}
                  data-testid="allow-upload-checkbox"
                />
                <Label htmlFor="allow_upload" className="text-sm">
                  Permitir que o colaborador envie documentos para esta pasta
                </Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setFolderDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="save-folder-btn">
                {saving ? 'A criar...' : 'Criar Pasta'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

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
              <Button type="submit" disabled={saving} data-testid="upload-btn">
                {saving ? 'A enviar...' : 'Enviar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Document Dialog */}
      <AlertDialog open={deleteDocDialogOpen} onOpenChange={setDeleteDocDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Documento</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar o documento "{selectedDocument?.name}"?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteDocument} className="bg-destructive text-destructive-foreground" data-testid="confirm-delete-doc-btn">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Folder Dialog */}
      <AlertDialog open={deleteFolderDialogOpen} onOpenChange={setDeleteFolderDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Pasta</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar a pasta "{folderToDelete?.name}" e todos os documentos dentro?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteFolder} className="bg-destructive text-destructive-foreground" data-testid="confirm-delete-folder-btn">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
