"""Lançamentos: validação, forma de pagamento, voz, importação, isolamento e migração."""
import html as H
import io
import re

import pytest

import voz

BASE = {'descricao': 'Almoço', 'tipo': 'Despesa', 'categoria': 'Alimentação', 'valor': '30', 'data': '2026-10-05'}


def _lanc(app, m, usuario, descricao):
    with app.app_context():
        return m.Lancamento.query.filter_by(conta_id=usuario.conta_id, descricao=descricao).first()


# ── Validação ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('campo,valor,erro', [
    ('data', 'xx', 'Data inválida.'),
    ('valor', 'inf', 'O valor deve ser maior que zero.'),
    ('valor', '0', 'O valor deve ser maior que zero.'),
    ('categoria', 'Salário', 'Categoria inválida.'),       # categoria de receita numa despesa
    ('tipo', 'Outro', 'Tipo inválido.'),
    ('descricao', '  ', 'A descrição é obrigatória.'),
    ('forma_pagamento', 'Boleto', 'Forma de pagamento inválida.'),
])
def test_validacao_recusa_dados_invalidos(app, novo_usuario, logar, flashes, campo, valor, erro):
    c = logar(novo_usuario())
    r = c.post('/add', data={**BASE, campo: valor})
    assert r.status_code == 302 and erro in flashes(c)


# ── Forma de pagamento ───────────────────────────────────────────────────────
def test_forma_de_pagamento_salva_edita_e_e_opcional(app, m, novo_usuario, logar):
    u = novo_usuario()
    c = logar(u)
    c.post('/add', data={**BASE, 'forma_pagamento': 'Pix'})
    c.post('/add', data={**BASE, 'descricao': 'Sem forma'})
    assert _lanc(app, m, u, 'Almoço').forma_pagamento == 'Pix'
    assert _lanc(app, m, u, 'Sem forma').forma_pagamento is None

    lid = _lanc(app, m, u, 'Almoço').id
    c.post(f'/edit/{lid}', data={**BASE, 'forma_pagamento': 'Cartão de Crédito'})
    assert _lanc(app, m, u, 'Almoço').forma_pagamento == 'Cartão de Crédito'
    c.post(f'/edit/{lid}', data={**BASE, 'forma_pagamento': ''})
    assert _lanc(app, m, u, 'Almoço').forma_pagamento is None


def test_campo_forma_aparece_nas_telas(app, novo_usuario, logar):
    h = logar(novo_usuario()).get('/lancamentos').get_data(as_text=True)
    assert 'id="add_forma"' in h and 'id="edit_forma"' in h and 'id="voz-forma"' in h
    assert '<th>FORMA</th>' in h
    for forma in voz.FORMAS_PAGAMENTO:
        assert f'<option value="{forma}">{forma}</option>' in h


# ── Voz ──────────────────────────────────────────────────────────────────────
def test_rota_de_voz_interpreta_e_usa_a_conta_do_usuario(app, novo_usuario, logar):
    c = logar(novo_usuario())
    d = c.post('/voz/interpretar', json={'texto': 'gastei 30 reais no almoço no pix'}).get_json()
    assert (d['valor'], d['tipo'], d['forma_pagamento'], d['categoria']) == (30.0, 'Despesa', 'Pix', 'Alimentação')
    assert d['conta'] == 'Conta Principal'
    assert c.post('/voz/interpretar', json={'texto': '  '}).status_code == 400


# ── Importação ───────────────────────────────────────────────────────────────
def test_importacao_sugere_e_grava_categoria_e_forma(app, m, novo_usuario, logar):
    u = novo_usuario()
    with app.app_context():
        m.db.session.add(m.Categoria(nome='Transporte', tipo='Despesa', usuario_id=u.id))
        m.db.session.commit()
    c = logar(u)
    itens = [('Pix recebido de FULANO', '100.00'), ('RVA2I18-ECOVIAS RAPOSO', '-5.70'),
             ('RVA2I18-IGUATEMI SAO PAULO', '-32.00')]
    ofx = ''.join(f'<STMTTRN><DTPOSTED>20261001<TRNAMT>{v}<MEMO>{d}</STMTTRN>' for d, v in itens).encode()
    h = c.post('/importar', data={'arquivo': (io.BytesIO(ofx), 'extrato.ofx')},
               content_type='multipart/form-data').get_data(as_text=True)
    sugestoes = [H.unescape(x) for x in re.findall(r'data-sugestao="([^"]*)"', h)]
    assert sugestoes == ['', 'Transporte', '']          # sem par: "Sem categoria", não a primeira da lista
    assert re.search(r'<option value="Pix"\s+selected', h)

    dados = H.unescape(re.search(r'name="dados_json"[^>]*>(.*?)</textarea>', h, re.S).group(1))
    c.post('/importar/confirmar', data={
        'dados_json': dados,
        'importar_0': 'on', 'tipo_0': 'Receita', 'categoria_0': 'Salário', 'forma_0': 'Pix',
        'importar_1': 'on', 'tipo_1': 'Despesa', 'categoria_1': 'Transporte', 'forma_1': '',
        'importar_2': 'on', 'tipo_2': 'Despesa', 'categoria_2': '', 'forma_2': 'Boleto',   # forma inválida
    })
    assert _lanc(app, m, u, 'Pix recebido de FULANO').forma_pagamento == 'Pix'
    assert _lanc(app, m, u, 'RVA2I18-ECOVIAS RAPOSO').categoria == 'Transporte'
    assert _lanc(app, m, u, 'RVA2I18-IGUATEMI SAO PAULO') is None     # recusado pela forma inválida


# ── Isolamento entre usuários ────────────────────────────────────────────────
def test_um_usuario_nao_ve_nem_altera_dados_do_outro(app, m, novo_usuario, logar):
    ana, bruno = novo_usuario('ana'), novo_usuario('bruno')
    logar(bruno).post('/add', data={**BASE, 'descricao': 'SEGREDO-BRUNO', 'valor': '111'})
    b = _lanc(app, m, bruno, 'SEGREDO-BRUNO')
    with app.app_context():
        cat_b = m.Categoria.query.filter_by(usuario_id=bruno.id, nome='Moradia').first().id

    c = logar(ana)
    for url in ['/', '/lancamentos?mes=10&ano=2026', '/contas', '/configuracoes', '/relatorios?ano=2026']:
        assert 'SEGREDO-BRUNO' not in c.get(url).get_data(as_text=True), url

    c.post(f'/edit/{b.id}', data={**BASE, 'descricao': 'HACK'})
    c.post(f'/quitar/{b.id}')
    c.post(f'/delete/{b.id}')
    c.post(f'/contas/edit/{bruno.conta_id}', data={'nome': 'HACK'})
    c.post(f'/contas/delete/{bruno.conta_id}')
    c.post(f'/configuracoes/categoria/edit/{cat_b}', data={'nome': 'HACK', 'tipo': 'Despesa'})
    c.post(f'/configuracoes/categoria/delete/{cat_b}')
    with c.session_transaction() as s:
        s['conta_id'] = bruno.conta_id            # sessão forjada apontando para a conta alheia
    c.post('/add', data={**BASE, 'descricao': 'INTRUSO'})

    with app.app_context():
        l = m.db.session.get(m.Lancamento, b.id)
        assert (l.descricao, l.valor, l.pago) == ('SEGREDO-BRUNO', 111.0, False)
        assert m.db.session.get(m.Conta, bruno.conta_id).nome == 'Conta Principal'
        assert m.db.session.get(m.Categoria, cat_b).nome == 'Moradia'
        assert m.Lancamento.query.filter_by(conta_id=bruno.conta_id, descricao='INTRUSO').first() is None


# ── Migração ─────────────────────────────────────────────────────────────────
def test_migracao_adiciona_coluna_sem_perder_dados(app, m, novo_usuario, logar):
    u = novo_usuario()
    logar(u).post('/add', data={**BASE, 'descricao': 'ANTES-DA-MIGRACAO'})
    with app.app_context():
        with m.db.engine.begin() as conn:      # volta ao formato antigo (como o banco de produção)
            conn.execute(m.text('ALTER TABLE lancamento DROP COLUMN forma_pagamento'))
        m._init_db()
        m._init_db()                           # idempotente
        colunas = {c['name'] for c in m.sa_inspect(m.db.engine).get_columns('lancamento')}
        assert 'forma_pagamento' in colunas
    assert _lanc(app, m, u, 'ANTES-DA-MIGRACAO') is not None


def test_telas_abrem(app, novo_usuario, logar):
    c = logar(novo_usuario(admin=True))
    for url in ['/', '/lancamentos', '/contas', '/configuracoes', '/relatorios', '/importar',
                '/admin/usuarios', '/alterar-senha']:
        assert c.get(url).status_code == 200, url
