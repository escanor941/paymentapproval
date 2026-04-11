from io import BytesIO

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def export_rows_to_excel(title: str, headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.append([title])
    ws.append([])
    ws.append(headers)
    for row in rows:
        ws.append(row)

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def export_rows_to_pdf(title: str, headers: list[str], rows: list[list]) -> bytes:
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=A4)
    width, height = A4

    y = height - 40
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, title)
    y -= 30

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, " | ".join(headers))
    y -= 15

    pdf.setFont("Helvetica", 9)
    for row in rows:
        text = " | ".join(str(x) for x in row)
        pdf.drawString(40, y, text[:140])
        y -= 14
        if y < 40:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 9)

    pdf.save()
    return stream.getvalue()
