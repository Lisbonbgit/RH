// Download de ficheiros que funciona na WEB e na APP nativa (Capacitor).
// - Web: descarrega normalmente (blob + <a download>).
// - iOS/Android: o WKWebView não deixa descarregar blobs, por isso gravamos
//   o ficheiro no armazenamento e abrimos a folha de partilha (ver / guardar
//   em "Ficheiros" / abrir noutra app).
import { Capacitor } from '@capacitor/core';
import { Filesystem, Directory } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * Descarrega (web) ou guarda+abre (app) um ficheiro protegido por token.
 * @param {string} url      URL do endpoint de download
 * @param {string} filename nome do ficheiro
 * @param {string} token    JWT do utilizador (Bearer)
 */
export async function downloadOrOpenFile(url, filename, token) {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`download falhou (${response.status})`);
  const blob = await response.blob();

  if (!Capacitor.isNativePlatform()) {
    // WEB
    const objectUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename || 'documento';
    a.click();
    window.URL.revokeObjectURL(objectUrl);
    return;
  }

  // NATIVO: gravar em cache e abrir a folha de partilha
  const base64 = await blobToBase64(blob);
  const safeName = (filename || 'documento').replace(/[/\\?%*:|"<>]/g, '_');
  const written = await Filesystem.writeFile({
    path: safeName,
    data: base64,
    directory: Directory.Cache,
  });
  await Share.share({ title: filename, url: written.uri });
}
