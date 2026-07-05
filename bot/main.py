import os
import sqlite3
import logging
import asyncio
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# --- SYSTEM CONFIGURATION ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

FULL_NAME, PHONE_NUMBER, UPLOAD_FILE = range(3)
ADMIN_GET_COMMENTS = range(3, 4)

TOKEN = "7978291878:AAFUhlX1mszOfvxMcokboyaniTkL-XnCrlw"

app = Flask('')
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

custom_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
application = Application.builder().token(TOKEN).request(custom_request).build()

# --- DATABASE LAYER ---
def init_db():
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            full_name TEXT,
            phone TEXT,
            file_id TEXT,
            status TEXT DEFAULT 'Under Review',
            admin_comments TEXT DEFAULT 'None'
        )
    """)
    conn.commit()
    conn.close()

# --- USER CORE LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "👋 Welcome to the Semera Logiya Municipality Building Permit Bot.\n\n"
        "Let's get your structural design blueprint submitted. What is your **Full Name**?"
    )
    return FULL_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Thank you. Now, please enter your **Phone Number**:")
    return PHONE_NUMBER

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['phone'] = update.message.text
    await update.message.reply_text(
        "Perfect. Finally, please upload your **Structural Design Blueprint File** (PDF or image document):"
    )
    return UPLOAD_FILE

async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    full_name = context.user_data.get('full_name', 'Unknown')
    phone = context.user_data.get('phone', 'Unknown')
    
    # Bulletproof catch for multiple phone upload formats
    if update.message.document:
        file_id = update.message.document.file_id
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif hasattr(update.message, 'attachment') and update.message.attachment:
        file_id = update.message.attachment.file_id
    else:
        await update.message.reply_text("❌ Telegram could not read this file format. Please try sending it as a standard PDF document or photo.")
        return UPLOAD_FILE

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO applications (user_id, full_name, phone, file_id, status)
            VALUES (?, ?, ?, ?, 'Under Review')
        """, (user_id, full_name, phone, file_id))
        conn.commit()
        await update.message.reply_text(
            "✅ Success! Your application and design files have been securely submitted to the Engineering Department.\n"
            "You will receive a notification here as soon as a review decision is made."
        )
    except Exception as e:
        logger.error(f"Database error during file upload: {e}")
        await update.message.reply_text("❌ System error saving your file to the database. Please try sending it again.")
    finally:
        conn.close()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Application process cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMINISTRATIVE REVIEW LOGIC (PASCODE SECURED) ---
async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Passcode validation check
    if not context.args or context.args[0] != "Semera2026":
        await update.message.reply_text("❌ Unauthorized access. Usage: `/review Semera2026`")
        return

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, status FROM applications WHERE status = 'Under Review'")
    apps = cursor.fetchall()
    conn.close()

    if not apps:
        await update.message.reply_text("📁 No pending applications require review right now.")
        return

    msg = "📋 **Pending Applications:**\n\n"
    for app_item in apps:
        msg += f"🔹 **ID:** {app_item[0]} | **Name:** {app_item[1]}\n"
    msg += "\nTo review a file, type `/view <Application ID>`"
    await update.message.reply_text(msg)

async def admin_view_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.args:
        await update.message.reply_text("Please specify an ID. Usage: `/view 1`")
        return ConversationHandler.END

    app_id = context.args[0]
    context.user_data['review_app_id'] = app_id

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, phone, file_id, status FROM applications WHERE id = ?", (app_id,))
    app_data = cursor.fetchone()
    conn.close()

    if not app_data:
        await update.message.reply_text("❌ Application ID not found.")
        return ConversationHandler.END

    context.user_data['review_target_user'] = app_data[0]
    
    await update.message.reply_text(f"📝 **Reviewing App #{app_id}**\n👤 **Name:** {app_data[1]}\n📞 **Phone:** {app_data[2]}\n🚦 **Status:** {app_data[4]}")
    
    try:
        await context.bot.send_document(chat_id=update.effective_chat.id, document=app_data[3], caption="Submitted Blueprint File")
    except Exception as e:
        logger.error(f"Document upload issue: {e}")

    reply_keyboard = [["Approved", "Rejected", "Under Review"]]
    await update.message.reply_text(
        "Select the updated status for this permit submission:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ADMIN_GET_COMMENTS

async def admin_save_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    app_id = context.user_data.get('review_app_id')
    status = update.message.text
    comments = f"Reviewed status updated to {status}"
    target_user = context.user_data.get('review_target_user')

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET status = ?, admin_comments = ? WHERE id = ?", (status, comments, app_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Record updated. Permit set to **{status}**.", reply_markup=ReplyKeyboardRemove())

    try:
        await context.bot.send_message(
            chat_id=target_user,
            text=f"🔔 **Permit Review Update Notification!**\n\n"
                 f"Your permit application status has been updated to: **{status}**."
        )
    except Exception as e:
        logger.error(f"Could not alert user: {e}")

    return ConversationHandler.END

# --- HANDLER ROUTING CONFIGURATION ---
citizen_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        UPLOAD_FILE: [MessageHandler(filters.Document.ALL | filters.PHOTO, get_file)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
)

admin_handler = ConversationHandler(
    entry_points=[CommandHandler("view", admin_view_app)],
    states={
        ADMIN_GET_COMMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_decision)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
)

application.add_handler(CommandHandler("review", admin_review))
application.add_handler(citizen_handler)
application.add_handler(admin_handler)

# --- SERVER GATEWAY & CRON TARGET ---
@app.route('/', methods=['GET', 'POST'])
def handle_webhook():
    if request.method == 'POST':
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        return 'OK', 200
    # Returns a clear 200 OK message to satisfy cron-job.org
    return "🚀 System Gateway Stream is Live and Listening...", 200

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    loop.run_forever()

if __name__ == "__main__":
    init_db()
    
    from threading import Thread
    t = Thread(target=start_background_loop, args=(loop,))
    t.daemon = True
    t.start()
    
    logger.info("🤖 Engine thread launched successfully. Starting Flask routing listener...")
    app.run(host='0.0.0.0', port=8080)