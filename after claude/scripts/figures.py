"""Paper figures from archived, sanitized session records; no AWS execution."""
import os, json, csv, statistics as st
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(BASE.parent / '.mplconfig'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

D = json.loads((BASE/'data/measurements.public.json').read_text())
K = ['smaug1','smaug3','smaug5','ntruplus_kem576','ntruplus_kem768','ntruplus_kem864','ntruplus_kem1152']
S = ['haetae2','haetae3','haetae5','aimer128f','aimer192f','aimer256f']
def name(s):
    return s.replace('ntruplus_kem','NTRU+ ').replace('smaug','SMAUG ').replace('haetae','HAETAE ').replace('aimer','AIMer ').replace('EC','ECDSA')
rows={}; rounds={}
for block in D['rounds']:
    mode=block['mode']
    for p in block['profiles']:
        if p['sentinel']: continue
        key=(mode,p['kem'],p['signature'])
        kept=[s for s in p['sessions'] if not s['warmup']]
        assert all(s['client']['success'] and not s['client']['reused'] for s in kept)
        rows.setdefault(key,[]).extend(kept)
        rounds.setdefault(key,[]).append(st.median(s['client']['handshake_ms'] for s in kept))
def value(mode,k,s,side,metric):
    return st.median(r[side][metric] for r in rows[mode,k,s])
for row in csv.DictReader((BASE/'data/summary.csv').open()):
    key=(row['mode'],row['kem'],row['signature'])
    assert len(rows[key]) == int(row['analyzed_n'])
    assert abs(value(*key,'client','handshake_ms')-float(row['client_handshake_median_ms'])) < 1e-9

BLUE, ORANGE = '#0072B2', '#D55E00'
for lang in ['ko','en']:
    ko=lang=='ko'
    plt.rcParams.update({'font.family':'Apple SD Gothic Neo' if ko else 'DejaVu Sans', 'font.size':11, 'axes.unicode_minus':False, 'svg.fonttype':'path'})
    out=BASE/'figures'/lang
    def save(fig,stem):
        for ext in ['svg','png']:
            path=out/f'{stem}.{ext}'
            fig.savefig(path,dpi=200,bbox_inches='tight',facecolor='white')
            if ext=='svg': path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')
        plt.close(fig)
    def style(ax):
        ax.spines[['top','right','left']].set_visible(False)
        ax.grid(axis='x',alpha=.18); ax.set_axisbelow(True); ax.tick_params(axis='y',length=0)
    for kind in ['latency','memory']:
        labels=(['새 프로세스','프로세스 재사용'] if ko else ['Fresh process','Reused process']) if kind=='latency' else (['클라이언트','서버'] if ko else ['Client','Server'])
        for family,ks in [('smaug',['X25519']+K[:3]),('ntru',K[3:])]:
            fig,axs=plt.subplots(2,2,figsize=(12.8,7.8),layout='constrained')
            for idx,(ax,k) in enumerate(zip(axs.flat,ks)):
                sigs=['EC'] if k=='X25519' else S
                for j,s in enumerate(sigs):
                    for mode,side,dy,color,marker in ([('cold','client',-.13,BLUE,'o'),('warm','client',.13,ORANGE,'s')] if kind=='latency' else [('memory','client',-.13,BLUE,'o'),('memory','server',.13,ORANGE,'s')]):
                        v=value(mode,k,s,side,'handshake_ms' if kind=='latency' else 'rss_window_peak_growth_kib')
                        ax.plot(v,j+dy,marker=marker,color=color,ms=7,ls='')
                        ax.annotate(f'{v:.2f}' if kind=='latency' else f'{v:.0f}',(v,j+dy),xytext=(7,0),textcoords='offset points',va='center',fontsize=9,color=color)
                ax.set_yticks(range(len(sigs)),[name(s) for s in sigs]); ax.set_ylim(len(sigs)-.5,-.5)
                ax.set_xlim(0,13 if kind=='latency' else 1450)
                ax.set_title(f'({chr(97+idx)}) {name(k)}',loc='left',fontsize=13,pad=12)
                ax.set_xlabel(('핸드셰이크 시간 (ms)' if ko else 'Handshake latency (ms)') if kind=='latency' else ('최대 RSS 증가량 (KiB)' if ko else 'Peak RSS growth (KiB)'))
                style(ax)
            fig.legend(handles=[Line2D([],[],marker=m,color=c,ls='',label=l) for l,c,m in zip(labels,[BLUE,ORANGE],['o','s'])],loc='outside upper center',ncol=2,frameon=False)
            save(fig,f'{kind}_{family}')
    selected=[('X25519','EC'),('smaug1','haetae2'),('smaug1','aimer128f'),('ntruplus_kem576','haetae2'),('ntruplus_kem576','aimer128f')]
    fig,axs=plt.subplots(3,2,figsize=(12.8,9),layout='constrained')
    for ax,(k,s) in zip(axs.flat,selected):
        for mode,c,m in [('cold',BLUE,'o'),('warm',ORANGE,'s')]: ax.plot(range(1,6),rounds[mode,k,s],color=c,marker=m,lw=1.5)
        ax.set_title(f'{name(k)} + {name(s)}',loc='left'); ax.set_xticks(range(1,6)); ax.set_ylim(0,6)
        ax.set_xlabel('라운드' if ko else 'Round'); ax.set_ylabel('핸드셰이크 시간 (ms)' if ko else 'Handshake latency (ms)'); style(ax)
    axs.flat[-1].axis('off')
    axs.flat[-1].legend(handles=[Line2D([],[],color=c,marker=m,label=l) for l,c,m in zip(['새 프로세스','프로세스 재사용'] if ko else ['Fresh process','Reused process'],[BLUE,ORANGE],['o','s'])],loc='center',frameon=False)
    save(fig,'rounds')
print('Verified 129 summary rows; generated 10 bilingual figures in PNG and SVG.')
