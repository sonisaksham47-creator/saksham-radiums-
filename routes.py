from app import app
from flask import render_template, redirect, url_for, request, flash, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Shop, Product, Inventory, Sale
from datetime import datetime, date
from functools import wraps
from sqlalchemy import func
import csv
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

# ----- Role-based access decorators -----
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_or_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'manager']:
            flash('Access denied.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def shop_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role == 'admin':
            return f(*args, **kwargs)
        if current_user.shop_id is None:
            flash('You are not assigned to a shop.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ----- Root redirect -----
@app.route('/')
def index():
    return redirect(url_for('login'))

# ----- Authentication -----
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('shop_dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ----- Delete Account (removed from UI, but kept if you want to re-enable) -----
# (We removed the button, but the route can stay)
@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = current_user
    if user.role == 'admin' and User.query.filter_by(role='admin').count() == 1:
        flash('Cannot delete the only admin account.', 'danger')
        return redirect(url_for('admin_dashboard' if user.role == 'admin' else 'shop_dashboard'))
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash('Your account has been permanently deleted.', 'success')
    return redirect(url_for('login'))

# ----- Admin dashboard -----
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_shops = Shop.query.count()
    total_sales = db.session.query(func.sum(Sale.quantity)).scalar() or 0
    low_stock_items = Inventory.query.filter(Inventory.quantity < 5).all()
    shops = Shop.query.all()
    return render_template('admin_dashboard.html',
                           total_shops=total_shops,
                           total_sales=total_sales,
                           low_stock_items=low_stock_items,
                           shops=shops)

@app.route('/admin/create_shop', methods=['GET', 'POST'])
@login_required
@admin_required
def create_shop():
    if request.method == 'POST':
        shop_name = request.form['shop_name']
        location = request.form['location']
        shop = Shop(shop_name=shop_name, location=location)
        db.session.add(shop)
        db.session.commit()
        flash('Shop created successfully', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_shop_user.html', type='shop')

@app.route('/admin/delete_shop/<int:id>')
@login_required
@admin_required
def delete_shop(id):
    shop = Shop.query.get_or_404(id)
    if User.query.filter_by(shop_id=id).count() > 0:
        flash('Cannot delete shop with existing users. Remove users first.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if Inventory.query.filter_by(shop_id=id).count() > 0:
        flash('Cannot delete shop with existing inventory. Clear inventory first.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if Sale.query.filter_by(shop_id=id).count() > 0:
        flash('Cannot delete shop with existing sales. Delete sales first.', 'danger')
        return redirect(url_for('admin_dashboard'))
    db.session.delete(shop)
    db.session.commit()
    flash('Shop deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/create_user', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    shops = Shop.query.all()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        shop_id = request.form.get('shop_id') if role != 'admin' else None
        if role != 'admin' and not shop_id:
            flash('Please select a shop for non-admin users', 'danger')
            return render_template('create_shop_user.html', type='user', shops=shops)
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists', 'danger')
            return render_template('create_shop_user.html', type='user', shops=shops)
        user = User(username=username,
                    password_hash=generate_password_hash(password),
                    role=role,
                    shop_id=shop_id)
        db.session.add(user)
        db.session.commit()
        flash('User created successfully', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_shop_user.html', type='user', shops=shops)

# ----- User management (admin only) -----
@app.route('/admin/users')
@login_required
@admin_required
def list_users():
    users = User.query.all()
    shops = Shop.query.all()
    return render_template('users.html', users=users, shops=shops)

@app.route('/admin/user/delete/<int:id>')
@login_required
@admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.role == 'admin' and User.query.filter_by(role='admin').count() == 1:
        flash('Cannot delete the only admin account.', 'danger')
        return redirect(url_for('list_users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted.', 'success')
    return redirect(url_for('list_users'))

# ----- Product management (admin only) -----
@app.route('/products', methods=['GET', 'POST'])
@login_required
@admin_required
def products():
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        product = Product(name=name, price=price)
        db.session.add(product)
        db.session.commit()
        flash('Product added', 'success')
        return redirect(url_for('products'))
    products_list = Product.query.all()
    return render_template('products.html', products=products_list)

@app.route('/products/update/<int:id>', methods=['POST'])
@login_required
@admin_required
def update_product(id):
    product = Product.query.get_or_404(id)
    product.name = request.form['name']
    product.price = float(request.form['price'])
    db.session.commit()
    flash('Product updated', 'success')
    return redirect(url_for('products'))

@app.route('/products/delete/<int:id>')
@login_required
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted', 'success')
    return redirect(url_for('products'))

# ----- Inventory management (admin or manager) with search -----
@app.route('/inventory')
@login_required
@manager_or_admin_required
def inventory():
    search = request.args.get('search', '')
    if current_user.role == 'admin':
        inventories_query = Inventory.query.join(Product)
        if search:
            inventories_query = inventories_query.filter(Product.name.ilike(f'%{search}%'))
        inventories = inventories_query.all()
        shops = Shop.query.all()
        products = Product.query.all()
    else:
        inventories_query = Inventory.query.filter_by(shop_id=current_user.shop_id).join(Product)
        if search:
            inventories_query = inventories_query.filter(Product.name.ilike(f'%{search}%'))
        inventories = inventories_query.all()
        shops = None
        products = Product.query.all()
    return render_template('inventory.html', inventories=inventories, shops=shops, products=products, search=search)

@app.route('/inventory/add', methods=['POST'])
@login_required
@manager_or_admin_required
def add_inventory():
    product_id = request.form['product_id']
    shop_id = request.form.get('shop_id') if current_user.role == 'admin' else current_user.shop_id
    quantity = int(request.form['quantity'])
    if not shop_id:
        flash('Shop not specified', 'danger')
        return redirect(url_for('inventory'))
    inventory = Inventory.query.filter_by(product_id=product_id, shop_id=shop_id).first()
    if inventory:
        inventory.quantity += quantity
    else:
        inventory = Inventory(product_id=product_id, shop_id=shop_id, quantity=quantity)
        db.session.add(inventory)
    db.session.commit()
    flash('Stock added', 'success')
    return redirect(url_for('inventory'))

@app.route('/inventory/update', methods=['POST'])
@login_required
@manager_or_admin_required
def update_inventory():
    inv_id = request.form['inventory_id']
    new_qty = int(request.form['quantity'])
    inventory = Inventory.query.get_or_404(inv_id)
    if current_user.role == 'manager' and inventory.shop_id != current_user.shop_id:
        flash('Access denied', 'danger')
        return redirect(url_for('inventory'))
    inventory.quantity = new_qty
    db.session.commit()
    flash('Inventory updated', 'success')
    return redirect(url_for('inventory'))

@app.route('/inventory/delete/<int:id>', methods=['POST'])
@login_required
@manager_or_admin_required
def delete_inventory(id):
    inventory = Inventory.query.get_or_404(id)
    if current_user.role == 'manager' and inventory.shop_id != current_user.shop_id:
        flash('Access denied', 'danger')
        return redirect(url_for('inventory'))
    db.session.delete(inventory)
    db.session.commit()
    flash('Inventory item deleted successfully', 'success')
    return redirect(url_for('inventory'))

# ----- Sales system -----
@app.route('/sales', methods=['GET', 'POST'])
@login_required
@manager_or_admin_required
def sales():
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity')
        if not product_id or not quantity:
            flash('Missing product or quantity', 'danger')
            return redirect(url_for('sales'))
        try:
            quantity = int(quantity)
        except ValueError:
            flash('Invalid quantity', 'danger')
            return redirect(url_for('sales'))

        if current_user.role == 'admin':
            shop_id = request.form.get('shop_id')
            if not shop_id:
                flash('Please select a shop', 'danger')
                return redirect(url_for('sales'))
        else:
            shop_id = current_user.shop_id

        inventory = Inventory.query.filter_by(product_id=product_id, shop_id=shop_id).first()
        if not inventory or inventory.quantity < quantity:
            flash('Insufficient stock', 'danger')
            return redirect(url_for('sales'))

        sale = Sale(product_id=product_id, shop_id=shop_id, quantity=quantity)
        inventory.quantity -= quantity
        db.session.add(sale)
        db.session.commit()
        flash('Sale recorded', 'success')
        return redirect(url_for('sales'))

    # GET
    if current_user.role == 'admin':
        sales_list = Sale.query.all()
        shops = Shop.query.all()
        inventories = Inventory.query.filter(Inventory.quantity > 0).all()
    else:
        sales_list = Sale.query.filter_by(shop_id=current_user.shop_id).all()
        shops = None
        inventories = Inventory.query.filter_by(shop_id=current_user.shop_id).filter(Inventory.quantity > 0).all()
    products = Product.query.all()
    return render_template('sales.html', sales=sales_list, products=products, shops=shops, inventories=inventories)

@app.route('/sales/delete/<int:id>', methods=['POST'])
@login_required
@manager_or_admin_required
def delete_sale(id):
    sale = Sale.query.get_or_404(id)
    if current_user.role == 'manager' and sale.shop_id != current_user.shop_id:
        flash('Access denied', 'danger')
        return redirect(url_for('sales'))
    inventory = Inventory.query.filter_by(product_id=sale.product_id, shop_id=sale.shop_id).first()
    if inventory:
        inventory.quantity += sale.quantity
    db.session.delete(sale)
    db.session.commit()
    flash('Sale deleted and inventory restored', 'success')
    return redirect(url_for('sales'))

# ----- Shop dashboard (for manager/staff) -----
@app.route('/shop/dashboard')
@login_required
@shop_required
def shop_dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    shop_id = current_user.shop_id
    inventories = Inventory.query.filter_by(shop_id=shop_id).all()
    today = date.today()
    daily_sales = Sale.query.filter(Sale.shop_id == shop_id, func.date(Sale.date) == today).all()
    total_daily = sum(s.quantity for s in daily_sales)
    return render_template('shop_dashboard.html', inventories=inventories,
                           daily_sales=daily_sales, total_daily=total_daily)

# ----- Reports (web + PDF + CSV) -----
@app.route('/reports')
@login_required
@manager_or_admin_required
def reports():
    if current_user.role == 'admin':
        shops = Shop.query.all()
        shop_sales = []
        for shop in shops:
            total_units = 0
            total_revenue = 0.0
            sales = Sale.query.filter_by(shop_id=shop.id).all()
            for sale in sales:
                product = Product.query.get(sale.product_id)
                if product:
                    total_units += sale.quantity
                    total_revenue += product.price * sale.quantity
            shop_sales.append((shop.shop_name, total_units, total_revenue))

        sales_all = Sale.query.all()
        daily_dict = {}
        for sale in sales_all:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily = [(day, data['units'], data['revenue']) for day, data in sorted(daily_dict.items())]

        monthly_dict = {}
        for sale in sales_all:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly = [(month, data['units'], data['revenue']) for month, data in sorted(monthly_dict.items())]
    else:
        shop_id = current_user.shop_id
        shops = None
        shop_sales = None
        sales_shop = Sale.query.filter_by(shop_id=shop_id).all()
        daily_dict = {}
        for sale in sales_shop:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily = [(day, data['units'], data['revenue']) for day, data in sorted(daily_dict.items())]

        monthly_dict = {}
        for sale in sales_shop:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly = [(month, data['units'], data['revenue']) for month, data in sorted(monthly_dict.items())]

    return render_template('reports.html', shop_sales=shop_sales, daily=daily, monthly=monthly, shops=shops)

@app.route('/reports/pdf')
@login_required
@manager_or_admin_required
def reports_pdf():
    # Reuse the same data gathering as reports()
    if current_user.role == 'admin':
        shops = Shop.query.all()
        shop_data = []
        for shop in shops:
            total_units = 0
            total_revenue = 0.0
            sales = Sale.query.filter_by(shop_id=shop.id).all()
            for sale in sales:
                product = Product.query.get(sale.product_id)
                if product:
                    total_units += sale.quantity
                    total_revenue += product.price * sale.quantity
            shop_data.append([shop.shop_name, total_units, f"₹{total_revenue:.2f}"])
        sales_all = Sale.query.all()
        daily_dict = {}
        for sale in sales_all:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily_data = [[day, data['units'], f"₹{data['revenue']:.2f}"] for day, data in sorted(daily_dict.items())]
        monthly_dict = {}
        for sale in sales_all:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly_data = [[month, data['units'], f"₹{data['revenue']:.2f}"] for month, data in sorted(monthly_dict.items())]
    else:
        shop_id = current_user.shop_id
        sales_shop = Sale.query.filter_by(shop_id=shop_id).all()
        daily_dict = {}
        for sale in sales_shop:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily_data = [[day, data['units'], f"₹{data['revenue']:.2f}"] for day, data in sorted(daily_dict.items())]
        monthly_dict = {}
        for sale in sales_shop:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly_data = [[month, data['units'], f"₹{data['revenue']:.2f}"] for month, data in sorted(monthly_dict.items())]
        shop_data = None

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Sales Report", styles['Title']))
    elements.append(Spacer(1, 0.2*inch))

    if current_user.role == 'admin' and shop_data:
        elements.append(Paragraph("Sales per Shop", styles['Heading2']))
        table_data = [["Shop", "Units Sold", "Revenue"]] + shop_data
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.2*inch))

    elements.append(Paragraph("Daily Summary", styles['Heading2']))
    daily_table_data = [["Date", "Units", "Revenue"]] + daily_data
    daily_table = Table(daily_table_data)
    daily_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 1, colors.black)
    ]))
    elements.append(daily_table)
    elements.append(Spacer(1, 0.2*inch))

    elements.append(Paragraph("Monthly Summary", styles['Heading2']))
    monthly_table_data = [["Month", "Units", "Revenue"]] + monthly_data
    monthly_table = Table(monthly_table_data)
    monthly_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 1, colors.black)
    ]))
    elements.append(monthly_table)

    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()

    response = make_response(pdf_data)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.pdf'
    return response

@app.route('/reports/csv')
@login_required
@manager_or_admin_required
def reports_csv():
    # Reuse same data logic as PDF (shortened for brevity)
    if current_user.role == 'admin':
        shops = Shop.query.all()
        shop_rows = []
        for shop in shops:
            total_units = 0
            total_revenue = 0.0
            sales = Sale.query.filter_by(shop_id=shop.id).all()
            for sale in sales:
                product = Product.query.get(sale.product_id)
                if product:
                    total_units += sale.quantity
                    total_revenue += product.price * sale.quantity
            shop_rows.append([shop.shop_name, total_units, total_revenue])
        sales_all = Sale.query.all()
        daily_dict = {}
        for sale in sales_all:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily_rows = [[day, data['units'], data['revenue']] for day, data in sorted(daily_dict.items())]
        monthly_dict = {}
        for sale in sales_all:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly_rows = [[month, data['units'], data['revenue']] for month, data in sorted(monthly_dict.items())]
    else:
        shop_id = current_user.shop_id
        sales_shop = Sale.query.filter_by(shop_id=shop_id).all()
        daily_dict = {}
        for sale in sales_shop:
            day = sale.date.strftime('%Y-%m-%d')
            product = Product.query.get(sale.product_id)
            if product:
                if day not in daily_dict:
                    daily_dict[day] = {'units': 0, 'revenue': 0.0}
                daily_dict[day]['units'] += sale.quantity
                daily_dict[day]['revenue'] += product.price * sale.quantity
        daily_rows = [[day, data['units'], data['revenue']] for day, data in sorted(daily_dict.items())]
        monthly_dict = {}
        for sale in sales_shop:
            month = sale.date.strftime('%Y-%m')
            product = Product.query.get(sale.product_id)
            if product:
                if month not in monthly_dict:
                    monthly_dict[month] = {'units': 0, 'revenue': 0.0}
                monthly_dict[month]['units'] += sale.quantity
                monthly_dict[month]['revenue'] += product.price * sale.quantity
        monthly_rows = [[month, data['units'], data['revenue']] for month, data in sorted(monthly_dict.items())]
        shop_rows = None

    output = BytesIO()
    writer = csv.writer(output)
    if current_user.role == 'admin' and shop_rows:
        writer.writerow(['Sales per Shop'])
        writer.writerow(['Shop', 'Units Sold', 'Revenue'])
        for row in shop_rows:
            writer.writerow([row[0], row[1], f"{row[2]:.2f}"])
        writer.writerow([])

    writer.writerow(['Daily Summary'])
    writer.writerow(['Date', 'Units', 'Revenue'])
    for row in daily_rows:
        writer.writerow([row[0], row[1], f"{row[2]:.2f}"])
    writer.writerow([])

    writer.writerow(['Monthly Summary'])
    writer.writerow(['Month', 'Units', 'Revenue'])
    for row in monthly_rows:
        writer.writerow([row[0], row[1], f"{row[2]:.2f}"])

    csv_data = output.getvalue()
    output.close()

    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=sales_report.csv'
    return response