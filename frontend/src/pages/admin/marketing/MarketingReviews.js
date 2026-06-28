import React, { useEffect, useState, useCallback } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import { getReviews } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Badge } from '../../../components/ui/badge';
import {
  Star, RefreshCw, MapPin, ExternalLink, AlertTriangle, Loader2,
  MessageSquare, Building2, Settings2, KeyRound,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { pt } from 'date-fns/locale';

// Estrelas (preenchidas conforme a nota)
function Stars({ rating, size = 'h-4 w-4' }) {
  const r = rating || 0;
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${r} de 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={`${size} ${i <= Math.round(r) ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/25'}`}
        />
      ))}
    </span>
  );
}

function timeAgo(iso) {
  if (!iso) return null;
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: pt });
  } catch {
    return null;
  }
}

// Iniciais para fallback do avatar
function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
}

function ReviewItem({ r }) {
  const [imgOk, setImgOk] = useState(true);
  return (
    <div className="flex gap-3 py-3 border-b last:border-0">
      {r.author_photo && imgOk ? (
        <img
          src={r.author_photo}
          alt={r.author}
          onError={() => setImgOk(false)}
          className="h-9 w-9 rounded-full object-cover shrink-0"
          referrerPolicy="no-referrer"
        />
      ) : (
        <div className="h-9 w-9 rounded-full bg-primary/10 text-primary grid place-items-center text-xs font-semibold shrink-0">
          {initials(r.author)}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium truncate">{r.author || 'Anónimo'}</span>
          <span className="text-xs text-muted-foreground shrink-0">{r.relative_time}</span>
        </div>
        <Stars rating={r.rating} size="h-3.5 w-3.5" />
        {r.text && <p className="text-sm text-muted-foreground mt-1 whitespace-pre-line">{r.text}</p>}
      </div>
    </div>
  );
}

function LocationCard({ loc }) {
  if (!loc.configured) {
    return (
      <Card className="border-dashed">
        <CardContent className="p-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="font-medium truncate">{loc.location_name}</p>
            <p className="text-xs text-muted-foreground">Ainda não está ligada ao Google</p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/locais"><Settings2 className="h-4 w-4 mr-1.5" /> Ligar</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4 space-y-3">
        {/* Cabeçalho da loja */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <MapPin className="h-4 w-4 text-primary shrink-0" />
              <p className="font-medium truncate">{loc.location_name}</p>
            </div>
            {loc.fetched_at && (
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Atualizado {timeAgo(loc.fetched_at)}{loc.cached ? ' (cache)' : ''}
              </p>
            )}
          </div>
          {loc.google_url && (
            <a
              href={loc.google_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline shrink-0"
            >
              Google <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        {/* Nota / total */}
        {loc.rating != null ? (
          <div className="flex items-center gap-3 rounded-lg bg-amber-50 border border-amber-100 px-3 py-2">
            <span className="text-3xl font-heading font-bold text-amber-600 leading-none">
              {Number(loc.rating).toFixed(1)}
            </span>
            <div>
              <Stars rating={loc.rating} />
              <p className="text-xs text-muted-foreground mt-0.5">
                {loc.total} {loc.total === 1 ? 'avaliação' : 'avaliações'}
              </p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Sem classificação disponível.</p>
        )}

        {loc.error && (
          <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{loc.error}</span>
          </div>
        )}

        {/* Avaliações recentes */}
        {loc.reviews && loc.reviews.length > 0 ? (
          <div>
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-1">
              <MessageSquare className="h-3.5 w-3.5" /> Avaliações recentes
            </div>
            <div className="-my-1">
              {loc.reviews.map((r, idx) => <ReviewItem key={idx} r={r} />)}
            </div>
          </div>
        ) : (
          !loc.error && <p className="text-xs text-muted-foreground">Ainda sem avaliações com texto.</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function MarketingReviews() {
  const { selectedCompany } = useOutletContext();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async (refresh = false) => {
    refresh ? setRefreshing(true) : setLoading(true);
    try {
      const res = await getReviews({ company_id: selectedCompany?.id, refresh });
      setData(res.data);
      if (refresh) toast.success('Avaliações atualizadas a partir da Google');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao carregar avaliações');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedCompany]);

  useEffect(() => { fetchData(false); }, [fetchData]);

  const summary = data?.summary;
  const locations = data?.locations || [];

  // agrupar por empresa
  const byCompany = locations.reduce((acc, loc) => {
    const key = loc.company_name || 'Sem empresa';
    (acc[key] = acc[key] || []).push(loc);
    return acc;
  }, {});

  return (
    <div className="space-y-6 animate-fade-in" data-testid="marketing-reviews-page">
      <PageHeader
        icon={Star}
        title="Avaliações"
        subtitle={selectedCompany ? `Reputação de ${selectedCompany.name} no Google` : 'Reputação do grupo no Google, por loja'}
      >
        <Button variant="outline" onClick={() => fetchData(true)} disabled={refreshing || loading}>
          {refreshing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
          Atualizar
        </Button>
      </PageHeader>

      {/* Aviso: chave Google não configurada */}
      {data && !data.api_configured && (
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="p-4 flex items-start gap-3">
            <KeyRound className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-800 space-y-1">
              <p className="font-medium">A ligação à Google ainda não está ativa.</p>
              <p className="text-amber-700">
                Falta a chave da <strong>Google Places API</strong> no servidor. Crie a chave na Google Cloud
                Console (ative "Places API") e envie-a para ser adicionada com segurança ao servidor.
                Depois, ligue cada loja ao Google em <Link to="/admin/locais" className="underline font-medium">Locais</Link>.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Resumo */}
      {!loading && summary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">Classificação média</p>
              {summary.avg_rating != null ? (
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-3xl font-heading font-bold text-amber-600 leading-none">
                    {Number(summary.avg_rating).toFixed(1)}
                  </span>
                  <Stars rating={summary.avg_rating} />
                </div>
              ) : (
                <p className="text-2xl font-heading font-bold mt-1">—</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">Total de avaliações</p>
              <p className="text-3xl font-heading font-bold mt-1">{summary.total_reviews}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">Lojas ligadas ao Google</p>
              <p className="text-3xl font-heading font-bold mt-1">
                {summary.configured_locations}
                <span className="text-base text-muted-foreground font-body"> / {summary.total_locations}</span>
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Conteúdo */}
      {loading ? (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
        </div>
      ) : locations.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Star className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="font-medium text-lg">Sem lojas</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Crie locais em <Link to="/admin/locais" className="underline">Locais</Link> e ligue-os ao Google.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {Object.entries(byCompany).map(([company, locs]) => (
            <div key={company} className="space-y-3">
              <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-heading font-semibold">{company}</h3>
                <Badge variant="outline" className="text-xs">{locs.length}</Badge>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {locs.map((loc) => <LocationCard key={loc.location_id} loc={loc} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
