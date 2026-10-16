// A sessão da app «Gestão Lisbonb» com Face ID — as decisões, fora do React.
//
// Três peças, todas testadas em Node (backend/tests/fin/test_sessao_do_bolso.py):
//   1. a BARREIRA: um ecrã opaco depois de mais de 5 minutos fora; enquanto está
//      fechada, os pedidos do `lib/bolso.js` esperam (`esperarBarreira`);
//   2. a RE-ENTRADA: a sessão de 24 h expirou → Face ID → Keychain → login,
//      UMA só para todos os pedidos que deram 401 ao mesmo tempo;
//   3. a PERGUNTA depois de um login com senha, e o «não» lembrado por email.
//
// Sem a peça nativa (browser, build 2, app do ponto) nada disto actua.
import {
  apagar, emailGuardado, faceIdLigado, guardar, ler, temFaceId, verificar,
} from './faceid';

export const CINCO_MINUTOS = 5 * 60 * 1000;
const CHAVE_SAIU = 'saiuAs';
const CHAVE_RECUSA = 'faceid_recusado:';

const lerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const gravarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } };

// --- 1. A barreira -------------------------------------------------------------

// Saiu há 5 minutos ou menos? Sem `saiuAs` conta como arranque (→ não).
export const voltouATempo = (agora = Date.now()) => {
  const saiu = Number(lerLocal(CHAVE_SAIU));
  return saiu > 0 && agora - saiu <= CINCO_MINUTOS;
};

// Decide-se ao carregar a página, antes de qualquer ecrã montar: os efeitos dos
// filhos correm ANTES dos do pai, e o primeiro pedido do painel não pode sair
// à frente da barreira.
let fechada = faceIdLigado() && !voltouATempo();
let aEspera = [];

export const barreiraFechada = () => fechada;

export function abrirBarreira() {
  fechada = false;
  aEspera.splice(0).forEach((soltar) => soltar());
}

// Ao esconder. Sem Face ID ligado não fecha nada: no browser, esconder o
// separador fechava a porta e ninguém a voltava a abrir.
export function fecharBarreira(agora = Date.now()) {
  if (!faceIdLigado()) return false;
  // `saiuAs` = a hora a que se saiu de uma sessão ABERTA. Com a barreira ainda
  // fechada (ir ao ecrã principal enquanto o Face ID pede o rosto) não se grava:
  // senão, ao voltar logo, contava como «voltou a tempo» e abria sem rosto.
  if (!fechada) gravarLocal(CHAVE_SAIU, String(agora));
  fechada = true;
  return true;
}

export const esperarBarreira = () => (
  fechada ? new Promise((soltar) => { aEspera.push(soltar); }) : Promise.resolve()
);

// --- 2. A re-entrada -----------------------------------------------------------

// O `login(email, senha)` do AuthContext: grava o token, o cabeçalho e o estado.
let entrar = null;
export const ligarEntrada = (fn) => { entrar = fn; };

async function tentarReentrar() {
  if (!entrar || !faceIdLigado()) return false;
  const credenciais = await ler(); // pede o Face ID, salvo se acabou de passar
  if (!credenciais) return false;
  try {
    await entrar(credenciais.email, credenciais.senha);
    return true;
  } catch (e) {
    // **Só o 401 do login apaga o Keychain**: a senha guardada já não é a certa.
    // Um 429 (limite de tentativas) ou a rede em baixo não dizem nada da senha.
    if (e?.response?.status === 401) await apagar();
    return false;
  }
}

// Dois pedidos com 401 ao mesmo tempo → uma só re-entrada (um só Face ID, um
// só login). Limpa-se DEPOIS de acabar, para a próxima expiração tentar de novo.
let emCurso = null;
export function reentrar() {
  if (!emCurso) {
    emCurso = tentarReentrar()
      .catch(() => false)
      .finally(() => { emCurso = null; });
  }
  return emCurso;
}

// --- 3. Depois de um login com senha -------------------------------------------

export const recusar = (email) => gravarLocal(CHAVE_RECUSA + email, '1');
export const esquecerRecusa = (email) => {
  try { localStorage.removeItem(CHAVE_RECUSA + email); } catch (e) { /* modo privado */ }
};

// 'perguntar' ou 'nada'. Quem já tem o Face ID ligado com este email não é
// perguntado: a senha que acabou de escrever substitui a guardada (é assim
// que uma senha trocada se cura sozinha).
export async function depoisDoLoginComSenha(email, senha) {
  if (!(await temFaceId())) return 'nada';
  if (emailGuardado() === email) {
    await guardar(email, senha);
    return 'nada';
  }
  return lerLocal(CHAVE_RECUSA + email) ? 'nada' : 'perguntar';
}

// O «Sim»: o Face ID passa primeiro (é aqui que o iPhone pede a licença), só
// depois se guarda. Recusar a licença não deixa uma senha guardada sem uso.
export async function ligarFaceId(email, senha) {
  if ((await verificar()) !== true) return false;
  return guardar(email, senha);
}
