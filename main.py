import os, re, csv, io, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase import create_client
TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "") + "/" + TOKEN
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MESES = {"janeiro":"01","fevereiro":"02","marco":"03","março":"03","abril":"04","maio":"05","junho":"06","julho":"07","agosto":"08","setembro":"09","outubro":"10","novembro":"11","dezembro":"12"}

def get_saldo():
    r = supabase.table("saldo_config").select("valor").eq("id", 1).execute()
    if not r.data:
        supabase.table("saldo_config").insert({"id": 1, "valor": 0}).execute()
        return 0.0
    return float(r.data[0]["valor"])
def set_saldo(v):
    supabase.table("saldo_config").upsert({"id": 1, "valor": v}).execute()
def mes_atual_str():
    return datetime.date.today().strftime("%Y-%m")
def mes_de(g):
    return str(g.get("data") or g.get("created_at") or "")[:7]
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
            ano = str(datetime.date.today().year)
            y = re.search(r"20\d{2}", txt)
            if y:
                ano = y.group(0)
            return f"{ano}-{num}"
    m = re.search(r"(\d{1,2})", txt)
    if m:
        return f"{datetime.date.today().year}-{int(m.group(1)):02d}"
    return None
def mes_anterior_str():
    hoje = datetime.date.today()
    ano = hoje.year
    mes = hoje.month - 1
    if mes == 0:
        mes = 12
        ano -= 1
    return f"{ano}-{mes:02d}"
def get_ultimo_mes_visto():
    try:
        r = supabase.table("saldo_config").select("valor").eq("id", 3).execute()
        if not r.data:
            return None
        v = int(float(r.data[0]["valor"]))
        s = str(v)
        return f"{s[:4]}-{s[5:7]}" if len(s) == 6 else None
    except:
        return None
def set_ultimo_mes_visto():
    try:
        v = int(datetime.date.today().strftime("%Y%m"))
        supabase.table("saldo_config").upsert({"id": 3, "valor": v}).execute()
    except:
        pass
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

async def resumo(update, context, filtro_mes=None, detalhado=False):
    g = supabase.table("gastos").select("*").execute().data or []
    d = supabase.table("despesas").select("*").execute().data or []
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    g = [x for x in g if mes_de(x) == filtro_mes]
    s = get_saldo()
    din = sum(float(x["valor"]) for x in g if x["tipo"] == "dinheiro")
    car = sum(float(x["valor"]) for x in g if x["tipo"] == "cartao")
    sod = sum(float(x["valor"]) for x in g if x["tipo"] == "sodexo")
    pag = sum(float(x["valor"]) for x in d if x["status"] == "pago")
    titulo = "📊 *Resumo Detalhado*" if detalhado else "📊 *Resumo*"
    t = f"{titulo} de {filtro_mes[5:7]}/{filtro_mes[:4]}\n\n💰 Saldo atual: R$ {s:.2f}\nDinheiro: R$ {din:.2f}\nCartão: R$ {car:.2f}\nSODEXO: R$ {sod:.2f}"
    if filtro_mes == mes_atual_str():
        t += f"\nPagas: R$ {pag:.2f}"
    if not g:
        t += "\n\nNenhum gasto nesse mês."
    elif detalhado:
        agrupado = {}
        for x in g:
            nome = x["descricao"].strip().title()
            agrupado[nome] = agrupado.get(nome, 0) + float(x["valor"])
        ordenado = sorted(agrupado.items(), key=lambda item: item[1], reverse=True)
        t += "\n\n🧾 *Detalhes:*"
        for i, (nome, valor) in enumerate(ordenado, start=1):
            t += f"\n{i}. {nome} - R$ {valor:.2f}"
    if update.callback_query:
        await update.callback_query.message.reply_text(t, parse_mode="Markdown")
    else:
        await update.message.reply_text(t, parse_mode="Markdown")

def menu():
    kb = [[InlineKeyboardButton("💰 Saldo", callback_data="saldo"), InlineKeyboardButton("💸 Dinheiro", callback_data="gasto_dinheiro")], [InlineKeyboardButton("💳 Cartão", callback_data="gasto_cartao"), InlineKeyboardButton("🍽️ SODEXO", callback_data="gasto_sodexo")], [InlineKeyboardButton("📋 Gastos", callback_data="listar_gastos"), InlineKeyboardButton("🧾 Despesas", callback_data="listar_despesas")], [InlineKeyboardButton("✅ Pagar", callback_data="pagar_despesa"), InlineKeyboardButton("🗑️ Apagar último", callback_data="apagar_ultimo")], [InlineKeyboardButton("🔄 Zerar mês", callback_data="zerar_mes")]]
    return InlineKeyboardMarkup(kb)

async def start(update, context):
    context.user_data.clear()
    ant = await checar_virada(update)
    if ant:
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        await update.message.reply_text(f"👋