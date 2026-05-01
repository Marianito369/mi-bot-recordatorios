import os
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "recordatorios.json"
scheduler = BackgroundScheduler()
scheduler.start()

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_reminders(chat_id):
    return load_data().get(str(chat_id), [])

def save_reminders(chat_id, reminders):
    data = load_data()
    data[str(chat_id)] = reminders
    save_data(data)

MENU = ReplyKeyboardMarkup(
    [["➕ Nuevo", "📋 Ver lista"], ["✅ Completar", "🗑 Eliminar"], ["❓ Ayuda"]],
    resize_keyboard=True
)

def start(update: Update, ctx: CallbackContext):
    update.message.reply_text(
        "Hola! Soy tu bot de recordatorios.\nUsá el menú para gestionar tus recordatorios.",
        reply_markup=MENU
    )

def ayuda(update: Update, ctx: CallbackContext):
    update.message.reply_text(
        "Comandos:\n\n"
        "Para crear un recordatorio escribí:\n"
        "/nuevo Titulo | DD/MM/AAAA HH:MM | prioridad | repeticion\n\n"
        "Ejemplo:\n"
        "/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria\n\n"
        "Prioridad: alta, media, baja\n"
        "Repeticion: ninguna, diaria, semanal, mensual",
        reply_markup=MENU
    )

def get_next_fecha(fecha, repeticion):
    if repeticion == "diaria":
        return fecha + relativedelta(days=1)
    elif repeticion == "semanal":
        return fecha + relativedelta(weeks=1)
    elif repeticion == "mensual":
        return fecha + relativedelta(months=1)
    return fecha

def schedule_reminder(bot, chat_id, reminder):
    try:
        fecha = datetime.strptime(reminder["fecha"], "%d/%m/%Y %H:%M")
        if fecha <= datetime.now():
            return
        job_id = str(chat_id) + "_" + reminder["id"]

        def send_alert():
            try:
                prio_emoji = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(reminder["prioridad"], "🔔")
                bot.send_message(
                    chat_id=chat_id,
                    text="🔔 Recordatorio!\n\n" + prio_emoji + " " + reminder["titulo"] +
                         "\nPrioridad: " + reminder["prioridad"] +
                         "\nCategoria: " + reminder.get("categoria", "General")
                )
                if reminder["repeticion"] != "ninguna":
                    nueva = get_next_fecha(fecha, reminder["repeticion"])
                    reminder["fecha"] = nueva.strftime("%d/%m/%Y %H:%M")
                    reminders = get_reminders(chat_id)
                    for r in reminders:
                        if r["id"] == reminder["id"]:
                            r["fecha"] = reminder["fecha"]
                    save_reminders(chat_id, reminders)
                    schedule_reminder(bot, chat_id, reminder)
                else:
                    reminders = get_reminders(chat_id)
                    for r in reminders:
                        if r["id"] == reminder["id"]:
                            r["activo"] = False
                    save_reminders(chat_id, reminders)
            except Exception as e:
                logger.error("Error en send_alert: " + str(e))

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        scheduler.add_job(send_alert, "date", run_date=fecha, id=job_id)
    except Exception as e:
        logger.error("Error en schedule_reminder: " + str(e))

def nuevo(update: Update, ctx: CallbackContext):
    if not ctx.args:
        update.message.reply_text(
            "Ejemplo:\n/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria\n\n"
            "Campos: titulo | fecha hora | prioridad | repeticion",
            reply_markup=MENU
        )
        return

    texto = " ".join(ctx.args)
    partes = [p.strip() for p in texto.split("|")]

    if len(partes) < 2:
        update.message.reply_text("Faltan datos. Ejemplo:\n/nuevo Dentista | 20/06/2025 10:00 | alta | ninguna")
        return

    titulo = partes[0]
    fecha_str = partes[1]
    prioridad = partes[2].lower() if len(partes) > 2 else "media"
    repeticion = partes[3].lower() if len(partes) > 3 else "ninguna"

    try:
        fecha = datetime.strptime(fecha_str, "%d/%m/%Y %H:%M")
    except ValueError:
        update.message.reply_text("Formato de fecha incorrecto. Usá: DD/MM/AAAA HH:MM\nEjemplo: 25/12/2025 08:00")
        return

    if fecha < datetime.now():
        update.message.reply_text("La fecha ya pasó. Ingresá una fecha futura.")
        return

    chat_id = update.effective_chat.id
    reminders = get_reminders(chat_id)
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
    save_reminders(chat_id, reminders)
    schedule_reminder(ctx.bot, chat_id, reminder)

    update.message.reply_text(
        "Recordatorio creado:\n\n"
        "Titulo: " + titulo + "\n"
        "Fecha: " + fecha_str + "\n"
        "Prioridad: " + prioridad + "\n"
        "Repeticion: " + repeticion,
        reply_markup=MENU
    )

def ver_lista(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_reminders(chat_id) if r.get("activo")]
    if not reminders:
        update.message.reply_text("No tenés recordatorios pendientes.", reply_markup=MENU)
        return

    texto = "Tus recordatorios pendientes:\n\n"
    for i, r in enumerate(reminders, 1):
        prio_emoji = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(r["prioridad"], "🔔")
        rep = " (" + r["repeticion"] + ")" if r["repeticion"] != "ninguna" else ""
        texto += str(i) + ". " + prio_emoji + " " + r["titulo"] + "\n   " + r["fecha"] + rep + "\n\n"

    update.message.reply_text(texto, reply_markup=MENU)

def completar(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_reminders(chat_id) if r.get("activo")]
    if not reminders:
        update.message.reply_text("No tenés recordatorios pendientes.", reply_markup=MENU)
        return
    texto = "Cual completaste? Respondé con el número:\n\n"
    for i, r in enumerate(reminders, 1):
        texto += str(i) + ". " + r["titulo"] + " — " + r["fecha"] + "\n"
    ctx.user_data["accion"] = "completar"
    ctx.user_data["lista"] = reminders
    update.message.reply_text(texto)

def eliminar(update: Update, ctx: CallbackContext):
    chat_id = update.effective_chat.id
    reminders = [r for r in get_reminders(chat_id) if r.get("activo")]
    if not reminders:
        update.message.reply_text("No tenés recordatorios para eliminar.", reply_markup=MENU)
        return
    texto = "Cual querés eliminar? Respondé con el número:\n\n"
    for i, r in enumerate(reminders, 1):
        texto += str(i) + ". " + r["titulo"] + " — " + r["fecha"] + "\n"
    ctx.user_data["accion"] = "eliminar"
    ctx.user_data["lista"] = reminders
    update.message.reply_text(texto)

def handle_message(update: Update, ctx: CallbackContext):
    texto = update.message.text.strip()
    chat_id = update.effective_chat.id

    if texto == "➕ Nuevo":
        update.message.reply_text(
            "Para crear un recordatorio escribí:\n/nuevo Titulo | DD/MM/AAAA HH:MM | prioridad | repeticion\n\n"
            "Ejemplo:\n/nuevo Tomar medicina | 25/12/2025 08:00 | alta | diaria"
        )
        return
    elif texto == "📋 Ver lista":
        ver_lista(update, ctx)
        return
    elif texto == "✅ Completar":
        completar(update, ctx)
        return
    elif texto == "🗑 Eliminar":
        eliminar(update, ctx)
        return
    elif texto == "❓ Ayuda":
        ayuda(update, ctx)
        return

    accion = ctx.user_data.get("accion")
    lista = ctx.user_data.get("lista", [])

    if accion and texto.isdigit():
        idx = int(texto) - 1
        if 0 <= idx < len(lista):
            rid = lista[idx]["id"]
            all_reminders = get_reminders(chat_id)
            if accion == "completar":
                for r in all_reminders:
                    if r["id"] == rid:
                        r["activo"] = False
                save_reminders(chat_id, all_reminders)
                update.message.reply_text("Completado: " + lista[idx]["titulo"], reply_markup=MENU)
            elif accion == "eliminar":
                all_reminders = [r for r in all_reminders if r["id"] != rid]
                save_reminders(chat_id, all_reminders)
                update.message.reply_text("Eliminado: " + lista[idx]["titulo"], reply_markup=MENU)
            ctx.user_data.clear()
        else:
            update.message.reply_text("Número inválido.", reply_markup=MENU)
    else:
        update.message.reply_text("No entendí. Usá el menú o escribí /ayuda.", reply_markup=MENU)

def restore_jobs(bot):
    data = load_data()
    for chat_id, reminders in data.items():
        for r in reminders:
            if r.get("activo"):
                try:
                    schedule_reminder(bot, int(chat_id), r)
                except Exception as e:
                    logger.error("Error restaurando job: " + str(e))

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("ayuda", ayuda))
    dp.add_handler(CommandHandler("nuevo", nuevo))
    dp.add_handler(CommandHandler("lista", ver_lista))
    dp.add_handler(CommandHandler("completar", completar))
    dp.add_handler(CommandHandler("eliminar", eliminar))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    restore_jobs(updater.bot)
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
