import React, { useEffect, useRef, useState } from 'react';
import { getMyProfile, updateMyProfile } from '../../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Camera, Loader2, User, Mail, Phone, MapPin, Calendar, Building2, Briefcase, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';

const initials = (name) =>
  (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toUpperCase();

export default function EmployeeProfile() {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);
  const [form, setForm] = useState({
    phone: '',
    address: '',
    birth_date: '',
    emergency_contact_name: '',
    emergency_contact_phone: '',
  });

  useEffect(() => {
    getMyProfile()
      .then((res) => {
        setProfile(res.data);
        setForm({
          phone: res.data.phone || '',
          address: res.data.address || '',
          birth_date: res.data.birth_date || '',
          emergency_contact_name: res.data.emergency_contact_name || '',
          emergency_contact_phone: res.data.emergency_contact_phone || '',
        });
      })
      .catch(() => toast.error('Erro ao carregar o perfil'))
      .finally(() => setLoading(false));
  }, []);

  const handlePhotoChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast.error('Selecione um ficheiro de imagem');
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new Image();
      img.onload = async () => {
        const max = 320;
        let { width, height } = img;
        if (width > height && width > max) {
          height = (height * max) / width;
          width = max;
        } else if (height > max) {
          width = (width * max) / height;
          height = max;
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        canvas.getContext('2d').drawImage(img, 0, 0, width, height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        setUploading(true);
        try {
          const res = await updateMyProfile({ photo: dataUrl });
          setProfile(res.data);
          toast.success('Foto atualizada!');
        } catch (err) {
          toast.error(err.response?.data?.detail || 'Erro ao atualizar a foto');
        } finally {
          setUploading(false);
        }
      };
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await updateMyProfile(form);
      setProfile(res.data);
      toast.success('Perfil atualizado!');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  const InfoRow = ({ icon: Icon, label, value }) => (
    <div className="flex items-center gap-3 py-2.5">
      <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
      <span className="text-sm text-muted-foreground w-32 shrink-0">{label}</span>
      <span className="text-sm font-medium">{value || '—'}</span>
    </div>
  );

  return (
    <div className="space-y-6 animate-fade-in max-w-2xl mx-auto" data-testid="employee-profile-page">
      <h1 className="text-2xl font-heading font-bold">O meu perfil</h1>

      {/* Avatar */}
      <Card>
        <CardContent className="p-6 flex flex-col items-center text-center">
          <div className="relative">
            <div className="h-28 w-28 rounded-full overflow-hidden bg-muted flex items-center justify-center ring-4 ring-primary/10">
              {profile?.photo ? (
                <img src={profile.photo} alt="Foto de perfil" className="h-full w-full object-cover" />
              ) : (
                <span className="text-3xl font-heading font-bold text-muted-foreground">{initials(profile?.name)}</span>
              )}
            </div>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="absolute -bottom-1 -right-1 h-9 w-9 rounded-full brand-gradient text-white flex items-center justify-center shadow-lg shadow-primary/30"
              data-testid="change-photo-btn"
              aria-label="Mudar foto"
            >
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
            </button>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handlePhotoChange} />
          </div>
          <h2 className="mt-4 text-xl font-heading font-bold">{profile?.name}</h2>
          <p className="text-sm text-muted-foreground">{profile?.position}{profile?.company_name ? ` · ${profile.company_name}` : ''}</p>
          <p className="text-xs text-muted-foreground mt-2">Toque na câmara para mudar a foto</p>
        </CardContent>
      </Card>

      {/* Dados pessoais (editáveis) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Dados pessoais</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="phone">Telemóvel</Label>
            <Input id="phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="Ex: 9XX XXX XXX" data-testid="profile-phone-input" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="address">Morada</Label>
            <Input id="address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="A sua morada" data-testid="profile-address-input" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="birth_date">Data de nascimento</Label>
            <Input id="birth_date" type="date" value={form.birth_date} onChange={(e) => setForm({ ...form, birth_date: e.target.value })} data-testid="profile-birthdate-input" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t">
            <div className="space-y-2">
              <Label htmlFor="ec_name" className="flex items-center gap-1.5"><ShieldAlert className="h-3.5 w-3.5 text-muted-foreground" />Contacto de emergência</Label>
              <Input id="ec_name" value={form.emergency_contact_name} onChange={(e) => setForm({ ...form, emergency_contact_name: e.target.value })} placeholder="Nome" data-testid="profile-ec-name-input" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ec_phone">Telefone de emergência</Label>
              <Input id="ec_phone" value={form.emergency_contact_phone} onChange={(e) => setForm({ ...form, emergency_contact_phone: e.target.value })} placeholder="Telefone" data-testid="profile-ec-phone-input" />
            </div>
          </div>
          <Button onClick={handleSave} disabled={saving} className="w-full sm:w-auto" data-testid="save-profile-btn">
            {saving ? 'A guardar...' : 'Guardar alterações'}
          </Button>
        </CardContent>
      </Card>

      {/* Dados profissionais (só leitura) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Dados profissionais</CardTitle>
        </CardHeader>
        <CardContent className="divide-y divide-border">
          <InfoRow icon={User} label="Nome" value={profile?.name} />
          <InfoRow icon={Mail} label="Email" value={profile?.email} />
          <InfoRow icon={Building2} label="Empresa" value={profile?.company_name} />
          <InfoRow icon={MapPin} label="Local" value={profile?.location_name} />
          <InfoRow icon={Briefcase} label="Cargo" value={profile?.position} />
          <InfoRow icon={Phone} label="Tipo de contrato" value={profile?.contract_type} />
          <InfoRow icon={Calendar} label="Início" value={profile?.start_date} />
          <InfoRow icon={Calendar} label="Férias" value={`${profile?.vacation_days_available ?? 0} de ${profile?.vacation_days ?? 0} dias disponíveis`} />
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground text-center pb-4">
        Para alterar dados profissionais (cargo, empresa, etc.), contacte a administração.
      </p>
    </div>
  );
}
