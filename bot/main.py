import os
import sqlite3
import logging
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
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
ADMIN_REJECTION_COMMENT = range(1) # State for admin conversation flow

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
    # Force clean state entry
    context.user_data.clear()
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
    await update.message.reply_text("❌ Process cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMINISTRATIVE REVIEW LOGIC (PASCODE SECURED) ---
async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def admin_view_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please specify an ID. Usage: `/view 1`")
        return

    app_id = context.args[0]

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, phone, file_id, status FROM applications WHERE id = ?", (app_id,))
    app_data = cursor.fetchone()
    conn.close()

    if not app_data:
        await update.message.reply_text("❌ Application ID not found.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"status_Approved_{app_id}_{app_data[0]}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"status_Rejected_{app_id}_{app_data[0]}")
        ],
        [
            InlineKeyboardButton("⏳ Keep Under Review", callback_data=f"status_Under Review_{app_id}_{app_data[0]}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📝 **Reviewing App #{app_id}**\n👤 **Name:** {app_data[1]}\n📞 **Phone:** {app_data[2]}\n🚦 **Status:** {app_data[4]}"
    )
    
    try:
        await context.bot.send_document(
            chat_id=update.effective_chat.id, 
            document=app_data[3], 
            caption="Review the blueprint file below and tap a decision:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Document upload issue: {e}")
        await update.message.reply_text("Action selection:", reply_markup=reply_markup)

async def admin_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    new_status = data_parts[1]
    app_id = data_parts[2]
    target_user = data_parts[3]

    if new_status == "Rejected":
        # Store context metadata safely
        context.user_data['handling_rejection_app_id'] = app_id
        context.user_data['handling_rejection_user_id'] = target_user
        
        # This message changes state and targets the admin comment block layout safely
        await query.edit_message_caption(caption="⚠️ **Status set to Rejected.**\nNow, type the reason for rejection directly in this chat:")
        return

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET status = ?, admin_comments = 'None' WHERE id = ?", (new_status, app_id))
    conn.commit()
    conn.close()

    await query.edit_message_caption(caption=f"🔒 **Decision Registered:** Set to {new_status}")

    try:
        await context.bot.send_message(
            chat_id=int(target_user),
            text=f"🔔 **Permit Review Update Notification!**\n\nYour permit application status has been updated to: **{new_status}**."
        )
    except Exception as e:
        logger.error(f"Could not alert user: {e}")

async def admin_save_rejection_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    app_id = context.user_data.get('handling_rejection_app_id')
    target_user = context.user_data.get('handling_rejection_user_id')
    
    if not app_id or not target_user:
        await update.message.reply_text("❌ No active application selection found under review. Use `/review` to pick one.")
        return ConversationHandler.END

    comment_text = update.message.text

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET status = 'Rejected', admin_comments = ? WHERE id = ?", (comment_text, app_id))
    conn.commit()
    conn.close()

    context.user_data.clear() # Wipe temporary review values completely clean

    await update.message.reply_text(f"✅ Rejection reason logged successfully for App #{app_id}.")

    try:
        await context.bot.send_message(
            chat_id=int(target_user),
            text=f"❌ **Permit Application Update: REJECTED**\n\n"
                 f"**Reason/Comments from Engineering Dept:**\n> {comment_text}\n\n"
                 f"Please correct these issues and use /start to re-submit your files."
        )
    except Exception as e:
        logger.error(f"Could not alert user: {e}")

    return ConversationHandler.END

# --- HANDLER ROUTING CONFIGURATION ---
citizen_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^/(review|view)'), get_name)],
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'^/(review|view)'), get_phone)],
        UPLOAD_FILE: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_file)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    name="citizen_flow",
    persistent=False
)

# Dedicated isolated ConversationHandler specifically to lock down open admin text commentary
admin_comment_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(admin_button_click, pattern=r"^status_Rejected_")],
    states={
        ADMIN_REJECTION_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_rejection_comment)]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    name="admin_flow",
    persistent=False
)

# Clean, safe linear registrations
application.add_handler(CommandHandler("review", admin_review))
application.add_handler(CommandHandler("view", admin_view_app))
application.add_handler(admin_comment_handler) # Catches rejections first safely within its own tracking state
application.add_handler(CallbackQueryHandler(admin_button_click)) # Handles approvals/under reviews safely
application.add_handler(citizen_handler)

# --- SERVER GATEWAY & CRON TARGET ---
@app.route('/', methods=['GET', 'POST'])
def handle_webhook():
    if request.method == 'POST':
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        return 'OK', 200
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