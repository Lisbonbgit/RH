// Utilitário simples para exportar dados para CSV (abre no Excel/Numbers).
// Não precisa de bibliotecas externas.

function escapeCell(value) {
  if (value == null) return '';
  const str = String(value);
  // Envolve em aspas se tiver vírgula, aspas ou quebra de linha
  if (/[",\n;]/.test(str)) {
    return '"' + str.replace(/"/g, '""') + '"';
  }
  return str;
}

/**
 * Descarrega um ficheiro CSV.
 * @param {string} filename  nome do ficheiro (ex.: "ponto.csv")
 * @param {string[]} headers cabeçalhos das colunas
 * @param {Array<Array>} rows linhas (array de arrays)
 */
export function downloadCSV(filename, headers, rows) {
  // BOM (﻿) garante acentos corretos no Excel
  const lines = [headers, ...rows].map((row) => row.map(escapeCell).join(';'));
  const csv = '﻿' + lines.join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
