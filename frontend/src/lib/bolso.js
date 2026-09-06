// Chamadas da Gestão de Bolso — instância própria de axios, deliberadamente à
// parte do `axios` global.
//
// O `AuthContext` guarda o JWT em `axios.defaults.headers.common`, que é um
// objecto GLOBAL partilhado por toda a SPA — incluindo a app Capacitor do
// ponto, que corre este mesmo bundle. Um interceptor de erro posto no axios
// global dispararia lá dentro também. É a mesma razão que levou o POS a ter a
// sua própria instância (`lib/pos.js`), e é a mesma solução.
//
// O token lê-se do `localStorage` A CADA PEDIDO, e não uma vez no arranque:
// quem entra com outra conta a meio da sessão do browser tem de ver o pedido
// seguinte a viajar com o token novo.
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api/bolso';

// **15 segundos, e não "para sempre".** Sem `timeout` o axios espera
// indefinidamente: no 4G de um café isso é um ecrã preso num spinner, sem uma
// palavra e sem saída. O painel é UM pedido só — se ele pendurar, não há mais
// nada no ecrã para olhar.
export const TIMEOUT_MS = 15000;

const api = axios.create({ baseURL: API_URL, timeout: TIMEOUT_MS });

api.interceptors.request.use((config) => {
  let token = null;
  try { token = localStorage.getItem('token'); } catch (e) { /* modo privado */ }
  config.headers = config.headers || {};
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// `empresa` é o id de uma empresa ou 'all' (o grupo); `unidade` é a loja, o
// terceiro nível, e só faz sentido DENTRO de uma empresa (o servidor recusa-a
// com 400 no grupo). Vai fora do objecto quando é nula para não mandar
// `unidade=null` na query string, que o FastAPI leria como a string "null".
//
// O servidor decide o que o âmbito quer dizer — 'all' soma só as empresas onde este utilizador é membro, e
// a resposta diz sempre QUAIS foram somadas.
export const getPainel = (empresa = 'all', unidade = null) =>
  api.get('/painel', { params: unidade ? { empresa, unidade } : { empresa } });

// O dinheiro escreve-se sempre com duas casas e o símbolo à frente, como no
// resto do portal. **`null` não é zero**: um valor que o servidor não soube
// dizer sai "—" e nunca "0,00 €" — é a regra da casa, e é por isso que este
// formatador não copia o `eur()` do `lib/finance.js`, que faz `Number(n) || 0`
// e transformaria um "não sei" num zero com ar de facto.
export const euros = (valor) => {
  if (valor === null || valor === undefined || !Number.isFinite(Number(valor))) return '—';
  return `€ ${Number(valor).toLocaleString('pt-PT', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
};

// A percentagem, com o sinal à frente. `null` (não havia período anterior)
// devolve `null` — quem desenha decide o que mostrar, e nunca mostra "0%".
export const percentagem = (v) => {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return null;
  const n = Number(v);
  return `${n >= 0 ? '+' : '−'}${Math.abs(n).toLocaleString('pt-PT', {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  })}%`;
};

// "às 09:04" a partir do carimbo ISO que o servidor manda. Hoje mostra a hora;
// noutro dia mostra o dia e a hora, porque "às 09:04" sobre uma leitura de
// anteontem é uma meia-verdade que se lê como uma leitura fresca.
export const quandoFoi = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hoje = new Date();
  const mesmoDia = d.toDateString() === hoje.toDateString();
  const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
  if (mesmoDia) return `às ${hora}`;
  return `${d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit' })} às ${hora}`;
};
