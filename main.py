import os, re, csv, io, datetime, unicodedata, asyncio
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, TypeHandler, ApplicationHandlerStop,
)
from supabase import create_client

TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PORT = int(os.environ.get("PORT", 10000))
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
WEBHOOK_URL = BASE_URL + "/" + TOKEN
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TZ = ZoneInfo("America/Sao_Paulo")
MESES = {"janeiro": "01", "fevereiro": "02", "marco": "03", "março": "03", "abril": "04", "maio": "05", "junho": "06", "julho": "07", "agosto": "08", "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12"}

# Palavras de forma de pagamento (removidas da descrição)
PAG_RE = r"\b(cartao|cartão|credito|crédito|sodexo|vale|pix|dinheiro|debito|débito)\b"
# Número com R$ opcional. O grupo 1 é só o número.
NUM_RE = r"(?:R\$\s*)?(\d[\d.,]*)"

# ---------- CATEGORIAS ----------
CATEGORIAS = {
    "Mercado": "🛒", "Alimentação": "🍽️", "Combustível": "⛽", "Manutenção": "🔧",
    "Transporte": "🚌", "Saúde": "💊", "Lazer": "🎉", "Compras": "👕",
    "Casa": "🏠", "Educação": "📚", "Viagem": "✈️", "Outros": "📦",
}
CAT_LISTA = list(CATEGORIAS.keys())
CORES = {
    "Mercado": "#2E7D32", "Alimentação": "#F9A825", "Combustível": "#EF6C00", "Manutenção": "#6D4C41",
    "Transporte": "#1565C0", "Saúde": "#C62828", "Lazer": "#8E24AA", "Compras": "#EC407A",
    "Casa": "#00897B", "Educação": "#3949AB", "Viagem": "#00ACC1", "Outros": "#757575", "Sem categoria": "#BDBDBD",
}
# Palavras que classificam sozinhas (sem acento/maiúscula; plural é aceito automaticamente)
PALAVRAS_CATEGORIA = {
    "Mercado": ["mercado", "supermercado", "feira", "acougue", "hortifruti", "atacadao", "sacolao"],
    "Alimentação": ["almoco", "jantar", "comida", "cafe", "lanche", "padaria", "restaurante", "pizza", "ifood", "marmita", "sorvete", "acai", "pastel", "pasteis", "hamburguer", "salgado", "refeicao", "pao", "paes"],
    "Combustível": ["combustivel", "gasolina", "gnv", "etanol", "alcool", "diesel", "posto", "abastecimento"],
    "Manutenção": ["manutencao", "oficina", "mecanico", "oleo", "pneu", "revisao", "peca", "alinhamento", "balanceamento", "bateria", "freio", "conserto"],
    "Transporte": ["uber", "99", "onibus", "passagem", "pedagio", "estacionamento", "metro", "taxi", "bilhete"],
    "Saúde": ["farmacia", "remedio", "consulta", "exame", "dentista", "medico", "hospital"],
    "Lazer": ["cinema", "bar", "passeio", "show", "festa", "jogo", "netflix", "spotify", "ingresso", "balada"],
    "Compras": ["roupa", "sapato", "tenis", "shopping", "camisa", "calca", "bermuda", "bolsa", "loja"],
    "Casa": ["gas", "botijao", "reforma", "limpeza", "movel", "moveis", "lampada", "ferramenta", "tinta"],
    "Educação": ["curso", "escola", "faculdade", "livro", "matricula", "apostila"],
    "Viagem": ["viagem", "hotel", "hospedagem", "pousada", "airbnb", "hostel", "excursao", "pacote"],
}

# ---------- SEGURANÇA: só os IDs liberados ----------
ALLOWED_IDS = set()
_raw = os.environ.get("ALLOWED_USER_IDS", "")
for _x in _raw.replace(";", ",").split(","):
    _x = _x.strip()
    if _x.isdigit():
        ALLOWED_IDS.add(int(_x))


async def so_permitidos(update, context):
    # Fechado por padrão: se o ID não estiver na lista (ou a lista estiver vazia), ignora.
    uid = update.effective_user.id if update.effective_user else None
    if uid not in ALLOWED_IDS:
        raise ApplicationHandlerStop


def escape_md(s):
    # Markdown simples do Telegram: só _ * ` [ precisam de barra
    return re.sub(r"([_*`\[])", r"\\\1", str(s))


# ---------- DATAS ----------
def hoje_sp():
    return datetime.datetime.now(TZ).date()


def mes_atual_str():
    return hoje_sp().strftime("%Y-%m")


def mes_anterior_str():
    h = hoje_sp()
    ano = h.year
    mes = h.month - 1
    if mes == 0:
        mes = 12
        ano -= 1
    return f"{ano}-{mes:02d}"


def mes_de(g):
    raw = str(g.get("data") or g.get("created_at") or "")
    if not raw:
        return ""
    if len(raw) == 10:
        # Só data (AAAA-MM-DD): não converte fuso
        return raw[:7]
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(TZ).strftime("%Y-%m")
    except Exception as e:
        print(f"Erro mes_de: {e}")
        return raw[:7]


def quando_de(g):
    # Data/hora do lançamento no fuso de São Paulo (ou None)
    raw = str(g.get("data") or g.get("created_at") or "")
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.datetime.fromisoformat(raw).replace(tzinfo=TZ)
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        return None


def data_curta(g, ano=False):
    # Só a data, ex.: 15/11 (ou 15/11/26 com ano), sem horário
    dt = quando_de(g)
    if not dt:
        return ""
    return dt.strftime("%d/%m/%y" if ano else "%d/%m")


def parse_mes(txt):
    txt = txt.lower()
    m = re.search(r"(\d{4})-(\d{1,2})", txt)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})/(\d{4})", txt)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    for nome, num in MESES.items():
        if nome in txt:
            ano = str(hoje_sp().year)
            y = re.search(r"20\d{2}", txt)
            if y:
                ano = y.group(0)
            return f"{ano}-{num}"
    m = re.search(r"(\d{1,2})", txt)
    if m:
        return f"{hoje_sp().year}-{int(m.group(1)):02d}"
    return None


# ---------- SALDO E VIRADA DE MÊS ----------
def get_saldo():
    try:
        r = supabase.table("saldo_config").select("valor").eq("id", 1).execute()
        if not r.data:
            supabase.table("saldo_config").insert({"id": 1, "valor": 0}).execute()
            return 0.0
        return float(r.data[0]["valor"])
    except Exception as e:
        print(f"Erro get_saldo: {e}")
        return 0.0


def set_saldo(v):
    try:
        supabase.table("saldo_config").upsert({"id": 1, "valor": v}).execute()
    except Exception as e:
        print(f"Erro set_saldo: {e}")


def get_ultimo_mes_visto():
    try:
        r = supabase.table("saldo_config").select("valor").eq("id", 3).execute()
        if not r.data:
            return None
        s = str(int(float(r.data[0]["valor"])))
        return f"{s[:4]}-{s[4:6]}" if len(s) == 6 else None
    except Exception as e:
        print(f"Erro get_ultimo_mes_visto: {e}")
        return None


def set_ultimo_mes_visto():
    try:
        v = int(hoje_sp().strftime("%Y%m"))
        supabase.table("saldo_config").upsert({"id": 3, "valor": v}).execute()
    except Exception as e:
        print(f"Erro set_ultimo_mes_visto: {e}")


async def checar_virada(update):
    atual = mes_atual_str()
    ultimo = get_ultimo_mes_visto()
    if ultimo is None:
        set_ultimo_mes_visto()
        return False
    if ultimo == atual:
        return False
    set_ultimo_mes_visto()
    return ultimo


# ---------- LEITURA DE VALORES E TEXTOS ----------
def parse_valor(s):
    # Aceita 35 | 35,5 | 1.500 | 1.500,50 | R$ 1500
    s = str(s).replace("R$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s)


def pega_num(s):
    ms = list(re.finditer(NUM_RE, s))
    if not ms:
        return None
    try:
        return parse_valor(ms[-1].group(1).rstrip(".,"))
    except ValueError:
        return None


def pega_desc(s, rem=""):
    d = re.sub(rem, "", s, flags=re.IGNORECASE) if rem else s
    ms = list(re.finditer(NUM_RE, d))
    if ms:
        m = ms[-1]
        d = d[:m.start()] + " " + d[m.end():]
    d = re.sub(r"\s+", " ", d).strip(" ,-")
    return d.title() if d else "Item"


def parse_linha(linha, rem=""):
    v = pega_num(linha)
    if v is None:
        return None
    return pega_desc(linha, rem), v


def limpar_pagamento(txt):
    return re.sub(PAG_RE, "", txt, flags=re.IGNORECASE)


def detectar_tipo(txt):
    t = txt.lower()
    if re.search(r"\b(cartao|cartão|credito|crédito)\b", t):
        return "cartao"
    if re.search(r"\b(sodexo|vale)\b", t):
        return "sodexo"
    return "dinheiro"


DATA_RE = re.compile(r"(?<![\d/.,])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")
PAL_DATA_RE = re.compile(r"\b(anteontem|ontem|hoje)\b", re.IGNORECASE)


def extrai_data(txt):
    # Tira a data do texto. Devolve (texto sem a data, data | None se não tem | False se inválida)
    hoje = hoje_sp()
    m = PAL_DATA_RE.search(txt)
    if m:
        resto = txt[:m.start()] + " " + txt[m.end():]
        palavra = m.group(1).lower()
        if palavra == "hoje":
            return resto, None
        return resto, hoje - datetime.timedelta(days=2 if palavra == "anteontem" else 1)
    m = DATA_RE.search(txt)
    if not m:
        return txt, None
    resto = txt[:m.start()] + " " + txt[m.end():]
    dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if ano:
            a = int(ano)
            if a < 100:
                a += 2000
            d = datetime.date(a, mes, dia)
        else:
            d = datetime.date(hoje.year, mes, dia)
            if d > hoje:
                d = datetime.date(hoje.year - 1, mes, dia)
    except ValueError:
        return resto, False
    return resto, d


_COLS_DATA = None
_DATA_E_DATE = False  # True quando a coluna "data" é do tipo date (guarda só AAAA-MM-DD)


def colunas_data():
    # Descobre qual coluna de data a tabela gastos tem: data e/ou created_at
    global _COLS_DATA, _DATA_E_DATE
    if _COLS_DATA:
        return _COLS_DATA
    try:
        r = supabase.table("gastos").select("*").limit(1).execute().data or []
        if r:
            cols = [c for c in ("data", "created_at") if c in r[0]]
            if cols:
                _COLS_DATA = cols
                if "data" in cols:
                    # Valor com 10 caracteres (AAAA-MM-DD) = coluna do tipo date. Com hora, ou vazio, usa o timestamp (serve nos dois tipos)
                    _DATA_E_DATE = len(str(r[0].get("data") or "")) == 10
                return cols
    except Exception as e:
        print(f"Erro ao descobrir a coluna de data: {e}")
    return ["created_at"]


def tentar_com_data(dados, dt, executar):
    # Executa (insert/update) gravando a data na coluna certa; se a primeira tentativa falhar, tenta as outras
    global _COLS_DATA
    if not dt:
        return executar(dados)
    iso = iso_data(dt)
    data_so = dt.strftime("%Y-%m-%d")
    opcoes, ultimo = [], None
    for cols in (colunas_data(), ["data"], ["created_at"], ["data", "created_at"]):
        if cols not in opcoes:
            opcoes.append(cols)
    for cols in opcoes:
        try:
            # Coluna "data" do tipo date recebe só o dia; as demais recebem o timestamp completo
            valores = {c: (data_so if (c == "data" and _DATA_E_DATE) else iso) for c in cols}
            r = executar({**dados, **valores})
            _COLS_DATA = cols
            return r
        except Exception as e:
            print(f"Erro ao gravar a data em {cols}: {e}")
            ultimo = e
    raise ultimo


def iso_data(d):
    # Meio-dia em São Paulo, pra a data não escorregar de dia por causa do fuso
    dt = datetime.datetime(d.year, d.month, d.day, 12, 0, tzinfo=TZ)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


TAG_RE = re.compile(r"(?<!\w)#(\w+)")


def extrai_categoria(txt):
    # Tira a #categoria do texto. Devolve (texto sem a tag, nome da categoria | None se não tem | False se não existe)
    m = TAG_RE.search(txt)
    if not m:
        return txt, None
    resto = txt[:m.start()] + " " + txt[m.end():]
    tag = normalizar(m.group(1))
    nomes = {normalizar(n): n for n in CATEGORIAS}
    if tag in nomes:
        return resto, nomes[tag]
    cand = [n for k, n in nomes.items() if len(tag) >= 3 and k.startswith(tag)]
    if len(cand) == 1:
        return resto, cand[0]
    return resto, False


def explica_falha(linha):
    _, dt = extrai_data(linha)
    if dt is False:
        return "data inválida"
    _, cat = extrai_categoria(linha)
    if cat is False:
        return "categoria desconhecida, use por exemplo #mercado ou #viagem"
    return "faltou o valor"


def parse_linha_data(linha, rem=""):
    # Como parse_linha, mas entende a data e a #categoria. Devolve (descrição, valor, data|None, categoria|None) ou None
    limpo, dt = extrai_data(linha)
    if dt is False:
        return None
    limpo, cat = extrai_categoria(limpo)
    if cat is False:
        return None
    r = parse_linha(limpo, rem)
    if r is None:
        return None
    return r[0], r[1], dt, cat


def processar_despesas(texto):
    ok = 0
    for linha in re.split(r"[\n;]", texto):
        linha = re.sub(r"^\s*/?despesas?(@\w+)?\s*", "", linha.strip(), flags=re.IGNORECASE)
        if not linha:
            continue
        linha, _ = extrai_data(linha)
        r = parse_linha(linha)
        if r is None:
            continue
        d, v = r
        if d == "Item":
            d = "Despesa"
        supabase.table("despesas").insert({"descricao": d, "valor": v, "status": "pendente"}).execute()
        ok += 1
    return ok


# ---------- GASTOS POR PERÍODO (filtro no Supabase) ----------
def gastos_entre(mes_ini, mes_fim):
    # Busca só o período (com 1 dia de folga) e confere o mês exato no Python
    try:
        a1, m1 = int(mes_ini[:4]), int(mes_ini[5:7])
        a2, m2 = int(mes_fim[:4]), int(mes_fim[5:7])
        ini = datetime.datetime(a1, m1, 1, tzinfo=TZ) - datetime.timedelta(days=1)
        prox_ano = a2 + 1 if m2 == 12 else a2
        prox_mes = 1 if m2 == 12 else m2 + 1
        fim = datetime.datetime(prox_ano, prox_mes, 1, tzinfo=TZ) + datetime.timedelta(days=1)
        f = "%Y-%m-%dT%H:%M:%SZ"
        r = (
            supabase.table("gastos").select("*")
            .gte(colunas_data()[0], ini.astimezone(datetime.timezone.utc).strftime(f))
            .lt(colunas_data()[0], fim.astimezone(datetime.timezone.utc).strftime(f))
            .order("id")
            .execute().data or []
        )
    except Exception as e:
        print(f"Erro gastos_entre (usando busca completa): {e}")
        r = supabase.table("gastos").select("*").order("id").execute().data or []
    return [x for x in r if mes_ini <= mes_de(x) <= mes_fim]


def gastos_do_mes(fm):
    return gastos_entre(fm, fm)


def lista_meses(fim, n):
    ano, mes = int(fim[:4]), int(fim[5:7])
    out = []
    for _ in range(n):
        out.append(f"{ano}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1
    return out[::-1]


# ---------- CATEGORIAS: detectar, aprender, perguntar ----------
def normalizar(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


_IDX = {}
for _nome, _lista in PALAVRAS_CATEGORIA.items():
    for _p in _lista:
        _k = normalizar(_p)
        for _forma in (_k, _k + "s", _k + "es"):
            _IDX.setdefault(_forma, _nome)

_APRENDIDAS = None


def aprendidas():
    global _APRENDIDAS
    if _APRENDIDAS is None:
        try:
            r = supabase.table("categoria_palavras").select("*").execute().data or []
            _APRENDIDAS = {x["palavra"]: x["categoria"] for x in r}
        except Exception as e:
            print(f"Erro ao carregar categorias aprendidas: {e}")
            return {}
    return _APRENDIDAS


def aprender(desc, nome):
    chave = normalizar(desc)
    if not chave:
        return
    try:
        supabase.table("categoria_palavras").upsert({"palavra": chave, "categoria": nome}).execute()
        aprendidas()[chave] = nome
    except Exception as e:
        print(f"Erro ao aprender categoria: {e}")


def detectar_categoria(desc):
    n = normalizar(desc)
    ap = aprendidas()
    if ap.get(n) in CATEGORIAS:
        return ap[n]
    tokens = re.findall(r"\w+", n)
    for t in tokens:
        if ap.get(t) in CATEGORIAS:
            return ap[t]
    for t in tokens:
        if t in _IDX:
            return _IDX[t]
    return None


def salvar_gasto(desc, valor, tipo, data=None, forcada=None):
    # Salva o gasto já com a categoria (a #escolhida ou a reconhecida). Devolve (id, categoria)
    cat = forcada or detectar_categoria(desc)
    dados = {"descricao": desc, "valor": valor, "tipo": tipo}
    if cat:
        dados["categoria"] = cat

    def inserir(d):
        return supabase.table("gastos").insert(d).execute()

    try:
        r = tentar_com_data(dados, data, inserir)
    except Exception as e:
        if "categoria" not in dados:
            raise
        print(f"Erro ao salvar com categoria (a coluna existe?): {e}")
        dados.pop("categoria")
        cat = None
        r = tentar_com_data(dados, data, inserir)
    gid = r.data[0]["id"] if r.data else None
    return gid, cat


def linha_recibo(d, v, cat, tipo=None, data=None):
    emoji = CATEGORIAS.get(cat, "❔")
    sufixo = f" ({tipo})" if tipo else ""
    quando = f" 📅 {data.strftime('%d/%m')}" if data else ""
    return f"{emoji} {d} - R$ {v:.2f}{sufixo} → {cat or 'sem categoria'}{quando}"


def teclado_categorias(gid):
    botoes = [InlineKeyboardButton(f"{CATEGORIAS[n]} {n}", callback_data=f"cat:{gid}:{i}") for i, n in enumerate(CAT_LISTA)]
    return InlineKeyboardMarkup([botoes[i:i + 2] for i in range(0, len(botoes), 2)])


async def perguntar_categoria(msg, gid, desc):
    await msg.reply_text(f"Qual a categoria de {desc}?", reply_markup=teclado_categorias(gid))


async def perguntar_sem_categoria(msg, lista, maximo=8):
    for gid, d in lista[:maximo]:
        await perguntar_categoria(msg, gid, d)
    if len(lista) > maximo:
        await msg.reply_text(f"Mais {len(lista) - maximo} sem categoria. Use: categoria ID (veja os IDs no botão Gastos).")


def totais_por_categoria(g):
    tot = {}
    for x in g:
        if x["tipo"] == "entrada":
            continue
        c = x.get("categoria") or "Sem categoria"
        tot[c] = tot.get(c, 0) + float(x["valor"])
    return tot


def ordenar_categorias(tot):
    return sorted(tot.items(), key=lambda kv: kv[1], reverse=True)


def _msg(update):
    return update.callback_query.message if update.callback_query else update.message


async def enviar_longo(msg, texto, limite=3800, parse_mode=None):
    bloco = ""
    for linha in texto.split("\n"):
        if len(bloco) + len(linha) + 1 > limite:
            await msg.reply_text(bloco, parse_mode=parse_mode)
            bloco = ""
        bloco += linha + "\n"
    if bloco.strip():
        await msg.reply_text(bloco, parse_mode=parse_mode)


def teclado_resumo(fm):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")],
        [InlineKeyboardButton("🗂️ Categorias + gráfico", callback_data=f"resumo_categorias:{fm}"), InlineKeyboardButton("📈 Comparar meses", callback_data=f"resumo_comparar:{fm}")],
    ])


# ---------- GRÁFICOS ----------
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def grafico_pizza(dados, titulo):
    # dados: lista de (categoria, valor), do maior para o menor
    try:
        plt = _plt()
        nomes = [n for n, _ in dados]
        valores = [v for _, v in dados]
        total = sum(valores)
        fig, ax = plt.subplots(figsize=(7, 8), dpi=120)
        fatias, _ = ax.pie(
            valores, colors=[CORES.get(n, "#9E9E9E") for n in nomes],
            startangle=90, counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white"),
        )
        ax.text(0, 0.06, f"R$ {total:.2f}", ha="center", va="center", fontsize=18, fontweight="bold")
        ax.text(0, -0.12, "total", ha="center", va="center", fontsize=11, color="#666666")
        ax.set_title(titulo, fontsize=15, pad=14)
        legendas = [f"{n} - R$ {v:.2f} ({v / total * 100:.0f}%)" for n, v in dados]
        ax.legend(fatias, legendas, loc="upper center", bbox_to_anchor=(0.5, 0.02), frameon=False, fontsize=11)
        ax.set_aspect("equal")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        buf.name = "categorias.png"
        return buf
    except Exception as e:
        print(f"Erro grafico_pizza: {e}")
        return None


def grafico_barras(meses, totais, titulo):
    try:
        plt = _plt()
        rotulos = [f"{m[5:7]}/{m[2:4]}" for m in meses]
        maximo = max(totais) if max(totais) > 0 else 1
        fig, ax = plt.subplots(figsize=(7, 5), dpi=120)
        cores = ["#1565C0"] * (len(meses) - 1) + ["#F9A825"]
        barras = ax.bar(rotulos, totais, color=cores)
        for b, v in zip(barras, totais):
            ax.text(b.get_x() + b.get_width() / 2, v + maximo * 0.01, f"{v:.0f}", ha="center", va="bottom", fontsize=10)
        ax.set_ylim(0, maximo * 1.15)
        ax.set_title(titulo, fontsize=15, pad=12)
        ax.set_ylabel("R$")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        buf.name = "comparativo.png"
        return buf
    except Exception as e:
        print(f"Erro grafico_barras: {e}")
        return None


async def comparativo(update, context, fim_mes=None, n=6):
    msg = _msg(update)
    n = max(2, min(12, n))
    fim = fim_mes or mes_atual_str()
    meses = lista_meses(fim, n)
    g = gastos_entre(meses[0], meses[-1])
    totais = {m: 0.0 for m in meses}
    por_cat = {m: {} for m in meses}
    for x in g:
        if x["tipo"] == "entrada":
            continue
        mm = mes_de(x)
        if mm not in totais:
            continue
        v = float(x["valor"])
        totais[mm] += v
        c = x.get("categoria") or "Sem categoria"
        por_cat[mm][c] = por_cat[mm].get(c, 0) + v
    if not any(totais.values()):
        await msg.reply_text("Ainda não há gastos nesse período para comparar.")
        return
    t = "📈 *Comparativo de gastos*\n"
    anterior = None
    for m in meses:
        v = totais[m]
        linha = f"\n{m[5:7]}/{m[:4]}: R$ {v:.2f}"
        if anterior:
            linha += f" ({(v - anterior) / anterior * 100:+.0f}%)"
        t += linha
        anterior = v
    if fim == mes_atual_str():
        t += "\n\n_(o mês atual vai só até hoje)_"
    cur, ant = meses[-1], meses[-2]
    difs = {c: por_cat[cur].get(c, 0) - por_cat[ant].get(c, 0) for c in set(por_cat[cur]) | set(por_cat[ant])}
    maiores = [(c, d) for c, d in sorted(difs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3] if abs(d) >= 0.01]
    if maiores:
        t += f"\n\n🔎 *Maiores mudanças ({ant[5:7]}/{ant[2:4]} → {cur[5:7]}/{cur[2:4]}):*"
        for c, d in maiores:
            t += f"\n{'⬆️' if d > 0 else '⬇️'} {CATEGORIAS.get(c, '❔')} {c}: {d:+.2f}"
    await msg.reply_text(t, parse_mode="Markdown")
    buf = grafico_barras(meses, [totais[m] for m in meses], "Total gasto por mês (R$)")
    if buf:
        await msg.reply_photo(photo=buf)
    else:
        await msg.reply_text("Não consegui gerar o gráfico agora.")


async def comparar_cmd(update, context):
    n = 6
    for a in context.args:
        if a.isdigit():
            n = int(a)
    await comparativo(update, context, n=n)


# ---------- BUSCAR ----------
def todos_gastos():
    # O Supabase devolve no máximo 1000 linhas por consulta, então busca em páginas
    saida, passo, ini = [], 1000, 0
    while True:
        r = supabase.table("gastos").select("*").order("id").range(ini, ini + passo - 1).execute().data or []
        saida += r
        if len(r) < passo:
            break
        ini += passo
    return saida


def _sem_trecho(txt, m):
    return (txt[:m.start()] + " " + txt[m.end():]).strip()


def extrai_escopo(txt):
    # Separa o período do termo. Devolve (termo, 'tudo' ou 'AAAA-MM'). Sem período = mês atual
    m = re.search(r"\b(tudo|todos|todas|geral|sempre)\b", txt, flags=re.IGNORECASE)
    if m:
        return _sem_trecho(txt, m), "tudo"
    m = re.search(r"\b(m[eê]s passado|m[eê]s anterior)\b", txt, flags=re.IGNORECASE)
    if m:
        return _sem_trecho(txt, m), mes_anterior_str()
    m = re.search(r"\b(\d{4})-(\d{1,2})\b", txt)
    if m:
        return _sem_trecho(txt, m), f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{1,2})/(\d{4})\b", txt)
    if m:
        return _sem_trecho(txt, m), f"{m.group(2)}-{int(m.group(1)):02d}"
    hoje = hoje_sp()
    for nome, num in MESES.items():
        m = re.search(rf"\b{nome}\b(?:\s+(?:de\s+)?(20\d{{2}}))?", txt, flags=re.IGNORECASE)
        if m:
            if m.group(1):
                ano = int(m.group(1))
            else:
                ano = hoje.year - 1 if int(num) > hoje.month else hoje.year
            return _sem_trecho(txt, m), f"{ano}-{num}"
    return txt.strip(), mes_atual_str()


async def buscar(update, context, texto):
    msg = _msg(update)
    termo, escopo = extrai_escopo(texto)
    termo = re.sub(r"\s+", " ", termo).strip(" ,-")
    if not termo:
        await msg.reply_text("Use:\nbuscar mercado\nbuscar mercado setembro\nbuscar mercado mês passado\nbuscar mercado tudo\nbuscar cartão 11/2026")
        return
    palavras = normalizar(termo).split()
    g = todos_gastos() if escopo == "tudo" else gastos_do_mes(escopo)
    achados = []
    for x in g:
        palco = normalizar(f"{x['descricao']} {x.get('categoria') or ''} {x['tipo']}")
        if all((p in palco) or (len(p) > 3 and p.endswith("s") and p[:-1] in palco) for p in palavras):
            achados.append(x)
    onde = "todos os meses" if escopo == "tudo" else f"{escopo[5:7]}/{escopo[:4]}"
    if not achados:
        dica = f"\nPra procurar em todos os meses: buscar {termo} tudo" if escopo != "tudo" else ""
        await msg.reply_text(f'🔎 Nada encontrado para "{termo}" em {onde}.{dica}')
        return
    inicio = datetime.datetime(1970, 1, 1, tzinfo=TZ)
    achados.sort(key=lambda x: (quando_de(x) or inicio, x.get("id", 0)), reverse=True)
    saidas = sum(float(x["valor"]) for x in achados if x["tipo"] != "entrada")
    entradas = sum(float(x["valor"]) for x in achados if x["tipo"] == "entrada")
    t = f'🔎 "{termo}" em {onde}\n{len(achados)} resultado(s) - Gastos: R$ {saidas:.2f}'
    if entradas:
        t += f" - Entradas: R$ {entradas:.2f}"
    if escopo == "tudo":
        por_mes = {}
        for x in achados:
            if x["tipo"] == "entrada":
                continue
            mm = mes_de(x)
            qtd, tot = por_mes.get(mm, (0, 0.0))
            por_mes[mm] = (qtd + 1, tot + float(x["valor"]))
        meses_ord = sorted(por_mes.items(), reverse=True)
        if len(meses_ord) > 1:
            t += "\n\nPor mês:"
            for mm, (qtd, tot) in meses_ord[:12]:
                t += f"\n{mm[5:7]}/{mm[:4]}: R$ {tot:.2f} ({qtd})"
    t += "\n"
    for x in achados[:50]:
        cat = x.get("categoria")
        extra = f" - {CATEGORIAS.get(cat, '❔')} {cat}" if cat else ""
        t += f"\n{x['id']}. {data_curta(x, ano=(escopo == 'tudo'))} - {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}{extra}"
    if len(achados) > 50:
        t += f"\n\n... e mais {len(achados) - 50}. Seja mais específico ou escolha um mês."
    await enviar_longo(msg, t)


async def buscar_cmd(update, context):
    await buscar(update, context, " ".join(context.args))


# ---------- BACKUP ----------
def gerar_csv_bytes():
    try:
        g = todos_gastos()
        d = supabase.table("despesas").select("*").execute().data or []
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["tipo", "descricao", "valor", "data/status", "categoria"])
        for x in g:
            w.writerow(["gasto", x["descricao"], x["valor"], x.get("data", "") or x.get("created_at", ""), x.get("categoria") or ""])
        for x in d:
            w.writerow(["despesa", x["descricao"], x["valor"], x["status"], ""])
        return out.getvalue().encode("utf-8-sig")
    except Exception as e:
        print(f"Erro gerar_csv: {e}")
        return b""


async def enviar_backup(update, legenda="Backup automático antes de apagar"):
    try:
        data = gerar_csv_bytes()
        if update.message:
            await update.message.reply_document(document=data, filename="backup.csv", caption=legenda)
        elif update.callback_query:
            await update.callback_query.message.reply_document(document=data, filename="backup.csv", caption=legenda)
    except Exception as e:
        print(f"Erro enviar_backup: {e}")


# ---------- TELAS ----------
async def resumo(update, context, filtro_mes=None, detalhado=False, categorias=False):
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    atual = filtro_mes == mes_atual_str()
    g = gastos_do_mes(filtro_mes)
    din = sum(float(x["valor"]) for x in g if x["tipo"] == "dinheiro")
    car = sum(float(x["valor"]) for x in g if x["tipo"] == "cartao")
    sod = sum(float(x["valor"]) for x in g if x["tipo"] == "sodexo")
    ent = sum(float(x["valor"]) for x in g if x["tipo"] == "entrada")
    titulo = "📊 *Resumo Detalhado*" if detalhado else "📊 *Resumo*"
    t = f"{titulo} de {filtro_mes[5:7]}/{filtro_mes[:4]}\n"
    if atual:
        t += f"\n💰 Saldo atual: R$ {get_saldo():.2f}"
    t += f"\nDinheiro: R$ {din:.2f}\nCartão: R$ {car:.2f}\nSODEXO: R$ {sod:.2f}\nTotal gasto: R$ {din + car + sod:.2f}"
    if ent:
        t += f"\nEntradas: R$ {ent:.2f}"
    if atual:
        d = supabase.table("despesas").select("*").execute().data or []
        pag = sum(float(x["valor"]) for x in d if x["status"] == "pago")
        t += f"\nPagas: R$ {pag:.2f}"
    if not g:
        t += "\n\nNenhum gasto nesse mês."
    elif detalhado:
        itens = [x for x in g if x["tipo"] != "entrada"]
        inicio = datetime.datetime(1970, 1, 1, tzinfo=TZ)
        itens.sort(key=lambda x: (quando_de(x) or inicio, x.get("id", 0)))
        if itens:
            t += "\n\n🧾 *Detalhes:*"
            for i, x in enumerate(itens, start=1):
                t += f"\n{i}. {data_curta(x)} - {escape_md(x['descricao'].strip().title())} - R$ {float(x['valor']):.2f}"
    tot_cat = totais_por_categoria(g)
    if categorias and tot_cat:
        total_c = sum(tot_cat.values())
        t += "\n\n🗂️ *Por categoria:*"
        for nome, valor in ordenar_categorias(tot_cat):
            t += f"\n{CATEGORIAS.get(nome, '❔')} {nome} - R$ {valor:.2f} ({valor / total_c * 100:.0f}%)"
    msg = _msg(update)
    await enviar_longo(msg, t, parse_mode="Markdown")
    if categorias and tot_cat:
        buf = grafico_pizza(ordenar_categorias(tot_cat), f"Gastos por categoria - {filtro_mes[5:7]}/{filtro_mes[:4]}")
        if buf:
            await msg.reply_photo(photo=buf)
        else:
            await msg.reply_text("Não consegui gerar o gráfico agora.")


def menu():
    kb = [
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo"), InlineKeyboardButton("💸 Dinheiro", callback_data="gasto_dinheiro")],
        [InlineKeyboardButton("💳 Cartão", callback_data="gasto_cartao"), InlineKeyboardButton("🍽️ SODEXO", callback_data="gasto_sodexo")],
        [InlineKeyboardButton("📋 Gastos", callback_data="listar_gastos"), InlineKeyboardButton("🧾 Despesas", callback_data="listar_despesas")],
        [InlineKeyboardButton("✅ Pagar", callback_data="pagar_despesa"), InlineKeyboardButton("🗑️ Apagar último", callback_data="apagar_ultimo")],
        [InlineKeyboardButton("📈 Resumos e gráficos", callback_data="menu_resumo"), InlineKeyboardButton("🔄 Zerar mês", callback_data="zerar_mes")],
    ]
    return InlineKeyboardMarkup(kb)


def aviso_zerar(fm):
    if fm == mes_atual_str():
        return "Vai apagar os gastos desse mês, TODAS as despesas e zerar o saldo (recomeça do zero)."
    return "Vai apagar só os gastos desse mês do histórico (despesas e saldo não mudam)."


def aviso_fechar(ant):
    return f"Fechar {ant[5:7]}/{ant[:4]} guarda os gastos no histórico e zera as despesas e o saldo."


async def start(update, context):
    context.user_data.clear()
    ant = await checar_virada(update)
    if ant:
        context.user_data["esperando"] = f"confirmar_fechar:{ant}"
        await update.message.reply_text(
            f"👋 Bem-vindo de volta!\n\n📅 Vi que virou o mês! Última vez que você falou comigo foi em {ant[5:7]}/{ant[:4]}.\n\n"
            f"Quer fechar {ant[5:7]}/{ant[:4]} e começar {mes_atual_str()[5:7]}/{mes_atual_str()[:4]} do zero?\n"
            f"{aviso_fechar(ant)}\nManda SIM pra fechar ou NÃO pra manter tudo como está."
        )
        return
    await update.message.reply_text("Bot de orçamento\nBem-vindo!", reply_markup=menu())


# ---------- OPERAÇÕES ----------
def apagar_ids(tabela, ids):
    for i in range(0, len(ids), 100):
        supabase.table(tabela).delete().in_("id", ids[i:i + 100]).execute()


async def apagar_gasto_por_id(gid):
    try:
        d = supabase.table("gastos").select("*").eq("id", gid).execute().data
        if not d:
            return None
        g = d[0]
        supabase.table("gastos").delete().eq("id", gid).execute()
        if g["tipo"] == "dinheiro":
            set_saldo(get_saldo() + float(g["valor"]))
        elif g["tipo"] == "entrada":
            set_saldo(get_saldo() - float(g["valor"]))
        return g
    except Exception as e:
        print(f"Erro apagar_gasto: {e}")
        return None


async def fechar_mes():
    # Fecha o mês: os gastos ficam guardados; só despesas e saldo são zerados
    try:
        d = supabase.table("despesas").select("id").execute().data or []
        apagar_ids("despesas", [x["id"] for x in d])
        set_saldo(0)
    except Exception as e:
        print(f"Erro fechar_mes: {e}")


async def zerar_mes(filtro_mes=None):
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    try:
        apagar_ids("gastos", [x["id"] for x in gastos_do_mes(filtro_mes)])
        if filtro_mes == mes_atual_str():
            d = supabase.table("despesas").select("id").execute().data or []
            apagar_ids("despesas", [x["id"] for x in d])
            set_saldo(0)
    except Exception as e:
        print(f"Erro zerar_mes: {e}")
    return filtro_mes


async def apagar_tudo():
    g = todos_gastos()
    apagar_ids("gastos", [x["id"] for x in g])
    d = supabase.table("despesas").select("id").execute().data or []
    apagar_ids("despesas", [x["id"] for x in d])
    set_saldo(0)


# ---------- BOTÕES ----------
async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("cat:"):
        try:
            _, gid, i = q.data.split(":")
            gid = int(gid)
            nome = CAT_LISTA[int(i)]
            r = supabase.table("gastos").select("*").eq("id", gid).execute().data
            if not r:
                await q.edit_message_text("Esse gasto não existe mais.")
                return
            gasto = r[0]
            supabase.table("gastos").update({"categoria": nome}).eq("id", gid).execute()
            aprender(gasto["descricao"], nome)
            await q.edit_message_text(f"✅ {gasto['descricao']} → {CATEGORIAS[nome]} {nome}")
        except Exception as e:
            print(f"Erro ao salvar categoria: {e}")
            await q.message.reply_text("Não consegui salvar a categoria. Confira se a coluna 'categoria' foi criada no Supabase.")
        return
    if q.data == "menu_resumo":
        fm = mes_atual_str()
        await q.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=teclado_resumo(fm))
        return
    if q.data.startswith("resumo_"):
        partes = q.data.split(":")
        tipo = partes[0]
        fm = partes[1] if len(partes) > 1 else None
        if tipo == "resumo_comparar":
            await comparativo(update, context, fim_mes=fm)
        else:
            await resumo(update, context, filtro_mes=fm, detalhado=(tipo == "resumo_detalhado"), categorias=(tipo == "resumo_categorias"))
        return
    if q.data == "saldo":
        context.user_data["esperando"] = "saldo"
        await q.message.reply_text("Envie o saldo. Ex: 3500")
    elif q.data.startswith("gasto_"):
        context.user_data["esperando"] = q.data
        await q.message.reply_text("Envie um por linha. Ex:\nAlmoço, 35\nPode ser com ou sem vírgula.\nPra outra data: Almoço 35 ontem ou Almoço 35 15/11\nPra escolher a categoria: Almoço 35 #viagem")
    elif q.data == "listar_gastos":
        g = gastos_do_mes(mes_atual_str())
        t = "Nenhum gasto nesse mês." if not g else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}" + (f" - {x['categoria']}" if x.get("categoria") else "") for x in g])
        await enviar_longo(q.message, t + "\n\nPra editar, manda: editar 3 45,90\nPra mudar a categoria, manda: categoria 3\nPra apagar um, manda: apagar 3\nPra apagar despesa, manda: apagar despesa 3\nPra apagar entrada, manda: apagar entrada 3000")
    elif q.data == "listar_despesas":
        d = supabase.table("despesas").select("*").order("id").execute().data or []
        t = "Nenhuma despesa." if not d else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['status']}" for x in d])
        await q.message.reply_text(t + "\n\nPra editar, manda: editar despesa 3 187,40\nPra apagar, manda: apagar despesa 3")
    elif q.data == "pagar_despesa":
        d = supabase.table("despesas").select("*").eq("status", "pendente").execute().data or []
        if not d:
            await q.message.reply_text("Nenhuma pendente.")
        else:
            t = "Pendentes - envie o ID (ou vários, ex: 1 2 5):\n" + "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f}" for x in d])
            context.user_data["esperando"] = "pagar"
            await q.message.reply_text(t)
    elif q.data == "apagar_ultimo":
        g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
        if not g:
            await q.message.reply_text("Nenhum gasto pra apagar.")
        else:
            ap = await apagar_gasto_por_id(g[0]["id"])
            if not ap:
                await q.message.reply_text("Não consegui apagar.")
            else:
                await q.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f} ({ap['tipo']})")
    elif q.data == "zerar_mes":
        fm = mes_atual_str()
        context.user_data["esperando"] = f"confirmar_zerar:{fm}"
        await q.message.reply_text(
            f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}?\n{aviso_zerar(fm)}\n\n"
            "Pra apagar os gastos de um mês passado, manda: zerar setembro\n\n"
            "Manda SIM pra confirmar ou NÃO pra cancelar."
        )
        return
    await resumo(update, context)


# ---------- TEXTO ----------
async def on_text(update, context):
    await tratar_texto(update, context, update.message.text.strip())


async def tratar_texto(update, context, o):
    tx = o.lower()
    esp = context.user_data.get("esperando")

    # Confirmação de fechar mês (virada) ou zerar mês
    if esp and (esp.startswith("confirmar_zerar") or esp.startswith("confirmar_fechar")):
        fechar = esp.startswith("confirmar_fechar")
        filtro = esp.split(":")[1] if ":" in esp else mes_atual_str()
        pendente = context.user_data.get("pendente")
        depois = context.user_data.get("esperando_depois")
        context.user_data.clear()
        sim = tx in ("sim", "s")
        nao = tx in ("nao", "não", "n", "cancelar")
        mes_txt = f"{filtro[5:7]}/{filtro[:4]}"
        if sim:
            if fechar:
                await enviar_backup(update, legenda=f"Backup ao fechar {mes_txt}")
                await fechar_mes()
                await update.message.reply_text(f"🔒 Mês {mes_txt} fechado! Os gastos ficaram guardados no histórico. Despesas e saldo foram zerados.")
                await update.message.reply_text("Agora lança o saldo inicial e as despesas do mês novo!", reply_markup=menu())
            else:
                await enviar_backup(update, legenda=f"Backup antes de zerar {filtro}")
                await zerar_mes(filtro)
                if filtro == mes_atual_str():
                    await update.message.reply_text(f"🔄 Mês {mes_txt} zerado! Gastos, despesas e saldo apagados. Pode recomeçar.", reply_markup=menu())
                else:
                    await update.message.reply_text(f"🗑️ Gastos de {mes_txt} apagados do histórico.", reply_markup=menu())
        else:
            await update.message.reply_text("Beleza, mantive tudo. Pode continuar normal.", reply_markup=menu())
        if depois:
            context.user_data["esperando"] = depois
        if pendente:
            await tratar_texto(update, context, pendente)
        if not sim and not nao:
            # A resposta era outra coisa (ex.: um gasto novo): processa normalmente
            await tratar_texto(update, context, o)
        return

    # Confirmação de apagar tudo (precisa digitar APAGAR TUDO)
    if esp and esp.startswith("confirmar_apagar_tudo"):
        context.user_data.clear()
        if o.strip().upper() == "APAGAR TUDO":
            await enviar_backup(update, legenda="Backup antes de apagar tudo")
            await apagar_tudo()
            await update.message.reply_text("🗑️ TUDO apagado! Backup enviado antes.")
            await resumo(update, context)
        else:
            await update.message.reply_text("Ufa! Cancelei, não apaguei nada.", reply_markup=menu())
        return

    # Virada de mês (guarda o que você mandou e o fluxo em andamento)
    ant = await checar_virada(update)
    if ant:
        context.user_data["esperando_depois"] = esp
        context.user_data["esperando"] = f"confirmar_fechar:{ant}"
        context.user_data["pendente"] = o
        await update.message.reply_text(
            f"📅 Vi que virou o mês! Última vez foi em {ant[5:7]}/{ant[:4]}.\n"
            f"Quer fechar {ant[5:7]}/{ant[:4]} e começar do zero? {aviso_fechar(ant)}\n"
            "Manda SIM pra fechar ou NÃO pra manter tudo como está.\n\n"
            "Seu gasto de agora vai ficar guardado, depois que responder eu processo ele."
        )
        return

    if esp == "saldo":
        v = pega_num(o)
        if v is None:
            await update.message.reply_text("Envie só o número, ex: 3500")
            return
        set_saldo(get_saldo() + v)
        context.user_data.clear()
        await update.message.reply_text(f"Saldo: R$ {v:.2f}")
        await resumo(update, context)
        return

    if esp and esp.startswith("gasto_"):
        tipo = esp.replace("gasto_", "")
        tot = 0
        recibo, sem_cat, falhas = [], [], []
        for linha in o.split("\n"):
            linha = linha.strip()
            if not linha:
                continue
            r = parse_linha_data(linha)
            if r is None:
                falhas.append(f"• {linha} ({explica_falha(linha)})")
                continue
            d, v, dt, fc = r
            gid, cat = salvar_gasto(d, v, tipo, dt, fc)
            tot += v
            recibo.append(linha_recibo(d, v, cat, data=dt))
            if not cat and gid:
                sem_cat.append((gid, d))
            if tipo == "dinheiro":
                set_saldo(get_saldo() - v)
        context.user_data.clear()
        texto = f"Registrado: {len(recibo)} item(ns) - R$ {tot:.2f}\n" + "\n".join(recibo)
        if falhas:
            texto += "\n\n⚠️ Não registrei:\n" + "\n".join(falhas)
        await update.message.reply_text(texto)
        await resumo(update, context)
        await perguntar_sem_categoria(update.message, sem_cat)
        return

    if esp == "pagar":
        ids = [int(x) for x in re.findall(r"\d+", o)]
        if not ids:
            await update.message.reply_text("Envie os IDs, ex: 1 2 5")
            return
        pagas, ja_pagas, nao_achou = [], [], []
        total = 0
        try:
            for i in dict.fromkeys(ids):
                r = supabase.table("despesas").select("*").eq("id", i).execute().data
                if not r:
                    nao_achou.append(i)
                    continue
                d = r[0]
                if d["status"] == "pago":
                    ja_pagas.append(i)
                    continue
                supabase.table("despesas").update({"status": "pago"}).eq("id", i).execute()
                total += float(d["valor"])
                pagas.append(d["descricao"])
            if total:
                set_saldo(get_saldo() - total)
        except Exception as e:
            print(f"Erro pagar: {e}")
            await update.message.reply_text("Deu erro ao pagar. Confira com o botão Despesas o que foi pago.")
            return
        if not pagas:
            await update.message.reply_text("Nenhuma despesa paga. Confira os IDs e tente de novo.")
            return
        context.user_data.clear()
        msg = f"✅ Pagas: {', '.join(pagas)}\nTotal: R$ {total:.2f}"
        if ja_pagas:
            msg += f"\nJá estavam pagas: {', '.join(map(str, ja_pagas))}"
        if nao_achou:
            msg += f"\nNão encontrei: {', '.join(map(str, nao_achou))}"
        await update.message.reply_text(msg)
        await resumo(update, context)
        return

    if tx.startswith("editar"):
        await editar_item(update, context, o)
        return

    if tx.startswith("categoria"):
        m = re.search(r"(\d+)", o)
        if not m:
            await update.message.reply_text("Use: categoria 12 (veja o ID no botão Gastos)")
            return
        gid = int(m.group(1))
        r = supabase.table("gastos").select("*").eq("id", gid).execute().data
        if not r:
            await update.message.reply_text("Não achei esse gasto.")
            return
        await perguntar_categoria(update.message, gid, r[0]["descricao"])
        return

    if tx.startswith("comparar"):
        m = re.search(r"(\d+)", o)
        await comparativo(update, context, n=int(m.group(1)) if m else 6)
        return

    if tx.startswith("buscar"):
        await buscar(update, context, o[len("buscar"):].strip())
        return

    if tx.startswith("apagar tudo") or tx == "apagar_tudo":
        context.user_data["esperando"] = "confirmar_apagar_tudo"
        await update.message.reply_text("⚠️ ATENÇÃO! Isso vai apagar TODOS os gastos de TODOS os meses, todas as despesas e zerar o saldo. O histórico inteiro some.\nVou mandar um backup antes.\n\nPra confirmar, digite exatamente: APAGAR TUDO\nQualquer outra coisa cancela.")
        return

    if tx.startswith("zerar"):
        fm = parse_mes(o) or mes_atual_str()
        context.user_data["esperando"] = f"confirmar_zerar:{fm}"
        await update.message.reply_text(f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}? {aviso_zerar(fm)}\nManda SIM pra confirmar ou NÃO pra cancelar.")
        return

    if tx.startswith("apagar entrada"):
        v = pega_num(o)
        if v is None:
            await update.message.reply_text("Use: apagar entrada 3000")
            return
        try:
            g = supabase.table("gastos").select("*").eq("tipo", "entrada").eq("valor", v).order("id", desc=True).limit(1).execute().data
        except Exception as e:
            print(f"Erro apagar entrada: {e}")
            g = None
        if not g:
            await update.message.reply_text(f"Não achei uma entrada de R$ {v:.2f}.")
            return
        supabase.table("gastos").delete().eq("id", g[0]["id"]).execute()
        set_saldo(get_saldo() - v)
        await update.message.reply_text(f"🗑️ Entrada de R$ {v:.2f} apagada, saldo corrigido.")
        await resumo(update, context)
        return

    if tx.startswith("apagar"):
        if "despesa" in tx:
            m = re.search(r"(\d+)", o)
            if not m:
                await update.message.reply_text("Manda: apagar despesa 3")
                return
            did = int(m.group(1))
            try:
                r = supabase.table("despesas").select("*").eq("id", did).execute().data
                if not r:
                    await update.message.reply_text("Não achei essa despesa.")
                    return
                dsp = r[0]
                supabase.table("despesas").delete().eq("id", did).execute()
                if dsp["status"] == "pago":
                    set_saldo(get_saldo() + float(dsp["valor"]))
                    await update.message.reply_text(f"🗑️ Despesa {did} apagada! Como estava paga, devolvi R$ {float(dsp['valor']):.2f} ao saldo.")
                else:
                    await update.message.reply_text(f"🗑️ Despesa {did} apagada!")
            except Exception as e:
                print(f"Erro apagar despesa: {e}")
                await update.message.reply_text("Não consegui apagar essa despesa.")
            return
        m = re.search(r"(\d+)", o)
        if "ultimo" in tx or "último" in tx or not m:
            g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
            if not g:
                await update.message.reply_text("Nenhum gasto pra apagar.")
                return
            ap = await apagar_gasto_por_id(g[0]["id"])
        else:
            ap = await apagar_gasto_por_id(int(m.group(1)))
        if not ap:
            await update.message.reply_text("ID não encontrado.")
            return
        await update.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f}")
        await resumo(update, context)
        return

    if tx.startswith("resumo"):
        fm = parse_mes(o) or mes_atual_str()
        kb = teclado_resumo(fm)
        await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=kb)
        return

    if tx.startswith("despesa"):
        ok = processar_despesas(o)
        if ok == 0:
            await update.message.reply_text("Use: despesa aluguel, 1500\nPode mandar várias, uma por linha.")
            return
        await update.message.reply_text(f"✅ {ok} despesa(s) adicionada(s)!")
        return

    if tx.startswith(("entrada", "recebi", "salario", "salário")):
        ok = 0
        tot = 0
        falhas = []
        for linha in [l.strip() for l in o.split("\n") if l.strip()]:
            ll = limpar_pagamento(linha)
            r = parse_linha_data(ll, r"^\s*(entrada|recebi)\b")
            if r is None:
                falhas.append(f"• {linha} ({explica_falha(linha)})")
                continue
            d, v, dt, _fc = r
            dados_ent = {"descricao": d, "valor": v, "tipo": "entrada"}
            try:
                tentar_com_data(dados_ent, dt, lambda x: supabase.table("gastos").insert(x).execute())
            except Exception as e:
                print(f"Erro ao salvar entrada: {e}")
                falhas.append(f"• {linha} (erro ao salvar)")
                continue
            set_saldo(get_saldo() + v)
            ok += 1
            tot += v
        if ok == 0:
            await update.message.reply_text(("⚠️ Não registrei:\n" + "\n".join(falhas)) if falhas else "Ex: entrada salario 3000")
            return
        texto = f"✅ {ok} entrada(s) lançada(s) - R$ {tot:.2f}"
        if falhas:
            texto += "\n\n⚠️ Não registrei:\n" + "\n".join(falhas)
        await update.message.reply_text(texto)
        await resumo(update, context)
        return

    if tx.startswith(("saida", "saída", "gasto", "gastei", "paguei")):
        tot = 0
        recibo, sem_cat, falhas = [], [], []
        for linha in [l.strip() for l in o.split("\n") if l.strip()]:
            t_linha = detectar_tipo(linha)
            ll = limpar_pagamento(linha)
            r = parse_linha_data(ll, r"^\s*(saida|saída|gastos?|gastei|paguei)\b")
            if r is None:
                falhas.append(f"• {linha} ({explica_falha(linha)})")
                continue
            d, v, dt, fc = r
            gid, cat = salvar_gasto(d, v, t_linha, dt, fc)
            if t_linha == "dinheiro":
                set_saldo(get_saldo() - v)
            tot += v
            recibo.append(linha_recibo(d, v, cat, t_linha, dt))
            if not cat and gid:
                sem_cat.append((gid, d))
        if not recibo:
            await update.message.reply_text(("⚠️ Não registrei:\n" + "\n".join(falhas)) if falhas else "Ex: saida mercado 50")
            return
        texto = f"✅ {len(recibo)} saída(s) lançada(s) - R$ {tot:.2f}\n" + "\n".join(recibo)
        if falhas:
            texto += "\n\n⚠️ Não registrei:\n" + "\n".join(falhas)
        await update.message.reply_text(texto)
        await resumo(update, context)
        await perguntar_sem_categoria(update.message, sem_cat)
        return

    # Texto solto com um valor: vira saída
    tipo = detectar_tipo(o)
    r = parse_linha_data(limpar_pagamento(o))
    if r is not None:
        d, v, dt, fc = r
        gid, cat = salvar_gasto(d, v, tipo, dt, fc)
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text("✅ Saída: " + linha_recibo(d, v, cat, tipo, dt))
        await resumo(update, context)
        if not cat and gid:
            await perguntar_categoria(update.message, gid, d)
        return

    motivo = explica_falha(o)
    if motivo != "faltou o valor":
        await update.message.reply_text(f"⚠️ Não registrei: {motivo}.")
        return

    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50\nresumo setembro\nzerar setembro\napagar ultimo\napagar despesa 3\napagar entrada 3000\neditar 12 45,90\ncategoria 12\ncomparar\nmercado 50 ontem\nmercado 50 15/11\nalmoço 35 #viagem\nbuscar mercado")


# ---------- EDITAR ----------
async def editar_item(update, context, o):
    ajuda = "Use:\neditar 12 45,90\neditar 12 45,90 Mercado\neditar 12 Mercado\neditar 12 ontem\neditar 12 15/11\neditar 12 #viagem\neditar despesa 3 187,40"
    m = re.match(r"^\s*editar\s+(despesa\s+)?(\d+)\s*(.*)$", o, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        await update.message.reply_text(ajuda)
        return
    eh_despesa = bool(m.group(1))
    iid = int(m.group(2))
    resto = m.group(3).strip()
    if not resto:
        await update.message.reply_text(ajuda)
        return
    resto, dt = extrai_data(resto)
    resto = resto.strip()
    if dt is False:
        await update.message.reply_text("Data inválida. Use por exemplo: editar 12 15/11 ou editar 12 ontem")
        return
    if dt and eh_despesa:
        await update.message.reply_text("Despesas não têm data. Pra gastos: editar 12 15/11")
        return
    resto, cat = extrai_categoria(resto)
    resto = resto.strip()
    if cat is False:
        await update.message.reply_text("Categoria desconhecida. Use por exemplo: editar 12 #viagem")
        return
    if cat and eh_despesa:
        await update.message.reply_text("Despesas não têm categoria.")
        return

    v = None
    desc = ""
    mv = re.match(r"^(?:R\$\s*)?(\d[\d.,]*)\s*(.*)$", resto, flags=re.DOTALL)
    mt = re.match(r"^(.*?)\s+(?:R\$\s*)?(\d[\d.,]*)$", resto, flags=re.DOTALL)
    try:
        if mv:
            v = parse_valor(mv.group(1).rstrip(".,"))
            desc = mv.group(2)
        elif mt:
            v = parse_valor(mt.group(2).rstrip(".,"))
            desc = mt.group(1)
        else:
            desc = resto
    except ValueError:
        v = None
        desc = resto
    desc = re.sub(r"\s+", " ", desc).strip(" ,-")
    nova_desc = desc.title() if desc else None
    if v is None and not nova_desc and not dt and not cat:
        await update.message.reply_text("Não entendi o novo valor.\n" + ajuda)
        return

    tabela = "despesas" if eh_despesa else "gastos"
    nome = "Despesa" if eh_despesa else "Gasto"
    try:
        r = supabase.table(tabela).select("*").eq("id", iid).execute().data
        if not r:
            await update.message.reply_text(f"Não achei {nome.lower()} com ID {iid}. Veja os IDs nos botões Gastos/Despesas.")
            return
        item = r[0]
        ov = float(item["valor"])
        nv = v if v is not None else ov
        nd = nova_desc if nova_desc else item["descricao"]
        ajuste = 0.0
        if eh_despesa:
            if item["status"] == "pago":
                ajuste = ov - nv
        elif item["tipo"] == "dinheiro":
            ajuste = ov - nv
        elif item["tipo"] == "entrada":
            ajuste = nv - ov
        upd = {"valor": nv, "descricao": nd}
        if cat:
            upd["categoria"] = cat
        tentar_com_data(upd, dt, lambda x: supabase.table(tabela).update(x).eq("id", iid).execute())
        if ajuste:
            set_saldo(get_saldo() + ajuste)
    except Exception as e:
        print(f"Erro editar: {e}")
        await update.message.reply_text("Não consegui editar. Tenta de novo.")
        return
    msg = f"✏️ {nome} {iid} atualizado: {nd} - R$ {nv:.2f}" + (f" 📅 {dt.strftime('%d/%m')}" if dt else "") + (f" {CATEGORIAS.get(cat, '❔')} {cat}" if cat else "")
    if ajuste:
        msg += f"\nSaldo ajustado em R$ {ajuste:+.2f}"
    await update.message.reply_text(msg)
    await resumo(update, context)


async def editar_cmd(update, context):
    partes = update.message.text.split(None, 1)
    resto = partes[1] if len(partes) > 1 else ""
    await editar_item(update, context, "editar " + resto)


# ---------- COMANDOS ----------
async def despesa_cmd(update, context):
    try:
        partes = update.message.text.split(None, 1)
        texto = partes[1] if len(partes) > 1 else ""
        ok = processar_despesas(texto)
        if ok == 0:
            await update.message.reply_text("Use: /despesa aluguel, 1500\nluz, 200\n(uma por linha ou separadas por ;)")
            return
        await update.message.reply_text(f"✅ {ok} despesa(s) adicionada(s).")
    except Exception as e:
        print(f"Erro despesa_cmd: {e}")
        await update.message.reply_text("Use assim, uma por linha:\n/despesa aluguel, 1500\nluz, 200\ninternet, 100")


async def exportar_cmd(update, context):
    data = gerar_csv_bytes()
    await update.message.reply_document(document=data, filename="backup.csv", caption=f"Saldo: R$ {get_saldo():.2f}")


async def zerar_mes_cmd(update, context):
    txt = " ".join(context.args)
    fm = parse_mes(txt) if txt else mes_atual_str()
    fm = fm or mes_atual_str()
    context.user_data["esperando"] = f"confirmar_zerar:{fm}"
    await update.message.reply_text(f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}? {aviso_zerar(fm)} Manda SIM pra confirmar ou NÃO pra cancelar.")


async def resumo_cmd(update, context):
    txt = " ".join(context.args)
    fm = parse_mes(txt) if txt else mes_atual_str()
    fm = fm or mes_atual_str()
    await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=teclado_resumo(fm))


async def apagar_tudo_cmd(update, context):
    context.user_data["esperando"] = "confirmar_apagar_tudo"
    await update.message.reply_text("⚠️ ATENÇÃO! Isso vai apagar TODOS os gastos de TODOS os meses, todas as despesas e zerar o saldo. O histórico inteiro some.\nVou mandar um backup antes.\n\nPra confirmar, digite exatamente: APAGAR TUDO\nQualquer outra coisa cancela.")


async def erro_geral(update, context):
    print(f"Erro: {context.error}")
    try:
        if update is not None and getattr(update, "effective_message", None):
            await update.effective_message.reply_text("⚠️ Deu um erro aqui. Tenta de novo.")
    except Exception:
        pass


# ---------- MONTAGEM DO APP ----------
def montar_app(com_updater=True):
    # com_updater=False: o servidor web (Starlette) entrega os updates ao bot (modo webhook)
    b = ApplicationBuilder().token(TOKEN)
    if not com_updater:
        b = b.updater(None)
    app = b.build()
    app.add_handler(TypeHandler(Update, so_permitidos), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("despesa", despesa_cmd))
    app.add_handler(CommandHandler("exportar", exportar_cmd))
    app.add_handler(CommandHandler("zerar_mes", zerar_mes_cmd))
    app.add_handler(CommandHandler("resumo", resumo_cmd))
    app.add_handler(CommandHandler("comparar", comparar_cmd))
    app.add_handler(CommandHandler("buscar", buscar_cmd))
    app.add_handler(CommandHandler("editar", editar_cmd))
    app.add_handler(CommandHandler("apagar_tudo", apagar_tudo_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(erro_geral)
    return app


async def rodar_webhook(app):
    # Servidor próprio: o Telegram entrega em POST /<TOKEN>; o cron-job.org (e o Render) usam GET / ou /health e recebem 200 "ok"
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

    async def telegram(request: Request) -> Response:
        try:
            dados = await request.json()
            await app.update_queue.put(Update.de_json(data=dados, bot=app.bot))
        except Exception as e:
            print(f"Erro ao receber update: {e}")
        return Response()

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok")

    web = Starlette(routes=[
        Route("/" + TOKEN, telegram, methods=["POST"]),
        Route("/", health, methods=["GET", "HEAD"]),
        Route("/health", health, methods=["GET", "HEAD"]),
    ])
    servidor = uvicorn.Server(config=uvicorn.Config(app=web, host="0.0.0.0", port=PORT, use_colors=False, log_level="warning"))

    async with app:
        await app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        await app.start()
        print("Bot rodando (webhook + health check)...")
        await servidor.serve()
        await app.stop()


def main():
    if not ALLOWED_IDS:
        print("ATENÇÃO: ALLOWED_USER_IDS vazio ou inválido. O bot vai ignorar todo mundo!")
    if BASE_URL:
        asyncio.run(rodar_webhook(montar_app(com_updater=False)))
    else:
        print("Bot rodando (polling, sem RENDER_EXTERNAL_URL)...")
        montar_app().run_polling()


if __name__ == "__main__":
    main()
