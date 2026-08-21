import React from 'react';

// Os números de um turno, desenhados uma única vez.
//
// **O mesmo bloco no Ponto de Caixa (a conferência a meio da tarde) e no Z
// (o fecho).** Não é economia de linhas: é a mesma razão por que o servidor
// tem uma só `_resumo_do_turno`. Se o "deve estar na gaveta" das 15h
// aparecesse com um desenho e o das 23h com outro, a operadora teria de
// aprender a ler duas tabelas para responder à mesma pergunta — e a primeira
// vez que uma delas mudasse sem a outra, ficavam a dizer coisas diferentes
// sobre o mesmo dinheiro.
//
// **Este componente não soma nada.** Todos os valores chegam já somados do
// servidor (regra da casa: a aritmética de dinheiro é do servidor, o ecrã
// recebe-a feita). Não há aqui um `reduce` sobre euros, nem um total
// recalculado "para conferir" — um segundo cálculo no browser é uma segunda
// verdade, e a que apareceria por baixo da tabela seria a errada.

export const euros = (valor) =>
  `€ ${(Number(valor) || 0).toLocaleString('pt-PT', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

export function LinhaValor({ label, valor, destaque }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className={destaque ? 'font-heading font-bold text-lg tabular-nums' : 'font-medium tabular-nums'}>
        {valor}
      </span>
    </div>
  );
}

// Um valor de dinheiro que pode não vir: mostra-se como "—" e nunca como
// "€ 0,00". Um campo ausente pintado de zero é a pior das duas leituras —
// "não há imposto declarado" e "o servidor não respondeu a isso" ficam com o
// mesmo aspecto, e ninguém dá por nada.
const eurosOuTraco = (valor) =>
  valor === null || valor === undefined ? '—' : euros(valor);

function Seccao({ titulo, nota, children }) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {titulo}
        {nota && <span className="ml-2 font-normal normal-case tracking-normal">{nota}</span>}
      </h4>
      {children}
    </section>
  );
}

function Vazio({ children }) {
  return <p className="text-sm text-muted-foreground py-1.5">{children}</p>;
}

// A tabela larga (5 colunas do mapa de imposto) rola dentro de si própria em
// vez de esticar o diálogo — num PC de balcão de 1024px o diálogo tem menos
// de 500px de largura.
function Tabela({ cabecalho, children }) {
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-muted-foreground text-xs">
            {cabecalho.map(([texto, alinhar], i) => (
              <th key={i} className={`font-normal pb-1 ${alinhar === 'r' ? 'text-right pl-3' : 'text-left'}`}>
                {texto}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  );
}

const Cel = ({ children, r, forte }) => (
  <td className={`py-1.5 ${r ? 'text-right pl-3' : ''} ${forte ? 'font-medium' : ''}`}>{children}</td>
);

export default function PosResumoDoTurno({ resumo }) {
  const pagamentos = resumo?.pagamentos || [];
  const mapa = resumo?.mapa_imposto || [];

  return (
    <div className="space-y-5">
      <Seccao titulo="Movimentos do turno">
        <div className="divide-y">
          <LinhaValor label="Abertura (fundo de maneio)" valor={euros(resumo?.fundo)} />
          <LinhaValor label="Vendas em dinheiro" valor={`+ ${euros(resumo?.vendas_dinheiro)}`} />
          <LinhaValor label="Entradas" valor={`+ ${euros(resumo?.entradas)}`} />
          {/* O sinal está escrito, e não subentendido: é a única forma de a
              coluna se ler de cima a baixo e dar o total que está no fim. */}
          <LinhaValor label="Saídas" valor={`− ${euros(resumo?.saidas)}`} />
          <LinhaValor label="Deve estar na gaveta" valor={euros(resumo?.esperado)} destaque />
        </div>
      </Seccao>

      <Seccao titulo="Por tipo de pagamento">
        {pagamentos.length === 0 ? (
          <Vazio>Ainda não foi cobrada nenhuma conta neste turno.</Vazio>
        ) : (
          <Tabela cabecalho={[['Tipo'], ['N.º', 'r'], ['Total', 'r']]}>
            {pagamentos.map((linha) => (
              <tr key={linha.tipo_pagamento_id || linha.nome}>
                <Cel>{linha.nome || '—'}</Cel>
                <Cel r>{linha.quantos}</Cel>
                <Cel r forte>{euros(linha.total)}</Cel>
              </tr>
            ))}
            {/* A coluna do N.º fica VAZIA nesta linha, de propósito: ela
                conta pagamentos (uma conta paga metade em dinheiro e metade
                em multibanco conta uma vez em cada linha) e o total é o de
                documentos — dois números que não se somam um ao outro. Pôr
                lá o de documentos fazia a coluna parecer uma soma errada. */}
            <tr className="border-t-2">
              <Cel forte>Total cobrado</Cel>
              <Cel r />
              <Cel r forte>{euros(resumo?.total_faturado)}</Cel>
            </tr>
          </Tabela>
        )}
      </Seccao>

      <Seccao
        titulo="Mapa de imposto"
        nota={resumo?.quantos_documentos
          ? `${resumo.quantos_documentos} ${resumo.quantos_documentos === 1 ? 'documento' : 'documentos'}`
          : null}
      >
        {mapa.length === 0 ? (
          <Vazio>Sem documentos emitidos neste turno.</Vazio>
        ) : (
          <Tabela cabecalho={[['Taxa'], ['Doc.', 'r'], ['Base', 'r'], ['IVA', 'r'], ['Total', 'r']]}>
            {mapa.map((linha) => (
              <tr key={linha.tax_id || 'sem-taxa'}>
                {/* Uma taxa que o servidor não reconheceu vem a `null` e
                    mostra-se como tal — nunca se inventa aqui uma
                    percentagem para a linha ficar bonita. O total continua a
                    aparecer, que é onde alguém dá por ela. */}
                <Cel>{linha.taxa === null || linha.taxa === undefined ? `${linha.tax_id || '?'} (?)` : `${linha.taxa} %`}</Cel>
                <Cel r>{linha.documentos}</Cel>
                <Cel r>{eurosOuTraco(linha.base)}</Cel>
                <Cel r>{eurosOuTraco(linha.iva)}</Cel>
                <Cel r forte>{euros(linha.total)}</Cel>
              </tr>
            ))}
            {/* A linha que torna visível a única coisa que interessa num
                mapa de imposto: base + IVA = total dos documentos do turno.
                Os três números vêm somados do servidor — somar as colunas
                aqui seria pôr por baixo da tabela um total que pode não ser
                o dela. */}
            {/* Também aqui a coluna do Doc. fica vazia: um documento com
                as duas taxas conta nas duas linhas, e 7 + 6 não dá os 8
                documentos do turno — esse número está no título da secção,
                onde não parece a soma de uma coluna. */}
            <tr className="border-t-2">
              <Cel forte>Total</Cel>
              <Cel r />
              <Cel r forte>{eurosOuTraco(resumo?.base_tributavel)}</Cel>
              <Cel r forte>{eurosOuTraco(resumo?.iva_total)}</Cel>
              <Cel r forte>{euros(resumo?.total_faturado)}</Cel>
            </tr>
          </Tabela>
        )}
      </Seccao>
    </div>
  );
}
