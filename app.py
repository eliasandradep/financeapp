from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Lancamento, Categoria, Usuario, Conta, TentativaLogin
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import extract, func
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlsplit, urlunsplit
from functools import wraps
import os, csv, io, re, json, math, secrets

# ── App & DB ──────────────────────────────────────────────────────────────────
# Modo dev: `python app.py` ou FLASK_DEBUG=1. Fora dele, a configuração é obrigatória.
_DEV = __name__ == '__main__' or os.environ.get('FLASK_DEBUG') == '1'

app = Flask(__name__)

_secret = os.environ.get('SECRET_KEY')
if not _secret:
    if not _DEV:
        raise RuntimeError('Defina a variável de ambiente SECRET_KEY.')
    _secret = 'dev-key-somente-local'
app.secret_key = _secret

_db_url = os.environ.get('DATABASE_URL')
if not _db_url:
    if not _DEV:
        raise RuntimeError('Defina a variável de ambiente DATABASE_URL (ex.: PostgreSQL).')
    _db_url = 'sqlite:///financas.db'
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,  SESSION_COOKIE_SAMESITE='Lax',  SESSION_COOKIE_SECURE=not _DEV,
    REMEMBER_COOKIE_HTTPONLY=True, REMEMBER_COOKIE_SAMESITE='Lax', REMEMBER_COOKIE_SECURE=not _DEV,
    WTF_CSRF_TIME_LIMIT=None,      # token vale enquanto durar a sessão
)

db.init_app(app)
csrf = CSRFProtect(app)

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faça login para acessar o sistema.'
login_manager.login_message_category = 'error'

@login_manager.user_loader
def load_user(uid):
    # uid = "<id>:<marca da senha>" (ver Usuario.get_id)
    id_, _, _ = uid.partition(':')
    if not id_.isdigit():
        return None
    u = db.session.get(Usuario, int(id_))
    return u if u and secrets.compare_digest(u.get_id(), uid) else None

# ── Migração / Seed ───────────────────────────────────────────────────────────
CATS_PADRAO = [('Salário', 'Receita'), ('Alimentação', 'Despesa'), ('Moradia', 'Despesa')]

def _seed_usuario(u):
    """Cria conta e categorias padrão para um usuário recém-criado."""
    conta = Conta(nome='Conta Principal', tipo='Corrente', usuario_id=u.id)
    db.session.add(conta)
    for nome, tipo in CATS_PADRAO:
        db.session.add(Categoria(nome=nome, tipo=tipo, usuario_id=u.id))

def _init_db():
    """Cria tabelas que faltam (nunca apaga dados) e o primeiro admin, se não houver nenhum."""
    db.create_all()
    if Usuario.query.filter_by(is_admin=True).first():
        return
    username = os.environ.get('ADMIN_USERNAME', 'Admin')
    senha = os.environ.get('ADMIN_PASSWORD')
    gerada = not senha
    if gerada:
        senha = secrets.token_urlsafe(12)
    try:
        admin = Usuario(username=username, password_hash=generate_password_hash(senha),
                        is_admin=True, ativo=True, primeiro_acesso=True)
        db.session.add(admin)
        db.session.flush()
        _seed_usuario(admin)
        db.session.commit()
    except IntegrityError:
        # Outro processo criou o admin ao mesmo tempo (ou o nome já existe sem ser admin).
        db.session.rollback()
        return
    if gerada:
        print(f'[FinanceApp] Admin inicial criado: usuário "{username}", senha "{senha}". '
              'A troca de senha será exigida no primeiro acesso.', flush=True)

with app.app_context():
    _init_db()
    # Com `gunicorn --preload` isto roda uma vez no processo mestre; descarta as
    # conexões abertas para que os workers não compartilhem sockets após o fork.
    db.engine.dispose()

# ── Erros ─────────────────────────────────────────────────────────────────────
@app.errorhandler(CSRFError)
def csrf_error(e):
    flash('Sua sessão expirou ou a requisição é inválida. Tente novamente.', 'error')
    return _redirect_seguro(request.referrer, 'index')

# ── Before request ────────────────────────────────────────────────────────────
@app.before_request
def check_primeiro_acesso():
    if request.endpoint is None:
        return
    livres = {'login', 'logout', 'static', 'alterar_senha'}
    if (current_user.is_authenticated
            and current_user.primeiro_acesso
            and request.endpoint not in livres):
        flash('Defina sua senha antes de continuar.', 'error')
        return redirect(url_for('alterar_senha'))

# ── Context processor (contas disponíveis em todos os templates) ──────────────
_CONTA_ICONS = {
    'Corrente':     'fa-building-columns',
    'Poupança':     'fa-piggy-bank',
    'Cartão':       'fa-credit-card',
    'Investimentos':'fa-chart-line',
    'Carteira':     'fa-wallet',
}

@app.context_processor
def inject_conta():
    def conta_tipo_icon(tipo):
        return _CONTA_ICONS.get(tipo, 'fa-building-columns')

    if current_user.is_authenticated:
        contas = Conta.query.filter_by(usuario_id=current_user.id).order_by(Conta.nome).all()
        return {'user_contas': contas, 'conta_atual': _get_conta(),
                'conta_tipo_icon': conta_tipo_icon}
    return {'user_contas': [], 'conta_atual': None, 'conta_tipo_icon': conta_tipo_icon}

# ── Decoradores ───────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Acesso restrito a administradores.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ── Filtros de template ───────────────────────────────────────────────────────
@app.template_filter('brl')
def format_brl(value):
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"

@app.template_filter('dmy')
def format_dmy(value):
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return str(value)

# ── Parsers de extrato ────────────────────────────────────────────────────────
def _decode(raw):
    for enc in ('utf-8-sig', 'iso-8859-1', 'windows-1252', 'utf-8'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')

def _br_value(s):
    s = str(s).strip()
    if not s:
        return None
    neg = s.startswith('-') or (s.startswith('(') and s.endswith(')'))
    s = s.replace('R$', '').replace(' ', '').lstrip('+-').strip('()')
    if not s:
        return None
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind('.') < s.rfind(',') else s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        s = s.replace(',', '.') if len(parts) == 2 and len(parts[1]) <= 2 else s.replace(',', '')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None

def _br_date(s):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%Y'):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None

def parse_ofx(raw):
    content = _decode(raw)
    out = []
    for block in re.finditer(r'<STMTTRN>(.*?)</STMTTRN>', content, re.DOTALL | re.IGNORECASE):
        seg = block.group(1)
        def tag(n, s=seg):
            m = re.search(rf'<{n}>\s*([^\r\n<]+)', s, re.IGNORECASE)
            return m.group(1).strip() if m else ''
        dp, amt, memo = tag('DTPOSTED'), tag('TRNAMT'), tag('MEMO') or tag('NAME') or ''
        try:
            dt = date(int(dp[:4]), int(dp[4:6]), int(dp[6:8]))
        except Exception:
            continue
        v = _br_value(amt)
        if v is None:
            continue
        out.append({'data': dt.isoformat(), 'descricao': (memo or 'Sem descrição')[:200],
                    'tipo': 'Receita' if v >= 0 else 'Despesa', 'valor': round(abs(v), 2)})
    return out

def parse_csv_generic(raw):
    content = _decode(raw)
    lines = [l for l in content.splitlines() if l.strip()]
    if not lines:
        return []
    sep = ';' if lines[0].count(';') >= lines[0].count(',') else ','
    rows = [r for r in csv.reader(io.StringIO(content), delimiter=sep) if any(c.strip() for c in r)]

    def norm(s):
        return re.sub(r'[\s_]', '', s).lower().translate(str.maketrans('çãáéíóú', 'caaeiou'))

    DATE_K = {'data', 'date', 'dt'}; VAL_K = {'valor', 'value', 'amount', 'vlr', 'credito', 'debito'}
    SKIP_K = {'saldo', 'balance'}; DESC_K = {'historico', 'descricao', 'memo', 'description', 'complemento'}
    dc = vc = xc = None; hi = 0

    for i, row in enumerate(rows[:25]):
        cells = [norm(c) for c in row]
        for j, cell in enumerate(cells):
            if (cell in DATE_K or 'data' in cell or 'date' in cell) and dc is None:
                dc = j
            elif cell in VAL_K and cell not in SKIP_K and vc is None:
                vc = j
            elif cell in DESC_K and xc is None:
                xc = j
        if dc is not None and vc is not None:
            hi = i; break

    if dc is None or vc is None:
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                if _br_date(cell) and j < 5:
                    for k, c2 in enumerate(row):
                        if k != j and _br_value(c2) is not None:
                            dc, vc = j, k
                            xc = next((m for m in range(len(row)) if m not in (j, k)), None)
                            hi = i - 1; break
                if dc is not None: break
            if dc is not None: break

    if dc is None or vc is None:
        return []

    out = []
    for row in rows[hi + 1:]:
        if len(row) <= max(dc, vc): continue
        dt = _br_date(row[dc]); v = _br_value(row[vc])
        if not dt or v is None or v == 0: continue
        desc = row[xc].strip() if xc is not None and xc < len(row) else ''
        if not desc:
            desc = next((c.strip() for k, c in enumerate(row)
                         if k not in (dc, vc) and c.strip() and _br_value(c) is None and _br_date(c) is None), '')
        out.append({'data': dt.isoformat(), 'descricao': (desc or 'Sem descrição')[:200],
                    'tipo': 'Receita' if v >= 0 else 'Despesa', 'valor': round(abs(v), 2)})
    return out

# ── Helpers ───────────────────────────────────────────────────────────────────
MESES = {1:'Janeiro', 2:'Fevereiro', 3:'Março', 4:'Abril', 5:'Maio', 6:'Junho',
         7:'Julho', 8:'Agosto', 9:'Setembro', 10:'Outubro', 11:'Novembro', 12:'Dezembro'}

def _get_periodo():
    hoje = datetime.now()
    return max(1, min(12, request.args.get('mes', hoje.month, type=int))), \
           request.args.get('ano', hoje.year, type=int)

def _prev_next(mes, ano):
    pm = 12 if mes == 1 else mes - 1; pa = ano - 1 if mes == 1 else ano
    nm = 1 if mes == 12 else mes + 1; na = ano + 1 if mes == 12 else ano
    return (pm, pa), (nm, na)

def _get_conta():
    if not current_user.is_authenticated:
        return None
    cid = session.get('conta_id')
    if cid:
        c = db.session.get(Conta, cid)
        if c and c.usuario_id == current_user.id:
            return c
    c = Conta.query.filter_by(usuario_id=current_user.id).first()
    if c:
        session['conta_id'] = c.id
    return c

def _query_mes(mes, ano, conta_id):
    return Lancamento.query.filter(
        extract('month', Lancamento.data_vencimento) == mes,
        extract('year',  Lancamento.data_vencimento) == ano,
        Lancamento.conta_id == conta_id
    )

def _cats_select(usuario_id):
    cats = Categoria.query.filter_by(usuario_id=usuario_id).all()
    return {'Receita': [c.nome for c in cats if c.tipo == 'Receita'],
            'Despesa': [c.nome for c in cats if c.tipo == 'Despesa']}

def _categoria_valida(nome, tipo, cats=None):
    """Categoria vazia ou pertencente ao usuário atual e ao tipo informado."""
    cats = cats or _cats_select(current_user.id)
    return nome == '' or nome in cats.get(tipo, [])

def _parse_data(s):
    try:
        return datetime.strptime(s or '', '%Y-%m-%d').date()
    except ValueError:
        return None

def _parse_valor(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 2) if math.isfinite(v) and v > 0 else None

def _validar_lancamento(form):
    """Valida o formulário de lançamento. Retorna (campos, None) ou (None, mensagem de erro)."""
    descricao = form.get('descricao', '').strip()
    tipo      = form.get('tipo', '')
    categoria = form.get('categoria', '').strip()
    if tipo not in ('Receita', 'Despesa'):
        return None, 'Tipo inválido.'
    if not descricao:
        return None, 'A descrição é obrigatória.'
    if not _categoria_valida(categoria, tipo):
        return None, 'Categoria inválida.'
    valor = _parse_valor(form.get('valor'))
    if valor is None:
        return None, 'O valor deve ser maior que zero.'
    data_obj = _parse_data(form.get('data'))
    if not data_obj:
        return None, 'Data inválida.'
    return {'data_vencimento': data_obj, 'descricao': descricao[:200], 'categoria': categoria,
            'tipo': tipo, 'valor': valor, 'pago': 'pago' in form}, None

def _redirect_seguro(alvo, padrao):
    """Redireciona só para URLs do próprio site (evita open redirect)."""
    if alvo:
        p = urlsplit(alvo.replace('\\', '/'))
        if (p.scheme in ('', 'http', 'https')
                and p.netloc in ('', request.host)
                and p.path.startswith('/') and not p.path.startswith('//')):
            return redirect(urlunsplit(('', '', p.path, p.query, '')))
    return redirect(url_for(padrao))

# Limite de tentativas de login por usuário
LOGIN_MAX_FALHAS = 5
LOGIN_JANELA     = timedelta(minutes=15)

def _agora_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _login_bloqueado(username):
    desde = _agora_utc() - LOGIN_JANELA
    return TentativaLogin.query.filter(TentativaLogin.username == username,
                                       TentativaLogin.criado_em >= desde).count() >= LOGIN_MAX_FALHAS

def _registrar_falha_login(username):
    agora = _agora_utc()
    TentativaLogin.query.filter(TentativaLogin.criado_em < agora - LOGIN_JANELA).delete()
    db.session.add(TentativaLogin(username=username, criado_em=agora))
    db.session.commit()

def _buscar_usuario(username):
    """Busca sem diferenciar maiúsculas/minúsculas."""
    return Usuario.query.filter(func.lower(Usuario.username) == username.lower()).first()

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        chave = username.lower()[:80]
        if _login_bloqueado(chave):
            flash('Muitas tentativas de login. Aguarde alguns minutos e tente novamente.', 'error')
            return redirect(url_for('login'))
        user = _buscar_usuario(username)
        if user and check_password_hash(user.password_hash, request.form.get('password', '')):
            if not user.ativo:
                flash('Conta desativada. Contacte o administrador.', 'error')
                return redirect(url_for('login'))
            TentativaLogin.query.filter_by(username=chave).delete()
            db.session.commit()
            session.clear()
            login_user(user, remember=bool(request.form.get('remember')))
            if user.primeiro_acesso:
                flash('Bem-vindo! Defina sua senha antes de continuar.', 'error')
                return redirect(url_for('alterar_senha'))
            return _redirect_seguro(request.args.get('next'), 'index')
        _registrar_falha_login(chave)
        flash('Usuário ou senha incorretos.', 'error')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.pop('conta_id', None)
    logout_user()
    return redirect(url_for('login'))

@app.route('/alterar-senha', methods=['GET', 'POST'])
@login_required
def alterar_senha():
    if request.method == 'POST':
        nova = request.form.get('nova_senha', '')
        if not current_user.primeiro_acesso:
            if not check_password_hash(current_user.password_hash, request.form.get('senha_atual', '')):
                flash('Senha atual incorreta.', 'error')
                return redirect(url_for('alterar_senha'))
        if len(nova) < 8:
            flash('A nova senha deve ter pelo menos 8 caracteres.', 'error')
            return redirect(url_for('alterar_senha'))
        if nova != request.form.get('confirmar_senha', ''):
            flash('As senhas não coincidem.', 'error')
            return redirect(url_for('alterar_senha'))
        user = current_user._get_current_object()
        user.password_hash = generate_password_hash(nova)
        user.primeiro_acesso = False
        db.session.commit()
        # A troca de senha invalida as sessões antigas; renova a sessão atual.
        login_user(user, remember=bool(request.cookies.get('remember_token')))
        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('index'))
    return render_template('alterar_senha.html')

# ── Contas ────────────────────────────────────────────────────────────────────
@app.route('/contas')
@login_required
def contas():
    lista = Conta.query.filter_by(usuario_id=current_user.id).order_by(Conta.nome).all()
    contagem = {c.id: Lancamento.query.filter_by(conta_id=c.id).count() for c in lista}
    return render_template('contas.html', contas=lista, contagem=contagem)

@app.route('/contas/add', methods=['POST'])
@login_required
def add_conta():
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('O nome da conta é obrigatório.', 'error')
        return redirect(url_for('contas'))
    nova = Conta(nome=nome, tipo=request.form.get('tipo', 'Corrente'),
                 banco=request.form.get('banco', '').strip() or None,
                 descricao=request.form.get('descricao', '').strip() or None,
                 usuario_id=current_user.id)
    db.session.add(nova)
    db.session.commit()
    session['conta_id'] = nova.id
    flash(f'Conta "{nome}" criada! Você está gerenciando ela agora.', 'success')
    return redirect(url_for('contas'))

@app.route('/contas/edit/<int:id>', methods=['POST'])
@login_required
def edit_conta(id):
    c = db.session.get(Conta, id)
    if not c or c.usuario_id != current_user.id:
        flash('Conta não encontrada.', 'error')
        return redirect(url_for('contas'))
    c.nome      = request.form.get('nome', '').strip() or c.nome
    c.tipo      = request.form.get('tipo', c.tipo)
    c.banco     = request.form.get('banco', '').strip() or None
    c.descricao = request.form.get('descricao', '').strip() or None
    db.session.commit()
    flash('Conta atualizada.', 'success')
    return redirect(url_for('contas'))

@app.route('/contas/delete/<int:id>', methods=['POST'])
@login_required
def delete_conta(id):
    c = db.session.get(Conta, id)
    if not c or c.usuario_id != current_user.id:
        flash('Conta não encontrada.', 'error')
        return redirect(url_for('contas'))
    if Conta.query.filter_by(usuario_id=current_user.id).count() <= 1:
        flash('Não é possível excluir a única conta. Crie outra primeiro.', 'error')
        return redirect(url_for('contas'))
    nome = c.nome
    if session.get('conta_id') == id:
        session.pop('conta_id', None)
    db.session.delete(c)
    db.session.commit()
    flash(f'Conta "{nome}" excluída.', 'success')
    return redirect(url_for('contas'))

@app.route('/contas/selecionar/<int:id>', methods=['POST'])
@login_required
def selecionar_conta(id):
    c = db.session.get(Conta, id)
    if c and c.usuario_id == current_user.id:
        session['conta_id'] = id
        flash(f'Conta alterada para "{c.nome}".', 'success')
    return _redirect_seguro(request.referrer, 'index')

# ── Admin: Usuários ───────────────────────────────────────────────────────────
@app.route('/admin/usuarios')
@login_required
@admin_required
def admin_usuarios():
    usuarios = Usuario.query.order_by(Usuario.username).all()
    n_contas = {u.id: Conta.query.filter_by(usuario_id=u.id).count() for u in usuarios}
    return render_template('admin_usuarios.html', usuarios=usuarios, n_contas=n_contas)

@app.route('/admin/usuarios/add', methods=['POST'])
@login_required
@admin_required
def admin_add_usuario():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin = bool(request.form.get('is_admin'))

    if not username:
        flash('Nome de usuário é obrigatório.', 'error')
        return redirect(url_for('admin_usuarios'))
    if len(password) < 8:
        flash('A senha deve ter pelo menos 8 caracteres.', 'error')
        return redirect(url_for('admin_usuarios'))
    if len(username) > 80:
        flash('Nome de usuário muito longo (máx. 80 caracteres).', 'error')
        return redirect(url_for('admin_usuarios'))
    if _buscar_usuario(username):
        flash(f'Usuário "{username}" já existe.', 'error')
        return redirect(url_for('admin_usuarios'))

    novo = Usuario(username=username, password_hash=generate_password_hash(password),
                   is_admin=is_admin, ativo=True, primeiro_acesso=True)
    db.session.add(novo)
    db.session.flush()
    _seed_usuario(novo)
    db.session.commit()
    flash(f'Usuário "{username}" criado com sucesso!', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_edit_usuario(id):
    user = db.session.get(Usuario, id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_usuarios'))
    novo_username = request.form.get('username', '').strip()
    if novo_username and novo_username != user.username:
        if len(novo_username) > 80:
            flash('Nome de usuário muito longo (máx. 80 caracteres).', 'error')
            return redirect(url_for('admin_usuarios'))
        existente = _buscar_usuario(novo_username)
        if existente and existente.id != user.id:
            flash(f'Usuário "{novo_username}" já existe.', 'error')
            return redirect(url_for('admin_usuarios'))
        user.username = novo_username
    # Não permite remover admin do próprio usuário
    if user.id != current_user.id:
        user.is_admin = bool(request.form.get('is_admin'))
    db.session.commit()
    flash('Usuário atualizado.', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/toggle/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_usuario(id):
    user = db.session.get(Usuario, id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_usuarios'))
    if user.id == current_user.id:
        flash('Você não pode desativar sua própria conta.', 'error')
        return redirect(url_for('admin_usuarios'))
    user.ativo = not user.ativo
    db.session.commit()
    flash(f'Usuário "{user.username}" {"ativado" if user.ativo else "desativado"}.', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/reset-senha/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_reset_senha(id):
    user = db.session.get(Usuario, id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_usuarios'))
    nova = request.form.get('nova_senha', '')
    if len(nova) < 8:
        flash('A senha deve ter pelo menos 8 caracteres.', 'error')
        return redirect(url_for('admin_usuarios'))
    user.password_hash = generate_password_hash(nova)
    user.primeiro_acesso = True
    db.session.commit()
    if user.id == current_user.id:
        login_user(user)  # a troca de senha invalidou a sessão atual
    flash(f'Senha de "{user.username}" redefinida. O usuário deverá alterá-la no próximo acesso.', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_usuario(id):
    user = db.session.get(Usuario, id)
    if not user:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('admin_usuarios'))
    if user.id == current_user.id:
        flash('Você não pode excluir sua própria conta.', 'error')
        return redirect(url_for('admin_usuarios'))
    nome = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f'Usuário "{nome}" e todos os seus dados foram excluídos.', 'success')
    return redirect(url_for('admin_usuarios'))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    conta = _get_conta()
    if not conta:
        flash('Crie uma conta financeira para começar a usar o app.', 'error')
        return redirect(url_for('contas'))

    mes, ano = _get_periodo()
    (pm, pa), (nm, na) = _prev_next(mes, ano)
    dados = _query_mes(mes, ano, conta.id).all()

    rec_real = sum(l.valor for l in dados if l.tipo == 'Receita' and l.pago)
    des_real = sum(l.valor for l in dados if l.tipo == 'Despesa' and l.pago)
    rec_prev = sum(l.valor for l in dados if l.tipo == 'Receita')
    des_prev = sum(l.valor for l in dados if l.tipo == 'Despesa')

    cats_map = {}
    for l in dados:
        if l.tipo == 'Despesa' and l.pago:
            cats_map[l.categoria] = cats_map.get(l.categoria, 0) + l.valor

    return render_template('dashboard.html',
                           rec_real=rec_real, des_real=des_real,
                           rec_prev=rec_prev, des_prev=des_prev,
                           categorias=cats_map,
                           mes_atual=mes, ano_atual=ano, nome_mes=MESES[mes],
                           prev_mes=pm, prev_ano=pa, next_mes=nm, next_ano=na)

# ── Lançamentos ───────────────────────────────────────────────────────────────
@app.route('/lancamentos')
@login_required
def lancamentos():
    conta = _get_conta()
    if not conta:
        flash('Crie uma conta financeira primeiro.', 'error')
        return redirect(url_for('contas'))

    mes, ano = _get_periodo()
    (pm, pa), (nm, na) = _prev_next(mes, ano)
    dados = _query_mes(mes, ano, conta.id).order_by(Lancamento.data_vencimento.asc()).all()

    return render_template('lancamentos.html',
                           dados=dados, categorias_select=_cats_select(current_user.id),
                           mes_atual=mes, ano_atual=ano, nome_mes=MESES[mes],
                           prev_mes=pm, prev_ano=pa, next_mes=nm, next_ano=na,
                           hoje=datetime.now().strftime('%Y-%m-%d'),
                           hoje_date=datetime.now().date())

@app.route('/add', methods=['POST'])
@login_required
def add():
    conta = _get_conta()
    if not conta:
        flash('Selecione uma conta primeiro.', 'error')
        return redirect(url_for('contas'))

    dados, erro = _validar_lancamento(request.form)
    if erro:
        flash(erro, 'error')
        return redirect(url_for('lancamentos'))
    db.session.add(Lancamento(conta_id=conta.id, **dados))
    db.session.commit()
    flash('Lançamento adicionado!', 'success')
    data_obj = dados['data_vencimento']
    return redirect(url_for('lancamentos', mes=data_obj.month, ano=data_obj.year))

@app.route('/edit/<int:id>', methods=['POST'])
@login_required
def edit_lancamento(id):
    l = db.session.get(Lancamento, id)
    if not l or l.conta.usuario_id != current_user.id:
        flash('Lançamento não encontrado.', 'error')
        return redirect(url_for('lancamentos'))
    dados, erro = _validar_lancamento(request.form)
    if erro:
        flash(erro, 'error')
        return redirect(url_for('lancamentos', mes=l.data_vencimento.month, ano=l.data_vencimento.year))
    for campo, v in dados.items():
        setattr(l, campo, v)
    db.session.commit()
    flash('Lançamento atualizado!', 'success')
    return redirect(url_for('lancamentos', mes=l.data_vencimento.month, ano=l.data_vencimento.year))

@app.route('/quitar/<int:id>', methods=['POST'])
@login_required
def quitar(id):
    l = db.session.get(Lancamento, id)
    if l and l.conta.usuario_id == current_user.id:
        l.pago = not l.pago
        db.session.commit()
    return _redirect_seguro(request.referrer, 'lancamentos')

@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    l = db.session.get(Lancamento, id)
    if not l or l.conta.usuario_id != current_user.id:
        flash('Lançamento não encontrado.', 'error')
        return redirect(url_for('lancamentos'))
    mes, ano = l.data_vencimento.month, l.data_vencimento.year
    db.session.delete(l)
    db.session.commit()
    flash('Lançamento excluído.', 'success')
    return redirect(url_for('lancamentos', mes=mes, ano=ano))

# ── Categorias ────────────────────────────────────────────────────────────────
@app.route('/configuracoes')
@login_required
def configuracoes():
    cats = Categoria.query.filter_by(usuario_id=current_user.id) \
                    .order_by(Categoria.tipo.desc(), Categoria.nome).all()
    conta = _get_conta()
    conta_ids = [c.id for c in current_user.contas]
    contagem = {c.nome: Lancamento.query.filter(
        Lancamento.categoria == c.nome,
        Lancamento.conta_id.in_(conta_ids)
    ).count() for c in cats}
    return render_template('configuracoes.html', categorias=cats, contagem=contagem)

@app.route('/configuracoes/categoria/add', methods=['POST'])
@login_required
def add_categoria():
    nome = request.form.get('nome', '').strip()
    tipo = request.form.get('tipo', '')
    if not nome:
        flash('O nome é obrigatório.', 'error')
        return redirect(url_for('configuracoes'))
    if tipo not in ('Receita', 'Despesa'):
        flash('Tipo inválido.', 'error')
        return redirect(url_for('configuracoes'))
    if Categoria.query.filter_by(nome=nome, usuario_id=current_user.id).first():
        flash(f'Categoria "{nome}" já existe.', 'error')
        return redirect(url_for('configuracoes'))
    db.session.add(Categoria(nome=nome, tipo=tipo, usuario_id=current_user.id))
    db.session.commit()
    flash(f'Categoria "{nome}" criada!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/edit/<int:id>', methods=['POST'])
@login_required
def edit_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat or cat.usuario_id != current_user.id:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('configuracoes'))
    novo_nome = request.form.get('nome', '').strip()
    if not novo_nome:
        flash('O nome é obrigatório.', 'error')
        return redirect(url_for('configuracoes'))
    if novo_nome != cat.nome and Categoria.query.filter_by(nome=novo_nome, usuario_id=current_user.id).first():
        flash(f'Categoria "{novo_nome}" já existe.', 'error')
        return redirect(url_for('configuracoes'))
    conta_ids = [c.id for c in current_user.contas]
    Lancamento.query.filter(
        Lancamento.categoria == cat.nome,
        Lancamento.conta_id.in_(conta_ids)
    ).update({Lancamento.categoria: novo_nome})
    cat.nome = novo_nome
    cat.tipo = request.form.get('tipo', cat.tipo)
    db.session.commit()
    flash('Categoria atualizada!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/delete/<int:id>', methods=['POST'])
@login_required
def delete_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat or cat.usuario_id != current_user.id:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('configuracoes'))
    nome = cat.nome
    db.session.delete(cat)
    db.session.commit()
    flash(f'Categoria "{nome}" excluída.', 'success')
    return redirect(url_for('configuracoes'))

# ── Relatórios ────────────────────────────────────────────────────────────────
@app.route('/relatorios')
@login_required
def relatorios():
    conta = _get_conta()
    if not conta:
        flash('Crie uma conta financeira primeiro.', 'error')
        return redirect(url_for('contas'))

    ano = request.args.get('ano', datetime.now().year, type=int)
    dados = Lancamento.query.filter(
        extract('year', Lancamento.data_vencimento) == ano,
        Lancamento.conta_id == conta.id
    ).all()

    md = {}
    for l in dados:
        m = l.data_vencimento.month
        md.setdefault(m, {'receita': 0, 'despesa': 0})
        md[m]['receita' if l.tipo == 'Receita' else 'despesa'] += l.valor

    nomes = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
    resumo = [{'mes': i, 'nome': nomes[i-1],
               'receita': md.get(i, {}).get('receita', 0),
               'despesa': md.get(i, {}).get('despesa', 0),
               'saldo':   md.get(i, {}).get('receita', 0) - md.get(i, {}).get('despesa', 0)}
              for i in range(1, 13)]

    total_rec = sum(r['receita'] for r in resumo)
    total_des = sum(r['despesa'] for r in resumo)
    return render_template('relatorios.html', resumo=resumo, ano_atual=ano,
                           total_rec=total_rec, total_des=total_des,
                           anos_disponiveis=list(range(datetime.now().year, datetime.now().year - 5, -1)))

# ── Importar extrato ──────────────────────────────────────────────────────────
@app.route('/importar', methods=['GET', 'POST'])
@login_required
def importar():
    transacoes = None
    arquivo_nome = None
    if request.method == 'POST':
        arq = request.files.get('arquivo')
        if not arq or not arq.filename:
            flash('Selecione um arquivo.', 'error')
            return redirect(url_for('importar'))
        raw = arq.read()
        nome = arq.filename.lower()
        if nome.endswith(('.ofx', '.qfx')):
            transacoes = parse_ofx(raw)
        elif nome.endswith(('.csv', '.txt')):
            transacoes = parse_csv_generic(raw)
        else:
            flash('Formato não suportado. Use .ofx, .qfx ou .csv', 'error')
            return redirect(url_for('importar'))
        if not transacoes:
            flash('Nenhuma transação encontrada no arquivo.', 'error')
            return redirect(url_for('importar'))
        arquivo_nome = arq.filename
    return render_template('importar.html', transacoes=transacoes,
                           arquivo_nome=arquivo_nome,
                           categorias_select=_cats_select(current_user.id))

@app.route('/importar/confirmar', methods=['POST'])
@login_required
def importar_confirmar():
    conta = _get_conta()
    if not conta:
        flash('Selecione uma conta primeiro.', 'error')
        return redirect(url_for('contas'))
    try:
        transacoes = json.loads(request.form.get('dados_json', '[]'))
    except (json.JSONDecodeError, TypeError):
        flash('Erro ao processar dados de importação.', 'error')
        return redirect(url_for('importar'))

    if not isinstance(transacoes, list):
        flash('Erro ao processar dados de importação.', 'error')
        return redirect(url_for('importar'))

    cats = _cats_select(current_user.id)
    importados = 0
    for i, t in enumerate(transacoes):
        if not request.form.get(f'importar_{i}') or not isinstance(t, dict):
            continue
        data_obj  = _parse_data(str(t.get('data', '')))
        valor     = _parse_valor(t.get('valor'))
        tipo      = request.form.get(f'tipo_{i}', t.get('tipo', 'Despesa'))
        categoria = request.form.get(f'categoria_{i}', '').strip()
        if (not data_obj or valor is None or tipo not in ('Receita', 'Despesa')
                or not _categoria_valida(categoria, tipo, cats)):
            continue
        db.session.add(Lancamento(
            data_vencimento=data_obj,
            descricao=str(t.get('descricao') or 'Sem descrição')[:200],
            categoria=categoria, tipo=tipo, valor=valor, pago=True, conta_id=conta.id
        ))
        importados += 1

    if importados:
        db.session.commit()
        flash(f'{importados} lançamento(s) importado(s)!', 'success')
    else:
        flash('Nenhum lançamento selecionado.', 'error')
    return redirect(url_for('lancamentos'))

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1')
