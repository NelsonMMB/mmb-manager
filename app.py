import streamlit as st
import sqlite3
import os
import datetime
from PIL import Image as PILImage
from streamlit_drawable_canvas import st_canvas

# Librerías para generación de PDF con ReportLab
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as PDFFigure
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Configuración inicial de la página
st.set_page_config(page_title="MMB Manager", layout="wide")

# Estilos generales y colores corporativos basados en tu logo
st.markdown("""
    <style>
    [data-testid="stSidebar"] { width: 290px !important; min-width: 290px !important; background-color: #f8fafc; padding-top: 10px; border-right: 2px solid #e2e8f0; }
    [data-testid="collapsedControl"] { display: none !important; }
    .main-header { background-color: #2d3748; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border-left: 6px solid #f39c12; }
    .stButton>button { width: 100% !important; border-radius: 6px; font-weight: bold; margin-bottom: 5px; background-color: #2d3748; color: white; }
    .stButton>button:hover { background-color: #f39c12; color: #000000; }
    </style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# INICIALIZAR BASE DE DATOS Y TABLAS
# -------------------------------------------------------------
def inicializar_bd():
    os.makedirs("database", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)
    conexion = sqlite3.connect("database/mmb.db")
    cursor = conexion.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_empresa TEXT NOT NULL,
            nit TEXT,
            direccion TEXT,
            contacto TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tecnicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cedula TEXT NOT NULL UNIQUE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            tipo_equipo TEXT,
            marca TEXT,
            modelo TEXT,
            serial TEXT,
            capacidad REAL,
            altura REAL,
            horometro REAL DEFAULT 0,
            foto_path TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    """)

    cursor.execute("PRAGMA table_info(equipos)")
    columnas_eq = [col[1] for col in cursor.fetchall()]
    if "foto_path" not in columnas_eq:
        cursor.execute("ALTER TABLE equipos ADD COLUMN foto_path TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consecutivos (
            tipo TEXT PRIMARY KEY,
            ultimo_numero INTEGER
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO consecutivos (tipo, ultimo_numero) VALUES ('OS', 0)")
    cursor.execute("INSERT OR IGNORE INTO consecutivos (tipo, ultimo_numero) VALUES ('COT', 0)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consecutivo TEXT,
            cliente_id INTEGER,
            detalles TEXT,
            total REAL,
            fecha TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ordenes_servicio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consecutivo TEXT,
            cliente_id INTEGER,
            equipo_id INTEGER,
            tecnico_id INTEGER,
            tipo_servicio TEXT,
            horometro_actual REAL,
            observaciones TEXT,
            persona_recibe TEXT,
            foto_path TEXT,
            fecha TEXT,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id),
            FOREIGN KEY (equipo_id) REFERENCES equipos (id),
            FOREIGN KEY (tecnico_id) REFERENCES tecnicos (id)
        )
    """)

    cursor.execute("PRAGMA table_info(ordenes_servicio)")
    columnas_os = [col[1] for col in cursor.fetchall()]
    if "foto_path" not in columnas_os:
        cursor.execute("ALTER TABLE ordenes_servicio ADD COLUMN foto_path TEXT")
    if "tecnico_id" not in columnas_os:
        cursor.execute("ALTER TABLE ordenes_servicio ADD COLUMN tecnico_id INTEGER")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cronograma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo_id INTEGER,
            titulo_evento TEXT,
            fecha_programada TEXT,
            estado TEXT,
            FOREIGN KEY (equipo_id) REFERENCES equipos (id)
        )
    """)

    conexion.commit()
    conexion.close()

inicializar_bd()
ruta_db = "database/mmb.db"

def obtener_siguiente_consecutivo(tipo):
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("SELECT ultimo_numero FROM consecutivos WHERE tipo = ?", (tipo,))
    ultimo = cursor.fetchone()[0]
    siguiente = ultimo + 1
    cursor.execute("UPDATE consecutivos SET ultimo_numero = ? WHERE tipo = ?", (siguiente, tipo))
    conexion.commit()
    conexion.close()
    
    prefix = "OS" if tipo == "OS" else "COT"
    return f"{prefix}-{siguiente:03d}"

def ver_proximo_consecutivo(tipo):
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("SELECT ultimo_numero FROM consecutivos WHERE tipo = ?", (tipo,))
    ultimo = cursor.fetchone()[0]
    conexion.close()
    
    siguiente = ultimo + 1
    prefix = "OS" if tipo == "OS" else "COT"
    return f"{prefix}-{siguiente:03d}"

def recaudar_fecha_actual():
    return datetime.date.today().strftime("%Y-%m-%d")

# -------------------------------------------------------------
# DEFINICIÓN DE CHECKLISTS TÉCNICOS COMPLETOS
# -------------------------------------------------------------
def obtener_items_checklist(tipo_eq):
    if "Eléctrico" in tipo_eq or "Apilador" in tipo_eq:
        return [
            "1. Estado de Batería (Nivel de electrolito/Voltaje)",
            "2. Estado de bornes y cables de potencia",
            "3. Funcionamiento de Motor de Tracción",
            "4. Funcionamiento de Motor de Elevación",
            "5. Sistema Hidráulico (Mangueras/Cilindros/Fugas)",
            "6. Sistema de Dirección y Ruedas motrices",
            "7. Estado de Llantas (Desgaste/Cortes)",
            "8. Sistema de Frenos (Electromagnético/Pedal)",
            "9. Tablero de control y pantalla de errores",
            "10. Dispositivos de seguridad (Bocina/Luces/Alarma retroceso)"
        ]
    elif "Combustión" in tipo_eq:
        return [
            "1. Nivel y estado de lubricantes (Motor/Transmisión)",
            "2. Sistema de refrigeración (Radiador/Mangueras/Ventilador)",
            "3. Sistema de admisión (Filtros de aire/Combustible)",
            "4. Sistema de Gas LP / Diesel (Fugas/Reguladores/Filtros)",
            "5. Sistema Hidráulico (Nivel/Fugas/Cilindros)",
            "6. Terminales de dirección y eje trasero",
            "7. Estado de Llantas (Profundidad/Cortes/Desgaste)",
            "8. Sistema de Frenos (Zapatas/Discos/Líquido/Parqueo)",
            "9. Tablero de control y testigos en tablero",
            "10. Dispositivos de seguridad (Bocina/Luces/Mástil/Cadenas)"
        ]
    else:
        return [
            "1. Estructura y Uñas de carga",
            "2. Sistema Hidráulico (Fugas/Sellos)",
            "3. Estado de Ruedas y Rodamientos",
            "4. Sistema de Frenos de Mano",
            "5. Articulaciones y puntos de engrase"
        ]

# -------------------------------------------------------------
# GENERADORES DE PDF CORPORATIVOS CON LOGO (REPORTLAB)
# -------------------------------------------------------------
def construir_encabezado_pdf():
    elementos_encabezado = []
    if os.path.exists("logo.png"):
        try:
            logo_pdf = PDFFigure("logo.png", width=120, height=50)
            logo_pdf.hAlign = 'CENTER'
            elementos_encabezado.append(logo_pdf)
            elementos_encabezado.append(Spacer(1, 5))
        except:
            pass

    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle('TituloCorp', parent=styles['Heading1'], fontSize=12, fontName="Helvetica-Bold", textColor=colors.HexColor('#2d3748'), alignment=1, spaceAfter=2)
    estilo_eslogan = ParagraphStyle('EsloganCorp', parent=styles['Normal'], fontSize=8.5, fontName="Helvetica-Oblique", textColor=colors.HexColor('#f39c12'), alignment=1, spaceAfter=4)
    estilo_sub = ParagraphStyle('SubCorp', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#4a5568'), alignment=1, spaceAfter=10)

    elementos_encabezado.append(Paragraph("<b>MONTACARGAS Y MANTENIMIENTOS BUCARAMANGA MMB</b>", estilo_titulo))
    elementos_encabezado.append(Paragraph("“Soluciones integrales para el manejo de carga y potencia industrial”", estilo_eslogan))
    elementos_encabezado.append(Paragraph("<b>Nelson Alberto Rojas Hernandez</b><br/>NIT: 1098604964-5 | Régimen Simplificado<br/>Cel: 3003043555 | Email: mantenimientos.bucaramanga@hotmail.com<br/>Bucaramanga, Santander", estilo_sub))
    return elementos_encabezado

def generar_pdf_orden(consecutivo, cliente_info, equipo_info, tipo_servicio, horometro, observaciones, recibe, tecnico_info, resultados_chk=None, foto_path=None):
    ruta_pdf = f"reports/{consecutivo}.pdf"
    doc = SimpleDocTemplate(ruta_pdf, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elementos = []
    elementos.extend(construir_encabezado_pdf())
    
    styles = getSampleStyleSheet()
    estilo_texto = ParagraphStyle('TextoCorp', parent=styles['Normal'], fontSize=9.5, textColor=colors.HexColor('#2d3748'))
    estilo_negrita = ParagraphStyle('NegritaCorp', parent=styles['Normal'], fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.HexColor('#2d3748'))

    tec_nombre, tec_cedula = tecnico_info if tecnico_info else ("No asignado", "N/A")

    data_encabezado = [
        [Paragraph(f"<b>Orden de Servicio:</b> {consecutivo}", estilo_texto), Paragraph(f"<b>Fecha:</b> {recaudar_fecha_actual()}", estilo_texto)],
        [Paragraph(f"<b>Técnico Encargado:</b> {tec_nombre}", estilo_texto), Paragraph(f"<b>Cédula Técnico:</b> {tec_cedula}", estilo_texto)],
        [Paragraph(f"<b>Cliente:</b> {cliente_info[1]}", estilo_texto), Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto)],
        [Paragraph(f"<b>Dirección:</b> {cliente_info[3]}", estilo_texto), Paragraph(f"<b>Contacto:</b> {cliente_info[4]}", estilo_texto)]
    ]
    t_enc = Table(data_encabezado, colWidths=[270, 270])
    t_enc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('LINEBELOW', (0,0), (-1,0), 1.5, colors.HexColor('#f39c12')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(t_enc)
    elementos.append(Spacer(1, 8))

    elementos.append(Paragraph("<b>INFORMACIÓN DEL MONTACARGAS INTERVENIDO</b>", estilo_negrita))
    data_equipo = [
        [Paragraph(f"<b>Tipo:</b> {equipo_info[1]}", estilo_texto), Paragraph(f"<b>Marca:</b> {equipo_info[2]}", estilo_texto)],
        [Paragraph(f"<b>Modelo:</b> {equipo_info[3]}", estilo_texto), Paragraph(f"<b>Serial:</b> {equipo_info[4]}", estilo_texto)],
        [Paragraph(f"<b>Capacidad:</b> {equipo_info[5]} kg", estilo_texto), Paragraph(f"<b>Horómetro Actual:</b> {horometro} hrs", estilo_texto)]
    ]
    t_eq = Table(data_equipo, colWidths=[270, 270])
    t_eq.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_eq)
    elementos.append(Spacer(1, 8))

    elementos.append(Paragraph(f"<b>Tipo de Servicio:</b> {tipo_servicio}", estilo_negrita))
    elementos.append(Spacer(1, 4))

    if resultados_chk:
        elementos.append(Paragraph("<b>CHECKLIST DE INSPECCIÓN TÉCNICA (B: Bueno | R: Regular | M: Malo)</b>", estilo_negrita))
        elementos.append(Spacer(1, 3))
        data_chk_pdf = [[Paragraph("<b>Ítem de Inspección</b>", estilo_negrita), Paragraph("<b>Estado</b>", estilo_negrita)]]
        for item_desc, estado_val in resultados_chk:
            data_chk_pdf.append([Paragraph(item_desc, estilo_texto), Paragraph(f"<b>{estado_val}</b>", estilo_texto)])
        
        t_chk_pdf = Table(data_chk_pdf, colWidths=[440, 100])
        t_chk_pdf.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f39c12')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 3),
            ('ALIGN', (1,1), (1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elementos.append(t_chk_pdf)
        elementos.append(Spacer(1, 8))

    elementos.append(Paragraph(f"<b>Trabajos Realizados / Observaciones Generales:</b><br/>{observaciones}", estilo_texto))
    elementos.append(Spacer(1, 8))

    if foto_path and os.path.exists(foto_path):
        try:
            elementos.append(Paragraph("<b>Registro Fotográfico del Servicio:</b>", estilo_negrita))
            elementos.append(Spacer(1, 3))
            img_pdf = PDFFigure(foto_path, width=180, height=130)
            img_pdf.hAlign = 'CENTER'
            elementos.append(img_pdf)
            elementos.append(Spacer(1, 8))
        except:
            pass

    data_firma = [
        [Paragraph("<b>Observaciones de Entrega:</b> Equipo entregado a entera satisfacción del cliente.", estilo_texto)],
        [Paragraph(f"<br/><br/>__________________________________________<br/><b>Recibe a Satisfacción:</b> {recibe}<br/>C.C. / NIT:", estilo_texto)]
    ]
    t_firma = Table(data_firma, colWidths=[540])
    t_firma.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f8fafc'))
    ]))
    elementos.append(t_firma)

    doc.build(elementos)
    return ruta_pdf

def generar_pdf_cotizacion(consecutivo, cliente_info, items_cotizacion, total_cot, fecha):
    ruta_pdf = f"reports/{consecutivo}.pdf"
    doc = SimpleDocTemplate(ruta_pdf, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elementos = []
    elementos.extend(construir_encabezado_pdf())
    
    styles = getSampleStyleSheet()
    estilo_texto = ParagraphStyle('TextoCorp', parent=styles['Normal'], fontSize=9.5, textColor=colors.HexColor('#2d3748'))
    estilo_negrita = ParagraphStyle('NegritaCorp', parent=styles['Normal'], fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.HexColor('#2d3748'))

    data_encabezado = [
        [Paragraph(f"<b>Cotización No.:</b> {consecutivo}", estilo_texto), Paragraph(f"<b>Fecha de Emisión:</b> {fecha}", estilo_texto)],
        [Paragraph(f"<b>Cliente:</b> {cliente_info[1]}", estilo_texto), Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto)],
        [Paragraph(f"<b>Dirección:</b> {cliente_info[3]}", estilo_texto), Paragraph(f"<b>Contacto:</b> {cliente_info[4]}", estilo_texto)]
    ]
    t_enc = Table(data_encabezado, colWidths=[270, 270])
    t_enc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('LINEBELOW', (0,0), (-1,0), 1.5, colors.HexColor('#f39c12')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(t_enc)
    elementos.append(Spacer(1, 15))

    elementos.append(Paragraph("<b>DETALLE DE REPUESTOS, SERVICIOS Y MANO DE OBRA</b>", estilo_negrita))
    elementos.append(Spacer(1, 5))

    tabla_datos = [[Paragraph("<b>Descripción</b>", estilo_negrita), Paragraph("<b>Cant.</b>", estilo_negrita), Paragraph("<b>V. Unitario</b>", estilo_negrita), Paragraph("<b>Subtotal</b>", estilo_negrita)]]
    
    for item in items_cotizacion:
        tabla_datos.append([
            Paragraph(item["desc"], estilo_texto),
            Paragraph(str(item["cant"]), estilo_texto),
            Paragraph(f"${item['pu']:,.2f}", estilo_texto),
            Paragraph(f"${item['sub']:,.2f}", estilo_texto)
        ])
    
    tabla_datos.append([
        Paragraph("<b>VALOR TOTAL COTIZACIÓN</b>", estilo_negrita),
        "", "",
        Paragraph(f"<b>${total_cot:,.2f} COP</b>", estilo_negrita)
    ])

    t_items = Table(tabla_datos, colWidths=[250, 60, 110, 120])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f39c12')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#f8fafc')),
        ('SPAN', (0, -1), (2, -1))
    ]))
    elementos.append(t_items)
    elementos.append(Spacer(1, 15))

    elementos.append(Paragraph("<b>Condiciones Comerciales:</b><br/>• Validez de la cotización: 15 días.<br/>• Forma de pago: Contado / Acordar con el cliente.<br/>• Garantía sobre los trabajos y repuestos especificados.", estilo_texto))

    doc.build(elementos)
    return ruta_pdf

def generar_pdf_hoja_de_vida(cliente_info, eq_data, historial_os):
    serial_limpio = eq_data[3].replace("/", "_").replace(" ", "_")
    ruta_pdf = f"reports/HV_{serial_limpio}.pdf"
    doc = SimpleDocTemplate(ruta_pdf, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elementos = []
    elementos.extend(construir_encabezado_pdf())
    
    styles = getSampleStyleSheet()
    estilo_texto = ParagraphStyle('TextoCorp', parent=styles['Normal'], fontSize=9.5, textColor=colors.HexColor('#2d3748'))
    estilo_negrita = ParagraphStyle('NegritaCorp', parent=styles['Normal'], fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.HexColor('#2d3748'))
    estilo_titulo_hv = ParagraphStyle('TitHV', parent=styles['Heading2'], fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor('#2d3748'), spaceAfter=6)

    data_encabezado = [
        [Paragraph(f"<b>HOJA DE VIDA DE EQUIPO</b>", estilo_negrita), Paragraph(f"<b>Fecha Impresión:</b> {recaudar_fecha_actual()}", estilo_texto)],
        [Paragraph(f"<b>Cliente Propietario:</b> {cliente_info[1]}", estilo_texto), Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto)],
    ]
    t_enc = Table(data_encabezado, colWidths=[270, 270])
    t_enc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('LINEBELOW', (0,0), (-1,0), 1.5, colors.HexColor('#f39c12')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(t_enc)
    elementos.append(Spacer(1, 10))

    foto_equipo_path = eq_data[9] if len(eq_data) > 9 else None
    
    data_specs = [
        [Paragraph(f"<b>Tipo de Equipo:</b> {eq_data[0]}", estilo_texto), Paragraph(f"<b>Marca:</b> {eq_data[1]}", estilo_texto)],
        [Paragraph(f"<b>Modelo:</b> {eq_data[2]}", estilo_texto), Paragraph(f"<b>Serial:</b> {eq_data[3]}", estilo_texto)],
        [Paragraph(f"<b>Capacidad:</b> {eq_data[4]} kg", estilo_texto), Paragraph(f"<b>Altura de Elevación:</b> {eq_data[5]} mm", estilo_texto)],
        [Paragraph(f"<b>Horómetro Actual:</b> {eq_data[6]} hrs", estilo_texto), ""]
    ]
    t_specs = Table(data_specs, colWidths=[270, 270])
    t_specs.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    if foto_equipo_path and os.path.exists(foto_equipo_path):
        try:
            img_eq = PDFFigure(foto_equipo_path, width=150, height=110)
            img_eq.hAlign = 'CENTER'
            tabla_foto_specs = Table([[t_specs, img_eq]], colWidths=[370, 170])
            tabla_foto_specs.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            elementos.append(tabla_foto_specs)
        except:
            elementos.append(t_specs)
    else:
        elementos.append(t_specs)

    elementos.append(Spacer(1, 15))
    elementos.append(Paragraph("<b>HISTORIAL Y RESUMEN DE SERVICIOS TÉCNICOS</b>", estilo_titulo_hv))

    if historial_os:
        tabla_historial = [[Paragraph("<b>Consecutivo</b>", estilo_negrita), Paragraph("<b>Tipo</b>", estilo_negrita), Paragraph("<b>Fecha</b>", estilo_negrita), Paragraph("<b>Horómetro</b>", estilo_negrita), Paragraph("<b>Trabajo / Observaciones</b>", estilo_negrita)]]
        for h in historial_os:
            tabla_historial.append([
                Paragraph(h[0], estilo_texto),
                Paragraph(h[1], estilo_texto),
                Paragraph(str(h[2]), estilo_texto),
                Paragraph(f"{h[5]} hrs", estilo_texto) if len(h) > 5 and h[5] is not None else Paragraph("N/A", estilo_texto),
                Paragraph(h[3], estilo_texto)
            ])
        t_hist = Table(tabla_historial, colWidths=[70, 70, 70, 70, 260])
        t_hist.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f39c12')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        elementos.append(t_hist)
    else:
        elementos.append(Paragraph("No se encuentran órdenes de servicio registradas para este equipo en su historial.", estilo_texto))

    doc.build(elementos)
    return ruta_pdf

# -------------------------------------------------------------
# CONTROL DE ESTADO DE NAVEGACIÓN (INICIO POR DEFECTO)
# -------------------------------------------------------------
if "menu_activo" not in st.session_state:
    st.session_state.menu_activo = "🏠 Inicio"

# -------------------------------------------------------------
# MENÚ LATERAL DE NAVEGACIÓN
# -------------------------------------------------------------
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.markdown("### **MMB Manager**")
    
    st.caption("Montacargas y Mantenimientos Bucaramanga")
    st.divider()
    
    if st.button("🏠 Inicio"):
        st.session_state.menu_activo = "🏠 Inicio"
        st.rerun()
    if st.button("📋 Órdenes de Servicio"):
        st.session_state.menu_activo = "📋 Órdenes de Servicio"
        st.rerun()
    if st.button("📑 Cotizaciones"):
        st.session_state.menu_activo = "📑 Cotizaciones"
        st.rerun()
    if st.button("📅 Cronograma"):
        st.session_state.menu_activo = "📅 Cronograma"
        st.rerun()
    if st.button("📖 Hojas de Vida"):
        st.session_state.menu_activo = "📖 Hojas de Vida"
        st.rerun()
    if st.button("👥 Clientes"):
        st.session_state.menu_activo = "👥 Clientes"
        st.rerun()
    if st.button("🛠️ Técnicos"):
        st.session_state.menu_activo = "🛠️ Técnicos"
        st.rerun()

menu = st.session_state.menu_activo

# -------------------------------------------------------------
# MÓDULO 0: INICIO / BIENVENIDA
# -------------------------------------------------------------
if menu == "🏠 Inicio":
    st.markdown('<div class="main-header"><h1>Montacargas y Mantenimientos Bucaramanga (MMB)</h1></div>', unsafe_allow_html=True)
    
    col_logo_ini, col_txt_ini = st.columns([1, 2])
    
    with col_logo_ini:
        if os.path.exists("logo.png"):
            st.image("logo.png", use_container_width=True)
        else:
            st.info("💡 Coloca tu archivo 'logo.png' en la carpeta del proyecto para visualizarlo aquí.")
            
    with col_txt_ini:
        st.markdown("### ¡Bienvenido a MMB Manager!")
        st.write("Sistema integral para la gestión de mantenimiento preventivo y correctivo, control de flotas de montacargas, órdenes de servicio y cotizaciones.")
        st.markdown("---")
        st.markdown("**Propietario:** Nelson Alberto Rojas Hernandez")
        st.markdown("**NIT:** 1098604964-5 | Régimen Simplificado")
        st.markdown("**Ubicación:** Bucaramanga, Santander")

    st.markdown("---")
    st.markdown("### 🚀 Accesos Directos a Módulos")
    
    col_d1, col_d2, col_d3 = st.columns(3)
    if col_d1.button("📋 Nueva Orden de Servicio"):
        st.session_state.menu_activo = "📋 Órdenes de Servicio"
        st.rerun()
    if col_d2.button("📑 Crear Cotización"):
        st.session_state.menu_activo = "📑 Cotizaciones"
        st.rerun()
    if col_d3.button("📖 Ver Hojas de Vida"):
        st.session_state.menu_activo = "📖 Hojas de Vida"
        st.rerun()

# -------------------------------------------------------------
# MÓDULO 1: ÓRDENES DE SERVICIO
# -------------------------------------------------------------
elif menu == "📋 Órdenes de Servicio":
    st.markdown('<div class="main-header"><h1>Montacargas y Mantenimientos Bucaramanga (MMB)</h1></div>', unsafe_allow_html=True)
    st.subheader("📋 Generador de Órdenes de Servicio")
    
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("SELECT id, nombre_empresa FROM clientes")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT id, nombre, cedula FROM tecnicos")
    tecnicos_db = cursor.fetchall()
    conexion.close()
    
    if not clientes:
        st.warning("⚠️ No hay clientes registrados. Ve primero al módulo de Clientes.")
    elif not tecnicos_db:
        st.warning("⚠️ No hay técnicos registrados. Ve primero al módulo de 🛠️ Técnicos para registrar al menos uno.")
    else:
        tecnico_dict = {f"{t[1]} (C.C. {t[2]})": t[0] for t in tecnicos_db}
        tec_sel = st.selectbox("Seleccionar Técnico Responsable", list(tecnico_dict.keys()))
        tecnico_id_sel = tecnico_dict[tec_sel]

        cliente_dict = {c[1]: c[0] for c in clientes}
        cliente_sel = st.selectbox("Seleccionar Cliente", list(cliente_dict.keys()))
        c_id = cliente_dict[cliente_sel]
        
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute("SELECT id, tipo_equipo, marca, modelo, serial, horometro FROM equipos WHERE cliente_id = ?", (c_id,))
        equipos = cursor.fetchall()
        conexion.close()
        
        if not equipos:
            st.warning(f"⚠️ El cliente '{cliente_sel}' no tiene montacargas asignados. Ve al módulo de Hojas de Vida para registrarle uno.")
        else:
            equipo_dict = {f"[{e[1]}] {e[2]} {e[3]} (Serial: {e[4]})": e for e in equipos}
            eq_label = st.selectbox("Seleccionar Montacarga", list(equipo_dict.keys()))
            eq_info = equipo_dict[eq_label]
            eq_id, tipo_eq, marca_eq, modelo_eq, serial_eq, hor_eq = eq_info
            
            proximo_os = ver_proximo_consecutivo("OS")
            st.info(f"📌 **Próximo Consecutivo de Orden:** `{proximo_os}` | **Montacarga:** {marca_eq} {modelo_eq} ({tipo_eq})")
            
            col1, col2 = st.columns(2)
            with col1:
                tipo_servicio = st.selectbox("Tipo de Servicio", ["Preventivo", "Correctivo"])
            with col2:
                nuevo_horometro = st.number_input("Horómetro Actual", value=float(hor_eq), step=0.5)
                
            nombre_recibe = st.text_input("Persona que Recibe a Satisfacción (Cliente)", "Carlos Julio Gómez")
            observaciones = st.text_area("Observaciones Generales / Trabajos Realizados", "Se realiza servicio técnico especializado en montacarga.")
            
            resultados_checklist = []
            if tipo_servicio == "Preventivo":
                st.markdown(f"### 📋 CHECKLIST TÉCNICO DE INSPECCIÓN ({tipo_eq.upper()})")
                st.caption("Marque el estado de cada componente: **B** (Bueno), **R** (Regular), **M** (Malo)")
                
                lista_items = obtener_items_checklist(tipo_eq)
                for idx, item_texto in enumerate(lista_items):
                    col_chk1, col_chk2 = st.columns([3, 1])
                    col_chk1.write(item_texto)
                    estado_elegido = col_chk2.radio(
                        "Estado", 
                        ["B", "R", "M"], 
                        key=f"chk_item_{idx}", 
                        horizontal=True, 
                        label_visibility="collapsed"
                    )
                    resultados_checklist.append((item_texto, estado_elegido))
            else:
                st.info("ℹ️ Servicio **Correctivo**: No aplica checklist preventivo estándar.")

            st.markdown("### 📷 Registro Fotográfico del Servicio")
            foto_os_file = st.file_uploader("Adjuntar foto del servicio o equipo intervenido", type=["png", "jpg", "jpeg"], key="foto_os_upload")
            ruta_foto_os_guardada = None
            if foto_os_file is not None:
                img_os = PILImage.open(foto_os_file)
                os.makedirs("uploads", exist_ok=True)
                ruta_foto_os_guardada = f"uploads/OS_{proximo_os}_{int(datetime.datetime.now().timestamp())}.jpg"
                img_os.save(ruta_foto_os_guardada)
                st.image(img_os, caption="Vista previa de la foto adjunta", width=300)

            st.markdown("### ✍️ Firma Digital del Cliente (Recibe a Satisfacción)")
            canvas_result = st_canvas(
                fill_color="rgba(255, 255, 255, 0)",
                stroke_width=2,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=130,
                width=350,
                drawing_mode="freedraw",
                key="canvas_firma",
            )
            
            if st.button("🚀 Guardar y Generar PDF de Orden de Servicio", type="primary"):
                siguiente_os = obtener_siguiente_consecutivo("OS")
                conexion = sqlite3.connect(ruta_db)
                cursor = conexion.cursor()
                cursor.execute("""
                    INSERT INTO ordenes_servicio (consecutivo, cliente_id, equipo_id, tecnico_id, tipo_servicio, horometro_actual, observaciones, persona_recibe, foto_path, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (siguiente_os, c_id, eq_id, tecnico_id_sel, tipo_servicio, nuevo_horometro, observaciones, nombre_recibe, ruta_foto_os_guardada))
                
                cursor.execute("UPDATE equipos SET horometro = ? WHERE id = ?", (nuevo_horometro, eq_id))
                conexion.commit()
                
                cursor.execute("SELECT * FROM clientes WHERE id = ?", (c_id,))
                c_data = cursor.fetchone()
                cursor.execute("SELECT * FROM equipos WHERE id = ?", (eq_id,))
                e_data = cursor.fetchone()
                cursor.execute("SELECT nombre, cedula FROM tecnicos WHERE id = ?", (tecnico_id_sel,))
                t_data = cursor.fetchone()
                conexion.close()
                
                ruta_pdf = generar_pdf_orden(siguiente_os, c_data, e_data, tipo_servicio, nuevo_horometro, observaciones, nombre_recibe, t_data, resultados_checklist, ruta_foto_os_guardada)
                
                st.success(f"🎉 Orden de Servicio **{siguiente_os}** generada con éxito.")
                with open(ruta_pdf, "rb") as pdf_file:
                    st.download_button(
                        label="📥 Descargar PDF de la Orden de Servicio",
                        data=pdf_file,
                        file_name=f"{siguiente_os}.pdf",
                        mime="application/pdf"
                    )

# -------------------------------------------------------------
# MÓDULO 2: COTIZACIONES
# -------------------------------------------------------------
elif menu == "📑 Cotizaciones":
    st.subheader("📑 Generador de Cotizaciones")
    
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("SELECT id, nombre_empresa FROM clientes")
    clientes = cursor.fetchall()
    conexion.close()
    
    if not clientes:
        st.warning("⚠️ Debes registrar un cliente primero en el módulo de Clientes.")
    else:
        cliente_dict = {c[1]: c[0] for c in clientes}
        cliente_sel = st.selectbox("Seleccionar Cliente para Cotización", list(cliente_dict.keys()))
        c_id = cliente_dict[cliente_sel]
        
        proximo_cot = ver_proximo_consecutivo("COT")
        st.info(f"📌 **Número de Cotización a Generar:** `{proximo_cot}`")
        
        st.markdown("---")
        st.markdown("### Detalle de Ítems (Repuestos / Servicios / Mano de Obra)")
        
        if "items_cot" not in st.session_state:
            st.session_state.items_cot = []

        with st.expander("➕ Agregar nuevo ítem a la lista", expanded=True):
            col_d, col_c, col_p = st.columns([3, 1, 1])
            desc_input = col_d.text_input("Descripción del ítem", placeholder="Ej. Kit de filtros o llantas para montacarga", key="input_desc_temp")
            cant_input = col_c.number_input("Cantidad", min_value=1.0, value=1.0, step=1.0, key="input_cant_temp")
            pu_input = col_p.number_input("Valor Unitario (COP)", min_value=0.0, value=0.0, step=10000.0, key="input_pu_temp")
            
            if st.button("Añadir a la cotización"):
                if desc_input.strip():
                    st.session_state.items_cot.append({
                        "desc": desc_input,
                        "cant": cant_input,
                        "pu": pu_input,
                        "sub": cant_input * pu_input
                    })
                    st.rerun()
                else:
                    st.error("Escribe una descripción válida para el ítem.")

        total_acumulado = 0.0
        items_para_pdf = []
        detalles_lista_db = []

        if st.session_state.items_cot:
            st.markdown("#### Ítems Agregados:")
            for i, item in enumerate(st.session_state.items_cot):
                c1, c2, c3, c4 = st.columns([3, 1, 1, 0.5])
                c1.write(f"• {item['desc']}")
                c2.write(f"Cant: {item['cant']}")
                c3.write(f"${item['sub']:,.2f}")
                if c4.button("❌", key=f"del_item_{i}", help="Eliminar este ítem"):
                    st.session_state.items_cot.pop(i)
                    st.rerun()
                
                total_acumulado += item['sub']
                detalles_lista_db.append(f"- {item['desc']} | Cant: {item['cant']} | V.Unit: ${item['pu']:,.2f} | Subtotal: ${item['sub']:,.2f}")
                items_para_pdf.append(item)
        else:
            st.info("No hay ítems agregados todavía. Usa el formulario de arriba para añadirlos.")

        st.markdown(f"### 💰 **VALOR TOTAL COTIZACIÓN: ${total_acumulado:,.2f} COP**")
        fecha_cot = st.text_input("Fecha de Emisión", recaudar_fecha_actual())

        if st.button("💾 Guardar y Generar PDF de Cotización", type="primary"):
            if total_acumulado > 0 and items_para_pdf:
                siguiente_cot = obtener_siguiente_consecutivo("COT")
                detalles_texto_final = "\n".join(detalles_lista_db)
                
                conexion = sqlite3.connect(ruta_db)
                cursor = conexion.cursor()
                cursor.execute("""
                    INSERT INTO cotizaciones (consecutivo, cliente_id, detalles, total, fecha)
                    VALUES (?, ?, ?, ?, ?)
                """, (siguiente_cot, c_id, detalles_texto_final, total_acumulado, fecha_cot))
                
                cursor.execute("SELECT * FROM clientes WHERE id = ?", (c_id,))
                c_data = cursor.fetchone()
                conexion.commit()
                conexion.close()
                
                ruta_pdf = generar_pdf_cotizacion(siguiente_cot, c_data, items_para_pdf, total_acumulado, fecha_cot)
                
                st.session_state.items_cot = []
                
                st.success(f"🎉 Cotización **{siguiente_cot}** generada correctamente por un total de ${total_acumulado:,.2f} COP.")
                with open(ruta_pdf, "rb") as pdf_file:
                    st.download_button(
                        label="📥 Descargar PDF de la Cotización",
                        data=pdf_file,
                        file_name=f"{siguiente_cot}.pdf",
                        mime="application/pdf"
                    )
            else:
                st.error("❌ Debes agregar al menos un ítem válido a la cotización.")

# -------------------------------------------------------------
# MÓDULO 3: CRONOGRAMA DE MANTENIMIENTOS
# -------------------------------------------------------------
elif menu == "📅 Cronograma":
    st.subheader("📅 Cronograma de Mantenimientos Preventivos - Montacargas")
    st.write("Planifica y visualiza las visitas técnicas preventivas, revisiones de horómetros o mantenimientos programados para los montacargas de tus clientes.")
    
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("""
        SELECT e.id, c.nombre_empresa, e.tipo_equipo, e.marca, e.serial 
        FROM equipos e JOIN clientes c ON e.cliente_id = c.id
    """)
    equipos_todos = cursor.fetchall()
    
    if not equipos_todos:
        st.warning("⚠️ No hay montacargas registrados para programar en el cronograma. Ve al módulo de Hojas de Vida.")
        conexion.close()
    else:
        equipo_cron_dict = {f"{eq[1]} - {eq[2]} {eq[3]} (Serial: {eq[4]})": eq[0] for eq in equipos_todos}
        
        with st.form("form_cronograma"):
            st.markdown("### ➕ Programar Nueva Visita Preventiva")
            col1, col2 = st.columns(2)
            eq_cron_sel = col1.selectbox("Seleccionar Montacarga", list(equipo_cron_dict.keys()))
            titulo_evento = col2.text_input("Título / Descripción del Evento", "Mantenimiento Preventivo 250 Horas")
            
            col3, col4 = st.columns(2)
            fecha_prog = col3.date_input("Fecha Programada", datetime.date.today())
            estado_cron = col4.selectbox("Estado del Evento", ["Programado", "Completado", "Pendiente"])
            
            btn_guardar_cron = st.form_submit_button("Guardar en el Cronograma")
            
            if btn_guardar_cron:
                eq_id_sel = equipo_cron_dict[eq_cron_sel]
                cursor.execute("""
                    INSERT INTO cronograma (equipo_id, titulo_evento, fecha_programada, estado)
                    VALUES (?, ?, ?, ?)
                """, (eq_id_sel, titulo_evento, str(fecha_prog), estado_cron))
                conexion.commit()
                st.success("✅ Evento agregado correctamente al cronograma del montacarga.")

        st.markdown("---")
        st.markdown("### 📋 Listado General de Cronograma y Visitas")
        
        cursor.execute("""
            SELECT c.nombre_empresa, eq.tipo_equipo, eq.marca, eq.serial, 
                   cr.titulo_evento, cr.fecha_programada, cr.estado, cr.id
            FROM cronograma cr 
            JOIN equipos eq ON cr.equipo_id = eq.id 
            JOIN clientes c ON eq.cliente_id = c.id
            ORDER BY cr.fecha_programada ASC
        """)
        cron_registros = cursor.fetchall()
        conexion.close()

        if cron_registros:
            for reg in cron_registros:
                empresa_reg, tipo_reg, marca_reg, serial_reg, titulo_reg, fecha_reg, estado_reg, id_evento = reg
                
                col_c1, col_c2, col_c3, col_c4 = st.columns([2, 2, 1, 1])
                col_c1.write(f"**Empresa:** {empresa_reg}\n\n*Equipo:* {marca_reg} ({tipo_reg} - {serial_reg})")
                col_c2.write(f"**Evento:** {titulo_reg}\n\n*Fecha:* {fecha_reg}")
                col_c3.markdown(f"**Estado:** `{estado_reg}`")
                
                if col_c4.button("🗑️ Eliminar", key=f"del_cron_{id_evento}"):
                    con_del = sqlite3.connect(ruta_db)
                    cur_del = con_del.cursor()
                    cur_del.execute("DELETE FROM cronograma WHERE id = ?", (id_evento,))
                    con_del.commit()
                    con_del.close()
                    st.success("Evento eliminado del cronograma.")
                    st.rerun()
                st.divider()
        else:
            st.info("No hay eventos registrados en el cronograma actualmente.")

# -------------------------------------------------------------
# MÓDULO 4: HOJAS DE VIDA (EQUIPOS)
# -------------------------------------------------------------
elif menu == "📖 Hojas de Vida":
    st.subheader("📖 Gestión de Hojas de Vida de Montacargas")
    
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("SELECT id, nombre_empresa FROM clientes")
    clientes = cursor.fetchall()
    
    if not clientes:
        st.warning("⚠️ Debes registrar un cliente primero antes de asociarle un montacarga.")
        conexion.close()
    else:
        cliente_dict = {c[1]: c[0] for c in clientes}
        
        tab_reg, tab_cons = st.tabs(["➕ Registrar Nuevo Montacarga", "🔍 Consultar y Generar Hoja de Vida"])
        
        with tab_reg:
            st.markdown("### Registro de Equipo para Hoja de Vida")
            with st.form("form_reg_equipo"):
                c_sel = st.selectbox("Cliente Propietario", list(cliente_dict.keys()), key="cli_eq_reg")
                cli_id_sel = cliente_dict[c_sel]
                
                col1, col2 = st.columns(2)
                tipo_eq = col1.selectbox("Tipo de Montacarga", ["Eléctrico Hombre A Bordo", "Eléctrico Apilador / Stacker", "Combustión Gas / Gasolina", "Combustión Diesel", "Estibador Manual / Hidráulico"])
                marca_eq = col2.text_input("Marca", placeholder="Ej. Toyota, Crown, Yale, Hyster, STILL")
                
                col3, col4 = st.columns(2)
                modelo_eq = col3.text_input("Modelo", placeholder="Ej. 3FG15 / 42-7FGU25")
                serial_eq = col4.text_input("Número de Serial", placeholder="Ej. 12345")
                
                col5, col6, col7 = st.columns(3)
                capacidad_eq = col5.number_input("Capacidad (kg)", min_value=500.0, value=2500.0, step=100.0)
                altura_eq = col6.number_input("Altura de Elevación (mm)", min_value=1000.0, value=3000.0, step=100.0)
                horometro_eq = col7.number_input("Horómetro Inicial", min_value=0.0, value=0.0, step=10.0)
                
                foto_eq_file = st.file_uploader("Foto del Montacarga (Opcional)", type=["png", "jpg", "jpeg"], key="foto_equipo_upload")
                
                btn_guardar_eq = st.form_submit_button("Guardar Montacarga en Base de Datos")
                
                if btn_guardar_eq:
                    ruta_foto_eq_guardada = None
                    if foto_eq_file is not None:
                        img_eq_obj = PILImage.open(foto_eq_file)
                        os.makedirs("uploads", exist_ok=True)
                        ruta_foto_eq_guardada = f"uploads/EQ_{serial_eq.replace('/', '_')}_{int(datetime.datetime.now().timestamp())}.jpg"
                        img_eq_obj.save(ruta_foto_eq_guardada)
                        
                    cursor.execute("""
                        INSERT INTO equipos (cliente_id, tipo_equipo, marca, modelo, serial, capacidad, altura, horometro, foto_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (cli_id_sel, tipo_eq, marca_eq, modelo_eq, serial_eq, capacidad_eq, altura_eq, horometro_eq, ruta_foto_eq_guardada))
                    conexion.commit()
                    st.success(f"🎉 Montacarga {marca_eq} serial {serial_eq} registrado con éxito.")
                    
            conexion.close()

        with tab_cons:
            conexion = sqlite3.connect(ruta_db)
            cursor = conexion.cursor()
            cursor.execute("""
                SELECT e.id, c.nombre_empresa, e.tipo_equipo, e.marca, e.modelo, e.serial, e.capacidad, e.altura, e.horometro, e.foto_path, c.id
                FROM equipos e JOIN clientes c ON e.cliente_id = c.id
            """)
            equipos_registrados = cursor.fetchall()
            conexion.close()
            
            if not equipos_registrados:
                st.info("No hay montacargas registrados en el sistema todavía.")
            else:
                eq_dict_hv = {f"[{eq[1]}] {eq[3]} {eq[4]} - Serial: {eq[5]}": eq for eq in equipos_registrados}
                eq_sel_key = st.selectbox("Seleccionar Montacarga para Hoja de Vida", list(eq_dict_hv.keys()))
                eq_selected_data = eq_dict_hv[eq_sel_key]
                
                e_id, empresa_cli, t_eq, marca_e, modelo_e, serial_e, cap_e, alt_e, hor_e, foto_e, c_id_owner = eq_selected_data
                
                st.markdown("---")
                col_info1, col_info2 = st.columns([2, 1])
                
                with col_info1:
                    st.markdown(f"### 📋 Hoja de Vida: {marca_e} {modelo_e}")
                    st.write(f"**Propietario:** {empresa_cli}")
                    st.write(f"**Tipo de Equipo:** {t_eq}")
                    st.write(f"**Serial:** `{serial_e}` | **Capacidad:** {cap_e} kg")
                    st.write(f"**Altura de Elevación:** {alt_e} mm | **Horómetro Actual:** {hor_e} hrs")
                
                with col_info2:
                    if foto_e and os.path.exists(foto_e):
                        st.image(foto_e, caption=f"Montacarga {marca_e}", width=220)
                    else:
                        st.info("Sin foto adjunta del equipo.")

                st.markdown("### 🛠️ Historial de Órdenes de Servicio Asociadas")
                conexion = sqlite3.connect(ruta_db)
                cursor = conexion.cursor()
                cursor.execute("""
                    SELECT consecutivo, tipo_servicio, fecha, observaciones, persona_recibe, horometro_actual, id 
                    FROM ordenes_servicio WHERE equipo_id = ? ORDER BY id DESC
                """, (e_id,))
                historial_os = cursor.fetchall()
                conexion.close()

                if historial_os:
                    for h in historial_os:
                        cons_h, tipo_h, fecha_h, obs_h, recibe_h, hor_h, id_os_db = h
                        with st.expander(f"Orden No. {cons_h} - Fecha: {fecha_h} ({tipo_h})"):
                            st.write(f"**Horómetro al servicio:** {hor_h} hrs")
                            st.write(f"**Trabajos / Observaciones:** {obs_h}")
                            st.write(f"**Recibe a satisfacción:** {recibe_h}")
                            
                            if st.button("🗑️ Eliminar este registro de servicio", key=f"del_os_{id_os_db}"):
                                con_del_os = sqlite3.connect(ruta_db)
                                cur_del_os = con_del_os.cursor()
                                cur_del_os.execute("DELETE FROM ordenes_servicio WHERE id = ?", (id_os_db,))
                                con_del_os.commit()
                                con_del_os.close()
                                st.success(f"Orden {cons_h} eliminada del historial.")
                                st.rerun()
                else:
                    st.info("Este montacarga no registra órdenes de servicio anteriores.")

                st.markdown("---")
                if st.button("📄 Generar y Descargar PDF de Hoja de Vida Completa", type="primary"):
                    conexion = sqlite3.connect(ruta_db)
                    cursor = conexion.cursor()
                    cursor.execute("SELECT * FROM clientes WHERE id = ?", (c_id_owner,))
                    c_data_hv = cursor.fetchone()
                    conexion.close()
                    
                    eq_tuple_for_pdf = (t_eq, marca_e, modelo_e, serial_e, cap_e, alt_e, hor_e, "", "", foto_e)
                    
                    ruta_pdf_hv = generar_pdf_hoja_de_vida(c_data_hv, eq_tuple_for_pdf, historial_os)
                    
                    st.success("🎉 Hoja de vida generada con éxito.")
                    with open(ruta_pdf_hv, "rb") as pdf_file:
                        st.download_button(
                            label="📥 Descargar PDF de Hoja de Vida",
                            data=pdf_file,
                            file_name=f"HV_{serial_e.replace('/', '_')}.pdf",
                            mime="application/pdf"
                        )

# -------------------------------------------------------------
# MÓDULO 5: CLIENTES
# -------------------------------------------------------------
elif menu == "👥 Clientes":
    st.subheader("👥 Gestión de Clientes y Propietarios de Flota")
    
    tab_reg_cli, tab_ver_cli = st.tabs(["➕ Registrar Nuevo Cliente", "📋 Listado de Clientes"])
    
    with tab_reg_cli:
        with st.form("form_cliente"):
            nombre_empresa = st.text_input("Nombre de la Empresa / Cliente", placeholder="Ej. Comercial Nutresa / S.A.S.")
            nit_cliente = st.text_input("NIT / Cédula", placeholder="Ej. 900.123.456-1")
            direccion_cliente = st.text_input("Dirección", placeholder="Ej. Zona Industrial Via Chimitá")
            contacto_cliente = st.text_input("Persona de Contacto / Teléfono", placeholder="Ej. Ing. Carlos Gomez - 3101234567")
            
            btn_guardar_cli = st.form_submit_button("Guardar Cliente")
            
            if btn_guardar_cli:
                if nombre_empresa.strip():
                    conexion = sqlite3.connect(ruta_db)
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO clientes (nombre_empresa, nit, direccion, contacto)
                        VALUES (?, ?, ?, ?)
                    """, (nombre_empresa, nit_cliente, direccion_cliente, contacto_cliente))
                    conexion.commit()
                    conexion.close()
                    st.success(f"🎉 Cliente **{nombre_empresa}** registrado correctamente.")
                else:
                    st.error("El nombre de la empresa es obligatorio.")
                    
    with tab_ver_cli:
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute("SELECT id, nombre_empresa, nit, direccion, contacto FROM clientes")
        clientes_db = cursor.fetchall()
        conexion.close()
        
        if clientes_db:
            for cli in clientes_db:
                id_c, empresa_c, nit_c, dir_c, cont_c = cli
                with st.expander(f"🏢 {empresa_c} (NIT: {nit_c})"):
                    st.write(f"**Dirección:** {dir_c}")
                    st.write(f"**Contacto / Teléfono:** {cont_c}")
                    
                    if st.button("🗑️ Eliminar Cliente", key=f"del_cli_{id_c}"):
                        conexion = sqlite3.connect(ruta_db)
                        cursor = conexion.cursor()
                        cursor.execute("DELETE FROM clientes WHERE id = ?", (id_c,))
                        conexion.commit()
                        conexion.close()
                        st.success("Cliente eliminado del sistema.")
                        st.rerun()
        else:
            st.info("No hay clientes registrados en el sistema.")

# -------------------------------------------------------------
# MÓDULO 6: TÉCNICOS
# -------------------------------------------------------------
elif menu == "🛠️ Técnicos":
    st.subheader("🛠️ Gestión de Personal Técnico MMB")
    
    tab_reg_tec, tab_ver_tec = st.tabs(["➕ Registrar Nuevo Técnico", "📋 Listado de Técnicos"])
    
    with tab_reg_tec:
        with st.form("form_tecnico"):
            nombre_tec = st.text_input("Nombre Completo del Técnico", placeholder="Ej. Nelson Rojas")
            cedula_tec = st.text_input("Número de Cédula", placeholder="Ej. 1098604964")
            
            btn_guardar_tec = st.form_submit_button("Guardar Técnico")
            
            if btn_guardar_tec:
                if nombre_tec.strip() and cedula_tec.strip():
                    try:
                        conexion = sqlite3.connect(ruta_db)
                        cursor = conexion.cursor()
                        cursor.execute("""
                            INSERT INTO tecnicos (nombre, cedula)
                            VALUES (?, ?)
                        """, (nombre_tec, cedula_tec))
                        conexion.commit()
                        conexion.close()
                        st.success(f"🎉 Técnico **{nombre_tec}** registrado correctamente.")
                    except sqlite3.IntegrityError:
                        st.error("❌ Ya existe un técnico registrado con este número de cédula.")
                else:
                    st.error("Por favor completa ambos campos.")
                    
    with tab_ver_tec:
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute("SELECT id, nombre, cedula FROM tecnicos")
        tecnicos_db = cursor.fetchall()
        conexion.close()
        
        if tecnicos_db:
            for tec in tecnicos_db:
                id_t, nombre_t, cedula_t = tec
                with st.expander(f"👨‍🔧 {nombre_t} - C.C. {cedula_t}"):
                    if st.button("🗑️ Eliminar Técnico", key=f"del_tec_{id_t}"):
                        conexion = sqlite3.connect(ruta_db)
                        cursor = conexion.cursor()
                        cursor.execute("DELETE FROM tecnicos WHERE id = ?", (id_t,))
                        conexion.commit()
                        conexion.close()
                        st.success("Técnico eliminado del sistema.")
                        st.rerun()
        else:
            st.info("No hay técnicos registrados en el sistema.")