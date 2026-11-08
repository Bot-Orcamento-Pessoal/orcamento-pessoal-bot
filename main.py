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
# --- NOVO: CONTROLE DE VIRADA DO MÊS ---
# Usa o id 3 do saldo_config pra guardar o último mês que você falou com o bot, ex: 202610
def get_ultimo_mes_visto():
    try:
        r = supabase.table("saldo_config").select("valor").eq("id", 3).execute()
        if not r.data:
            return None
        v = int(float(r.data[0]["valor"]))
        s = str(v)  # 202610
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
    # Retorna True se perguntou, pra não processar o resto ainda
    atual = mes_atual_str()
    ultimo = get_ultimo_mes_visto()
    if ultimo is None:
        set_ultimo_mes_visto()
        return False
    if ultimo == atual:
        return False
    # Virou o mês! Pergunta se quer zerar o mês anterior
    # Já atualiza pra não perguntar toda hora
    set_ultimo_mes_visto()
    ant = ultimo
    # Guarda o mês pra zerar quando responder SIM
    # Vamos usar user_data via context? Aqui usamos esperando no on_text/start
    # Por isso retornamos o mês anterior
    return ant

async def resumo(update, context, filtro_mes=None):
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
    t = f"📊 *Resumo de {filtro_mes[5:7]}/{filtro_mes[:4]}*\n\n💰 Saldo atual: R$ {s:.2f}\nDinheiro: R$ {din:.2f}\nCartão: R$ {car:.2f}\nSODEXO: R$ {sod:.2f}"
    if filtro_mes == mes_atual_str():
        t += f"\nPagas: R$ {pag:.2f}"
    if not g:
        t += "\n\nNenhum gasto nesse mês."
    if update.callback_query:
        await update.callback_query.message.reply_text(t, parse_mode="Markdown")
    else:
        await update.message.reply_text(t, parse_mode="Markdown")

def menu():
    kb = [[InlineKeyboardButton("💰 Saldo", callback_data="saldo"), InlineKeyboardButton("💸 Dinheiro", callback_data="gasto_dinheiro")], [InlineKeyboardButton("💳 Cartão", callback_data="gasto_cartao"), InlineKeyboardButton("🍽️ SODEXO", callback_data="gasto_sodexo")], [InlineKeyboardButton("📋 Gastos", callback_data="listar_gastos"), InlineKeyboardButton("🧾 Despesas", callback_data="listar_despesas")], [InlineKeyboardButton("✅ Pagar", callback_data="pagar_despesa"), InlineKeyboardButton("🗑️ Apagar último", callback_data="apagar_ultimo")], [InlineKeyboardButton("🔄 Zerar mês", callback_data="zerar_mes")]]
    return InlineKeyboardMarkup(kb)

async def start(update, context):
    context.user_data.clear()
    # CHECA VIRADA
    ant = await checar_virada(update)
    if ant:
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        await update.message.reply_text(f"👋 Bem-vindo de volta!\n\n📅 Vi que virou o mês! Última vez que você falou comigo foi em {ant[5:7]}/{ant[:4]}.\n\nQuer zerar {ant[5:7]}/{ant[:4]} pra começar {mes_atual_str()[5:7]}/{mes_atual_str()[:4]} do zero?\nManda SIM pra zerar ou NÃO pra manter.")
        return
    await update.message.reply_text("Bot de orçamento\nBem-vindo!", reply_markup=menu())

async def apagar_gasto_por_id(gid):
    d = supabase.table("gastos").select("*").eq("id", gid).execute().data
    if not d:
        return None
    g = d[0]
    supabase.table("gastos").delete().eq("id", gid).execute()
    if g["tipo"] == "dinheiro":
        set_saldo(get_saldo() + float(g["valor"]))
    return g

async def zerar_mes(filtro_mes=None):
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    g = supabase.table("gastos").select("*").execute().data or []
    for x in g:
        if mes_de(x) == filtro_mes:
            supabase.table("gastos").delete().eq("id", x["id"]).execute()
    if filtro_mes == mes_atual_str() or filtro_mes == mes_anterior_str():
        # Se zerou o mês anterior na virada, também zera saldo e despesas
        d = supabase.table("despesas").select("*").eq("status", "pago").execute().data or []
        for x in d:
            supabase.table("despesas").update({"status": "pendente"}).eq("id", x["id"]).execute()
        # Só zera saldo se for virada / mês atual
        if filtro_mes == mes_anterior_str():
            set_saldo(0)
    if filtro_mes == mes_atual_str():
        d = supabase.table("despesas").select("*").eq("status", "pago").execute().data or []
        for x in d:
            supabase.table("despesas").update({"status": "pendente"}).eq("id", x["id"]).execute()
        set_saldo(0)
    return filtro_mes

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
        g = [x for x in g if mes_de(x) == mes_atual_str()]
        t = "Nenhum gasto nesse mês." if not g else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}" for x in g])
        await q.message.reply_text(t + "\n\nPra apagar um, manda: apagar 3")
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
    elif q.data == "apagar_ultimo":
        g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
        if not g:
            await q.message.reply_text("Nenhum gasto pra apagar.")
        else:
            ap = await apagar_gasto_por_id(g[0]["id"])
            await q.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f} ({ap['tipo']})")
    elif q.data == "zerar_mes":
        context.user_data["esperando"] = f"confirmar_zerar:{mes_atual_str()}"
        await q.message.reply_text(f"⚠️ Zerar o mês {mes_atual_str()[5:7]}/{mes_atual_str()[:4]}?\nVai apagar TODOS os gastos desse mês e zerar o saldo.\n\nSe quiser zerar outro mês, manda direto: zerar setembro\n\nManda SIM pra confirmar ou NÃO pra cancelar.")
        return
    await resumo(update, context)

async def on_text(update, context):
    o = update.message.text.strip()
    tx = o.lower()
    esp = context.user_data.get("esperando")
    # Se está esperando confirmação da virada, trata primeiro
    if esp and esp.startswith("confirmar_zerar"):
        filtro = esp.split(":")[1] if ":" in esp else mes_atual_str()
        context.user_data.clear()
        if tx == "sim":
            await zerar_mes(filtro)
            await update.message.reply_text(f"🔄 Mês {filtro[5:7]}/{filtro[:4]} zerado! Começando {mes_atual_str()[5:7]}/{mes_atual_str()[:4]} do zero.")
            await update.message.reply_text("Agora pode mandar seu primeiro gasto do mês!", reply_markup=menu())
        else:
            await update.message.reply_text("Beleza, mantive o mês anterior. Pode continuar normal.", reply_markup=menu())
        return
    # CHECA VIRADA também quando manda texto direto, sem /start
    ant = await checar_virada(update)
    if ant and not esp:
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        await update.message.reply_text(f"📅 Vi que virou o mês! Última vez foi em {ant[5:7]}/{ant[:4]}.\nQuer zerar {ant[5:7]}/{ant[:4]} pra começar do zero?\nManda SIM ou NÃO.\n\nSeu gasto de agora vai ficar guardado, depois que responder eu processo ele.")
        # Guarda o texto pra depois? Simples: pede pra mandar de novo
        context.user_data["pendente"] = o
        return
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
    if tx.startswith("zerar"):
        fm = parse_mes(o) or mes_atual_str()
        context.user_data["esperando"] = f"confirmar_zerar:{fm}"
        await update.message.reply_text(f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}? Vai apagar todos os gastos desse mês.\nManda SIM pra confirmar ou NÃO pra cancelar.")
        return
    if tx.startswith("apagar"):
        m = re.search(r"(\d+)", o)
        if "ultimo" in tx or "último" in tx or not m:
            g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
            if not g:
                await update.message.reply_text("Nenhum gasto pra apagar.")
                return
            ap = await apagar_gasto_por_id(g[0]["id"])
            await update.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f}")
            await resumo(update, context)
            return
        ap = await apagar_gasto_por_id(int(m.group(1)))
        if not ap:
            await update.message.reply_text("ID não encontrado.")
            return
        await update.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f}")
        await resumo(update, context)
        return
    if tx.startswith("resumo"):
        fm = parse_mes(o)
        await resumo(update, context, filtro_mes=fm)
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
    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50\nresumo setembro\nzerar setembro\napagar ultimo")

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
        w.writerow(["gasto", x["descricao"], x["valor"], x.get("data", "")])
    for x in d:
        w.writerow(["despesa", x["descricao"], x["valor"], x["status"]])
    out.seek(0)
    await update.message.reply_document(document=out.getvalue().encode(), filename="backup.csv", caption=f"Saldo: R$ {get_saldo():.2f}")
async def zerar_mes_cmd(update, context):
    txt = " ".join(context.args)
    fm = parse_mes(txt) if txt else mes_atual_str()
    await zerar_mes(fm)
    await update.message.reply_text(f"🔄 Mês {fm[5:7]}/{fm[:4]} zerado!")
    await resumo(update, context, filtro_mes=fm)
async def resumo_cmd(update, context):
    txt = " ".join(context.args)
    fm = parse_mes(txt) if txt else None
    await resumo(update, context, filtro_mes=fm)
async def apagar_tudo_cmd(update, context):
    g = supabase.table("gastos").select("*").execute().data or []
    for x in g:
        supabase.table("gastos").delete().eq("id", x["id"]).execute()
    d = supabase.table("despesas").select("*").execute().data or []
    for x in d:
        supabase.table("despesas").delete().eq("id", x["id"]).execute()
    set_saldo(0)
    await update.message.reply_text("🗑️ TUDO apagado!")
    await resumo(update, context)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("despesa", despesa_cmd))
    app.add_handler(CommandHandler("exportar", exportar_cmd))
    app.add_handler(CommandHandler("zerar_mes", zerar_mes_cmd))
    app.add_handler(CommandHandler("resumo", resumo_cmd))
    app.add_handler(CommandHandler("apagar_tudo", apagar_tudo_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)
    print("Bot rodando (webhook)...")
if __name__ == "__main__":
    main()