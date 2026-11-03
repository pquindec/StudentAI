import json,sys,re,unicodedata,jiwer
n=lambda s:re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',unicodedata.normalize('NFC',s.lower()))).strip()
ref=n(open('corpus/es_lecture.txt').read()); L=265.117688
segs=json.load(open(sys.argv[1]))['transcription']
def t(ts):
    h,m,s=ts.split(':');return int(h)*3600+int(m)*60+float(s.replace(',','.'))
for i in range(14):
    hyp=n(' '.join(s['text'] for s in segs if i*L<=t(s['timestamps']['from'])<(i+1)*L))
    print(f"rep {i+1:2d} ({i*L/60:4.0f} min): palabras {len(hyp.split()):4d}/{len(ref.split())}  WER {jiwer.wer(ref,hyp):.3f}")
