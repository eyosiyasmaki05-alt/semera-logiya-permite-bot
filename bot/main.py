import os
import re
import logging
import sqlite3
from flask import Flask
from threading import Thread
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# System Configurations
DB_PATH = "/workspaces/semera-logiya-permite-bot/bot/permits.db"
ADMIN_PASSCODE = "SemeraLogiya2026"

# Conversation States
# Citizen Flow States
FULL_NAME, PHONE_NUMBER, UPLOAD_FILE = range(3)
# Admin Flow States
ADMIN_GET_COMMENTS = range(3, 4)

# --- FREE 24/7 KEEP-ALIVE SERVER BLOCK ---
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "⚡ Semera Logiya Permit Bot Engine is fully functional and running live!"

def run_flask():
    # Runs the web server on port 8080 (standard cloud deployment port)
    flask_app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """Starts a background thread to prevent the hosting container from sleeping"""
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    logger.info("Background keep-alive heartbeat web server initialized successfully.")

# --- DATABASE SETUP ---
def init_db():
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Core Table with admin_comments column included
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                full_name TEXT,
                phone_number TEXT,
                file_path TEXT,
                status TEXT DEFAULT 'Under Review',
                admin_comments TEXT DEFAULT 'No comments provided.'
            )
        ''')
        
        # Migration Safety Checks
        cursor.execute("PRAGMA table_info(applications)")
        columns = [col[1] for col in cursor.fetchall()]
        if "phone_number" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN phone_number TEXT")
        if "admin_comments" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN admin_comments TEXT DEFAULT 'No comments provided.'")
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- CITIZEN INTAKE FLOW ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear() 
    await update.message.reply_text(
        "🏛️ Welcome to the Semera Logiya Municipality Building Permit System.\n\n"
        "To begin your official application, please enter your **Full Name**:",
        parse_mode="Markdown"
    )
    return FULL_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name_text = update.message.text.strip()
    if not re.match(r"^[a-zA-Z\s]{3,60}$", name_text) or len(name_text.split()) < 2:
        await update.message.reply_text("⚠️ Please enter a valid full name (Letters only):")
        return FULL_NAME

    context.user_data['full_name'] = name_text
    await update.message.reply_text("Thank you. Now, please enter your **Phone Number** (e.g., 0911223344):")
    return PHONE_NUMBER

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_input = update.message.text.strip().replace(" ", "")
    if not re.match(r"^(?:\+251|0)[79]\d{8}$", phone_input):
        await update.message.reply_text("❌ **Invalid Format.** Enter a valid Ethiopian phone number:")
        return PHONE_NUMBER

    context.user_data['phone_number'] = phone_input
    await update.message.reply_text("📋 Final step: Upload your blueprint design file as a **Document/File attachment**:")
    return UPLOAD_FILE

async def get_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    document = update.message.document
    if not document:
        await update.message.reply_text("⚠️ Please attach the design blueprint as a raw document file:")
        return UPLOAD_FILE

    try:
        downloads_dir = "/workspaces/semera-logiya-permite-bot/bot/downloads"
        os.makedirs(downloads_dir, exist_ok=True)
        file_path = os.path.join(downloads_dir, document.file_name)
        
        new_file = await context.bot.get_file(document.file_id)
        await new_file.download_to_drive(file_path)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO applications (user_id, full_name, phone_number, file_path) VALUES (?, ?, ?, ?)",
            (update.message.from_user.id, context.user_data['full_name'], context.user_data['phone_number'], file_path)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text("✅ Application submitted successfully!", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Database Save Error:\n`{str(e)}`", parse_mode="Markdown")
        return ConversationHandler.END

# --- ENGINEER ADMIN FLOW ---
async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or context.args[0] != ADMIN_PASSCODE:
        await update.message.reply_text("❌ Unauthorized connection attempt blocked.")
        return

    if not os.path.exists(DB_PATH):
        await update.message.reply_text("📋 Database is empty. No applications found.")
        return

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, full_name, status FROM applications ORDER BY id DESC LIMIT 15")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("📋 There are currently no applications pending review.")
            return

        board_text = (
            "🏛️ **MUNICIPALITY ENGINEERING REVIEW PANEL**\n"
            "====================================\n\n"
            f"{'ID':<5} | {'APPLICANT NAME':<18} | {'STATUS':<12}\n"
            "------------------------------------\n"
        )
        for r in rows:
            board_text += f"`{r['id']:<5} | {r['full_name'][:16]:<18} | {r['status']:<12}`\n"
        
        board_text += "\n👉 To inspect an application, type:\n`/view ID` (Example: `/view 1`)"
        await update.message.reply_text(board_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Admin board error: {e}")

async def admin_view_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage error. Specify the numerical ID. Example: `/view 1`")
        return ConversationHandler.END

    target_id = int(context.args[0])

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, full_name, phone_number, admin_comments FROM applications WHERE id = ?", (target_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            await update.message.reply_text(f"❌ Application #{target_id} not found.")
            return ConversationHandler.END

        # Store target reference inside the conversation parameters
        context.user_data['admin_target_id'] = target_id
        file_path = row['file_path']

        await update.message.reply_text(
            f"📂 **Reviewing Application #{target_id}**\n"
            f"👤 **Name:** {row['full_name']}\n"
            f"📞 **Phone:** {row['phone_number']}\n"
            f"📝 **Current Comments:** {row['admin_comments']}\n\n"
            f"⬇️ *Transmitting engineering blueprint file attachment below...*"
        )

        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as doc_file:
                await update.message.reply_document(document=doc_file, caption=f"Blueprint for ID #{target_id}")
        else:
            await update.message.reply_text("⚠️ Notice: Physical file missing on hosting machine.")

        reply_keyboard = [["Approved", "Rejected", "Under Review"]]
        await update.message.reply_text(
            f"Select the status resolution action for Application #{target_id}:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return ADMIN_GET_COMMENTS
    except Exception as e:
        logger.error(f"Admin view execution error: {e}")
        return ConversationHandler.END

async def admin_save_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    comments_text = update.message.text.strip()
    app_id = context.user_data.get('admin_target_id')
    new_status = context.user_data.get('admin_selected_status')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE applications SET status = ?, admin_comments = ? WHERE id = ?",
            (new_status, comments_text, int(app_id))
        )
        conn.commit()
        
        cursor.execute("SELECT user_id FROM applications WHERE id = ?", (int(app_id),))
        row = cursor.fetchone()
        conn.close()

        await update.message.reply_text(
            f"✅ **Decision Locked.** Application #{app_id} marked as '{new_status}' with your comments recorded.",
            reply_markup=ReplyKeyboardRemove()
        )

        if row and row['user_id']:
            try:
                await context.bot.send_message(
                    chat_id=row['user_id'],
                    text=f"🔔 **Municipality Notification Update:**\n\n"
                         f"Your application status is now: *{new_status}*.\n"
                         f"💬 **Engineer Remarks:** {comments_text}"
                )
            except Exception:
                pass
            
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Status comment write failure: {e}")
        return ConversationHandler.END

async def admin_intercept_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    status_choice = update.message.text.strip()
    context.user_data['admin_selected_status'] = status_choice
    
    await update.message.reply_text(
        f"✍️ **Status captured: {status_choice}**\n\n"
        f"Please type your formal engineering comments/feedback for this decision below and press Send:",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADMIN_GET_COMMENTS

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Action canceled cleanly.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- INITIALIZATION ENGINE ---
def main():
    # 1. Fire up the local background Flask instance for Uptime pingers
    keep_alive()
    
    # 2. Synchronize internal structures
    init_db()
    
    TOKEN = "7978291878:AAFUhlX1mszOfvxMcokboyaniTkL-XnCrlw" 
    application = Application.builder().token(TOKEN).build()

    # Public Citizen Intake System
    citizen_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            UPLOAD_FILE: [MessageHandler(filters.Document.ALL, get_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    # Managed Engineer Verification System
    admin_handler = ConversationHandler(
        entry_points=[CommandHandler("view", admin_view_app)],
        states={
            ADMIN_GET_COMMENTS: [
                MessageHandler(filters.Text(["Approved", "Rejected", "Under Review"]), admin_intercept_status),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_decision)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    application.add_handler(citizen_handler)
    application.add_handler(admin_handler)
    application.add_handler(CommandHandler("review", admin_review))

    print("🚀 System Live with Web Heartbeat. Engine is securely looping...")
    application.run_polling()

if __name__ == "__main__":
    main()