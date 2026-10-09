#!/usr/bin/env python3
"""Rend des clips 1080x1920 a partir d'un fichier JSON (voir ../CLIPS_SPEC_EXEMPLE.json).

Usage : python3 make_clips.py spec.json [nom_clip ...]

Prerequis : ffmpeg + ffprobe dans le PATH, Python 3 + Pillow, police Inter ExtraBold
(sinon n'importe quelle police grasse : champ "font_file" du JSON).

Methode (mesuree sur les fichiers Drive 4K 2160x3840) :
  - la video utile est une bande CARREE de 2160x2160 entre y=840 et y=3000 ;
  - on recadre 56,25 % de la largeur de cette bande (ratio 9:16) puis on met a 1080x1920 ;
  - titre, handles et sous-titres d'origine sortent du cadre, sauf la legende baked au milieu de la bande ;
  - on la recouvre par une carte NOIRE OPAQUE (alpha 255) + la nouvelle legende.
    (Alpha < 255 = l'ancien texte transparait ; flou / inpainting = moche, abandonne.)
"""
import json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
DEFAULT_FONT = '/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf'


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        sys.exit(r.stderr[-2000:].decode(errors='replace'))
    return r.stdout.decode()


def probe(path):
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
               '-of', 'csv=p=0', path]).strip().split(',')
    return int(out[0]), int(out[1])


def card_png(text, path, font_file, size, y0, y1, pad=34, full=False, maxw=880):
    """Carte opaque (rectangle plein-largeur ou arrondi) avec le texte centre, agrandie si le texte deborde."""
    font = ImageFont.truetype(font_file, size)
    lines, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if font.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    lh = int(size * 1.2); th = lh * len(lines); cy = (y0 + y1) / 2; need = th + 2 * pad
    if y1 - y0 < need:
        y0, y1 = int(cy - need / 2), int(cy + need / 2)
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    if full:
        d.rectangle((0, y0, W, y1), fill=(8, 8, 8, 255))
    else:
        d.rounded_rectangle((40, y0, W - 40, y1), radius=42, fill=(8, 8, 8, 255))
    y = int(cy - th / 2) + int(size * 0.04)
    for ln in lines:
        d.text((W / 2, y), ln, font=font, fill=(255, 255, 255, 255), anchor='ma'); y += lh
    img.save(path)
    return lines


def render(c, spec, tmp):
    src_dir = spec['sources_dir']; out_dir = spec['out_dir']
    font_file = spec.get('font_file', DEFAULT_FONT)
    name = c['name']; segs = c['segments']
    total = sum(s['dur'] for s in segs)
    card = c.get('card', {})
    inputs, fc = [], []
    # --- video : un segment = un fichier, recadre sur la bande carree
    for i, s in enumerate(segs):
        p = os.path.join(src_dir, s['src']); sw, sh = probe(p)
        k = sh / 3840.0                              # echelle par rapport a un fichier 2160x3840
        bh = round(2160 * k); by = round(840 * k)    # bande carree
        cw = round(bh * 9 / 16) // 2 * 2
        x0 = int((sw - cw) * s.get('pan', 0.5))      # pan : 0 = gauche, 0.5 = centre, 1 = droite
        inputs += ['-i', p]
        fc.append(f"[{i}:v]trim=start={s['ss']}:duration={s['dur']},setpts=PTS-STARTPTS,"
                  f"crop={cw}:{bh}:{x0}:{by},scale={W}:{H}:flags=lanczos,fps=30,setsar=1[v{i}]")
    fc.append(''.join(f'[v{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=1:a=0[vc]')
    # --- cartes de legende, une par segment (position de l'ancienne legende propre a chaque plan)
    last, t = 'vc', 0.0; n = len(segs)
    for i, s in enumerate(segs):
        y0, y1 = s.get('card_y', card.get('y', [0.425, 0.585]))
        png = os.path.join(tmp, f'{name}_card{i}.png')
        lines = card_png(c['caption'], png, font_file, c.get('font', 66), int(y0 * H), int(y1 * H),
                         full=card.get('full', False), maxw=card.get('maxw', 880))
        inputs += ['-loop', '1', '-framerate', '30', '-t', str(total), '-i', png]
        fc.append(f"[{last}][{n + i}:v]overlay=0:0:enable='between(t,{t:.3f},{t + s['dur']:.3f})'[ov{i}]")
        last = f'ov{i}'; t += s['dur']
    fc.append(f'[{last}]null[vout]')
    # --- audio
    a = c.get('audio', {'mode': 'silent'})
    if a['mode'] == 'silent':
        fc.append(f'anullsrc=r=48000:cl=stereo,atrim=0:{total}[aout]')
    else:                                            # mode "source" : audio d'un fichier du Drive
        inputs += ['-i', os.path.join(src_dir, a['src'])]
        idx = sum(1 for x in inputs if x == '-i') - 1  # index ffmpeg du dernier -i
        chain = f"[{idx}:a]atrim=start={a.get('ss', 0)}:duration={total},asetpts=PTS-STARTPTS"
        for m0, m1 in a.get('mute', []):             # fenetres coupees (jurons) : silence + bip
            chain += f",volume=enable='between(t,{m0},{m1})':volume=0"
        chain += f",afade=t=in:st=0:d=0.05,afade=t=out:st={total - 0.15:.2f}:d=0.15,aformat=channel_layouts=mono[a1]"
        fc.append(chain)
        if a.get('mute'):
            labels = '[a1]'
            for j, (m0, m1) in enumerate(a['mute']):
                fc.append(f"sine=frequency=1000:sample_rate=48000:duration={m1 - m0:.2f},volume=0.2,"
                          f"adelay={int(m0 * 1000)}|{int(m0 * 1000)},aformat=channel_layouts=mono[bp{j}]")
                labels += f'[bp{j}]'
            fc.append(f"{labels}amix=inputs={1 + len(a['mute'])}:duration=first:normalize=0,"
                      f"alimiter=limit=0.89:level=disabled[aout]")
        else:
            fc.append('[a1]anull[aout]')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name + '.mp4')
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y'] + inputs +
        ['-filter_complex', ';'.join(fc), '-map', '[vout]', '-map', '[aout]', '-t', str(total),
         '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30',
         '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', out])
    print('ok', out, f'{total:.1f}s', lines)


if __name__ == '__main__':
    spec = json.load(open(sys.argv[1], encoding='utf-8'))
    only = set(sys.argv[2:])
    tmp = os.path.join(spec['out_dir'], '_tmp'); os.makedirs(tmp, exist_ok=True)
    for c in spec['clips']:
        if not only or c['name'] in only:
            render(c, spec, tmp)
