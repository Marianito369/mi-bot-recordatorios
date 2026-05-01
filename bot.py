import os
import json
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "recordatorios.json"
scheduler = AsyncIOScheduler()

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_reminders(chat_id):
    data = load_data()
    return data.get(str(chat_id), [])

def save_user_reminders(chat_id, reminders):
    data = load_data()
    data[str(chat_id)] = reminders
    save_data(data)

MENU = ReplyKeyboardMarkup(
    [["➕ Nuevo", "📋 Ver lista"], ["✅ Completar", "🗑 Eliminar"], ["❓ Ayuda"]],
    resize_keyboard=True
)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola! Soy tu bot de recordatorios.\n\nUsá el menú para agregar y gestionar tus recordatorios.",
        reply_markup=MENU
    )

async def ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = (
        "Comandos disponibles:\n\n"
        "➕ *Nuevo* — crear un recordatorio\n"
        "📋 *Ver lista* — ver pendientes\n"
        "✅ *Completar* — marcar como hecho\n"
        "🗑 *Eliminar* — borrar un recordatorio\n\n"
        "Para crear un recordatorio escribí:\n"
        "`/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria`\n\n"
        "Formato: *titulo | fecha hora | prioridad | repeticion*\n"
        "Prioridad: alta, media, baja\n"
        "Repeticion: ninguna, diaria, semanal, mensual"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")

async def nuevo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Ejemplo:\n`/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria`\n\n"
            "Campos: titulo | fecha hora | prioridad | repeticion",
            parse_mode="Markdown"
        )
        return

    texto = " ".join(ctx.args)
    partes = [p.strip() for p in texto.split("|")]

    if len(partes) < 2:
        await update.message.reply_text("Faltan datos. Ejemplo:\n`/nuevo Dentista | 20/06/2025 10:00 | alta | ninguna`", parse_mode="Markdown")
        return

    titulo = partes[0]
    fecha_str = partes[1] if len(partes) > 1 else ""
    prioridad = partes[2].lower() if len(partes) > 2 else "media"
    repeticion = partes[3].lower() if len(partes) > 3 else "ninguna"

    try:
        fecha = datetime.strptime(fecha_str, "%d/%m/%Y %H:%M")
    except ValueError:
        await update.message.reply_text("Formato de fecha incorrecto. Usá: DD/MM/AAAA HH:MM\nEjemplo: 25/12/2025 08:00")
        return

    if fecha < datetime.now():
        await update.message.reply_text("La fecha ya pasó. Por favor ingresá una fecha futura.")
        return

    chat_id = update.effective_chat.id
    reminders = get_user_reminders(chat_id)
    rid = str(int(datetime.now().timestamp()))

    reminder = {
        "id": rid,
        "titulo": titulo,
        "fecha": fecha.strftime("%d/%m/%Y %H:%M"),
        "prioridad": prioridad,
        "repeticion": repeticion,
        "activo": True
    }
    reminders.append(reminder)
    save_user_reminders(chat_id, reminders)

    await schedule_reminder(ctx.application, chat_id, reminder)

    await update.message.reply_text(
        f"Recordatorio creado:\n\n"
        f"Titulo: {titulo}\n"
        f"Fecha: {fecha_str}\n"
        f"Prioridad: {prioridad}\n"
        f"Repeticion: {repeticion}",
        reply_markup=MENU
    )

async def schedule_reminder(app, chat_id, reminder):
    fecha = datetime.strptime(reminder["fecha"], "%d/%m/%Y %H:%M")
    job_id = f"{chat_id}_{reminder['id']}"

    async def send_alert():
        prio_emoji = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(reminder["prioridad"], "🔔")
        await app.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 Recordatorio!\n\n{prio_emoji} {reminder['titulo']}\nPrioridad: {reminder['prioridad']}"
        )
        if reminder["repeticion"] != "ninguna":
            nueva_fecha = get_next_fecha(fecha, reminder["repeticion"])
            reminders = get_user_reminders(chat_id)
            for r in reminders:
                if r["id"] == reminder["id"]:
                    r["fecha"] = nueva_fecha.strftime("%d/%m/%Y %H:%M")
            save_user_reminders(chat_id, reminders)
            reminder["fecha"] = nueva_fecha.strftime("%d/%m/%Y %H:%M")
            await schedule_reminder(app, chat_id, reminder)

    if fecha > datetime.now():
        scheduler.add_job(send_alert, DateTrigger(run_date=fecha), id=job_id, replace_existing=True)

def get_next_fecha(fecha, repeticion):
    from dateutil.relativedelta import relativedelta
    if repeticion == "diaria":
        return fecha.replace(day=fecha.day+1) if fecha.day < 28 else fecha + __import__('datetime').timedelta(days=1)
    elif repeticion == "semanal":
        return fecha + __import__('datetime').timedelta(weeks=1)
    elif repeticion == "mensual":
        return fecha + relativedelta(months=1)
    return fecha

async def ver_lista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_user_reminders(chat_id) if r.get("activo")]
    if not reminders:
        await update.message.reply_text("No tenés recordatorios pendientes.", reply_markup=MENU)
        return

    texto = "Tus recordatorios pendientes:\n\n"
    for i, r in enumerate(reminders, 1):
        prio_emoji = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(r["prioridad"], "🔔")
        rep = f" ({r['repeticion']})" if r["repeticion"] != "ninguna" else ""
        texto += f"{i}. {prio_emoji} {r['titulo']}\n   {r['fecha']}{rep}\n\n"

    await update.message.reply_text(texto, reply_markup=MENU)

async def completar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_user_reminders(chat_id) if r.get("activo")]
    if not reminders:
        await update.message.reply_text("No tenés recordatorios pendientes.", reply_markup=MENU)
        return

    texto = "Qué recordatorio completaste? Respondé con el número:\n\n"
    for i, r in enumerate(reminders, 1):
        texto += f"{i}. {r['titulo']} — {r['fecha']}\n"

    ctx.user_data["accion"] = "completar"
    ctx.user_data["lista"] = reminders
    await update.message.reply_text(texto)

async def eliminar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_user_reminders(chat_id) if r.get("activo")]
    if not reminders:
        await update.message.reply_text("No tenés recordatorios para eliminar.", reply_markup=MENU)
        return

    texto = "Qué recordatorio querés eliminar? Respondé con el número:\n\n"
    for i, r in enumerate(reminders, 1):
        texto += f"{i}. {r['titulo']} — {r['fecha']}\n"

    ctx.user_data["accion"] = "eliminar"
    ctx.user_data["lista"] = reminders
    await update.message.reply_text(texto)

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    if texto == "➕ Nuevo":
        await update.message.reply_text(
            "Para crear un recordatorio escribí:\n`/nuevo Titulo | DD/MM/AAAA HH:MM | prioridad | repeticion`\n\nEjemplo:\n`/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria`",
            parse_mode="Markdown"
        )
        return
    elif texto == "📋 Ver lista":
        await ver_lista(update, ctx)
        return
    elif texto == "✅ Completar":
        await completar(update, ctx)
        return
    elif texto == "🗑 Eliminar":
        await eliminar(update, ctx)
        return
    elif texto == "❓ Ayuda":
        await ayuda(update, ctx)
        return

    accion = ctx.user_data.get("accion")
    lista = ctx.user_data.get("lista", [])

    if accion and texto.isdigit():
        idx = int(texto) - 1
        if 0 <= idx < len(lista):
            rid = lista[idx]["id"]
            all_reminders = get_user_reminders(chat_id)
            if accion == "completar":
                for r in all_reminders:
                    if r["id"] == rid:
                        r["activo"] = False
                save_user_reminders(chat_id, all_reminders)
                await update.message.reply_text(f"Completado: {lista[idx]['titulo']}", reply_markup=MENU)
            elif accion == "eliminar":
                all_reminders = [r for r in all_reminders if r["id"] != rid]
                save_user_reminders(chat_id, all_reminders)
                await update.message.reply_text(f"Eliminado: {lista[idx]['titulo']}", reply_markup=MENU)
            ctx.user_data.clear()
        else:
            await update.message.reply_text("Número inválido.", reply_markup=MENU)
    else:
        await update.message.reply_text("No entendí. Usá el menú o escribí /ayuda.", reply_markup=MENU)

async def restore_jobs(app):
    data = load_data()
    for chat_id, reminders in data.items():
        for r in reminders:
            if r.get("activo"):
                try:
                    fecha = datetime.strptime(r["fecha"], "%d/%m/%Y %H:%M")
                    if fecha > datetime.now():
                        await schedule_reminder(app, int(chat_id), r)
                except Exception as e:
                    logger.error(f"Error restaurando job: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("nuevo", nuevo))
    app.add_handler(CommandHandler("lista", ver_lista))
    app.add_handler(CommandHandler("completar", completar))
    app.add_handler(CommandHandler("eliminar", eliminar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler.start()
    app.post_init = restore_jobs
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
