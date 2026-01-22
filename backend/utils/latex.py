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
            ['pdflatex', '-disable-installer', '-interaction=nonstopmode', '-output-directory', OUTPUT_DIR, tex_path],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        pdf_filename = f"{filename_base}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        
        if os.path.exists(pdf_path):
            return pdf_filename, None
             
        if result.returncode != 0:
            return None, f"LaTeX Compilation Error: {result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'Unknown error'}"
             
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
        # Use latexonline.cc API
        # POST the tex file content
        response = requests.post(
            'https://latexonline.cc/compile',
            files={'file': (tex_filename, latex_source, 'application/x-tex')},
            data={'command': 'pdflatex'},
            timeout=120
        )
        
        if response.status_code == 200 and response.headers.get('content-type', '').startswith('application/pdf'):
            pdf_filename = f"{filename_base}.pdf"
            pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(response.content)
            
            return pdf_filename, None
        else:
            # Try alternative API: latex.ytotech.com
            response2 = requests.post(
                'https://latex.ytotech.com/builds/sync',
                json={
                    'compiler': 'pdflatex',
                    'resources': [
                        {'main': True, 'content': latex_source}
                    ]
                },
                headers={'Content-Type': 'application/json'},
                timeout=120
            )
            
            if response2.status_code == 200:
                pdf_filename = f"{filename_base}.pdf"
                pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
                
                with open(pdf_path, 'wb') as f:
                    f.write(response2.content)
                
                return pdf_filename, None
            else:
                return None, f"Cloud LaTeX API error: {response.status_code} - {response.text[:200]}"
                
    except requests.Timeout:
        return None, "Cloud LaTeX API timeout. Try again."
    except Exception as e:
        return None, f"Cloud compilation error: {str(e)}"


def compile_latex(content, topic="Рабочий лист", filename_base="worksheet"):
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
    latex_source = template.replace('VAR_CONTENT', content)
    latex_source = latex_source.replace('VAR_TOPIC', topic)

    # 3. Compile using appropriate method
    if USE_CLOUD_LATEX:
        return compile_latex_cloud(latex_source, filename_base)
    else:
        # Try local first, fall back to cloud if pdflatex not found
        result = compile_latex_local(latex_source, filename_base)
        if result[1] and "pdflatex not found" in result[1]:
            # Auto-fallback to cloud
            return compile_latex_cloud(latex_source, filename_base)
        return result
