from PIL import Image, ImageDraw, ImageFont
import os

def find_font():
    cands = [
      "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
      "/System/Library/Fonts/Supplemental/Arial.ttf",
      "/System/Library/Fonts/Helvetica.ttc",
      "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
    ]
    for c in cands:
        if os.path.exists(c): return c
    return None
fontp = find_font()

def rounded(d, box, rad, fill):
    d.rounded_rectangle([0,0,box-1,box-1], radius=rad, fill=fill)

def lerp(a,b,t): return int(a+(b-a)*t)

def render(size):
    S = size
    img = Image.new("RGBA",(S,S),(0,0,0,0))
    px = img.load()
    # supersample factor
    SS = 4
    big = Image.new("RGBA",(S*SS,S*SS),(0,0,0,0))
    db = ImageDraw.Draw(big)
    bs = S*SS
    rad = int(bs*0.20)
    # vertical gradient fill rounded rect
    top=(26,72,176); bot=(24,60,140)
    # mask
    mask = Image.new("L",(bs,bs),0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,bs-1,bs-1], radius=rad, fill=255)
    grad = Image.new("RGBA",(bs,bs),(0,0,0,0))
    gp = grad.load()
    for y in range(bs):
        t=y/(bs-1)
        c=(lerp(top[0],bot[0],t),lerp(top[1],bot[1],t),lerp(top[2],bot[2],t),255)
        for x in range(bs):
            gp[x,y]=c
    big.paste(grad,(0,0),mask)
    # letter C
    if fontp:
        fsize = int(bs*0.62)
        try:
            f = ImageFont.truetype(fontp, fsize)
        except Exception:
            f = ImageFont.load_default()
        # get text bbox
        tb = db.textbbox((0,0),"C",font=f)
        tw=tb[2]-tb[0]; th=tb[3]-tb[1]
        tx=(bs-tw)//2 - tb[0]
        ty=(bs-th)//2 - tb[1] + int(bs*0.02)
        # white with slight shadow for readability
        db.text((tx,ty),"C",font=f,fill=(255,255,255,255))
    img = big.resize((S,S), Image.LANCZOS)
    return img

sizes=[256,128,64,48,40,32,24,16]
images=[]
for s in sizes:
    images.append(render(s))
images[0].save("app.ico", format="ICO", sizes=[(s,s) for s in sizes], append_images=images[1:])
print("icon written", os.path.getsize("app.ico"), "bytes")
