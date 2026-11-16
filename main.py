import os, re, csv, io, datetime
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


def mes_afeta_tudo(fm):
    # Só zera despesas e saldo quando o mês é o atual ou o anterior
    return fm in (mes_atual_str(), mes_anterior_str())


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


def processar_despesas(texto):
    ok = 0
    for linha in re.split(r"[\n;]", texto):
        linha = re.sub(r"^\s*/?despesas?(@\w+)?\s*", "", linha.strip(), flags=re.IGNORECASE)
        if not linha:
            continue
        r = parse_linha(linha)
        if r is None:
            continue
        d, v = r
        if d == "Item":
            d = "Despesa"
        supabase.table("despesas").insert({"descricao": d, "valor": v, "status": "pendente"}).execute()
        ok += 1
    return ok


# ---------- BACKUP ----------
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
    kb = [
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo"), InlineKeyboardButton("💸 Dinheiro", callback_data="gasto_dinheiro")],
        [InlineKeyboardButton("💳 Cartão", callback_data="gasto_cartao"), InlineKeyboardButton("🍽️ SODEXO", callback_data="gasto_sodexo")],
        [InlineKeyboardButton("📋 Gastos", callback_data="listar_gastos"), InlineKeyboardButton("🧾 Despesas", callback_data="listar_despesas")],
        [InlineKeyboardButton("✅ Pagar", callback_data="pagar_despesa"), InlineKeyboardButton("🗑️ Apagar último", callback_data="apagar_ultimo")],
        [InlineKeyboardButton("🔄 Zerar mês", callback_data="zerar_mes")],
    ]
    return InlineKeyboardMarkup(kb)


def aviso_zerar(fm):
    if mes_afeta_tudo(fm):
        return "Vai apagar TODOS os gastos desse mês e TODAS as despesas, e zerar o saldo."
    return "Vai apagar só os gastos desse mês (despesas e saldo não mudam)."


async def start(update, context):
    context.user_data.clear()
    ant = await checar_virada(update)
    if ant:
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        await update.message.reply_text(
            f"👋 Bem-vindo de volta!\n\n📅 Vi que virou o mês! Última vez que você falou comigo foi em {ant[5:7]}/{ant[:4]}.\n\n"
            f"Quer zerar {ant[5:7]}/{ant[:4]} pra começar {mes_atual_str()[5:7]}/{mes_atual_str()[:4]} do zero?\n"
            f"{aviso_zerar(ant)}\nManda SIM pra zerar ou NÃO pra manter."
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


async def zerar_mes(filtro_mes=None):
    if not filtro_mes:
        filtro_mes = mes_atual_str()
    try:
        g = supabase.table("gastos").select("*").execute().data or []
        apagar_ids("gastos", [x["id"] for x in g if mes_de(x) == filtro_mes])
        if mes_afeta_tudo(filtro_mes):
            d = supabase.table("despesas").select("id").execute().data or []
            apagar_ids("despesas", [x["id"] for x in d])
            set_saldo(0)
    except Exception as e:
        print(f"Erro zerar_mes: {e}")
    return filtro_mes


async def apagar_tudo():
    g = supabase.table("gastos").select("id").execute().data or []
    apagar_ids("gastos", [x["id"] for x in g])
    d = supabase.table("despesas").select("id").execute().data or []
    apagar_ids("despesas", [x["id"] for x in d])
    set_saldo(0)


# ---------- BOTÕES ----------
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
        await q.message.reply_text("Envie um por linha. Ex:\nAlmoço, 35\nPode ser com ou sem vírgula.")
    elif q.data == "listar_gastos":
        g = supabase.table("gastos").select("*").order("id").execute().data or []
        g = [x for x in g if mes_de(x) == mes_atual_str()]
        t = "Nenhum gasto nesse mês." if not g else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}" for x in g])
        await q.message.reply_text(t + "\n\nPra apagar um, manda: apagar 3\nPra apagar despesa, manda: apagar despesa 3\nPra apagar entrada, manda: apagar entrada 3000")
    elif q.data == "listar_despesas":
        d = supabase.table("despesas").select("*").order("id").execute().data or []
        t = "Nenhuma despesa." if not d else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['status']}" for x in d])
        await q.message.reply_text(t + "\n\nPra apagar, manda: apagar despesa 3")
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
            if not ap:
                await q.message.reply_text("Não consegui apagar.")
            else:
                await q.message.reply_text(f"🗑️ Apagado: {ap['descricao']} - R$ {float(ap['valor']):.2f} ({ap['tipo']})")
    elif q.data == "zerar_mes":
        fm = mes_atual_str()
        context.user_data["esperando"] = f"confirmar_zerar:{fm}"
        await q.message.reply_text(
            f"⚠️ Zerar o mês {fm[5:7]}/{fm[:4]}?\n{aviso_zerar(fm)}\n\n"
            "Se quiser zerar outro mês, manda direto: zerar setembro\n\n"
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

    # Confirmação de zerar mês
    if esp and esp.startswith("confirmar_zerar"):
        filtro = esp.split(":")[1] if ":" in esp else mes_atual_str()
        pendente = context.user_data.get("pendente")
        depois = context.user_data.get("esperando_depois")
        context.user_data.clear()
        sim = tx in ("sim", "s")
        nao = tx in ("nao", "não", "n", "cancelar")
        if sim:
            await enviar_backup(update, legenda=f"Backup antes de zerar {filtro}")
            await zerar_mes(filtro)
            if mes_afeta_tudo(filtro):
                await update.message.reply_text(f"🔄 Mês {filtro[5:7]}/{filtro[:4]} zerado! Gastos e despesas apagados, saldo zerado.")
                await update.message.reply_text("Agora lança as despesas desse mês com os valores novos!", reply_markup=menu())
            else:
                await update.message.reply_text(f"🔄 Gastos de {filtro[5:7]}/{filtro[:4]} apagados.", reply_markup=menu())
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

    # Confirmação de apagar tudo
    if esp and esp.startswith("confirmar_apagar_tudo"):
        context.user_data.clear()
        if tx in ("sim", "s"):
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
        context.user_data["esperando"] = f"confirmar_zerar:{ant}"
        context.user_data["pendente"] = o
        await update.message.reply_text(
            f"📅 Vi que virou o mês! Última vez foi em {ant[5:7]}/{ant[:4]}.\n"
            f"Quer zerar {ant[5:7]}/{ant[:4]} pra começar do zero? {aviso_zerar(ant)}\n"
            "Manda SIM ou NÃO.\n\nSeu gasto de agora vai ficar guardado, depois que responder eu processo ele."
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
        ok = 0
        for linha in o.split("\n"):
            linha = linha.strip()
            if not linha:
                continue
            r = parse_linha(linha)
            if r is None:
                continue
            d, v = r
            supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": tipo}).execute()
            tot += v
            ok += 1
            if tipo == "dinheiro":
                set_saldo(get_saldo() - v)
        context.user_data.clear()
        await update.message.reply_text(f"Registrado: {ok} item(ns) - R$ {tot:.2f}")
        await resumo(update, context)
        return

    if esp == "pagar":
        try:
            i = int(o)
            r = supabase.table("despesas").select("*").eq("id", i).execute().data
            if not r:
                await update.message.reply_text("ID inválido.")
                return
            d = r[0]
            if d["status"] == "pago":
                await update.message.reply_text("Essa despesa já está paga.")
                return
            supabase.table("despesas").update({"status": "pago"}).eq("id", i).execute()
            set_saldo(get_saldo() - float(d["valor"]))
            context.user_data.clear()
            await update.message.reply_text(f"Paga: {d['descricao']}")
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")]])
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
        for linha in [l.strip() for l in o.split("\n") if l.strip()]:
            ll = limpar_pagamento(linha)
            r = parse_linha(ll, r"^\s*(entrada|recebi)\b")
            if r is None:
                continue
            d, v = r
            set_saldo(get_saldo() + v)
            supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": "entrada"}).execute()
            ok += 1
            tot += v
        if ok == 0:
            await update.message.reply_text("Ex: entrada salario 3000")
            return
        await update.message.reply_text(f"✅ {ok} entrada(s) lançada(s) - R$ {tot:.2f}")
        await resumo(update, context)
        return

    if tx.startswith(("saida", "saída", "gasto", "gastei", "paguei")):
        ok = 0
        tot = 0
        for linha in [l.strip() for l in o.split("\n") if l.strip()]:
            t_linha = detectar_tipo(linha)
            ll = limpar_pagamento(linha)
            r = parse_linha(ll, r"^\s*(saida|saída|gastos?|gastei|paguei)\b")
            if r is None:
                continue
            d, v = r
            supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": t_linha}).execute()
            if t_linha == "dinheiro":
                set_saldo(get_saldo() - v)
            ok += 1
            tot += v
        if ok == 0:
            await update.message.reply_text("Ex: saida mercado 50")
            return
        await update.message.reply_text(f"✅ {ok} saída(s) lançada(s) - R$ {tot:.2f}")
        await resumo(update, context)
        return

    # Texto solto com um valor: vira saída
    tipo = detectar_tipo(o)
    r = parse_linha(limpar_pagamento(o))
    if r is not None:
        d, v = r
        supabase.table("gastos").insert({"descricao": d, "valor": v, "tipo": tipo}).execute()
        if tipo == "dinheiro":
            set_saldo(get_saldo() - v)
        await update.message.reply_text(f"✅ Saída: {d} - R$ {v:.2f} ({tipo})")
        await resumo(update, context)
        return

    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50\nresumo setembro\nzerar setembro\napagar ultimo\napagar despesa 3\napagar entrada 3000")


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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")]])
    await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=kb)


async def apagar_tudo_cmd(update, context):
    context.user_data["esperando"] = "confirmar_apagar_tudo"
    await update.message.reply_text("⚠️ ATENÇÃO! Isso vai apagar TUDO e zerar o saldo.\nVou mandar um backup antes.\nManda SIM pra apagar tudo ou NÃO pra cancelar.")


async def erro_geral(update, context):
    print(f"Erro: {context.error}")
    try:
        if update is not None and getattr(update, "effective_message", None):
            await update.effective_message.reply_text("⚠️ Deu um erro aqui. Tenta de novo.")
    except Exception:
        pass


def main():
    if not ALLOWED_IDS:
        print("ATENÇÃO: ALLOWED_USER_IDS vazio ou inválido. O bot vai ignorar todo mundo!")
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
    app.add_error_handler(erro_geral)
    if BASE_URL:
        print("Bot rodando (webhook)...")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)
    else:
        print("Bot rodando (polling, sem RENDER_EXTERNAL_URL)...")
        app.run_polling()


if __name__ == "__main__":
    main()
