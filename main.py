import os
import re
import csv
import io
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
    return float(r.data[0]["valor"]) if r.data else 0.0

def set_saldo(v):
    supabase.table("saldo_config").update({"valor": v}).eq("id", 1).execute()

async def resumo(update, context):
    gastos = supabase.table("gastos").select("*").execute().data or []
    despesas = supabase.table("despesas").select("*").execute().data or []
    saldo = get_saldo()
    dinheiro = sum(float(g["valor"]) for g in gastos if g["tipo"] == "dinheiro")
    cartao = sum(float(g["valor"]) for g in gastos if g["tipo"] == "cartao")
    sodexo = sum(float(g["valor"]) for g in gastos if g["tipo"] == "sodexo")
    pagas = sum(float(d["valor"]) for d in despesas if d["status"] == "pago")
    texto = f"📊 *Resumo financeiro*\n\n💰 Saldo: R$ {saldo:.2f}\n\nGastos dinheiro/débito: R$ {dinheiro:.2f}\nGastos no cartão: R$ {cartao:.2f}\nGastos SODEXO: R$ {sodexo:.2f}\nDespesas pagas: R$ {pagas:.2f}"
    if update.callback_query:
        await update.callback_query.message.reply_text(texto, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, parse_mode="Markdown")

def menu():
    kb = [
        [InlineKeyboardButton("💰 Incluir saldo", callback_data="saldo"),
         InlineKeyboardButton("💸 Gasto dinheiro/débito", callback_data="gasto_dinheiro")],
        [InlineKeyboardButton("💳 Gasto cartão", callback_data="gasto_cartao"),
         InlineKeyboardButton("🍽️ Gasto SODEXO", callback_data="gasto_sodexo")],
        [InlineKeyboardButton("📋 Listar gastos", callback_data="listar_gastos"),
         InlineKeyboardButton("🧾 Listar despesas", callback_data="listar_despesas")],
        [InlineKeyboardButton("✅ Pagar despesa", callback_data="pagar_despesa")],
    ]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bot de orçamento\nBem-vindo ao seu bot de controle financeiro!", reply_markup=menu())

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "saldo":
        context.user_data["esperando"] = "saldo"
        await q.message.reply_text("Envie o valor do saldo. Ex: 3500 ou Salario, 3500")
    elif q.data.startswith("gasto_"):
        tipo = q.data.replace("gasto_", "")
        context.user_data["esperando"] = f"gasto_{tipo}"
        await q.message.reply_text("Envie os gastos, um por linha. Ex:\nAlmoço, 35\nUber, 22")
    elif q.data == "listar_gastos":
        gastos = supabase.table("gastos").select("*").order("id").execute().data or []
        if not gastos:
            await q.message.reply_text("Nenhum gasto ainda.")
        else:
            t = "Gastos:\n"
            for i, g in enumerate(gastos, 1):
                t += f"{i}. {g['descricao']} - R$ {float(g['valor']):.2f} - {g['tipo']} - {g['data']}\n"
            await q.message.reply_text(t)
    elif q.data == "listar_despesas":
        ds = supabase.table("despesas").select("*").order("id").execute().data or []
        if not ds:
            await q.message.reply_text("Nenhuma despesa cadastrada.")
        else:
            t = "Despesas fixas:\n"
            for d in ds:
                t += f"{d['id']}. {d['descricao']} - R$ {float(d['valor']):.2f} - {d['status']}\n"
            await q.message.reply_text(t)
    elif q.data == "pagar_despesa":
        ds = supabase.table("despesas").select("*").eq("status", "pendente").execute().data or []
        if not ds:
            await q.message.reply_text("Nenhuma despesa pendente.")
        else:
            t = "Pendentes - envie o ID pra pagar. Ex: 1\n"
            for d in ds:
                t += f"{d['id']}. {d['descricao']} - R$ {float(d['valor']):.2f}\n"
            context.user_data["esperando"] = "pagar"
            await q.message.reply_text(t)
    await resumo(update, context)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_original = update.message.text.strip()
    texto = texto_original.lower()
    espera = context.user_data.get("esperando")

    if espera == "saldo":
        val = texto_original.split(",")[-1].strip().replace("R$", "").replace(",", ".")
        try:
            v = float(val)
            set_saldo(get_saldo() + v)
            context.user_data.clear()
            await update.message.reply_text(f"Saldo adicionado: R$ {v:.2f}")
            await resumo(update, context)
        except:
            await update.message.reply_text("Formato inválido. Envie só o número, ex: 3500")
        return

    if espera and espera.startswith("gasto_"):
        tipo = espera.replace("gasto_", "")
        total = 0
        for linha in texto_original.split("\n"):
            if "," not in linha:
                continue
            desc, val = linha.rsplit(",", 1)
            try:
                v = float(val.strip().replace("R$", "").replace(",", "."))
            except:
                continue
            supabase.table("gastos").insert({"descricao": desc.strip(), "valor": v, "tipo": tipo}).execute()
            total += v
            if tipo == "dinheiro":
                set_saldo(get_saldo() - v)
        context.user_data.clear()
        await update.message.reply_text(f"Registrado: R$ {total:.2f} em {tipo}")
        await resumo(update, context)
        return

    if espera == "pagar":
        try:
            id_d = int(texto_original.strip())
            d = supabase.table("despesas").select("*").eq("id", id_d).execute().data[0]
            supabase.table("despesas").update({"status": "pago"}).eq("id", id_d).execute()
            set_saldo(get_saldo() - float(d["valor"]))
            context.user_data.clear()
            await update.message.reply_text(f"Despesa '{d['descricao']}' paga!")
            await resumo(update, context)
        except:
            await update.message.reply_text("ID inválido.")
        return

    tipo = "dinheiro"
    if "cartao" in texto or "cartão" in texto or "credito" in texto or "crédito" in texto:
        tipo = "cartao"
    elif "sodexo" in texto or "vale" in texto:
        tipo = "sodexo"
    elif "pix" in texto or "dinheiro" in texto or "debito" in texto or "débito" in texto:
        tipo = "dinheiro"

    limpo = texto_original
    for p in ["cartao", "cartão", "credito", "crédito", "sodexo", "vale", "pix", "dinheiro", "debito", "débito"]:
        limpo = re.sub(p, "", limpo, flags=re.IGNORECASE)

    if texto.startswith("despesa"):
        m = re.search(r"(\d+[.,]?\d*)", limpo)
        if not m:
            await update.message.reply_text("Use: despesa aluguel 1500")
            return
        v = float(m.group(1).replace(",", "."))
        desc = re.sub(r"despesa", "", limpo, flags=re.IGNORECASE)
        desc = re.sub(r"\d+[.,]?\d*", "", desc).strip() or "Despesa"
        supabase.table("despesas").insert({"descricao": desc, "valor": v, "status": "pendente"}).execute()
        await update.message.reply_text(f"✅ Despesa '{desc}' - R$ {v:.2f} adicionada como pendente.")
        return

    if texto.startswith(("entrada", "recebi", "salario", "salário")):
        m = re.search(r"(\d+[.,]?\d*)", limpo)
        if not m:
            await update.message.reply_text("Não entendi o valor. Ex: entrada salario 3000")
            return
        v = float(m.group(1).replace(",", "."))
        desc = re.sub(r"entrada|recebi|salario|salário", "", limpo, flags=re.IGNORECASE)
        desc = re.sub(r"\d+[.,]?\d*", "", desc).strip() or "Entrada"
        set_saldo(get_saldo() + v)
        await update.message.reply_text(f"✅ Entrada: {desc} - R$ {v:.2f}")
        await resumo(update, context)
        return

    if texto.startswith(("saida", "saída", "gasto", "gastei", "paguei")):
        m = re.search(r"(\d+[.,]?\d*)", limpo)
        if not m:
            await update.message.reply_text("Não entendi o valor. Ex: saida mercado 50")
            return
        v = float(m.group(1).replace(",", "."))
        desc = re.sub(r"saida|saída|gasto|gastei|paguei", "", limpo, flags=re.IGNORECASE)
        desc = re.sub(r"\d+[.,]?\d*", "", desc).strip() or "Gasto"
        supabase.table("gastos").insert({"descricao": desc, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {desc} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return

    m = re.search(r"(\d+[.,]?\d*)", limpo)
    if m:
        v = float(m.group(1).replace(",", "."))
        desc = re.sub(r"\d+[.,]?\d*", "", limpo).strip() or "Gasto"
        supabase.table("gastos").insert({"descricao": desc, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {desc} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return

    await update.message.reply_text("Não entendi. Tenta:\nentrada salario 3000\nsaida mercado 50\nsaida uber 22 cartao\ndespesa aluguel 1500")

async def despesa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        arg = " ".join(context.args)
        desc, val = arg.rsplit(",", 1)
        v = float(val.strip().replace(",", "."))
        supabase.table("despesas").insert({"descricao": desc.strip(), "valor": v, "status": "pendente"}).execute()
        await update.message.reply_text(f"Despesa '{desc.strip()}' adicionada como pendente.")
    except:
        await update.message.reply_text("Use: /despesa aluguel, 1500")

async def exportar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gastos = supabase.table("gastos").select("*").execute().data or []
    despesas = supabase.table("despesas").select("*").execute().data or []
    out = io.StringIO
    w = csv.writer(out)
    w.writerow(["tipo", "descricao", "valor", "data/status"])
    for g in gastos:
        w.writerow(["gasto", g["descricao"], g["valor"], g["data"]])
    for d in despesas:
        w.writerow(["despesa", d["descricao"], d["valor"], d["status"]])
    out.seek(0)
    await update.message.reply_document(document=out.getvalue().encode(), filename="backup.csv", caption=f"Saldo atual: R$ {get_saldo():.2f}")

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