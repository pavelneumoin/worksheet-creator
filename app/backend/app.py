from flask import Flask, request, jsonify, send_from_directory, send_file
import os
import uuid
# from utils.yandex import ocr_image, generate_worksheet_latex
from utils.latex import compile_latex
from utils.db import init_db, save_worksheet, get_history

from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

# Initialize database
init_db()

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/process', methods=['POST'])
def process_file():
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': 'No files selected'}), 400

    filepaths = []
    for file in files:
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            filepaths.append(filepath)

    if not filepaths:
        return jsonify({'error': 'Failed to save files'}), 500

    # 2. Process with GigaChat (Multimodal)
    from utils.gigachat_client import process_image_with_gigachat
    task_count = request.form.get('task_count', 3)
    topic = request.form.get('topic', 'Рабочий лист')
    model = request.form.get('model', 'GigaChat-Max')
    teacher_name = request.form.get('teacher_name', '')
    
    # This single call handles both OCR and LaTeX generation
    latex_content = process_image_with_gigachat(filepaths, task_count=task_count, model=model)

    # 4. Return LaTeX code (Do not compile yet)
    return jsonify({
        'message': 'Worksheet parsed successfully',
        'latex_code': latex_content,
        'model': model
    }), 200

@app.route('/api/compile', methods=['POST'])
def compile_code():
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400
        
    latex_content = data.get('latex_code')
    topic = data.get('topic', 'Рабочий лист')
    teacher_name = data.get('teacher_name', '')
    is_variant2 = data.get('is_variant2', False)
    layout = data.get('layout', '1col')
    
    if not latex_content:
        return jsonify({'error': 'No LaTeX code provided'}), 400
        
    base_name = f"variant2_{uuid.uuid4()}" if is_variant2 else f"worksheet_{uuid.uuid4()}"
    topic_str = f"{topic} (Вариант 2)" if is_variant2 else topic
    
    pdf_filename, keys_filename, error = compile_latex(latex_content, topic=topic_str, filename_base=base_name, teacher_name=teacher_name, layout=layout)

    if pdf_filename:
        pdf_url = f"/generated/{pdf_filename}"
        keys_url = f"/generated/{keys_filename}" if keys_filename else None
        
        # Save to history
        try:
            save_worksheet(topic_str, teacher_name, latex_content, pdf_url, keys_url)
        except Exception as e:
            print(f"Failed to save to history: {e}")

        response_data = {
            'message': 'PDF generated successfully',
            'pdf_url': pdf_url
        }
        if keys_url:
            response_data['keys_url'] = keys_url
            
        return jsonify(response_data), 200
    else:
        return jsonify({'error': f"PDF Generation failed: {error}"}), 500

@app.route('/api/generate_similar', methods=['POST'])
def generate_similar():
    from utils.gigachat_client import generate_similar_worksheet
    
    original_text = request.form.get('original_text')
    task_count = request.form.get('task_count', 3)
    model = request.form.get('model', 'GigaChat-Max')
    topic = request.form.get('topic', 'Рабочий лист')
    teacher_name = request.form.get('teacher_name', '')
    difficulty = request.form.get('difficulty', 'same')
    
    if not original_text:
        return jsonify({'error': 'Original text is required'}), 400
        
    # Generate similar tasks
    latex_content = generate_similar_worksheet(original_text, task_count=task_count, model=model, difficulty=difficulty)
    
    return jsonify({
        'message': 'Variant 2 text generated successfully',
        'latex_code': latex_content
    }), 200

@app.route('/api/history', methods=['GET'])
def history():
    limit = request.args.get('limit', 50, type=int)
    try:
        data = get_history(limit=limit)
        return jsonify({'history': data}), 200
    except Exception as e:
        return jsonify({'error': f"Failed to fetch history: {e}"}), 500

@app.route('/generated/<path:filename>')
def serve_generated(filename):
    return send_from_directory('static/generated', filename)

if __name__ == '__main__':
    app.run(debug=True, port=3000)
