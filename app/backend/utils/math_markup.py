"""Recognize explicit TeX delimiters without guessing mathematics in ordinary prose."""
import re


def canonical_delimiters(text):
    # Preserve content; all command validation happens in worksheet.rich_text_to_tex.
    for opening, closing in ((r'\[', r'\]'), (r'\(', r'\)')):
        text = re.sub(re.escape(opening) + r'(.*?)' + re.escape(closing),
                      lambda m: '$' + m.group(1).strip() + '$', text, flags=re.S)
    text = re.sub(r'\$\$(.+?)\$\$', lambda m: '$' + m.group(1).strip() + '$', text, flags=re.S)
    return text


def math_typography(part):
    # Unicode minus and relations are typographical equivalents, never recompute values.
    for before, after in [('−','-'),('≤',r'\leq '),('≥',r'\geq '),('≠',r'\ne '),('×',r'\times '),('·',r'\cdot ')]:
        part = part.replace(before, after)
    # Russian decimals use a punctuation-free comma; an existing {,} stays unchanged.
    part = re.sub(r'(?<=\d),(?=\d)', '{,}', part)
    return part
