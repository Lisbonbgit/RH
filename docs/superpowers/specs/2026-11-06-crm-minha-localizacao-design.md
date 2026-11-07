# CRM — "A minha localização" no mapa

Data: 2026-11-06. Aprovado pelo dono do projeto (opção A: liga-se com um toque).

## O que é

Quem está no terreno quer ver onde está em relação às lojas. Os dois mapas do CRM (Mapa e planeador da Rota) ganham
um botão "A minha localização": ao tocar, aparece um ponto azul na posição da pessoa, que acompanha o movimento.

## Comportamento

- **Liga com um toque**, de cada vez que se abre o mapa. Nunca sozinho, e a escolha não fica lembrada.
- O primeiro toque pede a autorização do browser, liga o ponto e centra o mapa nele uma vez.
- O mapa não persegue a pessoa: pode olhar para outras zonas. Tocar de novo no botão volta a centrar.
- Um círculo claro à volta do ponto mostra a precisão do GPS.
- Sair do ecrã desliga o GPS e tira o ponto.
- O ponto não responde a toques: as lojas por baixo continuam a poder tocar-se.
- O botão aparece a quem abre o mapa (perfis `admin` e `utilizador`). O perfil `motorista` só entra no terreno na F4,
  na "Rota do dia", que poderá reaproveitar o mesmo botão. A app nativa continua sem CRM.

## Privacidade

**A posição nunca sai do telemóvel para o portal.** Sem pedidos ao servidor, sem gravar no browser, sem registos.
Ninguém no escritório a vê; mostrá-la ao escritório seria outro projeto, com regras próprias de proteção de dados.

Esta funcionalidade muda uma regra do desenho original ("nunca há seguimento contínuo"). O motivo dessa regra era não
registar os movimentos das pessoas, e isso mantém-se: lê-se o GPS de forma contínua só para desenhar o ponto, a pedido
da própria pessoa. Regra nova: **`watchPosition` só para "A minha localização", e o resultado só vai para o mapa.**
"Estou nesta loja" não muda: uma leitura, ao tocar. A página de Privacidade e o dossiê (§5.4) passam a dizer isto.

## Limites conhecidos

- Só com o mapa aberto e o ecrã ligado. Com o telemóvel bloqueado o browser para o GPS; ao voltar, o seguimento
  recomeça sozinho.
- Gasta mais bateria enquanto está ligado.
- Não é navegação: a condução continua a ser no Google Maps ou no Waze.

## Erros

- Autorização recusada: desliga e diz como autorizar.
- Sem posição à primeira (sem sinal, tempo esgotado, browser sem GPS): desliga e pede para tentar de novo.
- Falha depois de já haver ponto: o ponto fica onde estava e a leitura seguinte atualiza-o.

## Fora do âmbito

Ver a posição de outras pessoas, histórico de percursos, seguir a pessoa com o mapa, manter o ecrã ligado, lembrar a
escolha entre visitas.
