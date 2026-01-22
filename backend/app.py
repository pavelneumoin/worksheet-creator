from flask import Flask, request, jsonify, send_from_directory, send_file
import os
import uuid
# from utils.yandex import ocr_image, generate_worksheet_latex
from utils.latex import compile_latex

from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/process', methods=['POST'])
def process_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # 2. Process with GigaChat (Multimodal)
        from utils.gigachat_client import process_image_with_gigachat
        task_count = request.form.get('task_count', 3)
        topic = request.form.get('topic', 'Рабочий лист')
        model = request.form.get('model', 'GigaChat-Max')
        teacher_name = request.form.get('teacher_name', '')
        
        # This single call handles both OCR and LaTeX generation
        latex_content = process_image_with_gigachat(filepath, task_count=task_count, model=model)

        # 4. Compile PDF
        pdf_filename, error = compile_latex(latex_content, topic=topic, filename_base=f"worksheet_{uuid.uuid4()}", teacher_name=teacher_name)

        if pdf_filename:
            return jsonify({
                'message': 'Worksheet generated successfully',
                'original_text': latex_content,  # Передаём реальный LaTeX для генерации Варианта 2
                'pdf_url': f"/generated/{pdf_filename}",
                'model': model,  # Передаём модель для Варианта 2
                'latex_code': latex_content  # LaTeX код для отображения в модальном окне
            }), 200
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
    
    if not original_text:
        return jsonify({'error': 'Original text is required'}), 400
        
    # Generate similar tasks
    latex_content = generate_similar_worksheet(original_text, task_count=task_count, model=model)
    
    # Compile with topic "Вариант 2"
    pdf_filename, error = compile_latex(latex_content, topic=f"{topic} (Вариант 2)", filename_base=f"variant2_{uuid.uuid4()}", teacher_name=teacher_name)
    
    if pdf_filename:
        return jsonify({
            'message': 'Variant 2 generated successfully',
            'pdf_url': f"/generated/{pdf_filename}",
            'latex_code': latex_content  # LaTeX код для отображения в модальном окне
        }), 200
    else:
        return jsonify({'error': f"PDF Generation failed: {error}"}), 500

@app.route('/generated/<path:filename>')
def serve_generated(filename):
    return send_from_directory('static/generated', filename)

if __name__ == '__main__':
    app.run(debug=True, port=3000)
