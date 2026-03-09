import os
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, render_template,request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from flask_caching import Cache
from flask_compress import Compress
from db import db
from models import Usuario, Producto, Pedido, Proveedor
from datetime import timedelta, datetime, timezone
import plotly.express as px
import plotly.utils
import json
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from functools import wraps

load_dotenv()

# IVA estándar aplicable (editable por transacción)
IVA_DEFECTO = 21.0

def admin_required(f):
    """Decorador que restringe el acceso solo a usuarios con rol admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash("Acceso denegado. Solo administradores pueden acceder.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def create_app():
    """Crea y configura la aplicación Flask con todas sus extensiones y configuraciones."""
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, 'database', 'suministros.db')

    # Configuración de base de datos y sesiones
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['REMEMBER_COOKIE_DURATION'] = 0
    app.config['SESSION_PERMANENT'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

    # Configuración de seguridad CSRF
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # Token no expira mientras la sesión esté activa

    # Configuración de caché para mejorar rendimiento
    app.config['CACHE_TYPE'] = 'simple'  # Caché en memoria (usar Redis en producción)
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutos por defecto

    db.init_app(app)

    # Activar protección CSRF en todos los formularios
    csrf = CSRFProtect(app)

    # Activar caché
    cache = Cache(app)

    # Activar compresión HTTP para reducir tamaño de respuestas
    compress = Compress(app)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    # Configurar headers de seguridad HTTP
    @app.after_request
    def set_security_headers(response):
        """Añade headers de seguridad a todas las respuestas HTTP"""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Hacer sesiones permanentes con timeout automático
    @app.before_request
    def make_session_permanent():
        """Configura sesiones permanentes con timeout de 30 minutos de inactividad"""
        session.permanent = True
        app.permanent_session_lifetime = timedelta(minutes=30)

    def limpiar_reservas_expiradas():
        """Libera stock de reservas pendientes que llevan más de 48 horas sin completarse."""
        # Política de negocio: liberación automática tras 48h sin recoger
        limite = datetime.now(timezone.utc) - timedelta(hours=48)
        expirados = Pedido.query.filter_by(estado='pendiente', tipo='venta').filter(Pedido.fecha < limite).all()

        for r in expirados:
            producto = Producto.query.get(r.producto_id)
            if producto:
                producto.cantidad_actual += r.cantidad
            r.estado = 'cancelado'

        if expirados:
            db.session.commit()

    @login_manager.user_loader
    def load_user(user_id):
        """Carga el usuario desde la base de datos para la sesión de Flask-Login."""
        return Usuario.query.get(int(user_id))

    # Generador automático de breadcrumbs
    @app.context_processor
    def inject_breadcrumbs():
        """Genera breadcrumbs automáticamente según la ruta actual"""
        def generate_breadcrumbs():
            breadcrumbs = []

            # Siempre añadir "Inicio"
            breadcrumbs.append({
                'text': 'Inicio',
                'url': url_for('index'),
                'active': request.endpoint == 'index'
            })

            # Mapeo de rutas a nombres amigables
            route_names = {
                'inventario': 'Inventario',
                'ver_proveedores': 'Proveedores',
                'panel_admin_reservas': 'Gestionar Reservas',
                'dashboard': 'Métricas',
                'ver_usuarios': 'Usuarios',
                'ver_catalogo': 'Catálogo',
                'pedidos_clientes': 'Mis Reservas',
                'ver_carrito': 'Carrito',
                'nuevo_producto': 'Nuevo Producto',
                'editar_producto': 'Editar Producto',
                'nuevo_proveedor': 'Nuevo Proveedor',
                'editar_proveedor': 'Editar Proveedor',
                'detalle_proveedor': 'Detalle Proveedor',
                'productos_archivados': 'Productos Archivados',
                'proveedores_archivados': 'Proveedores Archivados',
                'perfil': 'Mi Perfil',
                'login': 'Iniciar Sesión',
                'registro': 'Registrarse'
            }

            # Si no estamos en la página de inicio, añadir el breadcrumb actual
            if request.endpoint and request.endpoint != 'index':
                # Determinar la ruta padre según la ruta actual
                parent_routes = {
                    'nuevo_producto': 'inventario',
                    'editar_producto': 'inventario',
                    'productos_archivados': 'inventario',
                    'nuevo_proveedor': 'ver_proveedores',
                    'editar_proveedor': 'ver_proveedores',
                    'detalle_proveedor': 'ver_proveedores',
                    'proveedores_archivados': 'ver_proveedores',
                    'ver_carrito': 'ver_catalogo',
                }

                # Añadir breadcrumb padre si existe
                if request.endpoint in parent_routes:
                    parent = parent_routes[request.endpoint]
                    breadcrumbs.append({
                        'text': route_names.get(parent, parent.replace('_', ' ').title()),
                        'url': url_for(parent),
                        'active': False
                    })

                # Añadir breadcrumb actual
                current_name = route_names.get(request.endpoint, request.endpoint.replace('_', ' ').title())
                breadcrumbs.append({
                    'text': current_name,
                    'url': None,
                    'active': True
                })

            return breadcrumbs

        return dict(generate_breadcrumbs=generate_breadcrumbs)

    with app.app_context():
        db.create_all()

        user_env = os.getenv('ADMIN_USER')
        pass_env = os.getenv('ADMIN_PASS')

        # Prevención de duplicados al reiniciar aplicación
        if not Usuario.query.filter_by(username=user_env).first():
            admin_inicial = Usuario(
                username=user_env,
                rol='admin'
            )
            admin_inicial.set_password(pass_env)

            db.session.add(admin_inicial)
            db.session.commit()
            print(f"ÉXITO: Administrador '{user_env}' creado desde archivo .env")
        else:
            print("INFO: El administrador ya existe en la base de datos.")

    @app.route('/')
    def index():
        """Renderiza la página de inicio."""
        return render_template('index.html')

    @app.route('/registro', methods=['GET', 'POST'])
    def registro():
        """Gestiona el registro de nuevos usuarios clientes."""
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')

            # Validación de campos vacíos
            if not username or not password:
                flash("Debes completar todos los campos", "danger")
                return redirect(url_for('registro'))

            # Validación de longitud mínima de contraseña
            if len(password) < 6:
                flash("La contraseña debe tener al menos 6 caracteres", "danger")
                return redirect(url_for('registro'))

            user_exists = Usuario.query.filter_by(username=username).first()
            if user_exists:
                flash("Ese usuario ya existe", "warning")
                return redirect(url_for('registro'))

            nuevo_usuario = Usuario(username=username)
            nuevo_usuario.set_password(password)

            db.session.add(nuevo_usuario)
            db.session.commit()

            flash("¡Registro con éxito!", "success")
            return redirect(url_for('login'))

        return render_template('registro.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Gestiona el inicio de sesión de usuarios."""
        if request.method == 'POST':
            usuario_ingresado = request.form.get('username')
            password_ingresada = request.form.get('password')

            user = Usuario.query.filter_by(username=usuario_ingresado).first()

            if user and user.check_password(password_ingresada):
                if not user.activo:
                    flash("Tu cuenta ha sido desactivada. Contacta al administrador.", "danger")
                    return redirect(url_for('login'))
                login_user(user)
                flash("Sesión iniciada correctamente", "success")
                return redirect(url_for('index'))
            else:
                flash("Usuario o contraseña incorrectos", "danger")
                return redirect(url_for('login'))

        return render_template('login.html')

    @app.route('/usuarios')
    @login_required
    @admin_required
    def ver_usuarios():
        """Lista todos los usuarios del sistema (solo administrador)."""
        todos_los_usuarios = Usuario.query.all()
        return render_template('usuarios.html', usuarios=todos_los_usuarios)

    @app.route('/proveedores')
    @login_required
    @admin_required
    def ver_proveedores():
        """Lista proveedores activos con búsqueda y paginación."""
        from models import Proveedor

        # Paginación: obtener página actual desde URL
        page = request.args.get('page', 1, type=int)
        per_page = 15  # Proveedores por página

        # Búsqueda: obtener término de búsqueda
        busqueda = request.args.get('busqueda', '').strip()

        # Consulta base: solo proveedores activos
        query = Proveedor.query.filter_by(active=True)

        if busqueda:
            # Búsqueda por nombre de empresa o CIF
            filtro = f"%{busqueda}%"
            query = query.filter(
                db.or_(
                    Proveedor.nombre_empresa.ilike(filtro),
                    Proveedor.cif.ilike(filtro)
                )
            )

        # Aplicar paginación
        pagination = query.order_by(Proveedor.nombre_empresa).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        # Agregar información de productos asociados con subconsulta optimizada
        proveedores_info = []
        for prov in pagination.items:
            # Consulta agregada para contar productos activos
            num_productos = db.session.query(func.count(Producto.id)).filter(
                Producto.proveedor_id == prov.id,
                Producto.active == True
            ).scalar()

            proveedores_info.append({
                'proveedor': prov,
                'num_productos': num_productos
            })

        return render_template('proveedores.html',
                             proveedores=proveedores_info,
                             pagination=pagination,
                             busqueda=busqueda)

    @app.route('/proveedor/nuevo', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def nuevo_proveedor():
        """Crea un nuevo proveedor con validaciones de datos."""
        from models import Proveedor
        if request.method == 'POST':
            try:
                nombre = request.form.get('nombre_empresa')
                cif = request.form.get('cif')
                telefono = request.form.get('telefono')
                direccion = request.form.get('direccion')
                descuento = float(request.form.get('descuento', 0))

                # Validación: porcentajes solo entre 0-100
                if descuento < 0 or descuento > 100:
                    flash("El descuento debe estar entre 0 y 100%", "danger")
                    return redirect(url_for('nuevo_proveedor'))

                # Verificar si el CIF ya existe
                if cif and Proveedor.query.filter_by(cif=cif).first():
                    flash("Ya existe un proveedor con ese CIF", "warning")
                    return redirect(url_for('nuevo_proveedor'))

                nuevo = Proveedor(
                    nombre_empresa=nombre,
                    cif=cif,
                    telefono=telefono,
                    direccion=direccion,
                    descuento=descuento
                )
                db.session.add(nuevo)
                db.session.commit()
                flash(f'Proveedor {nombre} registrado con éxito', 'success')
                return redirect(url_for('ver_proveedores'))

            except (ValueError, TypeError):
                flash("Error en los datos ingresados", "danger")
                return redirect(url_for('nuevo_proveedor'))

        return render_template('nuevo_proveedor.html')

    @app.route('/proveedor/editar/<int:id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def editar_proveedor(id):
        """Edita los datos de un proveedor existente."""
        from models import Proveedor
        proveedor = Proveedor.query.get_or_404(id)

        if request.method == 'POST':
            try:
                nuevo_descuento = float(request.form.get('descuento', 0))

                if nuevo_descuento < 0 or nuevo_descuento > 100:
                    flash("El descuento debe estar entre 0 y 100%", "danger")
                    return redirect(url_for('editar_proveedor', id=id))

                proveedor.nombre_empresa = request.form.get('nombre_empresa')
                proveedor.cif = request.form.get('cif')
                proveedor.telefono = request.form.get('telefono')
                proveedor.direccion = request.form.get('direccion')
                proveedor.descuento = nuevo_descuento

                db.session.commit()
                flash(f'Proveedor {proveedor.nombre_empresa} actualizado', 'success')
                return redirect(url_for('ver_proveedores'))

            except (ValueError, TypeError):
                flash("Error en los datos ingresados", "danger")
                return redirect(url_for('editar_proveedor', id=id))

        return render_template('editar_proveedor.html', proveedor=proveedor)

    @app.route('/proveedor/eliminar/<int:id>')
    @login_required
    @admin_required
    def eliminar_proveedor(id):
        """Desactiva un proveedor mediante eliminación lógica."""
        from models import Proveedor
        proveedor = Proveedor.query.get_or_404(id)

        # Contar productos activos asociados
        productos_activos = len([p for p in proveedor.productos if p.active])

        if productos_activos > 0:
            flash(f"⚠️ Este proveedor tiene {productos_activos} producto(s) activo(s) asociado(s).", "warning")

        try:
            # Eliminación lógica: marcar como inactivo
            proveedor.active = False
            db.session.commit()
            flash(f'Proveedor "{proveedor.nombre_empresa}" desactivado correctamente. Ya no aparecerá en los listados.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al desactivar proveedor: {str(e)}', 'danger')

        return redirect(url_for('ver_proveedores'))

    @app.route('/proveedor/<int:id>/detalle')
    @login_required
    @admin_required
    def detalle_proveedor(id):
        """Muestra información detallada de un proveedor con productos y compras asociadas."""
        from models import Proveedor, Producto, Pedido
        proveedor = Proveedor.query.get_or_404(id)

        # Obtener todos los productos del proveedor (activos e inactivos)
        productos_activos = [p for p in proveedor.productos if p.active]
        productos_inactivos = [p for p in proveedor.productos if not p.active]

        # Obtener historial de compras a este proveedor
        # Las compras son pedidos de tipo='compra' de productos de este proveedor
        compras = []
        for producto in proveedor.productos:
            pedidos_compra = Pedido.query.filter_by(
                producto_id=producto.id,
                tipo='compra'
            ).order_by(Pedido.fecha.desc()).all()

            for pedido in pedidos_compra:
                compras.append({
                    'pedido': pedido,
                    'producto': producto
                })

        # Ordenar compras por fecha descendente
        compras.sort(key=lambda x: x['pedido'].fecha, reverse=True)

        # Calcular estadísticas
        total_compras = len(compras)
        total_productos = len(proveedor.productos)
        productos_activos_count = len(productos_activos)
        total_invertido = sum(c['pedido'].precio_unidad_coste * c['pedido'].cantidad for c in compras)

        estadisticas = {
            'total_compras': total_compras,
            'total_productos': total_productos,
            'productos_activos': productos_activos_count,
            'total_invertido': total_invertido
        }

        return render_template('detalle_proveedor.html',
                             proveedor=proveedor,
                             productos_activos=productos_activos,
                             productos_inactivos=productos_inactivos,
                             compras=compras,
                             estadisticas=estadisticas)

    @app.route('/proveedores/archivados')
    @login_required
    @admin_required
    def proveedores_archivados():
        """Lista proveedores desactivados con opción de reactivarlos."""
        from models import Proveedor

        # Obtener proveedores desactivados
        proveedores_inactivos = Proveedor.query.filter_by(active=False).all()

        # Agregar información de productos asociados
        proveedores_info = []
        for prov in proveedores_inactivos:
            num_productos = len([p for p in prov.productos if p.active])
            proveedores_info.append({
                'proveedor': prov,
                'num_productos': num_productos
            })

        return render_template('proveedores_archivados.html', proveedores=proveedores_info)

    @app.route('/proveedor/reactivar/<int:id>', methods=['POST'])
    @login_required
    @admin_required
    def reactivar_proveedor(id):
        """Reactiva un proveedor desactivado."""
        from models import Proveedor
        proveedor = Proveedor.query.get_or_404(id)

        try:
            proveedor.active = True
            db.session.commit()
            flash(f'Proveedor "{proveedor.nombre_empresa}" reactivado correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al reactivar proveedor: {str(e)}', 'danger')

        return redirect(url_for('proveedores_archivados'))

    @app.route('/logout')
    @login_required
    def logout():
        """Cierra la sesión del usuario actual."""
        logout_user()
        print("LOG: Sesión cerrada")
        return redirect(url_for('index'))

    @app.route('/usuarios/estado/<int:id>')
    @login_required
    @admin_required
    def cambiar_estado(id):
        """Activa o desactiva un usuario (no puede desactivarse a sí mismo)."""
        user = Usuario.query.get_or_404(id)

        # Protección: evita bloqueo total del sistema sin admin activo
        if user.id == current_user.id:
            flash("No puedes desactivar tu propia cuenta", "warning")
            return redirect(url_for('ver_usuarios'))

        user.activo = not user.activo
        db.session.commit()

        estado_texto = "activado" if user.activo else "desactivado"
        flash(f"El usuario {user.username} ha sido {estado_texto}.", "success")

        return redirect(url_for('ver_usuarios'))

    @app.route('/eliminar_usuario/<int:id>')
    @login_required
    @admin_required
    def eliminar_usuario(id):
        """Elimina un usuario de forma permanente (admin no puede eliminarse a sí mismo)."""
        user_a_eliminar = Usuario.query.get_or_404(id)

        # Evitar que el admin se elimine a sí mismo
        if user_a_eliminar.id == current_user.id:
            flash("No puedes darte de baja a ti mismo", "warning")
            return redirect(url_for('inventario'))

        db.session.delete(user_a_eliminar)
        db.session.commit()

        flash(f"Usuario {user_a_eliminar.username} eliminado correctamente", "success")
        return redirect(url_for('ver_usuarios'))

    @app.route('/usuario/resetear_password/<int:id>', methods=['POST'])
    @login_required
    @admin_required
    def resetear_password_usuario(id):
        """Permite al admin asignar una contraseña temporal a un usuario."""
        usuario = Usuario.query.get_or_404(id)

        # Seguridad: admin no puede cambiar su propia contraseña
        if usuario.id == current_user.id:
            flash("No puedes cambiar tu propia contraseña desde aquí. Usa tu perfil.", "warning")
            return redirect(url_for('ver_usuarios'))

        nueva_password = request.form.get('nueva_password', '').strip()

        if not nueva_password:
            flash("Debes ingresar una contraseña", "danger")
            return redirect(url_for('ver_usuarios'))

        if len(nueva_password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for('ver_usuarios'))

        usuario.set_password(nueva_password)
        db.session.commit()

        flash(f"✅ Contraseña de '{usuario.username}' cambiada exitosamente. Nueva contraseña: {nueva_password}", "success")
        return redirect(url_for('ver_usuarios'))

    @app.route('/perfil')
    @login_required
    def perfil():
        """Muestra el perfil del usuario para ver y cambiar su contraseña."""
        return render_template('perfil.html')

    @app.route('/cambiar_password', methods=['POST'])
    @login_required
    def cambiar_password():
        """Permite al usuario cambiar su propia contraseña."""
        password_actual = request.form.get('password_actual', '').strip()
        nueva_password = request.form.get('nueva_password', '').strip()
        confirmar_password = request.form.get('confirmar_password', '').strip()

        # Validaciones
        if not password_actual or not nueva_password or not confirmar_password:
            flash("Debes completar todos los campos", "danger")
            return redirect(url_for('perfil'))

        # Verificar contraseña actual
        if not current_user.check_password(password_actual):
            flash("La contraseña actual es incorrecta", "danger")
            return redirect(url_for('perfil'))

        # Verificar longitud mínima
        if len(nueva_password) < 6:
            flash("La nueva contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for('perfil'))

        # Verificar coincidencia
        if nueva_password != confirmar_password:
            flash("Las contraseñas nuevas no coinciden", "danger")
            return redirect(url_for('perfil'))

        # Cambiar la contraseña
        current_user.set_password(nueva_password)
        db.session.commit()

        flash("✅ Contraseña cambiada exitosamente", "success")
        return redirect(url_for('perfil'))

    @app.route('/producto/nuevo', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def nuevo_producto():
        """Crea un nuevo producto con validaciones completas y registro de stock inicial."""
        from models import Proveedor

        # Datos del formulario para preservar en caso de error
        form_data = {
            'nombre': '',
            'descripcion': '',
            'referencia': '',
            'ubicacion': '',
            'proveedor_id': '',
            'precio_coste': '',
            'precio_venta': '',
            'iva': '21',
            'cantidad_actual': '0',
            'stock_maximo': '100'
        }

        if request.method == 'POST':
            # Capturar datos del formulario
            nombre = request.form.get('nombre', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            referencia = request.form.get('referencia', '').strip()
            ubicacion = request.form.get('ubicacion', '').strip()
            proveedor_id = request.form.get('proveedor_id')

            # Actualizar form_data con los valores ingresados
            form_data.update({
                'nombre': nombre,
                'descripcion': descripcion,
                'referencia': referencia,
                'ubicacion': ubicacion,
                'proveedor_id': proveedor_id,
                'precio_coste': request.form.get('precio_coste', ''),
                'precio_venta': request.form.get('precio_venta', ''),
                'iva': request.form.get('iva', '21'),
                'cantidad_actual': request.form.get('cantidad_actual', '0'),
                'stock_maximo': request.form.get('stock_maximo', '100')
            })

            # Validación: campos obligatorios (excepto ubicación)
            if not nombre:
                flash("El nombre del producto es obligatorio", "danger")
                proveedores = Proveedor.query.all()
                return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            if not descripcion:
                flash("La descripción del producto es obligatoria", "danger")
                proveedores = Proveedor.query.all()
                return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            if not referencia:
                flash("La referencia del producto es obligatoria", "danger")
                proveedores = Proveedor.query.all()
                return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            # Validación: referencia única
            producto_existente = Producto.query.filter_by(referencia=referencia).first()
            if producto_existente:
                flash(f"Ya existe un producto con la referencia '{referencia}'. Debe ser única.", "danger")
                proveedores = Proveedor.query.all()
                return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            try:
                p_coste_sin_iva = float(request.form.get('precio_coste'))
                p_venta_sin_iva = float(request.form.get('precio_venta'))

                iva_porcentaje = float(request.form.get('iva', IVA_DEFECTO))
                if iva_porcentaje < 0 or iva_porcentaje > 100:
                    flash("El IVA debe estar entre 0 y 100%", "danger")
                    proveedores = Proveedor.query.all()
                    return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

                # Validación: precio de venta debe ser mayor o igual al precio de coste
                if p_venta_sin_iva < p_coste_sin_iva:
                    flash("ERROR: El precio de venta no puede ser menor al precio de coste. No puedes vender con pérdidas.", "danger")
                    proveedores = Proveedor.query.all()
                    return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

                # Aplicamos IVA manualmente para evitar inconsistencias en cálculos
                p_coste = round(p_coste_sin_iva * (1 + iva_porcentaje / 100), 2)
                p_venta = round(p_venta_sin_iva * (1 + iva_porcentaje / 100), 2)

                stock_inicial = int(request.form.get('cantidad_actual'))
                maximo = int(request.form.get('stock_maximo'))

                if p_coste_sin_iva < 0 or p_venta_sin_iva < 0:
                    flash("Los precios no pueden ser negativos", "danger")
                    proveedores = Proveedor.query.all()
                    return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

                if stock_inicial < 0 or maximo < 0:
                    flash("Las cantidades no pueden ser negativas", "danger")
                    proveedores = Proveedor.query.all()
                    return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

                if stock_inicial > maximo:
                    flash(f"El stock inicial ({stock_inicial}) no puede superar el máximo ({maximo})", "danger")
                    proveedores = Proveedor.query.all()
                    return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            except (ValueError, TypeError):
                flash("Error: Los campos numéricos contienen valores inválidos", "danger")
                proveedores = Proveedor.query.all()
                return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

            nuevo = Producto(
                nombre=nombre,
                descripcion=descripcion,
                referencia=referencia,
                ubicacion=ubicacion if ubicacion else None,
                precio_coste=p_coste,
                precio_venta=p_venta,
                cantidad_actual=stock_inicial,
                stock_maximo=maximo,
                proveedor_id=int(proveedor_id) if proveedor_id else None
            )

            db.session.add(nuevo)
            db.session.flush()

            # Registramos inversión inicial como compra para gráfico de costos
            if stock_inicial > 0:
                # Aplicar descuento del proveedor al costo real de la compra
                proveedor = Proveedor.query.get(nuevo.proveedor_id) if nuevo.proveedor_id else None
                descuento_proveedor = proveedor.descuento if proveedor else 0.0
                costo_real_con_descuento = round(p_coste * (1 - descuento_proveedor / 100), 2)

                registro_costo_inicial = Pedido(
                    cantidad=stock_inicial,
                    precio_unidad_coste=costo_real_con_descuento,  # Costo real con descuento aplicado
                    precio_unidad_venta=p_venta,
                    total_venta=0,
                    tipo='compra',
                    estado='completado',  # Las compras se registran directamente como completadas
                    usuario_id=current_user.id,
                    producto_id=nuevo.id
                )
                db.session.add(registro_costo_inicial)

            db.session.commit()
            flash('Producto y stock inicial registrados con éxito')
            return redirect(url_for('inventario'))

        proveedores = Proveedor.query.filter_by(active=True).all()
        return render_template('nuevo_producto.html', proveedores=proveedores, form_data=form_data)

    @app.route('/inventario')
    @login_required
    @admin_required
    def inventario():
        """Lista productos activos con búsqueda, paginación y estado de ocupación."""
        # Paginación: obtener página actual desde URL
        page = request.args.get('page', 1, type=int)
        per_page = 25  # Productos por página

        # Búsqueda: obtener término de búsqueda
        busqueda = request.args.get('busqueda', '').strip()

        # Consulta base: solo productos activos
        query = Producto.query.filter_by(active=True)

        if busqueda:
            # Búsqueda en nombre, referencia y descripción
            filtro = f"%{busqueda}%"
            query = query.filter(
                db.or_(
                    Producto.nombre.ilike(filtro),
                    Producto.referencia.ilike(filtro),
                    Producto.descripcion.ilike(filtro)
                )
            )

        # Aplicar paginación a la consulta filtrada
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        todos_los_productos = pagination.items

        # Sistema de alertas: rojo ≤10%, amarillo ≤25%, azul ≥90%
        productos_con_alertas = []
        for p in todos_los_productos:
            porcentaje_ocupacion = (p.cantidad_actual / p.stock_maximo * 100) if p.stock_maximo > 0 else 0
            alerta = None

            if porcentaje_ocupacion <= 10:
                alerta = 'danger'
            elif porcentaje_ocupacion <= 25:
                alerta = 'warning'
            elif porcentaje_ocupacion >= 90:
                alerta = 'info'

            productos_con_alertas.append({
                'producto': p,
                'porcentaje': round(porcentaje_ocupacion, 1),
                'alerta': alerta
            })

        clientes = Usuario.query.filter_by(rol='cliente', activo=True).all()

        return render_template('inventario.html',
                             productos=productos_con_alertas,
                             clientes=clientes,
                             pagination=pagination,
                             busqueda=busqueda)

    @app.route('/producto/eliminar/<int:id>')
    @login_required
    @admin_required
    def eliminar_producto(id):
        """Desactiva un producto mediante eliminación lógica con validaciones."""
        producto = Producto.query.get_or_404(id)

        # Verificar si tiene stock
        if producto.cantidad_actual > 0:
            flash(f'⚠️ Advertencia: El producto tiene {producto.cantidad_actual} unidades en stock', 'warning')

        # Verificar si tiene RESERVAS PENDIENTES (solo ventas a clientes, no compras a proveedores)
        pedidos_pendientes = Pedido.query.filter_by(
            producto_id=id,
            tipo='venta',  # Solo ventas (reservas de clientes)
            estado='pendiente'
        ).count()

        if pedidos_pendientes > 0:
            flash(f'⚠️ Este producto tiene {pedidos_pendientes} reserva(s) pendiente(s). Se desactivará pero las reservas se mantendrán.', 'warning')

        try:
            # Eliminación lógica: marcar como inactivo
            producto.active = False
            db.session.commit()
            flash(f'Producto "{producto.nombre}" desactivado correctamente. Ya no aparecerá en el inventario.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al desactivar producto: {str(e)}', 'danger')

        return redirect(url_for('inventario'))

    @app.route('/productos/archivados')
    @login_required
    @admin_required
    def productos_archivados():
        """Lista productos desactivados con información de pedidos asociados."""
        # Obtener productos desactivados
        productos_inactivos = Producto.query.filter_by(active=False).all()

        # Agregar información detallada de cada producto
        productos_info = []
        for p in productos_inactivos:
            # Contar solo pedidos de tipo 'venta' (no compras al proveedor)
            num_pedidos_venta = Pedido.query.filter_by(producto_id=p.id, tipo='venta').count()

            # Obtener pedidos pendientes específicamente
            pedidos_pendientes = Pedido.query.filter_by(
                producto_id=p.id,
                tipo='venta',
                estado='pendiente'
            ).count()

            productos_info.append({
                'producto': p,
                'num_pedidos': num_pedidos_venta,
                'pedidos_pendientes': pedidos_pendientes
            })

        return render_template('productos_archivados.html', productos=productos_info)

    @app.route('/producto/<int:id>/pedidos')
    @login_required
    @admin_required
    def ver_pedidos_producto(id):
        """Muestra todos los pedidos de venta asociados a un producto con estadísticas."""
        producto = Producto.query.get_or_404(id)

        # Obtener TODOS los pedidos de venta de este producto (pendientes, completados, cancelados)
        pedidos = Pedido.query.filter_by(
            producto_id=id,
            tipo='venta'
        ).order_by(Pedido.fecha.desc()).all()

        # Estadísticas del producto
        pedidos_pendientes = len([p for p in pedidos if p.estado == 'pendiente'])
        pedidos_completados = len([p for p in pedidos if p.estado == 'completado'])
        pedidos_cancelados = len([p for p in pedidos if p.estado == 'cancelado'])

        total_vendido = sum(p.cantidad for p in pedidos if p.estado == 'completado')
        ingresos_totales = sum(p.total_venta for p in pedidos if p.estado == 'completado')

        estadisticas = {
            'pendientes': pedidos_pendientes,
            'completados': pedidos_completados,
            'cancelados': pedidos_cancelados,
            'total_vendido': total_vendido,
            'ingresos': ingresos_totales
        }

        return render_template('pedidos_producto.html',
                             producto=producto,
                             pedidos=pedidos,
                             estadisticas=estadisticas)

    @app.route('/producto/reactivar/<int:id>', methods=['POST'])
    @login_required
    @admin_required
    def reactivar_producto(id):
        """Reactiva un producto desactivado para que vuelva a aparecer en el inventario."""
        producto = Producto.query.get_or_404(id)

        try:
            producto.active = True
            db.session.commit()
            flash(f'Producto "{producto.nombre}" reactivado correctamente. Ya aparece en el inventario.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al reactivar producto: {str(e)}', 'danger')

        return redirect(url_for('productos_archivados'))

    @app.route('/producto/editar/<int:id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def editar_producto(id):
        """Edita los datos de un producto existente con validaciones completas."""
        from models import Proveedor
        producto = Producto.query.get_or_404(id)

        if request.method == 'POST':
            nombre = request.form.get('nombre', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            referencia = request.form.get('referencia', '').strip()
            ubicacion = request.form.get('ubicacion', '').strip()

            # Validación: campos obligatorios (excepto ubicación)
            if not nombre:
                flash("El nombre del producto es obligatorio", "danger")
                return redirect(url_for('editar_producto', id=id))

            if not descripcion:
                flash("La descripción del producto es obligatoria", "danger")
                return redirect(url_for('editar_producto', id=id))

            if not referencia:
                flash("La referencia del producto es obligatoria", "danger")
                return redirect(url_for('editar_producto', id=id))

            # Validación: referencia única (excepto si es la misma que ya tiene)
            if referencia != producto.referencia:
                producto_existente = Producto.query.filter_by(referencia=referencia).first()
                if producto_existente:
                    flash(f"Ya existe otro producto con la referencia '{referencia}'. Debe ser única.", "danger")
                    return redirect(url_for('editar_producto', id=id))

            try:
                nuevo_precio_coste = float(request.form.get('precio_coste'))
                nuevo_precio_venta = float(request.form.get('precio_venta'))
                nueva_cantidad = int(request.form.get('cantidad_actual'))
                nuevo_maximo = int(request.form.get('stock_maximo'))
                proveedor_id = request.form.get('proveedor_id')

                if nuevo_precio_coste < 0 or nuevo_precio_venta < 0:
                    flash("Los precios no pueden ser negativos", "danger")
                    return redirect(url_for('editar_producto', id=id))

                # Validación: precio de venta debe ser mayor o igual al precio de coste
                if nuevo_precio_venta < nuevo_precio_coste:
                    flash("ERROR: El precio de venta no puede ser menor al precio de coste. No puedes vender con pérdidas.", "danger")
                    return redirect(url_for('editar_producto', id=id))

                if nueva_cantidad < 0 or nuevo_maximo < 0:
                    flash("Las cantidades no pueden ser negativas", "danger")
                    return redirect(url_for('editar_producto', id=id))

                if nueva_cantidad > nuevo_maximo:
                    flash(f"El stock actual ({nueva_cantidad}) no puede superar el máximo ({nuevo_maximo})", "danger")
                    return redirect(url_for('editar_producto', id=id))

                producto.nombre = nombre
                producto.descripcion = descripcion
                producto.referencia = referencia
                producto.ubicacion = ubicacion if ubicacion else None
                producto.precio_coste = nuevo_precio_coste
                producto.precio_venta = nuevo_precio_venta
                producto.cantidad_actual = nueva_cantidad
                producto.stock_maximo = nuevo_maximo
                producto.proveedor_id = int(proveedor_id) if proveedor_id else None

            except (ValueError, TypeError):
                flash("Error: Los campos numéricos contienen valores inválidos", "danger")
                return redirect(url_for('editar_producto', id=id))

            db.session.commit()

            flash(f'Producto "{producto.nombre}" actualizado con éxito')
            return redirect(url_for('inventario'))

        proveedores = Proveedor.query.filter_by(active=True).all()
        return render_template('editar_producto.html', producto=producto, proveedores=proveedores)

    @app.route('/venta/nueva/<int:producto_id>', methods=['POST'])
    @login_required
    def realizar_venta(producto_id):
        producto = Producto.query.get_or_404(producto_id)
        cantidad_a_vender = int(request.form.get('cantidad', 1))

        if producto.cantidad_actual < cantidad_a_vender:
            flash(f"Error: Stock insuficiente de {producto.nombre}", "danger")
            return redirect(url_for('inventario'))

        descuento_cliente = float(request.form.get('descuento', 0))
        if descuento_cliente < 0 or descuento_cliente > 100:
            descuento_cliente = 0

        iva_venta = float(request.form.get('iva', IVA_DEFECTO))
        if iva_venta < 0 or iva_venta > 100:
            iva_venta = IVA_DEFECTO

        # Quitamos IVA almacenado y aplicamos el nuevo con redondeo
        precio_base = producto.precio_venta / (1 + IVA_DEFECTO / 100)
        precio_con_nuevo_iva = round(precio_base * (1 + iva_venta / 100), 2)
        precio_con_descuento = round(precio_con_nuevo_iva * (1 - descuento_cliente / 100), 2)
        total = round(precio_con_descuento * cantidad_a_vender, 2)

        # Calcular costo real promedio ponderado considerando descuentos del proveedor
        compras_producto = Pedido.query.filter_by(
            producto_id=producto.id,
            tipo='compra',
            estado='completado'
        ).all()

        if compras_producto:
            total_unidades_compradas = sum(c.cantidad for c in compras_producto)
            costo_total_compras = sum(c.precio_unidad_coste * c.cantidad for c in compras_producto)
            costo_promedio_real = round(costo_total_compras / total_unidades_compradas, 2) if total_unidades_compradas > 0 else producto.precio_coste
        else:
            # Si no hay compras registradas, usar precio_coste base
            costo_promedio_real = producto.precio_coste

        # Si es admin puede especificar cliente, sino es el usuario actual
        if current_user.rol == 'admin':
            cliente_id = request.form.get('cliente_id')
            if cliente_id:
                cliente = Usuario.query.filter_by(id=int(cliente_id), rol='cliente', activo=True).first()
                if not cliente:
                    flash("Cliente no válido", "danger")
                    return redirect(url_for('inventario'))
                usuario_destino = int(cliente_id)
            else:
                usuario_destino = current_user.id
        else:
            usuario_destino = current_user.id

        nuevo_pedido = Pedido(
            tipo='venta',
            cantidad=cantidad_a_vender,
            precio_unidad_coste=costo_promedio_real,  # Usa costo real con descuentos aplicados
            precio_unidad_venta=precio_con_nuevo_iva,
            total_venta=total,
            descuento_aplicado=descuento_cliente,
            iva_aplicado=iva_venta,
            usuario_id=usuario_destino,
            producto_id=producto.id,
            estado='pendiente'
        )

        producto.cantidad_actual -= cantidad_a_vender

        db.session.add(nuevo_pedido)
        db.session.commit()

        if current_user.rol == 'admin':
            if cliente_id:
                cliente = Usuario.query.get(usuario_destino)
                flash(f"Reserva #{nuevo_pedido.id} creada para el cliente: {cliente.username}", "success")
            else:
                flash(f"Reserva #{nuevo_pedido.id} creada (sin cliente asignado)", "info")
            return redirect(url_for('inventario'))
        else:
            flash(f"¡Reserva confirmada! Recuerda recoger tu {producto.nombre} en las próximas 48 horas.", "success")
            return redirect(url_for('ver_catalogo'))

    @app.route('/carrito/añadir/<int:producto_id>', methods=['POST'])
    @login_required
    def anadir_al_carrito(producto_id):
        # Obtener el producto y la cantidad solicitada
        producto = Producto.query.get_or_404(producto_id)
        cantidad_solicitada = int(request.form.get('cantidad', 1))

        # Inicializar carrito en sesión si no existe (estructura: {producto_id: cantidad})
        if 'carrito' not in session:
            session['carrito'] = {}

        carrito = session['carrito']
        # Usar string como clave para compatibilidad con JSON en sesión
        id_str = str(producto_id)

        # Calcular cantidad total si aceptamos esta solicitud
        cantidad_actual_en_carrito = carrito.get(id_str, 0)
        nueva_cantidad_total = cantidad_actual_en_carrito + cantidad_solicitada

        # Calcular stock disponible descontando reservas pendientes
        stock_reservado = db.session.query(func.sum(Pedido.cantidad))\
            .filter(Pedido.producto_id == producto_id,
                    Pedido.estado == 'pendiente',
                    Pedido.tipo == 'venta')\
            .scalar() or 0

        stock_disponible = producto.cantidad_actual - stock_reservado

        # Validar stock disponible
        if nueva_cantidad_total > stock_disponible:
            flash(
                f"No puedes añadir {cantidad_solicitada} unidades. "
                f"Solo hay {stock_disponible} disponibles (considerando reservas pendientes). "
                f"Ya tienes {cantidad_actual_en_carrito} en tu carrito.",
                "warning")
            return redirect(url_for('ver_catalogo'))

        # Actualizar carrito
        carrito[id_str] = nueva_cantidad_total
        session['carrito'] = carrito
        session.modified = True

        flash(f"Añadido: {producto.nombre} (Cantidad: {cantidad_solicitada})", "success")
        return redirect(url_for('ver_catalogo'))

    @app.route('/carrito/eliminar/<int:producto_id>')
    @login_required
    def eliminar_del_carrito(producto_id):
        """Elimina un producto específico del carrito."""
        if 'carrito' in session:
            carrito = session['carrito']
            id_str = str(producto_id)

            if id_str in carrito:
                producto = Producto.query.get(producto_id)
                nombre_producto = producto.nombre if producto else "Producto"

                carrito.pop(id_str)
                session['carrito'] = carrito
                session.modified = True

                flash(f"{nombre_producto} eliminado del carrito", "info")
            else:
                flash("El producto no está en tu carrito", "warning")

        return redirect(url_for('ver_carrito'))

    @app.route('/carrito/vaciar')
    @login_required
    def vaciar_carrito():
        """Vacía completamente el carrito del usuario."""
        if 'carrito' in session and session['carrito']:
            session.pop('carrito', None)
            session.modified = True
            flash("Carrito vaciado correctamente", "info")
        else:
            flash("El carrito ya está vacío", "info")

        return redirect(url_for('ver_catalogo'))

    @app.route('/carrito')
    @login_required
    def ver_carrito():
        """Muestra el carrito con datos actualizados desde la base de datos."""
        items_carrito = []
        total_compra = 0

        if 'carrito' in session and session['carrito']:
            # Optimización: consulta única con eager loading de proveedores
            ids = [int(p_id) for p_id in session['carrito'].keys()]
            productos = Producto.query.options(
                joinedload(Producto.proveedor)  # Eager loading para evitar N+1
            ).filter(
                Producto.id.in_(ids),
                Producto.active == True  # Solo productos activos
            ).all()

            productos_dict = {p.id: p for p in productos}

            # Construir items con datos actualizados desde la BD
            for p_id, cantidad in session['carrito'].items():
                producto = productos_dict.get(int(p_id))
                if producto:
                    subtotal = round(producto.precio_venta * cantidad, 2)
                    total_compra += subtotal
                    items_carrito.append({
                        'id': producto.id,
                        'nombre': producto.nombre,
                        'precio': round(producto.precio_venta, 2),
                        'cantidad': cantidad,
                        'subtotal': subtotal
                    })
                else:
                    # Producto eliminado o desactivado, limpiar del carrito
                    session['carrito'].pop(p_id, None)
                    session.modified = True

        return render_template('carrito.html', items=items_carrito, total=round(total_compra, 2))

    @app.route('/carrito/confirmar', methods=['POST'])
    @login_required
    def confirmar_carrito():
        """
        Confirma el carrito y crea reservas/ventas pendientes.
        Implementa bloqueo pesimista (with_for_update) para prevenir condiciones de carrera.
        Valida stock disponible real (físico - reservado) antes de confirmar.
        """
        if 'carrito' not in session or not session['carrito']:
            flash("El carrito está vacío", "warning")
            return redirect(url_for('ver_catalogo'))

        try:
            # FASE 1: Validar stock disponible REAL con bloqueo pesimista (SELECT FOR UPDATE)
            for p_id, cantidad in session['carrito'].items():
                # Bloqueo pesimista: nadie más puede modificar este producto hasta commit/rollback
                producto = Producto.query.with_for_update().get(int(p_id))

                if not producto or not producto.active:
                    flash(f"Producto con ID {p_id} no disponible", "danger")
                    db.session.rollback()
                    return redirect(url_for('ver_carrito'))

                # Calcular stock REAL: físico - reservas pendientes de otros usuarios
                stock_reservado = db.session.query(func.sum(Pedido.cantidad))\
                    .filter(Pedido.producto_id == producto.id,
                            Pedido.estado == 'pendiente',
                            Pedido.tipo == 'venta')\
                    .scalar() or 0

                stock_disponible = producto.cantidad_actual - stock_reservado

                # Validar contra stock disponible REAL
                if stock_disponible < cantidad:
                    flash(f"Stock insuficiente de {producto.nombre}. "
                          f"Disponible: {stock_disponible}, Solicitado: {cantidad}", "danger")
                    db.session.rollback()
                    return redirect(url_for('ver_carrito'))

            # FASE 2: Crear pedidos y actualizar stock (ya validado dentro del bloqueo)
            pedidos_creados = 0
            for p_id, cantidad in session['carrito'].items():
                # Volver a obtener con bloqueo para la modificación
                producto = Producto.query.with_for_update().get(int(p_id))

                # Calcular costo real promedio ponderado considerando descuentos del proveedor
                compras_producto = Pedido.query.filter_by(
                    producto_id=producto.id,
                    tipo='compra',
                    estado='completado'
                ).all()

                if compras_producto:
                    total_unidades_compradas = sum(c.cantidad for c in compras_producto)
                    costo_total_compras = sum(c.precio_unidad_coste * c.cantidad for c in compras_producto)
                    costo_promedio_real = round(costo_total_compras / total_unidades_compradas, 2) if total_unidades_compradas > 0 else producto.precio_coste
                else:
                    # Si no hay compras registradas, usar precio_coste base
                    costo_promedio_real = producto.precio_coste

                nuevo_pedido = Pedido(
                    tipo='venta',
                    cantidad=cantidad,
                    precio_unidad_coste=costo_promedio_real,  # Usa costo real con descuentos aplicados
                    precio_unidad_venta=round(producto.precio_venta, 2),
                    total_venta=round(producto.precio_venta * cantidad, 2),
                    usuario_id=current_user.id,
                    producto_id=producto.id,
                    estado='pendiente'
                )

                # Reducir stock físico de forma atómica
                producto.cantidad_actual -= cantidad

                db.session.add(nuevo_pedido)
                pedidos_creados += 1

            # FASE 3: Vaciar carrito y confirmar transacción atómica
            session.pop('carrito', None)
            session.modified = True
            db.session.commit()

            # Mensaje según rol
            if current_user.rol == 'admin':
                flash(f"✅ {pedidos_creados} venta(s)/reserva(s) registradas en inventario.", "success")
                return redirect(url_for('inventario'))
            else:
                flash(f"¡Reserva realizada con éxito! {pedidos_creados} producto(s) reservado(s). "
                      f"Tienes 48 horas para recoger tus artículos.", "success")
                return redirect(url_for('pedidos_clientes'))

        except Exception as e:
            db.session.rollback()
            flash(f"Error al procesar el carrito: {str(e)}", "danger")
            return redirect(url_for('ver_carrito'))

    @app.route('/pedidos-clientes')
    @login_required
    def pedidos_clientes():
        # Obtener parámetro de filtro
        filtro_producto = request.args.get('producto', '')

        # Consulta base: Solo pedidos del usuario actual de tipo 'venta'
        query = Pedido.query.filter_by(usuario_id=current_user.id, tipo='venta')

        # Aplicar filtro de producto si existe
        if filtro_producto:
            query = query.filter(Pedido.producto_id == int(filtro_producto))

        # Ordenar por fecha descendente
        reservas = query.order_by(Pedido.fecha.desc()).all()

        # Gráfico TOP productos más comprados por el cliente
        graph_reserva_json = None
        if reservas:
            # Agregamos por producto sumando cantidades y dinero gastado (solo completadas)
            top_productos = db.session.query(
                Producto.nombre,
                func.sum(Pedido.cantidad).label('total_cantidad'),
                func.sum(Pedido.total_venta).label('total_gastado')
            ).join(Pedido).filter(
                Pedido.usuario_id == current_user.id,
                Pedido.tipo == 'venta',
                Pedido.estado == 'completado'
            ).group_by(Producto.id, Producto.nombre)\
             .order_by(func.sum(Pedido.cantidad).desc())\
             .limit(10).all()  # Máximo 10, pero si tiene menos muestra los que tenga

            if top_productos:
                # Crear DataFrame con los datos
                datos_top = [{
                    'Producto': nombre,
                    'Cantidad': int(cantidad),
                    'Total Gastado (€)': float(gastado)
                } for nombre, cantidad, gastado in top_productos]

                df = pd.DataFrame(datos_top)

                # Crear gráfico de barras mostrando DINERO GASTADO
                fig = px.bar(
                    df,
                    x='Producto',
                    y='Total Gastado (€)',
                    title=f'Tus {len(top_productos)} Productos: Total Gastado',
                    template='plotly_white',
                    color='Total Gastado (€)',
                    color_continuous_scale=['#4FC3F7', '#039BE5', '#0277BD'],  # Azul degradado
                    hover_data=['Cantidad']
                )

                # Personalizar diseño
                fig.update_layout(
                    xaxis_title='Producto',
                    yaxis_title='Dinero Gastado (€)',
                    showlegend=False,
                    xaxis_tickangle=-45,
                    coloraxis_showscale=False  # Ocultar la barra de color lateral
                )

                # Personalizar hover
                fig.update_traces(
                    hovertemplate='<b>%{x}</b><br>Gastado: %{y:.2f}€<br>Unidades: %{customdata[0]}<extra></extra>'
                )

                graph_reserva_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

        # Obtener lista de productos únicos del cliente para el filtro
        productos_cliente = db.session.query(Producto)\
            .join(Pedido)\
            .filter(Pedido.usuario_id == current_user.id, Pedido.tipo == 'venta')\
            .distinct().all()

        return render_template('pedidos_clientes.html',
                               pedidos=reservas,
                               graph_user=graph_reserva_json,
                               productos=productos_cliente,
                               filtro_producto=filtro_producto)

    @app.route('/admin/reservas')
    @login_required
    @admin_required
    def panel_admin_reservas():
        limpiar_reservas_expiradas()  # Limpiamos antes de mostrar

        # Obtener parámetros de filtro
        filtro_cliente = request.args.get('cliente', '')
        filtro_producto = request.args.get('producto', '')
        filtro_estado = request.args.get('estado', '')

        # Parámetro de página
        page = request.args.get('page', 1, type=int)

        # Consulta base: TODAS las reservas de tipo 'venta'
        query = Pedido.query.options(
            joinedload(Pedido.usuario),  # Eager loading
            joinedload(Pedido.producto)   # Eager loading
        ).filter_by(tipo='venta')

        # Aplicar filtros si existen
        if filtro_cliente:
            query = query.filter(Pedido.usuario_id == int(filtro_cliente))

        if filtro_producto:
            query = query.filter(Pedido.producto_id == int(filtro_producto))

        if filtro_estado:
            query = query.filter(Pedido.estado == filtro_estado)

        # Ordenar por fecha descendente y paginar
        pagination = query.order_by(Pedido.fecha.desc()).paginate(
            page=page, per_page=25, error_out=False
        )

        # Obtener listas para los selectores de filtro
        clientes = Usuario.query.filter_by(rol='cliente').all()
        productos = Producto.query.all()

        return render_template('admin_reservas.html',
                               pagination=pagination,
                               reservas=pagination.items,
                               clientes=clientes,
                               productos=productos,
                               filtro_cliente=filtro_cliente,
                               filtro_producto=filtro_producto,
                               filtro_estado=filtro_estado)

    @app.route('/pedido/confirmar_entrega/<int:id>')
    @login_required
    @admin_required
    def confirmar_entrega(id):

        pedido = Pedido.query.get_or_404(id)
        pedido.estado = 'completado'  # La reserva se convierte en venta real
        db.session.commit()
        flash(f"Pedido #{id} marcado como entregado y cobrado.", "success")
        return redirect(url_for('panel_admin_reservas'))

    @app.route('/pedido/cancelar/<int:pedido_id>')
    @login_required
    def cancelar_reserva(pedido_id):
        # Solo admin o el dueño del pedido pueden cancelar
        reserva = Pedido.query.get_or_404(pedido_id)

        if current_user.rol != 'admin' and reserva.usuario_id != current_user.id:
            flash("No tienes permiso.", "danger")
            return redirect(url_for('index'))

        if reserva.estado == 'pendiente':
            producto = Producto.query.get(reserva.producto_id)
            if producto:
                # Liberamos el stock bloqueado de la reserva cancelada
                producto.cantidad_actual += reserva.cantidad
            reserva.estado = 'cancelado'
            db.session.commit()
            flash("Reserva cancelada y stock devuelto.", "warning")

        if current_user.rol == 'admin':
            return redirect(url_for('panel_admin_reservas'))
        return redirect(url_for('pedidos_clientes'))

    @app.route('/dashboard')
    @login_required
    @admin_required
    def dashboard():

        limpiar_reservas_expiradas()

        # Obtener parámetros de filtro
        filtro_fecha_inicio = request.args.get('fecha_inicio', '')
        filtro_fecha_fin = request.args.get('fecha_fin', '')
        filtro_tipo = request.args.get('tipo', '')
        filtro_involucrado = request.args.get('involucrado', '')
        filtro_producto = request.args.get('producto', '')

        # Solo ventas completadas cuentan como ingreso real
        ventas_reales = Pedido.query.filter_by(tipo='venta', estado='completado').all()
        compras_proveedor = Pedido.query.filter_by(tipo='compra', estado='completado').all()

        total_ingresos = sum(v.total_venta for v in ventas_reales)
        total_costos = sum(c.precio_unidad_coste * c.cantidad for c in compras_proveedor)

        # Conversión explícita a float para compatibilidad con Plotly
        categorias = ["Ingresos Totales", "Costos Totales"]
        valores = [float(total_ingresos), float(total_costos)]

        fig_bar = px.bar(
            x=categorias,
            y=valores,
            title="Comparacion Costos contra Ingresos (€)",
            color=categorias,
            color_discrete_map={
                "Ingresos Totales": "#198754",
                "Costos Totales": "#dc3545"
            }
        )

        # 1. Quitamos la leyenda (la explicación de colores de la derecha)
        fig_bar.update_layout(showlegend=False, xaxis_title=None, yaxis_title=None, hovermode="x unified")

        # 2. Personalizamos la información al pasar el ratón (hover)
        # %{y} muestra el valor y .2f le da dos decimales.
        fig_bar.update_traces(hovertemplate="Valor: %{y:.2f}€<extra></extra>")

        # Convertir a JSON de forma explícita
        graph_bar_json = json.dumps(fig_bar, cls=plotly.utils.PlotlyJSONEncoder)

        # --- MÉTRICAS ---
        # 1. Valor del inventario actual - UNA SOLA CONSULTA AGREGADA
        valor_inventario_total = db.session.query(
            func.sum(
                Producto.cantidad_actual *
                func.coalesce(
                    # Subconsulta para calcular costo promedio
                    db.session.query(
                        func.sum(Pedido.precio_unidad_coste * Pedido.cantidad) / func.sum(Pedido.cantidad)
                    ).filter(
                        Pedido.producto_id == Producto.id,
                        Pedido.tipo == 'compra',
                        Pedido.estado == 'completado'
                    ).correlate(Producto).scalar_subquery(),
                    Producto.precio_coste  # Valor por defecto si no hay compras
                )
            )
        ).filter(Producto.active == True).scalar() or 0

        # 2. Margen de beneficio promedio - CONSULTA AGREGADA
        if ventas_reales:
            # Calcular ganancia total usando subconsulta para costo promedio
            total_ganancia_neta = 0
            for venta in ventas_reales:
                # Obtener costo promedio del producto (ya calculado anteriormente)
                costo_promedio = db.session.query(
                    func.sum(Pedido.precio_unidad_coste * Pedido.cantidad) / func.sum(Pedido.cantidad)
                ).filter(
                    Pedido.producto_id == venta.producto_id,
                    Pedido.tipo == 'compra',
                    Pedido.estado == 'completado'
                ).scalar() or venta.precio_unidad_coste

                ganancia_venta = venta.total_venta - (costo_promedio * venta.cantidad)
                total_ganancia_neta += ganancia_venta

            margen_beneficio_promedio = (total_ganancia_neta / total_ingresos * 100) if total_ingresos > 0 else 0
        else:
            margen_beneficio_promedio = 0

        # 3. Top 3 clientes con mayores compras
        top_clientes_raw = db.session.query(
            Usuario,
            func.count(Pedido.id).label('num_compras'),
            func.sum(Pedido.total_venta).label('total_gastado')
        ).join(Pedido, Usuario.id == Pedido.usuario_id).filter(
            Pedido.tipo == 'venta',
            Pedido.estado == 'completado',
            Usuario.rol == 'cliente'
        ).group_by(Usuario.id).order_by(func.sum(Pedido.total_venta).desc()).limit(3).all()

        top_3_clientes = []
        for cliente, num_compras, total_gastado in top_clientes_raw:
            top_3_clientes.append({
                'nombre': cliente.username,
                'id_cliente': f'ID: {cliente.id}',
                'num_compras': num_compras,
                'total_gastado': round(float(total_gastado), 2)
            })

        # --- TABLA TOP 3 PRODUCTOS ---
        top_ventas_raw = db.session.query(
            Producto,
            func.sum(Pedido.cantidad).label('total_qty'),
            func.sum(Pedido.total_venta).label('total_ingreso')
        ).join(Pedido).filter(
            Pedido.tipo == 'venta',
            Pedido.estado == 'completado'
        ).group_by(Producto.id) \
            .order_by(func.sum(Pedido.cantidad).desc()) \
            .limit(3).all()

        top_3_tabla = []
        for p, qty, ingreso in top_ventas_raw:
            # Calcular costo promedio en UNA consulta agregada
            costo_promedio_real = db.session.query(
                func.sum(Pedido.precio_unidad_coste * Pedido.cantidad) / func.sum(Pedido.cantidad)
            ).filter(
                Pedido.producto_id == p.id,
                Pedido.tipo == 'compra',
                Pedido.estado == 'completado'
            ).scalar() or p.precio_coste

            # Cálculo de ganancia neta
            costo_total_vendido = costo_promedio_real * qty
            ganancia = ingreso - costo_total_vendido

            top_3_tabla.append({
                'nombre': p.nombre,
                'cantidad': qty,
                'costo_total': round(costo_total_vendido, 2),
                'venta_total': ingreso,
                'ganancia': round(ganancia, 2)
            })

        # --- TABLA HISTORIAL DE TRANSACCIONES CON FILTROS ---
        # Consultas base con filtros
        query_compras = Pedido.query.filter_by(tipo='compra', estado='completado')
        query_ventas = Pedido.query.filter_by(tipo='venta', estado='completado')

        # Aplicar filtro de fecha
        if filtro_fecha_inicio:
            try:
                fecha_inicio = datetime.strptime(filtro_fecha_inicio, '%Y-%m-%d')
                fecha_inicio = fecha_inicio.replace(tzinfo=timezone.utc)
                query_compras = query_compras.filter(Pedido.fecha >= fecha_inicio)
                query_ventas = query_ventas.filter(Pedido.fecha >= fecha_inicio)
            except ValueError:
                pass

        if filtro_fecha_fin:
            try:
                fecha_fin = datetime.strptime(filtro_fecha_fin, '%Y-%m-%d')
                # Incluir todo el día final
                fecha_fin = fecha_fin.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                query_compras = query_compras.filter(Pedido.fecha <= fecha_fin)
                query_ventas = query_ventas.filter(Pedido.fecha <= fecha_fin)
            except ValueError:
                pass

        # Aplicar filtro de producto
        if filtro_producto:
            query_compras = query_compras.filter(Pedido.producto_id == int(filtro_producto))
            query_ventas = query_ventas.filter(Pedido.producto_id == int(filtro_producto))

        # Obtener transacciones según filtro de tipo
        todas_compras = []
        todas_ventas = []

        if not filtro_tipo or filtro_tipo == 'compra':
            todas_compras = query_compras.order_by(Pedido.fecha.desc()).all()

        if not filtro_tipo or filtro_tipo == 'venta':
            todas_ventas = query_ventas.order_by(Pedido.fecha.desc()).all()

        # Crear lista de transacciones con información relevante
        historial_transacciones = []

        # Agregar compras
        for compra in todas_compras:
            producto = Producto.query.get(compra.producto_id)
            proveedor = producto.proveedor if producto and producto.proveedor_id else None
            nombre_proveedor = proveedor.nombre_empresa if proveedor else 'Sin proveedor'

            # Filtrar por proveedor/cliente si se especifica
            if filtro_involucrado and filtro_involucrado.lower() not in nombre_proveedor.lower():
                continue

            historial_transacciones.append({
                'fecha': compra.fecha,
                'tipo': 'Compra',
                'involucrado': nombre_proveedor,
                'producto': producto.nombre if producto else 'Producto eliminado',
                'cantidad': compra.cantidad,
                'monto': round(compra.precio_unidad_coste * compra.cantidad, 2)
            })

        # Agregar ventas
        for venta in todas_ventas:
            producto = Producto.query.get(venta.producto_id)
            cliente = Usuario.query.get(venta.usuario_id)
            nombre_cliente = cliente.username if cliente else 'Usuario eliminado'

            # Filtrar por proveedor/cliente si se especifica
            if filtro_involucrado and filtro_involucrado.lower() not in nombre_cliente.lower():
                continue

            historial_transacciones.append({
                'fecha': venta.fecha,
                'tipo': 'Venta',
                'involucrado': nombre_cliente,
                'producto': producto.nombre if producto else 'Producto eliminado',
                'cantidad': venta.cantidad,
                'monto': round(venta.total_venta, 2)
            })

        # Ordenar por fecha descendente (más recientes primero)
        historial_transacciones.sort(key=lambda x: x['fecha'], reverse=True)

        # Calcular totales de las transacciones filtradas
        total_compras = sum(t['monto'] for t in historial_transacciones if t['tipo'] == 'Compra')
        total_ventas = sum(t['monto'] for t in historial_transacciones if t['tipo'] == 'Venta')
        balance_neto = total_ventas - total_compras
        cantidad_total = sum(t['cantidad'] for t in historial_transacciones)

        # Obtener listas para los selectores de filtro
        todos_productos = Producto.query.all()
        todos_proveedores = Proveedor.query.all()
        todos_clientes = Usuario.query.filter_by(rol='cliente').all()

        return render_template('dashboard.html',
                               graph_bar=graph_bar_json,
                               top_3=top_3_tabla,
                               historial=historial_transacciones,
                               productos=todos_productos,
                               proveedores=todos_proveedores,
                               clientes=todos_clientes,
                               filtro_fecha_inicio=filtro_fecha_inicio,
                               filtro_fecha_fin=filtro_fecha_fin,
                               filtro_tipo=filtro_tipo,
                               filtro_involucrado=filtro_involucrado,
                               filtro_producto=filtro_producto,
                               valor_inventario=round(valor_inventario_total, 2),
                               margen_beneficio=round(margen_beneficio_promedio, 2),
                               top_clientes=top_3_clientes,
                               total_compras=round(total_compras, 2),
                               total_ventas=round(total_ventas, 2),
                               balance_neto=round(balance_neto, 2),
                               cantidad_total=cantidad_total)

    @app.route('/catalogo')
    @login_required
    def ver_catalogo():
        """Muestra el catálogo de productos disponibles con búsqueda."""
        # Obtener término de búsqueda desde URL
        busqueda = request.args.get('busqueda', '').strip()

        # Consulta base: productos activos con stock disponible
        query = Producto.query.filter(Producto.cantidad_actual > 0, Producto.active == True)

        if busqueda:
            # Búsqueda en nombre, referencia y descripción
            filtro = f"%{busqueda}%"
            query = query.filter(
                db.or_(
                    Producto.nombre.ilike(filtro),
                    Producto.referencia.ilike(filtro),
                    Producto.descripcion.ilike(filtro)
                )
            )

        productos_en_stock = query.all()
        return render_template('catalogo.html', productos=productos_en_stock, busqueda=busqueda)

    @app.route('/producto/reabastecer/<int:producto_id>', methods=['POST'])
    @login_required
    @admin_required
    def reabastecer_producto(producto_id):
        """Reabastece un producto aplicando el descuento del proveedor al costo."""
        producto = Producto.query.get_or_404(producto_id)

        try:
            cantidad_compra = int(request.form.get('cantidad', 0))

            if cantidad_compra <= 0:
                flash("La cantidad debe ser mayor a 0.", "warning")
                return redirect(url_for('inventario'))

            # Validación límite: no exceder stock máximo configurado
            if producto.cantidad_actual + cantidad_compra > producto.stock_maximo:
                flash(f"No puedes añadir {cantidad_compra} unidades. Excederías el stock máximo de {producto.stock_maximo}. Actualmente tienes {producto.cantidad_actual}.", "danger")
                return redirect(url_for('inventario'))

        except (ValueError, TypeError):
            flash("Cantidad inválida", "danger")
            return redirect(url_for('inventario'))

        if cantidad_compra > 0:
            producto.cantidad_actual += cantidad_compra

            # Aplicar descuento del proveedor al costo real de la compra
            proveedor = Proveedor.query.get(producto.proveedor_id) if producto.proveedor_id else None
            descuento_proveedor = proveedor.descuento if proveedor else 0.0
            costo_real_con_descuento = round(producto.precio_coste * (1 - descuento_proveedor / 100), 2)

            # Registro como compra para auditoría de costos
            nueva_compra = Pedido(
                cantidad=cantidad_compra,
                precio_unidad_coste=costo_real_con_descuento,  # Costo real con descuento aplicado
                precio_unidad_venta=producto.precio_venta,
                total_venta=0,
                tipo='compra',
                estado='completado',  # Las compras se registran directamente como completadas
                usuario_id=current_user.id,
                producto_id=producto.id
            )

            db.session.add(nueva_compra)
            db.session.commit()
            flash(f"Se han añadido {cantidad_compra} unidades a {producto.nombre}.", "success")

        return redirect(url_for('inventario'))

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)

