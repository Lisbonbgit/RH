// Face ID da app «Gestão Lisbonb» — a ponte para a peça nativa da casca.
//
// A peça é o `@capgo/capacitor-native-biometric@6.0.4`, instalada SÓ na casca
// (`app-bolso/`). O site não a leva como dependência: regista-a pelo nome com o
// `registerPlugin` do `@capacitor/core` que já tem. **Sem implementação web de
// propósito** — com uma, o `isPluginAvailable` dava `true` no browser.
//
// **A versão 6 guarda a senha no Keychain SEM a prender ao Face ID**: o
// `getCredentials` devolve-a sem pedir nada. Quem garante o Face ID é este
// ficheiro: `ler()` só lê depois de `verificar()` passar. Nunca chamar o
// `getCredentials` por outro caminho.
//
// Nada aqui rebenta: sem a peça (browser, build 2 da casca, app do ponto) tudo
// devolve «não» e o resto do site fica como estava.
import { Capacitor, registerPlugin } from '@capacitor/core';

const NOME = 'NativeBiometric';
const NativeBiometric = registerPlugin(NOME);

// O `server` do Keychain (kSecAttrServer). Fixo: é a chave da gaveta, não um endereço.
const SERVIDOR = 'gestao.lisbonb.com';
// Quem activou o Face ID neste telemóvel. Serve para a barreira dizer «Entrar
// como …» SEM ler o Keychain antes do Face ID.
const CHAVE_EMAIL = 'faceid_email';

// A barreira e a re-entrada podem pedir o Face ID com segundos de diferença
// (arranque com a sessão expirada): um rosto vale este tempo, e não se pede outro.
export const JANELA_MS = 60 * 1000;
let verificadoAs = 0;

// Códigos do plugin (BiometricAuthError) que NÃO são a pessoa a recusar: a app
// a perder o primeiro plano, o sistema a interromper. Não terminam a sessão.
const INTERROMPIDO = ['11', '13', '15'];

// Um pedido de rosto de cada vez: um `verificar()` que chegue enquanto outro
// corre partilha-o (o `<React.StrictMode>` do `craco start` monta a Barreira
// duas vezes). Dois pedidos seguidos ao iPhone podiam cancelar-se um ao outro.
let emVerificacao = null;

export const pluginPresente = () => Capacitor.isPluginAvailable(NOME);

export const emailGuardado = () => {
  try { return localStorage.getItem(CHAVE_EMAIL); } catch (e) { return null; }
};

// Ligado = a peça existe E alguém activou o Face ID neste telemóvel. Síncrono.
export const faceIdLigado = () => pluginPresente() && !!emailGuardado();

// O telemóvel consegue fazer Face ID agora (tem a peça, o rosto registado e a licença dada).
export async function temFaceId() {
  if (!pluginPresente()) return false;
  try {
    const r = await NativeBiometric.isAvailable({ useFallback: false });
    return r?.isAvailable === true;
  } catch (e) {
    return false;
  }
}

// true = passou · false = falhou ou a pessoa cancelou · null = interrompido pelo sistema.
// Só biometria (`useFallback: false`): o código do iPhone não abre a senha da gestão.
export async function verificar() {
  if (Date.now() - verificadoAs < JANELA_MS) return true;
  if (!pluginPresente()) return false;
  emVerificacao ??= NativeBiometric.verifyIdentity({
    reason: 'Entrar na Gestão Lisbonb',
    title: 'Gestão Lisbonb',
    useFallback: false,
  })
    .then(() => { verificadoAs = Date.now(); return true; })
    .catch((e) => (INTERROMPIDO.includes(String(e?.code)) ? null : false))
    .finally(() => { emVerificacao = null; });
  return emVerificacao;
}

// { email, senha } ou null. **Só depois do Face ID** — ver o topo do ficheiro.
export async function ler() {
  if ((await verificar()) !== true) return null;
  try {
    const c = await NativeBiometric.getCredentials({ server: SERVIDOR });
    return c?.username && c?.password ? { email: c.username, senha: c.password } : null;
  } catch (e) {
    return null;
  }
}

export async function guardar(email, senha) {
  if (!pluginPresente()) return false;
  try {
    await NativeBiometric.setCredentials({ username: email, password: senha, server: SERVIDOR });
    localStorage.setItem(CHAVE_EMAIL, email);
    return true;
  } catch (e) {
    return false;
  }
}

export async function apagar() {
  try { localStorage.removeItem(CHAVE_EMAIL); } catch (e) { /* modo privado */ }
  if (!pluginPresente()) return;
  try { await NativeBiometric.deleteCredentials({ server: SERVIDOR }); } catch (e) { /* já não havia */ }
}
