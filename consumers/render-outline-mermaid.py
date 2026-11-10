"""Rasterize one Mermaid source with the existing local reading renderer runtime."""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def render(source,library,output):
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page(viewport={'width':1600,'height':1200},device_scale_factor=2)
            page.route('**/*',lambda route:route.abort())
            page.set_content('<!doctype html><meta charset="utf-8"><style>body{margin:0;background:white;font-family:Arial,"Microsoft YaHei",sans-serif}.mermaid{display:inline-block;padding:16px;background:white}svg{max-width:none!important}</style><div class="mermaid"></div>')
            page.locator('.mermaid').evaluate('(node,text)=>node.textContent=text',source.read_text(encoding='utf8'))
            page.add_script_tag(path=str(library))
            page.evaluate('''async()=>{mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'default'});await mermaid.run({nodes:[document.querySelector('.mermaid')]});await document.fonts.ready;}''')
            diagram=page.locator('.mermaid')
            assert diagram.locator('svg').count()==1,'Mermaid SVG missing'
            assert page.locator('.error-icon,.error-text').count()==0,'Mermaid parse failure'
            size=diagram.bounding_box()
            assert size and 0<size['width']<=12000 and 0<size['height']<=12000,'Invalid diagram size'
            diagram.screenshot(path=str(output),timeout=60000)
            print(json.dumps({'status':'rendered','width':size['width'],'height':size['height']}))
        finally:browser.close()


if __name__=='__main__':render(*(Path(s).resolve() for s in sys.argv[1:4]))
