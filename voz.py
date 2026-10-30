"""Interpretação de comandos de voz (pt-BR) em lançamentos, só com regras.

Ex.: "Assistente Financeiro, ontem ganhei R$ 25,00 com a venda de um produto"
  -> {tipo: Receita, valor: 25.0, data: ontem, descricao: "Venda de um produto", ...}
"""
import re
import unicodedata
from datetime import date, timedelta


def _sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


_ACENTOS = {'a': '[aáàâã]', 'e': '[eéê]', 'i': '[ií]', 'o': '[oóôõ]', 'u': '[uúü]', 'c': '[cç]'}

def _acc(palavra):
    """Regex que casa a palavra com ou sem acentos ("tres" casa "três")."""
    return ''.join(_ACENTOS.get(ch, re.escape(ch)) for ch in palavra)

def _alt(palavras):
    """Alternativa de palavras inteiras, mais longas primeiro."""
    return r'\b(?:' + '|'.join(_acc(p) for p in sorted(palavras, key=len, reverse=True)) + r')\b'


# ── Números por extenso ───────────────────────────────────────────────────────
_NUMEROS = {
    'zero': 0, 'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5,
    'seis': 6, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12, 'treze': 13,
    'quatorze': 14, 'catorze': 14, 'quinze': 15, 'dezesseis': 16, 'dezessete': 17, 'dezoito': 18,
    'dezenove': 19, 'vinte': 20, 'trinta': 30, 'quarenta': 40, 'cinquenta': 50, 'sessenta': 60,
    'setenta': 70, 'oitenta': 80, 'noventa': 90, 'cem': 100, 'cento': 100, 'duzentos': 200,
    'duzentas': 200, 'trezentos': 300, 'trezentas': 300, 'quatrocentos': 400, 'quatrocentas': 400,
    'quinhentos': 500, 'quinhentas': 500, 'seiscentos': 600, 'seiscentas': 600,
    'setecentos': 700, 'setecentas': 700, 'oitocentos': 800, 'oitocentas': 800,
    'novecentos': 900, 'novecentas': 900, 'mil': 1000,
}
_RE_PALAVRA_NUM = _alt(_NUMEROS)
_RE_SEQ_NUM = re.compile(rf'{_RE_PALAVRA_NUM}(?:\s+(?:e\s+)?{_RE_PALAVRA_NUM})*', re.I)

def _ordem(v):
    """Menor valor que ainda pode ser somado depois de v ("vinte e cinco", "cento e dez")."""
    if v >= 1000: return 1000
    if v >= 100:  return 100
    if v >= 20 and v % 10 == 0: return 10
    return 1

def _extenso_para_digitos(t):
    """'nove reais e noventa centavos' -> '9 reais e 90 centavos'; 'nove e noventa' -> '9 e 90'.
    Um 'um/uma' isolado só vira número se vier antes de real/reais/centavos/mil (senão é artigo)."""
    def troca(m):
        palavras = [_sem_acento(w) for w in m.group(0).split() if w != 'e']
        depois = t[m.end():].lstrip()
        if (len(palavras) == 1 and palavras[0] in ('um', 'uma')
                and not re.match(r'(?:reais|real|centavos?)\b', depois)):
            return m.group(0)
        grupos, atual, ultimo = [], None, None
        for w in palavras:
            v = _NUMEROS[w]
            if v == 1000:
                atual, ultimo = (atual or 1) * 1000, 1000
            elif atual is None:
                atual, ultimo = v, v
            elif v < _ordem(ultimo):
                atual, ultimo = atual + v, v
            else:
                grupos.append(atual)
                atual, ultimo = v, v
        grupos.append(atual)
        return ' e '.join(str(g) for g in grupos)
    return _RE_SEQ_NUM.sub(troca, t)


# ── Valor ─────────────────────────────────────────────────────────────────────
_NUM = r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+,\d{1,2}|\d+\.\d{1,2}|\d+'

def _num(s):
    if ',' in s:
        return float(s.replace('.', '').replace(',', '.'))
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', s):
        return float(s.replace('.', ''))
    return float(s)

_PADROES_VALOR = [
    # R$ 9,90 / R$ 9 reais e 90 centavos
    (re.compile(rf'r\$\s*({_NUM})(?:\s*(?:reais|real))?(?:\s*e\s*(\d{{1,2}})\s*centavos?)?'), 'reais'),
    # 9,90 reais / 9 reais e 90 (centavos)
    (re.compile(rf'(?<![\d,.])({_NUM})\s*(?:reais|real)\b(?:\s*e\s*(\d{{1,2}})(?:\s*centavos?)?\b)?'), 'reais'),
    # 90 centavos
    (re.compile(r'(?<![\d,.])(\d{1,2})\s*centavos?\b'), 'centavos'),
    # "9 e 90" (forma falada de 9,90)
    (re.compile(r'(?<![\d,./])(\d+)\s+e\s+(\d{2})(?![\d,./])'), 'reais'),
]
_RE_NUM_SOLTO = re.compile(rf'(?<![\d,./])({_NUM})(?![\d,./])')

def _extrair_valor(t):
    for rx, unidade in _PADROES_VALOR:
        m = rx.search(t)
        if m:
            if unidade == 'centavos':
                valor = int(m.group(1)) / 100
            else:
                valor = _num(m.group(1))
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    valor += int(m.group(2)) / 100
            return round(valor, 2), m.span()
    # Número solto: usa o último ("comprei 2 barrinhas por 10" -> 10)
    soltos = list(_RE_NUM_SOLTO.finditer(t))
    if soltos:
        m = soltos[-1]
        return round(_num(m.group(1)), 2), m.span()
    return None, None


# ── Data ──────────────────────────────────────────────────────────────────────
_MESES = ['janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho',
          'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
_RE_MES = '(' + '|'.join(_acc(m) for m in _MESES) + ')'
_DIAS_SEMANA = {'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6}

_PADROES_DATA = [
    ('relativo', re.compile(rf'\b(?:{_acc("antes de ontem")}|{_acc("anteontem")})\b'), -2),
    ('relativo', re.compile(r'\bontem\b'), -1),
    ('relativo', re.compile(rf'\b{_acc("amanha")}\b'), 1),
    ('relativo', re.compile(r'\bhoje\b'), 0),
    ('dia_mes', re.compile(rf'\b(?:(?:no|em)\s+)?(?:dia\s+)?(\d{{1,2}})\s+de\s+{_RE_MES}(?:\s+de\s+(\d{{4}}))?\b'), None),
    ('barra',   re.compile(r'\b(?:(?:no|em)\s+)?(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b'), None),
    ('dia',     re.compile(r'\b(?:(?:no|em)\s+)?dia\s+(\d{1,2})\b'), None),
    ('semana',  re.compile(
        r'\b(?:(?:n[ao]|em)\s+)?(?:(?:[uú]ltim[ao]|passad[ao])\s+)?'
        rf'({_acc("segunda")}|{_acc("terca")}|{_acc("quarta")}|{_acc("quinta")}|{_acc("sexta")}|{_acc("sabado")}|{_acc("domingo")})'
        r'(?:[\s-]+feira)?(?:\s+passad[ao])?\b'), None),
]

def _extrair_data(t, hoje):
    """Retorna (data, span, aviso)."""
    for tipo, rx, delta in _PADROES_DATA:
        m = rx.search(t)
        if not m:
            continue
        try:
            if tipo == 'relativo':
                return hoje + timedelta(days=delta), m.span(), None
            if tipo == 'dia_mes':
                mes = _MESES.index(_sem_acento(m.group(2))) + 1
                ano = int(m.group(3)) if m.group(3) else hoje.year
                d = date(ano, mes, int(m.group(1)))
                if not m.group(3) and d > hoje + timedelta(days=60):
                    d = d.replace(year=ano - 1)   # "28 de dezembro" dito em janeiro
                return d, m.span(), None
            if tipo == 'barra':
                ano = m.group(3)
                ano = (2000 + int(ano) if len(ano) == 2 else int(ano)) if ano else hoje.year
                return date(ano, int(m.group(2)), int(m.group(1))), m.span(), None
            if tipo == 'dia':
                return hoje.replace(day=int(m.group(1))), m.span(), None
            if tipo == 'semana':
                # Só é data com contexto ("na segunda", "sexta-feira", "sábado passado") ou no
                # início da frase ("sábado gastei..."); "a segunda parcela" não é dia da semana.
                if (t[:m.start()].strip()
                        and not re.search(r'^\s*(?:n[ao]|em|[uú]ltim|passad)|feira|passad', m.group(0))):
                    continue
                alvo = _DIAS_SEMANA[_sem_acento(m.group(1))]
                atras = (hoje.weekday() - alvo) % 7
                if atras == 0 and re.search(r'passad|[uú]ltim', m.group(0)):
                    atras = 7
                return hoje - timedelta(days=atras), m.span(), None
        except ValueError:
            return hoje, m.span(), f'Não entendi a data "{m.group(0).strip()}"; usei hoje.'
    return hoje, None, None


# ── Tipo, situação e descrição ────────────────────────────────────────────────
_PALAVRAS_RECEITA = ['ganhei', 'ganhamos', 'ganho', 'recebi', 'recebemos', 'recebimento', 'receita',
                     'entrada', 'vendi', 'vendemos', 'venda', 'faturei', 'lucrei', 'lucro', 'rendimento',
                     'rendeu', 'reembolso', 'me pagaram', 'me pagou', 'me deram', 'salario',
                     'vou receber', 'a receber', 'pix recebido']
_PALAVRAS_DESPESA = ['gastei', 'gastamos', 'gasto', 'gastos', 'paguei', 'pagamos', 'pagamento',
                     'comprei', 'compramos', 'compra', 'despesa', 'saida', 'conta de', 'boleto',
                     'fatura', 'vou pagar', 'a pagar', 'tenho que pagar', 'preciso pagar']
_RE_RECEITA = re.compile(_alt(_PALAVRAS_RECEITA))
_RE_DESPESA = re.compile(_alt(_PALAVRAS_DESPESA))

# Removidas da descrição (só indicam o tipo/situação, não o que foi)
_RE_RUIDO = re.compile(_alt([
    'tive um gasto', 'tive uma despesa', 'tive um ganho', 'tive uma receita', 'tive uma entrada',
    'gastei', 'gastamos', 'gasto', 'gastos', 'paguei', 'pagamos', 'ganhei', 'ganhamos', 'ganho',
    'recebi', 'recebemos', 'lucrei', 'faturei', 'despesa', 'receita', 'entrada', 'saida',
    'me pagaram', 'me pagou', 'me deram', 'vou pagar', 'tenho que pagar', 'preciso pagar',
    'a pagar', 'vou receber', 'a receber', 'pendente', 'que vence', 'vence', 'agendado', 'agendada',
    'reais', 'real', 'centavos', 'centavo',
]))

_RE_PENDENTE = re.compile(_alt(['a pagar', 'vou pagar', 'tenho que pagar', 'preciso pagar', 'pendente',
                                'a receber', 'vou receber', 'vence', 'vencimento', 'agendado', 'agendada']))

_CONECTIVOS = {'com', 'de', 'do', 'da', 'dos', 'das', 'no', 'na', 'nos', 'nas', 'em', 'um', 'uma', 'uns',
               'umas', 'num', 'numa', 'o', 'a', 'os', 'as', 'ao', 'aos', 'pra', 'para', 'pro', 'pela',
               'pelo', 'por', 'e', 'que', 'foi', 'referente', 'meu', 'minha', 'r$', 'reais', 'real'}

# Palavras que sugerem uma categoria (só usadas se o usuário tiver a categoria com esse nome)
_SUGESTOES = {
    'alimentacao': ['comida', 'lanche', 'almoco', 'jantar', 'cafe', 'padaria', 'pao', 'restaurante',
                    'mercado', 'supermercado', 'feira', 'hortifruti', 'acougue', 'ifood', 'pizza',
                    'barrinha', 'cereal', 'fruta', 'sorvete', 'refeicao', 'marmita', 'salgado', 'doce',
                    'lanchonete', 'pizzaria', 'churrascaria', 'mcdonalds', 'burger king', 'subway',
                    'starbucks', 'carrefour', 'assai', 'atacadao', 'pao de acucar'],
    'mercado':     ['mercado', 'supermercado', 'compras do mes', 'atacadao'],
    'moradia':     ['aluguel', 'condominio', 'luz', 'energia', 'agua', 'gas', 'internet', 'iptu',
                    'reforma', 'casa', 'apartamento'],
    'pedagio':     ['pedagio', 'ecovias', 'ecopistas', 'riosp', 'ccr', 'autoban', 'arteris', 'viaoeste',
                    'rodoanel', 'sem parar', 'conectcar', 'veloe'],
    'transporte':  ['uber', '99app', '99pop', '99 pop', '99 taxi', 'taxi', 'gasolina', 'combustivel',
                    'etanol', 'onibus', 'metro', 'estacionamento', 'pedagio', 'passagem', 'carro',
                    'oficina', 'ipva', 'ecovias', 'ecopistas', 'riosp', 'ccr', 'autoban', 'arteris',
                    'viaoeste', 'rodoanel', 'sem parar', 'conectcar', 'veloe', 'posto', 'shell',
                    'ipiranga', 'petrobras'],
    'saude':       ['farmacia', 'drogaria', 'drogasil', 'droga raia', 'remedio', 'medico', 'consulta',
                    'exame', 'dentista', 'plano de saude', 'hospital', 'academia'],
    'educacao':    ['escola', 'curso', 'livro', 'faculdade', 'mensalidade', 'material escolar'],
    'lazer':       ['cinema', 'show', 'viagem', 'bar', 'passeio', 'streaming', 'netflix', 'spotify', 'jogo'],
    'vestuario':   ['roupa', 'sapato', 'tenis', 'camisa', 'calca', 'vestido'],
    'salario':     ['salario', 'pagamento do mes', 'holerite'],
    'vendas':      ['venda', 'vendi', 'vendemos', 'vendendo', 'vendas'],
    'freelance':   ['freela', 'freelance', 'projeto', 'servico'],
}

def _sugerir_categoria(texto_norm, nomes):
    """Escolhe entre as categorias do usuário (do tipo certo) a que melhor casa com a frase."""
    por_norm = {_sem_acento(n.lower()): n for n in nomes}
    # 1) o nome da categoria aparece na frase (o mais longo vence)
    for norm in sorted(por_norm, key=len, reverse=True):
        if re.search(rf'\b{re.escape(norm)}\b', texto_norm):
            return por_norm[norm]
    # 2) palavras típicas da categoria
    for norm, palavras in _SUGESTOES.items():
        if norm in por_norm and any(re.search(rf'\b{re.escape(p)}\b', texto_norm) for p in palavras):
            return por_norm[norm]
    return ''

def sugerir_categoria(texto, nomes):
    """Sugere uma categoria para um texto livre (ex.: descrição de extrato); '' se nenhuma servir."""
    return _sugerir_categoria(_sem_acento((texto or '').lower()), nomes)

def _limpar_descricao(t):
    palavras = t.split()
    while palavras and _sem_acento(palavras[0]) in _CONECTIVOS:
        palavras.pop(0)
    while palavras and _sem_acento(palavras[-1]) in _CONECTIVOS:
        palavras.pop()
    desc = ' '.join(palavras)
    return (desc[:1].upper() + desc[1:])[:200]

def _remover(t, span, conectivo_antes=False):
    """Remove o trecho; com conectivo_antes, leva junto um "de/por/no valor de" solto antes dele
    ("pagamento de 800 reais do cliente" -> "pagamento do cliente")."""
    if not span:
        return t
    antes = t[:span[0]]
    if conectivo_antes:
        antes = re.sub(r'\b(?:no valor de|de|por)\s*$', '', antes)
    return antes + ' ' + t[span[1]:]


def interpretar(texto, hoje, categorias):
    """texto: frase ouvida; hoje: date local; categorias: {'Receita': [...], 'Despesa': [...]}.
    Retorna dict com tipo, valor (ou None), data (ISO), descricao, categoria, pago e avisos."""
    t = ' ' + (texto or '').lower() + ' '
    # Pontuação vira espaço, exceto vírgula/ponto entre dígitos ("9,90", "1.250") e a barra das datas
    t = re.sub(r'(?<!\d)[.,]|[.,](?!\d)', ' ', t)
    t = re.sub(r'[;:!?"“”()]', ' ', t)
    t = re.sub(rf'\b{_acc("assistente financeiro")}\b', ' ', t)
    t = _extenso_para_digitos(re.sub(r'\s+', ' ', t))
    avisos = []

    data_l, span, aviso = _extrair_data(t, hoje)
    t = _remover(t, span)
    if aviso:
        avisos.append(aviso)

    valor, span = _extrair_valor(t)
    t = _remover(t, span, conectivo_antes=True)
    if valor is None:
        avisos.append('Não identifiquei o valor. Preencha abaixo.')

    rec, desp = _RE_RECEITA.search(t), _RE_DESPESA.search(t)
    if rec and (not desp or rec.start() < desp.start()):
        tipo = 'Receita'
    else:
        tipo = 'Despesa'
        if not desp:
            avisos.append('Não ficou claro se é gasto ou ganho; considerei gasto.')

    pago = not (_RE_PENDENTE.search(t) or data_l > hoje)
    texto_norm = _sem_acento(t)
    categoria = _sugerir_categoria(texto_norm, categorias.get(tipo, []))

    descricao = _limpar_descricao(re.sub(r'\s+', ' ', _RE_RUIDO.sub(' ', t).replace('r$', ' ')))
    if not descricao:
        descricao = 'Lançamento por voz'
        avisos.append('Não identifiquei a descrição. Ajuste abaixo.')

    return {'tipo': tipo, 'valor': valor, 'data': data_l.isoformat(), 'descricao': descricao,
            'categoria': categoria, 'pago': pago, 'avisos': avisos}
