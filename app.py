from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, Lancamento, Categoria
from datetime import datetime
from sqlalchemy import extract
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'financas_2026_dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///financas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

MESES = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

# Filtro personalizado para formatar moeda Real (R$ 0.000,00)
@app.template_filter('brl')
def format_currency(value):
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"

with app.app_context():
    db.create_all()
    if Categoria.query.count() == 0:
        for n, t in [('Salário', 'Receita'), ('Alimentação', 'Despesa'), ('Moradia', 'Despesa')]:
            db.session.add(Categoria(nome=n, tipo=t))
        db.session.commit()

# --- HELPERS ---
def get_periodo():
    hoje = datetime.now()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    # Garante valores válidos
    mes = max(1, min(12, mes))
    return mes, ano

def prev_next_month(mes, ano):
    prev_mes = 12 if mes == 1 else mes - 1
    prev_ano = ano - 1 if mes == 1 else ano
    next_mes = 1 if mes == 12 else mes + 1
    next_ano = ano + 1 if mes == 12 else ano
    return (prev_mes, prev_ano), (next_mes, next_ano)

def _query_mes(mes, ano):
    return Lancamento.query.filter(
        extract('month', Lancamento.data_vencimento) == mes,
        extract('year', Lancamento.data_vencimento) == ano
    )

# --- ROTAS ---
@app.route('/')
def index():
    mes, ano = get_periodo()
    (prev_mes, prev_ano), (next_mes, next_ano) = prev_next_month(mes, ano)
    dados = _query_mes(mes, ano).all()

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
                           prev_mes=prev_mes, prev_ano=prev_ano,
                           next_mes=next_mes, next_ano=next_ano)

@app.route('/lancamentos')
def lancamentos():
    mes, ano = get_periodo()
    (prev_mes, prev_ano), (next_mes, next_ano) = prev_next_month(mes, ano)
    dados = _query_mes(mes, ano).order_by(Lancamento.data_vencimento.asc()).all()
    cats_db = Categoria.query.all()
    cats_select = {
        'Receita': [c.nome for c in cats_db if c.tipo == 'Receita'],
        'Despesa': [c.nome for c in cats_db if c.tipo == 'Despesa']
    }
    return render_template('lancamentos.html',
                           dados=dados, categorias_select=cats_select,
                           mes_atual=mes, ano_atual=ano, nome_mes=MESES[mes],
                           prev_mes=prev_mes, prev_ano=prev_ano,
                           next_mes=next_mes, next_ano=next_ano,
                           hoje=datetime.now().strftime('%Y-%m-%d'),
                           hoje_date=datetime.now().date())

@app.route('/add', methods=['POST'])
def add():
    descricao = request.form.get('descricao', '').strip()
    tipo = request.form.get('tipo', '')
    categoria = request.form.get('categoria', '').strip()

    if tipo not in ('Receita', 'Despesa'):
        flash('Tipo de lançamento inválido.', 'error')
        return redirect(url_for('lancamentos'))

    if not descricao:
        flash('A descrição é obrigatória.', 'error')
        return redirect(url_for('lancamentos'))

    try:
        valor = float(request.form.get('valor', 0))
        if valor <= 0:
            raise ValueError()
    except ValueError:
        flash('O valor deve ser maior que zero.', 'error')
        return redirect(url_for('lancamentos'))

    data_obj = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
    novo = Lancamento(
        data_vencimento=data_obj, descricao=descricao,
        categoria=categoria, tipo=tipo,
        valor=valor, pago='pago' in request.form
    )
    db.session.add(novo)
    db.session.commit()
    flash('Lançamento adicionado com sucesso!', 'success')
    return redirect(url_for('lancamentos', mes=data_obj.month, ano=data_obj.year))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_lancamento(id):
    l = db.session.get(Lancamento, id)
    if not l:
        flash('Lançamento não encontrado.', 'error')
        return redirect(url_for('lancamentos'))

    try:
        valor = float(request.form.get('valor', 0))
        if valor <= 0:
            raise ValueError()
    except ValueError:
        flash('O valor deve ser maior que zero.', 'error')
        return redirect(url_for('lancamentos', mes=l.data_vencimento.month, ano=l.data_vencimento.year))

    l.data_vencimento = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
    l.descricao = request.form.get('descricao', '').strip()
    l.tipo = request.form.get('tipo', l.tipo)
    l.categoria = request.form.get('categoria', l.categoria)
    l.valor = valor
    l.pago = 'pago' in request.form
    db.session.commit()
    flash('Lançamento atualizado com sucesso!', 'success')
    return redirect(url_for('lancamentos', mes=l.data_vencimento.month, ano=l.data_vencimento.year))

@app.route('/quitar/<int:id>')
def quitar(id):
    l = db.session.get(Lancamento, id)
    if l:
        l.pago = not l.pago
        db.session.commit()
    return redirect(request.referrer or url_for('lancamentos'))

@app.route('/delete/<int:id>')
def delete(id):
    l = db.session.get(Lancamento, id)
    if not l:
        flash('Lançamento não encontrado.', 'error')
        return redirect(url_for('lancamentos'))
    mes, ano = l.data_vencimento.month, l.data_vencimento.year
    db.session.delete(l)
    db.session.commit()
    flash('Lançamento excluído.', 'success')
    return redirect(url_for('lancamentos', mes=mes, ano=ano))

@app.route('/configuracoes')
def configuracoes():
    categorias = Categoria.query.order_by(Categoria.tipo.desc(), Categoria.nome).all()
    contagem = {c.nome: Lancamento.query.filter_by(categoria=c.nome).count() for c in categorias}
    return render_template('configuracoes.html', categorias=categorias, contagem=contagem)

@app.route('/configuracoes/categoria/add', methods=['POST'])
def add_categoria():
    nome = request.form.get('nome', '').strip()
    tipo = request.form.get('tipo', '')

    if not nome:
        flash('O nome da categoria é obrigatório.', 'error')
        return redirect(url_for('configuracoes'))

    if tipo not in ('Receita', 'Despesa'):
        flash('Tipo inválido.', 'error')
        return redirect(url_for('configuracoes'))

    if Categoria.query.filter_by(nome=nome).first():
        flash(f'Categoria "{nome}" já existe.', 'error')
        return redirect(url_for('configuracoes'))

    db.session.add(Categoria(nome=nome, tipo=tipo))
    db.session.commit()
    flash(f'Categoria "{nome}" criada com sucesso!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/edit/<int:id>', methods=['POST'])
def edit_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('configuracoes'))

    novo_nome = request.form.get('nome', '').strip()
    novo_tipo = request.form.get('tipo', '')

    if not novo_nome:
        flash('O nome da categoria é obrigatório.', 'error')
        return redirect(url_for('configuracoes'))

    if novo_nome != cat.nome and Categoria.query.filter_by(nome=novo_nome).first():
        flash(f'Já existe uma categoria com o nome "{novo_nome}".', 'error')
        return redirect(url_for('configuracoes'))

    Lancamento.query.filter_by(categoria=cat.nome).update({Lancamento.categoria: novo_nome})
    cat.nome = novo_nome
    cat.tipo = novo_tipo
    db.session.commit()
    flash('Categoria atualizada com sucesso!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/delete/<int:id>')
def delete_categoria(id):
    cat = db.session.get(Categoria, id)
    if not cat:
        flash('Categoria não encontrada.', 'error')
        return redirect(url_for('configuracoes'))
    nome = cat.nome
    db.session.delete(cat)
    db.session.commit()
    flash(f'Categoria "{nome}" excluída.', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/relatorios')
def relatorios():
    ano = request.args.get('ano', datetime.now().year, type=int)
    dados = Lancamento.query.filter(
        extract('year', Lancamento.data_vencimento) == ano
    ).all()

    meses_dados = {}
    for l in dados:
        m = l.data_vencimento.month
        if m not in meses_dados:
            meses_dados[m] = {'receita': 0, 'despesa': 0}
        if l.tipo == 'Receita':
            meses_dados[m]['receita'] += l.valor
        else:
            meses_dados[m]['despesa'] += l.valor

    nomes_curtos = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                    'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    resumo = []
    for i in range(1, 13):
        m = meses_dados.get(i, {'receita': 0, 'despesa': 0})
        resumo.append({
            'mes': i,
            'nome': nomes_curtos[i - 1],
            'receita': m['receita'],
            'despesa': m['despesa'],
            'saldo': m['receita'] - m['despesa'],
        })

    total_rec = sum(r['receita'] for r in resumo)
    total_des = sum(r['despesa'] for r in resumo)
    anos_disponiveis = list(range(datetime.now().year, datetime.now().year - 5, -1))

    return render_template('relatorios.html',
                           resumo=resumo, ano_atual=ano,
                           total_rec=total_rec, total_des=total_des,
                           anos_disponiveis=anos_disponiveis)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1')
