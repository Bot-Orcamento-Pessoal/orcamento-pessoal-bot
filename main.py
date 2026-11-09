import os, re, csv, io, datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters, TypeHandler, ApplicationHandlerStop
from supabase import create_client

TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "") + "/" + TOKEN
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TZ = ZoneInfo("America/Sao_Paulo")
MESES = {"janeiro":"01","fevereiro":"02","marco":"03","março":"03","abril":"04","maio":"05","junho":"06","julho":"07","agosto":"08","setembro":"09","outubro":"10","novembro":"11","dezembro":"12"}

# ---------- SEGURANÇA: SÓ VOCÊ + SUA MULHER ----------
ALLOWED_IDS = set()
_raw = os.environ.get("ALLOWED_USER_IDS", "")
for _x in _raw.replace(";", ",").split(","):
    _x = _x.strip()
    if _x.isdigit():
        ALLOWED_IDS.add(int(_x))

async def so_permitidos(update, context):
    if not ALLOWED_IDS:
        return
    uid = update.effective_user.id if update.effective_user else None
    if uid not in ALLOWED_IDS:
        raise ApplicationHandlerStop

def escape_md(s):
    s = str(s)
    for c in ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]:
        s = s.replace(c, "\\" + c)
    return s

def hoje_sp():
    return datetime.datetime.now(TZ).date()

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

def mes_atual_str():
    return hoje_sp().strftime("%Y-%m")

def mes_de(g):
    raw = g.get("data") or g.get("created_at") or ""
    if not raw:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(TZ)
        return dt.strftime("%Y-%m")
    except Exception as e:
        print(f"Erro mes_de: {e}")
        return str(raw)[:7]

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

def mes_anterior_str():
    h = hoje_sp()
    ano = h.year
    mes = h.month - 1
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

def gerar_csv_bytes():
    try:
        g = supabase.table("gastos").select("*").execute().data or []
        d = supabase.table("despesas").select("*").execute().data or []
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["tipo", "descricao", "valor", "data/status"])
        for x in g:
            w.writerow(["gasto", x["descricao"], x["valor"], x.get("data", "") or x.get("created_at", "")])
        for x in d:
            w.writerow(["despesa", x["descricao"], x["valor"], x["status"]])
        out.seek(0)
        return out.getvalue().encode()
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
            if x["tipo"] == "entrada":
                continue
            nome = x["descricao"].strip().title()
            agrupado[nome] = agrupado.get(nome, 0) + float(x["valor"])
        ordenado = sorted(agrupado.items(), key=lambda item: item[1], reverse=True)
        t += "\n\n🧾 *Detalhes:*"
        for i, (nome, valor) in enumerate(ordenado, start=1):
            t += f"\n{i}. {escape_md(nome)} - R$ {valor:.2f}"
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
        await update.message.reply_text(f"👋 Bem-vindo de volta!\n\n📅 Vi que virou o mês! Última vez que você falou comigo foi em {ant[5:7]}/{ant[:4]}.\n\nQuer zerar {ant[5:7]}/{ant[:4]} pra começar {mes_atual_str()[5:7]}/{mes_atual_str()[:4]} do zero?\nIsso vai apagar gastos E despesas.\nManda SIM pra zerar ou NÃO pra manter.")
        return
    await update.message.reply_text("Bot de orçamento\nBem-vindo!", reply_markup=menu())

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

async def zerar_mes(filtro_mes=None):
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    try:
        g = supabase.table("gastos").select("*").execute().data or []
        for x in g:
            if mes_de(x) == filtro_mes:
                supabase.table("gastos").delete().eq("id", x["id"]).execute()
        d = supabase.table("despesas").select("*").execute().data or []
        for x in d:
            supabase.table("despesas").delete().eq("id", x["id"]).execute()
        set_saldo(0)
    except Exception as e:
        print(f"Erro zerar_mes: {e}")
    return filtro_mes

# ---------- NOVO: ordem não importa ----------
def pega_num(s):
    m = re.findall(r"(\d+[.,]?\d*)", s)
    return float(m[-1].replace(",", ".")) if m else None
def pega_desc(s, rem):
    d = re.sub(rem, "", s, flags=re.IGNORECASE)
    d = re.sub(r"\s*\d+[.,]?\d*\s*$", "", d.strip())
    d = re.sub(r"^\s*\d+[.,]?\d*\s*", "", d.strip())
    d = d.strip(" ,-")
    return d.title() if d else "Item"

async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("resumo_"):
        partes = q.data.split(":")
        tipo = partes[0]
        fm = partes[1] if len(partes) > 1 else None
        detalhado = (tipo == "resumo_detalhado")
        await resumo(update, context, filtro_mes=fm, detalhado=detalhado)
        return
    if q.data == "saldo":
        context.user_data["esperando"] = "saldo"
        await q.message.reply_text("Envie o saldo. Ex: 3500")
    elif q.data.startswith("gasto_"):
        context.user_data["esperando"] = q.data
        await q.message.reply_text("Envie um por linha. Ex:\nAlmoço, 35")
    elif q.data == "listar_gastos":
        g = supabase.table("gastos").select("*").order("id").execute().data or []
        g = [x for x in g if mes_de(x) == mes_atual_str()]
        t = "Nenhum gasto nesse mês." if not g else "\n".join([f"{x['id']}. {escape_md(x['descricao'])} - R$ {float(x['valor']):.2f} - {x['tipo']}" for x in g])
        await q.message.reply_text(t + "\n\nPra apagar um, manda: apagar 3\nPra apagar despesa, manda: apagar despesa 3\nPra apagar entrada, manda: apagar entrada 3000")
    elif q.data == "listar_despesas":
        d = supabase.table("despesas").select("*").order("id").execute().data or []
        t = "Nenhuma despesa." if not d else "\n".join([f"{x['id']}. {escape_md(x['descricao'])} - R$ {float(x['valor']):.2f} - {x['status']}" for x in d])
        await q.message.reply_text(t + "\n\nPra apagar, manda: apagar despesa 3")
    elif q.data == "pagar_despesa":
        d = supabase.table("despesas").select("*").eq("status", "pendente").execute().data or []
        if not d:
            await q.message.reply_text("Nenhuma pendente.")
        else:
            t = "Pendentes - envie o ID:\n" + "\n".join([f"{x['id']}. {escape_md(x['descricao'])} - R$ {float(x['valor']):.2f}" for x in d])
            context.user_data["esperando"] = "pagar"
            await q.message.reply_text(t)
    elif q.data == "apagar_ultimo":
        g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
        if not g:
            await q.message.reply_text("Nenhum gasto pra apagar.")
        else:
            ap = await apagar_gasto_por_id(g[0]["id"])
            await q.message.reply_text(f"🗑️ Apagado: {escape_md(ap['descricao'])} - R$ {float(ap['valor']):.2f} ({ap['tipo']})")
    elif q.data == "zerar_mes":
        context.user_data["esperando"] = f"confirmar_zerar:{mes_atual_str()}"
        await q.message.reply_text(f"⚠️ Zerar o mês {mes_atual_str()[5:7]}/{mes_atual_str()[:4]}?\nVai apagar TODOS os gastos E TODAS as despesas e zerar o saldo.\n\nSe quiser zerar outro mês, manda direto: zerar setembro\n\nManda SIM pra confirmar ou NÃO pra cancelar.")
        return
    await resumo(update, context)

async def on_text(update, context):
    o = update.message.text.strip()
    tx = o.lower()
    esp = context.user_data.get("esperando")
    if esp and esp.startswith("confirmar_zerar"):
        filtro = esp.split(":")[1] if ":" in esp else mes_atual_str()
        pendente = context.user_data.get("pendente")
        context.user_data.clear()
        if tx == "sim":
            await enviar_backup(update, legenda=f"Backup antes de zerar {filtro}")
            await zerar_mes(filtro)
            await update.message.reply_text(f"🔄 Mês {filtro[5:7]}/{filtro[:4]} zerado! Gastos e despesas apagados, saldo zerado.")
            await update.message.reply_text("Agora lança as despesas desse mês com os valores novos!", reply_markup=menu())
        else:
            await update.message.reply_text("Beleza, mantive tudo. Pode continuar normal.", reply_markup=menu())
        if pendente:
            update.message.text = pendente
            await on_text(update, context)
        return
    if esp and esp.startswith("confirmar_apagar_tudo"):
        context.user_data.clear()
        if tx == "sim":
            await enviar_backup(update, legenda="Backup antes de apagar tudo")
            g = supabase.table("gastos").select("*").execute().data or []
            for x in g:
                supabase.table("gastos").delete().eq("id", x["id"]).execute()
            d = supabase.table("despesas").select("*").execute().data or []
            for x in d:
                supabase.table("despesas").delete().eq("id", x["id"]).execute()
            set_saldo(0)
            await update.message.reply_text("🗑️ TUDO apagado! Backup enviado antes.")
            await resumo(update, context)
        else:
            await update.message.reply_text("Ufa! Cancelei, não apaguei nada.", reply_markup=menu())
        return
    ant = await checar_virada(update)
    if ant and not esp:
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        await update.message.reply_text(f"📅 Vi que virou o mês! Última vez foi em {ant[5:7]}/{ant[:4]}.\nQuer zerar {ant[5:7]}/{ant[:4]} pra começar do zero? Vai apagar gastos E despesas.\nManda SIM ou NÃO.\n\nSeu gasto de agora vai ficar guardado, depois que responder eu processo ele.")
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
        except Exception as e:
            print(f"Erro saldo: {e}")
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
            except Exception as e:
                print(f"Erro gasto linha: {e}")
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
            await update.message.reply_text(f"Paga: {escape_md(d['descricao'])}")
            await resumo(update, context)
        except Exception as e:
            print(f"Erro pagar: {e}")
            await update.message.reply_text("ID inválido.")
        return
    if tx.startswith("apagar tudo") or tx == "apagar_tudo":
        context.user_data["esperando"] = "confirmar_apagar_tudo"
        await update.message.reply_text("⚠️ ATENÇÃO! Isso vai apagar TODOS os gastos, despesas e zerar o saldo.\nVou mandar um backup antes, mas confirma:\nManda SIM pra apagar tudo ou NÃO pra cancelar.")
        return
    if tx.startswith("zerar"):
        fm = parse_mes(o) or mes_atual_str()
        context.user_data["esperando"] = f"confirmar_zerar:{fm}"
        await update.message.reply_text(f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}? Vai apagar todos os gastos E todas as despesas e zerar o saldo.\nManda SIM pra confirmar ou NÃO pra cancelar.")
        return
    if tx.startswith("apagar entrada"):
        v = pega_num(o)
        if v is None:
            await update.message.reply_text("Use: apagar entrada 3000")
            return
        set_saldo(get_saldo() - v)
        try:
            g = supabase.table("gastos").select("*").eq("tipo", "entrada").eq("valor", v).order("id", desc=True).limit(1).execute().data
            if g:
                supabase.table("gastos").delete().eq("id", g[0]["id"]).execute()
        except Exception as e:
            print(f"Erro apagar entrada: {e}")
        await update.message.reply_text(f"🗑️ Entrada de R$ {v:.2f} apagada, saldo corrigido.")
        await resumo(update, context)
        return
    if tx.startswith("apagar"):
        if "despesa" in tx:
            m = re.search(r"(\d+)", o)
            if not m:
                await update.message.reply_text("Manda: apagar despesa 3")
                return
            try:
                supabase.table("despesas").delete().eq("id", int(m.group(1))).execute()
                await update.message.reply_text(f"🗑️ Despesa {m.group(1)} apagada!")
            except Exception as e:
                print(f"Erro apagar despesa: {e}")
                await update.message.reply_text("Não achei essa despesa.")
            return
        m = re.search(r"(\d+)", o)
        if "ultimo" in tx or "último" in tx or not m:
            g = supabase.table("gastos").select("*").order("id", desc=True).limit(1).execute().data or []
            if not g:
                await update.message.reply_text("Nenhum gasto pra apagar.")
                return
            ap = await apagar_gasto_por_id(g[0]["id"])
            await update.message.reply_text(f"🗑️ Apagado: {escape_md(ap['descricao'])} - R$ {float(ap['valor']):.2f}")
            await resumo(update, context)
            return
        ap = await apagar_gasto_por_id(int(m.group(1)))
        if not ap:
            await update.message.reply_text("ID não encontrado.")
            return
        await update.message.reply_text(f"🗑️ Apagado: {escape_md(ap['descricao'])} - R$ {float(ap['valor']):.2f}")
        await resumo(update, context)
        return
    if tx.startswith("resumo"):
        fm = parse_mes(o) or mes_atual_str()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")]])
        await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=kb)
        return
    tipo = "dinheiro"
    if re.search(r"\b(cartao|cartão|credito|crédito)\b", tx):
        tipo = "cartao"
    elif re.search(r"\b(sodexo|vale)\b", tx):
        tipo = "sodexo"
    limpo = o
    for p in [r"\bcartao\b", r"\bcartão\b", r"\bcredito\b", r"\bcrédito\b", r"\bsodexo\b", r"\bvale\b", r"\bpix\b", r"\bdinheiro\b", r"\bdebito\b", r"\bdébito\b"]:
        limpo = re.sub(p, "", limpo, flags=re.IGNORECASE)
    if tx.startswith("despesa"):
        linhas = [l.strip() for l in o.split("\n") if l.strip()]
        ok = 0
        for linha in linhas:
            linha_limpa = re.sub(r"^despesa\s*", "", linha, flags=re.IGNORECASE)
            if "," in linha_limpa:
                desc, val = linha_limpa.rsplit(",", 1)
                try:
                    v = float(val.replace("R$", "").replace(",", "."))
                except Exception as e:
                    print(f"Erro despesa linha: {e}")
                    continue
                d = desc.strip().title()
            else:
                v = pega_num(linha_limpa)
                if v is None:
                    continue
                d = pega_desc(linha_limpa, r"despesa")
            if not d:
                d = "Despesa"
            supabase.table("despesas").insert({"descricao": d, "valor": v, "status": "pendente"}).execute()
            ok += 1
        if ok == 0:
            await update.message.reply_text("Use: despesa aluguel, 1500\nPode mandar várias, uma por linha.")
            return
        await update.message.reply_text(f"✅ {ok} despesa(s) adicionada(s)!")
        return
    if tx.startswith(("entrada", "recebi", "salario", "salário")):
        v = pega_num(limpo)
        if v is None:
            await update.message.reply_text("Ex: entrada salario 3000")
            return
        d = pega_desc(limpo, r"entrada|recebi")
        set_saldo(get_saldo() + v)
        supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": "entrada"}).execute()
        await update.message.reply_text(f"✅ Entrada: {escape_md(d)} - R$ {v:.2f}")
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
        await update.message.reply_text(f"✅ Saída: {escape_md(d)} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return
    v = pega_num(limpo)
    if v is not None:
        d = pega_desc(limpo, r"")
        supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {escape_md(d)} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return
    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50\nresumo setembro\nzerar setembro\napagar ultimo\napagar despesa 3\napagar entrada 3000")

async def despesa_cmd(update, context):
    try:
        texto = " ".join(context.args)
        linhas = [l.strip() for l in texto.replace(";", "\n").split("\n") if l.strip()]
        if len(linhas) == 1 and texto.count(",") > 1:
            partes = [p.strip() for p in texto.split(",")]
            linhas = []
            for i in range(0, len(partes)-1, 2):
                linhas.append(f"{partes[i]}, {partes[i+1]}")
        ok = 0
        for linha in linhas:
            if "," not in linha:
                continue
            desc, val = linha.rsplit(",", 1)
            v = float(val.strip().replace("R$", "").replace(",", "."))
            supabase.table("despesas").insert({"descricao": desc.strip(), "valor": v, "status": "pendente"}).execute()
            ok += 1
        if ok == 0:
            await update.message.reply_text("Use: /despesa aluguel, 1500\nluz, 200")
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
    context.user_data["esperando"] = f"confirmar_zerar:{fm}"
    await update.message.reply_text(f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}? Vai apagar gastos E despesas. Manda SIM pra confirmar ou NÃO pra cancelar.")
async def resumo_cmd(update, context):
    txt = " ".join(context.args)
    fm = parse_mes(txt) if txt else mes_atual_str()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")]])
    await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=kb)
async def apagar_tudo_cmd(update, context):
    context.user_data["esperando"] = "confirmar_apagar_tudo"
    await update.message.reply_text("⚠️ ATENÇÃO! Isso vai apagar TUDO e zerar o saldo.\nVou mandar um backup antes.\nManda SIM pra apagar tudo ou NÃO pra cancelar.")

def main():
    print("Bot rodando (webhook)...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(TypeHandler(Update, so_permitidos), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("despesa", despesa_cmd))
    app.add_handler(CommandHandler("exportar", exportar_cmd))
    app.add_handler(CommandHandler("zerar_mes", zerar_mes_cmd))
    app.add_handler(CommandHandler("resumo", resumo_cmd))
    app.add_handler(CommandHandler("apagar_tudo", apagar_tudo_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)

if __name__ == "__main__":
    main()