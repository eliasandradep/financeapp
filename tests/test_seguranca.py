"""Login, CSRF, sessões e administração."""
import re

import pytest

from conftest import ADMIN


def _token(cliente, url='/login'):
    html = cliente.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_cookies_seguros_fora_do_modo_dev(app):
    assert app.config['SESSION_COOKIE_SECURE'] and app.config['REMEMBER_COOKIE_SECURE']
    assert app.config['SESSION_COOKIE_HTTPONLY']


def test_post_sem_token_csrf_e_recusado(app, flashes):
    app.config['WTF_CSRF_ENABLED'] = True
    c = app.test_client()
    r = c.post('/login', data={'username': ADMIN.username, 'password': ADMIN.senha})
    assert r.status_code == 302
    assert any('expirou' in f for f in flashes(c))


def test_post_com_token_csrf_funciona(app, novo_usuario):
    app.config['WTF_CSRF_ENABLED'] = True
    u = novo_usuario()
    c = app.test_client()
    r = c.post('/login', data={'username': u.username, 'password': u.senha, 'csrf_token': _token(c)})
    assert r.status_code == 302 and r.location.endswith('/')


@pytest.mark.parametrize('url', [
    '/delete/1', '/quitar/1', '/contas/delete/1', '/contas/selecionar/1', '/admin/usuarios/toggle/2',
    '/admin/usuarios/delete/2', '/configuracoes/categoria/delete/1', '/logout', '/voz/interpretar',
])
def test_acoes_que_alteram_dados_nao_aceitam_get(app, novo_usuario, logar, url):
    c = logar(novo_usuario(admin=True))
    assert c.get(url).status_code == 405


def test_login_ignora_maiusculas_e_exige_troca_no_primeiro_acesso(app, novo_usuario):
    u = novo_usuario(primeiro_acesso=True)
    c = app.test_client()
    r = c.post('/login', data={'username': u.username.upper(), 'password': u.senha})
    assert '/alterar-senha' in r.location
    assert c.get('/').status_code == 302          # bloqueado até trocar a senha
    r = c.post('/alterar-senha', data={'nova_senha': 'novaSenha123', 'confirmar_senha': 'novaSenha123'})
    assert r.location.endswith('/')
    assert c.get('/').status_code == 200          # a sessão foi renovada após a troca


def test_next_externo_e_ignorado_no_login(app, novo_usuario):
    u = novo_usuario()
    c = app.test_client()
    r = c.post('/login?next=https://evil.com', data={'username': u.username, 'password': u.senha})
    assert 'evil' not in r.location


def test_referrer_externo_e_ignorado(app, novo_usuario, logar, m):
    u = novo_usuario()
    c = logar(u)
    c.post('/add', data={'descricao': 'X', 'tipo': 'Despesa', 'categoria': '', 'valor': '1', 'data': '2026-10-01'})
    with app.app_context():
        lid = m.Lancamento.query.filter_by(conta_id=u.conta_id).first().id
    r = c.post(f'/quitar/{lid}', headers={'Referer': 'https://evil.com/x'})
    assert 'evil' not in r.location


def test_bloqueio_apos_cinco_falhas(app, novo_usuario, flashes):
    u = novo_usuario()
    c = app.test_client()
    for _ in range(5):
        c.post('/login', data={'username': u.username, 'password': 'errada'})
    c.post('/login', data={'username': u.username, 'password': u.senha})
    assert any('Muitas tentativas' in f for f in flashes(c))


def test_reset_de_senha_derruba_sessao(app, novo_usuario, logar):
    admin, alvo = novo_usuario(admin=True), novo_usuario()
    c_alvo = logar(alvo)
    assert c_alvo.get('/').status_code == 200
    logar(admin).post(f'/admin/usuarios/reset-senha/{alvo.id}', data={'nova_senha': 'resetada123'})
    r = c_alvo.get('/')
    assert r.status_code == 302 and '/login' in r.location


def test_usuario_duplicado_com_outra_caixa_e_recusado(app, novo_usuario, logar, flashes):
    admin, existente = novo_usuario(admin=True), novo_usuario()
    c = logar(admin)
    c.post('/admin/usuarios/add', data={'username': existente.username.upper(), 'password': 'senhaTeste123'})
    assert any('já existe' in f for f in flashes(c))


def test_usuario_comum_nao_acessa_admin(app, novo_usuario, logar):
    assert logar(novo_usuario()).get('/admin/usuarios').status_code == 302


def test_admin_renomeado_nao_e_recriado(app, m):
    with app.app_context():
        admin = m.Usuario.query.filter_by(username=ADMIN.username).first()
        try:
            admin.username = 'chefe-renomeado'
            m.db.session.commit()
            m._init_db()
            assert m.Usuario.query.filter(m.db.func.lower(m.Usuario.username) == 'admin').first() is None
        finally:
            admin.username = ADMIN.username
            m.db.session.commit()
