import React from 'react';
import {
  eurosPos, eurosComSinal, haPagamentosPorRegistar, temTaxaDesconhecida,
  tirouDaGavetaAMais, haDevolucoesAcimaDoRecebido,
} from '@/lib/pos';

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

// A formatação vem de `@/lib/pos` (`eurosPos`) e NÃO é escrita aqui — eram
// oito cópias da mesma linha e as oito pintavam `undefined` de "€ 0,00". Fica
// reexportada porque o `PosFecharCaixa` a importa deste ficheiro há muito.
export const euros = eurosPos;
// E o irmão que põe o sinal do próprio valor — «+ € -15,40» era o que a linha
// das vendas em dinheiro dizia com o `+` escrito à mão.
export const comSinal = eurosComSinal;

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
  // Uma taxa que o servidor não reconheceu tem `base` e `iva` a `null` e o
  // `total` preenchido — e é por isso que a última linha da tabela deixa de
  // fechar: base + IVA não dá o total. Ao balcão lia-se como um total partido
  // ("9,03 + 1,17 contra 11,35") sem uma palavra que o explicasse.
  const comTaxaDesconhecida = temTaxaDesconhecida(mapa);
  const porRegistar = haPagamentosPorRegistar(resumo);
  // **O que saiu da gaveta a mais, e o porquê** — DUAS perguntas e dois
  // predicados, e não um a mandar no outro. As decisões vivem em `lib/pos.js`,
  // como todas as deste ecrã, e os números vêm somados do servidor.
  const tirouAMais = tirouDaGavetaAMais(resumo);
  const devolucoesAcima = haDevolucoesAcimaDoRecebido(resumo);

  // **Um resumo ausente não se desenha como um turno de zeros.** Medido: com
  // `resumo` a `undefined` (o servidor não respondeu, o campo mudou de nome), o
  // bloco pintava um turno inteiro e perfeitamente legível de € 0,00 —
  // "Vendas em dinheiro + € 0,00", "Deve estar na gaveta € 0,00" — e a
  // funcionária fecha a gaveta com 200 € lá dentro a acreditar que está certo.
  // O `euros` defende-se hoje (sai "€ ?"), mas uma tabela inteira de "€ ?" não
  // é uma resposta: a resposta é dizer que não há números.
  if (!resumo) {
    return (
      <p className="text-sm text-muted-foreground py-2">
        Os números deste turno não vieram do servidor. Não são zero — não se
        sabem. Recarregue o ecrã; se continuar assim, NÃO feche a caixa por
        aqui e chame o gestor.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <Seccao titulo="Movimentos do turno">
        <div className="divide-y">
          <LinhaValor label="Abertura (fundo de maneio)" valor={euros(resumo?.fundo)} />
          {/* O sinal sai do VALOR: as vendas em dinheiro do turno são as
              faturas MENOS as devoluções, e podem ficar negativas. Com o `+`
              escrito à mão lia-se «+ € -15,40» — um mais colado a um número
              negativo, na única linha que mostra o vazamento quando mais nada
              o mostra. */}
          <LinhaValor label="Vendas em dinheiro" valor={comSinal(resumo?.vendas_dinheiro)} />
          <LinhaValor label="Entradas" valor={`+ ${euros(resumo?.entradas)}`} />
          {/* O sinal está escrito, e não subentendido: é a única forma de a
              coluna se ler de cima a baixo e dar o total que está no fim. */}
          <LinhaValor label="Saídas" valor={`− ${euros(resumo?.saidas)}`} />
          <LinhaValor label="Deve estar na gaveta" valor={euros(resumo?.esperado)} destaque />
        </div>
        {/* **O aviso que faltava, e é o que impede a gaveta de bater certo
            estando errada.** Um turno só pode tirar da gaveta o que lá pôs.
            Medido no servidor — fatura de 24,14 € paga 5,00 em dinheiro +
            19,14 em Multibanco, açaí de 20,40 € devolvido em DINHEIRO → as
            vendas em dinheiro caíam para −15,40 €, e a operadora contava a
            gaveta, batia certo, e ia para casa.

            **A frase NÃO diz «abaixo do fundo»**, e a versão anterior dizia:
            com uma sangria de 30,00 € para o cofre em cima disto, a gaveta
            fecha 45,40 € abaixo do fundo e não 15,40 — o número estava certo
            e a frase mentia sobre ele. O que este número é: quanto saiu da
            gaveta ALÉM do que as vendas do turno lá puseram. */}
        {tirouAMais && (
          <p
            className="text-xs text-amber-600 dark:text-amber-500 pt-1"
            data-testid="tirado-da-gaveta-a-mais"
          >
            Saíram {euros(resumo.tirado_da_gaveta_a_mais)} da gaveta a mais do
            que as vendas deste turno lá puseram. Isto não é uma diferença de
            contagem — conte a gaveta na mesma e mostre isto ao gestor.
          </p>
        )}
        {/* **E o porquê, no seu PRÓPRIO predicado.**
            `devolucoes_acima_do_recebido` é o leitor do `acima_do_recebido`
            que a nota de crédito grava. Esta frase esteve pendurada no aviso
            de cima e desaparecia com ele — com um reforço de troco na gaveta o
            servidor calculava 15,40 € e o ecrã não escrevia nada, e o campo
            voltava a ser só de escrita. São duas perguntas: um turno pode ter
            a gaveta certa e ainda assim ter devolvido por um meio que aquela
            fatura não recebeu. */}
        {devolucoesAcima && (
          <p
            className="text-xs text-amber-600 dark:text-amber-500 pt-1"
            data-testid="devolucoes-acima-do-recebido"
          >
            Saíram {euros(resumo.devolucoes_acima_do_recebido)} em devoluções
            por um meio de pagamento que essas faturas não receberam. Mostre
            isto ao gestor.
          </p>
        )}
      </Seccao>

      <Seccao titulo="Por tipo de pagamento">
        {pagamentos.length === 0 && !porRegistar ? (
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
            {/* **O que foi facturado e não tem pagamento nenhum por baixo.**
                Uma venda emitida sem `pagamentos` não entra em linha nenhuma
                da tabela, e a coluna somava 10,20 € debaixo de um "Total
                cobrado 11,35 €" — 1,15 € desaparecidos sem uma palavra. O
                número vem SOMADO do servidor (`pagamentos_por_registar`): o
                ecrã nunca soma colunas de dinheiro. Só aparece quando existe,
                e quando aparece a coluna volta a dar o rodapé. */}
            {porRegistar && (
              <tr className="text-amber-600 dark:text-amber-500">
                <Cel>Sem tipo de pagamento registado</Cel>
                <Cel r />
                <Cel r forte>{euros(resumo.pagamentos_por_registar)}</Cel>
              </tr>
            )}
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
        {/* Sem esta frase, a linha do Total ficava com duas colunas que não
            somam a terceira e nada que o dissesse. Dito por extenso, deixa de
            ser um total partido e passa a ser uma conta por resolver com o
            gestor. */}
        {comTaxaDesconhecida && (
          <p className="text-xs text-amber-600 dark:text-amber-500 pt-1">
            Há uma linha com uma taxa de IVA que este sistema não reconhece: o
            total dela conta para o turno, mas a base e o IVA não se sabem —
            por isso a Base e o IVA do Total NÃO somam o Total. Mostre isto ao
            gestor.
          </p>
        )}
      </Seccao>
    </div>
  );
}
