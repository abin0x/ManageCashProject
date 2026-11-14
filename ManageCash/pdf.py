"""PDF statement export for ManageCash (built with ReportLab)."""
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Palette (matches the web UI)
INDIGO = colors.HexColor('#4f46e5')
NAVY = colors.HexColor('#0f172a')
INCOME = colors.HexColor('#059669')
EXPENSE = colors.HexColor('#e11d48')
MUTED = colors.HexColor('#64748b')
BORDER = colors.HexColor('#e7e9f0')
ZEBRA = colors.HexColor('#f8fafc')
SOFT_INDIGO = colors.HexColor('#eef2ff')

CURRENCY = 'BDT'  # the built-in PDF fonts have no ৳ glyph

FILTER_LABELS = {'income': 'Income only', 'expense': 'Expenses only'}


def money(value, sign=''):
    return f'{sign}{CURRENCY} {Decimal(value):,.2f}'


def _styles():
    base = dict(fontName='Helvetica', fontSize=9, leading=12, textColor=NAVY)
    return {
        'cell': ParagraphStyle('cell', **base),
        'note': ParagraphStyle('note', **{**base, 'fontSize': 7.5, 'leading': 10, 'textColor': MUTED}),
        'label': ParagraphStyle('label', **{**base, 'fontSize': 7.5, 'textColor': MUTED}),
        'value': ParagraphStyle('value', **{**base, 'fontName': 'Helvetica-Bold', 'fontSize': 12, 'leading': 16}),
        'info': ParagraphStyle('info', **{**base, 'leading': 14}),
        'info_r': ParagraphStyle('info_r', **{**base, 'leading': 14, 'alignment': TA_RIGHT}),
        'h2': ParagraphStyle('h2', **{**base, 'fontName': 'Helvetica-Bold', 'fontSize': 11, 'leading': 14}),
    }


class _NumberedCanvas(rl_canvas.Canvas):
    """Canvas that draws the header band and a 'Page X of Y' footer on every page."""

    def __init__(self, *args, **kwargs):
        self._meta = kwargs.pop('meta')
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total):
        w, h = A4
        # Header band
        self.setFillColor(NAVY)
        self.rect(0, h - 26 * mm, w, 26 * mm, stroke=0, fill=1)
        self.setFillColor(INDIGO)
        self.roundRect(18 * mm, h - 18.5 * mm, 9 * mm, 9 * mm, 2 * mm, stroke=0, fill=1)
        self.setFillColor(colors.white)
        self.setFont('Helvetica-Bold', 11)
        self.drawCentredString(22.5 * mm, h - 15.6 * mm, 'M')
        self.setFont('Helvetica-Bold', 15)
        self.drawString(30 * mm, h - 15.8 * mm, 'ManageCash')
        self.setFont('Helvetica', 9)
        self.setFillColor(colors.HexColor('#a5b4fc'))
        self.drawRightString(w - 18 * mm, h - 13.5 * mm, 'TRANSACTION STATEMENT')
        self.setFillColor(colors.HexColor('#94a3b8'))
        self.drawRightString(w - 18 * mm, h - 18.5 * mm, self._meta['generated'])
        # Footer
        self.setStrokeColor(BORDER)
        self.setLineWidth(.6)
        self.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        self.setFont('Helvetica', 7.5)
        self.setFillColor(MUTED)
        self.drawString(18 * mm, 9.5 * mm, f"{self._meta['owner']} - Personal Cash Management")
        self.drawRightString(w - 18 * mm, 9.5 * mm, f'Page {self._pageNumber} of {total}')


def build_transactions_pdf(user, items, kind, overall):
    """Return PDF bytes for the given (already filtered) transaction rows.

    items:   list of dicts from views._transactions()
    overall: (total_income, total_expense, balance) for the whole account
    """
    st = _styles()
    now = timezone.localtime()
    owner = user.get_full_name() or user.username

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=34 * mm, bottomMargin=20 * mm,
        title='ManageCash - Transaction Statement', author=owner,
    )
    width = doc.width - 12  # frame has 6pt padding on each side; keep tables aligned with text
    story = []

    # ---- Account info ----
    if items:
        first = timezone.localtime(items[-1]['datetime']).strftime('%d %b %Y')
        last = timezone.localtime(items[0]['datetime']).strftime('%d %b %Y')
        period = first if first == last else f'{first} - {last}'
    else:
        period = 'No records'
    left = (f'<font color="#64748b" size="7.5">ACCOUNT HOLDER</font><br/>'
            f'<b>{escape(owner)}</b><br/>{escape(user.email or "@" + user.username)}')
    right = (f'<font color="#64748b" size="7.5">STATEMENT PERIOD</font><br/>'
             f'<b>{period}</b><br/>{FILTER_LABELS.get(kind, "All transactions")} - {len(items)} record(s)')
    info = Table([[Paragraph(left, st['info']), Paragraph(right, st['info_r'])]], colWidths=[width / 2] * 2)
    info.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    story += [info, Spacer(1, 7 * mm)]

    # ---- Summary boxes ----
    inc = sum((t['amount'] for t in items if t['kind'] == 'income'), Decimal('0'))
    exp = sum((t['amount'] for t in items if t['kind'] == 'expense'), Decimal('0'))
    balance = overall[2]

    def box(label, value, hex_color):
        return [Paragraph(label, st['label']),
                Paragraph(f'<font color="{hex_color}">{value}</font>', st['value'])]

    boxes = [box('TOTAL INCOME', money(inc), '#059669'),
             box('TOTAL EXPENSE', money(exp), '#e11d48'),
             box('NET AMOUNT', money(inc - exp), '#059669' if inc >= exp else '#e11d48'),
             box('CURRENT BALANCE', money(balance), '#4f46e5' if balance >= 0 else '#e11d48')]
    gap = 3 * mm
    bw = (width - 3 * gap) / 4
    summary = Table([[boxes[0], '', boxes[1], '', boxes[2], '', boxes[3]]],
                    colWidths=[bw, gap, bw, gap, bw, gap, bw])
    summary.setStyle(TableStyle([
        *[('BOX', (c, 0), (c, 0), .6, BORDER) for c in (0, 2, 4)],
        ('BACKGROUND', (6, 0), (6, 0), SOFT_INDIGO),
        ('BOX', (6, 0), (6, 0), .6, colors.HexColor('#c7d2fe')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story += [summary, Spacer(1, 8 * mm), Paragraph('Transactions', st['h2']), Spacer(1, 3 * mm)]

    # ---- Transactions table ----
    header = ['#', 'Date', 'Type', 'Source / Description', 'Amount']
    rows = [header]
    for i, t in enumerate(items, 1):
        dt = timezone.localtime(t['datetime'])
        desc = f'<b>{escape(t["title"])}</b>'
        if t['note']:
            desc += f'<br/><font size="7.5" color="#64748b">{escape(t["note"])}</font>'
        is_inc = t['kind'] == 'income'
        rows.append([
            str(i),
            Paragraph(f'{dt:%d %b %Y}<br/><font size="7.5" color="#64748b">{dt:%I:%M %p}</font>', st['cell']),
            'Income' if is_inc else 'Expense',
            Paragraph(desc, st['cell']),
            money(t['amount'], '+ ' if is_inc else '- '),
        ])
    if not items:
        rows.append(['', '', '', Paragraph('No transactions found for this filter.', st['note']), ''])

    col_w = [9 * mm, 27 * mm, 20 * mm, width - (9 + 27 + 20 + 34) * mm, 34 * mm]
    table = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 7.5),
        ('TEXTCOLOR', (0, 0), (-1, 0), MUTED),
        ('BACKGROUND', (0, 0), (-1, 0), ZEBRA),
        ('LINEBELOW', (0, 0), (-1, 0), .8, BORDER),
        ('FONT', (0, 1), (-1, -1), 'Helvetica', 9),
        ('FONT', (4, 1), (4, -1), 'Helvetica-Bold', 9),
        ('TEXTCOLOR', (0, 1), (0, -1), MUTED),
        ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 1), (-1, -1), .4, BORDER),
    ]
    for r, t in enumerate(items, 1):
        c = INCOME if t['kind'] == 'income' else EXPENSE
        style += [('TEXTCOLOR', (2, r), (2, r), c), ('TEXTCOLOR', (4, r), (4, r), c)]
        if r % 2 == 0:
            style.append(('BACKGROUND', (0, r), (-1, r), ZEBRA))
    table.setStyle(TableStyle(style))
    story.append(table)

    # ---- Totals row ----
    if items:
        totals = Table(
            [['', 'Total income', money(inc, '+ ')],
             ['', 'Total expense', money(exp, '- ')],
             ['', 'Net', money(inc - exp)]],
            colWidths=[width - 74 * mm, 40 * mm, 34 * mm])
        totals.setStyle(TableStyle([
            ('FONT', (1, 0), (-1, -1), 'Helvetica', 9),
            ('FONT', (1, 2), (-1, 2), 'Helvetica-Bold', 10),
            ('TEXTCOLOR', (1, 0), (1, -1), MUTED),
            ('TEXTCOLOR', (2, 0), (2, 0), INCOME), ('TEXTCOLOR', (2, 1), (2, 1), EXPENSE),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('LINEABOVE', (1, 2), (-1, 2), .8, NAVY),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story += [Spacer(1, 3 * mm), totals]

    meta = {'generated': f'Generated {now:%d %b %Y, %I:%M %p}', 'owner': owner}
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, meta=meta, **k))
    return buf.getvalue()
