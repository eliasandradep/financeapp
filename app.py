from flask import Flask, render_template, request, redirect, url_for
from models import db, Lancamento, Categoria
from datetime import datetime
from sqlalchemy import extract
import os

app = Flask(__name__)
app.secret_key = "financas_2026_widescreen_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///financas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Filtro personalizado para formatar moeda Real (R$ 0.000,00)
@app.template_filter('brl')
def format_currency(value):
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"

with app.app_context():
    db.create_all()
    # Popular categorias se vazio
    if Categoria.query.count() == 0:
        for n, t in [('Salário', 'Receita'), ('Alimentação', 'Despesa'), ('Moradia', 'Despesa')]:
            db.session.add(Categoria(nome=n, tipo=t))
        db.session.commit()

# --- HELPER PARA FILTRO DE DATA ---
def get_periodo():
    hoje = datetime.now()
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    return mes, ano

# --- ROTAS ---
@app.route('/')
def index():
    mes, ano = get_periodo()
    dados = Lancamento.query.filter(extract('month', Lancamento.data_vencimento) == mes, extract('year', Lancamento.data_vencimento) == ano).all()
    
    rec_real = sum(l.valor for l in dados if l.tipo == 'Receita' and l.pago)
    des_real = sum(l.valor for l in dados if l.tipo == 'Despesa' and l.pago)
    rec_prev = sum(l.valor for l in dados if l.tipo == 'Receita')
    des_prev = sum(l.valor for l in dados if l.tipo == 'Despesa')
    
    cats_map = {}
    for l in dados:
        if l.tipo == 'Despesa' and l.pago:
            cats_map[l.categoria] = cats_map.get(l.categoria, 0) + l.valor
            
    return render_template('dashboard.html', rec_real=rec_real, des_real=des_real, rec_prev=rec_prev, des_prev=des_prev,
                           categorias=cats_map, mes_atual=mes, ano_atual=ano)

@app.route('/lancamentos')
def lancamentos():
    mes, ano = get_periodo()
    dados = Lancamento.query.filter(extract('month', Lancamento.data_vencimento) == mes, extract('year', Lancamento.data_vencimento) == ano).order_by(Lancamento.data_vencimento.asc()).all()
    cats_db = Categoria.query.all()
    cats_select = {
        'Receita': [c.nome for c in cats_db if c.tipo == 'Receita'],
        'Despesa': [c.nome for c in cats_db if c.tipo == 'Despesa']
    }
    return render_template('lancamentos.html', dados=dados, categorias_select=cats_select, 
                           mes_atual=mes, ano_atual=ano, hoje=datetime.now().strftime('%Y-%m-%d'), hoje_date=datetime.now().date())

@app.route('/add', methods=['POST'])
def add():
    data_obj = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
    novo = Lancamento(
        data_vencimento=data_obj, descricao=request.form['descricao'], 
        categoria=request.form['categoria'], tipo=request.form['tipo'], 
        valor=float(request.form['valor']), pago='pago' in request.form
    )
    db.session.add(novo)
    db.session.commit()
    return redirect(url_for('lancamentos', mes=data_obj.month, ano=data_obj.year))

@app.route('/edit/<int:id>', methods=['POST'])
def edit_lancamento(id):
    l = Lancamento.query.get(id)
    if l:
        l.data_vencimento = datetime.strptime(request.form['data'], '%Y-%m-%d').date()
        l.descricao = request.form['descricao']
        l.tipo = request.form['tipo']
        l.categoria = request.form['categoria']
        l.valor = float(request.form['valor'])
        l.pago = 'pago' in request.form
        db.session.commit()
    return redirect(url_for('lancamentos', mes=l.data_vencimento.month, ano=l.data_vencimento.year))

@app.route('/quitar/<int:id>')
def quitar(id):
    l = Lancamento.query.get(id)
    if l:
        l.pago = not l.pago
        db.session.commit()
    return redirect(request.referrer)

@app.route('/delete/<int:id>')
def delete(id):
    l = Lancamento.query.get(id)
    mes, ano = l.data_vencimento.month, l.data_vencimento.year
    db.session.delete(l)
    db.session.commit()
    return redirect(url_for('lancamentos', mes=mes, ano=ano))

@app.route('/configuracoes')
def configuracoes():
    categorias = Categoria.query.order_by(Categoria.tipo.desc(), Categoria.nome).all()
    return render_template('configuracoes.html', categorias=categorias)

@app.route('/configuracoes/categoria/add', methods=['POST'])
def add_categoria():
    db.session.add(Categoria(nome=request.form['nome'], tipo=request.form['tipo']))
    db.session.commit()
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/edit/<int:id>', methods=['POST'])
def edit_categoria(id):
    cat = Categoria.query.get(id)
    if cat:
        novo_nome = request.form['nome']
        Lancamento.query.filter_by(categoria=cat.nome).update({Lancamento.categoria: novo_nome})
        cat.nome = novo_nome
        cat.tipo = request.form['tipo']
        db.session.commit()
    return redirect(url_for('configuracoes'))

@app.route('/configuracoes/categoria/delete/<int:id>')
def delete_categoria(id):
    cat = Categoria.query.get(id)
    if cat: db.session.delete(cat); db.session.commit()
    return redirect(url_for('configuracoes'))

if __name__ == '__main__':
    app.run(debug=True)