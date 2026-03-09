# PF SUMINISTROS TECNOLÓGICOS

Sistema de gestión de inventario y ventas desarrollado con Flask.

## Requisitos

- Python 3.8 o superior
- pip (gestor de paquetes de Python)

## Instalación

1. Clona este repositorio o descarga los archivos

2. Crea un entorno virtual (recomendado):
   ```bash
   python -m venv venv
   ```

3. Activa el entorno virtual:
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - Linux/Mac:
     ```bash
     source venv/bin/activate
     ```

4. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

5. Configura las variables de entorno:
   - Edita el archivo `.env` con tus credenciales:
     ```
     ADMIN_USER=tu_usuario_admin
     ADMIN_PASS=tu_contraseña_admin
     SECRET_KEY=tu_clave_secreta_aqui
     ```
   - Para generar una clave secreta segura, puedes usar:
     ```python
     import secrets
     print(secrets.token_hex(32))
     ```

## Ejecución

1. Ejecuta la aplicación:
   ```bash
   python main.py
   ```

2. Abre tu navegador en: `http://localhost:5000`

## Estructura del Proyecto

- `main.py` - Aplicación principal de Flask con todas las rutas
- `models.py` - Modelos de base de datos (Usuario, Producto, Pedido, Proveedor)
- `db.py` - Configuración de SQLAlchemy
- `templates/` - Plantillas HTML
- `database/` - Base de datos SQLite
- `requirements.txt` - Dependencias del proyecto
- `.env` - Variables de entorno (no incluido en el repositorio)

## Características

- Sistema de autenticación de usuarios
- Gestión de inventario
- Gestión de proveedores
- Sistema de pedidos
- Panel de administración
- Dashboard con estadísticas
- Carrito de compras

## Roles de Usuario

- **Admin**: Acceso completo al sistema
- **Cliente**: Acceso limitado a catálogo y carrito

## Tecnologías Utilizadas

- Flask - Framework web
- SQLAlchemy - ORM para base de datos
- Flask-Login - Gestión de sesiones
- Plotly - Visualización de datos
- Pandas - Procesamiento de datos
- Bootstrap - Framework CSS (en templates)


