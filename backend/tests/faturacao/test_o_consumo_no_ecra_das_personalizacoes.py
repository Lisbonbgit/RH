"""**A gramagem no ecrã das Personalizações** — onde o dono a escreve.

O backend sozinho não chega, e não é um detalhe de acabamento: o PUT do grupo
substitui o array `opcoes` por completo e o ecrã monta cada opção campo a
campo. Um backend que soubesse do consumo com um ecrã que não soubesse apagava
as gramagens de todas as opções à primeira gravação. O servidor já se defende
disso (`_preserva_o_consumo_que_o_pedido_nao_falou`), mas a defesa é para os
OUTROS chamadores — um curl, um script, um ecrã futuro. Este ecrã tem de saber
do assunto, e tem de conseguir apagar o que o dono apagou.

Três coisas que só se vêem montando o ecrã:

1. **a linha do consumo aparece em TODOS os grupos**, ao contrário da ligação
   ao Vendus, que só aparece no do tamanho. A granola gasta granola e o
   Regular gasta polpa — as duas coisas têm de se poder escrever;
2. **o Guardar manda os três campos SEMPRE**, também a `null`. Omiti-los
   deixava a gramagem anterior gravada e apagá-la era impossível pelo ecrã;
3. **o catálogo do Estoque é outro serviço, noutro servidor.** Não se lê ao
   abrir e, quando está em baixo, diz-se — uma lista vazia com ar de sucesso
   dizia «não há artigos» e o topping ficava por ligar por engano.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES

_TOPPINGS = {
    "id": "g-top", "nome": "Toppings", "tipo": "opcoes", "ativo": True,
    "min_select": 0, "max_select": 0, "sai_na_fatura": True,
    "e_variante": False,
    "opcoes": [
        {"id": "o-gra", "nome": "Granola", "preco": 0.80, "ativa": True,
         "consumo": 30, "consumo_unidade": "g", "estoque_produto_id": "est-granola"},
        {"id": "o-nut", "nome": "Nutella", "preco": 1.0, "ativa": True},
    ],
}
_TAMANHO = {
    "id": "g-tam", "nome": "Tamanho", "tipo": "opcoes", "ativo": True,
    "min_select": 1, "max_select": 1, "sai_na_fatura": True,
    "e_variante": True,
    "opcoes": [{"id": "o-reg", "nome": "Regular", "preco": 8.99, "ativa": True}],
}
_PRODUTOS_DO_ESTOQUE = [
    {"id": "est-granola", "nome": "Granola aveia", "unidade_medida": "kg",
     "fornecedor": "Makro"},
    {"id": "est-nutella", "nome": "Creme de avelã", "unidade_medida": "kg",
     "fornecedor": "Makro"},
]


def _monta(grupo, leituras, tmp_path, nome, falhar_estoque=False):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const Ecra = carregar(path2.join(ADMIN, 'FatPersonalizacoes.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/grupos-personalizacao'] = () => ({ data: %s });"
        % json.dumps([grupo], ensure_ascii=False),
        "RESPOSTAS_GESTAO['PUT /faturacao/grupos-personalizacao/%s'] = () => ({ data: {} });"
        % grupo["id"],
        # O catálogo do Vendus nunca é o assunto aqui, mas o ecrã pode
        # perguntar por ele — fica fabricado para não rebentar por 404.
        "RESPOSTAS_GESTAO['/faturacao/vendus/artigos'] = () => ({ data: [] });",
        ("RESPOSTAS_GESTAO['/estoque/produtos'] = () => { const e = "
         "new Error('502'); e.response = { status: 502, data: { detail: "
         "'O Estoque não respondeu.' } }; throw e; };") if falhar_estoque else
        ("RESPOSTAS_GESTAO['/estoque/produtos'] = () => ({ data: %s });"
         % json.dumps(_PRODUTOS_DO_ESTOQUE, ensure_ascii=False)),
        "const alvo = document.getElementById('raiz');",
        "await act(async () => { createRoot(alvo).render(React.createElement(Ecra)); });",
        "await act(async () => {});",
        "const porTestid = (t) => alvo.querySelector(`[data-testid=\"${t}\"]`);",
        "const clicar = async (t) => { const el = porTestid(t);",
        "  if (!el) throw new Error('sem ' + t);",
        "  await act(async () => { el.dispatchEvent(new window.MouseEvent('click',",
        "    { bubbles: true })); }); await act(async () => {});",
        "  await act(async () => {}); };",
        # Escrever num campo controlado do React: o valor põe-se pelo setter
        # nativo, senão o onChange do React não vê a mudança.
        "const escrever = async (t, valor) => { const el = porTestid(t);",
        "  if (!el) throw new Error('sem ' + t);",
        "  const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype",
        "    : window.HTMLInputElement.prototype;",
        "  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;",
        "  await act(async () => { setter.call(el, valor);",
        "    el.dispatchEvent(new window.Event('change', { bubbles: true })); });",
        "  await act(async () => {}); };",
        "const submeter = async () => {",
        "  await act(async () => { porTestid('save-grupo-btn').form.dispatchEvent(",
        "    new window.Event('submit', { bubbles: true, cancelable: true })); });",
        "  await act(async () => {}); await act(async () => {}); };",
        "await clicar('edit-grupo-%s');" % grupo["id"],
        "const gravou = () => pedidos.filter((p) => p.metodo === 'put'",
        "  && String(p.url).includes('/grupos-personalizacao/')).map((p) => p.corpo);",
        "const foiAoEstoque = () => pedidos.filter(",
        "  (p) => String(p.url).includes('/estoque/produtos')).length;",
        "const saida = {};",
    ] + leituras + [
        "saida.gravado = gravou();",
        "saida.idasAoEstoque = foiAoEstoque();",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => { "
        "process.stderr.write(String(e && e.stack || e)); process.exit(1); });" % guiao,
        tmp_path, nome)


def test_a_linha_do_consumo_aparece_num_grupo_que_NAO_e_o_tamanho(tmp_path):
    """A diferença que dá sentido a esta obra. A ligação ao Vendus só aparece
    no grupo do tamanho, de propósito. Esta tem de aparecer na Nutella também
    — senão ficava por escrever exactamente o que o dono pediu."""
    saida = _monta(_TOPPINGS, [
        "saida.granola = !!porTestid('opcao-consumo-0');",
        "saida.nutella = !!porTestid('opcao-consumo-1');",
        "saida.ligacaoAoVendus = !!porTestid('opcao-vendus-0');",
    ], tmp_path, "todos-os-grupos.js")
    assert saida["granola"], "a Granola não tem onde escrever o que gasta"
    assert saida["nutella"], "a Nutella não tem onde escrever o que gasta"
    assert saida["ligacaoAoVendus"] is False, (
        "a ligação ao Vendus não pode aparecer fora do grupo do tamanho")


def test_a_linha_do_consumo_aparece_TAMBEM_no_grupo_do_tamanho(tmp_path):
    """O copo base entra por aqui e sem código novo: o tamanho já é uma
    personalização, portanto «Regular gasta 200 g de polpa» escreve-se no
    mesmo campo que a granola."""
    saida = _monta(_TAMANHO, [
        "saida.temConsumo = !!porTestid('opcao-consumo-0');",
        "saida.temVendus = !!porTestid('opcao-vendus-0');",
    ], tmp_path, "tamanho-tambem.js")
    assert saida["temConsumo"], "o tamanho não tem onde escrever a polpa"
    assert saida["temVendus"], "e não pode ter perdido a ligação ao Vendus"


def test_o_consumo_ja_gravado_aparece_no_ecra(tmp_path):
    saida = _monta(_TOPPINGS, [
        "saida.quantidade = porTestid('opcao-consumo-input-0').value;",
        "saida.unidade = porTestid('opcao-consumo-unidade-0').value;",
        "saida.temArtigo = !!porTestid('trocar-artigo-estoque-0');",
        "saida.semArtigo = !!porTestid('ligar-artigo-estoque-1');",
    ], tmp_path, "ja-gravado.js")
    assert saida["quantidade"] == "30"
    assert saida["unidade"] == "g"
    assert saida["temArtigo"], "a Granola está ligada e o ecrã não o mostra"
    assert saida["semArtigo"], "a Nutella não tem por onde ligar"


def test_um_grupo_ao_abrir_NAO_vai_ao_Estoque(tmp_path):
    """O Estoque é outro serviço, noutro servidor, com 12-15 s de espera até
    desistir. Abrir um grupo para corrigir um preço não pode ficar pendurado
    nele. Lê-se quando se escolhe um artigo, e só aí."""
    saida = _monta(_TOPPINGS, [], tmp_path, "sem-ida.js")
    assert saida["idasAoEstoque"] == 0


def test_escolher_um_artigo_mostra_o_NOME_e_nao_o_id(tmp_path):
    saida = _monta(_TOPPINGS, [
        "await clicar('ligar-artigo-estoque-1');",
        "await clicar('artigo-do-estoque-est-nutella');",
        "saida.texto = (porTestid('opcao-consumo-1') || {}).textContent;",
    ], tmp_path, "escolher-estoque.js")
    assert "Creme de avelã" in saida["texto"], saida["texto"]


def test_o_GUARDAR_manda_a_quantidade_a_unidade_e_o_artigo(tmp_path):
    saida = _monta(_TOPPINGS, [
        "await escrever('opcao-consumo-input-1', '20');",
        "await escrever('opcao-consumo-unidade-1', 'ml');",
        "await clicar('ligar-artigo-estoque-1');",
        "await clicar('artigo-do-estoque-est-nutella');",
        "await submeter();",
    ], tmp_path, "guardar-consumo.js")
    assert saida["gravado"], "não gravou nada"
    opcoes = saida["gravado"][-1]["opcoes"]
    assert opcoes[1]["consumo"] == 20
    assert opcoes[1]["consumo_unidade"] == "ml"
    assert opcoes[1]["estoque_produto_id"] == "est-nutella"
    # E a que já lá estava não se perde por não lhe termos tocado.
    assert opcoes[0]["consumo"] == 30
    assert opcoes[0]["estoque_produto_id"] == "est-granola"


def test_APAGAR_a_quantidade_manda_null_e_nao_omite(tmp_path):
    """Omitir o campo deixava a gramagem anterior gravada — e o servidor,
    que preserva de propósito o que o pedido não menciona, mantinha-a. O dono
    apagava, o ecrã mostrava vazio, e o stock continuava a descontar."""
    saida = _monta(_TOPPINGS, [
        "await escrever('opcao-consumo-input-0', '');",
        "await escrever('opcao-consumo-unidade-0', '');",
        "await clicar('desligar-artigo-estoque-0');",
        "await submeter();",
    ], tmp_path, "apagar-consumo.js")
    assert saida["gravado"], "não gravou nada"
    opcao = saida["gravado"][-1]["opcoes"][0]
    assert "consumo" in opcao, "o campo tem de VIAJAR, mesmo a null"
    assert opcao["consumo"] is None
    assert opcao["consumo_unidade"] is None
    assert opcao["estoque_produto_id"] is None


def test_um_numero_SEM_unidade_nao_chega_a_gravar(tmp_path):
    """Espelho da regra do servidor, no sítio onde o dono a lê: «30» sozinho
    não diz se são gramas ou mililitros. Sem esta guarda no ecrã, o pedido ia
    ao servidor só para voltar com um 422 sem dizer qual das opções falhou."""
    saida = _monta(_TOPPINGS, [
        "await escrever('opcao-consumo-input-1', '20');",
        "await submeter();",
        "saida.erro = (porTestid('opcao-consumo-1') || {}).textContent;",
    ], tmp_path, "sem-unidade.js")
    assert saida["gravado"] == [], "gravou um número que não quer dizer nada"
    assert "unidade" in saida["erro"].lower(), saida["erro"]


def test_o_catalogo_do_Estoque_em_baixo_DIZ_o_que_se_passa(tmp_path):
    """Uma lista vazia com ar de sucesso dizia «não há artigos no Estoque» e o
    topping ficava por ligar por engano. A frase é a do servidor: é ele que
    sabe se o Estoque está em baixo ou se a conta não está configurada."""
    saida = _monta(_TOPPINGS, [
        "await clicar('ligar-artigo-estoque-1');",
        "saida.temErro = !!porTestid('erro-produtos-estoque');",
        "saida.texto = (porTestid('erro-produtos-estoque') || {}).textContent;",
    ], tmp_path, "estoque-em-baixo.js", falhar_estoque=True)
    assert saida["temErro"], "o Estoque em baixo passou por lista vazia"
    assert "Estoque" in saida["texto"], saida["texto"]


def test_o_Estoque_em_baixo_NAO_estraga_o_formulario(tmp_path):
    """O que se está a escrever não se perde por um serviço de fora ter caído:
    volta-se da escolha e a gramagem continua lá, para se poder guardar."""
    saida = _monta(_TOPPINGS, [
        "await escrever('opcao-consumo-input-1', '20');",
        "await escrever('opcao-consumo-unidade-1', 'ml');",
        "await clicar('ligar-artigo-estoque-1');",
        "await clicar('voltar-do-estoque-btn');",
        "saida.quantidade = porTestid('opcao-consumo-input-1').value;",
        "saida.unidade = porTestid('opcao-consumo-unidade-1').value;",
        "await submeter();",
    ], tmp_path, "estoque-em-baixo-formulario.js", falhar_estoque=True)
    assert saida["quantidade"] == "20"
    assert saida["unidade"] == "ml"
    assert saida["gravado"], "com o Estoque em baixo deixou de se poder guardar"
    assert saida["gravado"][-1]["opcoes"][1]["consumo"] == 20
