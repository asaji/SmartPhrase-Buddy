"""Extract candidate SmartPhrases from an Epic "print SmartPhrases" PDF export.

Nothing here persists or logs. The view holds the bytes in memory, calls
``parse_pdf`` and returns the result to the browser. Every segment is an
unapproved import draft: the caller still assigns title/Epic name/type/tags and
the header boundary, and approves each phrase through the normal review flow.
The split is best effort; names stay editable and segments can be merged in the
UI. Ambiguous clinical text, codes and Epic tokens are never rewritten.
"""
import io, re, html as _html
from pypdf import PdfReader

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_SEGMENTS = 2000

# An Epic SmartPhrase name: uppercase letters/digits, no spaces, on its own line.
NAME_RE = re.compile(r'[A-Z][A-Z0-9]{3,}')
AGE_RE = re.compile(r'\b\d{1,3}[\s-]*(?:year|yr)s?[\s-]*old\b', re.I)
TOKEN_RE = re.compile(r'@[^@\s<>]+@|\{[^{}]*\}|\*{3,}|\[%[^%\]]+%\]')
BRACKET_RE = re.compile(r'\[[^\[\]\n]{1,60}\]')
LETTERHEAD_RE = re.compile(
    r'SMG UROLOGY|FIRST HILL|Saji,\s*MD|\b\d{3}[.\s]\d{3}[.\s]\d{4}\b|^\s*SWEDISH\s*$',
    re.I,
)
DISCLAIMER_RE = re.compile(
    r'Disclaimer to patients|primary purpose of this note|Review of prior external note',
    re.I,
)
BULLET_RE = re.compile(r'^\s*(?:[-*•·▪]|\d+[.)])\s+')


def extract_text(data: bytes) -> str:
    """Return the concatenated selectable text of a PDF, or raise ValueError."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt('')
            except Exception:
                raise ValueError('The PDF is password protected. Remove the password and re-export.')
        pages = [(page.extract_text() or '') for page in reader.pages]
    except ValueError:
        raise
    except Exception:
        raise ValueError('That file could not be read as a PDF.')
    if not any(p.strip() for p in pages):
        raise ValueError(
            'No selectable text found. This looks like a scanned image PDF; '
            'use an Epic export that produces real text.'
        )
    return '\n'.join(pages)


def split_segments(text: str):
    """Split extracted text into ``[{'name': str|None, 'text': str}]``.

    A boundary is a line that is only an uppercase token and is preceded by a
    blank line (the spacing Epic prints before each SmartPhrase name). Text
    before the first boundary becomes an unnamed segment.
    """
    lines = text.splitlines()
    raw = []
    current = {'name': None, 'lines': []}
    for i, line in enumerate(lines):
        stripped = line.strip()
        prev_blank = (i == 0) or (not lines[i - 1].strip())
        if prev_blank and NAME_RE.fullmatch(stripped):
            if current['name'] is not None or '\n'.join(current['lines']).strip():
                raw.append(current)
            current = {'name': stripped, 'lines': []}
        else:
            current['lines'].append(line)
    if current['name'] is not None or '\n'.join(current['lines']).strip():
        raw.append(current)

    segments = []
    for seg in raw:
        body = _collapse('\n'.join(line.rstrip() for line in seg['lines']))
        if not body and seg['name'] is None:
            continue
        segments.append({'name': seg['name'], 'text': body})
    return segments


def _collapse(text: str) -> str:
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def text_to_html(text: str) -> str:
    """Conservative plain-text -> HTML.

    Each non-blank line becomes its own paragraph (Epic prints one logical line
    per line, and one <p> per line lets the reviewer split the Epic header at a
    real node boundary). Consecutive bullet lines collapse into a list. No
    headings or emphasis are inferred; the reviewer formats in the editor.
    """
    out = []
    bucket = []

    def flush():
        if bucket:
            out.append('<ul>' + ''.join(
                '<li>' + _html.escape(BULLET_RE.sub('', r)) + '</li>' for r in bucket
            ) + '</ul>')
            bucket.clear()

    for line in text.strip().splitlines():
        if not line.strip():
            flush()
            continue
        if BULLET_RE.match(line):
            bucket.append(line)
        else:
            flush()
            out.append('<p>' + _html.escape(line) + '</p>')
    flush()
    return ''.join(out) or '<p></p>'


def flags_for(name, text: str):
    flags = []
    lines = text.splitlines()
    if any(LETTERHEAD_RE.search(line) for line in lines):
        flags.append('Contains letterhead lines (provider name, clinic, phone). Remove them before saving.')
    if DISCLAIMER_RE.search(text):
        flags.append('Contains a patient-facing disclaimer / boilerplate block. Trim to the reusable content.')
    if AGE_RE.search(text):
        flags.append('Contains a fixed patient age. Review before saving reusable text.')
    if not TOKEN_RE.search(text):
        flags.append('No Epic tokens (@…@, {…}, ***) detected. Confirm this is the complete phrase.')
    if BRACKET_RE.search(text):
        flags.append('Contains bracket placeholders ([ … ]). Kept verbatim; confirm they are intended.')
    if name is None:
        flags.append('No SmartPhrase name detected above this text. Assign the Epic name during review.')
    return flags


def parse_pdf(data: bytes):
    """Bytes -> list of unapproved segment drafts. Raises ValueError on bad input."""
    if len(data) > MAX_PDF_BYTES:
        raise ValueError('The PDF exceeds the 25 MB import limit.')
    segments = split_segments(extract_text(data))
    if not segments:
        raise ValueError('No SmartPhrase content was found in that PDF.')
    if len(segments) > MAX_SEGMENTS:
        raise ValueError('That PDF contains more than %d segments; split it and retry.' % MAX_SEGMENTS)
    return [
        {
            'name': seg['name'] or '',
            'text': seg['text'],
            'html': text_to_html(seg['text']),
            'chars': len(seg['text']),
            'flags': flags_for(seg['name'], seg['text']),
        }
        for seg in segments
    ]
