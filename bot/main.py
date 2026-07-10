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
FULL_NAME, PHONE_NUMBER, CHOOSE_DOC, UPLOAD_SINGLE_DOC = range(4)

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

# --- DATABASE LAYER (SAFE & PERSISTENT) ---
def init_db():
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    # Safely creates the schema without erasing your data during server reboots
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT UNIQUE,
            user_id INTEGER,
            full_name TEXT,
            phone TEXT,
            doc_type TEXT,
            file_id TEXT,
            status TEXT DEFAULT 'Under Review',
            admin_comments TEXT DEFAULT 'None'
        )
    """)
    conn.commit()
    conn.close()

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
        "Let's create your submission profile first. Please type your **Full Name**:"
    )
    return FULL_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('admin_state') in ['WAITING_REJECTION_COMMENT', 'WAITING_ENGINEER_NAME', 'WAITING_ENGINEER_PHONE']:
        await handle_global_text(update, context)
        return ConversationHandler.END

    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Thank you! Now, please enter your **Phone Number**:")
    return PHONE_NUMBER

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data.get('admin_state') in ['WAITING_REJECTION_COMMENT', 'WAITING_ENGINEER_NAME', 'WAITING_ENGINEER_PHONE']:
        await handle_global_text(update, context)
        return ConversationHandler.END

    context.user_data['phone'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("📐 Architectural Drawings", callback_data="doc_Architectural Drawings")],
        [InlineKeyboardButton("🏗️ Structural Drawings", callback_data="doc_Structural Drawings")],
        [InlineKeyboardButton("⚡ Electrical Drawings", callback_data="doc_Electrical Drawings")],
        [InlineKeyboardButton("🧱 Foundation Details", callback_data="doc_Foundation Details")],
        [InlineKeyboardButton("📊 Bill of Quantities (BoQ)", callback_data="doc_Bill of Quantities (BoQ)")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📝 **Profile Details Captured:**\n"
        f"👤 Name: {context.user_data['full_name']}\n"
        f"📞 Phone: {context.user_data['phone']}\n\n"
        f"Please select the **one document** you want to attach to this application profile:",
        reply_markup=reply_markup
    )
    return CHOOSE_DOC

async def handle_doc_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    chosen_doc = query.data.split("_")[1]
    context.user_data['chosen_doc_type'] = chosen_doc
    
    await query.edit_message_text(
        text=f"📂 You selected: **{chosen_doc}**\n\nPlease upload or attach your file (PDF or Image) directly now:"
    )
    return UPLOAD_SINGLE_DOC

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

async def handle_single_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = extract_file_id(update.message)
    if not file_id:
        await update.message.reply_text("❌ Invalid file format. Please upload your document file directly:")
        return UPLOAD_SINGLE_DOC
    
    full_name = context.user_data.get('full_name', 'Unknown')
    phone = context.user_data.get('phone', 'Unknown')
    doc_type = context.user_data.get('chosen_doc_type')
    user_id = update.message.from_user.id
    tracking_id = generate_4_digit_id()

    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO applications (tracking_id, user_id, full_name, phone, doc_type, file_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Under Review')
        """, (tracking_id, user_id, full_name, phone, doc_type, file_id))
        conn.commit()
        
        await update.message.reply_text(
            f"✅ **Submission Successful!** Your application has been logged.\n\n"
            f"👤 **Applicant Name:** {full_name}\n"
            f"📞 **Phone Number:** {phone}\n"
            f"📋 **Document Category:** {doc_type}\n"
            f"🎫 **Tracking ID:** `{tracking_id}`\n\n"
            f"The engineering department will notify you directly here once evaluated."
        )
    except Exception as e:
        logger.error(f"Database save error: {e}")
        await update.message.reply_text("❌ An unexpected database error occurred. Type /start to try again.")
    finally:
        conn.close()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Registration cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- ADMINISTRATIVE CONTROL PANEL ---
async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] != "Semera2026":
        await update.message.reply_text("❌ Unauthorized dashboard password.")
        return

    keyboard = [
        [
            InlineKeyboardButton("📁 View Pending Queue", callback_data="nav_pending"),
            InlineKeyboardButton("📜 View Past Applications", callback_data="nav_past")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎛️ **Semera Logiya Engineering Management Console**\nSelect a collection to filter records:", reply_markup=reply_markup)

async def admin_navigation_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    nav_target = query.data.split("_")[1]
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    
    if nav_target == "pending":
        cursor.execute("SELECT tracking_id, full_name, doc_type FROM applications WHERE status = 'Under Review'")
        apps = cursor.fetchall()
        title_header = "📁 **Current Pending Queue (Under Review):**\n"
    else:
        cursor.execute("SELECT tracking_id, full_name, doc_type, status FROM applications WHERE status != 'Under Review'")
        apps = cursor.fetchall()
        title_header = "📜 **Historical Applications Log:**\n"
        
    conn.close()

    if not apps:
        await query.edit_message_text(text=f"{title_header}━━━━━━━━━━━━━━━━━━━\n🟩 The requested log folder is empty.\n━━━━━━━━━━━━━━━━━━━")
        return

    msg = title_header
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    for app_item in apps:
        if nav_target == "pending":
            msg += f"🆔 `/{app_item[0]}` │ 👤 {app_item[1]} │ 📐 {app_item[2]}\n"
        else:
            msg += f"🆔 `/{app_item[0]}` │ 👤 {app_item[1]} [{app_item[3]}]\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 *Tip: Click or type the blue command number directly (e.g. /1234) to open and inspect that specific document entry.*"
    
    await query.edit_message_text(text=msg, parse_mode="Markdown")

async def admin_view_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Strips the leading slash from the message command shortcut to read the raw ID values
    target_tracking_id = update.message.text.replace("/", "").strip()
    
    conn = sqlite3.connect("permit_system.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, phone, doc_type, file_id, status FROM applications WHERE tracking_id = ?", (target_tracking_id,))
    app_data = cursor.fetchone()
    conn.close()

    if not app_data:
        await update.message.reply_text("❌ Tracking ID could not be found.")
        return

    user_id, full_name, phone, doc_type, file_id, status = app_data

    await update.message.reply_text(
        f"🔍 **Reviewing ID:** #{target_tracking_id}\n\n"
        f"👤 **Applicant Name:** {full_name}\n"
        f"📞 **Applicant Phone:** {phone}\n"
        f"📂 **Document Type:** {doc_type}\n"
        f"🚦 **Application Status:** {status}"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"status_Approved_{target_tracking_id}_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"status_Rejected_{target_tracking_id}_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if file_id:
        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id, 
                document=file_id, 
                caption=f"Attachment File for Application #{target_tracking_id}",
                reply_markup=reply_markup
            )
        except Exception:
            await update.message.reply_text("Action selection panel:", reply_markup=reply_markup)

async def admin_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    new_status = data_parts[1]
    tracking_id = data_parts[2]
    target_user = data_parts[3]

    if new_status == "Rejected":
        context.user_data['admin_state'] = 'WAITING_REJECTION_COMMENT'
        context.user_data['handling_tracking_id'] = tracking_id
        context.user_data['handling_user_id'] = target_user
        await query.edit_message_caption(caption=f"⚠️ **Application #{tracking_id} set to Rejected.**\nType the rejection comment below:")
        return

    if new_status == "Approved":
        context.user_data['admin_state'] = 'WAITING_ENGINEER_NAME'
        context.user_data['handling_tracking_id'] = tracking_id
        context.user_data['handling_user_id'] = target_user
        await query.edit_message_caption(caption=f"⚙️ **Application #{tracking_id} Approved.**\nStep 1: Please type the **Full Name** of the approving Engineer:")
        return

# --- GLOBAL TEXT INTERCEPTOR ROUTER ---
async def handle_global_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('admin_state')
    
    if state == 'WAITING_REJECTION_COMMENT':
        tracking_id = context.user_data.get('handling_tracking_id')
        target_user = context.user_data.get('handling_user_id')
        comment_text = update.message.text

        conn = sqlite3.connect("permit_system.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET status = 'Rejected', admin_comments = ? WHERE tracking_id = ?", (comment_text, tracking_id))
        conn.commit()
        conn.close()

        context.user_data.clear()
        await update.message.reply_text(f"✅ Rejection reason logged successfully for #{tracking_id}.")

        try:
            await context.bot.send_message(
                chat_id=int(target_user),
                text=f"❌ **Permit Application Update: REJECTED (ID: #{tracking_id})**\n\n"
                     f"**Reason/Comments from Engineering Dept:**\n> {comment_text}\n\n"
                     f"Please correct the files and use /start to re-submit."
            )
        except Exception:
            pass
        return

    elif state == 'WAITING_ENGINEER_NAME':
        context.user_data['engineer_name'] = update.message.text
        context.user_data['admin_state'] = 'WAITING_ENGINEER_PHONE'
        await update.message.reply_text("Step 2: Now, please type the **Phone Number** for this Engineer:")
        return

    elif state == 'WAITING_ENGINEER_PHONE':
        eng_phone = update.message.text
        eng_name = context.user_data.get('engineer_name')
        tracking_id = context.user_data.get('handling_tracking_id')
        target_user = context.user_data.get('handling_user_id')

        conn = sqlite3.connect("permit_system.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET status = 'Approved', admin_comments = ? WHERE tracking_id = ?", (f"Approved by {eng_name} ({eng_phone})", tracking_id))
        conn.commit()
        conn.close()

        context.user_data.clear()
        await update.message.reply_text(f"✅ Application #{tracking_id} approval completed. Notification sent.")

        try:
            await context.bot.send_message(
                chat_id=int(target_user),
                text=f"🎉 **Permit Application Update: APPROVED!**\n\n"
                     f"Your permit application **#{tracking_id}** has been officially approved.\n\n"
                     f"👤 **Approving Engineer:** {eng_name}\n"
                     f"📞 **Phone Number:** {eng_phone}\n\n"
                     f"ℹ️ **Next Steps:** Please print out your submitted document file physical copy and meet with Engineer {eng_name} using the phone number listed above to collect your signed permit."
            )
        except Exception:
            pass
        return

    await update.message.reply_text("Type `/start` to begin your permit application registration.")

# --- HANDLER ROUTING CONFIGURATION ---
citizen_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
        CHOOSE_DOC: [CallbackQueryHandler(handle_doc_choice, pattern="^doc_")],
        UPLOAD_SINGLE_DOC: [MessageHandler(filters.ALL & ~filters.COMMAND, handle_single_upload)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
)

application.add_handler(CommandHandler("review", admin_review))
application.add_handler(CallbackQueryHandler(admin_navigation_click, pattern="^nav_"))
application.add_handler(CallbackQueryHandler(admin_button_click, pattern="^status_"))
# Handles dynamic commands like /1234 to pull database contents automatically
application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/\d{4}$'), admin_view_app_shortcut))

application.add_handler(citizen_handler)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_text))

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    logger.info("🤖 Starting Semera Logiya Permit Bot...")
    application.run_polling()