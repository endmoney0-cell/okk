import sys,subprocess,numpy as np
from faster_whisper import WhisperModel
f=sys.argv[1]
raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',f,'-ac','1','-ar','16000','-f','s16le','-'],capture_output=True,stdin=subprocess.DEVNULL).stdout
a=np.frombuffer(raw,np.int16).astype(np.float32)/32768
m=WhisperModel('small',device='cpu',compute_type='int8')
segs,_=m.transcribe(a,language='en',word_timestamps=True,condition_on_previous_text=False)
for s in segs:
    for w in s.words: print(f"{w.start:6.2f}-{w.end:6.2f} {w.word}")
