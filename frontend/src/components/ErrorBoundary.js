import React from 'react';

// **A última defesa contra a página branca.** Um erro a desenhar (um toast com
// uma lista em vez de texto, por exemplo) desmontava a app inteira: sem nada à
// volta, o React tira tudo do ecrã. Aqui fica uma frase e um botão. Recarrega-se
// a página em vez de tentar de novo: não se sabe que estado ficou estragado. Sem
// dependências de components/ui de propósito — o que rebentou pode ser um deles.
// Ver ErrorBoundary.test.js.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { erro: null };
  }

  static getDerivedStateFromError(erro) {
    return { erro };
  }

  componentDidCatch(erro, info) {
    console.error('Erro inesperado no portal:', erro, info?.componentStack);
  }

  render() {
    if (!this.state.erro) return this.props.children;
    return (
      <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-2 bg-background px-6 text-center">
        <p className="text-base font-semibold">Algo correu mal.</p>
        <p className="text-sm text-muted-foreground">Recarregue a página para continuar.</p>
        <button
          type="button"
          className="mt-3 h-11 px-6 rounded-md bg-primary text-primary-foreground text-sm font-medium shadow hover:bg-primary/90"
          onClick={() => window.location.reload()}
        >
          Recarregar
        </button>
      </div>
    );
  }
}
