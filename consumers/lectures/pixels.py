"""Mechanical crops of original visible pages, including annotations and masks."""
import io
import math
from pathlib import Path

from PIL import Image, ImageOps

from materials.common import file_sha, require, sha


class OriginalPages:
    def __init__(self,source,folder,masks=None):
        self.source=Path(source);self.folder=Path(folder);self.digest=file_sha(source)
        self.folder.mkdir(parents=True,exist_ok=True)
        self.pdf=None;self.raster=None;self.loaded={};self.masks=masks or []
        if self.source.suffix.lower()=='.pdf':
            import pymupdf
            self.pdf=pymupdf.open(self.source);self.count=len(self.pdf)
        else:
            try:
                with Image.open(self.source) as image:
                    require(getattr(image,'n_frames',1)==1,'Animated source requires a verified page adapter')
                    self.raster=ImageOps.exif_transpose(image).convert('RGB')
            except (OSError,ValueError) as error:
                raise ValueError('Original page crops require a PDF or still image; provide an original-page rendition for this new material form') from error
            self.count=1

    def page(self,number):
        require(type(number) is int and 1<=number<=self.count,'Invalid original page')
        if number not in self.loaded:
            if self.pdf is not None:
                import pymupdf
                pix=self.pdf[number-1].get_pixmap(matrix=pymupdf.Matrix(3,3),alpha=False,annots=True)
                image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                layers=[m for m in self.masks if m['page']==number and m.get('backgroundLayer')]
                if layers:image=self.separate_layers(number,image,layers)
            else:image=self.raster.copy()
            # Bound resident full-resolution pages even for long source books.
            if len(self.loaded)>=3:self.loaded.pop(next(iter(self.loaded)))
            self.loaded[number]=image
        return self.loaded[number]

    def separate_layers(self,number,original,marks):
        """Replace only proved background pixels in an in-memory page copy."""
        import pymupdf
        from PIL import ImageDraw
        with pymupdf.open() as doc:
            doc.insert_pdf(self.pdf,from_page=number-1,to_page=number-1)
            page=doc[0];infos=page.get_image_info(xrefs=True)
            for xref in sorted({m['backgroundLayer']['imageXref'] for m in marks}):
                group=[m for m in marks if m['backgroundLayer']['imageXref']==xref]
                raw=self.pdf.extract_image(xref)['image']
                require(all(sha(raw)==m['backgroundLayer']['imageSha256'] for m in group),'Noise layer image changed')
                image=Image.open(io.BytesIO(raw)).convert('RGB');draw=ImageDraw.Draw(image)
                for m in group:
                    r=m['backgroundLayer']['pixelRect'];draw.rectangle((r[0],r[1],r[2]-1,r[3]-1),fill='white')
                # insert_pdf remaps object IDs. Match the original bytes rather
                # than assuming those IDs survive the isolated copy.
                copies={i['xref'] for i in infos if i['xref'] and sha(doc.extract_image(i['xref'])['image'])==sha(raw)}
                require(len(copies)==1,'Cannot identify the original background layer in page copy')
                buffer=io.BytesIO();image.save(buffer,format='PNG');page.replace_image(copies.pop(),stream=buffer.getvalue())
            pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3),alpha=False,annots=True)
            cleaned=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        result=original.copy();w,h=original.size
        # Keep every pixel outside the explicit excluded regions byte-identical
        # even if an embedded colour profile renders differently after encoding.
        for mark in marks:
            b=mark['bbox'];r=(math.floor(w*b[0]/1000),math.floor(h*b[1]/1000),math.ceil(w*b[2]/1000),math.ceil(h*b[3]/1000))
            result.paste(cleaned.crop(r),(r[0],r[1]))
        return result

    def previews(self):
        result=[]
        for number in range(1,self.count+1):
            image=self.page(number).copy();image.thumbnail((1200,1700))
            path=self.folder/f'page-{number:04d}.png';image.save(path)
            result.append({'path':str(path),'sha256':file_sha(path)})
        return result

    def crop(self,page,box):
        require(isinstance(box,list) and len(box)==4 and all(type(x) in (int,float) and math.isfinite(x) for x in box),'Invalid crop coordinates')
        require(0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000,'Crop outside original page')
        image=self.page(page);w,h=image.size
        rect=(math.floor(w*box[0]/1000),math.floor(h*box[1]/1000),math.ceil(w*box[2]/1000),math.ceil(h*box[3]/1000))
        cropped=image.crop(rect)
        from PIL import ImageDraw
        draw=ImageDraw.Draw(cropped)
        for mark in self.masks:
            if mark['page']!=page:continue
            if mark.get('backgroundLayer'):continue
            b=mark['bbox'];r=(math.floor(w*b[0]/1000)-rect[0],math.floor(h*b[1]/1000)-rect[1],math.ceil(w*b[2]/1000)-rect[0],math.ceil(h*b[3]/1000)-rect[1])
            if r[0]<cropped.width and r[2]>0 and r[1]<cropped.height and r[3]>0:
                # PIL rectangles include the final pixel; preserve every pixel
                # outside the exact OCR-backed excluded rectangle.
                draw.rectangle((r[0],r[1],r[2]-1,r[3]-1),fill='white')
        buffer=io.BytesIO();cropped.save(buffer,format='PNG')
        return buffer.getvalue(),list(rect)

    def regions(self,atoms,indices,padding=12):
        """Full width preserves side notes; overlap/context is intentional."""
        pages={}
        for i in indices:
            a=atoms[i];box=a.get('bbox');page=a.get('page')
            require(isinstance(box,list) and len(box)==4,'Source atom has no page geometry: '+str(i))
            require(all(type(x) in (int,float) and math.isfinite(x) for x in box) and 0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000,'Invalid OCR geometry: '+str(i))
            self.page(page)
            pages.setdefault(page,[]).append(box)
        require(pages,'Empty original-image field')
        regions=[]
        for page,boxes in sorted(pages.items()):
            # OCR may mix a handwritten heading into a logo rectangle. Include
            # that full region with its overlapping teaching block after only
            # the independent background has been cleaned.
            boxes=boxes+[m['bbox'] for m in self.masks if m['page']==page and m.get('backgroundLayer') and set(indices).intersection(m.get('preserveAtoms',[]))]
            box=[0,max(0,min(b[1] for b in boxes)-padding),1000,min(1000,max(b[3] for b in boxes)+padding)]
            data,rect=self.crop(page,box)
            regions.append({'page':page,'bbox':box,'pixel_rect':rect,'sha256':sha(data),'data':data})
        return regions

    def close(self):
        if self.pdf is not None:self.pdf.close()
