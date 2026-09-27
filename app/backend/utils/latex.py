"""Local demo compilation; these TeX restrictions are not a production sandbox."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '../templates/default_worksheet.tex')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '../static/generated')
os.makedirs(OUTPUT_DIR, exist_ok=True)
USE_CLOUD_LATEX = False  # No document uploads, including when local TeX is absent.
MAX_CONTENT_BYTES = 64 * 1024

_SAFE_COMMANDS = set(r'''
TaskBox WriteField newpage clearpage pagebreak section subsection paragraph
begin end text textbf textit textnormal textrm textsf texttt emph underline
mathrm mathbf mathit mathsf mathtt mathcal mathbb operatorname
frac dfrac tfrac sqrt binom dbinom tbinom left right middle overline bar vec
overrightarrow overleftrightarrow hat widehat tilde widetilde dot ddot
cdot times div pm mp centerdot ast star circ bullet
le leq ge geq ne neq approx sim simeq equiv propto ll gg
in notin ni subset subseteq supset supseteq cup cap emptyset varnothing
forall exists nexists neg land lor implies iff to rightarrow leftarrow
leftrightarrow Rightarrow Leftarrow Leftrightarrow mapsto longrightarrow
infty partial nabla sum prod int iint iiint oint lim limits nolimits
sin cos tan cot tg ctg arcsin arccos arctan sinh cosh tanh log ln exp min max
det gcd mod bmod pmod lvert rvert lVert rVert vert Vert
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota
kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi
varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
quad qquad hspace vspace hfill smallskip medskip bigskip newline linebreak prime
hline cline multicolumn item noindent centering raggedright
displaystyle textstyle scriptstyle scriptscriptstyle
small normalsize large Large footnotesize scriptsize tiny
ldots cdots vdots ddots dots underbrace overbrace underset overset
textbackslash textasciitilde textasciicircum textdegree degree
color textcolor boxed fbox phantom hphantom vphantom rule
'''.split())
_SAFE_ENVIRONMENTS = {
    'tabular', 'tabular*', 'array', 'aligned', 'alignedat', 'align', 'align*',
    'gather', 'gather*', 'gathered', 'equation', 'equation*', 'split',
    'cases', 'matrix', 'pmatrix', 'bmatrix', 'Bmatrix', 'vmatrix', 'Vmatrix',
    'enumerate', 'itemize', 'description', 'center', 'flushleft',
}
_ESCAPES = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
            '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
            '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}


def get_latex_compiler():
    """Find XeLaTeX/pdfLaTeX, including a default Windows MiKTeX install."""
    configured = os.environ.get('LATEX_COMPILER', '').strip().strip('"')
    if configured:
        candidate = shutil.which(configured)
        if not candidate and Path(configured).is_file():
            candidate = str(Path(configured).resolve())
        return candidate
    for engine in ('xelatex', 'pdflatex'):
        candidate = shutil.which(engine)
        if candidate:
            return candidate
    if os.name == 'nt':
        roots = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/MiKTeX/miktex/bin/x64',
                 Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'MiKTeX/miktex/bin/x64']
        for root in roots:
            for engine in ('xelatex.exe', 'pdflatex.exe'):
                candidate = root / engine
                if candidate.is_file():
                    return str(candidate.resolve())
    return None


def _timeout_seconds():
    try:
        return max(5, min(int(os.environ.get('LATEX_TIMEOUT_SECONDS', '60')), 120))
    except ValueError:
        return 60


def _safe_filename(filename_base):
    return isinstance(filename_base, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', filename_base))


def _escape_header(value):
    return ''.join(_ESCAPES.get(char, char) for char in ' '.join(value.split()))


def _validate_content(content):
    if not isinstance(content, str) or not content.strip():
        return 'Добавьте задания в редактор LaTeX.'
    if len(content.encode('utf-8')) > MAX_CONTENT_BYTES:
        return 'Слишком большой документ: максимум 64 КБ LaTeX.'
    if '^^' in content or '\x00' in content:
        return 'Недопустимая управляющая последовательность LaTeX.'
    # Definitions, IO, packages, engine primitives are not editable worksheet content.
    for command in re.findall(r'\\([A-Za-z@]+)', content):
        if command not in _SAFE_COMMANDS:
            return f'Команда \\{command} не поддерживается в локальном редакторе. Используйте команды задач и формул.'
    for environment in re.findall(r'\\(?:begin|end)\s*\{([^{}]+)\}', content):
        if environment not in _SAFE_ENVIRONMENTS:
            return f'Окружение {environment} не поддерживается в локальном редакторе.'
    for height in re.findall(r'\\WriteField\s*\{([^{}]+)\}', content):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*mm\s*', height)
        if not match or not 5 <= float(match.group(1)) <= 150:
            return 'Высота WriteField должна быть от 5mm до 150mm.'
    return None


def _remove_output(filename_base):
    if _safe_filename(filename_base):
        for extension in ('.pdf', '.tex', '.log'):
            Path(OUTPUT_DIR, filename_base + extension).unlink(missing_ok=True)


def _diagnostic(output):
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('!') or re.search(r'\.tex:\d+:', line):
            return '\n'.join(lines[index:index + 6])[:900]
    return '\n'.join(lines[-10:])[-900:] or 'Компилятор не сообщил подробностей.'


def compile_latex_local(latex_source, filename_base):
    """Compile trusted template + validated body in a fresh local directory."""
    if not _safe_filename(filename_base):
        return None, 'Недопустимое имя выходного файла.'
    compiler = get_latex_compiler()
    if not compiler:
        return None, 'Локальный LaTeX не найден. Установите MiKTeX/TeX Live или задайте LATEX_COMPILER. Данные никуда не отправлены.'
    _remove_output(filename_base)
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    timeout = _timeout_seconds()
    try:
        with tempfile.TemporaryDirectory(prefix='listok-tex-') as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / 'document.tex').write_text(latex_source, encoding='utf-8')
            command = [compiler, '-interaction=nonstopmode', '-halt-on-error',
                       '-no-shell-escape', '-file-line-error']
            if 'miktex' in compiler.lower():
                command.append('--disable-installer')
            command.append('document.tex')
            environment = os.environ.copy()
            environment.update({'openin_any': 'p', 'openout_any': 'p', 'shell_escape': 'f'})
            environment['PATH'] = str(Path(compiler).parent) + os.pathsep + environment.get('PATH', '')
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            result = subprocess.run(command, cwd=temp_dir, env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False, **options)
            output = result.stdout.decode('utf-8', errors='replace')
            (output_dir / f'{filename_base}.tex').write_text(latex_source, encoding='utf-8')
            (output_dir / f'{filename_base}.log').write_text(output, encoding='utf-8')
            if re.search(r'Missing character\s*:', output, re.IGNORECASE):
                return None, ('Компилятор не смог отобразить символы: PDF не выдан, чтобы не потерять '
                              'единицы измерения или условия. Кириллические единицы внутри формул '
                              'оформляйте через \\text{...}; проверьте остальные символы и шрифт.')
            if result.returncode != 0:
                return None, 'Не удалось собрать PDF. ' + _diagnostic(output)
            pdf_path = temp_path / 'document.pdf'
            if not pdf_path.is_file() or pdf_path.stat().st_size < 100:
                return None, 'Компилятор завершился без PDF.'
            with pdf_path.open('rb') as file:
                if file.read(5) != b'%PDF-':
                    return None, 'Компилятор не создал корректный PDF.'
            pdf_filename = f'{filename_base}.pdf'
            shutil.copyfile(pdf_path, output_dir / pdf_filename)
            return pdf_filename, None
    except subprocess.TimeoutExpired:
        return None, f'Сборка PDF превысила {timeout} секунд. Упростите документ и повторите.'
    except OSError as error:
        return None, f'Не удалось запустить локальную сборку PDF: {error}'


def compile_latex_cloud(latex_source, filename_base):
    """Compatibility entrypoint; cloud submission is intentionally disabled."""
    return None, 'Облачная сборка отключена. Используйте локальный LaTeX; материалы не отправлены сторонним сервисам.'


def _compile_single_doc(content, topic, filename_base, teacher_name, layout='1col'):
    try:
        template = Path(TEMPLATE_PATH).read_text(encoding='utf-8')
    except OSError:
        return None, 'Не найден шаблон рабочего листа.'
    if layout == '2col':
        content = '\\begin{multicols}{2}\n' + content + '\n\\end{multicols}'
    teacher_line = ''
    if teacher_name.strip():
        teacher_line = r'\par\vspace{1mm}{\small\color{textgray} Учитель: ' + _escape_header(teacher_name) + '}'
    replacements = {'CONTENT': content, 'TOPIC': _escape_header(topic), 'TEACHER': teacher_line}
    latex_source = re.sub(r'PLACEHOLDER:(CONTENT|TOPIC|TEACHER)',
                          lambda match: replacements[match.group(1)], template)
    return compile_latex_local(latex_source, filename_base)


def extract_keys(content):
    """Split at the first answers heading, preserving all subsequent sections."""
    match = re.search(r'\\section\s*\*?\s*\{\s*Ответы(?:[^{}]*)\}', content, re.IGNORECASE)
    if not match:
        return content, ''
    tasks = re.sub(r'(?:\\(?:newpage|clearpage)\s*)+$', '', content[:match.start()].strip()).strip()
    return tasks, content[match.start():].strip()


def compile_latex(content, topic='Рабочий лист', filename_base='worksheet', teacher_name='', layout='1col'):
    """Return (worksheet_pdf, answers_pdf, error); never silently omit answers."""
    if not _safe_filename(filename_base):
        return None, None, 'Недопустимое имя выходного файла.'
    if not isinstance(topic, str) or not isinstance(teacher_name, str):
        return None, None, 'Тема и имя учителя должны быть текстом.'
    if len(topic) > 240 or len(teacher_name) > 160:
        return None, None, 'Сократите тему или имя учителя.'
    if layout not in ('1col', '2col'):
        return None, None, 'Выберите одну или две колонки.'
    error = _validate_content(content)
    if error:
        return None, None, error
    tasks, keys = extract_keys(content)
    if not tasks:
        return None, None, 'Перед ответами должны быть задания.'
    main_pdf, error = _compile_single_doc(tasks, topic, filename_base, teacher_name, layout)
    if error:
        return None, None, error
    keys_pdf = None
    if keys:
        keys_pdf, error = _compile_single_doc(keys, topic + ' — ответы', filename_base + '_keys', teacher_name)
        if error:
            _remove_output(filename_base)
            _remove_output(filename_base + '_keys')
            return None, None, 'Ошибка в документе с ответами. ' + error
    return main_pdf, keys_pdf, None
