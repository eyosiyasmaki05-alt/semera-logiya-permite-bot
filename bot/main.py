import os
import sqlite3
import logging
import asyncio
import threading
import random
from http.server import SimpleHTTPRequestHandler, HTTPServer
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

# Registration States
FULL_NAME, PHONE_NUMBER, UPLOAD_ARCH, UPLOAD_STRUCT, UPLOAD_ELEC, UPLOAD_FOUND, UPLOAD_BOQ = range(7)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7978291878:AAGL1uWtkWgvj9vf91kySu_kZkuk3Abm6nY").strip()

custom_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
application = Application.builder().token(TOKEN).request(custom_request).build()

# --- FAKE WEB SERVER FOR RENDER PORT BINDING ---
def run_health_server():
    port = int(os.getenv("PORT", 8000))
    server_address = ("", port)
    
    class HealthCheckHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is alive and running!")

    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info(f"🌍 Fake web server listening on port {port} to satisfy Render...")
    httpd.serve_forever()

# --- DATABASE LAYER ---
def init_db():
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    
    # Drop old table constraint structure if transitioning to allow multiple distinct tracking numbers
    cursor.execute("PRAGMA table_info(applications)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # If tracking_id doesn't exist, we build a clean scalable schema
    if "tracking_id" not in columns:
        cursor.execute("DROP TABLE IF EXISTS applications")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id TEXT UNIQUE,
                user_id INTEGER,
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
    conn.commit()
    conn.close()

# Helper logic to generate a unique 4-digit token identifier
def generate_4_digit_id():
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    while True:
        potential_id = str(random.randint(1000, 9999))
        cursor.execute("SELECT 1 FROM applications WHERE tracking_id = ?", (potential_id,))
        if not cursor.fetchone():
            conn.close()
            return potential_id

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

def extract_file_id(message):
    if message.document:
        return message.document.file_id
    elif message.photo:
        return message.photo[-1].file_id
    elif message.audio:
        return message.audio.file_id
    elif message.voice:
        return message.voice.file_id
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

    user_id = update.message.from_user.id
    full_name = context.user_data.get('full_name', 'Unknown')
    phone = context.user_data.get('phone', 'Unknown')
    arch_id = context.user_data.get('arch_file_id')
    struct_id = context.user_data.get('struct_file_id')
    elec_id = context.user_data.get('elec_file_id')
    found_id = context.user_data.get('found_file_id')
    boq_id = context.user_data.get('boq_file_id')
    
    # Generate random unique 4-digit tracking value
    tracking_id = generate_4_digit_id()

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO applications (
                tracking_id, user_id, full_name, phone, arch_file_id, struct_file_id, elec_file_id, found_file_id, boq_file_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Under Review')
        """, (tracking_id, user_id, full_name, phone, arch_id, struct_id, elec_id, found_id, boq_id))
        conn.commit()
        await update.message.reply_text(
            f"✅ **Success!** All 5 design files have been securely submitted to the Engineering Department.\n\n"
            f"🎫 Your 4-Digit Application tracking ID is: **{tracking_id}**\n"
            f"Keep this ID handy. You will receive an alert here when a decision is recorded."
        )
    except Exception as e:
        logger.error(f"Database error during insert tracking operations: {e}")
        await update.message.reply_text("❌ System error saving your files. Please try running /start to re-submit.")
    finally:
        conn.close()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Process cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMINISTRATIVE REVIEW LOGIC ---
async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != "Semera2026":
        await update.message.reply_text("❌ Unauthorized access. Usage: `/review Semera2026`")
        return

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    # Pull ALL rows marked Under Review
    cursor.execute("SELECT tracking_id, full_name FROM applications WHERE status = 'Under Review'")
    apps = cursor.fetchall()
    conn.close()

    if not apps:
        await update.message.reply_text("📁 No pending applications require review right now.")
        return

    msg = "📋 **Pending Applications Queue:**\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    for app_item in apps:
        msg += f"🆔 **ID:** `{app_item[0]}` │ 👤 **Name:** {app_item[1]}\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    msg += "To review an applicant's complete files package, type:\n`/view <4-Digit ID>`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_view_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please specify a 4-digit ID. Usage: `/view 1234`")
        return

    target_tracking_id = context.args[0]

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, full_name, phone, arch_file_id, struct_file_id, elec_file_id, found_file_id, boq_file_id, status 
        FROM applications WHERE tracking_id = ?
    """, (target_tracking_id,))
    app_data = cursor.fetchone()
    conn.close()

    if not app_data:
        await update.message.reply_text("❌ That 4-digit application tracking ID was not found.")
        return

    user_id, full_name, phone, arch, struct, elec, found, boq, status = app_data

    await update.message.reply_text(
        f"📝 **Reviewing Package ID: #{target_tracking_id}**\n"
        f"👤 **Name:** {full_name}\n"
        f"📞 **Phone:** {phone}\n"
        f"🚦 **Current Status:** {status}\n\n"
        f"⏳ *Delivering files package...*"
    )

    files_to_send = [
        ("1️⃣ Architectural Drawings", arch),
        ("2️⃣ Structural Drawings", struct),
        ("3️⃣ Electrical Drawings", elec),
        ("4️⃣ Foundation & Reinforcement Details", found),
        ("5️⃣ Bill of Quantities (BoQ)", boq)
    ]

    for label, file_id in files_to_send:
        if file_id:
            try:
                await context.bot.send_document(chat_id=update.effective_chat.id, document=file_id, caption=label)
                await asyncio.sleep(0.4)
            except Exception as e:
                logger.error(f"Error sending file: {e}")

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"status_Approved_{target_tracking_id}_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"status_Rejected_{target_tracking_id}_{user_id}")
        ],
        [
            InlineKeyboardButton("⏳ Keep Under Review", callback_data=f"status_Under Review_{target_tracking_id}_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🏁 **Evaluation Action for Application #{target_tracking_id}:**", reply_markup=reply_markup)

async def admin_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    new_status = data_parts[1]
    tracking_id = data_parts[2]
    target_user = data_parts[3]

    if new_status == "Rejected":
        context.user_data['admin_state'] = 'WAITING_REJECTION_COMMENT'
        context.user_data['handling_rejection_tracking_id'] = tracking_id
        context.user_data['handling_rejection_user_id'] = target_user
        
        await query.edit_message_text(text=f"⚠️ **Application #{tracking_id} set to Rejected.**\nType the reason for rejection directly into this chat:")
        return

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET status = ?, admin_comments = 'None' WHERE tracking_id = ?", (new_status, tracking_id))
    conn.commit()
    conn.close()

    await query.edit_message_text(text=f"🔒 **Decision Registered:** Application #{tracking_id} has been set to **{new_status}**.")

    try:
        await context.bot.send_message(
            chat_id=int(target_user),
            text=f"🔔 **Permit Review Update Notification!**\n\nYour permit application structure **#{tracking_id}** status has been updated to: **{new_status}**."
        )
    except Exception as e:
        logger.error(f"Could not alert user: {e}")

# --- GLOBAL TEXT INTERCEPTOR ROUTER ---
async def handle_global_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('admin_state') == 'WAITING_REJECTION_COMMENT':
        tracking_id = context.user_data.get('handling_rejection_tracking_id')
        target_user = context.user_data.get('handling_rejection_user_id')
        comment_text = update.message.text

        conn = sqlite3.connect("permit_system.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET status = 'Rejected', admin_comments = ? WHERE tracking_id = ?", (comment_text, tracking_id))
        conn.commit()
        conn.close()

        context.user_data.clear() 

        await update.message.reply_text(f"✅ Rejection reason logged successfully for Application #{tracking_id}.")

        try:
            await context.bot.send_message(
                chat_id=int(target_user),
                text=f"❌ **Permit Application Update: REJECTED (ID: #{tracking_id})**\n\n"
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
        UPLOAD_ARCH: [MessageHandler(filters.ALL & ~filters.COMMAND, get_architectural)],
        UPLOAD_STRUCT: [MessageHandler(filters.ALL & ~filters.COMMAND, get_structural)],
        UPLOAD_ELEC: [MessageHandler(filters.ALL & ~filters.COMMAND, get_electrical)],
        UPLOAD_FOUND: [MessageHandler(filters.ALL & ~filters.COMMAND, get_foundation)],
        UPLOAD_BOQ: [MessageHandler(filters.ALL & ~filters.COMMAND, get_boq)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
)

application.add_handler(CommandHandler("review", admin_review))
application.add_handler(CommandHandler("view", admin_view_app))
application.add_handler(CallbackQueryHandler(admin_button_click))

application.add_handler(citizen_handler)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_text))

# --- LIVE ENGINE EXECUTION TARGET ---
if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("🤖 Starting Semera Logiya Permit Bot in Web-Service Polling mode...")
    application.run_polling()