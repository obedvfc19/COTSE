import os
import requests
import uuid
import io
from flask import Flask, request, url_for
from twilio.twiml.messaging_response import MessagingResponse
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from dotenv import load_dotenv

# --- 0. INICIALIZACIÓN Y CARGA DE CREDENCIALES ---
load_dotenv()
app = Flask(__name__, static_folder='static')
user_sessions = {}

# --- 1. GUION DE LA CONVERSACIÓN (AJUSTADO PARA REPORTE_COTSE.pdf) ---
REPORT_FLOW = {
    'awaiting_start':           { 'key': 'Inicio', 'next_state': 'awaiting_ot'},
    'awaiting_ot':              { 'key': 'O.T.', 'next_state': 'awaiting_fecha', 'question': '✅ Reporte COTSE iniciado. Por favor, ingresa la *O.T. (Orden de Trabajo)*.'},
    'awaiting_fecha':           { 'key': 'Fecha', 'next_state': 'awaiting_area', 'question': 'Ahora, por favor, escribe la *Fecha* en formato DD/MM/YY.'},
    'awaiting_area':            { 'key': 'Area de trabajo', 'next_state': 'awaiting_lugar', 'question': 'Ingresa el *Área* de trabajo.'},
    'awaiting_lugar':           { 'key': 'Lugar', 'next_state': 'awaiting_turno', 'question': 'Gracias. Ahora, escribe el *Lugar* específico.'},
    'awaiting_turno':           { 'key': 'TURNO', 'next_state': 'awaiting_supervisor_cotse', 'question': 'Ingresa el *Turno*.'},
    'awaiting_supervisor_cotse':{ 'key': 'Supervisor COTSE', 'next_state': 'awaiting_supervisor_ternium', 'question': '¿Quién es el *Supervisor de COTSE*?'},
    'awaiting_supervisor_ternium':{ 'key': 'Usuario TERNIUM', 'next_state': 'awaiting_trabajadores', 'question': '¿Y el *Supervisor o Usuario de TERNIUM*?'},
    'awaiting_trabajadores':    { 'key': 'Trabajadores', 'next_state': 'awaiting_partida_descripcion', 'question': 'Anotado. Escribe los nombres de los *Trabajadores* que intervienen.'},
    
    # --- Flujo de Partidas (adaptado de test_app.py) ---
    'awaiting_partida_descripcion': { 'key': 'descripcion', 'next_state': 'awaiting_partida_um', 'question': '➡️ Ingrese la *descripción de la actividad* para la partida actual.'},
    'awaiting_partida_um':        { 'key': 'um', 'next_state': 'awaiting_partida_cantidad', 'question': 'Ahora ingrese la *Unidad de Medida (U/M)* (p. ej., pza, m, kg).'},
    'awaiting_partida_cantidad':  { 'key': 'cantidad', 'next_state': 'awaiting_next_partida', 'question': 'Ingrese la *cantidad*.'},
    'awaiting_next_partida':      { 'key': 'Partida_Control', 'next_state': 'awaiting_duracion', 'question': 'Partida agregada. ✅\n\n- Escriba *"agregar"* para añadir otra partida.\n- Escriba *"listo"* para continuar con el reporte.'},
    
    'awaiting_duracion':        { 'key': 'Duracion de trabajo', 'next_state': 'awaiting_fotos_antes', 'question': 'Perfecto. Ahora, especifica la *Duración del trabajo* (ej: 8 horas).'},
    
    # --- Flujo de Fotos (adaptado de app.py) ---
    'awaiting_fotos_antes':     { 'key': 'Fotos_antes', 'next_state': 'awaiting_fotos_despues', 'question': 'Ahora, envía hasta *2 fotos de ANTES*. Cuando termines, escribe "listo".'},
    'awaiting_fotos_despues':   { 'key': 'Fotos_despues', 'next_state': 'report_complete', 'question': 'Fotos de "antes" recibidas. ✅ Ahora, envía hasta *2 fotos de DESPUÉS*. Cuando termines, escribe "listo".'},
    'report_complete':          { 'key': 'Completo', 'next_state': 'report_complete', 'question': '¡Reporte completado! ✅ Estoy generando tu PDF, por favor espera un momento...'}
}


# --- 2. FUNCIÓN PARA CREAR EL PDF (AJUSTADA PARA REPORTE_COTSE.pdf) ---
def create_cotse_pdf(report_data, account_sid, auth_token):
    template_path = "REPORTE_COTSE.pdf" 
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)
    can.setFont("Helvetica", 9)

    # --- Coordenadas de texto para REPORTE_COTSE.pdf ---
    # Fila superior
    can.drawString(90, 756, str(report_data.get('Area de trabajo', '')))
    can.drawString(54, 744, str(report_data.get('Lugar', '')))
    can.drawString(318, 756, str(report_data.get('Fecha', '')))
    # Fila media
    can.drawString(308, 744, str(report_data.get('O.T.', '')))
    can.drawString(60, 732, str(report_data.get('TURNO', '')))
    can.drawString(370, 707, str(report_data.get('Supervisor COTSE', '')))
    # Fila inferior
    can.drawString(370, 720, str(report_data.get('Usuario TERNIUM', '')))
    can.drawString(85, 708, str(report_data.get('Trabajadores', '')))
    can.drawString(510, 744, str(report_data.get('Duracion de trabajo', '')))
    
    # --- Lógica para dibujar la tabla de partidas ---
    y_position = 678 # Posición inicial Y para la primera fila de la tabla
    line_height = 12
    item_count = 1
    text_object = can.beginText()
    text_object.setFont("Helvetica", 8)

    for partida in report_data.get('Partidas', []):
        text_object.setTextOrigin(40, y_position) # Columna ITEM
        text_object.textLine(str(item_count))
        
        text_object.setTextOrigin(65, y_position) # Columna DESCRIPCION
        text_object.textLine(str(partida.get('descripcion', '')))

        text_object.setTextOrigin(430, y_position) # Columna U/M
        text_object.textLine(str(partida.get('um', '')))

        text_object.setTextOrigin(524, y_position) # Columna CANTIDAD
        text_object.textLine(str(partida.get('cantidad', '')))
        
        y_position -= line_height
        item_count += 1
    
    can.drawText(text_object)
    
    # --- Lógica de imágenes (apila verticalmente las fotos en cada columna) ---
    def add_image_gallery(urls, x_start, y_top, image_width, image_height):
        y_cursor = y_top
        for url in urls:
            try:
                response = requests.get(url, auth=(account_sid, auth_token), timeout=20)
                if response.status_code == 200:
                    temp_path = os.path.join('temp_images', str(uuid.uuid4()))
                    with open(temp_path, 'wb') as f: f.write(response.content)
                    
                    y_coord_from_bottom = y_cursor - image_height
                    can.drawImage(temp_path, x_start, y_coord_from_bottom, width=image_width, height=image_height, mask='auto', preserveAspectRatio=True)
                else:
                    raise Exception(f"Estado de descarga: {response.status_code}")
                
                # Mueve el cursor para la siguiente imagen en la misma columna
                y_cursor -= (image_height + 6) # 5 es el padding
            except Exception as e:
                print(f"!!! ERROR al procesar imagen {url}: {e}")
                # Dibuja un cuadro de error si la imagen falla
                error_box_h = 40
                y_coord_from_bottom = y_cursor - error_box_h
                can.setFillColorRGB(1, 0.9, 0.9); can.rect(x_start, y_coord_from_bottom, image_width, error_box_h, fill=1, stroke=0)
                can.setFillColorRGB(0.7, 0, 0); can.drawString(x_start + 5, y_cursor - 25, "Error al cargar la imagen.")
                can.setFillColorRGB(0, 0, 0)
                y_cursor -= (error_box_h + 5)

    if not os.path.exists('temp_images'): os.makedirs('temp_images')
    # Dibuja las galerías en las coordenadas del nuevo formato
    add_image_gallery(report_data.get('Fotos_antes', []), x_start=26, y_top=538, image_width=258, image_height=154)
    add_image_gallery(report_data.get('Fotos_despues', []), x_start=290, y_top=538, image_width=277, image_height=154)

    # --- Fusión y guardado del PDF ---
    can.save()
    packet.seek(0)
    new_pdf_content = PdfReader(packet)
    existing_pdf_template = PdfReader(open(template_path, "rb"))
    output = PdfWriter()
    page = existing_pdf_template.pages[0]
    page.merge_page(new_pdf_content.pages[0])
    output.add_page(page)
    if not os.path.exists('static/reports'): os.makedirs('static/reports')
    pdf_filename = f'reporte_cotse_{uuid.uuid4()}.pdf'
    pdf_path = os.path.join(app.static_folder, 'reports', pdf_filename)
    with open(pdf_path, "wb") as outputStream: output.write(outputStream)
    if os.path.exists('temp_images'):
        for f in os.listdir('temp_images'): os.remove(os.path.join('temp_images', f))
    return os.path.join('reports', pdf_filename).replace('\\', '/')

# --- 3. LÓGICA PRINCIPAL DEL BOT (HÍBRIDA) ---
@app.route("/whatsapp", methods=['POST'])
def whatsapp_reply():
    sender_id = request.values.get('From', '')
    incoming_msg_original = request.values.get('Body', '').strip()
    incoming_msg_lower = incoming_msg_original.lower()
    media_urls = [request.values.get(f'MediaUrl{i}') for i in range(int(request.values.get('NumMedia', 0)))]
    resp = MessagingResponse()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    MAX_PHOTOS = 2 

    if sender_id not in user_sessions or 'iniciar' in incoming_msg_lower:
        user_sessions[sender_id] = {
            'state': 'awaiting_start', 
            'report_data': {'Partidas': []}, 
            'current_partida': {}
        }
    
    session = user_sessions[sender_id]
    current_state = session['state']
    flow_step = REPORT_FLOW[current_state]

    # --- Lógica para el bucle de Partidas ---
    if 'partida' in current_state:
        if current_state == 'awaiting_next_partida':
            if 'listo' in incoming_msg_lower:
                # El usuario terminó de agregar partidas, avanzar al siguiente paso
                session['state'] = flow_step['next_state']
                resp.message(REPORT_FLOW[session['state']]['question'])
            else: # El usuario quiere agregar otra partida
                session['state'] = 'awaiting_partida_descripcion'
                num_partida = len(session['report_data']['Partidas']) + 1
                resp.message(f"Ok, vamos con la partida #{num_partida}.")
                resp.message(REPORT_FLOW[session['state']]['question'])
        else:
            # Guardar el dato de la partida actual y pedir el siguiente
            session['current_partida'][flow_step['key']] = incoming_msg_original
            session['state'] = flow_step['next_state']
            # Si hemos recogido el último dato (cantidad), guardamos la partida completa
            if session['state'] == 'awaiting_next_partida':
                 session['report_data']['Partidas'].append(session['current_partida'])
                 session['current_partida'] = {} # Limpiar para la siguiente
            
            resp.message(REPORT_FLOW[session['state']]['question'])

    # --- Lógica para el bucle de Fotos ---
    elif 'fotos' in current_state:
        photo_key = flow_step['key']
        if photo_key not in session['report_data']:
            session['report_data'][photo_key] = []
        
        current_photo_count = len(session['report_data'][photo_key])

        if media_urls: # Si el usuario envía fotos
            if current_photo_count >= MAX_PHOTOS:
                resp.message(f"Ya has enviado el máximo de {MAX_PHOTOS} fotos. Escribe 'listo' para continuar.")
            else:
                photos_to_add = media_urls[:MAX_PHOTOS - current_photo_count]
                session['report_data'][photo_key].extend(photos_to_add)
                new_photo_count = len(session['report_data'][photo_key])
                
                if new_photo_count >= MAX_PHOTOS:
                    resp.message(f"Límite de {MAX_PHOTOS} fotos alcanzado. ✅")
                    session['state'] = flow_step['next_state']
                    next_question = REPORT_FLOW[session['state']]['question']
                    resp.message(next_question)
                else:
                    resp.message(f"Foto {new_photo_count} de {MAX_PHOTOS} recibida. Envía otra o escribe 'listo'.")

        elif 'listo' in incoming_msg_lower: # Si el usuario escribe 'listo'
            session['state'] = flow_step['next_state']
            next_question = REPORT_FLOW[session['state']]['question']
            resp.message(next_question)
        else:
            resp.message(f'Por favor, envía una foto (máximo {MAX_PHOTOS}) o escribe "listo".')
        
        # --- Generación del PDF al final del flujo de fotos ---
        if session['state'] == 'report_complete':
            try:
                pdf_relative_path = create_cotse_pdf(session['report_data'], account_sid, auth_token)
                pdf_url = url_for('static', filename=pdf_relative_path, _external=True)
                pdf_message = resp.message()
                pdf_message.media(pdf_url)
            except Exception as e:
                print(f"!!! ERROR FATAL al crear o enviar PDF: {e}")
                resp.message("Lo siento, tuve un problema crítico al generar tu PDF.")
    
    # --- Lógica para los demás estados de texto ---
    else: 
        if current_state == 'report_complete':
             resp.message("Reporte ya completado. Escribe 'iniciar' para comenzar otro.")
             return str(resp)

        session['report_data'][flow_step['key']] = incoming_msg_original
        session['state'] = flow_step['next_state']
        resp.message(REPORT_FLOW[session['state']]['question'])
            
    return str(resp)

# --- 4. INICIAR LA APLICACIÓN ---
if __name__ == "__main__":
    # Asegúrate de que el modo debug esté desactivado en producción
    app.run(debug=True, port=5002)