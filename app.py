from flask import Flask, request, jsonify, send_file, abort
import os
import tempfile
import shutil
from urllib.parse import urlparse
import re
from deezspot.deezloader import DeeLogin
import logging

app = Flask(__name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Obtener ARL token desde variables de entorno
ARL_TOKEN = os.getenv('DEEZER_ARL_TOKEN')
if not ARL_TOKEN:
    raise ValueError("La variable de entorno DEEZER_ARL_TOKEN no está definida")

# Inicializar cliente de Deezer
deezer = DeeLogin(arl=ARL_TOKEN, email='', password='', tags_separator=" / ")

def sanitize_filename(filename):
    """Sanitiza el nombre de archivo para evitar caracteres problemáticos"""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return filename

@app.route('/download/song/<string:id>', methods=['GET'])
def download_song(id):
    """
    Descarga una canción individual de Deezer
    Parámetros:
    - id: ID de la canción en Deezer
    - quality: Calidad del audio ('MP3_128', 'MP3_320', 'FLAC') - opcional
    """
    try:
        quality = request.args.get('quality', 'MP3_320')  # Valor por defecto
        allowed_qualities = ['MP3_128', 'MP3_320', 'FLAC']
        
        if quality not in allowed_qualities:
            return jsonify({'error': f'Calidad no válida. Opciones permitidas: {allowed_qualities}'}), 400
        
        # Validar que el ID sea numérico
        if not id.isdigit():
            return jsonify({'error': 'ID de canción inválido'}), 400
        
        # Crear directorio temporal para la descarga
        temp_dir = tempfile.mkdtemp()
        song_url = f"https://www.deezer.com/track/{id}"
        
        logger.info(f"Iniciando descarga de canción: {song_url}, calidad: {quality}")
        
        # Descargar la canción
        result = deezer.download_trackdee(
            link_track=song_url,
            output_dir=temp_dir,
            quality_download=quality,
            recursive_quality=False,
            recursive_download=False
        )
        
        # Buscar el archivo descargado
        downloaded_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.mp3', '.flac')):
                    downloaded_files.append(os.path.join(root, file))
        
        if not downloaded_files:
            return jsonify({'error': 'No se encontró el archivo descargado'}), 500
        
        # Encontrar el archivo de audio correcto
        audio_file = downloaded_files[0]
        
        # Extraer información del archivo para renombrarlo
        original_filename = os.path.basename(audio_file)
        
        # Intentar extraer artista y título del nombre original si es posible
        # El formato típico es "Artist - Title.ext" o similar
        base_name = os.path.splitext(original_filename)[0]
        
        # Renombrar el archivo con el formato Artista - Título
        # Este es un ejemplo de cómo podría formatearse - el cliente puede necesitar ajustar esto
        # basándose en los metadatos reales disponibles
        sanitized_name = sanitize_filename(base_name)
        new_filename = f"{sanitized_name}.{'flac' if quality == 'FLAC' else 'mp3'}"
        new_filepath = os.path.join(temp_dir, new_filename)
        
        # Si el nombre cambió, renombrar el archivo
        if audio_file != new_filepath:
            os.rename(audio_file, new_filepath)
            audio_file = new_filepath
        
        logger.info(f"Canción descargada exitosamente: {new_filename}")
        
        # Enviar el archivo al cliente
        response = send_file(
            audio_file,
            as_attachment=True,
            download_name=new_filename,
            mimetype='audio/mpeg' if quality != 'FLAC' else 'audio/flac'
        )
        
        # Eliminar el archivo temporal después de enviarlo
        @response.call_after_request
        def remove_file(response):
            try:
                os.remove(audio_file)
                os.rmdir(temp_dir)  # Intentar eliminar directorio si está vacío
            except Exception as e:
                logger.error(f"No se pudo eliminar archivos temporales: {e}")
            
            return response
        
        return response
        
    except Exception as e:
        logger.error(f"Error al descargar canción: {str(e)}")
        return jsonify({'error': f'Error al descargar la canción: {str(e)}'}), 500

@app.route('/download/album/<string:id>', methods=['GET'])
def download_album(id):
    """
    Descarga un álbum completo de Deezer
    Parámetros:
    - id: ID del álbum en Deezer
    - quality: Calidad del audio ('MP3_128', 'MP3_320', 'FLAC') - opcional
    """
    try:
        quality = request.args.get('quality', 'MP3_320')
        allowed_qualities = ['MP3_128', 'MP3_320', 'FLAC']
        
        if quality not in allowed_qualities:
            return jsonify({'error': f'Calidad no válida. Opciones permitidas: {allowed_qualities}'}), 400
        
        # Validar que el ID sea numérico
        if not id.isdigit():
            return jsonify({'error': 'ID de álbum inválido'}), 400
        
        # Crear directorio temporal para la descarga
        temp_dir = tempfile.mkdtemp()
        album_url = f"https://www.deezer.com/album/{id}"
        
        logger.info(f"Iniciando descarga de álbum: {album_url}, calidad: {quality}")
        
        # Descargar el álbum
        result = deezer.download_albumdee(
            link_album=album_url,
            output_dir=temp_dir,
            quality_download=quality,
            recursive_quality=True,
            recursive_download=False
        )
        
        # Buscar todos los archivos de audio descargados
        audio_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.mp3', '.flac')):
                    audio_files.append(os.path.join(root, file))
        
        if not audio_files:
            return jsonify({'error': 'No se encontraron archivos descargados'}), 500
        
        # Crear un archivo ZIP con todos los archivos
        zip_path = os.path.join(temp_dir, f"album_{id}.zip")
        import zipfile
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_path in audio_files:
                # Agregar archivo al ZIP manteniendo la estructura de carpetas relativas
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
        
        logger.info(f"Álbum descargado y empaquetado en ZIP: {len(audio_files)} archivos")
        
        # Enviar el archivo ZIP al cliente
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=f"album_{id}.zip",
            mimetype='application/zip'
        )
        
        # Eliminar archivos temporales después de enviar
        @response.call_after_request
        def remove_files(response):
            try:
                os.remove(zip_path)
                # Eliminar directorio con todos sus contenidos
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.error(f"No se pudieron eliminar archivos temporales: {e}")
            
            return response
        
        return response
        
    except Exception as e:
        logger.error(f"Error al descargar álbum: {str(e)}")
        return jsonify({'error': f'Error al descargar el álbum: {str(e)}'}), 500

@app.route('/download/playlist/<string:id>', methods=['GET'])
def download_playlist(id):
    """
    Descarga una playlist completa de Deezer
    Parámetros:
    - id: ID de la playlist en Deezer
    - quality: Calidad del audio ('MP3_128', 'MP3_320', 'FLAC') - opcional
    """
    try:
        quality = request.args.get('quality', 'MP3_320')
        allowed_qualities = ['MP3_128', 'MP3_320', 'FLAC']
        
        if quality not in allowed_qualities:
            return jsonify({'error': f'Calidad no válida. Opciones permitidas: {allowed_qualities}'}), 400
        
        # Validar que el ID sea numérico
        if not id.isdigit():
            return jsonify({'error': 'ID de playlist inválido'}), 400
        
        # Crear directorio temporal para la descarga
        temp_dir = tempfile.mkdtemp()
        playlist_url = f"https://www.deezer.com/playlist/{id}"
        
        logger.info(f"Iniciando descarga de playlist: {playlist_url}, calidad: {quality}")
        
        # Descargar la playlist
        result = deezer.download_playlistdee(
            link_playlist=playlist_url,
            output_dir=temp_dir,
            quality_download=quality,
            recursive_quality=True,
            recursive_download=False
        )
        
        # Buscar todos los archivos de audio descargados
        audio_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.mp3', '.flac')):
                    audio_files.append(os.path.join(root, file))
        
        if not audio_files:
            return jsonify({'error': 'No se encontraron archivos descargados'}), 500
        
        # Crear un archivo ZIP con todos los archivos
        zip_path = os.path.join(temp_dir, f"playlist_{id}.zip")
        import zipfile
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file_path in audio_files:
                # Agregar archivo al ZIP manteniendo la estructura de carpetas relativas
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
        
        logger.info(f"Playlist descargada y empaquetada en ZIP: {len(audio_files)} archivos")
        
        # Enviar el archivo ZIP al cliente
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=f"playlist_{id}.zip",
            mimetype='application/zip'
        )
        
        # Eliminar archivos temporales después de enviar
        @response.call_after_request
        def remove_files(response):
            try:
                os.remove(zip_path)
                # Eliminar directorio con todos sus contenidos
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.error(f"No se pudieron eliminar archivos temporales: {e}")
            
            return response
        
        return response
        
    except Exception as e:
        logger.error(f"Error al descargar playlist: {str(e)}")
        return jsonify({'error': f'Error al descargar la playlist: {str(e)}'}), 500

@app.route('/', methods=['GET'])
def index():
    """Endpoint raíz para verificar que la API está funcionando"""
    return jsonify({
        'message': 'API de descarga de música de Deezer',
        'endpoints': {
            '/download/song/<id>': 'Descargar canción individual',
            '/download/album/<id>': 'Descargar álbum completo',
            '/download/playlist/<id>': 'Descargar playlist completa'
        },
        'parameters': {
            'quality': 'MP3_128, MP3_320, FLAC (solo para Deezer Premium)'
        }
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Error interno del servidor'}), 500

if __name__ == '__main__':
    # Ejecutar la aplicación
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)