"""
ALPHA SCANNER PRO — Multi-Layer Alert System v4.0
Only sends alerts when ALL 4 analysis layers converge.
Layer 1: Radar (technical signals)
Layer 2: Investment Analysis (fundamentals)
Layer 3: Entry Zones (risk/reward)  
Layer 4: Game Theory (probabilistic confirmation)

Run: python scripts/check_alerts.py
"""
import json, os, smtplib, warnings, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore")

# ── UTILITY FUNCTIONS ────────────────────────────────────────────
def grade_score(gr):
    if not gr: return 0
    g = gr.lower()
    if g in ('excel','strong','cheap'): return 5
    if g in ('good','solid'): return 4
    if g in ('fair','mod'): return 3
    if g in ('med','pricey'): return 2
    return 1 if g != 'n/a' else 0

def composite_score(r):
    raw = (grade_score(r.get('eps_gr',''))*0.30 +
           grade_score(r.get('roe_gr',''))*0.25 +
           grade_score(r.get('roa_gr',''))*0.20 +
           grade_score(r.get('pe_gr',''))*0.25)
    return round((raw/5)*100)

def earnings_quality(r):
    eps_s = grade_score(r.get('eps_gr',''))
    roa_s = grade_score(r.get('roa_gr',''))
    if eps_s >= 4 and roa_s >= 4: return 'Alta'
    if eps_s >= 4 and roa_s <= 2: return 'Sospechosa'
    if eps_s >= 3 and roa_s >= 3: return 'Aceptable'
    return 'Debil'

def debt_risk(r):
    roe = r.get('roe') or 0
    roa = r.get('roa') or 0
    if roe > 0 and roa > 0:
        ratio = roe / roa
        if ratio > 3: return 'ALTO'
        if ratio > 2: return 'MODERADO'
        return 'BAJO'
    if roe > 0 and roa <= 0: return 'ALTO'
    return 'N/A'

CYCLICAL = ['Industrials','Materials','Energy','Financials']
DEFENSIVE = ['Utilities','Healthcare','Defense','Consumer Staples']

def sector_type(sector):
    if sector in CYCLICAL: return 'cyclical'
    if sector in DEFENSIVE: return 'defensive'
    return 'growth'

def bayesian_probability(r, cs):
    ai = r.get('ai') or 50
    rsi = r.get('rsi') or 50
    adx = r.get('adx') or 15
    d20 = r.get('20d') or 0
    rel_vol = r.get('rel_vol') or 1
    prior = 0.5
    lk_ai = (ai / 100)
    lk_vol = 1.3 if rel_vol > 1.1 else 0.9
    lk_rsi = 1.2 if (40 < rsi < 70) else 0.7
    lk_fund = cs / 85
    lk_mom = 1.2 if d20 > 3 else (1.0 if d20 > 0 else 0.7)
    lk_adx = 1.15 if adx > 20 else 0.85
    posterior = prior * lk_ai * lk_vol * lk_rsi * lk_fund * lk_mom * lk_adx * 3.5
    return min(0.95, max(0.15, posterior))


# ═══════════════════════════════════════════════════════════════
# ══ MULTI-LAYER VALIDATION ENGINE ══
# All 4 layers must PASS for an alert to be generated.
# ═══════════════════════════════════════════════════════════════

def validate_layer1_radar(r):
    """Layer 1: Radar — Technical signals must be active."""
    state = r.get('state', 'WAIT')
    score = r.get('score', 0)
    ai = r.get('ai', 0)
    abc = r.get('abc', '')
    rsi = r.get('rsi', 50)
    adx = r.get('adx', 0)
    
    checks = {}
    
    # State must be ENTRY+ or ENTRY (ACCUM not enough alone)
    checks['state_active'] = state in ('ENTRY+', 'ENTRY')
    
    # Score técnico mínimo 60
    checks['score_min'] = score >= 60
    
    # AI probability > 65%
    checks['ai_min'] = ai >= 65
    
    # ABC grade A or B (not bearish C)
    checks['abc_ok'] = abc in ('A', 'B')
    
    # RSI not overbought (< 75) — don't buy at top
    checks['rsi_safe'] = rsi is None or rsi < 75
    
    # ADX > 15 — must have some trend
    checks['adx_trend'] = adx is None or adx > 15
    
    passed = all(checks.values())
    return passed, checks

def validate_layer2_analysis(r):
    """Layer 2: Investment Analysis — Fundamentals must confirm."""
    cs = composite_score(r)
    eq = earnings_quality(r)
    dr = debt_risk(r)
    eps_g = r.get('eps_g') or 0
    roe = r.get('roe') or 0
    roa = r.get('roa') or 0
    
    checks = {}
    
    # Composite Score ≥ 55 (combined P/E + ROE + ROA + EPS)
    checks['composite_min'] = cs >= 55
    
    # Earnings quality NOT suspicious
    checks['earnings_clean'] = eq != 'Sospechosa'
    
    # Debt risk NOT high (D/E invalidates ROE)
    checks['debt_safe'] = dr != 'ALTO'
    
    # EPS Growth positive (company is growing)
    checks['eps_positive'] = eps_g > 0
    
    # ROE minimum 8% (decent return on equity)
    checks['roe_min'] = roe >= 8
    
    # ROA minimum 3% (real operational efficiency)
    checks['roa_min'] = roa >= 3
    
    passed = all(checks.values())
    return passed, checks, cs

def validate_layer3_entry(r, cs):
    """Layer 3: Entry Zones — Risk/reward must be favorable."""
    upside = r.get('upside') or 0
    close = r.get('close') or 0
    d20 = r.get('20d') or 0
    d5 = r.get('5d') or 0
    fund = r.get('fund') or 0
    
    checks = {}
    
    # Upside potential ≥ 8%
    checks['upside_min'] = upside >= 8
    
    # Momentum 20D positive (trend is up)
    checks['momentum_20d'] = d20 > 0
    
    # 5D not crashing (avoid catching falling knife)
    checks['not_crashing'] = d5 > -5
    
    # Fundamental score ≥ 50
    checks['fund_min'] = fund >= 50
    
    # Risk/Reward: upside must be > 1.5x the stop loss (2%)
    rr = upside / 2 if upside > 0 else 0
    checks['risk_reward'] = rr >= 1.5
    
    # Price > 0 (sanity)
    checks['price_valid'] = close > 0
    
    passed = all(checks.values())
    
    # Calculate entry zones
    entry_price = round(close * 0.985, 2)
    tp1 = round(close * 1.03, 2)
    tp2 = round(close * 1.06, 2)
    sl = round(close * 0.98, 2)
    
    return passed, checks, {'entry': entry_price, 'tp1': tp1, 'tp2': tp2, 'sl': sl}

def validate_layer4_gametheory(r, cs):
    """Layer 4: Game Theory — Probabilistic confirmation."""
    prob = bayesian_probability(r, cs)
    prob_pct = round(prob * 100)
    
    # Expected value calculation
    tgt_min = 3  # weekly target
    sl = 2
    ev = (prob * tgt_min) - ((1 - prob) * sl)
    
    # Kelly criterion
    kelly = max(0, prob - (1 - prob) / (tgt_min / sl))
    
    checks = {}
    
    # Bayesian probability ≥ 65%
    checks['prob_min'] = prob_pct >= 65
    
    # Expected value positive
    checks['ev_positive'] = ev > 0
    
    # Kelly criterion > 10% (worth betting)
    checks['kelly_min'] = kelly >= 0.10
    
    passed = all(checks.values())
    return passed, checks, {
        'probability': prob_pct,
        'expected_value': round(ev, 2),
        'kelly': round(kelly * 100)
    }


def run_full_validation(r):
    """Run ALL 4 layers. Only passes if EVERY layer confirms."""
    
    result = {
        'ticker': r.get('ticker', '?'),
        'name': r.get('name', '?'),
        'price': r.get('close', 0),
        'sector': r.get('sector', ''),
        'layers': {},
        'all_passed': False,
    }
    
    # Layer 1: Radar
    l1_pass, l1_checks = validate_layer1_radar(r)
    result['layers']['radar'] = {'passed': l1_pass, 'checks': l1_checks}
    
    # Layer 2: Analysis
    l2_pass, l2_checks, cs = validate_layer2_analysis(r)
    result['layers']['analysis'] = {'passed': l2_pass, 'checks': l2_checks, 'composite': cs}
    result['composite'] = cs
    
    # Layer 3: Entry Zones
    l3_pass, l3_checks, zones = validate_layer3_entry(r, cs)
    result['layers']['entry'] = {'passed': l3_pass, 'checks': l3_checks, 'zones': zones}
    result['zones'] = zones
    
    # Layer 4: Game Theory
    l4_pass, l4_checks, gt = validate_layer4_gametheory(r, cs)
    result['layers']['gametheory'] = {'passed': l4_pass, 'checks': l4_checks, 'gt': gt}
    result['gt'] = gt
    
    # ALL must pass
    result['all_passed'] = l1_pass and l2_pass and l3_pass and l4_pass
    result['layers_passed'] = sum([l1_pass, l2_pass, l3_pass, l4_pass])
    
    # Extra data
    result['state'] = r.get('state', 'WAIT')
    result['score'] = r.get('score', 0)
    result['ai'] = r.get('ai', 0)
    result['upside'] = r.get('upside', 0) or 0
    result['target'] = r.get('target', 0)
    result['roe'] = r.get('roe', 0) or 0
    result['roa'] = r.get('roa', 0) or 0
    result['eps_g'] = r.get('eps_g', 0) or 0
    result['pe'] = r.get('pe', 0)
    result['d20'] = r.get('20d', 0) or 0
    result['rsi'] = r.get('rsi', 50)
    result['group'] = ''  # will be set by caller
    
    return result


# ═══ EMAIL BUILDER ═══════════════════════════════════════════════
def build_email_html(confirmed, near_miss, timestamp):
    """Professional HTML email."""
    
    html = f"""<html><body style="margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',Arial,sans-serif;color:#c8cad0">
    <div style="max-width:640px;margin:0 auto;padding:20px">
    
    <div style="background:#12131a;border:1px solid #2a2b36;border-radius:8px;padding:20px;margin-bottom:16px;text-align:center">
        <h1 style="color:#00e676;margin:0;font-size:22px;letter-spacing:2px">🎯 ALPHA SCANNER PRO</h1>
        <p style="color:#8a8c96;margin:6px 0 0;font-size:12px">ALERTA MULTI-CAPA · {timestamp}</p>
        <div style="margin:12px 0 0;padding:10px;background:#0a2e1a;border:1px solid #00e67640;border-radius:6px">
            <p style="color:#00e676;margin:0;font-size:16px;font-weight:bold">{len(confirmed)} SEÑAL{'ES' if len(confirmed)!=1 else ''} CONFIRMADA{'S' if len(confirmed)!=1 else ''}</p>
            <p style="color:#69f0ae;margin:4px 0 0;font-size:10px">4/4 CAPAS VALIDADAS: Radar ✓ Analysis ✓ Entry Zones ✓ Game Theory ✓</p>
        </div>
    </div>"""
    
    # CONFIRMED SIGNALS
    for a in confirmed:
        z = a['zones']
        gt = a['gt']
        html += f"""
    <div style="background:#12131a;border:1px solid #00e676;border-left:4px solid #00e676;border-radius:8px;padding:16px;margin-bottom:12px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
            <span style="font-size:28px">🚀</span>
            <div>
                <div style="font-size:18px;font-weight:bold;color:#00e676">{a['ticker']} — {a['name']}</div>
                <div style="font-size:11px;color:#ffab00;font-weight:bold">COMPRAR — 4/4 CAPAS CONFIRMADAS</div>
            </div>
        </div>
        
        <div style="background:#0a0a0f;border-radius:6px;padding:12px;margin-bottom:10px">
            <table style="width:100%;border-collapse:separate;border-spacing:4px"><tr>
                <td style="padding:8px;background:#1a1b24;border-radius:4px;text-align:center;width:20%">
                    <div style="font-size:9px;color:#5a5c66;text-transform:uppercase">Precio</div>
                    <div style="font-size:15px;font-weight:bold;color:#c8cad0">${a['price']}</div>
                </td>
                <td style="padding:8px;background:#1a1b24;border-radius:4px;text-align:center;width:20%">
                    <div style="font-size:9px;color:#5a5c66;text-transform:uppercase">Composite</div>
                    <div style="font-size:15px;font-weight:bold;color:#00e676">{a['composite']}/100</div>
                </td>
                <td style="padding:8px;background:#1a1b24;border-radius:4px;text-align:center;width:20%">
                    <div style="font-size:9px;color:#5a5c66;text-transform:uppercase">AI Score</div>
                    <div style="font-size:15px;font-weight:bold;color:#00e5ff">{a['ai']}%</div>
                </td>
                <td style="padding:8px;background:#1a1b24;border-radius:4px;text-align:center;width:20%">
                    <div style="font-size:9px;color:#5a5c66;text-transform:uppercase">Prob GT</div>
                    <div style="font-size:15px;font-weight:bold;color:#b388ff">{gt['probability']}%</div>
                </td>
                <td style="padding:8px;background:#1a1b24;border-radius:4px;text-align:center;width:20%">
                    <div style="font-size:9px;color:#5a5c66;text-transform:uppercase">Upside</div>
                    <div style="font-size:15px;font-weight:bold;color:#00e676">+{a['upside']}%</div>
                </td>
            </tr></table>
        </div>
        
        <div style="background:#0a2e1a;border:1px solid #00e67640;border-radius:6px;padding:12px;margin-bottom:10px">
            <div style="font-size:10px;color:#00e676;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">🎯 ZONAS DE OPERACIÓN — Solo LONG</div>
            <table style="width:100%;border-collapse:separate;border-spacing:4px"><tr>
                <td style="padding:8px;background:#12131a;border-radius:4px;text-align:center;width:25%">
                    <div style="font-size:9px;color:#5a5c66">ENTRY</div>
                    <div style="font-size:14px;font-weight:bold;color:#00e676">${z['entry']}</div>
                </td>
                <td style="padding:8px;background:#12131a;border-radius:4px;text-align:center;width:25%">
                    <div style="font-size:9px;color:#5a5c66">TP1 (+3%)</div>
                    <div style="font-size:14px;font-weight:bold;color:#00e5ff">${z['tp1']}</div>
                </td>
                <td style="padding:8px;background:#12131a;border-radius:4px;text-align:center;width:25%">
                    <div style="font-size:9px;color:#5a5c66">TP2 (+6%)</div>
                    <div style="font-size:14px;font-weight:bold;color:#69f0ae">${z['tp2']}</div>
                </td>
                <td style="padding:8px;background:#12131a;border-radius:4px;text-align:center;width:25%">
                    <div style="font-size:9px;color:#5a5c66">STOP LOSS</div>
                    <div style="font-size:14px;font-weight:bold;color:#ff5252">${z['sl']}</div>
                </td>
            </tr></table>
        </div>
        
        <div style="background:#1a1b24;border-radius:6px;padding:10px;margin-bottom:8px">
            <div style="font-size:9px;color:#5a5c66;text-transform:uppercase;margin-bottom:6px">✅ Validación Multicapa</div>
            <div style="font-size:11px;color:#c8cad0;line-height:1.6">
                <span style="color:#00e676">✓ Radar:</span> {a['state']} · Score:{a['score']} · AI:{a['ai']}%<br>
                <span style="color:#00e676">✓ Analysis:</span> CS:{a['composite']} · ROE:{a['roe']}% · ROA:{a['roa']}% · EPS:{a['eps_g']}%<br>
                <span style="color:#00e676">✓ Entry Zone:</span> Upside:+{a['upside']}% · Momentum 20D:+{a['d20']}%<br>
                <span style="color:#00e676">✓ Game Theory:</span> P(↑)={gt['probability']}% · EV:+{gt['expected_value']}% · Kelly:{gt['kelly']}%
            </div>
        </div>
        
        <div style="font-size:10px;color:#5a5c66">{a['sector']} · {a['group']} · R/R: {a['upside']/2:.1f}:1</div>
    </div>"""
    
    # NEAR MISSES (3/4 layers)
    if near_miss:
        html += """
    <div style="background:#12131a;border:1px solid #2a2b36;border-radius:8px;padding:14px;margin-bottom:12px">
        <p style="color:#ffab00;font-size:12px;font-weight:bold;margin:0 0 8px">⏳ WATCHLIST — 3/4 Capas (monitorear)</p>"""
        for a in near_miss[:5]:
            failed = [k for k,v in a.get('failed_layers',{}).items() if not v]
            html += f"""
        <div style="padding:6px 0;border-bottom:1px solid #2a2b36;font-size:11px">
            <span style="color:#ffab00;font-weight:bold">{a['ticker']}</span>
            <span style="color:#8a8c96"> ${a['price']} · CS:{a['composite']} · AI:{a['ai']}%</span>
            <span style="color:#ff5252;font-size:10px"> — Falta: {', '.join(failed)}</span>
        </div>"""
        html += "</div>"
    
    # FOOTER
    html += f"""
    <div style="text-align:center;padding:16px;color:#5a5c66;font-size:10px;border-top:1px solid #2a2b36;margin-top:16px">
        <p style="margin:0">ALPHA SCANNER PRO v4.0 · Solo LONG · 4-Layer Validation</p>
        <p style="margin:4px 0 0;color:#ff5252;font-weight:bold">⚠️ Esto NO es consejo financiero. Investiga siempre antes de invertir.</p>
        <p style="margin:4px 0 0">{timestamp}</p>
    </div></div></body></html>"""
    return html


def build_plain_text(confirmed, near_miss, timestamp):
    t = f"ALPHA SCANNER PRO — ALERTA MULTI-CAPA\n{'='*55}\n"
    t += f"Fecha: {timestamp}\n"
    t += f"Señales 4/4 confirmadas: {len(confirmed)}\n\n"
    for a in confirmed:
        z = a['zones']
        gt = a['gt']
        t += f"🚀 {a['ticker']} — {a['name']} — COMPRAR\n"
        t += f"   Precio: ${a['price']} | CS: {a['composite']} | AI: {a['ai']}% | Prob: {gt['probability']}%\n"
        t += f"   Entry: ${z['entry']} | TP1: ${z['tp1']} | TP2: ${z['tp2']} | SL: ${z['sl']}\n"
        t += f"   Radar: {a['state']} Score:{a['score']} | ROE:{a['roe']}% ROA:{a['roa']}% EPS:{a['eps_g']}%\n"
        t += f"   Upside: +{a['upside']}% | Kelly: {gt['kelly']}%\n\n"
    if near_miss:
        t += f"WATCHLIST (3/4 capas):\n"
        for a in near_miss[:5]:
            t += f"  ⏳ {a['ticker']} ${a['price']} CS:{a['composite']} — falta confirmación\n"
    t += "\n⚠️ Esto NO es consejo financiero.\n"
    return t


# ═══ SEND EMAIL ══════════════════════════════════════════════════
def send_email(confirmed, near_miss, to_email, smtp_user, smtp_pass):
    bogota = timezone(timedelta(hours=-5))
    now = datetime.now(bogota)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S") + " (UTC-5 Bogotá)"
    
    tickers = [a['ticker'] for a in confirmed]
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚀 COMPRAR: {', '.join(tickers)} — {len(confirmed)} señal(es) 4/4 confirmadas"
    msg['From'] = smtp_user
    msg['To'] = to_email
    
    msg.attach(MIMEText(build_plain_text(confirmed, near_miss, timestamp), 'plain', 'utf-8'))
    msg.attach(MIMEText(build_email_html(confirmed, near_miss, timestamp), 'html', 'utf-8'))
    
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(smtp_user, smtp_pass)
    server.sendmail(smtp_user, to_email, msg.as_string())
    server.quit()
    print(f"  ✅ Email sent to {to_email}: {len(confirmed)} confirmed signals")


# ═══ MAIN ════════════════════════════════════════════════════════
def main():
    # Load snapshot
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'snapshot.json')
    if not os.path.exists(data_path):
        print("ERROR: snapshot.json not found. Run build_data.py first.")
        sys.exit(1)
    
    with open(data_path, 'r', encoding='utf-8') as f:
        snapshot = json.load(f)
    
    print(f"ALPHA SCANNER PRO — Multi-Layer Alert Check")
    print(f"{'='*55}")
    
    confirmed = []
    near_miss = []
    
    for group_name, stocks in snapshot.get('groups', {}).items():
        for r in stocks:
            result = run_full_validation(r)
            result['group'] = group_name
            
            if result['all_passed']:
                confirmed.append(result)
                print(f"  🚀 CONFIRMED: {result['ticker']} — 4/4 layers passed (CS:{result['composite']} AI:{result['ai']}% Prob:{result['gt']['probability']}%)")
            elif result['layers_passed'] == 3:
                # Track which layer failed
                failed = {}
                for layer_name, layer_data in result['layers'].items():
                    failed[layer_name] = layer_data['passed']
                result['failed_layers'] = failed
                near_miss.append(result)
                failed_names = [k for k,v in failed.items() if not v]
                print(f"  ⏳ NEAR MISS: {result['ticker']} — 3/4 layers (failed: {', '.join(failed_names)})")
    
    confirmed.sort(key=lambda x: (-x['composite'], -x['gt']['probability']))
    near_miss.sort(key=lambda x: (-x['composite']))
    
    print(f"\n{'='*55}")
    print(f"RESULTS: {len(confirmed)} confirmed | {len(near_miss)} near-miss (3/4)")
    
    # Save results to file for reference
    results_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'alerts.json')
    bogota = timezone(timedelta(hours=-5))
    results_data = {
        'checked_at': datetime.now(bogota).isoformat(),
        'confirmed': len(confirmed),
        'near_miss': len(near_miss),
        'signals': [{'ticker': a['ticker'], 'composite': a['composite'], 
                     'probability': a['gt']['probability'], 'zones': a['zones']} 
                    for a in confirmed],
        'watchlist': [{'ticker': a['ticker'], 'composite': a['composite'], 
                       'layers_passed': a['layers_passed']} 
                      for a in near_miss[:10]]
    }
    with open(results_path, 'w') as f:
        json.dump(results_data, f, indent=2)
    print(f"Results saved to {results_path}")
    
    # Send email only if there are confirmed signals
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    to_email = os.environ.get('ALERT_EMAIL', 'andrestf88@gmail.com')
    
    if confirmed and smtp_user and smtp_pass:
        try:
            send_email(confirmed, near_miss, to_email, smtp_user, smtp_pass)
        except Exception as e:
            print(f"  ❌ Email error: {e}")
    elif confirmed:
        print(f"\n  ⚠️ {len(confirmed)} signals found but SMTP not configured.")
        print(f"  Set SMTP_USER and SMTP_PASS environment variables (or GitHub Secrets).")
        print(f"\n  Signals found:")
        for a in confirmed:
            z = a['zones']
            print(f"    🚀 {a['ticker']} ${a['price']} → Entry:${z['entry']} TP1:${z['tp1']} TP2:${z['tp2']} SL:${z['sl']}")
    else:
        print(f"\n  ℹ️ No signals met ALL 4 layers. Market in wait mode.")
        if near_miss:
            print(f"  Watchlist (3/4):")
            for a in near_miss[:5]:
                print(f"    ⏳ {a['ticker']} CS:{a['composite']} — close to triggering")


if __name__ == "__main__":
    main()
