// Geração de PDF no cliente (jsPDF + autotable), com a identidade Lisbonb.
// Cabeçalho azul com a marca, tabela com cabeçalho colorido e rodapé com nº de página.
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';

const BRAND = [19, 102, 240];   // #1366F0
const INK = [31, 41, 55];       // #1f2937
const MUTED = [107, 114, 128];  // #6b7280
const ZEBRA = [245, 247, 250];

function fmtNow() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * Descarrega um PDF com cabeçalho da marca e uma tabela.
 * @param {Object} opts
 * @param {string} opts.filename   nome do ficheiro (ex.: "horas.pdf")
 * @param {string} opts.title      título do relatório
 * @param {string[]} [opts.meta]   linhas de contexto (empresa, período…)
 * @param {string[]} opts.headers  cabeçalhos das colunas
 * @param {Array<Array>} opts.rows linhas (array de arrays)
 * @param {Array} [opts.foot]      linha de totais (opcional)
 * @param {'portrait'|'landscape'} [opts.orientation]
 * @param {string} [opts.footerNote] nota no rodapé
 * @param {Object} [opts.extraTable] segunda tabela {title, headers, rows} (opcional)
 */
export function downloadTablePDF({
  filename, title, meta = [], headers, rows, foot = null,
  orientation = 'portrait', footerNote = '', extraTable = null,
}) {
  const doc = new jsPDF({ orientation, unit: 'mm', format: 'a4' });
  const pageW = doc.internal.pageSize.getWidth();
  const marginX = 14;

  // ----- Cabeçalho da marca -----
  doc.setFillColor(...BRAND);
  doc.rect(0, 0, pageW, 24, 'F');
  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  doc.text('GESTÃO LISBONB', marginX, 9);
  doc.setFontSize(15);
  doc.text(title, marginX, 18);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.text(`Gerado em ${fmtNow()}`, pageW - marginX, 9, { align: 'right' });

  // ----- Linhas de contexto -----
  let y = 31;
  if (meta.length) {
    doc.setTextColor(...MUTED);
    doc.setFontSize(9.5);
    meta.forEach((line) => {
      doc.text(String(line), marginX, y);
      y += 5;
    });
    y += 1;
  }

  // ----- Tabela -----
  const drawFooter = () => {
    const pageH = doc.internal.pageSize.getHeight();
    doc.setFontSize(8);
    doc.setTextColor(...MUTED);
    const page = doc.internal.getNumberOfPages();
    if (footerNote) doc.text(footerNote, marginX, pageH - 8);
    doc.text(`Página ${page}`, pageW - marginX, pageH - 8, { align: 'right' });
  };

  autoTable(doc, {
    head: [headers],
    body: rows,
    foot: foot ? [foot] : undefined,
    startY: Math.max(y, 30),
    theme: 'striped',
    styles: { font: 'helvetica', fontSize: 9, cellPadding: 2.6, textColor: INK, lineColor: [229, 231, 235], lineWidth: 0.1 },
    headStyles: { fillColor: BRAND, textColor: 255, fontStyle: 'bold' },
    footStyles: { fillColor: [232, 240, 254], textColor: BRAND, fontStyle: 'bold' },
    alternateRowStyles: { fillColor: ZEBRA },
    margin: { left: marginX, right: marginX },
    didDrawPage: drawFooter,
  });

  // ----- Segunda tabela (opcional) -----
  if (extraTable) {
    const pageH = doc.internal.pageSize.getHeight();
    let startY = (doc.lastAutoTable?.finalY || 40) + 10;
    // Sem espaço para o título no fundo da página → começa em página nova
    if (startY > pageH - 40) {
      doc.addPage();
      startY = 30;
    }
    doc.setTextColor(...INK);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.text(extraTable.title, marginX, startY);
    autoTable(doc, {
      head: [extraTable.headers],
      body: extraTable.rows,
      startY: startY + 3,
      theme: 'striped',
      styles: { font: 'helvetica', fontSize: 9, cellPadding: 2.6, textColor: INK, lineColor: [229, 231, 235], lineWidth: 0.1 },
      headStyles: { fillColor: BRAND, textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: ZEBRA },
      margin: { left: marginX, right: marginX },
      didDrawPage: drawFooter,
    });
  }

  doc.save(filename);
}
