import React from 'react';

// Política de privacidade pública (exigida pela App Store e Google Play).
// Acessível em https://rh.lisbonb.com/privacidade
export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-5 py-10">
        <h1 className="text-2xl font-heading font-bold mb-1">Política de Privacidade — Lisbonb RH</h1>
        <p className="text-sm text-muted-foreground mb-8">Última atualização: 29 de junho de 2026</p>

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
              obrigações legais do empregador. A localização serve exclusivamente para validar o registo de ponto.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold mb-2">4. Partilha de dados</h2>
            <p>
              Os dados <strong>não são vendidos</strong> nem partilhados para fins publicitários. São acedidos
              apenas pelo Grupo Lisbonb e pelos prestadores estritamente necessários ao funcionamento do serviço
              (alojamento e base de dados), sujeitos a confidencialidade.
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

          <section>
            <h2 className="text-base font-semibold mb-2">8. Alterações</h2>
            <p>
              Esta política pode ser atualizada. A data no topo indica a versão em vigor.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
