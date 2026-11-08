import os
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Oi! Sou seu bot de orçamento 💰\n\n"
        "Use:\n"
        "/add gasto 50 mercado - adiciona gasto\n"
        "/add receita 2000 salario - adiciona receita\n"
        "/saldo - ver saldo do mês\n"
        "/relatorio - ver últimos lançamentos"
    )


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tipo = context.args[0].lower()
        valor = float(context.args[1].replace(",", "."))
        categoria = context.args[2] if len(context.args) > 2 else "geral"
        descricao = " ".join(context.args[3:]) if len(context.args) > 3 else categoria

        if tipo not in ["gasto", "receita"]:
            await update.message.reply_text(
                "Use: /add gasto 50 mercado ou /add receita 2000 salario"
            )
            return

        supabase.table("transacoes").insert({
            "user_id": str(update.effective_user.id),
            "tipo": tipo,
            "valor": valor,
            "categoria": categoria,
            "descricao": descricao,
        }).execute()

        await update.message.reply_text(
            f"✅ {tipo} de R$ {valor:.2f} em {categoria} salvo!"
        )
    except Exception:
        await update.message.reply_text("Ops! Use assim: /add gasto 50 mercado")


async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inicio_mes = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    res = (
        supabase.table("transacoes")
        .select("*")
        .eq("user_id", str(update.effective_user.id))
        .gte("created_at", inicio_mes)
        .execute()
    )
    dados = res.data or []
    receitas = sum(x["valor"] for x in dados if x["tipo"] == "receita")
    gastos = sum(x["valor"] for x in dados if x["tipo"] == "gasto")
    await update.message.reply_text(
        f"📊 Seu saldo do mês:\n"
        f"Receitas: R$ {receitas:.2f}\n"
        f"Gastos: R$ {gastos:.2f}\n"
        f"Saldo: R$ {receitas - gastos:.2f}"
    )


async def relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = (
        supabase.table("transacoes")
        .select("*")
        .eq("user_id", str(update.effective_user.id))
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    dados = res.data or []
    if not dados:
        await update.message.reply_text("Nenhum lançamento ainda.")
        return
    texto = "🧾 Últimos 10:\n"
    for x in dados:
        texto += f"- {x['tipo']} R$ {x['valor']:.2f} | {x['categoria']} | {x.get('descricao', '')}\n"
    await update.message.reply_text(texto)


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("saldo", saldo))
    app.add_handler(CommandHandler("relatorio", relatorio))

    if WEBHOOK_URL:
        print("Bot rodando (webhook)...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        print("Bot rodando (polling)...")
        app.run_polling()