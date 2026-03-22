import tempfile
import shutil
import os
import logging
from flask import Flask, render_template, request, jsonify
from transmission_rpc import Client
from py_rutracker import RuTrackerClient

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === Переменные окружения ===
RUTRACKER_LOGIN = os.getenv('RUTRACKER_LOGIN')
RUTRACKER_PASSWORD = os.getenv('RUTRACKER_PASSWORD')

TRANSMISSION_HOST = os.getenv('TRANSMISSION_HOST', 'localhost')
TRANSMISSION_PORT = int(os.getenv('TRANSMISSION_PORT', 9091))
TRANSMISSION_USER = os.getenv('TRANSMISSION_USER')
TRANSMISSION_PASSWORD = os.getenv('TRANSMISSION_PASSWORD')

# Проверка обязательных переменных
if not RUTRACKER_LOGIN or not RUTRACKER_PASSWORD:
    logger.error("RUTRACKER_LOGIN and RUTRACKER_PASSWORD must be set")
    raise RuntimeError("Missing RuTracker credentials")

# === Инициализация Transmission ===
transmission_client = None
try:
    transmission_client = Client(
        host=TRANSMISSION_HOST,
        port=TRANSMISSION_PORT,
        username=TRANSMISSION_USER,
        password=TRANSMISSION_PASSWORD
    )
    # Проверяем соединение (без использования устаревшего атрибута)
    transmission_client.get_session()
    logger.info(f"Connected to Transmission at {TRANSMISSION_HOST}:{TRANSMISSION_PORT}")
except Exception as e:
    logger.error(f"Failed to connect to Transmission: {e}")

# === Инициализация RuTracker с поддержкой прокси ===
rutracker_client = None
try:
    rutracker_client = RuTrackerClient(
        login=RUTRACKER_LOGIN,
        password=RUTRACKER_PASSWORD
    )
    logger.info("RuTracker client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize RuTracker client: {e}")
    # Не прерываем работу, но поиск будет недоступен
    rutracker_client = None

# === Маршруты ===
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    status = {
        'status': 'healthy' if rutracker_client else 'degraded',
        'transmission': transmission_client is not None,
        'rutracker': rutracker_client is not None
    }
    return jsonify(status)

@app.route('/search')
def search():
    if not rutracker_client:
        return jsonify({'error': 'RuTracker client not available'}), 503

    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Empty search query'}), 400

    try:
        results = rutracker_client.search_all_pages(query)
        logger.info(f"Search for '{query}' returned {len(results)} results")

        formatted = []
        for item in results[:50]:
            # Пытаемся получить поля, пробуем разные варианты
            seeds = getattr(item, 'seeders', getattr(item, 'seeds', 0))
            leeches = getattr(item, 'leechers', getattr(item, 'leeches', 0))
            # Размер: если строка, оставляем как есть; если число, форматируем позже в шаблоне
            size = getattr(item, 'size', 0)
            # Если size строка типа "1.5 GB", оставляем; если int, можно отдать как есть и форматировать в JS
            formatted.append({
                'topic_id': item.topic_id,
                'title': item.title,
                'size': size,
                'seeds': seeds,
                'leeches': leeches,
                'download_url': f"/download/{item.topic_id}"
            })
        return jsonify(formatted)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500




@app.route('/download/<int:topic_id>', methods=['POST'])
def download(topic_id):
    if not transmission_client:
        return jsonify({'error': 'Transmission client not available'}), 503
    if not rutracker_client:
        return jsonify({'error': 'RuTracker client not available'}), 503

    try:
        # Получаем содержимое .torrent файла в виде байтов
        torrent_bytes = rutracker_client.download(topic_id)

        # Добавляем торрент в Transmission
        result = transmission_client.add_torrent(torrent_bytes)
        logger.info(f"Torrent added: topic_id={topic_id}, name={result.name}")

        return jsonify({
            'success': True,
            'message': f'Torrent "{result.name}" добавлен в Transmission',
            'torrent_id': result.id
        })
    except Exception as e:
        logger.error(f"Download error for topic_id {topic_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/status')
def status():
    if not transmission_client:
        return jsonify({'error': 'Transmission client not available'}), 503

    try:
        torrents = transmission_client.get_torrents()
        status_list = []
        for t in torrents:
            status_list.append({
                'id': t.id,
                'name': t.name,
                'progress': t.progress,
                'status': str(t.status),
                'rate_download': t.rate_download,
                'rate_upload': t.rate_upload,
                'size': t.total_size
            })
        return jsonify(status_list)
    except Exception as e:
        logger.error(f"Status error: {e}")
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
