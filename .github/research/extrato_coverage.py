"""Read-only measurement for issue #524 (wayfinder map #510).

Downloads CVM's FI "Extrato das Informacoes" (extrato_fi.csv, the current file
for all funds, plus extrato_fi_2024/2025/2026.csv), folds it to one row per CNPJ
and prints aggregates only. It also re-reads the lamina monthly zips to compare
TAXA_ADM for funds that have both. Writes nothing to any database, holds no
secret. Public CVM files in, log lines out.

Universe file (.github/research/lamina_universe.txt), one fund per line:
  cnpj14|A or B|D or N|pl_reais|e8|e7
  A = PL >= R$1M at its latest month in fact_fund_monthly, B = below.
  D = the fund reported NAV in cvm_fi_diario in 2026-09, N = it did not.
  e8 / e7 = balancete-derived annual fee estimate in percent for 2026-08 / 2026-07.
"""
import collections
import concurrent.futures as cf
import csv
import datetime as dt_mod
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import zipfile

EXT_BASE = "https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/DADOS/"
LAM_BASE = "https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/DADOS/"
REF_DATE = dt_mod.date(2026, 10, 2)  # day of the run's snapshot; ages are measured against it
REF_LAM = (2026, 8)
DEMO = ["42592315000115", "50088190000119", "35377390000106", "51488342000133", "08935128000159"]
csv.field_size_limit(sys.maxsize)
FAILED = []


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "silo-research/1.0"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.read()
        except Exception as exc:  # retried, then recorded and printed; never swallowed
            last = exc
            time.sleep(3 * (i + 1))
    FAILED.append((url, f"{type(last).__name__}: {last}"))
    return None


def norm(c):
    return re.sub(r"\D", "", c or "").zfill(14)


def num(x):
    x = (x or "").strip()
    if not x:
        return None
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def pct(vals, ps=(1, 5, 10, 25, 50, 75, 90, 95, 99)):
    v = sorted(vals)
    if not v:
        return {}
    out = {}
    for p in ps:
        k = min(len(v) - 1, max(0, int(round(p / 100 * (len(v) - 1)))))
        out[f"p{p}"] = round(v[k], 4)
    out["n"] = len(v)
    out["min"] = round(v[0], 4)
    out["max"] = round(v[-1], 4)
    return out


def decode(raw):
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def days_old(d):
    try:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        return (REF_DATE - dt_mod.date(y, m, dd)).days
    except (ValueError, IndexError):
        return None


def age_buckets(ds):
    b = collections.OrderedDict([("<=0", 0), ("1-30", 0), ("31-90", 0), ("91-180", 0), ("181-365", 0), ("366-730", 0), (">730", 0), ("unparsable", 0)])
    for d in ds:
        if d is None:
            b["unparsable"] += 1
        elif d <= 0:
            b["<=0"] += 1
        elif d <= 30:
            b["1-30"] += 1
        elif d <= 90:
            b["31-90"] += 1
        elif d <= 180:
            b["91-180"] += 1
        elif d <= 365:
            b["181-365"] += 1
        elif d <= 730:
            b["366-730"] += 1
        else:
            b[">730"] += 1
    return dict(b)


def read_csv(name, blob):
    """Returns (cols, rows, meta). Header, encoding and separator are detected, not assumed."""
    fffd = blob.count(b"\xef\xbf\xbd")
    text, enc = decode(blob)
    first = text.split("\n", 1)[0]
    sep = ";" if first.count(";") >= first.count(",") else ","
    rdr = csv.DictReader(io.StringIO(text), delimiter=sep)
    cols = rdr.fieldnames or []
    rows = list(rdr)
    meta = dict(file=name, bytes=len(blob), enc=enc, sep=repr(sep), fffd=fffd, ncols=len(cols),
                hdr=hashlib.md5(";".join(cols).encode()).hexdigest()[:8], rows=len(rows))
    return cols, rows, meta


def fold_extrato(rows, cnpj_col):
    """One row per CNPJ: newest DT_COMPTC, ties prefer a row with TAXA_ADM. Also returns row counts."""
    cnt = collections.Counter()
    best = {}
    for r in rows:
        c = norm(r.get(cnpj_col))
        cnt[c] += 1
        d = (r.get("DT_COMPTC") or "").strip()
        ta = num(r.get("TAXA_ADM"))
        cur = best.get(c)
        key = (d, ta is not None)
        if cur is None or key > cur[0]:
            best[c] = (key, r)
    return {c: v[1] for c, v in best.items()}, cnt


def lam_fold(uni):
    """Latest lamina per universe CNPJ: dt, class-level row preferred."""
    html = get(LAM_BASE)
    if html is None:
        return {}
    names = sorted(set(re.findall(r'href="(lamina_fi_\d{6}\.zip)"', html.decode("utf-8", "replace"))))
    print(f"LAMINA files listed: {len(names)} {names[:1]} {names[-1:]}", flush=True)
    latest = {}

    def fetch(n):
        return n, get(LAM_BASE + n)

    with cf.ThreadPoolExecutor(4) as ex:
        for n, blob in ex.map(fetch, names):
            if blob is None:
                print(f"FAILED {n}")
                continue
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                main = next((m for m in z.namelist() if m.lower().endswith(".csv") and "carteira" not in m and "rentab" not in m), None)
                if main is None:
                    FAILED.append((n, "no main csv"))
                    continue
                text, _ = decode(z.read(main))
            rdr = csv.DictReader(io.StringIO(text), delimiter=";")
            cc = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in (rdr.fieldnames or []) else next((c for c in rdr.fieldnames if "CNPJ" in c), None)
            for r in rdr:
                c = norm(r.get(cc))
                if c not in uni:
                    continue
                d = (r.get("DT_COMPTC") or "").strip()
                idsub = (r.get("ID_SUBCLASSE") or "").strip()
                rec = dict(dt=d, id_sub=idsub, taxa=num(r.get("TAXA_ADM")), tmin=num(r.get("TAXA_ADM_MIN")),
                           tmax=num(r.get("TAXA_ADM_MAX")), tp=(r.get("TP_TAXA_ADM") or "").strip())
                cur = latest.get(c)
                if cur is None or d > cur["dt"] or (d == cur["dt"] and not idsub and cur["id_sub"]):
                    latest[c] = rec
    return latest


def lam_age(d):
    return (REF_LAM[0] - int(d[:4])) * 12 + (REF_LAM[1] - int(d[5:7]))


def main():
    uni = {}
    for line in open(".github/research/lamina_universe.txt"):
        p = line.rstrip("\n").split("|")
        if len(p) < 6:
            continue
        uni[p[0]] = dict(band=p[1], diario=p[2], pl=float(p[3]) if p[3] else None,
                         e8=float(p[4]) if p[4] else None, e7=float(p[5]) if p[5] else None)
    print(f"UNIVERSE n={len(uni)} A={sum(1 for u in uni.values() if u['band']=='A')} "
          f"D={sum(1 for u in uni.values() if u['diario']=='D')} e8={sum(1 for u in uni.values() if u['e8'] is not None)}")

    # ---- the current file ----
    t0 = time.time()
    blob = get(EXT_BASE + "extrato_fi.csv")
    if blob is None:
        print("FATAL: extrato_fi.csv not downloadable"); print(FAILED); sys.exit(1)
    print(f"DOWNLOADED extrato_fi.csv {len(blob)} bytes in {time.time()-t0:.0f}s")
    cols, rows, meta = read_csv("extrato_fi.csv", blob)
    print("CURRENT FILE META:", json.dumps(meta))
    print("HEADER (", len(cols), "cols ):", ";".join(cols))
    cnpj_col = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in cols else next((c for c in cols if "CNPJ" in c), None)
    print("CNPJ column used:", cnpj_col, "| other CNPJ-like / subclass / version columns:",
          [c for c in cols if ("CNPJ" in c or "SUBCLASSE" in c or "VERS" in c or c.startswith("ID_")) and c != cnpj_col])
    print("FIRST DATA ROW KEYS (public registry facts):", {k: rows[0].get(k) for k in (cnpj_col, "TP_FUNDO_CLASSE", "DT_COMPTC", "TAXA_ADM") if k})

    fmt = collections.Counter()
    for r in rows:
        raw = (r.get(cnpj_col) or "").strip()
        if re.fullmatch(r"\d{14}", raw):
            fmt["14 digits no punctuation"] += 1
        elif re.fullmatch(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", raw):
            fmt["punctuated ##.###.###/####-##"] += 1
        elif not raw:
            fmt["empty"] += 1
        else:
            fmt["other"] += 1
    print("CNPJ FORMAT (rows):", dict(fmt))
    print("TP_FUNDO_CLASSE (rows):", dict(collections.Counter(r.get("TP_FUNDO_CLASSE", "?") for r in rows)))
    cur, cnt = fold_extrato(rows, cnpj_col)
    print(f"CURRENT: rows={len(rows)} distinct CNPJ={len(cur)} rows-per-CNPJ distribution={dict(sorted(collections.Counter(cnt.values()).items()))}")
    multi = [c for c, n in cnt.items() if n > 1]
    if multi:
        diff_taxa = 0
        for c in multi:
            vs = {num(r.get("TAXA_ADM")) for r in rows if norm(r.get(cnpj_col)) == c} if len(multi) < 400 else None
            if vs is not None and len(vs) > 1:
                diff_taxa += 1
        print(f"CNPJs with >1 row: {len(multi)}; of those with differing TAXA_ADM across rows (computed only if <400 CNPJs): {diff_taxa if len(multi) < 400 else 'not computed'}")
    dts = collections.Counter((r.get("DT_COMPTC") or "")[:7] for r in rows)
    print("DT_COMPTC by month (rows, newest 18 + oldest 6):", dict(sorted(dts.items())[-18:]), "| oldest:", dict(sorted(dts.items())[:6]))
    print("DT_COMPTC age in days vs 2026-10-02, all CNPJs in file:", json.dumps(pct([d for d in (days_old(r.get('DT_COMPTC') or '') for r in cur.values()) if d is not None])),
          age_buckets([days_old(r.get('DT_COMPTC') or '') for r in cur.values()]))

    # universe match
    inter = set(uni) & set(cur)
    print(f"MATCH: extrato CNPJs {len(cur)}, in universe {len(inter)} ({len(inter)/len(uni):.3f} of universe), universe funds absent from current file: {len(set(uni)-set(cur))}, extrato CNPJs outside universe: {len(set(cur)-set(uni))}")
    tp_in = collections.Counter(cur[c].get("TP_FUNDO_CLASSE", "?") for c in inter)
    print("TP_FUNDO_CLASSE of universe funds found in current file:", dict(tp_in))

    # per-column fill rates in the universe subset (folded rows)
    print("=" * 80)
    print("FILL RATE per column, universe funds found in current file (n=%d): column,non_empty,share" % len(inter))
    for c in cols:
        ne = sum(1 for k in inter if (cur[k].get(c) or "").strip() != "")
        print(f"  {c},{ne},{ne/max(1,len(inter)):.3f}")

    # ---- TAXA_ADM coverage ----
    def seg_ok(seg, u):
        return seg == "ALL" or seg == u["band"] or seg == u["diario"] or (seg == "A&D" and u["band"] == "A" and u["diario"] == "D")

    print("=" * 80)
    print("COVERAGE of TAXA_ADM (current file, newest row per CNPJ)")
    for seg in ("ALL", "A", "B", "D", "A&D"):
        n = fnd = taxa = zero = empty = 0
        for c, u in uni.items():
            if not seg_ok(seg, u):
                continue
            n += 1
            r = cur.get(c)
            if r is None:
                continue
            fnd += 1
            ta = num(r.get("TAXA_ADM"))
            if ta is None:
                empty += 1
            else:
                taxa += 1
                zero += ta == 0
        print(f"  SEG {seg}: n={n} in_file={fnd} ({fnd/max(1,n):.3f}) TAXA_ADM_filled={taxa} ({taxa/max(1,n):.3f}) of_which_exactly_0={zero} ({zero/max(1,n):.3f} of seg, {zero/max(1,taxa):.3f} of filled) "
              f"TAXA_ADM_empty_in_file={empty} ({empty/max(1,n):.3f}) positive={taxa-zero} ({(taxa-zero)/max(1,n):.3f})")
    print("PL buckets (universe; PL shares are weights only): bucket,n,PL_bn,in_file(n/PL share),taxa_positive(n/PL share)")
    for label, lo, hi in (("<1M", 0, 1e6), ("1M-10M", 1e6, 1e7), ("10M-100M", 1e7, 1e8), ("100M-1bn", 1e8, 1e9), (">=1bn", 1e9, 1e99)):
        n = a = t = 0
        pl_s = pl_a = pl_t = 0.0
        for c, u in uni.items():
            pl = u["pl"] or 0
            if not (lo <= pl < hi):
                continue
            n += 1; pl_s += pl
            r = cur.get(c)
            if r is not None:
                a += 1; pl_a += pl
                ta = num(r.get("TAXA_ADM"))
                if ta is not None and ta > 0:
                    t += 1; pl_t += pl
        d = max(1.0, pl_s)
        print(f"  {label}: n={n} PL={pl_s/1e9:.1f}bn in_file={a}/{pl_a/d:.3f} taxa_positive={t}/{pl_t/d:.3f}")

    # age of the row, universe funds, with and without TAXA_ADM
    print("=" * 80)
    ages_all, ages_fee = [], []
    for c in inter:
        d = days_old(cur[c].get("DT_COMPTC") or "")
        ages_all.append(d)
        if num(cur[c].get("TAXA_ADM")) is not None:
            ages_fee.append(d)
    print("AGE (days to 2026-10-02) of current-file row, universe funds in file:", json.dumps(pct([a for a in ages_all if a is not None])), age_buckets(ages_all))
    print("AGE of those with TAXA_ADM filled:", json.dumps(pct([a for a in ages_fee if a is not None])), age_buckets(ages_fee))
    ym = collections.Counter((cur[c].get("DT_COMPTC") or "")[:7] for c in inter)
    print("DT_COMPTC month of universe rows (newest 24):", dict(sorted(ym.items())[-24:]))

    # ---- values: unit, zeros, empties ----
    print("=" * 80)
    vals = [num(cur[c].get("TAXA_ADM")) for c in inter if num(cur[c].get("TAXA_ADM")) is not None]
    print("TAXA_ADM values (universe, in file, filled):", json.dumps(pct(vals)), f"| >5: {sum(1 for v in vals if v>5)} >10: {sum(1 for v in vals if v>10)} >100: {sum(1 for v in vals if v>100)} <0: {sum(1 for v in vals if v<0)} (0,0.05): {sum(1 for v in vals if 0<v<0.05)}")
    print("TAXA_ADM value mode (top 15 exact values):", collections.Counter(vals).most_common(15))

    def prof(label, pred, fields=("TP_FUNDO_CLASSE", "FUNDO_COTAS", "FUNDO_ESPELHO", "CONDOM", "EXISTE_TAXA_PERFM", "EXISTE_TAXA_INGRESSO", "EXISTE_TAXA_SAIDA", "POLIT_INVEST", "PUBLICO_ALVO")):
        sel = [c for c in inter if pred(num(cur[c].get("TAXA_ADM")))]
        print(f"PROFILE [{label}] n={len(sel)}")
        for f in fields:
            if f in cols:
                print(f"    {f}: {dict(collections.Counter((cur[c].get(f) or '').strip() or '(empty)' for c in sel).most_common(8))}")
        if "CLASSE_ANBIMA" in cols:
            print("    CLASSE_ANBIMA top8:", collections.Counter((cur[c].get("CLASSE_ANBIMA") or "").strip() or "(empty)" for c in sel).most_common(8))
        es = [uni[c]["e8"] for c in sel if uni[c]["e8"] is not None]
        print(f"    est_aug (balancete, % a.a.): n={len(es)} {json.dumps(pct(es))} share>0.10={sum(1 for x in es if x>0.10)/max(1,len(es)):.3f}")

    prof("TAXA_ADM = exactly 0", lambda t: t is not None and t == 0)
    prof("TAXA_ADM empty", lambda t: t is None)
    prof("TAXA_ADM > 0", lambda t: t is not None and t > 0)

    # ---- comparison with the balancete estimate ----
    print("=" * 80)
    for ekey in ("e8", "e7"):
        for label, cond in (("A, TAXA_ADM>0, any age", lambda u, t, r: u["band"] == "A" and t is not None and t > 0),
                            ("A, TAXA_ADM>0, row age <=365d", lambda u, t, r: u["band"] == "A" and t is not None and t > 0 and (days_old(r.get("DT_COMPTC") or "") or 99999) <= 365)):
            ratios, diffs = [], []
            for c in inter:
                u = uni[c]
                r = cur[c]
                t = num(r.get("TAXA_ADM"))
                if u[ekey] is None or not cond(u, t, r):
                    continue
                ratios.append(u[ekey] / t)
                diffs.append(u[ekey] - t)
            n = len(ratios)
            if n:
                print(f"COMPARE est={ekey} [{label}]: n={n} ratio(est/TAXA_ADM) {json.dumps(pct(ratios))} within+-25%={sum(1 for x in ratios if 0.75<=x<=1.25)/n:.3f} "
                      f"within x0.5..2={sum(1 for x in ratios if 0.5<=x<=2)/n:.3f} abs diff<=0.25pp={sum(1 for x in diffs if abs(x)<=0.25)/n:.3f}")
            else:
                print(f"COMPARE est={ekey} [{label}]: n=0")

    # ---- yearly files ----
    print("=" * 80)
    ycur = {}
    ymeta = {}
    for y in (2024, 2025, 2026):
        nm = f"extrato_fi_{y}.csv"
        b = get(EXT_BASE + nm)
        if b is None:
            print(f"FAILED {nm}"); continue
        ycols, yrows, m = read_csv(nm, b)
        ymeta[y] = m
        print("YEAR FILE META:", json.dumps(m), "| same header as current:", ycols == cols, "| cols added:", sorted(set(ycols) - set(cols)), "removed:", sorted(set(cols) - set(ycols)))
        ycn = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in ycols else next((c for c in ycols if "CNPJ" in c), None)
        yfold, ycnt = fold_extrato(yrows, ycn)
        ycur[y] = yfold
        yd = collections.Counter((r.get("DT_COMPTC") or "")[:7] for r in yrows)
        print(f"  {nm}: distinct CNPJ={len(yfold)} rows-per-CNPJ={dict(sorted(collections.Counter(ycnt.values()).items()))} in_universe={len(set(yfold)&set(uni))} "
              f"TP_FUNDO_CLASSE={dict(collections.Counter(r.get('TP_FUNDO_CLASSE','?') for r in yrows))} DT months={dict(sorted(yd.items()))}")
        print(f"  {nm}: universe funds with a TAXA_ADM in this year's file (any row): "
              f"{sum(1 for c in uni if c in yfold and num(yfold[c].get('TAXA_ADM')) is not None)}")
    # union: newest row per CNPJ across current + yearly files
    allr = {}
    for src, d in [("cur", cur)] + [(str(y), ycur[y]) for y in sorted(ycur)]:
        for c, r in d.items():
            k = ((r.get("DT_COMPTC") or ""), num(r.get("TAXA_ADM")) is not None)
            if c not in allr or k > allr[c][0]:
                allr[c] = (k, r, src)
    in_cur = sum(1 for c in uni if c in cur)
    in_union = sum(1 for c in uni if c in allr)
    f_cur = sum(1 for c in uni if c in cur and num(cur[c].get("TAXA_ADM")) is not None)
    f_union = sum(1 for c in uni if c in allr and num(allr[c][1].get("TAXA_ADM")) is not None)
    print(f"UNION current+2024..2026 (newest row per CNPJ): universe in file {in_union} (current alone {in_cur}); with TAXA_ADM {f_union} (current alone {f_cur})")
    stale = diffv = 0
    for c in cur:
        for y, d in ycur.items():
            if c in d and (d[c].get("DT_COMPTC") or "") > (cur[c].get("DT_COMPTC") or ""):
                stale += 1
                break
    print(f"current-file rows older than a row for the same CNPJ in a yearly file: {stale}")
    only_yearly = [c for c in uni if c not in cur and c in allr]
    print(f"universe funds absent from current but present in a yearly file: {len(only_yearly)}")

    # ---- lamina comparison ----
    print("=" * 80)
    lam = lam_fold(uni)
    print(f"LAMINA latest rows for universe funds: {len(lam)}")
    both = [c for c in inter if c in lam and lam[c]["taxa"] is not None and num(cur[c].get("TAXA_ADM")) is not None]
    print(f"funds with TAXA_ADM in both extrato and lamina(latest row): {len(both)}")
    for label, sel in (("all", both), ("lamina age <=12m", [c for c in both if lam_age(lam[c]["dt"]) <= 12]),
                       ("lamina age >12m", [c for c in both if lam_age(lam[c]["dt"]) > 12])):
        if not sel:
            print(f"  [{label}] n=0"); continue
        rt = [num(cur[c].get("TAXA_ADM")) / lam[c]["taxa"] for c in sel if lam[c]["taxa"] > 0]
        eq = sum(1 for c in sel if abs(num(cur[c].get("TAXA_ADM")) - lam[c]["taxa"]) < 1e-9)
        w5 = sum(1 for c in sel if abs(num(cur[c].get("TAXA_ADM")) - lam[c]["taxa"]) <= 0.05 * max(lam[c]["taxa"], 1e-9))
        print(f"  [{label}] n={len(sel)} exactly equal={eq} ({eq/len(sel):.3f}) within 5%={w5/len(sel):.3f} ratio extrato/lamina (lamina>0, n={len(rt)}) {json.dumps(pct(rt))} "
              f"both zero={sum(1 for c in sel if lam[c]['taxa']==0 and num(cur[c].get('TAXA_ADM'))==0)} "
              f"extrato 0 & lamina>0={sum(1 for c in sel if lam[c]['taxa']>0 and num(cur[c].get('TAXA_ADM'))==0)} extrato>0 & lamina 0={sum(1 for c in sel if lam[c]['taxa']==0 and num(cur[c].get('TAXA_ADM'))>0)}")
    # lamina Variavel with empty TAXA_ADM vs extrato TAXA_ADM
    var = [c for c in inter if c in lam and lam[c]["taxa"] is None and lam[c]["tmin"] is not None and num(cur[c].get("TAXA_ADM")) is not None]
    if var:
        rmin = [num(cur[c].get("TAXA_ADM")) / lam[c]["tmin"] for c in var if lam[c]["tmin"]]
        inside = sum(1 for c in var if lam[c]["tmin"] is not None and lam[c]["tmax"] is not None and lam[c]["tmin"] <= num(cur[c].get("TAXA_ADM")) <= lam[c]["tmax"])
        print(f"lamina TAXA_ADM empty with MIN/MAX but extrato TAXA_ADM filled: n={len(var)} extrato/MIN {json.dumps(pct(rmin))} inside [MIN,MAX]={inside/len(var):.3f}")
    # union coverage lamina fee vs extrato fee
    lam_fee = {c for c, r in lam.items() if r["taxa"] is not None}
    lam_fee12 = {c for c in lam_fee if lam_age(lam[c]["dt"]) <= 12}
    ext_fee = {c for c in inter if num(cur[c].get("TAXA_ADM")) is not None}
    ext_pos = {c for c in ext_fee if num(cur[c].get("TAXA_ADM")) > 0}
    N = len(uni)
    print(f"COVERAGE universe n={N}: lamina latest has TAXA_ADM {len(lam_fee)} ({len(lam_fee)/N:.3f}); lamina <=12m {len(lam_fee12)} ({len(lam_fee12)/N:.3f}); "
          f"extrato TAXA_ADM filled {len(ext_fee)} ({len(ext_fee)/N:.3f}); extrato >0 {len(ext_pos)} ({len(ext_pos)/N:.3f}); "
          f"extrato OR lamina fee {len(ext_fee|lam_fee)} ({len(ext_fee|lam_fee)/N:.3f}); lamina<=12m fee but extrato empty/absent {len(lam_fee12-ext_fee)}; "
          f"extrato fee but no lamina fee {len(ext_fee-lam_fee)}")

    # ---- samples: 20 rows of public registry facts ----
    print("=" * 80)
    print("SAMPLE (20 rows): tag | cnpj | denom | tp | dt_comptc | TAXA_ADM | TAXA_PERFM | CLASSE_ANBIMA | lamina TAXA_ADM (dt) | est_aug | PL")

    def line(tag, c):
        r = cur.get(c, {})
        l = lam.get(c)
        u = uni.get(c, {})
        return (f"  {tag} | {c} | {(r.get('DENOM_SOCIAL') or '')[:60]} | {r.get('TP_FUNDO_CLASSE')} | {r.get('DT_COMPTC')} | {r.get('TAXA_ADM')} | "
                f"{r.get('TAXA_PERFM')} | {(r.get('CLASSE_ANBIMA') or '')[:40]} | {(l['taxa'], l['dt']) if l else None} | {u.get('e8')} | {u.get('pl')}")

    by_pl = sorted(inter, key=lambda c: -(uni[c]["pl"] or 0))
    for c in DEMO:
        if c in uni:
            print(line("demo", c) if c in cur else f"  demo | {c} | not in current extrato | lamina={(lam.get(c) or {}).get('taxa')}")
    for tag, pred in (("top PL, fee>0", lambda t: t is not None and t > 0), ("top PL, fee=0", lambda t: t == 0), ("top PL, fee empty", lambda t: t is None)):
        k = 0
        for c in by_pl:
            if pred(num(cur[c].get("TAXA_ADM"))) and c not in DEMO:
                print(line(tag, c)); k += 1
                if k == 5:
                    break

    print("=" * 80)
    if FAILED:
        print("FAILED DOWNLOADS/PARSES:")
        for f in FAILED:
            print("  ", f)
    print("DONE", "with failures" if FAILED else "clean")
    sys.exit(1 if FAILED else 0)


main()
