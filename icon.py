from PIL import Image, ImageDraw
import math
S=1024
def make(size=S):
    k=4; N=size*k
    im=Image.new("RGBA",(N,N),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle((0,0,N-1,N-1),radius=int(N*0.225),fill=(28,28,26,255))
    cx=cy=N/2
    def ring(r,w,col,frac):
        bb=(cx-r,cy-r,cx+r,cy+r)
        d.arc(bb,0,360,fill=(58,57,53,255),width=w)
        d.arc(bb,-90,-90+360*frac,fill=col,width=w)
        # round caps
        for a in (-90,-90+360*frac):
            x=cx+(r-w/2)*math.cos(math.radians(a)); y=cy+(r-w/2)*math.sin(math.radians(a))
            d.ellipse((x-w/2,y-w/2,x+w/2,y+w/2),fill=col)
    w=int(N*0.075)
    ring(N*0.38,w,(217,119,87,255),0.86)
    ring(N*0.27,w,(75,123,236,255),0.62)
    ring(N*0.16,w,(47,163,107,255),0.40)
    return im.resize((size,size),Image.LANCZOS)
big=make(1024); big.save("icon.png")
big.save("icon.ico",sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
