import os
import sys
import sqlite3
import time

DB_PATH = "/workspaces/semera-logiya-permite-bot/bot/permits.db"
PASSCODE = "SemeraLogiya2026"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def show_applications():
    clear_screen()
    print("=========================================================================")
    print("🏛️  SEMERA LOGIYA MUNICIPALITY - ENGINEERING REVIEW BOARD CONTROL PANEL")
    print("=========================================================================")
    
    if not os.path.exists(DB_PATH):
        print("\n⚠️  No database found yet. Submit an application through the Telegram bot first.\n")
        return False
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, full_name, passport_id, status FROM applications ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            print("\n📋 No building permit applications found in the database.\n")
            return False
            
        print(f"{'ID':<6} | {'APPLICANT FULL NAME':<25} | {'PASSPORT / ID':<15} | {'CURRENT STATUS':<15}")
        print("-" * 73)
        for r in rows:
            print(f"{r['id']:<6} | {r['full_name']:<25} | {r['passport_id']:<15} | {r['status']:<15}")
        print("=========================================================================")
        return True
    except Exception as e:
        print(f"\n❌ Error reading records: {e}\n")
        return False

def update_application_status():
    try:
        app_id = input("\nEnter Target Application ID to update (or press Enter to cancel): ").strip()
        if not app_id:
            return
        
        print("\nSelect New Status:")
        print("1. Approved")
        print("2. Rejected")
        print("3. Under Review")
        choice = input("Choose option (1-3): ").strip()
        
        status_map = {"1": "Approved", "2": "Rejected", "3": "Under Review"}
        if choice not in status_map:
            print("⚠️ Invalid choice. Status update aborted.")
            time.sleep(1.5)
            return
            
        new_status = status_map[choice]
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET status = ? WHERE id = ?", (new_status, int(app_id)))
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"\n✅ Application #{app_id} status updated successfully to '{new_status}'!")
        else:
            print(f"\n⚠️ Application ID #{app_id} not found.")
            
        conn.close()
        time.sleep(2)
    except Exception as e:
        print(f"\n❌ Failed to update application: {e}")
        time.sleep(2)

def main():
    clear_screen()
    print("🔐 SECURE SECURITY AUTHENTICATION REQUIRED")
    entered_passcode = input("Enter Municipality Engineering Passcode: ").strip()
    
    if entered_passcode != PASSCODE:
        print("\n❌ Invalid Passcode. System connection blocked.")
        sys.exit()
        
    while True:
        show_applications()
        print("\n[R] Refresh Records | [U] Update Permit Status | [Q] Exit Dashboard")
        action = input("Select an action: ").strip().lower()
        
        if action == 'r':
            continue
        elif action == 'u':
            update_application_status()
        elif action == 'q':
            print("\nExiting Dashboard Panel safely. Goodbye!")
            break

if __name__ == "__main__":
    main()