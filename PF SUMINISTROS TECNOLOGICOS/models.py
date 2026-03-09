from db import db
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

# UserMixin provee is_authenticated, is_active, get_id
class Usuario(db.Model, UserMixin):
    """Modelo de usuario con autenticación y control de acceso por roles."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)  # Índice para búsquedas rápidas en login
    password = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='cliente', index=True)  # Índice para filtros por rol
    activo = db.Column(db.Boolean, default=True, index=True)  # Índice para filtros de usuarios activos

    def set_password(self, password_plana):
        """Hashea y almacena la contraseña usando bcrypt."""
        self.password = generate_password_hash(password_plana)

    def check_password(self, password_plana):
        """Verifica si la contraseña proporcionada coincide con el hash almacenado."""
        return check_password_hash(self.password, password_plana)

class Proveedor(db.Model):
    """Modelo de proveedor con datos fiscales y comerciales."""
    id = db.Column(db.Integer, primary_key=True)
    nombre_empresa = db.Column(db.String(100), nullable=False, index=True)  # Índice para búsquedas
    cif = db.Column(db.String(20), unique=True, index=True)  # Índice para búsquedas por CIF
    telefono = db.Column(db.String(20))
    direccion = db.Column(db.String(200))
    descuento = db.Column(db.Float, default=0.0)
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)  # Índice para filtros de activos
    productos = db.relationship('Producto', backref='proveedor', lazy='dynamic')  # lazy='dynamic' para consultas optimizadas

class Producto(db.Model):
    """Modelo de producto con control de stock y precios."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, index=True)  # Índice para búsquedas
    descripcion = db.Column(db.Text)
    precio_coste = db.Column(db.Float, nullable=False)
    precio_venta = db.Column(db.Float, nullable=False)
    cantidad_actual = db.Column(db.Integer, default=0, index=True)  # Índice para filtros de stock
    stock_maximo = db.Column(db.Integer, default=100)
    referencia = db.Column(db.String(50), unique=True, index=True)  # Índice para búsquedas por referencia
    ubicacion = db.Column(db.String(100))
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedor.id'), index=True)  # Índice para JOINs
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)  # Índice para filtros de activos

    # Índice compuesto para búsquedas complejas (nombre + referencia)
    __table_args__ = (
        db.Index('idx_producto_busqueda', 'nombre', 'referencia'),
        db.Index('idx_producto_activo_stock', 'active', 'cantidad_actual'),  # Para catálogo
    )

class Pedido(db.Model):
    """Modelo de pedido que registra ventas a clientes y compras a proveedores."""
    id = db.Column(db.Integer, primary_key=True)
    # UTC evita inconsistencias con zonas horarias
    fecha = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)  # Índice para ordenación
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unidad_coste = db.Column(db.Float, nullable=False)
    precio_unidad_venta = db.Column(db.Float, nullable=False)
    total_venta = db.Column(db.Float, nullable=False)
    descuento_aplicado = db.Column(db.Float, default=0.0)
    iva_aplicado = db.Column(db.Float, default=21.0)
    # Tipo: 'venta' (cliente) vs 'compra' (proveedor)
    tipo = db.Column(db.String(10), nullable=False, default='venta', index=True)  # Índice para filtros
    # Estado: pendiente → completado/cancelado
    estado = db.Column(db.String(20), default='pendiente', index=True)  # Índice para filtros

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False, index=True)  # Índice para JOINs
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False, index=True)  # Índice para JOINs

    usuario = db.relationship('Usuario', backref=db.backref('pedidos', lazy='dynamic'))  # lazy='dynamic' optimizado
    producto = db.relationship('Producto', backref=db.backref('pedidos', lazy='dynamic'))  # lazy='dynamic' optimizado

    # Índices compuestos para consultas frecuentes
    __table_args__ = (
        db.Index('idx_pedido_tipo_estado', 'tipo', 'estado'),  # Para dashboard
        db.Index('idx_pedido_usuario_estado', 'usuario_id', 'estado'),  # Para pedidos de cliente
        db.Index('idx_pedido_producto_tipo', 'producto_id', 'tipo', 'estado'),  # Para stock reservado
    )
