from flask import Flask, request, jsonify, send_from_directory, send_file
import os
import uuid
from utils.yandex import ocr_image, generate_worksheet_latex
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

        # 2. OCR (Yandex Vision)
        text_content = ocr_image(filepath)


        # 3. Generate LaTeX Content (Stub/Real)
        task_count = request.form.get('task_count', 3)
        latex_content = generate_worksheet_latex(text_content, task_count=task_count)

        # 4. Compile PDF
        pdf_filename, error = compile_latex(latex_content, filename_base=f"worksheet_{uuid.uuid4()}")

        if pdf_filename:
            return jsonify({
                'message': 'Worksheet generated successfully',
                'original_text': text_content,
                'pdf_url': f"/generated/{pdf_filename}"
            }), 200
        else:
            return jsonify({'error': f"PDF Generation failed: {error}"}), 500

@app.route('/generated/<path:filename>')
def serve_generated(filename):
    return send_from_directory('static/generated', filename)

if __name__ == '__main__':
    app.run(debug=True, port=3000)
