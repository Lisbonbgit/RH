"""A forma dos erros do CRM (crm/erros.py) e a leitura do corpo JSON
(crm/pedidos.py::corpo_json).

Contrato do plano §4: um erro do CRM sai como
`{"detail": {"codigo", "mensagem", "campos"?, …extra}}`; as escritas leem o
corpo com `corpo_json` (400 `json_invalido` se não for um objeto JSON) e
validam no domínio, sem modelos Pydantic. Porta de src/Http/ErroApi.php e de
Pedido::json() do CRM autónomo.

As rotas destes testes são locais a cada teste (uma app FastAPI descartável):
o router do CRM só ganha rotas de escrita na T1.7.
"""
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBearer
from fastapi.testclient import TestClient

from crm import erros
from crm.erros import erro, nao_encontrado, validacao
from crm.pedidos import corpo_json

JSON = {"Content-Type": "application/json"}
JSON_INVALIDO = {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}


# --- erro(), validacao(), nao_encontrado() ---------------------------------


def test_erro_devolve_uma_httpexception_com_codigo_mensagem_e_extra():
    lojas = [{"id": "a1", "nome": "Café Central", "distancia_m": 30}]
    e = erro(409, "conflito", "Alterado por outra pessoa — recarregar", lojas=lojas)
    assert isinstance(e, HTTPException)
    assert e.status_code == 409
    assert e.detail == {
        "codigo": "conflito",
        "mensagem": "Alterado por outra pessoa — recarregar",
        "lojas": lojas,
    }


def test_erro_sem_extra_so_tem_codigo_e_mensagem():
    e = erro(403, "sem_permissao", "Sem permissão para esta ação.")
    assert e.status_code == 403
    assert e.detail == {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}


def test_validacao_da_422_com_a_mensagem_geral_e_os_campos():
    e = validacao({"nome": "Indique o nome."})
    assert e.status_code == 422
    assert e.detail == {
        "codigo": "validacao",
        "mensagem": "Verifique os campos assinalados.",
        "campos": {"nome": "Indique o nome."},
    }


def test_validacao_guarda_uma_copia_dos_campos():
    campos = {"nome": "Indique o nome."}
    e = validacao(campos)
    campos["telefone"] = "mudado depois"
    assert e.detail["campos"] == {"nome": "Indique o nome."}


def test_validacao_mantem_a_ordem_dos_campos():
    # O frontend mostra os erros pela ordem dos campos do formulário.
    e = validacao({"nome": "a", "fase": "b", "lat": "c"})
    assert list(e.detail["campos"]) == ["nome", "fase", "lat"]


@pytest.mark.parametrize(
    "mensagem",
    ["Loja não encontrada.", "Região não encontrada.", "Membro não encontrado."],
    ids=["loja", "regiao", "membro"],
)
def test_nao_encontrado_da_404_com_a_mensagem_da_entidade(mensagem):
    e = nao_encontrado(mensagem)
    assert e.status_code == 404
    assert e.detail == {"codigo": "nao_encontrado", "mensagem": mensagem}


def test_os_codigos_e_estados_sao_os_da_tabela_do_plano():
    # Tabela "Códigos de erro do CRM" do plano §4 (e do dossiê §6). Um código
    # novo acrescenta-se lá e aqui — o frontend (lib/crm/api.js) decide pelo
    # código, por isso um erro de escrita no código é um erro do contrato.
    assert erros.ESTADOS == {
        "json_invalido": 400,
        "sem_acesso_crm": 403,
        "sem_permissao": 403,
        "nao_encontrado": 404,
        "validacao": 422,
        "duplicado": 409,
        "conflito": 409,
        "regiao_repetida": 409,
        "regiao_com_lojas": 409,
        "loja_com_historico": 409,
        "ja_membro": 409,
        "admin_master": 409,
        "morada_indisponivel": 503,
    }


def test_erro_recusa_um_codigo_fora_da_tabela():
    with pytest.raises(ValueError, match="conflitto"):
        erro(409, "conflitto", "Alterado por outra pessoa — recarregar")


def test_erro_recusa_um_estado_que_nao_e_o_do_codigo():
    with pytest.raises(ValueError, match="conflito"):
        erro(400, "conflito", "Alterado por outra pessoa — recarregar")


def _cliente_que_levanta(excecao):
    app = FastAPI()

    @app.get("/teste")
    async def _rota():
        raise excecao

    return TestClient(app)


def test_o_erro_chega_ao_cliente_dentro_de_detail():
    lojas = [{"id": "a1", "nome": "Café Central", "distancia_m": 30}]
    r = _cliente_que_levanta(
        erro(409, "duplicado", "Já existe Café Central aqui — é a mesma?", lojas=lojas)
    ).get("/teste")
    assert r.status_code == 409
    assert r.json() == {
        "detail": {
            "codigo": "duplicado",
            "mensagem": "Já existe Café Central aqui — é a mesma?",
            "lojas": lojas,
        }
    }


def test_a_validacao_chega_ao_cliente_com_os_campos():
    r = _cliente_que_levanta(validacao({"perfil": "Escolha um perfil."})).get("/teste")
    assert r.status_code == 422
    assert r.json() == {
        "detail": {
            "codigo": "validacao",
            "mensagem": "Verifique os campos assinalados.",
            "campos": {"perfil": "Escolha um perfil."},
        }
    }


# --- corpo_json -------------------------------------------------------------


def _cliente_eco():
    app = FastAPI()

    @app.post("/eco")
    async def _eco(corpo: dict = Depends(corpo_json)):
        return {"recebido": corpo}

    return TestClient(app)


def test_um_objeto_vazio_passa():
    r = _cliente_eco().post("/eco", content=b"{}", headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"recebido": {}}


def test_um_objeto_chega_inteiro_a_rota():
    corpo = '{"nome": "Café Central", "lat": 38.7075, "dias_fechada": ["dom"], "x": null}'
    r = _cliente_eco().post("/eco", content=corpo.encode("utf-8"), headers=JSON)
    assert r.status_code == 200
    assert r.json() == {
        "recebido": {"nome": "Café Central", "lat": 38.7075, "dias_fechada": ["dom"], "x": None}
    }


@pytest.mark.parametrize(
    "corpo",
    [
        b"[1]",
        b"[]",
        b'"x"',
        b"null",
        b"1",
        b"true",
        b"isto nao e JSON",
        b'{"nome": "Loja"',
        b"{nome: 'Loja'}",
        b"[",
    ],
    ids=[
        "lista",
        "lista vazia",
        "texto",
        "null",
        "numero",
        "verdadeiro",
        "texto que nao e JSON",
        "objeto por fechar",
        "aspas simples e chaves sem aspas",
        "so um parentese",
    ],
)
def test_o_que_nao_e_um_objeto_json_da_400_json_invalido(corpo):
    r = _cliente_eco().post("/eco", content=corpo, headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": JSON_INVALIDO}


@pytest.mark.parametrize(
    "corpo",
    [b'{"lat": NaN}', b'{"lat": Infinity}', b'{"lat": -Infinity}'],
    ids=["NaN", "Infinity", "-Infinity"],
)
def test_as_constantes_que_o_json_do_python_aceita_mas_nao_sao_json_dao_400(corpo):
    # O json.loads aceita NaN e Infinity por omissão; o json_decode do PHP (e
    # o JSON.parse do browser) não. Sem isto, um NaN chegava ao domínio.
    r = _cliente_eco().post("/eco", content=corpo, headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": JSON_INVALIDO}


def test_bytes_que_nao_sao_utf8_dao_400():
    r = _cliente_eco().post("/eco", content=b'{"nome": "Caf\xe9"}', headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": JSON_INVALIDO}


def test_json_com_bom_no_inicio_da_400_como_no_php():
    r = _cliente_eco().post("/eco", content=b"\xef\xbb\xbf{}", headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": JSON_INVALIDO}


def test_um_objeto_fundo_demais_da_400_e_nao_500():
    # O descodificador do Python levanta RecursionError (não ValueError) a
    # partir de uns milhares de níveis; sem o apanhar, saía um 500.
    fundo = b'{"a": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    r = _cliente_eco().post("/eco", content=fundo, headers=JSON)
    assert r.status_code == 400
    assert r.json() == {"detail": JSON_INVALIDO}


@pytest.mark.parametrize("corpo", [b"", b"  \n\t "], ids=["vazio", "so espacos"])
def test_um_corpo_vazio_vale_um_objeto_vazio(corpo):
    # Paridade com Pedido::json() do CRM autónomo: a validação do domínio é
    # que diz o que falta (422 com os campos), não um 400.
    r = _cliente_eco().post("/eco", content=corpo, headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"recebido": {}}


def test_o_tipo_de_conteudo_nao_e_exigido():
    # Diferença assumida face ao CRM autónomo (que exigia application/json
    # por causa das sessões em cookie): no portal a sessão vai no cabeçalho
    # Authorization, que um formulário de outro site não consegue enviar.
    r = _cliente_eco().post("/eco", content=b'{"a": 1}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 200
    assert r.json() == {"recebido": {"a": 1}}


def test_a_sessao_e_verificada_antes_do_corpo_quando_vem_declarada_primeiro():
    # Regra do plano (correções, T1.3/T2.15): a dependência de perfil vem
    # SEMPRE antes de corpo_json. O FastAPI resolve as dependências pela ordem
    # em que são declaradas, por isso um pedido sem sessão e com JSON inválido
    # recebe 403 "Not authenticated" (como as rotas reais na T1.7), nunca 400.
    app = FastAPI()

    @app.post("/protegida")
    async def _rota(_sessao=Depends(HTTPBearer()), corpo: dict = Depends(corpo_json)):
        return corpo

    r = TestClient(app).post("/protegida", content=b"[", headers=JSON)
    assert r.status_code == 403
    assert r.json() == {"detail": "Not authenticated"}


def test_com_o_corpo_declarado_primeiro_o_400_passava_a_frente_da_sessao():
    # O contraexemplo que justifica a regra de cima: a ordem conta mesmo.
    app = FastAPI()

    @app.post("/mal_ordenada")
    async def _rota(corpo: dict = Depends(corpo_json), _sessao=Depends(HTTPBearer())):
        return corpo

    r = TestClient(app).post("/mal_ordenada", content=b"[", headers=JSON)
    assert r.status_code == 400
