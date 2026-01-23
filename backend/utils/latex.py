import os
import requests
import subprocess
import shutil

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '../templates/default_worksheet.tex')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '../static/generated')

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Check if we're in production (Render) or local development
USE_CLOUD_LATEX = os.environ.get('USE_CLOUD_LATEX', 'false').lower() == 'true'

def compile_latex_local(latex_source, filename_base):
    """Compile LaTeX using local pdflatex (for development)."""
    tex_filename = f"{filename_base}.tex"
    tex_path = os.path.join(OUTPUT_DIR, tex_filename)
    
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(latex_source)

    try:
        result = subprocess.run(
            ['pdflatex', '-interaction=nonstopmode', '-output-directory', OUTPUT_DIR, tex_path],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60  # 60 second timeout to prevent hanging
        )
        
        pdf_filename = f"{filename_base}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        
        if os.path.exists(pdf_path):
            return pdf_filename, None
             
        if result.returncode != 0:
            return None, f"LaTeX Compilation Error: {result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'Unknown error'}"
             
    except subprocess.TimeoutExpired:
        return None, "LaTeX compilation timeout (60s). Document may be too complex."
    except FileNotFoundError:
        return None, "pdflatex not found. Set USE_CLOUD_LATEX=true for cloud compilation."
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"
         
    return None, "PDF was not created."


def compile_latex_cloud(latex_source, filename_base):
    """Compile LaTeX using cloud API (for production without TeX installed)."""
    
    # Save .tex file first
    tex_filename = f"{filename_base}.tex"
    tex_path = os.path.join(OUTPUT_DIR, tex_filename)
    
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(latex_source)
    
    try:
        # Option 1: Use texlive.net (official TeX Live online compiler)
        response = requests.post(
            'https://texlive.net/cgi-bin/latexcgi',
            data={
                'filecontents[]': latex_source,
                'filename[]': 'document.tex',
                'engine': 'pdflatex',
                'return': 'pdf'
            },
            timeout=120
        )
        
        if response.status_code == 200 and (
            response.headers.get('content-type', '').startswith('application/pdf') or
            len(response.content) > 1000 and response.content[:4] == b'%PDF'
        ):
            pdf_filename = f"{filename_base}.pdf"
            pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(response.content)
            
            return pdf_filename, None
        
        # Option 2: Try latex.ytotech.com with correct format
        response2 = requests.post(
            'https://latex.ytotech.com/builds/sync',
            json={
                'compiler': 'pdflatex',
                'resources': [
                    {
                        'main': True,
                        'path': 'main.tex',
                        'content': latex_source
                    }
                ]
            },
            headers={'Content-Type': 'application/json'},
            timeout=120
        )
        
        if response2.status_code == 200 and len(response2.content) > 100:
            pdf_filename = f"{filename_base}.pdf"
            pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(response2.content)
            
            return pdf_filename, None
        
        # Option 3: Try latexonline.cc with GET method (URL-based)
        import urllib.parse
        import base64
        
        # For short documents, we can use URL encoding
        encoded_source = base64.b64encode(latex_source.encode('utf-8')).decode('utf-8')
        
        # If all APIs fail, return meaningful error
        error_details = f"API 1: {response.status_code}, API 2: {response2.status_code}"
        return None, f"Cloud LaTeX compilation failed. {error_details}. Consider installing pdflatex on the server."
                
    except requests.Timeout:
        return None, "Cloud LaTeX API timeout. Try again."
    except Exception as e:
        return None, f"Cloud compilation error: {str(e)}"


def compile_latex(content, topic="Рабочий лист", filename_base="worksheet", teacher_name=""):
    """
    Injects content into the LaTeX template and compiles it to PDF.
    Uses local pdflatex or cloud API based on USE_CLOUD_LATEX env var.
    """
    # 1. Read Template
    try:
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        return None, "Template file not found."

    # 2. Inject Content
    latex_source = template.replace('PLACEHOLDER:CONTENT', content)
    latex_source = latex_source.replace('PLACEHOLDER:TOPIC', topic)
    
    # Generate teacher line only if teacher name is provided
    if teacher_name and teacher_name.strip():
        teacher_line = f"\\par\\vspace{{1mm}}{{\\small\\color{{textgray!70}} Учитель: {teacher_name}}}"
    else:
        teacher_line = ""
    latex_source = latex_source.replace('PLACEHOLDER:TEACHER', teacher_line)

    # 3. Compile using appropriate method
    if USE_CLOUD_LATEX:
        return compile_latex_cloud(latex_source, filename_base)
    else:
        # Try local first, fall back to cloud if pdflatex not found
        result = compile_latex_local(latex_source, filename_base)
        if result[1] and ("pdflatex" in result[1].lower() and "not found" in result[1].lower()):
            # Auto-fallback to cloud
            return compile_latex_cloud(latex_source, filename_base)
        return result

