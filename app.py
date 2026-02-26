from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import zipfile
import io
import time

from whatsapp_sender import enviar_whatsapp_selenium

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# =========================================================
# MODELOS
# =========================================================

class Profesor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    email = db.Column(db.String(100))
    telefono = db.Column(db.String(50))
    escala = db.Column(db.Integer)

class MateriaEscuela(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)

class Liquidacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey('profesor.id'))
    mes = db.Column(db.String(20))
    anio = db.Column(db.Integer)
    fecha = db.Column(db.DateTime, default=datetime.now)
    profesor = db.relationship('Profesor', backref='liquidaciones')

class DetalleLiquidacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    liquidacion_id = db.Column(db.Integer, db.ForeignKey('liquidacion.id'))
    materia = db.Column(db.String(100))
    horario = db.Column(db.String(100))
    comentario = db.Column(db.String(200))
    cantidad_alumnos = db.Column(db.Integer)
    horas_mes = db.Column(db.Float)
    valor_hora = db.Column(db.Float)
    subtotal = db.Column(db.Float)
    liquidacion = db.relationship('Liquidacion', backref='detalles')

class EscalaProfesor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    escala = db.Column(db.Integer, unique=True)
    valor_hora = db.Column(db.Float)

class EscalaCantidadAlumnos(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    escala_profesor = db.Column(db.Integer, nullable=False)  # 1,2,3
    minimo = db.Column(db.Integer, nullable=False)
    maximo = db.Column(db.Integer, nullable=False)
    valor_hora = db.Column(db.Float, nullable=False)

class ConfigCalculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    formula = db.Column(db.String(200))

# =========================================================
# INICIALIZACIÓN DB (DESPUÉS DE MODELOS)
# =========================================================

db_creada = False

@app.before_request
def crear_db():
    global db_creada
    if not db_creada:
        db.create_all()
        db_creada = True

        if not EscalaProfesor.query.first():
            for i in range(1, 4):
                db.session.add(EscalaProfesor(escala=i, valor_hora=0))
            db.session.commit()

        if not EscalaCantidadAlumnos.query.first():
            rangos = [
                (1, 4),
                (5, 8),
                (9, 12),
                (13, 16),
                (17, 99)
            ]

            for escala in [1, 2, 3]:
                for minimo, maximo in rangos:
                    db.session.add(EscalaCantidadAlumnos(
                    escala_profesor=escala,
                    minimo=minimo,
                    maximo=maximo,
                    valor_hora=0
                ))

            db.session.commit()

        if not ConfigCalculo.query.first():
            db.session.add(ConfigCalculo(
                formula="(valor_profesor + valor_alumnos) * horas"
            ))
            db.session.commit()

# =========================================================
# FUNCIONES DE CÁLCULO
# =========================================================

def obtener_valor_alumnos(escala_profesor, cantidad):
    escala = EscalaCantidadAlumnos.query.filter(
        EscalaCantidadAlumnos.escala_profesor == escala_profesor,
        EscalaCantidadAlumnos.minimo <= cantidad,
        EscalaCantidadAlumnos.maximo >= cantidad
    ).first()

    return escala.valor_hora if escala else 0

def calcular_subtotal(profesor, cantidad_alumnos, horas):
    escala_prof = EscalaProfesor.query.filter_by(escala=profesor.escala).first()
    valor_profesor = escala_prof.valor_hora if escala_prof else 0
    valor_alumnos = obtener_valor_alumnos(profesor.escala, cantidad_alumnos)

    config = ConfigCalculo.query.first()
    formula = config.formula if config else "0"

    contexto = {
        "valor_profesor": valor_profesor,
        "valor_alumnos": valor_alumnos,
        "horas": horas
    }

    try:
        return float(eval(formula, {}, contexto))
    except Exception:
        return 0

# -------------------------
# NUEVA RUTA PARA VALOR POR HORA DINÁMICO
# -------------------------
@app.route('/calcular_valor_hora')
def calcular_valor_hora():
    profesor_id = request.args.get('profesor_id', type=int)
    cantidad_alumnos = request.args.get('cantidad_alumnos', type=int)

    profesor = Profesor.query.get_or_404(profesor_id)
    escala_prof = EscalaProfesor.query.filter_by(escala=profesor.escala).first()
    valor_profesor = escala_prof.valor_hora if escala_prof else 0
    valor_alumnos = obtener_valor_alumnos(profesor.escala, cantidad_alumnos)
    valor_hora = valor_profesor + valor_alumnos

    return {"valor_hora": valor_hora}


# =========================================================
# RUTAS PRINCIPALES
# =========================================================

from sqlalchemy import func

@app.route('/')
def index():
    letra = request.args.get('letra')

    query = Profesor.query

    if letra:
        query = query.filter(Profesor.nombre.ilike(f"{letra}%"))

    profesores = query.order_by(func.lower(Profesor.nombre)).all()

    return render_template(
        'index.html',
        profesores=profesores,
        letra_actual=letra
    )

# ---------------------------------------------------------
# CONFIGURACIÓN DE CÁLCULO
# ---------------------------------------------------------

@app.route('/configuracion_calculo', methods=['GET', 'POST'])
def configuracion_calculo():
    config = ConfigCalculo.query.first()
    if request.method == 'POST':
        config.formula = request.form['formula']
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('configuracion_calculo.html', config=config)

# ---------------------------------------------------------
# ESCALAS PROFESOR
# ---------------------------------------------------------

@app.route('/escalas_profesor', methods=['GET', 'POST'])
def escalas_profesor():
    escalas = EscalaProfesor.query.order_by(EscalaProfesor.escala).all()
    if request.method == 'POST':
        for e in escalas:
            e.valor_hora = float(request.form[f'escala_{e.escala}'])
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('escalas_profesor.html', escalas=escalas)

# ---------------------------------------------------------
# ESCALAS ALUMNOS
# ---------------------------------------------------------

@app.route('/escalas_alumnos', methods=['GET', 'POST'])
def escalas_alumnos():
    escalas = EscalaCantidadAlumnos.query.order_by(EscalaCantidadAlumnos.minimo).all()
    if request.method == 'POST':
        for e in escalas:
            e.valor_hora = float(request.form[f'valor_{e.id}'])
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('escalas_alumnos.html', escalas=escalas)

# -------------------------
# PROFESORES
# -------------------------
@app.route('/agregar_profesor', methods=['POST'])
def agregar_profesor():
    nuevo = Profesor(
        nombre=request.form['nombre'],
        email=request.form['email'],
        telefono=request.form['telefono'],
        escala=int(request.form['escala'])
    )
    db.session.add(nuevo)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/editar_profesor/<int:profesor_id>')
def editar_profesor(profesor_id):
    profesor = Profesor.query.get_or_404(profesor_id)
    return render_template('editar_profesor.html', profesor=profesor)

@app.route('/actualizar_profesor/<int:profesor_id>', methods=['POST'])
def actualizar_profesor(profesor_id):
    profesor = Profesor.query.get_or_404(profesor_id)
    profesor.nombre = request.form['nombre']
    profesor.email = request.form['email']
    profesor.telefono = request.form['telefono']
    profesor.escala = int(request.form['escala'])
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/borrar_profesor/<int:profesor_id>')
def borrar_profesor(profesor_id):
    profesor = Profesor.query.get_or_404(profesor_id)
    db.session.delete(profesor)
    db.session.commit()
    return redirect(url_for('index'))

# -------------------------
# MATERIAS ESCUELA
# -------------------------
from sqlalchemy import func

@app.route('/materias')
def materias():
    materias = MateriaEscuela.query.order_by(
        func.lower(MateriaEscuela.nombre)
    ).all()

    return render_template('materias.html', materias=materias)

@app.route('/agregar_materia', methods=['POST'])
def agregar_materia():
    nombre = request.form['nombre'].strip()
    if nombre:
        existente = MateriaEscuela.query.filter_by(nombre=nombre).first()
        if not existente:
            db.session.add(MateriaEscuela(nombre=nombre))
            db.session.commit()
    return redirect(url_for('materias'))

@app.route('/borrar_materia/<int:materia_id>')
def borrar_materia(materia_id):
    materia = MateriaEscuela.query.get_or_404(materia_id)
    db.session.delete(materia)
    db.session.commit()
    return redirect(url_for('materias'))

@app.route('/editar_materia/<int:materia_id>')
def editar_materia(materia_id):
    materia = MateriaEscuela.query.get_or_404(materia_id)
    return render_template('editar_materia.html', materia=materia)

@app.route('/actualizar_materia/<int:materia_id>', methods=['POST'])
def actualizar_materia(materia_id):
    materia = MateriaEscuela.query.get_or_404(materia_id)
    materia.nombre = request.form['nombre']
    db.session.commit()
    return redirect(url_for('materias'))

# -------------------------
# SELECCION MES
# -------------------------
@app.route('/seleccionar_mes/<int:profesor_id>')
def seleccionar_mes(profesor_id):
    profesor = Profesor.query.get_or_404(profesor_id)
    return render_template('seleccionar_mes.html', profesor=profesor)

# -------------------------
# CREAR LIQUIDACION
# -------------------------
@app.route('/crear_liquidacion/<int:profesor_id>', methods=['POST'])
def crear_liquidacion(profesor_id):
    mes = request.form['mes']
    anio = int(request.form['anio'])
    anterior = Liquidacion.query.filter_by(profesor_id=profesor_id).order_by(Liquidacion.id.desc()).first()
    if anterior:
        materias = anterior.detalles
        return render_template(
            'copiar_anterior.html',
            profesor_id=profesor_id,
            mes=mes,
            anio=anio,
            detalles=materias
        )
    liquidacion = Liquidacion(
        profesor_id=profesor_id,
        mes=mes,
        anio=anio
    )
    db.session.add(liquidacion)
    db.session.commit()
    return redirect(url_for('editar_liquidacion', liquidacion_id=liquidacion.id))

@app.route('/confirmar_copia', methods=['POST'])
def confirmar_copia():
    profesor_id = int(request.form['profesor_id'])
    mes = request.form['mes']
    anio = int(request.form['anio'])
    liquidacion = Liquidacion(
        profesor_id=profesor_id,
        mes=mes,
        anio=anio
    )
    db.session.add(liquidacion)
    db.session.commit()
    seleccionados = request.form.getlist('detalles')
    anterior = Liquidacion.query.filter_by(profesor_id=profesor_id).order_by(Liquidacion.id.desc()).offset(1).first()
    for d in anterior.detalles:
        if str(d.id) in seleccionados:
            db.session.add(DetalleLiquidacion(
                liquidacion_id=liquidacion.id,
                materia=d.materia,
                horario=d.horario,
                comentario=d.comentario,
                cantidad_alumnos=d.cantidad_alumnos,
                horas_mes=d.horas_mes,
                valor_hora=d.valor_hora,
                subtotal=d.subtotal
            ))
    db.session.commit()
    return redirect(url_for('editar_liquidacion', liquidacion_id=liquidacion.id))

# -------------------------
# EDITAR LIQUIDACION
# -------------------------
@app.route('/editar_liquidacion/<int:liquidacion_id>')
def editar_liquidacion(liquidacion_id):

    liquidacion = Liquidacion.query.get_or_404(liquidacion_id)
    materias = MateriaEscuela.query.order_by(MateriaEscuela.nombre).all()

    # 🔹 MISMO ORDEN QUE EL PDF
    dias_orden = {
        "Lunes": 1,
        "Martes": 2,
        "Miércoles": 3,
        "Miercoles": 3,
        "Jueves": 4,
        "Viernes": 5,
        "Sábado": 6,
        "Sabado": 6,
        "Domingo": 7
    }

    def clave_orden(d):
        if not d.horario:
            return (99, "99:99")

        partes = d.horario.split()
        dia = partes[0]
        hora = partes[1] if len(partes) > 1 else "99:99"

        return (dias_orden.get(dia, 99), hora)

    detalles_ordenados = sorted(liquidacion.detalles, key=clave_orden)

    total = sum(d.subtotal for d in detalles_ordenados)

    return render_template(
        'liquidacion.html',
        liquidacion=liquidacion,
        materias=materias,
        total=total,
        detalles_ordenados=detalles_ordenados
    )

# -------------------------
# AGREGAR / BORRAR / EDITAR DETALLE
# -------------------------
@app.route('/agregar_detalle/<int:liquidacion_id>', methods=['POST'])
def agregar_detalle(liquidacion_id):
    liquidacion = Liquidacion.query.get_or_404(liquidacion_id)
    profesor = liquidacion.profesor

    cantidad_alumnos = int(request.form['cantidad_alumnos'])
    horas = float(request.form['horas_mes'])

    if request.form.get('subtotal_manual'):
        subtotal = float(request.form['subtotal_manual'])
        valor_hora = subtotal / horas if horas != 0 else 0
    else:
        escala_prof = EscalaProfesor.query.filter_by(escala=profesor.escala).first()
        valor_profesor = escala_prof.valor_hora if escala_prof else 0
        valor_alumnos = obtener_valor_alumnos(profesor.escala, cantidad_alumnos)
        subtotal = calcular_subtotal(profesor, cantidad_alumnos, horas)
        valor_hora = valor_profesor + valor_alumnos

    nuevo = DetalleLiquidacion(
        liquidacion_id=liquidacion_id,
        materia=request.form['materia'],
        horario=request.form['horario'],
        comentario=request.form['comentario'],
        cantidad_alumnos=cantidad_alumnos,
        horas_mes=horas,
        valor_hora=valor_hora,
        subtotal=subtotal
    )

    db.session.add(nuevo)
    db.session.commit()
    return redirect(url_for('editar_liquidacion', liquidacion_id=liquidacion_id))

@app.route('/borrar_detalle/<int:detalle_id>')
def borrar_detalle(detalle_id):
    detalle = DetalleLiquidacion.query.get_or_404(detalle_id)
    lid = detalle.liquidacion_id
    db.session.delete(detalle)
    db.session.commit()
    return redirect(url_for('editar_liquidacion', liquidacion_id=lid))

@app.route('/editar_detalle/<int:detalle_id>')
def editar_detalle(detalle_id):
    detalle = DetalleLiquidacion.query.get_or_404(detalle_id)
    materias = MateriaEscuela.query.order_by(MateriaEscuela.nombre).all()
    return render_template('editar_detalle.html', detalle=detalle, materias=materias)

@app.route('/actualizar_detalle/<int:detalle_id>', methods=['POST'])
def actualizar_detalle(detalle_id):
    detalle = DetalleLiquidacion.query.get_or_404(detalle_id)
    profesor = detalle.liquidacion.profesor

    detalle.materia = request.form['materia']
    detalle.horario = request.form['horario']
    detalle.comentario = request.form['comentario']
    detalle.cantidad_alumnos = int(request.form['cantidad_alumnos'])
    detalle.horas_mes = float(request.form['horas_mes'])

    if request.form.get('subtotal_manual'):
        detalle.subtotal = float(request.form['subtotal_manual'])
        detalle.valor_hora = detalle.subtotal / detalle.horas_mes if detalle.horas_mes != 0 else 0
    else:
        escala_prof = EscalaProfesor.query.filter_by(escala=profesor.escala).first()
        valor_profesor = escala_prof.valor_hora if escala_prof else 0
        valor_alumnos = obtener_valor_alumnos(profesor.escala, detalle.cantidad_alumnos)
        detalle.subtotal = calcular_subtotal(profesor, detalle.cantidad_alumnos, detalle.horas_mes)
        detalle.valor_hora = valor_profesor + valor_alumnos

    db.session.commit()
    return redirect(url_for('editar_liquidacion', liquidacion_id=detalle.liquidacion_id))

# -------------------------
# LIQUIDACIONES - LISTADO Y FILTRO
# -------------------------
@app.route('/liquidaciones')
def liquidaciones():
    profesor_id = request.args.get('profesor_id', type=int)
    mes = request.args.get('mes', type=str)
    anio = request.args.get('anio', type=int)

    query = Liquidacion.query

    if profesor_id:
        query = query.filter_by(profesor_id=profesor_id)
    if mes:
        query = query.filter_by(mes=mes)
    if anio:
        query = query.filter_by(anio=anio)

    liquidaciones = query.order_by(Liquidacion.fecha.desc()).all()

    datos = []
    total_general = 0   # 🔹 NUEVO CONTADOR

    for l in liquidaciones:
        total = sum(d.subtotal for d in l.detalles)

        total_general += total   # 🔹 SUMAMOS AL TOTAL GLOBAL

        datos.append({
            'id': l.id,
            'profesor': l.profesor.nombre if l.profesor else '',
            'mes': l.mes,
            'anio': l.anio,
            'fecha': l.fecha,
            'total': total
        })

    profesores = Profesor.query.order_by(Profesor.nombre).all()

    return render_template(
        'liquidaciones.html',
        liquidaciones=datos,
        profesores=profesores,
        filtro_profesor=profesor_id,
        filtro_mes=mes,
        filtro_anio=anio,
        total_general=total_general   # 🔹 ENVIAMOS EL TOTAL
    )

# -------------------------
# FUNCION GENERAR PDF
# -------------------------
def generar_pdf(liquidacion):

    # 🔹 ORDEN PROFESIONAL POR DIA + HORA
    dias_orden = {
        "Lunes": 1,
        "Martes": 2,
        "Miércoles": 3,
        "Miercoles": 3,
        "Jueves": 4,
        "Viernes": 5,
        "Sábado": 6,
        "Sabado": 6,
        "Domingo": 7
    }

    def clave_orden(d):
        if not d.horario:
            return (99, "99:99")

        partes = d.horario.split()
        dia = partes[0]
        hora = partes[1] if len(partes) > 1 else "99:99"

        return (dias_orden.get(dia, 99), hora)

    detalles_ordenados = sorted(liquidacion.detalles, key=clave_orden)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(tmp.name, pagesize=A4)
    width, height = A4

# -------------------------------------------------
# 🔹 LOGO ESCUELA
# -------------------------------------------------
    logo_path = os.path.join(app.static_folder, "logo.png")

    if os.path.exists(logo_path):
        c.drawImage(
            logo_path,
            40,                 # posición horizontal
            height - 90,        # posición vertical
            width=110,          # tamaño ancho logo
            preserveAspectRatio=True,
            mask='auto'
        )

# -------------------------------------------------
# 🔹 TITULO
# -------------------------------------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(170, height - 60, "LIQUIDACIÓN DOCENTE")

# Ajustamos punto inicial vertical
    y = height - 120

    y -= 25
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Profesor: {liquidacion.profesor.nombre}")
    y -= 15
    c.drawString(40, y, f"Mes: {liquidacion.mes} {liquidacion.anio}")
    y -= 15
    c.drawString(40, y, f"Fecha: {liquidacion.fecha.strftime('%d/%m/%Y')}")

    y -= 25
    c.setFont("Helvetica-Bold", 9)
    headers = ["Materia", "Horario", "Comentario", "Alum.", "Horas", "$/Hora", "Subtotal"]
    xs = [40, 120, 200, 340, 380, 420, 480]

    for h, x in zip(headers, xs):
        c.drawString(x, y, h)

    y -= 10
    c.line(40, y, 550, y)
    y -= 12

    c.setFont("Helvetica", 9)
    total = 0

    for d in detalles_ordenados:
        if y < 80:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

        c.drawString(40, y, d.materia)
        c.drawString(120, y, d.horario or "")
        c.drawString(200, y, d.comentario or "")
        c.drawRightString(360, y, str(d.cantidad_alumnos))
        c.drawRightString(400, y, f"{d.horas_mes:.2f}")
        c.drawRightString(460, y, f"{d.valor_hora:.2f}")
        c.drawRightString(540, y, f"{d.subtotal:.2f}")

        total += d.subtotal
        y -= 14

    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(540, y, f"TOTAL: $ {total:,.2f}")

    c.save()
    return tmp

# -------------------------
# GUARDAR PDF EN STATIC
# -------------------------
def guardar_pdf_en_static(liquidacion):
    carpeta = os.path.join(app.static_folder, "pdfs")
    os.makedirs(carpeta, exist_ok=True)

    nombre_archivo = (
        f"Liquidacion_{liquidacion.profesor.nombre}_"
        f"{liquidacion.mes}_{liquidacion.anio}_{liquidacion.id}.pdf"
    ).replace(" ", "_")

    ruta_final = os.path.join(carpeta, nombre_archivo)

    tmp = generar_pdf(liquidacion)
    with open(tmp.name, "rb") as origen, open(ruta_final, "wb") as destino:
        destino.write(origen.read())

    tmp.close()

    return nombre_archivo

# -------------------------
# DESCARGAR PDF (LINK WHATSAPP)
# -------------------------
@app.route('/descargar_liquidacion/<nombre_pdf>')
def descargar_liquidacion(nombre_pdf):
    ruta = os.path.join(app.static_folder, "pdfs", nombre_pdf)
    return send_file(ruta, as_attachment=True)

# -------------------------
# ENVIAR POR WHATSAPP
# -------------------------
@app.route('/enviar_whatsapp', methods=['POST'])
def enviar_whatsapp():
    ids = request.form.getlist('liquidacion_ids')
    if not ids:
        return {"ok": False, "fallidos": []}

    liquidaciones = Liquidacion.query.filter(
        Liquidacion.id.in_(ids)
    ).all()

    driver = None
    fallidos = []

    for liq in liquidaciones:
        profesor = liq.profesor

        try:
            nombre_pdf = guardar_pdf_en_static(liq)

            link_pdf = url_for(
                'descargar_liquidacion',
                nombre_pdf=nombre_pdf,
                _external=True
            )

            mensaje = (
                f"Hola {profesor.nombre},\n\n"
                f"Te comparto el recibo de honorarios correspondiente a "
                f"{liq.mes} {liq.anio}.\n\n"
                f"📄 Descarga acá el PDF:\n"
                f"{link_pdf}\n\n"
                f"Por favor enviame la factura a "
                f"roberto@escuelademusica.org\n\n"
                f"Gracias!"
            )

            driver, enviado_ok = enviar_whatsapp_selenium(
                nombre=profesor.nombre,
                telefono=profesor.telefono,
                mensaje=mensaje,
                driver=driver
            )

            # 🔹 SI FALLA, LO AGREGAMOS A LA LISTA
            if not enviado_ok:
                fallidos.append(profesor.nombre)

        except Exception as e:
            print(f"❌ Error enviando a {profesor.nombre}: {e}")
            fallidos.append(profesor.nombre)
            continue   # seguir con el próximo

    return {
        "ok": True,
        "fallidos": fallidos
    }

# -------------------------
# EXPORTAR PDF INDIVIDUAL
# -------------------------
@app.route('/liquidacion_pdf/<int:liquidacion_id>')
def liquidacion_pdf(liquidacion_id):
    liquidacion = Liquidacion.query.get_or_404(liquidacion_id)
    tmp = generar_pdf(liquidacion)

    nombre = f"Liquidacion_{liquidacion.profesor.nombre}_{liquidacion.mes}_{liquidacion.anio}_{liquidacion.id}.pdf"
    return send_file(tmp.name, as_attachment=True, download_name=nombre)

# -------------------------
# EXPORTAR PDF MASIVO (ZIP)
# -------------------------
@app.route('/exportar_pdfs_masivos', methods=['POST'])
def exportar_pdfs_masivos():
    ids = request.form.getlist('liquidacion_ids')
    if not ids:
        return redirect(url_for('liquidaciones'))

    liquidaciones = [Liquidacion.query.get(int(lid)) for lid in ids]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zf:
        for l in liquidaciones:
            tmp = generar_pdf(l)
            nombre = f"Liquidacion_{l.profesor.nombre}_{l.mes}_{l.anio}_{l.id}.pdf"
            zf.write(tmp.name, nombre)
            tmp.close()

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='Liquidaciones_seleccionadas.zip'
    )

# -------------------------
# EXPORTAR POR FILTRO
# -------------------------
@app.route('/exportar_pdfs_filtro', methods=['GET'])
def exportar_pdfs_filtro():
    profesor_id = request.args.get('profesor_id', type=int)
    mes = request.args.get('mes', type=str)
    anio = request.args.get('anio', type=int)

    query = Liquidacion.query
    if profesor_id:
        query = query.filter_by(profesor_id=profesor_id)
    if mes:
        query = query.filter_by(mes=mes)
    if anio:
        query = query.filter_by(anio=anio)

    liquidaciones = query.order_by(Liquidacion.fecha.desc()).all()
    if not liquidaciones:
        return redirect(url_for('liquidaciones'))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zf:
        for l in liquidaciones:
            tmp = generar_pdf(l)
            nombre = f"Liquidacion_{l.profesor.nombre}_{l.mes}_{l.anio}_{l.id}.pdf"
            zf.write(tmp.name, nombre)
            tmp.close()

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='Liquidaciones_Filtro.zip'
    )

# -------------------------
# BORRAR LIQUIDACIONES
# -------------------------
@app.route('/borrar_liquidaciones', methods=['POST'])
def borrar_liquidaciones():
    if request.form.get('delete_all') == '1':
        liquidaciones = Liquidacion.query.all()
        for l in liquidaciones:
            for d in l.detalles:
                db.session.delete(d)
            db.session.delete(l)
        db.session.commit()
        return redirect(url_for('liquidaciones'))

    ids = request.form.getlist('liquidacion_ids')
    for lid in ids:
        liquidacion = Liquidacion.query.get(int(lid))
        if liquidacion:
            for d in liquidacion.detalles:
                db.session.delete(d)
            db.session.delete(liquidacion)

    db.session.commit()
    return redirect(url_for('liquidaciones'))

@app.route('/borrar_liquidacion/<int:liquidacion_id>')
def borrar_liquidacion(liquidacion_id):
    liquidacion = Liquidacion.query.get_or_404(liquidacion_id)
    for d in liquidacion.detalles:
        db.session.delete(d)
    db.session.delete(liquidacion)
    db.session.commit()
    return redirect(url_for('liquidaciones'))

# -------------------------
# RUN
# -------------------------
if __name__ == '__main__':
    app.run(debug=True)
