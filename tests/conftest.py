"""Configuração dos testes: app em modo produção apontando para um SQLite temporário.

Rodar: venv\\Scripts\\python -m pytest
"""
import contextlib
import io
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_TMP = Path(tempfile.mkdtemp(prefix='financeapp-testes-'))

# O app lê a configuração ao ser importado, então o ambiente vem antes do import.
os.environ.update(
    SECRET_KEY='chave-somente-para-testes-' + 'x' * 32,
    DATABASE_URL='sqlite:///' + (_TMP / 'teste.db').as_posix(),
    ADMIN_USERNAME='Admin',
    ADMIN_PASSWORD='senhaAdmin123',
)
os.environ.pop('FLASK_DEBUG', None)
sys.path.insert(0, str(RAIZ))

with contextlib.redirect_stdout(io.StringIO()):
    import app as financeapp          # noqa: E402

from werkzeug.security import generate_password_hash   # noqa: E402

ADMIN = SimpleNamespace(username='Admin', senha='senhaAdmin123')


@pytest.fixture
def m():
    """O módulo do app (rotas, models e helpers)."""
    return financeapp


@pytest.fixture
def app():
    """App com CSRF desligado; os testes de CSRF religam explicitamente."""
    financeapp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield financeapp.app
    financeapp.app.config['WTF_CSRF_ENABLED'] = False


@pytest.fixture
def novo_usuario(app):
    """Cria um usuário com conta e categorias padrão. O banco é compartilhado entre os
    testes, então cada usuário recebe um nome único."""
    def criar(prefixo='user', admin=False, senha='senhaTeste123', primeiro_acesso=False):
        nome = f'{prefixo}-{uuid.uuid4().hex[:8]}'
        with app.app_context():
            u = financeapp.Usuario(username=nome, password_hash=generate_password_hash(senha),
                                   is_admin=admin, ativo=True, primeiro_acesso=primeiro_acesso)
            financeapp.db.session.add(u)
            financeapp.db.session.flush()
            financeapp._seed_usuario(u)
            financeapp.db.session.commit()
            conta = financeapp.Conta.query.filter_by(usuario_id=u.id).first()
            return SimpleNamespace(id=u.id, username=nome, senha=senha,
                                   sessao=u.get_id(), conta_id=conta.id)
    return criar


@pytest.fixture
def logar(app):
    """Cliente de teste já autenticado como o usuário informado."""
    def entrar(usuario):
        c = app.test_client()
        with c.session_transaction() as s:
            s['_user_id'] = usuario.sessao
            s['_fresh'] = True
        return c
    return entrar


@pytest.fixture
def flashes():
    """Mensagens flash pendentes na sessão do cliente."""
    def ler(cliente):
        with cliente.session_transaction() as s:
            return [msg for _, msg in s.get('_flashes', [])]
    return ler
