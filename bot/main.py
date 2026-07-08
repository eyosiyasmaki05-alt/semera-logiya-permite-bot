import os
import sqlite3
import logging
import asyncio
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

# Registration States (Expanded for 5 specific documents)
FULL_NAME, PHONE_NUMBER, UPLOAD_ARCH, UPLOAD_STRUCT, UPLOAD_ELEC, UPLOAD_FOUND, UPLOAD_BOQ = range(7)

# Replace the string below with your active fresh token from @BotFather
TOKEN = "7978291878:AAF0n9kf1InCL_OqzKD-Ar6FclAZ4Ug-n9I"

custom_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
application = Application.builder().token(TOKEN).request(custom_request).build()

# --- DATABASE LAYER ---
def init_db():
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    
    # Check if table already exists to avoid throwing errors on migration
    cursor.execute("PRAGMA table_info(applications)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if not columns:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                full_name TEXT,
                phone TEXT,
                arch_file_id TEXT,
                struct_file_id TEXT,
                elec_file_id TEXT,
                found_file_id TEXT,
                boq_file_id TEXT,
                status TEXT DEFAULT 'Under Review',
                admin_comments TEXT DEFAULT 'None'
            )
        """)
    else:
        # If migrating old database schema gracefully
        if "arch_file_id" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN arch_file_id TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN struct_file_id TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN elec_file_id TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN found_file_id TEXT")
            cursor.execute("ALTER TABLE applications ADD COLUMN boq_file_id TEXT")
            
    conn.commit()
    conn.close()

# --- USER CORE LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to the Semera Logiya Municipality Building Permit Bot.\n\n"
        "Let's get your structural design blueprint submitted. What is your **Full Name**?"
    )
    return FULL_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('admin_state') == 'WAITING_REJECTION_COMMENT':
        await handle_global_text(update, context)
        return ConversationHandler.END

    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Thank you. Now, please enter your **Phone Number**:")
    return PHONE_NUMBER

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('admin_state') == 'WAITING_REJECTION_COMMENT':
        await handle_global_text(update, context)
        return ConversationHandler.END

    context.user_data['phone'] = update.message.text
    await update.message.reply_text(
        "Perfect. Now let's upload the required documents step-by-step.\n\n"
        "1️⃣ Please upload your **Architectural Drawings** (PDF or image document):"
    )
    return UPLOAD_ARCH

# Helper function to extract file tracking ID cleanly without duplicating code blocks
def extract_file_id(message):
    if message.document:
        return message.document.file_id
    elif message.photo:
        return message.photo[-1].file_id
    elif hasattr(message, 'attachment') and message.attachment:
        return message.attachment.file_id
    return None

async def get_architectural(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ File format invalid. Please upload your **Architectural Drawings** as a PDF or photo:")
        return UPLOAD_ARCH
    
    context.user_data['arch_file_id'] = file_id
    await update.message.reply_text("2️⃣ Received! Next, please upload your **Structural Drawings** (PDF or image document):")
    return UPLOAD_STRUCT

async def get_structural(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ File format invalid. Please upload your **Structural Drawings** as a PDF or photo:")
        return UPLOAD_STRUCT
    
    context.user_data['struct_file_id'] = file_id
    await update.message.reply_text("3️⃣ Received! Next, please upload your **Electrical Drawings** (PDF or image document):")
    return UPLOAD_ELEC

async def get_electrical(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ File format invalid. Please upload your **Electrical Drawings** as a PDF or photo:")
        return UPLOAD_ELEC
    
    context.user_data['elec_file_id'] = file_id
    await update.message.reply_text("4️⃣ Received! Next, please upload your **Foundation and Reinforcement Details** (PDF or image document):")
    return UPLOAD_FOUND

async def get_foundation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ File format invalid. Please upload your **Foundation and Reinforcement Details** as a PDF or photo:")
        return UPLOAD_FOUND
    
    context.user_data['found_file_id'] = file_id
    await update.message.reply_text("5️⃣ Received! Last step, please upload your **Bill of Quantities (BoQ)** (PDF or image document):")
    return UPLOAD_BOQ

async def get_boq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ File format invalid. Please upload your **Bill of Quantities (BoQ)** as a PDF or photo:")
        return UPLOAD_BOQ
    
    context.user_data['boq_file_id'] = file_id

    # Gather data parameters for persistence
    user_id = update.message.from_user.id
    full_name = context.user_data.get('full_name', 'Unknown')
    phone = context.user_data.get('phone', 'Unknown')
    arch_id = context.user_data.get('arch_file_id')
    struct_id = context.user_data.get('struct_file_id')
    elec_id = context.user_data.get('elec_file_id')
    found_id = context.user_data.get('found_file_id')
    boq_id = context.user_data.get('boq_file_id')

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO applications (
                user_id, full_name, phone, arch_file_id, struct_file_id, elec_file_id, found_file_id, boq_file_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Under Review')
        """, (user_id, full_name, phone, arch_id, struct_id, elec_id, found_id, boq_id))
        conn.commit()
        await update.message.reply_text(
            "✅ Success! All 5 required architectural and structural engineering design files have been securely submitted to the Engineering Department.\n"
            "You will receive a notification here as soon as a review decision is made."
        )
    except Exception as e:
        logger.error(f"Database error during multi-file upload save operations: {e}")
        await update.message.reply_text("❌ System error saving your files to the database. Please try running /start to re-submit.")
    finally:
        conn.close()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Process cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMINISTRATIVE REVIEW LOGIC (PASSCODE SECURED) ---
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
    cursor.execute("SELECT user_id, full_name, phone, arch_file_id, status FROM applications WHERE id = ?", (app_id,))
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
        # Display primary Architectural file for review context
        await context.bot.send_document(
            chat_id=update.effective_chat.id, 
            document=app_data[3], 
            caption="Review the primary blueprint file below and tap a decision:",
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
        context.user_data['admin_state'] = 'WAITING_REJECTION_COMMENT'
        context.user_data['handling_rejection_app_id'] = app_id
        context.user_data['handling_rejection_user_id'] = target_user
        
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

# --- GLOBAL TEXT INTERCEPTOR ROUTER ---
async def handle_global_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_state') == 'WAITING_REJECTION_COMMENT':
        app_id = context.user_data.get('handling_rejection_app_id')
        target_user = context.user_data.get('handling_rejection_user_id')
        comment_text = update.message.text

        conn = sqlite3.connect("permit_system.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET status = 'Rejected', admin_comments = ? WHERE id = ?", (comment_text, app_id))
        conn.commit()
        conn.close()

        context.user_data.clear() 

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
        return

    await update.message.reply_text("Type `/start` to begin your permit application registration.")

# --- HANDLER ROUTING CONFIGURATION ---
citizen_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        UPLOAD_ARCH: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_architectural)],
        UPLOAD_STRUCT: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_structural)],
        UPLOAD_ELEC: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_electrical)],
        UPLOAD_FOUND: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_foundation)],
        UPLOAD_BOQ: [MessageHandler((filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND, get_boq)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
)

application.add_handler(CommandHandler("review", admin_review))
application.add_handler(CommandHandler("view", admin_view_app))
application.add_handler(CallbackQueryHandler(admin_button_click))
application.add_handler(citizen_handler)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_text))

# --- LIVE POLLING ENGINE TARGET ---
if __name__ == "__main__":
    init_db()
    
    logger.info("🤖 Starting Semera Logiya Permit Bot in local Polling mode...")
    # This loop polls updates continuously directly from the terminal window
    application.run_polling()