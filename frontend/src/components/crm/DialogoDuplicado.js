// O diálogo do 409 duplicado (desenho original §6.2; plano T2.27): "Já existe
// X aqui — é a mesma?" com "Sim, abrir X", "Não, é outra loja" e "Cancelar".
// Na nova loja (T2.27) e ao corrigir a localização na ficha (T2.28). Porta do
// `abrirDialogoDuplicado` de public/assets/js/componentes/dialogo.js do CRM
// autónomo, num `AlertDialog` do shadcn: modal, por cima do mapa, com o resto
// da página inerte; um toque fora não o fecha.
//
// Só desenha o `duplicado` da vista do ecrã (`{mensagem, botoes}` de
// `lib/crm/dialogo.js`; `null` = fechado) e devolve a escolha em
// `aoResponder('abrir' | 'outra' | null, loja)`. O Escape conta como "Cancelar"
// (null), e só a primeira escolha conta (`criarEscolhaUnica`). O foco vai para
// a primeira escolha ao abrir, como no autónomo, e para `refFocoAoFechar` (o
// botão Guardar) ao fechar. O nome da loja entra como texto (o React
// escapa-o).
import React, { useLayoutEffect, useMemo, useRef } from 'react';
import { Button } from '../ui/button';
import { AlertDialog, AlertDialogContent, AlertDialogTitle } from '../ui/alert-dialog';
import { criarEscolhaUnica } from '../../lib/crm/dialogo';

const VARIANTES = Object.freeze({ principal: 'default', normal: 'outline', discreto: 'ghost' });

export default function DialogoDuplicado({ duplicado, aoResponder, refFocoAoFechar }) {
  const aberto = duplicado != null;
  const primeiro = useRef(null);

  // A função mais recente do ecrã; uma escolha única por pergunta.
  const responder = useRef(aoResponder);
  useLayoutEffect(() => {
    responder.current = aoResponder;
  });
  // Uma pergunta nova (outra loja) pede uma escolha nova; a vista nova da mesma pergunta (ex.: a rede mudou
  // com o diálogo aberto) não.
  const loja = duplicado?.loja ?? null;
  const escolha = useMemo(() => criarEscolhaUnica((valor) => responder.current?.(valor, loja)), [loja]);

  return (
    <AlertDialog
      open={aberto}
      onOpenChange={(abrir) => {
        if (!abrir) escolha.escolher(null);
      }}
    >
      {aberto && (
        <AlertDialogContent
          aria-describedby={undefined}
          className="w-[calc(100%-2rem)] max-w-[26rem] rounded-2xl"
          onOpenAutoFocus={(evento) => {
            evento.preventDefault();
            primeiro.current?.focus();
          }}
          onCloseAutoFocus={(evento) => {
            evento.preventDefault();
            refFocoAoFechar?.current?.focus?.();
          }}
          data-testid="crm-dialogo-duplicado"
        >
          <AlertDialogTitle className="text-base font-normal leading-relaxed [overflow-wrap:anywhere]">
            {/* As partes são fixas e vêm sempre por esta ordem: a posição serve de chave. */}
            {duplicado.mensagem.map((parte, i) => (parte.forte
              ? <strong key={i} className="font-semibold">{parte.texto}</strong>
              : <React.Fragment key={i}>{parte.texto}</React.Fragment>))}
          </AlertDialogTitle>
          <div className="flex flex-col gap-2">
            {duplicado.botoes.map((botao, i) => (
              <Button
                key={botao.valor ?? 'cancelar'}
                ref={i === 0 ? primeiro : undefined}
                type="button"
                variant={VARIANTES[botao.variante] ?? 'outline'}
                className="h-auto min-h-11 w-full whitespace-normal py-2 [overflow-wrap:anywhere]"
                onClick={() => escolha.escolher(botao.valor)}
              >
                {botao.texto}
              </Button>
            ))}
          </div>
        </AlertDialogContent>
      )}
    </AlertDialog>
  );
}
