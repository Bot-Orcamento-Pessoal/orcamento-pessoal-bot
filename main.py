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


# ---------- GASTOS DO MÊS (filtro no Supabase) ----------
def gastos_do_mes(fm):
    # Busca só o período do mês (com 1 dia de folga) e confere o mês exato no Python
    try:
        ano, mes = int(fm[:4]), int(fm[5:7])
        ini = datetime.datetime(ano, mes, 1, tzinfo=TZ) - datetime.timedelta(days=1)
        prox_ano = ano + 1 if mes == 12 else ano
        prox_mes = 1 if mes == 12 else mes + 1
        fim = datetime.datetime(prox_ano, prox_mes, 1, tzinfo=TZ) + datetime.timedelta(days=1)
        f = "%Y-%m-%dT%H:%M:%SZ"
        r = (
            supabase.table("gastos").select("*")
            .gte("created_at", ini.astimezone(datetime.timezone.utc).strftime(f))
            .lt("created_at", fim.astimezone(datetime.timezone.utc).strftime(f))
            .order("id")
            .execute().data or []
        )
    except Exception as e:
        print(f"Erro gastos_do_mes (usando busca completa): {e}")
        r = supabase.table("gastos").select("*").order("id").execute().data or []
    return [x for x in r if mes_de(x) == fm]


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
        g = gastos_do_mes(mes_atual_str())
        t = "Nenhum gasto nesse mês." if not g else "\n".join([f"{x['id']}. {x['descricao']} - R$ {float(x['valor']):.2f} - {x['tipo']}" for x in g])
        await q.message.reply_text(t + "\n\nPra editar, manda: editar 3 45,90\nPra apagar um, manda: apagar 3\nPra apagar despesa, manda: apagar despesa 3\nPra apagar entrada, manda: apagar entrada 3000")
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

    await update.message.reply_text("Tenta:\nentrada salario 3000\nsaida mercado 50\nresumo setembro\nzerar setembro\napagar ultimo\napagar despesa 3\napagar entrada 3000\neditar 12 45,90")


# ---------- EDITAR ----------
async def editar_item(update, context, o):
    ajuda = "Use:\neditar 12 45,90\neditar 12 45,90 Mercado\neditar 12 Mercado\neditar despesa 3 187,40"
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
    if v is None and not nova_desc:
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
        supabase.table(tabela).update({"valor": nv, "descricao": nd}).eq("id", iid).execute()
        if ajuste:
            set_saldo(get_saldo() + ajuste)
    except Exception as e:
        print(f"Erro editar: {e}")
        await update.message.reply_text("Não consegui editar. Tenta de novo.")
        return
    msg = f"✏️ {nome} {iid} atualizado: {nd} - R$ {nv:.2f}"
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Resumido", callback_data=f"resumo_simples:{fm}"), InlineKeyboardButton("🧾 Detalhado", callback_data=f"resumo_detalhado:{fm}")]])
    await update.message.reply_text(f"Resumo de {fm[5:7]}/{fm[:4]} - quer como?", reply_markup=kb)


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
    app.add_handler(CommandHandler("editar", editar_cmd))
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
