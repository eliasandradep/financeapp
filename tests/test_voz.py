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
    ('gastei 10 reais', dict(valor=10.0, descricao='Lançamento por voz')),
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
