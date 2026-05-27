import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io, json

st.set_page_config(page_title="Análise de Viabilidade de Projetos Imobiliários",page_icon="🏗️",layout="wide")
st.markdown("""<style>
section[data-testid="stSidebar"]{background:#141f2e!important}
section[data-testid="stSidebar"] *{color:#dde8f5!important}
section[data-testid="stSidebar"] [data-testid="stMetricValue"]{color:#e6c06a!important;font-size:1.2rem!important}
section[data-testid="stSidebar"] [data-testid="stMetricLabel"]{color:#8aa8c4!important}
section[data-testid="stSidebar"] .stSelectbox>div>div{background:#1e2f44!important;border-color:#2d4460!important}
section[data-testid="stSidebar"] hr{border-color:#2d4460!important}
.stTabs [data-baseweb="tab"]{font-weight:600;padding:8px 12px}
[data-testid="stMetricValue"]{font-size:1.3rem!important;font-weight:700}
footer{visibility:hidden}
.watermark{position:fixed;bottom:14px;right:18px;font-size:11px;color:rgba(80,80,80,0.3);z-index:9999;pointer-events:none}
</style><div class='watermark'>© Desenvolvido por Alexandre Bomfim</div>""",unsafe_allow_html=True)

# ── Formatadores ─────────────────────────────────────────────────
def brl(n):
    if n is None or (isinstance(n,float) and not np.isfinite(n)): return "—"
    s=f"{abs(n):,.0f}".replace(",",".")
    return f"(R$ {s})" if n<0 else f"R$ {s}"
def brlk(n):
    if n is None or (isinstance(n,float) and not np.isfinite(n)): return "—"
    if abs(n)>=1e6: return f"R$ {n/1e6:.2f}M".replace(".",",")
    if abs(n)>=1e3: return f"R$ {n/1e3:.0f}k"
    return brl(n)
def pct(n,d=1):
    if n is None or (isinstance(n,float) and not np.isfinite(n)): return "—"
    return f"{n:.{d}f}%".replace(".",",")
def card(lbl,val,cor="#1565c0",sub=None,bg="#f0f4ff"):
    s=f"<div style='font-size:11px;color:#555;margin-top:2px'>{sub}</div>" if sub else ""
    return(f"<div style='background:{bg};border-radius:8px;padding:12px 14px;border-left:4px solid {cor};margin-bottom:6px'>"
           f"<div style='font-size:10px;color:#888;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px'>{lbl}</div>"
           f"<div style='font-size:20px;font-weight:700;color:{cor};font-variant-numeric:tabular-nums;line-height:1.2'>{val}</div>{s}</div>")

# ── Matemática ────────────────────────────────────────────────────
def calc_irr(cfs):
    r=0.01
    for _ in range(500):
        try:
            f=sum(c/(1+r)**t for t,c in enumerate(cfs))
            df=sum(-t*c/(1+r)**(t+1) for t,c in enumerate(cfs))
        except: break
        if not np.isfinite(f) or abs(df)<1e-12: break
        nr=r-f/df
        if abs(nr-r)<1e-10: r=nr; break
        r=max(-0.999,nr)
    return r
def calc_npv(cfs,r): return sum(c/(1+r)**t for t,c in enumerate(cfs))
def s_curve(n):
    a,p=[],0
    for i in range(1,n+1):
        t=i/n; c=3*t**2-2*t**3; a.append(c-p); p=c
    return a
def get_obra_curve(p):
    tp=p.get("obra_curve_type","scurve")
    if tp=="scurve": return s_curve(36)
    if tp=="linear": return [1/36]*36
    sem=p.get("obra_curve_sem",[100/6]*6); m=[]
    for s in sem: m.extend([s/100/6]*6)
    return m[:36]

# ── Compute ───────────────────────────────────────────────────────
def compute(p):
    # ─ Dimensões do projeto ─
    obra_start = max(1, int(p.get("aprovacao_meses",6)))
    delivery   = obra_start + 36
    N          = min(delivery + 26, 72)  # janela de 6 anos

    lt=p.get("land_type","Dinheiro")
    # ─ Mix de unidades ─
    mix_rows=[r for r in p.get("mix",[]) if r.get("Qtd",0)>0] if p.get("use_mix",False) else []
    if mix_rows:
        u   = sum(r["Qtd"] for r in mix_rows)
        raw_vgv = sum(r["Qtd"]*r["Preco"] for r in mix_rows)
        raw_area= sum(r["Qtd"]*r["Area"]  for r in mix_rows)
        pr  = raw_vgv/max(1,u)
        ar  = raw_area/max(1,u)
    else:
        u=p["units"]; pr=p["avg_price"]; ar=p["avg_area"]

    pu=0 if lt=="Dinheiro" else min(int(p.get("perm_units",0)),u-1)
    su=u-pu; pv=pu*pr
    lc=0 if lt=="Permuta Física" else p.get("land",0)
    itb_b=pv if lt=="Permuta Física" else(p.get("land",0)+pv if lt=="Misto" else p.get("land",0))
    itb=itb_b*p.get("itbi_pct",2.5)/100

    # ─ Distrato ─
    distrato=p.get("distrato_pct",0)/100
    eff_su=su*(1-distrato)
    vgv=eff_su*pr

    cb=u*ar*p["cost_per_sqm"]
    cf_=cb*p.get("const_fee_pct",12)/100
    prj=cb*p.get("projetos_pct",3.5)/100
    ins=cb*p.get("inss_pct",4.5)/100
    cont=cb*p.get("contingencia_pct",5)/100
    ct=cb+cf_+prj+ins+cont
    gar=ct*p.get("garantia_pct",1)/100
    ci=p.get("custo_incorp",50000)
    mkt=vgv*p.get("marketing_pct",3)/100
    brk=vgv*p.get("brokerage_pct",4)/100
    adm=vgv*p.get("admin_pct",5)/100
    std=p.get("sales_stand",180000); oth=p.get("other_costs",80000)
    IMP={"RET":0.04,"Lucro Presumido":0.0673,"Simples Nacional":0.03,"Nenhum":0.0}
    imp=vgv*IMP.get(p.get("imposto_tipo","Nenhum"),0.0)
    custom_cc=sum(float(c.get("Valor (R$)",0) or 0) for c in p.get("custom_costs",[]))
    cc=lc+itb+ct+mkt+std+brk+adm+oth+gar+ci+imp+custom_cc
    tc=cc+pv; nr=vgv-brk-imp; np_=vgv-tc
    nm=np_/vgv*100 if vgv else 0
    gp=nr-(lc+pv+itb+ct+mkt+std+adm+oth+gar+ci+custom_cc)
    gm=gp/nr*100 if nr else 0
    roi=np_/cc*100 if cc else 0; roit=np_/tc*100 if tc else 0

    # ─ Tabela de vendas ─
    t_sin=p.get("t_sinal",5); t_mn_n=max(0,int(p.get("t_mensais_n",5)))
    t_mn_p=p.get("t_mensais_pct",10); t_sm_n=max(0,int(p.get("t_semestrais_n",0)))
    t_sm_p=p.get("t_semestrais_pct",0); t_an_n=max(0,int(p.get("t_anuais_n",0)))
    t_an_p=p.get("t_anuais_pct",0); t_ft_p=p.get("t_financiamento_pct",30)
    t_sal=p.get("t_saldo",25)
    t_known=t_sin+t_mn_p+t_sm_p+t_an_p+t_ft_p+t_sal; tev=max(0,100-t_known)
    evol_start=max(t_mn_n+1,obra_start); evol_end=delivery-1; evol_em=max(0,evol_end-evol_start+1)
    mn_pc=(t_mn_p/100/t_mn_n) if t_mn_n>0 else 0
    sm_pc=(t_sm_p/100/t_sm_n) if t_sm_n>0 else 0
    an_pc=(t_an_p/100/t_an_n) if t_an_n>0 else 0
    ev_pc=(tev/100/evol_em)   if evol_em>0 else 0
    tab=[(0,t_sin/100,"Sinal")]
    for i in range(t_mn_n): tab.append((i+1,mn_pc,"Mensal"))
    for i in range(t_sm_n): tab.append(((i+1)*6,sm_pc,"Semestral"))
    for i in range(t_an_n): tab.append(((i+1)*12,an_pc,"Anual"))
    for i in range(evol_em): tab.append((evol_start+i,ev_pc,"Evolução"))
    tab.append((delivery,t_sal/100,"Saldo")); tab.append((delivery,t_ft_p/100,"FinComp"))
    if p.get("incc_ativo",False):
        incc_m=(1+p.get("incc_anual",5)/100)**(1/12)-1
        tab=[(off,pv2*(1+incc_m)**(off-evol_start) if lbl=="Evolução" else pv2,lbl) for off,pv2,lbl in tab]

    # ─ Curva de vendas ─
    vm0=p.get("v_m0",30)/100; vm16=p.get("v_m1m6",35)/100
    vm712=p.get("v_m7m12",20)/100; vr=max(0,1-vm0-vm16-vm712)
    spm=[0.0]*N
    spm[0]=eff_su*vm0
    for m in range(1,7): spm[m]+=eff_su*vm16/6
    for m in range(7,13): spm[m]+=eff_su*vm712/6
    for m in range(13,25): spm[m]+=eff_su*vr/12

    # ─ Preço por fase ─
    f1_pct=p.get("preco_fase1_pct",100)/100; f1_meses=int(p.get("preco_lancamento_meses",3))
    inf=[0.0]*N
    for sm_ in range(N):
        if not spm[sm_]: continue
        unit_pr=pr*f1_pct if sm_<=f1_meses else pr
        cv=spm[sm_]*unit_pr
        for off,pv2,_ in tab:
            pm=sm_+off
            if pm<N: inf[pm]+=cv*pv2

    # ─ Saídas ─
    pre_pct=p.get("outros_pre",40)/100; obra_pct=p.get("outros_obra",45)/100
    ent_pct=max(0,1-pre_pct-obra_pct)
    out=[0.0]*N
    if lc>0: out[0]+=lc
    out[0]+=itb+ci
    for m in range(min(4,N)): out[m]+=std/4
    mw=[0.35,0.20,0.15,0.10,0.08,0.07,0.05]
    for m in range(min(7,N)): out[m]+=mkt*mw[m]+adm/7
    obra_curve=get_obra_curve(p)
    # INCC no custo de obra
    incc_obra=((1+p.get("incc_obra_anual",5)/100)**(1/12)-1) if p.get("incc_obra_ativo",False) else 0
    for i,frac in enumerate(obra_curve):
        m=obra_start+i
        if m<N: out[m]+=ct*frac*((1+incc_obra)**i)
    for m in range(obra_start): out[m]+=oth*pre_pct/max(1,obra_start)
    obra_dur=delivery-obra_start
    for m in range(obra_start,delivery):
        if m<N: out[m]+=oth*obra_pct/max(1,obra_dur)
    if delivery<N: out[delivery]+=oth*ent_pct+gar
    si=sum(inf) or 1
    for m in range(N): out[m]+=(inf[m]/si)*(brk+imp)

    # ─ Custos adicionais mês a mês ─
    for cost in p.get("custom_costs",[]):
        valor=float(cost.get("Valor (R$)",0) or 0)
        m_ini=max(0,int(cost.get("Mês início",0) or 0))
        m_fim=max(m_ini,int(cost.get("Mês fim",m_ini) or m_ini))
        n_m=m_fim-m_ini+1
        for m in range(m_ini,min(m_fim+1,N)): out[m]+=valor/n_m

    # ─ Financiamento de obra ─
    fin_in=[0.0]*N; fin_int=[0.0]*N; fin_elig=obra_start; outstanding=0.0
    if p.get("fin_ativo",False):
        fin_amt=ct*p.get("fin_pct",60)/100
        rate_pm=(1+p.get("fin_taxa_pa",10)/100)**(1/12)-1
        ft=p.get("fin_trigger_type","auto")
        fin_repay_months=max(0,int(p.get("fin_repay_months",0)))

        # ── Determinar mês do gatilho ──
        if ft=="manual":
            fin_elig=int(p.get("fin_start_month_manual",12))
        elif ft=="vendas":
            fsp=p.get("fin_sales_trigger_pct",30); fin_elig=N; cs_f=0
            for m in range(N):
                cs_f+=spm[m]
                if cs_f>=eff_su*fsp/100: fin_elig=m; break
        elif ft=="obra_pct":
            trig=p.get("fin_obra_trigger_pct",30)/100; fin_elig=N; cum_o=0
            for i,frac in enumerate(obra_curve):
                cum_o+=frac
                if cum_o>=trig: fin_elig=obra_start+i; break
        else:
            fin_elig=obra_start

        # ── Liberação das parcelas ──
        if ft=="manual_tranches":
            # Completamente manual: usuário define mês + valor
            for tr in p.get("fin_manual_tranches",[]):
                m=int(tr.get("Mês",0) or 0); v=float(tr.get("Valor (R$)",0) or 0)
                if 0<=m<N: fin_in[m]+=v
        else:
            # Contínuo proporcional à curva de obra a partir do gatilho
            # Primeira parcela: catch-up de tudo que evoluiu antes do gatilho
            cum_antes=0.0; cum_total=0.0; primeira=True
            for i,frac in enumerate(obra_curve):
                cum_total+=frac; month=obra_start+i
                if month<fin_elig: cum_antes=cum_total; continue
                if primeira:
                    fin_in[month]=fin_amt*cum_total  # catch-up + mês atual
                    primeira=False
                else:
                    fin_in[month]=fin_amt*frac

        # ── Juros durante a obra ──
        outstanding=0.0
        for m in range(N):
            outstanding+=fin_in[m]
            if outstanding>0 and m<delivery: fin_int[m]=outstanding*rate_pm

        # ── Amortização: plano empresário ou quitação na entrega ──
        if fin_repay_months<=0:
            if delivery<N: out[delivery]+=outstanding
        else:
            parcela=outstanding/fin_repay_months; saldo_dev=outstanding
            for offset in range(fin_repay_months):
                m=delivery+offset
                if m<N and saldo_dev>0:
                    juros_mes=saldo_dev*rate_pm
                    out[m]+=min(parcela,saldo_dev)+juros_mes
                    fin_int[m]=juros_mes
                    saldo_dev=max(0,saldo_dev-parcela)

        for m in range(N): out[m]+=fin_int[m]

    ncf=[inf[m]+fin_in[m]-out[m] for m in range(N)]
    cum=0; ccf=[]
    for c in ncf: cum+=c; ccf.append(cum)
    pb=next((m for m in range(N) if ccf[m]>=0),None)
    irm=calc_irr(ncf); ira=((1+irm)**12-1)*100
    ira=ira if np.isfinite(ira) else None
    tma_m=(1+p.get("tma",12)/100)**(1/12)-1; npv=calc_npv(ncf,tma_m)
    beu=int(np.ceil(cc/pr)) if pr else 0; bep=min(100,beu/eff_su*100) if eff_su else 0
    pico=abs(min(min(ccf),0)); aporte_m=[max(0,-v) for v in ncf]
    cs=0; adrows=[]
    for m in range(min(25,N)):
        cs+=spm[m]; adrows.append({"Mês":m,"Novas":round(spm[m]),"% vendido":round(cs/max(1,eff_su)*100)})
    lucro_un=np_/eff_su if eff_su else 0; custo_m2=tc/(u*ar) if u*ar else 0
    chartD=list(range(min(N,delivery+4)))
    evts={0:"🚀 Lançamento",obra_start:f"🔨 Início obras",delivery:"🏠 Entrega"}
    chart=[{"m":m,"label":f"M{m}","evento":evts.get(m,""),
            "receita":round(inf[m]),"custo":round(out[m]),
            "saldo":round(ncf[m]),"acumulado":round(ccf[m]),
            "aporte":round(aporte_m[m]),"fin_in":round(fin_in[m])} for m in chartD]
    return dict(pu=pu,su=su,eff_su=eff_su,pv=pv,lc=lc,itb=itb,vgv=vgv,
        cb=cb,cf_=cf_,prj=prj,ins=ins,cont=cont,ct=ct,gar=gar,ci=ci,
        mkt=mkt,brk=brk,adm=adm,std=std,oth=oth,imp=imp,
        cc=cc,tc=tc,nr=nr,gp=gp,gm=gm,np_=np_,nm=nm,
        roi=roi,roit=roit,ira=ira,npv=npv,pb=pb,
        beu=beu,bep=bep,inf=inf,out=out,ncf=ncf,ccf=ccf,
        tev=tev,adrows=adrows,vr=vr*100,evol_start=evol_start,evol_em=evol_em,
        fin_in=fin_in,fin_int=fin_int,fin_repay=outstanding,fin_elig=fin_elig,
        obra_curve=obra_curve,pico=pico,aporte_m=aporte_m,lucro_un=lucro_un,
        custo_m2=custo_m2,t_known=t_known,t_mn_n=t_mn_n,t_sm_n=t_sm_n,t_an_n=t_an_n,
        obra_start=obra_start,delivery=delivery,N=N,chart=chart,chartD=chartD,
        pr=pr,ar=ar,distrato=distrato)

# ── Sensibilidade ─────────────────────────────────────────────────
SVARS=[("Preço médio","avg_price","rel"),("Custo/m²","cost_per_sqm","rel"),
       ("BDI","const_fee_pct","rel"),("Vel. vendas M0","v_m0","abs"),
       ("Marketing","marketing_pct","rel"),("Corretagem","brokerage_pct","rel")]
def sens_table(p):
    base=compute(p); rows=[]
    for nm,key,tp in SVARS:
        row={"Variável":nm,"Base":pct(base["nm"],1)}
        for chg in [-20,-10,-5,5,10,20]:
            pt={**p,key:p[key]*(1+chg/100) if tp=="rel" else max(0,p[key]+chg)}
            row[f"{'+' if chg>0 else ''}{chg}%"]=pct(compute(pt)["nm"],1)
        rows.append(row)
    return pd.DataFrame(rows)
def tornado(p):
    base_nm=compute(p)["nm"]; data=[]
    for nm,key,tp in SVARS:
        ph={**p,key:p[key]*1.20 if tp=="rel" else p[key]+20}
        pl={**p,key:p[key]*0.80 if tp=="rel" else max(0,p[key]-20)}
        hi=max(compute(ph)["nm"],compute(pl)["nm"])-base_nm
        lo=min(compute(ph)["nm"],compute(pl)["nm"])-base_nm
        data.append({"nm":nm,"lo":lo,"hi":hi,"rng":hi-lo})
    return sorted(data,key=lambda x:x["rng"],reverse=True)
def get_scenario(p,tipo):
    sp={**p}
    if tipo=="Pessimista":
        sp["avg_price"]=int(p["avg_price"]*0.90); sp["cost_per_sqm"]=int(p["cost_per_sqm"]*1.10)
        sp["v_m0"]=max(10,p.get("v_m0",30)-20); sp["v_m1m6"]=max(10,p.get("v_m1m6",35)-15)
    elif tipo=="Otimista":
        sp["avg_price"]=int(p["avg_price"]*1.10); sp["cost_per_sqm"]=int(p["cost_per_sqm"]*0.95)
        sp["v_m0"]=min(95,p.get("v_m0",30)+20); sp["v_m1m6"]=min(95,p.get("v_m1m6",35)+15)
    return compute(sp)

# ── Validações ────────────────────────────────────────────────────
def validar(p,r):
    w=[]
    if p.get("cost_per_sqm",0)<800: w.append("⚠️ Custo/m² abaixo de R$ 800 — verifique o padrão construtivo")
    if p.get("cost_per_sqm",0)>6500: w.append("⚠️ Custo/m² acima de R$ 6.500 — típico de padrão alto/AA")
    if p.get("marketing_pct",0)>8: w.append("⚠️ Marketing acima de 8% do VGV é atípico")
    if r["nm"]>40: w.append("⚠️ Margem acima de 40% — revise as premissas de custo")
    if r["nm"]<0: w.append("🔴 Projeto com prejuízo nas premissas atuais")
    if r["t_known"]>100: w.append("🔴 Tabela de vendas soma mais de 100%")
    if p.get("distrato_pct",0)>15: w.append("⚠️ Distrato acima de 15% — cenário pessimista de retenção")
    return w

# ── Parecer automático ─────────────────────────────────────────────
def parecer(r,p):
    viavel=r["nm"]>=10 and (r["ira"] or 0)>=p["tma"] and r["npv"]>=0
    status="✅ VIÁVEL" if viavel else("⚠️ ATENÇÃO" if r["nm"]>=0 else "🔴 INVIÁVEL")
    lines=[]
    if r["ira"]:
        diff=r["ira"]-p["tma"]
        lines.append(f"TIR de **{pct(r['ira'])}** {'supera' if diff>=0 else 'fica abaixo d'}a TMA em **{abs(diff):.1f} p.p.**")
    lines.append(f"Margem líquida de **{pct(r['nm'])}** sobre o VGV")
    lines.append(f"VPL **{brl(r['npv'])}** ao custo de oportunidade de {p['tma']}% a.a.")
    lines.append(f"Payback no **mês {r['pb']}**" if r["pb"] else "Payback **não atingido** no ciclo")
    lines.append(f"Break-even em **{pct(r['bep'])}** das unidades — margem de segurança de **{pct(max(0,100-r['bep']))}**")
    lines.append(f"Pico de aporte: **{brl(r['pico'])}** ao longo do ciclo")
    if p.get("distrato_pct",0)>0: lines.append(f"⚠️ Distrato de **{pct(p['distrato_pct'])}** aplicado — VGV efetivo: {brl(r['vgv'])}")
    if p.get("aprovacao_meses",6)!=6: lines.append(f"📅 Aprovação estimada em **{p['aprovacao_meses']} meses** — entrega projetada no **mês {r['delivery']}**")
    return status, lines

# ── Export Excel ──────────────────────────────────────────────────
def export_excel(p,r):
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine="xlsxwriter") as wr:
        pd.DataFrame([("Empreendimento",p["name"]),("VGV",r["vgv"]),("Custo Total",r["tc"]),
            ("Lucro",r["np_"]),("Margem %",r["nm"]),("ROI %",r["roi"]),("TIR %",r["ira"]),
            ("VPL",r["npv"]),("Payback",r["pb"]),("Pico aporte",r["pico"]),
            ("Entrega (mês)",r["delivery"])],columns=["Indicador","Valor"]).to_excel(wr,sheet_name="Resumo",index=False)
        pd.DataFrame(r["chart"]).to_excel(wr,sheet_name="Fluxo de Caixa",index=False)
        dre=[("VGV",r["vgv"]),("(-) Corretagem",-r["brk"]),("(-) Impostos",-r["imp"]),("Rec. Líquida",r["nr"]),
             ("(-) Permuta",-r["pv"]),("(-) Terreno",-r["lc"]),("(-) ITBI",-r["itb"]),("(-) Incorp.",-r["ci"]),
             ("(-) Construção",-r["cb"]),("(-) BDI",-r["cf_"]),("(-) Projetos",-r["prj"]),("(-) INSS",-r["ins"]),
             ("(-) Contingência",-r["cont"]),("(-) Garantia",-r["gar"]),("(-) Marketing",-r["mkt"]),
             ("(-) Stand",-r["std"]),("(-) Adm",-r["adm"]),("(-) Outros",-r["oth"]),("LUCRO",r["np_"])]
        pd.DataFrame(dre,columns=["Descrição","R$"]).to_excel(wr,sheet_name="DRE",index=False)
    buf.seek(0); return buf

# ── Defaults ──────────────────────────────────────────────────────
DEF=dict(
    name="Residencial Aurora",units=80,avg_price=450000,avg_area=65,
    use_mix=False,mix=[],aprovacao_meses=6,
    land_type="Dinheiro",land=3200000,perm_units=0,itbi_pct=2.5,
    cost_per_sqm=2200,const_fee_pct=12.0,projetos_pct=3.5,inss_pct=4.5,
    contingencia_pct=5.0,garantia_pct=1.0,custo_incorp=50000,
    marketing_pct=3.0,sales_stand=180000,brokerage_pct=4.0,admin_pct=5.0,
    other_costs=80000,imposto_tipo="Nenhum",tma=12.0,
    t_sinal=5,t_mensais_n=5,t_mensais_pct=10,t_semestrais_n=0,t_semestrais_pct=0,
    t_anuais_n=0,t_anuais_pct=0,t_financiamento_pct=30,t_saldo=25,
    v_m0=30,v_m1m6=35,v_m7m12=20,incc_ativo=False,incc_anual=5.0,
    distrato_pct=0,preco_fase1_pct=100,preco_lancamento_meses=3,
    obra_curve_type="scurve",obra_curve_sem=[100/6]*6,outros_pre=40,outros_obra=45,
    incc_obra_ativo=False,incc_obra_anual=5.0,
    fin_ativo=False,fin_pct=60,fin_taxa_pa=10.0,
    fin_trigger_type="auto",fin_sales_trigger_pct=30,fin_obra_trigger_pct=30,
    fin_start_month_manual=12,fin_repay_months=0,
    fin_manual_tranches=[],
    custom_costs=[],
)
if "projects" not in st.session_state:
    st.session_state.projects=[
        {**DEF},
        {**DEF,"name":"Torre Horizonte","units":120,"avg_price":680000,"avg_area":85,"land":5000000,"cost_per_sqm":2500,"imposto_tipo":"RET"},
        {**DEF,"name":"Park Residence","units":40,"avg_price":320000,"avg_area":50,"land":800000,"cost_per_sqm":1900,"land_type":"Misto","perm_units":5},
    ]
if "sel" not in st.session_state: st.session_state.sel=0

# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏗️ Viabilidade"); st.caption("Projetos Imobiliários"); st.divider()
    names=[p["name"] for p in st.session_state.projects]
    sel=st.selectbox("Empreendimento",names,index=st.session_state.sel)
    ni=names.index(sel)
    if ni!=st.session_state.sel: st.session_state.sel=ni; st.rerun()
    c1,c2=st.columns(2)
    with c1:
        if st.button("➕ Novo",use_container_width=True):
            n=len(st.session_state.projects)+1
            st.session_state.projects.append({**DEF,"name":f"Empreendimento {n}"})
            st.session_state.sel=len(st.session_state.projects)-1; st.rerun()
    with c2:
        if len(st.session_state.projects)>1 and st.button("🗑️ Deletar",use_container_width=True):
            st.session_state.projects.pop(st.session_state.sel)
            st.session_state.sel=max(0,st.session_state.sel-1); st.rerun()
    st.divider()
    p=st.session_state.projects[st.session_state.sel]; r0=compute(p)
    st.metric("VGV",brlk(r0["vgv"])); c1,c2=st.columns(2)
    c1.metric("Margem",pct(r0["nm"])); c2.metric("TIR a.a.",pct(r0["ira"]) if r0["ira"] else "—")
    st.metric("Lucro",brlk(r0["np_"])); st.metric("Pico aporte",brlk(r0["pico"]))
    st.divider()
    st.caption("**💾 Salvar / Carregar projetos**")
    json_str=json.dumps(st.session_state.projects,ensure_ascii=False,default=str)
    st.download_button("💾 Exportar projetos (.json)",json_str,"projetos_viabilidade.json","application/json",use_container_width=True)
    uploaded=st.file_uploader("📂 Importar projetos",type="json",label_visibility="collapsed")
    if uploaded:
        try:
            st.session_state.projects=json.load(uploaded); st.session_state.sel=0; st.rerun()
        except: st.error("Arquivo inválido")
    st.divider()
    st.markdown("<div style='text-align:center;font-size:10px;color:#4a6880'>Análise de Viabilidade<br><strong style='color:#6a92b8'>Alexandre Bomfim</strong></div>",unsafe_allow_html=True)

p=st.session_state.projects[st.session_state.sel]
st.markdown(f"### 🏗️ Análise de Viabilidade de Projetos Imobiliários &nbsp;·&nbsp; <span style='color:#888;font-size:16px;font-weight:400'>{p['name']}</span>",unsafe_allow_html=True)
tabs=st.tabs(["📋 Projeto","💰 Custos","🏗️ Curvas & Fin.","📊 Vendas","📈 Fluxo & Aporte","🔬 Sensibilidade","🎯 Indicadores","📊 Comparativo"])
t1,t2,t3,t4,t5,t6,t7,t8=tabs

# ════ PROJETO ════════════════════════════════════════════════════
with t1:
    st.subheader("Identificação")
    c1,c2,c3,c4=st.columns(4)
    p["name"]=c1.text_input("Nome",value=p["name"])
    p["units"]=c2.number_input("Nº unidades",value=p["units"],min_value=1,step=1)
    p["avg_price"]=c3.number_input("Preço médio (R$)",value=p["avg_price"],min_value=10000,step=10000)
    p["avg_area"]=c4.number_input("Área média (m²)",value=float(p["avg_area"]),min_value=20.0,step=1.0)
    st.divider()
    c1,c2=st.columns(2)
    with c1:
        st.subheader("Parâmetros")
        p["tma"]=st.number_input("TMA (% a.a.)",value=float(p["tma"]),min_value=0.0,step=0.5,format="%.1f",help="Taxa Mínima de Atratividade — custo de oportunidade do capital. Se TIR > TMA, o projeto cria valor.")
        p["aprovacao_meses"]=st.number_input("Meses até início das obras (aprovação)",value=int(p.get("aprovacao_meses",6)),min_value=1,max_value=36,step=1,help="Tempo de aprovação municipal, licenças e pré-obras. Padrão: 6 meses. Projetos complexos podem levar 12-24 meses.")
        r=compute(p)
        st.info(f"📅 Com {p['aprovacao_meses']} meses de aprovação, a entrega está projetada para o **mês {r['delivery']}**")
    with c2:
        st.subheader("🏢 Mix de tipologias")
        p["use_mix"]=st.toggle("Ativar mix de unidades (substitui preço/área médios)",value=bool(p.get("use_mix",False)))
        if p["use_mix"]:
            df_mix=pd.DataFrame(p.get("mix",[
                {"Tipo":"Studio","Qtd":0,"Preco":280000,"Area":35},
                {"Tipo":"2 Quartos","Qtd":int(p["units"]),"Preco":int(p["avg_price"]),"Area":int(p["avg_area"])},
                {"Tipo":"3 Quartos","Qtd":0,"Preco":650000,"Area":90},
                {"Tipo":"Cobertura","Qtd":0,"Preco":950000,"Area":130},
            ]))
            edited=st.data_editor(df_mix,hide_index=True,use_container_width=True,num_rows="dynamic",
                column_config={"Preco":st.column_config.NumberColumn("Preço (R$)",format="R$ %d"),"Area":st.column_config.NumberColumn("Área (m²)",format="%d m²"),"Qtd":st.column_config.NumberColumn("Qtd",format="%d")})
            p["mix"]=edited.to_dict("records")
            mix_rows=[r_ for r_ in p["mix"] if r_.get("Qtd",0)>0]
            if mix_rows:
                tu=sum(r_["Qtd"] for r_ in mix_rows); tvgv=sum(r_["Qtd"]*r_["Preco"] for r_ in mix_rows)
                ta_=sum(r_["Qtd"]*r_["Area"] for r_ in mix_rows)
                ca,cb,cc,cd=st.columns(4)
                ca.metric("Unidades",str(tu)); cb.metric("VGV total",brlk(tvgv))
                cc.metric("Preço médio",brlk(tvgv/max(1,tu))); cd.metric("Área média",f"{ta_/max(1,tu):.0f} m²")
        else:
            r=compute(p)
            ca,cb=st.columns(2)
            ca.markdown(card("VGV bruto",brlk(p["units"]*p["avg_price"]),"#1b5e20"),unsafe_allow_html=True)
            cb.markdown(card("Área total",f"{p['units']*p['avg_area']:,.0f} m²","#37474f"),unsafe_allow_html=True)

# ════ CUSTOS ═════════════════════════════════════════════════════
with t2:
    c1,c2=st.columns([1,1])
    with c1:
        with st.expander("🏚️ Terreno",expanded=True):
            lo=["Dinheiro","Permuta Física","Misto"]
            p["land_type"]=st.radio("Aquisição",lo,index=lo.index(p.get("land_type","Dinheiro")),horizontal=True)
            if p["land_type"] in ["Dinheiro","Misto"]:
                p["land"]=st.number_input("Valor cash (R$)" if p["land_type"]=="Misto" else "Custo (R$)",value=int(p.get("land",3200000)),min_value=0,step=50000)
            if p["land_type"] in ["Permuta Física","Misto"]:
                p["perm_units"]=st.number_input("Unidades em permuta",value=int(p.get("perm_units",0)),min_value=0,max_value=p["units"]-1,step=1)
                r_=compute(p); st.success(f"Permuta: **{brl(r_['pv'])}** · Vendáveis: {r_['su']} · VGV: {brl(r_['vgv'])}")
            p["itbi_pct"]=st.number_input("ITBI + Registro (%)",value=float(p.get("itbi_pct",2.5)),min_value=0.0,step=0.1,format="%.1f")
            p["custo_incorp"]=st.number_input("Despesas de incorporação (R$)",value=int(p.get("custo_incorp",50000)),min_value=0,step=5000)
        with st.expander("🔨 Construção",expanded=True):
            p["cost_per_sqm"]=st.number_input("Custo/m² (R$)",value=int(p["cost_per_sqm"]),min_value=500,step=50,help="Referência: CUB/m² da sua região × padrão construtivo")
            p["const_fee_pct"]=st.number_input("BDI / Taxa de obra (%)",value=float(p.get("const_fee_pct",12)),min_value=0.0,step=0.5,format="%.1f")
            p["projetos_pct"]=st.number_input("Projetos e engenharia (%)",value=float(p.get("projetos_pct",3.5)),min_value=0.0,step=0.5,format="%.1f")
            p["inss_pct"]=st.number_input("INSS da obra (%)",value=float(p.get("inss_pct",4.5)),min_value=0.0,step=0.1,format="%.1f")
            p["contingencia_pct"]=st.number_input("Contingência (%)",value=float(p.get("contingencia_pct",5)),min_value=0.0,step=0.5,format="%.1f",help="Reserva para imprevistos — padrão do setor: 5-10%")
            p["garantia_pct"]=st.number_input("Garantia pós-entrega (%)",value=float(p.get("garantia_pct",1)),min_value=0.0,step=0.5,format="%.1f")
        with st.expander("📣 Comercialização",expanded=True):
            p["marketing_pct"]=st.number_input("Marketing (% VGV)",value=float(p.get("marketing_pct",3)),min_value=0.0,step=0.5,format="%.1f")
            p["sales_stand"]=st.number_input("Stand de vendas (R$)",value=int(p.get("sales_stand",180000)),min_value=0,step=10000)
            p["brokerage_pct"]=st.number_input("Corretagem (% VGV)",value=float(p.get("brokerage_pct",4)),min_value=0.0,step=0.5,format="%.1f")
            p["admin_pct"]=st.number_input("Adm. incorporadora (% VGV)",value=float(p.get("admin_pct",5)),min_value=0.0,step=0.5,format="%.1f")
            p["other_costs"]=st.number_input("Outros (R$)",value=int(p.get("other_costs",80000)),min_value=0,step=10000)
        with st.expander("🧾 Regime tributário",expanded=False):
            imp_opts=["Nenhum","RET","Lucro Presumido","Simples Nacional"]
            p["imposto_tipo"]=st.radio("Regime",imp_opts,index=imp_opts.index(p.get("imposto_tipo","Nenhum")),horizontal=True)
            st.caption({"Nenhum":"Não modelar impostos","RET":"4% sobre receita (MCMV e outros)","Lucro Presumido":"~6,73% (IRPJ+CSLL+PIS+COFINS)","Simples Nacional":"~3% sobre receita"}[p["imposto_tipo"]])
        with st.expander("➕ Custos adicionais (mês a mês)",expanded=False):
            st.caption("Adicione custos específicos distribuídos em um período. Ex: publicidade de lançamento, honorários, etc.")
            _cc_default=p.get("custom_costs",[]) or []
            if not _cc_default: _cc_default=[{"Nome":"","Valor (R$)":0,"Mês início":0,"Mês fim":3}]
            _cc_df=pd.DataFrame(_cc_default)
            _cc_edit=st.data_editor(_cc_df,hide_index=True,num_rows="dynamic",use_container_width=True,
                column_config={
                    "Valor (R$)":st.column_config.NumberColumn(format="R$ %d",min_value=0,step=1000),
                    "Mês início":st.column_config.NumberColumn(format="M%d",min_value=0,max_value=60),
                    "Mês fim":st.column_config.NumberColumn(format="M%d",min_value=0,max_value=60),
                })
            p["custom_costs"]=_cc_edit.to_dict("records")
            _cc_total=sum(float(c.get("Valor (R$)",0) or 0) for c in p["custom_costs"])
            if _cc_total>0: st.info(f"Total de custos adicionais: **{brl(_cc_total)}**")
    with c2:
        r=compute(p)
        # Validações
        warns=validar(p,r)
        for w in warns: st.warning(w)
        st.subheader("Composição dos custos")
        items=[]
        if r["lc"]>0: items.append(("Terreno cash",r["lc"],"#c8a245"))
        if r["pv"]>0: items.append(("Permuta",r["pv"],"#f0a020"))
        if r["itb"]>0: items.append(("ITBI+Registro",r["itb"],"#e8b44a"))
        if r["ci"]>0: items.append(("Incorporação",r["ci"],"#ffa040"))
        items.append(("Construção base",r["cb"],"#4fa8f5"))
        if r["cf_"]>0: items.append(("BDI",r["cf_"],"#7b8ff0"))
        if r["prj"]>0: items.append(("Projetos",r["prj"],"#8b78f0"))
        if r["ins"]>0: items.append(("INSS",r["ins"],"#b068d4"))
        if r["cont"]>0: items.append(("Contingência",r["cont"],"#9c27b0"))
        if r["gar"]>0: items.append(("Garantia",r["gar"],"#ce93d8"))
        if r["mkt"]>0: items.append(("Marketing",r["mkt"],"#888"))
        if r["std"]>0: items.append(("Stand",r["std"],"#0ccf88"))
        if r["brk"]>0: items.append(("Corretagem",r["brk"],"#f04848"))
        if r["adm"]>0: items.append(("Adm.",r["adm"],"#f0c040"))
        if r["imp"]>0: items.append(("Impostos",r["imp"],"#e53935"))
        if r["oth"]>0: items.append(("Outros",r["oth"],"#aaa"))
        fig=go.Figure(go.Bar(x=[x[1] for x in items],y=[x[0] for x in items],orientation="h",
            marker_color=[x[2] for x in items],text=[f"{x[1]/r['tc']*100:.0f}%  {brlk(x[1])}" for x in items],
            textposition="outside",textfont=dict(size=10)))
        fig.update_layout(height=max(300,len(items)*30+60),margin=dict(l=0,r=130,t=10,b=10),
            plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=True,gridcolor="#eee",showticklabels=False),yaxis=dict(autorange="reversed"),showlegend=False)
        st.plotly_chart(fig,use_container_width=True)
        ca,cb2,cc=st.columns(3)
        ca.markdown(card("VGV",brlk(r["vgv"]),"#1b5e20"),unsafe_allow_html=True)
        cb2.markdown(card("Custo total",brlk(r["tc"]),"#b71c1c"),unsafe_allow_html=True)
        cc.markdown(card("Lucro",brlk(r["np_"]),"#1b5e20" if r["np_"]>=0 else "#b71c1c",pct(r["nm"])),unsafe_allow_html=True)

# ════ CURVAS & FINANCIAMENTO ══════════════════════════════════════
with t3:
    c1,c2=st.columns(2)
    with c1:
        st.subheader("🏗️ Curva de desembolso de obras")
        ct_opts=["S-Curva (recomendado)","Linear (igual)","Manual por semestre"]
        ct_map={"S-Curva (recomendado)":"scurve","Linear (igual)":"linear","Manual por semestre":"manual"}
        ct_inv={v:k for k,v in ct_map.items()}
        chosen=st.radio("Tipo",ct_opts,index=ct_opts.index(ct_inv.get(p.get("obra_curve_type","scurve"),"S-Curva (recomendado)")),horizontal=True)
        p["obra_curve_type"]=ct_map[chosen]
        if p["obra_curve_type"]=="manual":
            df_sem=pd.DataFrame({"Semestre":[f"Sem {i+1}" for i in range(6)],"% do custo":[round(v,2) for v in p.get("obra_curve_sem",[100/6]*6)]})
            edited=st.data_editor(df_sem,hide_index=True,use_container_width=True,
                column_config={"% do custo":st.column_config.NumberColumn(format="%.2f",min_value=0,max_value=100)})
            p["obra_curve_sem"]=edited["% do custo"].tolist()
            ts_=sum(p["obra_curve_sem"])
            if abs(ts_-100)>0.5: st.error(f"⚠️ Soma: {ts_:.1f}% — deve ser 100%")
            else: st.success(f"✅ {ts_:.1f}%")
        r=compute(p); obra_s=r["obra_start"]; ms_o=list(range(obra_s,obra_s+36))
        fig_o=make_subplots(specs=[[{"secondary_y":True}]])
        fig_o.add_trace(go.Bar(x=ms_o,y=[r["obra_curve"][i]*100 for i in range(len(ms_o))],name="% mensal",marker_color="#4fa8f5",opacity=0.8),secondary_y=False)
        fig_o.add_trace(go.Scatter(x=ms_o,y=np.cumsum([r["obra_curve"][i]*100 for i in range(len(ms_o))]).tolist(),name="% acumulado",line=dict(color="#f0a020",width=2)),secondary_y=True)
        fig_o.update_layout(height=210,margin=dict(l=0,r=0,t=5,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",legend=dict(orientation="h",y=-0.3))
        st.plotly_chart(fig_o,use_container_width=True)

        st.subheader("📈 INCC no custo de obra")
        p["incc_obra_ativo"]=st.toggle("Corrigir desembolso de obra pelo INCC",value=bool(p.get("incc_obra_ativo",False)),help="O custo de cada mês de obra é corrigido pelo INCC acumulado desde o início — aumenta o custo total real")
        if p["incc_obra_ativo"]:
            p["incc_obra_anual"]=st.number_input("INCC anual estimado (%)",value=float(p.get("incc_obra_anual",5)),min_value=0.0,step=0.5,format="%.1f")
            r=compute(p)
            custo_s_incc=p["units"]*p["avg_area"]*p["cost_per_sqm"]*(1+p.get("const_fee_pct",12)/100+p.get("projetos_pct",3.5)/100+p.get("inss_pct",4.5)/100+p.get("contingencia_pct",5)/100)
            st.info(f"Com INCC de {pct(p['incc_obra_anual'])} a.a., o custo total de obras sobe para aprox. **{brl(sum(r['out'][r['obra_start']:r['delivery']]))}** vs {brl(custo_s_incc)} sem correção.")
        st.subheader("💸 Distribuição de outros custos")
        p["outros_pre"]=st.slider("Pré-lançamento (%)",0,100,int(p.get("outros_pre",40)),5)
        p["outros_obra"]=st.slider("Fase de obras (%)",0,100,int(p.get("outros_obra",45)),5)
        o_ent=max(0,100-p["outros_pre"]-p["outros_obra"])
        if p["outros_pre"]+p["outros_obra"]>100: st.error("Soma excede 100%")
        else: st.success(f"Entrega (auto): **{o_ent}%**")
    with c2:
        st.subheader("🏦 Financiamento de obra")
        p["fin_ativo"]=st.toggle("Ativar financiamento de obra",value=bool(p.get("fin_ativo",False)))
        if p["fin_ativo"]:
            ca,cb=st.columns(2)
            p["fin_pct"]=ca.number_input("% da obra financiada",value=int(p.get("fin_pct",60)),min_value=0,max_value=90,step=5)
            p["fin_taxa_pa"]=cb.number_input("Juros (% a.a.)",value=float(p.get("fin_taxa_pa",10)),min_value=0.0,step=0.5,format="%.1f")

            st.markdown("**🎯 Gatilho de liberação**")
            st.caption("Uma vez atingido o gatilho, o banco libera mensalmente proporcional ao avanço físico da obra até o final.")
            trig_opts=["Automático (início das obras)","% de vendas (VSO)","% de evolução de obra","Mês fixo (manual)","Tranches manuais"]
            trig_map={"Automático (início das obras)":"auto","% de vendas (VSO)":"vendas","% de evolução de obra":"obra_pct","Mês fixo (manual)":"manual","Tranches manuais":"manual_tranches"}
            trig_inv={v:k for k,v in trig_map.items()}
            chosen_t=st.radio("",trig_opts,index=trig_opts.index(trig_inv.get(p.get("fin_trigger_type","auto"),"Automático (início das obras)")),horizontal=False,label_visibility="collapsed")
            p["fin_trigger_type"]=trig_map[chosen_t]

            if p["fin_trigger_type"]=="vendas":
                p["fin_sales_trigger_pct"]=st.slider("% mínimo de vendas (VSO) para liberar",10,100,int(p.get("fin_sales_trigger_pct",30)),5)
                r=compute(p); elig=r["fin_elig"]
                if elig<r["N"]: st.success(f"✅ Gatilho atingido no **mês {elig}** — banco começa a liberar a partir daí")
                else: st.error("⚠️ VSO nunca atingido com a absorção atual")
            elif p["fin_trigger_type"]=="obra_pct":
                p["fin_obra_trigger_pct"]=st.slider("% de evolução de obra para liberar",10,80,int(p.get("fin_obra_trigger_pct",30)),5)
                r=compute(p); elig=r["fin_elig"]
                if elig<r["N"]: st.success(f"✅ Gatilho de {p['fin_obra_trigger_pct']}% de obra atingido no **mês {elig}**")
                else: st.error("⚠️ Gatilho de obra não atingido no ciclo")
            elif p["fin_trigger_type"]=="manual":
                p["fin_start_month_manual"]=st.number_input("Mês de início das liberações",value=int(p.get("fin_start_month_manual",12)),min_value=0,max_value=48,step=1)
                st.caption("A partir desse mês, liberações proporcionais ao avanço físico de obra.")
            elif p["fin_trigger_type"]=="manual_tranches":
                st.caption("Defina exatamente quando e quanto o banco libera em cada tranche.")
                _tr_default=p.get("fin_manual_tranches",[]) or [{"Mês":8,"Valor (R$)":500000},{"Mês":16,"Valor (R$)":500000},{"Mês":24,"Valor (R$)":500000}]
                _tr_df=pd.DataFrame(_tr_default)
                _tr_edit=st.data_editor(_tr_df,hide_index=True,num_rows="dynamic",use_container_width=True,
                    column_config={"Mês":st.column_config.NumberColumn(format="M%d",min_value=0,max_value=60),
                                   "Valor (R$)":st.column_config.NumberColumn(format="R$ %d",min_value=0,step=50000)})
                p["fin_manual_tranches"]=_tr_edit.to_dict("records")
                _tr_total=sum(float(t.get("Valor (R$)",0) or 0) for t in p["fin_manual_tranches"])
                st.info(f"Total manual: **{brl(_tr_total)}**")
            else:
                st.info("🔄 Banco libera mensalmente proporcional ao avanço de obra a partir do início das obras.")

            st.divider()
            st.markdown("**🏦 Plano empresário — amortização pós-entrega**")
            p["fin_repay_months"]=st.number_input(
                "Prazo de amortização após entrega (meses)",
                value=int(p.get("fin_repay_months",0)),min_value=0,max_value=36,step=1,
                help="0 = quita tudo na entrega. 12 = amortiza em 12 meses após entrega (financiado pelos contratos de compra e venda dos compradores).")
            if p.get("fin_repay_months",0)>0:
                r=compute(p)
                st.caption(f"Amortização de {brl(sum(r['fin_in']))} em {p['fin_repay_months']} parcelas mensais a partir do mês {r.get('delivery',44)}.")

            r=compute(p)
            ca,cb=st.columns(2)
            ca.markdown(card("Total captado",brl(sum(r["fin_in"])),"#1565c0","Do banco","#e3f2fd"),unsafe_allow_html=True)
            cb.markdown(card("Juros totais",brl(sum(r["fin_int"])),"#e65100","Obra + amortização","#fff3e0"),unsafe_allow_html=True)
            tr_d=[(m,brl(v)) for m,v in enumerate(r["fin_in"]) if v>0]
            if tr_d:
                st.caption("**Calendário de liberações:**")
                st.dataframe(pd.DataFrame(tr_d,columns=["Mês","Liberado"]),hide_index=True,use_container_width=True)
        else:
            r=compute(p); st.info("💡 Ative para modelar crédito associativo, SFH ou CCB.")
        st.divider()
        r=compute(p)
        st.markdown(card("Pico de aporte",brl(r["pico"]),"#c62828" if r["pico"]>0 else "#2e7d32","Máx. equity necessário","#fce4e4" if r["pico"]>0 else "#e8f5e9"),unsafe_allow_html=True)

# ════ VENDAS ═════════════════════════════════════════════════════
with t4:
    c1,c2=st.columns(2)
    with c1:
        st.subheader("📋 Tabela de vendas")
        p["t_sinal"]=st.number_input("Sinal (%)",value=int(p.get("t_sinal",5)),min_value=0,max_value=30,step=1)
        st.markdown("**Entrada parcelada**")
        ca,cb=st.columns(2)
        p["t_mensais_n"]=ca.number_input("Mensais — nº",value=int(p.get("t_mensais_n",5)),min_value=0,max_value=60,step=1)
        p["t_mensais_pct"]=cb.number_input("Mensais — total (%)",value=int(p.get("t_mensais_pct",10)),min_value=0,max_value=60,step=1)
        ca,cb=st.columns(2)
        p["t_semestrais_n"]=ca.number_input("Semestrais — nº",value=int(p.get("t_semestrais_n",0)),min_value=0,max_value=10,step=1)
        p["t_semestrais_pct"]=cb.number_input("Semestrais — total (%)",value=int(p.get("t_semestrais_pct",0)),min_value=0,max_value=50,step=1)
        ca,cb=st.columns(2)
        p["t_anuais_n"]=ca.number_input("Anuais — nº",value=int(p.get("t_anuais_n",0)),min_value=0,max_value=5,step=1)
        p["t_anuais_pct"]=cb.number_input("Anuais — total (%)",value=int(p.get("t_anuais_pct",0)),min_value=0,max_value=50,step=1)
        st.markdown("**Na entrega**")
        ca,cb=st.columns(2)
        p["t_financiamento_pct"]=ca.number_input("Financiamento bancário (%)",value=int(p.get("t_financiamento_pct",30)),min_value=0,max_value=90,step=1,help="Parte do comprador financiada via banco (FGTS, SFH etc.)")
        p["t_saldo"]=cb.number_input("Saldo em caixa (%)",value=int(p.get("t_saldo",25)),min_value=0,max_value=90,step=1)
        p["incc_ativo"]=st.toggle("Correção INCC na evolução",value=bool(p.get("incc_ativo",False)))
        if p["incc_ativo"]:
            p["incc_anual"]=st.number_input("INCC anual (%)",value=float(p.get("incc_anual",5)),min_value=0.0,step=0.5,format="%.1f")
        r=compute(p); tknown=r["t_known"]
        if tknown>100: st.error(f"⚠️ Soma {tknown:.0f}% excede 100%")
        else: st.success(f"✅ Evolução (auto): **{pct(r['tev'],1)}** em {r['evol_em']} meses = {pct(r['tev']/max(1,r['evol_em']),3)}/mês")
        st.divider()
        # Tabela resumo
        rows=[]
        rows.append({"Componente":"🔑 Sinal","Quando":"M0","%":f"{p.get('t_sinal',5)}%","R$/un":brl(r["pr"]*p.get("t_sinal",5)/100)})
        if p.get("t_mensais_n",5)>0: rows.append({"Componente":f"📅 Mensais ({p.get('t_mensais_n',5)}×)","Quando":f"M1–M{p.get('t_mensais_n',5)}","%":f"{p.get('t_mensais_pct',10)}%","R$/un":brl(r["pr"]*p.get("t_mensais_pct",10)/100/max(1,p.get("t_mensais_n",5)))+"/m"})
        if p.get("t_semestrais_n",0)>0: rows.append({"Componente":f"📆 Semestrais ({p.get('t_semestrais_n',0)}×)","Quando":"M6,12...","%" :f"{p.get('t_semestrais_pct',0)}%","R$/un":brl(r["pr"]*p.get("t_semestrais_pct",0)/100/max(1,p.get("t_semestrais_n",0)))})
        if p.get("t_anuais_n",0)>0: rows.append({"Componente":f"📅 Anuais ({p.get('t_anuais_n',0)}×)","Quando":"M12,24...","%" :f"{p.get('t_anuais_pct',0)}%","R$/un":brl(r["pr"]*p.get("t_anuais_pct",0)/100/max(1,p.get("t_anuais_n",0)))})
        if r["evol_em"]>0: rows.append({"Componente":f"🏗️ Evolução ({r['evol_em']}×)","Quando":f"M{r['evol_start']}–M{r['delivery']-1}","%":pct(r["tev"],1),"R$/un":brl(r["pr"]*r["tev"]/100/max(1,r["evol_em"]))+"/m"})
        if p.get("t_financiamento_pct",30)>0: rows.append({"Componente":"🏦 Financiamento","Quando":f"M{r['delivery']}","%":f"{p.get('t_financiamento_pct',30)}%","R$/un":brl(r["pr"]*p.get("t_financiamento_pct",30)/100)})
        if p.get("t_saldo",25)>0: rows.append({"Componente":"💰 Saldo","Quando":f"M{r['delivery']}","%":f"{p.get('t_saldo',25)}%","R$/un":brl(r["pr"]*p.get("t_saldo",25)/100)})
        rows.append({"Componente":"━ TOTAL","Quando":"—","%":f"{min(100,tknown+r['tev']):.0f}%","R$/un":brl(r["pr"])})
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    with c2:
        st.subheader("📈 Absorção de vendas")
        p["v_m0"]=st.slider("Lançamento M0 (%)",0,100,int(p.get("v_m0",30)),5)
        p["v_m1m6"]=st.slider("Pós-lançamento M1–6 (%)",0,100,int(p.get("v_m1m6",35)),5)
        p["v_m7m12"]=st.slider("Maturação M7–12 (%)",0,100,int(p.get("v_m7m12",20)),5)
        r=compute(p); vs=p.get("v_m0",30)+p.get("v_m1m6",35)+p.get("v_m7m12",20); vrs=max(0,100-vs)
        if vs>100: st.error(f"⚠️ Soma {vs}%")
        else: st.success(f"✅ M13–24 (auto): **{vrs}%** — {round(r['eff_su']*vrs/100)} un.")
        ad=pd.DataFrame(r["adrows"])
        fig_a=make_subplots(specs=[[{"secondary_y":True}]])
        fig_a.add_trace(go.Bar(x=ad["Mês"],y=ad["Novas"],name="Novas vendas",marker_color="#c8a245",opacity=0.75),secondary_y=False)
        fig_a.add_trace(go.Scatter(x=ad["Mês"],y=ad["% vendido"],name="% vendido",line=dict(color="#0ccf88",width=2)),secondary_y=True)
        fig_a.update_layout(height=240,margin=dict(l=0,r=0,t=10,b=30),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",legend=dict(orientation="h",y=-0.2))
        fig_a.update_yaxes(title_text="Unidades",secondary_y=False); fig_a.update_yaxes(title_text="% Vendido",secondary_y=True,range=[0,110])
        st.plotly_chart(fig_a,use_container_width=True)
        st.subheader("⚠️ Distrato & Preço por fase")
        p["distrato_pct"]=st.number_input("Taxa de distrato (%)",value=float(p.get("distrato_pct",0)),min_value=0.0,max_value=30.0,step=0.5,format="%.1f",help="% de unidades vendidas que serão canceladas. Reduz o VGV efetivo.")
        if p.get("distrato_pct",0)>0:
            r=compute(p); st.warning(f"VGV efetivo após distrato: **{brl(r['vgv'])}** (−{brl(r['su']*r['pr']-r['vgv'])})")
        p["preco_fase1_pct"]=st.number_input("Desconto no lançamento (% do preço)",value=int(p.get("preco_fase1_pct",100)),min_value=50,max_value=110,step=1,help="100% = preço cheio. 95% = 5% de desconto na fase de lançamento.")
        p["preco_lancamento_meses"]=st.number_input("Duração do lançamento (meses)",value=int(p.get("preco_lancamento_meses",3)),min_value=0,max_value=12,step=1)
        if p.get("preco_fase1_pct",100)!=100:
            st.info(f"Unidades vendidas nos primeiros {p['preco_lancamento_meses']} meses recebem **{p['preco_fase1_pct']}%** do preço médio.")

# ════ FLUXO & APORTE ══════════════════════════════════════════════
with t5:
    r=compute(p); ms=[d["m"] for d in r["chart"]]; view=st.radio("",["📊 Gráficos","📋 Tabela"],horizontal=True)
    st.info(f"✅ Payback no mês **{r['pb']}**" if r["pb"] else "❌ Payback não atingido")
    if view=="📊 Gráficos":
        fig1=go.Figure()
        fig1.add_trace(go.Bar(x=ms,y=[d["receita"] for d in r["chart"]],name="Receitas",marker_color="#0ccf88",opacity=0.8))
        if any(d["fin_in"]>0 for d in r["chart"]): fig1.add_trace(go.Bar(x=ms,y=[d["fin_in"] for d in r["chart"]],name="Fin. captado",marker_color="#4fa8f5",opacity=0.8))
        fig1.add_trace(go.Bar(x=ms,y=[-d["custo"] for d in r["chart"]],name="Custos",marker_color="#f04848",opacity=0.7))
        fig1.add_vline(x=r["obra_start"],line_dash="dot",line_color="#888",annotation_text="Obras",annotation_font_size=9)
        fig1.add_vline(x=r["delivery"],line_dash="dot",line_color="#c8a245",annotation_text="Entrega",annotation_font_size=9)
        fig1.update_layout(title="Fluxo mensal",barmode="relative",height=280,margin=dict(l=0,r=0,t=40,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=False),yaxis=dict(gridcolor="#eee"),legend=dict(orientation="h",y=-0.2))
        st.plotly_chart(fig1,use_container_width=True)
        fig2=go.Figure()
        fig2.add_trace(go.Scatter(x=ms,y=[d["acumulado"] for d in r["chart"]],fill="tozeroy",fillcolor="rgba(79,168,245,0.1)",line=dict(color="#4fa8f5",width=2),name="Saldo acumulado"))
        fig2.add_hline(y=0,line_dash="dash",line_color="orange",opacity=0.7)
        if r["pb"]: fig2.add_vline(x=r["pb"],line_dash="dash",line_color="#0ccf88",annotation_text=f"  Payback M{r['pb']}",annotation_font_color="#0ccf88",annotation_position="top right")
        fig2.update_layout(title="Saldo acumulado",height=230,margin=dict(l=0,r=0,t=40,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=False),yaxis=dict(gridcolor="#eee"))
        st.plotly_chart(fig2,use_container_width=True)
        st.subheader("💰 Aporte necessário")
        c1_,c2_,c3_=st.columns(3)
        c1_.markdown(card("Pico de aporte",brl(r["pico"]),"#c62828" if r["pico"]>0 else "#2e7d32","Máximo equity simultâneo","#fce4e4" if r["pico"]>0 else "#e8f5e9"),unsafe_allow_html=True)
        c2_.markdown(card("Total aportado",brl(sum(r["aporte_m"])),"#b71c1c","Soma meses negativos","#fff3e0"),unsafe_allow_html=True)
        c3_.markdown(card("Captado financ.",brl(sum(r["fin_in"])),"#1565c0" if sum(r["fin_in"])>0 else "#455a64","Do banco","#e3f2fd" if sum(r["fin_in"])>0 else "#f5f5f5"),unsafe_allow_html=True)
        aporte_cum=[abs(min(r["ccf"][m],0)) for m in range(len(r["ccf"]))]
        fig3=make_subplots(specs=[[{"secondary_y":True}]])
        fig3.add_trace(go.Bar(x=ms,y=[d["aporte"] for d in r["chart"]],name="Aporte mensal",marker_color="#e53935",opacity=0.7),secondary_y=False)
        fig3.add_trace(go.Scatter(x=ms,y=[aporte_cum[d["m"]] for d in r["chart"]],name="Exposição acum.",line=dict(color="#ff7043",width=2)),secondary_y=True)
        fig3.update_layout(title="Fluxo de aporte",height=240,margin=dict(l=0,r=0,t=40,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=False),yaxis=dict(title="Aporte mensal",gridcolor="#eee"),yaxis2=dict(title="Exposição acum.",overlaying="y",side="right"),legend=dict(orientation="h",y=-0.2))
        st.plotly_chart(fig3,use_container_width=True)
    else:
        df_cf=pd.DataFrame([{"Mês":d["m"],"Evento":d["evento"],"Receitas":brl(d["receita"]) if d["receita"]>100 else "—","Fin. captado":brl(d["fin_in"]) if d["fin_in"]>100 else "—","Custos":brl(d["custo"]) if d["custo"]>100 else "—","Aporte":brl(d["aporte"]) if d["aporte"]>100 else "—","Saldo mês":brl(d["saldo"]),"Saldo acum.":brl(d["acumulado"])} for d in r["chart"]])
        st.dataframe(df_cf,hide_index=True,use_container_width=True,height=540)
        c1_,c2_,c3_=st.columns(3)
        c1_.metric("Total receitas",brlk(sum(r["inf"]))); c2_.metric("Total custos",brlk(sum(r["out"]))); c3_.metric("Resultado",brlk(r["ccf"][r["delivery"]] if r["delivery"]<len(r["ccf"]) else r["ccf"][-1]))

# ════ SENSIBILIDADE ═══════════════════════════════════════════════
with t6:
    r=compute(p); s1,s2=st.tabs(["🌪️ Sensibilidade","📐 Cenários"])
    with s1:
        st.subheader("Impacto de cada variável na margem líquida")
        st.caption(f"Base: Margem = **{pct(r['nm'])}** · TIR = **{pct(r['ira']) if r['ira'] else '—'}**")
        with st.spinner("Calculando..."): df_s=sens_table(p); td=tornado(p)
        st.dataframe(df_s,hide_index=True,use_container_width=True)
        fig_t=go.Figure()
        ys=[d["nm"] for d in td]
        fig_t.add_trace(go.Bar(y=ys,x=[d["hi"] for d in td],orientation="h",name="Alta",marker_color="#0ccf88",opacity=0.85))
        fig_t.add_trace(go.Bar(y=ys,x=[d["lo"] for d in td],orientation="h",name="Baixa",marker_color="#f04848",opacity=0.85))
        fig_t.add_vline(x=0,line_color="#333",line_width=1.5)
        fig_t.update_layout(barmode="overlay",height=300,margin=dict(l=0,r=0,t=10,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(title="Variação na margem (p.p.)",gridcolor="#eee"),legend=dict(orientation="h",y=-0.25))
        st.plotly_chart(fig_t,use_container_width=True)
    with s2:
        st.subheader("Comparativo de cenários")
        with st.spinner("Calculando..."): sc_p=get_scenario(p,"Pessimista"); sc_b=r; sc_o=get_scenario(p,"Otimista")
        c1_,c2_,c3_=st.columns(3)
        for col,sc,lbl,cor,bg in [(c1_,sc_p,"📉 PESSIMISTA\nPreço −10% · Obra +10% · Vel. −","#b71c1c","#fce4e4"),(c2_,sc_b,"📊 BASE\nParâmetros atuais","#1565c0","#e3f2fd"),(c3_,sc_o,"📈 OTIMISTA\nPreço +10% · Obra −5% · Vel. +","#1b5e20","#e8f5e9")]:
            with col: st.markdown(f"<div style='text-align:center;font-weight:700;color:{cor};padding:8px;background:{bg};border-radius:6px;margin-bottom:8px;white-space:pre-line;font-size:12px'>{lbl}</div>",unsafe_allow_html=True)
        for lbl_,vals_ in [("VGV",[brlk(x["vgv"]) for x in [sc_p,sc_b,sc_o]]),("Lucro",[brlk(x["np_"]) for x in [sc_p,sc_b,sc_o]]),("Margem",[pct(x["nm"]) for x in [sc_p,sc_b,sc_o]]),("TIR",[pct(x["ira"]) if x["ira"] else "—" for x in [sc_p,sc_b,sc_o]]),("VPL",[brlk(x["npv"]) for x in [sc_p,sc_b,sc_o]]),("Payback",[f"{x['pb']}m" if x["pb"] else ">42m" for x in [sc_p,sc_b,sc_o]]),("Pico aporte",[brlk(x["pico"]) for x in [sc_p,sc_b,sc_o]])]:
            for col,(v,cor,bg) in zip([c1_,c2_,c3_],zip(vals_,["#b71c1c","#1565c0","#1b5e20"],["#fce4e4","#e3f2fd","#e8f5e9"])):
                col.markdown(card(lbl_,v,cor,bg=bg),unsafe_allow_html=True)
        fig_s=go.Figure()
        for sc_,nm_,cor_ in [(sc_p,"Pessimista","#f04848"),(sc_b,"Base","#4fa8f5"),(sc_o,"Otimista","#0ccf88")]:
            ms_=list(range(len(sc_["ccf"]))); fig_s.add_trace(go.Scatter(x=ms_,y=sc_["ccf"],name=nm_,line=dict(color=cor_,width=2 if nm_=="Base" else 1.5,dash=None if nm_=="Base" else "dash")))
        fig_s.add_hline(y=0,line_dash="dot",line_color="#aaa")
        fig_s.update_layout(height=260,margin=dict(l=0,r=0,t=10,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=False),yaxis=dict(gridcolor="#eee"),legend=dict(orientation="h",y=-0.2))
        st.plotly_chart(fig_s,use_container_width=True)

# ════ INDICADORES ════════════════════════════════════════════════
with t7:
    r=compute(p)
    # Parecer automático
    status_,lines_=parecer(r,p)
    with st.expander(f"📋 Parecer automático — {status_}",expanded=True):
        for line in lines_: st.markdown(f"• {line}")
    warns=validar(p,r)
    for w in warns: st.warning(w)
    st.divider()
    c1,c2,c3,c4=st.columns(4)
    c1.markdown(card("VGV Total",brlk(r["vgv"]),"#1b5e20",f"{r['eff_su']:.0f} un. vendáveis","#e8f5e9"),unsafe_allow_html=True)
    c1.markdown(card("Custo Total",brlk(r["tc"]),"#b71c1c",f"{pct(r['tc']/r['vgv']*100 if r['vgv'] else 0)} do VGV","#fce4e4"),unsafe_allow_html=True)
    c2.markdown(card("Lucro Líquido",brlk(r["np_"]),"#1b5e20" if r["np_"]>=0 else "#b71c1c","","#e8f5e9" if r["np_"]>=0 else "#fce4e4"),unsafe_allow_html=True)
    c2.markdown(card("Margem Líquida",pct(r["nm"]),"#1b5e20" if r["nm"]>=15 else "#e65100","Sobre VGV"),unsafe_allow_html=True)
    c3.markdown(card("ROI s/ caixa" if r["pv"]>0 else "ROI s/ custo",pct(r["roi"]),"#1565c0",f"Total c/ permuta: {pct(r['roit'])}" if r["pv"]>0 else ""),unsafe_allow_html=True)
    c3.markdown(card("TIR Anual",pct(r["ira"]) if r["ira"] else "—","#1b5e20" if (r["ira"] or 0)>=p["tma"] else "#b71c1c",f"TMA: {p['tma']}% a.a."),unsafe_allow_html=True)
    c4.markdown(card("VPL",brlk(r["npv"]),"#1b5e20" if r["npv"]>=0 else "#b71c1c",f"@ TMA {p['tma']}%"),unsafe_allow_html=True)
    c4.markdown(card("Payback",f"{r['pb']} meses" if r["pb"] else "> ciclo","#1b5e20" if r["pb"] else "#b71c1c",f"Entrega: M{r['delivery']}"),unsafe_allow_html=True)
    st.divider()
    ca,cb,cc,cd=st.columns(4)
    ca.markdown(card("Lucro por unidade",brlk(r["lucro_un"]),"#37474f"),unsafe_allow_html=True)
    cb.markdown(card("Custo total/m²",brl(r["custo_m2"]),"#37474f"),unsafe_allow_html=True)
    cc.markdown(card("Pico de aporte",brlk(r["pico"]),"#c62828" if r["pico"]>0 else "#2e7d32"),unsafe_allow_html=True)
    cd.markdown(card("Impostos",brlk(r["imp"]),"#e53935" if r["imp"]>0 else "#455a64",p.get("imposto_tipo","Nenhum")),unsafe_allow_html=True)
    st.divider()
    ca,cb=st.columns(2)
    with ca:
        st.subheader("📄 DRE")
        dre=[("VGV — Receita bruta",brl(r["vgv"])),("(−) Corretagem",f"({brl(r['brk'])})")]
        if r["imp"]>0: dre.append((f"(−) Impostos ({p.get('imposto_tipo','')})",f"({brl(r['imp'])})"))
        dre.append(("━ Receita líquida",brl(r["nr"])))
        if r["pv"]>0: dre.append(("(−) Permuta",f"({brl(r['pv'])})"))
        if r["lc"]>0: dre.append(("(−) Terreno",f"({brl(r['lc'])})"))
        if r["itb"]>0: dre.append(("(−) ITBI",f"({brl(r['itb'])})"))
        if r["ci"]>0: dre.append(("(−) Incorporação",f"({brl(r['ci'])})"))
        dre+=[("(−) Construção base",f"({brl(r['cb'])})"),("(−) BDI",f"({brl(r['cf_'])})")]
        if r["prj"]>0: dre.append(("(−) Projetos",f"({brl(r['prj'])})"))
        if r["ins"]>0: dre.append(("(−) INSS",f"({brl(r['ins'])})"))
        if r["cont"]>0: dre.append(("(−) Contingência",f"({brl(r['cont'])})"))
        if r["gar"]>0: dre.append(("(−) Garantia",f"({brl(r['gar'])})"))
        dre+=[("(−) Marketing",f"({brl(r['mkt'])})"),("(−) Stand",f"({brl(r['std'])})"),("(−) Adm.",f"({brl(r['adm'])})"),("(−) Outros",f"({brl(r['oth'])})")]
        if p.get("fin_ativo") and sum(r["fin_int"])>0: dre.append(("(−) Juros financiamento",f"({brl(sum(r['fin_int']))})"))
        dre.append(("━ LUCRO LÍQUIDO",brl(r["np_"])))
        st.dataframe(pd.DataFrame(dre,columns=["Descrição","Valor"]),hide_index=True,use_container_width=True)
        cg,cl=st.columns(2); cg.metric("Margem bruta",pct(r["gm"])); cl.metric("Margem líquida",pct(r["nm"]))
    with cb:
        st.subheader("🎯 Break-even & Retorno")
        st.metric("Unidades mínimas",f"{r['beu']} de {r['eff_su']:.0f}",f"{pct(r['bep'])} das vendáveis")
        st.progress(min(1.0,r["bep"]/100))
        st.caption(f"Margem de segurança: **{pct(max(0,100-r['bep']))}**")
        st.divider()
        irm_=(1+r["ira"]/100)**(1/12)-1 if r["ira"] else None
        rets=[("ROI sobre caixa" if r["pv"]>0 else "ROI s/ custo",pct(r["roi"])),("TIR mensal",pct(irm_*100,2) if irm_ else "—"),("TIR anual",pct(r["ira"]) if r["ira"] else "—"),(f"VPL @ TMA {p['tma']}%",brl(r["npv"])),("Payback",f"{r['pb']} meses" if r["pb"] else ">ciclo"),("Pico de aporte",brl(r["pico"])),("Lucro por unidade",brl(r["lucro_un"]))]
        st.dataframe(pd.DataFrame(rets,columns=["Indicador","Valor"]),hide_index=True,use_container_width=True)
        st.divider()
        if st.button("Gerar Excel completo",type="primary",use_container_width=True):
            buf=export_excel(p,r)
            st.download_button("⬇️ Baixar Excel",data=buf,file_name=f"viabilidade_{p['name'].replace(' ','_')}.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)

# ════ COMPARATIVO ════════════════════════════════════════════════
with t8:
    st.subheader("📊 Comparativo consolidado de empreendimentos")
    with st.spinner("Calculando todos os projetos..."):
        all_r=[compute(proj) for proj in st.session_state.projects]
    metrics_rows=[]
    for proj,r_ in zip(st.session_state.projects,all_r):
        metrics_rows.append({"Empreendimento":proj["name"],"VGV":brlk(r_["vgv"]),"Custo":brlk(r_["tc"]),"Lucro":brlk(r_["np_"]),"Margem":pct(r_["nm"]),"ROI":pct(r_["roi"]),"TIR":pct(r_["ira"]) if r_["ira"] else "—","VPL":brlk(r_["npv"]),"Payback":f"{r_['pb']}m" if r_["pb"] else ">ciclo","Pico aporte":brlk(r_["pico"]),"Entrega":f"M{r_['delivery']}"})
    st.dataframe(pd.DataFrame(metrics_rows),hide_index=True,use_container_width=True)
    st.divider()
    c1_,c2_=st.columns(2)
    with c1_:
        st.subheader("Saldo acumulado — todos os projetos")
        fig_comp=go.Figure()
        colors_comp=["#4fa8f5","#0ccf88","#f0a020","#f04848","#8b78f0","#c8a245"]
        for i,(proj,r_) in enumerate(zip(st.session_state.projects,all_r)):
            ms_=list(range(len(r_["ccf"])))
            fig_comp.add_trace(go.Scatter(x=ms_,y=r_["ccf"],name=proj["name"],line=dict(color=colors_comp[i%len(colors_comp)],width=2)))
        fig_comp.add_hline(y=0,line_dash="dot",line_color="#aaa")
        fig_comp.update_layout(height=300,margin=dict(l=0,r=0,t=10,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=False,title="Mês"),yaxis=dict(gridcolor="#eee"),legend=dict(orientation="h",y=-0.25))
        st.plotly_chart(fig_comp,use_container_width=True)
    with c2_:
        st.subheader("Ranking por margem líquida")
        rank=sorted(zip(st.session_state.projects,all_r),key=lambda x:x[1]["nm"],reverse=True)
        fig_rank=go.Figure(go.Bar(
            y=[proj["name"] for proj,_ in rank],
            x=[r_["nm"] for _,r_ in rank],
            orientation="h",
            marker_color=["#0ccf88" if r_["nm"]>=15 else "#f0a020" if r_["nm"]>=8 else "#f04848" for _,r_ in rank],
            text=[f"{pct(r_['nm'])}  TIR: {pct(r_['ira']) if r_['ira'] else '—'}" for _,r_ in rank],
            textposition="outside"))
        fig_rank.update_layout(height=max(200,len(rank)*60+60),margin=dict(l=0,r=150,t=10,b=0),plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)",xaxis=dict(showgrid=True,gridcolor="#eee",title="Margem líquida (%)"),yaxis=dict(autorange="reversed"),showlegend=False)
        st.plotly_chart(fig_rank,use_container_width=True)
