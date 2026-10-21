import React from 'react';

// Política de privacidade pública (exigida pela App Store e Google Play).
// Acessível em https://rh.lisbonb.com/privacidade
export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-5 py-10">
        <h1 className="text-2xl font-heading font-bold mb-1">Política de Privacidade — Lisbonb RH</h1>
        <p className="text-sm text-muted-foreground mb-8">Última atualização: 10 de outubro de 2026</p>

        <div className="space-y-6 text-sm leading-relaxed">
          <section>
            <p>
              A aplicação <strong>Lisbonb RH</strong> é uma ferramenta de gestão de recursos humanos do
              <strong> Grupo Lisbonb</strong>, destinada aos seus colaboradores para registo de ponto
              (entradas e saídas), consulta de horários, pedidos de férias/ausências e documentos.
              Esta política explica que dados são tratados e para quê.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">1. Responsável pelo tratamento</h2>
            <p>
              Grupo Lisbonb. Para qualquer questão sobre os seus dados, contacte:{' '}
              <a href="mailto:geral@lisbonb.com" className="text-primary underline">geral@lisbonb.com</a>.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">2. Que dados tratamos</h2>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Identificação e conta:</strong> nome, email e função, usados para autenticação.</li>
              <li><strong>Registos de ponto:</strong> data e hora das entradas e saídas.</li>
              <li>
                <strong>Localização:</strong> a posição (GPS) é recolhida <strong>apenas no momento</strong> em
                que toca em "Entrada" ou "Saída", para confirmar que o registo é feito junto ao local de
                trabalho. <strong>Não</strong> há recolha de localização em segundo plano nem seguimento contínuo.
              </li>
              <li><strong>Dados de RH:</strong> pedidos de férias/ausências e documentos que partilhe na app.</li>
              <li><strong>Dados técnicos mínimos</strong> necessários ao funcionamento (ex.: tipo de dispositivo).</li>
            </ul>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">3. Finalidades e base legal</h2>
            <p>
              Os dados são tratados para a <strong>gestão da relação laboral</strong> (registo de assiduidade,
              gestão de ausências e documentação), no âmbito do contrato de trabalho e do cumprimento de
              obrigações legais do empregador. No registo de ponto, a localização serve exclusivamente para validar o registo.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">4. Partilha de dados</h2>
            <p>
              Os dados <strong>não são vendidos</strong> nem partilhados para fins publicitários. São acedidos
              apenas pelo Grupo Lisbonb e pelos prestadores estritamente necessários ao funcionamento do serviço
              (alojamento e base de dados), sujeitos a confidencialidade.
              No CRM (secção 8), o mapa é o Google Maps (Google Ireland Limited): é o próprio browser que lhe pede
              o mapa, a pesquisa de moradas e a posição dos lugares, dando-lhe a conhecer, como em qualquer site, o
              endereço IP. A morada sugerida de um ponto do GPS vem da Geoapify (dados OpenStreetMap), a quem o
              servidor só envia pontos do mapa, sem dados pessoais.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">5. Conservação</h2>
            <p>
              Os dados são conservados enquanto durar a relação laboral e pelos prazos legais aplicáveis,
              sendo depois eliminados ou anonimizados.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">6. Os seus direitos</h2>
            <p>
              Pode solicitar o acesso, correção, eliminação ou limitação dos seus dados, bem como opor-se ao
              tratamento, contactando{' '}
              <a href="mailto:geral@lisbonb.com" className="text-primary underline">geral@lisbonb.com</a>.
              Tem ainda o direito de apresentar reclamação à autoridade de controlo (em Portugal, a CNPD).
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">7. Permissões da aplicação</h2>
            <p>
              A app pede permissão de <strong>localização</strong> apenas para o registo de ponto. Pode recusar
              ou revogar esta permissão nas definições do telemóvel; nesse caso, poderá não conseguir registar o
              ponto em locais que exijam validação de proximidade.
            </p>
          </section>

          {/* CRM (T2.31): redação a rever pelo dono antes de publicar (texto legal). */}
          <section>
            <h2 className="text-base font-semibold mb-2">8. CRM Purple House (equipa comercial)</h2>
            <p className="mb-2">
              Os membros da equipa comercial usam o CRM Purple House, no browser (não na app instalada), para
              registar num mapa as lojas que são clientes ou potenciais clientes.
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                <strong>Localização:</strong> a posição (GPS) só é pedida quando um membro toca em "Estou nesta
                loja", e é lida uma única vez, nesse momento. Guarda-se só o ponto da loja, <strong>nunca</strong> a
                posição da pessoa nem percursos, e <strong>não</strong> há seguimento contínuo. Na primeira vez, o
                browser pede autorização; se a recusar, pode marcar a loja no mapa ou pela morada.
              </li>
              <li>
                <strong>Dados guardados:</strong> os das lojas (nome, morada, telefone, pessoa de contacto, horário,
                fase e notas), o perfil de cada membro no CRM e quem registou cada loja e cada mudança de fase.
              </li>
              <li>
                <strong>Mapa:</strong> o mapa é o Google Maps, da Google Ireland Limited. Ao usar o mapa do CRM, o
                membro fica sujeito aos{' '}
                <a href="https://maps.google.com/help/terms_maps/" className="text-primary underline">Termos adicionais do Google Maps/Google Earth</a>{' '}
                e à{' '}
                <a href="https://policies.google.com/privacy" className="text-primary underline">Política de Privacidade da Google</a>.
              </li>
              <li>
                <strong>Lojas e moradas:</strong> o nome e o telefone de uma loja são sempre escritos pelo membro e{' '}
                <strong>nunca</strong> copiados da Google; quando a loja parte de um lugar da Google, guarda-se só o
                identificador do lugar (place ID) e o pino confirmado pelo membro. A morada preenchida depois de uma
                pesquisa vem da Google; a de um ponto do GPS vem da Geoapify (dados OpenStreetMap), com a indicação
                Powered by Geoapify.
              </li>
            </ul>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">9. Alterações</h2>
            <p>
              Esta política pode ser atualizada. A data no topo indica a versão em vigor.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
