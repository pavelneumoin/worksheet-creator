import os
import subprocess
import shutil

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '../templates/default_worksheet.tex')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '../static/generated')

os.makedirs(OUTPUT_DIR, exist_ok=True)

def compile_latex(content, topic="Рабочий лист", filename_base="worksheet"):
    """
    Injects content into the LaTeX template and compiles it to PDF.
    Returns the path to the generated PDF.
    """
    # 1. Read Template
    try:
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        return None, "Template file not found."

    # 2. Inject Content
    # Simple string replacement for now. 
    # In a real app, might use Jinja2 for latex templates.
    latex_source = template.replace('VAR_CONTENT', content)
    # Use provided topic
    latex_source = latex_source.replace('VAR_TOPIC', topic)

    # 3. Write .tex file
    tex_filename = f"{filename_base}.tex"
    tex_path = os.path.join(OUTPUT_DIR, tex_filename)
    
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(latex_source)

    # 4. Compile with pdflatex
    # -interaction=nonstopmode prevents hanging on errors
    # -output-directory specifies where to put the pdf
    try:
        # Run pdflatex without check=True to handle potential non-fatal warnings/errors
        result = subprocess.run(
            ['pdflatex', '-disable-installer', '-interaction=nonstopmode', '-output-directory', OUTPUT_DIR, tex_path],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Verify PDF creation regardless of return code
        pdf_filename = f"{filename_base}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        
        if os.path.exists(pdf_path):
             return pdf_filename, None
             
        # If PDF missing and we had an error code, report it
        if result.returncode != 0:
             return None, f"LaTeX Compilation Error: {result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'Unknown error'}"
             
    except FileNotFoundError:
        return None, "pdflatex command not found. Please ensure MiKTeX or TeX Live is installed and in PATH."
    except Exception as e:
         return None, f"Unexpected error during compilation: {str(e)}"
         
    return None, "PDF file was not created (Unknown reason)."

    # PDF check moved inside try/except block
    return None, "PDF generation failed."
