import os, re, csv, io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase import create_client
TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "") + "/" + TOKEN
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_saldo():
    r = supabase.table("saldo_config").select("valor").eq("id", 1).execute()
    if not r.data:
        supabase.table("saldo_config").insert({"id": 1, "valor": 0}).execute()
        return 0.0
    return float(r.data[0]["valor"])

def set_saldo(v):
    supabase.table("saldo_config").upsert({"id": 1, "valor": v}).execute()

async def resumo(update, context):
    g = supabase.table("gastos").select("*").execute().data or []
    d = supabase.table("despesas").select("*").execute().data or []
    s = get_saldo()
    din = sum(float(x["valor"]) for x in g if x["tipo"] == "dinheiro")
    car = sum(float(x["valor"]) for x in g if x["tipo"] == "cartao")
    sod = sum(float(x["valor"]) for x in g if x["tipo"] == "sodexo")
    pag = sum(float(x["valor"]) for x in d if x["status"] == "pago")
    t = f"📊 *Resumo*\n\n💰 Saldo: R$ {s:.2f}\nDinheiro: R$ {din:.2f}\nCartão: R$ {car:.2f}\nSODEXO: R$ {sod:.2f}\nPagas: R$ {pag:.2f}"
    if update.callback_query:
        await update.callback_query.message.reply_text(t, parse_mode="Markdown")
    else:
        await update.message.reply_text(t, parse_mode="Markdown")

def menu():
    kb = [[InlineKeyboardButton("💰 Saldo", callback_data="saldo"), InlineKeyboardButton("💸 Dinheiro", callback_data="gasto_dinheiro")], [InlineKeyboardButton("💳 Cartão", callback_data="gasto_cartao"), InlineKeyboardButton("🍽️ SODEXO", callback_data="gasto_sodexo")], [InlineKeyboardButton("📋 Gastos", callback_data="listar_gastos"), InlineKeyboardButton("🧾 Despesas", callback_data="listar_despesas")], [InlineKeyboardButton("✅ Pagar", callback_data="pagar_despesa")]]
    return InlineKeyboardMarkup(kb)

async def start(update, context):
    context.user_data.clear()
    await update.message.reply_text("Bot de orçamento\nBem-vindo!", reply_markup=menu())

async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "saldo":
        context.user_data["esperando"] = "saldo"
        await q.message.reply_text("Envie o saldo. Ex: 3500")
    elif q.data.startswith("gasto_"):
        context.user_data["esperando"] = q.data
        await q.message.reply_text("Envie um por linha. Ex:\nAlmoço, 35")
    elif q.data == "listar_gastos":
        g = supabase.table("gastos").select("*").order("id").execute().data or []
        t = "Nenhum gasto." if not g else "\n".join([f"{i+1}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}" for i, x in enumerate(g)])
        await q.message.reply_text(t)
    elif q.data == "listar_despesas":
        d = supabase.table("despesas").select("*").order("id").execute().data or []
        t = "Nenhuma despesa." if not d else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['status']}" for x in d])
        await q.message.reply_text(t)
    elif q.data == "pagar_despesa":
        d = supabase.table("despesas").select("*").eq("status", "pendente").execute().data or []
        if not d:
            await q.message.reply_text("Nenhuma pendente.")
        else:
            t = "Pendentes - envie o ID:\n" + "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f}" for x in d])
            context.user_data["esperando"] = "pagar"
            await q.message.reply_text(t)
    await resumo(update, context)

async def on_text(update, context):
    o = update.message.text.strip()
    tx = o.lower()
    esp = context.user_data.get("esperando")
    if esp == "saldo":
        m2 = re.search(r"(\d+[.,]?\d*)", o)
        try:
            v = float(m2.group(1).replace(",", "."))
            set_saldo(get_saldo() + v)
            context.user_data.clear()
            await update.message.reply_text(f"Saldo: R$ {v:.2f}")
            await resumo(update, context)
        except:
            await update.message.reply_text("Envie só o número, ex: 3500")
        return
    if esp and esp.startswith("gasto_"):
        tipo = esp.replace("gasto_", "")
        tot = 0
        for linha in o.split("\n"):
            if "," not in linha:
                continue
            desc, val = linha.rsplit(",", 1)
            try:
                v = float(val.replace("R$", "").replace(",", "."))
            except:
                continue
            supabase.table("gastos").insert({"descricao": desc.strip(), "valor": v, "tipo": tipo}).execute()
            tot += v
            if tipo == "dinheiro":
                set_saldo(get_saldo() - v)
        context.user_data.clear()
        await update.message.reply_text(f"Registrado: R$ {tot:.2f}")
        await resumo(update, context)
        return
    if esp == "pagar":
        try:
            i = int(o)
            d = supabase.table("despesas").select("*").eq("id", i).execute().data[0]
            supabase.table("despesas").update({"status": "pago"}).eq("id", i).execute()
            set_saldo(get_saldo() - float(d["valor"]))
            context.user_data.clear()
            await update.message.reply_text(f"Paga: {d['descricao']}")
            await resumo(update, context)
        except:
            await update.message.reply_text("ID inválido.")
        return
    tipo = "dinheiro"
    if "cartao" in tx or "cartão" in tx or "credito" in tx:
        tipo = "cartao"
    elif "sodexo" in tx or "vale" in tx:
        tipo = "sodexo"
    limpo = o
    for p in ["cartao", "cartão", "credito", "crédito", "sodexo", "vale", "pix", "dinheiro", "debito", "débito"]:
        limpo = re.sub(p, "", limpo, flags=re.IGNORECASE)
    def pega_num(s):
        m = re.search(r"(\d+[.,]?\d*)", s)
        return float(m.group(1).replace(",", ".")) if m else None
    def pega_desc(s, rem):
        d = re.sub(rem, "", s, flags=re.IGNORECASE)
        d = re.sub(r"\d+[.,]?\d*", "", d).strip()
        return d or "Item"
    if tx.startswith("despesa"):
        v = pega_num(limpo)
        if v is None:
            await update.message.reply_text("Use: despesa aluguel 1500")
            return
        d = pega_desc(limpo, r"despesa")
        supabase.table("despesas").insert({"descricao": d, "valor": v, "status": "pendente"}).execute()
        await update.message.reply_text(f"✅ Despesa {d} - R$ {v:.2f}")
        return
    if tx.startswith(("entrada", "recebi", "salario", "salário")):
        v = pega_num(limpo)
        if v is None:
            await update.message.reply_text("Ex: entrada salario 3000")
            return
        d = pega_desc(limpo, r"entrada|recebi|salario|salário")
        set_saldo(get_saldo() + v)
        await update.message.reply_text(f"✅ Entrada: {d} - R$ {v:.2f}")
        await resumo(update, context)
        return
    if tx.startswith(("saida", "saída", "gasto", "gastei", "paguei")):
        v = pega_num(limpo)
        if v is None:
            await update.message.reply_text("Ex: saida mercado 50")
            return
        d = pega_desc(limpo, r"saida|saída|gasto|gastei|paguei")
        supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {d} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return
    v = pega_num(limpo)
    if v is not None:
        d = pega_desc(limpo, r"")
        supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {d} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return
    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50")

async def despesa_cmd(update, context):
    try:
        arg = " ".join(context.args)
        desc, val = arg.rsplit(",", 1)
        v = float(val.strip().replace(",", "."))
        supabase.table("despesas").insert({"descricao": desc.strip(), "valor": v, "status": "pendente"}).execute()
        await update.message.reply_text(f"Despesa '{desc.strip()}' adicionada.")
    except:
        await update.message.reply_text("Use: /despesa aluguel, 1500")

async def exportar_cmd(update, context):
    g = supabase.table("gastos").select("*").execute().data or []
    d = supabase.table("despesas").select("*").execute().data or []
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["tipo", "descricao", "valor", "data/status"])
    for x in g:
        w.writerow(["gasto", x["descricao"], x["valor"], x["data"]])
    for x in d:
        w.writerow(["despesa", x["descricao"], x["valor"], x["status"]])
    out.seek(0)
    await update.message.reply_document(document=out.getvalue().encode(), filename="backup.csv", caption=f"Saldo: R$ {get_saldo():.2f}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("despesa", despesa_cmd))
    app.add_handler(CommandHandler("exportar", exportar_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)
    print("Bot rodando (webhook)...")

if __name__ == "__main__":
    main()