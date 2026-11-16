"""Interpretação de frases de voz e sugestões a partir de descrições de extrato."""
from datetime import date

import pytest

import voz

HOJE = date(2026, 10, 16)   # sexta-feira
CATS = {'Receita': ['Salário', 'Vendas'],
        'Despesa': ['Alimentação', 'Moradia', 'Transporte', 'Saúde']}

# (frase, campos esperados) — só os campos informados são conferidos
CASOS = [
    ('Assistente Financeiro, gasto com barrinha de cereal R$ 9,90.',
     dict(tipo='Despesa', valor=9.90, data='2026-10-16', descricao='Barrinha de cereal',
          categoria='Alimentação', pago=True)),
    ('Assistente Financeiro, ontem ganhei R$ 25,00 com a venda de um determinado produto.',
     dict(tipo='Receita', valor=25.0, data='2026-10-15', descricao='Venda de um determinado produto',
          categoria='Vendas', pago=True)),
    # Valores falados por extenso
    ('gastei nove reais e noventa centavos com barrinha de cereal', dict(valor=9.90, descricao='Barrinha de cereal')),
    ('gastei nove e noventa no lanche', dict(valor=9.90, descricao='Lanche', categoria='Alimentação')),
    ('ganhei vinte e cinco reais vendendo bolo', dict(tipo='Receita', valor=25.0, categoria='Vendas')),
    ('paguei mil e quinhentos reais de aluguel', dict(valor=1500.0, descricao='Aluguel', categoria='Moradia')),
    ('paguei 1.250,00 de aluguel', dict(valor=1250.0)),
    ('gastei 15 reais no uber', dict(valor=15.0, descricao='Uber', categoria='Transporte')),
    ('gastei 15 no almoço', dict(valor=15.0, descricao='Almoço', categoria='Alimentação')),
    ('comprei 2 barrinhas por 10 reais', dict(valor=10.0, descricao='Comprei 2 barrinhas')),
    ('comprei duas barrinhas por 10', dict(valor=10.0)),
    ('gastei 50 centavos de bala', dict(valor=0.5)),
    ('gastei R$9.90 em café', dict(valor=9.90, descricao='Café')),
    # "um/uma" como artigo não vira número
    ('comprei uma pizza por 45 reais', dict(valor=45.0, descricao='Comprei uma pizza', categoria='Alimentação')),
    ('gastei um real de bala', dict(valor=1.0)),
    # Datas
    ('anteontem paguei 30 reais de farmácia', dict(data='2026-10-14', categoria='Saúde')),
    ('antes de ontem gastei 12 reais', dict(data='2026-10-14')),
    ('dia 5 paguei 200 reais de luz', dict(data='2026-10-05', valor=200.0, categoria='Moradia')),
    ('no dia 3 de setembro recebi 3000 reais de salário',
     dict(data='2026-09-03', tipo='Receita', valor=3000.0, categoria='Salário')),
    ('12/10 gastei 40 reais no mercado', dict(data='2026-10-12', valor=40.0)),
    ('na segunda gastei 20 reais de gasolina', dict(data='2026-10-12', categoria='Transporte')),
    ('sexta passada paguei 80 reais', dict(data='2026-10-09')),
    ('sábado gastei 10 reais', dict(data='2026-10-10', valor=10.0)),
    ('paguei a segunda parcela do carro 500 reais',
     dict(data='2026-10-16', valor=500.0, descricao='Segunda parcela do carro')),
    ('dia 31 de fevereiro gastei 10 reais', dict(data='2026-10-16')),
    # Pendentes / futuros
    ('conta de luz de 180 reais vence dia 25', dict(tipo='Despesa', valor=180.0, data='2026-10-25', pago=False)),
    ('amanhã vou pagar 90 reais de internet', dict(data='2026-10-17', pago=False, categoria='Moradia')),
    ('vou receber 300 reais de um freela', dict(tipo='Receita', pago=False)),
    # Informação faltando
    ('barrinha de cereal', dict(valor=None, tipo='Despesa')),
    ('gastei 10 reais', dict(valor=10.0, descricao='')),
    ('recebi o pagamento de 800 reais do cliente',
     dict(tipo='Receita', valor=800.0, descricao='Pagamento do cliente')),
    # Forma de pagamento
    ('gastei 30 reais no almoço no pix', dict(forma_pagamento='Pix', descricao='Almoço')),
    ('paguei 120 reais de gasolina no cartão de crédito',
     dict(forma_pagamento='Cartão de Crédito', descricao='Gasolina')),
    ('gastei 15 reais no débito com lanche', dict(forma_pagamento='Cartão de Débito', descricao='Lanche')),
    ('paguei 8 reais em dinheiro no pão', dict(forma_pagamento='Dinheiro', descricao='Pão')),
    ('recebi um pix de 50 reais do joão', dict(tipo='Receita', forma_pagamento='Pix', descricao='João')),
    ('gastei 9,90 com barrinha de cereal', dict(forma_pagamento='')),
    ('conta de luz no débito automático 180 reais', dict(forma_pagamento='')),
    ('comprei crédito de celular 20 reais', dict(forma_pagamento='')),
]


@pytest.mark.parametrize('frase,esperado', CASOS, ids=[c[0][:45] for c in CASOS])
def test_interpretar(frase, esperado):
    r = voz.interpretar(frase, HOJE, CATS)
    assert {k: r[k] for k in esperado} == esperado


CATS_COMPLETAS = {
    'Receita': ['Salário', 'Distribuição de Lucros', 'Aluguéis', 'Outras Receitas'],
    'Despesa': ['Moradia', 'Alimentação', 'Transporte', 'Educação', 'Saúde', 'Lazer', 'Outras Despesas'],
    'Investimento': ['Investimentos'],
}
CONTAS = [{'id': 1, 'nome': 'Conta Principal', 'banco': None},
          {'id': 2, 'nome': 'Nubank Cartão', 'banco': 'Nubank'},
          {'id': 3, 'nome': 'Santander', 'banco': 'Santander'},
          {'id': 4, 'nome': 'Carteira', 'banco': None}]

CASOS_COMPLETOS = [
    # Todos os campos de uma vez
    ('ontem gastei R$ 45 no mercado no pix pela conta Santander',
     dict(tipo='Despesa', valor=45.0, data='2026-10-15', descricao='Mercado', categoria='Alimentação',
          forma_pagamento='Pix', conta_id=3, pago=True, nao_identificados=[])),
    ('paguei 120 reais de gasolina no cartão de crédito do nubank',
     dict(categoria='Transporte', forma_pagamento='Cartão de Crédito', conta_id=2, descricao='Gasolina')),
    ('recebi 2000 reais de aluguel do inquilino na conta principal',
     dict(tipo='Receita', categoria='Aluguéis', conta_id=1)),
    # Investimento: tipo próprio, pelo verbo ou pela categoria
    ('apliquei 500 reais no tesouro direto',
     dict(tipo='Investimento', categoria='Investimentos', valor=500.0, descricao='Tesouro direto')),
    ('investi 1000 reais em CDB pelo nubank', dict(tipo='Investimento', categoria='Investimentos', conta_id=2)),
    ('fiz um aporte de 300 reais', dict(tipo='Investimento', valor=300.0)),
    ('tesouro direto 200 reais', dict(tipo='Investimento', categoria='Investimentos')),   # sem verbo
    ('recebi 50 reais de rendimento do investimento', dict(tipo='Receita')),              # 1º verbo vence
    ('recebi 3000 de distribuição de lucros', dict(tipo='Receita', categoria='Distribuição de Lucros')),
    # Tipo deduzido pela categoria quando não há "gastei/recebi"
    ('barrinha de cereal 9,90 no débito', dict(tipo='Despesa', categoria='Alimentação',
                                               forma_pagamento='Cartão de Débito')),
    # Ambíguo (aluguel pode ser Moradia ou Aluguéis): tipo e categoria ficam em branco
    ('aluguel 1500 reais', dict(tipo='', categoria='', valor=1500.0)),
    # Conta: sem preposição não conta; nome genérico não confunde
    ('comprei uma carteira de couro por 80 reais', dict(conta_id=None, descricao='Comprei uma carteira de couro')),
    ('gastei 20 reais em dinheiro da carteira', dict(conta_id=4, forma_pagamento='Dinheiro')),
    ('gastei 20 reais no almoço', dict(conta_id=None)),
    # Nada identificável além do texto
    ('isso aqui não é um lançamento', dict(tipo='', valor=None, categoria='', forma_pagamento='')),
]


@pytest.mark.parametrize('frase,esperado', CASOS_COMPLETOS, ids=[c[0][:45] for c in CASOS_COMPLETOS])
def test_interpretar_todos_os_campos(frase, esperado):
    r = voz.interpretar(frase, HOJE, CATS_COMPLETAS, CONTAS)
    assert {k: r[k] for k in esperado} == esperado


def test_conta_ambigua_fica_em_branco():
    contas = [{'id': 1, 'nome': 'Nubank Conta', 'banco': 'Nubank'},
              {'id': 2, 'nome': 'Nubank Cartão', 'banco': 'Nubank'}]
    assert voz.interpretar('gastei 10 reais no nubank', HOJE, CATS, contas)['conta_id'] is None
    assert voz.interpretar('gastei 10 reais no nubank cartão', HOJE, CATS, contas)['conta_id'] == 2


def test_aviso_lista_o_que_faltou():
    r = voz.interpretar('aluguel 1500 reais', HOJE, CATS_COMPLETAS, CONTAS)
    assert r['nao_identificados'] == ['tipo', 'categoria', 'forma de pagamento']
    assert r['avisos'] == ['Não identifiquei: tipo, categoria, forma de pagamento. Preencha abaixo, se quiser.']


def test_avisos_quando_falta_informacao():
    r = voz.interpretar('barrinha de cereal', HOJE, CATS)
    assert any('valor' in a for a in r['avisos'])
    r = voz.interpretar('dia 31 de fevereiro gastei 10 reais', HOJE, CATS)
    assert any('data' in a for a in r['avisos'])


@pytest.mark.parametrize('descricao,esperado', [
    ('RVA2I18-ECOVIAS RAPOSO CASTELLO SP280 1', 'Transporte'),
    ('RVA2I18-ECOPISTAS AYRTON SENNA E CARVALH', 'Transporte'),
    ('PADARIA CENTRAL', 'Alimentação'),
    ('RVA2I18-IGUATEMI SAO PAULO AVENIDA BRIG', ''),
])
def test_sugerir_categoria_extrato(descricao, esperado):
    assert voz.sugerir_categoria(descricao, CATS['Despesa']) == esperado


@pytest.mark.parametrize('descricao,esperado', [
    ('Pix recebido de FULANO', 'Pix'),
    ('PIX ENVIADO MARIA', 'Pix'),
    ('COMPRA CARTAO DEBITO PADARIA', 'Cartão de Débito'),
    ('COMPRA CARTAO CREDITO LOJA', 'Cartão de Crédito'),
    ('SAQUE 24H', 'Dinheiro'),
    ('RVA2I18-ECOVIAS RAPOSO', ''),
    ('DEBITO AUTOMATICO SABESP', ''),
])
def test_sugerir_forma_extrato(descricao, esperado):
    assert voz.sugerir_forma_pagamento(descricao) == esperado
