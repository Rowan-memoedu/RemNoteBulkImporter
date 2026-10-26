"""Generate small independent cross-subject source files outside the repository."""
import argparse
import json
from pathlib import Path
import zipfile


def create(root):
    from PIL import Image, ImageDraw, ImageFont
    root.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1000,600),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',38)
    draw.text((60,40),'Biology: Cells',font=font,fill='black')
    draw.text((60,120),'The membrane surrounds the cell.',font=font,fill='black')
    draw.text((60,200),'1. Nucleus\n2. Cytoplasm',font=font,fill='black',spacing=12)
    draw.ellipse((450,300,700,520),outline='blue',width=6)
    image.save(root/'biology.png')
    (root/'history.txt').write_text('The industrial revolution\nThe steam engine changed manufacturing.\nTransport\nRailways connected cities.\n',encoding='utf-8')
    (root/'chemistry.md').write_text('# Chemistry\n\n## Gas laws\n\n- State variables\n  - Pressure $p$ and volume $V$.\n  - $pV=nRT$\n\n## Laboratory\n\n| Quantity | Value |\n| --- | --- |\n| Temperature | 300 K |\n| Amount | 1 mol |\n',encoding='utf-8')
    (root/'geography.html').write_text('<!doctype html><html><body><h1>Geography</h1><h2>Earth</h2><p>The <b>surface</b> includes land and oceans.</p><h2>Map</h2><p>Local illustration:</p><img src="biology.png"></body></html>',encoding='utf-8')
    from docx import Document
    document=Document();document.add_heading('Literature',0);document.add_heading('Poetry',1)
    document.add_paragraph('Rhythm and imagery help create meaning.');document.add_heading('Prose',1);document.add_paragraph('Narrative follows characters through events.')
    table=document.add_table(rows=2,cols=2);table.cell(0,0).text='Form';table.cell(0,1).text='Example';table.cell(1,0).text='Prose';table.cell(1,1).text='Novel'
    document.save(root/'literature.docx')
    from pptx import Presentation
    deck=Presentation()
    for title,body in [('Computer science','Algorithms describe finite procedures.'),('Data structures','Lists preserve ordering.\nTrees represent hierarchies.')]:
        slide=deck.slides.add_slide(deck.slide_layouts[1]);slide.shapes.title.text=title;slide.placeholders[1].text=body
    deck.save(root/'computing.pptx')
    with zipfile.ZipFile(root/'astronomy.epub','w') as archive:
        archive.writestr('mimetype','application/epub+zip')
        archive.writestr('META-INF/container.xml','<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr('book.opf','''<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">synthetic-astronomy</dc:identifier><dc:title>Astronomy</dc:title><dc:language>en</dc:language></metadata><manifest><item id="c" href="chapters.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="c"/></spine></package>''')
        archive.writestr('chapters.xhtml','<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Astronomy</title></head><body><h1 id="stars">Stars</h1><p>Stars emit light.</p><h1 id="planets">Planets</h1><p>Planets orbit stars.</p></body></html>')
        archive.writestr('nav.xhtml','<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol><li><a href="chapters.xhtml#stars">Stars</a></li><li><a href="chapters.xhtml#planets">Planets</a></li></ol></nav></body></html>')
    print(json.dumps({'fixture_directory':str(root),'files':[p.name for p in root.iterdir()]},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');create(Path(parser.parse_args().output))
