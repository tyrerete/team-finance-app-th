# =====================================================================
# ไฟล์ที่ 1: app.py (เวอร์ชันใหม่พร้อมฐานข้อมูล SQLite และรองรับ Render Disk)
# (วางโค้ดนี้ทับไฟล์ app.py เดิม)
# =====================================================================
import uuid
import sqlite3
import json
import os # <-- เพิ่มเข้ามา
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from datetime import datetime
import functools
import io
import csv

# ----------------- INITIALIZE APP & CONFIG -----------------
app = Flask(__name__)
app.secret_key = 'a-very-very-secret-key-for-the-final-version-with-database'
ADMIN_PASSWORD = "1111ab"

# --- NEW: Define database path based on environment ---
# On Render, this will point to the persistent disk at /var/data/database.db
# Locally, it will just be database.db in the same folder.
RENDER_DISK_PATH = '/var/data'
DATABASE_FILE = os.path.join(RENDER_DISK_PATH, 'database.db') if os.path.exists(RENDER_DISK_PATH) else 'database.db'


# ----------------- DATABASE FUNCTIONS -----------------

def get_db():
    """Opens a new database connection if there is none yet for the current application context."""
    db = sqlite3.connect(DATABASE_FILE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Initializes the database schema and default data if it doesn't exist."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # Use a single key-value table to store our main data structure as JSON
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS data_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        # Check if default data exists, if not, insert it
        cursor.execute("SELECT key FROM data_store WHERE key = 'main_db'")
        if cursor.fetchone() is None:
            # This is the initial data structure when the app is first run
            initial_db_state = {
                "members": {
                    "UserA": {"id": "UserA", "share_percentage": 50},
                    "UserB": {"id": "UserB", "share_percentage": 25},
                    "UserC": {"id": "UserC", "share_percentage": 25}
                },
                "categories": {
                    "income_sources": ["รายได้จาก Platform A", "รายได้จาก Platform B", "งานพิเศษ"],
                    "shared_expense_items": ["ค่า Photoshop", "ค่า Gemini API", "ค่าเช่าออฟฟิศ"],
                    "individual_expense_items": ["ซื้อปากกา Stylus", "ค่าเดินทาง", "ค่าอาหารส่วนตัว"]
                },
                "records": {
                    "2025-07": {
                        "locked": False,
                        "admin_note": "นี่คือโน้ตเริ่มต้นสำหรับแอดมิน",
                        "team_note": "นี่คือโน้ตเริ่มต้นสำหรับทีม",
                        "rounds": {}
                    }
                }
            }
            db_json = json.dumps(initial_db_state)
            cursor.execute("INSERT INTO data_store (key, value) VALUES (?, ?)", ('main_db', db_json))
            db.commit()
        db.close()

def load_db_data():
    """Loads the main data structure from the database."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM data_store WHERE key = 'main_db'")
    row = cursor.fetchone()
    db.close()
    if row:
        return json.loads(row['value'])
    return {} # Should not happen after init_db

def save_db_data(data):
    """Saves the main data structure to the database."""
    db = get_db()
    cursor = db.cursor()
    db_json = json.dumps(data)
    cursor.execute("INSERT OR REPLACE INTO data_store (key, value) VALUES (?, ?)", ('main_db', db_json))
    db.commit()
    db.close()

# Initialize the database when the app starts
init_db()

# ----------------- HELPER FUNCTIONS -----------------
def get_latest_month(db_data):
    if not db_data.get('records'):
        return None
    return max(db_data['records'].keys())

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get('logged_in'):
            flash('กรุณาใส่รหัสผ่านเพื่อเข้าสู่โหมดผู้ดูแล', 'warning')
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

# ----------------- BACKEND ROUTES -----------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('เข้าสู่ระบบผู้ดูแลสำเร็จ!', 'success')
            return redirect(url_for('view_dashboard'))
        else:
            flash('รหัสผ่านไม่ถูกต้อง', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('ออกจากระบบแล้ว', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('view_dashboard'))
    return redirect(url_for('login'))

@app.route('/view')
def view_dashboard():
    DB = load_db_data()
    selected_month = request.args.get('month', get_latest_month(DB))
    now = datetime.now()

    if not selected_month or selected_month not in DB.get('records', {}):
        flash('ยังไม่มีข้อมูลเดือน กรุณาเพิ่มเดือนใหม่', 'info')
        return render_template('index.html', db=DB, current_month=None, all_months=sorted(DB.get('records', {}).keys(), reverse=True), now=now)

    month_data = DB['records'][selected_month]
    
    member_count = len(DB["members"])
    total_income = sum(r['amount'] for rd in month_data.get('rounds', {}).values() for r in rd.get('income', []))
    total_shared_expenses = sum(r['amount'] for rd in month_data.get('rounds', {}).values() for r in rd.get('shared_expenses', []))

    all_income_records = [item for rd in month_data.get('rounds', {}).values() for item in rd.get('income', [])]
    all_shared_expense_records = [item for rd in month_data.get('rounds', {}).values() for item in rd.get('shared_expenses', [])]

    summary_data = {
        "total_income": total_income,
        "total_shared_expenses": total_shared_expenses,
        "member_count": len(DB["members"])
    }
    
    breakdown_data = []
    shared_expense_share_equal = total_shared_expenses / member_count if member_count > 0 else 0

    for name, member_data in DB["members"].items():
        percentage = member_data.get('share_percentage', 0)
        income_share = total_income * (percentage / 100)
        
        total_individual_expenses = 0
        all_individual_expenses = []
        for round_data in month_data.get('rounds', {}).values():
            expenses = [exp for exp in round_data.get('individual_expenses', []) if exp.get('member_id') == name]
            total_individual_expenses += sum(exp['amount'] for exp in expenses)
            all_individual_expenses.extend(expenses)

        final_pay = income_share - shared_expense_share_equal - total_individual_expenses
        breakdown_data.append({
            "name": name,
            "income_share": income_share,
            "shared_expense_share": shared_expense_share_equal,
            "individual_expenses_total": total_individual_expenses,
            "final_pay": final_pay,
            "individual_expenses_list": all_individual_expenses,
            "share_percentage": percentage
        })

    return render_template('index.html', 
                           db=DB, 
                           summary=summary_data, 
                           breakdown=breakdown_data,
                           month_data=month_data,
                           current_month=selected_month,
                           all_months=sorted(DB.get('records', {}).keys(), reverse=True),
                           now=now,
                           all_income_records=all_income_records,
                           all_shared_expense_records=all_shared_expense_records)

@app.route('/month/add', methods=['POST'])
@login_required
def add_month():
    DB = load_db_data()
    year = request.form.get('year')
    month = request.form.get('month')
    new_month_key = f"{year}-{month.zfill(2)}"
    if new_month_key not in DB['records']:
        DB['records'][new_month_key] = {"locked": False, "admin_note": "", "team_note": "", "rounds": {}}
        save_db_data(DB)
        flash(f'เพิ่มเดือน {new_month_key} เรียบร้อยแล้ว', 'success')
        return redirect(url_for('view_dashboard', month=new_month_key))
    else:
        flash(f'เดือน {new_month_key} มีอยู่แล้ว', 'warning')
        return redirect(url_for('view_dashboard', month=new_month_key))

@app.route('/month/delete/<month>')
@login_required
def delete_month(month):
    DB = load_db_data()
    if month in DB['records']:
        del DB['records'][month]
        save_db_data(DB)
        flash(f'ลบเดือน {month} เรียบร้อยแล้ว', 'success')
    return redirect(url_for('view_dashboard'))

@app.route('/month/toggle_lock/<month>')
@login_required
def toggle_lock_month(month):
    DB = load_db_data()
    if month in DB['records']:
        DB['records'][month]['locked'] = not DB['records'][month]['locked']
        save_db_data(DB)
        status = "ล็อก" if DB['records'][month]['locked'] else "ปลดล็อก"
        flash(f'{status}การแก้ไขสำหรับเดือน {month} แล้ว', 'info')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/notes/save/<month>', methods=['POST'])
@login_required
def save_notes(month):
    DB = load_db_data()
    if month in DB['records']:
        DB['records'][month]['admin_note'] = request.form.get('admin_note', '')
        DB['records'][month]['team_note'] = request.form.get('team_note', '')
        save_db_data(DB)
        flash('บันทึก Note เรียบร้อยแล้ว', 'success')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/round/add/<month>', methods=['POST'])
@login_required
def add_round(month):
    DB = load_db_data()
    new_round_id = "round" + str(uuid.uuid4())
    DB['records'][month]['rounds'][new_round_id] = {
        "date": request.form['date'],
        "description": request.form['description'],
        "income": [], "shared_expenses": [], "individual_expenses": []
    }
    save_db_data(DB)
    flash('เพิ่มรอบการจ่ายใหม่เรียบร้อย', 'success')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/round/delete/<month>/<round_id>')
@login_required
def delete_round(month, round_id):
    DB = load_db_data()
    if round_id in DB['records'][month]['rounds']:
        del DB['records'][month]['rounds'][round_id]
        save_db_data(DB)
        flash('ลบรอบการจ่ายเรียบร้อย', 'success')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/record/add/<month>/<round_id>/<type>', methods=['POST'])
@login_required
def add_record(month, round_id, type):
    DB = load_db_data()
    amount = float(request.form['amount'])
    new_record = {"id": str(uuid.uuid4()), "amount": amount}
    
    if type == 'income': new_record['source'] = request.form['source']
    elif type == 'shared_expenses': new_record['item'] = request.form['item']
    elif type == 'individual_expenses':
        new_record['item'] = request.form['item']
        new_record['member_id'] = request.form['member_id']
    
    DB['records'][month]['rounds'][round_id][type].append(new_record)
    save_db_data(DB)
    flash('เพิ่มรายการเรียบร้อย', 'success')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/record/delete/<month>/<round_id>/<type>/<id>')
@login_required
def delete_record(month, round_id, type, id):
    DB = load_db_data()
    round_data = DB['records'][month]['rounds'][round_id]
    round_data[type] = [r for r in round_data[type] if r['id'] != id]
    save_db_data(DB)
    flash('ลบรายการเรียบร้อย', 'warning')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/member/add', methods=['GET'])
@login_required
def add_member():
    DB = load_db_data()
    name = request.args.get('name', '').strip()
    month = request.args.get('month')
    if name and name not in DB['members']:
        DB['members'][name] = {'id': name, 'share_percentage': 0}
        save_db_data(DB)
        flash(f'เพิ่มสมาชิก "{name}" เรียบร้อย (ส่วนแบ่ง 0%) กรุณาไปที่ "จัดการสมาชิก" เพื่อตั้งค่าส่วนแบ่ง', 'success')
    else:
        flash(f'ไม่สามารถเพิ่ม "{name}" ได้ อาจมีชื่อซ้ำหรือเป็นค่าว่าง', 'danger')
    return redirect(url_for('view_dashboard', month=month))

@app.route('/member/delete/<name>')
@login_required
def delete_member(name):
    DB = load_db_data()
    if name in DB['members']:
        del DB['members'][name]
        save_db_data(DB)
        flash(f'ลบสมาชิก "{name}" เรียบร้อย กรุณาตรวจสอบผลรวมส่วนแบ่ง', 'warning')
    return redirect(url_for('view_dashboard', month=request.args.get('month')))

@app.route('/members/update_shares', methods=['POST'])
@login_required
def update_member_shares():
    DB = load_db_data()
    total_percentage = 0
    for member_name in DB['members']:
        try:
            share = float(request.form.get(f'share_{member_name}', 0))
            DB['members'][member_name]['share_percentage'] = share
            total_percentage += share
        except (ValueError, TypeError):
            flash(f'ค่าส่วนแบ่งของ {member_name} ไม่ถูกต้อง', 'danger')
            return redirect(url_for('view_dashboard', month=request.args.get('month')))

    if total_percentage != 100:
        flash(f'ผลรวมของส่วนแบ่งไม่เท่ากับ 100% (ได้ {total_percentage}%) กรุณาแก้ไข', 'warning')
    else:
        flash('อัปเดตส่วนแบ่งเรียบร้อยแล้ว!', 'success')
    
    save_db_data(DB)
    return redirect(url_for('view_dashboard', month=request.args.get('month')))

@app.route('/category/add/<type>', methods=['POST'])
@login_required
def add_category(type):
    DB = load_db_data()
    name = request.form['name'].strip()
    if name and name not in DB['categories'][type]:
        DB['categories'][type].append(name)
        save_db_data(DB)
    return redirect(url_for('view_dashboard', month=request.form['month']))

@app.route('/category/delete/<type>/<name>')
@login_required
def delete_category(type, name):
    DB = load_db_data()
    month = request.args.get('month')
    if name in DB['categories'][type]:
        DB['categories'][type].remove(name)
        save_db_data(DB)
    return redirect(url_for('view_dashboard', month=month))

@app.route('/category/edit/<type>', methods=['POST'])
@login_required
def edit_category(type):
    DB = load_db_data()
    month = request.form.get('month')
    old_name = request.form.get('old_name')
    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        flash('ชื่อใหม่ต้องไม่เป็นค่าว่าง', 'danger')
        return redirect(url_for('view_dashboard', month=month))

    if old_name in DB['categories'][type]:
        index = DB['categories'][type].index(old_name)
        DB['categories'][type][index] = new_name
        
        for m_data in DB['records'].values():
            for r_data in m_data['rounds'].values():
                key_to_check = 'source' if type == 'income_sources' else 'item'
                list_to_update = r_data.get('income' if type == 'income_sources' else ('shared_expenses' if type == 'shared_expense_items' else 'individual_expenses'), [])
                for record in list_to_update:
                    if record.get(key_to_check) == old_name:
                        record[key_to_check] = new_name
        save_db_data(DB)
        flash('แก้ไขชื่อหมวดหมู่เรียบร้อย', 'success')
    else:
        flash('ไม่พบหมวดหมู่ที่ต้องการแก้ไข', 'danger')
        
    return redirect(url_for('view_dashboard', month=month))

@app.route('/export/csv/<month>')
@login_required
def export_csv(month):
    DB = load_db_data()
    month_data = DB['records'][month]
    member_count = len(DB["members"])
    
    total_income = sum(r['amount'] for rd in month_data['rounds'].values() for r in rd['income'])
    total_shared = sum(r['amount'] for rd in month_data['rounds'].values() for r in rd['shared_expenses'])
    shared_share_equal = total_shared / member_count if member_count > 0 else 0

    si = io.StringIO()
    cw = csv.writer(si)

    cw.writerow([f'สรุปข้อมูลประจำเดือน {month}'])
    cw.writerow([])
    cw.writerow(['ภาพรวม'])
    cw.writerow(['รายรับรวม', total_income])
    cw.writerow(['ค่าใช้จ่ายรวม (หารเท่ากัน)', total_shared])
    cw.writerow(['จำนวนสมาชิก', len(DB['members'])])
    cw.writerow([])

    cw.writerow(['สรุปยอดของแต่ละคน'])
    header = ['สมาชิก', 'ส่วนแบ่ง (%)', 'ส่วนแบ่งรายได้', 'หัก คชจ. กลาง', 'หัก คชจ. ส่วนตัว', 'คงเหลือสุทธิ']
    cw.writerow(header)

    for name, member_data in DB['members'].items():
        percentage = member_data.get('share_percentage', 0)
        income_share = total_income * (percentage / 100)
        individual_total = sum(r['amount'] for rd in month_data['rounds'].values() for r in rd['individual_expenses'] if r['member_id'] == name)
        final_pay = income_share - shared_share_equal - individual_total
        row = [name, percentage, income_share, shared_share_equal, individual_total, final_pay]
        cw.writerow(row)
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=summary-{month}.csv"}
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
