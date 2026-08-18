import datetime
import os
import sqlite3
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as PDFFigure, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from streamlit_drawable_canvas import st_canvas
import streamlit as st

# Configuración inicial de la página
st.set_page_config(page_title="MMB Manager", layout="wide")

# Estilos generales y colores corporativos basados en tu logo
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { width: 290px !important; min-width: 290px !important; background-color: #f8fafc; padding-top: 10px; border-right: 2px solid #e2e8f0; }
    [data-testid="collapsedControl"] { display: none !important; }
    .main-header { background-color: #2d3748; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border-left: 6px solid #f39c12; }
    .stButton>button { width: 100% !important; border-radius: 6px; font-weight: bold; margin-bottom: 5px; background-color: #2d3748; color: white; }
    .stButton>button:hover { background-color: #f39c12; color: #000000; }
    </style>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------
# INICIALIZAR BASE DE DATOS Y TABLAS (CON MIGRACIONES SEGURAS)
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
  cursor.execute(
      "INSERT OR IGNORE INTO consecutivos (tipo, ultimo_numero) VALUES ('OS',"
      " 0)"
  )
  cursor.execute(
      "INSERT OR IGNORE INTO consecutivos (tipo, ultimo_numero) VALUES"
      " ('COT', 0)"
  )

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
            firma_path TEXT,
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
  if "firma_path" not in columnas_os:
    cursor.execute("ALTER TABLE ordenes_servicio ADD COLUMN firma_path TEXT")
  if "tecnico_id" not in columnas_os:
    cursor.execute(
        "ALTER TABLE ordenes_servicio ADD COLUMN tecnico_id INTEGER"
    )

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

  # Tabla de Usuarios para Autenticación
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            rol TEXT NOT NULL,
            cliente_id INTEGER,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    """)

  # Crear administrador por defecto si no existe
  cursor.execute("SELECT COUNT(*) FROM usuarios WHERE rol = 'admin'")
  if cursor.fetchone()[0] == 0:
    cursor.execute(
        """
            INSERT INTO usuarios (username, password, rol, cliente_id)
            VALUES (?, ?, ?, NULL)
        """,
        ("admin", "admin123", "admin"),
    )

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
  cursor.execute(
      "UPDATE consecutivos SET ultimo_numero = ? WHERE tipo = ?",
      (siguiente, tipo),
  )
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
        "10. Dispositivos de seguridad (Bocina/Luces/Alarma retroceso)",
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
        "10. Dispositivos de seguridad (Bocina/Luces/Mástil/Cadenas)",
    ]
  else:
    return [
        "1. Estructura y Uñas de carga",
        "2. Sistema Hidráulico (Fugas/Sellos)",
        "3. Estado de Ruedas y Rodamientos",
        "4. Sistema de Frenos de Mano",
        "5. Articulaciones y puntos de engrase",
    ]


# -------------------------------------------------------------
# CLASE CANVAS PARA MARCA DE AGUA Y ENCABEZADO CORPORATIVO
# -------------------------------------------------------------
class MarcaDeAguaCanvas(canvas.Canvas):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def showPage(self):
    self.draw_marca_de_agua()
    super().showPage()

  def save(self):
    super().save()

  def draw_marca_de_agua(self):
    self.saveState()
    if os.path.exists("logo.png"):
      try:
        self.setFillAlpha(0.08)
        pil_img = PILImage.open("logo.png")
        img_w, img_h = pil_img.size
        aspect = img_w / img_h

        w_wm = 350
        h_wm = w_wm / aspect
        x_wm = (612 - w_wm) / 2
        y_wm = (792 - h_wm) / 2

        self.drawImage(
            "logo.png",
            x_wm,
            y_wm,
            width=w_wm,
            height=h_wm,
            mask="auto",
        )
      except:
        pass
    self.restoreState()


def construir_encabezado_pdf():
  elementos_encabezado = []
  if os.path.exists("logo.png"):
    try:
      pil_img = PILImage.open("logo.png")
      img_w, img_h = pil_img.size

      max_w, max_h = 290, 130
      aspect = img_w / img_h
      if img_w > img_h:
        pdf_w = max_w
        pdf_h = max_w / aspect
      else:
        pdf_h = max_h
        pdf_w = max_h * aspect

      logo_pdf = PDFFigure("logo.png", width=pdf_w, height=pdf_h)
      logo_pdf.hAlign = "CENTER"
      elementos_encabezado.append(logo_pdf)
      elementos_encabezado.append(Spacer(1, 4))
    except:
      pass

  styles = getSampleStyleSheet()
  estilo_titulo = ParagraphStyle(
      "TituloCorp",
      parent=styles["Heading1"],
      fontSize=11,
      fontName="Helvetica-Bold",
      textColor=colors.HexColor("#2d3748"),
      alignment=1,
      spaceAfter=2,
  )
  estilo_eslogan = ParagraphStyle(
      "EsloganCorp",
      parent=styles["Normal"],
      fontSize=8,
      fontName="Helvetica-Oblique",
      textColor=colors.HexColor("#f39c12"),
      alignment=1,
      spaceAfter=3,
  )
  estilo_sub = ParagraphStyle(
      "SubCorp",
      parent=styles["Normal"],
      fontSize=7.5,
      textColor=colors.HexColor("#4a5568"),
      alignment=1,
      spaceAfter=8,
  )

  elementos_encabezado.append(
      Paragraph(
          "<b>MONTACARGAS Y MANTENIMIENTOS BUCARAMANGA MMB</b>", estilo_titulo
      )
  )
  elementos_encabezado.append(
      Paragraph(
          "“Soluciones integrales para el manejo de carga y potencia"
          " industrial”",
          estilo_eslogan,
      )
  )
  elementos_encabezado.append(
      Paragraph(
          "<b>Nelson Alberto Rojas Hernandez</b><br/>NIT: 1098604964-5 | Régimen"
          " Simplificado<br/>Cel: 3003043555 | Email:"
          " mantenimientos.bucaramanga@hotmail.com<br/>Bucaramanga, Santander",
          estilo_sub,
      )
  )
  return elementos_encabezado


def generar_pdf_orden(
    consecutivo,
    cliente_info,
    equipo_info,
    tipo_servicio,
    horometro,
    observaciones,
    recibe,
    tecnico_info,
    resultados_chk=None,
    fotos_paths=None,
    firma_path=None,
):
  ruta_pdf = f"reports/{consecutivo}.pdf"
  doc = SimpleDocTemplate(
      ruta_pdf,
      pagesize=letter,
      rightMargin=30,
      leftMargin=30,
      topMargin=30,
      bottomMargin=30,
  )
  elementos = []
  elementos.extend(construir_encabezado_pdf())

  styles = getSampleStyleSheet()
  estilo_texto = ParagraphStyle(
      "TextoCorp",
      parent=styles["Normal"],
      fontSize=9,
      textColor=colors.HexColor("#2d3748"),
  )
  estilo_negrita = ParagraphStyle(
      "NegritaCorp",
      parent=styles["Normal"],
      fontSize=9,
      fontName="Helvetica-Bold",
      textColor=colors.HexColor("#2d3748"),
  )

  tec_nombre, tec_cedula = (
      tecnico_info if tecnico_info else ("No asignado", "N/A")
  )

  data_encabezado = [
      [
          Paragraph(f"<b>Orden de Servicio:</b> {consecutivo}", estilo_texto),
          Paragraph(
              f"<b>Fecha:</b> {recaudar_fecha_actual()}", estilo_texto
          ),
      ],
      [
          Paragraph(
              f"<b>Técnico Encargado:</b> {tec_nombre}", estilo_texto
          ),
          Paragraph(f"<b>Cédula Técnico:</b> {tec_cedula}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Cliente:</b> {cliente_info[1]}", estilo_texto),
          Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Dirección:</b> {cliente_info[3]}", estilo_texto),
          Paragraph(f"<b>Contacto:</b> {cliente_info[4]}", estilo_texto),
      ],
  ]
  t_enc = Table(data_encabezado, colWidths=[270, 270])
  t_enc.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#f39c12")),
          ("PADDING", (0, 0), (-1, -1), 4),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
      ])
  )
  elementos.append(t_enc)
  elementos.append(Spacer(1, 6))

  elementos.append(
      Paragraph(
          "<b>INFORMACIÓN DEL MONTACARGAS INTERVENIDO</b>", estilo_negrita
      )
  )
  data_equipo = [
      [
          Paragraph(f"<b>Tipo:</b> {equipo_info[1]}", estilo_texto),
          Paragraph(f"<b>Marca:</b> {equipo_info[2]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Modelo:</b> {equipo_info[3]}", estilo_texto),
          Paragraph(f"<b>Serial:</b> {equipo_info[4]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Capacidad:</b> {equipo_info[5]} kg", estilo_texto),
          Paragraph(
              f"<b>Horómetro Actual:</b> {horometro} hrs", estilo_texto
          ),
      ],
  ]
  t_eq = Table(data_equipo, colWidths=[270, 270])
  t_eq.setStyle(
      TableStyle([
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("PADDING", (0, 0), (-1, -1), 3),
      ])
  )
  elementos.append(t_eq)
  elementos.append(Spacer(1, 6))

  elementos.append(
      Paragraph(f"<b>Tipo de Servicio:</b> {tipo_servicio}", estilo_negrita)
  )
  elementos.append(Spacer(1, 3))

  if resultados_chk:
    elementos.append(
        Paragraph(
            "<b>CHECKLIST DE INSPECCIÓN TÉCNICA (B: Bueno | R: Regular | M:"
            " Malo)</b>",
            estilo_negrita,
        )
    )
    elementos.append(Spacer(1, 2))
    data_chk_pdf = [[
        Paragraph("<b>Ítem de Inspección</b>", estilo_negrita),
        Paragraph("<b>Estado</b>", estilo_negrita),
    ]]
    for item_desc, estado_val in resultados_chk:
      data_chk_pdf.append([
          Paragraph(item_desc, estilo_texto),
          Paragraph(f"<b>{estado_val}</b>", estilo_texto),
      ])

    t_chk_pdf = Table(data_chk_pdf, colWidths=[440, 100])
    t_chk_pdf.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f39c12")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING", (0, 0), (-1, -1), 2.5),
            ("ALIGN", (1, 1), (1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    elementos.append(t_chk_pdf)
    elementos.append(Spacer(1, 6))

  elementos.append(
      Paragraph(
          f"<b>Trabajos Realizados / Observaciones"
          f" Generales:</b><br/>{observaciones}",
          estilo_texto,
      )
  )
  elementos.append(Spacer(1, 6))

  if fotos_paths:
    elementos.append(
        Paragraph("<b>Registro Fotográfico del Servicio:</b>", estilo_negrita)
    )
    elementos.append(Spacer(1, 3))
    filas_fotos = []
    fila_actual = []
    for f_path in fotos_paths:
      if os.path.exists(f_path):
        try:
          img_pdf = PDFFigure(f_path, width=160, height=115)
          fila_actual.append(img_pdf)
          if len(fila_actual) == 3:
            filas_fotos.append(fila_actual)
            fila_actual = []
        except:
          pass
    if fila_actual:
      while len(fila_actual) < 3:
        fila_actual.append("")
      filas_fotos.append(fila_actual)

    if filas_fotos:
      t_fotos = Table(filas_fotos, colWidths=[180, 180, 180])
      t_fotos.setStyle(
          TableStyle([
              ("ALIGN", (0, 0), (-1, -1), "CENTER"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("PADDING", (0, 0), (-1, -1), 3),
          ])
      )
      elementos.append(t_fotos)
      elementos.append(Spacer(1, 6))

  elementos.append(
      Paragraph(
          "<b>Observaciones de Entrega:</b> Equipo entregado a entera"
          " satisfacción del cliente.",
          estilo_texto,
      )
  )
  elementos.append(Spacer(1, 4))

  firma_flowable = ""
  if firma_path and os.path.exists(firma_path):
    try:
      firma_flowable = PDFFigure(firma_path, width=140, height=50)
    except:
      firma_flowable = "Firma digital no disponible"

  data_firma = [
      [
          Paragraph(f"<b>Recibe a Satisfacción:</b> {recibe}", estilo_texto),
          Paragraph("<b>Firma Autorizada Cliente:</b>", estilo_texto),
      ],
      [
          "",
          (
              firma_flowable
              if firma_path
              else Paragraph(
                  "__________________________________________", estilo_texto
              )
          ),
      ],
  ]
  t_firma = Table(data_firma, colWidths=[270, 270])
  t_firma.setStyle(
      TableStyle([
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("PADDING", (0, 0), (-1, -1), 5),
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("ALIGN", (1, 1), (1, 1), "CENTER"),
      ])
  )
  elementos.append(t_firma)

  doc.build(elementos, canvasmaker=MarcaDeAguaCanvas)
  return ruta_pdf


def generar_pdf_cotizacion(
    consecutivo,
    cliente_info,
    items_cotizacion,
    total_cot,
    fecha,
    metodo_pago,
    garantia,
):
  ruta_pdf = f"reports/{consecutivo}.pdf"
  doc = SimpleDocTemplate(
      ruta_pdf,
      pagesize=letter,
      rightMargin=30,
      leftMargin=30,
      topMargin=30,
      bottomMargin=30,
  )
  elementos = []
  elementos.extend(construir_encabezado_pdf())

  styles = getSampleStyleSheet()
  estilo_texto = ParagraphStyle(
      "TextoCorp",
      parent=styles["Normal"],
      fontSize=9,
      textColor=colors.HexColor("#2d3748"),
  )
  estilo_negrita = ParagraphStyle(
      "NegritaCorp",
      parent=styles["Normal"],
      fontSize=9,
      fontName="Helvetica-Bold",
      textColor=colors.HexColor("#2d3748"),
  )

  data_encabezado = [
      [
          Paragraph(f"<b>Cotización No.:</b> {consecutivo}", estilo_texto),
          Paragraph(f"<b>Fecha de Emisión:</b> {fecha}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Cliente:</b> {cliente_info[1]}", estilo_texto),
          Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Dirección:</b> {cliente_info[3]}", estilo_texto),
          Paragraph(f"<b>Contacto:</b> {cliente_info[4]}", estilo_texto),
      ],
  ]
  t_enc = Table(data_encabezado, colWidths=[270, 270])
  t_enc.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#f39c12")),
          ("PADDING", (0, 0), (-1, -1), 5),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
      ])
  )
  elementos.append(t_enc)
  elementos.append(Spacer(1, 12))

  elementos.append(
      Paragraph(
          "<b>DETALLE DE REPUESTOS, SERVICIOS Y MANO DE OBRA</b>",
          estilo_negrita,
      )
  )
  elementos.append(Spacer(1, 4))

  tabla_datos = [[
      Paragraph("<b>Descripción</b>", estilo_negrita),
      Paragraph("<b>Cant.</b>", estilo_negrita),
      Paragraph("<b>V. Unitario</b>", estilo_negrita),
      Paragraph("<b>Subtotal</b>", estilo_negrita),
  ]]

  for item in items_cotizacion:
    tabla_datos.append([
        Paragraph(item["desc"], estilo_texto),
        Paragraph(str(item["cant"]), estilo_texto),
        Paragraph(f"${item['pu']:,.2f}", estilo_texto),
        Paragraph(f"${item['sub']:,.2f}", estilo_texto),
    ])

  tabla_datos.append([
      Paragraph("<b>VALOR TOTAL COTIZACIÓN</b>", estilo_negrita),
      "",
      "",
      Paragraph(f"<b>${total_cot:,.2f} COP</b>", estilo_negrita),
  ])

  t_items = Table(tabla_datos, colWidths=[250, 60, 110, 120])
  t_items.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f39c12")),
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
          ("PADDING", (0, 0), (-1, -1), 5),
          ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
          ("SPAN", (0, -1), (2, -1)),
      ])
  )
  elementos.append(t_items)
  elementos.append(Spacer(1, 12))

  condiciones_texto = (
      "<b>Condiciones Comerciales:</b><br/>• Validez de la cotización:"
      f" 15 días.<br/>• Forma de pago: {metodo_pago}.<br/>• Garantía:"
      f" {garantia}."
  )
  elementos.append(Paragraph(condiciones_texto, estilo_texto))

  doc.build(elementos, canvasmaker=MarcaDeAguaCanvas)
  return ruta_pdf


def generar_pdf_hoja_de_vida(cliente_info, eq_data, historial_os):
  serial_limpio = eq_data[3].replace("/", "_").replace(" ", "_")
  ruta_pdf = f"reports/HV_{serial_limpio}.pdf"
  doc = SimpleDocTemplate(
      ruta_pdf,
      pagesize=letter,
      rightMargin=30,
      leftMargin=30,
      topMargin=30,
      bottomMargin=30,
  )
  elementos = []
  elementos.extend(construir_encabezado_pdf())

  styles = getSampleStyleSheet()
  estilo_texto = ParagraphStyle(
      "TextoCorp",
      parent=styles["Normal"],
      fontSize=9,
      textColor=colors.HexColor("#2d3748"),
  )
  estilo_negrita = ParagraphStyle(
      "NegritaCorp",
      parent=styles["Normal"],
      fontSize=9,
      fontName="Helvetica-Bold",
      textColor=colors.HexColor("#2d3748"),
  )
  estilo_titulo_hv = ParagraphStyle(
      "TitHV",
      parent=styles["Heading2"],
      fontSize=10.5,
      fontName="Helvetica-Bold",
      textColor=colors.HexColor("#2d3748"),
      spaceAfter=4,
  )

  data_encabezado = [
      [
          Paragraph(f"<b>HOJA DE VIDA DE EQUIPO</b>", estilo_negrita),
          Paragraph(
              f"<b>Fecha Impresión:</b> {recaudar_fecha_actual()}", estilo_texto
          ),
      ],
      [
          Paragraph(
              f"<b>Cliente Propietario:</b> {cliente_info[1]}", estilo_texto
          ),
          Paragraph(f"<b>NIT:</b> {cliente_info[2]}", estilo_texto),
      ],
  ]
  t_enc = Table(data_encabezado, colWidths=[270, 270])
  t_enc.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
          ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
          ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#f39c12")),
          ("PADDING", (0, 0), (-1, -1), 4),
      ])
  )
  elementos.append(t_enc)
  elementos.append(Spacer(1, 8))

  foto_equipo_path = eq_data[9] if len(eq_data) > 9 else None

  data_specs = [
      [
          Paragraph(f"<b>Tipo de Equipo:</b> {eq_data[0]}", estilo_texto),
          Paragraph(f"<b>Marca:</b> {eq_data[1]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Modelo:</b> {eq_data[2]}", estilo_texto),
          Paragraph(f"<b>Serial:</b> {eq_data[3]}", estilo_texto),
      ],
      [
          Paragraph(f"<b>Capacidad:</b> {eq_data[4]} kg", estilo_texto),
          Paragraph(
              f"<b>Altura de Elevación:</b> {eq_data[5]} mm", estilo_texto
          ),
      ],
      [
          Paragraph(
              f"<b>Horómetro Actual:</b> {eq_data[6]} hrs", estilo_texto
          ),
          "",
      ],
  ]
  t_specs = Table(data_specs, colWidths=[210, 210])
  t_specs.setStyle(
      TableStyle([
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("PADDING", (0, 0), (-1, -1), 3),
      ])
  )

  if foto_equipo_path and os.path.exists(foto_equipo_path):
    try:
      img_eq = PDFFigure(foto_equipo_path, width=110, height=85)
      img_eq.hAlign = "CENTER"
      t_foto_marco = Table([[img_eq]], colWidths=[120])
      t_foto_marco.setStyle(
          TableStyle([
              ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
              ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
              ("ALIGN", (0, 0), (-1, -1), "CENTER"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("PADDING", (0, 0), (-1, -1), 4),
          ])
      )

      tabla_contenedor_principal = Table(
          [[t_specs, t_foto_marco]], colWidths=[420, 120]
      )
      tabla_contenedor_principal.setStyle(
          TableStyle([
              ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("PADDING", (0, 0), (-1, -1), 4),
              ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
          ])
      )
      elementos.append(tabla_contenedor_principal)
    except:
      elementos.append(t_specs)
  else:
    t_specs_full = Table(data_specs, colWidths=[270, 270])
    t_specs_full.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    elementos.append(t_specs_full)

  elementos.append(Spacer(1, 10))
  elementos.append(
      Paragraph(
          "<b>HISTORIAL Y RESUMEN DE SERVICIOS TÉCNICOS</b>", estilo_titulo_hv
      )
  )

  if historial_os:
    tabla_historial = [[
        Paragraph("<b>Consecutivo</b>", estilo_negrita),
        Paragraph("<b>Tipo</b>", estilo_negrita),
        Paragraph("<b>Fecha</b>", estilo_negrita),
        Paragraph("<b>Horómetro</b>", estilo_negrita),
        Paragraph("<b>Trabajo Realizado</b>", estilo_negrita),
    ]]
    for h in historial_os:
      cons_h = h[0]
      tipo_h = h[1]
      fecha_h = str(h[2])
      obs_h = h[3]
      hor_h = f"{h[5]} hrs" if len(h) > 5 and h[5] is not None else "N/A"

      tabla_historial.append([
          Paragraph(f"<b>{cons_h}</b>", estilo_texto),
          Paragraph(tipo_h, estilo_texto),
          Paragraph(fecha_h, estilo_texto),
          Paragraph(hor_h, estilo_texto),
          Paragraph(obs_h, estilo_texto),
      ])
    t_hist = Table(tabla_historial, colWidths=[65, 60, 60, 65, 290])
    t_hist.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f39c12")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    elementos.append(t_hist)
  else:
    elementos.append(
        Paragraph(
            "No se encuentran órdenes de servicio registradas para este equipo"
            " en su historial.",
            estilo_texto,
        )
    )

  doc.build(elementos, canvasmaker=MarcaDeAguaCanvas)
  return ruta_pdf


# -------------------------------------------------------------
# CONTROL DE SESIÓN Y AUTENTICACIÓN
# -------------------------------------------------------------
if "autenticado" not in st.session_state:
  st.session_state.autenticado = False
  st.session_state.rol = None
  st.session_state.username = None
  st.session_state.cliente_id_usuario = None

if not st.session_state.autenticado:
  st.markdown(
      '<div class="main-header"><h1>MMB Manager - Iniciar Sesión</h1></div>',
      unsafe_allow_html=True,
  )

  col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
  with col_l2:
    if os.path.exists("logo.png"):
      st.image("logo.png", use_container_width=True)

    with st.form("form_login"):
      usuario_input = st.text_input("Usuario")
      password_input = st.text_input("Contraseña", type="password")
      btn_login = st.form_submit_button("Ingresar al Sistema")

      if btn_login:
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id, username, password, rol, cliente_id FROM usuarios WHERE"
            " username = ?",
            (usuario_input,),
        )
        user_db = cursor.fetchone()
        conexion.close()

        if user_db and user_db[2] == password_input:
          st.session_state.autenticado = True
          st.session_state.username = user_db[1]
          st.session_state.rol = user_db[3]
          st.session_state.cliente_id_usuario = user_db[4]
          st.success("¡Bienvenido! Ingresando...")
          st.rerun()
        else:
          st.error("Usuario o contraseña incorrectos.")
  st.stop()

# -------------------------------------------------------------
# CONTROL DE ESTADO DE NAVEGACIÓN (INICIO POR DEFECTO)
# -------------------------------------------------------------
if "menu_activo" not in st.session_state:
  st.session_state.menu_activo = "🏠 Inicio"

# -------------------------------------------------------------
# MENÚ LATERAL DE NAVEGACIÓN SEGÚN ROL
# -------------------------------------------------------------
with st.sidebar:
  if os.path.exists("logo.png"):
    st.image("logo.png", use_container_width=True)
  else:
    st.markdown("### **MMB Manager**")

  st.caption(
      f"Sesión: **{st.session_state.username}**"
      f" ({st.session_state.rol.upper()})"
  )
  st.divider()

  if st.button("🏠 Inicio"):
    st.session_state.menu_activo = "🏠 Inicio"
    st.rerun()

  if st.session_state.rol == "admin":
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
    if st.button("👥 Usuarios"):
      st.session_state.menu_activo = "👥 Usuarios"
      st.rerun()
  else:
    # Menú limitado para clientes
    if st.button("📖 Mis Hojas de Vida"):
      st.session_state.menu_activo = "📖 Hojas de Vida"
      st.rerun()

  # Opción general de cambio de contraseña para cualquier usuario activo
  if st.button("🔑 Cambiar Contraseña"):
    st.session_state.menu_activo = "🔑 Cambiar Contraseña"
    st.rerun()

  st.divider()
  if st.button("🚪 Cerrar Sesión"):
    st.session_state.autenticado = False
    st.session_state.rol = None
    st.session_state.username = None
    st.session_state.cliente_id_usuario = None
    st.session_state.menu_activo = "🏠 Inicio"
    st.rerun()

menu = st.session_state.menu_activo

# -------------------------------------------------------------
# MÓDULO 0: INICIO / BIENVENIDA
# -------------------------------------------------------------
if menu == "🏠 Inicio":
  st.markdown(
      '<div class="main-header"><h1>Montacargas y Mantenimientos'
      " Bucaramanga (MMB)</h1></div>",
      unsafe_allow_html=True,
  )

  col_logo_ini, col_txt_ini = st.columns([1, 2])

  with col_logo_ini:
    if os.path.exists("logo.png"):
      st.image("logo.png", use_container_width=True)
    else:
      st.info(
          "💡 Coloca tu archivo 'logo.png' en la carpeta del proyecto para"
          " visualizarlo aquí."
      )

  with col_txt_ini:
    st.markdown("### ¡Bienvenido a MMB Manager!")
    st.write(
        "Sistema integral para la gestión de mantenimiento preventivo y"
        " correctivo, control de flotas de montacargas, órdenes de servicio y"
        " cotizaciones."
    )
    st.markdown("---")
    st.markdown("**Propietario:** Nelson Alberto Rojas Hernandez")
    st.markdown("**NIT:** 1098604964-5 | Régimen Simplificado")
    st.markdown("**Ubicación:** Bucaramanga, Santander")

  if st.session_state.rol == "admin":
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
# MÓDULO 1: ÓRDENES DE SERVICIO (Solo Admin)
# -------------------------------------------------------------
elif menu == "📋 Órdenes de Servicio" and st.session_state.rol == "admin":
  st.markdown(
      '<div class="main-header"><h1>Montacargas y Mantenimientos'
      " Bucaramanga (MMB)</h1></div>",
      unsafe_allow_html=True,
  )
  st.subheader("📋 Generador de Órdenes de Servicio")

  conexion = sqlite3.connect(ruta_db)
  cursor = conexion.cursor()
  cursor.execute("SELECT id, nombre_empresa FROM clientes")
  clientes = cursor.fetchall()

  cursor.execute("SELECT id, nombre, cedula FROM tecnicos")
  tecnicos_db = cursor.fetchall()
  conexion.close()

  if not clientes:
    st.warning(
        "⚠️ No hay clientes registrados. Ve primero al módulo de Clientes."
    )
  elif not tecnicos_db:
    st.warning(
        "⚠️ No hay técnicos registrados. Ve primero al módulo de 🛠️ Técnicos"
        " para registrar al menos uno."
    )
  else:
    tecnico_dict = {f"{t[1]} (C.C. {t[2]})": t[0] for t in tecnicos_db}
    tec_sel = st.selectbox(
        "Seleccionar Técnico Responsable", list(tecnico_dict.keys())
    )
    tecnico_id_sel = tecnico_dict[tec_sel]

    cliente_dict = {c[1]: c[0] for c in clientes}
    cliente_sel = st.selectbox("Seleccionar Cliente", list(cliente_dict.keys()))
    c_id = cliente_dict[cliente_sel]

    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute(
        "SELECT id, tipo_equipo, marca, modelo, serial, horometro FROM equipos"
        " WHERE cliente_id = ?",
        (c_id,),
    )
    equipos = cursor.fetchall()
    conexion.close()

    if not equipos:
      st.warning(
          f"⚠️ El cliente '{cliente_sel}' no tiene montacargas asignados. Ve al"
          " módulo de Hojas de Vida para registrarle uno."
      )
    else:
      equipo_dict = {
          f"[{e[1]}] {e[2]} {e[3]} (Serial: {e[4]})": e for e in equipos
      }
      eq_label = st.selectbox(
          "Seleccionar Montacarga", list(equipo_dict.keys())
      )
      eq_info = equipo_dict[eq_label]
      eq_id, tipo_eq, marca_eq, modelo_eq, serial_eq, hor_eq = eq_info

      proximo_os = ver_proximo_consecutivo("OS")
      st.info(
          f"📌 **Próximo Consecutivo de Orden:** `{proximo_os}` |"
          f" **Montacarga:** {marca_eq} {modelo_eq} ({tipo_eq})"
      )

      col1, col2 = st.columns(2)
      with col1:
        tipo_servicio = st.selectbox(
            "Tipo de Servicio", ["Preventivo", "Correctivo"]
        )
      with col2:
        nuevo_horometro = st.number_input(
            "Horómetro Actual", value=float(hor_eq), step=0.5
        )

      nombre_recibe = st.text_input(
          "Persona que Recibe a Satisfacción (Cliente)", "Carlos Julio Gómez"
      )
      observaciones = st.text_area(
          "Observaciones Generales / Trabajos Realizados",
          "Se realiza servicio técnico especializado en montacarga.",
      )

      resultados_checklist = []
      if tipo_servicio == "Preventivo":
        st.markdown(
            f"### 📋 CHECKLIST TÉCNICO DE INSPECCIÓN ({tipo_eq.upper()})"
        )
        st.caption(
            "Marque el estado de cada componente: **B** (Bueno), **R**"
            " (Regular), **M** (Malo)"
        )

        lista_items = obtener_items_checklist(tipo_eq)
        for idx, item_texto in enumerate(lista_items):
          col_chk1, col_chk2 = st.columns([3, 1])
          col_chk1.write(item_texto)
          estado_elegido = col_chk2.radio(
              "Estado",
              ["B", "R", "M"],
              key=f"chk_item_{idx}",
              horizontal=True,
              label_visibility="collapsed",
          )
          resultados_checklist.append((item_texto, estado_elegido))
      else:
        st.info(
            "ℹ️ Servicio **Correctivo**: No aplica checklist preventivo"
            " estándar."
        )

      st.markdown("### 📷 Registro Fotográfico Múltiple del Servicio")
      fotos_os_files = st.file_uploader(
          "Adjuntar fotos del servicio o equipo intervenido (Puedes"
          " seleccionar varias)",
          type=["png", "jpg", "jpeg"],
          accept_multiple_files=True,
          key="fotos_os_upload",
      )

      rutas_fotos_guardadas = []
      if fotos_os_files:
        os.makedirs("uploads", exist_ok=True)
        for i, f_file in enumerate(fotos_os_files):
          img_os = PILImage.open(f_file)
          f_path = (
              f"uploads/OS_{proximo_os}_{i}_{int(datetime.datetime.now().timestamp())}.jpg"
          )
          img_os.save(f_path)
          rutas_fotos_guardadas.append(f_path)
        st.success(
            f"✅ {len(rutas_fotos_guardadas)} imágenes cargadas correctamente."
        )

      st.markdown(
          "### ✍️ Firma Digital del Cliente (Recibe a Satisfacción)"
      )
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

      if st.button(
          "🚀 Guardar y Generar PDF de Orden de Servicio", type="primary"
      ):
        siguiente_os = obtener_siguiente_consecutivo("OS")

        ruta_firma_guardada = None
        if canvas_result.image_data is not None:
          import numpy as np

          if np.any(canvas_result.image_data[:, :, 3] > 0):
            img_firma = PILImage.fromarray(
                canvas_result.image_data.astype("uint8"), mode="RGBA"
            )
            background = PILImage.new(
                "RGB", img_firma.size, (255, 255, 255)
            )
            background.paste(img_firma, mask=img_firma.split()[3])
            os.makedirs("uploads", exist_ok=True)
            ruta_firma_guardada = (
                f"uploads/FIRMA_{siguiente_os}_{int(datetime.datetime.now().timestamp())}.jpg"
            )
            background.save(ruta_firma_guardada)

        fotos_str_db = (
            ";".join(rutas_fotos_guardadas) if rutas_fotos_guardadas else ""
        )

        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute(
            """
                    INSERT INTO ordenes_servicio (consecutivo, cliente_id, equipo_id, tecnico_id, tipo_servicio, horometro_actual, observaciones, persona_recibe, foto_path, firma_path, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
            (
                siguiente_os,
                c_id,
                eq_id,
                tecnico_id_sel,
                tipo_servicio,
                nuevo_horometro,
                observaciones,
                nombre_recibe,
                fotos_str_db,
                ruta_firma_guardada,
            ),
        )

        cursor.execute(
            "UPDATE equipos SET horometro = ? WHERE id = ?",
            (nuevo_horometro, eq_id),
        )
        conexion.commit()

        cursor.execute("SELECT * FROM clientes WHERE id = ?", (c_id,))
        c_data = cursor.fetchone()
        cursor.execute("SELECT * FROM equipos WHERE id = ?", (eq_id,))
        e_data = cursor.fetchone()
        cursor.execute(
            "SELECT nombre, cedula FROM tecnicos WHERE id = ?",
            (tecnico_id_sel,),
        )
        t_data = cursor.fetchone()
        conexion.close()

        ruta_pdf = generar_pdf_orden(
            siguiente_os,
            c_data,
            e_data,
            tipo_servicio,
            nuevo_horometro,
            observaciones,
            nombre_recibe,
            t_data,
            resultados_checklist,
            rutas_fotos_guardadas,
            ruta_firma_guardada,
        )

        st.success(
            f"🎉 Orden de Servicio **{siguiente_os}** generada con éxito."
        )
        with open(ruta_pdf, "rb") as pdf_file:
          st.download_button(
              label="📥 Descargar PDF de la Orden de Servicio",
              data=pdf_file,
              file_name=f"{siguiente_os}.pdf",
              mime="application/pdf",
          )

# -------------------------------------------------------------
# MÓDULO 2: COTIZACIONES (Solo Admin)
# -------------------------------------------------------------
elif menu == "📑 Cotizaciones" and st.session_state.rol == "admin":
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
    cliente_sel = st.selectbox(
        "Seleccionar Cliente para Cotización", list(cliente_dict.keys())
    )
    c_id = cliente_dict[cliente_sel]

    proximo_cot = ver_proximo_consecutivo("COT")
    st.info(f"📌 **Número de Cotización a Generar:** `{proximo_cot}`")

    st.markdown("---")
    st.markdown(
        "### Detalle de Ítems (Repuestos / Servicios / Mano de Obra)"
    )

    if "items_cot" not in st.session_state:
      st.session_state.items_cot = []

    with st.expander("➕ Agregar nuevo ítem a la lista", expanded=True):
      col_d, col_c, col_p = st.columns([3, 1, 1])
      desc_input = col_d.text_input(
          "Descripción del ítem",
          placeholder="Ej. Kit de filtros o llantas para montacarga",
          key="input_desc_temp",
      )
      cant_input = col_c.number_input(
          "Cantidad",
          min_value=1.0,
          value=1.0,
          step=1.0,
          key="input_cant_temp",
      )
      pu_input = col_p.number_input(
          "Valor Unitario (COP)",
          min_value=0.0,
          value=0.0,
          step=10000.0,
          key="input_pu_temp",
      )

      if st.button("Añadir a la cotización"):
        if desc_input.strip():
          st.session_state.items_cot.append({
              "desc": desc_input,
              "cant": cant_input,
              "pu": pu_input,
              "sub": cant_input * pu_input,
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

        total_acumulado += item["sub"]
        detalles_lista_db.append(
            f"- {item['desc']} | Cant: {item['cant']} | V.Unit:"
            f" ${item['pu']:,.2f} | Subtotal: ${item['sub']:,.2f}"
        )
        items_para_pdf.append(item)
    else:
      st.info(
          "No hay ítems agregados todavía. Usa el formulario de arriba para"
          " añadirlos."
      )

    st.markdown(
        f"### 💰 **VALOR TOTAL COTIZACIÓN: ${total_acumulado:,.2f} COP**"
    )

    st.markdown("---")
    st.markdown("### ⚙️ Condiciones Comerciales Personalizables")
    col_pc1, col_pc2 = st.columns(2)
    metodo_pago_custom = col_pc1.text_input(
        "Método / Forma de Pago",
        "Contado / 50% Anticipo y 50% Saldo al entregar",
    )
    garantia_custom = col_pc2.text_input(
        "Garantía del Repuesto / Servicio", "3 meses por defectos de fábrica"
    )
    fecha_cot = st.text_input("Fecha de Emisión", recaudar_fecha_actual())

    if st.button("💾 Guardar y Generar PDF de Cotización", type="primary"):
      if total_acumulado > 0 and items_para_pdf:
        siguiente_cot = obtener_siguiente_consecutivo("COT")
        detalles_texto_final = "\n".join(detalles_lista_db)

        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute(
            """
                    INSERT INTO cotizaciones (consecutivo, cliente_id, detalles, total, fecha)
                    VALUES (?, ?, ?, ?, ?)
                """,
            (
                siguiente_cot,
                c_id,
                detalles_texto_final,
                total_acumulado,
                fecha_cot,
            ),
        )

        cursor.execute("SELECT * FROM clientes WHERE id = ?", (c_id,))
        c_data = cursor.fetchone()
        conexion.commit()
        conexion.close()

        ruta_pdf = generar_pdf_cotizacion(
            siguiente_cot,
            c_data,
            items_para_pdf,
            total_acumulado,
            fecha_cot,
            metodo_pago_custom,
            garantia_custom,
        )

        st.session_state.items_cot = []

        st.success(
            f"🎉 Cotización **{siguiente_cot}** generada correctamente por un"
            f" total de ${total_acumulado:,.2f} COP."
        )
        with open(ruta_pdf, "rb") as pdf_file:
          st.download_button(
              label="📥 Descargar PDF de la Cotización",
              data=pdf_file,
              file_name=f"{siguiente_cot}.pdf",
              mime="application/pdf",
          )
      else:
        st.error("❌ Debes agregar al menos un ítem válido a la cotización.")

# -------------------------------------------------------------
# MÓDULO 3: CRONOGRAMA DE MANTENIMIENTOS (Solo Admin)
# -------------------------------------------------------------
elif menu == "📅 Cronograma" and st.session_state.rol == "admin":
  st.subheader(
      "📅 Cronograma de Mantenimientos Preventivos - Montacargas"
  )
  st.write(
      "Planifica y visualiza las visitas técnicas preventivas, revisiones de"
      " horómetros o mantenimientos programados para los montacargas de tus"
      " clientes."
  )

  conexion = sqlite3.connect(ruta_db)
  cursor = conexion.cursor()
  cursor.execute("""
        SELECT e.id, c.nombre_empresa, e.tipo_equipo, e.marca, e.serial 
        FROM equipos e JOIN clientes c ON e.cliente_id = c.id
    """)
  equipos_todos = cursor.fetchall()

  if not equipos_todos:
    st.warning(
        "⚠️ No hay montacargas registrados para programar en el cronograma. Ve"
        " al módulo de Hojas de Vida."
    )
    conexion.close()
  else:
    equipo_cron_dict = {
        f"{eq[1]} - {eq[2]} {eq[3]} (Serial: {eq[4]})": eq[0]
        for eq in equipos_todos
    }

    with st.form("form_cronograma"):
      st.markdown("### ➕ Programar Nueva Visita Preventiva")
      col1, col2 = st.columns(2)
      eq_cron_sel = col1.selectbox(
          "Seleccionar Montacarga", list(equipo_cron_dict.keys())
      )
      titulo_evento = col2.text_input(
          "Título / Descripción del Evento",
          "Mantenimiento Preventivo 250 Horas",
      )

      col3, col4 = st.columns(2)
      fecha_prog = col3.date_input("Fecha Programada", datetime.date.today())
      estado_cron = col4.selectbox(
          "Estado del Evento", ["Programado", "Completado", "Pendiente"]
      )

      btn_guardar_cron = st.form_submit_button("Guardar en el Cronograma")

      if btn_guardar_cron:
        eq_id_sel = equipo_cron_dict[eq_cron_sel]
        cursor.execute(
            """
                    INSERT INTO cronograma (equipo_id, titulo_evento, fecha_programada, estado)
                    VALUES (?, ?, ?, ?)
                """,
            (eq_id_sel, titulo_evento, str(fecha_prog), estado_cron),
        )
        conexion.commit()
        st.success(
            "✅ Evento agregado correctamente al cronograma del montacarga."
        )

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
        (
            empresa_reg,
            tipo_reg,
            marca_reg,
            serial_reg,
            titulo_reg,
            fecha_reg,
            estado_reg,
            id_evento,
        ) = reg

        col_c1, col_c2, col_c3, col_c4 = st.columns([2, 2, 1, 1])
        col_c1.write(
            f"**Empresa:** {empresa_reg}\n\n*Equipo:* {marca_reg} ({tipo_reg} -"
            f" {serial_reg})"
        )
        col_c2.write(
            f"**Evento:** {titulo_reg}\n\n*Fecha:* {fecha_reg}"
        )
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
# MÓDULO 4: HOJAS DE VIDA (EQUIPOS) - Adaptado para Admin y Clientes
# -------------------------------------------------------------
elif menu == "📖 Hojas de Vida":
  st.subheader("📖 Gestión de Hojas de Vida de Montacargas")

  conexion = sqlite3.connect(ruta_db)
  cursor = conexion.cursor()

  if st.session_state.rol == "admin":
    cursor.execute("SELECT id, nombre_empresa FROM clientes")
    clientes = cursor.fetchall()
  else:
    # Si es cliente, solo ve su propia empresa
    cursor.execute(
        "SELECT id, nombre_empresa FROM clientes WHERE id = ?",
        (st.session_state.cliente_id_usuario,),
    )
    clientes = cursor.fetchall()
  conexion.close()

  if not clientes:
    st.warning("⚠️ No hay clientes asociados a tu cuenta.")
  else:
    cliente_dict = {c[1]: c[0] for c in clientes}

    if st.session_state.rol == "admin":
      tab_reg, tab_cons = st.tabs(
          ["➕ Registrar Nuevo Montacarga", "🔍 Consultar y Generar Hoja de Vida"]
      )

      with tab_reg:
        st.markdown("### Registro de Equipo para Hoja de Vida")
        with st.form("form_reg_equipo"):
          c_sel = st.selectbox(
              "Cliente Propietario",
              list(cliente_dict.keys()),
              key="cli_eq_reg",
          )
          cli_id_sel = cliente_dict[c_sel]

          col1, col2 = st.columns(2)
          tipo_eq = col1.selectbox(
              "Tipo de Montacarga",
              [
                  "Eléctrico Hombre A Bordo",
                  "Eléctrico Apilador / Stacker",
                  "Combustión Gas / Gasolina",
                  "Combustión Diesel",
                  "Estibador Manual / Hidráulico",
              ],
          )
          marca_eq = col2.text_input(
              "Marca", placeholder="Ej. Toyota, Crown, Yale, Hyster, STILL"
          )

          col3, col4 = st.columns(2)
          modelo_eq = col3.text_input(
              "Modelo", placeholder="Ej. 3FG15 / 42-7FGU25"
          )
          serial_eq = col4.text_input("Número de Serial", placeholder="Ej. 12345")

          col5, col6, col7 = st.columns(3)
          capacidad_eq = col5.number_input(
              "Capacidad (kg)", min_value=500.0, value=2500.0, step=100.0
          )
          altura_eq = col6.number_input(
              "Altura de Elevación (mm)",
              min_value=1000.0,
              value=3000.0,
              step=100.0,
          )
          horometro_eq = col7.number_input(
              "Horómetro Inicial", min_value=0.0, value=0.0, step=10.0
          )

          foto_eq_file = st.file_uploader(
              "Foto del Montacarga (Espacio exclusivo en Hoja de Vida)",
              type=["png", "jpg", "jpeg"],
              key="foto_equipo_upload",
          )

          btn_guardar_eq = st.form_submit_button(
              "Guardar Montacarga en Base de Datos"
          )

          if btn_guardar_eq:
            ruta_foto_eq_guardada = None
            if foto_eq_file is not None:
              img_eq_obj = PILImage.open(foto_eq_file)
              os.makedirs("uploads", exist_ok=True)
              ruta_foto_eq_guardada = (
                  f"uploads/EQ_{serial_eq.replace('/', '_')}_{int(datetime.datetime.now().timestamp())}.jpg"
              )
              img_eq_obj.save(ruta_foto_eq_guardada)

            conexion_reg = sqlite3.connect(ruta_db)
            cursor_reg = conexion_reg.cursor()
            cursor_reg.execute(
                """
                            INSERT INTO equipos (cliente_id, tipo_equipo, marca, modelo, serial, capacidad, altura, horometro, foto_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                (
                    cli_id_sel,
                    tipo_eq,
                    marca_eq,
                    modelo_eq,
                    serial_eq,
                    capacidad_eq,
                    altura_eq,
                    horometro_eq,
                    ruta_foto_eq_guardada,
                ),
            )
            conexion_reg.commit()
            conexion_reg.close()
            st.success(
                f"🎉 Montacarga {marca_eq} serial {serial_eq} registrado con"
                " éxito."
            )

      with tab_cons:
        st.markdown(
            "### 🔍 Filtrar por Cliente y Seleccionar Montacarga"
        )

        cliente_busqueda_dict = {c[1]: c[0] for c in clientes}
        cliente_hv_sel = st.selectbox(
            "1. Seleccionar Cliente",
            list(cliente_busqueda_dict.keys()),
            key="filtro_cli_hv",
        )
        cli_id_busqueda = cliente_busqueda_dict[cliente_hv_sel]

        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute(
            """
                    SELECT id, tipo_equipo, marca, modelo, serial, capacidad, altura, horometro, foto_path 
                    FROM equipos WHERE cliente_id = ?
                """,
            (cli_id_busqueda,),
        )
        equipos_cliente_sel = cursor.fetchall()
        conexion.close()

        if not equipos_cliente_sel:
          st.info(
              f"ℹ️ El cliente '{cliente_hv_sel}' no tiene montacargas"
              " registrados todavía."
          )
        else:
          eq_dict_hv = {
              f"[{eq[1]}] {eq[2]} {eq[3]} - Serial: {eq[4]}": eq
              for eq in equipos_cliente_sel
          }
          eq_sel_key = st.selectbox(
              "2. Seleccionar Montacarga Asignado",
              list(eq_dict_hv.keys()),
              key="filtro_eq_hv",
          )
          eq_selected_data = eq_dict_hv[eq_sel_key]

          e_id, t_eq, marca_e, modelo_e, serial_e, cap_e, alt_e, hor_e, foto_e = (
              eq_selected_data
          )

          st.markdown("---")
          col_info1, col_info2 = st.columns([2, 1])

          with col_info1:
            st.markdown(
                f"### 📋 Hoja de Vida: {marca_e} {modelo_e}"
            )
            st.write(f"**Propietario:** {cliente_hv_sel}")
            st.write(f"**Tipo de Equipo:** {t_eq}")
            st.write(
                f"**Serial:** `{serial_e}` | **Capacidad:** {cap_e} kg"
            )
            st.write(
                f"**Altura de Elevación:** {alt_e} mm | **Horómetro Actual:**"
                f" {hor_e} hrs"
            )

          with col_info2:
            if foto_e and os.path.exists(foto_e):
              st.image(
                  foto_e, caption=f"Montacarga {marca_e}", width=220
              )
            else:
              st.info("Sin foto adjunta del equipo.")

          st.markdown(
              "### 🛠️ Historial de Órdenes de Servicio Asociadas"
          )
          conexion = sqlite3.connect(ruta_db)
          cursor = conexion.cursor()
          cursor.execute(
              """
                        SELECT consecutivo, tipo_servicio, fecha, observaciones, persona_recibe, horometro_actual, foto_path, firma_path, tecnico_id, id 
                        FROM ordenes_servicio WHERE equipo_id = ? ORDER BY id DESC
                    """,
              (e_id,),
          )
          historial_os = cursor.fetchall()

          cursor.execute(
              "SELECT * FROM clientes WHERE id = ?", (cli_id_busqueda,)
          )
          c_data_hv = cursor.fetchone()
          cursor.execute("SELECT * FROM equipos WHERE id = ?", (e_id,))
          e_tuple_db = cursor.fetchone()
          conexion.close()

          if historial_os:
            for h in historial_os:
              (
                  cons_h,
                  tipo_h,
                  fecha_h,
                  obs_h,
                  recibe_h,
                  hor_h,
                  f_path_h,
                  firma_path_h,
                  tec_id_h,
                  id_os_db,
              ) = h
              with st.expander(
                  f"Orden No. {cons_h} - Fecha: {fecha_h} ({tipo_h})"
              ):
                st.write(f"**Horómetro al servicio:** {hor_h} hrs")
                st.write(f"**Trabajos / Observaciones:** {obs_h}")
                st.write(f"**Recibe a satisfacción:** {recibe_h}")

                if st.button(
                    "🗑️ Eliminar este registro de servicio",
                    key=f"del_os_{id_os_db}",
                ):
                  con_del_os = sqlite3.connect(ruta_db)
                  cur_del_os = con_del_os.cursor()
                  cur_del_os.execute(
                      "DELETE FROM ordenes_servicio WHERE id = ?", (id_os_db,)
                  )
                  con_del_os.commit()
                  con_del_os.close()
                  st.success(f"Orden {cons_h} eliminada del historial.")
                  st.rerun()
          else:
            st.info(
                "Este montacarga no registra órdenes de servicio anteriores."
            )

          st.markdown("---")
          if st.button(
              "📄 Generar y Descargar PDF de Hoja de Vida Completa",
              type="primary",
          ):
            eq_tuple_for_pdf = (
                t_eq,
                marca_e,
                modelo_e,
                serial_e,
                cap_e,
                alt_e,
                hor_e,
                "",
                "",
                foto_e,
            )
            ruta_pdf_hv = generar_pdf_hoja_de_vida(
                c_data_hv, eq_tuple_for_pdf, historial_os
            )

            st.success("🎉 Hoja de vida generada con éxito.")
            with open(ruta_pdf_hv, "rb") as pdf_file:
              st.download_button(
                  label="📥 Descargar PDF de Hoja de Vida",
                  data=pdf_file,
                  file_name=f"HV_{serial_e.replace('/', '_')}.pdf",
                  mime="application/pdf",
              )
    else:
      # Vista exclusiva para perfil cliente logueado
      cli_id_cliente = st.session_state.cliente_id_usuario
      conexion = sqlite3.connect(ruta_db)
      cursor = conexion.cursor()
      cursor.execute(
          "SELECT id, tipo_equipo, marca, modelo, serial, capacidad, altura,"
          " horometro, foto_path FROM equipos WHERE cliente_id = ?",
          (cli_id_cliente,),
      )
      equipos_cliente_log = cursor.fetchall()

      cursor.execute(
          "SELECT * FROM clientes WHERE id = ?", (cli_id_cliente,)
      )
      c_data_hv = cursor.fetchone()
      conexion.close()

      if not equipos_cliente_log:
        st.info("No tienes montacargas registrados en tu flota actualmente.")
      else:
        eq_dict_cli = {
            f"[{eq[1]}] {eq[2]} {eq[3]} - Serial: {eq[4]}": eq
            for eq in equipos_cliente_log
        }
        eq_sel_key = st.selectbox(
            "Selecciona tu Montacarga", list(eq_dict_cli.keys())
        )
        eq_selected_data = eq_dict_cli[eq_sel_key]

        e_id, t_eq, marca_e, modelo_e, serial_e, cap_e, alt_e, hor_e, foto_e = (
            eq_selected_data
        )

        st.markdown("---")
        st.markdown(
            f"### 📋 Hoja de Vida: {marca_e} {modelo_e} (Serial:"
            f" {serial_e})"
        )
        st.write(
            f"**Tipo:** {t_eq} | **Capacidad:** {cap_e} kg | **Altura:** {alt_e}"
            f" mm | **Horómetro:** {hor_e} hrs"
        )

        if foto_e and os.path.exists(foto_e):
          st.image(foto_e, width=250)

        st.markdown("### 🛠️ Historial de Servicios")
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT consecutivo, tipo_servicio, fecha, observaciones,"
            " persona_recibe, horometro_actual, foto_path, firma_path,"
            " tecnico_id, id FROM ordenes_servicio WHERE equipo_id = ? ORDER BY"
            " id DESC",
            (e_id,),
        )
        historial_os = cursor.fetchall()
        conexion.close()

        if historial_os:
          for h in historial_os:
            (
                cons_h,
                tipo_h,
                fecha_h,
                obs_h,
                recibe_h,
                hor_h,
                f_path_h,
                firma_path_h,
                tec_id_h,
                id_os_db,
            ) = h
            with st.expander(
                f"Orden No. {cons_h} - Fecha: {fecha_h} ({tipo_h})"
            ):
              st.write(f"**Horómetro:** {hor_h} hrs")
              st.write(f"**Trabajos / Observaciones:** {obs_h}")
              st.write(f"**Recibe:** {recibe_h}")
        else:
          st.info("No hay servicios técnicos registrados para este equipo.")

# -------------------------------------------------------------
# MÓDULO 5: CLIENTES (Solo Admin)
# -------------------------------------------------------------
elif menu == "👥 Clientes" and st.session_state.rol == "admin":
  st.subheader("👥 Gestión de Clientes y Propietarios de Flota")

  tab_reg_cli, tab_ver_cli = st.tabs(
      ["➕ Registrar Nuevo Cliente", "📋 Listado de Clientes"]
  )

  with tab_reg_cli:
    with st.form("form_cliente"):
      nombre_empresa = st.text_input(
          "Nombre de la Empresa / Cliente",
          placeholder="Ej. Comercial Nutresa / S.A.S.",
      )
      nit_cliente = st.text_input("NIT / Cédula", placeholder="Ej. 900.123.456-1")
      direccion_cliente = st.text_input(
          "Dirección", placeholder="Ej. Zona Industrial Via Chimitá"
      )
      contacto_cliente = st.text_input(
          "Persona de Contacto / Teléfono",
          placeholder="Ej. Ing. Carlos Gomez - 3101234567",
      )

      btn_guardar_cli = st.form_submit_button("Guardar Cliente")

      if btn_guardar_cli:
        if nombre_empresa.strip():
          conexion = sqlite3.connect(ruta_db)
          cursor = conexion.cursor()
          cursor.execute(
              """
                        INSERT INTO clientes (nombre_empresa, nit, direccion, contacto)
                        VALUES (?, ?, ?, ?)
                    """,
              (
                  nombre_empresa,
                  nit_cliente,
                  direccion_cliente,
                  contacto_cliente,
              ),
          )
          conexion.commit()
          conexion.close()
          st.success(
              f"🎉 Cliente **{nombre_empresa}** registrado correctamente."
          )
        else:
          st.error("El nombre de la empresa es obligatorio.")

  with tab_ver_cli:
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute(
        "SELECT id, nombre_empresa, nit, direccion, contacto FROM clientes"
    )
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
# MÓDULO 6: TÉCNICOS (Solo Admin)
# -------------------------------------------------------------
elif menu == "🛠️ Técnicos" and st.session_state.rol == "admin":
  st.subheader("🛠️ Gestión de Personal Técnico MMB")

  tab_reg_tec, tab_ver_tec = st.tabs(
      ["➕ Registrar Nuevo Técnico", "📋 Listado de Técnicos"]
  )

  with tab_reg_tec:
    with st.form("form_tecnico"):
      nombre_tec = st.text_input(
          "Nombre Completo del Técnico", placeholder="Ej. Nelson Rojas"
      )
      cedula_tec = st.text_input(
          "Número de Cédula", placeholder="Ej. 1098604964"
      )

      btn_guardar_tec = st.form_submit_button("Guardar Técnico")

      if btn_guardar_tec:
        if nombre_tec.strip() and cedula_tec.strip():
          try:
            conexion = sqlite3.connect(ruta_db)
            cursor = conexion.cursor()
            cursor.execute(
                """
                            INSERT INTO tecnicos (nombre, cedula)
                            VALUES (?, ?)
                        """,
                (nombre_tec, cedula_tec),
            )
            conexion.commit()
            conexion.close()
            st.success(
                f"🎉 Técnico **{nombre_tec}** registrado correctamente."
            )
          except sqlite3.IntegrityError:
            st.error(
                "❌ Ya existe un técnico registrado con este número de cédula."
            )
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

# -------------------------------------------------------------
# MÓDULO 7: GESTIÓN DE USUARIOS (Solo Admin)
# -------------------------------------------------------------
elif menu == "👥 Usuarios" and st.session_state.rol == "admin":
  st.subheader("👥 Gestión de Usuarios y Accesos al Portal")

  conexion = sqlite3.connect(ruta_db)
  cursor = conexion.cursor()
  cursor.execute("SELECT id, nombre_empresa FROM clientes")
  clientes_u = cursor.fetchall()
  conexion.close()

  tab_reg_u, tab_ver_u = st.tabs(
      ["➕ Crear Nuevo Usuario", "📋 Listado de Usuarios"]
  )

  with tab_reg_u:
    with st.form("form_nuevo_usuario"):
      nuevo_user = st.text_input(
          "Nombre de Usuario (Login)", placeholder="Ej. nutresa_user"
      )
      nuevo_pass = st.text_input("Contraseña de Acceso", type="password")
      rol_sel = st.selectbox("Rol del Usuario", ["admin", "cliente"])

      cliente_asociado_id = None
      if rol_sel == "cliente":
        if clientes_u:
          cli_dict_u = {c[1]: c[0] for c in clientes_u}
          cli_asoc_sel = st.selectbox(
              "Asociar a Cliente", list(cli_dict_u.keys())
          )
          cliente_asociado_id = cli_dict_u[cli_asoc_sel]
        else:
          st.warning(
              "⚠️ No hay clientes registrados para asociar. Crea uno primero"
              " en el módulo de Clientes."
          )

      btn_guardar_user = st.form_submit_button("Crear Usuario")

      if btn_guardar_user:
        if nuevo_user.strip() and nuevo_pass.strip():
          try:
            conexion = sqlite3.connect(ruta_db)
            cursor = conexion.cursor()
            cursor.execute(
                """
                            INSERT INTO usuarios (username, password, rol, cliente_id)
                            VALUES (?, ?, ?, ?)
                        """,
                (
                    nuevo_user,
                    nuevo_pass,
                    rol_sel,
                    cliente_asociado_id,
                ),
            )
            conexion.commit()
            conexion.close()
            st.success(f"🎉 Usuario **{nuevo_user}** creado exitosamente.")
          except sqlite3.IntegrityError:
            st.error(
                "❌ El nombre de usuario ya existe. Elige otro."
            )
        else:
          st.error("Por favor completa el usuario y la contraseña.")

  with tab_ver_u:
    conexion = sqlite3.connect(ruta_db)
    cursor = conexion.cursor()
    cursor.execute("""
            SELECT u.id, u.username, u.rol, c.nombre_empresa 
            FROM usuarios u 
            LEFT JOIN clientes c ON u.cliente_id = c.id
        """)
    usuarios_db = cursor.fetchall()
    conexion.close()

    if usuarios_db:
      for u in usuarios_db:
        u_id, u_name, u_rol, u_cli = u
        empresa_texto = f" (Cliente: {u_cli})" if u_cli else ""
        with st.expander(
            f"👤 {u_name} - Rol: `{u_rol.upper()}`{empresa_texto}"
        ):
          if (
              u_name != "admin"
          ):  # Evitar eliminar al admin principal por error
            if st.button("🗑️ Eliminar Usuario", key=f"del_u_{u_id}"):
              conexion = sqlite3.connect(ruta_db)
              cursor = conexion.cursor()
              cursor.execute("DELETE FROM usuarios WHERE id = ?", (u_id,))
              conexion.commit()
              conexion.close()
              st.success("Usuario eliminado.")
              st.rerun()
          else:
            st.info(
                "Este es el usuario administrador principal del sistema."
            )
    else:
      st.info("No hay usuarios adicionales registrados.")

# -------------------------------------------------------------
# MÓDULO 8: CAMBIAR CONTRASEÑA (Para cualquier usuario activo)
# -------------------------------------------------------------
elif menu == "🔑 Cambiar Contraseña":
  st.subheader("🔑 Cambiar Contraseña de Acceso")
  st.write(
      f"Estás actualizando la contraseña para el usuario actual: "
      f"**{st.session_state.username}**"
  )

  with st.form("form_cambiar_pass"):
    password_actual = st.text_input(
        "Contraseña Actual", type="password", key="pwd_act"
    )
    nuevo_password = st.text_input(
        "Nueva Contraseña", type="password", key="pwd_nuevo"
    )
    confirmar_password = st.text_input(
        "Confirmar Nueva Contraseña", type="password", key="pwd_conf"
    )
    submit_pass = st.form_submit_button("Actualizar Contraseña")

    if submit_pass:
      if not password_actual or not nuevo_password or not confirmar_password:
        st.error("Por favor completa todos los campos.")
      elif nuevo_password != confirmar_password:
        st.error("Las nuevas contraseñas no coinciden.")
      else:
        conexion = sqlite3.connect(ruta_db)
        cursor = conexion.cursor()

        # Verificar contraseña actual en la base de datos
        cursor.execute(
            "SELECT password FROM usuarios WHERE username = ?",
            (st.session_state.username,),
        )
        resultado = cursor.fetchone()

        if resultado and resultado[0] == password_actual:
          # Actualizar con la nueva contraseña
          cursor.execute(
              "UPDATE usuarios SET password = ? WHERE username = ?",
              (nuevo_password, st.session_state.username),
          )
          conexion.commit()
          conexion.close()
          st.success(
              "🎉 ¡Contraseña actualizada exitosamente! Ya puedes usarla en"
              " tu próximo inicio de sesión."
          )
        else:
          conexion.close()
          st.error("❌ La contraseña actual es incorrecta.")
