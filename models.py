from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuario'
    id              = db.Column(db.Integer, primary_key=True)
    username        = db.Column(db.String(80), unique=True, nullable=False)
    password_hash   = db.Column(db.String(256), nullable=False)
    is_admin        = db.Column(db.Boolean, default=False, nullable=False)
    ativo           = db.Column(db.Boolean, default=True, nullable=False)
    primeiro_acesso = db.Column(db.Boolean, default=True, nullable=False)

    contas     = db.relationship('Conta',     backref='usuario', lazy=True, cascade='all, delete-orphan')
    categorias = db.relationship('Categoria', backref='usuario', lazy=True, cascade='all, delete-orphan')

    @property
    def is_active(self):
        return self.ativo


class Conta(db.Model):
    __tablename__ = 'conta'
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    tipo       = db.Column(db.String(50),  nullable=False, default='Corrente')
    banco      = db.Column(db.String(100))
    descricao  = db.Column(db.String(200))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)

    lancamentos = db.relationship('Lancamento', backref='conta', lazy=True, cascade='all, delete-orphan')


class Categoria(db.Model):
    __tablename__  = 'categoria'
    __table_args__ = (db.UniqueConstraint('nome', 'usuario_id', name='uq_cat_usuario'),)
    id         = db.Column(db.Integer, primary_key=True)
    nome       = db.Column(db.String(100), nullable=False)
    tipo       = db.Column(db.String(20),  nullable=False)   # 'Receita' ou 'Despesa'
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)


class Lancamento(db.Model):
    __tablename__   = 'lancamento'
    id              = db.Column(db.Integer, primary_key=True)
    data_vencimento = db.Column(db.Date,    nullable=False)
    descricao       = db.Column(db.String(200), nullable=False)
    categoria       = db.Column(db.String(100), nullable=False)
    tipo            = db.Column(db.String(20),  nullable=False)
    valor           = db.Column(db.Float,   nullable=False)
    pago            = db.Column(db.Boolean, default=False)
    conta_id        = db.Column(db.Integer, db.ForeignKey('conta.id'), nullable=False)
